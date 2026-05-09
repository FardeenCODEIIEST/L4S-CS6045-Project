import os
import shutil

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BMV2_RUNTIME_TESTS") != "1",
    reason="set RUN_BMV2_RUNTIME_TESTS=1 to run BMv2/PTF packet tests",
)


def require_runtime_tools():
    missing = [
        tool
        for tool in ("simple_switch", "simple_switch_CLI")
        if shutil.which(tool) is None
    ]
    if missing:
        pytest.skip(f"missing BMv2 runtime tools: {', '.join(missing)}")

    try:
        import ptf  # noqa: F401
        import scapy  # noqa: F401
    except ModuleNotFoundError as exc:
        pytest.skip(f"missing packet-test dependency: {exc.name}")


def test_runtime_scaffold_prerequisites_are_available():
    require_runtime_tools()


@pytest.mark.skip(reason="PTF harness is scaffolded; packet test implementation is pending")
def test_ecn_classification_sets_expected_priority_queue():
    require_runtime_tools()


@pytest.mark.skip(reason="PTF harness is scaffolded; packet test implementation is pending")
def test_threshold_marking_sets_ce_only_for_ecn_capable_packets():
    require_runtime_tools()


@pytest.mark.skip(reason="PTF harness is scaffolded; packet test implementation is pending")
def test_l3_forwarding_rewrites_macs_decrements_ttl_and_drops_expired_ttl():
    require_runtime_tools()


@pytest.mark.skip(reason="PTF harness is scaffolded; packet test implementation is pending")
def test_arp_forwarding_uses_l2_table_entries():
    require_runtime_tools()


@pytest.mark.skip(reason="PTF harness is scaffolded; packet test implementation is pending")
def test_classic_protection_budget_demotes_l4s_packets():
    require_runtime_tools()
