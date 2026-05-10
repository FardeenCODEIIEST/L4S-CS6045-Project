import json

from scripts.run_project_suite import aggregate_row, controller_trace_stats


def test_controller_trace_stats_counts_actions_and_signal_maxima(tmp_path):
    trace = tmp_path / "controller_trace.jsonl"
    trace.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "action": "tighten",
                        "new_threshold": 5,
                        "signals": {
                            "classic_qdepth": 80,
                            "classic_growth": 1,
                            "l4s_qdepth": 0,
                            "l4s_delay": 3,
                        },
                    }
                ),
                json.dumps(
                    {
                        "action": "hold",
                        "new_threshold": 7,
                        "signals": {
                            "classic_qdepth": 0,
                            "classic_growth": 77,
                            "l4s_qdepth": 2,
                            "l4s_delay": 99,
                        },
                    }
                ),
            ]
        )
        + "\n"
    )

    stats = controller_trace_stats(tmp_path)

    assert stats["controller_samples"] == 2
    assert stats["controller_tighten"] == 1
    assert stats["controller_hold"] == 1
    assert stats["controller_threshold_min"] == 5
    assert stats["controller_threshold_max"] == 7
    assert stats["controller_classic_qdepth_max"] == 80
    assert stats["controller_classic_growth_max"] == 77
    assert stats["controller_l4s_qdepth_max"] == 2
    assert stats["controller_l4s_delay_max"] == 99


def test_controller_trace_stats_handles_missing_trace(tmp_path):
    stats = controller_trace_stats(tmp_path)

    assert stats["controller_samples"] == 0
    assert stats["controller_tighten"] == 0
    assert stats["controller_threshold_min"] is None


def test_aggregate_row_flattens_summary_metrics(tmp_path):
    summary = {
        "classes": {
            "l4s": {
                "server_mbps": 7.5,
                "retransmits": 3,
                "pcap": {"ce_rate": 0.02},
            },
            "classic": {
                "server_mbps": 2.0,
                "retransmits": 1,
                "pcap": {"ce_rate": 0.05},
            },
        },
        "fairness": {
            "jain_server_throughput": 0.8,
            "l4s_share": 0.78,
        },
    }

    row = aggregate_row("dynamic_overload_tuned", tmp_path, summary)

    assert row["variant"] == "dynamic_overload_tuned"
    assert row["l4s_mbps"] == 7.5
    assert row["classic_mbps"] == 2.0
    assert row["jain_fairness"] == 0.8
    assert row["l4s_ce_rate"] == 0.02
    assert row["classic_ce_rate"] == 0.05
