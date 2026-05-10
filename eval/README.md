# `eval/` — Evaluation & Metrics

Post-processing pipeline for L4S experiment results.

---

## Files

| File | Input | Output |
|---|---|---|
| `parse_ecn.py` | `capture.pcap` | Console JSON summary of per-class ECN codepoint counts and CE rate |
| `parse_pcap.py` | `capture.pcap`, `iperf3_*.json` | `packets.csv`, `throughput.csv`, `marking_rate.csv` |
| `stats.py` | CSVs from parse_pcap | Console summary + `summary_<variant>.json` |
| `plot_results.py` | CSVs or summary JSONs | PNG plots |

---

## Dependencies

```bash
pip install scapy matplotlib numpy
```

`parse_ecn.py` requires `tcpdump` to be installed and available in PATH.

---

## Workflow

### Step 0 — Quick ECN sanity check (optional but recommended)

Before full parsing, verify CE marking happened at all:

```bash
python3 eval/parse_ecn.py results/capture.pcap \
    --receiver-ip 10.0.5.5 \
    --l4s-port 5201 \
    --classic-port 5202
```

Prints a JSON summary to stdout:

```json
{
  "classes": {
    "l4s":     { "packets": 12000, "ce_packets": 340, "ce_rate": 0.028 },
    "classic": { "packets": 11800, "ce_packets":  92, "ce_rate": 0.007 }
  }
}
```

If `ce_rate` is 0 for both classes, the thresholds are too high or traffic
never congested the queue — check register values before proceeding.

### Step 1 — Parse raw results

```bash
python3 eval/parse_pcap.py \
    --pcap results/capture.pcap \
    --l4s-json results/iperf3_l4s.json \
    --classic-json results/iperf3_classic.json \
    --output-dir eval_out/fixed/
```

Produces three CSVs in `eval_out/fixed/`:
- `packets.csv` — per-packet ECN bits, timestamp, class, port
- `throughput.csv` — per-interval Mbps from iperf3, L4S and Classic
- `marking_rate.csv` — CE marking rate in 1-second windows per class

### Step 2 — Compute statistics

```bash
python3 eval/stats.py --input-dir eval_out/fixed/ --variant fixed
```

Prints to console:
- ECN codepoint distribution per class
- CE marking rate (mean, median, p95, p99)
- Throughput (mean, p5, p95)
- Jain fairness index

Saves `eval_out/fixed/summary_fixed.json` for cross-variant comparison.

### Step 3 — Generate plots (single variant)

```bash
python3 eval/plot_results.py --input-dir eval_out/fixed/ --variant fixed
```

Produces in `eval_out/fixed/`:
- `ecn_marking_rate.png` — CE rate over time, L4S vs Classic
- `throughput.png` — throughput timeline
- `ecn_distribution.png` — ECN codepoint bar chart


### Step 4 — Cross-variant comparison

After running Steps 1-3 for baseline, fixed, and dynamic variants:

```bash
python3 eval/plot_results.py --compare \
    eval_out/baseline:Baseline \
    eval_out/fixed:Fixed \
    eval_out/dynamic:Dynamic \
    --output-dir eval_out/comparison/
```

Produces in `eval_out/comparison/`:
- `cross_variant_marking.png` — CE rate across all variants
- `fairness_comparison.png` — Jain fairness index bar chart
- `throughput_comparison.png` — mean throughput per class per variant

---

## Metrics Explained

| Metric | Description | Why it matters |
|---|---|---|
| CE marking rate | Fraction of packets marked CE per class | Shows how aggressively AQM responds |
| Throughput (mean, p5, p95) | Mbps per class per interval | Checks Classic isn't starved |
| Jain fairness index | 1.0 = perfect, 0.5 = one class monopolizes | Summary fairness signal |
| ECN distribution | Fraction of Not-ECT/ECT(0)/ECT(1)/CE per class | Sanity check on classification |

---

## Key Result to Show

The central claim of the paper: **the dynamic-threshold design preserves most of the L4S latency benefit while reducing Classic starvation compared to the fixed-threshold design.**

Evidence comes from:
1. CE marking rate for L4S is lower in dynamic vs fixed (threshold adapted when Classic was starved)
2. Classic throughput share is higher in dynamic vs fixed
3. Jain fairness index is higher in dynamic vs fixed