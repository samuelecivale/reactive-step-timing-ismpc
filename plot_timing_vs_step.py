#!/usr/bin/env python3
import argparse
import csv
import json
import math
import os

import matplotlib.pyplot as plt


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def get_update_events(data):
    dt = data.get("push_window", {}).get("dt", 0.01)
    trace = data.get("trace", [])

    events = []

    for r in trace:
        if not r.get("adapter_updated", False):
            continue

        ss_before = r.get("ss_before")
        ss_after = r.get("ss_after")

        xb = r.get("target_before_x")
        yb = r.get("target_before_y")
        xa = r.get("target_after_x")
        ya = r.get("target_after_y")

        if ss_before is None or ss_after is None:
            continue
        if xb is None or yb is None or xa is None or ya is None:
            continue

        dss_ticks = int(ss_after) - int(ss_before)
        dss_seconds = dss_ticks * dt

        dx = float(xa) - float(xb)
        dy = float(ya) - float(yb)
        dpos = math.sqrt(dx * dx + dy * dy)

        events.append({
            "tick": int(r["tick"]),
            "time_s": float(r["time_s"]),
            "step_index": r.get("step_index"),
            "ss_before": int(ss_before),
            "ss_after": int(ss_after),
            "dss_ticks": dss_ticks,
            "dss_seconds": dss_seconds,
            "dss_ms": dss_seconds * 1000.0,
            "target_before_x": float(xb),
            "target_before_y": float(yb),
            "target_after_x": float(xa),
            "target_after_y": float(ya),
            "dx": dx,
            "dy": dy,
            "dpos": dpos,
        })

    return events


def add_push_window(ax, data):
    pw = data.get("push_window", {})
    dt = pw.get("dt")
    start = pw.get("start_tick")
    end = pw.get("end_tick")

    if dt is None or start is None or end is None:
        return

    ax.axvspan(start * dt, end * dt, alpha=0.18, label="push window")


def make_timing_timeline(data):
    trace = data.get("trace", [])
    if not trace:
        return [], []

    current_ss = None

    for r in trace:
        if r.get("ss_before") is not None:
            current_ss = r["ss_before"]
            break

    if current_ss is None:
        current_ss = 70

    times = []
    ss_values = []

    for r in trace:
        times.append(float(r["time_s"]))

        if r.get("adapter_updated") and r.get("ss_after") is not None:
            current_ss = int(r["ss_after"])

        ss_values.append(current_ss)

    return times, ss_values


def save_csv(events, out_csv):
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "tick",
                "time_s",
                "step_index",
                "ss_before",
                "ss_after",
                "dss_ticks",
                "dss_ms",
                "target_before_x",
                "target_before_y",
                "target_after_x",
                "target_after_y",
                "dx",
                "dy",
                "dpos",
            ],
        )
        writer.writeheader()
        for e in events:
            writer.writerow(e)


def plot_timing_vs_step(data, events, out_png):
    times, ss_values = make_timing_timeline(data)

    fig = plt.figure(figsize=(13, 9))

    ax1 = fig.add_subplot(3, 1, 1)
    ax2 = fig.add_subplot(3, 1, 2)
    ax3 = fig.add_subplot(3, 1, 3)

    # 1. Timing timeline
    if times:
        ax1.step(times, ss_values, where="post", linewidth=2)
    add_push_window(ax1, data)
    ax1.set_ylabel("ss_duration [ticks]")
    ax1.set_title("Timing adaptation: current single-support duration")
    ax1.grid(True, alpha=0.3)

    # 2. Timing delta at update instants
    ev_times = [e["time_s"] for e in events]
    dss = [e["dss_ticks"] for e in events]

    ax2.axhline(0.0, linestyle="--", linewidth=1)
    if events:
        ax2.bar(ev_times, dss, width=0.08)
        for t, v in zip(ev_times, dss):
            ax2.text(t, v, f"{v:+d}", ha="center", va="bottom" if v >= 0 else "top", fontsize=9)

    add_push_window(ax2, data)
    ax2.set_ylabel("Δ timing [ticks]")
    ax2.set_title("Timing change at each adapter update")
    ax2.grid(True, alpha=0.3)

    # 3. Step displacement at update instants
    dpos = [e["dpos"] for e in events]
    dy = [e["dy"] for e in events]

    if events:
        ax3.bar(ev_times, dpos, width=0.08, label="step displacement norm")
        ax3.scatter(ev_times, [abs(v) for v in dy], marker="x", label="abs lateral displacement")
        for t, v in zip(ev_times, dpos):
            ax3.text(t, v, f"{v:.3f}m", ha="center", va="bottom", fontsize=9)

    add_push_window(ax3, data)
    ax3.set_xlabel("time [s]")
    ax3.set_ylabel("Δ step [m]")
    ax3.set_title("Footstep location change at each adapter update")
    ax3.grid(True, alpha=0.3)
    ax3.legend()

    title = (
        f"{data.get('profile')} | adapt={data.get('adapt_enabled')} | "
        f"F={data.get('force_N')}N | dir={data.get('direction')} | "
        f"S{data.get('push_step')} P={data.get('push_phase')}"
    )

    fig.suptitle(title, fontsize=14)
    fig.tight_layout()
    fig.savefig(out_png, dpi=200)
    plt.close(fig)


def print_summary(events):
    if not events:
        print("[info] Nessun adapter update trovato nel JSON.")
        return

    print("\nADAPTER UPDATES")
    print("-" * 90)

    for e in events:
        kind = []

        if e["dss_ticks"] != 0:
            kind.append("TIMING")
        if e["dpos"] > 1e-6:
            kind.append("STEP")

        if not kind:
            kind.append("NO EFFECT")

        print(
            f"t={e['time_s']:.2f}s tick={e['tick']} step={e['step_index']} | "
            f"ss {e['ss_before']} -> {e['ss_after']} "
            f"({e['dss_ticks']:+d} ticks, {e['dss_ms']:+.1f} ms) | "
            f"step Δ={e['dpos']:.4f} m "
            f"(dx={e['dx']:+.4f}, dy={e['dy']:+.4f}) | "
            f"{'+'.join(kind)}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path")
    parser.add_argument("--outdir", default="viz_adapter")
    args = parser.parse_args()

    data = load_json(args.json_path)
    ensure_dir(args.outdir)

    stem = os.path.splitext(os.path.basename(args.json_path))[0]

    events = get_update_events(data)

    out_png = os.path.join(args.outdir, f"{stem}_timing_vs_step.png")
    out_csv = os.path.join(args.outdir, f"{stem}_timing_vs_step.csv")

    plot_timing_vs_step(data, events, out_png)
    save_csv(events, out_csv)
    print_summary(events)

    print(f"\n[saved] {out_png}")
    print(f"[saved] {out_csv}")


if __name__ == "__main__":
    main()
