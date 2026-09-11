#!/usr/bin/env python3
"""Pause Cemu / Azahar / Eden while Steam overlay or qAM has focus.

Steam and the emulator both keep the Sunshine pad open. EVIOCGRAB on that
node would also steal overlay / qAM navigation. SIGSTOP the emulator
instead; Steam keeps the pad. SIGCONT when Steam UI closes.

Steam UI is ``STEAM_OVERLAY=1`` on Big Picture, or ``GAMESCOPE_FOCUSED_APP=769``
(overlay, qAM, Exit menu). Do not grab ``/dev/input``. Never pgrep -f sunshine.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIDFILE = Path(os.environ.get("EMU_STEAM_UI_INHIBIT_PIDFILE", ROOT / "logs/emu-steam-ui-inhibit.pid"))
LOG = Path(os.environ.get("EMU_STEAM_UI_INHIBIT_LOG", ROOT / "logs/emu-steam-ui-inhibit.log"))
STEAM_CLIENT_ID = "769"
DISPLAYS = (":0", ":1")


def _load_bind():
    path = Path(__file__).resolve().parent / "bind-gamepad.py"
    spec = importlib.util.spec_from_file_location("bind_gamepad", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BIND = _load_bind()


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%dT%H:%M:%S") + " " + msg
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def xprop_root(display: str, atom: str) -> str:
    try:
        out = subprocess.check_output(
            ["xprop", "-root", atom],
            env={**os.environ, "DISPLAY": display},
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    if "=" not in out:
        return ""
    return out.split("=", 1)[1].strip().split(",")[0].strip()


def overlay_on(display: str) -> bool:
    try:
        ids = subprocess.check_output(
            ["xdotool", "search", "--class", "steam"],
            env={**os.environ, "DISPLAY": display},
            stderr=subprocess.DEVNULL,
            text=True,
        ).split()
    except (OSError, subprocess.CalledProcessError):
        ids = []
    try:
        ids += subprocess.check_output(
            ["xdotool", "search", "--class", "steamwebhelper"],
            env={**os.environ, "DISPLAY": display},
            stderr=subprocess.DEVNULL,
            text=True,
        ).split()
    except (OSError, subprocess.CalledProcessError):
        pass
    for xid in ids:
        try:
            out = subprocess.check_output(
                ["xprop", "-id", xid, "STEAM_OVERLAY"],
                env={**os.environ, "DISPLAY": display},
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        if "=" in out and out.split("=", 1)[1].strip() == "1":
            return True
    return False


def emu_age_seconds(pids: list[int]) -> float:
    hz = os.sysconf("SC_CLK_TCK") or 100
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0
    oldest: float | None = None
    for pid in pids:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            continue
        rparen = stat.rfind(")")
        if rparen < 0:
            continue
        fields = stat[rparen + 2 :].split()
        if len(fields) < 20:
            continue
        try:
            start = int(fields[19]) / hz
        except ValueError:
            continue
        age = uptime - start
        if oldest is None or age < oldest:
            oldest = age
    return max(0.0, oldest or 0.0)


def term_pending(pid: int) -> bool:
    """Steam Exit SIGTERM stays pending while the emulator is SIGSTOP'd."""
    try:
        text = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return False
    for key in ("SigPnd", "ShdPnd"):
        prefix = key + ":"
        for line in text.splitlines():
            if not line.startswith(prefix):
                continue
            try:
                mask = int(line.split()[1], 16)
            except (IndexError, ValueError):
                return False
            if mask & (1 << 14):
                return True
    return False


def steam_ui_up(emu_age_s: float = 0.0) -> bool:
    overlay = False
    for display in DISPLAYS:
        if overlay_on(display):
            overlay = True
    if overlay:
        return True
    # qAM / Exit are FOCUSED_APP=769 on HDMI / BPM (:0). :1 often stays 769
    # after restore-steam-gamescope-focus.sh while Azahar/Cemu is focused on
    # :0 — that is not Steam UI (SIGSTOP there freezes a fresh launch).
    focused_steam = xprop_root(":0", "GAMESCOPE_FOCUSED_APP") == STEAM_CLIENT_ID
    # Wait until the emulator has been up so Launching (769 + 10x10 Cemu stub)
    # is not SIGSTOP'd into the spinning logo.
    return focused_steam and emu_age_s >= 8.0


def emu_pids() -> list[int]:
    try:
        out = subprocess.check_output(["ps", "-eo", "pid=,comm="], text=True)
    except OSError:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        comm = parts[1].strip()
        if BIND.is_cemu_comm(comm) or BIND.is_azahar_comm(comm) or BIND.is_eden_comm(comm):
            try:
                pids.append(int(parts[0]))
            except ValueError:
                continue
    return pids


def proc_stopped(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    rparen = stat.rfind(")")
    if rparen < 0:
        return False
    fields = stat[rparen + 2 :].split()
    return bool(fields) and fields[0] == "T"


def stop_pid(pid: int) -> bool:
    if proc_stopped(pid):
        return False
    try:
        os.kill(pid, signal.SIGSTOP)
    except OSError:
        return False
    return True


def cont_pid(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGCONT)
    except OSError:
        return False
    return True


def write_pidfile() -> None:
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()) + "\n")


def already_running() -> bool:
    try:
        old = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return False
    if old == os.getpid():
        return False
    return Path(f"/proc/{old}").is_dir()


def restore_steam_focus() -> None:
    script = Path(__file__).resolve().parent / "restore-steam-gamescope-focus.sh"
    if not script.is_file():
        return
    try:
        subprocess.run(
            ["bash", str(script)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return
    log("restored Steam FOCUSED_APP=769 (emulator gone)")


def loop() -> int:
    stopped: set[int] = set()
    idle = 0
    ui = False
    saw_emu = False
    write_pidfile()
    log("watch start")
    try:
        while True:
            pids = set(emu_pids())
            if not pids:
                idle += 1
                if stopped:
                    for pid in list(stopped):
                        cont_pid(pid)
                    stopped.clear()
                    ui = False
                if saw_emu:
                    restore_steam_focus()
                    saw_emu = False
                if idle >= 150:
                    log("no emulator; exiting")
                    return 0
                time.sleep(0.2)
                continue
            idle = 0
            saw_emu = True
            dying = {pid for pid in pids if term_pending(pid)}
            if dying:
                for pid in dying:
                    if cont_pid(pid):
                        log(f"SIGCONT pid {pid} (SIGTERM pending — Steam Exit)")
                    stopped.discard(pid)
            live = pids - dying
            now = bool(live) and steam_ui_up(emu_age_seconds(list(live)))
            if now and not ui:
                for pid in live:
                    if stop_pid(pid):
                        stopped.add(pid)
                        log(f"SIGSTOP pid {pid} (Steam overlay/qAM)")
                ui = True
            elif now:
                for pid in live - stopped:
                    if stop_pid(pid):
                        stopped.add(pid)
                        log(f"SIGSTOP pid {pid} (late)")
                stopped = {pid for pid in stopped if pid in live}
            elif ui:
                for pid in list(stopped):
                    if cont_pid(pid):
                        log(f"SIGCONT pid {pid}")
                stopped.clear()
                ui = False
            time.sleep(0.2)
    finally:
        for pid in list(stopped):
            cont_pid(pid)
        if PIDFILE.is_file():
            try:
                if PIDFILE.read_text().strip() == str(os.getpid()):
                    PIDFILE.unlink()
            except OSError:
                pass
        log("watch exit")


def self_test() -> int:
    assert BIND.is_cemu_comm("Cemu_relwithdeb")
    assert BIND.is_azahar_comm("azahar")
    assert not BIND.is_azahar_comm("azahar-launcher")
    assert BIND.is_eden_comm("eden")
    assert steam_ui_up() in (True, False)
    assert (1 << 14) == 0x4000
    print("inhibit-emu-input-on-steam-ui self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ensure", action="store_true", help="no-op if already watching")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.ensure and already_running():
        return 0
    if already_running():
        print(f"already running ({PIDFILE.read_text().strip()})", file=sys.stderr)
        return 0
    return loop()


if __name__ == "__main__":
    raise SystemExit(main())
