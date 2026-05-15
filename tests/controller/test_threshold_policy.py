from controller.threshold_policy import QueueSignals, ThresholdPolicyConfig, compute_threshold


def test_policy_tightens_on_classic_backlog():
    decision = compute_threshold(
        30,
        QueueSignals(l4s_qdepth=2, classic_qdepth=50, l4s_delay=0, l4s_growth=0),
        ThresholdPolicyConfig(classic_backlog_threshold=20, tighten_step=5),
    )

    assert decision.threshold == 25
    assert decision.action == "tighten"
    assert decision.reason == "classic_backlog"


def test_policy_tightens_on_l4s_growth():
    decision = compute_threshold(
        30,
        QueueSignals(l4s_qdepth=10, classic_qdepth=0, l4s_delay=0, l4s_growth=12),
        ThresholdPolicyConfig(growth_high=8, tighten_step=5),
    )

    assert decision.threshold == 25
    assert decision.reason == "l4s_growth"


def test_policy_relaxes_when_queues_are_healthy():
    decision = compute_threshold(
        30,
        QueueSignals(l4s_qdepth=0, classic_qdepth=0, l4s_delay=0, l4s_growth=0),
        ThresholdPolicyConfig(relax_step=2),
    )

    assert decision.threshold == 32
    assert decision.action == "relax"


def test_policy_holds_when_classic_growth_is_visible():
    decision = compute_threshold(
        30,
        QueueSignals(l4s_qdepth=0, classic_qdepth=0, l4s_delay=0, l4s_growth=0, classic_growth=8),
        ThresholdPolicyConfig(relax_step=2),
    )

    assert decision.threshold == 30
    assert decision.action == "hold"
    assert decision.reason == "within_band"


def test_policy_clamps_threshold():
    decision = compute_threshold(
        6,
        QueueSignals(l4s_qdepth=0, classic_qdepth=50, l4s_delay=0, l4s_growth=0),
        ThresholdPolicyConfig(min_threshold=5, tighten_step=10),
    )

    assert decision.threshold == 5
