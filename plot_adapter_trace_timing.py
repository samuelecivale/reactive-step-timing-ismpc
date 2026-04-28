#!/usr/bin/env python3
"""
plot_adapter_trace_timing.py

Genera un MP4/GIF a partire dal JSON prodotto da simulation.py --log-json.
È pensato per mostrare insieme:
  - piano nominale vs piano adattato
  - traiettoria CoM/DCM/ZMP se disponibile nella trace ricca
  - push window
  - cambio del passo
  - cambio del timing ss_before -> ss_after

Uso:
  python simulation.py --headless --steps 1000 \
    --adapt --timing-biased \
    --profile forward \
    --force 46 --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base \
    --log-json logs_viz/fwd_timing_hybrid_F46_P055_left_S3.json

  python plot_adapter_trace_timing.py logs_viz/fwd_timing_hybrid_F46_P055_left_S3.json \
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


FOOT_LENGTH = 0.22
FOOT_WIDTH = 0.11


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
    """
    Prova più formati possibili:
      row["com"] = [x, y, z]
      row["com_x"], row["com_y"]
      row["current_com_x"], ...
    """
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


def list_xy(trace, dt, *names):
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


def get_nominal_plan(data):
    plan = data.get("nominal_plan")
    if isinstance(plan, list) and plan:
        return normalize_plan(plan)

    # fallback: a volte è dentro metadata o non c'è
    return []


def get_active_plan(data):
    plan = data.get("final_adapted_plan") or data.get("adapted_plan") or data.get("active_plan")
    if isinstance(plan, list) and plan:
        return normalize_plan(plan)
    return []


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
    if not plan:
        return []

    for ev in events:
        if ev["tick"] > tick:
            continue
        step_index = ev.get("step_index")
        if step_index is None:
            continue

        # In questo progetto l'evento modifica ss_duration dello step corrente
        # e target position dello step successivo.
        try:
            step_index = int(step_index)
        except Exception:
            continue

        ss_after = ev.get("ss_after")
        if ss_after is not None and 0 <= step_index < len(plan):
            plan[step_index]["ss"] = int(ss_after)

        xa = ev.get("target_after_x")
        ya = ev.get("target_after_y")
        target_idx = step_index + 1
        if xa is not None and ya is not None and 0 <= target_idx < len(plan):
            plan[target_idx]["x"] = float(xa)
            plan[target_idx]["y"] = float(ya)

    return plan


def draw_foot(ax, x, y, theta=0.0, label=None, mode="nominal"):
    if x is None or y is None or np.isnan(x) or np.isnan(y):
        return

    if mode == "nominal":
        edgecolor = "0.45"
        facecolor = "none"
        linestyle = "--"
        linewidth = 1.2
        alpha = 0.65
        zorder = 2
    elif mode == "adapted":
        edgecolor = "tab:red"
        facecolor = "mistyrose"
        linestyle = "-"
        linewidth = 2.0
        alpha = 0.90
        zorder = 4
    else:
        edgecolor = "tab:blue"
        facecolor = "aliceblue"
        linestyle = "-"
        linewidth = 2.0
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
        ax.text(x, y, label, fontsize=7, ha="center", va="center", zorder=zorder + 1)


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


def add_push_window(ax, data):
    pw = data.get("push_window", {}) or {}
    dt = pw.get("dt", None)
    s = pw.get("start_tick", None)
    e = pw.get("end_tick", None)
    if dt is None or s is None or e is None:
        return
    ax.axvspan(float(s) * float(dt), float(e) * float(dt), alpha=0.18, label="push")


def event_delta_text(ev, dt):
    parts = []
    if ev.get("ss_before") is not None and ev.get("ss_after") is not None:
        dss = int(ev["ss_after"]) - int(ev["ss_before"])
        parts.append(f"ΔT={dss:+d} ticks ({dss * dt * 1000:+.0f} ms)")
        parts.append(f"ss:{int(ev['ss_before'])}->{int(ev['ss_after'])}")

    vals = [ev.get("target_before_x"), ev.get("target_before_y"), ev.get("target_after_x"), ev.get("target_after_y")]
    if all(v is not None for v in vals):
        xb, yb, xa, ya = [float(v) for v in vals]
        dpos = math.sqrt((xa - xb) ** 2 + (ya - yb) ** 2)
        parts.append(f"Δp={100*dpos:.1f} cm")
    return "\n".join(parts)


def save_event_csv(data, trace, out_csv):
    dt = get_dt(data)
    events = get_events(trace)
    with open(out_csv, "w") as f:
        f.write("tick,time_s,step,ss_before,ss_after,dss_ticks,dss_ms,dpos_cm\n")
        for ev in events:
            dss = ""
            dss_ms = ""
            if ev.get("ss_before") is not None and ev.get("ss_after") is not None:
                dss_i = int(ev["ss_after"]) - int(ev["ss_before"])
                dss = str(dss_i)
                dss_ms = f"{dss_i * dt * 1000:.3f}"
            dpos_cm = ""
            vals = [ev.get("target_before_x"), ev.get("target_before_y"), ev.get("target_after_x"), ev.get("target_after_y")]
            if all(v is not None for v in vals):
                xb, yb, xa, ya = [float(v) for v in vals]
                dpos_cm = f"{100*math.sqrt((xa-xb)**2+(ya-yb)**2):.4f}"
            f.write(f"{ev.get('tick')},{ev.get('time_s')},{ev.get('step_index')},{ev.get('ss_before')},{ev.get('ss_after')},{dss},{dss_ms},{dpos_cm}\n")


def make_dashboard(data, out_png):
    trace = get_trace(data)
    dt = get_dt(data)
    events = get_events(trace)

    times = np.asarray([get_time(r, dt) for r in trace], dtype=float)
    dcm_err = np.asarray([float(r.get("dcm_error", np.nan)) if r.get("dcm_error") is not None else np.nan for r in trace])
    margins = np.asarray([float(r.get("margin", np.nan)) if r.get("margin") is not None else np.nan for r in trace])

    fig, axs = plt.subplots(3, 1, figsize=(12, 8), sharex=True)

    axs[0].plot(times, dcm_err, linewidth=2)
    add_push_window(axs[0], data)
    axs[0].set_ylabel("DCM error [m]")
    axs[0].grid(True, alpha=0.3)

    axs[1].plot(times, margins, linewidth=2)
    axs[1].axhline(0.0, linestyle="--", linewidth=1)
    add_push_window(axs[1], data)
    axs[1].set_ylabel("margin")
    axs[1].grid(True, alpha=0.3)

    ev_t = []
    dss_vals = []
    dpos_vals = []
    for ev in events:
        t = float(ev["tick"]) * dt
        ev_t.append(t)
        if ev.get("ss_before") is not None and ev.get("ss_after") is not None:
            dss_vals.append(int(ev["ss_after"]) - int(ev["ss_before"]))
        else:
            dss_vals.append(0)
        vals = [ev.get("target_before_x"), ev.get("target_before_y"), ev.get("target_after_x"), ev.get("target_after_y")]
        if all(v is not None for v in vals):
            xb, yb, xa, ya = [float(v) for v in vals]
            dpos_vals.append(100 * math.sqrt((xa - xb) ** 2 + (ya - yb) ** 2))
        else:
            dpos_vals.append(0)

    if ev_t:
        axs[2].bar(ev_t, dss_vals, width=0.06, label="ΔT [ticks]")
        axs[2].scatter(ev_t, dpos_vals, marker="x", label="Δp [cm]")
    add_push_window(axs[2], data)
    axs[2].set_ylabel("updates")
    axs[2].set_xlabel("time [s]")
    axs[2].legend()
    axs[2].grid(True, alpha=0.3)

    title = (
        f"Timing + footstep adaptation | profile={data.get('profile')} "
        f"F={data.get('force_N')}N dir={data.get('direction')} "
        f"S{data.get('push_step')} P={data.get('push_phase')}"
    )
    fig.suptitle(title, fontsize=14)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def make_animation(data, out_video, fps=8, stride=4):
    trace = get_trace(data)
    if not trace:
        raise RuntimeError("JSON senza trace: rilancia simulation.py con --log-json dopo la patch di rich trace.")

    dt = get_dt(data)
    nominal_plan = get_nominal_plan(data)
    events = get_events(trace)

    times = np.asarray([get_time(r, dt) for r in trace], dtype=float)
    ticks = np.asarray([get_tick(r) for r in trace], dtype=int)

    com_x, com_y = list_xy(trace, dt, "com", "current_com", "desired_com")
    dcm_x, dcm_y = list_xy(trace, dt, "dcm", "current_dcm")
    zmp_x, zmp_y = list_xy(trace, dt, "zmp", "current_zmp")
    zmp_ref_x, zmp_ref_y = list_xy(trace, dt, "zmp_ref", "desired_zmp")

    dcm_err = np.asarray([float(r.get("dcm_error", np.nan)) if r.get("dcm_error") is not None else np.nan for r in trace])
    frame_ids = list(range(0, len(trace), max(1, int(stride))))

    fig = plt.figure(figsize=(15, 8))
    gs = fig.add_gridspec(2, 2, width_ratios=[2.0, 1.15], height_ratios=[1.0, 1.0])

    ax_xy = fig.add_subplot(gs[:, 0])
    ax_sig = fig.add_subplot(gs[0, 1])
    ax_info = fig.add_subplot(gs[1, 1])

    max_err = np.nanmax(dcm_err) if np.any(np.isfinite(dcm_err)) else 0.01
    max_err = max(max_err, 0.005)

    def update(k):
        idx = frame_ids[k]
        tick = ticks[idx]
        t = times[idx]

        ax_xy.clear()
        ax_sig.clear()
        ax_info.clear()
        ax_info.axis("off")

        setup_xy_limits(ax_xy, nominal_plan, com_x, com_y, dcm_x, dcm_y)
        ax_xy.set_title("Nominal plan vs adapted plan")
        ax_xy.set_xlabel("x [m]")
        ax_xy.set_ylabel("y [m]")
        ax_xy.grid(True, alpha=0.25)

        # Nominal footprints
        for s in nominal_plan:
            draw_foot(ax_xy, s["x"], s["y"], s["theta"], label=f"N{s['i']}", mode="nominal")

        # Adapted plan up to current tick
        adapted = plan_after_events(nominal_plan, events, tick)
        for s in adapted:
            draw_foot(ax_xy, s["x"], s["y"], s["theta"], label=f"A{s['i']}", mode="adapted")

        # Trajectories if available
        if np.any(np.isfinite(com_x)):
            ax_xy.plot(com_x[:idx+1], com_y[:idx+1], linewidth=2.0, label="CoM")
            ax_xy.scatter(com_x[idx], com_y[idx], s=45, zorder=10)
        if np.any(np.isfinite(dcm_x)):
            ax_xy.plot(dcm_x[:idx+1], dcm_y[:idx+1], linewidth=1.8, label="DCM")
            ax_xy.scatter(dcm_x[idx], dcm_y[idx], s=55, marker="x", zorder=11)
        if np.any(np.isfinite(zmp_x)):
            ax_xy.plot(zmp_x[:idx+1], zmp_y[:idx+1], linewidth=1.3, label="ZMP")
        if np.any(np.isfinite(zmp_ref_x)):
            ax_xy.plot(zmp_ref_x[:idx+1], zmp_ref_y[:idx+1], "--", linewidth=1.2, label="ZMP ref")

        # Update annotations currently active / latest
        past_events = [ev for ev in events if ev["tick"] <= tick]
        last_ev = past_events[-1] if past_events else None
        if last_ev is not None:
            txt = event_delta_text(last_ev, dt)
            ax_xy.text(
                0.02, 0.98,
                "LAST ADAPTER UPDATE\n" + txt,
                transform=ax_xy.transAxes,
                ha="left", va="top",
                fontsize=11,
                bbox=dict(boxstyle="round", facecolor="white", edgecolor="tab:red", alpha=0.9),
            )

        ax_xy.legend(loc="upper right", fontsize=8)

        # DCM error timeline + update markers
        ax_sig.plot(times[:idx+1], dcm_err[:idx+1], linewidth=2, label="DCM error")
        add_push_window(ax_sig, data)

        for ev in events:
            ev_t = float(ev["tick"]) * dt
            if ev["tick"] <= tick:
                ax_sig.axvline(ev_t, linestyle="--", linewidth=1.2, alpha=0.7)
                if ev.get("ss_before") is not None and ev.get("ss_after") is not None:
                    dss = int(ev["ss_after"]) - int(ev["ss_before"])
                    ax_sig.text(ev_t, max_err * 0.90, f"ΔT={dss:+d}", rotation=90,
                                fontsize=8, ha="right", va="top")

        ax_sig.set_xlim(times[0], times[-1])
        ax_sig.set_ylim(0, max_err * 1.25)
        ax_sig.set_title("Trigger signal and timing updates")
        ax_sig.set_ylabel("DCM error [m]")
        ax_sig.grid(True, alpha=0.3)
        ax_sig.legend(fontsize=8)

        # Info panel
        lines = [
            f"tick: {tick}",
            f"time: {t:.2f} s",
            f"profile: {data.get('profile')}",
            f"force: {data.get('force_N')} N",
            f"direction: {data.get('direction')}",
            f"push step: {data.get('push_step')}",
            f"push phase: {data.get('push_phase')}",
            "",
            f"adapter updates so far: {len(past_events)}",
        ]

        if last_ev:
            if last_ev.get("ss_before") is not None and last_ev.get("ss_after") is not None:
                dss = int(last_ev["ss_after"]) - int(last_ev["ss_before"])
                lines += [
                    "",
                    "Last timing update:",
                    f"  ss: {int(last_ev['ss_before'])} -> {int(last_ev['ss_after'])}",
                    f"  ΔT: {dss:+d} ticks = {dss * dt * 1000:+.0f} ms",
                ]

            vals = [last_ev.get("target_before_x"), last_ev.get("target_before_y"), last_ev.get("target_after_x"), last_ev.get("target_after_y")]
            if all(v is not None for v in vals):
                xb, yb, xa, ya = [float(v) for v in vals]
                dpos = math.sqrt((xa - xb) ** 2 + (ya - yb) ** 2)
                lines += [
                    "",
                    "Last footstep update:",
                    f"  before: ({xb:.3f}, {yb:.3f})",
                    f"  after:  ({xa:.3f}, {ya:.3f})",
                    f"  Δp: {100*dpos:.1f} cm",
                ]

        ax_info.text(
            0.02, 0.98,
            "\n".join(lines),
            ha="left", va="top",
            fontsize=10,
            family="monospace",
        )

        fig.suptitle(
            f"Reactive adapter: timing + footstep update | t={t:.2f}s",
            fontsize=15,
            fontweight="bold",
        )
        fig.tight_layout()

    anim = FuncAnimation(fig, update, frames=len(frame_ids), interval=1000 / fps, blit=False)

    out_video = Path(out_video)
    out_video.parent.mkdir(parents=True, exist_ok=True)

    try:
        writer = FFMpegWriter(fps=fps, bitrate=3000)
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
