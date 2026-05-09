# Mininet Topology

This directory contains the runnable Mininet/BMv2 topology scaffold for the
L4S prototype.

## Shape

```text
h1 L4S sender      \
h2 L4S sender       \
h3 Classic sender    s1 BMv2 simple_switch -> h5 receiver
h4 Classic sender   /
```

The sender links default to 100 Mbps. The `s1` to `h5` receiver link defaults
to 10 Mbps and is the bottleneck.

## Runtime Model

BMv2 acts as a small IPv4 router. Each host is placed on a separate `/24` link
and receives:

- a default route through a synthetic gateway IP on its link,
- a static ARP entry mapping that gateway IP to the source MAC used by the P4
  forwarding action for the corresponding switch port.

The topology script installs:

- one `IngressImpl.ipv4_lpm` `/32` route per host,
- one `IngressImpl.l2_forward` unicast entry per host,
- initial threshold, protection, and telemetry register values.
- checksum/segmentation offloads are disabled on Mininet interfaces so BMv2
  forwards TCP packets with valid checksums.

## Usage

Preview the BMv2 runtime commands without root:

```bash
python3 topo/topology.py --dry-run
```

Start the topology:

```bash
sudo python3 topo/topology.py
```

Run a non-interactive connectivity smoke test:

```bash
sudo python3 topo/topology.py --smoke-test
```

Run one fixed-threshold traffic experiment without using the Mininet CLI:

```bash
sudo python3 topo/topology.py --run-fixed --experiment-duration 30 --output-dir results/fixed
```

The runner returns result-file ownership to the user who invoked `sudo`, so
post-processing can run without `sudo`.

Run one dynamic-threshold traffic experiment:

```bash
sudo python3 topo/topology.py --run-dynamic --experiment-duration 30 --output-dir results/dynamic
```

This starts `controller/controller.py` while traffic is active and writes a
JSON-lines threshold trace to:

```text
results/dynamic/controller_trace.jsonl
```

Useful Mininet checks:

```bash
mininet> h1 ping -c 3 h5
mininet> h3 ping -c 3 h5
```

Traffic scripts can then be run inside the Mininet CLI. Start the receiver in
the background first, then start L4S and Classic clients while it is still
running:

```bash
mininet> h5 sudo python3 traffic/recv.py --iface h5-eth0 --duration 45 --output-dir results/fixed &
mininet> h1 sudo python3 traffic/send_l4s.py --dst 10.0.5.5 --port 5201 --bandwidth 4 --duration 30 --output results/fixed/l4s_client.json &
mininet> h3 sudo python3 traffic/send_classic.py --dst 10.0.5.5 --port 5202 --bandwidth 4 --duration 30 --ecn --output results/fixed/classic_client.json &
```

After the commands finish, check that the iperf output contains intervals rather
than an empty or interrupted run:

```bash
mininet> h5 ls -lh results/fixed
```

The controller currently uses `simple_switch_CLI` for register reads/writes.
This is intentionally simple and slower than a persistent thrift client, but it
is adequate for one-second threshold updates in the project prototype.
