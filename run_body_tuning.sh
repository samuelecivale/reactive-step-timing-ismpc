#!/usr/bin/env bash
set -u
set -o pipefail

SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-1000}"
LOGDIR="${LOGDIR:-logs_body_tuning}"

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

# ------------------------------------------------------------
# BASELINE REFERENCES
# ------------------------------------------------------------

for PH in 0.35 0.55; do
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
done

# ------------------------------------------------------------
# ADAPTED - MAIN FRONTIER
# ------------------------------------------------------------

for PH in 0.35 0.55; do
  PHTAG=$(phase_tag "$PH")
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
done

# ------------------------------------------------------------
# HARD CASE ONLY
# ------------------------------------------------------------

PH="0.75"
PHTAG=$(phase_tag "$PH")

for F in 35 40; do
  run_test "body_base_F${F}_P${PHTAG}" \
    --profile forward \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

for F in 40 45 50; do
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

# ------------------------------------------------------------
# SAME FORCE, DIFFERENT PHASE
# ------------------------------------------------------------

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
  run_test "body_adapt_F45_P${PHTAG}" \
    --profile forward \
    --adapt \
    --force 45 \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

# ------------------------------------------------------------
# SUMMARY
# ------------------------------------------------------------

python - <<'PY'
import glob
import json
import os

rows = []
tuning = None

for path in sorted(glob.glob("logs_body_tuning/*.json")):
    with open(path, "r") as f:
        d = json.load(f)

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

if tuning is not None:
    print()
    print("TUNING PARAMETERS")
    for k, v in tuning.items():
        print(f"{k}: {v}")
    print()

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
