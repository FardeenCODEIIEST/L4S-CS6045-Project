# bugs/fix-l3-forwarding

## Why This Branch Exists

The previous IPv4 forwarding action behaved like an incomplete router rewrite. It changed only the Ethernet destination MAC, decremented IPv4 TTL unconditionally, and set the egress port.

That creates two practical problems:

- forwarded IPv4 packets kept the original sender's Ethernet source MAC instead of using the switch/router MAC for the outgoing link,
- packets with TTL `0` or `1` could be decremented and forwarded with invalid wrapped or expired TTL values.

Both issues are runtime behavior problems. The P4 program compiled successfully, but BMv2 could emit packets that do not look like valid L3 forwarding output.

## What Changed

This branch makes the IPv4 forwarding path more router-like:

- `set_nhop` now accepts a next-hop destination MAC, an outgoing source MAC, and an egress port.
- `set_nhop` rewrites both `hdr.ethernet.dst_addr` and `hdr.ethernet.src_addr`.
- ingress drops IPv4 packets with `ttl <= 1` before applying the IPv4 LPM table.
- packets with `ttl > 1` continue through `ipv4_lpm`, where `set_nhop` decrements TTL and sets the egress port.

The existing checksum recomputation path already covers TTL and Ethernet-independent IPv4 changes, so no checksum-specific change was needed.

## Runtime Requirement

Every `ipv4_lpm` entry using `set_nhop` must now provide the outgoing source MAC in addition to the next-hop destination MAC and port.

Expected runtime setup shape:

```text
table_add IngressImpl.ipv4_lpm IngressImpl.set_nhop <dst-prefix> => <next-hop-mac> <switch-src-mac> <egress-port>
```

The `<switch-src-mac>` value should be the MAC address that hosts on the outgoing link should see as the router/switch source address.

## Validation

Compile check:

```bash
p4c-bm2-ss p4src/l4s.p4 -o /tmp/staging_p4_build/l4s.json
```

Result: the program compiles cleanly with no warnings.

Generated BMv2 JSON confirms that `IngressImpl.set_nhop` now has runtime parameters:

- `dst_addr` (`bit<48>`)
- `src_addr` (`bit<48>`)
- `port` (`bit<9>`)

Runtime behavior still needs a BMv2 packet test. The relevant checks should verify that a forwarded IPv4 packet has rewritten source and destination MACs, TTL decremented by one, and that packets with TTL `0` or `1` are dropped.
