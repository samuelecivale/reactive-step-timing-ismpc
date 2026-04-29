#!/usr/bin/env bash
set -euo pipefail

OLD_LOGS="logs_final_1000"
TIMING_LOGS="logs_timing_biased_full_1000"
GAP_LOGS="logs_gapfill_1000"

echo "============================================================"
echo "CHECK LOG COUNTS"
echo "============================================================"
echo "$OLD_LOGS:    $(find "$OLD_LOGS" -name '*.json' | wc -l) json"
echo "$TIMING_LOGS: $(find "$TIMING_LOGS" -name '*.json' | wc -l) json"
echo "$GAP_LOGS:    $(find "$GAP_LOGS" -name '*.json' | wc -l) json"

echo
echo "============================================================"
echo "GENERATING FULL RESULT SUMMARY"
echo "============================================================"
python show_results.py "$OLD_LOGS" "$TIMING_LOGS" "$GAP_LOGS" | tee results_all_1000.txt

echo
echo "============================================================"
echo "GENERATING RADAR/BAR PLOTS: ALL COMPLETE CASES"
echo "============================================================"
python plot_better_recovery_radar.py \
  --logs "$OLD_LOGS" "$TIMING_LOGS" "$GAP_LOGS" \
  --complete-only \
  --outdir plots_final_1000/gapfilled_all

echo
echo "============================================================"
echo "GENERATING RADAR/BAR PLOTS: SHORT PUSH, PHASE 0.55"
echo "============================================================"
python plot_better_recovery_radar.py \
  --logs "$OLD_LOGS" "$TIMING_LOGS" "$GAP_LOGS" \
  --phase 0.55 \
  --duration 0.10 \
  --complete-only \
  --outdir plots_final_1000/gapfilled_p055_short

echo
echo "============================================================"
echo "GENERATING RADAR/BAR PLOTS: LONG PUSH, PHASE 0.55"
echo "============================================================"
python plot_better_recovery_radar.py \
  --logs "$OLD_LOGS" "$TIMING_LOGS" "$GAP_LOGS" \
  --phase 0.55 \
  --duration 0.20 \
  --complete-only \
  --outdir plots_final_1000/gapfilled_long

echo
echo "============================================================"
echo "GENERATING RADAR/BAR PLOTS: PAPER-STYLE EARLY PUSH"
echo "============================================================"
python plot_better_recovery_radar.py \
  --logs "$OLD_LOGS" "$TIMING_LOGS" "$GAP_LOGS" \
  --phase 0.05 \
  --duration 0.10 \
  --complete-only \
  --outdir plots_final_1000/gapfilled_paper

echo
echo "============================================================"
echo "GENERATING DEFAULT vs TIMING-BIASED TEXT COMPARISON"
echo "============================================================"
if [ -f compare_default_vs_timing.py ]; then
  OLD_LOGDIR="$OLD_LOGS" TIMING_LOGDIR="$TIMING_LOGS" python compare_default_vs_timing.py | tee compare_default_vs_timing_1000.txt
elif [ -f logs_timing_biased_full/compare_default_vs_timing.py ]; then
  OLD_LOGDIR="$OLD_LOGS" TIMING_LOGDIR="$TIMING_LOGS" python logs_timing_biased_full/compare_default_vs_timing.py | tee compare_default_vs_timing_1000.txt
else
  echo "WARNING: compare_default_vs_timing.py not found, skipping comparison."
fi

echo
echo "============================================================"
echo "GENERATED FILES"
echo "============================================================"
find plots_final_1000 -type f \( -name "*.png" -o -name "*.csv" \) | sort

echo
echo "DONE. Main figures:"
echo "  plots_final_1000/gapfilled_all/recovery_radar_clean.png"
echo "  plots_final_1000/gapfilled_all/recovery_bar_clean.png"
echo "  plots_final_1000/gapfilled_p055_short/recovery_radar_clean.png"
echo "  plots_final_1000/gapfilled_p055_short/recovery_bar_clean.png"
echo "  plots_final_1000/gapfilled_long/recovery_radar_clean.png"
echo "  plots_final_1000/gapfilled_paper/recovery_radar_clean.png"
