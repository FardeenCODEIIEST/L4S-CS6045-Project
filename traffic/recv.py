#!/usr/bin/env python3
"""
recv.py — Receiver: iperf3 server + parallel tcpdump ECN capture

Runs iperf3 in server mode on two ports (L4S and Classic) for throughput
measurement, and simultaneously runs tcpdump to capture all TCP traffic
for ECN and latency analysis by eval/parse_pcap.py.

iperf3 server handles the TCP connection and reports per-interval
throughput in JSON format. tcpdump captures the raw packets including
IP TOS (ECN) bits, which iperf3 does not report.

Usage:
    sudo python3 recv.py --l4s-port <port> --classic-port <port>
                         --output-dir <dir> --duration <seconds>
                         [--iface <iface>]
"""

import argparse
import subprocess
import sys
import os
import signal
import time
import threading
import shutil


def require_tool(name):
    if shutil.which(name) is None:
        print(f"[ERROR] Missing required command: {name}")
        print("        Install it on the Mininet host system, e.g. sudo apt install iperf3 tcpdump")
        sys.exit(1)


def run_iperf3_server(port, output_file, stop_event):
    cmd = [
        "iperf3", "-s",
        "-4",
        "-p", str(port),
        "-J",
        "--logfile", output_file,
        "--one-off",    # Handle one client at a time, then exit; we re-launch until stop_event is set
    ]
    # Re-launch after each client disconnects until stop_event is set
    while not stop_event.is_set():
        print(f"[iperf3 server] Listening on port {port}")
        proc = subprocess.Popen(cmd)
        while not stop_event.is_set() and proc.poll() is None:
            time.sleep(0.5)
        if proc.poll() is None:
            proc.terminate()


def run_tcpdump(iface, ports, pcap_file, stop_event):
    """
    Capture TCP traffic on given ports to a pcap file.
    """
    port_filter = " or ".join(f"port {p}" for p in ports)
    cmd = [
        "tcpdump", "-i", iface,
        "-w", pcap_file,
        "-s", "96",          # snap length: enough for IP+TCP headers, no payload 
        "--immediate-mode",
        f"tcp and ({port_filter})"
    ]
    print(f"[tcpdump] Capturing on {iface}: {port_filter} -> {pcap_file}")
    proc = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
    while not stop_event.is_set():
        time.sleep(0.5)
    proc.terminate()
    proc.wait()
    print(f"[tcpdump] Capture stopped. File: {pcap_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Receiver: iperf3 servers + tcpdump ECN capture"
    )
    parser.add_argument("--l4s-port",     type=int, default=5201,
                        help="iperf3 port for L4S traffic")
    parser.add_argument("--classic-port", type=int, default=5202,
                        help="iperf3 port for Classic traffic")
    parser.add_argument("--output-dir",   default="results",
                        help="Directory for iperf3 JSON logs and pcap file")
    parser.add_argument("--duration",     type=float, default=0,
                        help="Stop after N seconds (0 = run until Ctrl-C)")
    parser.add_argument("--iface",        default="eth0",
                        help="Interface for tcpdump capture")
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("[ERROR] Must run as root (required for tcpdump raw capture)")
        sys.exit(1)
    require_tool("iperf3")
    require_tool("tcpdump")

    os.makedirs(args.output_dir, exist_ok=True)

    l4s_json     = os.path.join(args.output_dir, "iperf3_l4s.json")
    classic_json = os.path.join(args.output_dir, "iperf3_classic.json")
    pcap_file    = os.path.join(args.output_dir, "capture.pcap")
    for output_file in (l4s_json, classic_json, pcap_file):
        try:
            os.remove(output_file)
        except FileNotFoundError:
            pass

    stop_event = threading.Event()

    threads = [
        threading.Thread(target=run_iperf3_server,
                         args=(args.l4s_port, l4s_json, stop_event), daemon=True),
        threading.Thread(target=run_iperf3_server,
                         args=(args.classic_port, classic_json, stop_event), daemon=True),
        threading.Thread(target=run_tcpdump,
                         args=(args.iface, [args.l4s_port, args.classic_port],
                               pcap_file, stop_event), daemon=True),
    ]

    for t in threads:
        t.start()

    print(f"[recv] L4S port={args.l4s_port}  Classic port={args.classic_port}")
    print(f"[recv] Outputs -> {args.output_dir}/  (Ctrl-C to stop)")

    def shutdown(signum=None, frame=None):
        print("\n[recv] Shutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        if args.duration > 0:
            time.sleep(args.duration)
            shutdown()
        else:
            while not stop_event.is_set():
                time.sleep(1)
    except KeyboardInterrupt:
        shutdown()

    for t in threads:
        t.join(timeout=3)

    print(f"[recv] Done. Files written:")
    print(f"  Throughput (L4S):     {l4s_json}")
    print(f"  Throughput (Classic): {classic_json}")
    print(f"  ECN capture:          {pcap_file}")


if __name__ == "__main__":
    main()
