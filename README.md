# Reactive Step Timing Adaptation for IS-MPC Humanoid Locomotion

This project extends the [DIAG Robotics Lab IS-MPC framework](https://github.com/DIAG-Robotics-Lab/ismpc) with a **reactive step adaptation layer** for humanoid locomotion under perturbations.

The baseline framework provides nominal footstep planning, IS-MPC for CoM/ZMP regulation, swing-foot trajectory generation, inverse dynamics control, and DART-based simulation. The extension adds an online recovery layer that can modify **where** the next step lands and, when needed, **when** it lands, while leaving the original IS-MPC pipeline largely intact.

The current repository snapshot is centered on two main files:

- `simulation.py`: simulation entry point, CLI, headless runner, JSON summaries, push scheduling
- `step_timing_adapter.py`: the reactive QP-based adaptation layer

The quantitative discussion below is aligned with the **`logs_final` battery** summarized by `python show_results.py logs_final`.

---

## Motivation

A fixed offline gait works well in nominal walking, but it can become too rigid under external pushes. The goal of this project is to keep the original IS-MPC walking controller as the main engine and add a lightweight reactive layer that intervenes only when necessary.

The implementation is inspired by:

> **M. Khadiv, A. Herzog, S. A. A. Moosavian, and L. Righetti**, *"Walking Control Based on Step Timing Adaptation"*, arXiv:1704.01271, 2020.

The paper shows that, under the LIPM, adapting only the **next step location** and **next step timing** is enough to preserve viability. This project does **not** reimplement the full controller from the paper. Instead, it injects those ideas into the existing DIAG IS-MPC codebase.

---

## Setup (Ubuntu 24.04.3 LTS x86_64)

```bash
# 1. Create a virtual environment
python3 -m venv ~/venvs/dev

# 2. Activate it
source ~/venvs/dev/bin/activate

# 3. Enter the project directory
cd ~/civale_leonardi_ismpc

# 4. Install dependencies
pip install -r requirements.txt

# 5. Verify imports
python -c "import dartpy, casadi, scipy, matplotlib, osqp, yaml, numpy; print('ok')"

# 6. Run a headless test
python simulation.py --headless
```

You need `dartpy >= 6.16`. If pip does not allow the correct version, use Python 3.12 or conda.

---

## Repository structure

| File | Role |
|---|---|
| `simulation.py` | Main simulation entry point (viewer + headless), push scheduling, JSON summary export |
| `step_timing_adapter.py` | Reactive layer: evaluates activation conditions, solves a local QP, updates the active plan |
| `footstep_planner.py` | Stores both immutable nominal plan and mutable active plan |
| `foot_trajectory_generator.py` | Swing-foot trajectory generation |
| `ismpc.py` | Main IS-MPC controller |
| `inverse_dynamics.py` | Whole-body inverse dynamics |
| `filter.py` | Kalman filter for CoM/ZMP estimation |
| `utils.py` | QP wrapper and helper utilities |
| `logger.py` | Real-time plotting |
| `show_results.py` | Aggregates JSON logs and prints comparison tables |
| `run_all_tests.sh` | Final 123-test battery used for the main quantitative results |

---

## Pipeline

1. **Nominal footstep planner** generates an offline reference gait.
2. The planner exposes both an immutable **nominal plan** and a mutable **active plan**.
3. **State estimation** reads and filters CoM/ZMP state.
4. **Reactive adapter** (`StepTimingAdapter`) checks whether the current step should be modified.
5. **IS-MPC** solves the CoM/ZMP control problem using the active plan.
6. **Swing-foot generation** produces trajectories consistent with the current plan.
7. **Inverse dynamics** computes the final joint torques.
8. **Perturbation** is applied if requested from the CLI.
9. **Logging** stores summary statistics and optional JSON traces.

---

## What the current implementation changes

### `footstep_planner.py`

The planner is no longer purely static. It now supports:

- reading both nominal and active steps
- updating position, angle, and `ss_duration` online
- converting between world and local support coordinates
- computing phase, time-in-step, and total plan duration

### `step_timing_adapter.py`

This is the core reactive layer. The current uploaded version is explicitly marked as a **v3** implementation and includes the following key ideas:

1. **Preventive triggering**: activation can happen when the viability margin becomes small, not only after it becomes negative.
2. **Active-plan reference**: the QP cost tracks the current active plan rather than pulling every update back to the original nominal one.
3. **`T_gap` clamp**: if the optimizer proposes a step time that is too short, the solution is clamped instead of discarded.
4. **Geometry-derived pelvis half-width**: internal lateral geometry is estimated from nominal footsteps rather than hardcoded.
5. **Per-update displacement clamp**: large footstep jumps are limited to reduce MPC infeasibility.
6. **Soft propagation to step `N+2`**: a fraction of the displacement is propagated to the following step to smooth the moving constraints seen by IS-MPC.

The QP uses 7 decision variables:

- `dx`, `dy`: next-step displacement in the local support frame
- `tau`: step timing variable
- `bx`, `by`: DCM offset variables
- `sx`, `sy`: slack variables

The adapter also tracks:

- `updates`
- `activations`
- `qp_failures`
- `tgap_clamps`
- `displacement_clamps`
- `max_dcm_error`

### `simulation.py`

The current simulation entry point provides:

- `--adapt` to enable the reactive layer
- `--headless` for reproducible command-line tests
- push scheduling by force, duration, step, phase, direction, and target
- `--profile {forward,inplace,scianca}`
- optional JSON export via `--log-json`
- summary printing at the end of each run

The controller summary exported by `simulation.py` includes both adapter statistics and the tuning parameters used in that run.

### `ismpc.py`

The MPC backbone is not redesigned. It continues to solve the original IS-MPC problem, but now it reads the **active** footstep plan, so any accepted adaptation is immediately reflected in the constraints used by the controller.

---

## Push convention

The meaningful body-push tests are lateral pushes toward the **unsupported side**.

- **Step 3**: support foot = `rfoot` → critical direction = **left**
- **Step 4**: support foot = `lfoot` → critical direction = **right**

Pushing toward the support side is usually much less informative.

---

## Activation logic in the current adapter

The adapter can activate only if all of the following hold:

- adaptation is enabled
- the robot is in **single support**
- the current step index is valid and a next step exists
- the controller is outside the **warmup** window
- the controller is outside the **freeze** window near the end of the step
- the controller is outside the **cooldown** window after a recent accepted update

Then at least one trigger must hold:

- `dcm_error >= adapt_dcm_error_threshold`
- `margin <= adapt_viability_margin` **and** `dcm_error >= adapt_margin_error_gate`

This is important: in the current code the margin condition is **preventive**. It is not waiting for the margin to become negative.

If the QP returns a valid solution, the adapter may:

- shorten or lengthen the current single-support duration
- move the next step target
- clamp timing via `T_gap`
- clamp displacement to keep updates incremental
- softly propagate part of the displacement to the following step

---

## CLI arguments

| Argument | Description |
|---|---|
| `--adapt` | Enable the reactive step timing adaptation layer |
| `--headless` | Run without the viewer |
| `--steps N` | Maximum number of simulation ticks |
| `--force F` | Push force in Newtons |
| `--duration D` | Push duration in seconds |
| `--push-step S` | Planner step index for the push |
| `--push-time T` | Absolute push start time |
| `--push-phase P` | Fraction of the chosen step single-support phase |
| `--direction DIR` | `left`, `right`, `forward`, `backward` |
| `--push-target` | `base`, `stance_foot`, `lfoot`, `rfoot` |
| `--profile` | `forward`, `inplace`, `scianca` |
| `--log-json PATH` | Save run summary to JSON |
| `--realtime-factor R` | Viewer playback speed |
| `--quiet` | Reduce console output |

---

## Tuning

### Current defaults in the uploaded `simulation.py`

```python
adapt_dcm_error_threshold = 0.002
adapt_viability_margin    = 0.01
adapt_margin_error_gate   = 0.001
adapt_alpha_time          = 3.0
adapt_alpha_offset        = 500.0
adapt_alpha_slack         = 1e5
T_gap_ticks               = 10
adapt_freeze_ticks        = 5
adapt_warmup_ticks        = 8
adapt_cooldown_ticks      = 5
min_timing_update_ticks   = 1
min_step_update           = 0.003
max_displacement_per_update = 0.08
adapt_propagation_alpha   = 0.3
T_min_ticks               = 35
T_max_ticks               = 100
```

### Tuning used in `logs_final`

The quantitative results reported below come from the `logs_final` battery, whose stored summaries are aggregated by `show_results.py`. The printed tuning for that battery is:

```python
adapt_dcm_error_threshold = 0.003
adapt_margin_error_gate   = 0.002
adapt_cooldown_ticks      = 10
adapt_warmup_ticks        = 15
adapt_freeze_ticks        = 8
T_gap_ticks               = 16
min_timing_update_ticks   = 2
min_step_update           = 0.01
adapt_alpha_time          = 5.0
adapt_alpha_offset        = 50.0
adapt_alpha_slack         = 10000.0
```

So, the implementation description in this README is based on the current code files, while the experimental tables below are based on the `logs_final` summaries.

---

## Usage examples

### Viewer

```bash
python simulation.py
python simulation.py --adapt
```

### Headless examples

```bash
# Baseline — 45N left push on step 3
python simulation.py --headless --quiet --profile forward --steps 1400 \
    --force 45 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base

# Adapted — same case
python simulation.py --headless --quiet --profile forward --adapt --steps 1400 \
    --force 45 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base

# Symmetry test — right push on step 4
python simulation.py --headless --quiet --profile forward --adapt --steps 1400 \
    --force 40 --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.55 --push-target base
```

### Aggregate previous runs

```bash
python show_results.py logs_final/
```

---

## Results from `logs_final`

The final battery contains **123 tests** and yields **42 direct base-vs-adapt comparisons**.

### Global summary

| Outcome | Count |
|---|---:|
| Adapter saves the robot | **9** |
| Tie / no meaningful difference | 31 |
| Adapter worsens the outcome | 2 |

The 2 worse cases are both in the **in-place** scenario.

---

## Main result: forward walking with lateral body pushes

### A. Left push on step 3

This is the clearest success case.

#### `push_phase = 0.35`

| Force | Baseline | Adapted |
|---|---|---|
| 40 N | survives | survives |
| 45 N | **falls** | **survives** |
| 50 N | falls | falls |

#### `push_phase = 0.55`

| Force | Baseline | Adapted |
|---|---|---|
| 40 N | survives | survives |
| 45 N | **falls** | **survives** |
| 50 N | **falls** | **survives** |
| 55 N | falls | falls (+9 ticks) |

### F. Frontier sweep at `push_phase = 0.55`

| Force | Baseline | Adapted |
|---|---|---|
| 46 N | **falls** | **survives** |
| 48 N | **falls** | **survives** |
| 50 N | **falls** | **survives** |
| 52 N | falls | falls (+27 ticks) |
| 55 N | falls | falls (+9 ticks) |
| 60 N | falls | falls (+33 ticks) |

### Interpretation

The clean take-away is that, for the strongest lateral body-push scenario studied here, the adapter moves the useful recovery frontier from roughly **45 N** to roughly **50 N**, with additional partial gains beyond that.

---

## Symmetry result: right push on step 4

### B. Right push on step 4

| Force | Phase | Baseline | Adapted |
|---|---|---|---|
| 40 N | 0.35 | **falls** | **survives** |
| 40 N | 0.55 | **falls** | **survives** |

The battery also contains adapted 45 N right-push runs that survive, but the direct base counterpart is not part of the same comparison summary, so the strongest clean claim remains the **40 N** save on step 4.

---

## Forward/backward directional pushes

### C. Pushes in sagittal directions

These tests do **not** produce clean saves.

Typical behavior:

- both baseline and adapted fall
- the adapter sometimes adds a few ticks of survival time
- improvements remain modest (`+3`, `+5`, `+9`, `+11`, `+14` ticks)

This suggests that the current layer is mainly useful for **lateral body-push recovery during forward walking**, not as a general all-direction disturbance handler.

---

## Long pushes

### E. Push duration `0.20 s`

No long-push case in the final battery turns a fall into a survival, but several runs show nontrivial survival-time gains:

- `+50` ticks
- `+34` ticks
- several gains in the `+9` to `+12` tick range

So the adapter still helps, but not enough to fully recover under these longer perturbations.

---

## In-place stepping

### D. Standard in-place battery

The final results do **not** support the claim that the adapter is useful in the in-place profile.

Direct comparisons show:

| Case | Baseline | Adapted | Verdict |
|---|---|---|---|
| left S3, 30 N, P=0.35 | falls | falls | tie |
| left S3, 30 N, P=0.55 | survives | **falls** | worse |
| right S4, 30 N, P=0.35 | falls | falls | tie |
| right S4, 30 N, P=0.55 | survives | **falls** | worse |

So the adapter is actually **worse** in two in-place comparisons.

### G. Paper-style early push (`push_phase = 0.05`)

There is one isolated in-place case where the adapted run survives while the baseline falls:

- `F = 25 N`, left, step 3, `P = 0.05`

However, the summary reports:

- `upd = 0`
- `act = 0`

So this survival **cannot be attributed to an actual accepted adaptation**. It should be treated as run-to-run outcome variability, not as evidence that the in-place controller works.

### Interpretation

The in-place profile remains **inconclusive to negative** in the current project state:

- there is no clean in-place recovery case with accepted step updates
- there are two direct cases where adaptation makes the result worse
- the only apparent “save” happens with `upd = 0`

For this reason, the current implementation should be presented as a **forward-walking lateral push recovery layer**, not as a robust stepping-in-place recovery controller.

---

## What the final battery supports

The strongest supported claim is:

> In forward walking, for lateral body pushes applied toward the unsupported side, the reactive step adaptation layer clearly improves robustness and produces several clean saves over the baseline, especially in the 45–50 N range.

What the battery does **not** support:

- a general all-direction recovery claim
- a slippage-recovery claim
- a robust stepping-in-place claim

---

## Viewer commands for the best cases

```bash
# Baseline (falls)
python simulation.py --profile forward --force 45.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.35 --push-target base
# Adapted (survives)
python simulation.py --adapt --profile forward --force 45.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.35 --push-target base

# Baseline (falls)
python simulation.py --profile forward --force 45.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base
# Adapted (survives)
python simulation.py --adapt --profile forward --force 45.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base

# Baseline (falls)
python simulation.py --profile forward --force 50.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base
# Adapted (survives)
python simulation.py --adapt --profile forward --force 50.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base

# Baseline (falls)
python simulation.py --profile forward --force 40.0 --duration 0.1 --direction right --push-step 4 --push-phase 0.35 --push-target base
# Adapted (survives)
python simulation.py --adapt --profile forward --force 40.0 --duration 0.1 --direction right --push-step 4 --push-phase 0.35 --push-target base

# Baseline (falls)
python simulation.py --profile forward --force 40.0 --duration 0.1 --direction right --push-step 4 --push-phase 0.55 --push-target base
# Adapted (survives)
python simulation.py --adapt --profile forward --force 40.0 --duration 0.1 --direction right --push-step 4 --push-phase 0.55 --push-target base

# Frontier
python simulation.py --profile forward --force 46.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base
python simulation.py --adapt --profile forward --force 46.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base

python simulation.py --profile forward --force 48.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base
python simulation.py --adapt --profile forward --force 48.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base

python simulation.py --profile forward --force 50.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base
python simulation.py --adapt --profile forward --force 50.0 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base
```

---

## Differences from the reference paper

1. **Architecture**: this is an extension of DIAG IS-MPC, not a standalone controller designed from scratch around step timing adaptation.
2. **Backbone**: the paper’s controller is built around step adaptation itself, whereas here the reactive layer sits on top of an existing CoM/ZMP MPC.
3. **QP usage**: the paper solves the adaptation problem continuously at each control cycle; this implementation uses gated activation.
4. **Triggering**: the current adapter includes warmup, freeze, cooldown, timing clamps, and displacement clamps to avoid jitter and infeasibility.
5. **Observed behavior**: the paper reports strong benefits both in forward walking and stepping in place; this project only shows strong and repeatable benefits in the **forward lateral body-push** regime.

---

## References

- **M. Khadiv, A. Herzog, S. A. A. Moosavian, and L. Righetti**, *"Walking Control Based on Step Timing Adaptation"*, arXiv:1704.01271v3, 2020. [[arXiv]](https://arxiv.org/abs/1704.01271)
- **N. Scianca, D. De Simone, L. Lanari, G. Oriolo**, *"MPC for Humanoid Gait Generation: Stability and Feasibility"*, Transactions on Robotics, 2020. [[IEEE]](https://ieeexplore.ieee.org/document/8955951)
- **DIAG Robotics Lab IS-MPC framework**: [[GitHub]](https://github.com/DIAG-Robotics-Lab/ismpc)
