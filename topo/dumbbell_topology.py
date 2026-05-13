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
    sudo python3 topo/dumbbell_topology.py
    sudo python3 topo/dumbbell_topology.py --smoke-test
    sudo python3 topo/dumbbell_topology.py --run-fixed --experiment-duration 30 --output-dir results/dumbbell_fixed
    sudo python3 topo/dumbbell_topology.py --run-dynamic --experiment-duration 30 --output-dir results/dumbbell_dynamic
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
import yaml
from pathlib import Path
from typing import Sequence

from topo.topology import (
    BMv2Switch,
    CLI,
    Host,
    Mininet,
    TCLink,
    build_runtime_commands,
    configure_hosts,
    configure_switch,
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
    setLogLevel,
    HOSTS as S1_HOSTS,
)

DEFAULT_CONFIG = REPO_ROOT / "topo" / "config.yaml"

THRIFT_PORT_S1 = 9090
THRIFT_PORT_S2 = 9091

# Receivers on s2 — one dedicated receiver per sender
RECEIVER_HOSTS: tuple[dict, ...] = (
    {
        "name": "h5", "ip": "10.0.5.5/24", "mac": "00:00:00:00:05:05",
        "gateway_ip": "10.0.5.254", "gateway_mac": "00:aa:bb:00:05:fe",
        "switch_port": 1, "role": "receiver",
    },
    {
        "name": "h6", "ip": "10.0.6.6/24", "mac": "00:00:00:00:06:06",
        "gateway_ip": "10.0.6.254", "gateway_mac": "00:aa:bb:00:06:fe",
        "switch_port": 2, "role": "receiver",
    },
    {
        "name": "h7", "ip": "10.0.7.7/24", "mac": "00:00:00:00:07:07",
        "gateway_ip": "10.0.7.254", "gateway_mac": "00:aa:bb:00:07:fe",
        "switch_port": 3, "role": "receiver",
    },
    {
        "name": "h8", "ip": "10.0.8.8/24", "mac": "00:00:00:00:08:08",
        "gateway_ip": "10.0.8.254", "gateway_mac": "00:aa:bb:00:08:fe",
        "switch_port": 4, "role": "receiver",
    },
)

S1_S2_PORT = 5
S2_S1_PORT = 5


def load_config(path: str | Path) -> dict:
    with open(path) as handle:
        return yaml.safe_load(handle)


def build_net(
    json_path: Path,
    bw_bottleneck: int,
    bw_host: int,
    delay_ms: int,
    queue_size: int,
    priority_queues: int,
) -> tuple:
    net = Mininet(controller=None, link=TCLink)

    s1 = net.addSwitch(
        "s1", cls=BMv2Switch, sw_path=DEFAULT_SWITCH_PATH,
        json_path=str(json_path), thrift_port=THRIFT_PORT_S1,
        priority_queues=priority_queues,
    )
    s2 = net.addSwitch(
        "s2", cls=BMv2Switch, sw_path=DEFAULT_SWITCH_PATH,
        json_path=str(json_path), thrift_port=THRIFT_PORT_S2,
        priority_queues=priority_queues,
    )

    net.addLink(
        s1, s2, port1=S1_S2_PORT, port2=S2_S1_PORT, cls=TCLink,
        bw=bw_bottleneck, delay=f"{delay_ms}ms",
        max_queue_size=queue_size, use_htb=True,
    )

    for spec in [s for s in S1_HOSTS if s.role != "receiver"]:
        h = net.addHost(spec.name, ip=spec.cidr, mac=spec.mac, cls=Host)
        net.addLink(
            h, s1, port2=spec.switch_port, cls=TCLink,
            bw=bw_host, delay=f"{delay_ms}ms",
            max_queue_size=queue_size, use_htb=True,
        )

    for r in RECEIVER_HOSTS:
        h = net.addHost(r["name"], ip=r["ip"], mac=r["mac"], cls=Host)
        net.addLink(
            h, s2, port2=r["switch_port"], cls=TCLink,
            bw=bw_host, delay=f"{delay_ms}ms",
            max_queue_size=queue_size, use_htb=True,
        )

    return net, s1, s2


def run_fixed_experiment(
    net: Mininet,
    output_dir: str | Path,
    duration_s: int,
    l4s_bw_mbps: float,
    classic_bw_mbps: float,
) -> int:
    """Run one fixed-threshold L4S + Classic traffic experiment."""

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
    h3 = net.get("h3")

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
    classic = h3.popen(
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

    print(f"*** Dumbbell fixed experiment output: {output_dir}")
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

    failures = 0
    for host_name in ("h1", "h3"):
        output = net.get(host_name).cmd("ping -c 3 -W 1 10.0.5.5")
        print(f"--- {host_name} -> h5 ---")
        print(output.strip())
        if " 0% packet loss" not in output:
            failures += 1
    return 1 if failures else 0


def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the L4S dumbbell Mininet topology")
    parser.add_argument("--config",   default=str(DEFAULT_CONFIG), help="Path to config.yaml")
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
                        help="Run h1/h3 to h5 pings and exit")
    parser.add_argument("--run-fixed",   action="store_true",
                        help="Run one fixed-threshold traffic experiment and exit")
    parser.add_argument("--run-dynamic", action="store_true",
                        help="Run one dynamic-threshold traffic experiment and exit")
    parser.add_argument("--experiment-duration", type=int,   default=30)
    parser.add_argument("--l4s-bw",              type=float, default=4.0)
    parser.add_argument("--classic-bw",          type=float, default=4.0)
    parser.add_argument("--controller-interval", type=float, default=1.0)
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "results" / "dumbbell_fixed"))
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

    net, s1, s2 = build_net(
        json_path=json_path,
        bw_bottleneck=cfg["bottleneck_bw_mbps"],
        bw_host=cfg["sender_bw_mbps"],
        delay_ms=cfg["link_delay_ms"],
        queue_size=cfg["queue_size_pkts"],
        priority_queues=cfg["priority_queues"],
    )

    try:
        net.start()
        configure_hosts(net)

        for port in (THRIFT_PORT_S1, THRIFT_PORT_S2):
            if not wait_for_port("127.0.0.1", port):
                raise SystemExit(f"BMv2 thrift port {port} did not become ready")
            configure_switch(port, commands, args.cli_path)

        info("*** Dumbbell topology configured\n")
        info("*** s1: h1/h2 (L4S) h3/h4 (Classic)  s2: h5-h8 (receivers)\n")

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