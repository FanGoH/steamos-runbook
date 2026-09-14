#!/usr/bin/env python3
"""Mute EmuPads sinks while any Steam UI has focus.

Steam and the emulator both keep pads open. EVIOCGRAB on a Sunshine
node would also steal overlay / QAM / Home navigation. Touch
``$XDG_RUNTIME_DIR/emupads-mute`` so the mux emits zeros; Steam still
reads the real pads. Do not SIGSTOP the emulator (that holds Steam's
SIGTERM on Exit).

Steam UI (mute only — do not quit):
- Overlay (Guide / Hold-Select): ``STEAM_OVERLAY=1``
- QAM (Quick Access Menu, ``...``): ``GAMESCOPE_BLUR_MODE`` != 0 on HDMI ``:0``.
  FOCUSED_APP stays the game — do not treat 769 as QAM.
- Home / Library / other BPM menus: ``GAMESCOPE_FOCUSED_APP=769`` on ``:0``
  while the emulator is still running. Overlay closing into Home used to
  unmute, then the 8s 769 gate ``--quit``'d Cemu (looked like a crash).

Exit **quits** Azahar or Cemu only when SIGTERM is pending (Steam Exit).
Do not SIGSTOP. Playbook SteamLaunch may not be a Steam child.

Do not grab ``/dev/input``. Never pgrep -f sunshine.
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
MUTE_KINDS = ("overlay", "qam", "menu")


def _load_bind():
    path = Path(__file__).resolve().parent / "bind-gamepad.py"
    spec = importlib.util.spec_from_file_location("bind_gamepad", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BIND = _load_bind()
MUTE_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "emupads-mute"


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%dT%H:%M:%S") + " " + msg
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _x11_env(display: str) -> dict[str, str]:
    env = {**os.environ, "DISPLAY": display}
    env.pop("LD_PRELOAD", None)
    env.pop("LD_PRELOAD_32", None)
    env.pop("LD_PRELOAD_64", None)
    return env


def xprop_root(display: str, atom: str) -> str:
    try:
        out = subprocess.check_output(
            ["xprop", "-root", atom],
            env=_x11_env(display),
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
            env=_x11_env(display),
            stderr=subprocess.DEVNULL,
            text=True,
        ).split()
    except (OSError, subprocess.CalledProcessError):
        ids = []
    try:
        ids += subprocess.check_output(
            ["xdotool", "search", "--class", "steamwebhelper"],
            env=_x11_env(display),
            stderr=subprocess.DEVNULL,
            text=True,
        ).split()
    except (OSError, subprocess.CalledProcessError):
        pass
    for xid in ids:
        try:
            out = subprocess.check_output(
                ["xprop", "-id", xid, "STEAM_OVERLAY"],
                env=_x11_env(display),
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


def qam_on(display: str = ":0") -> bool:
    """Steam Quick Access Menu blurs the running game; FOCUSED_APP stays the game."""
    mode = xprop_root(display, "GAMESCOPE_BLUR_MODE")
    return bool(mode) and mode != "0"


def steam_ui_kind() -> str:
    """overlay | qam | menu | ''."""
    for display in DISPLAYS:
        if overlay_on(display):
            return "overlay"
    if qam_on(":0"):
        return "qam"
    if xprop_root(":0", "GAMESCOPE_FOCUSED_APP") == STEAM_CLIENT_ID:
        return "menu"
    return ""


def steam_ui_up() -> bool:
    return steam_ui_kind() in MUTE_KINDS


def azahar_on_hdmi() -> bool:
    for display in DISPLAYS:
        try:
            out = subprocess.check_output(
                ["xdotool", "search", "--class", "Azahar"],
                env=_x11_env(display),
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        if out.split():
            return True
    return False


def quit_azahar() -> None:
    script = Path(__file__).resolve().parent / "ensure-azahar-gamemode-dual-screen.sh"
    if not script.is_file():
        return
    try:
        subprocess.run(
            ["timeout", "8", "bash", str(script), "--quit"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return
    log("Steam Exit — quit Azahar (reaper is not a Steam child)")


def cemu_on_session() -> bool:
    for display in DISPLAYS:
        try:
            out = subprocess.check_output(
                ["xdotool", "search", "--name", "Cemu"],
                env=_x11_env(display),
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        if out.split():
            return True
    return False


def quit_cemu() -> None:
    script = Path(__file__).resolve().parent / "ensure-cemu-gamemode-dual-screen.sh"
    if not script.is_file():
        return
    try:
        subprocess.run(
            ["bash", str(script), "--quit"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return
    log("Steam Exit — quit Cemu")


def quit_for_steam_exit(stopped: set[int], live: set[int]) -> None:
    """SIGCONT then --quit. Do not SIGSTOP first — that holds SIGTERM."""
    for pid in list(live | stopped):
        cont_pid(pid)
    if azahar_on_hdmi():
        quit_azahar()
    elif cemu_on_session():
        quit_cemu()


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


def mute_sinks() -> None:
    MUTE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MUTE_PATH.write_text("1\n", encoding="utf-8")


def unmute_sinks() -> None:
    try:
        MUTE_PATH.unlink()
    except OSError:
        pass


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


def restore_bottom_screen() -> None:
    """Kill leftover :2 x11grab and paint the idle clock.

    Azahar's focus watcher can die with the Tender tile before Azahar
    itself exits, which leaves Moonlight video/1 on the last 3DS bottom
    frame. Safe no-op while Cemu/Azahar is still up. --paint hops out
    of Steam's reaper; do not start the clock until the emu is gone.
    """
    if BIND.cemu_running() or BIND.azahar_running():
        return
    script = Path(__file__).resolve().parent / "sunshine-ds-gamemode-virtual.sh"
    if not script.is_file():
        return
    try:
        subprocess.run(
            ["bash", str(script), "--paint"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return
    log("painted :2 idle clock (emulator gone)")


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
                if ui:
                    unmute_sinks()
                    ui = False
                if saw_emu:
                    restore_steam_focus()
                    restore_bottom_screen()
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
                unmute_sinks()
                log("Steam Exit — SIGTERM pending, quitting")
                quit_for_steam_exit(stopped, pids)
                stopped.clear()
                ui = False
                time.sleep(0.1)
                continue
            live = pids
            kind = steam_ui_kind()
            now = bool(live) and kind in MUTE_KINDS
            if now and not ui:
                mute_sinks()
                for pid in live:
                    if proc_stopped(pid) and cont_pid(pid):
                        log(f"SIGCONT pid {pid} (leftover stop; mute sinks instead)")
                stopped.clear()
                log(f"muted EmuPads sinks (Steam {kind})")
                ui = True
            elif now:
                for pid in live:
                    if proc_stopped(pid) and cont_pid(pid):
                        log(f"SIGCONT pid {pid} (late {kind})")
                stopped = {pid for pid in stopped if pid in live}
            elif ui:
                unmute_sinks()
                for pid in list(stopped):
                    if cont_pid(pid):
                        log(f"SIGCONT pid {pid}")
                stopped.clear()
                log("unmuted EmuPads sinks")
                ui = False
            time.sleep(0.2)
    finally:
        unmute_sinks()
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
    assert steam_ui_kind() in ("", "overlay", "qam", "menu")
    assert MUTE_KINDS == ("overlay", "qam", "menu")
    assert qam_on(":0") in (True, False)
    assert azahar_on_hdmi() in (True, False)
    assert cemu_on_session() in (True, False)
    assert (1 << 14) == 0x4000
    mute_sinks()
    assert MUTE_PATH.is_file()
    unmute_sinks()
    assert not MUTE_PATH.is_file()
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
