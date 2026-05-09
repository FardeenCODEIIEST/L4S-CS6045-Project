# bugs/fix-classic-starvation

## Why This Branch Exists

The previous Classic anti-starvation guard was based on `reg_classic_qdepth`, which was updated from `standard_metadata.deq_qdepth` when Classic packets reached egress. That signal is useful telemetry, but it is a weak trigger for starvation protection.

Under strict-priority scheduling, a continuous L4S stream can prevent Classic packets from dequeuing. Once Classic dequeue events stop, `reg_classic_qdepth` stops being refreshed. The stored value can therefore remain stale or low exactly when Classic traffic is waiting behind the high-priority queue. This made the guard depend on a signal that can disappear during the condition it was meant to detect.

BMv2 does not expose a direct "read the current depth of another queue" primitive to ingress. A dataplane-only fix therefore needs to avoid pretending ingress can observe live Classic queue occupancy.

## What Changed

This branch replaces the dequeue-depth trigger with an ingress-observed Classic demand budget:

- `reg_classic_protection_budget` stores protection credits.
- Native Classic IPv4 arrivals add one credit, capped by `reg_classic_protection_threshold`.
- L4S IPv4 arrivals consume one available credit by being demoted to the Classic queue.
- `reg_classic_protection_threshold == 0` disables the guard and clears any stale protection budget.
- `classic_protection_triggered` still records whether the packet was demoted by the guard.

This keeps the guard tied to ingress-visible Classic demand rather than egress-visible Classic service. It does not claim precise weighted scheduling or exact live queue occupancy, but it avoids the stale-dequeue failure mode and reduces high-priority refill pressure when Classic traffic is present.

## Runtime Requirement

The existing `reg_classic_protection_threshold` value now acts as the maximum protection budget. A value of `0` disables the guard. A positive value allows Classic arrivals to accumulate up to that many credits.

Example shape:

```text
register_write reg_classic_protection_threshold 0 <budget-cap>
```

The right value should be tuned with runtime tests. Smaller caps make the guard react quickly but can demote L4S more often. Larger caps tolerate short Classic bursts but allow more L4S priority refill before the guard has visible impact.

## Validation

Compile check:

```bash
p4c-bm2-ss p4src/l4s.p4 -o /tmp/staging_p4_build/l4s.json
```

Result: the program compiles cleanly with no warnings.

Runtime behavior still needs a BMv2 packet/runtime test harness. The relevant runtime test should verify that Classic packets increment `reg_classic_protection_budget`, L4S packets consume it, and L4S packets with available budget leave through the Classic queue priority.
