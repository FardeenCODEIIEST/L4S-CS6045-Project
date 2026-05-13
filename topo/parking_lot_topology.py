#!/usr/bin/env python3
"""
Mininet topology for the L4S BMv2 prototype — parking lot variant.

Three BMv2 switches in a linear chain. Flows enter at different points,
traversing different numbers of hops to reach h5.

  h1 (L4S, 3-hop)   ──┐
                       s1 ──[bn1]── s2 ──[bn2]── s3 ──── h5 (receiver)
  h2 (Classic, 3-hop)──┘    ↑               ↑
                        h3 (L4S,       h4 (Classic,
                          2-hop)          1-hop)

bn1 and bn2 can be set independently in config_parking_lot.yaml to create
asymmetric congestion. The default symmetric configuration has bn1 == bn2.

Usage:
    sudo python3 topo/parking_lot_topology.py
    sudo python3 topo/parking_lot_topology.py --smoke-test
    sudo python3 topo/parking_lot_topology.py --run-fixed --experiment-duration 30 --output-dir results/parking_fixed
    sudo python3 topo/parking_lot_topology.py --run-dynamic --experiment-duration 30 --output-dir results/parking_dynamic
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
import yaml
from pathlib import Path
from typing import Sequence

try:
    from mininet.cli import CLI
    from mininet.link import TCLink
    from mininet.log import info, setLogLevel
    from mininet.net import Mininet
    from mininet.node import Host
except ModuleNotFoundError:  # pragma: no cover - exercised only off Mininet hosts
    CLI = None
    TCLink = None
    Mininet = None
    Host = object

from topo.topology import (
    BMv2Switch,
    build_runtime_commands,
    configure_switch,
    disable_offloads,
    wait_for_port,
    wait_for_host_listen,
    compile_p4,
    require_tool,
    restore_output_ownership,
    _wait_process,
    REPO_ROOT,
    DEFAULT_P4_FILE,
    DEFAULT_JSON,
    DEFAULT_SWITCH_PATH,
    DEFAULT_CLI_PATH,
)

DEFAULT_CONFIG = REPO_ROOT / "topo" / "config_parking_lot.yaml"

THRIFT_PORT_S1 = 9090
THRIFT_PORT_S2 = 9091
THRIFT_PORT_S3 = 9092

# Port assignments for inter-switch links
S1_TO_S2   = 3
S2_FROM_S1 = 2
S2_TO_S3   = 3
S3_FROM_S2 = 3

HOSTS: tuple[dict, ...] = (
    {
        "name": "h1", "ip": "10.0.1.1/24", "mac": "00:00:00:00:01:01",
        "gateway_ip": "10.0.1.254", "gateway_mac": "00:aa:bb:00:01:fe",
        "switch": "s1", "port": 1, "role": "l4s",
    },
    {
        "name": "h2", "ip": "10.0.2.2/24", "mac": "00:00:00:00:02:02",
        "gateway_ip": "10.0.2.254", "gateway_mac": "00:aa:bb:00:02:fe",
        "switch": "s1", "port": 2, "role": "classic",
    },
    {
        "name": "h3", "ip": "10.0.3.3/24", "mac": "00:00:00:00:03:03",
        "gateway_ip": "10.0.3.254", "gateway_mac": "00:aa:bb:00:03:fe",
        "switch": "s2", "port": 1, "role": "l4s",
    },
    {
        "name": "h4", "ip": "10.0.4.4/24", "mac": "00:00:00:00:04:04",
        "gateway_ip": "10.0.4.254", "gateway_mac": "00:aa:bb:00:04:fe",
        "switch": "s3", "port": 1, "role": "classic",
    },
    {
        "name": "h5", "ip": "10.0.5.5/24", "mac": "00:00:00:00:05:05",
        "gateway_ip": "10.0.5.254", "gateway_mac": "00:aa:bb:00:05:fe",
        "switch": "s3", "port": 2, "role": "receiver",
    },
)


def load_config(path: str | Path) -> dict:
    with open(path) as handle:
        return yaml.safe_load(handle)


def build_net(
    json_path: Path,
    bw_bn1: int,
    bw_bn2: int,
    bw_host: int,
    delay_ms: int,
    queue_size: int,
    priority_queues: int,
) -> tuple:
    """
    bw_bn1 — bandwidth of s1-s2 link (Mbps)
    bw_bn2 — bandwidth of s2-s3 link (Mbps)
    Setting bw_bn1 != bw_bn2 creates asymmetric congestion across hops.
    """
    net = Mininet(controller=None, link=TCLink)

    switches = {}
    for name, port in (
        ("s1", THRIFT_PORT_S1),
        ("s2", THRIFT_PORT_S2),
        ("s3", THRIFT_PORT_S3),
    ):
        switches[name] = net.addSwitch(
            name, cls=BMv2Switch, sw_path=DEFAULT_SWITCH_PATH,
            json_path=str(json_path), thrift_port=port,
            priority_queues=priority_queues,
        )

    # bn1: s1 -> s2
    net.addLink(
        switches["s1"], switches["s2"],
        port1=S1_TO_S2, port2=S2_FROM_S1, cls=TCLink,
        bw=bw_bn1, delay=f"{delay_ms}ms",
        max_queue_size=queue_size, use_htb=True,
    )

    # bn2: s2 -> s3
    net.addLink(
        switches["s2"], switches["s3"],
        port1=S2_TO_S3, port2=S3_FROM_S2, cls=TCLink,
        bw=bw_bn2, delay=f"{delay_ms}ms",
        max_queue_size=queue_size, use_htb=True,
    )

    for spec in HOSTS:
        h = net.addHost(spec["name"], ip=spec["ip"], mac=spec["mac"], cls=Host)
        net.addLink(
            h, switches[spec["switch"]], port2=spec["port"], cls=TCLink,
            bw=bw_host, delay=f"{delay_ms}ms",
            max_queue_size=queue_size, use_htb=True,
        )

    return net, switches


def configure_hosts(net: Mininet) -> None:
    """Install default routes and static gateway ARP entries."""

    for spec in HOSTS:
        host = net.get(spec["name"])
        host.cmd(
            f"ip route replace default via {spec['gateway_ip']} dev {spec['name']}-eth0"
        )
        host.cmd(f"arp -s {spec['gateway_ip']} {spec['gateway_mac']}")
        disable_offloads(host, f"{spec['name']}-eth0")
        if spec["role"] == "l4s":
            host.cmd(
                'sysctl -w net.ipv4.tcp_allowed_congestion_control="reno cubic dctcp"'
            )


def run_fixed_experiment(
    net: Mininet,
    output_dir: str | Path,
    duration_s: int,
    l4s_bw_mbps: float,
    classic_bw_mbps: float,
) -> int:
    """Run one fixed-threshold L4S + Classic traffic experiment.

    Uses h1 (L4S, 3-hop) and h2 (Classic, 3-hop) as senders so both
    traverse identical paths and any difference is purely due to L4S vs
    Classic treatment at each switch.
    """

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_files = {
        "l4s_server":     output_dir / "iperf3_l4s.json",
        "classic_server": output_dir / "iperf3_classic.json",
        "l4s_client":     output_dir / "l4s_client.json",
        "classic_client": output_dir / "classic_client.json",
        "pcap":           output_dir / "capture.pcap",
    }
    for output_file in output_files.values():
        try:
            output_file.unlink()
        except FileNotFoundError:
            pass

    l4s_script     = REPO_ROOT / "traffic" / "send_l4s.py"
    classic_script = REPO_ROOT / "traffic" / "send_classic.py"

    h5 = net.get("h5")
    h1 = net.get("h1")
    h2 = net.get("h2")

    tcpdump = h5.popen(
        [
            "tcpdump", "-i", "h5-eth0", "-w", str(output_files["pcap"]),
            "-s", "96", "--immediate-mode",
            "tcp and (port 5201 or port 5202)",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    l4s_server = h5.popen(
        ["iperf3", "-s", "-4", "-p", "5201", "-1", "-J",
         "--logfile", str(output_files["l4s_server"])],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    classic_server = h5.popen(
        ["iperf3", "-s", "-4", "-p", "5202", "-1", "-J",
         "--logfile", str(output_files["classic_server"])],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    if not wait_for_host_listen(h5, [5201, 5202], timeout_s=5.0):
        for proc in (l4s_server, classic_server, tcpdump):
            proc.terminate()
        return 1

    l4s = h1.popen(
        [
            "python3", str(l4s_script),
            "--dst", "10.0.5.5", "--port", "5201",
            "--bandwidth", str(l4s_bw_mbps),
            "--duration", str(duration_s),
            "--output", str(output_files["l4s_client"]),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    classic = h2.popen(
        [
            "python3", str(classic_script),
            "--dst", "10.0.5.5", "--port", "5202",
            "--bandwidth", str(classic_bw_mbps),
            "--duration", str(duration_s),
            "--ecn", "--output", str(output_files["classic_client"]),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    failures = 0
    for name, proc in (("l4s", l4s), ("classic", classic)):
        code, output = _wait_process(name, proc, duration_s + 20)
        print(f"--- {name} sender output ---")
        print(output.strip())
        if code != 0:
            failures += 1

    for name, proc in (("l4s server", l4s_server), ("classic server", classic_server)):
        code, output = _wait_process(name, proc, 10)
        print(f"--- {name} output ---")
        print(output.strip())
        if code != 0:
            failures += 1

    tcpdump.terminate()
    code, output = _wait_process("tcpdump", tcpdump, 5)
    print("--- tcpdump output ---")
    print(output.strip())
    if code not in (0, -15):
        failures += 1

    print(f"*** Parking lot fixed experiment output: {output_dir}")
    restore_output_ownership(output_dir)
    return 1 if failures else 0


def run_dynamic_experiment(
    net: Mininet,
    output_dir: str | Path,
    duration_s: int,
    l4s_bw_mbps: float,
    classic_bw_mbps: float,
    thrift_port: int,
    cli_path: str,
    controller_interval_s: float,
) -> int:
    """Run one traffic experiment while the dynamic threshold controller runs."""

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    controller_log = output_dir / "controller_trace.jsonl"
    try:
        controller_log.unlink()
    except FileNotFoundError:
        pass

    controller_script = REPO_ROOT / "controller" / "controller.py"
    controller = subprocess.Popen(
        [
            "python3", str(controller_script),
            "--thrift-port", str(thrift_port),
            "--cli-path", cli_path,
            "--interval", str(controller_interval_s),
            "--log", str(controller_log),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    time.sleep(controller_interval_s)

    try:
        return run_fixed_experiment(
            net=net,
            output_dir=output_dir,
            duration_s=duration_s,
            l4s_bw_mbps=l4s_bw_mbps,
            classic_bw_mbps=classic_bw_mbps,
        )
    finally:
        controller.terminate()
        code, output = _wait_process("dynamic controller", controller, 5)
        print("--- dynamic controller output ---")
        print(output.strip())
        if code not in (0, -15):
            print(f"[WARN] dynamic controller exited with code {code}")
        restore_output_ownership(output_dir)


def run_smoke_tests(net: Mininet) -> int:
    """Ping h5 from one L4S and one Classic sender."""

    receiver_ip = next(spec["ip"].split("/")[0] for spec in HOSTS if spec["name"] == "h5")
    failures = 0
    for host_name in ("h1", "h2"):
        output = net.get(host_name).cmd(f"ping -c 3 -W 1 {receiver_ip}")
        print(f"--- {host_name} -> h5 ---")
        print(output.strip())
        if " 0% packet loss" not in output:
            failures += 1
    return 1 if failures else 0


def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the L4S parking lot Mininet topology")
    parser.add_argument("--config",   default=str(DEFAULT_CONFIG), help="Path to config yaml")
    parser.add_argument("--p4-file",  default=str(DEFAULT_P4_FILE))
    parser.add_argument("--json",     default=str(DEFAULT_JSON), help="BMv2 JSON path")
    parser.add_argument("--switch",   default=DEFAULT_SWITCH_PATH, help="simple_switch path")
    parser.add_argument("--cli-path", default=DEFAULT_CLI_PATH, help="simple_switch_CLI path")
    parser.add_argument(
        "--bmv2-queue-rate-pps", type=int, default=800,
        help="BMv2 packet-per-second cap on the receiver egress port; 0 disables",
    )
    parser.add_argument(
        "--bmv2-queue-depth", type=int, default=100,
        help="BMv2 receiver egress queue depth in packets; 0 leaves BMv2 default",
    )
    parser.add_argument("--smoke-test",  action="store_true",
                        help="Run h1/h2 to h5 pings and exit")
    parser.add_argument("--run-fixed",   action="store_true",
                        help="Run one fixed-threshold traffic experiment and exit")
    parser.add_argument("--run-dynamic", action="store_true",
                        help="Run one dynamic-threshold traffic experiment and exit")
    parser.add_argument("--experiment-duration", type=int,   default=30)
    parser.add_argument("--l4s-bw",              type=float, default=4.0)
    parser.add_argument("--classic-bw",          type=float, default=4.0)
    parser.add_argument("--controller-interval", type=float, default=1.0)
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "results" / "parking_fixed"))
    parser.add_argument("--no-cli",  action="store_true", help="Start and configure, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Print runtime commands only")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_arg_parser()
    args = parser.parse_args(argv)

    cfg = load_config(args.config)

    commands = build_runtime_commands(
        l4s_threshold=cfg["l4s_threshold"],
        classic_threshold=cfg["classic_threshold"],
        classic_protection_threshold=cfg["classic_protection_threshold"],
        bmv2_queue_rate_pps=args.bmv2_queue_rate_pps,
        bmv2_queue_depth_pkts=args.bmv2_queue_depth,
    )

    if args.dry_run:
        print("\n".join(commands))
        return 0

    if os.geteuid() != 0:
        raise SystemExit("Mininet topology must be run as root")
    if Mininet is None:
        raise SystemExit("Python Mininet package is not available")

    require_tool(args.switch)
    require_tool(args.cli_path)
    require_tool("p4c-bm2-ss")

    json_path = compile_p4(args.p4_file, args.json)
    setLogLevel("info")

    net, switches = build_net(
        json_path=json_path,
        bw_bn1=cfg["bn1_bw_mbps"],
        bw_bn2=cfg["bn2_bw_mbps"],
        bw_host=cfg["sender_bw_mbps"],
        delay_ms=cfg["link_delay_ms"],
        queue_size=cfg["queue_size_pkts"],
        priority_queues=cfg["priority_queues"],
    )

    try:
        net.start()
        configure_hosts(net)

        for port in (THRIFT_PORT_S1, THRIFT_PORT_S2, THRIFT_PORT_S3):
            if not wait_for_port("127.0.0.1", port):
                raise SystemExit(f"BMv2 thrift port {port} did not become ready")
            configure_switch(port, commands, args.cli_path)

        info("*** Parking lot topology configured\n")
        info("*** h1/h2 on s1 (3-hop)  h3 on s2 (2-hop)  h4 on s3 (1-hop)  h5 receiver\n")

        if args.smoke_test:
            return run_smoke_tests(net)

        if args.run_fixed:
            return run_fixed_experiment(
                net=net,
                output_dir=args.output_dir,
                duration_s=args.experiment_duration,
                l4s_bw_mbps=args.l4s_bw,
                classic_bw_mbps=args.classic_bw,
            )

        if args.run_dynamic:
            return run_dynamic_experiment(
                net=net,
                output_dir=args.output_dir,
                duration_s=args.experiment_duration,
                l4s_bw_mbps=args.l4s_bw,
                classic_bw_mbps=args.classic_bw,
                thrift_port=THRIFT_PORT_S1,
                cli_path=args.cli_path,
                controller_interval_s=args.controller_interval,
            )

        if not args.no_cli:
            CLI(net)
    finally:
        net.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())