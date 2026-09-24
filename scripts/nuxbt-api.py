#!/usr/bin/env python3
"""JSON API for Switch 2 / NUXBT bridge (SSH + Decky).

Commands:
  status
  start [--grip]
  stop
  grip          # advertise + L+R (touch want-grip, or start --grip if down)
  reconnect     # MAC reconnect request / start

Does not touch EmuPads, Sunshine ports, or dual-stream. PluginLoader must
run this as user deck (BlueZ + tmux live in the session).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("HOME", str(Path.home())))
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
BRIDGE_SH = ROOT / "scripts" / "nuxbt-bridge.sh"
OUT = Path(os.environ.get("NUXBT_BRIDGE_OUT", "/tmp/nuxbt-bridge.out"))
WANT_GRIP = RUNTIME / "nuxbt-want-grip"
WANT_RECONNECT = RUNTIME / "nuxbt-want-reconnect"
TMUX_CONF = "/exec-daemon/tmux.portal.conf"
SESSION = "nuxbt-bridge"
SWITCH_MAC = os.environ.get("NUXBT_SWITCH_MAC", "48:F1:EB:C3:F4:85")
ADAPTER = os.environ.get("NUXBT_ADAPTER", "/org/bluez/hci1")


def _ok(data: dict | None = None, **extra) -> dict:
    out = {"ok": True, **(data or {}), **extra}
    return out


def _err(message: str, **extra) -> dict:
    return {"ok": False, "message": message, **extra}


def _tmux(*args: str) -> subprocess.CompletedProcess:
    cmd = ["tmux"]
    if Path(TMUX_CONF).is_file():
        cmd += ["-f", TMUX_CONF]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10)


def bridge_running() -> bool:
    proc = subprocess.run(
        ["pgrep", "-f", "scripts/nuxbt-sunshine-bridge.py"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _tail_out(n: int = 40) -> str:
    try:
        lines = OUT.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])


def _parse_state(text: str) -> str:
    state = ""
    for line in text.splitlines():
        if line.startswith("state="):
            state = line.split("=", 1)[1].strip()
    return state


def _bluez_switch() -> dict:
    mac = SWITCH_MAC.replace(":", "_")
    path = f"/org/bluez/hci1/dev_{mac}"
    script = f"""
import json
import dbus
bus = dbus.SystemBus()
out = {{"path": "{path}", "present": False, "connected": False, "paired": False}}
try:
    om = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
    objects = om.GetManagedObjects()
    for obj_path, ifaces in objects.items():
        if "org.bluez.Adapter1" in ifaces and str(obj_path).endswith("/hci1"):
            a = ifaces["org.bluez.Adapter1"]
            out["adapter_address"] = str(a.get("Address", ""))
            out["adapter_powered"] = bool(a.get("Powered", False))
            out["adapter_alias"] = str(a.get("Alias", ""))
        if str(obj_path) != "{path}":
            continue
        if "org.bluez.Device1" not in ifaces:
            continue
        d = ifaces["org.bluez.Device1"]
        out["present"] = True
        out["address"] = str(d.get("Address", ""))
        out["name"] = str(d.get("Name", d.get("Alias", "")))
        out["connected"] = bool(d.get("Connected", False))
        out["paired"] = bool(d.get("Paired", False))
except Exception as e:
    out["error"] = str(e)
print(json.dumps(out))
"""
    py = HOME / "code" / "nuxbt-host" / "bin" / "python3-nuxbt"
    if not py.is_file():
        py = Path(sys.executable)
    try:
        proc = subprocess.run(
            [str(py), "-c", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"present": False, "error": str(e)}
    return {
        "present": False,
        "error": (proc.stderr or proc.stdout or "bluez query failed")[:200],
    }


def _sunshine_source() -> dict | None:
    try:
        from evdev import InputDevice, list_devices
    except ImportError:
        return None
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        name = dev.name or ""
        if "Sunshine" in name and "libvirtualhid" in name.lower():
            return {
                "path": dev.path,
                "name": name,
                "vid": f"{dev.info.vendor:04x}",
                "pid": f"{dev.info.product:04x}",
            }
    return None


def cmd_status(_: argparse.Namespace) -> dict:
    running = bridge_running()
    tail = _tail_out()
    state = _parse_state(tail) if running else ""
    switch = _bluez_switch()
    source = _sunshine_source()
    messages = []
    if running and state:
        messages.append(f"NUXBT {state}")
    elif running:
        messages.append("bridge running")
    else:
        messages.append("bridge stopped")
    if switch.get("connected"):
        messages.append("Switch BT connected")
    elif switch.get("paired"):
        messages.append("Switch paired (not connected)")
    elif switch.get("present"):
        messages.append("Switch device present")
    else:
        messages.append("Switch not on hci1")
    if source:
        messages.append(f"source {source.get('name')}")
    else:
        messages.append("no Sunshine pad")
    return _ok(
        running=running,
        state=state or ("stopped" if not running else "unknown"),
        adapter=ADAPTER,
        switch_mac=SWITCH_MAC,
        switch=switch,
        source=source,
        want_grip=WANT_GRIP.is_file(),
        want_reconnect=WANT_RECONNECT.is_file(),
        log_tail=tail[-800:],
        message="; ".join(messages),
        tips=[
            "Grip/Order: stay on that Switch screen, then Grip (advertise + L+R).",
            "Day-to-day: Start / Reconnect (MAC). Auto-recovers on drop.",
            f"SSH: touch {WANT_GRIP} or {WANT_RECONNECT}",
        ],
    )


def _bridge_pids() -> list[int]:
    """PIDs of the real bridge python only — never shells that merely mention it."""
    proc = subprocess.run(
        ["pgrep", "-af", "nuxbt-sunshine-bridge.py"],
        capture_output=True,
        text=True,
    )
    out: list[int] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pid_s, cmd = line.split(None, 1)
            pid = int(pid_s)
        except ValueError:
            continue
        # Require the interpreter running the script (not bash/tmux/agent wrappers).
        if "nuxbt-sunshine-bridge.py" not in cmd:
            continue
        if not (cmd.startswith("python") or "/python" in cmd.split()[0]):
            continue
        if "nuxbt-api.py" in cmd or "fix-nuxbt" in cmd:
            continue
        out.append(pid)
    return out


def _stop_bridge() -> None:
    _tmux("kill-session", "-t", SESSION)
    pids = _bridge_pids()
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    time.sleep(0.8)
    for pid in _bridge_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    time.sleep(0.3)


def _wait_connected(timeout_s: float = 12.0) -> str:
    """Poll bridge log / process until connected or timeout."""
    deadline = time.time() + timeout_s
    last = "unknown"
    while time.time() < deadline:
        tail = _tail_out(30)
        st = _parse_state(tail) or last
        last = st or last
        if st == "connected":
            return st
        if not bridge_running():
            last = "stopped"
        time.sleep(0.4)
    return last


def _start_bridge(extra: list[str], *, wait: bool = True) -> dict:
    if not BRIDGE_SH.is_file():
        return _err(f"missing {BRIDGE_SH}")
    _stop_bridge()
    try:
        OUT.write_text("", encoding="utf-8")
    except OSError:
        pass
    # Prefer portal tmux so agents can inspect; fall back to plain tmux / no-tmux
    conf = ["-f", TMUX_CONF] if Path(TMUX_CONF).is_file() else []
    _tmux("kill-session", "-t", SESSION)
    cmd = [
        "tmux",
        *conf,
        "new-session",
        "-d",
        "-s",
        SESSION,
        "-c",
        str(ROOT),
        "--",
        "bash",
        "-lc",
        f"PYTHONUNBUFFERED=1 {BRIDGE_SH} {' '.join(extra)} 2>&1 | tee {OUT}; echo EXIT:$?; exec bash -l",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if proc.returncode != 0:
        # plain bash background fallback (no portal tmux)
        log = open(OUT, "w", encoding="utf-8")
        bg = subprocess.Popen(
            ["bash", "-lc", f"PYTHONUNBUFFERED=1 {BRIDGE_SH} {' '.join(extra)}"],
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            start_new_session=True,
        )
        state = _wait_connected(12.0) if wait else "started"
        return _ok(
            message=f"started pid {bg.pid} (no tmux); state={state}",
            pid=bg.pid,
            mode="grip" if "--grip" in extra else "reconnect",
            state=state,
            via="hard",
            log_tail=_tail_out(25),
        )
    for _ in range(20):
        time.sleep(0.5)
        if bridge_running():
            break
    state = _wait_connected(12.0) if wait else ("running" if bridge_running() else "unknown")
    mode = "grip/advertise" if "--grip" in extra else "reconnect"
    ok = state == "connected" or bridge_running()
    return {
        "ok": ok,
        "message": f"started {mode}; state={state}",
        "running": bridge_running(),
        "mode": "grip" if "--grip" in extra else "reconnect",
        "state": state,
        "via": "hard",
        "log_tail": _tail_out(25),
    }


def cmd_start(ns: argparse.Namespace) -> dict:
    extra = ["--grip"] if getattr(ns, "grip", False) else []
    return _start_bridge(extra)


def cmd_stop(_: argparse.Namespace) -> dict:
    _stop_bridge()
    return _ok(message="stopped", running=bridge_running(), via="hard")


def cmd_grip(ns: argparse.Namespace) -> dict:
    """Advertise + L+R. Default: hard restart (QAM-reliable). --soft = flag only."""
    if getattr(ns, "soft", False) and bridge_running():
        WANT_GRIP.touch()
        return _ok(
            message="requested advertise + L+R (nuxbt-want-grip)",
            running=True,
            via="flag",
        )
    return _start_bridge(["--grip"])


def cmd_reconnect(ns: argparse.Namespace) -> dict:
    """MAC reconnect. Default: hard restart (QAM-reliable). --soft = flag only."""
    if getattr(ns, "soft", False) and bridge_running():
        WANT_RECONNECT.touch()
        return _ok(
            message="requested MAC reconnect (nuxbt-want-reconnect)",
            running=True,
            via="flag",
        )
    return _start_bridge([])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p_start = sub.add_parser("start")
    p_start.add_argument("--grip", action="store_true")
    sub.add_parser("stop")
    p_grip = sub.add_parser("grip")
    p_grip.add_argument(
        "--soft",
        action="store_true",
        help="only touch nuxbt-want-grip (weaker; default is hard restart)",
    )
    p_re = sub.add_parser("reconnect")
    p_re.add_argument(
        "--soft",
        action="store_true",
        help="only touch nuxbt-want-reconnect (weaker; default is hard restart)",
    )
    ns = ap.parse_args()
    handlers = {
        "status": cmd_status,
        "start": cmd_start,
        "stop": cmd_stop,
        "grip": cmd_grip,
        "reconnect": cmd_reconnect,
    }
    try:
        result = handlers[ns.cmd](ns)
    except Exception as e:
        result = _err(str(e))
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
