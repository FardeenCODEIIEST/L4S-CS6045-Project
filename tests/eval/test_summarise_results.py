"""Tests for eval.summarize_results."""

from __future__ import annotations

import json

import pytest

from eval.summarize_results import (
    end_sum,
    interval_mbps,
    jain_fairness,
    summarize_iperf_pair,
    write_summary_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_iperf3_json(
    bits_per_second: float = 40_000_000,
    retransmits: int = 0,
    sender_tcp_congestion: str = "cubic",
    error: str | None = None,
    num_intervals: int = 3,
) -> dict:
    intervals = [
        {"sum": {"bits_per_second": bits_per_second, "bytes": int(bits_per_second / 8)}}
        for _ in range(num_intervals)
    ]
    result: dict = {
        "start": {},
        "intervals": intervals,
        "end": {
            "sum_received": {
                "bits_per_second": bits_per_second,
                "bytes": int(bits_per_second / 8),
            },
            "sum_sent": {
                "bits_per_second": bits_per_second,
                "retransmits": retransmits,
            },
            "sender_tcp_congestion": sender_tcp_congestion,
            "receiver_tcp_congestion": sender_tcp_congestion,
        },
    }
    if error is not None:
        result["error"] = error
    return result


def _write_iperf3(path, **kwargs):
    path.write_text(json.dumps(_make_iperf3_json(**kwargs)))
    return path


# ---------------------------------------------------------------------------
# end_sum
# ---------------------------------------------------------------------------

def test_end_sum_prefers_sum_received():
    data = {
        "end": {
            "sum_received": {"bits_per_second": 10.0},
            "sum_sent":     {"bits_per_second": 20.0},
        }
    }
    assert end_sum(data) == {"bits_per_second": 10.0}


def test_end_sum_falls_back_to_sum_sent():
    data = {"end": {"sum_sent": {"bits_per_second": 20.0}}}
    assert end_sum(data) == {"bits_per_second": 20.0}


def test_end_sum_returns_empty_dict_when_missing():
    assert end_sum({}) == {}
    assert end_sum({"end": {}}) == {}


# ---------------------------------------------------------------------------
# interval_mbps
# ---------------------------------------------------------------------------

def test_interval_mbps_converts_bits_to_megabits():
    data = {
        "intervals": [
            {"sum": {"bits_per_second": 40_000_000}},
            {"sum": {"bits_per_second": 80_000_000}},
        ]
    }
    assert interval_mbps(data) == [40.0, 80.0]


def test_interval_mbps_skips_intervals_without_bits_per_second():
    data = {"intervals": [{"sum": {}}, {"sum": {"bits_per_second": 20_000_000}}]}
    assert interval_mbps(data) == [20.0]


def test_interval_mbps_returns_empty_list_for_no_intervals():
    assert interval_mbps({}) == []
    assert interval_mbps({"intervals": []}) == []


# ---------------------------------------------------------------------------
# jain_fairness
# ---------------------------------------------------------------------------

def test_jain_fairness_is_one_for_equal_rates():
    assert jain_fairness([5.0, 5.0]) == pytest.approx(1.0)


def test_jain_fairness_is_half_when_one_class_gets_everything():
    assert jain_fairness([10.0, 0.0]) == pytest.approx(0.5)


def test_jain_fairness_returns_zero_for_empty_input():
    assert jain_fairness([]) == 0.0


def test_jain_fairness_returns_zero_for_negative_values():
    assert jain_fairness([-1.0, 5.0]) == 0.0


def test_jain_fairness_is_symmetric():
    assert jain_fairness([3.0, 7.0]) == pytest.approx(jain_fairness([7.0, 3.0]))


# ---------------------------------------------------------------------------
# summarize_iperf_pair
# ---------------------------------------------------------------------------

def test_summarize_iperf_pair_reports_server_mbps(tmp_path):
    client = _write_iperf3(tmp_path / "client.json", bits_per_second=40_000_000)
    server = _write_iperf3(tmp_path / "server.json", bits_per_second=38_000_000)

    result = summarize_iperf_pair(client, server)

    assert result["server_mbps"] == pytest.approx(38.0)
    assert result["client_mbps"] == pytest.approx(40.0)


def test_summarize_iperf_pair_counts_intervals(tmp_path):
    client = _write_iperf3(tmp_path / "client.json", num_intervals=5)
    server = _write_iperf3(tmp_path / "server.json", num_intervals=5)

    result = summarize_iperf_pair(client, server)

    assert result["intervals"] == 5


def test_summarize_iperf_pair_reports_retransmits(tmp_path):
    client = _write_iperf3(tmp_path / "client.json", retransmits=12)
    server = _write_iperf3(tmp_path / "server.json")

    result = summarize_iperf_pair(client, server)

    assert result["retransmits"] == 12


def test_summarize_iperf_pair_reports_congestion_control(tmp_path):
    client = _write_iperf3(tmp_path / "client.json", sender_tcp_congestion="dctcp")
    server = _write_iperf3(tmp_path / "server.json")

    result = summarize_iperf_pair(client, server)

    assert result["sender_tcp_congestion"] == "dctcp"


def test_summarize_iperf_pair_captures_server_error(tmp_path):
    client = _write_iperf3(tmp_path / "client.json")
    server = _write_iperf3(
        tmp_path / "server.json",
        error="interrupt - the server has terminated",
    )

    result = summarize_iperf_pair(client, server)

    assert result["server_error"] is not None
    assert "interrupt" in result["server_error"]


# ---------------------------------------------------------------------------
# write_summary_files
# ---------------------------------------------------------------------------

def _make_summary(tmp_path) -> dict:
    return {
        "result_dir": str(tmp_path),
        "receiver_ip": "10.0.5.5",
        "classes": {
            "l4s": {
                "server_mbps": 7.5,
                "client_mbps": 7.6,
                "mean_interval_mbps": 7.4,
                "intervals": 30,
                "retransmits": 2,
                "sender_tcp_congestion": "dctcp",
                "receiver_tcp_congestion": "dctcp",
                "client_error": None,
                "server_error": None,
                "client_file": "l4s_client.json",
                "server_file": "iperf3_l4s.json",
                "pcap": {
                    "packets": 1000,
                    "payload_packets": 950,
                    "payload_bytes": 950_000,
                    "ce_packets": 50,
                    "ce_rate": 0.05,
                    "ecn_counts": {"not_ect": 0, "ect0": 0, "ect1": 950, "ce": 50},
                },
            },
            "classic": {
                "server_mbps": 2.5,
                "client_mbps": 2.6,
                "mean_interval_mbps": 2.4,
                "intervals": 30,
                "retransmits": 0,
                "sender_tcp_congestion": "cubic",
                "receiver_tcp_congestion": "cubic",
                "client_error": None,
                "server_error": None,
                "client_file": "classic_client.json",
                "server_file": "iperf3_classic.json",
                "pcap": {
                    "packets": 800,
                    "payload_packets": 780,
                    "payload_bytes": 780_000,
                    "ce_packets": 10,
                    "ce_rate": 0.0125,
                    "ecn_counts": {"not_ect": 400, "ect0": 380, "ect1": 0, "ce": 10},
                },
            },
        },
        "fairness": {
            "jain_server_throughput": 0.72,
            "l4s_share": 0.75,
        },
    }


def test_write_summary_files_creates_json_and_csv(tmp_path):
    write_summary_files(_make_summary(tmp_path), tmp_path)

    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "summary.csv").exists()


def test_write_summary_files_json_is_valid(tmp_path):
    write_summary_files(_make_summary(tmp_path), tmp_path)

    loaded = json.loads((tmp_path / "summary.json").read_text())
    assert loaded["fairness"]["jain_server_throughput"] == pytest.approx(0.72)


def test_write_summary_files_csv_has_one_row_per_class(tmp_path):
    write_summary_files(_make_summary(tmp_path), tmp_path)

    import csv
    rows = list(csv.DictReader((tmp_path / "summary.csv").open()))
    classes = {r["class"] for r in rows}
    assert classes == {"l4s", "classic"}


def test_write_summary_files_csv_contains_ce_rate(tmp_path):
    write_summary_files(_make_summary(tmp_path), tmp_path)

    import csv
    rows = {r["class"]: r for r in csv.DictReader((tmp_path / "summary.csv").open())}
    assert float(rows["l4s"]["ce_rate"]) == pytest.approx(0.05)
    assert float(rows["classic"]["ce_rate"]) == pytest.approx(0.0125)