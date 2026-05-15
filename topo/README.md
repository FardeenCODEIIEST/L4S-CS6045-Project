# `topo/` — Mininet/BMv2 Topology

This directory contains the runnable Mininet/BMv2 topology used by the L4S prototype experiments.

## Files

| File | Description |
|---|---|
| `topology.py` | Main Mininet topology runner. Builds the single BMv2 bottleneck topology, configures hosts and switch runtime state, and can run fixed or dynamic traffic experiments. |
| `config.yaml` | Default topology configuration for normal fixed-threshold or manual runs. |
| `config_fairness_tuning.yaml` | Fairness-oriented profile with lower L4S threshold, higher Classic threshold/protection values, BMv2 queue shaping defaults, and dynamic-controller tuning knobs. |
| `__init__.py` | Package marker for Python imports. |

## Topology

`topology.py` builds a single-switch bottleneck:

```text
h1 L4S sender      \
h2 L4S sender       \
h3 Classic sender    s1 BMv2 -- bottleneck --> h5 receiver
h4 Classic sender   /
```

In the current fixed and dynamic experiment helpers, traffic is generated from:

- `h1` to `h5` for L4S traffic on TCP port `5201`
- `h3` to `h5` for Classic traffic on TCP port `5202`

`h2` and `h4` are available in the topology but are not used by the default fixed/dynamic experiment runner.

## Runtime Model

BMv2 runs the compiled P4 program from:

```text
p4src/l4s.p4
```

The topology script compiles it to:

```text
build/l4s.json
```

if the JSON is missing or older than the P4 source.

Each host is placed on a separate `/24` link. Static routes and ARP entries are installed because the P4 program forwards IPv4 packets but does not implement ARP responder behavior for the router-facing gateway addresses.

At startup, `topology.py` configures:

- host IP, route, ARP, TCP ECN, and congestion-control settings
- BMv2 forwarding table entries
- L4S, Classic, and Classic-protection threshold registers
- optional BMv2 receiver egress queue rate/depth settings
- checksum offload disabling on Mininet interfaces

## Configuration Files

### `config.yaml`

Default profile:

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

`topology.py` also has built-in defaults for optional BMv2 queue shaping:

```yaml
bmv2_queue_rate_pps: 800
bmv2_queue_depth_pkts: 100
```

These can be added to the YAML or overridden with CLI flags.

### `config_fairness_tuning.yaml`

Fairness-oriented dynamic profile. It keeps the same basic topology parameters but changes threshold behavior:

```yaml
l4s_threshold: 8
classic_threshold: 100
classic_protection_threshold: 32
bmv2_queue_rate_pps: 800
bmv2_queue_depth_pkts: 100
```

It also includes a `controller:` section. `topology.py --run-dynamic` translates these values into `controller/controller.py` CLI arguments:

```yaml
controller:
  interval_s: 0.5
  min_threshold: 3
  max_threshold: 40
  growth_high: 8
  classic_backlog_threshold: 10
  l4s_delay_high: 1000
  healthy_l4s_qdepth: 3
  healthy_classic_qdepth: 2
  tighten_step: 24
  relax_step: 1
  classic_max_threshold: 120
  classic_protection_max_threshold: 64
  classic_adjust_step: 4
  classic_relax_step: 1
```

## Manual Usage

Run commands from the project root:

```bash
export RUN="sudo env PATH=$PATH PYTHONPATH=."
```

Start the topology and drop into the Mininet CLI:

```bash
$RUN python3 topo/topology.py
```

Run a connectivity smoke test from `h1` and `h3` to `h5`:

```bash
$RUN python3 topo/topology.py --smoke-test
```

Start and configure the topology, then exit without opening the CLI:

```bash
$RUN python3 topo/topology.py --no-cli
```

Print the BMv2 runtime commands that would be installed:

```bash
python3 topo/topology.py --dry-run
```

## Fixed Experiment

Run one fixed-threshold experiment:

```bash
$RUN python3 topo/topology.py \
  --run-fixed \
  --experiment-duration 180 \
  --l4s-bw 10.0 \
  --classic-bw 10.0 \
  --output-dir results/fixed_run_1
```

The fixed experiment writes:

```text
<output-dir>/iperf3_l4s.json
<output-dir>/iperf3_classic.json
<output-dir>/l4s_client.json
<output-dir>/classic_client.json
<output-dir>/capture.pcap
```

Summarize the result with:

```bash
python3 -m eval.summarize_results results/fixed_run_1
```

## Dynamic Experiment

Run one dynamic-threshold experiment:

```bash
$RUN python3 topo/topology.py \
  --run-dynamic \
  --config topo/config_fairness_tuning.yaml \
  --experiment-duration 180 \
  --l4s-bw 10.0 \
  --classic-bw 10.0 \
  --output-dir results/dynamic_run_example
```

`--run-dynamic` starts `controller/controller.py` alongside the traffic experiment. The dynamic controller writes:

```text
<output-dir>/controller_trace.jsonl
```

The traffic outputs are the same as the fixed experiment outputs.

Summarize the result with:

```bash
python3 -m eval.summarize_results results/dynamic_run_example
```

## Useful CLI Overrides

Most YAML values can be overridden from the command line:

```bash
$RUN python3 topo/topology.py \
  --config topo/config.yaml \
  --bottleneck-bw 10 \
  --sender-bw 100 \
  --delay-ms 5 \
  --queue-size 100 \
  --l4s-threshold 30 \
  --classic-threshold 80 \
  --classic-protection-threshold 16
```

BMv2 queue shaping overrides:

```bash
$RUN python3 topo/topology.py \
  --bmv2-queue-rate-pps 800 \
  --bmv2-queue-depth 100
```

Dynamic controller interval override:

```bash
$RUN python3 topo/topology.py \
  --run-dynamic \
  --controller-interval 0.5
```

## Connectivity Checks

Inside the Mininet CLI:

```bash
mininet> h1 ping -c 3 10.0.5.5
mininet> h3 ping -c 3 10.0.5.5
```

Or use host names:

```bash
mininet> h1 ping -c 3 h5
mininet> h3 ping -c 3 h5
```

## Notes

- `topology.py` must be run as root for Mininet.
- `topology.py` requires `simple_switch`, `simple_switch_CLI`, `p4c-bm2-ss`, Mininet, `iperf3`, and `tcpdump`.
- The script attempts to load and allow Linux `dctcp` support before creating the topology.
- Result files created under `sudo` are chowned back to the invoking user when `SUDO_UID` and `SUDO_GID` are available.
- For the full fixed-baseline plus dynamic-ablation workflow, see `scripts/README.md`.
