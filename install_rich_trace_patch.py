#!/usr/bin/env python3
"""
install_rich_trace_patch.py

Run this from the project root, next to simulation.py:

    python install_rich_trace_patch.py

It patches simulation.py to add rich per-tick trace fields used by
plot_adapter_trace_fancy.py. A backup named simulation.py.bak_rich_trace is
created before writing.
"""

from __future__ import annotations

from pathlib import Path

SIM_PATH = Path("simulation.py")
BACKUP_PATH = Path("simulation.py.bak_rich_trace")

HELPER_METHODS = r'''
    def _json_vec(self, value, n=None):
        if value is None:
            return None
        try:
            arr = np.asarray(value, dtype=float).reshape(-1)
            if n is not None:
                arr = arr[:n]
            return [float(x) for x in arr]
        except Exception:
            return None

    def _serialize_plan_snapshot(self, use_nominal=False):
        plan = self.footstep_planner.nominal_plan if use_nominal else self.footstep_planner.plan
        rows = []
        for i, step in enumerate(plan):
            start = int(self.footstep_planner.get_start_time(i, use_nominal=use_nominal))
            ss = int(step['ss_duration'])
            ds = int(step['ds_duration'])
            rows.append({
                'step': int(i),
                'foot_id': step.get('foot_id'),
                'pos': self._json_vec(step.get('pos'), 3),
                'ang': self._json_vec(step.get('ang'), 3),
                'x': float(step['pos'][0]),
                'y': float(step['pos'][1]),
                'z': float(step['pos'][2]),
                'yaw': float(step['ang'][2]),
                'ss_duration': ss,
                'ds_duration': ds,
                'start_tick': start,
                'ss_end_tick': start + ss,
                'end_tick': start + ss + ds,
            })
        return rows

    def _serialize_adapter_event(self, event):
        if event is None:
            return None
        step_index = int(event['step_index'])
        before = np.asarray(event['target_before_world'], dtype=float).reshape(-1)
        after = np.asarray(event['target_after_world'], dtype=float).reshape(-1)
        out = {
            'tick': int(event['time_tick']),
            'time_s': float(event['time_tick'] * self.params['world_time_step']),
            'step_index': step_index,
            'target_step_index': step_index + 1,
            'dcm_error': float(event['dcm_error']),
            'margin': float(event['margin']),
            'ss_before': int(event['ss_before']),
            'ss_after': int(event['ss_after']),
            'target_before_x': float(before[0]),
            'target_before_y': float(before[1]),
            'target_after_x': float(after[0]),
            'target_after_y': float(after[1]),
        }
        if 'local_target_after' in event:
            local = np.asarray(event['local_target_after'], dtype=float).reshape(-1)
            out['local_target_after_x'] = float(local[0])
            out['local_target_after_y'] = float(local[1])
        if 'slack_x' in event:
            out['slack_x'] = float(event['slack_x'])
        if 'slack_y' in event:
            out['slack_y'] = float(event['slack_y'])
        return out

    def _plan_step_fields(self, prefix, step):
        return {
            f'{prefix}_x': float(step['pos'][0]),
            f'{prefix}_y': float(step['pos'][1]),
            f'{prefix}_z': float(step['pos'][2]),
            f'{prefix}_yaw': float(step['ang'][2]),
            f'{prefix}_ss': int(step['ss_duration']),
            f'{prefix}_ds': int(step['ds_duration']),
            f'{prefix}_foot': step.get('foot_id'),
        }

    def _make_rich_trace_fields(self, adapter_event, phase_diag):
        fields = {}
        try:
            step_index = self.footstep_planner.get_step_index_at_time(self.time)
            next_index = min(step_index + 1, len(self.footstep_planner) - 1)

            nominal_step = self.footstep_planner.get_step(step_index, use_nominal=True)
            active_step = self.footstep_planner.get_step(step_index, use_nominal=False)
            nominal_next = self.footstep_planner.get_step(next_index, use_nominal=True)
            active_next = self.footstep_planner.get_step(next_index, use_nominal=False)

            fields.update(self._plan_step_fields('nominal_step', nominal_step))
            fields.update(self._plan_step_fields('active_step', active_step))
            fields.update(self._plan_step_fields('nominal_next', nominal_next))
            fields.update(self._plan_step_fields('active_next', active_next))

            fields['plan_modified'] = bool(
                abs(float(active_step['ss_duration']) - float(nominal_step['ss_duration'])) > 0
                or np.linalg.norm(np.asarray(active_next['pos'][:2]) - np.asarray(nominal_next['pos'][:2])) > 1e-9
            )

            dcm = self.step_timing_adapter.compute_dcm(self.current)
            desired_dcm = self.desired['com']['pos'][:2] + self.desired['com']['vel'][:2] / self.params['eta']
            fields['dcm_x'] = float(dcm[0])
            fields['dcm_y'] = float(dcm[1])
            fields['desired_dcm_x'] = float(desired_dcm[0])
            fields['desired_dcm_y'] = float(desired_dcm[1])
            fields['dcm_error_live'] = float(np.linalg.norm(dcm - desired_dcm))

            for batch_name, state in [('current', self.current), ('desired', self.desired)]:
                fields[f'{batch_name}_com_x'] = float(state['com']['pos'][0])
                fields[f'{batch_name}_com_y'] = float(state['com']['pos'][1])
                fields[f'{batch_name}_com_z'] = float(state['com']['pos'][2])
                fields[f'{batch_name}_zmp_x'] = float(state['zmp']['pos'][0])
                fields[f'{batch_name}_zmp_y'] = float(state['zmp']['pos'][1])
                fields[f'{batch_name}_zmp_z'] = float(state['zmp']['pos'][2])
                for foot in ['lfoot', 'rfoot']:
                    pose = state[foot]['pos']
                    fields[f'{batch_name}_{foot}_x'] = float(pose[3])
                    fields[f'{batch_name}_{foot}_y'] = float(pose[4])
                    fields[f'{batch_name}_{foot}_z'] = float(pose[5])

        except Exception as e:
            fields['rich_trace_error'] = str(e)

        return fields
'''


def patch() -> None:
    if not SIM_PATH.exists():
        raise SystemExit("simulation.py not found. Run this from the project root.")

    text = SIM_PATH.read_text()
    if "def _make_rich_trace_fields" in text:
        print("simulation.py already seems patched. Nothing to do.")
        return

    if not BACKUP_PATH.exists():
        BACKUP_PATH.write_text(text)
        print(f"backup created: {BACKUP_PATH}")

    text = text.replace(
        "        self.adapter_trace = []\n",
        "        self.adapter_trace = []\n        self.adapter_events = []\n",
        1,
    )

    marker = "    def customPreStep(self):\n"
    if marker not in text:
        raise SystemExit("Could not find customPreStep marker in simulation.py")
    text = text.replace(marker, HELPER_METHODS + "\n" + marker, 1)

    old_append = "        self.adapter_trace.append(trace_row)\n"
    new_append = (
        "        trace_row.update(self._make_rich_trace_fields(adapter_event, phase_diag))\n"
        "        if adapter_event is not None:\n"
        "            self.adapter_events.append(self._serialize_adapter_event(adapter_event))\n"
        "        self.adapter_trace.append(trace_row)\n"
    )
    if old_append not in text:
        raise SystemExit("Could not find adapter_trace.append(trace_row) in simulation.py")
    text = text.replace(old_append, new_append, 1)

    old_summary = "            'trace': self.adapter_trace,\n"
    new_summary = (
        "            'trace': self.adapter_trace,\n"
        "            'adapter_events': self.adapter_events,\n"
        "            'nominal_plan': self._serialize_plan_snapshot(use_nominal=True),\n"
        "            'final_plan': self._serialize_plan_snapshot(use_nominal=False),\n"
    )
    if old_summary not in text:
        raise SystemExit("Could not find trace field in get_summary().")
    text = text.replace(old_summary, new_summary, 1)

    SIM_PATH.write_text(text)
    print("simulation.py patched successfully.")
    print("Now run a simulation with --log-json, then use plot_adapter_trace_fancy.py.")


if __name__ == "__main__":
    patch()
