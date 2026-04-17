import argparse
import copy
import os

import dartpy as dart
import numpy as np

import filter
import foot_trajectory_generator as ftg
import footstep_planner
import inverse_dynamics as id
import ismpc
from logger import Logger
from step_timing_adapter import StepTimingAdapter
from utils import *
import json
from datetime import datetime


def build_reference(profile: str):
    if profile == 'inplace':
        return [(0.0, 0.0, 0.0)] * 25
    if profile == 'forward':
        return [(0.2, 0.0, 0.0)] * 25
    if profile == 'scianca':
        return [(0.1, 0.0, 0.2)] * 5 + [(0.1, 0.0, -0.1)] * 10 + [(0.1, 0.0, 0.0)] * 10
    raise ValueError(f"Unknown profile: {profile}")

class Hrp4Controller(dart.gui.osg.RealTimeWorldNode):
    def __init__(self, world, hrp4, args=None):
        super(Hrp4Controller, self).__init__(world)
        self.world = world
        self.hrp4 = hrp4
        self.args = args or argparse.Namespace()
        self.time = 0
        self.finished = False
        self.fall_detected = False
        self.last_contact = 'ds'
        self.adapter_trace = []

        self.params = {
            'g': 9.81,
            'h': 0.72,
            'foot_size': 0.1,
            'step_height': 0.02,
            'ss_duration': 70,
            'ds_duration': 30,
            'world_time_step': world.getTimeStep(),
            'first_swing': 'rfoot',
            'µ': 0.5,
            'N': 100,
            'dof': self.hrp4.getNumDofs(),
            # Reactive layer parameters.
            'use_step_timing_adaptation': bool(getattr(self.args, 'adapt', False)),
            'adapt_dcm_error_threshold': 0.003,
            'adapt_viability_margin': 0.02,
            'adapt_margin_error_gate': 0.002,
            'adapt_alpha_step': 1.0,
            'adapt_alpha_time': 5.0,
            'adapt_alpha_offset': 50.0,
            'adapt_alpha_slack': 1e4,
            'adapt_debug': True,
            'adapt_debug_every': 5,
            'adapt_debug_reasons': True,
            'T_gap_ticks': 16,
            'adapt_freeze_ticks': 8,
            'adapt_warmup_ticks': 15,
            'adapt_cooldown_ticks': 10,
            'min_timing_update_ticks': 2,
            'min_step_update': 0.01,
            'step_length_forward_margin': 0.15,
            'step_length_backward_margin': 0.08,
            'step_width_outward_margin': 0.10,
            'step_width_inward_margin': 0.05,
            'cross_margin': 0.01,
            'T_min_ticks': 40,
            'T_max_ticks': 100,
        }
        self.params['eta'] = np.sqrt(self.params['g'] / self.params['h'])

        # Robot links.
        self.lsole = hrp4.getBodyNode('l_sole')
        self.rsole = hrp4.getBodyNode('r_sole')
        self.torso = hrp4.getBodyNode('torso')
        self.base = hrp4.getBodyNode('body')

        for i in range(hrp4.getNumJoints()):
            joint = hrp4.getJoint(i)
            dim = joint.getNumDofs()
            if dim == 6:
                joint.setActuatorType(dart.dynamics.ActuatorType.PASSIVE)
            elif dim == 1:
                joint.setActuatorType(dart.dynamics.ActuatorType.FORCE)

        self._set_initial_configuration()
        self._place_robot_on_ground()


        self.initial = self.retrieve_state()
        self.contact = 'lfoot' if self.params['first_swing'] == 'rfoot' else 'rfoot'
        self.desired = copy.deepcopy(self.initial)
        self.current = copy.deepcopy(self.initial)

        redundant_dofs = [
            "NECK_Y", "NECK_P",
            "R_SHOULDER_P", "R_SHOULDER_R", "R_SHOULDER_Y", "R_ELBOW_P",
            "L_SHOULDER_P", "L_SHOULDER_R", "L_SHOULDER_Y", "L_ELBOW_P",
        ]

        self.id = id.InverseDynamics(self.hrp4, redundant_dofs)

        #stepping in place: 
        #reference = [(0.0, 0.0, 0.0)] * 25
        #forward walking
        #reference = [(0.2, 0.0, 0.0)] * 25
        #quella di scianca
        # reference = [(0.1, 0.0, 0.2)] * 5 + [(0.1, 0.0, -0.1)] * 10 + [(0.1, 0.0, 0.0)] * 10
        reference = build_reference(getattr(self.args, 'profile', 'forward'))
        self.footstep_planner = footstep_planner.FootstepPlanner(
            reference,
            self.initial['lfoot']['pos'],
            self.initial['rfoot']['pos'],
            self.params,
        )

        self.step_timing_adapter = StepTimingAdapter(self.footstep_planner, self.params)
        print(f"[init] step_timing_adaptation={self.step_timing_adapter.enabled}")
        print(f"[init] adapt_debug={self.params.get('adapt_debug', False)}")
        self.mpc = ismpc.Ismpc(self.initial, self.footstep_planner, self.params)
        self.foot_trajectory_generator = ftg.FootTrajectoryGenerator(self.initial, self.footstep_planner, self.params)

        A = np.identity(3) + self.params['world_time_step'] * self.mpc.A_lip
        B = self.params['world_time_step'] * self.mpc.B_lip
        d = np.zeros(9)
        d[7] = -self.params['world_time_step'] * self.params['g']
        H = np.identity(3)
        Q = block_diag(1.0, 1.0, 1.0)
        R = block_diag(1e1, 1e2, 1e4)
        P = np.identity(3)
        x = np.array([
            self.initial['com']['pos'][0], self.initial['com']['vel'][0], self.initial['zmp']['pos'][0],
            self.initial['com']['pos'][1], self.initial['com']['vel'][1], self.initial['zmp']['pos'][1],
            self.initial['com']['pos'][2], self.initial['com']['vel'][2], self.initial['zmp']['pos'][2],
        ])
        self.kf = filter.KalmanFilter(
            block_diag(A, A, A),
            block_diag(B, B, B),
            d,
            block_diag(H, H, H),
            block_diag(Q, Q, Q),
            block_diag(R, R, R),
            block_diag(P, P, P),
            x,
        )

        self.logger = Logger(self.initial)
        if not getattr(self.args, 'headless', False):
            self.logger.initialize_plot(frequency=10)

        self.push_start_tick = None
        self.push_end_tick = None
        self.push_force_world = np.zeros(3)
        self.push_target = 'base'

        self.push_force_arrow_shape = None
        self.push_force_simple_frame = None
        self.push_force_visual = None
        self._dart_shape_cls = None

        self.push_visual_start_tick = None
        self.push_visual_end_tick = None
        self.push_visual_duration_ticks = max(
            1, int(round(1.0 / self.params['world_time_step']))
        )

        self._init_push_visual()
        self.push_arrow_length = self   ._estimate_push_arrow_length()

        self._configure_push()
        self._print_plan_summary()
    def _set_initial_configuration(self):
        initial_configuration = {
            'CHEST_P': 0.0, 'CHEST_Y': 0.0, 'NECK_P': 0.0, 'NECK_Y': 0.0,
            'R_HIP_Y': 0.0, 'R_HIP_R': -3.0, 'R_HIP_P': -25.0, 'R_KNEE_P': 50.0, 'R_ANKLE_P': -25.0, 'R_ANKLE_R': 3.0,
            'L_HIP_Y': 0.0, 'L_HIP_R': 3.0, 'L_HIP_P': -25.0, 'L_KNEE_P': 50.0, 'L_ANKLE_P': -25.0, 'L_ANKLE_R': -3.0,
            'R_SHOULDER_P': 4.0, 'R_SHOULDER_R': -8.0, 'R_SHOULDER_Y': 0.0, 'R_ELBOW_P': -25.0,
            'L_SHOULDER_P': 4.0, 'L_SHOULDER_R': 8.0, 'L_SHOULDER_Y': 0.0, 'L_ELBOW_P': -25.0,
        }
        for joint_name, value in initial_configuration.items():
            self.hrp4.setPosition(self.hrp4.getDof(joint_name).getIndexInSkeleton(), value * np.pi / 180.0)

    def _place_robot_on_ground(self):
        lsole_pos = self.lsole.getTransform(
            withRespectTo=dart.dynamics.Frame.World(),
            inCoordinatesOf=dart.dynamics.Frame.World(),
        ).translation()
        rsole_pos = self.rsole.getTransform(
            withRespectTo=dart.dynamics.Frame.World(),
            inCoordinatesOf=dart.dynamics.Frame.World(),
        ).translation()
        self.hrp4.setPosition(3, -(lsole_pos[0] + rsole_pos[0]) / 2.0)
        self.hrp4.setPosition(4, -(lsole_pos[1] + rsole_pos[1]) / 2.0)
        self.hrp4.setPosition(5, -(lsole_pos[2] + rsole_pos[2]) / 2.0)

    def _configure_push(self):
        force = float(getattr(self.args, 'force', 0.0) or 0.0)
        direction = getattr(self.args, 'direction', 'right')
        duration = float(getattr(self.args, 'duration', 0.05) or 0.05)
        push_time = getattr(self.args, 'push_time', None)
        push_step = getattr(self.args, 'push_step', None)
        push_phase = float(getattr(self.args, 'push_phase', 0.7) or 0.7)
        self.push_target = getattr(self.args, 'push_target', 'base')
        if force <= 0.0:
            return

        direction_map = {
            'left': np.array([0.0, 1.0, 0.0]),
            'right': np.array([0.0, -1.0, 0.0]),
            'forward': np.array([1.0, 0.0, 0.0]),
            'backward': np.array([-1.0, 0.0, 0.0]),
        }
        self.push_force_world = force * direction_map[direction]
        duration_ticks = max(1, int(round(duration / self.params['world_time_step'])))

        if push_time is not None:
            self.push_start_tick = max(0, int(round(float(push_time) / self.params['world_time_step'])))
        elif push_step is not None:
            push_step = int(push_step)
            push_step = int(np.clip(push_step, 0, len(self.footstep_planner.nominal_plan) - 1))
            start = self.footstep_planner.get_start_time(push_step, use_nominal=True)
            ss = self.footstep_planner.get_step(push_step, use_nominal=True)['ss_duration']
            self.push_start_tick = start + int(round(push_phase * max(ss, 1)))
        else:
            self.push_start_tick = None
            return

        self.push_end_tick = self.push_start_tick + duration_ticks
        print(
            f"[push] scheduled {direction} push on {self.push_target}: "
            f"t={self.push_start_tick * self.params['world_time_step']:.2f}s, "
            f"F={force:.1f}N, dt={duration:.2f}s"
        )
    def _get_push_body(self):
        target = getattr(self, 'push_target', 'base')

        if target == 'base':
            return self.base

        if target == 'lfoot':
            return self.lsole

        if target == 'rfoot':
            return self.rsole

        if target == 'stance_foot':
            step_index = self.footstep_planner.get_step_index_at_time(self.time)
            support_foot = self.footstep_planner.get_step(step_index)['foot_id']
            return self.lsole if support_foot == 'lfoot' else self.rsole

        return self.base

    def _init_push_visual(self):
        self.push_force_arrow_shape = None
        self.push_force_simple_frame = None
        self.push_force_visual = None
        self._dart_shape_cls = None

        if getattr(self.args, 'headless', False):
            return

        arrow_cls = getattr(dart, 'ArrowShape', None)
        if arrow_cls is None:
            arrow_cls = getattr(dart.dynamics, 'ArrowShape', None)

        frame_cls = getattr(dart, 'SimpleFrame', None)
        if frame_cls is None:
            frame_cls = getattr(dart.dynamics, 'SimpleFrame', None)

        shape_cls = getattr(dart, 'Shape', None)
        if shape_cls is None:
            shape_cls = getattr(dart.dynamics, 'Shape', None)

        if arrow_cls is None or frame_cls is None:
            if not getattr(self.args, 'quiet', False):
                print('[push-visual] ArrowShape/SimpleFrame not available in this dartpy build')
            return

        try:
            self.push_force_arrow_shape = arrow_cls([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
            self.push_force_simple_frame = frame_cls()
            self.push_force_simple_frame.setShape(self.push_force_arrow_shape)

            self.push_force_visual = self.push_force_simple_frame.createVisualAspect()
            self.push_force_visual.setColor([1.0, 0.0, 0.0])
            self.push_force_visual.hide()

            self._dart_shape_cls = shape_cls
            self.world.addSimpleFrame(self.push_force_simple_frame)

        except Exception as e:
            self.push_force_arrow_shape = None
            self.push_force_simple_frame = None
            self.push_force_visual = None
            self._dart_shape_cls = None
            if not getattr(self.args, 'quiet', False):
                print(f'[push-visual] disabled: {e}')
    def _estimate_push_arrow_length(self):
        try:
            torso_tf = self.torso.getTransform(
                withRespectTo=dart.dynamics.Frame.World(),
                inCoordinatesOf=dart.dynamics.Frame.World(),
            )
            lsole_tf = self.lsole.getTransform(
                withRespectTo=dart.dynamics.Frame.World(),
                inCoordinatesOf=dart.dynamics.Frame.World(),
            )
            rsole_tf = self.rsole.getTransform(
                withRespectTo=dart.dynamics.Frame.World(),
                inCoordinatesOf=dart.dynamics.Frame.World(),
            )

            torso_pos = np.asarray(torso_tf.translation(), dtype=float)
            feet_mid = 0.5 * (
                np.asarray(lsole_tf.translation(), dtype=float) +
                np.asarray(rsole_tf.translation(), dtype=float)
            )

            robot_height = float(np.linalg.norm(torso_pos - feet_mid))
            return max(0.25, 0.5 * robot_height)

        except Exception:
            return 0.45

    def _update_push_visual(self):
        if self.push_force_arrow_shape is None or self.push_force_visual is None:
            return

        show_visual = (
            self.push_visual_start_tick is not None
            and self.push_visual_end_tick is not None
            and self.push_visual_start_tick <= self.time < self.push_visual_end_tick
            and float(np.linalg.norm(self.push_force_world)) > 0.0
        )

        if not show_visual:
            try:
                if self._dart_shape_cls is not None and hasattr(self._dart_shape_cls, 'STATIC'):
                    self.push_force_arrow_shape.setDataVariance(self._dart_shape_cls.STATIC)
                self.push_force_visual.hide()
            except Exception:
                pass
            return

        push_body = self._get_push_body()
        body_tf = push_body.getTransform(
            withRespectTo=dart.dynamics.Frame.World(),
            inCoordinatesOf=dart.dynamics.Frame.World(),
        )

        arrow_tail = np.asarray(body_tf.translation(), dtype=float).copy()

        if push_body == self.base:
            arrow_tail[2] += 0.20
        else:
            arrow_tail[2] += 0.05

        force_norm = float(np.linalg.norm(self.push_force_world))
        arrow_dir = self.push_force_world / max(force_norm, 1e-9)

        # lunghezza fissa: circa metà robot
        arrow_length = self.push_arrow_length
        arrow_head = arrow_tail + arrow_dir * arrow_length

        self.push_force_arrow_shape.setPositions(arrow_tail, arrow_head)

        try:
            if self._dart_shape_cls is not None and hasattr(self._dart_shape_cls, 'DYNAMIC'):
                self.push_force_arrow_shape.setDataVariance(self._dart_shape_cls.DYNAMIC)
        except Exception:
            pass

        self.push_force_visual.show()
    def _print_plan_summary(self):
        if getattr(self.args, 'quiet', False):
            return
        print('[plan summary]')
        for i, step in enumerate(self.footstep_planner.nominal_plan):
            start = self.footstep_planner.get_start_time(i, use_nominal=True) * self.params['world_time_step']
            ss_end = (self.footstep_planner.get_start_time(i, use_nominal=True) + step['ss_duration']) * self.params['world_time_step']
            ds_end = (
                self.footstep_planner.get_start_time(i, use_nominal=True) + step['ss_duration'] + step['ds_duration']
            ) * self.params['world_time_step']
            print(
                f"  step={i:02d} support={step['foot_id']} start={start:.2f}s "
                f"ss_end={ss_end:.2f}s ds_end={ds_end:.2f}s "
                f"ss={step['ss_duration']} ds={step['ds_duration']}"
            )

    def customPreStep(self):
        self.step_controller()

    def step_controller(self):
        if self.finished:
            return

        self.current = self.retrieve_state()

        u = np.array([
            self.desired['zmp']['vel'][0],
            self.desired['zmp']['vel'][1],
            self.desired['zmp']['vel'][2],
        ])
        self.kf.predict(u)
        x_flt, _ = self.kf.update(np.array([
            self.current['com']['pos'][0], self.current['com']['vel'][0], self.current['zmp']['pos'][0],
            self.current['com']['pos'][1], self.current['com']['vel'][1], self.current['zmp']['pos'][1],
            self.current['com']['pos'][2], self.current['com']['vel'][2], self.current['zmp']['pos'][2],
        ]))

        self.current['com']['pos'][0] = x_flt[0]
        self.current['com']['vel'][0] = x_flt[1]
        self.current['zmp']['pos'][0] = x_flt[2]
        self.current['com']['pos'][1] = x_flt[3]
        self.current['com']['vel'][1] = x_flt[4]
        self.current['zmp']['pos'][1] = x_flt[5]
        self.current['com']['pos'][2] = x_flt[6]
        self.current['com']['vel'][2] = x_flt[7]
        self.current['zmp']['pos'][2] = x_flt[8]

        adapter_event = self.step_timing_adapter.maybe_adapt(self.current, self.desired, self.time)
        trace_row = {
            'tick': int(self.time),
            'time_s': float(self.time * self.params['world_time_step']),
            'push_active': bool(
                self.push_start_tick is not None
                and self.push_start_tick <= self.time < self.push_end_tick
            ),
            'adapter_updated': bool(adapter_event is not None),
            'step_index': None,
            'dcm_error': None,
            'margin': None,
            'ss_before': None,
            'ss_after': None,
            'target_before_x': None,
            'target_before_y': None,
            'target_after_x': None,
            'target_after_y': None,
        }

        if adapter_event is not None:
            trace_row['step_index'] = int(adapter_event['step_index'])
            trace_row['dcm_error'] = float(adapter_event['dcm_error'])
            trace_row['margin'] = float(adapter_event['margin'])
            trace_row['ss_before'] = int(adapter_event['ss_before'])
            trace_row['ss_after'] = int(adapter_event['ss_after'])
            trace_row['target_before_x'] = float(adapter_event['target_before_world'][0])
            trace_row['target_before_y'] = float(adapter_event['target_before_world'][1])
            trace_row['target_after_x'] = float(adapter_event['target_after_world'][0])
            trace_row['target_after_y'] = float(adapter_event['target_after_world'][1])

        self.adapter_trace.append(trace_row)
        if adapter_event is not None and not getattr(self.args, 'quiet', False):
            before_xy = adapter_event['target_before_world']
            after_xy = adapter_event['target_after_world']
            print(
                f"[adapter] t={self.time:04d} step={adapter_event['step_index']} "
                f"err={adapter_event['dcm_error']:.4f} margin={adapter_event['margin']:.4f} "
                f"ss:{adapter_event['ss_before']}->{adapter_event['ss_after']} "
                f"xy:({before_xy[0]:.3f},{before_xy[1]:.3f})->({after_xy[0]:.3f},{after_xy[1]:.3f})"
            )

        lip_state, contact = self.mpc.solve(self.current, self.time)
        self.last_contact = contact

        self.desired['com']['pos'] = lip_state['com']['pos']
        self.desired['com']['vel'] = lip_state['com']['vel']
        self.desired['com']['acc'] = lip_state['com']['acc']
        self.desired['zmp']['pos'] = lip_state['zmp']['pos']
        self.desired['zmp']['vel'] = lip_state['zmp']['vel']

        feet_trajectories = self.foot_trajectory_generator.generate_feet_trajectories_at_time(self.time, current=self.current)
        for foot in ['lfoot', 'rfoot']:
            for key in ['pos', 'vel', 'acc']:
                self.desired[foot][key] = feet_trajectories[foot][key]

        for link in ['torso', 'base']:
            for key in ['pos', 'vel', 'acc']:
                self.desired[link][key] = (
                    self.desired['lfoot'][key][:3] + self.desired['rfoot'][key][:3]
                ) / 2.0

        commands = self.id.get_joint_torques(self.desired, self.current, contact)
        for i in range(self.params['dof'] - 6):
            self.hrp4.setCommand(i + 6, commands[i])

        
        self._apply_push_if_needed()
        self._update_push_visual()
        self.logger.log_data(self.desired, self.current)
        if not getattr(self.args, 'headless', False):
            # self.logger.update_plot(self.time)
            pass

        self.time += 1
        self.fall_detected = self.has_fallen()

        if self.time >= self.footstep_planner.get_total_duration() - 1:
            self.finished = True

    def _apply_push_if_needed(self):
        if self.push_start_tick is None:
            return
        if not (self.push_start_tick <= self.time < self.push_end_tick):
            if self.time == self.push_end_tick and not getattr(self.args, 'quiet', False):
                print(f"[push] finished at t={self.time * self.params['world_time_step']:.2f}s")
            return

        force = self.push_force_world
        body = self._get_push_body()
        offset = np.zeros(3)

        applied = False
        for call in (
            lambda: body.addExtForce(force),
            lambda: body.addExtForce(force, offset),
            lambda: body.addExtForce(force, offset, False, False),
            lambda: body.setExtForce(force),
            lambda: body.setExtForce(force, offset),
            lambda: body.setExtForce(force, offset, False, False),
        ):
            try:
                call()
                applied = True
                break
            except Exception:
                continue

        if self.time == self.push_start_tick and applied:
            self.push_visual_start_tick = int(self.time)
            self.push_visual_end_tick = int(self.time) + self.push_visual_duration_ticks

            if not getattr(self.args, 'quiet', False):
                print(f"[push] started at t={self.time * self.params['world_time_step']:.2f}s")
    def has_fallen(self):
        state = self.retrieve_state()
        com_z = float(state['com']['pos'][2])
        base_tilt = float(np.linalg.norm(state['base']['pos'][:2]))
        if not np.isfinite(com_z) or not np.isfinite(base_tilt):
            return True
        if com_z < 0.40:
            return True
        if base_tilt > 0.9:
            return True
        return False

    def retrieve_state(self):
        com_position = self.hrp4.getCOM()
        torso_orientation = get_rotvec(
            self.hrp4.getBodyNode('torso').getTransform(
                withRespectTo=dart.dynamics.Frame.World(),
                inCoordinatesOf=dart.dynamics.Frame.World(),
            ).rotation()
        )
        base_orientation = get_rotvec(
            self.hrp4.getBodyNode('body').getTransform(
                withRespectTo=dart.dynamics.Frame.World(),
                inCoordinatesOf=dart.dynamics.Frame.World(),
            ).rotation()
        )

        l_foot_transform = self.lsole.getTransform(
            withRespectTo=dart.dynamics.Frame.World(),
            inCoordinatesOf=dart.dynamics.Frame.World(),
        )
        l_foot_orientation = get_rotvec(l_foot_transform.rotation())
        l_foot_position = l_foot_transform.translation()
        left_foot_pose = np.hstack((l_foot_orientation, l_foot_position))

        r_foot_transform = self.rsole.getTransform(
            withRespectTo=dart.dynamics.Frame.World(),
            inCoordinatesOf=dart.dynamics.Frame.World(),
        )
        r_foot_orientation = get_rotvec(r_foot_transform.rotation())
        r_foot_position = r_foot_transform.translation()
        right_foot_pose = np.hstack((r_foot_orientation, r_foot_position))

        com_velocity = self.hrp4.getCOMLinearVelocity(
            relativeTo=dart.dynamics.Frame.World(),
            inCoordinatesOf=dart.dynamics.Frame.World(),
        )
        torso_angular_velocity = self.hrp4.getBodyNode('torso').getAngularVelocity(
            relativeTo=dart.dynamics.Frame.World(),
            inCoordinatesOf=dart.dynamics.Frame.World(),
        )
        base_angular_velocity = self.hrp4.getBodyNode('body').getAngularVelocity(
            relativeTo=dart.dynamics.Frame.World(),
            inCoordinatesOf=dart.dynamics.Frame.World(),
        )
        l_foot_spatial_velocity = self.lsole.getSpatialVelocity(
            relativeTo=dart.dynamics.Frame.World(),
            inCoordinatesOf=dart.dynamics.Frame.World(),
        )
        r_foot_spatial_velocity = self.rsole.getSpatialVelocity(
            relativeTo=dart.dynamics.Frame.World(),
            inCoordinatesOf=dart.dynamics.Frame.World(),
        )

        force = np.zeros(3)
        contacts = self.world.getLastCollisionResult().getContacts()
        for contact in contacts:
            force += contact.force

        zmp = np.zeros(3)
        if force[2] > 0.1:
            zmp[2] = com_position[2] - force[2] / (self.hrp4.getMass() * self.params['g'] / self.params['h'])
            for contact in contacts:
                if contact.force[2] <= 0.1:
                    continue
                zmp[0] += contact.point[0] * contact.force[2] / force[2] + (zmp[2] - contact.point[2]) * contact.force[0] / force[2]
                zmp[1] += contact.point[1] * contact.force[2] / force[2] + (zmp[2] - contact.point[2]) * contact.force[1] / force[2]

            midpoint = (l_foot_position + r_foot_position) / 2.0
            zmp[0] = np.clip(zmp[0], midpoint[0] - 0.3, midpoint[0] + 0.3)
            zmp[1] = np.clip(zmp[1], midpoint[1] - 0.3, midpoint[1] + 0.3)
            zmp[2] = np.clip(zmp[2], midpoint[2] - 0.3, midpoint[2] + 0.3)
        else:
            zmp[:] = 0.0

        return {
            'lfoot': {'pos': left_foot_pose, 'vel': l_foot_spatial_velocity, 'acc': np.zeros(6)},
            'rfoot': {'pos': right_foot_pose, 'vel': r_foot_spatial_velocity, 'acc': np.zeros(6)},
            'com': {'pos': com_position, 'vel': com_velocity, 'acc': np.zeros(3)},
            'torso': {'pos': torso_orientation, 'vel': torso_angular_velocity, 'acc': np.zeros(3)},
            'base': {'pos': base_orientation, 'vel': base_angular_velocity, 'acc': np.zeros(3)},
            'joint': {'pos': self.hrp4.getPositions(), 'vel': self.hrp4.getVelocities(), 'acc': np.zeros(self.params['dof'])},
            'zmp': {'pos': zmp, 'vel': np.zeros(3), 'acc': np.zeros(3)},
        }

   
    def get_summary(self):
        return {
            'ticks': int(self.time),
            'sim_time_s': float(self.time * self.params['world_time_step']),
            'fell': bool(self.fall_detected),
            'last_contact': self.last_contact,
            'adapter': self.step_timing_adapter.stats,
            'trace': self.adapter_trace,
            'push_window': {
                'start_tick': self.push_start_tick,
                'end_tick': self.push_end_tick,
                'dt': float(self.params['world_time_step']),
            },
            'tuning_params': {
                'adapt_dcm_error_threshold': self.params['adapt_dcm_error_threshold'],
                'adapt_margin_error_gate': self.params['adapt_margin_error_gate'],
                'adapt_cooldown_ticks': self.params['adapt_cooldown_ticks'],
                'adapt_warmup_ticks': self.params['adapt_warmup_ticks'],
                'adapt_freeze_ticks': self.params['adapt_freeze_ticks'],
                'T_gap_ticks': self.params['T_gap_ticks'],
                'min_timing_update_ticks': self.params['min_timing_update_ticks'],
                'min_step_update': self.params['min_step_update'],
                'adapt_alpha_time': self.params['adapt_alpha_time'],
                'adapt_alpha_offset': self.params['adapt_alpha_offset'],
                'adapt_alpha_slack': self.params['adapt_alpha_slack'],
            },
        }
def build_world(current_dir):
    world = dart.simulation.World()
    urdf_parser = dart.utils.DartLoader()

    hrp4 = urdf_parser.parseSkeleton(os.path.join(current_dir, 'urdf', 'hrp4.urdf'))
    ground = urdf_parser.parseSkeleton(os.path.join(current_dir, 'urdf', 'ground.urdf'))

    world.addSkeleton(hrp4)
    world.addSkeleton(ground)
    world.setGravity([0, 0, -9.81])
    world.setTimeStep(0.01)

    default_inertia = dart.dynamics.Inertia(1e-8, np.zeros(3), 1e-10 * np.identity(3))
    for body in hrp4.getBodyNodes():
        if body.getMass() == 0.0:
            body.setMass(1e-8)
            body.setInertia(default_inertia)

    return world, hrp4


def run_headless(args):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    world, hrp4 = build_world(current_dir)
    node = Hrp4Controller(world, hrp4, args=args)

    max_steps = int(args.steps)
    failure = None

    for _ in range(max_steps):
        try:
            node.step_controller()
            world.step()
        except Exception as e:
            node.fall_detected = True
            node.finished = True
            failure = {
                'type': type(e).__name__,
                'message': str(e),
            }
            break

        if node.fall_detected:
            break
        if node.finished:
            break

    summary = node.get_summary()
    summary['profile'] = getattr(args, 'profile', 'forward')
    summary['adapt_enabled'] = bool(getattr(args, 'adapt', False))
    summary['force_N'] = float(getattr(args, 'force', 0.0))
    summary['duration_s'] = float(getattr(args, 'duration', 0.0))
    summary['direction'] = getattr(args, 'direction', 'right')
    summary['push_step'] = getattr(args, 'push_step', None)
    summary['push_phase'] = float(getattr(args, 'push_phase', 0.0))
    summary['failure'] = failure
    summary['timestamp'] = datetime.now().isoformat()

    print('[summary]')
    print(
        f"  profile={summary['profile']} adapt={summary['adapt_enabled']} "
        f"fell={summary['fell']} "
        f"ticks={summary['ticks']} sim_time={summary['sim_time_s']:.2f}s "
        f"contact={summary['last_contact']}"
    )
    print(
        f"  force={summary['force_N']:.1f}N duration={summary['duration_s']:.2f}s "
        f"direction={summary['direction']} push_step={summary['push_step']} "
        f"push_phase={summary['push_phase']:.2f}"
    )
    print(
        f"  adapter_updates={summary['adapter']['updates']} "
        f"activations={summary['adapter']['activations']} "
        f"qp_failures={summary['adapter']['qp_failures']} "
        f"max_dcm_error={summary['adapter']['max_dcm_error']:.4f}"
    )
    if failure is not None:
        print(f"  failure_type={failure['type']}")
        print(f"  failure_message={failure['message']}")

    if args.log_json:
        with open(args.log_json, 'w') as f:
            json.dump(summary, f, indent=2)

def run_viewer(args):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    world, hrp4 = build_world(current_dir)
    node = Hrp4Controller(world, hrp4, args=args)

    viewer = dart.gui.osg.Viewer()
    node.setTargetRealTimeFactor(float(args.realtime_factor))
    viewer.addWorldNode(node)
    viewer.setUpViewInWindow(0, 0, 1280, 720)
    viewer.setCameraHomePosition([5.0, -1.0, 1.5], [1.0, 0.0, 0.5], [0.0, 0.0, 1.0])
    viewer.run()


def parse_args():
    parser = argparse.ArgumentParser(description='Humanoid walking simulation with optional step timing adaptation.')
    parser.add_argument('--adapt', action='store_true', help='Enable the reactive step timing adaptation layer.')
    parser.add_argument('--headless', action='store_true', help='Run without the viewer for reproducible command-line tests.')
    parser.add_argument('--steps', type=int, default=2200, help='Maximum number of simulation ticks in headless mode.')
    parser.add_argument('--force', type=float, default=0.0, help='Push force magnitude in Newtons.')
    parser.add_argument('--duration', type=float, default=0.05, help='Push duration in seconds.')
    parser.add_argument('--push-step', type=int, default=None, help='Planner step index at which the push is applied.')
    parser.add_argument('--push-time', type=float, default=None, help='Absolute push start time in seconds.')
    parser.add_argument('--push-phase', type=float, default=0.7, help='Fraction of the selected step single-support phase used for the push start.')
    parser.add_argument('--direction', choices=['left', 'right', 'forward', 'backward'], default='right', help='Push direction.')
    parser.add_argument('--push-target',choices=['base', 'stance_foot', 'lfoot', 'rfoot'],default='base',help='Body on which the external force is applied.')
    parser.add_argument('--realtime-factor', type=float, default=10.0, help='Viewer realtime factor.')
    parser.add_argument('--quiet', action='store_true', help='Reduce console output.')
    parser.add_argument('--profile',choices=['forward', 'inplace', 'scianca'],default='forward',help='Walking reference profile.')
    parser.add_argument('--log-json',type=str,default=None,help='Optional path to save a JSON summary of the run.')
    
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    if args.headless:
        run_headless(args)
    else:
        run_viewer(args)
