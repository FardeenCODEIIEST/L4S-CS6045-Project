#!/usr/bin/env python3
"""Generate fixed-threshold baseline confidence intervals from fixed_run_* results."""

from __future__ import annotations

import argparse
import glob
import json
import math
import statistics
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "results" / "ablation_plots" / "fixed_baseline_ci.json"
T_CRITICAL_95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


def resolve_result_dirs(pattern: str) -> list[Path]:
    pattern_path = Path(pattern)
    glob_pattern = str(pattern_path if pattern_path.is_absolute() else REPO_ROOT / pattern)
    return [Path(match) for match in sorted(glob.glob(glob_pattern))]


def load_summary(result_dir: Path) -> dict:
    summary_path = result_dir / "summary.json"
    if not summary_path.exists():
        raise SystemExit(f"missing summary.json: {summary_path}")
    with summary_path.open() as handle:
        return json.load(handle)


def extract_metrics(summary: dict) -> dict[str, float]:
    classes = summary["classes"]
    l4s = classes["l4s"]
    classic = classes["classic"]
    fairness = summary["fairness"]
    return {
        "l4s_mbps": float(l4s["server_mbps"]),
        "classic_mbps": float(classic["server_mbps"]),
        "jain_fairness": float(fairness["jain_server_throughput"]),
        "l4s_share": float(fairness["l4s_share"]),
    }


def ci(values: list[float]) -> dict[str, float | int | list[float]]:
    n = len(values)
    mean = statistics.mean(values)
    if n < 2:
        return {
            "n": n,
            "mean": mean,
            "ci_lo": mean,
            "ci_hi": mean,
            "sample_stddev": 0.0,
            "standard_error": 0.0,
            "t_critical": math.nan,
            "values": values,
        }

    sample_stddev = statistics.stdev(values)
    standard_error = sample_stddev / math.sqrt(n)
    t_critical = T_CRITICAL_95.get(n - 1, 1.96)
    margin = t_critical * standard_error
    return {
        "n": n,
        "mean": mean,
        "ci_lo": mean - margin,
        "ci_hi": mean + margin,
        "sample_stddev": sample_stddev,
        "standard_error": standard_error,
        "t_critical": t_critical,
        "values": values,
    }


def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate fixed baseline CI JSON for ablation plots.")
    parser.add_argument("--pattern", default="results/fixed_run_*", help="Glob for fixed result directories.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = create_arg_parser().parse_args(argv)
    result_dirs = resolve_result_dirs(args.pattern)
    if not result_dirs:
        raise SystemExit(f"no result directories matched: {args.pattern}")

    per_run = []
    for result_dir in result_dirs:
        per_run.append({"result_dir": str(result_dir), **extract_metrics(load_summary(result_dir))})

    metric_names = [name for name in per_run[0] if name != "result_dir"]
    baseline = {
        "label": "Fixed baseline",
        "result_dirs": [run["result_dir"] for run in per_run],
        "metrics": {
            metric: ci([float(run[metric]) for run in per_run])
            for metric in metric_names
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    print(f"Read {len(per_run)} fixed result directories")
    print(f"Wrote {args.output}")
    for metric, stats in baseline["metrics"].items():
        print(
            f"{metric}: mean={stats['mean']:.6f}, "
            f"95% CI=[{stats['ci_lo']:.6f}, {stats['ci_hi']:.6f}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
