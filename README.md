# L4S-Aware Queueing Prototype in BMv2

A P4-based prototype implementing Low-Latency, Low-Loss, and Scalable Throughput ([L4S](https://www.rfc-editor.org/rfc/rfc9330)) aware dual-queue management on BMv2, with static and dynamic ECN-marking thresholds.

**Team Members**<br>
- **CS25S031 Sooraj Subramanian M. S.**<br>
- **CS25S020 Kunal Umaji**<br>
- **CS25S010 Sk Fardeen Hossain**<br>

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Components](#components)
  - [1. P4 Data Plane (`p4src/`)](#1-p4-data-plane-p4src)
  - [2. Control Plane Controller (`controller/`)](#2-control-plane-controller-controller)
  - [3. Mininet Topology (`topo/`)](#3-mininet-topology-topo)
  - [4. Traffic Generation (`traffic/`)](#4-traffic-generation-traffic)
  - [5. Evaluation & Metrics (`eval/`)](#5-evaluation--metrics-eval)
- [Design Variants](#design-variants)
- [Dynamic Thresholding](#dynamic-thresholding)
- [Queue Telemetry Signals](#queue-telemetry-signals)
- [Evaluation Plan](#evaluation-plan)
- [Known Limitations & Risks](#known-limitations--risks)
- [References](#references)

---

## Overview

This project implements an **L4S-aware queueing prototype** running on [BMv2](https://github.com/p4lang/behavioral-model) (the P4 software switch), exercised inside a Mininet environment. The goal is to:

- Classify packets by their **ECN codepoint** as defined in RFC 9331 and RFC 9332.
- Separate traffic into an **L4S queue** (ECT(1) and CE) and a **Classic queue** (Not-ECT and ECT(0)).
- Exploit BMv2's **multi-priority queue support** to approximate the DualQ Coupled AQM scheduler.
- Apply **queue-aware ECN marking** in egress, driven by configurable thresholds.
- Compare a **fixed-threshold** design against a **lightweight dynamic-threshold** design.

The prototype is *not* a standards-faithful DualQ implementation; it is a reproducible, measurable approximation that can be used to study relative latency and fairness behavior under controlled congestion.

---

## Architecture

```
Senders
   |
   ▼
Mininet bottleneck link
   │
   ▼
BMv2 Ingress
  ├─ ECN field parsing
  └─ L4S / Classic classification
       │
       ├──► Priority Queue 1  (L4S  — higher priority)
       └──► Priority Queue 0  (Classic — lower priority)
                  │
                  ▼
         BMv2 Egress
           ├─ Queue telemetry read  (deq_timedelta, deq_qdepth, enq_qdepth)
           ├─ ECN marking / demotion (threshold check)
           └─ Forward to receivers
                  ▲
                  │  threshold updates (register writes)
         Control Plane Controller
           ├─ Reads exported queue signals
           └─ Computes and installs new threshold values
```

---

## Components

### 1. P4 Data Plane (`p4src/`)

All P4 code targets **P4_16** with the **v1model architecture**.

#### `p4src/l4s.p4` — Main Switch Program

| Block | Responsibility |
|---|---|
| **Parser** | Parse Ethernet → IPv4 → extract the ECN field (bits 0–1 of the DSCP/ECN byte in the IP header). |
| **Ingress — ECN Classification** | Read `hdr.ipv4.ecn`. Set a local metadata field `meta.is_l4s = 1` if ECN belongs to {ECT(1)=`0b01`, CE=`0b11`}; otherwise `meta.is_l4s = 0` (Classic). |
| **Ingress — Queue Selection** | Write `standard_metadata.priority` based on `meta.is_l4s`. L4S packets receive the higher-priority queue index; Classic packets receive the lower-priority queue index. BMv2 must be launched with `--priority-queues 2`. |
| **Egress — Threshold Read** | Read the current ECN-marking threshold from a **register** (`reg_l4s_threshold` or `reg_classic_threshold`). |
| **Egress — ECN Marking** | Compare `standard_metadata.deq_qdepth` (or `deq_timedelta`) against the threshold. If exceeded, mark the packet CE (`hdr.ipv4.ecn = 0b11`) for L4S packets; optionally drop or mark for Classic packets. |
| **Egress — Telemetry Export** | Write queue state (`deq_qdepth`, `enq_qdepth`, `deq_timedelta`) into registers so the controller can read them. |
| **Deparser** | Reconstruct the packet with a (possibly modified) ECN field. |

#### `p4src/headers.p4`

Defines all header types (`ethernet_t`, `ipv4_t`) and metadata structs (`l4s_meta_t`) including:
- `is_l4s` — classification bit
- `queue_id` — resolved queue index
- Mirrored telemetry fields for control plane export

#### `p4src/registers.p4`

Declares all P4 registers shared between the data plane and the control plane:

| Register | Width | Description |
|---|---|---|
| `reg_l4s_threshold` | 32-bit | Current ECN marking threshold for the L4S queue (depth or delay units). |
| `reg_classic_threshold` | 32-bit | Current ECN marking threshold for the Classic queue. |
| `reg_classic_protection_threshold` | 32-bit | Maximum ingress Classic protection budget; `0` disables L4S demotion for Classic protection. |
| `reg_classic_protection_budget` | 32-bit | Current ingress-observed Classic protection credits consumed by later L4S demotions. |
| `reg_l4s_qdepth` | 32-bit | Latest sampled L4S queue depth (written each packet, read by controller). |
| `reg_classic_qdepth` | 32-bit | Latest sampled Classic queue depth. |
| `reg_l4s_delay` | 32-bit | Latest `deq_timedelta` for the L4S queue. |
| `reg_l4s_growth` | 32-bit | Delta of L4S queue depth between two consecutive controller polling intervals. |

---

### 2. Control Plane Controller (`controller/`)

Written in **Python 3** using the BMv2 thrift runtime API .

#### `controller/controller.py` — Main Controller Loop

```
while True:
    1. Poll registers: read reg_l4s_qdepth, reg_classic_qdepth, reg_l4s_delay, reg_l4s_growth
    2. Compute new threshold (based on Dynamic Thresholding logic)
    3. Write updated threshold to reg_l4s_threshold via runtime API
    4. Sleep for some seconds
```

The controller is only active in the **dynamic-threshold variant**. In the static variant, thresholds are written once at startup and the controller loop is not run.

#### `controller/threshold_policy.py` — Threshold Update Logic

Implements the threshold computation function

Configurable knobs (set via some `config.yaml`):

| Parameter | Description |
|---|---|
| `POLL_INTERVAL` | Controller polling period (seconds). |
| `GROWTH_HIGH` | L4S queue growth rate above which threshold tightens. |
| `CLASSIC_BACKLOG_THRESH` | Classic queue depth that signals persistent backlog. |
| `TIGHTEN_STEP` | Amount to decrease threshold per tightening event. |
| `RELAX_STEP` | Amount to increase threshold per relaxation event. |
| `MIN_THRESH` | Hard lower bound on threshold. |
| `MAX_THRESH` | Hard upper bound on threshold. |

#### `controller/runtime_api.py`

Thin wrapper around BMv2's thrift runtime for register read/write operations.

---

### 3. Mininet Topology (`topo/`)

#### `topo/topology.py` — Single Bottleneck Topology

```
h1 (L4S sender) ──────┐
h2 (L4S sender) ──────┤
h3 (Classic sender) ──┤──► s1 (BMv2) ──► h5 (receiver)
h4 (Classic sender) ──┘
```

- All sender–switch links: configurable bandwidth and delay.
- Switch–receiver link: the **bottleneck link** with a reduced bandwidth cap to induce some level of congestion.
- BMv2 is launched with `--priority-queues 2` to enable multi-queue mode.
- The topology configures host routes, static gateway ARP entries, P4 forwarding entries, and threshold registers.
- The topology disables checksum/segmentation offloads on Mininet interfaces so BMv2 sees complete TCP checksums.
- The dynamic controller is still a separate pending component; once implemented, it should be started after the topology and BMv2 runtime state are ready.

Preview generated BMv2 runtime commands:

```bash
python3 topo/topology.py --dry-run
```

Start the interactive topology:

```bash
sudo python3 topo/topology.py
```

Run a non-interactive connectivity check:

```bash
sudo python3 topo/topology.py --smoke-test
```

Run one non-interactive fixed-threshold traffic experiment:

```bash
sudo python3 topo/topology.py --run-fixed --experiment-duration 30 --output-dir results/fixed
```

Inside the interactive Mininet CLI, run traffic with the receiver in the
background before starting clients:

```bash
mininet> h5 sudo python3 traffic/recv.py --iface h5-eth0 --duration 45 --output-dir results/fixed &
mininet> h1 sudo python3 traffic/send_l4s.py --dst 10.0.5.5 --port 5201 --bandwidth 4 --duration 30 --output results/fixed/l4s_client.json &
mininet> h3 sudo python3 traffic/send_classic.py --dst 10.0.5.5 --port 5202 --bandwidth 4 --duration 30 --ecn --output results/fixed/classic_client.json &
```

#### `topo/config.yaml` — Topology and Experiment Parameters

```yaml
bottleneck_bw_mbps: 10
sender_bw_mbps: 100
link_delay_ms: 5
num_l4s_senders: 2
num_classic_senders: 2
queue_size_pkts: 100
```

---

### 4. Traffic Generation (`traffic/`)

#### `traffic/send_l4s.py`

Runs `iperf3` client with DCTCP (`sysctl net.ipv4.tcp_congestion_control=dctcp`). Applies an `iptables` mangle rule (`--set-tos 0x01/0x03`) on startup to rewrite ECT(0) → ECT(1) on all outgoing TCP packets so BMv2 classifies them into the L4S queue. Restores sysctl and removes the rule on exit.

#### `traffic/send_classic.py`

Runs `iperf3` client with TCP Cubic. The `--ecn` flag optionally enables ECN negotiation so the Classic sender receives CE marks and responds with TCP's standard 50% window halve.

#### `traffic/recv.py`

Runs `iperf3` servers on the L4S and Classic ports for throughput measurement, alongside a parallel `tcpdump` capture to `capture.pcap` for per-packet ECN bit extraction. `eval/parse_pcap.py` reads the pcap for ECN and latency analysis.

#### `traffic/load_profile.py`

Orchestrates time-varying load experiments (steady, ramp, step, burst, mixed) by spawning `send_l4s.py` and `send_classic.py` as subprocesses with stage-specific bandwidth targets.

---

### 5. Evaluation & Metrics (`eval/`)

#### `eval/parse_pcap.py`

Parses `.pcap` captures taken at sender and receiver to compute:
- **ECN marking rate** — fraction of forward-direction packets received with CE mark.
- **ECN codepoint counts** — Not-ECT, ECT(0), ECT(1), and CE per traffic class.
- **Payload packet and byte counts** per class.

Current parser scope is intentionally narrow: it summarizes receiver-side pcaps
from this topology using `tcpdump` output. Latency and drop inference can be
added after sender-side captures exist.

Run the fixed experiment summarizer:

```bash
python3 -m eval.summarize_results results/fixed
```

This writes:

```text
results/fixed/summary.json
results/fixed/summary.csv
```

If `results/fixed` was created before the topology returned file ownership to
the invoking user, either rerun `--run-fixed` or preview without writing:

```bash
python3 -m eval.summarize_results results/fixed --no-write
```

#### `eval/plot_results.py`

Generates plots comparing the three design variants:

| Plot | X-axis | Y-axis |
|---|---|---|
| Latency CDF | Queueing delay (ms) | CDF (per class) |
| Throughput timeline | Time (s) | Throughput (Mbps), L4S vs Classic |
| ECN marking rate | Offered load (Mbps) | Fraction marked CE |
| Threshold trace | Time (s) | Dynamic threshold value |
| Fairness | L4S fraction of offered load (%) | Throughput share ratio |

#### `eval/stats.py`

Computes median, p95, and p99 latency per class, and the Jain fairness index for each experiment run.

---

## Design Variants

Three configurations are implemented and compared:

| Variant | Queue mode | Threshold | Controller |
|---|---|---|---|
| **Baseline** | Single queue, no L4S classification | N/A | None |
| **Fixed-threshold** | Two priority queues, ECN classification | Static value set at startup | None |
| **Dynamic-threshold** | Two priority queues, ECN classification | Adjusted at runtime by controller | Active polling loop |

Each variant is launched via a dedicated run script:

```bash
# Baseline
sudo python3 run_experiment.py --variant baseline

# Fixed threshold
sudo python3 run_experiment.py --variant fixed --l4s-thresh 30 --classic-thresh 80

# Dynamic threshold
sudo python3 run_experiment.py --variant dynamic --config topo/config.yaml
```

---

## Dynamic Thresholding

The dynamic threshold operates as a simple feedback loop entirely based on signals already available from BMv2 queue telemetry.

**Tighten threshold when:**
- L4S queue depth is growing rapidly (i.e., `l4s_growth > GROWTH_HIGH`), indicating that L4S traffic is accumulating faster than it is being drained.
- Classic queue depth remains persistently high (i.e., `classic_depth > CLASSIC_BACKLOG_THRESH`), indicating that Classic traffic is near starvation due to strict-priority preemption.

**Relax threshold when:**
- Both L4S queue depth and Classic queue depth fall below their respective healthy operating points.

The threshold is clamped to `[MIN_THRESH, MAX_THRESH]` to prevent runaway tightening or relaxation. The fallback, if the controller loop proves unnecessary, is a purely in-switch register-based rule using the same signals read directly in the egress pipeline.

---

## Queue Telemetry Signals

The following BMv2 `standard_metadata` fields are used. All are available in egress in the v1model architecture.

| Field | Description | Used for |
|---|---|---|
| `deq_timedelta` | Time the packet spent in the queue (microseconds) | Latency-based ECN marking; exported to controller |
| `deq_qdepth` | Queue depth at dequeue time (packets) | Depth-based ECN marking |
| `enq_qdepth` | Queue depth at enqueue time (packets) | Queue growth estimation |
| `priority` | Queue index the packet was placed into | Verify correct queue assignment in egress |

---

## Evaluation Plan

Experiments vary:
- **Total offered load**: from 50% to 150% of bottleneck capacity.
- **L4S traffic fraction**: 25%, 50%, 75%.

For each combination, all three variants are run and the following metrics are collected:

1. **Queueing delay** — median, p95, p99, reported per class (L4S and Classic separately).
2. **Throughput** — measured in 100 ms windows, per class.
3. **ECN marking rate** — fraction of L4S and Classic packets marked CE.
4. **Drop rate** — to distinguish delay reduction via early marking from reduction via loss.
5. **Fairness** — relative throughput share in overload; Classic starvation is the primary concern.

The central hypothesis to be validated:<br>
The dynamic-threshold design preserves most of the L4S latency benefit while reducing Classic starvation compared to the fixed-threshold design.

---

## Known Limitations & Risks

**TBD**

---

## References

1. nsg-ethz/p4-learning Wiki. *BMv2 Simple Switch*. GitHub wiki, accessed March 27, 2026.
2. K. D. Schepper, B. Briscoe, G. White. *Dual-Queue Coupled AQM for L4S*. RFC 9332, Jan. 2023.
3. K. D. Schepper, B. Briscoe. *ECN Protocol for L4S*. RFC 9331, Jan. 2023.
4. C. Papagianni, K. D. Schepper. *PI2 for P4*. CoNEXT 2019.
5. H. Harkous et al. *Virtual Queues for P4: A Poor Man's Programmable Traffic Manager*. IEEE TNSM, 2021.
6. S. Nádas et al. *A Congestion Control Independent L4S Scheduler*. ANRW 2020.
