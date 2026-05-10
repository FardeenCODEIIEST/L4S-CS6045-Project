#!/usr/bin/env python3
"""
parking_lot_topology.py — Parking lot topology 
Three BMv2 switches in a linear chain. Flows enter at different points,
traversing different numbers of hops to reach h5.

  h1 (L4S, 3-hop)  ──┐
                      s1 ──[bn1]── s2 ──[bn2]── s3 ──── h5 (receiver)
  h2 (Classic, 3-hop)─┘    ↑              ↑
                       h3 (L4S, 2-hop)  h4 (Classic, 1-hop)

bn1 and bn2 can have different bandwidths to create asymmetric congestion.
See config_parking_lot.yaml for parameter tuning.

Usage:
    sudo python3 topo/parking_lot_topology.py
    sudo python3 topo/parking_lot_topology.py --config topo/config_parking_lot.yaml
"""

import argparse
import os

import yaml

from mininet.net import Mininet
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.node import Host

from topo.topology import (
    BMv2Switch,
    build_runtime_commands,
    configure_switch,
    disable_offloads,
    wait_for_port,
    compile_p4,
    require_tool,
    DEFAULT_P4_FILE,
    DEFAULT_JSON,
    DEFAULT_SWITCH_PATH,
    DEFAULT_CLI_PATH,
)

DEFAULT_CONFIG = 'topo/config_parking_lot.yaml'

THRIFT_PORT_S1 = 9090
THRIFT_PORT_S2 = 9091
THRIFT_PORT_S3 = 9092

# Port assignments for inter-switch links
S1_TO_S2   = 3
S2_FROM_S1 = 2
S2_TO_S3   = 3
S3_FROM_S2 = 3

HOSTS = [
    {'name': 'h1', 'ip': '10.0.1.1/24', 'mac': '00:00:00:00:01:01',
     'gateway_ip': '10.0.1.254', 'gateway_mac': '00:aa:bb:00:01:fe',
     'switch': 's1', 'port': 1, 'role': 'l4s'},
    {'name': 'h2', 'ip': '10.0.2.2/24', 'mac': '00:00:00:00:02:02',
     'gateway_ip': '10.0.2.254', 'gateway_mac': '00:aa:bb:00:02:fe',
     'switch': 's1', 'port': 2, 'role': 'classic'},
    {'name': 'h3', 'ip': '10.0.3.3/24', 'mac': '00:00:00:00:03:03',
     'gateway_ip': '10.0.3.254', 'gateway_mac': '00:aa:bb:00:03:fe',
     'switch': 's2', 'port': 1, 'role': 'l4s'},
    {'name': 'h4', 'ip': '10.0.4.4/24', 'mac': '00:00:00:00:04:04',
     'gateway_ip': '10.0.4.254', 'gateway_mac': '00:aa:bb:00:04:fe',
     'switch': 's3', 'port': 1, 'role': 'classic'},
    {'name': 'h5', 'ip': '10.0.5.5/24', 'mac': '00:00:00:00:05:05',
     'gateway_ip': '10.0.5.254', 'gateway_mac': '00:aa:bb:00:05:fe',
     'switch': 's3', 'port': 2, 'role': 'receiver'},
]


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_net(json_path, bw_bn1, bw_bn2, bw_host, delay_ms, queue_size,
              priority_queues):
    """
    bw_bn1 — bandwidth of s1-s2 link (Mbps)
    bw_bn2 — bandwidth of s2-s3 link (Mbps)
    Setting bw_bn1 != bw_bn2 creates asymmetric congestion across hops.
    """
    net = Mininet(controller=None, link=TCLink)

    switches = {}
    for name, port in (('s1', THRIFT_PORT_S1), ('s2', THRIFT_PORT_S2),
                       ('s3', THRIFT_PORT_S3)):
        switches[name] = net.addSwitch(
            name, cls=BMv2Switch, sw_path=DEFAULT_SWITCH_PATH,
            json_path=str(json_path), thrift_port=port,
            priority_queues=priority_queues)

    # bn1: s1 -> s2
    net.addLink(switches['s1'], switches['s2'],
                port1=S1_TO_S2, port2=S2_FROM_S1, cls=TCLink,
                bw=bw_bn1, delay=f'{delay_ms}ms',
                max_queue_size=queue_size, use_htb=True)

    # bn2: s2 -> s3
    net.addLink(switches['s2'], switches['s3'],
                port1=S2_TO_S3, port2=S3_FROM_S2, cls=TCLink,
                bw=bw_bn2, delay=f'{delay_ms}ms',
                max_queue_size=queue_size, use_htb=True)

    for spec in HOSTS:
        h = net.addHost(spec['name'], ip=spec['ip'], mac=spec['mac'], cls=Host)
        net.addLink(h, switches[spec['switch']], port2=spec['port'],
                    cls=TCLink, bw=bw_host, delay=f'{delay_ms}ms',
                    max_queue_size=queue_size, use_htb=True)

    return net, switches


def configure_hosts(net):
    for spec in HOSTS:
        host = net.get(spec['name'])
        host.cmd(f"ip route replace default via {spec['gateway_ip']} "
                 f"dev {spec['name']}-eth0")
        host.cmd(f"arp -s {spec['gateway_ip']} {spec['gateway_mac']}")
        disable_offloads(host, f"{spec['name']}-eth0")
        if spec['role'] == 'l4s':
            host.cmd('sysctl -w net.ipv4.tcp_allowed_congestion_control='
                     '"reno cubic dctcp"')


def main():
    parser = argparse.ArgumentParser(description='Parking lot L4S topology')
    parser.add_argument('--config',  default=DEFAULT_CONFIG,
                        help='Path to config yaml')
    parser.add_argument('--p4-file', default=str(DEFAULT_P4_FILE))
    parser.add_argument('--json',    default=str(DEFAULT_JSON))
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--dry-run',    action='store_true')
    args = parser.parse_args()

    cfg = load_config(args.config)
    bw_bn1          = cfg['bn1_bw_mbps']
    bw_bn2          = cfg['bn2_bw_mbps']
    sender_bw       = cfg['sender_bw_mbps']
    delay_ms        = cfg['link_delay_ms']
    queue_size      = cfg['queue_size_pkts']
    priority_queues = cfg['priority_queues']
    l4s_thresh      = cfg['l4s_threshold']
    classic_thresh  = cfg['classic_threshold']
    protection_thresh = cfg['classic_protection_threshold']

    cmds = build_runtime_commands(
        l4s_threshold=l4s_thresh,
        classic_threshold=classic_thresh,
        classic_protection_threshold=protection_thresh,
    )

    if args.dry_run:
        print('\n'.join(cmds))
        return 0

    if os.geteuid() != 0:
        raise SystemExit('Must run as root')

    require_tool(DEFAULT_SWITCH_PATH)
    require_tool(DEFAULT_CLI_PATH)

    json_path = compile_p4(args.p4_file, args.json)
    setLogLevel('info')

    net, switches = build_net(json_path, bw_bn1, bw_bn2, sender_bw,
                              delay_ms, queue_size, priority_queues)

    try:
        net.start()
        configure_hosts(net)

        for port in (THRIFT_PORT_S1, THRIFT_PORT_S2, THRIFT_PORT_S3):
            if not wait_for_port('127.0.0.1', port):
                raise SystemExit(f'BMv2 thrift port {port} did not become ready')
            configure_switch(port, cmds, DEFAULT_CLI_PATH)

        if args.smoke_test:
            h1 = net.get('h1')
            output = h1.cmd('ping -c 3 -W 1 10.0.5.5')
            print(output)
            return 0 if '0% packet loss' in output else 1

        CLI(net)
    finally:
        net.stop()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())