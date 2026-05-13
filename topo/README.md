# `topo/` — Mininet/BMv2 Topologies

This directory contains the runnable Mininet/BMv2 topology scaffold for the L4S prototype.

## Files

| File | Description |
|---|---|
| `topology.py` | Single bottleneck — 4 senders, 1 receiver. Baseline. |
| `dumbbell_topology.py` | Dumbbell — 4 senders on s1, 4 dedicated receivers on s2. |
| `parking_lot_topology.py` | Parking lot — 3 switches in a linear chain; flows enter at 1, 2, or 3 hops from the receiver. |
| `config.yaml` | Parameters for `topology.py` and `dumbbell_topology.py`. |
| `config_parking_lot.yaml` | Parameters for `parking_lot_topology.py` (symmetric, bn1=bn2=10 Mbps). |
| `config_parking_lot_asymmetric.yaml` | Parking lot with bn1=15, bn2=10 Mbps — tighter final hop. Used automatically by `run_project_suite.py`. |
| `__init__.py` | Package init. |

## Topologies

### Single Bottleneck (`topology.py`)

```text
h1 L4S sender      \
h2 L4S sender       \
h3 Classic sender    s1 BMv2 --[10 Mbps]--> h5 receiver
h4 Classic sender   /
```

All four senders compete at one bottleneck link. Baseline topology for
validating L4S/Classic queue separation, CE marking, and anti-starvation.

### Dumbbell (`dumbbell_topology.py`)

```text
h1 (L4S)    ──┐                        ┌── h5 (recv for h1)
h2 (L4S)    ──┤                        ├── h6 (recv for h2)
               s1 ──[bottleneck]── s2
h3 (Classic)──┤                        ├── h7 (recv for h3)
h4 (Classic)──┘                        └── h8 (recv for h4)
```

Each sender has a dedicated receiver. Four concurrent flows compete at the
inter-switch bottleneck. Tests per-flow fairness between L4S and Classic.

### Parking Lot (`parking_lot_topology.py`)

```text
h1 (L4S, 3-hop)   ──┐
                     s1 ──[bn1]── s2 ──[bn2]── s3 ──── h5 (receiver)
h2 (Classic, 3-hop)──┘    ↑               ↑
                      h3 (L4S,       h4 (Classic,
                        2-hop)          1-hop)
```

## Runtime Model

BMv2 acts as a small IPv4 router. Each host is on a separate `/24` link with a
static ARP entry for its gateway IP. The topology script installs forwarding
rules, queue rate/depth caps, and threshold register values via
`simple_switch_CLI` at startup. Checksum offloads are disabled on all
interfaces.

## Configuration

All runtime parameters come from the config yaml — no recompilation needed.
Edit the relevant file and re-run.

```yaml
# config.yaml (single bottleneck / dumbbell)
bottleneck_bw_mbps: 10
sender_bw_mbps: 100
link_delay_ms: 5
queue_size_pkts: 100
priority_queues: 2
thrift_port: 9090
l4s_threshold: 30
classic_threshold: 80
classic_protection_threshold: 16
```

```yaml
# config_parking_lot.yaml
bn1_bw_mbps: 10   # s1 -> s2
bn2_bw_mbps: 10   # s2 -> s3
# ... same other fields
```

## Manual Usage

For running full experiment suites, see `scripts/README.md`. For quick manual
runs and debugging:

```bash
export RUN="sudo env PATH=$PATH PYTHONPATH=."

# Drop into Mininet CLI
$RUN python3 topo/topology.py

# Smoke test
$RUN python3 topo/topology.py --smoke-test

# Non-interactive fixed-threshold experiment
$RUN python3 topo/topology.py \
    --run-fixed --experiment-duration 30 --output-dir results/fixed

# Same for dumbbell and parking lot
$RUN python3 topo/dumbbell_topology.py --run-fixed ...
$RUN python3 topo/parking_lot_topology.py --run-fixed ...

# Parking lot asymmetric
$RUN python3 topo/parking_lot_topology.py \
    --config topo/config_parking_lot_asymmetric.yaml --run-fixed ...
```

## Connectivity Checks

```bash
mininet> h1 ping -c 3 h5
mininet> h3 ping -c 3 h5
```

---

## Dynamic Threshold Experiment

`--run-dynamic` starts `controller/controller.py` alongside traffic and writes
a JSON-lines threshold trace to:

```text
<output-dir>/controller_trace.jsonl
```

The controller uses `simple_switch_CLI` for register reads/writes — adequate
for one-second threshold updates in the prototype.