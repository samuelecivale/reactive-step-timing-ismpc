#!/usr/bin/env bash
# =============================================================================
# run_final_1000_pipeline.sh
#
# Final uniform 1000-step pipeline:
#   1. baseline + default adapter battery -> logs_final_1000
#   2. timing-biased re-run of adapted scenarios -> logs_timing_biased_full_1000
#   3. textual comparison -> plots_final_1000/compare_default_vs_timing_1000.txt
#
# Usage:
#   chmod +x run_final_1000_pipeline.sh
#   ./run_final_1000_pipeline.sh
#
# Optional:
#   FORCE_RERUN=1 ./run_final_1000_pipeline.sh
# =============================================================================

set -euo pipefail

STEPS="${STEPS:-1000}"
LOGDIR="${LOGDIR:-logs_final_1000}"
TIMING_LOGDIR="${TIMING_LOGDIR:-logs_timing_biased_full_1000}"
PLOTDIR="${PLOTDIR:-plots_final_1000}"
MAKE_VIDEOS="${MAKE_VIDEOS:-0}"
FORCE_RERUN="${FORCE_RERUN:-0}"

mkdir -p "$LOGDIR" "$TIMING_LOGDIR" "$PLOTDIR"

echo "============================================================"
echo "FINAL 1000-STEP SIMULATION PIPELINE"
echo "============================================================"
echo "STEPS:        $STEPS"
echo "LOGDIR:       $LOGDIR"
echo "TIMING_LOGDIR:$TIMING_LOGDIR"
echo "PLOTDIR:      $PLOTDIR"
echo "MAKE_VIDEOS:  $MAKE_VIDEOS"
echo "FORCE_RERUN:  $FORCE_RERUN"
echo "============================================================"
echo

if [[ ! -f run_all_tests.sh ]]; then
  echo "[ERROR] run_all_tests.sh not found. Run from repo root."
  exit 1
fi

if [[ ! -f run_timing_biased_on_old_tests.sh ]]; then
  echo "[ERROR] run_timing_biased_on_old_tests.sh not found."
  exit 1
fi

echo "============================================================"
echo "1/3 Running baseline + default adapter battery at ${STEPS} steps"
echo "============================================================"
STEPS="$STEPS" LOGDIR="$LOGDIR" MAKE_VIDEOS=0 bash run_all_tests.sh

echo
echo "============================================================"
echo "2/3 Running timing-biased adapted scenarios at ${STEPS} steps"
echo "============================================================"
FORCE_RERUN=1 \
STEPS="$STEPS" \
OLD_LOGDIR="$LOGDIR" \
OUTDIR="$TIMING_LOGDIR" \
./run_timing_biased_on_old_tests.sh

echo
echo "============================================================"
echo "3/3 Generating textual comparison"
echo "============================================================"
OLD_LOGDIR="$LOGDIR" \
TIMING_LOGDIR="$TIMING_LOGDIR" \
python "$TIMING_LOGDIR/compare_default_vs_timing.py" \
  | tee "$PLOTDIR/compare_default_vs_timing_1000.txt"

echo
echo "============================================================"
echo "FINAL 1000-STEP PIPELINE COMPLETE"
echo "============================================================"
echo "Next:"
echo "  bash generate_final_plots_and_assets.sh"
echo "============================================================"
