# P4SRC Component Overview

This document explains the current `p4src` implementation for the L4S project. It is written to help a reader understand what the code is doing today, how packets move through the pipeline, and what parts of the design are already implemented.

The current branch is expected to be `feature/p4src`, and the implementation in this folder is a **two-queue BMv2 design**:

- Queue `0`: Classic / non-L4S traffic
- Queue `1`: L4S traffic

This design assumes BMv2 is started with two priority queues, for example with `--priority-queues 2`.

## Goal of This Component

The purpose of the `p4src` component is to:

- parse Ethernet and IPv4 packets,
- classify traffic as **L4S** or **Classic** using the IPv4 ECN field,
- place the packet into one of two queues,
- protect Classic traffic from starvation when its queue backlog becomes too high,
- monitor queue state in egress, and
- mark packets with `CE` when the queue depth crosses a configured threshold.

In short, the current P4 program separates traffic into two classes and performs simple threshold-based congestion marking independently for each class.

## Files in `p4src`

### [`headers.p4`](/home/kunal/Documents/L4S-CS6045-Project/p4src/headers.p4)

Defines:

- protocol constants such as IPv4 EtherType,
- ECN codepoints,
- queue IDs for Classic and L4S traffic,
- packet headers (`ethernet_t`, `ipv4_t`),
- custom metadata (`l4s_meta_t`) used to carry classification and queue telemetry across the pipeline.

### [`registers.p4`](/home/kunal/Documents/L4S-CS6045-Project/p4src/registers.p4)

Defines all register state used by the dataplane:

- per-class marking thresholds,
- Classic-queue protection threshold,
- per-class queue depth samples,
- per-class queue delay samples,
- per-class growth samples,
- previous enqueue-depth values used to estimate queue growth.

### [`l4s.p4`](/home/kunal/Documents/L4S-CS6045-Project/p4src/l4s.p4)

Contains the full P4 pipeline:

- parser,
- ingress logic,
- egress logic,
- checksum recomputation,
- deparser.

## High-Level Packet Flow

The current packet processing flow is:

1. Parse Ethernet.
2. If the EtherType is IPv4, parse the IPv4 header.
3. In ingress, classify the packet using the IPv4 ECN field.
4. Assign the packet to either the Classic queue or the L4S queue.
5. If the Classic queue is already backlogged, temporarily demote new L4S packets to the Classic queue.
6. Forward the packet using the IPv4 LPM table.
7. In egress, read queue metadata and the queue-specific threshold.
8. If the queue depth is above threshold, set ECN to `CE` for ECN-capable packets.
9. Write queue telemetry back to registers for controller use.
10. Recompute the IPv4 checksum and emit the packet.

## ECN-Based Traffic Classification

The current code uses the IPv4 ECN field to decide whether a packet should be treated as L4S or Classic.

Defined ECN values:

- `ECN_NOT_ECT = 0b00`
- `ECN_ECT1    = 0b01`
- `ECN_ECT0    = 0b10`
- `ECN_CE      = 0b11`

Current classification logic:

- **L4S traffic**: packets with `ECT(1)` or `CE`
- **Classic traffic**: packets with `Not-ECT` or `ECT(0)`

This logic appears in ingress:

- packets start with `meta.is_l4s = 0` and `meta.queue_id = CLASSIC_QUEUE_ID`,
- if `hdr.ipv4.ecn` is `ECN_ECT1` or `ECN_CE`, the packet is reclassified as L4S,
- otherwise it remains in the Classic class.

This means the current implementation uses ECN as the only signal for deciding which queue a packet should enter.

## Queue Selection Logic

The queue mapping constants are:

- `CLASSIC_QUEUE_ID = 0`
- `L4S_QUEUE_ID = 1`

After classification, ingress writes the selected queue ID into:

- `meta.queue_id`
- `standard_metadata.priority`

In BMv2 with priority queues enabled, `standard_metadata.priority` determines which queue the packet uses. So the program is effectively doing:

- Classic traffic -> queue `0`
- L4S traffic -> queue `1`

This is the main mechanism that creates the two-queue behavior in the current implementation.

There is now one exception for starvation protection:

- if a packet is classified as L4S but the Classic queue depth is already above a configured protection threshold, that packet is temporarily placed into the Classic queue instead of the L4S queue.

## Ingress Logic Explained

The ingress control performs three main tasks.

### 1. Initialize metadata

At the beginning of `apply`, the program resets all custom metadata fields:

- `is_l4s`
- `queue_id`
- `classic_protection_triggered`
- `current_threshold`
- `classic_qdepth_snapshot`
- `classic_protection_threshold`
- `qdepth_sample`
- `enq_qdepth_sample`
- `delay_sample`
- `growth_sample`
- `threshold_exceeded`

This ensures that every packet starts with clean metadata values before classification and egress processing.

### 2. Classify L4S vs Classic

If the packet contains a valid IPv4 header, ingress checks the ECN bits:

- `ECT(1)` and `CE` are treated as L4S,
- everything else is treated as Classic.

The result is stored in `meta.is_l4s`.

### 3. Set queue and forward packet

Once the class is known:

- ingress reads the latest Classic queue depth from `reg_classic_qdepth`,
- ingress reads the starvation-protection threshold from `reg_classic_protection_threshold`,
- if the packet is L4S and the Classic queue depth is at or above that threshold, ingress demotes the packet to the Classic queue,
- ingress sets `standard_metadata.priority` to the chosen queue ID,
- then applies the `ipv4_lpm` table for forwarding.

This is the anti-starvation logic in the current code. The idea is simple:

- if L4S packets keep entering the higher-priority queue forever, Classic traffic can wait indefinitely,
- once the Classic queue shows sustained backlog, the switch stops feeding new packets into the higher-priority queue,
- the L4S queue drains, and the scheduler gets an opportunity to serve Classic traffic.

The forwarding table supports:

- `set_nhop(bit<48> dst_addr, bit<9> port)`
- `drop()`
- `NoAction`

`set_nhop` updates:

- Ethernet destination MAC,
- IPv4 TTL,
- egress port (`standard_metadata.egress_spec`).

The default action is `drop()`.

## Egress Logic Explained

The egress control is where congestion-related logic happens in the current design.

### Queue metadata read from BMv2

For every valid IPv4 packet, egress reads:

- `standard_metadata.deq_qdepth`
- `standard_metadata.enq_qdepth`
- `standard_metadata.deq_timedelta`

These are used as the runtime queue measurements for the packet currently leaving the switch.

### Per-class threshold selection

The program keeps separate thresholds for L4S and Classic traffic:

- `reg_l4s_threshold`
- `reg_classic_threshold`

Based on `meta.is_l4s`, egress reads the appropriate threshold register.

After the anti-starvation change, the actual code uses `meta.queue_id` instead of only `meta.is_l4s` for this decision. That matters because a packet can still be classified as L4S but temporarily use the Classic queue.

It also reads a per-class helper register storing the previous enqueue depth:

- `reg_l4s_prev_enq_qdepth`
- `reg_classic_prev_enq_qdepth`

### Queue growth estimation

The current code estimates queue growth using:

`growth = current_enq_qdepth - previous_enq_qdepth`

but only when the current enqueue depth is not smaller than the previous one. Otherwise, growth is set to `0`.

This is a simple one-step approximation intended to indicate whether the queue is building up.

### Threshold-based CE marking

After reading the threshold and queue depth, egress checks:

- `threshold > 0`
- `current_qdepth >= threshold`

If both conditions are true:

- `meta.threshold_exceeded = 1`
- `hdr.ipv4.ecn = ECN_CE`

So the current marking logic is:

- no marking when threshold is `0`,
- no `CE` marking for `Not-ECT` packets,
- mark with `CE` when the measured dequeue queue depth reaches or exceeds the configured per-class threshold.

This is the main congestion response implemented today.

### Telemetry export to registers

After marking, the program writes telemetry back into class-specific registers.

For L4S traffic:

- `reg_l4s_qdepth`
- `reg_l4s_delay`
- `reg_l4s_growth`
- `reg_l4s_prev_enq_qdepth`

For Classic traffic:

- `reg_classic_qdepth`
- `reg_classic_delay`
- `reg_classic_growth`
- `reg_classic_prev_enq_qdepth`

This gives the controller a way to inspect recent queue state for each class and potentially update thresholds over time.

## Meaning of the Custom Metadata

The `l4s_meta_t` structure carries per-packet state between ingress and egress.

- `is_l4s`: whether the packet was classified as L4S
- `queue_id`: selected queue ID
- `classic_protection_triggered`: whether starvation protection demoted the packet
- `current_threshold`: threshold value read in egress
- `classic_qdepth_snapshot`: Classic queue depth seen by ingress
- `classic_protection_threshold`: protection threshold read by ingress
- `qdepth_sample`: sampled dequeue queue depth
- `enq_qdepth_sample`: sampled enqueue queue depth
- `delay_sample`: sampled dequeue time delta
- `growth_sample`: estimated queue growth
- `threshold_exceeded`: whether the queue depth crossed threshold for this packet

Some of these fields are mainly useful for observability and debugging, because they let us trace what decision the dataplane made for a packet.

## Registers Used in the Current Design

All registers currently use a single entry with index `REG_INDEX = 0`. That means:

- there is one global L4S threshold value,
- one global Classic threshold value,
- one latest queue sample per class.

The current register layout is:

- `reg_l4s_threshold`
- `reg_classic_threshold`
- `reg_classic_protection_threshold`
- `reg_l4s_qdepth`
- `reg_classic_qdepth`
- `reg_l4s_delay`
- `reg_classic_delay`
- `reg_l4s_growth`
- `reg_classic_growth`
- `reg_l4s_prev_enq_qdepth`
- `reg_classic_prev_enq_qdepth`

This is a simple and practical starting point for the project, although it is not yet a full multi-flow or per-port state design.

## What Is Implemented Today

The current `p4src` code already supports:

- IPv4 parsing,
- ECN-based L4S/Classic classification,
- two-queue traffic separation,
- starvation protection for Classic traffic by temporarily demoting new L4S packets when the Classic backlog is high,
- IPv4 forwarding through an LPM table,
- per-class threshold-based CE marking,
- per-class queue telemetry export through registers,
- checksum recomputation after ECN changes.

## What Is Not Yet Implemented

The current code does **not** yet implement:

- coupled AQM behavior between the two classes,
- weighted scheduling or precise fairness guarantees between queues,
- dynamic threshold adaptation inside the dataplane,
- a single-queue mode,
- richer per-port or per-flow register indexing.

So, at this stage, the P4 component should be understood as a clean prototype for:

- separating L4S and Classic traffic, and
- applying independent threshold-based congestion marking to each class.

## Practical Summary

If someone wants to understand the code quickly, the core idea is:

- ingress uses ECN to decide whether a packet is L4S or Classic,
- the packet is mapped to one of two BMv2 queues using `standard_metadata.priority`,
- if the Classic queue backlog is too high, new L4S packets are temporarily redirected into the Classic queue,
- egress checks the queue depth against a class-specific threshold,
- if the threshold is crossed, the packet is marked with `CE`,
- recent queue measurements are stored in registers for external monitoring or controller logic.

That is the current working logic implemented in `p4src`.
