import copy
import numpy as np


class FootstepPlanner:
    """
    Nominal offline planner + mutable active plan.

    - self.nominal_plan: immutable reference gait
    - self.plan        : active gait used by MPC / swing generator

    The reactive layer is expected to modify only:
      * self.plan[current_step]['ss_duration']
      * self.plan[current_step + 1]['pos'] / ['ang']
    so the nominal plan always remains available.
    """

    def __init__(self, vref, initial_lfoot, initial_rfoot, params):
        self.params = params
        self.nominal_plan = []
        self._build_nominal_plan(vref, initial_lfoot, initial_rfoot, params)
        self.plan = copy.deepcopy(self.nominal_plan)

    def _build_nominal_plan(self, vref, initial_lfoot, initial_rfoot, params):
        default_ss_duration = params['ss_duration']
        default_ds_duration = params['ds_duration']

        unicycle_pos = (initial_lfoot[3:5] + initial_rfoot[3:5]) / 2.0
        unicycle_theta = (initial_lfoot[2] + initial_rfoot[2]) / 2.0
        support_foot = params['first_swing']

        for j in range(len(vref)):
            ss_duration = int(default_ss_duration)
            ds_duration = int(default_ds_duration)

            # First dummy step: extended double support, no swing.
            if j == 0:
                ss_duration = 0
                ds_duration = int((default_ss_duration + default_ds_duration) * 2)

            # Move the virtual unicycle using the nominal timing only.
            for _ in range(ss_duration + ds_duration):
                if j > 1:
                    unicycle_theta += vref[j][2] * params['world_time_step']
                    rot = np.array([
                        [np.cos(unicycle_theta), -np.sin(unicycle_theta)],
                        [np.sin(unicycle_theta),  np.cos(unicycle_theta)],
                    ])
                    unicycle_pos += rot @ np.asarray(vref[j][:2]) * params['world_time_step']

            displacement = 0.1 if support_foot == 'lfoot' else -0.1
            displ_x = -np.sin(unicycle_theta) * displacement
            displ_y =  np.cos(unicycle_theta) * displacement
            pos = np.array((unicycle_pos[0] + displ_x,
                            unicycle_pos[1] + displ_y,
                            0.0), dtype=float)
            ang = np.array((0.0, 0.0, unicycle_theta), dtype=float)

            self.nominal_plan.append({
                'pos': pos,
                'ang': ang,
                'ss_duration': int(ss_duration),
                'ds_duration': int(ds_duration),
                'foot_id': support_foot,
            })

            support_foot = 'rfoot' if support_foot == 'lfoot' else 'lfoot'

    def __len__(self):
        return len(self.plan)

    def get_step(self, step_index, use_nominal=False):
        plan = self.nominal_plan if use_nominal else self.plan
        step_index = int(np.clip(step_index, 0, len(plan) - 1))
        return plan[step_index]

    def reset_step_to_nominal(self, step_index):
        if 0 <= step_index < len(self.plan):
            self.plan[step_index] = copy.deepcopy(self.nominal_plan[step_index])

    def update_step(self, step_index, pos=None, ang=None, ss_duration=None, ds_duration=None):
        if not (0 <= step_index < len(self.plan)):
            return

        step = self.plan[step_index]
        nominal_step = self.nominal_plan[step_index]

        if pos is not None:
            pos = np.asarray(pos, dtype=float).copy()
            if pos.shape == (2,):
                pos = np.array([pos[0], pos[1], nominal_step['pos'][2]], dtype=float)
            step['pos'] = pos

        if ang is not None:
            step['ang'] = np.asarray(ang, dtype=float).copy()

        if ss_duration is not None:
            step['ss_duration'] = max(1, int(round(ss_duration))) if step_index > 0 else int(round(ss_duration))

        if ds_duration is not None:
            step['ds_duration'] = max(1, int(round(ds_duration)))

    def get_step_index_at_time(self, time, use_nominal=False):
        plan = self.nominal_plan if use_nominal else self.plan
        t = 0
        time = int(time)
        for i, step in enumerate(plan):
            t += int(step['ss_duration']) + int(step['ds_duration'])
            if t > time:
                return i
        return len(plan) - 1

    def get_start_time(self, step_index, use_nominal=False):
        plan = self.nominal_plan if use_nominal else self.plan
        step_index = int(np.clip(step_index, 0, len(plan)))
        t = 0
        for i in range(step_index):
            t += int(plan[i]['ss_duration']) + int(plan[i]['ds_duration'])
        return t

    def get_phase_at_time(self, time, use_nominal=False):
        plan = self.nominal_plan if use_nominal else self.plan
        step_index = self.get_step_index_at_time(time, use_nominal=use_nominal)
        start_time = self.get_start_time(step_index, use_nominal=use_nominal)
        time_in_step = int(time) - start_time
        if time_in_step < int(plan[step_index]['ss_duration']):
            return 'ss'
        return 'ds'

    def get_time_in_step(self, time, use_nominal=False):
        step_index = self.get_step_index_at_time(time, use_nominal=use_nominal)
        return int(time) - self.get_start_time(step_index, use_nominal=use_nominal)

    def get_step_time_remaining(self, time, use_nominal=False):
        step_index = self.get_step_index_at_time(time, use_nominal=use_nominal)
        phase = self.get_phase_at_time(time, use_nominal=use_nominal)
        step = self.get_step(step_index, use_nominal=use_nominal)
        time_in_step = self.get_time_in_step(time, use_nominal=use_nominal)
        if phase == 'ss':
            return int(step['ss_duration']) - time_in_step
        return int(step['ss_duration']) + int(step['ds_duration']) - time_in_step

    def get_support_rotation(self, step_index, use_nominal=False):
        yaw = self.get_step(step_index, use_nominal=use_nominal)['ang'][2]
        c = np.cos(yaw)
        s = np.sin(yaw)
        return np.array([[c, -s], [s, c]], dtype=float)

    def world_to_local(self, step_index, point_world, use_nominal=False):
        point_world = np.asarray(point_world, dtype=float)
        support = self.get_step(step_index, use_nominal=use_nominal)
        rot = self.get_support_rotation(step_index, use_nominal=use_nominal)
        return rot.T @ (point_world[:2] - support['pos'][:2])

    def local_to_world(self, step_index, point_local, use_nominal=False, z_value=None):
        point_local = np.asarray(point_local, dtype=float)
        support = self.get_step(step_index, use_nominal=use_nominal)
        rot = self.get_support_rotation(step_index, use_nominal=use_nominal)
        xy = support['pos'][:2] + rot @ point_local[:2]
        z = support['pos'][2] if z_value is None else float(z_value)
        return np.array([xy[0], xy[1], z], dtype=float)

    def get_next_step_displacement_local(self, step_index, use_nominal=False):
        plan = self.nominal_plan if use_nominal else self.plan
        if step_index + 1 >= len(plan):
            return np.zeros(2)
        support = plan[step_index]
        target = plan[step_index + 1]
        rot = self.get_support_rotation(step_index, use_nominal=use_nominal)
        return rot.T @ (target['pos'][:2] - support['pos'][:2])

    def get_total_duration(self, use_nominal=False):
        plan = self.nominal_plan if use_nominal else self.plan
        return sum(int(step['ss_duration']) + int(step['ds_duration']) for step in plan)
