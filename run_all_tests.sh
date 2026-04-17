#!/usr/bin/env bash
# =============================================================================
# run_all_tests.sh — Batteria unificata di test
#
# Struttura:
#   A. Forward + left push su step 3 (support=rfoot) — caso principale
#   B. Forward + right push su step 4 (support=lfoot) — simmetria
#   C. Forward/backward push su step 3 e 4
#   D. In-place + left S3 / right S4
#   E. Long push (0.20s)
#   F. Frontiera fine (50-60N, P=0.55, left S3)
#   G. Paper-style: push a inizio step (P=0.05) e confronto
#
# Convenzione push-step:
#   Push LEFT  → step 3 (support=rfoot, push verso lato libero)
#   Push RIGHT → step 4 (support=lfoot, push verso lato libero)
# =============================================================================
set -u
set -o pipefail

SIM="${SIM:-simulation.py}"
STEPS="${STEPS:-1400}"
LOGDIR="${LOGDIR:-logs_final}"

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
}

# ============================================================
# A. FORWARD + LEFT su step 3 — caso principale
# ============================================================

for PH in 0.35 0.55; do
  PHTAG=$(phase_tag "$PH")

  # Baseline
  for F in 35 40 45; do
    run_test "A_fwd_base_F${F}_P${PHTAG}_left_S3" \
      --profile forward \
      --force "$F" --duration 0.10 --direction left \
      --push-step 3 --push-phase "$PH" --push-target base
  done

  # Adapted
  for F in 40 45 50 55; do
    run_test "A_fwd_adapt_F${F}_P${PHTAG}_left_S3" \
      --profile forward --adapt \
      --force "$F" --duration 0.10 --direction left \
      --push-step 3 --push-phase "$PH" --push-target base
  done
done

# Hard case PH=0.75
for F in 35 40; do
  run_test "A_fwd_base_F${F}_P075_left_S3" \
    --profile forward \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.75 --push-target base
done
for F in 40 45 50; do
  run_test "A_fwd_adapt_F${F}_P075_left_S3" \
    --profile forward --adapt \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.75 --push-target base
done

# ============================================================
# B. FORWARD + RIGHT su step 4 — simmetria
# ============================================================

for PH in 0.35 0.55; do
  PHTAG=$(phase_tag "$PH")

  for F in 35 40; do
    run_test "B_fwd_base_F${F}_P${PHTAG}_right_S4" \
      --profile forward \
      --force "$F" --duration 0.10 --direction right \
      --push-step 4 --push-phase "$PH" --push-target base
  done
  for F in 40 45 50; do
    run_test "B_fwd_adapt_F${F}_P${PHTAG}_right_S4" \
      --profile forward --adapt \
      --force "$F" --duration 0.10 --direction right \
      --push-step 4 --push-phase "$PH" --push-target base
  done
done

# ============================================================
# C. FORWARD/BACKWARD push su step 3 e 4
# ============================================================

for STEP in 3 4; do
  for PH in 0.35 0.55; do
    PHTAG=$(phase_tag "$PH")

    for F in 35 40; do
      run_test "C_fwd_base_F${F}_P${PHTAG}_fwd_S${STEP}" \
        --profile forward \
        --force "$F" --duration 0.10 --direction forward \
        --push-step "$STEP" --push-phase "$PH" --push-target base

      run_test "C_fwd_base_F${F}_P${PHTAG}_bwd_S${STEP}" \
        --profile forward \
        --force "$F" --duration 0.10 --direction backward \
        --push-step "$STEP" --push-phase "$PH" --push-target base
    done

    for F in 40 45; do
      run_test "C_fwd_adapt_F${F}_P${PHTAG}_fwd_S${STEP}" \
        --profile forward --adapt \
        --force "$F" --duration 0.10 --direction forward \
        --push-step "$STEP" --push-phase "$PH" --push-target base

      run_test "C_fwd_adapt_F${F}_P${PHTAG}_bwd_S${STEP}" \
        --profile forward --adapt \
        --force "$F" --duration 0.10 --direction backward \
        --push-step "$STEP" --push-phase "$PH" --push-target base
    done
  done
done

# ============================================================
# D. IN-PLACE — left S3, right S4
# ============================================================

# Left su step 3
for PH in 0.35 0.55; do
  PHTAG=$(phase_tag "$PH")
  for F in 25 30; do
    run_test "D_inplace_base_F${F}_P${PHTAG}_left_S3" \
      --profile inplace \
      --force "$F" --duration 0.10 --direction left \
      --push-step 3 --push-phase "$PH" --push-target base
  done
  for F in 30 35 40; do
    run_test "D_inplace_adapt_F${F}_P${PHTAG}_left_S3" \
      --profile inplace --adapt \
      --force "$F" --duration 0.10 --direction left \
      --push-step 3 --push-phase "$PH" --push-target base
  done
done

# Right su step 4
for PH in 0.35 0.55; do
  PHTAG=$(phase_tag "$PH")
  for F in 25 30; do
    run_test "D_inplace_base_F${F}_P${PHTAG}_right_S4" \
      --profile inplace \
      --force "$F" --duration 0.10 --direction right \
      --push-step 4 --push-phase "$PH" --push-target base
  done
  for F in 30 35 40; do
    run_test "D_inplace_adapt_F${F}_P${PHTAG}_right_S4" \
      --profile inplace --adapt \
      --force "$F" --duration 0.10 --direction right \
      --push-step 4 --push-phase "$PH" --push-target base
  done
done

# ============================================================
# E. LONG PUSH (0.20s) — left S3, right S4
# ============================================================

for F in 25 30 35; do
  run_test "E_long_base_F${F}_P055_left_S3" \
    --profile forward \
    --force "$F" --duration 0.20 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base

  run_test "E_long_adapt_F${F}_P055_left_S3" \
    --profile forward --adapt \
    --force "$F" --duration 0.20 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base

  run_test "E_long_base_F${F}_P055_right_S4" \
    --profile forward \
    --force "$F" --duration 0.20 --direction right \
    --push-step 4 --push-phase 0.55 --push-target base

  run_test "E_long_adapt_F${F}_P055_right_S4" \
    --profile forward --adapt \
    --force "$F" --duration 0.20 --direction right \
    --push-step 4 --push-phase 0.55 --push-target base
done

# ============================================================
# F. FRONTIERA FINE — forward left S3, 46-60N a P=0.55
# ============================================================

for F in 46 48 50 52 55 60; do
  run_test "F_frontier_base_F${F}_P055_left_S3" \
    --profile forward \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base

  run_test "F_frontier_adapt_F${F}_P055_left_S3" \
    --profile forward --adapt \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.55 --push-target base
done

# ============================================================
# G. PAPER-STYLE — push a inizio step (P=0.05)
#    Il paper testa push "at the start of a step"
# ============================================================

# Left S3
for F in 35 40 45; do
  run_test "G_paper_base_F${F}_P005_left_S3" \
    --profile forward \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.05 --push-target base

  run_test "G_paper_adapt_F${F}_P005_left_S3" \
    --profile forward --adapt \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.05 --push-target base
done

# Right S4
for F in 35 40 45; do
  run_test "G_paper_base_F${F}_P005_right_S4" \
    --profile forward \
    --force "$F" --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.05 --push-target base

  run_test "G_paper_adapt_F${F}_P005_right_S4" \
    --profile forward --adapt \
    --force "$F" --duration 0.10 --direction right \
    --push-step 4 --push-phase 0.05 --push-target base
done

# In-place, paper-style
for F in 25 30 35; do
  run_test "G_paper_inplace_base_F${F}_P005_left_S3" \
    --profile inplace \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.05 --push-target base

  run_test "G_paper_inplace_adapt_F${F}_P005_left_S3" \
    --profile inplace --adapt \
    --force "$F" --duration 0.10 --direction left \
    --push-step 3 --push-phase 0.05 --push-target base
done

# ============================================================
# SUMMARY
# ============================================================

echo "============================================================"
echo "BATTERY COMPLETE: $TOTAL test eseguiti, $FAILED falliti"
echo "============================================================"
echo

python - "$LOGDIR" <<'PYEOF'
import glob
import json
import os
import sys

logdir = sys.argv[1] if len(sys.argv) > 1 else "logs_final"

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
        "profile": d.get("profile", "?"),
        "direction": d.get("direction", "?"),
        "duration": d.get("duration_s", 0.0),
        "push_step": d.get("push_step", "?"),
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

# --- Tuning ---
if tuning is not None:
    print()
    print("TUNING PARAMETERS")
    print("-" * 40)
    for k, v in tuning.items():
        print(f"  {k}: {v}")
    print()

# --- Full table ---
headers = [
    ("name",        46),
    ("fell",         6),
    ("ticks",        6),
    ("force",        6),
    ("phase",        6),
    ("dir",          8),
    ("step",         5),
    ("adapt",        6),
    ("upd",          4),
    ("act",          4),
    ("qpf",          4),
    ("max_err",      8),
    ("fail",        14),
]

line = " | ".join(fmt(h, w) for h, w in headers)
sep  = "-+-".join("-" * w for _, w in headers)

print("FULL RESULTS")
print(line)
print(sep)

for r in rows:
    print(" | ".join([
        fmt(r["name"],        46),
        fmt(r["fell"],         6),
        fmt(r["ticks"],        6),
        fmt(r["force"],        6),
        fmt(r["phase"],        6),
        fmt(r["direction"],    8),
        fmt(r["push_step"],    5),
        fmt(r["adapt"],        6),
        fmt(r["updates"],      4),
        fmt(r["activations"],  4),
        fmt(r["qp_failures"],  4),
        fmt(r["max_dcm_err"],  8),
        fmt(r["failure"],     14),
    ]))

# --- Confronto rapido per sezione ---
print()
print("=" * 80)
print("CONFRONTO RAPIDO BASE vs ADAPT")
print("=" * 80)

by_key = {}
for r in rows:
    key = (r["profile"], r["direction"], r["push_step"],
           r["force"], r["phase"], r["duration"])
    by_key.setdefault(key, []).append(r)

# Raggruppa per sezione (lettera iniziale del nome)
sections = {}
for r in rows:
    sec = r["name"].split("_")[0]  # A, B, C, D, E, F, G
    sections.setdefault(sec, set())
    key = (r["profile"], r["direction"], r["push_step"],
           r["force"], r["phase"], r["duration"])
    sections[sec].add(key)

sec_names = {
    "A": "Forward + Left S3",
    "B": "Forward + Right S4",
    "C": "Forward/Backward push",
    "D": "In-place",
    "E": "Long push (0.20s)",
    "F": "Frontiera fine",
    "G": "Paper-style (P=0.05)",
}

wins = 0
ties = 0
losses = 0
total_comparisons = 0

for sec in sorted(sections.keys()):
    keys_in_sec = sections[sec]
    has_comparison = False
    lines_buf = []

    for key in sorted(keys_in_sec):
        if key not in by_key:
            continue
        group = by_key[key]
        base = [r for r in group if not r["adapt"]]
        adapt = [r for r in group if r["adapt"]]
        if not base or not adapt:
            continue

        has_comparison = True
        total_comparisons += 1
        b = base[0]
        a = adapt[0]

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
        lines_buf.append(
            f"  {prof:8s} {dirn:8s} S{step} F={force:5.1f}N P={phase:.2f} dt={dur:.2f}s  "
            f"base={'FELL' if b['fell'] else ' ok '}({b['ticks']:4d}t)  "
            f"adapt={'FELL' if a['fell'] else ' ok '}({a['ticks']:4d}t upd={a['updates']})  "
            f"[{tag}]"
        )

    if has_comparison:
        print(f"\n--- {sec}: {sec_names.get(sec, sec)} ---")
        for ln in lines_buf:
            print(ln)

print()
print("=" * 80)
print(f"TOTALE CONFRONTI: {total_comparisons}")
print(f"  Adapter salva (OK):     {wins}")
print(f"  Parità (==):            {ties}")
print(f"  Adapter peggiora:       {losses}")
print("=" * 80)

# --- Raccomandazioni viewer ---
print()
print("RACCOMANDAZIONI PER VIEWER (senza --headless)")
print("-" * 60)
best_cases = []
for key, group in sorted(by_key.items()):
    base = [r for r in group if not r["adapt"]]
    adapt = [r for r in group if r["adapt"]]
    if not base or not adapt:
        continue
    b = base[0]
    a = adapt[0]
    if b["fell"] and not a["fell"]:
        best_cases.append((key, b, a))

if best_cases:
    print("Casi dove l'adapter salva il robot (i più interessanti):")
    for key, b, a in best_cases[:8]:
        prof, dirn, step, force, phase, dur = key
        print(
            f"  python simulation.py --adapt "
            f"--profile {prof} --force {force} --duration {dur} "
            f"--direction {dirn} --push-step {step} --push-phase {phase} "
            f"--push-target base"
        )
    print()
    print("Per confronto, stessi parametri SENZA --adapt:")
    for key, b, a in best_cases[:4]:
        prof, dirn, step, force, phase, dur = key
        print(
            f"  python simulation.py "
            f"--profile {prof} --force {force} --duration {dur} "
            f"--direction {dirn} --push-step {step} --push-phase {phase} "
            f"--push-target base"
        )
else:
    print("Nessun caso OK trovato — controllare i risultati.")
print()
PYEOF
