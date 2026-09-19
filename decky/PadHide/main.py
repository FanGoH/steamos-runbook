"""Decky plugin: hide host pads from Steam/games without unplugging.

PluginLoader is root, so the script writes USB ``authorized`` / HID unbind
directly (SSH as deck needs ``sudoers/zzz-hide-controllers``). Do not
``sudo systemctl --user``. Do not ``pgrep -f`` sunshine. The pad driving
QAM cannot hide itself — ``hide-controllers.py`` refuses that without
``--force``, and this plugin never passes ``--force``.
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


def _has_set(script: str) -> bool:
    try:
        text = open(script, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    return 'add_parser("set"' in text or "add_parser('set'" in text


def _playbook() -> str:
    home = _user_home()
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    script = os.path.join("scripts", "hide-controllers.py")
    candidates: list[str] = []
    if env:
        candidates.append(env)
    candidates.append(os.path.join(home, "steamos-playbook"))
    candidates.append(os.path.join(home, "homebrew", "data", "PadHide"))
    fallback = os.path.join(home, "steamos-playbook")
    for cand in candidates:
        path = os.path.join(cand, script)
        if os.path.isfile(path) and _has_set(path):
            return cand
        if os.path.isfile(path) and cand == fallback:
            fallback = cand
    return fallback


def _script() -> str:
    return os.path.join(_playbook(), "scripts", "hide-controllers.py")


def _log(msg: str) -> None:
    if decky is None:
        return
    logger = getattr(decky, "logger", None)
    if logger is not None:
        logger.info(msg)


def _run_script(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    """Stay root when PluginLoader is root so sysfs writes work without sudoers."""
    uid = _session_uid()
    runtime = f"/run/user/{uid}"
    home = _user_home()
    prefix = [
        "env",
        f"HOME={home}",
        "USER=deck",
        f"PAD_HIDE_HOME={home}",
        f"XDG_RUNTIME_DIR={runtime}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
        "LD_PRELOAD=",
    ]
    cmd = [*prefix, "python3", _script(), *args]
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
        return {"ok": False, "message": err, "rc": proc.returncode, "pads": []}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        err = (proc.stderr or text)[:400]
        return {"ok": False, "message": err, "rc": proc.returncode, "pads": []}
    if isinstance(data, dict) and "ok" not in data:
        data["ok"] = proc.returncode == 0
    if isinstance(data, dict):
        data["rc"] = proc.returncode
        data.setdefault("pads", [])
    return data if isinstance(data, dict) else {"ok": False, "message": "bad json", "pads": []}


def _missing_backend() -> dict:
    return {
        "ok": False,
        "message": "Pad Hide backend missing. Run ./scripts/ensure-pad-hide-decky.sh",
        "pads": [],
    }


class Plugin:
    async def _main(self) -> None:
        _log(f"Pad Hide plugin loaded (playbook={_playbook()})")

    async def get_status(self) -> dict:
        script = _script()
        if not os.path.isfile(script):
            return _missing_backend()
        try:
            proc = _run_script(["status"], timeout=12)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "hide-controllers status timed out", "pads": []}
        return _json_from(proc)

    async def set_hidden(self, pad_id: str = "", hidden: object = True, **kwargs: object) -> dict:
        if kwargs:
            pad_id = str(kwargs.get("pad_id", kwargs.get("id", pad_id)) or pad_id)
            hidden = kwargs.get("hidden", hidden)
        script = _script()
        if not os.path.isfile(script):
            return _missing_backend()
        pad_id = (pad_id or "").strip()
        if not pad_id:
            return {"ok": False, "message": "Missing pad id", "pads": []}
        flag = "hide"
        if hidden is False or str(hidden).strip().lower() in (
            "0",
            "false",
            "no",
            "show",
            "on",
            "visible",
        ):
            flag = "show"
        try:
            proc = _run_script(["set", "--id", pad_id, "--hidden", flag], timeout=12)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "hide-controllers set timed out", "pads": []}
        return _json_from(proc)
