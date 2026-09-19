"""Decky plugin: run the SteamOS playbook post-update.sh.

PluginLoader runs as root. Call ``scripts/playbook-post-update.py`` as user
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


def _snapshot() -> str:
    return os.path.join(_user_home(), "homebrew", "data", "Playbook")


def _playbook() -> str:
    home = _user_home()
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    script = os.path.join("scripts", "playbook-post-update.py")
    post = "post-update.sh"
    candidates: list[str] = []
    if env:
        candidates.append(env)
    candidates.append(os.path.join(home, "steamos-playbook"))
    candidates.append(_snapshot())
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, script)) and os.path.isfile(
            os.path.join(cand, post)
        ):
            return cand
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, script)):
            return cand
    return candidates[0] if candidates else os.path.join(home, "steamos-playbook")


def _script() -> str:
    return os.path.join(_playbook(), "scripts", "playbook-post-update.py")


def _log(msg: str) -> None:
    if decky is None:
        return
    logger = getattr(decky, "logger", None)
    if logger is not None:
        logger.info(msg)


def _sudo_script() -> str:
    return os.path.join(_playbook(), "scripts", "playbook-sudo.py")


def _clear_sudo() -> None:
    script = _sudo_script()
    if not os.path.isfile(script):
        return
    subprocess.run(
        ["python3", script, "clear"],
        capture_output=True,
        text=True,
        timeout=8,
    )


def _prepare_sudo(password: object) -> dict:
    secret = str(password or "")
    if not secret.strip():
        return {"ok": False, "message": "Enter your sudo password first."}
    script = _sudo_script()
    if not os.path.isfile(script):
        return {"ok": False, "message": "playbook-sudo.py missing. Re-run ensure-playbook-decky.sh"}
    try:
        written = subprocess.run(
            ["python3", script, "write"],
            input=secret,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "sudo password write timed out"}
    data = _json_from(written)
    if data.get("ok") is False:
        return {
            "ok": False,
            "message": data.get("message") or "could not store sudo password",
        }
    try:
        checked = subprocess.run(
            ["python3", script, "verify"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        _clear_sudo()
        return {"ok": False, "message": "sudo password check timed out"}
    verified = _json_from(checked)
    if verified.get("ok") is False:
        _clear_sudo()
        return {"ok": False, "message": "sudo password was rejected"}
    askpass = str(data.get("askpass") or "")
    if not askpass:
        _clear_sudo()
        return {"ok": False, "message": "sudo askpass helper missing"}
    return {"ok": True, "askpass": askpass}


def _run_as_deck(
    args: list[str],
    timeout: int = 20,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    uid = _session_uid()
    runtime = f"/run/user/{uid}"
    prefix = [
        "env",
        f"HOME={_user_home()}",
        "USER=deck",
        f"XDG_RUNTIME_DIR={runtime}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
        "LD_PRELOAD=",
        f"STEAMOS_PLAYBOOK_DIR={_playbook()}",
    ]
    for key, value in (extra_env or {}).items():
        if key in ("PASSWORD", "SUDO_PASSWORD") or not value:
            continue
        prefix.append(f"{key}={value}")
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


def _missing_backend() -> dict:
    return {
        "ok": False,
        "running": False,
        "message": "Playbook backend missing. Run ./scripts/ensure-playbook-decky.sh",
    }


class Plugin:
    async def _main(self) -> None:
        _log(f"Playbook plugin loaded (playbook={_playbook()})")

    async def get_status(self) -> dict:
        script = _script()
        if not os.path.isfile(script):
            return _missing_backend()
        try:
            proc = _run_as_deck(["python3", script, "status"], timeout=12)
        except subprocess.TimeoutExpired:
            return {"ok": False, "running": False, "message": "playbook status timed out"}
        return _json_from(proc)

    async def run_post_update(self, password: str = "", **kwargs: object) -> dict:
        if kwargs:
            password = str(kwargs.get("password", password) or password)
        script = _script()
        if not os.path.isfile(script):
            return _missing_backend()
        prep = _prepare_sudo(password)
        if prep.get("ok") is False:
            return prep
        try:
            proc = _run_as_deck(
                ["python3", script, "start"],
                timeout=20,
                extra_env={"SUDO_ASKPASS": str(prep.get("askpass") or "")},
            )
        except subprocess.TimeoutExpired:
            _clear_sudo()
            return {"ok": False, "running": False, "message": "start post-update timed out"}
        data = _json_from(proc)
        if data.get("ok") is False:
            _clear_sudo()
        return data

    async def update_tender(self, password: str = "", **kwargs: object) -> dict:
        if kwargs:
            password = str(kwargs.get("password", password) or password)
        script = _script()
        if not os.path.isfile(script):
            return _missing_backend()
        prep = _prepare_sudo(password)
        if prep.get("ok") is False:
            return prep
        try:
            proc = _run_as_deck(
                ["python3", script, "tender-start"],
                timeout=20,
                extra_env={"SUDO_ASKPASS": str(prep.get("askpass") or "")},
            )
        except subprocess.TimeoutExpired:
            _clear_sudo()
            return {
                "ok": False,
                "running": False,
                "message": "start Tender update timed out",
            }
        data = _json_from(proc)
        if data.get("ok") is False:
            _clear_sudo()
        return data
