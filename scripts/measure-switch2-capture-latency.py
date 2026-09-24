#!/usr/bin/env python3
"""Measure Switch capture latency (Test Input Devices).

Default: sample /dev/video0 directly (MS2109). Briefly stops ffplay if it
holds the device, then restarts scripts/switch2-capture-viewer.sh.

Optional --desktop samples DISPLAY=:1 (often black under gamescope).

Usage (pad linked, Switch on Test Input Devices):
  ./scripts/measure-switch2-capture-latency.py
  ./scripts/measure-switch2-capture-latency.py --manual
"""
from __future__ import annotations

import argparse
import os
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
WANT_TAP = RUNTIME / "nuxbt-want-tap"
WANT_TAP_HOLD = RUNTIME / "nuxbt-want-tap.hold"
WIDTH = int(os.environ.get("SWITCH2_LATENCY_W", "320"))
HEIGHT = int(os.environ.get("SWITCH2_LATENCY_H", "180"))
FPS = int(os.environ.get("SWITCH2_LATENCY_FPS", "60"))
THRESH = float(os.environ.get("SWITCH2_LATENCY_THRESH", "1.2"))
SETTLE_S = float(os.environ.get("SWITCH2_LATENCY_SETTLE", "0.45"))
CAPTURE_S = float(os.environ.get("SWITCH2_LATENCY_CAPTURE", "1.5"))
HOLD_S = float(os.environ.get("SWITCH2_LATENCY_HOLD", "0.55"))
DEV = os.environ.get("SWITCH2_CAPTURE_DEV", "/dev/video0")
CAP_W = os.environ.get("SWITCH2_CAPTURE_WIDTH", "1280")
CAP_H = os.environ.get("SWITCH2_CAPTURE_HEIGHT", "720")
FRAME = WIDTH * HEIGHT
VIEWER = ROOT / "scripts" / "switch2-capture-viewer.sh"


def mean_abs_diff(a: bytes, b: bytes) -> float:
    n = min(len(a), len(b), FRAME)
    if n <= 0:
        return 0.0
    total = 0
    count = 0
    for i in range(0, n, 2):
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


def wait_pad_press(path: str, timeout_s: float = 30.0) -> float | None:
    from evdev import InputDevice, ecodes

    dev = InputDevice(path)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        event = dev.read_one()
        if event is None:
            time.sleep(0.001)
            continue
        if event.type == ecodes.EV_KEY and event.value == 1:
            if event.code in (
                ecodes.BTN_SOUTH, ecodes.BTN_EAST, ecodes.BTN_WEST, ecodes.BTN_NORTH,
                ecodes.BTN_TL, ecodes.BTN_TR,
            ):
                return time.time()
    return None


def stop_ffplay() -> list[int]:
    pids = []
    try:
        out = subprocess.check_output(["pgrep", "-x", "ffplay"], text=True)
    except subprocess.CalledProcessError:
        return []
    for line in out.split():
        try:
            pid = int(line)
        except ValueError:
            continue
        # Only capture-card ffplay
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        if "v4l2" in cmdline or "/dev/video" in cmdline:
            pids.append(pid)
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    deadline = time.time() + 3
    while time.time() < deadline and any(Path(f"/proc/{p}").exists() for p in pids):
        time.sleep(0.05)
    for pid in pids:
        if Path(f"/proc/{pid}").exists():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    time.sleep(0.2)
    return pids


def start_viewer() -> None:
    if not VIEWER.is_file():
        return
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":1")
    subprocess.Popen(
        ["bash", str(VIEWER)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class FrameStream:
    def __init__(self, mode: str, display: str) -> None:
        self.mode = mode
        env = os.environ.copy()
        if mode == "desktop":
            env["DISPLAY"] = display
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-fflags", "nobuffer", "-flags", "low_delay",
                "-f", "x11grab", "-video_size", "1920x1080", "-framerate", str(FPS),
                "-i", display, "-an",
                "-vf", f"scale={WIDTH}:{HEIGHT},format=gray",
                "-f", "rawvideo", "-pix_fmt", "gray", "-",
            ]
        else:
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-fflags", "nobuffer", "-flags", "low_delay",
                "-f", "v4l2", "-input_format", "mjpeg",
                "-video_size", f"{CAP_W}x{CAP_H}", "-framerate", str(FPS),
                "-i", DEV, "-an",
                "-vf", f"scale={WIDTH}:{HEIGHT},format=gray",
                "-f", "rawvideo", "-pix_fmt", "gray", "-",
            ]
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
        )
        if self.proc.stdout is None:
            raise RuntimeError("ffmpeg stdout missing")
        # Warm-up / fail fast
        try:
            for _ in range(8):
                self.read_frame()
        except Exception:
            err = b""
            try:
                err = self.proc.stderr.read() if self.proc.stderr else b""
            except Exception:
                pass
            self.close()
            raise RuntimeError(f"ffmpeg warm-up failed: {err[:300]!r}")

    def read_frame(self) -> tuple[float, bytes]:
        assert self.proc.stdout is not None
        buf = b""
        while len(buf) < FRAME:
            chunk = self.proc.stdout.read(FRAME - len(buf))
            if not chunk:
                raise RuntimeError("ffmpeg pipe closed")
            buf += chunk
        return time.time(), buf

    def close(self) -> None:
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def fire_tap(hold_s: float = HOLD_S) -> float:
    WANT_TAP_HOLD.write_text(f"{hold_s}\n", encoding="utf-8")
    WANT_TAP.write_text("1\n", encoding="utf-8")
    return time.time()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manual", action="store_true")
    ap.add_argument("--trials", type=int, default=8)
    ap.add_argument("--desktop", action="store_true", help="sample DISPLAY=:1 (often black on gamescope)")
    ap.add_argument("--display", default=os.environ.get("SWITCH2_LATENCY_DISPLAY", ":1"))
    ap.add_argument("--thresh", type=float, default=THRESH)
    ap.add_argument("--keep-ffplay", action="store_true", help="do not reclaim /dev/video0")
    args = ap.parse_args()
    mode = "desktop" if args.desktop else "v4l2"
    thresh = args.thresh

    stopped: list[int] = []
    if mode == "v4l2" and not args.keep_ffplay:
        stopped = stop_ffplay()
        if stopped:
            print(f"Stopped ffplay {stopped} to open {DEV} (viewer restarts after).")

    print(f"Sampling {mode} ({WIDTH}x{HEIGHT} gray @ {FPS}fps) thresh MAD≥{thresh}")
    print("Pipeline under test: NUXBT/pad → Switch UI → HDMI → MS2109" + (
        " → ffplay → :1" if mode == "desktop" else " (capture card node)"
    ))
    print("Stay on Controllers → Test Input Devices.")

    try:
        stream = FrameStream(mode, args.display)
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        if stopped:
            start_viewer()
        return 2

    # Confirm we are not looking at black
    _, probe = stream.read_frame()
    mean = sum(probe) / len(probe)
    print(f"Probe frame mean luminance={mean:.1f} (0=black)")
    if mean < 1.0 and mode == "v4l2":
        print("WARN: capture looks black — is Switch HDMI live into the card?")

    results: list[float] = []
    pad = find_sunshine_pad() if args.manual else None
    if args.manual and not pad:
        stream.close()
        if stopped:
            start_viewer()
        print("FAIL: no Sunshine pad", file=sys.stderr)
        return 2

    try:
        for i in range(1, args.trials + 1):
            time.sleep(SETTLE_S)
            _, baseline = stream.read_frame()
            _, baseline = stream.read_frame()
            if args.manual:
                print(f"trial {i}/{args.trials}: press A/B on Odin…")
                t0 = wait_pad_press(pad, timeout_s=30.0)
                if t0 is None:
                    print(f"trial {i}: no press")
                    continue
            else:
                t0 = fire_tap(HOLD_S)
            deadline = t0 + CAPTURE_S
            ms = None
            peak = 0.0
            while time.time() < deadline:
                t_grab, frame = stream.read_frame()
                diff = mean_abs_diff(baseline, frame)
                peak = max(peak, diff)
                if diff >= thresh and t_grab >= t0:
                    ms = (t_grab - t0) * 1000.0
                    break
            if ms is None:
                print(f"trial {i}: no change (peak MAD={peak:.2f})")
                continue
            results.append(ms)
            print(f"trial {i}: {ms:.1f} ms (MAD={peak:.2f})")
    finally:
        stream.close()
        if stopped:
            print("Restarting capture viewer…")
            start_viewer()

    if not results:
        print("No successful trials.")
        return 1
    results.sort()
    mean = statistics.mean(results)
    med = statistics.median(results)
    p90 = results[max(0, int(round(0.9 * (len(results) - 1))))]
    print()
    print(f"=== latency to {mode} ===")
    print(
        f"n={len(results)}  mean={mean:.1f} ms  median={med:.1f} ms  "
        f"p90={p90:.1f} ms  min={results[0]:.1f}  max={results[-1]:.1f}"
    )
    if mode == "v4l2":
        print("Includes: BT/NUXBT + Switch UI + HDMI + MS2109 USB MJPEG dequeue.")
        print("Not included: ffplay present, gamescope, Sunshine encode, Wi-Fi, Moonlight decode.")
        print("Add ~1–2 frames for ffplay (~16–33ms) + ~1–3 frames encode/net/client (~16–50ms).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
