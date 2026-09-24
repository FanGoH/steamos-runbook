#!/usr/bin/env python3
"""JSON API for Switch 2 / NUXBT bridge (SSH + Decky).

Commands:
  status
  start [--grip]
  stop
  grip          # advertise + L+R (hard restart via user systemd)
  reconnect     # MAC reconnect (hard restart via user systemd)

Does not touch EmuPads, Sunshine ports, or dual-stream. PluginLoader must
run this as user deck (BlueZ + systemd --user live in the session).

Hard start uses ``systemd-run --user`` so Decky/PluginLoader (root cgroup)
cannot kill the bridge when the QAM callable returns — that was why Grip in
QAM left ``state=stopped`` while the same CLI command worked.
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
UNIT = "nuxbt-bridge.service"
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
    return bool(_bridge_pids())


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


def _user_bus_env() -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(HOME)
    env["USER"] = env.get("USER") or "deck"
    env["XDG_RUNTIME_DIR"] = str(RUNTIME)
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={RUNTIME}/bus"
    env["STEAMOS_PLAYBOOK_DIR"] = str(ROOT)
    env["NUXBT_ADAPTER"] = ADAPTER
    env["NUXBT_SWITCH_MAC"] = SWITCH_MAC
    env["PATH"] = env.get("PATH") or "/usr/bin:/bin"
    # Ensure common bins even if PluginLoader handed us a root-ish PATH.
    for p in ("/usr/bin", "/bin", "/usr/local/bin", str(HOME / ".local" / "bin")):
        if p not in env["PATH"].split(":"):
            env["PATH"] = f"{p}:{env['PATH']}"
    return env


def _systemctl_user(*args: str, timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_user_bus_env(),
    )


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
    # Prefer leaving PluginLoader's cgroup: stop the user unit first.
    _systemctl_user("stop", UNIT)
    _systemctl_user("reset-failed", UNIT)
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
            # Still starting, or died — distinguish briefly.
            if last not in ("connecting", "reconnecting", "connected"):
                last = "stopped"
            elif time.time() + 1.0 >= deadline and not bridge_running():
                last = "stopped"
        time.sleep(0.4)
    return last


def _wait_for_mode(extra: list[str]) -> float:
    """Grip needs a longer window — Switch must be on Change Grip/Order."""
    if "--grip" in extra:
        return float(os.environ.get("NUXBT_GRIP_WAIT_S", "45"))
    return float(os.environ.get("NUXBT_RECONNECT_WAIT_S", "12"))


def _launch_via_systemd(extra: list[str]) -> tuple[bool, str]:
    """Start bridge under systemd --user (survives Decky/PluginLoader)."""
    args = " ".join(extra)
    inner = (
        f"PYTHONUNBUFFERED=1 {BRIDGE_SH} {args} 2>&1 | tee {OUT}; "
        f"echo EXIT:$? >> {OUT}"
    )
    cmd = [
        "systemd-run",
        "--user",
        "--collect",
        f"--unit={SESSION}",
        f"--working-directory={ROOT}",
        "--property=Type=simple",
        "--property=KillMode=process",
        f"--setenv=HOME={HOME}",
        "--setenv=USER=deck",
        f"--setenv=XDG_RUNTIME_DIR={RUNTIME}",
        f"--setenv=DBUS_SESSION_BUS_ADDRESS=unix:path={RUNTIME}/bus",
        f"--setenv=STEAMOS_PLAYBOOK_DIR={ROOT}",
        f"--setenv=NUXBT_ADAPTER={ADAPTER}",
        f"--setenv=NUXBT_SWITCH_MAC={SWITCH_MAC}",
        "/bin/bash",
        "-lc",
        inner,
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=20, env=_user_bus_env()
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:300]
        return False, err or "systemd-run failed"
    return True, "systemd"


def _launch_via_tmux(extra: list[str]) -> tuple[bool, str]:
    conf = ["-f", TMUX_CONF] if Path(TMUX_CONF).is_file() else []
    _tmux("kill-session", "-t", SESSION)
    args = " ".join(extra)
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
        f"PYTHONUNBUFFERED=1 {BRIDGE_SH} {args} 2>&1 | tee {OUT}; echo EXIT:$?; exec bash -l",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=15, env=_user_bus_env()
    )
    if proc.returncode == 0:
        return True, "tmux"
    return False, (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[:300]


def _start_bridge(extra: list[str], *, wait: bool = True) -> dict:
    if not BRIDGE_SH.is_file():
        return _err(f"missing {BRIDGE_SH}")
    _stop_bridge()
    try:
        OUT.write_text("", encoding="utf-8")
    except OSError:
        pass

    via = "hard"
    ok_launch, detail = _launch_via_systemd(extra)
    if not ok_launch:
        ok_tmux, tmux_detail = _launch_via_tmux(extra)
        if ok_tmux:
            via = "tmux"
            detail = tmux_detail
        else:
            # Last resort: bare Popen outside PluginLoader wait (new session).
            try:
                log = open(OUT, "w", encoding="utf-8")
            except OSError as e:
                return _err(
                    f"start failed (systemd: {detail}; tmux: {tmux_detail}; out: {e})"
                )
            bg = subprocess.Popen(
                ["bash", "-lc", f"PYTHONUNBUFFERED=1 {BRIDGE_SH} {' '.join(extra)}"],
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=str(ROOT),
                start_new_session=True,
                env=_user_bus_env(),
            )
            via = "popen"
            detail = f"pid {bg.pid}"
            state = _wait_connected(_wait_for_mode(extra)) if wait else "started"
            return _ok(
                message=f"started {detail} (fallback); state={state}",
                pid=bg.pid,
                mode="grip" if "--grip" in extra else "reconnect",
                state=state,
                via=via,
                log_tail=_tail_out(25),
            )

    for _ in range(20):
        time.sleep(0.5)
        if bridge_running():
            break
    wait_s = _wait_for_mode(extra)
    state = _wait_connected(wait_s) if wait else ("running" if bridge_running() else "unknown")
    mode = "grip/advertise" if "--grip" in extra else "reconnect"
    ok = state == "connected" or bridge_running()
    tips = []
    if "--grip" in extra and state != "connected" and bridge_running():
        tips.append(
            "Still advertising — on the Switch open Controllers → Change Grip/Order, "
            "then: python3 scripts/nuxbt-api.py status"
        )
    return {
        "ok": ok,
        "message": f"started {mode}; state={state}",
        "running": bridge_running(),
        "mode": "grip" if "--grip" in extra else "reconnect",
        "state": state,
        "via": via,
        "launch": detail,
        "wait_s": wait_s if wait else 0,
        "log_tail": _tail_out(25),
        "tips": tips,
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
