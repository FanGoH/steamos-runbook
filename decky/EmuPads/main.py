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


def _bind_has_apply(script: str) -> bool:
    # apply lives near the argparse tail (~95k). An 8k prefix miss makes
    # fallback the last ~/worktrees/* copy, which has no set-enabled.
    try:
        text = open(script, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    return 'add_parser("apply"' in text or "add_parser('apply'" in text


def _playbook() -> str:
    home = _user_home()
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    bind = os.path.join("scripts", "bind-gamepad.py")
    playbook = os.path.join(home, "steamos-playbook")
    candidates: list[str] = []
    if env:
        candidates.append(env)
    candidates.append(playbook)
    wt = os.path.join(home, "worktrees")
    if os.path.isdir(wt):
        try:
            names = sorted(os.listdir(wt))
        except OSError:
            names = []
        for name in names:
            candidates.append(os.path.join(wt, name))
    fallback = playbook
    for cand in candidates:
        script = os.path.join(cand, bind)
        if os.path.isfile(script) and _bind_has_apply(script):
            return cand
        if os.path.isfile(script) and cand == playbook:
            fallback = cand
    return fallback


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
        # rc 2 is "empty / warn" from list/status, not a hard failure.
        data["ok"] = proc.returncode not in (1,)
    if isinstance(data, dict):
        data["rc"] = proc.returncode
    return data if isinstance(data, dict) else {"ok": False, "message": "bad json"}


def _looks_like_argparse_error(data: dict) -> bool:
    msg = str(data.get("message") or "").lower()
    return any(
        needle in msg
        for needle in ("invalid choice", "unrecognized arguments", "usage:", "the following arguments")
    )


def _status_or_list(script: str) -> dict:
    """Prefer ``status``. Fall back to ``list`` if that subcommand is missing.

    Checking out another playbook branch used to delete ``status`` from
    bind-gamepad.py. QAM then showed an empty pad list even with Odin up.
    """
    try:
        proc = _run_as_deck(["python3", script, "status"], timeout=15)
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "bind-gamepad status timed out", "pads": []}
    data = _json_from(proc)
    pads_ok = isinstance(data.get("pads"), list)
    failed = (not pads_ok) or data.get("ok") is False or _looks_like_argparse_error(data)
    if not failed:
        data.setdefault("pads", [])
        return data
    try:
        listed = _run_as_deck(["python3", script, "list"], timeout=10)
    except subprocess.TimeoutExpired:
        if not isinstance(data, dict):
            data = {"ok": False, "message": "bind-gamepad list timed out", "pads": []}
        data.setdefault("pads", [])
        return data
    listed_data = _json_from(listed)
    pads = listed_data.get("pads") if isinstance(listed_data.get("pads"), list) else []
    if not isinstance(data, dict):
        data = {}
    data["pads"] = pads
    data["ok"] = True
    if _looks_like_argparse_error(data):
        data.pop("message", None)
    data.setdefault("mux", {})
    data.setdefault("emus", {})
    if pads:
        data["pad_hint"] = ""
    else:
        data.setdefault(
            "pad_hint",
            "Moonlight Odin/Thor not connected. Reconnect, then Refresh pads.",
        )
    return data


class Plugin:
    async def _main(self) -> None:
        _log(f"Emu Pads plugin loaded (playbook={_playbook()})")

    async def get_status(self) -> dict:
        script = _bind_py()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}", "pads": []}
        return _status_or_list(script)

    async def set_mode(self, mode: str = "shared", **kwargs: object) -> dict:
        if kwargs:
            mode = str(kwargs.get("mode", mode) or mode)
        script = _bind_py()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}"}
        mode = (mode or "shared").strip().lower()
        if mode not in ("shared", "multi"):
            return {"ok": False, "message": f"Unknown mode {mode}"}
        try:
            proc = _run_as_deck(["python3", script, "set-mode", "--mode", mode], timeout=10)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "bind-gamepad set-mode timed out"}
        return _json_from(proc)

    async def set_enabled(self, enabled: object = True, **kwargs: object) -> dict:
        if kwargs:
            enabled = kwargs.get("enabled", enabled)
        script = _bind_py()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}"}
        flag = "on"
        if enabled is False or str(enabled).strip().lower() in (
            "0",
            "false",
            "no",
            "off",
        ):
            flag = "off"
        try:
            proc = _run_as_deck(
                ["python3", script, "set-enabled", "--enabled", flag],
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "bind-gamepad set-enabled timed out"}
        return _json_from(proc)

    async def apply(
        self,
        emu: str = "all",
        pads: str = "",
        mode: str = "shared",
        cemu_p1: str = "",
        restart: object = False,
        **kwargs: object,
    ) -> dict:
        if kwargs:
            emu = str(kwargs.get("emu", emu) or emu)
            pads = str(kwargs.get("pads", pads) or pads)
            mode = str(kwargs.get("mode", mode) or mode)
            cemu_p1 = str(kwargs.get("cemu_p1", cemu_p1) or cemu_p1)
            restart = kwargs.get("restart", restart)
        script = _bind_py()
        if not os.path.isfile(script):
            return {"ok": False, "message": f"Missing {script}"}
        emu = (emu or "all").strip().lower()
        pads = (pads or "").strip()
        mode = (mode or "shared").strip().lower()
        cemu_p1 = (cemu_p1 or "").strip().lower().replace(" ", "_")
        do_restart = restart is True or str(restart).strip().lower() in ("1", "true", "yes")
        if cemu_p1 in ("pro_controller", "wii_u_pro", "wii_u_pro_controller"):
            cemu_p1 = "pro"
        if mode not in ("shared", "multi"):
            return {"ok": False, "message": f"Unknown mode {mode}"}
        if emu not in ("all", "cemu", "azahar", "eden"):
            return {"ok": False, "message": f"Unknown emu {emu}"}
        if cemu_p1 and cemu_p1 not in ("gamepad", "pro"):
            return {"ok": False, "message": f"Unknown Cemu P1 type {cemu_p1}"}
        cmd = ["python3", script, "apply", "--emu", emu, "--force", "--mode", mode]
        if cemu_p1:
            cmd.extend(["--cemu-p1", cemu_p1])
        if pads:
            cmd.extend(["--pads", pads])
        else:
            cmd.append("--all-sources")
        if do_restart:
            cmd.append("--restart")
        timeout = 55 if do_restart else 25
        try:
            proc = _run_as_deck(cmd, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "bind-gamepad apply timed out"}
        data = _json_from(proc)
        if not data.get("messages") and data.get("message"):
            data["messages"] = [data["message"]]
        return data
