This directory contains all traffic generation and reception scripts for the L4S BMv2 prototype.

The **L4S sender** uses **iperf3 with DCTCP** for a closed-loop scalable CC response to ECN marks. Since DCTCP marks packets ECT(0) by default, an `iptables` mangle rule rewrites outgoing TCP packets to ECT(1) so BMv2 classifies them into the L4S queue (RFC 9331). The **Classic sender** uses **iperf3 with TCP Cubic** — the standard halving response.

---

## Files

| File | Purpose |
|---|---|
| `send_l4s.py` | iperf3 client with DCTCP + iptables ECT(0)→ECT(1) rewrite |
| `send_classic.py` | iperf3 client with TCP Cubic |
| `recv.py` | iperf3 servers + parallel tcpdump ECN capture |
| `load_profile.py` | Orchestrates time-varying load experiments across stages |

---

## Dependencies

```bash
# Required on all Mininet hosts
sudo apt install iperf3 tcpdump

# Verify if dctcp is available:
modprobe tcp_dctcp
sysctl net.ipv4.tcp_available_congestion_control | grep dctcp
```

All scripts require **root** (for `sysctl`, `iptables`, and `tcpdump`).

---

## ECN + Transport Design

```
L4S sender host
  iperf3 (DCTCP)         → packets leave as ECT(0)
  iptables mangle rule   → rewrites ECT(0) to ECT(1) 
  BMv2 ingress           → sees ECT(1), classifies as L4S queue 
  BMv2 egress (congested)→ marks CE (0b11)
  iperf3 receiver ACK    → ECE flag set (TCP ECN echo)
  DCTCP sender           → reduces cwnd proportionally   (gentle response)

Classic sender host
  iperf3 (Cubic)         → packets leave as ECT(0) or Not-ECT
  BMv2 ingress           → sees ECT(0)/Not-ECT, classifies as Classic queue 
  BMv2 egress (congested)→ marks CE (0b11)
  iperf3 receiver ACK    → ECE flag set
  Cubic sender           → halves cwnd    (standard response)
```

---

## Quick Start

### 1. Start the receiver (on receiver host h5)

```bash
sudo python3 recv.py --l4s-port 5201 --classic-port 5202 \
    --output-dir results/ --duration 60 --iface h5-eth0
```

### 2. Start L4S sender (on host h1, inside Mininet)

```bash
sudo python3 send_l4s.py --dst 10.0.0.5 --port 5201 \
    --bandwidth 4 --duration 30 --parallel 1 --output l4s_out.json
```

### 3. Start Classic sender (on host h3, inside Mininet)

```bash
# With ECN enabled (Cubic responds to CE marks via TCP halving)
sudo python3 send_classic.py --dst 10.0.0.5 --port 5202 \
    --bandwidth 4 --duration 30 --ecn --output classic_out.json
```

### 4. Run a full load profile experiment

```bash
# Steady load — 50% L4S, 50% Classic, 60 s
sudo python3 load_profile.py --profile steady --dst 10.0.0.5 \
    --bottleneck-bw 10 --l4s-fraction 0.5 --duration 60 \
    --output-dir results/steady/

# Step load — overload at midpoint
sudo python3 load_profile.py --profile step --dst 10.0.0.5 \
    --bottleneck-bw 10 --l4s-fraction 0.5 --duration 60 \
    --output-dir results/step/

# Dry run — print commands without executing
sudo python3 load_profile.py --profile mixed --dst 10.0.0.5 \
    --bottleneck-bw 10 --l4s-fraction 0.5 --duration 60 --dry-run
```

---

## ECN Codepoints Reference

| Codepoint | Binary | Decimal | Queue at switch |
|---|---|---|---|
| Not-ECT | `0b00` | 0 | Classic |
| ECT(1)  | `0b01` | 1 | **L4S** (RFC 9331) |
| ECT(0)  | `0b10` | 2 | Classic |
| CE      | `0b11` | 3 | Congestion signal (set by switch egress) |

DCTCP sends ECT(0) natively. The iptables rule in `send_l4s.py` rewrites this to ECT(1) on the wire. The switch never sees ECT(0) from the L4S sender.

---

## iptables Rule Details

Applied by `send_l4s.py` at startup, removed on exit:

```bash
# Add
iptables -t mangle -A POSTROUTING -p tcp -j TOS --set-tos 0x01/0x03

# Remove (done automatically on exit)
iptables -t mangle -D POSTROUTING -p tcp -j TOS --set-tos 0x01/0x03
```

`--set-tos 0x01/0x03` means: in the bits selected by mask `0x03` (low 2 bits of TOS = ECN field), set them to `0x01` (ECT(1)). DSCP bits are preserved.

---

## Load Profiles

| Profile | Description | Primary stress tested |
|---|---|---|
| `steady` | Fixed rates throughout | Baseline comparison |
| `ramp`   | Linear 10%→100% in 5 steps | Gradual threshold adaptation |
| `step`   | Normal load → 150% overload at midpoint | Sudden congestion onset |
| `burst`  | Alternating L4S and Classic bursts every quarter-duration | Asymmetric class pressure |
| `mixed`  | Ramp-up → steady overload → L4S spike | Combined stress |

---

## Output Files

| File | Source | Used by |
|---|---|---|
| `results/iperf3_l4s.json` | iperf3 server (L4S port) | `eval/` throughput analysis |
| `results/iperf3_classic.json` | iperf3 server (Classic port) | `eval/` throughput analysis |
| `results/capture.pcap` | tcpdump (both ports) | `eval/parse_pcap.py` for ECN bits + latency |
| `results/stage{N}_l4s.json` | load_profile iperf3 output | Per-stage throughput |
| `results/stage{N}_classic.json` | load_profile iperf3 output | Per-stage throughput |

---

## Notes

- Run scripts **inside Mininet hosts**: `h1 sudo python3 send_l4s.py ...`
- `sysctl` changes in Mininet are per-network-namespace (per host) — safe to set independently on h1 and h3.
- Timestamps in `capture.pcap` are from the receiver host's kernel clock. Since all Mininet hosts share the same system clock, sender–receiver timestamp differences approximate queueing delay directly without NTP correction.
- The `--no-cleanup` flag on both senders is used internally by `load_profile.py` so it can manage sysctl and iptables state centrally across stages.