import numpy as np

from utils import QPSolver


class StepTimingAdapter:
    IDX_DX = 0
    IDX_DY = 1
    IDX_TAU = 2
    IDX_BX = 3
    IDX_BY = 4
    IDX_SX = 5
    IDX_SY = 6

    def __init__(self, footstep_planner, params):
        self.footstep_planner = footstep_planner
        self.params = params
        self.delta = float(params['world_time_step'])
        self.eta = float(params['eta'])
        self.enabled = bool(params.get('use_step_timing_adaptation', False))

        self.debug = bool(params.get('adapt_debug', False))
        self.debug_every = max(1, int(params.get('adapt_debug_every', 5)))
        self.debug_reasons = bool(params.get('adapt_debug_reasons', True))

        self.qp = QPSolver(n_vars=7, n_eq_constraints=2, n_ineq_constraints=16)

        self.last_step_index = None
        self.last_event = None
        self.stats = {
            'updates': 0,
            'activations': 0,
            'qp_failures': 0,
            'max_dcm_error': 0.0,
            'last_update_tick': None,
        }

    def reset(self):
        self.last_step_index = None
        self.last_event = None
        self.stats = {
            'updates': 0,
            'activations': 0,
            'qp_failures': 0,
            'max_dcm_error': 0.0,
            'last_update_tick': None,
        }

    def compute_dcm(self, current):
        return current['com']['pos'][:2] + current['com']['vel'][:2] / self.eta

    def _should_print(self, time_tick):
        if not self.debug:
            return False
        return (int(time_tick) % self.debug_every) == 0

    def _dbg(self, msg, time_tick=None, force=False):
        if not self.debug:
            return
        if force or time_tick is None or self._should_print(time_tick):
            print(msg)

    def maybe_adapt(self, current, desired, time_tick):
        self.last_event = None

        if not self.enabled:
            return None

        step_index = self.footstep_planner.get_step_index_at_time(time_tick)
        phase = self.footstep_planner.get_phase_at_time(time_tick)

        if step_index != self.last_step_index:
            self.last_step_index = step_index
            self._dbg(f"[adapt-state] t={int(time_tick):04d} step={step_index} phase={phase}", time_tick, force=True)

        if phase != 'ss':
            if self.debug_reasons:
                self._dbg(f"[adapt-skip] t={int(time_tick):04d} step={step_index} reason=not_single_support phase={phase}", time_tick)
            return None

        if step_index is None or step_index <= 0:
            if self.debug_reasons:
                self._dbg(f"[adapt-skip] t={int(time_tick):04d} step={step_index} reason=invalid_step_index", time_tick)
            return None

        if step_index + 1 >= len(self.footstep_planner):
            if self.debug_reasons:
                self._dbg(f"[adapt-skip] t={int(time_tick):04d} step={step_index} reason=no_next_step", time_tick)
            return None

        current_step = self.footstep_planner.get_step(step_index)
        current_ss = int(current_step['ss_duration'])
        time_in_step_ticks = int(self.footstep_planner.get_time_in_step(time_tick))
        remaining_ticks = current_ss - time_in_step_ticks

        freeze_ticks = int(self.params.get('adapt_freeze_ticks', 6))
        if remaining_ticks <= freeze_ticks:
            if self.debug_reasons:
                self._dbg(
                    f"[adapt-skip] t={int(time_tick):04d} step={step_index} reason=freeze_window "
                    f"remaining={remaining_ticks} freeze={freeze_ticks}",
                    time_tick
                )
            return None

        warmup_ticks = int(self.params.get('adapt_warmup_ticks', 20))
        if time_in_step_ticks < warmup_ticks:
            if self.debug_reasons:
                self._dbg(
                    f"[adapt-skip] t={int(time_tick):04d} step={step_index} reason=warmup "
                    f"time_in_step={time_in_step_ticks} warmup={warmup_ticks}",
                    time_tick
                )
            return None

        cooldown_ticks = int(self.params.get('adapt_cooldown_ticks', 8))
        last_tick = self.stats.get('last_update_tick')
        if last_tick is not None and (int(time_tick) - int(last_tick)) < cooldown_ticks:
            if self.debug_reasons:
                self._dbg(
                    f"[adapt-skip] t={int(time_tick):04d} step={step_index} reason=cooldown "
                    f"dt={int(time_tick) - int(last_tick)} cooldown={cooldown_ticks}",
                    time_tick
                )
            return None

        support = self.footstep_planner.get_step(step_index)
        target_active = self.footstep_planner.get_step(step_index + 1)
        target_nominal = self.footstep_planner.get_step(step_index + 1, use_nominal=True)

        u0 = np.asarray(support['pos'][:2], dtype=float)
        rot = self.footstep_planner.get_support_rotation(step_index)

        dcm_world = self.compute_dcm(current)
        dcm_local = rot.T @ (dcm_world - u0)

        elapsed = max(time_in_step_ticks * self.delta, 0.0)

        tau_nom = self._ss_ticks_to_tau(
            self.footstep_planner.get_step(step_index, use_nominal=True)['ss_duration']
        )
        d_nom = self.footstep_planner.get_next_step_displacement_local(
            step_index, use_nominal=True
        )

        coeff_local = dcm_local * np.exp(-self.eta * elapsed)
        b_nom = self._nominal_offset(d_nom, tau_nom)
        b_if_nom = coeff_local * tau_nom - d_nom

        desired_dcm = desired['com']['pos'][:2] + desired['com']['vel'][:2] / self.eta
        dcm_error = float(np.linalg.norm(dcm_world - desired_dcm))
        self.stats['max_dcm_error'] = max(self.stats['max_dcm_error'], dcm_error)

        bounds = self._compute_step_bounds(step_index, d_nom)
        viability = self._compute_viability_bounds(bounds)

        margin = min(
            viability['bx_max'] - abs(b_if_nom[0]),
            viability['by_max'] - abs(b_if_nom[1]),
        )

        err_thr = float(self.params.get('adapt_dcm_error_threshold', 0.03))
        margin_thr = float(self.params.get('adapt_viability_margin', 0.02))
        margin_err_gate = float(self.params.get('adapt_margin_error_gate', 0.015))

        should_activate = (
            dcm_error >= err_thr
            or (margin <= -margin_thr and dcm_error >= margin_err_gate)
        )

        self._dbg(
            f"[adapt-check] t={int(time_tick):04d} step={step_index} "
            f"err={dcm_error:.4f} err_thr={err_thr:.4f} "
            f"margin={margin:.4f} margin_thr={margin_thr:.4f} "
            f"gate_err={margin_err_gate:.4f} activate={should_activate}",
            time_tick
        )

        if not should_activate:
            if self.debug_reasons:
                self._dbg(
                    f"[adapt-skip] t={int(time_tick):04d} step={step_index} reason=below_activation_threshold",
                    time_tick
                )
            return None

        self.stats['activations'] += 1
        self._dbg(
            f"[adapt-enter] t={int(time_tick):04d} step={step_index} "
            f"err={dcm_error:.4f} margin={margin:.4f}",
            time_tick,
            force=True
        )

        solution = self._solve_qp(coeff_local, d_nom, tau_nom, bounds, viability)
        if solution is None:
            self.stats['qp_failures'] += 1
            self._dbg(
                f"[adapt-qpfail] t={int(time_tick):04d} step={step_index}",
                time_tick,
                force=True
            )
            return None

        dx = float(solution[self.IDX_DX])
        dy = float(solution[self.IDX_DY])
        tau = float(solution[self.IDX_TAU])
        sx = float(solution[self.IDX_SX])
        sy = float(solution[self.IDX_SY])

        if not np.isfinite([dx, dy, tau, sx, sy]).all():
            self.stats['qp_failures'] += 1
            self._dbg(
                f"[adapt-qpfail] t={int(time_tick):04d} step={step_index} reason=nonfinite_solution",
                time_tick,
                force=True
            )
            return None

        proposed_ss = self._tau_to_ss_ticks(tau)

        gap_ticks = int(self.params.get('T_gap_ticks', 12))
        if proposed_ss < time_in_step_ticks + gap_ticks:
            self._dbg(
                f"[adapt-reject] t={int(time_tick):04d} step={step_index} "
                f"reason=T_gap proposed_ss={proposed_ss} "
                f"time_in_step={time_in_step_ticks} gap={gap_ticks}",
                time_tick,
                force=True
            )
            return None

        current_target_world = np.asarray(target_active['pos'][:2], dtype=float)
        proposed_target_world = self.footstep_planner.local_to_world(
            step_index,
            np.array([dx, dy], dtype=float),
            z_value=target_nominal['pos'][2],
        )

        position_change = float(np.linalg.norm(proposed_target_world[:2] - current_target_world))
        timing_change = abs(proposed_ss - current_ss)

        if (
            timing_change < int(self.params.get('min_timing_update_ticks', 1))
            and position_change < float(self.params.get('min_step_update', 0.005))
        ):
            self._dbg(
                f"[adapt-reject] t={int(time_tick):04d} step={step_index} "
                f"reason=tiny_update dss={timing_change} dpos={position_change:.4f}",
                time_tick,
                force=True
            )
            return None

        self.footstep_planner.update_step(step_index, ss_duration=proposed_ss)
        self.footstep_planner.update_step(
            step_index + 1,
            pos=proposed_target_world,
            ang=target_nominal['ang'],
        )

        self.stats['updates'] += 1
        self.stats['last_update_tick'] = int(time_tick)

        self.last_event = {
            'step_index': int(step_index),
            'time_tick': int(time_tick),
            'dcm_error': dcm_error,
            'margin': float(margin),
            'ss_before': int(current_ss),
            'ss_after': int(proposed_ss),
            'target_before_world': current_target_world.copy(),
            'target_after_world': np.asarray(proposed_target_world[:2]).copy(),
            'local_target_after': np.array([dx, dy], dtype=float),
            'slack_x': sx,
            'slack_y': sy,
        }

        self._dbg(
            f"[adapter] t={int(time_tick):04d} step={step_index} "
            f"err={dcm_error:.4f} margin={margin:.4f} "
            f"ss:{current_ss}->{proposed_ss} "
            f"xy:({current_target_world[0]:.3f},{current_target_world[1]:.3f})->"
            f"({proposed_target_world[0]:.3f},{proposed_target_world[1]:.3f}) "
            f"slack=({sx:.4e},{sy:.4e})",
            time_tick,
            force=True
        )

        return self.last_event

    def _solve_qp(self, coeff_local, d_nom, tau_nom, bounds, viability):
        alpha_step = float(self.params.get('adapt_alpha_step', 1.0))
        alpha_time = float(self.params.get('adapt_alpha_time', 5.0))
        alpha_offset = float(self.params.get('adapt_alpha_offset', 1000.0))
        alpha_slack = float(self.params.get('adapt_alpha_slack', 1e6))

        b_nom = self._nominal_offset(d_nom, tau_nom)

        H = np.zeros((7, 7), dtype=float)
        F = np.zeros(7, dtype=float)

        for idx, ref, weight in [
            (self.IDX_DX, d_nom[0], alpha_step),
            (self.IDX_DY, d_nom[1], alpha_step),
            (self.IDX_TAU, tau_nom, alpha_time),
            (self.IDX_BX, b_nom[0], alpha_offset),
            (self.IDX_BY, b_nom[1], alpha_offset),
        ]:
            H[idx, idx] = 2.0 * weight
            F[idx] = -2.0 * weight * ref

        H[self.IDX_SX, self.IDX_SX] = 2.0 * alpha_slack
        H[self.IDX_SY, self.IDX_SY] = 2.0 * alpha_slack

        A_eq = np.zeros((2, 7), dtype=float)
        b_eq = np.zeros(2, dtype=float)

        A_eq[0, self.IDX_DX] = 1.0
        A_eq[0, self.IDX_BX] = 1.0
        A_eq[0, self.IDX_TAU] = -coeff_local[0]

        A_eq[1, self.IDX_DY] = 1.0
        A_eq[1, self.IDX_BY] = 1.0
        A_eq[1, self.IDX_TAU] = -coeff_local[1]

        A_ineq = []
        b_ineq = []

        A_ineq.append(self._row(self.IDX_DX, 1.0));  b_ineq.append(bounds['dx_max'])
        A_ineq.append(self._row(self.IDX_DX, -1.0)); b_ineq.append(-bounds['dx_min'])
        A_ineq.append(self._row(self.IDX_DY, 1.0));  b_ineq.append(bounds['dy_max'])
        A_ineq.append(self._row(self.IDX_DY, -1.0)); b_ineq.append(-bounds['dy_min'])

        A_ineq.append(self._row(self.IDX_TAU, 1.0));  b_ineq.append(bounds['tau_max'])
        A_ineq.append(self._row(self.IDX_TAU, -1.0)); b_ineq.append(-bounds['tau_min'])

        row = np.zeros(7); row[self.IDX_BX] = 1.0; row[self.IDX_SX] = -1.0
        A_ineq.append(row); b_ineq.append(viability['bx_max'])

        row = np.zeros(7); row[self.IDX_BX] = -1.0; row[self.IDX_SX] = -1.0
        A_ineq.append(row); b_ineq.append(viability['bx_max'])

        row = np.zeros(7); row[self.IDX_BY] = 1.0; row[self.IDX_SY] = -1.0
        A_ineq.append(row); b_ineq.append(viability['by_max'])

        row = np.zeros(7); row[self.IDX_BY] = -1.0; row[self.IDX_SY] = -1.0
        A_ineq.append(row); b_ineq.append(viability['by_max'])

        A_ineq.append(self._row(self.IDX_SX, -1.0)); b_ineq.append(0.0)
        A_ineq.append(self._row(self.IDX_SY, -1.0)); b_ineq.append(0.0)

        A_ineq.append(self._row(self.IDX_BX, 1.0));  b_ineq.append(3.0 * viability['bx_max'])
        A_ineq.append(self._row(self.IDX_BX, -1.0)); b_ineq.append(3.0 * viability['bx_max'])
        A_ineq.append(self._row(self.IDX_BY, 1.0));  b_ineq.append(3.0 * viability['by_max'])
        A_ineq.append(self._row(self.IDX_BY, -1.0)); b_ineq.append(3.0 * viability['by_max'])

        A_ineq = np.asarray(A_ineq, dtype=float)
        b_ineq = np.asarray(b_ineq, dtype=float)

        self.qp.set_values(H, F, A_eq=A_eq, b_eq=b_eq, A_ineq=A_ineq, b_ineq=b_ineq)
        solution = self.qp.solve()

        if solution is None:
            return None
        if np.linalg.norm(solution) == 0.0 and np.linalg.norm(F) > 0.0:
            return None

        return solution

    @staticmethod
    def _row(index, value):
        row = np.zeros(7, dtype=float)
        row[index] = value
        return row

    def _nominal_offset(self, d_nom, tau_nom):
        denom = max(tau_nom - 1.0, 1e-6)
        return np.asarray(d_nom, dtype=float) / denom

    def _ss_ticks_to_tau(self, ss_ticks):
        return float(np.exp(self.eta * max(int(ss_ticks), 1) * self.delta))

    def _tau_to_ss_ticks(self, tau):
        tau = max(float(tau), 1.0 + 1e-6)
        duration = np.log(tau) / self.eta
        return max(1, int(round(duration / self.delta)))

    def _compute_step_bounds(self, step_index, d_nom):
        forward_margin = float(self.params.get('step_length_forward_margin', 0.08))
        backward_margin = float(self.params.get('step_length_backward_margin', 0.03))
        outward_margin = float(self.params.get('step_width_outward_margin', 0.03))
        inward_margin = float(self.params.get('step_width_inward_margin', 0.02))
        cross_margin = float(self.params.get('cross_margin', 0.03))

        support_foot = self.footstep_planner.get_step(step_index)['foot_id']

        dx_min = float(d_nom[0] - backward_margin)
        dx_max = float(d_nom[0] + forward_margin)

        if support_foot == 'lfoot':
            dy_min = float(d_nom[1] - outward_margin)
            dy_max = float(min(d_nom[1] + inward_margin, -cross_margin))
        else:
            dy_min = float(max(d_nom[1] - inward_margin, cross_margin))
            dy_max = float(d_nom[1] + outward_margin)

        t_nom_ticks = int(self.footstep_planner.get_step(step_index, use_nominal=True)['ss_duration'])
        t_min_ticks = int(self.params.get('T_min_ticks', max(20, t_nom_ticks - 15)))
        t_max_ticks = int(self.params.get('T_max_ticks', t_nom_ticks + 12))
        t_min_ticks = max(1, t_min_ticks)
        t_max_ticks = max(t_min_ticks, t_max_ticks)

        return {
            'dx_min': dx_min,
            'dx_max': dx_max,
            'dy_min': dy_min,
            'dy_max': dy_max,
            'tau_min': self._ss_ticks_to_tau(t_min_ticks),
            'tau_max': self._ss_ticks_to_tau(t_max_ticks),
        }

    def _compute_viability_bounds(self, bounds):
        tau_min = max(bounds['tau_min'], 1.0 + 1e-6)
        denom = max(tau_min - 1.0, 1e-6)

        bx_max = max(abs(bounds['dx_min']), abs(bounds['dx_max'])) / denom
        by_max = max(abs(bounds['dy_min']), abs(bounds['dy_max'])) / denom

        return {
            'bx_max': float(max(bx_max, 1e-3)),
            'by_max': float(max(by_max, 1e-3)),
        }