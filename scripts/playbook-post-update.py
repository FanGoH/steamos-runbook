#!/usr/bin/env python3
"""Start / status for ./post-update.sh (Decky Playbook + SSH).

PluginLoader is root — call this as user deck with the session bus.
Never sudo systemctl --user. Never pgrep -f sunshine.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

UNIT = "steamos-playbook-post-update"
UNIT_SERVICE = f"{UNIT}.service"
STATE_NAME = "playbook-post-update.json"
RESULTS_NAME = "post-update-results.txt"
MANUAL_NAME = "manual-actions-post-update.txt"


def playbook_root() -> Path:
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    home = Path(os.environ.get("HOME") or Path.home())
    candidates.append(home / "steamos-playbook")
    here = Path(__file__).resolve().parent.parent
    candidates.append(here)
    for cand in candidates:
        if (cand / "post-update.sh").is_file():
            return cand
    return candidates[0] if candidates else home / "steamos-playbook"


def logs_dir(root: Path | None = None) -> Path:
    path = (root or playbook_root()) / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(root: Path | None = None) -> Path:
    return logs_dir(root) / STATE_NAME


def results_path(root: Path | None = None) -> Path:
    return (root or playbook_root()) / "logs" / RESULTS_NAME


def manual_path(root: Path | None = None) -> Path:
    return (root or playbook_root()) / "logs" / MANUAL_NAME


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def summarize_results(text: str) -> dict[str, Any]:
    ok = warn = fail = 0
    steps: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        status, name, *rest = line.split("|")
        status = status.strip().upper()
        if status not in ("OK", "WARN", "FAIL"):
            continue
        rc = 0
        if rest:
            try:
                rc = int(rest[0])
            except ValueError:
                rc = 1
        steps.append({"status": status, "name": name, "rc": rc})
        if status == "OK":
            ok += 1
        elif status == "WARN":
            warn += 1
        else:
            fail += 1
    if fail:
        overall = "fail"
    elif warn:
        overall = "warn"
    elif ok:
        overall = "ok"
    else:
        overall = "idle"
    return {
        "overall": overall,
        "ok": ok,
        "warn": warn,
        "fail": fail,
        "steps": steps,
    }


def manual_excerpt(text: str, limit: int = 12) -> list[str]:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    return lines[:limit]


def latest_log(root: Path | None = None) -> str:
    folder = logs_dir(root)
    logs = sorted(folder.glob("post-update-*.log"))
    if not logs:
        return ""
    return str(logs[-1])


def unit_state() -> str:
    proc = subprocess.run(
        ["systemctl", "--user", "show", UNIT_SERVICE, "-p", "ActiveState", "--value"],
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "").strip() or "unknown"


def unit_running(state: str | None = None) -> bool:
    return (state or unit_state()) in ("active", "activating")


def drop_unit() -> None:
    subprocess.run(
        ["systemctl", "--user", "stop", UNIT_SERVICE],
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["systemctl", "--user", "reset-failed", UNIT_SERVICE],
        capture_output=True,
        text=True,
    )
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid() or 1000}"
    fragment = Path(runtime) / "systemd" / "transient" / UNIT_SERVICE
    try:
        fragment.unlink()
    except OSError:
        pass
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True,
        text=True,
    )


def cmd_status() -> dict[str, Any]:
    root = playbook_root()
    active = unit_state()
    running = unit_running(active)
    saved = read_json(state_path(root))
    if running:
        saved["running"] = True
    results = ""
    try:
        results = results_path(root).read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    summary = summarize_results(results)
    manual = ""
    try:
        manual = manual_path(root).read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    log = saved.get("log") or latest_log(root)
    if running:
        message = "post-update is running (a few minutes)."
    elif summary["overall"] == "fail" or saved.get("rc") not in (None, 0, "0"):
        message = saved.get("message") or "Last post-update had failures."
    elif summary["overall"] == "warn":
        message = saved.get("message") or "Last post-update finished with warnings."
    elif summary["overall"] == "ok":
        message = saved.get("message") or "Last post-update finished OK."
    else:
        message = "No post-update run yet."
    return {
        "ok": True,
        "running": running,
        "unit": active,
        "playbook": str(root),
        "log": log,
        "overall": "running" if running else summary["overall"],
        "ok_count": summary["ok"],
        "warn_count": summary["warn"],
        "fail_count": summary["fail"],
        "steps": summary["steps"][-12:],
        "manual": manual_excerpt(manual),
        "started": saved.get("started"),
        "finished": saved.get("finished"),
        "rc": saved.get("rc"),
        "message": message,
    }


def cmd_start() -> dict[str, Any]:
    if unit_running():
        data = cmd_status()
        data["message"] = "post-update already running."
        return data
    root = playbook_root()
    script = Path(__file__).resolve()
    if not (root / "post-update.sh").is_file():
        return {
            "ok": False,
            "running": False,
            "message": f"Missing {root / 'post-update.sh'}",
        }
    drop_unit()
    home = os.environ.get("HOME") or str(Path.home())
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid() or 1000}"
    bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={runtime}/bus"
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    write_json(
        state_path(root),
        {
            "running": True,
            "started": started,
            "finished": None,
            "rc": None,
            "log": "",
            "message": "Starting post-update…",
        },
    )
    cmd = [
        "systemd-run",
        "--user",
        "--collect",
        "--quiet",
        "--no-block",
        f"--unit={UNIT}",
        "--property=Type=oneshot",
        f"--property=WorkingDirectory={root}",
        f"--setenv=HOME={home}",
        "--setenv=USER=deck",
        f"--setenv=XDG_RUNTIME_DIR={runtime}",
        f"--setenv=DBUS_SESSION_BUS_ADDRESS={bus}",
        "--setenv=NO_COLOR=1",
        f"--setenv=STEAMOS_PLAYBOOK_DIR={root}",
        sys.executable,
        str(script),
        "--run",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:400]
        write_json(
            state_path(root),
            {
                "running": False,
                "started": started,
                "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
                "rc": proc.returncode,
                "message": err or "systemd-run failed",
            },
        )
        return {"ok": False, "running": False, "message": err or "systemd-run failed"}
    data = cmd_status()
    data["ok"] = True
    data["running"] = True
    data["message"] = "Started post-update. Leave QAM; reopen to see the result."
    return data


def cmd_run() -> int:
    root = playbook_root()
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    write_json(
        state_path(root),
        {
            "running": True,
            "started": started,
            "finished": None,
            "rc": None,
            "log": "",
            "message": "Running post-update…",
        },
    )
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    env["STEAMOS_PLAYBOOK_DIR"] = str(root)
    proc = subprocess.run(
        ["bash", str(root / "post-update.sh")],
        cwd=str(root),
        env=env,
    )
    finished = time.strftime("%Y-%m-%d %H:%M:%S")
    summary = summarize_results("")
    try:
        summary = summarize_results(
            results_path(root).read_text(encoding="utf-8", errors="replace")
        )
    except OSError:
        pass
    log = latest_log(root)
    if proc.returncode != 0 or summary["fail"]:
        overall = "fail"
        message = "post-update finished with failures. Check logs/manual actions."
    elif summary["warn"]:
        overall = "warn"
        message = "post-update finished with warnings."
    else:
        overall = "ok"
        message = "post-update finished OK."
    write_json(
        state_path(root),
        {
            "running": False,
            "started": started,
            "finished": finished,
            "rc": proc.returncode,
            "log": log,
            "overall": overall,
            "message": message,
        },
    )
    return proc.returncode


def self_test() -> int:
    text = "OK|ensure-pacman|0\nWARN|ensure-sunshine|2\nFAIL|ensure-sshd|1\n"
    summary = summarize_results(text)
    assert summary["ok"] == 1
    assert summary["warn"] == 1
    assert summary["fail"] == 1
    assert summary["overall"] == "fail"
    assert summarize_results("OK|a|0\n")["overall"] == "ok"
    assert summarize_results("")["overall"] == "idle"
    excerpt = manual_excerpt("## One\n# comment\n\n## Two\n", limit=2)
    assert excerpt == ["## One", "# comment"]
    root = playbook_root()
    assert (root / "post-update.sh").is_file(), f"missing post-update.sh under {root}"
    print("playbook-post-update self-test ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=("status", "start", "self-test"),
    )
    parser.add_argument("--run", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.run:
        return cmd_run()
    if args.command == "self-test":
        return self_test()
    if args.command == "start":
        print(json.dumps(cmd_start()))
        return 0
    print(json.dumps(cmd_status()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
