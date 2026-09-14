"""Decky plugin: Game Mode second-screen toggle and window placement.

PluginLoader runs as root. Call ``scripts/second-screen-windows.py`` as user
deck. Never ``sudo systemctl --user``. Never ``pgrep -f`` sunshine.
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
    script = os.path.join("scripts", "second-screen-windows.py")
    candidates: list[str] = []
    if env:
        candidates.append(env)
    candidates.append(os.path.join(home, "steamos-playbook"))
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, script)):
            return cand
    return candidates[0] if candidates else os.path.join(home, "steamos-playbook")


def _script() -> str:
    return os.path.join(_playbook(), "scripts", "second-screen-windows.py")


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
        "LD_PRELOAD=",
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
        data["ok"] = proc.returncode == 0
    if isinstance(data, dict):
        data["rc"] = proc.returncode
    return data if isinstance(data, dict) else {"ok": False, "message": "bad json"}


class Plugin:
    async def _main(self) -> None:
        _log(f"Second Screen plugin loaded (playbook={_playbook()})")

    async def get_status(self) -> dict:
        script = _script()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}", "windows": []}
        try:
            proc = _run_as_deck(["python3", script, "status"], timeout=12)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "second-screen status timed out", "windows": []}
        return _json_from(proc)

    async def set_dual_screen(self, mode: str = "auto", **kwargs: object) -> dict:
        if kwargs:
            mode = str(kwargs.get("mode", mode) or mode)
        script = _script()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}"}
        mode = (mode or "auto").strip().lower()
        if mode not in ("auto", "on", "off"):
            return {"ok": False, "message": f"Unknown dual-screen mode {mode}"}
        try:
            proc = _run_as_deck(
                ["python3", script, "set-dual-screen", "--mode", mode],
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "set-dual-screen timed out"}
        return _json_from(proc)

    async def show_window(
        self,
        display: str = "",
        window_id: str = "",
        **kwargs: object,
    ) -> dict:
        if kwargs:
            display = str(kwargs.get("display", display) or display)
            window_id = str(
                kwargs.get("window_id", kwargs.get("id", window_id)) or window_id
            )
        script = _script()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}"}
        window_id = (window_id or "").strip()
        display = (display or "").strip()
        if not window_id:
            return {"ok": False, "message": "Missing window id"}
        cmd = ["python3", script, "show", "--id", window_id]
        if display:
            cmd.extend(["--display", display])
        try:
            proc = _run_as_deck(cmd, timeout=20)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "show window timed out"}
        return _json_from(proc)

    async def idle_clock(self) -> dict:
        script = _script()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}"}
        try:
            proc = _run_as_deck(["python3", script, "idle"], timeout=25)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "idle clock timed out"}
        return _json_from(proc)
