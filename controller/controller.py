#!/usr/bin/env python3
"""Dynamic L4S threshold controller."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

try:
    from controller.runtime_api import RuntimeAPI
    from controller.threshold_policy import QueueSignals, ThresholdPolicyConfig, compute_threshold
except ModuleNotFoundError:
    # Allow direct execution as `python3 controller/controller.py`.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from controller.runtime_api import RuntimeAPI
    from controller.threshold_policy import QueueSignals, ThresholdPolicyConfig, compute_threshold


REGISTER_NAMES = {
    "threshold": "reg_l4s_threshold",
    "l4s_qdepth": "reg_l4s_qdepth",
    "classic_qdepth": "reg_classic_qdepth",
    "l4s_delay": "reg_l4s_delay",
    "l4s_growth": "reg_l4s_growth",
    "classic_growth": "reg_classic_growth",
}


def read_signals(runtime: RuntimeAPI) -> tuple[int, QueueSignals]:
    current_threshold = runtime.read_register(REGISTER_NAMES["threshold"])
    return current_threshold, QueueSignals(
        l4s_qdepth=runtime.read_register(REGISTER_NAMES["l4s_qdepth"]),
        classic_qdepth=runtime.read_register(REGISTER_NAMES["classic_qdepth"]),
        l4s_delay=runtime.read_register(REGISTER_NAMES["l4s_delay"]),
        l4s_growth=runtime.read_register(REGISTER_NAMES["l4s_growth"]),
        classic_growth=runtime.read_register(REGISTER_NAMES["classic_growth"]),
    )


def run_controller(
    runtime: RuntimeAPI,
    config: ThresholdPolicyConfig,
    interval_s: float,
    iterations: int | None,
    log_path: Path,
    dry_run: bool = False,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    completed = 0

    with log_path.open("a") as log_file:
        while iterations is None or completed < iterations:
            sampled_at = time.time()
            current_threshold, signals = read_signals(runtime)
            decision = compute_threshold(current_threshold, signals, config)
            if not dry_run and decision.threshold != current_threshold:
                runtime.write_register(REGISTER_NAMES["threshold"], decision.threshold)

            row = {
                "timestamp": sampled_at,
                "current_threshold": current_threshold,
                "new_threshold": decision.threshold,
                "action": decision.action,
                "reason": decision.reason,
                "signals": asdict(signals),
            }
            log_file.write(json.dumps(row, sort_keys=True) + "\n")
            log_file.flush()

            completed += 1
            if iterations is None or completed < iterations:
                time.sleep(interval_s)


def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dynamic L4S threshold controller")
    parser.add_argument("--thrift-port", type=int, default=9090)
    parser.add_argument("--cli-path", default="simple_switch_CLI")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--iterations", type=int)
    parser.add_argument("--log", type=Path, default=Path("results/dynamic/controller_trace.jsonl"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-threshold", type=int, default=ThresholdPolicyConfig.min_threshold)
    parser.add_argument("--max-threshold", type=int, default=ThresholdPolicyConfig.max_threshold)
    parser.add_argument("--growth-high", type=int, default=ThresholdPolicyConfig.growth_high)
    parser.add_argument(
        "--classic-backlog-threshold",
        type=int,
        default=ThresholdPolicyConfig.classic_backlog_threshold,
    )
    parser.add_argument("--l4s-delay-high", type=int, default=ThresholdPolicyConfig.l4s_delay_high)
    parser.add_argument("--healthy-l4s-qdepth", type=int, default=ThresholdPolicyConfig.healthy_l4s_qdepth)
    parser.add_argument(
        "--healthy-classic-qdepth",
        type=int,
        default=ThresholdPolicyConfig.healthy_classic_qdepth,
    )
    parser.add_argument("--tighten-step", type=int, default=ThresholdPolicyConfig.tighten_step)
    parser.add_argument("--relax-step", type=int, default=ThresholdPolicyConfig.relax_step)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_arg_parser()
    args = parser.parse_args(argv)
    config = ThresholdPolicyConfig(
        min_threshold=args.min_threshold,
        max_threshold=args.max_threshold,
        growth_high=args.growth_high,
        classic_backlog_threshold=args.classic_backlog_threshold,
        l4s_delay_high=args.l4s_delay_high,
        healthy_l4s_qdepth=args.healthy_l4s_qdepth,
        healthy_classic_qdepth=args.healthy_classic_qdepth,
        tighten_step=args.tighten_step,
        relax_step=args.relax_step,
    )
    runtime = RuntimeAPI(thrift_port=args.thrift_port, cli_path=args.cli_path)
    run_controller(
        runtime=runtime,
        config=config,
        interval_s=args.interval,
        iterations=args.iterations,
        log_path=args.log,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
