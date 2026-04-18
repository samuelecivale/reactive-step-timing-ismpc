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
| `plot_adapter_trace.py` | Generates diagnostic plots from JSON traces |
| `show_results.py` | Reads JSON logs and prints results grid, comparisons, viewer commands |
| `run_all_tests.sh` | **Final unified test battery** (123 tests, 7 sections) — main quantitative results |
| `run_slippage_tests.sh` | Slippage recovery test battery (36 tests) |
| `run_inplace_tests.sh` | Stepping-in-place test battery (46 tests) |
| `run_body_tuning.sh` | Earlier body-push tuning battery (superseded by `run_all_tests.sh`) |

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

## Push direction and step convention

The push must be directed toward the **unsupported side** of the robot to be a meaningful test. The gait alternates support feet:

- **Step 3**: support = `rfoot` → push **left** is the critical case (toward the free side)
- **Step 4**: support = `lfoot` → push **right** is the critical case (toward the free side)

Pushing toward the support foot (e.g. right push on step 3) is largely absorbed by the stance leg and does not test the adapter.

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
'adapt_dcm_error_threshold': 0.003,
'adapt_margin_error_gate': 0.002,
'adapt_cooldown_ticks': 10,
'adapt_warmup_ticks': 15,
'adapt_freeze_ticks': 8,
'T_gap_ticks': 16,
'min_timing_update_ticks': 2,
'min_step_update': 0.01,
'adapt_alpha_step': 1.0,
'adapt_alpha_time': 5.0,
'adapt_alpha_offset': 50.0,
'adapt_alpha_slack': 1e4,
'step_length_forward_margin': 0.15,
'step_length_backward_margin': 0.08,
'step_width_outward_margin': 0.10,
'step_width_inward_margin': 0.05,
'cross_margin': 0.01,
'T_min_ticks': 40,
'T_max_ticks': 100,
```

The initial tuning had geometric bounds that were too tight (`forward_margin=0.08`, `outward_margin=0.05`) and a QP weight imbalance (`alpha_offset=400` vs `alpha_step=8`), which caused the QP to fail on nearly every activation. The revised tuning widens the step bounds so the QP is feasible, lowers `alpha_offset` to give the optimizer more freedom, and shortens the warmup/cooldown windows so the adapter can intervene earlier and more than once per step if needed.

---

## Usage examples

**Viewer (qualitative inspection):**

```bash
python simulation.py
python simulation.py --adapt
```

**Headless (quantitative tests):**

```bash
# Baseline — 45N left push on step 3 (falls)
python simulation.py --headless --quiet --profile forward --steps 1400 \
    --force 45 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55

# Adapted — same push (survives)
python simulation.py --headless --quiet --profile forward --adapt --steps 1400 \
    --force 45 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55

# Adapted — 50N left push (survives, strongest case)
python simulation.py --headless --quiet --profile forward --adapt --steps 1400 \
    --force 50 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55

# Right push on step 4 (symmetry test)
python simulation.py --headless --quiet --profile forward --adapt --steps 1400 \
    --force 40 --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.55
```

**Viewing results from previous headless runs:**

```bash
python show_results.py logs_final/
```

> **Note:** the source of truth for quantitative results are headless runs only, because the viewer can crash directly if the solver raises an exception.

---

## Results

Results are based on the final unified battery of 123 headless tests (`run_all_tests.sh`), producing 44 direct base-vs-adapt comparisons.

### Summary

| Outcome | Count |
|---|---|
| Adapter saves the robot | **10** |
| Tie (both survive or both fall with similar ticks) | 32 |
| Adapter worsens | 2 (false positives: `upd=0`, adapter made no update) |

### Forward walking — lateral push (main result)

**Left push on step 3 (support = rfoot), `push_phase = 0.55`:**

| Force | Baseline | Adapted |
|---|---|---|
| 35 N | survives | survives |
| 40 N | survives | survives |
| 45 N | **falls** | survives |
| 46 N | **falls** | survives |
| 48 N | **falls** | survives |
| 50 N | **falls** | **survives** |
| 52 N | falls | falls (+27 ticks) |
| 55 N | falls | falls (+9 ticks) |

The adapter shifts the failure frontier from ~40 N to ~50 N, an improvement of approximately 25%.

**Left push on step 3, `push_phase = 0.35`:**

| Force | Baseline | Adapted |
|---|---|---|
| 40 N | survives | survives |
| 45 N | **falls** | **survives** |
| 50 N | falls | falls |

### Symmetry — right push on step 4

**Right push on step 4 (support = lfoot):**

| Force | Phase | Baseline | Adapted |
|---|---|---|---|
| 35 N | 0.35 | survives | survives |
| 35 N | 0.55 | survives | survives |
| 40 N | 0.35 | **falls** | **survives** |
| 40 N | 0.55 | **falls** | **survives** |
| 45 N | 0.35 | — | survives |
| 45 N | 0.55 | — | survives |
| 50 N | 0.35 | — | falls |

This confirms that the adapter works on both sides when the push is directed toward the unsupported foot.

### Forward/backward push

All tests fall for both baseline and adapted at 35–45 N. The adapter is not designed for sagittal perturbations and the results are consistent with the reference paper, which shows the largest improvements for lateral pushes (see Fig. 5 in the paper, polar plot of maximum tolerable impulse by direction).

### Behavior at different push phases

The adapter is most effective at `push_phase = 0.55` (mid single-support). At `push_phase = 0.05` (start of step) the DCM has not diverged enough to trigger activation. At `push_phase = 0.75` (late in the step) the freeze window prevents adaptation. This is consistent with the paper's observation that push timing within a step affects recovery difficulty.

---

## Stepping in place — why it does not work in our setup

Stepping-in-place tests (`run_inplace_tests.sh`, 46 tests) revealed that the HRP4 robot in DART is **unstable in the in-place profile even without any external push**: the robot falls at ~375 ticks with zero force applied. This makes quantitative evaluation of the adapter impossible for this scenario.

The instability is not caused by the adapter (which makes no updates, `upd=0` in all cases) but by the simulation environment. The DART penalty-based contact model combined with the HRP4 whole-body dynamics does not produce a stable stepping-in-place gait. The reference paper uses a different robot (Sarcos with passive ankles) on a different simulator (SL with 18 contact points per foot and a tuned penalty contact model), where stepping in place is stable.

Additionally, in the IS-MPC framework the CoM/ZMP controller is designed to track a moving reference. When the reference velocity is zero, the ZMP moving constraints in the MPC converge to a point, reducing the effective support polygon and making the controller more sensitive to any small perturbation — including numerical noise from the contact solver.

For these reasons, stepping-in-place results are not included in the main quantitative claims. In earlier tuning runs where the robot survived longer in the in-place profile, the adapter did produce genuine timing changes (`ss:70→69`), confirming that the timing adaptation mechanism works correctly when the underlying gait is stable.

---

## Slippage recovery — why it does not work in our setup

Slippage tests (`run_slippage_tests.sh`, 36 tests) simulate stance-foot slippage by applying a force directly on the support foot (`--push-target rfoot` on step 3, `--push-target lfoot` on step 4).

Results show that **the adapter does not improve slippage recovery**: both baseline and adapted controllers survive at 20 N and fall at 30 N+, with no significant difference in survival time. This is an architectural limitation, not a tuning problem.

The key difference with respect to the reference paper lies in the controller backbone:

**The paper's controller** does not control the CoP at all. It relies entirely on step placement and timing to regulate the DCM. When the stance foot slips, the CoP assumption is not violated because there is no CoP control in the first place. The controller simply observes the DCM divergence and reacts by adjusting the next step. This is why the paper reports successful slippage recovery with forces up to 930 N (Fig. 14).

**Our IS-MPC controller** actively regulates CoM/ZMP trajectories using the CoP as a control variable inside a receding-horizon optimization. The controller assumes a stable, stationary contact under the stance foot. When the foot slips, this assumption breaks: the ZMP measurement becomes unreliable, the Kalman filter receives corrupted observations, and the MPC computes control actions based on an incorrect contact model. By the time the adapter detects the DCM deviation, the whole-body controller has already entered an irrecoverable state.

In other words, the IS-MPC backbone provides better nominal performance (the robot walks more stably during undisturbed forward walking) but is inherently more fragile to contact model violations. The paper's architecture trades nominal walking quality for robustness to contact disruptions. This is a fundamental architectural trade-off that cannot be resolved by tuning the adapter parameters alone — it would require modifying the IS-MPC core to be less dependent on the CoP assumption, which is outside the scope of this project.

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
| `archives/old_logs/` | First exploratory sweeps (body-push + slip-like, old tuning) |
| `logs_body_tuning/` | Earlier body-push battery (before QP fix) |
| `logs_extra/` | Extended tests: multi-direction, frontier, in-place (old push-step convention) |
| `logs_final/` | **Final unified battery** — 123 tests, 7 sections, source of the main quantitative results |
| `logs_slippage/` | Slippage recovery battery — 36 tests |
| `logs_inplace/` | Stepping-in-place battery — 46 tests (inconclusive, see above) |
| `plots_body/` | Diagnostic plots for selected body-push runs |

The final battery (`run_all_tests.sh`) is organized in sections:

| Section | Description | Tests |
|---|---|---|
| A | Forward + left push on step 3 | 19 |
| B | Forward + right push on step 4 (symmetry) | 10 |
| C | Forward/backward push on step 3 and 4 | 24 |
| D | In-place, left S3 + right S4 | 16 |
| E | Long push 0.20 s | 12 |
| F | Frontier (46–60 N at P=0.55) | 12 |
| G | Paper-style push at step start (P=0.05) | 18 |

Results can be inspected at any time without re-running:

```bash
python show_results.py logs_final/
python show_results.py logs_slippage/
python show_results.py logs_final/ logs_body_tuning/   # multiple folders
```

---

## Differences from the reference paper

1. **Architecture**: extension of the DIAG IS-MPC codebase, not a standalone reimplementation of the paper's controller.
2. **Controller backbone**: the paper builds a stepping controller that uses only step location and timing without explicit CoP or CoM control; here the existing IS-MPC handles CoM/ZMP regulation, and the adaptation layer sits on top. This is the root cause of the different behavior in slippage recovery and stepping in place (see dedicated sections above).
3. **QP formulation**: the paper solves the stepping QP at every control cycle (1 kHz) with variables τ = e^(ω₀T), b, and uT, and weights α₁=1, α₂=5, α₃=1000. Our adapter runs only when activation conditions are met and uses a 7-variable QP (dx, dy, τ, bx, by, sx, sy) with different weights adapted to our local-frame formulation. The paper implements the viability constraint as a soft constraint with very high weight; we use explicit slack variables for the same purpose.
4. **Activation strategy**: the paper runs the QP at every control cycle; our adapter activates only when the DCM error or viability margin exceeds a threshold, with warmup, freeze, and cooldown windows to prevent jitter.
5. **Swing-foot trajectory**: the paper uses a 9th-order vertical QP recomputed at each cycle; here we use quintics with online re-anchoring (lighter and sufficient for this setup).
6. **Push direction convention**: the paper tests pushes in all directions (polar plot, Fig. 5) and finds the largest improvements for lateral pushes. Our results confirm this pattern.
7. **Observed behavior**: coherent with the paper — forward walking recovery is mostly step placement adaptation. The paper also reports that stepping in place shows explicit timing adaptation; in our setup the in-place profile is not stable enough in DART to verify this quantitatively, although the adapter does produce genuine timing changes in runs where the robot survived longer.

---

## Viewer commands for best cases

```bash
# 50N lateral — strongest recovery case
python simulation.py --profile forward --force 50 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base
python simulation.py --adapt --profile forward --force 50 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base

# 45N at two phases
python simulation.py --profile forward --force 45 --duration 0.1 --direction left --push-step 3 --push-phase 0.35 --push-target base
python simulation.py --adapt --profile forward --force 45 --duration 0.1 --direction left --push-step 3 --push-phase 0.35 --push-target base

python simulation.py --profile forward --force 45 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base
python simulation.py --adapt --profile forward --force 45 --duration 0.1 --direction left --push-step 3 --push-phase 0.55 --push-target base

# Symmetry — right push on step 4
python simulation.py --profile forward --force 45 --duration 0.1 --direction right --push-step 4 --push-phase 0.55 --push-target base
python simulation.py --adapt --profile forward --force 45 --duration 0.1 --direction right --push-step 4 --push-phase 0.55 --push-target base
```

---

## References

- **M. Khadiv, A. Herzog, S. A. A. Moosavian, and L. Righetti**, *"Walking Control Based on Step Timing Adaptation"*, arXiv:1704.01271v3, 2020. [[arXiv]](https://arxiv.org/abs/1704.01271)
- **N. Scianca, D. De Simone, L. Lanari, G. Oriolo**, *"MPC for Humanoid Gait Generation: Stability and Feasibility"*, Transactions on Robotics, 2020. [[IEEE]](https://ieeexplore.ieee.org/document/8955951)
- **M. Cipriano, P. Ferrari, N. Scianca, L. Lanari, G. Oriolo**, *"Humanoid motion generation in a world of stairs"*, Robotics and Autonomous Systems, 2023. [[ScienceDirect]](https://www.sciencedirect.com/science/article/pii/S0921889023001343)
- **DIAG Robotics Lab IS-MPC framework**: [[GitHub]](https://github.com/DIAG-Robotics-Lab/ismpc)
