#!/usr/bin/env python3
"""Debug: toggle Steam Game Mode overlay atoms (sunshine-ds owns this now).

sunshine-ds pulses HOME after ``back_button_timeout`` and writes
``STEAM_OVERLAY`` / ``GAMESCOPE_FOCUSED_APP=769`` itself. Keep this script for
``--show`` / ``--hide`` / ``--self-test``. Do not start it from
``ensure-cemu-gamemode-dual-screen.sh`` (double-toggle).
"""
from __future__ import annotations

from pathlib import Path
import argparse
import os
import select
import struct
import subprocess
import sys
import time

EV_KEY = 1
BTN_SELECT = 0x13A
BTN_MODE = 0x13C
EVENT_FMT = struct.Struct("llHHi")
HOLD_S = 0.5
STEAM_CLIENT_ID = 769
PROC_DEVICES = Path("/proc/bus/input/devices")


def _run(argv: list[str], display: str) -> str:
    env = os.environ.copy()
    env["DISPLAY"] = display
    return subprocess.check_output(argv, env=env, text=True, stderr=subprocess.DEVNULL)


def bpm_xid(display: str) -> int | None:
    try:
        tree = _run(["xwininfo", "-root", "-tree"], display)
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in tree.splitlines():
        if "Steam Big Picture Mode" not in line:
            continue
        token = line.strip().split()[0]
        try:
            return int(token, 16)
        except ValueError:
            continue
    return None


def cemu_tv_xid(display: str) -> int | None:
    try:
        tree = _run(["xwininfo", "-root", "-tree"], display)
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in tree.splitlines():
        if "Cemu 2.6" not in line or "GamePad" in line:
            continue
        token = line.strip().split()[0]
        try:
            return int(token, 16)
        except ValueError:
            continue
    return None


def xprop_set(display: str, target: str, atom: str, value: int) -> None:
    env = os.environ.copy()
    env["DISPLAY"] = display
    subprocess.call(
        ["xprop", "-id" if target != "root" else "-root"]
        + ([] if target == "root" else [target])
        + ["-f", atom, "32c", "-set", atom, str(value)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def overlay_is_on(display: str) -> bool:
    xid = bpm_xid(display)
    if xid is None:
        return False
    env = os.environ.copy()
    env["DISPLAY"] = display
    try:
        out = subprocess.check_output(
            ["xprop", "-id", str(xid), "STEAM_OVERLAY"],
            env=env,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return "= 1" in out or "=1" in out


def show_overlay(display: str, appid: int) -> None:
    xid = bpm_xid(display)
    if xid is None:
        print("no Steam Big Picture window", file=sys.stderr)
        return
    xprop_set(display, str(xid), "STEAM_OVERLAY", 1)
    env = os.environ.copy()
    env["DISPLAY"] = display
    for args in (
        ["xprop", "-root", "-f", "GAMESCOPE_FOCUSED_APP", "32c", "-set", "GAMESCOPE_FOCUSED_APP", str(STEAM_CLIENT_ID)],
        ["xprop", "-root", "-f", "GAMESCOPE_FOCUSED_APP_GFX", "32c", "-set", "GAMESCOPE_FOCUSED_APP_GFX", str(appid)],
    ):
        subprocess.call(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"overlay on bpm={xid} gfx={appid}", flush=True)


def hide_overlay(display: str, appid: int) -> None:
    xid = bpm_xid(display)
    if xid is not None:
        xprop_set(display, str(xid), "STEAM_OVERLAY", 0)
    tv = cemu_tv_xid(display)
    env = os.environ.copy()
    env["DISPLAY"] = display
    if tv is not None:
        for atom, val in (
            ("GAMESCOPE_FOCUSED_WINDOW", tv),
            ("GAMESCOPE_FOCUSED_APP", appid),
            ("GAMESCOPE_FOCUSED_APP_GFX", appid),
            ("GAMESCOPECTRL_BASELAYER_WINDOW", tv),
        ):
            subprocess.call(
                ["xprop", "-root", "-f", atom, "32c", "-set", atom, str(val)],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    else:
        subprocess.call(
            ["xprop", "-root", "-f", "GAMESCOPE_FOCUSED_APP", "32c", "-set", "GAMESCOPE_FOCUSED_APP", str(appid)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.call(
            ["xprop", "-root", "-f", "GAMESCOPE_FOCUSED_APP_GFX", "32c", "-set", "GAMESCOPE_FOCUSED_APP_GFX", str(appid)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    print(f"overlay off tv={tv} app={appid}", flush=True)


def sunshine_event_nodes() -> list[tuple[str, str]]:
    """Return (name, /dev/input/eventN) for Sunshine x360 pads, not mouse."""
    if not PROC_DEVICES.is_file():
        return []
    out: list[tuple[str, str]] = []
    for block in PROC_DEVICES.read_text().split("\n\n"):
        name = ""
        event = ""
        vendor = ""
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("I:"):
                for part in line.split():
                    if part.startswith("Vendor="):
                        vendor = part.split("=", 1)[1].lower()
            elif line.startswith("H: Handlers="):
                for tok in line.replace("=", " ").split():
                    if tok.startswith("event"):
                        event = tok
        if "sunshine" not in name.lower() or "mouse" in name.lower():
            continue
        if vendor not in {"045e", "054c", "057e"}:
            continue
        if not event:
            continue
        path = f"/dev/input/{event}"
        if os.path.exists(path):
            out.append((name, path))
    return out


def toggle(display: str, appid: int) -> None:
    if overlay_is_on(display):
        hide_overlay(display, appid)
    else:
        show_overlay(display, appid)


def watch(display: str, appid: int, hold_s: float) -> int:
    nodes = sunshine_event_nodes()
    if not nodes:
        print("No Sunshine pads to watch", file=sys.stderr)
        return 2
    fds: dict[int, tuple[str, str]] = {}
    pressed: dict[int, float | None] = {}
    try:
        for name, path in nodes:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            fds[fd] = (name, path)
            pressed[fd] = None
            print(f"watching {name} {path}", flush=True)
        while True:
            ready, _, _ = select.select(list(fds), [], [], 0.05)
            now = time.monotonic()
            for fd in ready:
                data = os.read(fd, EVENT_FMT.size * 32)
                for off in range(0, len(data) - EVENT_FMT.size + 1, EVENT_FMT.size):
                    _s, _u, ev_type, code, value = EVENT_FMT.unpack_from(data, off)
                    if ev_type != EV_KEY:
                        continue
                    if code not in (BTN_SELECT, BTN_MODE):
                        continue
                    if code == BTN_MODE and value == 1:
                        print(f"Guide on {fds[fd][0]}", flush=True)
                        toggle(display, appid)
                        pressed[fd] = None
                        continue
                    if code == BTN_SELECT:
                        if value == 1:
                            pressed[fd] = now
                        elif value == 0:
                            pressed[fd] = None
            for fd, start in list(pressed.items()):
                if start is not None and now - start >= hold_s:
                    print(f"Select hold {hold_s:.1f}s on {fds[fd][0]}", flush=True)
                    toggle(display, appid)
                    pressed[fd] = None
    finally:
        for fd in fds:
            os.close(fd)
    return 0


def _self_test() -> int:
    sample = """
     0x2200035 "Steam Big Picture Mode": ("steamwebhelper" "steam")  1920x1080+0+0  +0+0
     0x3600003 "Cemu 2.6 - FPS: 30.05": ("Cemu" "Cemu")  1920x1080+0+0  +0+0
     0x3600016 "GamePad View - FPS: 30.05": ("Cemu" "Cemu")  1920x1080+0+0  +0+0
"""
    bpm = None
    tv = None
    for line in sample.splitlines():
        if "Steam Big Picture Mode" in line:
            bpm = int(line.strip().split()[0], 16)
        if "Cemu 2.6" in line and "GamePad" not in line:
            tv = int(line.strip().split()[0], 16)
    assert bpm == 0x2200035, bpm
    assert tv == 0x3600003, tv
    devices = (
        'I: Bus=0005 Vendor=045e Product=028e Version=0114\n'
        'N: Name="Sunshine (libvirtualhid) Odin2_Portal"\n'
        'H: Handlers=event27 js3 \n'
    )
    name = event = vendor = ""
    for line in devices.splitlines():
        if line.startswith("N: Name="):
            name = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("I:"):
            for part in line.split():
                if part.startswith("Vendor="):
                    vendor = part.split("=", 1)[1].lower()
        elif line.startswith("H: Handlers="):
            for tok in line.replace("=", " ").split():
                if tok.startswith("event"):
                    event = tok
    assert name.startswith("Sunshine")
    assert vendor == "045e"
    assert event == "event27", event
    pads = sunshine_event_nodes()
    print(f"steam-guide-from-select self-test ok (live sunshine pads: {len(pads)})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default=os.environ.get("DISPLAY", ":0"))
    parser.add_argument("--appid", type=int, default=int(os.environ.get("CEMU_STEAM_APPID", "2374129079")))
    parser.add_argument("--hold-ms", type=int, default=500)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--show", action="store_true", help="Open overlay once and exit")
    parser.add_argument("--hide", action="store_true", help="Close overlay once and exit")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.show:
        show_overlay(args.display, args.appid)
        return 0
    if args.hide:
        hide_overlay(args.display, args.appid)
        return 0
    return watch(args.display, args.appid, args.hold_ms / 1000.0)


if __name__ == "__main__":
    raise SystemExit(main())
