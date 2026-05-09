#!/usr/bin/env python3
"""
stats.py — Compute per-class statistics from the CSV outputs.

Outputs:- 
Generates a table of stats including:
  - ECN marking rate (mean, per class)
  - Throughput (mean Mbps, per class)
  - Jain fairness index between L4S and Classic throughput
  - CE marking rate (mean, p95, p99 per class)
  - Packet counts per ECN codepoint

Usage:
    python3 eval/stats.py --input-dir eval_out/ [--variant <name>]
"""

import argparse
import csv
import json
import os
import sys

try:
    import numpy as np
except ImportError:
    print("[ERROR] numpy not found. Install with: pip install numpy")
    sys.exit(1)

def read_csv(path):
    if not os.path.exists(path):
        print(f"[WARNING:] File not found: {path}")
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))
    
def print_section(title):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")

def ecn_distribution(rows):
    """Count packets per ECN label per class."""
    dist = {}
    for r in rows:
        cls   = r["traffic_class"]
        label = r["ecn_label"]
        dist.setdefault(cls, {})
        dist[cls][label] = dist[cls].get(label, 0) + 1
    return dist


def marking_stats(marking_rows):
    stats = {}
    for cls in ["L4S", "Classic"]:
        rates = [float(r["ce_rate"])
                 for r in marking_rows
                 if r["traffic_class"] == cls]
        if not rates:
            continue
        a = np.array(rates)
        stats[cls] = {
            "mean":   float(np.mean(a)),
            "median": float(np.median(a)),
            "p95":    float(np.percentile(a, 95)),
            "p99":    float(np.percentile(a, 99)),
            "max":    float(np.max(a)),
        }
    return stats


def throughput_stats(tp_rows):
    stats = {}
    for cls in ["L4S", "Classic"]:
        mbps = [float(r["mbps"])
                for r in tp_rows
                if r["traffic_class"] == cls]
        if not mbps:
            continue
        a = np.array(mbps)
        stats[cls] = {
            "mean":   float(np.mean(a)),
            "median": float(np.median(a)),
            "p5":     float(np.percentile(a, 5)),  
            "p95":    float(np.percentile(a, 95)),
            "total_mb": float(np.sum(a)),
        }
    return stats


def jain_fairness(tp_stats):
    """
    Jain's fairness index between L4S and Classic mean throughput.
    J = (sum xi's)^2 / (n * sum xi's^2)
    1.0 = perfectly fair, 0.5 = one class gets everything.
    """
    values = [tp_stats[cls]["mean"]
              for cls in ["L4S", "Classic"]
              if cls in tp_stats]
    if len(values) < 2:
        return None
    x = np.array(values)
    return float((np.sum(x) ** 2) / (len(x) * np.sum(x ** 2)))


def ce_marking_count(pkt_rows):
    """Count CE-marked packets per class."""
    result = {}
    for cls in ["L4S", "Classic"]:
        total = sum(1 for r in pkt_rows if r["traffic_class"] == cls)
        ce    = sum(1 for r in pkt_rows
                    if r["traffic_class"] == cls and r["is_ce"] == "1")
        result[cls] = {
            "total":    total,
            "ce":       ce,
            "ce_rate":  ce / total if total > 0 else 0,
        }
    return result


def print_stats(variant, pkt_rows, tp_rows, marking_rows):
    print(f"\nVariant: {variant}")

    # ECN distribution
    print_section("ECN Codepoint Distribution")
    dist = ecn_distribution(pkt_rows)
    for cls, counts in dist.items():
        total = sum(counts.values())
        print(f"  {cls}:")
        for label, count in sorted(counts.items()):
            print(f"    {label:12s}: {count:6d}  ({100*count/total:.1f}%)")

    # CE marking
    print_section("CE Marking Rate (per class)")
    ce = ce_marking_count(pkt_rows)
    for cls, s in ce.items():
        print(f"  {cls}: {s['ce']:5d} / {s['total']:5d} marked CE  "
              f"({100*s['ce_rate']:.1f}%)")

    # Marking rate over time
    print_section("CE Marking Rate — Time Series Stats")
    ms = marking_stats(marking_rows)
    for cls, s in ms.items():
        print(f"  {cls}:")
        print(f"    mean={s['mean']:.3f}  median={s['median']:.3f}  "
              f"p95={s['p95']:.3f}  p99={s['p99']:.3f}  max={s['max']:.3f}")

    # Throughput
    print_section("Throughput (Mbps)")
    ts = throughput_stats(tp_rows)
    for cls, s in ts.items():
        print(f"  {cls}:")
        print(f"    mean={s['mean']:.2f}  median={s['median']:.2f}  "
              f"p5={s['p5']:.2f}  p95={s['p95']:.2f}")

    # Fairness
    jf = jain_fairness(ts)
    if jf is not None:
        print(f"\n  Jain Fairness Index (L4S vs Classic): {jf:.4f}")
        if jf >= 0.9:
            print("    → Good fairness")
        elif jf >= 0.7:
            print("    → Moderate fairness")
        else:
            print("    → Poor fairness — Classic may be starved")


def save_summary_json(variant, pkt_rows, tp_rows, marking_rows, output_dir):
    ce      = ce_marking_count(pkt_rows)
    ms      = marking_stats(marking_rows)
    ts      = throughput_stats(tp_rows)
    jf      = jain_fairness(ts)
    summary = {
        "variant":        variant,
        "ce_marking":     ce,
        "marking_stats":  ms,
        "throughput":     ts,
        "jain_fairness":  jf,
    }
    path = os.path.join(output_dir, f"summary_{variant}.json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[stats] Summary saved to {path}")


def main():
    parser = argparse.ArgumentParser(
        description="Compute L4S experiment statistics"
    )
    parser.add_argument("--input-dir",  default="eval_out",
                        help="Directory with packets.csv, throughput.csv, "
                             "marking_rate.csv from parse_pcap.py")
    parser.add_argument("--variant",    default="experiment",
                        help="Variant name for summary JSON "
                             "(e.g. baseline, fixed, dynamic)")
    args = parser.parse_args()

    pkt_rows     = read_csv(os.path.join(args.input_dir, "packets.csv"))
    tp_rows      = read_csv(os.path.join(args.input_dir, "throughput.csv"))
    marking_rows = read_csv(os.path.join(args.input_dir, "marking_rate.csv"))

    if not pkt_rows:
        print("[ERROR] packets.csv is empty or missing. "
              "Run parse_pcap.py first.")
        sys.exit(1)

    print_stats(args.variant, pkt_rows, tp_rows, marking_rows)
    save_summary_json(args.variant, pkt_rows, tp_rows, marking_rows,
                      args.input_dir)


if __name__ == "__main__":
    main()