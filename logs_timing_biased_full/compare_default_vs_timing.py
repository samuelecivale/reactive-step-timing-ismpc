#!/usr/bin/env python3
import glob
import json
import os
import re
import sys

old_dir = os.environ.get("OLD_LOGDIR", "logs_final")
timing_dir = os.environ.get("TIMING_LOGDIR", "logs_timing_biased_full")

def load_dir(path):
    rows = {}
    for p in glob.glob(os.path.join(path, "*.json")):
        try:
            with open(p) as f:
                d = json.load(f)
        except Exception:
            continue

        name = os.path.basename(p).replace(".json", "")

        key = (
            d.get("profile", d.get("walk_profile", "?")),
            d.get("direction", "?"),
            int(d.get("push_step", -1)),
            float(d.get("force_N", d.get("force", -1))),
            float(d.get("push_phase", -1)),
            float(d.get("duration_s", d.get("duration", -1))),
        )

        rows.setdefault(key, {})[name] = d
    return rows

old = load_dir(old_dir)
timing = load_dir(timing_dir)

def status(d):
    if d is None:
        return "missing"
    return "FELL" if d.get("fell") else "ok"

def ticks(d):
    if d is None:
        return "-"
    return d.get("ticks", "-")

def updates(d):
    if d is None:
        return "-"
    return d.get("adapter", {}).get("updates", "-")

def qpf(d):
    if d is None:
        return "-"
    return d.get("adapter", {}).get("qp_failures", "-")

wins_vs_base = 0
wins_vs_default = 0
worse_vs_default = 0
same_vs_default = 0
total = 0

print("=" * 100)
print("BASELINE vs DEFAULT ADAPTER vs TIMING-BIASED ADAPTER")
print("=" * 100)
print(f"old_dir:    {old_dir}")
print(f"timing_dir: {timing_dir}")
print()

header = (
    f"{'profile':8s} {'dir':8s} {'S':>2s} {'F':>5s} {'P':>4s} {'dt':>4s} | "
    f"{'base':>10s} {'default':>14s} {'timing-biased':>18s} | result"
)
print(header)
print("-" * len(header))

for key in sorted(timing.keys()):
    prof, direction, step, force, phase, duration = key

    old_group = old.get(key, {})
    timing_group = timing.get(key, {})

    base = None
    default = None
    timing_biased = None

    for name, d in old_group.items():
        if d.get("adapt_enabled", False):
            default = d
        else:
            base = d

    for name, d in timing_group.items():
        if d.get("adapt_enabled", False):
            timing_biased = d
            break

    if timing_biased is None:
        continue

    total += 1

    result = []
    if base is not None and base.get("fell") and not timing_biased.get("fell"):
        wins_vs_base += 1
        result.append("saves vs base")

    if default is not None:
        if default.get("fell") and not timing_biased.get("fell"):
            wins_vs_default += 1
            result.append("improves vs default")
        elif not default.get("fell") and timing_biased.get("fell"):
            worse_vs_default += 1
            result.append("worse vs default")
        else:
            same_vs_default += 1
            if default.get("fell") and timing_biased.get("fell"):
                dticks = (timing_biased.get("ticks") or 0) - (default.get("ticks") or 0)
                result.append(f"both fall, Δticks={dticks:+d}")
            else:
                result.append("same survival")

    print(
        f"{prof:8s} {direction:8s} {step:2d} {force:5.1f} {phase:4.2f} {duration:4.2f} | "
        f"{status(base):>4s}({ticks(base):>4}) "
        f"{status(default):>6s}({ticks(default):>4},u={updates(default)},q={qpf(default)}) "
        f"{status(timing_biased):>6s}({ticks(timing_biased):>4},u={updates(timing_biased)},q={qpf(timing_biased)}) | "
        f"{'; '.join(result)}"
    )

print()
print("=" * 100)
print(f"Compared timing-biased cases: {total}")
print(f"Timing-biased saves vs baseline:      {wins_vs_base}")
print(f"Timing-biased improves vs default:    {wins_vs_default}")
print(f"Timing-biased same category/default:  {same_vs_default}")
print(f"Timing-biased worse than default:     {worse_vs_default}")
print("=" * 100)
