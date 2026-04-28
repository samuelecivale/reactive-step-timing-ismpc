#!/usr/bin/env python3
import argparse
import json
import math


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path")
    args = parser.parse_args()

    with open(args.json_path, "r") as f:
        data = json.load(f)

    trace = data.get("trace", [])
    dt = None

    if "push_window" in data:
        dt = data["push_window"].get("dt")

    if dt is None:
        dt = 0.01

    found = False

    print()
    print(f"FILE: {args.json_path}")
    print("-" * 90)

    for r in trace:
        if not r.get("adapter_updated", False):
            continue

        found = True

        ss_before = r.get("ss_before")
        ss_after = r.get("ss_after")

        xb = r.get("target_before_x")
        yb = r.get("target_before_y")
        xa = r.get("target_after_x")
        ya = r.get("target_after_y")

        if ss_before is None or ss_after is None:
            print(f"t={r.get('time_s')} tick={r.get('tick')} | update trovato, ma ss_before/ss_after non presenti")
            continue

        dss = int(ss_after) - int(ss_before)
        dss_ms = dss * dt * 1000.0

        if None not in [xb, yb, xa, ya]:
            dx = float(xa) - float(xb)
            dy = float(ya) - float(yb)
            dpos = math.sqrt(dx * dx + dy * dy)
        else:
            dx = dy = dpos = None

        if dss != 0 and dpos is not None and dpos > 1e-6:
            kind = "TIMING + STEP"
        elif dss != 0:
            kind = "TIMING ONLY"
        elif dpos is not None and dpos > 1e-6:
            kind = "STEP ONLY"
        else:
            kind = "NO CHANGE"

        print(
            f"t={r.get('time_s'):.2f}s tick={r.get('tick')} step={r.get('step_index')} | "
            f"ss {ss_before} -> {ss_after} "
            f"Δss={dss:+d} ticks ({dss_ms:+.1f} ms) | "
            f"Δstep={dpos if dpos is not None else None} m "
            f"dx={dx if dx is not None else None} "
            f"dy={dy if dy is not None else None} | "
            f"{kind}"
        )

    if not found:
        print("Nessun adapter update trovato nel trace.")
        print()
        print("Possibili motivi:")
        print("1. Il caso non ha attivato l'adapter.")
        print("2. Il JSON è stato generato prima della patch di logging ricco.")
        print("3. Il JSON contiene solo summary e non contiene trace.")
        print("4. Hai guardato un baseline senza --adapt.")


if __name__ == "__main__":
    main()
