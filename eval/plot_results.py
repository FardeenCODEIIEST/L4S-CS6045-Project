#!/usr/bin/env python3
"""
plot_results.py — Generate evaluation plots from parsed CSVs.

Produces:
  1. ecn_marking_rate.pdf  — CE marking rate over time (L4S vs Classic)
  2. throughput.pdf        — Throughput timeline (L4S vs Classic)
  3. ecn_distribution.pdf  — ECN codepoint distribution bar chart
  4. fairness.pdf          — Jain fairness index across variants (if multiple)
  5. cross_variant.pdf     — Side-by-side CE rate comparison across variants

Usage:
    # Single variant
    python3 eval/plot_results.py --input-dir eval_out/ --variant fixed

    # Compare multiple variants
    python3 eval/plot_results.py --compare \
        eval_out/baseline:Baseline \
        eval_out/fixed:Fixed \
        eval_out/dynamic:Dynamic
"""

import argparse
import csv
import json


import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


L4S_COLOR     = '#2196F3'   # blue
CLASSIC_COLOR = '#F44336'   # red
DYNAMIC_COLOR  = '#4CAF50'   # green

plt.rcParams.update({
    'font.family':     'monospace',
    'font.size':       7,
    'axes.spines.top':    False,
    'axes.spines.right':  False,
    'axes.grid':          True,
    'grid.alpha':         0.3,
    'figure.dpi':         300,
})


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def read_json(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)

def plot_marking_rate(marking_rows, output_path, variant=""):
    fig, ax = plt.subplots(figsize=(3.5, 2.5))

    for cls, color in [("L4S", L4S_COLOR), ("Classic", CLASSIC_COLOR)]:
        rows = [r for r in marking_rows if r["traffic_class"] == cls]
        if not rows:
            continue
        t    = [float(r["window_start"]) for r in rows]
        rate = [float(r["ce_rate"]) * 100 for r in rows]
        ax.plot(t, rate, color=color, linewidth=1.2, label=cls)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("CE Marking Rate (%)")
    title = "CE Marking Rate over Time"
    if variant:
        title += f"  [{variant}]"
    ax.set_title(title)
    ax.legend()
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f%%'))
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    print(f"[plot] Saved {output_path}")


def plot_throughput(tp_rows, output_path, variant=""):
    fig, ax = plt.subplots(figsize=(3.5, 2.5))

    for cls, color in [("L4S", L4S_COLOR), ("Classic", CLASSIC_COLOR)]:
        rows = [r for r in tp_rows if r["traffic_class"] == cls]
        if not rows:
            continue
        t    = [float(r["start_s"]) for r in rows]
        mbps = [float(r["mbps"])    for r in rows]
        ax.plot(t, mbps, color=color, linewidth=1.2, label=cls)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Throughput (Mbps)")
    title = "Throughput Timeline"
    if variant:
        title += f"  [{variant}]"
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    print(f"[plot] Saved {output_path}")


def plot_ecn_distribution(pkt_rows, output_path, variant=""):
    labels  = ["Not-ECT", "ECT1-L4S", "ECT0", "CE"]
    classes = ["L4S", "Classic"]
    colors  = [L4S_COLOR, CLASSIC_COLOR]

    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    x     = np.arange(len(labels))
    width = 0.35

    for i, (cls, color) in enumerate(zip(classes, colors)):
        rows  = [r for r in pkt_rows if r["traffic_class"] == cls]
        total = len(rows) if rows else 1
        counts = []
        for lbl in labels:
            c = sum(1 for r in rows if r["ecn_label"] == lbl)
            counts.append(100 * c / total)
        offset = (i - 0.5) * width
        ax.bar(x + offset, counts, width, label=cls, color=color, alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Fraction of packets (%)")
    title = "ECN Codepoint Distribution"
    if variant:
        title += f"  [{variant}]"
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    print(f"[plot] Saved {output_path}")


def plot_cross_variant(variant_data, output_path):
    """
    variant_data: list of (label, marking_rows) tuples
    """
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    colors  = [L4S_COLOR, CLASSIC_COLOR, DYNAMIC_COLOR,
               '#FF9800', '#9C27B0', '#00BCD4']

    for i, (label, marking_rows) in enumerate(variant_data):
        for cls, ls in [("L4S", "-"), ("Classic", "--")]:
            rows = [r for r in marking_rows if r["traffic_class"] == cls]
            if not rows:
                continue
            t    = [float(r["window_start"]) for r in rows]
            rate = [float(r["ce_rate"]) * 100 for r in rows]
            ax.plot(t, rate,
                    color=colors[i % len(colors)],
                    linestyle=ls,
                    linewidth=1.0,
                    label=f"{label} / {cls}")

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("CE Marking Rate (%)")
    ax.set_title("CE Marking Rate — Cross-Variant Comparison")
    ax.legend(fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.0f%%'))
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    print(f"[plot] Saved {output_path}")


def plot_fairness(summaries, output_path):
    """
    summaries: list of (label, summary_maps) tuples
    """
    labels    = [s[0] for s in summaries]
    jf_values = [s[1].get("jain_fairness") or 0 for s in summaries]

    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    bars = ax.bar(labels, jf_values, color=DYNAMIC_COLOR, alpha=0.85, width=0.5)

    for bar, val in zip(bars, jf_values):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.01,
                f"{val:.3f}",
                ha='center', va='bottom', fontsize=10)

    ax.axhline(1.0, color='gray', linestyle='--', linewidth=1, alpha=0.5,
               label='Perfect fairness')
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Jain Fairness Index")
    ax.set_title("Fairness across Variants")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    print(f"[plot] Saved {output_path}")


def plot_throughput_comparison(summaries, output_path):
    labels    = [s[0] for s in summaries]
    l4s_tp    = [s[1].get("throughput", {}).get("L4S", {}).get("mean", 0)
                 for s in summaries]
    classic_tp = [s[1].get("throughput", {}).get("Classic", {}).get("mean", 0)
                  for s in summaries]

    x     = np.arange(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    ax.bar(x - width/2, l4s_tp,    width, label='L4S',    color=L4S_COLOR,     alpha=0.85)
    ax.bar(x + width/2, classic_tp, width, label='Classic', color=CLASSIC_COLOR, alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Mean Throughput (Mbps)")
    ax.set_title("Mean Throughput per Class — Cross-Variant")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    print(f"[plot] Saved {output_path}")

def main():
    parser = argparse.ArgumentParser(
        description="Generate L4S evaluation plots"
    )
    parser.add_argument("--input-dir", default="eval_out",
                        help="Directory with CSVs from parse_pcap.py "
                             "(single variant mode)")
    parser.add_argument("--variant",   default="experiment",
                        help="Variant label for plot titles")
    parser.add_argument("--output-dir", default=None,
                        help="Where to write plots (default: same as input-dir)")
    parser.add_argument("--compare",   nargs="+", default=None,
                        metavar="DIR:LABEL",
                        help="Compare multiple variants: "
                             "eval_out/fixed:Fixed eval_out/dynamic:Dynamic")
    args = parser.parse_args()

    out_dir = args.output_dir or args.input_dir
    os.makedirs(out_dir, exist_ok=True)

    if args.compare:
        # Multi-variant mode
        variant_data   = []
        summary_data   = []
        for spec in args.compare:
            parts = spec.split(":", 1)
            d     = parts[0]
            label = parts[1] if len(parts) > 1 else os.path.basename(d)
            marking_rows = read_csv(os.path.join(d, "marking_rate.csv"))
            tp_rows      = read_csv(os.path.join(d, "throughput.csv"))
            summary      = read_json(os.path.join(d, f"summary_{label}.json"))
            variant_data.append((label, marking_rows))
            summary_data.append((label, summary))

        plot_cross_variant(variant_data,
                           os.path.join(out_dir, "cross_variant_marking.png"))
        plot_fairness(summary_data,
                      os.path.join(out_dir, "fairness_comparison.png"))
        plot_throughput_comparison(summary_data,
                                   os.path.join(out_dir, "throughput_comparison.png"))

    else:
        # Single variant mode
        pkt_rows     = read_csv(os.path.join(args.input_dir, "packets.csv"))
        tp_rows      = read_csv(os.path.join(args.input_dir, "throughput.csv"))
        marking_rows = read_csv(os.path.join(args.input_dir, "marking_rate.csv"))

        plot_marking_rate(marking_rows,
                          os.path.join(out_dir, "ecn_marking_rate.png"),
                          variant=args.variant)
        plot_throughput(tp_rows,
                        os.path.join(out_dir, "throughput.png"),
                        variant=args.variant)
        plot_ecn_distribution(pkt_rows,
                              os.path.join(out_dir, "ecn_distribution.png"),
                              variant=args.variant)

    print(f"\n[plot] All plots written to {out_dir}/")


if __name__ == "__main__":
    main()