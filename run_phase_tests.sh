#!/usr/bin/env bash
# =============================================================================
# run_phase_tests.sh — Phase-aware push tests
#
# Goal:
#   Compare left/right pushes not only by numerical push_phase, but by the
#   real swing-foot vertical phase logged in the JSON:
#     rising / apex / descending / near_ground
#
# Main comparison:
#   LEFT  S3: support=rfoot, swing=lfoot
#   RIGHT S4: support=lfoot, swing=rfoot
# =============================================================================

set -u
set -o pipefail

SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-1000}"
LOGDIR="${LOGDIR:-logs_phase}"

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

# -----------------------------------------------------------------------------
# 1. Main forward phase-aware tests
# -----------------------------------------------------------------------------
# Forces:
#   40N = safe/intermediate
#   45N = adapter usually useful
#   50N = near frontier
#
# Phases:
#   0.25 = early-ish swing
#   0.50 = mid swing
#   0.75 = late swing / touchdown-sensitive
# -----------------------------------------------------------------------------

for F in 40 45 50; do
  for PH in 0.25 0.50 0.75; do
    PHTAG=$(phase_tag "$PH")

    # LEFT S3 — baseline
    run_test "base_left_S3_F${F}_P${PHTAG}" \
      --profile forward \
      --force "$F" --duration 0.10 --direction left \
      --push-step 3 --push-phase "$PH" --push-target base

    # LEFT S3 — adapted
    run_test "adapt_left_S3_F${F}_P${PHTAG}" \
      --profile forward --adapt \
      --force "$F" --duration 0.10 --direction left \
      --push-step 3 --push-phase "$PH" --push-target base

    # RIGHT S4 — baseline
    run_test "base_right_S4_F${F}_P${PHTAG}" \
      --profile forward \
      --force "$F" --duration 0.10 --direction right \
      --push-step 4 --push-phase "$PH" --push-target base

    # RIGHT S4 — adapted
    run_test "adapt_right_S4_F${F}_P${PHTAG}" \
      --profile forward --adapt \
      --force "$F" --duration 0.10 --direction right \
      --push-step 4 --push-phase "$PH" --push-target base
  done
done

# -----------------------------------------------------------------------------
# 2. Touchdown sensitivity sweep
# -----------------------------------------------------------------------------
# This isolates the late-swing effect.
# -----------------------------------------------------------------------------

for PH in 0.60 0.65 0.70 0.75 0.80; do
  PHTAG=$(phase_tag "$PH")

  run_test "touch_adapt_left_S3_F40_P${PHTAG}" \
    --profile forward --adapt \
    --force 40 --duration 0.10 --direction left \
    --push-step 3 --push-phase "$PH" --push-target base

  run_test "touch_adapt_right_S4_F40_P${PHTAG}" \
    --profile forward --adapt \
    --force 40 --duration 0.10 --direction right \
    --push-step 4 --push-phase "$PH" --push-target base
done

echo "============================================================"
echo "PHASE-AWARE BATTERY COMPLETE: $TOTAL tests, $FAILED command failures"
echo "============================================================"
echo

python show_results.py "$LOGDIR"
