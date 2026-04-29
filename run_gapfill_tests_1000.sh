#!/usr/bin/env bash
set -u

STEPS="${STEPS:-1000}"
LOGDIR="${LOGDIR:-logs_gapfill_1000}"

mkdir -p "$LOGDIR"

run_case() {
  local name="$1"
  local variant="$2"
  local profile="$3"
  local direction="$4"
  local step="$5"
  local phase="$6"
  local duration="$7"
  local force="$8"

  local json="$LOGDIR/${name}.json"
  local log="$LOGDIR/${name}.log"

  if [[ -f "$json" ]]; then
    echo "SKIP: $name"
    return
  fi

  local flags=()
  if [[ "$variant" == "adapt" ]]; then
    flags=(--adapt)
  elif [[ "$variant" == "timing_biased" ]]; then
    flags=(--adapt --timing-biased)
  fi

  echo "============================================================"
  echo "RUNNING GAPFILL: $name"
  echo "COMMAND: python simulation.py --headless --steps $STEPS --quiet ${flags[*]} --profile $profile --force $force --duration $duration --direction $direction --push-step $step --push-phase $phase --push-target base --log-json $json"
  echo "============================================================"

  python simulation.py \
    --headless \
    --steps "$STEPS" \
    --quiet \
    "${flags[@]}" \
    --profile "$profile" \
    --force "$force" \
    --duration "$duration" \
    --direction "$direction" \
    --push-step "$step" \
    --push-phase "$phase" \
    --push-target base \
    --log-json "$json" \
    > "$log" 2>&1
}

variants=(base adapt timing_biased)

echo "============================================================"
echo "GAP-FILLING TEST BATTERY"
echo "Output folder: $LOGDIR"
echo "Steps: $STEPS"
echo "============================================================"

# ------------------------------------------------------------------
# 1. Sagittal pushes during forward walking, P=0.55, dt=0.10
# ------------------------------------------------------------------
for variant in "${variants[@]}"; do
  for F in 5 10 15 20 25 30; do
    for step in 3 4; do
      run_case "C_fwd_${variant}_F${F}_P055_fwd_S${step}" \
        "$variant" forward forward "$step" 0.55 0.10 "$F"

      run_case "C_fwd_${variant}_F${F}_P055_bwd_S${step}" \
        "$variant" forward backward "$step" 0.55 0.10 "$F"
    done
  done
done

# ------------------------------------------------------------------
# 2. Long lateral pushes, P=0.55, dt=0.20
# ------------------------------------------------------------------
for variant in "${variants[@]}"; do
  for F in 5 10 15 20; do
    run_case "E_long_${variant}_F${F}_P055_left_S3" \
      "$variant" forward left 3 0.55 0.20 "$F"

    run_case "E_long_${variant}_F${F}_P055_right_S4" \
      "$variant" forward right 4 0.55 0.20 "$F"
  done
done

# ------------------------------------------------------------------
# 3. Paper-style right side, P=0.05, dt=0.10
# ------------------------------------------------------------------
for variant in "${variants[@]}"; do
  for F in 5 10 15 20 25 30; do
    run_case "G_paper_${variant}_F${F}_P005_right_S4" \
      "$variant" forward right 4 0.05 0.10 "$F"
  done
done

# ------------------------------------------------------------------
# 4. In-place low-force sweep, P=0.55, dt=0.10
# ------------------------------------------------------------------
for variant in "${variants[@]}"; do
  for F in 5 10 15 20; do
    run_case "D_inplace_${variant}_F${F}_P055_left_S3" \
      "$variant" inplace left 3 0.55 0.10 "$F"

    run_case "D_inplace_${variant}_F${F}_P055_right_S4" \
      "$variant" inplace right 4 0.55 0.10 "$F"
  done
done

echo "============================================================"
echo "GAP-FILLING COMPLETE"
echo "Output folder: $LOGDIR"
echo "============================================================"

echo
echo "Next commands:"
echo "  python show_results.py logs_final_1000 logs_timing_biased_full_1000 $LOGDIR"
echo "  python plot_better_recovery_radar.py --logs logs_final_1000 logs_timing_biased_full_1000 $LOGDIR --complete-only --outdir plots_final_1000/gapfilled_all"
echo "  python plot_better_recovery_radar.py --logs logs_final_1000 logs_timing_biased_full_1000 $LOGDIR --phase 0.55 --duration 0.10 --complete-only --outdir plots_final_1000/gapfilled_p055_short"
echo "  python plot_better_recovery_radar.py --logs logs_final_1000 logs_timing_biased_full_1000 $LOGDIR --phase 0.55 --duration 0.20 --complete-only --outdir plots_final_1000/gapfilled_long"
echo "  python plot_better_recovery_radar.py --logs logs_final_1000 logs_timing_biased_full_1000 $LOGDIR --phase 0.05 --duration 0.10 --complete-only --outdir plots_final_1000/gapfilled_paper"
