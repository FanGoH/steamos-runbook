#!/usr/bin/env python3
"""Hint gamescope to send the pad to Kimochi's overlay (option 4).

Kimochi 0.9.0 opens the controller pie then cancels it with
``controller-cancelled`` / ``focus-elsewhere`` because Trails keeps
``GAMESCOPE_FOCUSED_APP``. This sidecar only sets ``STEAM_INPUT_FOCUS=1``
on Kimochi *overlay* windows (already ``GAMESCOPE_EXTERNAL_OVERLAY=1``,
or titled Overlay/Dictionary). It does **not**:

- wrap ``gaming-mode/launch.sh``
- SIGSTOP / SIGCONT steam
- write ``GAMESCOPECTRL_BASELAYER_APPID`` / ``GAMESCOPE_FOCUSED_APP``
- EVIOCGRAB pads
- ``pgrep -f`` / ``pkill -f`` sunshine

If Steam is painting Guide (``STEAM_OVERLAY=1`` on a steam window), the
hint is cleared so QAM / overlay keep the pad.

Manual: ``python3 scripts/kimochi-overlay-input-focus.py`` while Kimochi
and the game are running, then LS+RS. ``--stop`` kills the sidecar.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIDFILE = Path(
    os.environ.get(
        "KIMOCHI_OVERLAY_FOCUS_PIDFILE", ROOT / "logs/kimochi-overlay-input-focus.pid"
    )
)
LOG = Path(
    os.environ.get("KIMOCHI_OVERLAY_FOCUS_LOG", ROOT / "logs/kimochi-overlay-input-focus.log")
)
EVIDENCE = Path(
    os.environ.get(
        "KIMOCHI_EVIDENCE",
        Path.home() / ".local/share/dev.kimochi.app/evidence.jsonl",
    )
)
DISPLAYS = (":0", ":1")
POLL_S = float(os.environ.get("KIMOCHI_OVERLAY_FOCUS_POLL_S", "0.02"))
OVERLAY_NAME_MARKS = ("overlay", "dictionary", "controller")


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%dT%H:%M:%S") + " " + msg
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def _x11_env(display: str) -> dict[str, str]:
    env = {**os.environ, "DISPLAY": display}
    env.pop("LD_PRELOAD", None)
    env.pop("LD_PRELOAD_32", None)
    env.pop("LD_PRELOAD_64", None)
    return env


def _xprop_out(display: str, argv: list[str]) -> str:
    try:
        return subprocess.check_output(
            argv, env=_x11_env(display), stderr=subprocess.DEVNULL, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return ""


def xprop_cardinal(display: str, xid: str, atom: str) -> str:
    out = _xprop_out(display, ["xprop", "-id", xid, atom])
    if "=" not in out:
        return ""
    return out.split("=", 1)[1].strip().split(",")[0].strip()


def xprop_set(display: str, xid: str, atom: str, value: int) -> None:
    subprocess.call(
        ["xprop", "-id", xid, "-f", atom, "32c", "-set", atom, str(value)],
        env=_x11_env(display),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def xprop_name(display: str, xid: str) -> str:
    out = _xprop_out(display, ["xprop", "-id", xid, "WM_NAME"])
    if "=" not in out:
        return ""
    return out.split("=", 1)[1].strip().strip('"')


def xprop_class(display: str, xid: str) -> str:
    out = _xprop_out(display, ["xprop", "-id", xid, "WM_CLASS"])
    return out.lower()


def steam_overlay_on(display: str) -> bool:
    ids: list[str] = []
    for cls in ("steam", "steamwebhelper"):
        try:
            ids += subprocess.check_output(
                ["xdotool", "search", "--class", cls],
                env=_x11_env(display),
                stderr=subprocess.DEVNULL,
                text=True,
            ).split()
        except (OSError, subprocess.CalledProcessError):
            pass
    for xid in ids:
        if xprop_cardinal(display, xid, "STEAM_OVERLAY") == "1":
            return True
    return False


def kimochi_xids(display: str) -> list[str]:
    try:
        return subprocess.check_output(
            ["xdotool", "search", "--class", "kimochi"],
            env=_x11_env(display),
            stderr=subprocess.DEVNULL,
            text=True,
        ).split()
    except (OSError, subprocess.CalledProcessError):
        return []


def is_overlay_window(display: str, xid: str, name: str, wm_class: str) -> bool:
    if "tray-icon" in wm_class:
        return False
    if xprop_cardinal(display, xid, "GAMESCOPE_EXTERNAL_OVERLAY") == "1":
        return True
    lowered = name.lower()
    return any(mark in lowered for mark in OVERLAY_NAME_MARKS)


def set_input_focus(display: str, xid: str, want: int, name: str, armed: dict[str, int]) -> None:
    key = f"{display}:{xid}"
    cur = xprop_cardinal(display, xid, "STEAM_INPUT_FOCUS")
    if cur == str(want) and armed.get(key) == want:
        return
    xprop_set(display, xid, "STEAM_INPUT_FOCUS", want)
    armed[key] = want
    log(f"{display} xid={xid} name={name!r} STEAM_INPUT_FOCUS={want} (was {cur or 'unset'})")


def read_evidence_opens(fh, pos: int) -> tuple[int, bool]:
    """Return (new_pos, saw_openControllerMenu) since pos. Never raise on rotate."""
    if not EVIDENCE.is_file():
        return 0, False
    size = EVIDENCE.stat().st_size
    if pos > size:
        pos = 0
    fh.seek(pos)
    chunk = fh.read()
    saw = False
    for line in chunk.splitlines():
        if "openControllerMenu" not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            saw = True
            continue
        if rec.get("check") == "overlay-action" and rec.get("name") == "openControllerMenu":
            saw = True
        elif rec.get("check") == "openControllerMenu":
            saw = True
    return EVIDENCE.stat().st_size, saw


def tick(armed: dict[str, int], force: bool) -> None:
    overlay_up = any(steam_overlay_on(d) for d in DISPLAYS)
    want = 0 if overlay_up else 1
    if overlay_up and force:
        log("steam overlay up — leaving Kimochi INPUT_FOCUS clear")
    seen: set[str] = set()
    for display in DISPLAYS:
        for xid in kimochi_xids(display):
            key = f"{display}:{xid}"
            seen.add(key)
            wm_class = xprop_class(display, xid)
            name = xprop_name(display, xid)
            if not is_overlay_window(display, xid, name, wm_class):
                continue
            set_input_focus(display, xid, want, name, armed)
            if want == 1 and force:
                subprocess.call(
                    ["xdotool", "windowraise", xid],
                    env=_x11_env(display),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
    for key in list(armed):
        if key not in seen:
            del armed[key]


def kill_old() -> None:
    try:
        old = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return
    if old == os.getpid() or old <= 1:
        return
    try:
        os.kill(old, 0)
    except OSError:
        return
    os.kill(old, signal.SIGTERM)
    for _ in range(20):
        try:
            os.kill(old, 0)
        except OSError:
            break
        time.sleep(0.05)


def write_pid() -> None:
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--once", action="store_true", help="Tag current overlay windows and exit")
    args = parser.parse_args()

    if args.stop:
        kill_old()
        try:
            PIDFILE.unlink()
        except OSError:
            pass
        return 0

    if os.environ.get("DISPLAY") in (None, ""):
        os.environ["DISPLAY"] = ":0"
    os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")

    if not args.once:
        kill_old()
        write_pid()

    armed: dict[str, int] = {}
    tick(armed, force=True)
    if args.once:
        return 0

    evidence_pos = EVIDENCE.stat().st_size if EVIDENCE.is_file() else 0
    evidence_fh = None
    try:
        if EVIDENCE.is_file():
            evidence_fh = EVIDENCE.open("r", encoding="utf-8", errors="replace")
    except OSError:
        evidence_fh = None

    log(f"watching overlays poll={POLL_S}s evidence={EVIDENCE}")
    try:
        while True:
            force = False
            if evidence_fh is not None:
                try:
                    evidence_pos, force = read_evidence_opens(evidence_fh, evidence_pos)
                except OSError:
                    force = False
            tick(armed, force=force)
            time.sleep(POLL_S)
    except KeyboardInterrupt:
        return 0
    finally:
        if evidence_fh is not None:
            evidence_fh.close()
        if PIDFILE.is_file() and PIDFILE.read_text().strip() == str(os.getpid()):
            PIDFILE.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
