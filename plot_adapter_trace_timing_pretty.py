#!/usr/bin/env python3
"""
plot_adapter_trace_timing_pretty.py

Pretty visualizer for the reactive adapter.

Main outputs:
  - *_timing_animation.mp4 / .gif
  - *_timing_dashboard.png
  - *_timing_events.csv

The video/dashboard show:
  - nominal vs adapted footstep plan
  - adapter timing update: ss_before -> ss_after, ΔT
  - footstep location update: Δp
  - DCM error and push window
  - next-step target x(t) and y(t), comparing nominal vs adapted

Usage:
  python simulation.py --headless --steps 1000 \
    --adapt --timing-biased \
    --profile forward \
    --force 46 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base \
    --log-json logs_viz/fwd_hybrid_timing_step_F46_P055_left_S3.json

  python plot_adapter_trace_timing_pretty.py logs_viz/fwd_hybrid_timing_step_F46_P055_left_S3.json \
    --outdir viz_adapter --fps 8 --stride 4
"""

import argparse
import json
import math
import os
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, FFMpegWriter, PillowWriter
from matplotlib.patches import Rectangle
import numpy as np


# -----------------------------
# Style / colors
# -----------------------------

COLORS = {
    "bg": "#FAFAFA",
    "panel": "#FFFFFF",
    "grid": "#D9D9D9",
    "text": "#1F2933",
    "muted": "#6B7280",
    "nominal": "#8A8A8A",
    "adapted": "#D9480F",
    "adapted_fill": "#FFE8D9",
    "com": "#1F77B4",
    "dcm": "#7B2CBF",
    "zmp": "#2F9E44",
    "zmp_ref": "#74B816",
    "push": "#FFD43B",
    "update": "#E03131",
    "timing": "#E8590C",
    "step": "#0CA678",
}

FOOT_LENGTH = 0.22
FOOT_WIDTH = 0.11


# -----------------------------
# Loading helpers
# -----------------------------

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def get_trace(data):
    return data.get("trace", []) or []


def get_dt(data):
    pw = data.get("push_window", {}) or {}
    return float(pw.get("dt", data.get("dt", 0.01)) or 0.01)


def get_time(row, dt):
    if "time_s" in row and row["time_s"] is not None:
        return float(row["time_s"])
    if "t" in row and row["t"] is not None:
        return float(row["t"])
    return float(row.get("tick", 0)) * dt


def get_tick(row):
    return int(row.get("tick", 0))


def get_xy(row, *names):
    for name in names:
        value = row.get(name)
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return float(value[0]), float(value[1])

    for name in names:
        x = row.get(f"{name}_x")
        y = row.get(f"{name}_y")
        if x is not None and y is not None:
            return float(x), float(y)

    return None


def list_xy(trace, *names):
    xs, ys = [], []
    for r in trace:
        xy = get_xy(r, *names)
        if xy is None:
            xs.append(np.nan)
            ys.append(np.nan)
        else:
            xs.append(xy[0])
            ys.append(xy[1])
    return np.asarray(xs), np.asarray(ys)


def normalize_plan(plan):
    out = []
    for i, s in enumerate(plan):
        if not isinstance(s, dict):
            continue

        if "pos" in s and isinstance(s["pos"], (list, tuple)) and len(s["pos"]) >= 2:
            x, y = float(s["pos"][0]), float(s["pos"][1])
            z = float(s["pos"][2]) if len(s["pos"]) > 2 else 0.0
        else:
            x = s.get("x", s.get("pos_x", None))
            y = s.get("y", s.get("pos_y", None))
            z = s.get("z", s.get("pos_z", 0.0))
            if x is None or y is None:
                continue
            x, y, z = float(x), float(y), float(z)

        if "ang" in s and isinstance(s["ang"], (list, tuple)) and len(s["ang"]) >= 3:
            theta = float(s["ang"][2])
        else:
            theta = float(s.get("theta", s.get("yaw", 0.0)) or 0.0)

        out.append({
            "i": int(s.get("step", s.get("i", i))),
            "x": x,
            "y": y,
            "z": z,
            "theta": theta,
            "foot": s.get("foot_id", s.get("foot", "?")),
            "ss": int(s.get("ss_duration", s.get("ss", 70)) or 70),
            "ds": int(s.get("ds_duration", s.get("ds", 30)) or 30),
        })
    return out


def get_nominal_plan(data):
    plan = data.get("nominal_plan")
    if isinstance(plan, list) and plan:
        return normalize_plan(plan)
    return []


def get_events(trace):
    events = []
    for r in trace:
        updated = bool(r.get("adapter_updated", False))
        has_ss = r.get("ss_before") is not None and r.get("ss_after") is not None
        has_target = (
            r.get("target_before_x") is not None
            and r.get("target_before_y") is not None
            and r.get("target_after_x") is not None
            and r.get("target_after_y") is not None
        )
        if not updated and not (has_ss or has_target):
            continue

        events.append({
            "tick": int(r.get("tick", 0)),
            "time_s": r.get("time_s"),
            "step_index": r.get("step_index"),
            "ss_before": r.get("ss_before"),
            "ss_after": r.get("ss_after"),
            "target_before_x": r.get("target_before_x"),
            "target_before_y": r.get("target_before_y"),
            "target_after_x": r.get("target_after_x"),
            "target_after_y": r.get("target_after_y"),
            "dcm_error": r.get("dcm_error"),
            "margin": r.get("margin"),
        })
    return events


def plan_after_events(nominal_plan, events, tick):
    plan = [dict(s) for s in nominal_plan]

    for ev in events:
        if ev["tick"] > tick:
            continue

        step_index = ev.get("step_index")
        if step_index is None:
            continue

        try:
            step_index = int(step_index)
        except Exception:
            continue

        # Timing update applies to the current support step.
        ss_after = ev.get("ss_after")
        if ss_after is not None and 0 <= step_index < len(plan):
            plan[step_index]["ss"] = int(ss_after)

        # Footstep target update applies to the next step.
        xa = ev.get("target_after_x")
        ya = ev.get("target_after_y")
        target_idx = step_index + 1
        if xa is not None and ya is not None and 0 <= target_idx < len(plan):
            plan[target_idx]["x"] = float(xa)
            plan[target_idx]["y"] = float(ya)

    return plan


def event_deltas(ev, dt):
    dss = None
    dss_ms = None
    if ev.get("ss_before") is not None and ev.get("ss_after") is not None:
        dss = int(ev["ss_after"]) - int(ev["ss_before"])
        dss_ms = dss * dt * 1000.0

    dpos = None
    vals = [
        ev.get("target_before_x"), ev.get("target_before_y"),
        ev.get("target_after_x"), ev.get("target_after_y")
    ]
    if all(v is not None for v in vals):
        xb, yb, xa, ya = [float(v) for v in vals]
        dpos = math.sqrt((xa - xb) ** 2 + (ya - yb) ** 2)

    return dss, dss_ms, dpos


def build_next_target_series(trace, nominal_plan, events, dt):
    """
    Builds time series for the next landing target currently relevant to the
    active step:
        nominal_x(t), nominal_y(t)
        adapted_x(t), adapted_y(t)

    The adapted series is reconstructed by applying all adapter events up to
    the current tick. This makes the x(t)/y(t) jumps visible exactly when the
    adapter changes the next footstep.
    """
    times = []
    nom_x, nom_y = [], []
    adp_x, adp_y = [], []

    for r in trace:
        tick = get_tick(r)
        t = get_time(r, dt)
        step_index = r.get("step_index", None)

        if step_index is None:
            times.append(t)
            nom_x.append(np.nan); nom_y.append(np.nan)
            adp_x.append(np.nan); adp_y.append(np.nan)
            continue

        try:
            target_idx = int(step_index) + 1
        except Exception:
            target_idx = -1

        if not (0 <= target_idx < len(nominal_plan)):
            times.append(t)
            nom_x.append(np.nan); nom_y.append(np.nan)
            adp_x.append(np.nan); adp_y.append(np.nan)
            continue

        adapted_plan = plan_after_events(nominal_plan, events, tick)

        times.append(t)
        nom_x.append(nominal_plan[target_idx]["x"])
        nom_y.append(nominal_plan[target_idx]["y"])
        adp_x.append(adapted_plan[target_idx]["x"])
        adp_y.append(adapted_plan[target_idx]["y"])

    return (
        np.asarray(times, dtype=float),
        np.asarray(nom_x, dtype=float),
        np.asarray(nom_y, dtype=float),
        np.asarray(adp_x, dtype=float),
        np.asarray(adp_y, dtype=float),
    )


# -----------------------------
# Drawing helpers
# -----------------------------

def prettify_axis(ax):
    ax.set_facecolor(COLORS["panel"])
    ax.tick_params(colors=COLORS["muted"], labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#E5E7EB")
    ax.grid(True, color=COLORS["grid"], alpha=0.45, linewidth=0.8)


def draw_foot(ax, x, y, theta=0.0, label=None, mode="nominal"):
    if x is None or y is None or np.isnan(x) or np.isnan(y):
        return

    if mode == "nominal":
        edgecolor = COLORS["nominal"]
        facecolor = "none"
        linestyle = "--"
        linewidth = 1.1
        alpha = 0.55
        zorder = 2
    elif mode == "adapted":
        edgecolor = COLORS["adapted"]
        facecolor = COLORS["adapted_fill"]
        linestyle = "-"
        linewidth = 2.0
        alpha = 0.95
        zorder = 4
    else:
        edgecolor = COLORS["com"]
        facecolor = "#E7F5FF"
        linestyle = "-"
        linewidth = 1.8
        alpha = 0.90
        zorder = 5

    rect = Rectangle(
        (x - FOOT_LENGTH / 2.0, y - FOOT_WIDTH / 2.0),
        FOOT_LENGTH,
        FOOT_WIDTH,
        angle=math.degrees(theta),
        edgecolor=edgecolor,
        facecolor=facecolor,
        linestyle=linestyle,
        linewidth=linewidth,
        alpha=alpha,
        zorder=zorder,
    )
    ax.add_patch(rect)

    if label:
        ax.text(
            x, y, label,
            fontsize=7,
            ha="center",
            va="center",
            color=COLORS["text"],
            zorder=zorder + 1,
        )


def setup_xy_limits(ax, nominal_plan, com_x, com_y, dcm_x, dcm_y):
    xs, ys = [], []

    for s in nominal_plan:
        xs.append(s["x"])
        ys.append(s["y"])

    for xarr, yarr in [(com_x, com_y), (dcm_x, dcm_y)]:
        if len(xarr):
            xs += [float(v) for v in xarr if np.isfinite(v)]
            ys += [float(v) for v in yarr if np.isfinite(v)]

    if not xs:
        xs = [-0.2, 1.0]
        ys = [-0.3, 0.3]

    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    dx = max(xmax - xmin, 0.8)
    dy = max(ymax - ymin, 0.5)

    ax.set_xlim(xmin - 0.25 * dx - 0.1, xmax + 0.25 * dx + 0.1)
    ax.set_ylim(ymin - 0.35 * dy - 0.1, ymax + 0.35 * dy + 0.1)
    ax.set_aspect("equal", adjustable="box")


def add_push_window(ax, data, label=False):
    pw = data.get("push_window", {}) or {}
    dt = pw.get("dt", None)
    s = pw.get("start_tick", None)
    e = pw.get("end_tick", None)
    if dt is None or s is None or e is None:
        return

    t0 = float(s) * float(dt)
    t1 = float(e) * float(dt)
    ax.axvspan(
        t0, t1,
        color=COLORS["push"],
        alpha=0.25,
        label="push window" if label else None,
        zorder=0,
    )


def update_card_text(ev, dt):
    if ev is None:
        return "No adapter update yet"

    dss, dss_ms, dpos = event_deltas(ev, dt)

    lines = ["LAST ADAPTER UPDATE"]

    if dss is not None:
        lines += [
            "",
            f"Timing: ss {int(ev['ss_before'])} → {int(ev['ss_after'])}",
            f"ΔT = {dss:+d} ticks  ({dss_ms:+.0f} ms)",
        ]

    if dpos is not None:
        lines += [
            "",
            f"Footstep shift: Δp = {100*dpos:.1f} cm",
        ]

        xb = float(ev["target_before_x"])
        yb = float(ev["target_before_y"])
        xa = float(ev["target_after_x"])
        ya = float(ev["target_after_y"])
        lines += [
            f"({xb:.3f}, {yb:.3f}) → ({xa:.3f}, {ya:.3f})"
        ]

    return "\n".join(lines)


def save_event_csv(data, trace, out_csv):
    dt = get_dt(data)
    events = get_events(trace)
    with open(out_csv, "w") as f:
        f.write("tick,time_s,step,ss_before,ss_after,dss_ticks,dss_ms,dpos_cm\n")
        for ev in events:
            dss, dss_ms, dpos = event_deltas(ev, dt)
            f.write(
                f"{ev.get('tick')},{ev.get('time_s')},{ev.get('step_index')},"
                f"{ev.get('ss_before')},{ev.get('ss_after')},"
                f"{'' if dss is None else dss},"
                f"{'' if dss_ms is None else f'{dss_ms:.3f}'},"
                f"{'' if dpos is None else f'{100*dpos:.4f}'}\n"
            )


def plot_target_panel(ax, times, nom, adp, dim_label, data, upto_idx=None):
    prettify_axis(ax)

    if upto_idx is None:
        upto_idx = len(times) - 1

    sl = slice(0, max(0, upto_idx) + 1)

    ax.plot(
        times[sl], nom[sl],
        color=COLORS["nominal"],
        linestyle="--",
        linewidth=1.8,
        label=f"nominal {dim_label}",
    )
    ax.plot(
        times[sl], adp[sl],
        color=COLORS["adapted"],
        linewidth=2.2,
        label=f"adapted {dim_label}",
    )

    add_push_window(ax, data)
    ax.set_ylabel(f"{dim_label} [m]")
    ax.legend(fontsize=8, frameon=True)


# -----------------------------
# Static dashboard
# -----------------------------

def make_dashboard(data, out_png):
    trace = get_trace(data)
    dt = get_dt(data)
    nominal_plan = get_nominal_plan(data)
    events = get_events(trace)

    times = np.asarray([get_time(r, dt) for r in trace], dtype=float)
    dcm_err = np.asarray([
        float(r.get("dcm_error", np.nan)) if r.get("dcm_error") is not None else np.nan
        for r in trace
    ])
    margins = np.asarray([
        float(r.get("margin", np.nan)) if r.get("margin") is not None else np.nan
        for r in trace
    ])

    target_t, nom_x, nom_y, adp_x, adp_y = build_next_target_series(trace, nominal_plan, events, dt)

    ev_t, dss_vals, dpos_vals = [], [], []
    for ev in events:
        dss, _, dpos = event_deltas(ev, dt)
        ev_t.append(float(ev["tick"]) * dt)
        dss_vals.append(0 if dss is None else dss)
        dpos_vals.append(0 if dpos is None else 100 * dpos)

    fig = plt.figure(figsize=(15, 10), facecolor=COLORS["bg"])
    gs = fig.add_gridspec(3, 2, width_ratios=[1.35, 1.0], height_ratios=[1.0, 1.0, 1.0])

    ax_err = fig.add_subplot(gs[0, 0])
    ax_margin = fig.add_subplot(gs[1, 0])
    ax_updates = fig.add_subplot(gs[2, 0])
    ax_x = fig.add_subplot(gs[0, 1])
    ax_y = fig.add_subplot(gs[1, 1])
    ax_note = fig.add_subplot(gs[2, 1])

    for ax in [ax_err, ax_margin, ax_updates, ax_x, ax_y]:
        prettify_axis(ax)

    ax_err.plot(times, dcm_err, color=COLORS["dcm"], linewidth=2.2)
    add_push_window(ax_err, data)
    for t in ev_t:
        ax_err.axvline(t, color=COLORS["update"], linestyle="--", linewidth=1.2, alpha=0.7)
    ax_err.set_title("DCM error and adapter events", color=COLORS["text"], fontweight="bold")
    ax_err.set_ylabel("DCM error [m]")

    ax_margin.plot(times, margins, color=COLORS["step"], linewidth=2.2)
    ax_margin.axhline(0.0, color=COLORS["muted"], linestyle="--", linewidth=1)
    add_push_window(ax_margin, data)
    for t in ev_t:
        ax_margin.axvline(t, color=COLORS["update"], linestyle="--", linewidth=1.2, alpha=0.7)
    ax_margin.set_title("Viability margin", color=COLORS["text"], fontweight="bold")
    ax_margin.set_ylabel("margin")

    if ev_t:
        width = 0.06
        ax_updates.bar(
            np.asarray(ev_t) - width / 2,
            dss_vals,
            width=width,
            color=COLORS["timing"],
            alpha=0.85,
            label="ΔT [ticks]",
        )
        ax_updates.scatter(
            ev_t,
            dpos_vals,
            color=COLORS["step"],
            s=70,
            marker="x",
            linewidth=2.5,
            label="Δp [cm]",
        )
    add_push_window(ax_updates, data, label=True)
    ax_updates.axhline(0.0, color=COLORS["muted"], linewidth=1)
    ax_updates.set_title("Timing vs footstep update", color=COLORS["text"], fontweight="bold")
    ax_updates.set_ylabel("update magnitude")
    ax_updates.set_xlabel("time [s]")
    ax_updates.legend(frameon=True)

    plot_target_panel(ax_x, target_t, nom_x, adp_x, "next target x", data)
    ax_x.set_title("Next footstep x over time", color=COLORS["text"], fontweight="bold")

    plot_target_panel(ax_y, target_t, nom_y, adp_y, "next target y", data)
    ax_y.set_title("Next footstep y over time", color=COLORS["text"], fontweight="bold")
    ax_y.set_xlabel("time [s]")

    ax_note.axis("off")
    if events:
        ev = events[-1]
        ax_note.text(
            0.04, 0.92,
            update_card_text(ev, dt),
            ha="left", va="top",
            fontsize=11,
            color=COLORS["text"],
            linespacing=1.35,
            bbox=dict(
                boxstyle="round,pad=0.65",
                facecolor="#FFF4E6",
                edgecolor=COLORS["adapted"],
                linewidth=1.5,
                alpha=0.97,
            ),
        )
    else:
        ax_note.text(0.04, 0.92, "No adapter update found.", ha="left", va="top")

    title = (
        f"Reactive adapter update summary  |  profile={data.get('profile')}  "
        f"F={data.get('force_N')}N  dir={data.get('direction')}  "
        f"S{data.get('push_step')} P={data.get('push_phase')}"
    )
    fig.suptitle(title, fontsize=15, color=COLORS["text"], fontweight="bold")
    fig.tight_layout(rect=[0, 0.01, 1, 0.94])
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


# -----------------------------
# Animation
# -----------------------------

def make_animation(data, out_video, fps=8, stride=4):
    trace = get_trace(data)
    if not trace:
        raise RuntimeError("JSON senza trace: rilancia simulation.py con --log-json.")

    dt = get_dt(data)
    nominal_plan = get_nominal_plan(data)
    events = get_events(trace)

    times = np.asarray([get_time(r, dt) for r in trace], dtype=float)
    ticks = np.asarray([get_tick(r) for r in trace], dtype=int)

    com_x, com_y = list_xy(trace, "com", "current_com", "desired_com")
    dcm_x, dcm_y = list_xy(trace, "dcm", "current_dcm")
    zmp_x, zmp_y = list_xy(trace, "zmp", "current_zmp")
    zmp_ref_x, zmp_ref_y = list_xy(trace, "zmp_ref", "desired_zmp")

    dcm_err = np.asarray([
        float(r.get("dcm_error", np.nan)) if r.get("dcm_error") is not None else np.nan
        for r in trace
    ])

    target_t, nom_x, nom_y, adp_x, adp_y = build_next_target_series(trace, nominal_plan, events, dt)

    finite_err = dcm_err[np.isfinite(dcm_err)]
    max_err = max(float(np.max(finite_err)) if len(finite_err) else 0.005, 0.005)

    frame_ids = list(range(0, len(trace), max(1, int(stride))))

    fig = plt.figure(figsize=(16, 9), facecolor=COLORS["bg"])
    gs = fig.add_gridspec(
        4, 2,
        width_ratios=[2.05, 1.0],
        height_ratios=[0.7, 1.0, 1.0, 1.0],
        wspace=0.18,
        hspace=0.32,
    )

    ax_xy = fig.add_subplot(gs[:, 0])
    ax_card = fig.add_subplot(gs[0, 1])
    ax_sig = fig.add_subplot(gs[1, 1])
    ax_x = fig.add_subplot(gs[2, 1])
    ax_y = fig.add_subplot(gs[3, 1])

    def update(k):
        idx = frame_ids[k]
        tick = int(ticks[idx])
        t = float(times[idx])

        for ax in [ax_xy, ax_card, ax_sig, ax_x, ax_y]:
            ax.clear()
            ax.set_facecolor(COLORS["panel"])

        # -------- Left: XY plan --------
        prettify_axis(ax_xy)
        setup_xy_limits(ax_xy, nominal_plan, com_x, com_y, dcm_x, dcm_y)
        ax_xy.set_title("Nominal plan vs adapted plan", color=COLORS["text"], fontweight="bold", fontsize=13)
        ax_xy.set_xlabel("x [m]", color=COLORS["muted"])
        ax_xy.set_ylabel("y [m]", color=COLORS["muted"])

        for s in nominal_plan:
            label = f"N{s['i']}" if s["i"] < 10 else None
            draw_foot(ax_xy, s["x"], s["y"], s["theta"], label=label, mode="nominal")

        adapted = plan_after_events(nominal_plan, events, tick)
        for s in adapted:
            label = f"A{s['i']}" if s["i"] < 10 else None
            draw_foot(ax_xy, s["x"], s["y"], s["theta"], label=label, mode="adapted")

        # Trajectories, if present.
        if np.any(np.isfinite(com_x)):
            ax_xy.plot(com_x[:idx+1], com_y[:idx+1], color=COLORS["com"], linewidth=2.2, label="CoM")
            if np.isfinite(com_x[idx]) and np.isfinite(com_y[idx]):
                ax_xy.scatter(com_x[idx], com_y[idx], color=COLORS["com"], s=50, zorder=10)
        if np.any(np.isfinite(dcm_x)):
            ax_xy.plot(dcm_x[:idx+1], dcm_y[:idx+1], color=COLORS["dcm"], linewidth=1.9, label="DCM")
            if np.isfinite(dcm_x[idx]) and np.isfinite(dcm_y[idx]):
                ax_xy.scatter(dcm_x[idx], dcm_y[idx], color=COLORS["dcm"], s=65, marker="x", zorder=11)
        if np.any(np.isfinite(zmp_x)):
            ax_xy.plot(zmp_x[:idx+1], zmp_y[:idx+1], color=COLORS["zmp"], linewidth=1.3, label="ZMP")
        if np.any(np.isfinite(zmp_ref_x)):
            ax_xy.plot(zmp_ref_x[:idx+1], zmp_ref_y[:idx+1], color=COLORS["zmp_ref"], linestyle="--", linewidth=1.2, label="ZMP ref")

        # Update arrow/points if there is a past event.
        past_events = [ev for ev in events if ev["tick"] <= tick]
        last_ev = past_events[-1] if past_events else None
        if last_ev is not None:
            vals = [
                last_ev.get("target_before_x"), last_ev.get("target_before_y"),
                last_ev.get("target_after_x"), last_ev.get("target_after_y")
            ]
            if all(v is not None for v in vals):
                xb, yb, xa, ya = [float(v) for v in vals]
                ax_xy.scatter([xb], [yb], color=COLORS["nominal"], s=45, zorder=20)
                ax_xy.scatter([xa], [ya], color=COLORS["update"], s=70, zorder=21)
                ax_xy.annotate(
                    "",
                    xy=(xa, ya),
                    xytext=(xb, yb),
                    arrowprops=dict(arrowstyle="->", color=COLORS["update"], linewidth=2.2),
                    zorder=22,
                )

        ax_xy.legend(loc="upper right", fontsize=8, frameon=True)

        # -------- Card: big update info --------
        ax_card.axis("off")
        card_text = update_card_text(last_ev, dt)
        ax_card.text(
            0.04,
            0.95,
            card_text,
            ha="left",
            va="top",
            fontsize=10.5,
            color=COLORS["text"],
            linespacing=1.23,
            bbox=dict(
                boxstyle="round,pad=0.55",
                facecolor="#FFF4E6",
                edgecolor=COLORS["adapted"],
                linewidth=1.5,
                alpha=0.97,
            ),
        )

        # -------- Signal panel --------
        prettify_axis(ax_sig)
        ax_sig.plot(times[:idx+1], dcm_err[:idx+1], color=COLORS["dcm"], linewidth=2.2, label="DCM error")
        add_push_window(ax_sig, data, label=True)

        for ev in events:
            ev_t = float(ev["tick"]) * dt
            if ev["tick"] <= tick:
                dss, _, _ = event_deltas(ev, dt)
                ax_sig.axvline(ev_t, color=COLORS["update"], linestyle="--", linewidth=1.3, alpha=0.8)
                if dss is not None:
                    ax_sig.text(
                        ev_t,
                        max_err * 1.05,
                        f"ΔT={dss:+d}",
                        rotation=90,
                        fontsize=8,
                        color=COLORS["update"],
                        ha="right",
                        va="top",
                    )

        ax_sig.set_xlim(times[0], times[-1])
        ax_sig.set_ylim(0, max_err * 1.25)
        ax_sig.set_title("Trigger signal and timing markers", color=COLORS["text"], fontweight="bold", fontsize=10)
        ax_sig.set_ylabel("DCM error [m]")
        ax_sig.legend(fontsize=8, frameon=True)

        # -------- x(t) and y(t) target panels --------
        plot_target_panel(ax_x, target_t, nom_x, adp_x, "x", data, upto_idx=idx)
        ax_x.set_xlim(times[0], times[-1])
        ax_x.set_title("Next footstep target x(t)", color=COLORS["text"], fontweight="bold", fontsize=10)

        plot_target_panel(ax_y, target_t, nom_y, adp_y, "y", data, upto_idx=idx)
        ax_y.set_xlim(times[0], times[-1])
        ax_y.set_title("Next footstep target y(t)", color=COLORS["text"], fontweight="bold", fontsize=10)
        ax_y.set_xlabel("time [s]")

        fig.suptitle(
            f"Reactive adapter: footstep + timing adaptation  |  t = {t:.2f}s",
            color=COLORS["text"],
            fontsize=16,
            fontweight="bold",
            y=0.985,
        )

    anim = FuncAnimation(fig, update, frames=len(frame_ids), interval=1000 / fps, blit=False)

    out_video = Path(out_video)
    out_video.parent.mkdir(parents=True, exist_ok=True)

    try:
        writer = FFMpegWriter(fps=fps, bitrate=3200)
        anim.save(out_video, writer=writer)
        print(f"[saved] {out_video}")
    except Exception as e:
        gif = out_video.with_suffix(".gif")
        print(f"[warn] mp4 failed: {e}")
        print(f"[saved fallback] {gif}")
        writer = PillowWriter(fps=fps)
        anim.save(gif, writer=writer)

    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path")
    parser.add_argument("--outdir", default="viz_adapter")
    parser.add_argument("--fps", type=int, default=8)
    parser.add_argument("--stride", type=int, default=4)
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args()

    data = load_json(args.json_path)
    trace = get_trace(data)

    ensure_dir(args.outdir)
    stem = Path(args.json_path).stem

    csv_path = Path(args.outdir) / f"{stem}_timing_events.csv"
    dashboard_path = Path(args.outdir) / f"{stem}_timing_dashboard.png"
    video_path = Path(args.outdir) / f"{stem}_timing_animation.mp4"

    save_event_csv(data, trace, csv_path)
    make_dashboard(data, dashboard_path)

    if not args.no_video:
        make_animation(data, video_path, fps=args.fps, stride=args.stride)

    print(f"[saved] {csv_path}")
    print(f"[saved] {dashboard_path}")


if __name__ == "__main__":
    main()
