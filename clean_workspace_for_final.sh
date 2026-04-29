#!/usr/bin/env bash
# =============================================================================
# clean_workspace_for_final.sh
#
# Archives old logs/plots/videos into archives/workspace_cleanup_<timestamp>.
# It does NOT delete simulation/source files.
#
# Dry run:
#   bash clean_workspace_for_final.sh
#
# Apply:
#   APPLY=1 bash clean_workspace_for_final.sh
# =============================================================================

set -euo pipefail

STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="archives/workspace_cleanup_${STAMP}"
APPLY="${APPLY:-0}"

ITEMS=(
  "logs_body_tuning"
  "logs_extra"
  "logs_inplace"
  "logs_phase"
  "logs_slippage"
  "logs_timing_check"
  "logs_timing_weights"
  "logs_timing_biased_full"
  "logs_final"
  "logs_viz"
  "plots_better"
  "plots_better_all"
  "plots_better_H"
  "plots_better_p055"
  "plots_better_paper"
  "plots_body"
  "plots_timing_weights"
  "videos"
  "viz_adapter"
  "__pycache__"
  "simulation.py.bak_rich_trace"
  "test.txt"
)

echo "============================================================"
echo "CLEAN WORKSPACE FOR FINAL RUN"
echo "============================================================"
echo "Destination: $DEST"
echo "APPLY=$APPLY"
echo

if [[ "$APPLY" != "1" ]]; then
  echo "Dry run only. Nothing will be moved."
  echo "To apply:"
  echo "  APPLY=1 bash clean_workspace_for_final.sh"
  echo
fi

mkdir -p "$DEST"

for item in "${ITEMS[@]}"; do
  if [[ -e "$item" ]]; then
    echo "[ARCHIVE] $item -> $DEST/"
    if [[ "$APPLY" == "1" ]]; then
      mv "$item" "$DEST/"
    fi
  else
    echo "[SKIP]    $item"
  fi
done

if [[ "$APPLY" == "1" ]]; then
  mkdir -p logs_final_1000 logs_timing_biased_full_1000 plots_final_1000 videos_final_1000 viz_final_1000
  echo
  echo "Created clean final folders:"
  echo "  logs_final_1000/"
  echo "  logs_timing_biased_full_1000/"
  echo "  plots_final_1000/"
  echo "  videos_final_1000/"
  echo "  viz_final_1000/"
fi

echo
echo "Recommended next checks:"
echo "  git status --short"
echo "  tree -L 2"
echo "============================================================"
