#!/usr/bin/env python3
"""
parse_pcap.py — Parse capture.pcap and iperf3 JSON outputs into CSVs
                for downstream analysis by stats.py and plot_results.py.

Outputs (--output-dir):
  packets.csv   — per-packet ECN bits, timestamps, class, port
  throughput.csv — per-interval throughput from iperf3 JSON (L4S + Classic)

Usage:
    python3 eval/parse_pcap.py --pcap results/capture.pcap
                               --l4s-json results/iperf3_l4s.json
                               --classic-json results/iperf3_classic.json
                               --output-dir eval_out/
                               [--l4s-port 5201] [--classic-port 5202]
"""

import argparse
import csv
import json
import os
import sys

try:
    from scapy.all import rdpcap, IP, TCP, Raw
    from scapy.layers.inet import IP, TCP
except ImportError:
    print("[ERROR] scapy not found")
    sys.exit(1)

ECN_LABELS = {
    0b00: "Not-ECT",
    0b01: "ECT1-L4S",
    0b10: "ECT0",
    0b11: "CE",
}


def parse_pcap(pcap_path, l4s_port, classic_port):
    """
    Parse capture.pcap and return a list of per-packet dicts/maps
    Each dict has: {
                    timestamp, src_ip, dst_ip, sport, dport,
                    ecn_bits, ecn_label, traffic_class, pkt_len, is_ce
                    }
    """
    print(f"[parse_pcap] Reading {pcap_path}")
    try:
        pkts = rdpcap(pcap_path)
    except Exception as e:
        print(f"[ERROR] Cannot read pcap: {e}")
        return []

    rows = []
    for pkt in pkts:
        if not pkt.haslayer(IP):
            continue
        ip = pkt[IP]
        ecn_bits  = ip.tos & 0b11
        ecn_label = ECN_LABELS.get(ecn_bits, "unknown")

        sport = dport = 0
        if pkt.haslayer(TCP):
            sport = pkt[TCP].sport
            dport = pkt[TCP].dport

        if dport == l4s_port or sport == l4s_port:
            traffic_class = "L4S"
        elif dport == classic_port or sport == classic_port:
            traffic_class = "Classic"
        else:
            traffic_class = "Unknown"

        rows.append({
            "timestamp":     float(pkt.time),
            "src_ip":        ip.src,
            "dst_ip":        ip.dst,
            "sport":         sport,
            "dport":         dport,
            "ecn_bits":      ecn_bits,
            "ecn_label":     ecn_label,
            "traffic_class": traffic_class,
            "pkt_len":       len(pkt),
            "is_ce":         1 if ecn_bits == 0b11 else 0,
        })

    print(f"[parse_pcap] Parsed {len(rows)} packets "
          f"({sum(1 for r in rows if r['traffic_class']=='L4S')} L4S, "
          f"{sum(1 for r in rows if r['traffic_class']=='Classic')} Classic)")
    return rows


def write_packets_csv(rows, path):
    if not rows:
        print("[WARNING:] No packets to write")
        return
    fieldnames = ["timestamp", "src_ip", "dst_ip", "sport", "dport",
                  "ecn_bits", "ecn_label", "traffic_class", "pkt_len", "is_ce"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"[parse_pcap] Wrote {len(rows)} rows to {path}")


def parse_iperf3_json(json_path, traffic_class):
    """
    Parse iperf3 JSON output and return per-interval throughput rows.
    Each tuple-> timestamp (start of interval), duration_s, bits_per_second, traffic_class
    """
    if not os.path.exists(json_path):
        print(f"[WARNING:] iperf3 JSON not found: {json_path}")
        return []

    with open(json_path) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[WARNING:] Cannot parse iperf3 JSON {json_path}: {e}")
            return []

    rows = []
    intervals = data.get("intervals", [])
    for interval in intervals:
        s = interval.get("sum", {})
        rows.append({
            "start_s":        s.get("start", 0),
            "end_s":          s.get("end",   0),
            "bits_per_second": s.get("bits_per_second", 0),
            "mbps":           s.get("bits_per_second", 0) / 1e6,
            "bytes":          s.get("bytes", 0),
            "traffic_class":  traffic_class,
        })

    print(f"[parse_pcap] {traffic_class}: {len(rows)} iperf3 intervals "
          f"from {json_path}")
    return rows


def write_throughput_csv(l4s_rows, classic_rows, path):
    rows = l4s_rows + classic_rows
    if not rows:
        print("[WARNING:] No throughput data to write")
        return
    fieldnames = ["start_s", "end_s", "bits_per_second",
                  "mbps", "bytes", "traffic_class"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"[parse_pcap] Wrote {len(rows)} throughput rows to {path}")



def compute_marking_rate(rows, window_s=1.0):
    """
    Compute CE marking rate in sliding windows for L4S and Classic separately.
    Returns list of dicts: {window_start, traffic_class, total, ce_count, ce_rate}
    """
    if not rows:
        return []

    t_min = min(r["timestamp"] for r in rows)
    t_max = max(r["timestamp"] for r in rows)
    results = []

    t = t_min
    while t < t_max:
        for cls in ["L4S", "Classic"]:
            window = [r for r in rows
                      if r["traffic_class"] == cls
                      and t <= r["timestamp"] < t + window_s]
            total    = len(window)
            ce_count = sum(r["is_ce"] for r in window)
            ce_rate  = ce_count / total if total > 0 else 0
            results.append({
                "window_start":  round(t - t_min, 3),
                "traffic_class": cls,
                "total_pkts":    total,
                "ce_pkts":       ce_count,
                "ce_rate":       round(ce_rate, 4),
            })
        t += window_s

    return results


def write_marking_rate_csv(results, path):
    if not results:
        return
    fieldnames = ["window_start", "traffic_class",
                  "total_pkts", "ce_pkts", "ce_rate"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)
    print(f"[parse_pcap] Wrote marking rate to {path}")

def main():
    parser = argparse.ArgumentParser(
        description="Parse pcap and iperf3 JSON into analysis CSVs"
    )
    parser.add_argument("--pcap",         required=True,
                        help="Path to capture.pcap from recv.py")
    parser.add_argument("--l4s-json",     default="results/iperf3_l4s.json")
    parser.add_argument("--classic-json", default="results/iperf3_classic.json")
    parser.add_argument("--output-dir",   default="eval_out")
    parser.add_argument("--l4s-port",     type=int, default=5201)
    parser.add_argument("--classic-port", type=int, default=5202)
    parser.add_argument("--window",       type=float, default=1.0,
                        help="Marking rate window size in seconds")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    rows = parse_pcap(args.pcap, args.l4s_port, args.classic_port)
    write_packets_csv(rows,
                      os.path.join(args.output_dir, "packets.csv"))

    l4s_tp     = parse_iperf3_json(args.l4s_json,     "L4S")
    classic_tp = parse_iperf3_json(args.classic_json, "Classic")
    write_throughput_csv(l4s_tp, classic_tp,
                         os.path.join(args.output_dir, "throughput.csv"))

    marking = compute_marking_rate(rows, window_s=args.window)
    write_marking_rate_csv(marking,
                           os.path.join(args.output_dir, "marking_rate.csv"))

    print(f"\n[parse_pcap] Done. Outputs in {args.output_dir}/")
    print("  packets.csv       — per-packet ECN data")
    print("  throughput.csv    — per-interval iperf3 throughput")
    print("  marking_rate.csv  — CE marking rate over time")


if __name__ == "__main__":
    main()