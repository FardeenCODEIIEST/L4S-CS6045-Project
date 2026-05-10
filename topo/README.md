# Mininet Topology

This directory contains the runnable Mininet/BMv2 topology scaffold for the
L4S prototype.

## Files

| File | Description |
|---|---|
| `topology.py` | Single bottleneck topology — 4 senders, 1 receiver (base) |
| `dumbbell_topology.py` | Dumbbell topology — 4 senders on s1, 4 receivers on s2 |
| `parking_lot_topology.py` | Parking lot topology — 3 switches in linear chain |
| `config.yaml` | Shared parameters for `topology.py` and `dumbbell_topology.py` |
| `config_parking_lot.yaml` | Parameters for `parking_lot_topology.py` (can do asymmetric bottleneck testing) |
| `__init__.py` | Package init |

---

## Topologies

### Single Bottleneck (`topology.py`)

```text
h1 L4S sender      \
h2 L4S sender       \
h3 Classic sender    s1 BMv2 simple_switch --[10 Mbps]--> h5 receiver
h4 Classic sender   /
```

All four senders compete at a single bottleneck link. The baseline topology
for validating L4S/Classic separation, CE marking, and anti-starvation logic.

### Dumbbell (`dumbbell_topology.py`)

```text
h1 (L4S)   ──┐                        ┌── h5 (recv for h1)
h2 (L4S)   ──┤                        ├── h6 (recv for h2)
              s1 ──[bottleneck]── s2
h3 (Classic)──┤                        ├── h7 (recv for h3)
h4 (Classic)──┘                        └── h8 (recv for h4)
```

Each sender has a dedicated receiver. Four concurrent flows compete at the
inter-switch bottleneck. Tests per-flow fairness between L4S and Classic
traffic.

### Parking Lot (`parking_lot_topology.py`)

```text
h1 (L4S, 3-hop)   ──┐
                     s1 ──[bn1]── s2 ──[bn2]── s3 ──── h5 (receiver)
h2 (Classic, 3-hop)──┘    ↑              ↑
                      h3 (L4S,      h4 (Classic,
                        2-hop)         1-hop)
```

Flows enter at different points along the chain and traverse different numbers
of hops. `bn1` and `bn2` can be set independently in `config_parking_lot.yaml`
to create asymmetric congestion. Tests whether L4S marking compounds across
multiple AQM points and whether longer flows accumulate more delay.

**Asymmetric configurations:**

| Config | bn1 | bn2 | Effect |
|---|---|---|---|
| Symmetric | 10 Mbps | 10 Mbps | Baseline |
| Tighter final hop | 15 Mbps | 10 Mbps | 3-hop flows marked at both s1 and s2 |
| Tighter first hop | 10 Mbps | 15 Mbps | Only long flows see first bottleneck |

---

## Runtime Model

BMv2 acts as a small IPv4 router. Each host is placed on a separate `/24` link
and receives:
- a default route through a synthetic gateway IP on its link,
- a static ARP entry mapping that gateway IP to the source MAC used by the P4
  forwarding action for the corresponding switch port.

The topology script installs:
- one `IngressImpl.ipv4_lpm` `/32` route per host,
- one `IngressImpl.l2_forward` unicast entry per host,
- BMv2 `set_queue_rate` and `set_queue_depth` on the receiver egress port,
- initial threshold, protection, and telemetry register values.

Checksum/segmentation offloads are disabled on Mininet interfaces so BMv2
forwards TCP packets with valid checksums.

---

## Configuration

All parameters are read from the config yaml at startup. Edit the relevant
file before running — no recompilation needed.

**`config.yaml`** — used by `topology.py` and `dumbbell_topology.py`:

```yaml
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

**`config_parking_lot.yaml`** — used by `parking_lot_topology.py`:

```yaml
bn1_bw_mbps: 10        # s1 -> s2 bottleneck
bn2_bw_mbps: 10        # s2 -> s3 bottleneck
sender_bw_mbps: 100
link_delay_ms: 5
queue_size_pkts: 100
priority_queues: 2
l4s_threshold: 30
classic_threshold: 80
classic_protection_threshold: 16
```

---

## Usage

### Single bottleneck

```bash
# Preview BMv2 runtime commands without root
python3 topo/topology.py --dry-run

# Start topology
sudo env PATH=$PATH PYTHONPATH=. python3 topo/topology.py

# Smoke test (ping h1/h3 -> h5)
sudo env PATH=$PATH PYTHONPATH=. python3 topo/topology.py --smoke-test

# Run fixed-threshold experiment
sudo env PATH=$PATH PYTHONPATH=. python3 topo/topology.py \
    --run-fixed --experiment-duration 30 --output-dir results/fixed

# Run dynamic-threshold experiment
sudo env PATH=$PATH PYTHONPATH=. python3 topo/topology.py \
    --run-dynamic --experiment-duration 30 --output-dir results/dynamic
```

### Dumbbell

```bash
sudo env PATH=$PATH PYTHONPATH=. python3 topo/dumbbell_topology.py
sudo env PATH=$PATH PYTHONPATH=. python3 topo/dumbbell_topology.py --smoke-test
sudo env PATH=$PATH PYTHONPATH=. python3 topo/dumbbell_topology.py \
    --config topo/config.yaml --dry-run
```

### Parking lot

```bash
# Symmetric bottleneck
sudo env PATH=$PATH PYTHONPATH=. python3 topo/parking_lot_topology.py

# Asymmetric — tighter final hop
# Edit config_parking_lot.yaml: bn1_bw_mbps: 15, bn2_bw_mbps: 10
sudo env PATH=$PATH PYTHONPATH=. python3 topo/parking_lot_topology.py \
    --config topo/config_parking_lot.yaml
```

---

## Running Traffic in the Mininet CLI

Start the receiver in the background first, then start senders:

```bash
mininet> h5 sudo python3 traffic/recv.py --iface h5-eth0 \
             --duration 45 --output-dir results/fixed &
mininet> h1 sudo python3 traffic/send_l4s.py --dst 10.0.5.5 \
             --port 5201 --bandwidth 4 --duration 30 \
             --output results/fixed/l4s_client.json &
mininet> h3 sudo python3 traffic/send_classic.py --dst 10.0.5.5 \
             --port 5202 --bandwidth 4 --duration 30 --ecn \
             --output results/fixed/classic_client.json &
```

After commands finish, verify results were captured:

```bash
mininet> h5 ls -lh results/fixed
```

---

## Dynamic Threshold Experiment

Running `--run-dynamic` starts `controller/controller.py` alongside the traffic
and writes a JSON-lines threshold trace to:

```text
results/dynamic/controller_trace.jsonl
```

The controller uses `simple_switch_CLI` for register reads/writes — intentionally
simple and adequate for one-second threshold updates in the prototype.
