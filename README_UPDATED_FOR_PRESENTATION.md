# Reactive Step Timing Adaptation for IS-MPC Humanoid Locomotion

> Updated README for project explanation, final simulations, plots, animations, and presentation generation.  
> Last updated: 2026-04-28

This repository extends the DIAG Robotics Lab **IS-MPC humanoid walking framework** with a **reactive step adaptation layer** for push recovery. The baseline controller already provides nominal footstep planning, IS-MPC CoM/ZMP regulation, swing-foot trajectory generation, inverse dynamics, and DART-based simulation. This project adds an online recovery layer that can modify:

- **where** the next footstep lands;
- **when** the current/next step ends, through online single-support duration updates.

The implementation is inspired by Khadiv et al., *Walking Control Based on Step Timing Adaptation*, but it is not a direct reimplementation of that paper. The project keeps the original DIAG IS-MPC architecture and adds a gated, reactive QP layer on top of the existing planner/controller pipeline.

---

## Executive summary

The project demonstrates that a lightweight reactive layer can improve humanoid push recovery without redesigning the whole walking controller.

The strongest result is in **forward walking with lateral body pushes toward the unsupported side**. In this regime, the adapter produces several clean recoveries that the baseline cannot handle, especially around the **45-50 N** push range.

The most important conclusion is:

> The default adapter improves forward-walking lateral push robustness mainly through online next-footstep relocation. A timing-biased variant confirms that the timing branch is functional, because it changes the active single-support duration online, but it is more tuning-sensitive and can introduce regressions. Therefore, the default adapter should be presented as the stable controller, while timing-biased adaptation should be presented as an ablation/diagnostic extension.

---

## What is new in the current version

Compared with the earlier project state, the repository now includes:

1. **Final 1000-step evaluation protocol**
   - New clean workflow to rerun all final experiments at a uniform simulation horizon.
   - Avoids mixing older runs at 900, 1000, and 1400 steps.

2. **Workspace cleanup workflow**
   - Old logs/plots/videos are archived instead of deleted.
   - Final results are regenerated in clean folders.

3. **Three-controller comparison**
   - Baseline controller.
   - Default reactive adapter.
   - Timing-biased reactive adapter.

4. **Timing-biased diagnostic mode**
   - Enabled with `--timing-biased`.
   - Makes timing updates cheaper and footstep relocation more expensive in the QP.
   - Confirms that `ss_duration` can actually change online, for example:
     ```text
     ss:70->71
     xy:(0.600,-0.100)->(0.562,-0.051)
     ```

5. **Cleaner recovery plots**
   - Improved radar/bar plotting with `plot_better_recovery_radar.py`.
   - Avoids plotting untested categories as `0 N`.
   - Supports comparison among baseline, default adapter, and timing-biased adapter.

6. **Better visualization assets**
   - Dashboard plots.
   - Timing/footstep traces.
   - Plan animations.
   - CSV event export for accepted adapter updates.

---

## Repository structure

| File / folder | Role |
|---|---|
| `simulation.py` | Main entry point: viewer/headless simulation, push scheduling, CLI, JSON logs, adapter setup |
| `step_timing_adapter.py` | Core reactive QP layer for step location and timing adaptation |
| `footstep_planner.py` | Nominal and active footstep plans; supports online updates |
| `foot_trajectory_generator.py` | Swing-foot trajectory generation; consumes the active plan |
| `ismpc.py` | Original IS-MPC controller backbone; reads the active plan |
| `inverse_dynamics.py` | Whole-body inverse dynamics |
| `filter.py` | CoM/ZMP state filtering |
| `logger.py` | Realtime/debug plotting |
| `utils.py` | Helper utilities and QP wrappers |
| `show_results.py` | Aggregates JSON logs and prints result summaries |
| `run_all_tests.sh` | Baseline + default adapter final battery |
| `run_timing_biased_on_old_tests.sh` | Reruns adapted scenarios with `--timing-biased` |
| `run_final_1000_pipeline.sh` | Final uniform 1000-step pipeline |
| `clean_workspace_for_final.sh` | Archives old logs/plots/videos before final run |
| `generate_final_plots_and_assets.sh` | Produces final plots and selected visualization assets |
| `plot_better_recovery_radar.py` | Clean radar/bar plots for max recoverable force |
| `plot_adapter_trace_fancy.py` | Publication-style dashboard and nominal/adapted plan animation |
| `plot_adapter_trace_timing.py` | Timing-focused trace visualization |
| `plot_adapter_trace_timing_pretty.py` | Improved timing/footstep visualization, including target x(t), y(t) |
| `logs_final_1000/` | Final baseline + default adapter logs after rerun |
| `logs_timing_biased_full_1000/` | Final timing-biased logs after rerun |
| `plots_final_1000/` | Final plots for the presentation |
| `viz_final_1000/` | Final dashboard/animation assets |
| `archives/` | Archived old logs, scripts, plots, and miscellaneous previous results |

---

## Scientific motivation

A nominal offline footstep plan is rigid. It can work in unperturbed walking, but under external pushes the robot may need to quickly adjust its next step.

The reference paper by Khadiv et al. shows that, under a simplified LIPM/DCM model, adapting the **next footstep location** and **step timing** can preserve viability. The key idea is that the robot does not need to replan the whole gait; it can react by modifying only the next step.

In this project, the goal is more conservative:

> Keep the original DIAG IS-MPC walking pipeline intact, and add a local reactive layer that intervenes only when the current plan appears insufficient.

This makes the project valuable because it tests whether step timing/location adaptation can be integrated into an existing humanoid MPC framework without replacing the whole controller.

---

## Baseline architecture

The original DIAG IS-MPC pipeline can be summarized as:

1. Generate a nominal footstep plan.
2. Use IS-MPC to regulate CoM/ZMP motion over the planned footsteps.
3. Generate swing-foot trajectories from the planned footstep sequence.
4. Use inverse dynamics to compute torques.
5. Simulate the humanoid in DART.

The baseline controller uses fixed timing and fixed footstep positions. Once the walk starts, the nominal plan is not reactively modified in response to pushes.

---

## Added reactive architecture

The new architecture inserts a reactive adapter between state estimation / planning and the IS-MPC/swing-foot modules.

At each tick:

1. The simulator obtains current CoM/DCM/ZMP-related state.
2. The adapter checks whether it is allowed to intervene.
3. If activation conditions are satisfied, it solves a local QP.
4. If the QP solution is accepted, it updates the active footstep plan.
5. IS-MPC and swing-foot generation continue using the updated active plan.

The key architectural design is the separation between:

- **nominal plan**: immutable reference gait;
- **active plan**: mutable plan used online by MPC and swing-foot generation.

This makes the implementation relatively non-invasive: the original controller still solves the main walking problem, but the reference plan can be updated online.

---

## `step_timing_adapter.py`

This file is the core contribution.

### Decision variables

The local adaptation QP uses variables conceptually corresponding to:

| Variable | Meaning |
|---|---|
| `dx` | next-step x displacement in support/local frame |
| `dy` | next-step y displacement in support/local frame |
| `tau` | timing variable / timing-related decision |
| `bx`, `by` | DCM offset variables |
| `sx`, `sy` | slack variables |

The adapter can therefore modify both:

- the **spatial target** of the next step;
- the **temporal duration** of the active single-support step.

### Activation gates

The adapter is intentionally not always active. It can intervene only if:

- `--adapt` is enabled;
- the robot is in single support;
- the current step is valid;
- a next step exists;
- the system is outside the warmup window;
- the system is outside the freeze window near touchdown;
- the system is outside the cooldown window after a previous accepted update.

Then at least one disturbance/viability trigger must hold:

- DCM error is above threshold;
- or viability margin is small enough and DCM error is also non-negligible.

This makes the layer **reactive but gated**, reducing jitter and avoiding unnecessary plan changes during nominal walking.

### Safety and robustness mechanisms

The adapter includes practical safeguards:

- **Warmup ticks**: avoids changing the step immediately after a support switch.
- **Freeze ticks**: avoids changing the step too close to touchdown.
- **Cooldown ticks**: avoids repeated high-frequency updates.
- **`T_gap` clamp**: avoids accepting timing changes that make the remaining step too short.
- **Timing bounds**: `T_min_ticks`, `T_max_ticks`.
- **Minimum timing update**: ignores very small timing changes.
- **Minimum step displacement update**: ignores negligible footstep changes.
- **Per-update displacement clamp**: avoids excessive instantaneous footstep jumps.
- **Soft propagation to step N+2**: spreads part of the displacement to the following step, smoothing the active plan.

### Logged adapter statistics

Typical JSON/log summaries include:

- `updates`
- `activations`
- `qp_failures`
- `max_dcm_error`
- `ss_before`
- `ss_after`
- `nominal_step_ss`
- `active_step_ss`
- `nominal_next_ss`
- `active_next_ss`
- `last_update_tick`

These are crucial for explaining whether the controller actually modified the plan.

---

## `simulation.py`

The simulator now supports a rich experimental CLI.

Important flags:

| Argument | Description |
|---|---|
| `--adapt` | Enables the reactive adapter |
| `--timing-biased` | Enables diagnostic timing-biased QP tuning |
| `--headless` | Runs without viewer |
| `--steps N` | Maximum simulation ticks |
| `--profile forward/inplace/scianca` | Selects gait profile |
| `--force F` | Push force in Newtons |
| `--duration D` | Push duration in seconds |
| `--direction left/right/forward/backward` | Push direction |
| `--push-step S` | Step index at which the push is applied |
| `--push-phase P` | Fraction of the single-support phase |
| `--push-target base/stance_foot/lfoot/rfoot` | Push target |
| `--log-json PATH` | Saves detailed JSON trace |
| `--quiet` | Reduces console output |

Example baseline:

```bash
python simulation.py --headless --steps 1000   --profile forward   --force 45 --duration 0.10 --direction left   --push-step 3 --push-phase 0.55 --push-target base
```

Example default adapter:

```bash
python simulation.py --headless --steps 1000   --profile forward --adapt   --force 45 --duration 0.10 --direction left   --push-step 3 --push-phase 0.55 --push-target base
```

Example timing-biased adapter:

```bash
python simulation.py --headless --steps 1000   --profile forward --adapt --timing-biased   --force 50 --duration 0.10 --direction left   --push-step 3 --push-phase 0.55 --push-target base
```

---

## Push convention

The most meaningful tests are lateral pushes toward the unsupported side.

The main tested pattern is:

| Scenario | Step | Critical push direction |
|---|---:|---|
| Forward walking, step 3 | `S3` | `left` |
| Forward walking, step 4 | `S4` | `right` |

These are the cases where the robot must react by changing the next step to preserve balance.

Forward/backward pushes and in-place pushes are also tested, but they are harder and less consistently improved by the current adapter.

---

## Default adapter tuning

The default tuning used in the main previous final battery was:

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

This tuning behaves conservatively. In successful forward lateral-push cases, it mostly modifies **next footstep location** while often leaving timing unchanged.

This should be presented as the **stable controller**.

---

## Timing-biased diagnostic tuning

The diagnostic timing-biased mode is enabled by:

```bash
--timing-biased
```

It changes the QP cost/thresholds to make timing changes easier to accept. Typical diagnostic settings are:

```python
adapt_dcm_error_threshold = 0.0022
adapt_margin_error_gate   = 0.0015
adapt_viability_margin    = 0.030

adapt_alpha_step          = 35.0
adapt_alpha_time          = 0.05
adapt_alpha_offset        = 50.0
adapt_alpha_slack         = 1e4

T_gap_ticks               = 4
T_min_ticks               = 20
T_max_ticks               = 120

min_timing_update_ticks   = 1
min_step_update           = 0.005

adapt_warmup_ticks        = 15
adapt_freeze_ticks        = 4
adapt_cooldown_ticks      = 8
```

This mode has two purposes:

1. Show that the implementation can actually modify timing.
2. Study whether timing-biased adaptation improves recovery over the default adapter.

It should **not** automatically be presented as better than the default adapter. It is an ablation/diagnostic variant.

Representative timing update:

```text
[adapter] t=0443 step=3 err=0.0025 margin=0.1814
ss:70->71
xy:(0.600,-0.100)->(0.562,-0.051)
```

This means the adapter changed both:

- single-support duration: `70 -> 71` ticks;
- next footstep target: `(0.600,-0.100) -> (0.562,-0.051)`.

Important interpretation:

> The recovery is spatio-temporal: timing and footstep location change together. Do not claim that timing alone explains the improvement.

---

## Final 1000-step evaluation workflow

The previous workspace contained several generations of logs and plots, including runs with different horizons. For final presentation-quality results, the clean protocol is to rerun everything with:

```text
steps = 1000
```

The new final workflow produces:

| Folder | Meaning |
|---|---|
| `logs_final_1000/` | baseline + default adapter battery |
| `logs_timing_biased_full_1000/` | timing-biased rerun of adapted scenarios |
| `plots_final_1000/` | clean plots |
| `viz_final_1000/` | selected dashboards/animations |

### Step 1 — clean workspace

Dry run:

```bash
bash clean_workspace_for_final.sh
```

Apply:

```bash
APPLY=1 bash clean_workspace_for_final.sh
```

This archives old result folders under:

```text
archives/workspace_cleanup_<timestamp>/
```

It does not delete the source files.

### Step 2 — run final simulations

```bash
chmod +x run_final_1000_pipeline.sh
./run_final_1000_pipeline.sh
```

This runs:

```text
123 tests: baseline + default adapter
 64 tests: timing-biased adapted scenarios
-----------------------------------------
187 simulations total
```

### Step 3 — generate plots and visualization assets

```bash
chmod +x generate_final_plots_and_assets.sh
./generate_final_plots_and_assets.sh
```

Main outputs:

```text
plots_final_1000/p055_short/recovery_radar_clean.png
plots_final_1000/p055_short/recovery_bar_clean.png
plots_final_1000/paper_style/recovery_bar_clean.png
plots_final_1000/all/recovery_radar_clean.png
plots_final_1000/compare_default_vs_timing_1000.txt
viz_final_1000/
```

The most presentation-friendly plot is usually:

```text
plots_final_1000/p055_short/recovery_bar_clean.png
```

The radar plot is useful as a compact overview, but the bar plot is easier to read.

---

## Test battery structure

The main battery is organized into categories.

| Label | Scenario |
|---|---|
| A | Forward walking, left lateral push on step 3 |
| B | Forward walking, right lateral push on step 4 |
| C | Forward walking, sagittal pushes (`forward` / `backward`) |
| D | In-place stepping |
| E | Long push duration (`0.20 s`) |
| F | Fine frontier sweep around the lateral push recovery boundary |
| G | Paper-style early push (`push_phase = 0.05`) |
| H | Timing-biased diagnostic subset / timing sweep, used during development |

For the final slide deck, the most important categories are:

1. A: forward left S3 lateral pushes.
2. B: forward right S4 lateral pushes.
3. F: frontier sweep.
4. Timing-biased comparison as ablation.
5. In-place and long pushes as limitations.

---

## Main result: default adapter

The robust claim supported by the previous final battery is:

> In forward walking, for lateral body pushes toward the unsupported side, the default adapter improves recovery compared with the baseline.

Representative clean cases:

| Case | Baseline | Default adapter |
|---|---|---|
| Forward left S3, 45 N, P=0.35 | falls | survives |
| Forward left S3, 45 N, P=0.55 | falls | survives |
| Forward left S3, 50 N, P=0.55 | falls | survives |
| Forward right S4, 40 N, P=0.35 | falls | survives |
| Forward right S4, 40 N, P=0.55 | falls | survives |
| Frontier left S3, 46 N, P=0.55 | falls | survives |
| Frontier left S3, 48 N, P=0.55 | falls | survives |
| Frontier left S3, 50 N, P=0.55 | falls | survives |

Interpretation:

> The adapter shifts the useful recovery frontier upward in the forward lateral-push setting, with the clearest improvement around 45-50 N.

---

## Timing-biased comparison

A timing-biased full adapted rerun was added to compare:

```text
baseline
vs default adapter
vs timing-biased adapter
```

The preliminary non-uniform comparison showed:

```text
Compared timing-biased cases: 64
Timing-biased saves vs baseline:      9
Timing-biased improves vs default:    5
Timing-biased same category/default:  54
Timing-biased worse than default:     5
```

This means timing-biased adaptation is not simply better. It is useful because it:

- confirms that timing updates are functional;
- saves some cases that default does not save;
- improves survival time in some failing cases;
- but also creates regressions relative to the default adapter.

Correct interpretation:

> Timing-biased adaptation is promising but tuning-sensitive. The default adapter remains the more stable controller, while the timing-biased variant is evidence that the temporal adaptation branch works and can improve selected cases.

After running the final 1000-step pipeline, these values should be updated from:

```text
plots_final_1000/compare_default_vs_timing_1000.txt
```

---

## Limitations and negative results

The project should not be oversold. The current experiments do **not** support a general push-recovery claim.

### Forward/backward pushes

Sagittal pushes are not cleanly solved. Typically:

- both baseline and adapter fall;
- the adapter may increase survival time by a few ticks;
- no strong full-recovery claim should be made.

### Long pushes

For `duration = 0.20 s`, the adapter often helps only partially. It may delay falling but usually does not fully recover.

### In-place stepping

The in-place profile remains inconclusive/negative.

Previous results showed cases where the adapter makes performance worse. The likely causes are:

- the active plan is less informative in in-place stepping;
- lateral footstep relocation may interact badly with near-zero forward progression;
- timing/location updates may perturb the swing-foot/MPC consistency more than they help;
- the reference paper's in-place examples use a controller built around timing adaptation, whereas this project injects a reactive layer into an existing IS-MPC stack.

Correct statement:

> The current implementation should be presented as a forward-walking lateral push recovery layer, not as a robust in-place push recovery controller.

### Slippage

Slippage tests exist in older folders, but the final supported claim should avoid slippage unless a clean final battery is run specifically for it.

---

## Visualization strategy for the presentation

Recommended visual assets:

### 1. Main quantitative plot

Use:

```text
plots_final_1000/p055_short/recovery_bar_clean.png
```

This should be the main results plot because it is easier to read than the radar.

### 2. Overview plot

Use:

```text
plots_final_1000/p055_short/recovery_radar_clean.png
```

This is useful as a compact overview of recovery frontier changes.

### 3. Paper-style / early push plot

Use:

```text
plots_final_1000/paper_style/recovery_bar_clean.png
```

This helps discuss early-push behavior and relation to the paper.

### 4. Adapter trace dashboard

Use one dashboard from `viz_final_1000/` showing:

- DCM error / trigger behavior;
- accepted update;
- nominal vs adapted next footstep;
- timing change if available.

### 5. Animation/video

Use one or two animations only:

1. Baseline falls vs adapted survives for a clean forward lateral push.
2. Timing-biased example showing spatio-temporal adaptation.

Do not overload the presentation with too many videos.

---

## Best viewer/demo commands

### Clean default-adapter success

Baseline:

```bash
python simulation.py --profile forward   --force 45 --duration 0.10 --direction left   --push-step 3 --push-phase 0.55 --push-target base
```

Default adapter:

```bash
python simulation.py --adapt --profile forward   --force 45 --duration 0.10 --direction left   --push-step 3 --push-phase 0.55 --push-target base
```

### Frontier example

Baseline:

```bash
python simulation.py --profile forward   --force 50 --duration 0.10 --direction left   --push-step 3 --push-phase 0.55 --push-target base
```

Default adapter:

```bash
python simulation.py --adapt --profile forward   --force 50 --duration 0.10 --direction left   --push-step 3 --push-phase 0.55 --push-target base
```

Timing-biased:

```bash
python simulation.py --adapt --timing-biased --profile forward   --force 50 --duration 0.10 --direction left   --push-step 3 --push-phase 0.55 --push-target base
```

### Timing-branch demonstration

```bash
python simulation.py --headless --steps 1000   --adapt --timing-biased   --profile forward   --force 50 --duration 0.10 --direction left   --push-step 3 --push-phase 0.55 --push-target base   --log-json logs_viz/timing_demo_F50_P055_left_S3.json
```

Then:

```bash
python plot_adapter_trace_timing_pretty.py   logs_viz/timing_demo_F50_P055_left_S3.json   --outdir viz_adapter --fps 8 --stride 4
```

---

## Suggested slide structure

A strong presentation could follow this structure:

1. **Title**
   - Reactive Step Timing Adaptation for IS-MPC Humanoid Locomotion.

2. **Problem**
   - Fixed walking plans are fragile under pushes.

3. **Baseline**
   - DIAG IS-MPC pipeline: footstep planner, MPC, swing foot, inverse dynamics.

4. **Idea**
   - Add a reactive layer that modifies only next step location/timing.

5. **Reference paper**
   - Khadiv et al. and the idea of step timing/location adaptation.

6. **Architecture**
   - Nominal plan vs active plan.
   - Adapter inserted before MPC/swing-foot generation.

7. **QP / activation logic**
   - DCM error, viability margin, warmup/freeze/cooldown.
   - Local QP variables.

8. **Implementation**
   - Files modified: `simulation.py`, `step_timing_adapter.py`, `footstep_planner.py`, `foot_trajectory_generator.py`, `ismpc.py`.

9. **Experimental protocol**
   - 1000-step final run.
   - 123 baseline/default tests + 64 timing-biased tests.

10. **Main results**
    - Forward lateral push recovery.
    - Bar/radar plot.

11. **Timing-biased ablation**
    - Shows timing branch is active.
    - Saves selected cases but introduces regressions.

12. **Limitations**
    - In-place, long pushes, sagittal pushes.

13. **Conclusion**
    - Stable forward-walking lateral recovery achieved.
    - Timing adaptation is functional but tuning-sensitive.
    - Future work: integrate timing more deeply into MPC/foot trajectory consistency.

---

## Recommended conclusion for the presentation

> This project extends an existing IS-MPC humanoid walking controller with a lightweight reactive adaptation layer. The final controller improves robustness in the most relevant tested regime: forward walking under lateral body pushes toward the unsupported side. The default adapter achieves this mainly by relocating the next footstep online. A timing-biased variant confirms that the implemented QP can also modify the active single-support duration, but the results show that timing adaptation is tuning-sensitive and can introduce regressions. Therefore, the main contribution is a stable reactive step-location adaptation layer integrated into IS-MPC, with timing adaptation validated as a functional but still experimental extension.

---

## Files to pass to Claude for slide generation

Pass these files first:

```text
README_UPDATED_FOR_PRESENTATION.md
simulation.py
step_timing_adapter.py
footstep_planner.py
foot_trajectory_generator.py
ismpc.py
show_results.py
plot_better_recovery_radar.py
```

After the final 1000-step run, also pass:

```text
plots_final_1000/compare_default_vs_timing_1000.txt
plots_final_1000/p055_short/recovery_frontier_values.csv
plots_final_1000/p055_short/recovery_bar_clean.png
plots_final_1000/p055_short/recovery_radar_clean.png
plots_final_1000/paper_style/recovery_bar_clean.png
```

For animation/video slides, pass selected files from:

```text
viz_final_1000/
videos_final_1000/
```

Also useful:

```text
run_final_1000_pipeline.sh
generate_final_plots_and_assets.sh
clean_workspace_for_final.sh
```

Do **not** pass all old log folders unless needed. They may confuse the model because they include older runs with different horizons and partially obsolete settings.

---

## Prompt to give Claude

```text
I am preparing a technical presentation about my robotics project.

The project extends an existing DIAG IS-MPC humanoid locomotion framework with a reactive step adaptation layer. The layer modifies the active footstep plan online under pushes. The default adapter mainly improves recovery through next-footstep relocation. A timing-biased ablation confirms that the timing branch is active because the single-support duration can change online, but this variant is tuning-sensitive and not always better than the default controller.

Use the uploaded README and code files to generate a clear slide deck. The presentation should be suitable for a university robotics professor. It should be technically precise, but not overloaded. It must avoid overclaiming: the strong result is forward-walking lateral push recovery; in-place, sagittal, long-push, and slippage results are limitations.

Please structure the slides as:
1. Motivation
2. Baseline IS-MPC framework
3. Reference paper idea
4. Proposed reactive layer
5. Architecture and modified files
6. QP/activation logic
7. Experimental protocol
8. Main results
9. Timing-biased ablation
10. Limitations
11. Conclusion
12. Backup slides

Use the plots I uploaded as figures. Prefer the bar plot for quantitative comparison and the radar plot as overview. Include speaker notes in English at B2/C1 level.
```

---

## References

- M. Khadiv, A. Herzog, S. A. A. Moosavian, and L. Righetti, *Walking Control Based on Step Timing Adaptation*, arXiv:1704.01271.
- N. Scianca, D. De Simone, L. Lanari, and G. Oriolo, *MPC for Humanoid Gait Generation: Stability and Feasibility*, IEEE Transactions on Robotics, 2020.
- DIAG Robotics Lab IS-MPC framework.
