#!/usr/bin/env bash
set -euo pipefail

# clean_github_workspace.sh
#
# Non-destructive cleanup for the reactive-step-timing-ismpc workspace.
# Default mode is DRY RUN. Use --apply to actually move files.
#
# Usage:
#   bash clean_github_workspace.sh
#   bash clean_github_workspace.sh --apply
#
# Goal:
#   Keep the GitHub-facing repository focused on:
#     - source code
#     - final 1000-tick evaluation
#     - final plots/assets/GIFs
#     - reproducible final scripts
#   Move old tuning logs, obsolete plots, temporary scripts and local artifacts
#   into archives/workspace_cleanup_<timestamp>/.

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
fi

if [[ ! -f "simulation.py" || ! -f "step_timing_adapter.py" ]]; then
  echo "[error] Run this script from the repository root."
  echo "        Expected files: simulation.py and step_timing_adapter.py"
  exit 1
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_ROOT="archives/workspace_cleanup_${STAMP}"

move_item() {
  local src="$1"
  local dst_dir="$2"

  if [[ ! -e "$src" ]]; then
    return 0
  fi

  if [[ "$APPLY" -eq 1 ]]; then
    mkdir -p "$dst_dir"
    mv "$src" "$dst_dir/"
    echo "[moved] $src -> $dst_dir/"
  else
    echo "[dry-run] mv $src $dst_dir/"
  fi
}

copy_if_exists() {
  local src="$1"
  local dst="$2"

  if [[ ! -e "$src" ]]; then
    return 0
  fi

  if [[ "$APPLY" -eq 1 ]]; then
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "[copied] $src -> $dst"
  else
    echo "[dry-run] cp $src $dst"
  fi
}

echo
if [[ "$APPLY" -eq 1 ]]; then
  echo "[mode] APPLY"
else
  echo "[mode] DRY RUN"
  echo "       Nothing will be moved. Re-run with --apply to clean the workspace."
fi
echo

# ---------------------------------------------------------------------------
# 1. Keep final folders in root
# ---------------------------------------------------------------------------
# These are intentionally NOT moved:
#
#   docs/assets/
#   logs_final_1000/
#   logs_timing_biased_full_1000/
#   logs_gapfill_1000/
#   plots_final_1000/
#   viz_final_1000/
#   urdf/
#   meshes/
#
# Rationale:
#   They support the final README/result story:
#   - 1000-tick final evaluation
#   - timing-biased ablation
#   - gap-filled frontier plots
#   - README figures/GIFs

# ---------------------------------------------------------------------------
# 2. Move obsolete / exploratory log folders
# ---------------------------------------------------------------------------

OLD_LOG_DIRS=(
  "logs_body_tuning"
  "logs_extra"
  "logs_final"
  "logs_inplace"
  "logs_phase"
  "logs_slippage"
  "logs_timing_biased_full"
  "logs_timing_check"
  "logs_timing_weights"
  "logs_viz"
)

for d in "${OLD_LOG_DIRS[@]}"; do
  move_item "$d" "${ARCHIVE_ROOT}/old_logs"
done

# ---------------------------------------------------------------------------
# 3. Move obsolete / exploratory plot and visualization folders
# ---------------------------------------------------------------------------

OLD_PLOT_DIRS=(
  "plots_better"
  "plots_better_all"
  "plots_better_H"
  "plots_better_p055"
  "plots_better_paper"
  "plots_body"
  "plots_timing_weights"
)

for d in "${OLD_PLOT_DIRS[@]}"; do
  move_item "$d" "${ARCHIVE_ROOT}/old_plots"
done

OLD_VIZ_DIRS=(
  "videos"
  "viz_adapter"
)

for d in "${OLD_VIZ_DIRS[@]}"; do
  move_item "$d" "${ARCHIVE_ROOT}/old_visualizations"
done

# ---------------------------------------------------------------------------
# 4. Move obsolete / one-off scripts
# ---------------------------------------------------------------------------
# Keep in root:
#   run_final_1000_pipeline.sh
#   run_gapfill_tests_1000.sh
#   generate_final_plots_and_assets.sh
#   generate_all_plots_1000.sh
#   run_all_tests.sh
#   run_timing_biased_on_old_tests.sh
#
# Move experimental one-off scripts.

OLD_SCRIPTS=(
  "run_inplace_tests.sh"
  "run_only_timing_H.sh"
  "run_phase_tests.sh"
  "run_slippage_tests.sh"
  "plot_recovery_radar.py"
  "plot_adapter_trace.py"
  "plot_timing_vs_step.py"
  "install_rich_trace_patch.py"
)

for f in "${OLD_SCRIPTS[@]}"; do
  move_item "$f" "${ARCHIVE_ROOT}/old_scripts"
done

# ---------------------------------------------------------------------------
# 5. Move local/temporary artifacts
# ---------------------------------------------------------------------------

OLD_MISC=(
  "albero.txt"
  "test.txt"
  "README_UPDATED_FOR_PRESENTATION.md"
  "results_all_1000.txt"
  "simulation.py.bak_rich_trace"
  "messaggio_scianca.txtù"
)

for f in "${OLD_MISC[@]}"; do
  move_item "$f" "${ARCHIVE_ROOT}/old_misc"
done

# Python cache should not stay in the repo root.
move_item "__pycache__" "${ARCHIVE_ROOT}/cache"

# ---------------------------------------------------------------------------
# 6. Ensure README assets exist if final plots/GIFs are available
# ---------------------------------------------------------------------------

copy_if_exists "plots_final_1000/gapfilled_all/recovery_bar_clean.png" \
  "docs/assets/recovery_frontier_all_bar.png"

copy_if_exists "plots_final_1000/gapfilled_all/recovery_radar_clean.png" \
  "docs/assets/recovery_frontier_all_radar.png"

copy_if_exists "plots_final_1000/gapfilled_p055_short/recovery_bar_clean.png" \
  "docs/assets/recovery_frontier_p055_dt010_bar.png"

copy_if_exists "plots_final_1000/gapfilled_p055_short/recovery_radar_clean.png" \
  "docs/assets/recovery_frontier_p055_dt010_radar.png"

copy_if_exists "plots_final_1000/gapfilled_long/recovery_bar_clean.png" \
  "docs/assets/recovery_frontier_long_dt020_bar.png"

copy_if_exists "plots_final_1000/gapfilled_paper/recovery_bar_clean.png" \
  "docs/assets/recovery_frontier_paper_bar.png"

copy_if_exists "plots_final_1000/gapfilled_paper/recovery_radar_clean.png" \
  "docs/assets/recovery_frontier_paper_radar.png"

# ---------------------------------------------------------------------------
# 7. Create/update .gitignore
# ---------------------------------------------------------------------------

if [[ "$APPLY" -eq 1 ]]; then
  touch .gitignore

  add_gitignore_line() {
    local line="$1"
    grep -qxF "$line" .gitignore || echo "$line" >> .gitignore
  }

  add_gitignore_line ""
  add_gitignore_line "# Python"
  add_gitignore_line "__pycache__/"
  add_gitignore_line "*.py[cod]"
  add_gitignore_line ".pytest_cache/"
  add_gitignore_line ""
  add_gitignore_line "# Local environments"
  add_gitignore_line ".venv/"
  add_gitignore_line "venv/"
  add_gitignore_line ".env"
  add_gitignore_line ""
  add_gitignore_line "# OS/editor noise"
  add_gitignore_line ".DS_Store"
  add_gitignore_line "*.swp"
  add_gitignore_line ""
  add_gitignore_line "# Local cleanup archives"
  add_gitignore_line "archives/workspace_cleanup_*/"
  add_gitignore_line ""
  add_gitignore_line "# Temporary local files"
  add_gitignore_line "albero.txt"
  add_gitignore_line "test.txt"
  add_gitignore_line "*.bak"
  add_gitignore_line "*.bak_*"

  echo "[updated] .gitignore"
else
  echo "[dry-run] update .gitignore"
fi

# ---------------------------------------------------------------------------
# 8. Write cleanup manifest
# ---------------------------------------------------------------------------

MANIFEST="${ARCHIVE_ROOT}/CLEANUP_MANIFEST.md"

if [[ "$APPLY" -eq 1 ]]; then
  mkdir -p "$ARCHIVE_ROOT"
  cat > "$MANIFEST" <<'EOF'
# Workspace cleanup manifest

This cleanup is non-destructive. Files were moved into this archive to keep the
GitHub-facing repository focused on the final project state.

## Kept in repository root

- Core source files:
  - `simulation.py`
  - `step_timing_adapter.py`
  - `footstep_planner.py`
  - `foot_trajectory_generator.py`
  - `ismpc.py`
  - `inverse_dynamics.py`
  - `filter.py`
  - `logger.py`
  - `utils.py`

- Final/evaluation scripts:
  - `run_final_1000_pipeline.sh`
  - `run_gapfill_tests_1000.sh`
  - `generate_final_plots_and_assets.sh`
  - `generate_all_plots_1000.sh`
  - `run_all_tests.sh`
  - `run_timing_biased_on_old_tests.sh`

- Final data/assets:
  - `logs_final_1000/`
  - `logs_timing_biased_full_1000/`
  - `logs_gapfill_1000/`
  - `plots_final_1000/`
  - `viz_final_1000/`
  - `docs/assets/`

- Robot assets:
  - `urdf/`
  - `meshes/`

## Moved to archive

- Old tuning logs and pre-1000-step logs
- Old plots and intermediate visualizations
- One-off scripts for phase/in-place/slippage/timing experiments
- Backup files, local notes, generated tree files, Python cache

## Intended final story

The repository should present the final 1000-tick evaluation, the gap-filled
recovery frontier, and the timing-biased ablation. Older exploratory runs are
kept locally but should not define the public GitHub-facing project narrative.
EOF
  echo "[written] $MANIFEST"
else
  echo "[dry-run] write cleanup manifest"
fi

echo
echo "[done]"
if [[ "$APPLY" -eq 0 ]]; then
  echo "Dry run completed. To actually clean the workspace:"
  echo "  bash clean_github_workspace.sh --apply"
else
  echo "Workspace cleaned non-destructively."
  echo
  echo "Suggested checks:"
  echo "  tree -L 2"
  echo "  git status --short"
  echo "  python3 show_results.py logs_final_1000 logs_timing_biased_full_1000 logs_gapfill_1000"
fi
