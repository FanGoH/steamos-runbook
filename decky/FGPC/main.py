"""Decky plugin: QAM catalog for fgpc (stream / screen / pad / hide).

PluginLoader is root. ``fgpc-api.py dump`` and stream/screen/pad/saves run
as user deck. Hide mutates stay root so USB ``authorized`` works without
sudoers. Never ``--force``. Never ``sudo systemctl --user``. Never
``pgrep -f`` sunshine. host / mode / bootstrap stay SSH ``fgpc`` only.
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
    return os.path.join(_user_home(), "homebrew", "data", "FGPC")


def _has_api(root: str) -> bool:
    return os.path.isfile(os.path.join(root, "scripts", "fgpc-api.py")) and os.path.isfile(
        os.path.join(root, "fgpc", "src", "fgpc", "api.py")
    )


def _playbook() -> str:
    home = _user_home()
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    candidates: list[str] = []
    if env:
        candidates.append(env)
    candidates.append(os.path.join(home, "steamos-playbook"))
    candidates.append(_snapshot())
    for cand in candidates:
        if _has_api(cand):
            return cand
    return candidates[0] if candidates else os.path.join(home, "steamos-playbook")


def _script() -> str:
    return os.path.join(_playbook(), "scripts", "fgpc-api.py")


def _log(msg: str) -> None:
    if decky is None:
        return
    logger = getattr(decky, "logger", None)
    if logger is not None:
        logger.info(msg)


def _env_prefix() -> list[str]:
    uid = _session_uid()
    runtime = f"/run/user/{uid}"
    return [
        "env",
        f"HOME={_user_home()}",
        "USER=deck",
        f"XDG_RUNTIME_DIR={runtime}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
        "LD_PRELOAD=",
        f"STEAMOS_PLAYBOOK_DIR={_playbook()}",
    ]


def _run(args: list[str], *, as_deck: bool, timeout: int) -> subprocess.CompletedProcess:
    prefix = _env_prefix()
    inner = [*prefix, "python3", _script(), *args]
    if as_deck and os.getuid() == 0:
        cmd = ["runuser", "-u", "deck", "--", *inner]
    else:
        cmd = inner
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
        "message": "FGPC backend missing. Run ./scripts/ensure-fgpc-decky.sh",
        "tips": [],
        "qam": [],
        "pads": [],
        "windows": [],
    }


class Plugin:
    async def _main(self) -> None:
        _log(f"FGPC plugin loaded (playbook={_playbook()})")

    async def get_status(self) -> dict:
        script = _script()
        if not os.path.isfile(script):
            return _missing_backend()
        try:
            proc = _run(["dump"], as_deck=True, timeout=18)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "fgpc-api dump timed out", "tips": []}
        return _json_from(proc)

    async def run_action(
        self,
        group: str = "",
        action: str = "",
        pad_id: str = "",
        mode: str = "",
        emu: str = "",
        display: str = "",
        target: str = "",
        hidden: object = "",
        **kwargs: object,
    ) -> dict:
        if kwargs:
            group = str(kwargs.get("group", group) or group)
            action = str(kwargs.get("action", action) or action)
            pad_id = str(kwargs.get("pad_id", kwargs.get("id", pad_id)) or pad_id)
            mode = str(kwargs.get("mode", mode) or mode)
            emu = str(kwargs.get("emu", emu) or emu)
            display = str(kwargs.get("display", display) or display)
            target = str(kwargs.get("target", target) or target)
            hidden = kwargs.get("hidden", hidden)
        script = _script()
        if not os.path.isfile(script):
            return _missing_backend()
        group = (group or "").strip().lower()
        action = (action or "").strip().lower()
        if not group or not action:
            return {"ok": False, "message": "Missing group/action"}
        if group in ("host", "mode", "complete", "decky") or action in (
            "bootstrap",
            "post-update",
            "complete",
        ):
            return {
                "ok": False,
                "message": f"{group} {action} is SSH-only (fgpc). QAM skips those.",
            }

        args = ["run", group, action]
        pad_id = (pad_id or "").strip()
        mode = (mode or "").strip()
        emu = (emu or "").strip()
        display = (display or "").strip()
        target = (target or "").strip()
        if pad_id:
            args.extend(["--id", pad_id])
        if mode:
            args.extend(["--mode", mode])
        if emu:
            args.extend(["--emu", emu])
        if display:
            args.extend(["--display", display])
        if target:
            args.extend(["--target", target])
        if hidden not in ("", None):
            args.extend(["--hidden", str(hidden)])

        # Hide sysfs writes stay root. Everything else is user deck.
        as_deck = group != "hide"
        timeout = 90 if group == "stream" else 25
        try:
            proc = _run(args, as_deck=as_deck, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": f"fgpc-api {group} {action} timed out"}
        return _json_from(proc)
