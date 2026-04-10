#!/usr/bin/env bash
set -u

rm -rf logs
mkdir -p logs

run_test() {
  NAME="$1"
  shift
  echo "============================================================"
  echo "RUNNING: $NAME"
  echo "COMMAND: python simulation.py $*"
  echo "============================================================"

  python simulation.py "$@" \
    --log-json "logs/${NAME}.json" \
    | tee "logs/${NAME}.log"

  echo
  echo "Saved:"
  echo "  logs/${NAME}.log"
  echo "  logs/${NAME}.json"
  echo
}

# ------------------------------------------------------------
# FORWARD WALKING
# ------------------------------------------------------------

# Baseline
run_test "forward_base_F30" \
  --headless \
  --quiet \
  --profile forward \
  --steps 1000 \
  --force 30 \
  --duration 0.10 \
  --direction left \
  --push-step 3 \
  --push-phase 0.05

run_test "forward_base_F40" \
  --headless \
  --quiet \
  --profile forward \
  --steps 1000 \
  --force 40 \
  --duration 0.10 \
  --direction left \
  --push-step 3 \
  --push-phase 0.05

# Adapt
run_test "forward_adapt_F40" \
  --headless \
  --quiet \
  --profile forward \
  --adapt \
  --steps 1000 \
  --force 40 \
  --duration 0.10 \
  --direction left \
  --push-step 3 \
  --push-phase 0.55

run_test "forward_adapt_F50" \
  --headless \
  --quiet \
  --profile forward \
  --adapt \
  --steps 1000 \
  --force 50 \
  --duration 0.10 \
  --direction left \
  --push-step 3 \
  --push-phase 0.55

# ------------------------------------------------------------
# STEPPING IN PLACE
# ------------------------------------------------------------

# Baseline
run_test "inplace_base_F20" \
  --headless \
  --quiet \
  --profile inplace \
  --steps 1000 \
  --force 20 \
  --duration 0.10 \
  --direction left \
  --push-step 3 \
  --push-phase 0.05

run_test "inplace_base_F30" \
  --headless \
  --quiet \
  --profile inplace \
  --steps 1000 \
  --force 30 \
  --duration 0.10 \
  --direction left \
  --push-step 3 \
  --push-phase 0.05

# Adapt
run_test "inplace_adapt_F30" \
  --headless \
  --quiet \
  --profile inplace \
  --adapt \
  --steps 1000 \
  --force 30 \
  --duration 0.10 \
  --direction left \
  --push-step 3 \
  --push-phase 0.55

run_test "inplace_adapt_F40" \
  --headless \
  --quiet \
  --profile inplace \
  --adapt \
  --steps 1000 \
  --force 40 \
  --duration 0.10 \
  --direction left \
  --push-step 3 \
  --push-phase 0.55

echo "All tests completed."
echo "Logs are in ./logs"
