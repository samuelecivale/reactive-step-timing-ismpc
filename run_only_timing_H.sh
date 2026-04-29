#!/usr/bin/env bash
# =============================================================================
# run_only_timing_H.sh — Solo subset H timing-biased
#
# Scopo:
#   Eseguire SOLO i test diagnostici H senza ripetere la batteria principale A-G.
#   Confronta:
#     - timing base:    baseline senza --adapt
#     - timing biased:  --adapt --timing-biased
#
# Output:
#   - JSON/log in logs_timing_weights/
#   - grafici/video in plots_timing_weights/ se gli script di plotting sono presenti
#
# Uso tipico:
#   bash run_only_timing_H.sh
#
# Override utili:
#   STEPS=900 MAKE_VIDEOS=0 bash run_only_timing_H.sh
#   TIMING_LOGDIR=logs_timing_weights_new PLOTDIR=plots_timing_weights_new bash run_only_timing_H.sh
# =============================================================================
set -u
set -o pipefail

SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-900}"
TIMING_LOGDIR="${TIMING_LOGDIR:-logs_timing_weights}"
PLOTDIR="${PLOTDIR:-plots_timing_weights}"
MAKE_PLOTS="${MAKE_PLOTS:-1}"
MAKE_VIDEOS="${MAKE_VIDEOS:-1}"

# Non tocchiamo logs_final: qui vogliamo solo i test H.
rm -rf "$TIMING_LOGDIR" "$PLOTDIR"
mkdir -p "$TIMING_LOGDIR" "$PLOTDIR"

TOTAL=0
FAILED=0

run_timing_base() {
  local NAME="$1"
  shift

  if [[ -f "$TIMING_LOGDIR/${NAME}.json" ]]; then
    echo "[SKIP] $NAME — già eseguito"
    return 0
  fi

  TOTAL=$((TOTAL + 1))

  echo "============================================================"
  echo "RUNNING TIMING BASE [$TOTAL]: $NAME"
  echo "COMMAND: python $SIM --headless --steps $STEPS $*"
  echo "============================================================"

  python "$SIM" \
    --headless \
    --steps "$STEPS" \
    --quiet \
    --log-json "$TIMING_LOGDIR/${NAME}.json" \
    "$@" \
    2>&1 | tee "$TIMING_LOGDIR/${NAME}.log"

  local EXIT_CODE=${PIPESTATUS[0]}
  if [[ $EXIT_CODE -ne 0 ]]; then
    echo "[FAIL] $NAME — exit code $EXIT_CODE"
    FAILED=$((FAILED + 1))
  fi
  echo
}

run_timing_biased() {
  local NAME="$1"
  shift

  if [[ -f "$TIMING_LOGDIR/${NAME}.json" ]]; then
    echo "[SKIP] $NAME — già eseguito"
    return 0
  fi

  TOTAL=$((TOTAL + 1))

  echo "============================================================"
  echo "RUNNING TIMING-BIASED [$TOTAL]: $NAME"
  echo "COMMAND: python $SIM --headless --steps $STEPS --adapt --timing-biased $*"
  echo "============================================================"

  python "$SIM" \
    --headless \
    --steps "$STEPS" \
    --quiet \
    --adapt \
    --timing-biased \
    --log-json "$TIMING_LOGDIR/${NAME}.json" \
    "$@" \
    2>&1 | tee "$TIMING_LOGDIR/${NAME}.log"

  local EXIT_CODE=${PIPESTATUS[0]}
  if [[ $EXIT_CODE -ne 0 ]]; then
    echo "[FAIL] $NAME — exit code $EXIT_CODE"
    FAILED=$((FAILED + 1))
  fi
  echo
}

# ============================================================
# H. TIMING-BIASED DIAGNOSTIC SUBSET
#    Questo subset NON ripete A-G.
#    Serve solo a valutare il tuning --timing-biased e a produrre
#    grafici/video dove siano visibili eventuali cambi di timing.
# ============================================================

# H1. Forward left S3 — caso principale/frontiera
for F in 46 48 50; do
  run_timing_base "H_time_base_F${F}_P055_left_S3" \
    --profile forward \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base

  run_timing_biased "H_time_biased_F${F}_P055_left_S3" \
    --profile forward \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base
 done

# H2. Forward right S4 — simmetria laterale
for F in 40 45; do
  run_timing_base "H_time_base_F${F}_P055_right_S4" \
    --profile forward \
    --force "$F" --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.55 --push-target base

  run_timing_biased "H_time_biased_F${F}_P055_right_S4" \
    --profile forward \
    --force "$F" --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.55 --push-target base
 done

# H3. In-place — casi diagnostici dove il timing può emergere,
#     ma non vanno confusi con il claim principale.
for F in 35 40; do
  run_timing_base "H_time_inplace_base_F${F}_P055_left_S3" \
    --profile inplace \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base

  run_timing_biased "H_time_inplace_biased_F${F}_P055_left_S3" \
    --profile inplace \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base
 done

for F in 30 35; do
  run_timing_base "H_time_inplace_base_F${F}_P055_right_S4" \
    --profile inplace \
    --force "$F" --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.55 --push-target base

  run_timing_biased "H_time_inplace_biased_F${F}_P055_right_S4" \
    --profile inplace \
    --force "$F" --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.55 --push-target base
 done

# H4. Paper-style early push: utile per vedere se il timing-biased
#     anticipa/ritarda la decisione vicino all'inizio dello step.
for F in 35 40; do
  run_timing_base "H_time_paper_base_F${F}_P005_left_S3" \
    --profile forward \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.05 --push-target base

  run_timing_biased "H_time_paper_biased_F${F}_P005_left_S3" \
    --profile forward \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.05 --push-target base
 done

# SUMMARY
# ============================================================

echo "============================================================"
echo "TIMING H SUBSET COMPLETE: $TOTAL test eseguiti, $FAILED falliti"
echo "============================================================"
echo

python - "$TIMING_LOGDIR" <<'PYEOF'
import glob
import json
import os
import sys

logdir = sys.argv[1] if len(sys.argv) > 1 else "logs_timing_weights"

rows = []
tuning = None

for path in sorted(glob.glob(os.path.join(logdir, "*.json"))):
    try:
        with open(path, "r") as f:
            d = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[WARN] impossibile leggere {path}: {e}")
        continue

    if tuning is None and "tuning_params" in d:
        tuning = d["tuning_params"]

    failure = d.get("failure")
    failure_type = failure.get("type", "") if isinstance(failure, dict) else ""
    adapter = d.get("adapter", {}) or {}

    # Campi opzionali: dipendono da come il logger salva le info di timing.
    timing_updates = (
        adapter.get("timing_updates")
        or adapter.get("time_updates")
        or adapter.get("T_updates")
        or adapter.get("duration_updates")
        or 0
    )

    name = os.path.basename(path).replace(".json", "")
    variant = "biased" if "biased" in name else "base"

    rows.append({
        "name": name,
        "variant": variant,
        "fell": d.get("fell"),
        "ticks": d.get("ticks"),
        "force": d.get("force_N"),
        "phase": d.get("push_phase"),
        "adapt": d.get("adapt_enabled", False),
        "profile": d.get("profile", "?"),
        "direction": d.get("direction", "?"),
        "duration": d.get("duration_s", 0.0),
        "push_step": d.get("push_step", "?"),
        "updates": adapter.get("updates", 0),
        "timing_updates": timing_updates,
        "activations": adapter.get("activations", 0),
        "qp_failures": adapter.get("qp_failures", 0),
        "max_dcm_err": adapter.get("max_dcm_error", 0.0),
        "failure": failure_type,
    })

def fmt(x, w):
    if isinstance(x, float):
        s = f"{x:.4f}" if abs(x) < 100 else f"{x:.1f}"
    else:
        s = str(x)
    if len(s) > w:
        s = s[:w-1] + "…"
    return s.ljust(w)

if tuning is not None:
    print()
    print("TUNING PARAMETERS")
    print("-" * 40)
    for k, v in tuning.items():
        print(f"  {k}: {v}")
    print()

headers = [
    ("name",        48),
    ("var",          7),
    ("fell",         6),
    ("ticks",        6),
    ("force",        6),
    ("phase",        6),
    ("dir",          8),
    ("step",         5),
    ("adapt",        6),
    ("upd",          4),
    ("tupd",         5),
    ("act",          4),
    ("qpf",          4),
    ("max_err",      8),
    ("fail",        14),
]

print("FULL TIMING-H RESULTS")
print(" | ".join(fmt(h, w) for h, w in headers))
print("-+-".join("-" * w for _, w in headers))

for r in rows:
    print(" | ".join([
        fmt(r["name"],            48),
        fmt(r["variant"],          7),
        fmt(r["fell"],             6),
        fmt(r["ticks"],            6),
        fmt(r["force"],            6),
        fmt(r["phase"],            6),
        fmt(r["direction"],        8),
        fmt(r["push_step"],        5),
        fmt(r["adapt"],            6),
        fmt(r["updates"],          4),
        fmt(r["timing_updates"],   5),
        fmt(r["activations"],      4),
        fmt(r["qp_failures"],      4),
        fmt(r["max_dcm_err"],      8),
        fmt(r["failure"],         14),
    ]))

print()
print("=" * 80)
print("CONFRONTO TIMING BASE vs TIMING-BIASED")
print("=" * 80)

by_key = {}
for r in rows:
    key = (r["profile"], r["direction"], r["push_step"],
           r["force"], r["phase"], r["duration"])
    by_key.setdefault(key, []).append(r)

wins = ties = losses = 0
total = 0

for key in sorted(by_key.keys()):
    group = by_key[key]
    base = [r for r in group if r["variant"] == "base"]
    biased = [r for r in group if r["variant"] == "biased"]
    if not base or not biased:
        continue

    total += 1
    b = base[0]
    a = biased[0]

    if not b["fell"] and not a["fell"]:
        tag = "=="
        ties += 1
    elif b["fell"] and not a["fell"]:
        tag = "OK  <<<"
        wins += 1
    elif not b["fell"] and a["fell"]:
        tag = "WORSE !!"
        losses += 1
    else:
        delta = (a["ticks"] or 0) - (b["ticks"] or 0)
        tag = f"+{delta}t" if delta > 0 else f"{delta}t"
        ties += 1

    prof, dirn, step, force, phase, dur = key
    print(
        f"  {prof:8s} {dirn:8s} S{step} F={force:5.1f}N P={phase:.2f} dt={dur:.2f}s  "
        f"base={'FELL' if b['fell'] else ' ok '}({b['ticks']:4d}t)  "
        f"biased={'FELL' if a['fell'] else ' ok '}({a['ticks']:4d}t upd={a['updates']} tupd={a['timing_updates']})  "
        f"[{tag}]"
    )

print()
print("=" * 80)
print(f"TOTALE CONFRONTI H: {total}")
print(f"  Timing-biased salva:     {wins}")
print(f"  Parità / simile:         {ties}")
print(f"  Timing-biased peggiora:  {losses}")
print("=" * 80)
print()
PYEOF

# ============================================================
# POST-PROCESSING: grafici e video
# ============================================================

if [[ "$MAKE_PLOTS" == "1" ]]; then
  echo "============================================================"
  echo "GENERATING TIMING-H RECOVERY PLOTS"
  echo "============================================================"

  if [[ -f "plot_recovery_radar.py" ]]; then
    python plot_recovery_radar.py "$TIMING_LOGDIR" || true
    [[ -f recovery_bar.png ]] && mv recovery_bar.png "$PLOTDIR/recovery_bar_timing_H.png"
    [[ -f recovery_radar.png ]] && mv recovery_radar.png "$PLOTDIR/recovery_radar_timing_H.png"
  else
    echo "[plots] plot_recovery_radar.py non trovato, salto radar/bar plots"
  fi
fi

if [[ "$MAKE_VIDEOS" == "1" ]]; then
  echo "============================================================"
  echo "GENERATING TIMING-BIASED VISUALIZATION"
  echo "============================================================"

  DEMO_JSON="$TIMING_LOGDIR/H_time_biased_F46_P055_left_S3.json"

  if [[ -f "$DEMO_JSON" && -f "plot_adapter_trace_timing_pretty.py" ]]; then
    python plot_adapter_trace_timing_pretty.py "$DEMO_JSON" \
      --outdir "$PLOTDIR" --fps 8 --stride 4 || true
  else
    echo "[video] impossibile generare video timing-biased"
    echo "        DEMO_JSON=$DEMO_JSON"
    echo "        plot_adapter_trace_timing_pretty.py presente? $(test -f plot_adapter_trace_timing_pretty.py && echo yes || echo no)"
  fi
fi

echo "============================================================"
echo "OUTPUT"
echo "============================================================"
echo "Timing-biased logs:    $TIMING_LOGDIR"
echo "Plots/videos folder:   $PLOTDIR"
echo
echo "Suggerimento:"
echo "  python show_results.py $TIMING_LOGDIR"
echo "============================================================"
