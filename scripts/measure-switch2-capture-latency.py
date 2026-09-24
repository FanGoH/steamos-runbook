#!/usr/bin/env python3
"""Measure Switch capture → desktop view latency (Test Input Devices).

Pipeline under test (host side):
  NUXBT tap / Sunshine pad → Switch UI → HDMI → MS2109 → ffplay (:1)
  → gamescope → (Sunshine encodes this for Moonlight)

ffplay holds /dev/video0 exclusively, so we sample DISPLAY=:1 (what the
desktop stream sees), not the V4L2 node directly.

Usage:
  ./scripts/measure-switch2-capture-latency.py          # auto-tap via nuxbt-want-tap
  ./scripts/measure-switch2-capture-latency.py --manual # wait for Odin A/B presses
"""
from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
WANT_TAP = RUNTIME / "nuxbt-want-tap"
DISPLAY = os.environ.get("SWITCH2_LATENCY_DISPLAY", ":1")
WIDTH = int(os.environ.get("SWITCH2_LATENCY_W", "320"))
HEIGHT = int(os.environ.get("SWITCH2_LATENCY_H", "180"))
FPS = int(os.environ.get("SWITCH2_LATENCY_FPS", "60"))
THRESH = float(os.environ.get("SWITCH2_LATENCY_THRESH", "4.5"))  # mean abs diff 0-255
SETTLE_S = float(os.environ.get("SWITCH2_LATENCY_SETTLE", "0.35"))
CAPTURE_S = float(os.environ.get("SWITCH2_LATENCY_CAPTURE", "1.25"))


def _x11_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    return env


def grab_gray_frame() -> bytes:
    """One greyscale frame from the desktop capture view (ffplay on :1)."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "x11grab", "-video_size", "1920x1080", "-framerate", "60",
        "-i", DISPLAY,
        "-frames:v", "1",
        "-vf", f"scale={WIDTH}:{HEIGHT},format=gray",
        "-f", "rawvideo", "-",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, env=_x11_env(), timeout=3
    )
    if proc.returncode != 0 or len(proc.stdout) < WIDTH * HEIGHT:
        raise RuntimeError(
            f"x11grab failed rc={proc.returncode}: {(proc.stderr or b'')[:200]!r}"
        )
    return proc.stdout[: WIDTH * HEIGHT]


def mean_abs_diff(a: bytes, b: bytes) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    total = 0
    # Sample every 4th pixel for speed (still ~14k samples at 320x180).
    step = 4
    count = 0
    for i in range(0, n, step):
        total += abs(a[i] - b[i])
        count += 1
    return total / max(count, 1)


def find_sunshine_pad() -> str | None:
    try:
        from evdev import InputDevice, list_devices
    except ImportError:
        return None
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        name = (dev.name or "").lower()
        if "sunshine" in name and "libvirtualhid" in name:
            return dev.path
    return None


def wait_pad_press(path: str, timeout_s: float = 20.0) -> float | None:
    from evdev import InputDevice, ecodes

    dev = InputDevice(path)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        event = dev.read_one()
        if event is None:
            time.sleep(0.002)
            continue
        if event.type == ecodes.EV_KEY and event.value == 1:
            # Any face / shoulder counts (Test Input Devices lights something).
            if event.code in (
                ecodes.BTN_SOUTH, ecodes.BTN_EAST, ecodes.BTN_WEST, ecodes.BTN_NORTH,
                ecodes.BTN_TL, ecodes.BTN_TR, ecodes.BTN_START, ecodes.BTN_SELECT,
            ):
                return time.time()
    return None


def measure_once(*, t0: float, baseline: bytes) -> float | None:
    """Return ms from t0 until :1 view differs from baseline."""
    deadline = t0 + CAPTURE_S
    while time.time() < deadline:
        t_grab = time.time()
        try:
            frame = grab_gray_frame()
        except RuntimeError:
            continue
        diff = mean_abs_diff(baseline, frame)
        if diff >= THRESH:
            return (t_grab - t0) * 1000.0
    return None


def auto_tap() -> float:
    WANT_TAP.write_text("1\n", encoding="utf-8")
    t0 = time.time()
    return t0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manual", action="store_true", help="wait for Odin/Sunshine pad press")
    ap.add_argument("--trials", type=int, default=8)
    ap.add_argument("--display", default=None)
    args = ap.parse_args()
    display = args.display or os.environ.get("SWITCH2_LATENCY_DISPLAY", ":1")

    print(f"Sampling desktop capture view on DISPLAY={display} ({WIDTH}x{HEIGHT} gray @ detect)")
    print("Pipeline: Switch HDMI → MS2109 → ffplay → gamescope :1 (Sunshine encodes this)")
    print(f"Change threshold MAD≥{THRESH}  settle={SETTLE_S}s  window={CAPTURE_S}s")

    def grab() -> bytes:
        env = os.environ.copy()
        env["DISPLAY"] = display
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "x11grab", "-video_size", "1920x1080", "-framerate", "60",
            "-i", display,
            "-frames:v", "1",
            "-vf", f"scale={WIDTH}:{HEIGHT},format=gray",
            "-f", "rawvideo", "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, env=env, timeout=3)
        if proc.returncode != 0 or len(proc.stdout) < WIDTH * HEIGHT:
            raise RuntimeError(
                f"x11grab failed rc={proc.returncode}: {(proc.stderr or b'')[:200]!r}"
            )
        return proc.stdout[: WIDTH * HEIGHT]

    # Warm up ffmpeg / x11grab
    try:
        baseline = grab()
    except RuntimeError as e:
        print(f"FAIL: cannot grab {display}: {e}", file=sys.stderr)
        return 2

    results: list[float] = []
    pad = find_sunshine_pad() if args.manual else None
    if args.manual and not pad:
        print("FAIL: no Sunshine pad for --manual", file=sys.stderr)
        return 2

    for i in range(1, args.trials + 1):
        time.sleep(SETTLE_S)
        try:
            baseline = grab()
        except RuntimeError as e:
            print(f"trial {i}: baseline grab failed: {e}")
            continue

        if args.manual:
            print(f"trial {i}/{args.trials}: press A/B on Odin now…")
            t0 = wait_pad_press(pad, timeout_s=30.0)
            if t0 is None:
                print(f"trial {i}: no pad press")
                continue
        else:
            WANT_TAP.write_text("1\n", encoding="utf-8")
            t0 = time.time()
            time.sleep(0.02)

        deadline = t0 + CAPTURE_S
        ms = None
        while time.time() < deadline:
            t_grab = time.time()
            try:
                frame = grab()
            except RuntimeError:
                continue
            if mean_abs_diff(baseline, frame) >= THRESH:
                ms = (t_grab - t0) * 1000.0
                break
        if ms is None:
            print(f"trial {i}: no visual change detected (stay on Test Input Devices)")
            continue
        results.append(ms)
        print(f"trial {i}: {ms:.1f} ms")

    if not results:
        print("No successful trials.")
        return 1

    results.sort()
    mean = statistics.mean(results)
    med = statistics.median(results)
    p90 = results[max(0, int(round(0.9 * (len(results) - 1))))]
    print()
    print("=== capture + desktop view latency (to gamescope :1) ===")
    print(
        f"n={len(results)}  mean={mean:.1f} ms  median={med:.1f} ms  "
        f"p90={p90:.1f} ms  min={results[0]:.1f}  max={results[-1]:.1f}"
    )
    print("Not included: Sunshine encode + network + Moonlight decode on the handheld.")
    print("Rough full-stream add: typically +1–3 frames encode/send (+16–50 ms) plus client decode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
