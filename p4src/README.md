# P4 Data Plane Status (`p4src`)

This document captures the **current implementation state** of the P4 data plane for the L4S project.

## What Is Implemented

- P4 target: `P4_16` + `v1model` (`simple_switch` / BMv2).
- Traffic parsing: Ethernet + IPv4.
- ECN-based traffic classification:
  - **L4S**: `ECT(1)` and `CE`
  - **Classic (non-L4S)**: `Not-ECT` and `ECT(0)`
- Queue selection in ingress using `standard_metadata.priority`:
  - `CLASSIC_QUEUE_ID = 0`
  - `L4S_QUEUE_ID = 1`
- Egress threshold-driven CE marking:
  - Per-class thresholds read from registers
  - If `deq_qdepth >= threshold`, packet ECN is set to `CE`
- Queue telemetry export in egress to registers:
  - queue depth (`deq_qdepth`)
  - enqueue depth (`enq_qdepth`) derived growth
  - queueing delay proxy (`deq_timedelta`)

> Current mode is a **two-queue design** (priority queue for L4S and another for Classic), assuming BMv2 runs with `--priority-queues 2`.

## File-by-File Notes

### `headers.p4`

- Defines constants for:
  - EtherType (`TYPE_IPV4`)
  - ECN values (`ECN_NOT_ECT`, `ECN_ECT1`, `ECN_ECT0`, `ECN_CE`)
  - queue IDs (`CLASSIC_QUEUE_ID`, `L4S_QUEUE_ID`)
- Defines headers:
  - `ethernet_t`
  - `ipv4_t`
- Defines metadata (`l4s_meta_t`) used to carry:
  - class decision (`is_l4s`)
  - selected queue ID
  - sampled threshold / queue metrics / growth
  - threshold-crossing flag

### `registers.p4`

- Defines the control/state registers:
  - thresholds:
    - `reg_l4s_threshold`
    - `reg_classic_threshold`
  - queue depth:
    - `reg_l4s_qdepth`
    - `reg_classic_qdepth`
  - dequeue delay:
    - `reg_l4s_delay`
    - `reg_classic_delay`
  - growth estimate:
    - `reg_l4s_growth`
    - `reg_classic_growth`
  - helper previous enqueue depth:
    - `reg_l4s_prev_enq_qdepth`
    - `reg_classic_prev_enq_qdepth`

### `l4s.p4`

- **Parser** extracts Ethernet and IPv4.
- **Ingress**:
  - classifies packets by IPv4 ECN
  - sets queue ID in metadata
  - writes queue ID to `standard_metadata.priority`
  - performs forwarding via `ipv4_lpm`
- **Egress**:
  - reads per-class threshold
  - samples queue metadata fields
  - computes enqueue-depth growth
  - sets ECN to `CE` when threshold is crossed
  - exports telemetry into registers per class
- **Checksum + Deparser**:
  - checksum updated after potential ECN modification
  - emits Ethernet and IPv4 headers

## Current Behavior Summary

1. L4S and Classic packets are separated into two priority queues.
2. Each class has independent threshold state in registers.
3. Egress applies threshold-based CE marking and exports telemetry.
4. Controller (outside `p4src`) can read telemetry and adjust thresholds dynamically.

## Known Gaps in Current `p4src`

- No explicit in-switch coupling logic between L4S and Classic thresholds.
- No direct anti-starvation logic beyond threshold tuning.
- No single-queue emulation mode yet.

## Next Planned Direction

Implement an optional **single-queue mode** where both classes share one queue, while ingress/egress logic approximates L4S prioritization and protects Classic traffic from starvation using class-aware admission/marking logic.
