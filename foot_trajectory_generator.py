import numpy as np


class FootTrajectoryGenerator:
    """
    Online swing-foot trajectory generator.

    Compared to the original version, this generator:
      - reads the mutable active plan at each call
      - re-anchors the swing trajectory whenever the next landing time
        or landing position changes
      - uses boundary-conditioned quintics, which keeps the desired
        trajectory continuous in position / velocity / acceleration

    This is less invasive than reproducing the paper's full 9th-order
    vertical QP, but it is robust and compatible with online timing updates.
    """

    def __init__(self, initial, footstep_planner, params):
        self.delta = params['world_time_step']
        self.step_height = params['step_height']
        self.initial = initial
        self.footstep_planner = footstep_planner

        self.active_context = None
        self.last_swing_sample = None

    def generate_feet_trajectories_at_time(self, time, current=None):
        plan = self.footstep_planner.plan
        step_index = self.footstep_planner.get_step_index_at_time(time)
        time_in_step = self.footstep_planner.get_time_in_step(time)
        phase = self.footstep_planner.get_phase_at_time(time)
        support_foot = plan[step_index]['foot_id']
        swing_foot = 'lfoot' if support_foot == 'rfoot' else 'rfoot'

        if step_index == 0:
            self.active_context = None
            self.last_swing_sample = None
            zero_vel = np.zeros(6)
            zero_acc = np.zeros(6)
            return {
                'lfoot': {'pos': self.initial['lfoot']['pos'], 'vel': zero_vel, 'acc': zero_acc},
                'rfoot': {'pos': self.initial['rfoot']['pos'], 'vel': zero_vel, 'acc': zero_acc},
            }

        if phase == 'ds' or step_index + 1 >= len(plan):
            self.active_context = None
            self.last_swing_sample = None
            return self._double_support_output(step_index)

        self._refresh_context(time, step_index, swing_foot, current)
        swing_data = self._evaluate_active_context(time)
        support_data = self._stationary_support_output(step_index)

        self.last_swing_sample = {
            'step_index': step_index,
            'swing_foot': swing_foot,
            'time': int(time),
            'pos': swing_data['pos'].copy(),
            'vel': swing_data['vel'].copy(),
            'acc': swing_data['acc'].copy(),
        }

        return {
            support_foot: support_data,
            swing_foot: swing_data,
        }

    def _refresh_context(self, time, step_index, swing_foot, current):
        plan = self.footstep_planner.plan
        target_step = plan[step_index + 1]
        current_step = plan[step_index]
        target_pose = np.hstack((target_step['ang'], target_step['pos']))
        signature = (
            int(step_index),
            int(current_step['ss_duration']),
            tuple(np.round(target_pose, 9)),
        )

        needs_replan = (
            self.active_context is None
            or self.active_context['signature'] != signature
            or self.active_context['step_index'] != step_index
        )

        if not needs_replan:
            return

        if (
            self.last_swing_sample is not None
            and self.last_swing_sample['step_index'] == step_index
            and self.last_swing_sample['swing_foot'] == swing_foot
        ):
            anchor_pos = self.last_swing_sample['pos'].copy()
            anchor_vel = self.last_swing_sample['vel'].copy()
            anchor_acc = self.last_swing_sample['acc'].copy()
        else:
            anchor_pos, anchor_vel, anchor_acc = self._get_step_start_state(step_index, swing_foot, current)

        remaining_ticks = max(int(current_step['ss_duration']) - self.footstep_planner.get_time_in_step(time), 1)
        remaining_time = max(remaining_ticks * self.delta, self.delta)

        coeff = self._quintic_coefficients(
            p0=anchor_pos,
            v0=anchor_vel,
            a0=anchor_acc,
            pf=np.hstack((target_step['ang'], target_step['pos'])),
            vf=np.zeros(6),
            af=np.zeros(6),
            T=remaining_time,
        )

        self.active_context = {
            'signature': signature,
            'step_index': step_index,
            'swing_foot': swing_foot,
            'anchor_time': int(time),
            'duration': remaining_time,
            'coeff': coeff,
        }

    def _get_step_start_state(self, step_index, swing_foot, current):
        plan = self.footstep_planner.plan
        start_pose = np.hstack((plan[step_index - 1]['ang'], plan[step_index - 1]['pos']))
        zero = np.zeros(6)

        if current is None or swing_foot not in current:
            return start_pose.copy(), zero.copy(), zero.copy()

        pose = np.asarray(current[swing_foot]['pos'], dtype=float).copy()
        vel = np.asarray(current[swing_foot]['vel'], dtype=float).copy()
        acc = np.zeros(6)
        if pose.shape != (6,):
            pose = start_pose.copy()
        if vel.shape != (6,):
            vel = zero.copy()
        return pose, vel, acc

    def _evaluate_active_context(self, time):
        ctx = self.active_context
        tau = np.clip((int(time) - ctx['anchor_time']) * self.delta, 0.0, ctx['duration'])
        pos, vel, acc = self._evaluate_quintic(ctx['coeff'], tau)

        # Keep the swing foot above the ground in a robust way.
        pos[5] = max(pos[5], 0.0)
        if pos[5] <= 0.0 and vel[5] < 0.0:
            vel[5] = 0.0
        if pos[5] <= 0.0 and acc[5] < 0.0:
            acc[5] = 0.0

        return {
            'pos': pos,
            'vel': vel,
            'acc': acc,
        }

    def _stationary_support_output(self, step_index):
        plan = self.footstep_planner.plan
        support_pos = plan[step_index]['pos']
        support_ang = plan[step_index]['ang']
        zero = np.zeros(6)
        return {
            'pos': np.hstack((support_ang, support_pos)),
            'vel': zero.copy(),
            'acc': zero.copy(),
        }

    def _double_support_output(self, step_index):
        plan = self.footstep_planner.plan
        support_foot = plan[step_index]['foot_id']
        swing_foot = 'lfoot' if support_foot == 'rfoot' else 'rfoot'
        support_data = self._stationary_support_output(step_index)

        target_index = min(step_index + 1, len(plan) - 1)
        target_pose = np.hstack((plan[target_index]['ang'], plan[target_index]['pos']))
        zero = np.zeros(6)
        swing_data = {
            'pos': target_pose,
            'vel': zero.copy(),
            'acc': zero.copy(),
        }
        return {
            support_foot: support_data,
            swing_foot: swing_data,
        }

    @staticmethod
    def _quintic_coefficients(p0, v0, a0, pf, vf, af, T):
        p0 = np.asarray(p0, dtype=float)
        v0 = np.asarray(v0, dtype=float)
        a0 = np.asarray(a0, dtype=float)
        pf = np.asarray(pf, dtype=float)
        vf = np.asarray(vf, dtype=float)
        af = np.asarray(af, dtype=float)
        T = float(max(T, 1e-6))

        c0 = p0
        c1 = v0
        c2 = 0.5 * a0

        A = np.array([
            [T**3,      T**4,       T**5],
            [3*T**2,    4*T**3,     5*T**4],
            [6*T,      12*T**2,    20*T**3],
        ], dtype=float)

        rhs = np.vstack([
            (pf - (c0 + c1 * T + c2 * T**2)),
            (vf - (c1 + 2.0 * c2 * T)),
            (af - (2.0 * c2)),
        ])

        c3_to_c5 = np.linalg.solve(A, rhs).T
        coeff = np.column_stack((c0, c1, c2, c3_to_c5[:, 0], c3_to_c5[:, 1], c3_to_c5[:, 2]))
        return coeff

    @staticmethod
    def _evaluate_quintic(coeff, t):
        coeff = np.asarray(coeff, dtype=float)
        t = float(t)
        powers = np.array([1.0, t, t**2, t**3, t**4, t**5], dtype=float)
        d1 = np.array([0.0, 1.0, 2.0*t, 3.0*t**2, 4.0*t**3, 5.0*t**4], dtype=float)
        d2 = np.array([0.0, 0.0, 2.0, 6.0*t, 12.0*t**2, 20.0*t**3], dtype=float)
        pos = coeff @ powers
        vel = coeff @ d1
        acc = coeff @ d2
        return pos, vel, acc
