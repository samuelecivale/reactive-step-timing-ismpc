# Reactive Step Timing Adaptation for IS-MPC Humanoid Locomotion

This project extends the [DIAG Robotics Lab IS-MPC framework](https://github.com/DIAG-Robotics-Lab/ismpc) with a **reactive step adaptation layer** for humanoid locomotion under perturbations.

The original framework provides an MPC-based humanoid walking controller with:
- nominal footstep planning,
- IS-MPC for CoM/ZMP regulation,
- swing foot trajectory generation,
- inverse dynamics control,
- DART-based simulation.

My contribution adds an online recovery layer that can modify:
- **where** the next footstep lands,
- and, when needed, **when** it lands.

The goal is to improve robustness against disturbances while keeping the original IS-MPC pipeline largely intact.

---

## Motivation

In the original baseline, the walking plan is generated offline and executed with fixed step timing.
This works well in nominal conditions, but when the robot is pushed, a fixed plan may become too rigid.

The idea of this extension is simple:

- keep the original IS-MPC controller as the main walking controller,
- monitor the robot online during walking,
- if the state becomes critical, adapt the next step online,
- recover balance by changing step placement and, in some cases, step timing.

This project is inspired by the ideas presented in:

> **M. Khadiv, A. Herzog, S. A. A. Moosavian, and L. Righetti**,
> *"Walking Control Based on Step Timing Adaptation"*,
> arXiv:1704.01271, 2020.

The paper shows that, under the Linear Inverted Pendulum Model (LIPM), it is sufficient to optimize only the next step location and timing to guarantee that any viable state remains viable — without needing a multi-step preview horizon. It proposes a convex QP that adapts step placement and duration at every control cycle, and demonstrates significant improvements in push recovery on a humanoid with passive ankles.

This project takes those ideas and implements them as a **practical extension of the DIAG IS-MPC codebase**, rather than a full reimplementation of the paper's controller.

---

## What was added

### 1. Reactive `StepTimingAdapter`
A new module, `step_timing_adapter.py`, was added.

It observes simplified balance-related variables during walking and, when activation conditions are met, solves a small QP to update:
- the **single-support duration** of the current step,
- the **landing position** of the next step.

The adapter keeps track of:
- activations,
- successful updates,
- QP failures,
- maximum observed DCM error.

### 2. Nominal plan + active plan
The original planner used a single fixed plan.

In the extended version, the planner conceptually separates:
- a **nominal plan** (reference),
- an **active plan** (mutable online).

This allows online corrections without destroying the original reference trajectory.

### 3. Online swing-foot trajectory re-planning
The original swing-foot generator assumed fixed timing and fixed landing targets.

The modified version:
- reads the active plan at each call,
- re-anchors the swing trajectory when timing or landing position changes,
- uses boundary-conditioned quintic trajectories,
- keeps the trajectory continuous in position, velocity and acceleration.

This makes the adaptation layer compatible with the full humanoid simulation.

### 4. Headless testing and logging
The simulation was extended with:
- command-line arguments,
- `--headless` mode for repeatable experiments,
- scheduled pushes from CLI,
- JSON logging of test summaries,
- automatic collection of adaptation statistics.

This made it possible to run systematic perturbation tests and compare the baseline against the adaptive version.

---

## How the pipeline works

1. **Nominal footstep planner** generates a reference gait.
2. A mutable **active plan** is maintained online.
3. The robot state is read and filtered.
4. The **StepTimingAdapter** checks whether a correction is needed.
5. If activated, it updates the active plan:
   - next landing position,
   - current step timing.
6. The main **IS-MPC** controller solves the CoM/ZMP problem using the active plan.
7. The swing foot generator produces trajectories consistent with the updated plan.
8. Inverse dynamics generates the final torques for the humanoid.
9. Pushes can be injected for evaluation.

---

## When the adapter activates

The adapter does **not** run continuously.

It only enters under specific conditions:
- step timing adaptation is enabled,
- the robot is in **single support**,
- it is not too early in the step (`warmup` window),
- it is not too late in the step (`freeze` window),
- it is not inside a cooldown period after a recent update,
- and the measured balance indicators exceed activation thresholds.

The main indicators used are:
- **DCM error**
- **viability margin**

If the state is critical enough, the local QP is solved and the step is adapted.

---

## Main parameters introduced

The reactive layer adds parameters such as:

| Parameter | Description |
|---|---|
| `use_step_timing_adaptation` | Enable/disable the reactive layer |
| `adapt_dcm_error_threshold` | DCM error threshold for activation |
| `adapt_viability_margin` | Viability margin threshold |
| `adapt_margin_error_gate` | Combined margin–error gate |
| `adapt_alpha_step` | QP cost weight for step placement |
| `adapt_alpha_time` | QP cost weight for timing change |
| `adapt_alpha_offset` | QP cost weight for offset |
| `adapt_alpha_slack` | QP cost weight for slack variable |
| `adapt_warmup_ticks` | Ticks before adapter can activate |
| `adapt_freeze_ticks` | Ticks before step end where adapter freezes |
| `adapt_cooldown_ticks` | Cooldown after a successful update |
| `T_gap_ticks` | Gap ticks for double support transition |
| `T_min_ticks` / `T_max_ticks` | Bounds on single-support duration |
| `min_timing_update_ticks` | Minimum timing change to accept |
| `min_step_update` | Minimum step placement change to accept |
| Geometric margins | `forward`, `backward`, `outward`, `inward`, `cross_margin` |

These parameters control activation sensitivity, QP cost structure, timing bounds, feasible footstep region, and anti-jitter logic.

---

## CLI arguments

| Argument | Description |
|---|---|
| `--adapt` | Enable the reactive adaptation layer |
| `--headless` | Run without the graphical viewer |
| `--steps` | Maximum number of simulation ticks |
| `--force` | Magnitude of the external push (N) |
| `--duration` | Duration of the push (s) |
| `--direction` | Push direction (`left`, `right`, `forward`, `backward`) |
| `--push-step` | Step index where the perturbation is applied |
| `--push-phase` | Fraction of the step phase at which the push is injected |
| `--quiet` | Reduce console output |

In the local experimental version used for testing, I also used:
- `--profile` to switch between `forward` and `inplace` scenarios,
- `--log-json` to save structured summaries for each run.

---

## Experimental setup

I tested two main walking profiles:

- **Forward walking**
- **Stepping in place**

The main goal was not just to see whether the robot falls or survives, but to compare baseline fixed-timing behavior against adaptive behavior under the same perturbation.

For quantitative comparisons, I used **headless runs only**, since they are more repeatable than viewer-based execution.

---

## Results

### Forward walking
A representative result is:

- baseline survives at **30 N**
- baseline fails at **40 N**
- adaptive controller survives at **40 N**

This shows that the reactive layer improves robustness in forward walking.

At the same time, the observed recovery in forward walking is still mostly driven by **footstep placement adaptation**, which is also consistent with the main humanoid forward-walking results discussed in the reference literature.

### Stepping in place
This scenario is where timing adaptation becomes more visible.

In the adaptive runs, I observed a genuine timing update in the logs:

```
ss:70 -> 69
```

This means the controller is not only changing **where** to step, but also **when** to step.

This is important because it demonstrates that the project goal was actually achieved: the system can vary the timing between consecutive steps when required by a perturbation.

---

## Difference from the reference paper

This project is **inspired by** the paper by Khadiv et al. (*"Walking Control Based on Step Timing Adaptation"*, arXiv:1704.01271), but it is **not** a full reproduction.

Main differences:

1. The original DIAG IS-MPC codebase was kept as the main controller backbone, whereas the paper builds a standalone stepping controller with no reliance on CoP modulation.
2. The reactive layer was implemented as an extension on top of the existing IS-MPC controller, which already handles CoM/ZMP regulation. The paper's controller instead uses only step location and timing, without explicit CoP or CoM control.
3. The paper formulates the stepping QP with decision variables τ = e^(ω₀T), b (DCM offset), and uT (next footstep), solved at every control cycle (1 kHz). My adapter runs only when activation conditions are met, and uses a simplified QP.
4. The swing-foot generator uses a practical online quintic re-anchoring method instead of reproducing the paper's full 9th-order vertical swing-foot QP (Eq. 21 in the paper).
5. The paper demonstrates that timing adaptation can improve push recovery by up to ~5x in impulse tolerance. In my tests on the DIAG IS-MPC framework, forward walking mainly showed **step placement adaptation**, while **timing adaptation** became more evident in stepping in place, which is coherent with the qualitative behavior discussed in the paper.

---

## Environment

Recommended environment:
- **Ubuntu 24.04.3 LTS x86_64**
- Python virtual environment

Typical dependencies:
- `numpy`
- `scipy`
- `matplotlib`
- `osqp`
- `pyyaml`
- `casadi`
- `dartpy`

A reproducible environment can be restored with:

```bash
pip install -r requirements.txt
```

---

## Example commands

Baseline:

```bash
python simulation.py --headless --quiet --profile forward --steps 1400 --force 40 --duration 0.10 --direction left --push-step 3 --push-phase 0.05
```

Adaptive:

```bash
python simulation.py --headless --quiet --profile forward --adapt --steps 1400 --force 40 --duration 0.10 --direction left --push-step 3 --push-phase 0.55
```

Stepping in place:

```bash
python simulation.py --headless --quiet --profile inplace --adapt --steps 1400 --force 30 --duration 0.10 --direction left --push-step 3 --push-phase 0.55
```

---

## Takeaway

The final result is a practical extension of the DIAG IS-MPC humanoid walking framework that adds:

- reactive footstep adaptation,
- reactive step timing adaptation,
- headless perturbation testing,
- reproducible logging for robustness evaluation.

In forward walking, the method improves robustness against perturbations.
In stepping in place, it also shows explicit timing changes, demonstrating that the controller can adapt both step location and step timing online.

---

## References

- **M. Khadiv, A. Herzog, S. A. A. Moosavian, and L. Righetti**, *"Walking Control Based on Step Timing Adaptation"*, arXiv:1704.01271v3, 2020. [[arXiv]](https://arxiv.org/abs/1704.01271)
- **DIAG Robotics Lab IS-MPC framework**: [[GitHub]](https://github.com/DIAG-Robotics-Lab/ismpc)
