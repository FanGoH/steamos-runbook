#!/usr/bin/env python3
"""Measure Switch capture latency (Test Input Devices).

Default: sample /dev/video0 directly (MS2109). Briefly stops ffplay if it
holds the device, then restarts scripts/switch2-capture-viewer.sh.

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
# Global MAD of a small button highlight is tiny (~0.2–0.4). Default was 1.2 → misses.
THRESH = float(os.environ.get("SWITCH2_LATENCY_THRESH", "0.15"))
SETTLE_S = float(os.environ.get("SWITCH2_LATENCY_SETTLE", "0.45"))
CAPTURE_S = float(os.environ.get("SWITCH2_LATENCY_CAPTURE", "1.8"))
HOLD_S = float(os.environ.get("SWITCH2_LATENCY_HOLD", "0.7"))
DEV = os.environ.get("SWITCH2_CAPTURE_DEV", "")
CAP_W = os.environ.get("SWITCH2_CAPTURE_WIDTH", "1280")
CAP_H = os.environ.get("SWITCH2_CAPTURE_HEIGHT", "720")
USB_VID = os.environ.get("SWITCH2_CAPTURE_USB_VID", "534d")
USB_PID = os.environ.get("SWITCH2_CAPTURE_USB_PID", "2109")
FRAME = WIDTH * HEIGHT
TILE = 40  # px; max-tile MAD catches small Test Input highlights
VIEWER = ROOT / "scripts" / "switch2-capture-viewer.sh"


def find_capture_dev() -> str:
    """Resolve MS2109 capture node (number can flip video0↔video1 after reclaim)."""
    if DEV:
        return DEV
    import re

    for vd in sorted(Path("/sys/class/video4linux").glob("video*")):
        resolved = vd.resolve()
        parent = resolved
        vid = pid = ""
        while parent != parent.parent:
            idv = parent / "idVendor"
            idp = parent / "idProduct"
            if idv.is_file() and idp.is_file():
                vid = idv.read_text().strip()
                pid = idp.read_text().strip()
                break
            parent = parent.parent
        if vid != USB_VID or pid != USB_PID:
            continue
        node = f"/dev/{vd.name}"
        try:
            out = subprocess.check_output(
                ["v4l2-ctl", "-d", node, "--list-formats-ext"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
        if re.search(r"MJPG|Motion-JPEG|YUYV", out):
            return node
    raise RuntimeError(
        f"MacroSilicon capture card {USB_VID}:{USB_PID} not found under /dev/video*"
    )


def wait_capture_dev(timeout_s: float = 5.0) -> str:
    deadline = time.time() + timeout_s
    last_err = "not found"
    while time.time() < deadline:
        try:
            return find_capture_dev()
        except RuntimeError as e:
            last_err = str(e)
            time.sleep(0.15)
    raise RuntimeError(last_err)


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


def max_tile_mad(a: bytes, b: bytes, tile: int = TILE) -> float:
    """Largest mean-abs-diff among tile×tile blocks (highlights are local)."""
    if len(a) < FRAME or len(b) < FRAME:
        return mean_abs_diff(a, b)
    best = 0.0
    for y0 in range(0, HEIGHT - tile + 1, tile):
        for x0 in range(0, WIDTH - tile + 1, tile):
            total = 0
            count = 0
            for y in range(y0, y0 + tile):
                row = y * WIDTH
                for x in range(x0, x0 + tile, 2):
                    i = row + x
                    total += abs(a[i] - b[i])
                    count += 1
            if count:
                best = max(best, total / count)
    return best


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
    time.sleep(0.25)
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
    def __init__(self, mode: str, display: str, dev: str) -> None:
        self.mode = mode
        self.display = display
        self.dev = dev
        self.proc: subprocess.Popen | None = None
        self._open()

    def _cmd(self) -> list[str]:
        if self.mode == "desktop":
            return [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-fflags", "nobuffer", "-flags", "low_delay",
                "-f", "x11grab", "-video_size", "1920x1080", "-framerate", str(FPS),
                "-i", self.display, "-an",
                "-vf", f"scale={WIDTH}:{HEIGHT},format=gray",
                "-f", "rawvideo", "-pix_fmt", "gray", "-",
            ]
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-fflags", "nobuffer", "-flags", "low_delay",
            "-use_wallclock_as_timestamps", "1",
            "-f", "v4l2", "-input_format", "mjpeg",
            "-video_size", f"{CAP_W}x{CAP_H}", "-framerate", str(FPS),
            "-i", self.dev, "-an",
            "-vsync", "0",
            "-vf", f"scale={WIDTH}:{HEIGHT},format=gray",
            "-f", "rawvideo", "-pix_fmt", "gray", "-",
        ]

    def _open(self) -> None:
        self.close()
        env = os.environ.copy()
        if self.mode == "desktop":
            env["DISPLAY"] = self.display
        self.proc = subprocess.Popen(
            self._cmd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        if self.proc.stdout is None:
            raise RuntimeError("ffmpeg stdout missing")
        try:
            for _ in range(8):
                self.read_frame()
        except Exception:
            err = b""
            try:
                if self.proc.stderr:
                    err = self.proc.stderr.read()
            except Exception:
                pass
            self.close()
            raise RuntimeError(f"ffmpeg warm-up failed: {err[:300]!r}")

    def read_frame(self) -> tuple[float, bytes]:
        if self.proc is None or self.proc.stdout is None:
            raise RuntimeError("ffmpeg not running")
        buf = b""
        while len(buf) < FRAME:
            chunk = self.proc.stdout.read(FRAME - len(buf))
            if not chunk:
                raise RuntimeError("ffmpeg pipe closed")
            buf += chunk
        return time.time(), buf

    def read_frame_reopen(self) -> tuple[float, bytes]:
        try:
            return self.read_frame()
        except RuntimeError:
            print("ffmpeg pipe closed — reopening capture…", flush=True)
            time.sleep(0.3)
            if self.mode == "v4l2":
                try:
                    self.dev = wait_capture_dev(4.0)
                except RuntimeError:
                    pass
            self._open()
            return self.read_frame()

    def close(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None


def fire_tap(hold_s: float = HOLD_S) -> float:
    WANT_TAP_HOLD.write_text(f"{hold_s}\n", encoding="utf-8")
    WANT_TAP.write_text("1\n", encoding="utf-8")
    return time.time()


def noise_floor(stream: FrameStream, samples: int = 20) -> float:
    """Peak tile-MAD between consecutive idle frames (compression noise)."""
    peak = 0.0
    _, prev = stream.read_frame_reopen()
    for _ in range(samples):
        _, cur = stream.read_frame_reopen()
        peak = max(peak, max_tile_mad(prev, cur), mean_abs_diff(prev, cur))
        prev = cur
    return peak


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manual", action="store_true")
    ap.add_argument("--trials", type=int, default=8)
    ap.add_argument("--desktop", action="store_true", help="sample DISPLAY=:1 (often black on gamescope)")
    ap.add_argument("--display", default=os.environ.get("SWITCH2_LATENCY_DISPLAY", ":1"))
    ap.add_argument("--thresh", type=float, default=None, help="override detect threshold (tile MAD)")
    ap.add_argument("--keep-ffplay", action="store_true", help="do not reclaim /dev/video0")
    args = ap.parse_args()
    mode = "desktop" if args.desktop else "v4l2"

    stopped: list[int] = []
    cap_dev = ""
    if mode == "v4l2" and not args.keep_ffplay:
        stopped = stop_ffplay()
        if stopped:
            print(f"Stopped ffplay {stopped} to open capture device (viewer restarts after).")
        try:
            cap_dev = wait_capture_dev(5.0)
        except RuntimeError as e:
            print(f"FAIL: {e}", file=sys.stderr)
            if stopped:
                start_viewer()
            return 2
        print(f"Using capture device {cap_dev}")
    elif mode == "v4l2":
        try:
            cap_dev = find_capture_dev()
        except RuntimeError as e:
            print(f"FAIL: {e}", file=sys.stderr)
            return 2
        print(f"Using capture device {cap_dev}")

    print(f"Sampling {mode} ({WIDTH}x{HEIGHT} gray @ {FPS}fps)")
    print("Pipeline: NUXBT/pad → Switch UI → HDMI → MS2109" + (
        " → ffplay → :1" if mode == "desktop" else " (capture card node)"
    ))
    print("Stay on Controllers → Test Input Devices.")

    stream: FrameStream | None = None
    try:
        stream = FrameStream(mode, args.display, cap_dev or ":1")
        _, probe = stream.read_frame_reopen()
        mean = sum(probe) / len(probe)
        print(f"Probe frame mean luminance={mean:.1f} (0=black)")
        if mean < 1.0 and mode == "v4l2":
            print("WARN: capture looks black — is Switch HDMI live into the card?")

        floor = noise_floor(stream)
        if args.thresh is not None:
            thresh = args.thresh
        else:
            # Above idle noise; your earlier run peaked ~0.28 on a real tap.
            thresh = max(THRESH, floor * 3.0 + 0.08)
        print(f"Noise floor tile-MAD={floor:.3f}  detect thresh={thresh:.3f}  hold={HOLD_S}s")

        results: list[float] = []
        pad = find_sunshine_pad() if args.manual else None
        if args.manual and not pad:
            print("FAIL: no Sunshine pad", file=sys.stderr)
            return 2

        for i in range(1, args.trials + 1):
            try:
                # Wait until the picture is quiet again (previous A highlight gone).
                quiet_needed = 8
                quiet = 0
                _, baseline = stream.read_frame_reopen()
                settle_deadline = time.time() + 3.0
                while time.time() < settle_deadline and quiet < quiet_needed:
                    _, frame = stream.read_frame_reopen()
                    if max_tile_mad(baseline, frame) <= max(floor * 2, 0.05):
                        quiet += 1
                        baseline = frame
                    else:
                        quiet = 0
                        baseline = frame
                time.sleep(0.05)
                _, baseline = stream.read_frame_reopen()
                _, baseline = stream.read_frame_reopen()
                if args.manual:
                    print(f"trial {i}/{args.trials}: press A/B on Odin…", flush=True)
                    t0 = wait_pad_press(pad, timeout_s=30.0)
                    if t0 is None:
                        print(f"trial {i}: no press")
                        continue
                else:
                    t0 = fire_tap(HOLD_S)
                deadline = t0 + CAPTURE_S
                ms = None
                peak = 0.0
                peak_global = 0.0
                while time.time() < deadline:
                    t_grab, frame = stream.read_frame_reopen()
                    tile = max_tile_mad(baseline, frame)
                    glob = mean_abs_diff(baseline, frame)
                    peak = max(peak, tile)
                    peak_global = max(peak_global, glob)
                    # Sub-20ms is not physical for BT+Switch+HDMI+USB2 MJPEG.
                    if tile >= thresh and t_grab >= t0:
                        cand = (t_grab - t0) * 1000.0
                        if cand >= 20.0:
                            ms = cand
                            break
                if ms is None:
                    print(
                        f"trial {i}: no change "
                        f"(peak tile-MAD={peak:.3f} global={peak_global:.3f})"
                    )
                    continue
                results.append(ms)
                print(f"trial {i}: {ms:.1f} ms (tile-MAD={peak:.3f})")
            except RuntimeError as e:
                print(f"trial {i}: capture error ({e}) — retrying stream")
                try:
                    stream._open()
                except Exception as e2:
                    print(f"reopen failed: {e2}")
                    break

        if not results:
            print("No successful trials.")
            print("If taps fire but peak stays near noise: confirm Test Input Devices")
            print("is on-screen and Steam is focused on the Switch capture tile (not Home).")
            return 1

        results.sort()
        mean_v = statistics.mean(results)
        med = statistics.median(results)
        p90 = results[max(0, int(round(0.9 * (len(results) - 1))))]
        print()
        print(f"=== latency to {mode} ===")
        print(
            f"n={len(results)}  mean={mean_v:.1f} ms  median={med:.1f} ms  "
            f"p90={p90:.1f} ms  min={results[0]:.1f}  max={results[-1]:.1f}"
        )
        if mode == "v4l2":
            print("Includes: BT/NUXBT + Switch UI + HDMI + MS2109 USB MJPEG dequeue.")
            print("Not included: ffplay, gamescope, Sunshine encode, Wi-Fi, Moonlight decode.")
            print("Rough add: ffplay ~16–33ms + encode/net/client ~16–50ms.")
        return 0
    finally:
        if stream is not None:
            stream.close()
        if stopped:
            print("Restarting capture viewer…")
            start_viewer()


if __name__ == "__main__":
    raise SystemExit(main())
