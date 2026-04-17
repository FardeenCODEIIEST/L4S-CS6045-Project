#!/usr/bin/env python3
"""
send_l4s.py — L4S traffic sender (DCTCP + ECT(1) rewrite)

Uses iperf3 with DCTCP congestion control as the L4S sender.
Since DCTCP marks packets ECT(0) by default, an iptables mangle rule
rewrites outgoing TCP packets to ECT(1) so the BMv2 switch classifies
them into the L4S queue.

The DCTCP feedback loop remains intact because the switch marks CE
(0b11) on congested packets, and DCTCP responds to CE via the ECE/CWR
flags in TCP ACKs — independent of whether the original codepoint
was ECT(0) or ECT(1).

Usage:
    python3 send_l4s.py --dst <ip> --port <port> --bandwidth <Mbps>
                        --duration <seconds> [--parallel <streams>]
                        [--output <file>] [--no-cleanup]
"""

import argparse
import subprocess
import sys
import os
import signal


IPTABLES_ADD = [
    "iptables", "-t", "mangle", "-A", "POSTROUTING",
    "-p", "tcp",
    "-j", "TOS", "--set-tos", "0x01/0x03"
]
IPTABLES_DEL = [
    "iptables", "-t", "mangle", "-D", "POSTROUTING",
    "-p", "tcp",
    "-j", "TOS", "--set-tos", "0x01/0x03"
]

SYSCTL_DCTCP = {
    "net.ipv4.tcp_congestion_control": "dctcp",
    "net.ipv4.tcp_ecn":                "1",   # Enable ECN negotiation
    "net.ipv4.tcp_ecn_fallback":       "0",   # Do not fall back if peer lacks ECN
}


def run(cmd, check=True, capture=False):
    return subprocess.run(
        cmd, check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True
    )


def apply_sysctl(settings, restore=False, saved=None):
    """Apply sysctl settings; if restore=True, reinstate saved originals."""
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


def add_iptables_rule():
    try:
        run(IPTABLES_ADD)
        print("[iptables] ECT(0) -> ECT(1) rewrite rule added (POSTROUTING mangle)")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to add iptables rule: {e}")
        print("        Make sure you are running as root.")
        sys.exit(1)


def remove_iptables_rule():
    try:
        run(IPTABLES_DEL, check=False)
        print("[iptables] ECT(1) rewrite rule removed")
    except Exception:
        pass


def run_iperf3(dst, port, bandwidth_mbps, duration_s, parallel, output_file):
    cmd = [
        "iperf3",
        "-c", dst,
        "-p", str(port),
        "-b", f"{bandwidth_mbps}M",
        "-t", str(int(duration_s)),
        "-P", str(parallel),
        "-J",                      
        "--logfile", output_file,
    ]
    print(f"[iperf3/L4S] {' '.join(cmd)}")
    return subprocess.Popen(cmd)


def main():
    parser = argparse.ArgumentParser(
        description="L4S sender: DCTCP + iptables ECT(1) rewrite"
    )
    parser.add_argument("--dst",        required=True,          help="Destination IP")
    parser.add_argument("--port",       type=int,  default=5201, help="iperf3 server port")
    parser.add_argument("--bandwidth",  type=float, default=5.0, help="Target bandwidth in Mbps")
    parser.add_argument("--duration",   type=float, default=30.0, help="Duration in seconds")
    parser.add_argument("--parallel",   type=int,  default=1,    help="Parallel iperf3 streams")
    parser.add_argument("--output",     default="l4s_iperf3.json", help="iperf3 JSON output file")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Skip sysctl restore and iptables removal on exit")
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("[ERROR] Must run as root (required for sysctl and iptables)")
        sys.exit(1)

    saved_sysctl = apply_sysctl(SYSCTL_DCTCP)
    add_iptables_rule()

    proc = run_iperf3(args.dst, args.port, args.bandwidth,
                      args.duration, args.parallel, args.output)

    def cleanup(signum=None, frame=None):
        if proc.poll() is None:
            proc.terminate()
        if not args.no_cleanup:
            remove_iptables_rule()
            apply_sysctl(SYSCTL_DCTCP, restore=True, saved=saved_sysctl)
        sys.exit(0)

    signal.signal(signal.SIGINT,  cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        proc.wait()
    finally:
        cleanup()


if __name__ == "__main__":
    main()