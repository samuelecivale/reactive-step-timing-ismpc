#!/usr/bin/env bash
set -u
set -o pipefail

SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-1000}"
LOGDIR="${LOGDIR:-logs}"

rm -rf "$LOGDIR"
mkdir -p "$LOGDIR"

run_test() {
  NAME="$1"
  shift

  echo "============================================================"
  echo "RUNNING: $NAME"
  echo "COMMAND: python $SIM --headless --steps $STEPS $*"
  echo "============================================================"

  python "$SIM" \
    --headless \
    --steps "$STEPS" \
    --log-json "$LOGDIR/${NAME}.json" \
    "$@" \
    | tee "$LOGDIR/${NAME}.log"

  echo
  echo "Saved:"
  echo "  $LOGDIR/${NAME}.log"
  echo "  $LOGDIR/${NAME}.json"
  echo
}

# ------------------------------------------------------------
# A) BODY PUSH - FORCE LADDER
# ------------------------------------------------------------
# Obiettivo:
# - trovare una zona ragionevole di confronto baseline vs adapt
# - qui il target è il corpo, non il piede

for F in 30 40 50; do
  run_test "body_base_F${F}_P055" \
    --quiet \
    --profile forward \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase 0.55 \
    --push-target base
done

for F in 40 50 60; do
  run_test "body_adapt_F${F}_P055" \
    --quiet \
    --profile forward \
    --adapt \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase 0.55 \
    --push-target base
done

# ------------------------------------------------------------
# B) BODY PUSH - PHASE SWEEP
# ------------------------------------------------------------
# Obiettivo:
# - mostrare che una spinta più tardiva nello step è più dura
# - stessa forza, cambia solo push_phase

for PH in 0.05 0.35 0.55 0.75; do
  PH_TAG=$(echo "$PH" | tr '.' '')
  run_test "body_base_F40_P${PH_TAG}" \
    --quiet \
    --profile forward \
    --force 40 \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

for PH in 0.05 0.35 0.55 0.75; do
  PH_TAG=$(echo "$PH" | tr '.' '')
  run_test "body_adapt_F50_P${PH_TAG}" \
    --quiet \
    --profile forward \
    --adapt \
    --force 50 \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

# ------------------------------------------------------------
# C) STANCE-FOOT "SLIPPAGE-LIKE" - FORCE LADDER
# ------------------------------------------------------------
# Obiettivo:
# - testare la perturbazione applicata al piede in stance
# - dai tuoi run sappiamo che 500N e 800N sono troppo alti,
#   quindi partiamo più bassi

for F in 150 200 250 300; do
  run_test "slip_base_F${F}_P055" \
    --quiet \
    --profile forward \
    --force "$F" \
    --duration 0.20 \
    --direction left \
    --push-step 3 \
    --push-phase 0.55 \
    --push-target stance_foot
done

for F in 200 250 300 350 400; do
  run_test "slip_adapt_F${F}_P055" \
    --quiet \
    --profile forward \
    --adapt \
    --force "$F" \
    --duration 0.20 \
    --direction left \
    --push-step 3 \
    --push-phase 0.55 \
    --push-target stance_foot
done

# ------------------------------------------------------------
# D) STANCE-FOOT "SLIPPAGE-LIKE" - PHASE SWEEP
# ------------------------------------------------------------
# Obiettivo:
# - spiegare la differenza di push_phase anche nel caso slip-like
# - qui uso forze più conservative rispetto ai test manuali che hai fatto

for PH in 0.15 0.35 0.55 0.75; do
  PH_TAG=$(echo "$PH" | tr '.' '')
  run_test "slip_base_F250_P${PH_TAG}" \
    --quiet \
    --profile forward \
    --force 250 \
    --duration 0.20 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target stance_foot
done

for PH in 0.15 0.35 0.55 0.75; do
  PH_TAG=$(echo "$PH" | tr '.' '')
  run_test "slip_adapt_F300_P${PH_TAG}" \
    --quiet \
    --profile forward \
    --adapt \
    --force 300 \
    --duration 0.20 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target stance_foot
done

# ------------------------------------------------------------
# E) EXTRA "PAPER-LIKE" COMPARISON
# ------------------------------------------------------------
# Baseline: forward
# Adapt: inplace
# Non è una replica del paper, ma aiuta a fare un confronto narrativo

run_test "paperlike_slip_base_forward_F250_P055" \
  --quiet \
  --profile forward \
  --force 250 \
  --duration 0.20 \
  --direction left \
  --push-step 3 \
  --push-phase 0.55 \
  --push-target stance_foot

run_test "paperlike_slip_adapt_inplace_F300_P055" \
  --quiet \
  --profile inplace \
  --adapt \
  --force 300 \
  --duration 0.20 \
  --direction left \
  --push-step 3 \
  --push-phase 0.55 \
  --push-target stance_foot

# ------------------------------------------------------------
# FINAL SUMMARY TABLE
# ------------------------------------------------------------
python - <<'PY'
import glob
import json
import os

rows = []

for path in sorted(glob.glob("logs/*.json")):
    with open(path, "r") as f:
        d = json.load(f)

    failure = d.get("failure")
    failure_type = failure["type"] if failure else ""
    adapter = d.get("adapter", {})

    rows.append({
        "name": os.path.basename(path).replace(".json", ""),
        "fell": d.get("fell"),
        "ticks": d.get("ticks"),
        "force": d.get("force_N"),
        "phase": d.get("push_phase"),
        "updates": adapter.get("updates"),
        "activations": adapter.get("activations"),
        "qp_failures": adapter.get("qp_failures"),
        "failure": failure_type,
    })

def fmt(x, w):
    s = str(x)
    if len(s) > w:
        s = s[:w-1] + "…"
    return s.ljust(w)

headers = [
    ("name", 42),
    ("fell", 6),
    ("ticks", 6),
    ("force", 7),
    ("phase", 7),
    ("upd", 5),
    ("act", 5),
    ("qpf", 5),
    ("failure", 14),
]

line = " | ".join(fmt(h, w) for h, w in headers)
sep = "-+-".join("-" * w for _, w in headers)

print()
print("SUMMARY")
print(line)
print(sep)

for r in rows:
    print(" | ".join([
        fmt(r["name"], 42),
        fmt(r["fell"], 6),
        fmt(r["ticks"], 6),
        fmt(r["force"], 7),
        fmt(r["phase"], 7),
        fmt(r["updates"], 5),
        fmt(r["activations"], 5),
        fmt(r["qp_failures"], 5),
        fmt(r["failure"], 14),
    ]))
print()
PY
