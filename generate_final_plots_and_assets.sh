#!/usr/bin/env bash
# =============================================================================
# generate_final_plots_and_assets.sh
#
# Generates final plots and selected visualization assets from 1000-step logs.
#
# Usage:
#   chmod +x generate_final_plots_and_assets.sh
#   ./generate_final_plots_and_assets.sh
# =============================================================================

set -euo pipefail

BASE_LOGDIR="${BASE_LOGDIR:-logs_final_1000}"
TIMING_LOGDIR="${TIMING_LOGDIR:-logs_timing_biased_full_1000}"
OUT_ROOT="${OUT_ROOT:-plots_final_1000}"
VIZ_OUT="${VIZ_OUT:-viz_final_1000}"

mkdir -p "$OUT_ROOT" "$VIZ_OUT"

if [[ ! -d "$BASE_LOGDIR" ]]; then
  echo "[ERROR] Missing $BASE_LOGDIR"
  exit 1
fi

if [[ ! -d "$TIMING_LOGDIR" ]]; then
  echo "[ERROR] Missing $TIMING_LOGDIR"
  exit 1
fi

if [[ ! -f plot_better_recovery_radar.py ]]; then
  echo "[ERROR] Missing plot_better_recovery_radar.py"
  exit 1
fi

echo "============================================================"
echo "GENERATING FINAL PLOTS"
echo "============================================================"

python plot_better_recovery_radar.py \
  --logs "$BASE_LOGDIR" "$TIMING_LOGDIR" \
  --complete-only \
  --outdir "$OUT_ROOT/all"

python plot_better_recovery_radar.py \
  --logs "$BASE_LOGDIR" "$TIMING_LOGDIR" \
  --phase 0.55 \
  --duration 0.10 \
  --complete-only \
  --outdir "$OUT_ROOT/p055_short"

python plot_better_recovery_radar.py \
  --logs "$BASE_LOGDIR" "$TIMING_LOGDIR" \
  --phase 0.05 \
  --duration 0.10 \
  --complete-only \
  --outdir "$OUT_ROOT/paper_style"

python plot_better_recovery_radar.py \
  --logs "$BASE_LOGDIR" "$TIMING_LOGDIR" \
  --phase 0.55 \
  --duration 0.20 \
  --complete-only \
  --outdir "$OUT_ROOT/long_push"

echo
echo "============================================================"
echo "TEXT COMPARISON"
echo "============================================================"
OLD_LOGDIR="$BASE_LOGDIR" \
TIMING_LOGDIR="$TIMING_LOGDIR" \
python "$TIMING_LOGDIR/compare_default_vs_timing.py" \
  | tee "$OUT_ROOT/compare_default_vs_timing_1000.txt"

echo
echo "============================================================"
echo "GENERATING SELECTED TRACE/ANIMATION ASSETS"
echo "============================================================"

# Candidate cases for final slides/videos.
# These are chosen to show:
#   1. default adapter saving a clean lateral push;
#   2. timing-biased saving a harder frontier case;
#   3. a timing-adaptation trace;
#   4. one regression/tuning-sensitivity case, if desired.
CANDIDATES=(
  "$BASE_LOGDIR/A_fwd_base_F45_P055_left_S3.json"
  "$BASE_LOGDIR/A_fwd_adapt_F45_P055_left_S3.json"
  "$BASE_LOGDIR/F_frontier_base_F50_P055_left_S3.json"
  "$BASE_LOGDIR/F_frontier_adapt_F50_P055_left_S3.json"
  "$TIMING_LOGDIR/F_frontier_timing_biased_F50_P055_left_S3.json"
  "$TIMING_LOGDIR/A_fwd_timing_biased_F40_P075_left_S3.json"
  "$TIMING_LOGDIR/B_fwd_timing_biased_F45_P055_right_S4.json"
)

make_trace() {
  local json="$1"
  local name
  name="$(basename "$json" .json)"

  if [[ ! -f "$json" ]]; then
    echo "[SKIP] missing $json"
    return 0
  fi

  echo "[TRACE] $json"

  # Prefer timing-specific pretty plotter when available.
  if [[ -f plot_adapter_trace_timing_pretty.py ]]; then
    python plot_adapter_trace_timing_pretty.py "$json" --outdir "$VIZ_OUT" || true
  elif [[ -f plot_adapter_trace_timing.py ]]; then
    python plot_adapter_trace_timing.py "$json" --outdir "$VIZ_OUT" || true
  elif [[ -f plot_adapter_trace_fancy.py ]]; then
    python plot_adapter_trace_fancy.py "$json" --outdir "$VIZ_OUT" || true
  elif [[ -f plot_adapter_trace.py ]]; then
    python plot_adapter_trace.py "$json" --outdir "$VIZ_OUT" || true
  else
    echo "[WARN] no trace plotting script found"
  fi
}

for json in "${CANDIDATES[@]}"; do
  make_trace "$json"
done

echo
echo "============================================================"
echo "FINAL ASSETS READY"
echo "============================================================"
echo "Main plots:"
echo "  $OUT_ROOT/p055_short/recovery_radar_clean.png"
echo "  $OUT_ROOT/p055_short/recovery_bar_clean.png"
echo "  $OUT_ROOT/paper_style/recovery_bar_clean.png"
echo "  $OUT_ROOT/all/recovery_radar_clean.png"
echo
echo "Trace/video assets:"
echo "  $VIZ_OUT/"
echo
echo "Open quickly:"
echo "  xdg-open $OUT_ROOT/p055_short/recovery_radar_clean.png"
echo "  xdg-open $OUT_ROOT/p055_short/recovery_bar_clean.png"
echo "============================================================"
