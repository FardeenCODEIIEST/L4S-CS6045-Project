#!/usr/bin/env python3
"""
dumbbell_topology.py — Dumbbell topology
Two BMv2 switches connected by a single bottleneck link.
4 senders on the left switch, 4 receivers on the right switch.

  h1 (L4S)   ──┐                        ┌── h5 (recv for h1)
  h2 (L4S)   ──┤                        ├── h6 (recv for h2)
               s1 ──[bottleneck]──s2
  h3 (Classic)──┤                        ├── h7 (recv for h3)
  h4 (Classic)──┘                        └── h8 (recv for h4)

Usage:
    sudo python3 topo/dumbbell_topology.py [--bottleneck-bw <Mbps>]
                                  [--sender-bw <Mbps>]
                                  [--delay-ms <ms>]
                                  [--json <path>]
"""

import argparse
import os

import yaml

from mininet.net import Mininet
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel

from topo.topology import (
    BMv2Switch,
    build_runtime_commands,
    configure_hosts,
    configure_switch,
    wait_for_port,
    compile_p4,
    require_tool,
    REPO_ROOT,
    DEFAULT_P4_FILE,
    DEFAULT_JSON,
    DEFAULT_SWITCH_PATH,
    DEFAULT_CLI_PATH,
    HOSTS as S1_HOSTS,
)
from mininet.node import Host


DEFAULT_BW_BN   = 10
DEFAULT_BW_HOST = 100
DEFAULT_DELAY   = 5

THRIFT_PORT_S1 = 9090
THRIFT_PORT_S2 = 9091

# Receivers on s2 — mirror of the sender IPs
RECEIVER_HOSTS = [
    {'name': 'h5', 'ip': '10.0.5.5/24', 'mac': '00:00:00:00:05:05',
     'gateway_ip': '10.0.5.254', 'gateway_mac': '00:aa:bb:00:05:fe',
     'switch_port': 1, 'role': 'receiver'},
    {'name': 'h6', 'ip': '10.0.6.6/24', 'mac': '00:00:00:00:06:06',
     'gateway_ip': '10.0.6.254', 'gateway_mac': '00:aa:bb:00:06:fe',
     'switch_port': 2, 'role': 'receiver'},
    {'name': 'h7', 'ip': '10.0.7.7/24', 'mac': '00:00:00:00:07:07',
     'gateway_ip': '10.0.7.254', 'gateway_mac': '00:aa:bb:00:07:fe',
     'switch_port': 3, 'role': 'receiver'},
    {'name': 'h8', 'ip': '10.0.8.8/24', 'mac': '00:00:00:00:08:08',
     'gateway_ip': '10.0.8.254', 'gateway_mac': '00:aa:bb:00:08:fe',
     'switch_port': 4, 'role': 'receiver'},
]

S1_S2_PORT = 5
S2_S1_PORT = 5


DEFAULT_CONFIG = 'topo/config.yaml'


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_net(json_path, bw_bottleneck, bw_host, delay_ms, queue_size,
              priority_queues):
    net = Mininet(controller=None, link=TCLink)

    s1 = net.addSwitch('s1', cls=BMv2Switch, sw_path=DEFAULT_SWITCH_PATH,
                        json_path=str(json_path), thrift_port=THRIFT_PORT_S1,
                        priority_queues=priority_queues)
    s2 = net.addSwitch('s2', cls=BMv2Switch, sw_path=DEFAULT_SWITCH_PATH,
                        json_path=str(json_path), thrift_port=THRIFT_PORT_S2,
                        priority_queues=priority_queues)

    net.addLink(s1, s2, port1=S1_S2_PORT, port2=S2_S1_PORT, cls=TCLink,
                bw=bw_bottleneck, delay=f'{delay_ms}ms',
                max_queue_size=queue_size, use_htb=True)

    for spec in [s for s in S1_HOSTS if s.role != 'receiver']:
        h = net.addHost(spec.name, ip=spec.cidr, mac=spec.mac, cls=Host)
        net.addLink(h, s1, port2=spec.switch_port, cls=TCLink,
                    bw=bw_host, delay=f'{delay_ms}ms',
                    max_queue_size=queue_size, use_htb=True)

    for r in RECEIVER_HOSTS:
        h = net.addHost(r['name'], ip=r['ip'], mac=r['mac'], cls=Host)
        net.addLink(h, s2, port2=r['switch_port'], cls=TCLink,
                    bw=bw_host, delay=f'{delay_ms}ms',
                    max_queue_size=queue_size, use_htb=True)

    return net, s1, s2


def main():
    parser = argparse.ArgumentParser(description='Dumbbell L4S topology')
    parser.add_argument('--config',   default=DEFAULT_CONFIG,
                        help='Path to config.yaml')
    parser.add_argument('--p4-file', default=str(DEFAULT_P4_FILE))
    parser.add_argument('--json',    default=str(DEFAULT_JSON))
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--dry-run',    action='store_true')
    args = parser.parse_args()

    cfg = load_config(args.config)
    bottleneck_bw   = cfg['bottleneck_bw_mbps']
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

    net, s1, s2 = build_net(json_path, bottleneck_bw, sender_bw,
                             delay_ms, queue_size, priority_queues)

    try:
        net.start()
        configure_hosts(net)

        for port in (THRIFT_PORT_S1, THRIFT_PORT_S2):
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