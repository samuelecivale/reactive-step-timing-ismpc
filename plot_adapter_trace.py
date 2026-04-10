import argparse
import json
import math
import os

import matplotlib.pyplot as plt


def load_data(path):
    with open(path, "r") as f:
        return json.load(f)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def forward_fill(values):
    out = []
    last = None
    for v in values:
        if v is not None:
            last = v
        out.append(last)
    return out


def valid_xy(times, values):
    xs, ys = [], []
    for t, v in zip(times, values):
        if v is None:
            continue
        xs.append(t)
        ys.append(v)
    return xs, ys


def add_push_window(ax, data):
    pw = data.get("push_window", {})
    dt = pw.get("dt", None)
    s = pw.get("start_tick", None)
    e = pw.get("end_tick", None)

    if dt is None or s is None or e is None:
        return

    t0 = s * dt
    t1 = e * dt
    ax.axvspan(t0, t1, alpha=0.2)


def save_dcm_error_plot(data, outdir, stem):
    trace = data.get("trace", [])
    times = [r["time_s"] for r in trace]
    errs = [r["dcm_error"] for r in trace]
    upd_t = [r["time_s"] for r in trace if r["adapter_updated"]]
    upd_e = [r["dcm_error"] for r in trace if r["adapter_updated"] and r["dcm_error"] is not None]

    plt.figure(figsize=(10, 4))
    x, y = valid_xy(times, errs)
    plt.plot(x, y)
    if upd_t and upd_e:
        plt.scatter(upd_t, upd_e)
    add_push_window(plt.gca(), data)
    plt.xlabel("time [s]")
    plt.ylabel("DCM error")
    plt.title("DCM error and adapter updates")
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, f"{stem}_dcm_error.png"), dpi=150)
    plt.close()


def save_margin_plot(data, outdir, stem):
    trace = data.get("trace", [])
    times = [r["time_s"] for r in trace]
    margins = [r["margin"] for r in trace]
    upd_t = [r["time_s"] for r in trace if r["adapter_updated"]]
    upd_m = [r["margin"] for r in trace if r["adapter_updated"] and r["margin"] is not None]

    plt.figure(figsize=(10, 4))
    x, y = valid_xy(times, margins)
    plt.plot(x, y)
    if upd_t and upd_m:
        plt.scatter(upd_t, upd_m)
    plt.axhline(0.0, linestyle="--")
    add_push_window(plt.gca(), data)
    plt.xlabel("time [s]")
    plt.ylabel("margin")
    plt.title("Viability margin and adapter updates")
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, f"{stem}_margin.png"), dpi=150)
    plt.close()


def save_step_update_plot(data, outdir, stem):
    trace = data.get("trace", [])
    times = [r["time_s"] for r in trace]

    ss_after = forward_fill([r["ss_after"] for r in trace])
    target_y = forward_fill([r["target_after_y"] for r in trace])

    fig = plt.figure(figsize=(10, 6))

    ax1 = fig.add_subplot(2, 1, 1)
    x1, y1 = valid_xy(times, ss_after)
    ax1.plot(x1, y1)
    add_push_window(ax1, data)
    ax1.set_xlabel("time [s]")
    ax1.set_ylabel("ss_duration [ticks]")
    ax1.set_title("Step timing updates")

    ax2 = fig.add_subplot(2, 1, 2)
    x2, y2 = valid_xy(times, target_y)
    ax2.plot(x2, y2)
    add_push_window(ax2, data)
    ax2.set_xlabel("time [s]")
    ax2.set_ylabel("next target y [m]")
    ax2.set_title("Next step lateral target")

    plt.tight_layout()
    plt.savefig(os.path.join(outdir, f"{stem}_step_updates.png"), dpi=150)
    plt.close()


def save_text_summary(data, outdir, stem):
    path = os.path.join(outdir, f"{stem}_summary.txt")
    adapter = data.get("adapter", {})
    tuning = data.get("tuning_params", {})

    with open(path, "w") as f:
        f.write(f"name: {stem}\n")
        f.write(f"fell: {data.get('fell')}\n")
        f.write(f"ticks: {data.get('ticks')}\n")
        f.write(f"sim_time_s: {data.get('sim_time_s')}\n")
        f.write(f"force_N: {data.get('force_N')}\n")
        f.write(f"push_phase: {data.get('push_phase')}\n")
        f.write(f"adapt_enabled: {data.get('adapt_enabled')}\n")
        f.write("\nadapter stats\n")
        for k, v in adapter.items():
            f.write(f"{k}: {v}\n")
        f.write("\ntuning params\n")
        for k, v in tuning.items():
            f.write(f"{k}: {v}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path", help="Path to one run JSON file")
    parser.add_argument("--outdir", default="plots_adapter", help="Output directory")
    args = parser.parse_args()

    data = load_data(args.json_path)
    ensure_dir(args.outdir)

    stem = os.path.splitext(os.path.basename(args.json_path))[0]

    save_dcm_error_plot(data, args.outdir, stem)
    save_margin_plot(data, args.outdir, stem)
    save_step_update_plot(data, args.outdir, stem)
    save_text_summary(data, args.outdir, stem)

    print(f"Saved plots in: {args.outdir}")


if __name__ == "__main__":
    main()