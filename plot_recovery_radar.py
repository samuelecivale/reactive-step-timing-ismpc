import os
import glob
import json
import math
import argparse

import numpy as np
import matplotlib.pyplot as plt


def load_rows(logdirs):
    rows = []
    seen = set()

    for logdir in logdirs:
        for path in sorted(glob.glob(os.path.join(logdir, "*.json"))):
            if path in seen:
                continue
            seen.add(path)

            try:
                with open(path, "r") as f:
                    d = json.load(f)
            except Exception:
                continue

            rows.append({
                "path": path,
                "name": os.path.basename(path).replace(".json", ""),
                "fell": bool(d.get("fell", True)),
                "force": float(d.get("force_N", 0.0) or 0.0),
                "phase": float(d.get("push_phase", 0.0) or 0.0),
                "adapt": bool(d.get("adapt_enabled", False)),
                "profile": d.get("profile", "?"),
                "direction": d.get("direction", "?"),
                "duration": float(d.get("duration_s", 0.0) or 0.0),
                "push_step": int(d.get("push_step", -1) or -1),
            })

    return rows


def classify_case(r):
    profile = r["profile"]
    direction = r["direction"]
    step = r["push_step"]
    duration = r["duration"]
    phase = r["phase"]

    # Long push
    if duration >= 0.19:
        if direction == "left" and step == 3:
            return "Long L-S3"
        if direction == "right" and step == 4:
            return "Long R-S4"

    # Paper-style
    if phase <= 0.06:
        if profile == "forward" and direction == "left" and step == 3:
            return "Paper L-S3"
        if profile == "forward" and direction == "right" and step == 4:
            return "Paper R-S4"
        if profile == "inplace" and direction == "left" and step == 3:
            return "Paper Inplace L-S3"

    # In-place
    if profile == "inplace":
        if direction == "left" and step == 3:
            return "Inplace L-S3"
        if direction == "right" and step == 4:
            return "Inplace R-S4"

    # Forward walking with lateral pushes
    if profile == "forward" and direction == "left" and step == 3:
        return "Forward L-S3"
    if profile == "forward" and direction == "right" and step == 4:
        return "Forward R-S4"

    # Forward walking with forward/backward pushes
    if profile == "forward" and direction == "forward" and step == 3:
        return "Push Fwd S3"
    if profile == "forward" and direction == "forward" and step == 4:
        return "Push Fwd S4"
    if profile == "forward" and direction == "backward" and step == 3:
        return "Push Bwd S3"
    if profile == "forward" and direction == "backward" and step == 4:
        return "Push Bwd S4"

    return None


def compute_max_recovered(rows):
    categories = [
        "Forward L-S3",
        "Forward R-S4",
        "Push Fwd S3",
        "Push Fwd S4",
        "Push Bwd S3",
        "Push Bwd S4",
        "Inplace L-S3",
        "Inplace R-S4",
        "Long L-S3",
        "Long R-S4",
        "Paper L-S3",
        "Paper R-S4",
        "Paper Inplace L-S3",
    ]

    baseline = {c: 0.0 for c in categories}
    adapted = {c: 0.0 for c in categories}

    for r in rows:
        cat = classify_case(r)
        if cat is None or cat not in baseline:
            continue

        if not r["fell"]:
            if r["adapt"]:
                adapted[cat] = max(adapted[cat], r["force"])
            else:
                baseline[cat] = max(baseline[cat], r["force"])

    return categories, baseline, adapted


def radar_plot(categories, baseline, adapted, out_png="recovery_radar.png"):
    values_base = [baseline[c] for c in categories]
    values_adpt = [adapted[c] for c in categories]

    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()

    values_base += values_base[:1]
    values_adpt += values_adpt[:1]
    angles += angles[:1]

    fig = plt.figure(figsize=(10, 10))
    ax = plt.subplot(111, polar=True)

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)

    plt.xticks(angles[:-1], categories, fontsize=10)
    ax.set_rlabel_position(0)

    max_force = max(max(values_base), max(values_adpt), 10)
    rmax = int(math.ceil(max_force / 5.0) * 5)
    ax.set_ylim(0, rmax)

    rticks = list(range(5, rmax + 1, 5))
    plt.yticks(rticks, [str(t) for t in rticks], fontsize=9)

    ax.plot(angles, values_base, linewidth=2, label="Baseline")
    ax.fill(angles, values_base, alpha=0.15)

    ax.plot(angles, values_adpt, linewidth=2, label="Adapted")
    ax.fill(angles, values_adpt, alpha=0.15)

    for angle, val in zip(angles[:-1], values_base[:-1]):
        ax.text(angle, val + 0.8, f"{val:.0f}", fontsize=8, ha="center", va="center")

    for angle, val in zip(angles[:-1], values_adpt[:-1]):
        ax.text(angle, val + 2.0, f"{val:.0f}", fontsize=8, ha="center", va="center")

    plt.title("Maximum Recoverable Force by Scenario", size=14, pad=20)
    plt.legend(loc="upper right", bbox_to_anchor=(1.2, 1.1))
    plt.tight_layout()
    plt.savefig(out_png, dpi=200)
    print(f"[saved] {out_png}")


def bar_plot(categories, baseline, adapted, out_png="recovery_bar.png"):
    x = np.arange(len(categories))
    base_vals = [baseline[c] for c in categories]
    adpt_vals = [adapted[c] for c in categories]

    fig = plt.figure(figsize=(14, 6))
    ax = fig.add_subplot(111)

    width = 0.38
    ax.bar(x - width / 2, base_vals, width, label="Baseline")
    ax.bar(x + width / 2, adpt_vals, width, label="Adapted")

    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=35, ha="right")
    ax.set_ylabel("Max recovered force [N]")
    ax.set_title("Maximum Recoverable Force by Scenario")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_png, dpi=200)
    print(f"[saved] {out_png}")


def print_summary(categories, baseline, adapted):
    print("\nMAX RECOVERABLE FORCE")
    print("-" * 60)
    for c in categories:
        b = baseline[c]
        a = adapted[c]
        delta = a - b
        print(f"{c:20s}  base={b:5.1f} N   adapt={a:5.1f} N   delta={delta:+5.1f} N")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("logdirs", nargs="+", help="One or more log directories")
    args = parser.parse_args()

    rows = load_rows(args.logdirs)
    categories, baseline, adapted = compute_max_recovered(rows)

    print_summary(categories, baseline, adapted)
    radar_plot(categories, baseline, adapted, out_png="recovery_radar.png")
    bar_plot(categories, baseline, adapted, out_png="recovery_bar.png")


if __name__ == "__main__":
    main()
