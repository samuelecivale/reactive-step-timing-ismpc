#!/usr/bin/env bash
set -uo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"
SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-1000}"
LOGDIR="${LOGDIR:-logs_body_tuning}"
CLEAN_LOGDIR="${CLEAN_LOGDIR:-1}"

TOTAL_RUNS=0
FAILED_RUNS=()

phase_tag() {
  printf '%s' "$1" | tr -d '.'
}

require_inputs() {
  if [[ ! -f "$SIM" ]]; then
    echo "[fatal] simulation file not found: $SIM" >&2
    exit 1
  fi
}

prepare_logdir() {
  if [[ "$CLEAN_LOGDIR" == "1" ]]; then
    rm -rf -- "$LOGDIR"
  fi
  mkdir -p -- "$LOGDIR"
}

run_test() {
  local name="$1"
  shift

  local json_path="$LOGDIR/${name}.json"
  local log_path="$LOGDIR/${name}.log"
  local exitcode_path="$LOGDIR/${name}.exitcode"

  local -a cmd=(
    "$PYTHON_BIN" "$SIM"
    --headless
    --steps "$STEPS"
    --quiet
    --log-json "$json_path"
    "$@"
  )

  ((TOTAL_RUNS+=1))

  if [[ -e "$json_path" || -e "$log_path" || -e "$exitcode_path" ]]; then
    echo "[run_test] duplicate output name detected: $name" >&2
    FAILED_RUNS+=("$name:duplicate_name")
    return 1
  fi

  echo "============================================================"
  echo "RUNNING: $name"
  printf 'COMMAND:'
  printf ' %q' "${cmd[@]}"
  printf '\n'
  echo "============================================================"

  "${cmd[@]}" 2>&1 | tee "$log_path"
  local rc=${PIPESTATUS[0]}
  printf '%s\n' "$rc" > "$exitcode_path"

  if (( rc != 0 )); then
    echo "[run_test] FAILED: exit code $rc" | tee -a "$log_path"
    FAILED_RUNS+=("$name:rc=$rc")
    return 0
  fi

  if [[ ! -f "$json_path" ]]; then
    echo "[run_test] FAILED: missing JSON summary" | tee -a "$log_path"
    FAILED_RUNS+=("$name:missing_json")
    return 0
  fi

  echo
  echo "Saved:"
  echo "  $log_path"
  echo "  $json_path"
  echo
}

print_summary() {
  LOGDIR="$LOGDIR" python - <<'PY'
import glob
import json
import os

logdir = os.environ['LOGDIR']
rows = []
tuning = None

for path in sorted(glob.glob(os.path.join(logdir, '*.json'))):
    with open(path, 'r') as f:
        d = json.load(f)

    if tuning is None and 'tuning_params' in d:
        tuning = d['tuning_params']

    failure = d.get('failure')
    failure_type = failure['type'] if failure else ''
    adapter = d.get('adapter', {})

    rows.append({
        'name': os.path.basename(path).replace('.json', ''),
        'fell': d.get('fell'),
        'ticks': d.get('ticks'),
        'force': d.get('force_N'),
        'phase': d.get('push_phase'),
        'updates': adapter.get('updates'),
        'activations': adapter.get('activations'),
        'qp_failures': adapter.get('qp_failures'),
        'failure': failure_type,
    })


def fmt(x, w):
    s = str(x)
    if len(s) > w:
        s = s[:w - 1] + '…'
    return s.ljust(w)


if tuning is not None:
    print()
    print('TUNING PARAMETERS')
    for k, v in tuning.items():
        print(f'{k}: {v}')
    print()

headers = [
    ('name', 42),
    ('fell', 6),
    ('ticks', 6),
    ('force', 7),
    ('phase', 7),
    ('upd', 5),
    ('act', 5),
    ('qpf', 5),
    ('failure', 14),
]

line = ' | '.join(fmt(h, w) for h, w in headers)
sep = '-+-'.join('-' * w for _, w in headers)

print('SUMMARY')
print(line)
print(sep)
for r in rows:
    print(' | '.join([
        fmt(r['name'], 42),
        fmt(r['fell'], 6),
        fmt(r['ticks'], 6),
        fmt(r['force'], 7),
        fmt(r['phase'], 7),
        fmt(r['updates'], 5),
        fmt(r['activations'], 5),
        fmt(r['qp_failures'], 5),
        fmt(r['failure'], 14),
    ]))
print()
PY
}

require_inputs
prepare_logdir

# ------------------------------------------------------------
# BASELINE REFERENCES
# ------------------------------------------------------------
for PH in 0.35 0.55; do
  PHTAG=$(phase_tag "$PH")
  for F in 35 40 45; do
    run_test "frontier_base_F${F}_P${PHTAG}" \
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
    run_test "frontier_adapt_F${F}_P${PHTAG}" \
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
  run_test "hard_base_F${F}_P${PHTAG}" \
    --profile forward \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

for F in 40 45 50; do
  run_test "hard_adapt_F${F}_P${PHTAG}" \
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
  run_test "phase_base_F40_P${PHTAG}" \
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
  run_test "phase_adapt_F45_P${PHTAG}" \
    --profile forward \
    --adapt \
    --force 45 \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

print_summary

echo "[done] total_runs=$TOTAL_RUNS"
if (( ${#FAILED_RUNS[@]} > 0 )); then
  echo "[done] failures=${#FAILED_RUNS[@]}"
  printf '  - %s\n' "${FAILED_RUNS[@]}"
else
  echo "[done] failures=0"
fi
