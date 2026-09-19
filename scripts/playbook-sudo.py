#!/usr/bin/env python3
"""One-shot sudo askpass for QAM Playbook (password is never logged).

PluginLoader writes the password to $XDG_RUNTIME_DIR/playbook-sudo/ (tmpfs),
then systemd-run --user inherits SUDO_ASKPASS so the deck oneshot can sudo
without a TTY. Clear after the run. Do not put the password on argv or in JSON.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import tempfile


def deck_user() -> pwd.struct_passwd:
    name = os.environ.get("STEAMOS_USER") or os.environ.get("USER") or "deck"
    try:
        return pwd.getpwnam(name)
    except KeyError:
        return pwd.getpwuid(os.getuid())


def runtime_dir() -> Path:
    override = os.environ.get("PLAYBOOK_SUDO_DIR")
    if override:
        return Path(override)
    uid = deck_user().pw_uid
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    return Path(base) / "playbook-sudo"


def pass_path(folder: Path | None = None) -> Path:
    return (folder or runtime_dir()) / "pass"


def askpass_path(folder: Path | None = None) -> Path:
    return (folder or runtime_dir()) / "askpass"


def _chown_deck(path: Path) -> None:
    if os.getuid() != 0:
        return
    info = deck_user()
    try:
        os.chown(path, info.pw_uid, info.pw_gid)
    except OSError:
        pass


def write_password(password: str, folder: Path | None = None) -> dict[str, str]:
    secret = (password or "").strip("\n")
    if not secret:
        raise ValueError("empty sudo password")
    dest = folder or runtime_dir()
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    _chown_deck(dest)
    secret_path = pass_path(dest)
    secret_path.write_text(secret + "\n", encoding="utf-8")
    os.chmod(secret_path, 0o600)
    _chown_deck(secret_path)
    helper = askpass_path(dest)
    helper.write_text(
        "#!/bin/sh\nexec cat -- {path}\n".format(path=json.dumps(str(secret_path))),
        encoding="utf-8",
    )
    os.chmod(helper, 0o700)
    _chown_deck(helper)
    return {"askpass": str(helper), "dir": str(dest)}


def clear_password(folder: Path | None = None) -> None:
    dest = folder or runtime_dir()
    secret_path = pass_path(dest)
    try:
        if secret_path.is_file():
            secret_path.write_bytes(b"\0" * max(secret_path.stat().st_size, 1))
            secret_path.unlink()
    except OSError:
        pass
    helper = askpass_path(dest)
    try:
        helper.unlink()
    except OSError:
        pass
    try:
        dest.rmdir()
    except OSError:
        pass


def verify_password(folder: Path | None = None) -> bool:
    helper = askpass_path(folder)
    if not helper.is_file() or not os.access(helper, os.X_OK):
        return False
    env = dict(os.environ)
    env["SUDO_ASKPASS"] = str(helper)
    cmd = ["sudo", "-A", "-k", "-p", "", "true"]
    if os.getuid() == 0:
        info = deck_user()
        cmd = [
            "runuser",
            "-u",
            info.pw_name,
            "--",
            "env",
            f"SUDO_ASKPASS={helper}",
            "sudo",
            "-A",
            "-k",
            "-p",
            "",
            "true",
        ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    return proc.returncode == 0


def cmd_write() -> int:
    secret = sys.stdin.read()
    try:
        paths = write_password(secret)
    except ValueError as exc:
        print(json.dumps({"ok": False, "message": str(exc)}))
        return 2
    print(json.dumps({"ok": True, "askpass": paths["askpass"]}))
    return 0


def cmd_verify() -> int:
    ok = verify_password()
    print(json.dumps({"ok": ok, "message": "" if ok else "sudo password was rejected"}))
    return 0 if ok else 1


def cmd_clear() -> int:
    clear_password()
    print(json.dumps({"ok": True}))
    return 0


def self_test() -> int:
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td) / "playbook-sudo"
        os.environ["PLAYBOOK_SUDO_DIR"] = str(folder)
        try:
            write_password("")
            raise AssertionError("empty password must fail")
        except ValueError:
            pass
        paths = write_password("not-the-real-password")
        assert Path(paths["askpass"]).is_file()
        assert pass_path(folder).read_text(encoding="utf-8") == "not-the-real-password\n"
        mode = stat.S_IMODE(pass_path(folder).stat().st_mode)
        assert mode == 0o600, oct(mode)
        helper = askpass_path(folder).read_text(encoding="utf-8")
        assert "not-the-real-password" not in helper
        dumped = json.dumps(paths)
        assert "not-the-real-password" not in dumped
        clear_password(folder)
        assert not pass_path(folder).exists()
    print("playbook-sudo self-test ok")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "write":
        return cmd_write()
    if cmd == "verify":
        return cmd_verify()
    if cmd == "clear":
        return cmd_clear()
    if cmd == "self-test":
        return self_test()
    print(json.dumps({"ok": False, "message": f"unknown command {cmd}"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
