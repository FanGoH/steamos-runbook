"""Decky plugin: Eden / Azahar / Cemu quick graphics settings.

PluginLoader runs as root. Call ``scripts/emu-quick-settings.py`` as user
deck — never hand-edit INI/XML here, and never ``sudo systemctl --user``.
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
    script = os.path.join("scripts", "emu-quick-settings.py")
    if env and os.path.isfile(os.path.join(env, script)):
        return env
    cand = os.path.join(home, "steamos-playbook")
    if os.path.isfile(os.path.join(cand, script)):
        return cand
    return cand


def _script() -> str:
    return os.path.join(_playbook(), "scripts", "emu-quick-settings.py")


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
        data["ok"] = proc.returncode == 0
    if isinstance(data, dict):
        data["rc"] = proc.returncode
    return data if isinstance(data, dict) else {"ok": False, "message": "bad json"}


class Plugin:
    async def _main(self) -> None:
        _log(f"Emu Quick plugin loaded (playbook={_playbook()})")

    async def get_status(self, emu: str = "", title: str = "", **kwargs: object) -> dict:
        if kwargs:
            emu = str(kwargs.get("emu", emu) or emu)
            title = str(kwargs.get("title", title) or title)
        script = _script()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}", "emus": {}}
        cmd = ["python3", script, "status"]
        emu = (emu or "").strip().lower()
        title = (title or "").strip()
        if emu in ("eden", "azahar", "cemu"):
            cmd.extend(["--emu", emu])
        if title:
            cmd.extend(["--title", title])
        try:
            proc = _run_as_deck(cmd, timeout=15)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "emu-quick-settings status timed out", "emus": {}}
        data = _json_from(proc)
        if "emus" not in data:
            data["emus"] = {}
        return data

    async def set_setting(
        self,
        emu: str = "eden",
        scope: str = "global",
        title: str = "",
        key: str = "",
        value: str = "",
        **kwargs: object,
    ) -> dict:
        if kwargs:
            emu = str(kwargs.get("emu", emu) or emu)
            scope = str(kwargs.get("scope", scope) or scope)
            title = str(kwargs.get("title", title) or title)
            key = str(kwargs.get("key", key) or key)
            value = str(kwargs.get("value", value) or value)
        script = _script()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}"}
        emu = (emu or "eden").strip().lower()
        scope = (scope or "global").strip().lower()
        title = (title or "").strip()
        key = (key or "").strip()
        value = str(value).strip()
        if emu not in ("eden", "azahar", "cemu"):
            return {"ok": False, "message": f"Unknown emu {emu}"}
        if scope not in ("global", "game"):
            return {"ok": False, "message": f"Unknown scope {scope}"}
        if not key:
            return {"ok": False, "message": "Missing key"}
        cmd = [
            "python3",
            script,
            "set",
            "--emu",
            emu,
            "--scope",
            scope,
            "--key",
            key,
            "--value",
            value,
        ]
        live = bool(kwargs.get("live")) if kwargs else False
        if live:
            cmd.append("--live")
        if title:
            cmd.extend(["--title", title])
        try:
            proc = _run_as_deck(cmd, timeout=25)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "emu-quick-settings set timed out"}
        data = _json_from(proc)
        if not data.get("messages") and data.get("message"):
            data["messages"] = [data["message"]]
        return data

    async def apply_live(
        self,
        emu: str = "eden",
        scope: str = "global",
        title: str = "",
        key: str = "",
        value: str = "",
        **kwargs: object,
    ) -> dict:
        if kwargs:
            emu = str(kwargs.get("emu", emu) or emu)
            scope = str(kwargs.get("scope", scope) or scope)
            title = str(kwargs.get("title", title) or title)
            key = str(kwargs.get("key", key) or key)
            value = str(kwargs.get("value", value) or value)
        return await self.set_setting(emu, scope, title, key, value, live=True)

    async def save_settings(
        self,
        emu: str = "eden",
        scope: str = "global",
        title: str = "",
        values: str = "{}",
        **kwargs: object,
    ) -> dict:
        if kwargs:
            emu = str(kwargs.get("emu", emu) or emu)
            scope = str(kwargs.get("scope", scope) or scope)
            title = str(kwargs.get("title", title) or title)
            values = str(kwargs.get("values", values) if kwargs.get("values") is not None else values)
        script = _script()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}"}
        emu = (emu or "eden").strip().lower()
        scope = (scope or "global").strip().lower()
        title = (title or "").strip()
        if emu not in ("eden", "azahar", "cemu"):
            return {"ok": False, "message": f"Unknown emu {emu}"}
        if scope not in ("global", "game"):
            return {"ok": False, "message": f"Unknown scope {scope}"}
        if isinstance(values, dict):
            payload = json.dumps(values)
        else:
            payload = str(values or "{}")
        cmd = [
            "python3",
            script,
            "save",
            "--emu",
            emu,
            "--scope",
            scope,
            "--values",
            payload,
        ]
        if title:
            cmd.extend(["--title", title])
        try:
            proc = _run_as_deck(cmd, timeout=25)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "emu-quick-settings save timed out"}
        data = _json_from(proc)
        if not data.get("messages") and data.get("message"):
            data["messages"] = [data["message"]]
        return data

    async def reset_settings(
        self,
        emu: str = "eden",
        scope: str = "global",
        title: str = "",
        **kwargs: object,
    ) -> dict:
        if kwargs:
            emu = str(kwargs.get("emu", emu) or emu)
            scope = str(kwargs.get("scope", scope) or scope)
            title = str(kwargs.get("title", title) or title)
        script = _script()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}"}
        emu = (emu or "eden").strip().lower()
        scope = (scope or "global").strip().lower()
        title = (title or "").strip()
        if emu not in ("eden", "azahar", "cemu"):
            return {"ok": False, "message": f"Unknown emu {emu}"}
        if scope not in ("global", "game"):
            return {"ok": False, "message": f"Unknown scope {scope}"}
        cmd = ["python3", script, "reset", "--emu", emu, "--scope", scope]
        if title:
            cmd.extend(["--title", title])
        try:
            proc = _run_as_deck(cmd, timeout=20)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "emu-quick-settings reset timed out"}
        data = _json_from(proc)
        if not data.get("messages") and data.get("message"):
            data["messages"] = [data["message"]]
        return data
