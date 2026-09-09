"""Decky plugin: list pads and apply Cemu / Azahar / Eden binds.

PluginLoader runs as root. Talk to the deck user via runuser — never
``sudo systemctl --user``. Do not hand-edit emulator XML/INI; call
``scripts/bind-gamepad.py``.
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


def _playbook() -> str:
    home = _user_home()
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    bind = os.path.join("scripts", "bind-gamepad.py")
    if env and os.path.isfile(os.path.join(env, bind)):
        return env
    cand = os.path.join(home, "steamos-playbook")
    if os.path.isfile(os.path.join(cand, bind)):
        return cand
    return cand


def _bind_py() -> str:
    return os.path.join(_playbook(), "scripts", "bind-gamepad.py")


def _log(msg: str) -> None:
    if decky is None:
        return
    logger = getattr(decky, "logger", None)
    if logger is not None:
        logger.info(msg)


def _run_as_deck(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    uid = _session_uid()
    runtime = f"/run/user/{uid}"
    prefix = [
        "env",
        f"HOME={_user_home()}",
        "USER=deck",
        f"XDG_RUNTIME_DIR={runtime}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
    ]
    if os.getuid() == 0:
        cmd = ["runuser", "-u", "deck", "--", *prefix, *args]
    else:
        cmd = [*prefix, *args]
    _log("run: " + " ".join(cmd))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _json_from(proc: subprocess.CompletedProcess) -> dict:
    text = (proc.stdout or "").strip()
    if not text:
        err = (proc.stderr or "").strip() or f"exit {proc.returncode}"
        return {"ok": False, "message": err, "rc": proc.returncode}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        err = (proc.stderr or text)[:400]
        return {"ok": False, "message": err, "rc": proc.returncode}
    if isinstance(data, dict) and "ok" not in data:
        data["ok"] = proc.returncode != 1
    if isinstance(data, dict):
        data["rc"] = proc.returncode
    return data if isinstance(data, dict) else {"ok": False, "message": "bad json"}


class Plugin:
    async def _main(self) -> None:
        _log(f"Emu Pads plugin loaded (playbook={_playbook()})")

    async def get_status(self) -> dict:
        script = _bind_py()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}", "pads": []}
        try:
            proc = _run_as_deck(["python3", script, "status"], timeout=15)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "bind-gamepad status timed out", "pads": []}
        data = _json_from(proc)
        if "pads" not in data:
            data["pads"] = []
        return data

    async def apply(self, emu: str = "all", pads: str = "", **kwargs: object) -> dict:
        if kwargs:
            emu = str(kwargs.get("emu", emu) or emu)
            pads = str(kwargs.get("pads", pads) or pads)
        script = _bind_py()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}"}
        emu = (emu or "all").strip().lower()
        pads = (pads or "").strip()
        if not pads:
            return {"ok": False, "message": "No pads selected.", "rc": 2}
        if emu not in ("all", "cemu", "azahar", "eden"):
            return {"ok": False, "message": f"Unknown emu {emu}"}
        try:
            proc = _run_as_deck(
                ["python3", script, "apply", "--emu", emu, "--pads", pads, "--force"],
                timeout=25,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "bind-gamepad apply timed out"}
        data = _json_from(proc)
        if not data.get("messages") and data.get("message"):
            data["messages"] = [data["message"]]
        return data
