#!/usr/bin/env bash
set -u
set -o pipefail

SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-1000}"
LOGDIR="${LOGDIR:-logs_refined}"

rm -rf "$LOGDIR"
mkdir -p "$LOGDIR"

phase_tag() {
  printf "%s" "$1" | tr -d '.'
}

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
    --quiet \
    --log-json "$LOGDIR/${NAME}.json" \
    "$@" \
    | tee "$LOGDIR/${NAME}.log"

  echo
  echo "Saved:"
  echo "  $LOGDIR/${NAME}.log"
  echo "  $LOGDIR/${NAME}.json"
  echo
}

# ============================================================
# A) BODY PUSH - FRONTIER @ push_phase = 0.55
# Baseline già fragile intorno a 40N
# Adapted regge fino a ~50N e poi cede verso 60N
# ============================================================

PH="0.55"
PHTAG=$(phase_tag "$PH")

for F in 35 40 45; do
  run_test "body_base_F${F}_P${PHTAG}" \
    --profile forward \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

for F in 45 50 55 60; do
  run_test "body_adapt_F${F}_P${PHTAG}" \
    --profile forward \
    --adapt \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

# ============================================================
# B) BODY PUSH - LATE PHASE @ push_phase = 0.75
# Serve per mostrare che più tardi arriva la spinta, peggio è
# ============================================================

PH="0.75"
PHTAG=$(phase_tag "$PH")

for F in 30 35 40; do
  run_test "body_base_F${F}_P${PHTAG}" \
    --profile forward \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

for F in 40 45 50 55; do
  run_test "body_adapt_F${F}_P${PHTAG}" \
    --profile forward \
    --adapt \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

# ============================================================
# C) BODY PUSH - SAME FORCE, DIFFERENT PHASE
# Confronto didattico puro sull'effetto di push_phase
# ============================================================

for PH in 0.05 0.35 0.55 0.75; do
  PHTAG=$(phase_tag "$PH")
  run_test "body_base_F40_P${PHTAG}" \
    --profile forward \
    --force 40 \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

for PH in 0.05 0.35 0.55 0.75; do
  PHTAG=$(phase_tag "$PH")
  run_test "body_adapt_F50_P${PHTAG}" \
    --profile forward \
    --adapt \
    --force 50 \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

# ============================================================
# D) STANCE-FOOT "SLIP-LIKE" - FRONTIER @ push_phase = 0.75
# Dai tuoi test è qui che si intravede la differenza migliore
# ============================================================

PH="0.75"
PHTAG=$(phase_tag "$PH")

for F in 250 275 300 325; do
  run_test "slip_base_F${F}_P${PHTAG}" \
    --profile forward \
    --force "$F" \
    --duration 0.20 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target stance_foot
done

for F in 300 325 350 375 400; do
  run_test "slip_adapt_F${F}_P${PHTAG}" \
    --profile forward \
    --adapt \
    --force "$F" \
    --duration 0.20 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target stance_foot
done

# ============================================================
# E) STANCE-FOOT "SLIP-LIKE" - SAME FORCE, DIFFERENT PHASE
# Solo per vedere se la fase tarda peggiora anche qui
# ============================================================

for PH in 0.35 0.55 0.75; do
  PHTAG=$(phase_tag "$PH")
  run_test "slip_base_F250_P${PHTAG}" \
    --profile forward \
    --force 250 \
    --duration 0.20 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target stance_foot
done

for PH in 0.35 0.55 0.75; do
  PHTAG=$(phase_tag "$PH")
  run_test "slip_adapt_F300_P${PHTAG}" \
    --profile forward \
    --adapt \
    --force 300 \
    --duration 0.20 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target stance_foot
done

# ============================================================
# SUMMARY TABLE
# ============================================================

python - <<'PY'
import glob
import json
import os

rows = []

for path in sorted(glob.glob("logs_refined/*.json")):
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
