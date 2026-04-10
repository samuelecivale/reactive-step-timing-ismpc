# IS-MPC – Reactive Step Timing Adaptation

This repository extends the original IS-MPC humanoid locomotion workspace with a **reactive step adaptation layer** that can modify **step timing** and **next-footstep location** online after a perturbation.

The goal of the project was not to rewrite the whole controller, but to **add a reactive layer on top of the baseline MPC** while keeping the nominal planner and the main IS-MPC structure as intact as possible.

---

## 1. Final repository logic

The project is now organized around a **single final simulation entry point**:

- `simulation.py` → final simulation file used for both viewer runs and reproducible headless tests
- `step_timing_adapter.py` → reactive layer that evaluates whether adaptation is needed and, if so, updates the active plan
- `footstep_planner.py` → holds both the immutable nominal plan and the active plan that can be modified online
- `foot_trajectory_generator.py` → updates the swing-foot motion consistently with timing/landing changes
- `ismpc.py` → main MPC controller, kept as close as possible to the original baseline

The rest of the pipeline stays conceptually the same:

1. recover robot state
2. filter CoM / ZMP
3. possibly run the reactive adapter
4. solve the main MPC
5. generate the foot trajectories
6. compute torques with inverse dynamics
7. apply the scheduled perturbation
8. log results and detect failure

---

## 2. Main idea of the extension

The original workspace uses a nominal footstep plan with fixed timing.
The extension introduces a **StepTimingAdapter** that can:

- detect critical situations through a heuristic based on **DCM error** and **viability margin**
- solve a small QP to adapt the next step
- modify:
  - the **single-support duration** of the relevant step
  - the **landing position** of the next footstep
- leave the nominal plan untouched and update only the **active plan**

This means the adaptation layer behaves as a **reactive correction module**, not as a second always-on planner.

---

## 3. Important modifications in `simulation.py`

The final `simulation.py` now supports a richer CLI and a more test-oriented workflow.

### New parser arguments

The final parser includes:

- `--adapt` → enable the reactive layer
- `--headless` → run without viewer for reproducible tests
- `--steps` → stop after a fixed number of ticks
- `--force` → push magnitude in Newtons
- `--duration` → push duration in seconds
- `--push-step` → planner step index used to schedule the perturbation
- `--push-time` → absolute push time in seconds
- `--push-phase` → fraction of the selected single-support phase where the perturbation starts
- `--direction` → `left`, `right`, `forward`, `backward`
- `--push-target` → `base`, `stance_foot`, `lfoot`, `rfoot`
- `--profile` → `forward`, `inplace`, `scianca`
- `--log-json` → save summary JSON for the run

### Meaning of `push_target`

`push_target` was added to distinguish between two classes of perturbation:

- `base` → force applied to the robot body / trunk region
- `stance_foot` → force applied to the current support foot
- `lfoot`, `rfoot` → force applied explicitly to one foot

This was introduced to separate:

1. **body push recovery**, which turned out to be the cleanest and most convincing experimental scenario
2. **slip-like stance-foot perturbation**, which was explored to mimic the paper more closely but was less conclusive in this implementation

---

## 4. Force visualization in the viewer

A visual arrow was added in the viewer to show the external push direction and its timing.

Purpose:

- make the perturbation easier to understand during qualitative runs
- help produce short videos for the presentation
- visually verify whether the perturbation is applied to the body or to the support foot

The arrow is only meant for viewer inspection; quantitative conclusions come from the headless tests and JSON summaries.

---

## 5. Headless testing and failure handling

The final workflow relies mainly on **headless runs**.

Why:

- they are easier to repeat
- they stop after a known number of ticks
- they produce `.json` summaries and `.log` files
- numerical failures of the solver are captured and treated as failed runs

A run is considered failed if:

- the robot falls physically, or
- the solver raises a `RuntimeError`

This is important because some unstable runs do not simply look like a visual fall: they may instead collapse numerically.

---

## 6. Test batteries that were used

### `logs/`
First exploratory sweep.
Used to understand roughly where baseline and adapted behavior started to differ.
Contains both body-push and slip-like experiments.

### `logs_refined/`
Second battery, more focused than the first one.
Used to refine force ranges and `push_phase` values.
Still includes both body push and stance-foot perturbation tests.

### `logs_body_tuning/`
Final body-push tuning battery.
This is the most relevant folder for the final result, because it contains the tests used after tuning the reactive-layer parameters.

---

## 7. Final tuning used for the best body-push results

The final body-push battery was run with the following parameters:

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

Interpretation:

- the adapter becomes less nervous
- tiny updates are filtered out
- the cooldown is longer
- the final part of the step is protected more strongly
- the QP is less likely to react to insignificant deviations

This made the **body-push frontier** much more readable.

---

## 8. Main quantitative result that we keep

The strongest final result is on **body pushes at `push_phase = 0.55`**.

### Baseline
- `35 N` → survives
- `40 N` → fails
- `45 N` → fails

### Adapted
- `40 N` → survives
- `45 N` → survives
- `50 N` → survives in the tuning battery that produced the final frontier
- `55 N` → fails

This gives a readable conclusion:

> with the final tuning, the reactive layer shifts the failure frontier forward in the body-push scenario.

This is the result that should be presented as the main quantitative outcome.

---

## 9. What happened with the slip-like / stance-foot tests

We also introduced tests with `--push-target stance_foot` to approximate a **slip-like perturbation**.
These tests can be found mainly in:

- `logs/`
- `logs_refined/`

Typical filenames are:

- `slip_base_*.json`
- `slip_adapt_*.json`
- `paperlike_slip_*.json`

### Why they were less convincing than body pushes

The body-push scenario worked better because it is a cleaner perturbation for the current setup.
The slip-like scenario was less convincing for at least three reasons:

1. **Contact-model sensitivity**
   A stance-foot perturbation depends strongly on how contact and friction are simulated.
   If the foot does not really slip in a clean and repeatable way, the scenario becomes hard to interpret.

2. **Different physical emphasis from the paper**
   The paper uses a full humanoid simulation setup explicitly designed for these kinds of perturbations, including detailed foot contacts, passive-ankle behavior, and a contact model that makes slippage a more central effect.
   In our case, the body-push scenario is much more robust and repeatable than the slip-like one.

3. **Less clear separation between baseline and adaptation**
   In our slip-like tests, baseline and adapted runs often survived together, or the adapted controller activated without producing a strong visible advantage.
   So the result was exploratory, not strong enough to be the main claim.

### Relation to the paper

The paper includes both push recovery and slippage recovery experiments, and in the slippage experiments the scenarios are not exactly identical between the non-adaptive and adaptive cases. In particular, one slippage test is discussed in forward walking and another one in stepping-in-place with timing adaptation. This makes sense in the paper’s own setup, but it also means that reproducing the same qualitative story in a different simulator is not trivial.

For our project, the fairest choice is therefore:

- **body push** → main result
- **stance-foot / slip-like** → exploratory extension

---

## 10. Plots that were added and what they show

We added a small plotting workflow that reads the JSON trace and generates figures for selected runs.

Example files produced:

- `body_base_F40_P055_dcm_error.png`
- `body_base_F40_P055_margin.png`
- `body_base_F40_P055_step_updates.png`
- `body_adapt_F45_P055_dcm_error.png`
- `body_adapt_F45_P055_margin.png`
- `body_adapt_F45_P055_step_updates.png`
- `body_adapt_F50_P055_dcm_error.png`
- `body_adapt_F50_P055_margin.png`
- `body_adapt_F50_P055_step_updates.png`

### Plot meaning

#### `*_dcm_error.png`
Shows the DCM error over time.
Used to highlight when the perturbation happens and whether the adapter update is triggered near a growth in instability.

#### `*_margin.png`
Shows the viability margin over time.
Used to show whether the system approaches or crosses a critical viability region.

#### `*_step_updates.png`
Contains two subplots:
- single-support duration over time
- next-step lateral target over time

Purpose:

- show whether the adapter really changed timing
- show whether it changed the lateral foothold target
- connect the intervention timing with the push interval

### Practical remark

The plots are useful mainly as **diagnostic plots**.
In our final selected body-push cases, the adapter often performs only one meaningful update, so the plots are informative but visually minimal. They help explain the mechanism, but they are not dramatic trajectory plots.

---

## 11. Final scripts and their roles

### `run_final_tests.sh`
Initial exploratory sweep.
Useful for early debugging and broad scanning.

### `run_final_tests_arrow.sh`
Intermediate script used while the simulation with viewer-arrow support was still separated.
Now mostly legacy if `simulation.py` is the only final entry point.

### `run_final_tests_ABCDE.sh`
Keep only if needed for older experimental branches.
Not necessary for the final project narrative.

### `run_body_tuning.sh`
Most important final script.
Used to test the tuned controller only on the body-push scenario and generate the final readable frontier.

---

## 12. What should go into the presentation

### Core technical files
- `simulation.py`
- `step_timing_adapter.py`
- `footstep_planner.py`
- `foot_trajectory_generator.py`
- `ismpc.py`

### Result files worth mentioning
- `logs_body_tuning/` as main quantitative battery
- selected JSON summaries for the key cases
- selected viewer videos for a few representative runs
- optionally one or two diagnostic plots

### Viewer cases worth recording
- baseline body push that fails around the final selected threshold
- adapted body push that survives at a higher force
- optionally one hard late-phase case (`push_phase = 0.75`) to show that later pushes are harder to recover from

---

## 13. Final conclusion

The project successfully added a **reactive step timing / step location adaptation layer** on top of the baseline IS-MPC structure.

The strongest and most defensible result is:

- in **body-push recovery**, with the final tuning, the adaptive controller improves the robustness frontier compared to the baseline

The **stance-foot / slip-like** extension was implemented and tested, but in this simulator it remained more exploratory and less conclusive than the body-push case.

So the final story of the project is not “we reproduced every scenario from the paper perfectly”, but rather:

- we implemented the reactive mechanism
- we integrated it coherently into the IS-MPC stack
- we obtained a clear benefit in the most stable and interpretable perturbation scenario