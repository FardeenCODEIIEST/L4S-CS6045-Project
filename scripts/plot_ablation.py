#!/usr/bin/env python3
"""
plot_ablation.py — Generate heatmaps and CI error-bar plots from ablation results.

Reads:  results/ablation_plots/confidence_intervals.json
        (produced by:  python3 scripts/run_ablation.py analyze)
        results/ablation_plots/fixed_baseline_ci.json
        (optional, produced by: python3 scripts/generate_fixed_baseline_ci.py)

Writes into results/ablation_plots/:
    heatmap_l4s_mbps.pdf
    heatmap_classic_mbps.pdf
    heatmap_jain_fairness.pdf
    ci_errorbar_l4s_mbps_relax_<RelaxStep>.pdf
    ci_errorbar_classic_mbps_relax_<RelaxStep>.pdf
    ci_errorbar_jain_fairness_relax_<RelaxStep>.pdf

Usage:
    python3 scripts/plot_ablation.py
    python3 scripts/plot_ablation.py --ci-json path/to/confidence_intervals.json
    python3 scripts/plot_ablation.py --output-dir results/my_plots/
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REPO_ROOT  = Path(__file__).resolve().parents[1]
PLOTS_DIR  = REPO_ROOT / "results" / "ablation_plots"
CI_JSON    = PLOTS_DIR / "confidence_intervals.json"
BASELINE_JSON = PLOTS_DIR / "fixed_baseline_ci.json"

HEATMAP_SPECS = [
    ("l4s_mbps",      "L4S Throughput (Mbps)",     "Blues"),
    ("classic_mbps",  "Classic Throughput (Mbps)", "Oranges"),
    ("jain_fairness", "Jain Fairness Index",        "RdYlGn"),
]

MAP_CASE = {
    "l4s_mbps":      "L4sMbps",
    "classic_mbps":  "ClassicMbps",
    "jain_fairness": "JainFairness"
}

# ---------------------------------------------------------------------------
# Load CI data
# ---------------------------------------------------------------------------

def load_ci(path: Path) -> dict:
    """Return {metric: [{relax_step, tighten_step, mean, ci_lo, ci_hi}, ...]}"""
    with path.open() as f:
        return json.load(f)


def load_baseline(path: Path | None) -> dict:
    """Return fixed baseline CI data, or an empty mapping if unavailable."""

    if path is None or not path.exists():
        return {}
    with path.open() as f:
        return json.load(f)


def baseline_metric(baseline: dict, metric: str) -> dict | None:
    metrics = baseline.get("metrics", {})
    value = metrics.get(metric)
    return value if isinstance(value, dict) else None


def _pivot(records: list[dict]) -> tuple[list[int], list[int], list[list[tuple]]]:
    """
    From a flat list of {relax_step, tighten_step, mean, ci_lo, ci_hi} records,
    return (relax_values, tighten_values, grid) where
    grid[ri][ti] = (mean, ci_lo, ci_hi).
    """
    relax_vals   = sorted(set(r["relax_step"]   for r in records))
    tighten_vals = sorted(set(r["tighten_step"] for r in records))
    lookup = {(r["relax_step"], r["tighten_step"]): r for r in records}
    grid = []
    for relax in relax_vals:
        row = []
        for tighten in tighten_vals:
            rec = lookup.get((relax, tighten))
            if rec:
                row.append((rec["mean"], rec["ci_lo"], rec["ci_hi"]))
            else:
                row.append((float("nan"),) * 3)
        grid.append(row)
    return relax_vals, tighten_vals, grid


# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------

def plot_heatmap(
    metric: str,
    title: str,
    cmap: str,
    relax_vals: list[int],
    tighten_vals: list[int],
    grid: list[list[tuple]],
    output_dir: Path,
) -> None:
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = np.array([[grid[ri][ti][0] for ti in range(len(tighten_vals))]
                      for ri in range(len(relax_vals))])

    fig, ax = plt.subplots(figsize=(5, 4))
    im = ax.imshow(data, cmap=cmap, aspect="auto", origin="lower")

    ax.set_xticks(range(len(tighten_vals)))
    ax.set_xticklabels(tighten_vals)
    ax.set_yticks(range(len(relax_vals)))
    ax.set_yticklabels(relax_vals)
    ax.set_xlabel("TightenStep")
    ax.set_ylabel("RelaxStep")
    ax.set_title(title)

    vrange = data.max() - data.min() + 1e-9
    for ri in range(len(relax_vals)):
        for ti in range(len(tighten_vals)):
            mu, lo, hi = grid[ri][ti]
            if not math.isnan(mu):
                margin = (hi - lo) / 2
                bright = (data[ri, ti] - data.min()) / vrange
                color  = "white" if bright > 0.6 else "black"
                ax.text(
                    ti, ri,
                    f"{mu:.2f}\n±{margin:.2f}",
                    ha="center", va="center",
                    fontsize=6, color=color,
                )

    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()

    path = output_dir / f"heatmap_{metric}.pdf"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# CI error-bar plots
# ---------------------------------------------------------------------------

def plot_errorbars(
    metric: str,
    title: str,
    relax_vals: list[int],
    tighten_vals: list[int],
    grid: list[list[tuple]],
    output_dir: Path,
    baseline: dict | None = None,
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    base = baseline_metric(baseline or {}, metric)

    for ri, relax in enumerate(relax_vals):
        fig, ax = plt.subplots(figsize=(5.5, 4.0))
        means   = [grid[ri][ti][0] for ti in range(len(tighten_vals))]
        lo_errs = [grid[ri][ti][0] - grid[ri][ti][1] for ti in range(len(tighten_vals))]
        hi_errs = [grid[ri][ti][2] - grid[ri][ti][0] for ti in range(len(tighten_vals))]
        ax.errorbar(
            tighten_vals, means,
            yerr=[lo_errs, hi_errs],
            fmt="o-", capsize=4, linewidth=1.2,
            color="tab:blue", label="Dynamic mean ± 95% CI",
        )
        ax.set_title(f"RelaxStep = {relax}", fontsize=8)
        ax.set_xlabel("TightenStep", fontsize=7)
        ax.set_ylabel(MAP_CASE.get(metric, metric), fontsize=7)
        ax.set_xticks(tighten_vals)
        ax.grid(alpha=0.3)
        if base:
            mean = base["mean"]
            ci_lo = base["ci_lo"]
            ci_hi = base["ci_hi"]
            ax.axhline(mean, color="black", linewidth=1.2, linestyle="-", label="Fixed mean")
            ax.axhline(ci_lo, color="black", linewidth=1.0, linestyle=":", label="Fixed 95% CI")
            ax.axhline(ci_hi, color="black", linewidth=1.0, linestyle=":")

        fig.suptitle(f"{title}\n95% CI vs TightenStep")
        handles, labels = ax.get_legend_handles_labels()
        fig.legend(
            handles,
            labels,
            fontsize=6,
            loc="upper right",
            bbox_to_anchor=(0.98, 0.98),
            frameon=True,
            edgecolor="black",
            framealpha=1.0,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.86))

        path = output_dir / f"ci_errorbar_{metric}_relax_{relax}.pdf"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)
        print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot ablation heatmaps and error bars")
    parser.add_argument(
        "--ci-json", type=Path, default=CI_JSON,
        help=f"Path to confidence_intervals.json (default: {CI_JSON})",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=PLOTS_DIR,
        help=f"Directory for output PNGs (default: {PLOTS_DIR})",
    )
    parser.add_argument(
        "--baseline-json", type=Path, default=BASELINE_JSON,
        help=f"Optional fixed baseline CI JSON (default: {BASELINE_JSON})",
    )
    args = parser.parse_args(argv)

    if not args.ci_json.exists():
        raise SystemExit(
            f"CI JSON not found: {args.ci_json}\n"
            "Run  python3 scripts/run_ablation.py analyze  first."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ci_data = load_ci(args.ci_json)
    baseline = load_baseline(args.baseline_json)
    if baseline:
        print(f"Loaded fixed baseline: {args.baseline_json}")
    else:
        print(f"[info] fixed baseline not found, skipping overlay: {args.baseline_json}")

    for metric, title, cmap in HEATMAP_SPECS:
        if metric not in ci_data:
            print(f"[skip] {metric} not in CI JSON")
            continue
        relax_vals, tighten_vals, grid = _pivot(ci_data[metric])
        plot_heatmap(metric, title, cmap, relax_vals, tighten_vals, grid, args.output_dir)
        plot_errorbars(metric, title, relax_vals, tighten_vals, grid, args.output_dir, baseline)

    print(f"\nDone. All plots in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
