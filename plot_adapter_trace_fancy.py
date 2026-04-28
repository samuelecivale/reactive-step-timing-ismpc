#!/usr/bin/env python3
"""
plot_adapter_trace_fancy.py

Generate publication-style plots and an animation for the reactive step timing adapter.

It works best with the rich trace patch for simulation.py, but it also produces
basic event plots from the older JSON format.

Outputs:
  - <stem>_dashboard.png
  - <stem>_plan_animation.mp4 if ffmpeg is available, otherwise .gif
  - <stem>_events.csv

Usage:
  python plot_adapter_trace_fancy.py logs_final/A_fwd_adapt_F45_P055_left_S3.json --outdir viz --fps 30 --stride 2
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter, FuncAnimation, PillowWriter
from matplotlib.patches import FancyArrowPatch, Rectangle
import numpy as np


FOOT_LENGTH = 0.22
FOOT_WIDTH = 0.11


# -----------------------------------------------------------------------------
# Small utilities
# -----------------------------------------------------------------------------


def load_json(path: str | Path) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_float(x: Any, default: float = np.nan) -> float:
    try:
        if x is None:
            return default
        y = float(x)
        if not np.isfinite(y):
            return default
        return y
    except Exception:
        return default


def series(trace: Sequence[Dict[str, Any]], key: str, default: float = np.nan) -> np.ndarray:
    return np.asarray([safe_float(row.get(key), default=default) for row in trace], dtype=float)


def bool_series(trace: Sequence[Dict[str, Any]], key: str) -> np.ndarray:
    return np.asarray([bool(row.get(key, False)) for row in trace], dtype=bool)


def first_present(row: Dict[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return default


def has_rich_trace(data: Dict[str, Any]) -> bool:
    trace = data.get("trace", [])
    if not trace:
        return False
    row = trace[min(1, len(trace) - 1)]
    required = ["current_com_x", "current_com_y", "dcm_x", "dcm_y"]
    return any(k in row for k in required) and "nominal_plan" in data


def get_time(trace: Sequence[Dict[str, Any]]) -> np.ndarray:
    return np.asarray([safe_float(row.get("time_s"), 0.0) for row in trace], dtype=float)


def plan_to_array(plan: Sequence[Dict[str, Any]]) -> np.ndarray:
    out = []
    for s in plan:
        pos = s.get("pos", None)
        ang = s.get("ang", None)
        if pos is not None:
            x, y = safe_float(pos[0]), safe_float(pos[1])
            z = safe_float(pos[2]) if len(pos) > 2 else 0.0
        else:
            x = safe_float(s.get("x"))
            y = safe_float(s.get("y"))
            z = safe_float(s.get("z"), 0.0)
        if ang is not None:
            yaw = safe_float(ang[2]) if len(ang) > 2 else 0.0
        else:
            yaw = safe_float(s.get("yaw"), 0.0)
        out.append([x, y, z, yaw])
    return np.asarray(out, dtype=float) if out else np.zeros((0, 4), dtype=float)


def normalize_plan(plan: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    norm = []
    for i, s in enumerate(plan):
        pos = s.get("pos", None)
        ang = s.get("ang", None)
        item = dict(s)
        item["step"] = int(s.get("step", s.get("index", i)))
        item["foot_id"] = s.get("foot_id", s.get("foot", "?"))
        if pos is not None:
            item["x"] = safe_float(pos[0])
            item["y"] = safe_float(pos[1])
            item["z"] = safe_float(pos[2]) if len(pos) > 2 else 0.0
        else:
            item["x"] = safe_float(s.get("x"))
            item["y"] = safe_float(s.get("y"))
            item["z"] = safe_float(s.get("z"), 0.0)
        if ang is not None:
            item["yaw"] = safe_float(ang[2]) if len(ang) > 2 else 0.0
        else:
            item["yaw"] = safe_float(s.get("yaw"), 0.0)
        item["ss_duration"] = int(safe_float(s.get("ss_duration", s.get("ss", 0)), 0))
        item["ds_duration"] = int(safe_float(s.get("ds_duration", s.get("ds", 0)), 0))
        norm.append(item)
    return norm


def adapter_events(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Rich trace stores explicit adapter_events. Older JSON stores updates inside trace rows.
    events = list(data.get("adapter_events", []) or [])
    if events:
        return sorted(events, key=lambda e: int(e.get("tick", e.get("time_tick", 0))))

    out = []
    for row in data.get("trace", []):
        if not row.get("adapter_updated", False):
            continue
        step_index = row.get("step_index")
        if step_index is None:
            continue
        out.append({
            "tick": int(row.get("tick", 0)),
            "time_s": safe_float(row.get("time_s"), 0.0),
            "step_index": int(step_index),
            "target_step_index": int(step_index) + 1,
            "ss_before": row.get("ss_before"),
            "ss_after": row.get("ss_after"),
            "target_before_x": row.get("target_before_x"),
            "target_before_y": row.get("target_before_y"),
            "target_after_x": row.get("target_after_x"),
            "target_after_y": row.get("target_after_y"),
            "dcm_error": row.get("dcm_error"),
            "margin": row.get("margin"),
        })
    return sorted(out, key=lambda e: int(e.get("tick", 0)))


def active_plan_at_tick(nominal_plan: Sequence[Dict[str, Any]], events: Sequence[Dict[str, Any]], tick: int) -> List[Dict[str, Any]]:
    plan = [dict(s) for s in normalize_plan(nominal_plan)]
    for ev in events:
        ev_tick = int(ev.get("tick", ev.get("time_tick", 10**18)))
        if ev_tick > tick:
            continue

        step_idx = ev.get("step_index", None)
        target_idx = ev.get("target_step_index", None)
        if target_idx is None and step_idx is not None:
            target_idx = int(step_idx) + 1

        if step_idx is not None:
            step_idx = int(step_idx)
            if 0 <= step_idx < len(plan) and ev.get("ss_after") is not None:
                plan[step_idx]["ss_duration"] = int(ev["ss_after"])

        if target_idx is not None:
            target_idx = int(target_idx)
            if 0 <= target_idx < len(plan):
                if ev.get("target_after_x") is not None:
                    plan[target_idx]["x"] = safe_float(ev.get("target_after_x"))
                if ev.get("target_after_y") is not None:
                    plan[target_idx]["y"] = safe_float(ev.get("target_after_y"))
    return plan


def draw_foot(ax, x: float, y: float, yaw: float = 0.0, *, label: Optional[str] = None,
              mode: str = "nominal", alpha: Optional[float] = None) -> None:
    if not np.isfinite(x) or not np.isfinite(y):
        return

    style = {
        "nominal": dict(edgecolor="0.55", facecolor="none", linestyle="--", linewidth=1.2, zorder=2),
        "active": dict(edgecolor="#d62728", facecolor="#d6272822", linestyle="-", linewidth=1.9, zorder=4),
        "current": dict(edgecolor="#1f77b4", facecolor="#1f77b422", linestyle="-", linewidth=2.0, zorder=5),
        "desired": dict(edgecolor="#2ca02c", facecolor="#2ca02c18", linestyle="-", linewidth=1.6, zorder=4),
    }[mode]
    if alpha is not None:
        style["alpha"] = alpha

    rect = Rectangle(
        (x - FOOT_LENGTH / 2.0, y - FOOT_WIDTH / 2.0),
        FOOT_LENGTH,
        FOOT_WIDTH,
        angle=math.degrees(yaw),
        **style,
    )
    ax.add_patch(rect)
    if label:
        ax.text(x, y, label, ha="center", va="center", fontsize=7, zorder=10)


def set_xy_limits(ax, nominal_plan: Sequence[Dict[str, Any]], trace: Sequence[Dict[str, Any]]) -> None:
    xs, ys = [], []
    for s in normalize_plan(nominal_plan):
        xs.append(s["x"])
        ys.append(s["y"])
    for keyx, keyy in [
        ("current_com_x", "current_com_y"),
        ("desired_com_x", "desired_com_y"),
        ("dcm_x", "dcm_y"),
        ("current_zmp_x", "current_zmp_y"),
        ("desired_zmp_x", "desired_zmp_y"),
    ]:
        x = series(trace, keyx)
        y = series(trace, keyy)
        xs.extend(x[np.isfinite(x)].tolist())
        ys.extend(y[np.isfinite(y)].tolist())

    xs = [x for x in xs if np.isfinite(x)]
    ys = [y for y in ys if np.isfinite(y)]
    if not xs:
        xs = [-0.5, 1.5]
    if not ys:
        ys = [-0.5, 0.5]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    dx = max(0.8, xmax - xmin)
    dy = max(0.5, ymax - ymin)
    ax.set_xlim(xmin - 0.18 * dx - 0.15, xmax + 0.18 * dx + 0.15)
    ax.set_ylim(ymin - 0.35 * dy - 0.15, ymax + 0.35 * dy + 0.15)
    ax.set_aspect("equal", adjustable="box")


def add_push_window(ax, data: Dict[str, Any], *, ymax: Optional[float] = None) -> None:
    pw = data.get("push_window", {}) or {}
    dt = pw.get("dt", None)
    start = pw.get("start_tick", None)
    end = pw.get("end_tick", None)
    if dt is None or start is None or end is None:
        return
    t0 = safe_float(start) * safe_float(dt)
    t1 = safe_float(end) * safe_float(dt)
    ax.axvspan(t0, t1, alpha=0.17, label="push window")


# -----------------------------------------------------------------------------
# Static dashboard
# -----------------------------------------------------------------------------


def save_events_csv(data: Dict[str, Any], outdir: Path, stem: str) -> None:
    events = adapter_events(data)
    path = outdir / f"{stem}_events.csv"
    keys = [
        "tick", "time_s", "step_index", "target_step_index",
        "ss_before", "ss_after",
        "target_before_x", "target_before_y", "target_after_x", "target_after_y",
        "dcm_error", "margin",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for ev in events:
            w.writerow({k: ev.get(k, "") for k in keys})


def save_dashboard(data: Dict[str, Any], outdir: Path, stem: str) -> None:
    trace = data.get("trace", [])
    if not trace:
        return

    t = get_time(trace)
    events = adapter_events(data)

    # Prefer live DCM error from rich traces; fallback to update-only dcm_error.
    dcm_err = series(trace, "dcm_error_live")
    if np.all(~np.isfinite(dcm_err)):
        dcm_err = series(trace, "dcm_error")

    margin = series(trace, "margin")
    adapter_upd = bool_series(trace, "adapter_updated")
    push_active = bool_series(trace, "push_active")

    # Active-plan signals: current-step SS and next-step y.
    ss_active = series(trace, "active_step_ss")
    next_y = series(trace, "active_next_y")
    if np.all(~np.isfinite(ss_active)):
        ss_active = np.full_like(t, np.nan)
    if np.all(~np.isfinite(next_y)):
        # Old JSON fallback: forward-fill update target y.
        last = np.nan
        vals = []
        for r in trace:
            y = safe_float(r.get("target_after_y"))
            if np.isfinite(y):
                last = y
            vals.append(last)
        next_y = np.asarray(vals, dtype=float)

    fig = plt.figure(figsize=(14, 9))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.1, 1.0, 1.0])
    ax0 = fig.add_subplot(gs[0, :])
    ax1 = fig.add_subplot(gs[1, 0])
    ax2 = fig.add_subplot(gs[1, 1])
    ax3 = fig.add_subplot(gs[2, 0])
    ax4 = fig.add_subplot(gs[2, 1])

    ax0.plot(t, dcm_err, linewidth=2.0, label="DCM error")
    add_push_window(ax0, data)
    if adapter_upd.any():
        ax0.scatter(t[adapter_upd], dcm_err[adapter_upd], s=45, marker="x", label="adapter update")
    thr = data.get("tuning_params", {}).get("adapt_dcm_error_threshold", None)
    if thr is not None:
        ax0.axhline(float(thr), linestyle="--", linewidth=1.2, label="trigger threshold")
    ax0.set_title("Adapter trigger: DCM error over time")
    ax0.set_ylabel("error [m]")
    ax0.grid(alpha=0.25)
    ax0.legend(loc="upper right")

    ax1.plot(t, margin, linewidth=1.8, label="viability margin")
    ax1.axhline(0.0, linestyle="--", linewidth=1.0)
    add_push_window(ax1, data)
    if adapter_upd.any():
        ax1.scatter(t[adapter_upd], margin[adapter_upd], s=45, marker="x")
    ax1.set_title("Viability margin")
    ax1.set_xlabel("time [s]")
    ax1.set_ylabel("margin [m]")
    ax1.grid(alpha=0.25)

    ax2.step(t, push_active.astype(int), where="post", label="push active")
    ax2.step(t, adapter_upd.astype(int), where="post", label="adapter update")
    ax2.set_ylim(-0.1, 1.2)
    ax2.set_title("Discrete events")
    ax2.set_xlabel("time [s]")
    ax2.grid(alpha=0.25)
    ax2.legend()

    ax3.plot(t, ss_active, linewidth=1.8)
    add_push_window(ax3, data)
    ax3.set_title("Active current-step single-support duration")
    ax3.set_xlabel("time [s]")
    ax3.set_ylabel("SS duration [ticks]")
    ax3.grid(alpha=0.25)

    ax4.plot(t, next_y, linewidth=1.8)
    add_push_window(ax4, data)
    ax4.set_title("Active next-foot lateral target")
    ax4.set_xlabel("time [s]")
    ax4.set_ylabel("next target y [m]")
    ax4.grid(alpha=0.25)

    status = "FELL" if data.get("fell") else "SURVIVED"
    fig.suptitle(
        f"{stem} | {status} | adapt={data.get('adapt_enabled')} | "
        f"F={data.get('force_N')}N {data.get('direction')} S{data.get('push_step')} P={data.get('push_phase')}",
        fontsize=15,
        fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(outdir / f"{stem}_dashboard.png", dpi=180)
    plt.close(fig)


# -----------------------------------------------------------------------------
# Animation
# -----------------------------------------------------------------------------


def make_animation(data: Dict[str, Any], outdir: Path, stem: str, *, fps: int = 30, stride: int = 2) -> None:
    trace = data.get("trace", [])
    if not trace:
        raise ValueError("JSON has no trace field.")

    nominal_plan = normalize_plan(data.get("nominal_plan", []))
    if not nominal_plan:
        # Old JSON fallback: synthesize a minimal plan around update points.
        nominal_plan = []
        for ev in adapter_events(data):
            target_idx = int(ev.get("target_step_index", ev.get("step_index", 0) + 1))
            while len(nominal_plan) <= target_idx:
                nominal_plan.append({
                    "step": len(nominal_plan),
                    "foot_id": "?",
                    "x": float(len(nominal_plan)) * 0.08,
                    "y": 0.0,
                    "z": 0.0,
                    "yaw": 0.0,
                    "ss_duration": 70,
                    "ds_duration": 30,
                })
            if ev.get("target_before_x") is not None:
                nominal_plan[target_idx]["x"] = safe_float(ev.get("target_before_x"))
            if ev.get("target_before_y") is not None:
                nominal_plan[target_idx]["y"] = safe_float(ev.get("target_before_y"))

    events = adapter_events(data)
    t = get_time(trace)
    ticks = np.asarray([int(row.get("tick", i)) for i, row in enumerate(trace)], dtype=int)

    com_x = series(trace, "current_com_x")
    com_y = series(trace, "current_com_y")
    dcm_x = series(trace, "dcm_x")
    dcm_y = series(trace, "dcm_y")
    zmp_x = series(trace, "current_zmp_x")
    zmp_y = series(trace, "current_zmp_y")
    dzmp_x = series(trace, "desired_zmp_x")
    dzmp_y = series(trace, "desired_zmp_y")

    # Fallback for old JSON: only event points are meaningful.
    if np.all(~np.isfinite(com_x)):
        com_x = np.full(len(trace), np.nan)
        com_y = np.full(len(trace), np.nan)
        dcm_x = np.full(len(trace), np.nan)
        dcm_y = np.full(len(trace), np.nan)

    dcm_err = series(trace, "dcm_error_live")
    if np.all(~np.isfinite(dcm_err)):
        dcm_err = series(trace, "dcm_error")
    adapter_upd = bool_series(trace, "adapter_updated")
    push_active = bool_series(trace, "push_active")

    frame_ids = list(range(0, len(trace), max(1, int(stride))))
    if frame_ids[-1] != len(trace) - 1:
        frame_ids.append(len(trace) - 1)

    fig = plt.figure(figsize=(15, 8.5))
    gs = fig.add_gridspec(2, 2, width_ratios=[2.0, 1.0], height_ratios=[1.1, 1.0])
    ax_xy = fig.add_subplot(gs[:, 0])
    ax_err = fig.add_subplot(gs[0, 1])
    ax_text = fig.add_subplot(gs[1, 1])

    global_max_err = np.nanmax(dcm_err) if np.any(np.isfinite(dcm_err)) else 0.01
    global_max_err = max(global_max_err, 0.01)
    t_min = float(np.nanmin(t)) if len(t) else 0.0
    t_max = float(np.nanmax(t)) if len(t) else 1.0

    def draw_frame(frame_number: int) -> None:
        idx = frame_ids[frame_number]
        tick = int(ticks[idx])
        row = trace[idx]

        ax_xy.clear()
        ax_err.clear()
        ax_text.clear()
        ax_text.axis("off")

        set_xy_limits(ax_xy, nominal_plan, trace)
        ax_xy.set_title("Nominal plan vs active/adapted plan")
        ax_xy.set_xlabel("x [m]")
        ax_xy.set_ylabel("y [m]")
        ax_xy.grid(alpha=0.22)

        # Nominal footsteps.
        for s in nominal_plan:
            label = f"N{s['step']}"
            draw_foot(ax_xy, s["x"], s["y"], s.get("yaw", 0.0), label=label, mode="nominal", alpha=0.75)

        # Active/adapted footsteps up to the current tick.
        active_plan = active_plan_at_tick(nominal_plan, events, tick)
        for s in active_plan:
            # Highlight only steps that differ from nominal.
            i = int(s["step"])
            n = nominal_plan[i] if 0 <= i < len(nominal_plan) else None
            different = False
            if n is not None:
                different = (
                    abs(s["x"] - n["x"]) > 1e-6
                    or abs(s["y"] - n["y"]) > 1e-6
                    or int(s.get("ss_duration", 0)) != int(n.get("ss_duration", 0))
                )
            if different:
                label = f"A{i}"
                draw_foot(ax_xy, s["x"], s["y"], s.get("yaw", 0.0), label=label, mode="active")

        valid = np.isfinite(com_x[: idx + 1]) & np.isfinite(com_y[: idx + 1])
        if valid.any():
            ax_xy.plot(com_x[: idx + 1][valid], com_y[: idx + 1][valid], linewidth=2.0, label="CoM")
        valid = np.isfinite(dcm_x[: idx + 1]) & np.isfinite(dcm_y[: idx + 1])
        if valid.any():
            ax_xy.plot(dcm_x[: idx + 1][valid], dcm_y[: idx + 1][valid], linewidth=1.5, label="DCM")
        valid = np.isfinite(dzmp_x[: idx + 1]) & np.isfinite(dzmp_y[: idx + 1])
        if valid.any():
            ax_xy.plot(dzmp_x[: idx + 1][valid], dzmp_y[: idx + 1][valid], linestyle="--", linewidth=1.2, label="ZMP ref")
        valid = np.isfinite(zmp_x[: idx + 1]) & np.isfinite(zmp_y[: idx + 1])
        if valid.any():
            ax_xy.plot(zmp_x[: idx + 1][valid], zmp_y[: idx + 1][valid], linestyle=":", linewidth=1.0, label="ZMP")

        if np.isfinite(com_x[idx]) and np.isfinite(com_y[idx]):
            ax_xy.scatter(com_x[idx], com_y[idx], s=70, marker="o", zorder=20, label="current CoM")
        if np.isfinite(dcm_x[idx]) and np.isfinite(dcm_y[idx]):
            ax_xy.scatter(dcm_x[idx], dcm_y[idx], s=80, marker="x", zorder=21, label="current DCM")

        # Current physical feet if present.
        lf_x = safe_float(row.get("current_lfoot_x"))
        lf_y = safe_float(row.get("current_lfoot_y"))
        rf_x = safe_float(row.get("current_rfoot_x"))
        rf_y = safe_float(row.get("current_rfoot_y"))
        if np.isfinite(lf_x) and np.isfinite(lf_y):
            draw_foot(ax_xy, lf_x, lf_y, 0.0, label="L", mode="current")
        if np.isfinite(rf_x) and np.isfinite(rf_y):
            draw_foot(ax_xy, rf_x, rf_y, 0.0, label="R", mode="current")

        # Push arrow, direction inferred from CLI summary.
        if bool(row.get("push_active", False)) and np.isfinite(com_x[idx]) and np.isfinite(com_y[idx]):
            direction = str(data.get("direction", ""))
            dir_vec = {
                "left": np.array([0.0, 1.0]),
                "right": np.array([0.0, -1.0]),
                "forward": np.array([1.0, 0.0]),
                "backward": np.array([-1.0, 0.0]),
            }.get(direction, np.array([0.0, 0.0]))
            if np.linalg.norm(dir_vec) > 0:
                tail = np.array([com_x[idx], com_y[idx]])
                head = tail + 0.22 * dir_vec
                ax_xy.add_patch(FancyArrowPatch(tail, head, arrowstyle="->", mutation_scale=20, linewidth=2.5, zorder=30))
                ax_xy.text(head[0], head[1], "push", fontsize=9, ha="center", va="bottom")

        # Update arrows: show all updates up to current tick.
        for ev in events:
            ev_tick = int(ev.get("tick", 10**18))
            if ev_tick > tick:
                continue
            bx = safe_float(ev.get("target_before_x"))
            by = safe_float(ev.get("target_before_y"))
            ax = safe_float(ev.get("target_after_x"))
            ay = safe_float(ev.get("target_after_y"))
            if np.isfinite([bx, by, ax, ay]).all() and math.hypot(ax - bx, ay - by) > 1e-5:
                ax_xy.add_patch(FancyArrowPatch((bx, by), (ax, ay), arrowstyle="->", mutation_scale=15, linewidth=1.8, zorder=25))

        if bool(row.get("adapter_updated", False)):
            ax_xy.text(
                0.02, 0.96, "ADAPTER UPDATE", transform=ax_xy.transAxes,
                fontsize=13, fontweight="bold",
                bbox=dict(boxstyle="round", facecolor="#fff0b3", edgecolor="#cc9900"),
            )
        elif bool(row.get("plan_modified", False)):
            ax_xy.text(
                0.02, 0.96, "ADAPTED PLAN ACTIVE", transform=ax_xy.transAxes,
                fontsize=12, fontweight="bold",
                bbox=dict(boxstyle="round", facecolor="#ffd6d6", edgecolor="#d62728"),
            )

        ax_xy.legend(loc="upper right", fontsize=8)

        # DCM error panel.
        ax_err.set_title("DCM error and adapter updates")
        finite_err = np.isfinite(dcm_err[: idx + 1])
        if finite_err.any():
            ax_err.plot(t[: idx + 1][finite_err], dcm_err[: idx + 1][finite_err], linewidth=2.0, label="DCM error")
        add_push_window(ax_err, data)
        if adapter_upd[: idx + 1].any():
            upd = adapter_upd[: idx + 1] & np.isfinite(dcm_err[: idx + 1])
            ax_err.scatter(t[: idx + 1][upd], dcm_err[: idx + 1][upd], marker="x", s=55, label="adapter update")
        thr = data.get("tuning_params", {}).get("adapt_dcm_error_threshold", None)
        if thr is not None:
            ax_err.axhline(float(thr), linestyle="--", linewidth=1.1, label="threshold")
        ax_err.axvline(t[idx], linewidth=1.0, alpha=0.4)
        ax_err.set_xlim(t_min, t_max)
        ax_err.set_ylim(0.0, global_max_err * 1.25)
        ax_err.set_xlabel("time [s]")
        ax_err.set_ylabel("error [m]")
        ax_err.grid(alpha=0.25)
        ax_err.legend(fontsize=8)

        # Text panel.
        last_event = None
        for ev in events:
            if int(ev.get("tick", 10**18)) <= tick:
                last_event = ev
            else:
                break

        lines = [
            f"time: {safe_float(row.get('time_s'), 0.0):.2f} s",
            f"tick: {tick}",
            f"step: {row.get('step_index')}",
            f"phase: {row.get('planner_phase')}",
            f"support: {row.get('support_foot')}",
            f"swing: {row.get('swing_foot')}",
            f"swing phase: {row.get('swing_phase_label')}",
            "",
            f"push active: {row.get('push_active')}",
            f"adapter update: {row.get('adapter_updated')}",
            f"plan modified: {row.get('plan_modified', False)}",
            f"fell: {data.get('fell')}",
        ]
        if last_event is not None:
            lines += [
                "",
                "last update:",
                f"  t={safe_float(last_event.get('time_s'), 0.0):.2f}s step={last_event.get('step_index')}",
                f"  ss {last_event.get('ss_before')} -> {last_event.get('ss_after')}",
                f"  x {safe_float(last_event.get('target_before_x')):.3f} -> {safe_float(last_event.get('target_after_x')):.3f}",
                f"  y {safe_float(last_event.get('target_before_y')):.3f} -> {safe_float(last_event.get('target_after_y')):.3f}",
                f"  err={safe_float(last_event.get('dcm_error')):.4f}",
                f"  margin={safe_float(last_event.get('margin')):.4f}",
            ]
        ax_text.text(0.02, 0.98, "\n".join(lines), va="top", ha="left", family="monospace", fontsize=10)

        fig.suptitle(
            f"{stem} | nominal vs adapted | t={safe_float(row.get('time_s'), 0.0):.2f}s",
            fontsize=15,
            fontweight="bold",
        )
        fig.tight_layout()

    anim = FuncAnimation(fig, draw_frame, frames=len(frame_ids), interval=1000.0 / max(1, fps), blit=False)

    mp4_path = outdir / f"{stem}_plan_animation.mp4"
    try:
        writer = FFMpegWriter(fps=fps, bitrate=3500)
        anim.save(mp4_path, writer=writer)
        print(f"[ok] saved animation: {mp4_path}")
    except Exception as e:
        gif_path = outdir / f"{stem}_plan_animation.gif"
        print(f"[warn] could not save mp4 with ffmpeg: {e}")
        print(f"[warn] saving GIF fallback: {gif_path}")
        writer = PillowWriter(fps=max(1, min(fps, 20)))
        anim.save(gif_path, writer=writer)
    finally:
        plt.close(fig)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Create fancy adapter plots and a plan animation from a simulation JSON.")
    parser.add_argument("json_path", help="Path to one JSON produced by simulation.py --log-json")
    parser.add_argument("--outdir", default="viz_adapter", help="Output directory")
    parser.add_argument("--fps", type=int, default=30, help="Animation FPS")
    parser.add_argument("--stride", type=int, default=2, help="Use one frame every N trace rows")
    parser.add_argument("--no-video", action="store_true", help="Only save static dashboard and CSV")
    args = parser.parse_args()

    data = load_json(args.json_path)
    outdir = ensure_dir(args.outdir)
    stem = Path(args.json_path).stem

    if not has_rich_trace(data):
        print("[warn] This JSON does not contain the rich per-tick fields/nominal_plan.")
        print("[warn] Static plots will work; animation will be event-level rather than full CoM/DCM/ZMP.")

    save_dashboard(data, outdir, stem)
    save_events_csv(data, outdir, stem)
    if not args.no_video:
        make_animation(data, outdir, stem, fps=args.fps, stride=args.stride)

    print(f"[ok] outputs saved in: {outdir}")


if __name__ == "__main__":
    main()
