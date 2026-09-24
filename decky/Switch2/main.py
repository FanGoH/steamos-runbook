"""Decky plugin: Switch 2 / NUXBT Pro Controller bridge actions.

PluginLoader is root — call ``nuxbt-api.py`` as user deck (session bus +
BlueZ + tmux). Never ``sudo systemctl --user``. Never ``pgrep -f`` sunshine.
Additive Switch RP only — does not touch EmuPads / dual-stream defaults.
"""

from __future__ import annotations

import json
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


def _snapshot() -> str:
    return os.path.join(_user_home(), "homebrew", "data", "Switch2")


def _playbook() -> str:
    home = _user_home()
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    candidates: list[str] = []
    if env:
        candidates.append(env)
    candidates.append(os.path.join(home, "steamos-playbook"))
    candidates.append(_snapshot())
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, "scripts", "nuxbt-api.py")):
            return cand
    return candidates[0] if candidates else os.path.join(home, "steamos-playbook")


def _script() -> str:
    return os.path.join(_playbook(), "scripts", "nuxbt-api.py")


def _log(msg: str) -> None:
    if decky is None:
        return
    logger = getattr(decky, "logger", None)
    if logger is not None:
        logger.info(msg)


def _run(args: list[str], timeout: int = 45) -> subprocess.CompletedProcess:
    uid = _session_uid()
    runtime = f"/run/user/{uid}"
    home = _user_home()
    prefix = [
        "env",
        f"HOME={home}",
        "USER=deck",
        f"XDG_RUNTIME_DIR={runtime}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
        "LD_PRELOAD=",
        f"STEAMOS_PLAYBOOK_DIR={_playbook()}",
    ]
    inner = [*prefix, "python3", _script(), *args]
    if os.getuid() == 0:
        cmd = ["runuser", "-u", "deck", "--", *inner]
    else:
        cmd = inner
    _log("run: " + " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _json_from(proc: subprocess.CompletedProcess) -> dict:
    text = (proc.stdout or "").strip()
    if not text:
        err = (proc.stderr or "").strip() or f"exit {proc.returncode}"
        return {"ok": False, "message": err, "rc": proc.returncode}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "message": (proc.stderr or text)[:400], "rc": proc.returncode}
    if isinstance(data, dict) and "ok" not in data:
        data["ok"] = proc.returncode == 0
    return data if isinstance(data, dict) else {"ok": False, "message": "bad json"}


class Plugin:
    async def get_status(self) -> dict:
        return _json_from(_run(["status"], timeout=15))

    async def start(self) -> dict:
        return _json_from(_run(["start"], timeout=60))

    async def stop(self) -> dict:
        return _json_from(_run(["stop"], timeout=20))

    async def grip(self) -> dict:
        """Change Grip/Order: advertise + hold L+R on NUXBT."""
        return _json_from(_run(["grip"], timeout=60))

    async def reconnect(self) -> dict:
        """MAC reconnect (Switch on, not on Grip/Order)."""
        return _json_from(_run(["reconnect"], timeout=60))

    async def _main(self) -> None:
        _log(f"Switch 2 / NUXBT plugin loaded; playbook={_playbook()}")
