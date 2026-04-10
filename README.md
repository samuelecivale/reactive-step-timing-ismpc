# Reactive Step Timing Adaptation for IS-MPC Humanoid Locomotion

This project extends the [DIAG Robotics Lab IS-MPC framework](https://github.com/DIAG-Robotics-Lab/ismpc) with a **reactive step adaptation layer** for humanoid locomotion under perturbations.

The original framework provides an MPC-based humanoid walking controller with nominal footstep planning, IS-MPC for CoM/ZMP regulation, swing foot trajectory generation, inverse dynamics control, and DART-based simulation.

The extension adds an online recovery layer that can modify **where** the next footstep lands and, when needed, **when** it lands, improving robustness against disturbances while keeping the original IS-MPC pipeline largely intact.

---

## Motivation

In the original baseline the walking plan is generated offline and executed with fixed step timing. This works well in nominal conditions, but when the robot is pushed a fixed plan may become too rigid.

The idea is simple: keep the original IS-MPC controller as the main walking engine, monitor the robot online, and if the state becomes critical adapt the next step by changing its placement and, in some cases, its timing.

This project is inspired by:

> **M. Khadiv, A. Herzog, S. A. A. Moosavian, and L. Righetti**, *"Walking Control Based on Step Timing Adaptation"*, arXiv:1704.01271, 2020.

The paper shows that, under the Linear Inverted Pendulum Model (LIPM), it is sufficient to optimize only the next step location and timing to guarantee that any viable state remains viable. It proposes a convex QP that adapts step placement and duration at every control cycle. This project takes those ideas and implements them as a **practical extension of the DIAG IS-MPC codebase**, rather than a full reimplementation of the paper's controller.

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

You need `dartpy >= 6.16`. If pip does not allow you to install the right version, upgrade to Python 3.12 or use conda.

---

## Repository structure

| File | Role |
|---|---|
| `simulation.py` | Final simulation entry point (viewer + headless) |
| `step_timing_adapter.py` | Reactive layer: evaluates activation conditions, solves a local QP, updates the active plan |
| `footstep_planner.py` | Holds both the immutable nominal plan and the mutable active plan |
| `foot_trajectory_generator.py` | Swing-foot trajectory with online re-anchoring |
| `ismpc.py` | Main IS-MPC controller (kept as close as possible to the original baseline) |
| `inverse_dynamics.py` | Whole-body inverse dynamics |
| `filter.py` | Kalman filter for CoM/ZMP estimation |
| `utils.py` | QP solver wrapper, rotation utilities, block-diagonal helper |
| `logger.py` | Real-time plotting of CoM/ZMP trajectories |
| `run_final_tests.sh` | Exploratory test battery |
| `run_body_tuning.sh` | Final body-push tuning battery (main quantitative results) |

---

## Pipeline

1. **Nominal footstep planner** generates a reference gait offline, copied into a mutable active plan.
2. **State estimation**: robot state is read and filtered (CoM/ZMP Kalman filter).
3. **Reactive layer** (`StepTimingAdapter`): if the situation is critical, solves a small QP and updates the active plan (step timing + landing position).
4. **Main MPC** (`Ismpc`): solves the CoM/ZMP problem using the active plan for moving constraints. Since it reads the active plan directly, any adaptation is automatically picked up.
5. **Swing foot generator**: produces foot trajectories consistent with the (possibly updated) plan.
6. **Inverse dynamics**: computes the final joint torques.
7. **Perturbation**: external push applied if scheduled.
8. **Logging / fall detection**: statistics and summary.

---

## What was modified from the original IS-MPC workspace

### `footstep_planner.py`

The original planner used a single fixed plan. The modified version introduces `self.nominal_plan` (immutable reference) and `self.plan` (active, modifiable online). New methods allow reading either plan, updating position/angle/`ss_duration` of a step, computing phase and time remaining, converting world↔local coordinates, and computing total plan duration.

### `step_timing_adapter.py` (new file)

Core of the extension. The module computes the current DCM, evaluates activation conditions based on `dcm_error` and viability margin, solves a 7-variable QP (`dx`, `dy` for step displacement, `tau` for timing, `bx`, `by` for DCM offset, `sx`, `sy` for slack), and if the solution is valid updates the active plan. It tracks statistics (updates, activations, QP failures, max DCM error).

### `foot_trajectory_generator.py`

The original generator used cubics with fixed timing and target. The modified version reads the active plan at each call, detects changes in timing or landing target, re-anchors the swing trajectory using boundary-conditioned quintics (position/velocity/acceleration), and keeps the foot above the ground robustly. This is necessary to make online adaptation coherent at the whole-body level.

### `simulation.py`

Most extensively modified. Adds CLI argument parsing, `--headless` mode for reproducible tests, push scheduling from command line, `StepTimingAdapter` initialization and usage, force visualization in the viewer (blue arrow + yellow marker), JSON summary export, and fall detection.

### `ismpc.py`

The MPC core was not rewritten. It solves the original problem using `self.footstep_planner.plan` (the active plan), so when the adapter updates timings and positions the MPC automatically uses the adapted values. This keeps the baseline nearly intact and makes the comparison clean.

---

## Activation conditions

The adapter activates **only** when all of these are satisfied:

- Adaptation is enabled (`use_step_timing_adaptation=True`)
- The robot is in single support
- It is not the first step, and a next step exists
- Not inside the warmup window (beginning of step)
- Not inside the freeze window (end of step)
- Not inside a cooldown window after a recent update

Additionally, at least one trigger condition must hold:

- `dcm_error >= adapt_dcm_error_threshold`
- `margin <= -adapt_viability_margin` **and** `dcm_error >= adapt_margin_error_gate`

If the QP solution is valid and not "too small", timing and/or position of the next step are updated.

---

## CLI arguments

| Argument | Description |
|---|---|
| `--adapt` | Enable the reactive adaptation layer |
| `--headless` | Run without the graphical viewer |
| `--steps N` | Maximum number of simulation ticks (headless) |
| `--force F` | Push force magnitude in Newtons |
| `--duration D` | Push duration in seconds |
| `--direction DIR` | `left`, `right`, `forward`, `backward` |
| `--push-step S` | Planner step index for the push |
| `--push-time T` | Absolute push start time in seconds |
| `--push-phase P` | Fraction of single-support phase for push start |
| `--push-target` | `base`, `stance_foot`, `lfoot`, `rfoot` |
| `--profile` | `forward`, `inplace`, `scianca` |
| `--log-json PATH` | Save a JSON summary of the run |
| `--realtime-factor R` | Viewer playback speed |
| `--quiet` | Reduce console output |

---

## Reactive layer parameters

| Parameter | Description |
|---|---|
| `use_step_timing_adaptation` | Enable/disable the layer |
| `adapt_dcm_error_threshold` | DCM error threshold for activation |
| `adapt_viability_margin` | Viability margin threshold |
| `adapt_margin_error_gate` | Minimum DCM error for margin-based activation |
| `adapt_alpha_step` | QP cost weight on step displacement (`dx`, `dy`) |
| `adapt_alpha_time` | QP cost weight on timing change (`tau`) |
| `adapt_alpha_offset` | QP cost weight on DCM offset (`bx`, `by`) |
| `adapt_alpha_slack` | Penalty on slack variables |
| `adapt_warmup_ticks` | Ticks before adapter can activate in a step |
| `adapt_freeze_ticks` | Ticks before step end where adapter freezes |
| `adapt_cooldown_ticks` | Minimum ticks between two updates |
| `T_gap_ticks` | Prevents timing too close to current instant |
| `T_min_ticks` / `T_max_ticks` | Bounds on single-support duration |
| `min_timing_update_ticks` | Minimum timing change to accept a solution |
| `min_step_update` | Minimum position change to accept a solution |
| Geometric margins | `step_length_forward_margin`, `step_length_backward_margin`, `step_width_outward_margin`, `step_width_inward_margin`, `cross_margin` |

---

## Final tuning (body-push battery)

```python
'adapt_dcm_error_threshold': 0.004,
'adapt_margin_error_gate': 0.002,
'adapt_cooldown_ticks': 20,
'adapt_warmup_ticks': 25,
'adapt_freeze_ticks': 8,
'T_gap_ticks': 16,
'min_timing_update_ticks': 2,
'min_step_update': 0.01,
'adapt_alpha_time': 5.0,
'adapt_alpha_offset': 400.0,
'adapt_alpha_slack': 1e5,
```

With this tuning the adapter is less nervous: tiny updates are filtered out, cooldown is longer, the final part of the step is protected, and the QP is unlikely to react to insignificant deviations.

---

## Usage examples

**Viewer (qualitative inspection):**

```bash
python simulation.py
python simulation.py --adapt
```

**Headless (quantitative tests):**

```bash
# Baseline
python simulation.py --headless --quiet --profile forward --steps 1400 \
    --force 40 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.05

# Adapted
python simulation.py --headless --quiet --profile forward --adapt --steps 1400 \
    --force 40 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55

# Stepping in place
python simulation.py --headless --quiet --profile inplace --adapt --steps 1400 \
    --force 30 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55
```

> **Note:** the source of truth for quantitative results are headless runs only, because the viewer can crash directly if the solver raises an exception.

---

## Results

### Main result: body push at `push_phase = 0.55`

**Baseline:**
- 35 N → survives
- 40 N → fails

**Adapted:**
- 40 N → survives
- 45 N → survives
- 50 N → survives (with final tuning)
- 55 N → fails

The reactive layer shifts the failure frontier forward: the adapted controller tolerates significantly higher push forces before becoming infeasible.

### Forward walking

The recovery in forward walking is mainly driven by **step placement adaptation**, which is consistent with what is discussed in the reference paper.

### Stepping in place

In stepping-in-place runs the adapter also produces genuine **timing adaptation**. A representative log entry:

```
ss:70 → 69
```

This confirms that the controller modifies not only where to step but also when to step, which was the main goal of the project.

### Stance-foot / slip-like perturbation (exploratory)

Tests with `--push-target stance_foot` were also implemented to approximate slip-like perturbations. These results were less conclusive than body-push ones for three reasons: sensitivity to the simulator's contact/friction model, physical emphasis different from the paper's setup, and less clear separation between baseline and adapted behavior. For this reason the slip-like scenario is treated as an exploratory extension, not as the main claim.

---

## Diagnostic plots

A plotting workflow reads the JSON trace and generates figures for selected runs:

- `*_dcm_error.png` — DCM error over time; highlights when the perturbation happens and whether the adapter triggers.
- `*_margin.png` — viability margin over time; shows whether the system approaches a critical region.
- `*_step_updates.png` — two subplots (single-support duration, lateral target) showing what the adapter actually changed and when.

In the final body-push cases the adapter typically performs one meaningful update, so the plots are informative but visually minimal.

---

## Force visualization in the viewer

A blue arrow shows the push direction and magnitude during viewer runs. A yellow sphere marker is placed at the arrow base. The arrow length scales with force (0.01 m per Newton). This is purely for qualitative inspection; quantitative conclusions come from headless tests.

---

## Test batteries

| Folder | Purpose |
|---|---|
| `logs/` | First exploratory sweep (body-push + slip-like) |
| `logs_refined/` | Second battery, refined force ranges and push phases |
| `logs_body_tuning/` | **Final body-push battery** with tuned parameters — source of the main quantitative result |

---

## Differences from the reference paper

1. **Architecture**: extension of the DIAG IS-MPC codebase, not a standalone reimplementation of the paper's controller.
2. **Controller backbone**: the paper builds a stepping controller that uses only step location and timing without explicit CoP or CoM control; here the existing IS-MPC handles CoM/ZMP regulation, and the adaptation layer sits on top.
3. **QP formulation**: the paper solves the stepping QP at every control cycle (1 kHz) with variables τ = e^(ω₀T), b, and uT. Our adapter runs only when activation conditions are met and uses a simplified 7-variable QP.
4. **Swing-foot trajectory**: the paper uses a 9th-order vertical QP recomputed at each cycle; here we use quintics with online re-anchoring (lighter and sufficient for this setup).
5. **Observed behavior**: coherent with the paper — forward walking recovery is mostly step placement, stepping in place also shows explicit timing adaptation.

---

## References

- **M. Khadiv, A. Herzog, S. A. A. Moosavian, and L. Righetti**, *"Walking Control Based on Step Timing Adaptation"*, arXiv:1704.01271v3, 2020. [[arXiv]](https://arxiv.org/abs/1704.01271)
- **N. Scianca, D. De Simone, L. Lanari, G. Oriolo**, *"MPC for Humanoid Gait Generation: Stability and Feasibility"*, Transactions on Robotics, 2020. [[IEEE]](https://ieeexplore.ieee.org/document/8955951)
- **M. Cipriano, P. Ferrari, N. Scianca, L. Lanari, G. Oriolo**, *"Humanoid motion generation in a world of stairs"*, Robotics and Autonomous Systems, 2023. [[ScienceDirect]](https://www.sciencedirect.com/science/article/pii/S0921889023001343)
- **DIAG Robotics Lab IS-MPC framework**: [[GitHub]](https://github.com/DIAG-Robotics-Lab/ismpc)