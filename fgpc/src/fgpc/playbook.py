"""Locate the playbook and a deck session environment."""

from __future__ import annotations

import os
from pathlib import Path


def playbook_root() -> Path:
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    here = Path(__file__).resolve()
    home = Path(os.environ.get("HOME") or "/home/deck")
    candidates = []
    if env:
        candidates.append(Path(env))
    # fgpc/src/fgpc/playbook.py → repo root
    candidates.append(here.parents[3])
    candidates.append(home / "steamos-playbook")
    for cand in candidates:
        if (cand / "scripts" / "bind-gamepad.py").is_file():
            return cand
    return candidates[-1]


def scripts() -> Path:
    return playbook_root() / "scripts"


def session_env() -> dict[str, str]:
    env = os.environ.copy()
    uid = os.getuid()
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    env["XDG_RUNTIME_DIR"] = runtime
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    env.setdefault("HOME", str(Path.home()))
    env.setdefault("USER", os.environ.get("USER") or "deck")
    env.setdefault("STEAMOS_PLAYBOOK_DIR", str(playbook_root()))
    env.pop("LD_PRELOAD", None)
    return env
