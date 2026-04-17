#!/usr/bin/env bash
# =============================================================================
# run_inplace_tests.sh — Test in-place con forze basse per trovare la frontiera
# =============================================================================
set -u
set -o pipefail

SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-1000}"
LOGDIR="${LOGDIR:-logs_inplace}"

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
# 1. SENZA PUSH — il robot sta in piedi?
# ============================================================

run_test "nopush_base" \
  --profile inplace --force 0 --duration 0.10 --direction left \
  --push-step 3 --push-phase 0.55 --push-target base

run_test "nopush_adapt" \
  --profile inplace --adapt --force 0 --duration 0.10 --direction left \
  --push-step 3 --push-phase 0.55 --push-target base

# ============================================================
# 2. LEFT su step 3, P=0.55 — forze basse
# ============================================================

for F in 5 10 15 20 25 30; do
  run_test "inplace_base_F${F}_P055_left_S3" \
    --profile inplace \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base

  run_test "inplace_adapt_F${F}_P055_left_S3" \
    --profile inplace --adapt \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base
done

# ============================================================
# 3. RIGHT su step 4, P=0.55 — simmetria
# ============================================================

for F in 5 10 15 20 25 30; do
  run_test "inplace_base_F${F}_P055_right_S4" \
    --profile inplace \
    --force "$F" --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.55 --push-target base

  run_test "inplace_adapt_F${F}_P055_right_S4" \
    --profile inplace --adapt \
    --force "$F" --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.55 --push-target base
done

# ============================================================
# 4. LEFT su step 3, P=0.35 — stesso ma fase diversa
# ============================================================

for F in 5 10 15 20 25; do
  run_test "inplace_base_F${F}_P035_left_S3" \
    --profile inplace \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.35 --push-target base

  run_test "inplace_adapt_F${F}_P035_left_S3" \
    --profile inplace --adapt \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.35 --push-target base
done

# ============================================================
# 5. PUSH PIÙ TARDI — step 5 invece di 3
#    Il robot ha più tempo per stabilizzarsi
# ============================================================

for F in 10 15 20 25 30; do
  run_test "inplace_base_F${F}_P055_left_S5" \
    --profile inplace \
    --force "$F" --duration 0.10 --direction left \
    --push-step 5 --push-phase 0.55 --push-target base

  run_test "inplace_adapt_F${F}_P055_left_S5" \
    --profile inplace --adapt \
    --force "$F" --duration 0.10 --direction left \
    --push-step 5 --push-phase 0.55 --push-target base
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

logdir = sys.argv[1] if len(sys.argv) > 1 else "logs_inplace"
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
        "push_step": d.get("push_step", "?"),
        "updates": adapter.get("updates", 0),
        "activations": adapter.get("activations", 0),
        "qp_failures": adapter.get("qp_failures", 0),
        "failure": failure["type"] if failure else "",
    })

def fmt(x, w):
    s = f"{x:.4f}" if isinstance(x, float) and abs(x) < 100 else str(x)
    return (s[:w-1] + "…" if len(s) > w else s).ljust(w)

headers = [("name",40),("fell",6),("ticks",6),("force",6),("phase",6),
           ("dir",6),("step",5),("adapt",6),("upd",4),("act",4),("qpf",4),("fail",14)]
print(" | ".join(fmt(h,w) for h,w in headers))
print("-+-".join("-"*w for _,w in headers))
for r in rows:
    print(" | ".join([fmt(r["name"],40),fmt(r["fell"],6),fmt(r["ticks"],6),
        fmt(r["force"],6),fmt(r["phase"],6),fmt(r["direction"],6),
        fmt(r["push_step"],5),fmt(r["adapt"],6),fmt(r["updates"],4),
        fmt(r["activations"],4),fmt(r["qp_failures"],4),fmt(r["failure"],14)]))

# Confronto
print("\nCONFRONTO BASE vs ADAPT")
print("-" * 70)
by_key = {}
for r in rows:
    key = (r["direction"], r["push_step"], r["force"], r["phase"])
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
    dirn, step, force, phase = key
    print(f"  {dirn:6s} S{step} F={force:5.1f}N P={phase:.2f}  "
          f"base={'FELL' if b['fell'] else ' ok '}({b['ticks']:4d}t)  "
          f"adapt={'FELL' if a['fell'] else ' ok '}({a['ticks']:4d}t upd={a['updates']})  [{tag}]")

print(f"\nOK={wins}  ==={ties}  WORSE={losses}")
PYEOF
