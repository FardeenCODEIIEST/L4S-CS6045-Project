"""Tests for topo.dumbbell_topology."""

from __future__ import annotations

from topo.dumbbell_topology import (
    RECEIVER_HOSTS,
    S1_S2_PORT,
    S2_S1_PORT,
    THRIFT_PORT_S1,
    THRIFT_PORT_S2,
)
from topo.topology import HOSTS as S1_HOSTS


# ---------------------------------------------------------------------------
# Sender host counts
# ---------------------------------------------------------------------------

def test_dumbbell_has_four_sender_hosts_on_s1():
    senders = [s for s in S1_HOSTS if s.role != "receiver"]
    assert len(senders) == 4


def test_dumbbell_has_two_l4s_senders():
    assert len([s for s in S1_HOSTS if s.role == "l4s"]) == 2


def test_dumbbell_has_two_classic_senders():
    assert len([s for s in S1_HOSTS if s.role == "classic"]) == 2


# ---------------------------------------------------------------------------
# Receiver host counts and properties
# ---------------------------------------------------------------------------

def test_dumbbell_has_four_receiver_hosts_on_s2():
    assert len(RECEIVER_HOSTS) == 4


def test_dumbbell_all_receivers_have_role_receiver():
    assert all(r["role"] == "receiver" for r in RECEIVER_HOSTS)


def test_dumbbell_receiver_macs_are_unique():
    macs = [r["mac"] for r in RECEIVER_HOSTS]
    assert len(macs) == len(set(macs))


def test_dumbbell_receiver_ips_are_unique():
    ips = [r["ip"].split("/")[0] for r in RECEIVER_HOSTS]
    assert len(ips) == len(set(ips))


# ---------------------------------------------------------------------------
# Port collision checks
# ---------------------------------------------------------------------------

def test_dumbbell_thrift_ports_are_distinct():
    assert THRIFT_PORT_S1 != THRIFT_PORT_S2


def test_dumbbell_inter_switch_ports_are_defined():
    assert S1_S2_PORT == 5
    assert S2_S1_PORT == 5


def test_dumbbell_sender_switch_ports_do_not_collide_with_inter_switch_port():
    sender_ports = {s.switch_port for s in S1_HOSTS if s.role != "receiver"}
    assert S1_S2_PORT not in sender_ports


def test_dumbbell_receiver_switch_ports_do_not_collide_with_inter_switch_port():
    receiver_ports = {r["switch_port"] for r in RECEIVER_HOSTS}
    assert S2_S1_PORT not in receiver_ports


# ---------------------------------------------------------------------------
# IP uniqueness across both switches
# ---------------------------------------------------------------------------

def test_dumbbell_sender_and_receiver_ips_do_not_overlap():
    sender_ips = {s.ip for s in S1_HOSTS if s.role != "receiver"}
    receiver_ips = {r["ip"].split("/")[0] for r in RECEIVER_HOSTS}
    assert sender_ips.isdisjoint(receiver_ips)