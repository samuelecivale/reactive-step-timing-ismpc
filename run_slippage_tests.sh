#!/usr/bin/env bash
# =============================================================================
# run_slippage_tests.sh — Slippage recovery: push sullo stance foot
#
# Step 3: support=rfoot → push su rfoot (--push-target rfoot)
# Step 4: support=lfoot → push su lfoot (--push-target lfoot)
#
# Direzione left = il piede scivola verso sinistra
# =============================================================================
set -u
set -o pipefail

SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-1000}"
LOGDIR="${LOGDIR:-logs_slippage}"

rm -rf "$LOGDIR"
mkdir -p "$LOGDIR"

TOTAL=0
FAILED=0

run_test() {
  local NAME="$1"
  shift

  if [[ -f "$LOGDIR/${NAME}.json" ]]; then
    echo "[SKIP] $NAME"
    return 0
  fi

  TOTAL=$((TOTAL + 1))
  echo "============================================================"
  echo "RUNNING [$TOTAL]: $NAME"
  echo "============================================================"

  python "$SIM" \
    --headless \
    --steps "$STEPS" \
    --quiet \
    --log-json "$LOGDIR/${NAME}.json" \
    "$@" \
    2>&1 | tee "$LOGDIR/${NAME}.log"

  local EXIT_CODE=${PIPESTATUS[0]}
  if [[ $EXIT_CODE -ne 0 ]]; then
    FAILED=$((FAILED + 1))
  fi
  echo
}

# ============================================================
# 1. Push su RFOOT (stance) a step 3, direzione left
#    Il piede destro scivola verso sinistra
# ============================================================

for F in 20 30 40 50 60 80 100; do
  run_test "slip_base_F${F}_P055_rfoot_S3_left" \
    --profile forward \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target rfoot

  run_test "slip_adapt_F${F}_P055_rfoot_S3_left" \
    --profile forward --adapt \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target rfoot
done

# ============================================================
# 2. Push su LFOOT (stance) a step 4, direzione right
#    Il piede sinistro scivola verso destra
# ============================================================

for F in 20 30 40 50 60 80 100; do
  run_test "slip_base_F${F}_P055_lfoot_S4_right" \
    --profile forward \
    --force "$F" --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.55 --push-target lfoot

  run_test "slip_adapt_F${F}_P055_lfoot_S4_right" \
    --profile forward --adapt \
    --force "$F" --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.55 --push-target lfoot
done

# ============================================================
# 3. Push più lunga (0.20s) su rfoot S3 — slip prolungato
# ============================================================

for F in 20 30 40 50; do
  run_test "slip_long_base_F${F}_P055_rfoot_S3_left" \
    --profile forward \
    --force "$F" --duration 0.20 --direction left \
    --push-step 3 --push-phase 0.55 --push-target rfoot

  run_test "slip_long_adapt_F${F}_P055_rfoot_S3_left" \
    --profile forward --adapt \
    --force "$F" --duration 0.20 --direction left \
    --push-step 3 --push-phase 0.55 --push-target rfoot
done

# ============================================================
# SUMMARY
# ============================================================

echo "============================================================"
echo "BATTERY COMPLETE: $TOTAL test, $FAILED falliti"
echo "============================================================"
echo

python - "$LOGDIR" <<'PYEOF'
import glob, json, os, sys

logdir = sys.argv[1] if len(sys.argv) > 1 else "logs_slippage"
rows = []

for path in sorted(glob.glob(os.path.join(logdir, "*.json"))):
    try:
        with open(path, "r") as f:
            d = json.load(f)
    except Exception as e:
        print(f"[WARN] {path}: {e}")
        continue

    failure = d.get("failure")
    adapter = d.get("adapter", {})
    rows.append({
        "name": os.path.basename(path).replace(".json", ""),
        "fell": d.get("fell"),
        "ticks": d.get("ticks"),
        "force": d.get("force_N"),
        "phase": d.get("push_phase"),
        "adapt": d.get("adapt_enabled", False),
        "direction": d.get("direction", "?"),
        "duration": d.get("duration_s", 0.0),
        "push_step": d.get("push_step", "?"),
        "updates": adapter.get("updates", 0),
        "activations": adapter.get("activations", 0),
        "qp_failures": adapter.get("qp_failures", 0),
        "failure": failure["type"] if failure else "",
    })

def fmt(x, w):
    s = f"{x:.4f}" if isinstance(x, float) and abs(x) < 100 else str(x)
    return (s[:w-1] + "…" if len(s) > w else s).ljust(w)

headers = [("name",44),("fell",6),("ticks",6),("force",6),("dur",5),
           ("dir",6),("step",5),("adapt",6),("upd",4),("act",4),("qpf",4),("fail",14)]
print(" | ".join(fmt(h,w) for h,w in headers))
print("-+-".join("-"*w for _,w in headers))
for r in rows:
    print(" | ".join([fmt(r["name"],44),fmt(r["fell"],6),fmt(r["ticks"],6),
        fmt(r["force"],6),fmt(r["duration"],5),fmt(r["direction"],6),
        fmt(r["push_step"],5),fmt(r["adapt"],6),fmt(r["updates"],4),
        fmt(r["activations"],4),fmt(r["qp_failures"],4),fmt(r["failure"],14)]))

print("\nCONFRONTO BASE vs ADAPT")
print("-" * 70)
by_key = {}
for r in rows:
    key = (r["name"].split("_")[1], r["direction"], r["push_step"], r["force"], r["duration"])
    by_key.setdefault(key, []).append(r)

wins = ties = losses = 0
for key in sorted(by_key.keys()):
    group = by_key[key]
    base = [r for r in group if not r["adapt"]]
    adapt = [r for r in group if r["adapt"]]
    if not base or not adapt:
        continue
    b, a = base[0], adapt[0]
    if not b["fell"] and not a["fell"]:
        tag = "=="; ties += 1
    elif b["fell"] and not a["fell"]:
        tag = "OK <<<"; wins += 1
    elif not b["fell"] and a["fell"]:
        tag = "WORSE"; losses += 1
    else:
        delta = (a["ticks"] or 0) - (b["ticks"] or 0)
        tag = f"+{delta}t" if delta > 0 else f"{delta}t"; ties += 1
    typ, dirn, step, force, dur = key
    print(f"  {typ:5s} {dirn:6s} S{step} F={force:5.1f}N dt={dur:.2f}s  "
          f"base={'FELL' if b['fell'] else ' ok '}({b['ticks']:4d}t)  "
          f"adapt={'FELL' if a['fell'] else ' ok '}({a['ticks']:4d}t upd={a['updates']})  [{tag}]")

print(f"\nOK={wins}  ==={ties}  WORSE={losses}")
PYEOF
