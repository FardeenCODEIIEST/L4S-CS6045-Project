#!/usr/bin/env python3
"""
Mininet topology for the L4S BMv2 prototype.

The topology matches the proposal's single-bottleneck shape:

    h1/h2 L4S senders \
    h3/h4 Classic senders -> s1 BMv2 -> h5 receiver

BMv2 is used as a small router. Hosts are placed on separate /24 links and
given static ARP entries for their gateway IPs because the P4 program forwards
IPv4 packets but does not implement an ARP responder for router interfaces.
"""

from __future__ import annotations

import yaml
import argparse
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

try:
    from mininet.cli import CLI
    from mininet.link import TCLink
    from mininet.log import info, setLogLevel
    from mininet.net import Mininet
    from mininet.node import Host, Switch
    from mininet.topo import Topo
except ModuleNotFoundError:  # pragma: no cover - exercised only off Mininet hosts
    CLI = None
    TCLink = None
    Mininet = None
    Host = object
    Switch = object
    Topo = object
    info = None
    setLogLevel = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_P4_FILE = REPO_ROOT / "p4src" / "l4s.p4"
DEFAULT_JSON = REPO_ROOT / "build" / "l4s.json"
DEFAULT_SWITCH_PATH = "simple_switch"
DEFAULT_CLI_PATH = "simple_switch_CLI"
DEFAULT_CONFIG = REPO_ROOT / "topo" / "config.yaml"


@dataclass(frozen=True)
class HostSpec:
    name: str
    ip: str
    cidr: str
    mac: str
    gateway_ip: str
    gateway_mac: str
    switch_port: int
    role: str


HOSTS: tuple[HostSpec, ...] = (
    HostSpec(
        name="h1",
        ip="10.0.1.1",
        cidr="10.0.1.1/24",
        mac="00:00:00:00:01:01",
        gateway_ip="10.0.1.254",
        gateway_mac="00:aa:bb:00:01:fe",
        switch_port=1,
        role="l4s",
    ),
    HostSpec(
        name="h2",
        ip="10.0.1.2",
        cidr="10.0.1.2/24",
        mac="00:00:00:00:01:02",
        gateway_ip="10.0.1.254",
        gateway_mac="00:aa:bb:00:01:fe",
        switch_port=2,
        role="l4s",
    ),
    HostSpec(
        name="h3",
        ip="10.0.2.3",
        cidr="10.0.2.3/24",
        mac="00:00:00:00:02:03",
        gateway_ip="10.0.2.254",
        gateway_mac="00:aa:bb:00:02:fe",
        switch_port=3,
        role="classic",
    ),
    HostSpec(
        name="h4",
        ip="10.0.2.4",
        cidr="10.0.2.4/24",
        mac="00:00:00:00:02:04",
        gateway_ip="10.0.2.254",
        gateway_mac="00:aa:bb:00:02:fe",
        switch_port=4,
        role="classic",
    ),
    HostSpec(
        name="h5",
        ip="10.0.5.5",
        cidr="10.0.5.5/24",
        mac="00:00:00:00:05:05",
        gateway_ip="10.0.5.254",
        gateway_mac="00:aa:bb:00:05:fe",
        switch_port=5,
        role="receiver",
    ),
)


class BMv2Switch(Switch):
    """Mininet switch node backed by BMv2 simple_switch."""

    def __init__(
        self,
        name: str,
        sw_path: str = DEFAULT_SWITCH_PATH,
        json_path: str | Path = DEFAULT_JSON,
        thrift_port: int = 9090,
        priority_queues: int = 2,
        log_file: str | Path | None = None,
        device_id: int = 0,
        **kwargs,
    ):
        kwargs.setdefault("inNamespace", False)
        super().__init__(name, **kwargs)
        self.sw_path = str(sw_path)
        self.json_path = str(json_path)
        self.thrift_port = int(thrift_port)
        self.priority_queues = int(priority_queues)
        self.device_id = int(device_id)
        self.log_file = str(log_file or REPO_ROOT / "build" / f"{name}.log")
        self.simple_switch_pid: int | None = None
        self.notifications_addr: str | None = None

    def start(self, controllers):  # noqa: D401 - Mininet API signature
        intf_args = []
        for intf in self.intfList():
            if not intf.name.startswith(f"{self.name}-eth"):
                continue
            port = self.ports[intf]
            intf_args.extend(["-i", f"{port}@{intf.name}"])

        self.notifications_addr = build_notifications_addr(self.device_id, self.thrift_port)
        cleanup_ipc_addr(self.notifications_addr)
        Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
        cmd = build_simple_switch_command(
            sw_path=self.sw_path,
            json_path=self.json_path,
            thrift_port=self.thrift_port,
            priority_queues=self.priority_queues,
            device_id=self.device_id,
            interface_args=intf_args,
            notifications_addr=self.notifications_addr,
        )
        cmd_str = " ".join(shlex.quote(part) for part in cmd)
        pid_text = self.cmd(f"{cmd_str} > {shlex.quote(self.log_file)} 2>&1 & echo $!").strip()
        try:
            self.simple_switch_pid = int(pid_text.splitlines()[-1])
        except (IndexError, ValueError):
            self.simple_switch_pid = None
        info(f"*** Started {self.name} with PID {self.simple_switch_pid}\n")

    def stop(self, deleteIntfs=True):
        if self.simple_switch_pid is not None:
            self.cmd(f"kill {self.simple_switch_pid}")
            self.simple_switch_pid = None
        if self.notifications_addr:
            cleanup_ipc_addr(self.notifications_addr)
            self.notifications_addr = None
        super().stop(deleteIntfs=deleteIntfs)


class L4SBottleneckTopo(Topo):
    """Five-host single-switch bottleneck topology."""

    def build(
        self,
        sender_bw_mbps: int = 100,
        bottleneck_bw_mbps: int = 10,
        link_delay_ms: int = 5,
        queue_size_pkts: int = 100,
        sw_path: str = DEFAULT_SWITCH_PATH,
        json_path: str | Path = DEFAULT_JSON,
        thrift_port: int = 9090,
        priority_queues: int = 2,
    ):
        switch = self.addSwitch(
            "s1",
            cls=BMv2Switch,
            sw_path=sw_path,
            json_path=str(json_path),
            thrift_port=thrift_port,
            priority_queues=priority_queues,
        )

        for spec in HOSTS:
            host = self.addHost(spec.name, ip=spec.cidr, mac=spec.mac, cls=Host)
            bw = bottleneck_bw_mbps if spec.role == "receiver" else sender_bw_mbps
            self.addLink(
                host,
                switch,
                port2=spec.switch_port,
                cls=TCLink,
                bw=bw,
                delay=f"{link_delay_ms}ms",
                max_queue_size=queue_size_pkts,
                use_htb=True,
            )


def build_simple_switch_command(
    sw_path: str,
    json_path: str | Path,
    thrift_port: int,
    priority_queues: int,
    device_id: int = 0,
    interface_args: Sequence[str] = (),
    notifications_addr: str | None = None,
) -> list[str]:
    """Build a simple_switch command with target options after '--'."""

    command = [
        sw_path,
        "--device-id",
        str(device_id),
        "--thrift-port",
        str(thrift_port),
    ]
    if notifications_addr:
        command.extend(["--notifications-addr", notifications_addr])
    command.extend(
        [
            *interface_args,
            str(json_path),
            "--",
            "--priority-queues",
            str(priority_queues),
        ]
    )
    return command


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)

def build_notifications_addr(device_id: int, thrift_port: int) -> str:
    """Return a per-run BMv2 notifications socket address.

    BMv2's default notification address is keyed only by device id, so rapid
    consecutive Mininet runs can collide with a stale socket and prevent thrift
    from starting.
    """

    unique = f"{os.getpid()}-{int(time.time() * 1000)}"
    return f"ipc:///tmp/l4s-bmv2-{device_id}-{thrift_port}-{unique}-notifications.ipc"


def cleanup_ipc_addr(address: str) -> None:
    """Remove a filesystem-backed IPC socket if BMv2 left one behind."""

    if not address.startswith("ipc://"):
        return
    path = Path(address.removeprefix("ipc://"))
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def build_runtime_commands(
    hosts: Sequence[HostSpec] = HOSTS,
    l4s_threshold: int = 30,
    classic_threshold: int = 80,
    classic_protection_threshold: int = 16,
    bmv2_queue_rate_pps: int | None = None,
    bmv2_queue_depth_pkts: int | None = None,
    bmv2_queue_port: int | None = None,
) -> list[str]:
    """Return simple_switch_CLI commands for forwarding and registers."""

    commands: list[str] = []
    if bmv2_queue_port is None:
        bmv2_queue_port = next(spec.switch_port for spec in hosts if spec.role == "receiver")

    if bmv2_queue_rate_pps and bmv2_queue_rate_pps > 0:
        commands.append(f"set_queue_rate {bmv2_queue_rate_pps} {bmv2_queue_port}")
    if bmv2_queue_depth_pkts and bmv2_queue_depth_pkts > 0:
        commands.append(f"set_queue_depth {bmv2_queue_depth_pkts} {bmv2_queue_port}")

    for spec in hosts:
        commands.append(
            "table_add IngressImpl.ipv4_lpm IngressImpl.set_nhop "
            f"{spec.ip}/32 => {spec.mac} {spec.gateway_mac} {spec.switch_port}"
        )
        commands.append(
            "table_add IngressImpl.l2_forward IngressImpl.set_egress "
            f"{spec.mac} => {spec.switch_port}"
        )

    commands.extend(
        [
            f"register_write reg_l4s_threshold 0 {l4s_threshold}",
            f"register_write reg_classic_threshold 0 {classic_threshold}",
            "register_write reg_classic_protection_budget 0 0",
            f"register_write reg_classic_protection_threshold 0 {classic_protection_threshold}",
            "register_write reg_l4s_qdepth 0 0",
            "register_write reg_classic_qdepth 0 0",
            "register_write reg_l4s_delay 0 0",
            "register_write reg_classic_delay 0 0",
            "register_write reg_l4s_growth 0 0",
            "register_write reg_classic_growth 0 0",
            "register_write reg_l4s_prev_enq_qdepth 0 0",
            "register_write reg_classic_prev_enq_qdepth 0 0",
        ]
    )
    return commands


def configure_hosts(net: Mininet, hosts: Sequence[HostSpec] = HOSTS) -> None:
    """Install default routes and static gateway ARP entries."""

    for spec in hosts:
        host = net.get(spec.name)
        host.cmd(f"ip route replace default via {spec.gateway_ip} dev {spec.name}-eth0")
        host.cmd(f"arp -s {spec.gateway_ip} {spec.gateway_mac}")
        disable_offloads(host, f"{spec.name}-eth0")
        if spec.role == "l4s":
            host.cmd('sysctl -w net.ipv4.tcp_allowed_congestion_control="reno cubic dctcp"')

    switch = net.get("s1")
    for spec in hosts:
        disable_offloads(switch, f"s1-eth{spec.switch_port}")


def disable_offloads(node, iface: str) -> None:
    """Disable NIC offloads that leave bad checksums in packets BMv2 forwards."""

    if shutil.which("ethtool") is None:
        print("[WARN] ethtool not found; TCP checksums may be invalid through BMv2")
        return
    node.cmd(
        "ethtool -K "
        f"{iface} "
        "tx off rx off sg off tso off gso off gro off lro off "
        "2>/dev/null || true"
    )


def configure_switch(
    thrift_port: int,
    commands: Iterable[str],
    cli_path: str = DEFAULT_CLI_PATH,
) -> subprocess.CompletedProcess:
    """Apply runtime commands through simple_switch_CLI."""

    payload = "\n".join(commands) + "\n"
    return subprocess.run(
        [cli_path, "--thrift-port", str(thrift_port)],
        input=payload,
        text=True,
        check=True,
        capture_output=True,
    )


def run_smoke_tests(net: Mininet) -> int:
    """Ping the receiver from one L4S and one Classic sender."""

    receiver_ip = next(spec.ip for spec in HOSTS if spec.name == "h5")
    failures = 0
    for host_name in ("h1", "h3"):
        output = net.get(host_name).cmd(f"ping -c 3 -W 1 {receiver_ip}")
        print(f"--- {host_name} -> h5 ---")
        print(output.strip())
        if " 0% packet loss" not in output:
            failures += 1
    return 1 if failures else 0


def _wait_process(name: str, proc: subprocess.Popen, timeout_s: float) -> tuple[int, str]:
    try:
        output, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.terminate()
        output, _ = proc.communicate(timeout=5)
        return 124, f"[{name}] timed out\n{output or ''}"
    return proc.returncode, output or ""


def restore_output_ownership(output_dir: Path) -> None:
    """Give result files back to the user who invoked sudo, when available."""

    sudo_uid = os.environ.get("SUDO_UID")
    sudo_gid = os.environ.get("SUDO_GID")
    if not sudo_uid or not sudo_gid:
        return

    uid = int(sudo_uid)
    gid = int(sudo_gid)
    for path in [output_dir, *output_dir.rglob("*")]:
        try:
            os.chown(path, uid, gid)
        except PermissionError:
            pass


def wait_for_host_listen(host: Host, ports: Sequence[int], timeout_s: float = 5.0) -> bool:
    """Wait until all TCP ports are listening inside a Mininet host namespace."""

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        listening = host.cmd("ss -H -ltn").splitlines()
        ready = True
        for port in ports:
            if not any(f":{port} " in line or line.rstrip().endswith(f":{port}") for line in listening):
                ready = False
                break
        if ready:
            return True
        time.sleep(0.2)
    print("--- h5 listening sockets ---")
    print(host.cmd("ss -H -ltn").strip())
    return False


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
        "l4s_server": output_dir / "iperf3_l4s.json",
        "classic_server": output_dir / "iperf3_classic.json",
        "l4s_client": output_dir / "l4s_client.json",
        "classic_client": output_dir / "classic_client.json",
        "pcap": output_dir / "capture.pcap",
    }
    for output_file in output_files.values():
        try:
            output_file.unlink()
        except FileNotFoundError:
            pass

    l4s_script = REPO_ROOT / "traffic" / "send_l4s.py"
    classic_script = REPO_ROOT / "traffic" / "send_classic.py"

    h5 = net.get("h5")
    h1 = net.get("h1")
    h3 = net.get("h3")

    tcpdump = h5.popen(
        [
            "tcpdump",
            "-i",
            "h5-eth0",
            "-w",
            str(output_files["pcap"]),
            "-s",
            "96",
            "--immediate-mode",
            "tcp and (port 5201 or port 5202)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    l4s_server = h5.popen(
        [
            "iperf3",
            "-s",
            "-4",
            "-p",
            "5201",
            "-1",
            "-J",
            "--logfile",
            str(output_files["l4s_server"]),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    classic_server = h5.popen(
        [
            "iperf3",
            "-s",
            "-4",
            "-p",
            "5202",
            "-1",
            "-J",
            "--logfile",
            str(output_files["classic_server"]),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if not wait_for_host_listen(h5, [5201, 5202], timeout_s=5.0):
        for proc in (l4s_server, classic_server, tcpdump):
            proc.terminate()
        return 1

    l4s = h1.popen(
        [
            "python3",
            str(l4s_script),
            "--dst",
            "10.0.5.5",
            "--port",
            "5201",
            "--bandwidth",
            str(l4s_bw_mbps),
            "--duration",
            str(duration_s),
            "--output",
            str(output_files["l4s_client"]),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    classic = h3.popen(
        [
            "python3",
            str(classic_script),
            "--dst",
            "10.0.5.5",
            "--port",
            "5202",
            "--bandwidth",
            str(classic_bw_mbps),
            "--duration",
            str(duration_s),
            "--ecn",
            "--output",
            str(output_files["classic_client"]),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
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

    print(f"*** Fixed experiment output: {output_dir}")
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
            "python3",
            str(controller_script),
            "--thrift-port",
            str(thrift_port),
            "--cli-path",
            cli_path,
            "--interval",
            str(controller_interval_s),
            "--log",
            str(controller_log),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
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


def wait_for_port(host: str, port: int, timeout_s: float = 5.0) -> bool:
    """Wait for BMv2 thrift to accept connections."""

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def compile_p4(
    p4_file: str | Path = DEFAULT_P4_FILE,
    json_path: str | Path = DEFAULT_JSON,
    p4c: str = "p4c-bm2-ss",
) -> Path:
    """Compile the P4 program to BMv2 JSON if needed."""

    p4_file = Path(p4_file)
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    if json_path.exists() and json_path.stat().st_mtime >= p4_file.stat().st_mtime:
        return json_path

    subprocess.run([p4c, str(p4_file), "-o", str(json_path)], check=True)
    return json_path


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"missing required tool: {name}")


def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the L4S BMv2 Mininet topology")
    parser.add_argument("--p4-file", default=str(DEFAULT_P4_FILE))
    parser.add_argument("--json", default=str(DEFAULT_JSON), help="BMv2 JSON path")
    parser.add_argument("--switch", default=DEFAULT_SWITCH_PATH, help="simple_switch path")
    parser.add_argument("--cli-path", default=DEFAULT_CLI_PATH, help="simple_switch_CLI path")
    parser.add_argument("--thrift-port", type=int, default=9090)
    parser.add_argument("--priority-queues", type=int, default=2)
    parser.add_argument("--sender-bw", type=int, default=100, help="sender links in Mbps")
    parser.add_argument("--bottleneck-bw", type=int, default=10, help="receiver link in Mbps")
    parser.add_argument("--delay-ms", type=int, default=5)
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                    help="Path to config.yaml")
    parser.add_argument("--queue-size", type=int, default=100)
    parser.add_argument(
        "--bmv2-queue-rate-pps",
        type=int,
        default=800,
        help="BMv2 packet-per-second cap on the receiver egress port; 0 disables",
    )
    parser.add_argument(
        "--bmv2-queue-depth",
        type=int,
        default=100,
        help="BMv2 receiver egress queue depth in packets; 0 leaves BMv2 default",
    )
    parser.add_argument("--l4s-threshold", type=int, default=30)
    parser.add_argument("--classic-threshold", type=int, default=80)
    parser.add_argument("--classic-protection-threshold", type=int, default=16)
    parser.add_argument("--smoke-test", action="store_true", help="run h1/h3 to h5 pings and exit")
    parser.add_argument("--run-fixed", action="store_true", help="run one fixed-threshold traffic experiment and exit")
    parser.add_argument("--run-dynamic", action="store_true", help="run one dynamic-threshold traffic experiment and exit")
    parser.add_argument("--experiment-duration", type=int, default=30)
    parser.add_argument("--l4s-bw", type=float, default=4.0)
    parser.add_argument("--classic-bw", type=float, default=4.0)
    parser.add_argument("--controller-interval", type=float, default=1.0)
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "results" / "fixed"))
    parser.add_argument("--no-cli", action="store_true", help="start and configure, then exit")
    parser.add_argument("--dry-run", action="store_true", help="print runtime commands only")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_arg_parser()
    args = parser.parse_args(argv)

    cfg = load_config(args.config)

    cfg = load_config(args.config)

    commands = build_runtime_commands(
        l4s_threshold=cfg['l4s_threshold'],
        classic_threshold=cfg['classic_threshold'],
        classic_protection_threshold=cfg['classic_protection_threshold'],
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
    topo = L4SBottleneckTopo(
        sender_bw_mbps=cfg['sender_bw_mbps'],
        bottleneck_bw_mbps=cfg['bottleneck_bw_mbps'],
        link_delay_ms=cfg['link_delay_ms'],
        queue_size_pkts=cfg['queue_size_pkts'],
        sw_path=args.switch,
        json_path=json_path,
        thrift_port=cfg['thrift_port'],
        priority_queues=cfg['priority_queues'],
    )
    net = Mininet(topo=topo, link=TCLink, controller=None, autoSetMacs=False)

    try:
        net.start()
        configure_hosts(net)
        if not wait_for_port("127.0.0.1", args.thrift_port):
            raise SystemExit(f"BMv2 thrift port {args.thrift_port} did not become ready")
        configure_switch(args.thrift_port, commands, args.cli_path)
        info("*** Topology is configured\n")
        info("*** Sender hosts: h1/h2 L4S, h3/h4 Classic; receiver: h5\n")
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
                thrift_port=args.thrift_port,
                cli_path=args.cli_path,
                controller_interval_s=args.controller_interval,
            )
        if not args.no_cli:
            CLI(net)
    finally:
        net.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
