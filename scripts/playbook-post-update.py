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
TENDER_UNIT = "steamos-playbook-tender"
TENDER_UNIT_SERVICE = f"{TENDER_UNIT}.service"
STATE_NAME = "playbook-post-update.json"
TENDER_STATE_NAME = "playbook-tender.json"
RESULTS_NAME = "post-update-results.txt"
MANUAL_NAME = "manual-actions-post-update.txt"
WRAP_MARKERS = ("CEMU_GAMEMODE_DS", "HOST_EDEN_MIN_BYTES", "ensure-azahar-gamemode-dual-screen")


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


def tender_state_path(root: Path | None = None) -> Path:
    return logs_dir(root) / TENDER_STATE_NAME


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
    ok = warn = fail = skip = 0
    steps: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        status, name, *rest = line.split("|")
        status = status.strip().upper()
        if status not in ("OK", "WARN", "FAIL", "SKIP"):
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
        elif status == "SKIP":
            skip += 1
        else:
            fail += 1
    if fail:
        overall = "fail"
    elif warn:
        overall = "warn"
    elif ok or skip:
        overall = "ok"
    else:
        overall = "idle"
    return {
        "overall": overall,
        "ok": ok,
        "warn": warn,
        "fail": fail,
        "skip": skip,
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


def unit_state(service: str = UNIT_SERVICE) -> str:
    proc = subprocess.run(
        ["systemctl", "--user", "show", service, "-p", "ActiveState", "--value"],
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "").strip() or "unknown"


def unit_running(state: str | None = None, service: str = UNIT_SERVICE) -> bool:
    return (state or unit_state(service)) in ("active", "activating")


def tender_running() -> bool:
    return unit_running(service=TENDER_UNIT_SERVICE)


def drop_unit(service: str = UNIT_SERVICE) -> None:
    subprocess.run(
        ["systemctl", "--user", "stop", service],
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["systemctl", "--user", "reset-failed", service],
        capture_output=True,
        text=True,
    )
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid() or 1000}"
    fragment = Path(runtime) / "systemd" / "transient" / service
    try:
        fragment.unlink()
    except OSError:
        pass
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        capture_output=True,
        text=True,
    )


def tender_plugin_dir() -> Path:
    env = os.environ.get("TENDER_PLUGIN_DIR")
    if env:
        return Path(env)
    home = Path(os.environ.get("HOME") or Path.home())
    return home / "homebrew" / "plugins" / "romm-tender"


def launcher_paths() -> list[Path]:
    home = Path(os.environ.get("HOME") or Path.home())
    dest = tender_plugin_dir() / "bin" / "rom-launcher"
    leftover = home / "homebrew" / "plugins" / "decky-romm-sync" / "bin" / "rom-launcher"
    return [dest, leftover]


def launcher_wrapped(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(marker in text for marker in WRAP_MARKERS)


def installed_tender_version(plugin_dir: Path | None = None) -> str:
    path = (plugin_dir or tender_plugin_dir()) / "plugin.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("version") or "").strip()


def parse_tender_output(text: str) -> dict[str, Any]:
    installed = ""
    wanted = ""
    finished = ""
    needs_update: bool | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Tender installed:"):
            installed = line.split(":", 1)[1].strip()
            if installed in ("none", "?", ""):
                installed = ""
        elif line.startswith("Tender wanted:"):
            rest = line.split(":", 1)[1].strip()
            wanted = rest.split()[0] if rest else ""
            if wanted in ("?", ""):
                wanted = ""
        elif line.startswith("needs_update:"):
            needs_update = "yes" in line.lower()
        elif line.startswith("Tender is "):
            bits = line.split()
            if len(bits) >= 3:
                finished = bits[2]
    if finished:
        installed = finished
        needs_update = False
    return {
        "installed": installed,
        "wanted": wanted,
        "needs_update": needs_update,
    }


def wrap_status() -> dict[str, Any]:
    paths = {}
    any_wrap = False
    present = False
    for path in launcher_paths():
        exists = path.is_file()
        wrapped = launcher_wrapped(path) if exists else False
        paths[str(path)] = {"exists": exists, "wrapped": wrapped}
        present = present or exists
        any_wrap = any_wrap or wrapped
    return {"wrapped": any_wrap, "present": present, "paths": paths}


def tender_payload(root: Path | None = None) -> dict[str, Any]:
    root = root or playbook_root()
    saved = read_json(tender_state_path(root))
    running = tender_running()
    wrap = wrap_status()
    installed = installed_tender_version() or str(saved.get("installed") or "")
    wanted = str(saved.get("wanted") or "")
    needs = saved.get("needs_update")
    if running:
        message = saved.get("message") or "Updating Tender and re-wrapping rom-launcher…"
    elif saved.get("message"):
        message = str(saved["message"])
    elif wrap["wrapped"]:
        message = f"Tender {installed or 'installed'} · playbook wrap on."
    elif wrap["present"]:
        message = f"Tender {installed or 'installed'} · stock rom-launcher (wrap needed)."
    else:
        message = "Tender plugin not installed yet."
    return {
        "installed": installed,
        "wanted": wanted,
        "needs_update": bool(needs) if needs is not None else False,
        "wrapped": wrap["wrapped"],
        "running": running,
        "message": message,
        "log": saved.get("log") or "",
        "rc": saved.get("rc"),
    }


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
        "skip_count": summary["skip"],
        "steps": summary["steps"][-12:],
        "manual": manual_excerpt(manual),
        "started": saved.get("started"),
        "finished": saved.get("finished"),
        "rc": saved.get("rc"),
        "message": message,
        "tender": tender_payload(root),
    }


def cmd_start() -> dict[str, Any]:
    if unit_running():
        data = cmd_status()
        data["message"] = "post-update already running."
        return data
    if tender_running():
        data = cmd_status()
        data["ok"] = False
        data["message"] = "Tender update is running. Wait, then run post-update."
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


def _session_env() -> tuple[str, str, str]:
    home = os.environ.get("HOME") or str(Path.home())
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid() or 1000}"
    bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={runtime}/bus"
    return home, runtime, bus


def cmd_tender_start() -> dict[str, Any]:
    if tender_running():
        data = cmd_status()
        data["message"] = "Tender update already running."
        return data
    if unit_running():
        data = cmd_status()
        data["ok"] = False
        data["message"] = "post-update is running (it already updates Tender)."
        return data
    root = playbook_root()
    script = Path(__file__).resolve()
    ensure = root / "scripts" / "ensure-tender.sh"
    if not ensure.is_file():
        return {
            "ok": False,
            "running": False,
            "message": f"Missing {ensure}",
        }
    drop_unit(TENDER_UNIT_SERVICE)
    home, runtime, bus = _session_env()
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    write_json(
        tender_state_path(root),
        {
            "running": True,
            "started": started,
            "finished": None,
            "rc": None,
            "log": "",
            "installed": installed_tender_version(),
            "message": "Starting Tender update + rom-launcher wrap…",
        },
    )
    cmd = [
        "systemd-run",
        "--user",
        "--collect",
        "--quiet",
        "--no-block",
        f"--unit={TENDER_UNIT}",
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
        "--run-tender",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:400]
        write_json(
            tender_state_path(root),
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
    data["message"] = "Started Tender update + wrap. Leave QAM; reopen to see the result."
    return data


def cmd_run_tender() -> int:
    root = playbook_root()
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    log = logs_dir(root) / time.strftime("tender-%Y%m%d-%H%M%S.log")
    write_json(
        tender_state_path(root),
        {
            "running": True,
            "started": started,
            "finished": None,
            "rc": None,
            "log": str(log),
            "installed": installed_tender_version(),
            "message": "Updating Tender and re-wrapping rom-launcher…",
        },
    )
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    env["STEAMOS_PLAYBOOK_DIR"] = str(root)
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            ["bash", str(root / "scripts" / "ensure-tender.sh")],
            cwd=str(root),
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
        )
    output = ""
    try:
        output = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    parsed = parse_tender_output(output)
    wrap = wrap_status()
    finished = time.strftime("%Y-%m-%d %H:%M:%S")
    if proc.returncode not in (0, 2):
        message = "Tender update failed. Check logs/manual actions."
    elif proc.returncode == 2:
        message = (
            "Tender finished with warnings (often sudo cp for root-owned plugins)."
        )
    elif wrap["wrapped"]:
        ver = parsed.get("installed") or installed_tender_version()
        message = f"Tender {ver or 'ok'} · playbook wrap on."
    else:
        message = "Tender finished; rom-launcher wrap still missing (sudo cp)."
    write_json(
        tender_state_path(root),
        {
            "running": False,
            "started": started,
            "finished": finished,
            "rc": proc.returncode,
            "log": str(log),
            "installed": parsed.get("installed") or installed_tender_version(),
            "wanted": parsed.get("wanted") or "",
            "needs_update": bool(parsed.get("needs_update")),
            "wrapped": wrap["wrapped"],
            "message": message,
        },
    )
    return 0 if proc.returncode in (0, 2) else proc.returncode


def self_test() -> int:
    text = "OK|ensure-pacman|0\nWARN|ensure-sunshine|2\nFAIL|ensure-sshd|1\n"
    summary = summarize_results(text)
    assert summary["ok"] == 1
    assert summary["warn"] == 1
    assert summary["fail"] == 1
    assert summary["overall"] == "fail"
    assert summarize_results("OK|a|0\n")["overall"] == "ok"
    skipped = summarize_results("OK|a|0\nSKIP|ensure-switch2-controllers|0\n")
    assert skipped["skip"] == 1
    assert skipped["overall"] == "ok"
    assert summarize_results("SKIP|ensure-switch2-controllers|0\n")["overall"] == "ok"
    assert summarize_results("")["overall"] == "idle"
    excerpt = manual_excerpt("## One\n# comment\n\n## Two\n", limit=2)
    assert excerpt == ["## One", "# comment"]
    parsed = parse_tender_output(
        "Tender installed: 0.31.0\n"
        "Tender wanted: 0.33.0 (tender-v0.33.0)\n"
        "needs_update: yes\n"
        "Tender is 0.33.0 (was 0.31.0).\n"
    )
    assert parsed["installed"] == "0.33.0"
    assert parsed["wanted"] == "0.33.0"
    assert parsed["needs_update"] is False
    behind = parse_tender_output(
        "Tender installed: 0.31.0\nneeds_update: yes\n"
    )
    assert behind["needs_update"] is True
    assert behind["installed"] == "0.31.0"
    stock = "#!/bin/sh\nexec /usr/bin/flatpak run net.retrodeck.retrodeck \"$@\"\n"
    wrap = "export CEMU_GAMEMODE_DS=1\nHOST_EDEN_MIN_BYTES=1\n"
    tmp = logs_dir() / "playbook-tender-self-test-launcher"
    tmp.write_text(stock, encoding="utf-8")
    assert launcher_wrapped(tmp) is False
    tmp.write_text(wrap, encoding="utf-8")
    assert launcher_wrapped(tmp) is True
    tmp.unlink(missing_ok=True)
    root = playbook_root()
    assert (root / "post-update.sh").is_file(), f"missing post-update.sh under {root}"
    assert (root / "scripts" / "ensure-tender.sh").is_file()
    print("playbook-post-update self-test ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=("status", "start", "tender-start", "self-test"),
    )
    parser.add_argument("--run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run-tender", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.run_tender:
        return cmd_run_tender()
    if args.run:
        return cmd_run()
    if args.command == "self-test":
        return self_test()
    if args.command == "start":
        print(json.dumps(cmd_start()))
        return 0
    if args.command == "tender-start":
        print(json.dumps(cmd_tender_start()))
        return 0
    print(json.dumps(cmd_status()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
