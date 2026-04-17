#!/usr/bin/env bash
# =============================================================================
# run_body_tuning.sh — Battery di test body-push per confronto baseline vs adapt
#
# Bug corretti rispetto alla versione precedente:
#   1. Nomi di test duplicati: le sezioni "BASELINE", "ADAPTED", "HARD CASE"
#      e "SAME FORCE DIFFERENT PHASE" generavano lo stesso nome (es.
#      body_base_F40_P035) più volte, sovrascrivendo i JSON.
#      Ora ogni test ha un nome unico, e quelli già eseguiti non vengono ripetuti.
#   2. Mancava set -e: se la simulazione crashava, lo script proseguiva senza
#      segnalare l'errore. Ora si usa un contatore di fallimenti esplicito.
#   3. Il summary Python hardcodava "logs_body_tuning/" ignorando $LOGDIR.
#   4. La sezione "same force, different phase" confrontava baseline@40N vs
#      adapt@45N — poco pulito. Ora entrambi sono testati alla stessa forza (40N
#      e 45N) per un confronto diretto.
# =============================================================================
set -u
set -o pipefail

SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-1000}"
LOGDIR="${LOGDIR:-logs_body_tuning}"

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

  # Salta se già eseguito in questa sessione (evita duplicati)
  if [[ -f "$LOGDIR/${NAME}.json" ]]; then
    echo "[SKIP] $NAME — già eseguito"
    return 0
  fi

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
  echo "Saved:"
  echo "  $LOGDIR/${NAME}.log"
  echo "  $LOGDIR/${NAME}.json"
  echo
}

# ============================================================
# SEZIONE 1: BASELINE — nessun adattamento
# PH in {0.35, 0.55}, F in {35, 40, 45}
# ============================================================

for PH in 0.35 0.55; do
  PHTAG=$(phase_tag "$PH")
  for F in 35 40 45; do
    run_test "body_base_F${F}_P${PHTAG}" \
      --profile forward \
      --force "$F" \
      --duration 0.10 \
      --direction left \
      --push-step 3 \
      --push-phase "$PH" \
      --push-target base
  done
done

# ============================================================
# SEZIONE 2: ADAPTED — frontiera principale
# PH in {0.35, 0.55}, F in {40, 45, 50, 55}
# ============================================================

for PH in 0.35 0.55; do
  PHTAG=$(phase_tag "$PH")
  for F in 40 45 50 55; do
    run_test "body_adapt_F${F}_P${PHTAG}" \
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

# ============================================================
# SEZIONE 3: HARD CASE (PH=0.75)
# ============================================================

PH="0.75"
PHTAG=$(phase_tag "$PH")

for F in 35 40; do
  run_test "body_base_F${F}_P${PHTAG}" \
    --profile forward \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

for F in 40 45 50; do
  run_test "body_adapt_F${F}_P${PHTAG}" \
    --profile forward \
    --adapt \
    --force "$F" \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

# ============================================================
# SEZIONE 4: PHASE SWEEP — stessa forza, fasi diverse
# Aggiungiamo solo i test che le sezioni precedenti NON hanno
# già coperto. Il guard nel run_test li salta se esistono già,
# ma è più chiaro elencare esplicitamente quelli nuovi.
#
# Baseline F=40: P005 è l'unico mancante (P035,P055 già in S1, P075 in S3)
# Adapt F=45:    P005 e P075 mancanti (P035,P055 già in S2)
#
# Per un confronto pulito aggiungiamo anche adapt F=40 sulle
# stesse fasi, così si confrontano baseline@40 vs adapt@40.
# ============================================================

# Baseline F=40 — fasi aggiuntive
for PH in 0.05; do
  PHTAG=$(phase_tag "$PH")
  run_test "body_base_F40_P${PHTAG}" \
    --profile forward \
    --force 40 \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

# Adapt F=40 — confronto diretto con baseline@40
for PH in 0.05 0.35 0.55 0.75; do
  PHTAG=$(phase_tag "$PH")
  run_test "body_adapt_F40_P${PHTAG}" \
    --profile forward \
    --adapt \
    --force 40 \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

# Adapt F=45 — fasi aggiuntive
for PH in 0.05 0.75; do
  PHTAG=$(phase_tag "$PH")
  run_test "body_adapt_F45_P${PHTAG}" \
    --profile forward \
    --adapt \
    --force 45 \
    --duration 0.10 \
    --direction left \
    --push-step 3 \
    --push-phase "$PH" \
    --push-target base
done

# ============================================================
# SUMMARY
# ============================================================

echo "============================================================"
echo "BATTERY COMPLETE: $TOTAL test eseguiti, $FAILED falliti"
echo "============================================================"
echo

python - "$LOGDIR" <<'PY'
import glob
import json
import os
import sys

logdir = sys.argv[1] if len(sys.argv) > 1 else "logs_body_tuning"

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
    failure_type = failure["type"] if failure else ""
    adapter = d.get("adapter", {})

    rows.append({
        "name": os.path.basename(path).replace(".json", ""),
        "fell": d.get("fell"),
        "ticks": d.get("ticks"),
        "force": d.get("force_N"),
        "phase": d.get("push_phase"),
        "adapt": d.get("adapt_enabled", False),
        "updates": adapter.get("updates", 0),
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
    ("name",        42),
    ("fell",         6),
    ("ticks",        6),
    ("force",        6),
    ("phase",        6),
    ("adapt",        6),
    ("upd",          5),
    ("act",          5),
    ("qpf",          5),
    ("max_err",      8),
    ("failure",     14),
]

line = " | ".join(fmt(h, w) for h, w in headers)
sep  = "-+-".join("-" * w for _, w in headers)

print("SUMMARY")
print(line)
print(sep)

for r in rows:
    print(" | ".join([
        fmt(r["name"],        42),
        fmt(r["fell"],         6),
        fmt(r["ticks"],        6),
        fmt(r["force"],        6),
        fmt(r["phase"],        6),
        fmt(r["adapt"],        6),
        fmt(r["updates"],      5),
        fmt(r["activations"],  5),
        fmt(r["qp_failures"],  5),
        fmt(r["max_dcm_err"],  8),
        fmt(r["failure"],     14),
    ]))

# Tabella riassuntiva base vs adapt
print()
print("CONFRONTO RAPIDO (stessa forza/fase)")
print("-" * 60)
by_key = {}
for r in rows:
    key = (r["force"], r["phase"])
    by_key.setdefault(key, []).append(r)

for (force, phase), group in sorted(by_key.items()):
    base = [r for r in group if not r["adapt"]]
    adapt = [r for r in group if r["adapt"]]
    if not base or not adapt:
        continue
    b = base[0]
    a = adapt[0]
    arrow = "OK" if not a["fell"] and b["fell"] else ("==" if a["fell"] == b["fell"] else "WORSE")
    print(
        f"  F={force:5.1f}N P={phase:.2f}  "
        f"base={'FELL' if b['fell'] else ' ok '}  "
        f"adapt={'FELL' if a['fell'] else ' ok '}  "
        f"[{arrow}]"
    )
print()
PY
