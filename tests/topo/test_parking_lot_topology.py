"""Tests for topo.parking_lot_topology."""

from __future__ import annotations

from topo.parking_lot_topology import (
    HOSTS,
    S1_TO_S2,
    S2_FROM_S1,
    S2_TO_S3,
    S3_FROM_S2,
    THRIFT_PORT_S1,
    THRIFT_PORT_S2,
    THRIFT_PORT_S3,
)


# ---------------------------------------------------------------------------
# Host counts and roles
# ---------------------------------------------------------------------------

def test_parking_lot_has_five_hosts():
    assert len(HOSTS) == 5


def test_parking_lot_has_one_receiver():
    receivers = [h for h in HOSTS if h["role"] == "receiver"]
    assert len(receivers) == 1
    assert receivers[0]["name"] == "h5"


def test_parking_lot_has_two_l4s_senders():
    assert len([h for h in HOSTS if h["role"] == "l4s"]) == 2


def test_parking_lot_has_two_classic_senders():
    assert len([h for h in HOSTS if h["role"] == "classic"]) == 2


# ---------------------------------------------------------------------------
# Switch placement
# ---------------------------------------------------------------------------

def test_parking_lot_hosts_attach_to_correct_switches():
    switch_map = {h["name"]: h["switch"] for h in HOSTS}

    assert switch_map["h1"] == "s1"
    assert switch_map["h2"] == "s1"
    assert switch_map["h3"] == "s2"
    assert switch_map["h4"] == "s3"
    assert switch_map["h5"] == "s3"


# ---------------------------------------------------------------------------
# Uniqueness checks
# ---------------------------------------------------------------------------

def test_parking_lot_all_macs_are_unique():
    macs = [h["mac"] for h in HOSTS]
    assert len(macs) == len(set(macs))


def test_parking_lot_all_ips_are_unique():
    ips = [h["ip"].split("/")[0] for h in HOSTS]
    assert len(ips) == len(set(ips))


# ---------------------------------------------------------------------------
# Port checks
# ---------------------------------------------------------------------------

def test_parking_lot_thrift_ports_are_all_distinct():
    ports = {THRIFT_PORT_S1, THRIFT_PORT_S2, THRIFT_PORT_S3}
    assert len(ports) == 3


def test_parking_lot_inter_switch_ports_are_defined():
    assert S1_TO_S2   == 3
    assert S2_FROM_S1 == 2
    assert S2_TO_S3   == 3
    assert S3_FROM_S2 == 3


def test_parking_lot_s1_host_ports_do_not_collide_with_uplink():
    s1_host_ports = {h["port"] for h in HOSTS if h["switch"] == "s1"}
    assert S1_TO_S2 not in s1_host_ports


def test_parking_lot_s2_host_ports_do_not_collide_with_either_link():
    s2_host_ports = {h["port"] for h in HOSTS if h["switch"] == "s2"}
    assert S2_FROM_S1 not in s2_host_ports
    assert S2_TO_S3   not in s2_host_ports


# ---------------------------------------------------------------------------
# Hop count logic
# ---------------------------------------------------------------------------

def test_parking_lot_hop_counts_match_switch_position():
    """Verify each sender is the expected number of hops from h5."""
    switch_order = {"s1": 1, "s2": 2, "s3": 3}
    receiver_switch = next(h["switch"] for h in HOSTS if h["name"] == "h5")

    expected_hops = {
        "h1": 3,   # s1 -> s2 -> s3 -> h5
        "h2": 3,
        "h3": 2,   # s2 -> s3 -> h5
        "h4": 1,   # s3 -> h5
    }
    for host in HOSTS:
        if host["role"] == "receiver":
            continue
        hops = switch_order[receiver_switch] - switch_order[host["switch"]] + 1
        assert hops == expected_hops[host["name"]], (
            f"{host['name']}: expected {expected_hops[host['name']]} hops, got {hops}"
        )