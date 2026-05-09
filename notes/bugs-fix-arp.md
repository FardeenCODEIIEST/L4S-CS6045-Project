# bugs/fix-arp

## Why This Branch Exists

The `staging` P4 pipeline handled only IPv4 packets in ingress. The parser accepted non-IPv4 Ethernet frames, but the ingress control only applied a forwarding table inside the `hdr.ipv4.isValid()` branch. As a result, ARP packets could pass parsing but never receive an `egress_spec` or multicast group assignment.

That is a runtime problem, not a compiler problem. The P4 program compiled successfully, but a BMv2 switch using this pipeline would not forward ARP unless the topology worked around it with static ARP entries or some external mechanism. In a Mininet experiment, that can prevent hosts from resolving each other before any L4S or Classic TCP traffic starts.

## What Changed

This branch adds an explicit non-IPv4 Ethernet forwarding path:

- `TYPE_ARP` was added for EtherType `0x0806`.
- The parser now recognizes ARP as a deliberate accepted non-IPv4 packet type.
- Ingress now includes a new `l2_forward` table keyed on Ethernet destination MAC.
- `l2_forward` can set a unicast egress port with `set_egress`.
- `l2_forward` can set a BMv2 multicast group with `set_mcast_grp`, which is intended for broadcast ARP.
- Non-IPv4 packets now use the Classic queue priority and apply `l2_forward` instead of falling through without a forwarding decision.

The IPv4 L4S logic remains unchanged except that Classic ECN classification is now explicit for `Not-ECT` and `ECT(0)`. This removes the previous unused-constant warning for `ECN_ECT0` and makes the code match the documented classification table.

## Runtime Requirement

The ARP fix requires runtime entries, the same way IPv4 forwarding requires `ipv4_lpm` entries. A switch launched with no `l2_forward` entries will still drop ARP because the default action remains `drop()`.

Expected runtime setup shape:

```text
table_add IngressImpl.l2_forward IngressImpl.set_egress <host-mac> => <egress-port>
table_add IngressImpl.l2_forward IngressImpl.set_mcast_grp ff:ff:ff:ff:ff:ff => <arp-broadcast-group>
```

The multicast group itself must be created through `simple_switch_CLI` or the control plane before the broadcast entry is useful. This branch provides the dataplane hook; the topology/controller work should install the entries.

## Validation

Compile check:

```bash
p4c-bm2-ss p4src/l4s.p4 -o /tmp/staging_p4_build/l4s.json
```

Result: the program compiles cleanly with no warnings.

Runtime behavior still needs a BMv2 packet test once the repo has a PTF or Mininet-based runtime-test harness.
