#!/usr/bin/env bash
# =============================================================================
# run_timing_biased_on_old_tests.sh
#
# Goal:
#   Re-run ONLY the old adapted scenarios from logs_final, but with:
#       --adapt --timing-biased
#
# This avoids repeating the baseline/default-adapter battery and creates a
# third result set that can be compared against the existing 123-test logs.
#
# Input:
#   OLD_LOGDIR=logs_final
#
# Output:
#   OUTDIR=logs_timing_biased_full
#
# Usage:
#   chmod +x run_timing_biased_on_old_tests.sh
#   STEPS=900 OLD_LOGDIR=logs_final OUTDIR=logs_timing_biased_full ./run_timing_biased_on_old_tests.sh
#
# Then:
#   python show_results.py logs_timing_biased_full
# =============================================================================

set -u
set -o pipefail

SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-900}"
OLD_LOGDIR="${OLD_LOGDIR:-logs_final}"
OUTDIR="${OUTDIR:-logs_timing_biased_full}"
FORCE_RERUN="${FORCE_RERUN:-0}"

mkdir -p "$OUTDIR"

if [[ ! -d "$OLD_LOGDIR" ]]; then
  echo "[ERROR] OLD_LOGDIR not found: $OLD_LOGDIR"
  echo "        Run this script from the repository root, or set OLD_LOGDIR=/path/to/logs_final"
  exit 1
fi

echo "============================================================"
echo "TIMING-BIASED FULL RE-RUN FROM OLD ADAPTED TESTS"
echo "============================================================"
echo "SIM:        $SIM"
echo "STEPS:      $STEPS"
echo "OLD_LOGDIR: $OLD_LOGDIR"
echo "OUTDIR:     $OUTDIR"
echo "FORCE_RERUN:$FORCE_RERUN"
echo "============================================================"
echo

COMMANDS_FILE="$OUTDIR/.timing_biased_commands.sh"

python - "$OLD_LOGDIR" "$OUTDIR" "$SIM" "$STEPS" > "$COMMANDS_FILE" <<'PYEOF'
import glob
import json
import os
import shlex
import sys

old_logdir, outdir, sim, steps = sys.argv[1:5]

def q(x):
    return shlex.quote(str(x))

def get_first(d, keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default

paths = sorted(glob.glob(os.path.join(old_logdir, "*.json")))
count = 0

for path in paths:
    try:
        with open(path, "r") as f:
            d = json.load(f)
    except Exception as e:
        print(f"echo '[WARN] cannot read {q(path)}: {q(e)}'", file=sys.stderr)
        continue

    # We only re-run the scenarios that were adapted in the old battery.
    if not d.get("adapt_enabled", False):
        continue

    old_name = os.path.basename(path).replace(".json", "")

    # Avoid re-running already timing-biased/H diagnostic logs if user points to a mixed folder.
    if "timing" in old_name.lower() or "biased" in old_name.lower() or old_name.startswith("H_"):
        continue

    new_name = old_name.replace("_adapt_", "_timing_biased_")
    if new_name == old_name:
        new_name = old_name + "_timing_biased"

    profile = get_first(d, ["profile", "walk_profile"], "forward")
    force = get_first(d, ["force_N", "force"], None)
    duration = get_first(d, ["duration_s", "duration"], 0.10)
    direction = get_first(d, ["direction"], "left")
    push_step = get_first(d, ["push_step"], None)
    push_phase = get_first(d, ["push_phase"], None)
    push_target = get_first(d, ["push_target"], "base")

    if force is None or push_step is None or push_phase is None:
        print(f"echo '[WARN] skipping {q(old_name)}: missing force/push_step/push_phase'", file=sys.stderr)
        continue

    log_json = os.path.join(outdir, new_name + ".json")
    log_txt = os.path.join(outdir, new_name + ".log")

    cmd = [
        "python", sim,
        "--headless",
        "--steps", steps,
        "--quiet",
        "--adapt",
        "--timing-biased",
        "--profile", profile,
        "--force", force,
        "--duration", duration,
        "--direction", direction,
        "--push-step", push_step,
        "--push-phase", push_phase,
        "--push-target", push_target,
        "--log-json", log_json,
    ]

    printable = " ".join(q(x) for x in cmd)
    print(f"run_one {q(new_name)} {q(printable)} {q(log_json)} {q(log_txt)}")
    count += 1

print(f"echo '[INFO] generated {count} timing-biased commands from adapted logs'", file=sys.stderr)
PYEOF

run_one() {
  local NAME="$1"
  local PRINTABLE_CMD="$2"
  local JSON_OUT="$3"
  local LOG_OUT="$4"

  if [[ "$FORCE_RERUN" != "1" && -f "$JSON_OUT" ]]; then
    echo "[SKIP] $NAME — already exists"
    return 0
  fi

  echo "============================================================"
  echo "RUNNING TIMING-BIASED: $NAME"
  echo "COMMAND: $PRINTABLE_CMD"
  echo "============================================================"

  # shellcheck disable=SC2086
  eval "$PRINTABLE_CMD" 2>&1 | tee "$LOG_OUT"

  local EXIT_CODE=${PIPESTATUS[0]}
  if [[ $EXIT_CODE -ne 0 ]]; then
    echo "[FAIL] $NAME — exit code $EXIT_CODE"
  fi
  echo
}

source "$COMMANDS_FILE"

echo "============================================================"
echo "TIMING-BIASED RUN COMPLETE"
echo "Output folder: $OUTDIR"
echo "============================================================"
echo

echo "Quick checks:"
echo "  ls $OUTDIR | head"
echo "  python show_results.py $OUTDIR"
echo

echo "To compare against the old logs:"
echo "  OLD_LOGDIR=$OLD_LOGDIR TIMING_LOGDIR=$OUTDIR python compare_default_vs_timing.py"
echo

# Optional comparison helper generated next to the output folder.
cat > "$OUTDIR/compare_default_vs_timing.py" <<'PYEOF'
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
PYEOF

chmod +x "$OUTDIR/compare_default_vs_timing.py"
