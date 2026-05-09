#!/usr/bin/env python3
"""Summarize one experiment result directory."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import mean

from eval.parse_pcap import parse_pcap


CLASS_FILES = {
    "l4s": {
        "client": "l4s_client.json",
        "server": "iperf3_l4s.json",
    },
    "classic": {
        "client": "classic_client.json",
        "server": "iperf3_classic.json",
    },
}


def load_json(path: Path) -> dict:
    with path.open() as handle:
        return json.load(handle)


def end_sum(data: dict) -> dict:
    end = data.get("end", {})
    return end.get("sum_received") or end.get("sum_sent") or {}


def interval_mbps(data: dict) -> list[float]:
    values = []
    for interval in data.get("intervals", []):
        bits_per_second = interval.get("sum", {}).get("bits_per_second")
        if bits_per_second is not None:
            values.append(bits_per_second / 1_000_000)
    return values


def summarize_iperf_pair(client_path: Path, server_path: Path) -> dict[str, object]:
    client = load_json(client_path)
    server = load_json(server_path)
    client_end = client.get("end", {})
    server_sum = end_sum(server)
    client_sum = end_sum(client)
    server_intervals = interval_mbps(server)

    return {
        "client_file": str(client_path),
        "server_file": str(server_path),
        "client_error": client.get("error"),
        "server_error": server.get("error"),
        "intervals": len(server.get("intervals", [])),
        "server_mbps": server_sum.get("bits_per_second", 0) / 1_000_000,
        "client_mbps": client_sum.get("bits_per_second", 0) / 1_000_000,
        "mean_interval_mbps": mean(server_intervals) if server_intervals else 0.0,
        "retransmits": client_end.get("sum_sent", {}).get("retransmits", 0),
        "sender_tcp_congestion": client_end.get("sender_tcp_congestion"),
        "receiver_tcp_congestion": client_end.get("receiver_tcp_congestion"),
    }


def jain_fairness(values: list[float]) -> float:
    if not values or any(value < 0 for value in values):
        return 0.0
    numerator = sum(values) ** 2
    denominator = len(values) * sum(value * value for value in values)
    return numerator / denominator if denominator else 0.0


def summarize_results(
    result_dir: str | Path,
    receiver_ip: str = "10.0.5.5",
    l4s_port: int = 5201,
    classic_port: int = 5202,
) -> dict[str, object]:
    result_dir = Path(result_dir)
    classes = {}
    for traffic_class, files in CLASS_FILES.items():
        classes[traffic_class] = summarize_iperf_pair(
            result_dir / files["client"],
            result_dir / files["server"],
        )

    pcap_summary = parse_pcap(
        result_dir / "capture.pcap",
        receiver_ip=receiver_ip,
        l4s_port=l4s_port,
        classic_port=classic_port,
    )
    for traffic_class, pcap_class in pcap_summary["classes"].items():
        classes[traffic_class]["pcap"] = pcap_class

    server_rates = [classes["l4s"]["server_mbps"], classes["classic"]["server_mbps"]]
    return {
        "result_dir": str(result_dir),
        "receiver_ip": receiver_ip,
        "classes": classes,
        "fairness": {
            "jain_server_throughput": jain_fairness(server_rates),
            "l4s_share": server_rates[0] / sum(server_rates) if sum(server_rates) else 0.0,
        },
    }


def write_summary_files(summary: dict[str, object], result_dir: Path) -> None:
    summary_path = result_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    rows = []
    for traffic_class, data in summary["classes"].items():
        pcap = data.get("pcap", {})
        ecn_counts = pcap.get("ecn_counts", {})
        rows.append(
            {
                "class": traffic_class,
                "server_mbps": f"{data['server_mbps']:.6f}",
                "client_mbps": f"{data['client_mbps']:.6f}",
                "intervals": data["intervals"],
                "retransmits": data["retransmits"],
                "sender_cc": data.get("sender_tcp_congestion") or "",
                "packets": pcap.get("packets", 0),
                "payload_packets": pcap.get("payload_packets", 0),
                "payload_bytes": pcap.get("payload_bytes", 0),
                "ce_packets": pcap.get("ce_packets", 0),
                "ce_rate": f"{pcap.get('ce_rate', 0):.6f}",
                "not_ect": ecn_counts.get("not_ect", 0),
                "ect0": ecn_counts.get("ect0", 0),
                "ect1": ecn_counts.get("ect1", 0),
                "ce": ecn_counts.get("ce", 0),
            }
        )

    csv_path = result_dir / "summary.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize an L4S experiment result directory")
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("--receiver-ip", default="10.0.5.5")
    parser.add_argument("--l4s-port", type=int, default=5201)
    parser.add_argument("--classic-port", type=int, default=5202)
    parser.add_argument("--no-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_arg_parser()
    args = parser.parse_args(argv)
    summary = summarize_results(args.result_dir, args.receiver_ip, args.l4s_port, args.classic_port)
    if not args.no_write:
        write_summary_files(summary, args.result_dir)
    json.dump(summary, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

