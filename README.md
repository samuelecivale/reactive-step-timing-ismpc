# Reactive Step Timing Adaptation for IS-MPC Humanoid Locomotion

Reactive footstep and step-timing adaptation for **humanoid push recovery**, built on top of an IS-MPC walking controller.

The project adds a lightweight online adaptation layer that modifies the active walking plan when external disturbances make the nominal plan insufficient.

## Key Results

Under lateral pushes during forward walking:

| Scenario     | Baseline IS-MPC | Default Adapter | Timing-Biased Adapter |
| ------------ | --------------: | --------------: | --------------------: |
| Forward L-S3 |            40 N |        **50 N** |              **55 N** |
| Forward R-S4 |            35 N |        **45 N** |              **50 N** |

The default adapter improves recoverable push magnitude by approximately:

* **+25%** in the Forward L-S3 scenario;
* **+29%** in the Forward R-S4 scenario.

The timing-biased configuration extends the recovery frontier further in selected cases, reaching **55 N** and **50 N**, respectively.

> The default adapter should be considered the stable controller.
> The timing-biased configuration is an ablation used to study the contribution of temporal adaptation.

---

## Motivation

A nominal humanoid walking controller follows a predefined footstep sequence and timing schedule.

This works well during undisturbed locomotion, but a sufficiently strong external push can make the current plan dynamically infeasible.

Instead of replacing the underlying walking controller, this project introduces a **reactive adaptation layer** that modifies the reference plan online.

The system maintains two plans:

* **Nominal plan** — the original walking reference;
* **Active plan** — the plan currently used by the controller and updated after disturbances.

The adapter remains inactive during normal walking and intervenes only when the current walking state indicates that the nominal plan may no longer be sufficient.

---

## System Architecture

The original walking pipeline contains:

```text
Footstep Planning
       │
       ▼
IS-MPC CoM / ZMP Control
       │
       ▼
Swing-Foot Trajectory Generation
       │
       ▼
Whole-Body Inverse Dynamics
       │
       ▼
DART Simulation
```

This project inserts a reactive layer between state estimation/planning and the existing walking-control modules:

```text
Walking State
     │
     ▼
Reactive Step Adapter
     │
     ├── Footstep Position Update
     └── Step Timing Update
     │
     ▼
Active Footstep Plan
     │
     ├───────────────┐
     ▼               ▼
   IS-MPC       Swing-Foot Generator
     │               │
     └───────┬───────┘
             ▼
     Inverse Dynamics
             │
             ▼
       DART Simulation
```

The original IS-MPC controller therefore remains largely unchanged.

The adapter modifies the **reference plan**, rather than replacing the underlying stabilization architecture.

---

## Reactive Adaptation

At every simulation step:

1. the current walking state is read;
2. the adapter determines whether intervention is allowed;
3. disturbance-related viability conditions are evaluated;
4. if necessary, a local optimization problem is solved;
5. the active footstep plan is updated;
6. the existing IS-MPC and swing-foot modules continue using the updated plan.

This allows the controller to react to disturbances while preserving the original walking-control pipeline.

---

## Adaptation Variables

The reactive optimization can modify both spatial and temporal quantities.

| Variable   | Meaning                                  |
| ---------- | ---------------------------------------- |
| `dx`       | Next-footstep displacement along local x |
| `dy`       | Next-footstep displacement along local y |
| `tau`      | Timing-related decision variable         |
| `bx`, `by` | DCM offset variables                     |
| `sx`, `sy` | Slack variables                          |

A successful intervention may therefore contain both:

* **footstep relocation**;
* **step-duration modification**.

The resulting recovery should be interpreted as **spatio-temporal adaptation**, rather than timing adaptation alone.

---

## Activation Logic

The adapter does not continuously alter the nominal gait.

An update is considered only when the main activation conditions are satisfied:

* adaptation has been enabled;
* the robot is in **single support**;
* a valid next footstep exists;
* the controller is outside warm-up, freeze, and cooldown intervals;
* the DCM/viability trigger indicates that the current plan may be insufficient.

Additional safeguards include:

* timing bounds;
* footstep displacement limits;
* minimum update thresholds;
* update rejection logic;
* soft propagation of corrections to subsequent footsteps.

These constraints reduce unnecessary modifications during nominal walking.

---

## Evaluation Setup

The main final evaluation uses:

```text
Simulation horizon : 1000 ticks
Push phase         : 0.55
Push duration      : 0.10 s
Push target        : robot base
```

The main benchmark studies forward walking under lateral disturbances toward the unsupported side.

The maximum recoverable disturbance is then compared across:

```text
Baseline IS-MPC
      vs
Default Reactive Adapter
      vs
Timing-Biased Adapter
```

---

## Results

### Recovery Frontier

| Controller      | Forward L-S3 | Forward R-S4 |
| --------------- | -----------: | -----------: |
| Baseline        |         40 N |         35 N |
| Default adapter |     **50 N** |     **45 N** |
| Timing-biased   |     **55 N** |     **50 N** |

The **default adapter** provides the main robust improvement.

Its gain is driven primarily by reactive next-footstep relocation.

The **timing-biased adapter** demonstrates that the timing branch is active and can improve selected recovery cases further, but it is more sensitive to tuning and may introduce regressions in other scenarios.

For this reason:

```text
Default Adapter  → main controller
Timing-Biased    → diagnostic / ablation configuration
```

---

## Example Recovery

A typical experiment applies a lateral push while the robot is in single support.

### Baseline

```bash
python3 simulation.py \
  --headless \
  --steps 1000 \
  --profile forward \
  --force 45 \
  --duration 0.10 \
  --direction left \
  --push-step 3 \
  --push-phase 0.55 \
  --push-target base
```

### Reactive Adapter

```bash
python3 simulation.py \
  --headless \
  --steps 1000 \
  --profile forward \
  --adapt \
  --force 45 \
  --duration 0.10 \
  --direction left \
  --push-step 3 \
  --push-phase 0.55 \
  --push-target base
```

### Timing-Biased Ablation

```bash
python3 simulation.py \
  --headless \
  --steps 1000 \
  --profile forward \
  --adapt \
  --timing-biased \
  --force 45 \
  --duration 0.10 \
  --direction left \
  --push-step 3 \
  --push-phase 0.55 \
  --push-target base
```

---

## Timing Adaptation Example

A timing-biased intervention may produce an update such as:

```text
[adapter] t=0443 step=3
ss: 70 -> 71
xy: (0.600, -0.100) -> (0.562, -0.051)
```

In this example both the support duration and the target footstep position change.

This illustrates why the improvement should be interpreted as **combined spatial and temporal adaptation**.

---

## Repository Structure

```text
reactive-step-timing-ismpc/
│
├── simulation.py
├── step_timing_adapter.py
├── footstep_planner.py
├── foot_trajectory_generator.py
├── ismpc.py
├── inverse_dynamics.py
├── filter.py
├── logger.py
│
├── show_results.py
├── plot_better_recovery_radar.py
├── plot_adapter_trace_fancy.py
│
├── run_all_tests.sh
├── run_final_1000_pipeline.sh
├── run_gapfill_tests_1000.sh
├── run_timing_biased_on_old_tests.sh
│
├── logs_final_1000/
├── logs_timing_biased_full_1000/
├── logs_gapfill_1000/
│
├── plots_final_1000/
├── viz_final_1000/
└── docs/assets/
```

### Main Components

| File                            | Purpose                                                                  |
| ------------------------------- | ------------------------------------------------------------------------ |
| `simulation.py`                 | Simulation entry point, disturbance scheduling and adapter configuration |
| `step_timing_adapter.py`        | Reactive optimization layer                                              |
| `footstep_planner.py`           | Nominal and active footstep-plan management                              |
| `foot_trajectory_generator.py`  | Swing-foot trajectory generation                                         |
| `ismpc.py`                      | IS-MPC walking-control backbone                                          |
| `inverse_dynamics.py`           | Whole-body inverse-dynamics controller                                   |
| `show_results.py`               | Aggregation of evaluation results                                        |
| `plot_better_recovery_radar.py` | Recovery-frontier visualization                                          |

---

## Reproducing the Evaluation

Run the complete final evaluation battery:

```bash
chmod +x run_final_1000_pipeline.sh
./run_final_1000_pipeline.sh
```

Additional recovery-frontier experiments can be generated with:

```bash
chmod +x run_gapfill_tests_1000.sh
./run_gapfill_tests_1000.sh
```

Aggregate the generated logs:

```bash
python3 show_results.py \
  logs_final_1000 \
  logs_timing_biased_full_1000 \
  logs_gapfill_1000
```

Generate the recovery-frontier plots:

```bash
python3 plot_better_recovery_radar.py \
  --logs \
    logs_final_1000 \
    logs_timing_biased_full_1000 \
    logs_gapfill_1000 \
  --phase 0.55 \
  --duration 0.10 \
  --complete-only \
  --outdir plots_final_1000/gapfilled_p055_short
```

---

## Visualizations

The evaluation pipeline can produce:

* recovery-frontier plots;
* controller traces;
* footstep-plan evolution;
* robot-motion animations;
* baseline vs adapted-controller comparisons.

Representative simulation animations can also be converted to lightweight GIFs for visualization directly on GitHub.

Example:

```bash
ffmpeg \
  -i viz_final_1000/A_fwd_adapt_F45_P055_left_S3_timing_animation.mp4 \
  -vf "fps=12,scale=900:-1:flags=lanczos" \
  docs/assets/adapter_recovery.gif
```

If available, a representative recovery GIF can then be embedded near the top of this README:

```markdown
![Reactive humanoid push recovery](docs/assets/adapter_recovery.gif)
```

---

## Useful CLI Options

| Argument          | Description                                     |
| ----------------- | ----------------------------------------------- |
| `--adapt`         | Enable reactive adaptation                      |
| `--timing-biased` | Enable timing-biased ablation                   |
| `--headless`      | Run without graphical viewer                    |
| `--steps N`       | Maximum simulation horizon                      |
| `--profile`       | Walking profile                                 |
| `--force F`       | Push magnitude in Newtons                       |
| `--duration D`    | Push duration                                   |
| `--direction`     | Push direction                                  |
| `--push-step S`   | Step where the disturbance is applied           |
| `--push-phase P`  | Phase of single support where the push occurs   |
| `--push-target`   | Body or contact point receiving the disturbance |
| `--log-json PATH` | Save simulation trace                           |
| `--quiet`         | Reduce terminal output                          |

---

## Design Philosophy

The main design goal was to avoid replacing an existing walking controller with a completely new architecture.

Instead, the project explores whether a **small reactive planning layer** can significantly improve robustness.

The resulting architecture separates:

```text
Nominal locomotion control
          +
Reactive disturbance handling
```

This keeps the baseline controller interpretable while allowing online adaptation when necessary.

---

## Limitations

The results should be interpreted within the tested simulation conditions.

In particular:

* the strongest improvements were observed in selected forward-walking disturbance scenarios;
* the timing-biased configuration is more tuning-sensitive than the default adapter;
* not every disturbance direction benefits equally from adaptation;
* the evaluation is simulation-based;
* the current method does not establish robustness for arbitrary pushes or walking conditions.

The timing-biased configuration should therefore not be interpreted as universally superior to the default adapter.

---

## Possible Extensions

Future work could explore:

* automatic tuning of adaptation weights;
* more systematic viability constraints;
* broader disturbance directions and magnitudes;
* uneven terrain;
* turning and non-straight walking;
* online disturbance estimation;
* learned adaptation policies;
* integration with model-based reinforcement learning;
* evaluation on a physical humanoid platform.

---

## Tech Stack

`Python` · `Model Predictive Control` · `Quadratic Programming` · `Humanoid Robotics` · `Walking Control` · `DART` · `Inverse Dynamics` · `Optimization`

---

## Skills Demonstrated

This project covers:

* humanoid locomotion;
* model predictive control;
* online optimization;
* disturbance recovery;
* reactive planning;
* inverse dynamics;
* simulation;
* controller evaluation;
* experiment design;
* quantitative robustness analysis.

---

## Background

The project extends an existing **IS-MPC humanoid walking framework** by adding a reactive layer for online footstep and timing adaptation.

The approach is inspired by research on step-timing adaptation for humanoid walking, while preserving the original controller architecture and implementing the adaptation as a lightweight overlay.

---

## Author

**Samuele Civale**
MSc Artificial Intelligence and Robotics
Sapienza University of Rome

GitHub: [@samuelecivale](https://github.com/samuelecivale)
