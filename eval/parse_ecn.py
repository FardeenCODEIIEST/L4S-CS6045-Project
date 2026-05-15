"""Parse TCP ECN codepoints from experiment pcaps using tcpdump output."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


ECN_NAMES = {
    0: "not_ect",
    1: "ect1",
    2: "ect0",
    3: "ce",
}

TOS_RE = re.compile(r"\btos 0x(?P<tos>[0-9a-fA-F]+)")
FLOW_RE = re.compile(
    r"^\s*(?P<src>\d+\.\d+\.\d+\.\d+)\.(?P<src_port>\d+)"
    r" > (?P<dst>\d+\.\d+\.\d+\.\d+)\.(?P<dst_port>\d+):"
)
TCP_PAYLOAD_LEN_RE = re.compile(r", length (?P<length>\d+)$")


@dataclass
class ClassCounts:
    packets: int = 0
    payload_packets: int = 0
    payload_bytes: int = 0
    ecn: Counter[str] = field(default_factory=Counter)

    def observe(self, ecn_name: str, payload_len: int) -> None:
        self.packets += 1
        self.ecn[ecn_name] += 1
        if payload_len > 0:
            self.payload_packets += 1
            self.payload_bytes += payload_len

    def to_dict(self) -> dict[str, object]:
        ce_packets = self.ecn.get("ce", 0)
        return {
            "packets": self.packets,
            "payload_packets": self.payload_packets,
            "payload_bytes": self.payload_bytes,
            "ecn_counts": {name: self.ecn.get(name, 0) for name in ECN_NAMES.values()},
            "ce_packets": ce_packets,
            "ce_rate": ce_packets / self.packets if self.packets else 0.0,
        }


def run_tcpdump(pcap_path: Path, ports: Iterable[int]) -> str:
    """Return tcpdump text for the given pcap and TCP ports."""

    if shutil.which("tcpdump") is None:
        raise RuntimeError("tcpdump is required to parse pcaps")

    port_filter = " or ".join(f"port {port}" for port in ports)
    cmd = [
        "tcpdump",
        "-nn",
        "-tt",
        "-v",
        "-r",
        str(pcap_path),
        f"tcp and ({port_filter})",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


def parse_tcpdump_text(
    text: str,
    receiver_ip: str = "10.0.5.5",
    l4s_port: int = 5201,
    classic_port: int = 5202,
) -> dict[str, object]:
    """Parse forward-direction packet ECN counts from tcpdump text."""

    counts = {
        "l4s": ClassCounts(),
        "classic": ClassCounts(),
    }
    total_lines = 0
    pending_ecn: str | None = None

    for line in text.splitlines():
        total_lines += 1
        tos_match = TOS_RE.search(line)
        if tos_match:
            tos = int(tos_match.group("tos"), 16)
            pending_ecn = ECN_NAMES[tos & 0x3]
            continue

        flow_match = FLOW_RE.search(line)
        if not flow_match or pending_ecn is None:
            continue

        dst_ip = flow_match.group("dst")
        dst_port = int(flow_match.group("dst_port"))
        if dst_ip != receiver_ip:
            pending_ecn = None
            continue

        if dst_port == l4s_port:
            traffic_class = "l4s"
        elif dst_port == classic_port:
            traffic_class = "classic"
        else:
            pending_ecn = None
            continue

        payload_len = 0
        len_match = TCP_PAYLOAD_LEN_RE.search(line)
        if len_match:
            payload_len = int(len_match.group("length"))

        counts[traffic_class].observe(pending_ecn, payload_len)
        pending_ecn = None

    return {
        "receiver_ip": receiver_ip,
        "ports": {
            "l4s": l4s_port,
            "classic": classic_port,
        },
        "tcpdump_lines": total_lines,
        "classes": {name: class_counts.to_dict() for name, class_counts in counts.items()},
    }


def parse_pcap(
    pcap_path: str | Path,
    receiver_ip: str = "10.0.5.5",
    l4s_port: int = 5201,
    classic_port: int = 5202,
) -> dict[str, object]:
    pcap_path = Path(pcap_path)
    text = run_tcpdump(pcap_path, [l4s_port, classic_port])
    return parse_tcpdump_text(text, receiver_ip, l4s_port, classic_port)


def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse ECN codepoints from an experiment pcap")
    parser.add_argument("pcap", type=Path)
    parser.add_argument("--receiver-ip", default="10.0.5.5")
    parser.add_argument("--l4s-port", type=int, default=5201)
    parser.add_argument("--classic-port", type=int, default=5202)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = create_arg_parser()
    args = parser.parse_args(argv)
    summary = parse_pcap(args.pcap, args.receiver_ip, args.l4s_port, args.classic_port)
    json.dump(summary, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())