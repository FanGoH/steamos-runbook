#!/usr/bin/env python3
"""Pin the NUXBT adapter Bluetooth MAC (Switch Pro Con identity).

The Switch keys pairing by the *controller* BD_ADDR — which for NUXBT is the
USB dongle adapter address. Keep that MAC stable so day-to-day
``nuxbt-api reconnect`` works without Change Grip/Order.

Classic NXBT could call ``get_random_controller_mac()`` (Nintendo OUI
``7C:BB:8A:…``) on every create; a new MAC forces Grip every time. This
playbook never randomizes: it locks one address into
``~/.config/nuxbt/controller-mac`` and re-applies it after BlueZ override
restarts (spoofed MACs are lost on ``hciconfig reset`` / bluetoothd restart;
the dongle hardware MAC comes back on its own).

Resolution order:
  1. ``NUXBT_CONTROLLER_MAC`` env (also written to the config file)
  2. ``~/.config/nuxbt/controller-mac``
  3. Current adapter Address (locked into the config on first run)

Special env values:
  ``hardware`` / empty → use current adapter Address and lock it
  ``7C:BB:8A:DE:F0:01`` (or any fixed Nintendo-OUI) → spoof; needs one Grip
    the first time, then reconnect. Re-applied after every ``nuxbt-bluez enable``.

Usage:
  nuxbt-pin-controller-mac.py              # ensure pin (default)
  nuxbt-pin-controller-mac.py --print      # resolve + print JSON, no HCI write
  nuxbt-pin-controller-mac.py --force      # set even if Address already matches
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("HOME", str(Path.home())))
CONFIG_DIR = Path(os.environ.get("NUXBT_CONFIG_DIR", str(HOME / ".config" / "nuxbt")))
CONFIG_FILE = CONFIG_DIR / "controller-mac"
ADAPTER = os.environ.get("NUXBT_ADAPTER", "/org/bluez/hci1")
MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


def _normalize(mac: str) -> str:
    return mac.strip().upper()


def _valid(mac: str) -> bool:
    return bool(MAC_RE.match(mac))


def _adapter_id(path: str) -> str:
    return path.rstrip("/").split("/")[-1]


def _dbus_address(adapter: str) -> str:
    script = f"""
import dbus
bus = dbus.SystemBus()
p = dbus.Interface(bus.get_object("org.bluez", "{adapter}"),
                   "org.freedesktop.DBus.Properties")
print(p.Get("org.bluez.Adapter1", "Address"))
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            (proc.stderr or proc.stdout or "dbus Address failed").strip()[:300]
        )
    return _normalize(proc.stdout.strip().splitlines()[-1])


def _dbus_set_powered(adapter: str, on: bool) -> None:
    script = f"""
import dbus
bus = dbus.SystemBus()
p = dbus.Interface(bus.get_object("org.bluez", "{adapter}"),
                   "org.freedesktop.DBus.Properties")
p.Set("org.bluez.Adapter1", "Powered", dbus.Boolean({str(bool(on))}))
"""
    subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def _read_config() -> str | None:
    try:
        text = CONFIG_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text or text.splitlines()[0].startswith("#"):
        # allow comment header; first non-comment line wins
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                text = line
                break
        else:
            return None
    mac = _normalize(text.splitlines()[0])
    return mac if _valid(mac) else None


def _write_config(mac: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        "# NUXBT Pro Controller BD_ADDR (Switch pairing identity).\n"
        "# Changing this requires Controllers → Change Grip/Order + QAM Grip once.\n"
        f"{_normalize(mac)}\n",
        encoding="utf-8",
    )


def resolve_mac(adapter: str) -> tuple[str, str, bool]:
    """Return (desired_mac, source, changed_config)."""
    env = os.environ.get("NUXBT_CONTROLLER_MAC", "").strip()
    current = _dbus_address(adapter)

    if env and env.lower() not in ("hardware", "auto", "-"):
        mac = _normalize(env)
        if not _valid(mac):
            raise SystemExit(f"invalid NUXBT_CONTROLLER_MAC={env!r}")
        prev = _read_config()
        if prev != mac:
            _write_config(mac)
            return mac, "env", True
        return mac, "env", False

    locked = _read_config()
    if locked:
        return locked, "config", False

    # First run: lock the live adapter address (usually dongle hardware MAC).
    _write_config(current)
    return current, "hardware-lock", True


def set_address(adapter: str, mac: str) -> None:
    """Vendor HCI write + reset (same sequence as nuxbt.bluez.BlueZ.set_address)."""
    hci = _adapter_id(adapter)
    parts = _normalize(mac).split(":")
    cmd = [
        "hcitool",
        "-i",
        hci,
        "cmd",
        "0x3f",
        "0x001",
        f"0x{parts[5]}",
        f"0x{parts[4]}",
        f"0x{parts[3]}",
        f"0x{parts[2]}",
        f"0x{parts[1]}",
        f"0x{parts[0]}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if proc.returncode != 0 or (proc.stderr or "").strip():
        err = (proc.stderr or proc.stdout or "hcitool failed").strip()
        raise RuntimeError(f"hcitool set_address: {err[:300]}")
    proc = subprocess.run(
        ["hciconfig", hci, "reset"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "hciconfig reset failed").strip()
        raise RuntimeError(f"hciconfig reset: {err[:300]}")
    # BlueZ may drop Powered across reset — bring the adapter back.
    time.sleep(0.4)
    _dbus_set_powered(adapter, True)
    time.sleep(0.3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", default=ADAPTER)
    ap.add_argument("--print", action="store_true", help="JSON only; no HCI write")
    ap.add_argument("--force", action="store_true", help="set even if already matching")
    args = ap.parse_args()

    try:
        before = _dbus_address(args.adapter)
    except Exception as e:
        print(json.dumps({"ok": False, "message": str(e)}), flush=True)
        return 1

    try:
        desired, source, wrote = resolve_mac(args.adapter)
    except SystemExit as e:
        print(json.dumps({"ok": False, "message": str(e)}), flush=True)
        return 2

    out = {
        "ok": True,
        "adapter": args.adapter,
        "before": before,
        "controller_mac": desired,
        "source": source,
        "config": str(CONFIG_FILE),
        "config_written": wrote,
        "changed": False,
        "grip_required": False,
    }

    if args.print:
        out["message"] = f"controller MAC {desired} ({source})"
        print(json.dumps(out), flush=True)
        return 0

    need = args.force or before != desired
    if not need:
        out["message"] = f"controller MAC already {desired} ({source})"
        print(json.dumps(out), flush=True)
        return 0

    try:
        set_address(args.adapter, desired)
        after = _dbus_address(args.adapter)
    except Exception as e:
        out["ok"] = False
        out["message"] = str(e)
        print(json.dumps(out), flush=True)
        return 1

    out["after"] = after
    out["changed"] = after != before
    out["grip_required"] = after != before
    if after != desired:
        out["ok"] = False
        out["message"] = (
            f"wanted {desired} but adapter reports {after} "
            "(dongle may ignore vendor MAC write)"
        )
        print(json.dumps(out), flush=True)
        return 1

    out["message"] = (
        f"set controller MAC {before} → {after} ({source}); "
        "open Change Grip/Order and run Grip once if this is a new address"
        if out["changed"]
        else f"controller MAC {after} ({source})"
    )
    print(json.dumps(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
