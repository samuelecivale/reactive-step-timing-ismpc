#!/usr/bin/env bash
# =============================================================================
# run_extra_tests.sh — Test aggiuntivi: in-place, direzioni, frontiera
# =============================================================================
set -u
set -o pipefail

SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-1400}"
LOGDIR="${LOGDIR:-logs_extra}"

rm -rf "$LOGDIR"
mkdir -p "$LOGDIR"

TOTAL=0
FAILED=0

phase_tag() {
  printf "%s" "$1" | tr -d '.'
}

run_test() {
  local NAME="$1"
  shift

  if [[ -f "$LOGDIR/${NAME}.json" ]]; then
    echo "[SKIP] $NAME — già eseguito"
    return 0
  fi

  TOTAL=$((TOTAL + 1))

  echo "============================================================"
  echo "RUNNING [$TOTAL]: $NAME"
  echo "COMMAND: python $SIM --headless --steps $STEPS $*"
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
    echo "[FAIL] $NAME — exit code $EXIT_CODE"
    FAILED=$((FAILED + 1))
  fi
  echo
}

# ============================================================
# 1. IN-PLACE — stepping in place, push laterale
#    Qui ci aspettiamo timing adaptation (non solo placement)
# ============================================================

for PH in 0.35 0.55; do
  PHTAG=$(phase_tag "$PH")

  # Baseline
  for F in 20 25 30; do
    run_test "inplace_base_F${F}_P${PHTAG}_left" \
      --profile inplace \
      --force "$F" \
      --duration 0.10 \
      --direction left \
      --push-step 3 \
      --push-phase "$PH" \
      --push-target base
  done

  # Adapted
  for F in 25 30 35 40; do
    run_test "inplace_adapt_F${F}_P${PHTAG}_left" \
      --profile inplace \
      --adapt \
      --force "$F" \
      --duration 0.10 \
      --direction left \
      --push-step 3 \
      --push-phase "$PH" \
      --push-target base
  done
done

# ============================================================
# 2. FORWARD — direzioni diverse (right, forward, backward)
#    Per vedere se l'adapter generalizza oltre la push "left"
# ============================================================

for DIR in right forward backward; do
  for PH in 0.35 0.55; do
    PHTAG=$(phase_tag "$PH")

    # Baseline
    for F in 35 40; do
      run_test "fwd_base_F${F}_P${PHTAG}_${DIR}" \
        --profile forward \
        --force "$F" \
        --duration 0.10 \
        --direction "$DIR" \
        --push-step 3 \
        --push-phase "$PH" \
        --push-target base
    done

    # Adapted
    for F in 40 45 50; do
      run_test "fwd_adapt_F${F}_P${PHTAG}_${DIR}" \
        --profile forward \
        --adapt \
        --force "$F" \
        --duration 0.10 \
        --direction "$DIR" \
        --push-step 3 \
        --push-phase "$PH" \
        --push-target base
    done
  done
done

# ============================================================
# 3. FRONTIERA FINE — forward left, esplorare 50-60N a P=0.55
#    Dove si rompe il nuovo tuning?
# ============================================================

for F in 50 52 55 58 60; do
  run_test "frontier_fine_base_F${F}_P055_left" \
    --profile forward \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase 0.55 \
    --push-target base

  run_test "frontier_fine_adapt_F${F}_P055_left" \
    --profile forward \
    --adapt \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase 0.55 \
    --push-target base
done

# ============================================================
# 4. IN-PLACE — push right (simmetria)
# ============================================================

for PH in 0.35 0.55; do
  PHTAG=$(phase_tag "$PH")

  for F in 25 30; do
    run_test "inplace_base_F${F}_P${PHTAG}_right" \
      --profile inplace \
      --force "$F" \
      --duration 0.10 \
      --direction right \
      --push-step 3 \
      --push-phase "$PH" \
      --push-target base
  done

  for F in 30 35; do
    run_test "inplace_adapt_F${F}_P${PHTAG}_right" \
      --profile inplace \
      --adapt \
      --force "$F" \
      --duration 0.10 \
      --direction right \
      --push-step 3 \
      --push-phase "$PH" \
      --push-target base
  done
done

# ============================================================
# 5. DURATA PUSH PIÙ LUNGA (0.20s invece di 0.10s)
#    Per testare la robustezza a perturbazioni prolungate
# ============================================================

for F in 30 35 40; do
  run_test "long_push_base_F${F}_P055_left" \
    --profile forward \
    --force "$F" \
    --duration 0.20 \
    --direction left \
    --push-step 3 \
    --push-phase 0.55 \
    --push-target base

  run_test "long_push_adapt_F${F}_P055_left" \
    --profile forward \
    --adapt \
    --force "$F" \
    --duration 0.20 \
    --direction left \
    --push-step 3 \
    --push-phase 0.55 \
    --push-target base
done

# ============================================================
# SUMMARY
# ============================================================

echo "============================================================"
echo "BATTERY COMPLETE: $TOTAL test eseguiti, $FAILED falliti"
echo "============================================================"
echo

python - "$LOGDIR" <<'PY'
import glob
import json
import os
import sys

logdir = sys.argv[1] if len(sys.argv) > 1 else "logs_extra"

rows = []
tuning = None

for path in sorted(glob.glob(os.path.join(logdir, "*.json"))):
    try:
        with open(path, "r") as f:
            d = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[WARN] impossibile leggere {path}: {e}")
        continue

    if tuning is None and "tuning_params" in d:
        tuning = d["tuning_params"]

    failure = d.get("failure")
    failure_type = failure["type"] if failure else ""
    adapter = d.get("adapter", {})

    rows.append({
        "name": os.path.basename(path).replace(".json", ""),
        "fell": d.get("fell"),
        "ticks": d.get("ticks"),
        "force": d.get("force_N"),
        "phase": d.get("push_phase"),
        "adapt": d.get("adapt_enabled", False),
        "profile": d.get("profile", "?"),
        "direction": d.get("direction", "?"),
        "duration": d.get("duration_s", 0.0),
        "updates": adapter.get("updates", 0),
        "activations": adapter.get("activations", 0),
        "qp_failures": adapter.get("qp_failures", 0),
        "max_dcm_err": adapter.get("max_dcm_error", 0.0),
        "failure": failure_type,
    })

def fmt(x, w):
    if isinstance(x, float):
        s = f"{x:.4f}" if abs(x) < 100 else f"{x:.1f}"
    else:
        s = str(x)
    if len(s) > w:
        s = s[:w-1] + "…"
    return s.ljust(w)

if tuning is not None:
    print()
    print("TUNING PARAMETERS")
    print("-" * 40)
    for k, v in tuning.items():
        print(f"  {k}: {v}")
    print()

headers = [
    ("name",        44),
    ("fell",         6),
    ("ticks",        6),
    ("force",        6),
    ("phase",        6),
    ("dir",          8),
    ("prof",         8),
    ("adapt",        6),
    ("upd",          5),
    ("act",          5),
    ("qpf",          5),
    ("max_err",      8),
    ("failure",     14),
]

line = " | ".join(fmt(h, w) for h, w in headers)
sep  = "-+-".join("-" * w for _, w in headers)

print("SUMMARY")
print(line)
print(sep)

for r in rows:
    print(" | ".join([
        fmt(r["name"],        44),
        fmt(r["fell"],         6),
        fmt(r["ticks"],        6),
        fmt(r["force"],        6),
        fmt(r["phase"],        6),
        fmt(r["direction"],    8),
        fmt(r["profile"],      8),
        fmt(r["adapt"],        6),
        fmt(r["updates"],      5),
        fmt(r["activations"],  5),
        fmt(r["qp_failures"],  5),
        fmt(r["max_dcm_err"],  8),
        fmt(r["failure"],     14),
    ]))

# Confronto per gruppi
print()
print("CONFRONTI (stessa configurazione, base vs adapt)")
print("-" * 70)
by_key = {}
for r in rows:
    key = (r["profile"], r["direction"], r["force"], r["phase"], r["duration"])
    by_key.setdefault(key, []).append(r)

for key, group in sorted(by_key.items()):
    prof, dirn, force, phase, dur = key
    base = [r for r in group if not r["adapt"]]
    adapt = [r for r in group if r["adapt"]]
    if not base or not adapt:
        continue
    b = base[0]
    a = adapt[0]
    if not b["fell"] and not a["fell"]:
        tag = "=="
    elif b["fell"] and not a["fell"]:
        tag = "OK"      # adapter salva
    elif not b["fell"] and a["fell"]:
        tag = "WORSE"   # adapter peggiora
    else:
        delta = (a["ticks"] or 0) - (b["ticks"] or 0)
        tag = f"+{delta}t" if delta > 0 else f"{delta}t"

    print(
        f"  {prof:8s} {dirn:8s} F={force:5.1f}N P={phase:.2f} dt={dur:.2f}s  "
        f"base={'FELL' if b['fell'] else ' ok '}({b['ticks']:4d}t)  "
        f"adapt={'FELL' if a['fell'] else ' ok '}({a['ticks']:4d}t)  "
        f"[{tag}]"
    )
print()
PY
