#!/usr/bin/env python3
"""
plot_better_recovery_radar.py

Cleaner recovery-frontier plots for the IS-MPC reactive step timing project.

Main improvement over the previous radar:
- it does NOT plot untested categories as 0 N;
- it can compare baseline, default adapter, and timing-biased adapter;
- it writes a CSV table with the values used in the plots;
- it produces both a radar plot and a grouped bar plot.

Typical usage:

  # Compare old logs_final against timing-biased full battery
  python plot_better_recovery_radar.py \
    --logs logs_final logs_timing_biased_full \
    --outdir plots_better

  # Focus only on canonical phase P=0.55 and short pushes
  python plot_better_recovery_radar.py \
    --logs logs_final logs_timing_biased_full \
    --phase 0.55 \
    --duration 0.10 \
    --outdir plots_better_p055

  # H subset only
  python plot_better_recovery_radar.py \
    --logs logs_timing_weights \
    --outdir plots_better_H

Notes:
- "max recoverable force" = maximum tested force where fell == false.
- If a category is not tested for a variant, it is excluded from the radar
  comparison instead of being silently treated as 0.
"""

import argparse
import csv
import glob
import json
import math
import os
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np


Variant = str
Category = str


CATEGORY_ORDER = [
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
    "Paper Inplace R-S4",
]

VARIANT_ORDER = ["base", "default", "timing-biased"]


def almost_equal(a: Optional[float], b: Optional[float], eps: float = 1e-9) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= eps


def get_first(d: dict, keys: List[str], default=None):
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


def infer_variant(name: str, d: dict, source_dir: str) -> Variant:
    low = (name + " " + source_dir).lower()

    if "timing_biased" in low or "_biased_" in low or "time_biased" in low:
        return "timing-biased"

    # Some H logs use names like H_time_biased_...
    if "biased" in low:
        return "timing-biased"

    if bool(d.get("adapt_enabled", False)):
        return "default"

    return "base"


def infer_category(d: dict) -> Optional[Category]:
    profile = str(get_first(d, ["profile", "walk_profile"], "forward"))
    direction = str(get_first(d, ["direction"], ""))
    step = get_first(d, ["push_step"], None)
    phase = float(get_first(d, ["push_phase"], -1.0))
    duration = float(get_first(d, ["duration_s", "duration"], 0.10))

    if step is None:
        return None

    try:
        step_int = int(step)
    except Exception:
        return None

    # Paper-style early push
    is_paper = almost_equal(phase, 0.05)
    is_long = duration >= 0.19

    if profile == "inplace":
        if is_paper:
            if direction == "left":
                return "Paper Inplace L-S3"
            if direction == "right":
                return "Paper Inplace R-S4"
        if direction == "left":
            return "Inplace L-S3"
        if direction == "right":
            return "Inplace R-S4"
        return None

    if profile == "forward":
        if is_paper:
            if direction == "left":
                return "Paper L-S3"
            if direction == "right":
                return "Paper R-S4"
            return None

        if is_long:
            if direction == "left":
                return "Long L-S3"
            if direction == "right":
                return "Long R-S4"
            return None

        if direction == "left":
            return "Forward L-S3"
        if direction == "right":
            return "Forward R-S4"
        if direction == "forward":
            return f"Push Fwd S{step_int}"
        if direction == "backward":
            return f"Push Bwd S{step_int}"

    return None


def load_rows(log_dirs: List[str], phase_filter: Optional[float], duration_filter: Optional[float]) -> List[dict]:
    rows = []

    for log_dir in log_dirs:
        for path in sorted(glob.glob(os.path.join(log_dir, "*.json"))):
            name = os.path.basename(path).replace(".json", "")

            try:
                with open(path, "r") as f:
                    d = json.load(f)
            except Exception as exc:
                print(f"[WARN] cannot read {path}: {exc}")
                continue

            force = get_first(d, ["force_N", "force"], None)
            phase = get_first(d, ["push_phase"], None)
            duration = get_first(d, ["duration_s", "duration"], None)

            if force is None or phase is None or duration is None:
                continue

            force = float(force)
            phase = float(phase)
            duration = float(duration)

            if phase_filter is not None and not almost_equal(phase, phase_filter):
                continue

            if duration_filter is not None and not almost_equal(duration, duration_filter):
                continue

            category = infer_category(d)
            if category is None:
                continue

            variant = infer_variant(name, d, log_dir)

            rows.append({
                "name": name,
                "source_dir": log_dir,
                "variant": variant,
                "category": category,
                "force": force,
                "phase": phase,
                "duration": duration,
                "fell": bool(d.get("fell", False)),
                "ticks": d.get("ticks"),
                "updates": get_first(d.get("adapter", {}), ["updates"], 0),
                "qp_failures": get_first(d.get("adapter", {}), ["qp_failures"], 0),
                "max_dcm_error": get_first(d.get("adapter", {}), ["max_dcm_error"], 0.0),
            })

    return rows


def summarize(rows: List[dict]) -> Dict[Tuple[Category, Variant], dict]:
    grouped = defaultdict(list)
    for r in rows:
        grouped[(r["category"], r["variant"])].append(r)

    summary = {}

    for key, group in grouped.items():
        tested_forces = [r["force"] for r in group]
        success_forces = [r["force"] for r in group if not r["fell"]]

        summary[key] = {
            "n": len(group),
            "n_success": len(success_forces),
            "n_fail": len(group) - len(success_forces),
            "max_tested_force": max(tested_forces) if tested_forces else None,
            "max_recoverable_force": max(success_forces) if success_forces else 0.0,
            "tested_forces": sorted(set(tested_forces)),
            "success_forces": sorted(set(success_forces)),
        }

    return summary


def ordered_categories(summary: Dict[Tuple[Category, Variant], dict], require_variants: List[Variant]) -> List[Category]:
    available = sorted({cat for cat, _ in summary.keys()}, key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 999)

    kept = []
    for cat in available:
        if all((cat, v) in summary for v in require_variants):
            kept.append(cat)

    return kept


def write_csv(summary: Dict[Tuple[Category, Variant], dict], categories: List[Category], out_csv: str):
    with open(out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "category",
            "variant",
            "max_recoverable_force",
            "max_tested_force",
            "n_success",
            "n_total",
            "tested_forces",
            "success_forces",
        ])

        for cat in categories:
            for variant in VARIANT_ORDER:
                s = summary.get((cat, variant))
                if not s:
                    continue
                writer.writerow([
                    cat,
                    variant,
                    s["max_recoverable_force"],
                    s["max_tested_force"],
                    s["n_success"],
                    s["n"],
                    " ".join(str(x) for x in s["tested_forces"]),
                    " ".join(str(x) for x in s["success_forces"]),
                ])


def plot_radar(summary: Dict[Tuple[Category, Variant], dict], categories: List[Category], variants: List[Variant], out_path: str, title: str):
    if len(categories) < 3:
        print("[WARN] radar plot needs at least 3 categories; skipping radar")
        return

    angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False)
    angles_closed = np.concatenate([angles, [angles[0]]])

    fig = plt.figure(figsize=(11, 9))
    ax = plt.subplot(111, polar=True)

    max_value = 0.0

    for variant in variants:
        values = []
        for cat in categories:
            s = summary.get((cat, variant))
            values.append(float(s["max_recoverable_force"]) if s else np.nan)

        if all(np.isnan(v) for v in values):
            continue

        values_closed = np.concatenate([values, [values[0]]])
        finite_vals = [v for v in values if not np.isnan(v)]
        if finite_vals:
            max_value = max(max_value, max(finite_vals))

        ax.plot(angles_closed, values_closed, linewidth=2, marker="o", label=variant)
        ax.fill(angles_closed, values_closed, alpha=0.08)

    ax.set_xticks(angles)
    ax.set_xticklabels(categories, fontsize=9)

    radial_max = max(10.0, math.ceil((max_value + 5.0) / 10.0) * 10.0)
    ax.set_ylim(0, radial_max)

    ax.set_title(title, pad=25, fontsize=14)
    ax.legend(loc="upper right", bbox_to_anchor=(1.20, 1.15))
    ax.grid(True)

    plt.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)

    print(f"[saved] {out_path}")


def plot_bar(summary: Dict[Tuple[Category, Variant], dict], categories: List[Category], variants: List[Variant], out_path: str, title: str):
    x = np.arange(len(categories))
    width = 0.8 / max(1, len(variants))

    fig = plt.figure(figsize=(max(12, len(categories) * 0.9), 7))
    ax = plt.gca()

    for i, variant in enumerate(variants):
        values = []
        for cat in categories:
            s = summary.get((cat, variant))
            values.append(float(s["max_recoverable_force"]) if s else np.nan)

        offset = (i - (len(variants) - 1) / 2) * width
        ax.bar(x + offset, values, width, label=variant)

    ax.set_title(title, fontsize=14)
    ax.set_ylabel("Max recoverable force [N]")
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=30, ha="right")
    ax.legend()
    ax.grid(axis="y", alpha=0.35)

    plt.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)

    print(f"[saved] {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", nargs="+", required=True, help="One or more log directories containing JSON files")
    parser.add_argument("--outdir", default="plots_better", help="Output directory")
    parser.add_argument("--phase", type=float, default=None, help="Optional push phase filter, e.g. 0.55")
    parser.add_argument("--duration", type=float, default=None, help="Optional duration filter, e.g. 0.10")
    parser.add_argument(
        "--variants",
        nargs="+",
        default=None,
        help="Variants to compare. Default: auto-detect in order base default timing-biased.",
    )
    parser.add_argument(
        "--complete-only",
        action="store_true",
        help="Keep only categories that exist for all selected variants. Recommended for radar.",
    )
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    rows = load_rows(args.logs, args.phase, args.duration)
    if not rows:
        raise SystemExit("[ERROR] no rows loaded. Check paths/filters.")

    summary = summarize(rows)

    if args.variants is None:
        detected = sorted({variant for _, variant in summary.keys()}, key=lambda v: VARIANT_ORDER.index(v) if v in VARIANT_ORDER else 999)
        variants = detected
    else:
        variants = args.variants

    if args.complete_only:
        categories = ordered_categories(summary, variants)
    else:
        # For radar, categories with missing variants are still problematic.
        # We keep categories where at least one selected variant exists, but the user should prefer --complete-only for final slides.
        all_cats = sorted({cat for cat, variant in summary.keys() if variant in variants}, key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 999)
        categories = all_cats

    if not categories:
        raise SystemExit("[ERROR] no comparable categories found for selected variants.")

    phase_txt = f"P={args.phase:.2f}" if args.phase is not None else "all phases"
    dur_txt = f"dt={args.duration:.2f}s" if args.duration is not None else "all durations"
    title = f"Recovery frontier ({phase_txt}, {dur_txt})"

    csv_path = os.path.join(args.outdir, "recovery_frontier_values.csv")
    write_csv(summary, categories, csv_path)
    print(f"[saved] {csv_path}")

    radar_path = os.path.join(args.outdir, "recovery_radar_clean.png")
    plot_radar(summary, categories, variants, radar_path, title)

    bar_path = os.path.join(args.outdir, "recovery_bar_clean.png")
    plot_bar(summary, categories, variants, bar_path, title)

    print()
    print("Summary used for plots:")
    print("-" * 80)
    for cat in categories:
        parts = []
        for variant in variants:
            s = summary.get((cat, variant))
            if s:
                parts.append(f"{variant}={s['max_recoverable_force']:.1f}N ({s['n_success']}/{s['n']})")
            else:
                parts.append(f"{variant}=N/A")
        print(f"{cat:22s}  " + " | ".join(parts))
    print("-" * 80)
    print()
    print("Suggested final-slide command:")
    print(f"  python {os.path.basename(__file__)} --logs {' '.join(args.logs)} --phase 0.55 --duration 0.10 --complete-only --outdir {args.outdir}_p055")


if __name__ == "__main__":
    main()
