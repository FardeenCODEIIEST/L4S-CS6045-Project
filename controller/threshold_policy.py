"""Threshold update policy for the dynamic L4S controller."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueueSignals:
    """Queue telemetry sampled from dataplane registers."""

    l4s_qdepth: int
    classic_qdepth: int
    l4s_delay: int
    l4s_growth: int
    classic_growth: int = 0


@dataclass(frozen=True)
class ThresholdPolicyConfig:
    """Knobs for the lightweight dynamic-threshold policy."""

    min_threshold: int = 5
    max_threshold: int = 120
    growth_high: int = 8
    classic_backlog_threshold: int = 20
    l4s_delay_high: int = 5_000
    healthy_l4s_qdepth: int = 5
    healthy_classic_qdepth: int = 5
    tighten_step: int = 5
    relax_step: int = 2
    classic_max_threshold: int = 100
    classic_protection_max_threshold: int = 32
    classic_adjust_step: int = 2
    classic_relax_step: int = 4


@dataclass(frozen=True)
class ThresholdDecision:
    threshold: int
    action: str
    reason: str


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def compute_threshold(
    current_threshold: int,
    signals: QueueSignals,
    config: ThresholdPolicyConfig = ThresholdPolicyConfig(),
) -> ThresholdDecision:
    """Return the next L4S threshold from the current sampled queue state."""

    current = clamp(current_threshold, config.min_threshold, config.max_threshold)

    if signals.classic_qdepth >= config.classic_backlog_threshold:
        return ThresholdDecision(
            threshold=clamp(current - config.tighten_step, config.min_threshold, config.max_threshold),
            action="tighten",
            reason="classic_backlog",
        )

    if signals.l4s_growth >= config.growth_high:
        return ThresholdDecision(
            threshold=clamp(current - config.tighten_step, config.min_threshold, config.max_threshold),
            action="tighten",
            reason="l4s_growth",
        )

    if signals.l4s_delay >= config.l4s_delay_high:
        return ThresholdDecision(
            threshold=clamp(current - config.tighten_step, config.min_threshold, config.max_threshold),
            action="tighten",
            reason="l4s_delay",
        )

    if (
        signals.l4s_qdepth <= config.healthy_l4s_qdepth
        and signals.classic_qdepth <= config.healthy_classic_qdepth
        and signals.l4s_growth == 0
        and signals.classic_growth == 0
    ):
        return ThresholdDecision(
            threshold=clamp(current + config.relax_step, config.min_threshold, config.max_threshold),
            action="relax",
            reason="healthy_queues",
        )

    return ThresholdDecision(
        threshold=current,
        action="hold",
        reason="within_band",
    )
