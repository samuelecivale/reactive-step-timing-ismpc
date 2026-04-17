#!/usr/bin/env python3
"""
show_results.py — Legge i JSON dalla cartella dei log e stampa
la griglia completa + confronti rapidi + raccomandazioni viewer.

Uso:
    python show_results.py                      # default: logs_final/
    python show_results.py logs_body_tuning/    # altra cartella
    python show_results.py logs_*/              # più cartelle insieme
"""
import glob
import json
import os
import sys


def load_rows(logdirs):
    rows = []
    tuning = None
    seen = set()

    for logdir in logdirs:
        for path in sorted(glob.glob(os.path.join(logdir, "*.json"))):
            if path in seen:
                continue
            seen.add(path)
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

    return rows, tuning


def fmt(x, w):
    if isinstance(x, float):
        s = f"{x:.4f}" if abs(x) < 100 else f"{x:.1f}"
    else:
        s = str(x)
    if len(s) > w:
        s = s[: w - 1] + "…"
    return s.ljust(w)


def print_full_table(rows):
    headers = [
        ("name", 46),
        ("fell", 6),
        ("ticks", 6),
        ("force", 6),
        ("phase", 6),
        ("dir", 8),
        ("step", 5),
        ("adapt", 6),
        ("upd", 4),
        ("act", 4),
        ("qpf", 4),
        ("max_err", 8),
        ("fail", 14),
    ]

    line = " | ".join(fmt(h, w) for h, w in headers)
    sep = "-+-".join("-" * w for _, w in headers)

    print("FULL RESULTS")
    print(line)
    print(sep)

    for r in rows:
        print(
            " | ".join(
                [
                    fmt(r["name"], 46),
                    fmt(r["fell"], 6),
                    fmt(r["ticks"], 6),
                    fmt(r["force"], 6),
                    fmt(r["phase"], 6),
                    fmt(r["direction"], 8),
                    fmt(r["push_step"], 5),
                    fmt(r["adapt"], 6),
                    fmt(r["updates"], 4),
                    fmt(r["activations"], 4),
                    fmt(r["qp_failures"], 4),
                    fmt(r["max_dcm_err"], 8),
                    fmt(r["failure"], 14),
                ]
            )
        )


def print_comparisons(rows):
    by_key = {}
    for r in rows:
        key = (
            r["profile"],
            r["direction"],
            r["push_step"],
            r["force"],
            r["phase"],
            r["duration"],
        )
        by_key.setdefault(key, []).append(r)

    # raggruppa per sezione
    sections = {}
    for r in rows:
        sec = r["name"].split("_")[0]
        sections.setdefault(sec, set())
        key = (
            r["profile"],
            r["direction"],
            r["push_step"],
            r["force"],
            r["phase"],
            r["duration"],
        )
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
    best_cases = []

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
                best_cases.append((key, b, a))
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

    return best_cases


def print_viewer_commands(best_cases):
    print()
    print("COMANDI VIEWER (senza --headless)")
    print("-" * 60)

    if not best_cases:
        print("Nessun caso OK trovato.")
        return

    print("Casi dove l'adapter salva il robot:\n")
    for key, b, a in best_cases[:8]:
        prof, dirn, step, force, phase, dur = key
        print(
            f"  # Baseline (cade)\n"
            f"  python simulation.py "
            f"--profile {prof} --force {force} --duration {dur} "
            f"--direction {dirn} --push-step {step} --push-phase {phase} "
            f"--push-target base\n"
            f"\n"
            f"  # Adapted (sopravvive)\n"
            f"  python simulation.py --adapt "
            f"--profile {prof} --force {force} --duration {dur} "
            f"--direction {dirn} --push-step {step} --push-phase {phase} "
            f"--push-target base\n"
        )


def main():
    if len(sys.argv) > 1:
        logdirs = sys.argv[1:]
    else:
        # cerca la cartella più recente
        candidates = ["logs_final", "logs_extra_v2", "logs_body_tuning"]
        logdirs = [d for d in candidates if os.path.isdir(d)]
        if not logdirs:
            logdirs = sorted(glob.glob("logs*/"))
        if not logdirs:
            print("Nessuna cartella di log trovata. Uso: python show_results.py <cartella>")
            sys.exit(1)

    print(f"Cartelle: {', '.join(logdirs)}")
    rows, tuning = load_rows(logdirs)

    if not rows:
        print("Nessun JSON trovato.")
        sys.exit(1)

    print(f"Test caricati: {len(rows)}\n")

    if tuning is not None:
        print("TUNING PARAMETERS")
        print("-" * 40)
        for k, v in tuning.items():
            print(f"  {k}: {v}")
        print()

    print_full_table(rows)

    print()
    print("=" * 80)
    print("CONFRONTO RAPIDO BASE vs ADAPT")
    print("=" * 80)

    best_cases = print_comparisons(rows)
    print_viewer_commands(best_cases)


if __name__ == "__main__":
    main()
