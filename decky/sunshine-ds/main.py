"""Decky plugin: switch to Plasma and start proven sunshine-ds.

PluginLoader runs as root. Talk to the deck user's systemd bus — never
`sudo systemctl --user`. Does not launch Cemu/Azahar.
"""

from __future__ import annotations

import os
import pwd
import subprocess

try:
    import decky  # type: ignore
except ImportError:
    decky = None  # type: ignore


def _user_home() -> str:
    if decky is not None:
        home = getattr(decky, "DECKY_USER_HOME", None)
        if home:
            return str(home)
    env = os.environ.get("DECKY_USER_HOME")
    if env:
        return env
    if os.getuid() == 0:
        try:
            return pwd.getpwnam("deck").pw_dir
        except KeyError:
            return "/home/deck"
    return os.path.expanduser("~")


def _session_uid() -> int:
    try:
        return pwd.getpwnam("deck").pw_uid
    except KeyError:
        return 1000 if os.getuid() == 0 else os.getuid()


def _playbook() -> str:
    home = _user_home()
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    if env and os.path.isfile(os.path.join(env, "scripts", "switch-to-desktop-ds.sh")):
        return env
    cand = os.path.join(home, "steamos-playbook")
    if os.path.isfile(os.path.join(cand, "scripts", "switch-to-desktop-ds.sh")):
        return cand
    return cand


def _log(msg: str) -> None:
    if decky is not None:
        decky.logger.info(msg)


def _run_as_deck(args: list[str], timeout: int = 20, background: bool = False) -> subprocess.CompletedProcess:
    uid = _session_uid()
    runtime = f"/run/user/{uid}"
    prefix = [
        "env",
        f"HOME={_user_home()}",
        f"USER=deck",
        f"XDG_RUNTIME_DIR={runtime}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
    ]
    if os.getuid() == 0:
        cmd = ["runuser", "-u", "deck", "--", *prefix, *args]
    else:
        cmd = [*prefix, *args]
    _log("run: " + " ".join(cmd))
    if background:
        subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _active(unit: str) -> bool:
    r = _run_as_deck(["systemctl", "--user", "is-active", unit], timeout=8)
    return r.returncode == 0 and (r.stdout or "").strip() == "active"


def _ds_state() -> str:
    r = _run_as_deck(
        ["curl", "-sS", "--max-time", "2", "http://127.0.0.1:48100/serverinfo"],
        timeout=6,
    )
    xml = r.stdout or ""
    if "SUNSHINE_SERVER_BUSY" in xml:
        return "BUSY"
    if "SUNSHINE_SERVER_FREE" in xml:
        return "FREE"
    return "DOWN"


class Plugin:
    async def _main(self) -> None:
        _log(f"Sunshine DS plugin loaded (playbook={_playbook()})")

    async def get_status(self) -> dict:
        gamescope = _active("gamescope-session.service")
        plasma = _active("plasma-plasmashell.service")
        ds = _ds_state()
        if gamescope:
            headline = "Game Mode"
            detail = "Start Dual-Stream Desktop to switch to Plasma and boot sunshine-ds on :48100. Cemu/Azahar stay Moonlight apps."
        elif ds in ("FREE", "BUSY"):
            headline = f"sunshine-ds {ds}"
            detail = "Moonlight → host :48100. Return via the Sunshine app Return to Game Mode."
        else:
            headline = "Desktop"
            detail = "sunshine-ds is not answering :48100 yet."
        return {
            "ok": True,
            "gamescope": gamescope,
            "plasma": plasma,
            "ds": ds,
            "headline": headline,
            "detail": detail,
        }

    async def start_desktop_ds(self) -> dict:
        script = os.path.join(_playbook(), "scripts", "switch-to-desktop-ds.sh")
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}"}
        # --yes leaves Game Mode. Return quickly; steamosctl does not come back.
        _run_as_deck(["/bin/bash", script, "--yes"], timeout=15, background=True)
        return {
            "ok": True,
            "message": "Switching to Plasma. sunshine-ds starts when KWin is up. Moonlight: :48100.",
        }
