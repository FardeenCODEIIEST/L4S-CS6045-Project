#!/usr/bin/env python3
"""
load_profile.py — Time-varying traffic load orchestrator (iperf3)

Launches send_l4s.py and send_classic.py as subprocesses according to
a named load profile, to stress-test threshold adaptation in the switch.

Profiles
--------
  steady  — Fixed rates for both classes throughout.
  ramp    — Linear increase from 10% to 100% of target in 5 steps.
  step    — Normal load for first half, 150% overload at midpoint.
  burst   — Alternating L4S and Classic bursts every quarter-duration.
  mixed   — Ramp-up → steady overload → L4S spike.

Usage:
    python3 load_profile.py --profile <n>
                            --dst <ip>
                            --bottleneck-bw <Mbps>
                            --l4s-fraction <0.0-1.0>
                            --duration <seconds>
                            [--l4s-port <port>] [--classic-port <port>]
                            [--parallel <streams>]
                            [--output-dir <dir>]
                            [--dry-run]
"""

import argparse
import subprocess
import sys
import os
import time
import signal

SEND_L4S_SCRIPT     = os.path.join(os.path.dirname(__file__), "send_l4s.py")
SEND_CLASSIC_SCRIPT = os.path.join(os.path.dirname(__file__), "send_classic.py")


def build_steady(bw, l4s_frac, duration):
    return [{"start": 0,
             "l4s_bw": bw * l4s_frac,
             "classic_bw": bw * (1 - l4s_frac),
             "duration": duration}]


def build_ramp(bw, l4s_frac, duration):
    steps = 5
    step_dur = duration / steps
    return [
        {"start": i * step_dur,
         "l4s_bw":     bw * l4s_frac     * (0.1 + 0.9 * i / (steps - 1)),
         "classic_bw": bw * (1-l4s_frac) * (0.1 + 0.9 * i / (steps - 1)),
         "duration": step_dur}
        for i in range(steps)
    ]


def build_step(bw, l4s_frac, duration):
    half = duration / 2
    return [
        {"start": 0,    "l4s_bw": bw * l4s_frac * 0.8,
         "classic_bw": bw * (1-l4s_frac) * 0.8, "duration": half},
        {"start": half, "l4s_bw": bw * l4s_frac * 1.5,
         "classic_bw": bw * (1-l4s_frac) * 1.5, "duration": half},
    ]


def build_burst(bw, l4s_frac, duration):
    seg = duration / 4
    bl, bc = bw * l4s_frac, bw * (1 - l4s_frac)
    return [
        {"start": 0,       "l4s_bw": bl * 2.0, "classic_bw": bc,       "duration": seg},
        {"start": seg,     "l4s_bw": bl,        "classic_bw": bc,       "duration": seg},
        {"start": seg * 2, "l4s_bw": bl,        "classic_bw": bc * 2.0, "duration": seg},
        {"start": seg * 3, "l4s_bw": bl,        "classic_bw": bc,       "duration": seg},
    ]


def build_mixed(bw, l4s_frac, duration):
    t1, t2 = duration * 0.3, duration * 0.7
    bl, bc = bw * l4s_frac, bw * (1 - l4s_frac)
    return [
        {"start": 0,  "l4s_bw": bl * 0.5, "classic_bw": bc * 0.5, "duration": t1},
        {"start": t1, "l4s_bw": bl * 1.3, "classic_bw": bc * 1.3, "duration": t2 - t1},
        {"start": t2, "l4s_bw": bl * 2.0, "classic_bw": bc * 0.8, "duration": duration - t2},
    ]


PROFILES = {
    "steady": build_steady,
    "ramp":   build_ramp,
    "step":   build_step,
    "burst":  build_burst,
    "mixed":  build_mixed,
}


def launch(script, dst, port, bw, duration, parallel, output_file, dry_run):
    cmd = [
        sys.executable, script,
        "--dst",       dst,
        "--port",      str(port),
        "--bandwidth", f"{bw:.4f}",
        "--duration",  f"{duration:.2f}",
        "--parallel",  str(parallel),
        "--output",    output_file,
        "--no-cleanup",
    ]
    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
        return None
    return subprocess.Popen(cmd)


def run_profile(stages, dst, l4s_port, classic_port, parallel, output_dir, dry_run):
    os.makedirs(output_dir, exist_ok=True)
    procs = []
    exp_start = time.time()

    print(f"[load_profile] Starting: {len(stages)} stage(s)")

    for i, s in enumerate(stages):
        delay = s["start"] - (time.time() - exp_start)
        if delay > 0:
            time.sleep(delay)

        print(f"[load_profile] Stage {i+1}/{len(stages)}  "
              f"L4S={s['l4s_bw']:.2f} Mbps  "
              f"Classic={s['classic_bw']:.2f} Mbps  "
              f"dur={s['duration']:.1f}s")

        if s["l4s_bw"] > 0:
            out = os.path.join(output_dir, f"stage{i+1}_l4s.json")
            p = launch(SEND_L4S_SCRIPT, dst, l4s_port,
                       s["l4s_bw"], s["duration"], parallel, out, dry_run)
            if p:
                procs.append(p)

        if s["classic_bw"] > 0:
            out = os.path.join(output_dir, f"stage{i+1}_classic.json")
            p = launch(SEND_CLASSIC_SCRIPT, dst, classic_port,
                       s["classic_bw"], s["duration"], parallel, out, dry_run)
            if p:
                procs.append(p)

    for p in procs:
        try:
            p.wait(timeout=120)
        except subprocess.TimeoutExpired:
            p.send_signal(signal.SIGINT)

    print("[load_profile] All stages complete.")


def main():
    parser = argparse.ArgumentParser(description="L4S load profile orchestrator (iperf3)")
    parser.add_argument("--profile",       choices=list(PROFILES.keys()), default="steady")
    parser.add_argument("--dst",           required=True,        help="Destination IP")
    parser.add_argument("--bottleneck-bw", type=float, default=10.0,
                        help="Bottleneck link bandwidth in Mbps")
    parser.add_argument("--l4s-fraction",  type=float, default=0.5,
                        help="Fraction of bandwidth for L4S (0.0–1.0)")
    parser.add_argument("--duration",      type=float, default=60.0)
    parser.add_argument("--parallel",      type=int,   default=1,
                        help="Parallel iperf3 streams per sender")
    parser.add_argument("--l4s-port",      type=int,   default=5201)
    parser.add_argument("--classic-port",  type=int,   default=5202)
    parser.add_argument("--output-dir",    default="results",
                        help="Directory for per-stage iperf3 JSON outputs")
    parser.add_argument("--dry-run",       action="store_true")
    args = parser.parse_args()

    if not (0.0 < args.l4s_fraction < 1.0):
        print("[ERROR] --l4s-fraction must be strictly between 0 and 1")
        sys.exit(1)

    stages = PROFILES[args.profile](
        args.bottleneck_bw, args.l4s_fraction, args.duration
    )

    print(f"[load_profile] profile={args.profile}  "
          f"BW={args.bottleneck_bw} Mbps  "
          f"L4S fraction={args.l4s_fraction}  "
          f"duration={args.duration}s")

    run_profile(stages, args.dst, args.l4s_port, args.classic_port,
                args.parallel, args.output_dir, args.dry_run)


if __name__ == "__main__":
    main()