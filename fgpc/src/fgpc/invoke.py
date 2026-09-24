"""Run playbook scripts with a deck session bus. Never sudo systemctl --user."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from fgpc.playbook import scripts, session_env


@dataclass
class Result:
    rc: int
    stdout: str
    stderr: str
    data: object | None = None


def _cmd(path: Path, args: list[str]) -> list[str]:
    if path.suffix == ".py":
        return ["python3", str(path), *args]
    return [str(path), *args]


def run(
    name: str,
    args: list[str] | None = None,
    *,
    timeout: float | None = 45,
    json_out: bool = True,
    stream: bool = False,
) -> Result:
    path = scripts() / name
    if not path.is_file():
        return Result(1, "", f"missing {path}", None)
    cmd = _cmd(path, args or [])
    env = session_env()
    if stream:
        proc = subprocess.run(cmd, env=env, timeout=timeout)
        return Result(proc.returncode, "", "", None)
    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    data = None
    text = (proc.stdout or "").strip()
    if json_out and text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
    return Result(proc.returncode, proc.stdout or "", proc.stderr or "", data)


def run_root(name: str, args: list[str] | None = None, **kwargs: object) -> Result:
    """Same as run; name is relative to the playbook root (bootstrap.sh)."""
    path = scripts().parent / name
    if not path.is_file():
        return Result(1, "", f"missing {path}", None)
    cmd = _cmd(path, list(args or []))
    env = session_env()
    timeout = kwargs.get("timeout", 120)
    stream = bool(kwargs.get("stream", True))
    if stream:
        proc = subprocess.run(cmd, env=env, timeout=timeout)
        return Result(proc.returncode, "", "", None)
    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return Result(proc.returncode, proc.stdout or "", proc.stderr or "", None)


def die_if_missing(name: str) -> None:
    path = scripts() / name
    if not path.is_file():
        print(f"missing {path}", file=sys.stderr)
        raise SystemExit(1)
