#!/usr/bin/env python3
"""
run_ablation.py — Controller step-size ablation study.

Sweeps relax_step × tighten_step ∈ {1,2,4,8,16,32}² with 3 trials each
(108 runs × 300 s = ~9 hours wall time). Produces:
  - One result dir per run:
      results/dynamic_run_{trial}_relax_{r}_tighten_{t}/
  - 95% confidence intervals on l4s_throughput, classic_throughput, fairness
  - Heatmaps for each metric (6×6 grid, saved as PNG)

Usage:
    # Run all experiments then analyse
    sudo env PATH=$PATH PYTHONPATH=. python3 scripts/run_ablation.py run

    # Analyse existing results (no root needed)
    python3 scripts/run_ablation.py analyze

    # Both in sequence
    sudo env PATH=$PATH PYTHONPATH=. python3 scripts/run_ablation.py all
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths and parameters
# ---------------------------------------------------------------------------

# REPO_ROOT is the project root — the directory containing topo/, eval/, etc.
# When run as 'python3 scripts/run_ablation.py' from the project root,
# __file__ resolves to <root>/scripts/run_ablation.py so parents[1] is correct.
# If run from elsewhere (e.g. during dev), override with --repo-root.
_SCRIPT_DERIVED_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT   = _SCRIPT_DERIVED_ROOT
BASE_CONFIG = REPO_ROOT / "topo" / "config_fair_dynamic.yaml"
RESULTS_DIR = REPO_ROOT / "results"
PLOTS_DIR   = REPO_ROOT / "results" / "ablation_plots"

STEP_VALUES: tuple[int, ...] = (1, 2, 4, 8, 16, 32)
TRIALS:      tuple[int, ...] = (1, 2, 3)
DURATION_S  = 180
L4S_BW      = 10.0
CLASSIC_BW  = 10.0

# t(0.025, df=2) — 95 % CI with 3 samples
T_CRITICAL  = 4.303


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shell_join(cmd: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in cmd)


def _subprocess_env() -> dict[str, str]:
    """Preserve PATH and PYTHONPATH across sudo."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    repo     = str(REPO_ROOT)
    if repo not in existing.split(":"):
        env["PYTHONPATH"] = f"{repo}:{existing}" if existing else repo
    return env


def _result_dir(trial: int, relax: int, tighten: int) -> Path:
    return RESULTS_DIR / f"dynamic_run_{trial}_relax_{relax}_tighten_{tighten}"


def _make_config(base: dict, relax: int, tighten: int, tmp_dir: str) -> Path:
    """Write a temporary config yaml with the given step values."""
    cfg = copy.deepcopy(base)
    cfg.setdefault("controller", {})["relax_step"]   = relax
    cfg["controller"]["tighten_step"] = tighten
    path = Path(tmp_dir) / f"cfg_relax{relax}_tighten{tighten}.yaml"
    path.write_text(yaml.dump(cfg, default_flow_style=False))
    return path


def _run(cmd: list[str], *, dry_run: bool = False) -> None:
    print(f"$ {_shell_join(cmd)}")
    if dry_run:
        return
    subprocess.run(cmd, cwd=REPO_ROOT, env=_subprocess_env(), check=True)


def _ci(values: list[float]) -> tuple[float, float, float]:
    """Return (mean, lower_bound, upper_bound) for a 95 % CI."""
    n   = len(values)
    mu  = sum(values) / n
    if n < 2:
        return mu, mu, mu
    variance = sum((x - mu) ** 2 for x in values) / (n - 1)
    se = math.sqrt(variance / n)
    margin = T_CRITICAL * se
    return mu, mu - margin, mu + margin


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------

def run_trial(
    trial: int,
    relax: int,
    tighten: int,
    base_cfg: dict,
    tmp_dir: str,
    *,
    dry_run: bool = False,
) -> None:
    """Run one trial and summarise results."""
    out_dir    = _result_dir(trial, relax, tighten)
    config_path = _make_config(base_cfg, relax, tighten, tmp_dir)

    print(
        f"\n{'='*60}\n"
        f"  trial={trial}  relax_step={relax}  tighten_step={tighten}\n"
        f"  output → {out_dir.relative_to(REPO_ROOT)}\n"
        f"{'='*60}"
    )

    # Step 1 — aggressive Mininet cleanup before each run.
    # NOTE: do NOT use a single bash -c string for all pkill commands — the bash
    # process's own command line would contain the pattern strings, causing pkill
    # -f to SIGTERM the bash process itself (exit -15). Use separate calls instead.
    prefix = ["sudo"] if not dry_run and os.geteuid() != 0 else []
    _run([*prefix, "mn", "-c"], dry_run=dry_run)
    if not dry_run:
        import re as _re
        # Kill leftover simple_switch (match by exact process name, not -f)
        subprocess.run([*prefix, "pkill", "-x", "simple_switch"],
                       capture_output=True)
        # Kill leftover controller.py (separate call — cmdline won't self-match)
        subprocess.run([*prefix, "pkill", "-f", "controller.py"],
                       capture_output=True)
        time.sleep(2)
        # Delete stale veth interfaces left by a crashed Mininet
        iface_out = subprocess.run(
            ["ip", "link", "show"], capture_output=True, text=True
        ).stdout
        for iface in _re.findall(r"[-a-z0-9]+-eth[0-9]+", iface_out):
            subprocess.run([*prefix, "ip", "link", "delete", iface],
                           capture_output=True)
    else:
        print("$ pkill -x simple_switch")
        print("$ pkill -f controller.py")
        print("$ [delete stale veth interfaces]")
    _run(
        [
            *prefix,
            "python3", "topo/topology.py",
            "--run-dynamic",
            "--experiment-duration", str(DURATION_S),
            "--l4s-bw",    str(L4S_BW),
            "--classic-bw", str(CLASSIC_BW),
            "--config",    str(config_path),
            "--output-dir", str(out_dir),
        ],
        dry_run=dry_run,
    )

    # Step 2 — summarise
    _run(
        [sys.executable, "-m", "eval.summarize_results", str(out_dir)],
        dry_run=dry_run,
    )


def run_all_trials(
    *,
    trials: tuple[int, ...] = TRIALS,
    step_values: tuple[int, ...] = STEP_VALUES,
    dry_run: bool = False,
) -> None:
    """Sweep all (relax, tighten, trial) combinations."""
    if not dry_run and os.geteuid() != 0:
        raise SystemExit(
            "Run experiments as root:\n"
            "  sudo env PATH=$PATH PYTHONPATH=. python3 scripts/run_ablation.py run"
        )

    base_cfg = yaml.safe_load(BASE_CONFIG.read_text())
    total       = len(trials) * len(step_values) ** 2
    done        = 0
    failed_runs: list[tuple[int, int, int]] = []

    with tempfile.TemporaryDirectory(prefix="l4s_ablation_") as tmp_dir:
        for trial in trials:
            for relax in step_values:
                for tighten in step_values:
                    done += 1
                    elapsed_hint = f"[{done}/{total}]"
                    print(f"\n{elapsed_hint} relax={relax} tighten={tighten} trial={trial}")
                    try:
                        run_trial(trial, relax, tighten, base_cfg, tmp_dir, dry_run=dry_run)
                    except subprocess.CalledProcessError as exc:
                        print(
                            f"[ERROR] trial={trial} relax={relax} tighten={tighten} "
                            f"failed with exit code {exc.returncode} — skipping, continuing sweep."
                        )
                        failed_runs.append((trial, relax, tighten))
                        time.sleep(2)  # brief pause before next run

    print(f"\n{'='*60}")
    print(f"  Sweep complete: {done - len(failed_runs)}/{total} runs succeeded.")
    if failed_runs:
        print(f"  Failed runs ({len(failed_runs)}):")
        for t, r, tg in failed_runs:
            print(f"    trial={t} relax={r} tighten={tg}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Analysis and heatmaps
# ---------------------------------------------------------------------------

def _load_summary(result_dir: Path) -> dict | None:
    path = result_dir / "summary.json"
    if not path.exists():
        print(f"[WARN] missing {path}")
        return None
    with path.open() as f:
        return json.load(f)


def _extract_metrics(summary: dict) -> dict[str, float]:
    classes = summary.get("classes", {})
    l4s     = classes.get("l4s",     {})
    classic = classes.get("classic", {})
    fairness = summary.get("fairness", {})
    return {
        "l4s_mbps":      l4s.get("server_mbps", float("nan")),
        "classic_mbps":  classic.get("server_mbps", float("nan")),
        "jain_fairness": fairness.get("jain_server_throughput", float("nan")),
        "l4s_share":     fairness.get("l4s_share", float("nan")),
    }


def analyze_results(
    *,
    step_values: tuple[int, ...] = STEP_VALUES,
    trials: tuple[int, ...] = TRIALS,
    output_dir: Path = PLOTS_DIR,
) -> None:
    """Collect per-cell metric samples, compute 95% CIs, write JSON + console table."""
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics = ("l4s_mbps", "classic_mbps", "jain_fairness", "l4s_share")

    # cell_data[relax][tighten][metric] = [val_trial1, val_trial2, ...]
    cell_data: dict[int, dict[int, dict[str, list[float]]]] = {}
    for relax in step_values:
        cell_data[relax] = {}
        for tighten in step_values:
            cell_data[relax][tighten] = {m: [] for m in metrics}
            for trial in trials:
                rd      = _result_dir(trial, relax, tighten)
                summary = _load_summary(rd)
                if summary is None:
                    continue
                vals = _extract_metrics(summary)
                for m in metrics:
                    cell_data[relax][tighten][m].append(vals[m])

    # Compute CIs
    ci_table: dict[str, dict] = {m: {} for m in metrics}
    for m in metrics:
        rows = []
        for relax in step_values:
            row = []
            for tighten in step_values:
                samples = cell_data[relax][tighten][m]
                row.append(_ci(samples) if samples else (float("nan"),) * 3)
            rows.append(row)
        ci_table[m] = {"step_values": list(step_values), "rows": rows}

    # Write CI JSON
    ci_json_path = output_dir / "confidence_intervals.json"
    ci_out = {}
    for m in metrics:
        ci_out[m] = []
        for ri, relax in enumerate(step_values):
            for ti, tighten in enumerate(step_values):
                mean_, lo, hi = ci_table[m]["rows"][ri][ti]
                ci_out[m].append(
                    {
                        "relax_step":   relax,
                        "tighten_step": tighten,
                        "mean":  round(mean_, 4),
                        "ci_lo": round(lo,    4),
                        "ci_hi": round(hi,    4),
                    }
                )
    ci_json_path.write_text(json.dumps(ci_out, indent=2))
    print(f"Wrote {ci_json_path}")

    # Print console table
    print(f"\n{'='*72}")
    print(f"  95% Confidence Intervals  ({len(trials)} trials per cell, t-crit={T_CRITICAL})")
    print(f"{'='*72}")
    for m in metrics:
        print(f"\n  {m}:")
        header = "relax \\ tighten".ljust(16) + "  ".join(f"{t:>5}" for t in step_values)
        print("  " + header)
        for ri, relax in enumerate(step_values):
            cells = []
            for ti in range(len(step_values)):
                mu, lo, hi = ci_table[m]["rows"][ri][ti]
                cells.append("  n/a" if math.isnan(mu) else f"{mu:5.2f}")
            print(f"  {str(relax):<16}" + "  ".join(cells))

    print(f"\nRun  python3 scripts/plot_ablation.py  to generate heatmaps.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="L4S controller step-size ablation study"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_p = subparsers.add_parser("run", help="Run all 108 experiments")
    run_p.add_argument("--dry-run", action="store_true",
                       help="Print commands without executing")

    _ana = subparsers.add_parser("analyze", help="Compute CIs and generate heatmaps")

    all_p = subparsers.add_parser("all", help="Run then analyze")
    all_p.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_arg_parser()
    args   = parser.parse_args(argv)

    if args.command in ("run", "all"):
        run_all_trials(dry_run=getattr(args, "dry_run", False))

    if args.command in ("analyze", "all"):
        analyze_results()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
