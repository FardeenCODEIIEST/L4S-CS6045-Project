#!/usr/bin/env python3
"""
send_classic.py — Classic traffic sender (TCP Cubic)

Uses iperf3 with TCP Cubic (Linux default) as the Classic sender.
Packets are sent with ECT(0) (ECN-capable, classic) or Not-ECT,
both of which the BMv2 switch classifies into the Classic queue.

ECN is optionally enabled via sysctl so the Classic sender can
receive CE marks and respond with the standard TCP halving behavior
(50% cwnd reduction on any CE-marked packet) — the behavior that
L4S is explicitly designed to decouple from the L4S queue.

Usage:
    python3 send_classic.py --dst <ip> --port <port> --bandwidth <Mbps>
                            --duration <seconds> [--parallel <streams>]
                            [--ecn] [--output <file>] [--no-cleanup]
"""

import argparse
import subprocess
import sys
import os
import signal
import shutil

SYSCTL_CUBIC_ECN = {
    "net.ipv4.tcp_congestion_control": "cubic",
    "net.ipv4.tcp_ecn":                "1",
}
SYSCTL_CUBIC_NO_ECN = {
    "net.ipv4.tcp_congestion_control": "cubic",
    "net.ipv4.tcp_ecn":                "0",
}
CLASSIC_CONGESTION_CONTROL = "cubic"


def require_tool(name):
    if shutil.which(name) is None:
        print(f"[ERROR] Missing required command: {name}")
        print("        Install it on the Mininet host system, e.g. sudo apt install iperf3")
        sys.exit(1)


def require_tool(name):
    if shutil.which(name) is None:
        print(f"[ERROR] Missing required command: {name}")
        print("        Install it on the Mininet host system, e.g. sudo apt install iperf3")
        sys.exit(1)


def run(cmd, check=True, capture=False):
    return subprocess.run(
        cmd, check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True
    )


def apply_sysctl(settings, restore=False, saved=None):
    if restore and saved:
        for key, val in saved.items():
            run(["sysctl", "-w", f"{key}={val}"], check=False)
        print("[sysctl] Original settings restored")
        return

    original = {}
    for key, val in settings.items():
        try:
            result = run(["sysctl", "-n", key], capture=True)
            original[key] = result.stdout.strip()
            run(["sysctl", "-w", f"{key}={val}"])
            print(f"[sysctl] {key} = {val}  (was: {original[key]})")
        except subprocess.CalledProcessError as e:
            print(f"[WARN] sysctl {key} failed: {e}")
    return original


def run_iperf3(dst, port, bandwidth_mbps, duration_s, parallel, output_file):
    try:
        os.remove(output_file)
    except FileNotFoundError:
        pass
    cmd = [
        "iperf3",
        "-4",
        "-c", dst,
        "-p", str(port),
        "-b", f"{bandwidth_mbps}M",
        "-t", str(int(duration_s)),
        "-P", str(parallel),
        "-C", CLASSIC_CONGESTION_CONTROL,
        "-J",
        "--logfile", output_file,
    ]
    print(f"[iperf3/Classic] {' '.join(cmd)}")
    return subprocess.Popen(cmd)


def main():
    parser = argparse.ArgumentParser(
        description="Classic sender: TCP Cubic (with optional ECN)"
    )
    parser.add_argument("--dst",        required=True,          help="Destination IP")
    parser.add_argument("--port",       type=int,  default=5202, help="iperf3 server port")
    parser.add_argument("--bandwidth",  type=float, default=5.0, help="Target bandwidth in Mbps")
    parser.add_argument("--duration",   type=float, default=30.0, help="Duration in seconds")
    parser.add_argument("--parallel",   type=int,  default=1,    help="Parallel iperf3 streams")
    parser.add_argument("--ecn",        action="store_true",
                        help="Enable ECN (ECT(0)) so Classic sender reacts to CE marks via TCP halving")
    parser.add_argument("--output",     default="classic_iperf3.json",
                        help="iperf3 JSON output file")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Skip sysctl restore on exit")
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("[ERROR] Must run as root (required for sysctl)")
        sys.exit(1)
    require_tool("iperf3")

    settings = SYSCTL_CUBIC_ECN if args.ecn else SYSCTL_CUBIC_NO_ECN
    saved_sysctl = apply_sysctl(settings)

    proc = run_iperf3(args.dst, args.port, args.bandwidth,
                      args.duration, args.parallel, args.output)

    cleaned_up = False

    def cleanup(signum=None, frame=None):
        nonlocal cleaned_up
        if cleaned_up:
            return
        cleaned_up = True
        if proc.poll() is None:
            proc.terminate()
        if not args.no_cleanup:
            apply_sysctl(settings, restore=True, saved=saved_sysctl)

    signal.signal(signal.SIGINT,  cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        proc.wait()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
