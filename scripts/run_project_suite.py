#!/usr/bin/env python3
"""Run project checks, experiments, and report summaries."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.summarize_results import summarize_results, write_summary_files


@dataclass(frozen=True)
class ExperimentCase:
    name: str
    mode: str
    l4s_bw_mbps: float
    classic_bw_mbps: float
    output_dir: Path


DEFAULT_CASES: tuple[ExperimentCase, ...] = (
    ExperimentCase("fixed_balanced", "fixed", 4.0, 4.0, Path("results/fixed_balanced")),
    ExperimentCase("dynamic_balanced", "dynamic", 4.0, 4.0, Path("results/dynamic_balanced")),
    ExperimentCase("fixed_overload_bmv2", "fixed", 8.0, 8.0, Path("results/fixed_overload_bmv2")),
    ExperimentCase("dynamic_overload_tuned", "dynamic", 8.0, 8.0, Path("results/dynamic_overload_tuned")),
)


def shell_join(command: Iterable[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def run_command(command: list[str], *, dry_run: bool = False, env: dict[str, str] | None = None) -> None:
    print(f"$ {shell_join(command)}")
    if dry_run:
        return
    subprocess.run(command, cwd=REPO_ROOT, env=env, check=True)


def sudo_prefix(use_sudo: bool) -> list[str]:
    return ["sudo"] if use_sudo and os.geteuid() != 0 else []


def run_checks(python: str, dry_run: bool = False) -> None:
    env = os.environ.copy()
    env["PYTHON"] = python
    run_command(["make", "test", f"PYTHON={python}"], dry_run=dry_run, env=env)


def select_cases(names: list[str] | None) -> list[ExperimentCase]:
    cases_by_name = {case.name: case for case in DEFAULT_CASES}
    if not names:
        return list(DEFAULT_CASES)

    missing = [name for name in names if name not in cases_by_name]
    if missing:
        available = ", ".join(sorted(cases_by_name))
        raise SystemExit(f"unknown experiment case(s): {', '.join(missing)}; available: {available}")
    return [cases_by_name[name] for name in names]


def run_experiment_case(
    case: ExperimentCase,
    *,
    duration_s: int,
    use_sudo: bool,
    clean_mininet: bool,
    dry_run: bool,
) -> None:
    prefix = sudo_prefix(use_sudo)
    if clean_mininet:
        run_command([*prefix, "mn", "-c"], dry_run=dry_run)

    mode_flag = "--run-fixed" if case.mode == "fixed" else "--run-dynamic"
    run_command(
        [
            *prefix,
            "python3",
            "topo/topology.py",
            mode_flag,
            "--experiment-duration",
            str(duration_s),
            "--l4s-bw",
            str(case.l4s_bw_mbps),
            "--classic-bw",
            str(case.classic_bw_mbps),
            "--output-dir",
            str(case.output_dir),
        ],
        dry_run=dry_run,
    )


def run_experiments(
    cases: list[ExperimentCase],
    *,
    duration_s: int,
    use_sudo: bool,
    clean_mininet: bool,
    dry_run: bool,
) -> None:
    for case in cases:
        selected = replace(case, output_dir=Path(case.output_dir))
        run_experiment_case(
            selected,
            duration_s=duration_s,
            use_sudo=use_sudo,
            clean_mininet=clean_mininet,
            dry_run=dry_run,
        )


def controller_trace_stats(result_dir: Path) -> dict[str, object]:
    trace_path = result_dir / "controller_trace.jsonl"
    stats: dict[str, object] = {
        "controller_samples": 0,
        "controller_tighten": 0,
        "controller_relax": 0,
        "controller_hold": 0,
        "controller_threshold_min": None,
        "controller_threshold_max": None,
        "controller_classic_qdepth_max": None,
        "controller_classic_growth_max": None,
        "controller_l4s_qdepth_max": None,
        "controller_l4s_delay_max": None,
    }
    if not trace_path.exists():
        return stats

    rows = [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()]
    if not rows:
        return stats

    actions = Counter(row.get("action") for row in rows)
    stats.update(
        {
            "controller_samples": len(rows),
            "controller_tighten": actions.get("tighten", 0),
            "controller_relax": actions.get("relax", 0),
            "controller_hold": actions.get("hold", 0),
            "controller_threshold_min": min(row.get("new_threshold", 0) for row in rows),
            "controller_threshold_max": max(row.get("new_threshold", 0) for row in rows),
            "controller_classic_qdepth_max": max(row.get("signals", {}).get("classic_qdepth", 0) for row in rows),
            "controller_classic_growth_max": max(row.get("signals", {}).get("classic_growth", 0) for row in rows),
            "controller_l4s_qdepth_max": max(row.get("signals", {}).get("l4s_qdepth", 0) for row in rows),
            "controller_l4s_delay_max": max(row.get("signals", {}).get("l4s_delay", 0) for row in rows),
        }
    )
    return stats


def aggregate_row(name: str, result_dir: Path, summary: dict[str, object]) -> dict[str, object]:
    classes = summary["classes"]
    l4s = classes["l4s"]
    classic = classes["classic"]
    return {
        "variant": name,
        "result_dir": str(result_dir),
        "l4s_mbps": l4s["server_mbps"],
        "classic_mbps": classic["server_mbps"],
        "jain_fairness": summary["fairness"]["jain_server_throughput"],
        "l4s_share": summary["fairness"]["l4s_share"],
        "l4s_ce_rate": l4s.get("pcap", {}).get("ce_rate", 0.0),
        "classic_ce_rate": classic.get("pcap", {}).get("ce_rate", 0.0),
        "l4s_retransmits": l4s["retransmits"],
        "classic_retransmits": classic["retransmits"],
        **controller_trace_stats(result_dir),
    }


def write_aggregate(rows: list[dict[str, object]], csv_path: Path) -> None:
    if not rows:
        raise SystemExit("no summaries to write")

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    json_path = csv_path.with_suffix(".json")
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")


def summarize_many(
    result_dirs: list[Path],
    *,
    output_csv: Path,
    skip_missing: bool,
) -> list[dict[str, object]]:
    rows = []
    for result_dir in result_dirs:
        if not result_dir.exists():
            message = f"missing result directory: {result_dir}"
            if skip_missing:
                print(f"[skip] {message}")
                continue
            raise SystemExit(message)

        summary = summarize_results(result_dir)
        write_summary_files(summary, result_dir)
        rows.append(aggregate_row(result_dir.name, result_dir, summary))

    write_aggregate(rows, output_csv)
    return rows


def default_python() -> str:
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def add_case_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--case",
        action="append",
        choices=[case.name for case in DEFAULT_CASES],
        help="Experiment case to run or summarize; may be repeated. Defaults to all built-in cases.",
    )


def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run L4S project checks, experiments, and report summaries")
    subparsers = parser.add_subparsers(dest="command", required=True)

    checks = subparsers.add_parser("checks", help="Run P4 compile and Python tests")
    checks.add_argument("--python", default=default_python())
    checks.add_argument("--dry-run", action="store_true")

    experiments = subparsers.add_parser("experiments", help="Run selected Mininet/BMv2 experiment cases")
    add_case_args(experiments)
    experiments.add_argument("--duration", type=int, default=30)
    experiments.add_argument("--no-sudo", action="store_true")
    experiments.add_argument("--no-clean-mininet", action="store_true")
    experiments.add_argument("--dry-run", action="store_true")

    summarize = subparsers.add_parser("summarize", help="Summarize result directories into an aggregate CSV/JSON")
    add_case_args(summarize)
    summarize.add_argument("result_dir", nargs="*", type=Path)
    summarize.add_argument("--output", type=Path, default=Path("results/summary.csv"))
    summarize.add_argument("--skip-missing", action="store_true")

    all_cmd = subparsers.add_parser("all", help="Run checks, experiments, then aggregate summaries")
    add_case_args(all_cmd)
    all_cmd.add_argument("--python", default=default_python())
    all_cmd.add_argument("--duration", type=int, default=30)
    all_cmd.add_argument("--output", type=Path, default=Path("results/summary.csv"))
    all_cmd.add_argument("--no-sudo", action="store_true")
    all_cmd.add_argument("--no-clean-mininet", action="store_true")
    all_cmd.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "checks":
        run_checks(args.python, dry_run=args.dry_run)
        return 0

    if args.command == "experiments":
        run_experiments(
            select_cases(args.case),
            duration_s=args.duration,
            use_sudo=not args.no_sudo,
            clean_mininet=not args.no_clean_mininet,
            dry_run=args.dry_run,
        )
        return 0

    if args.command == "summarize":
        result_dirs = args.result_dir or [case.output_dir for case in select_cases(args.case)]
        summarize_many(result_dirs, output_csv=args.output, skip_missing=args.skip_missing)
        return 0

    if args.command == "all":
        cases = select_cases(args.case)
        run_checks(args.python, dry_run=args.dry_run)
        run_experiments(
            cases,
            duration_s=args.duration,
            use_sudo=not args.no_sudo,
            clean_mininet=not args.no_clean_mininet,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            summarize_many([case.output_dir for case in cases], output_csv=args.output, skip_missing=False)
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
