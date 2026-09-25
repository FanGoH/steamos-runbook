#!/usr/bin/env python3
"""Prepare the USB BT dongle for NUXBT ↔ Switch 2.

Proven bring-up (2026-09-25): when Grip/Order advertise sits forever with no
ACL traffic, power-cycling ``hci1`` (off → on) then setting Pro Controller
name + gamepad CoD makes the Switch see the pad again.

Steps:
  1. Optional: ensure BlueZ ``--compat --noplugin=*`` override (NOPASSWD helper).
  2. Power **off** MT7922 ``hci0`` (onboard combo — NUXBT must not use it).
  3. Power-cycle TP-Link ``hci1`` (Powered=false → sleep → Powered=true).
  4. HCI Write Class ``0x002508`` (Peripheral / Gamepad).
  5. HCI Write Local Name ``Pro Controller``.

Env:
  ``NUXBT_ADAPTER`` — default ``/org/bluez/hci1``
  ``NUXBT_SKIP_RADIO_PREP=1`` — no-op (exit 0)
  ``NUXBT_RADIO_ENSURE_BLUEZ=0`` — skip override enable
  ``NUXBT_RADIO_POWER_CYCLE=0`` — only force Powered on (no off/on)

Used by ``nuxbt-api.py`` (Decky QAM Grip/Reconnect) and ``nuxbt-bridge.sh``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = os.environ.get("NUXBT_ADAPTER", "/org/bluez/hci1")
HCI0 = "/org/bluez/hci0"
HELPER = ROOT / "scripts" / "hide-controllers-sysfs.sh"


def _cap_python() -> str:
    home = Path(os.environ.get("HOME", str(Path.home())))
    cand = home / "code" / "nuxbt-host" / "bin" / "python3-nuxbt"
    if cand.is_file():
        return str(cand)
    return sys.executable


def _ensure_bluez() -> dict:
    override = Path("/run/systemd/system/bluetooth.service.d/nuxbt.conf")
    if override.is_file():
        return {"ok": True, "bluez": "already", "path": str(override)}
    if os.environ.get("NUXBT_RADIO_ENSURE_BLUEZ", "1").strip() in ("0", "false", "no"):
        return {"ok": True, "bluez": "skipped"}
    if not HELPER.is_file():
        return {"ok": False, "bluez": "missing helper", "path": str(HELPER)}
    proc = subprocess.run(
        ["sudo", "-n", str(HELPER), "nuxbt-bluez", "enable"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "ok": proc.returncode == 0 and override.is_file(),
        "bluez": "enabled" if proc.returncode == 0 else "enable-failed",
        "rc": proc.returncode,
        "stderr": (proc.stderr or "")[:200],
    }


def _prepare(adapter: str, *, power_cycle: bool) -> dict:
    """Run as capped python3-nuxbt so raw HCI name/class writes work."""
    script = f"""
import json, time, dbus
from nuxbt.bluez import BlueZ

adapter = {adapter!r}
hci0 = {HCI0!r}
power_cycle = {str(bool(power_cycle))}
bus = dbus.SystemBus()
out = {{"adapter": adapter, "power_cycle": power_cycle}}

def props(path):
    return dbus.Interface(bus.get_object("org.bluez", path),
                          "org.freedesktop.DBus.Properties")

# Onboard MT7922 stays down — NUXBT belongs on the USB dongle only.
try:
    props(hci0).Set("org.bluez.Adapter1", "Powered", dbus.Boolean(False))
    out["hci0_powered"] = False
except Exception as e:
    out["hci0_error"] = str(e)[:120]

p = props(adapter)
if power_cycle:
    try:
        p.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(False))
        time.sleep(1.0)
    except Exception as e:
        out["power_off_error"] = str(e)[:120]
p.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
time.sleep(0.45)
try:
    p.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(True))
    p.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))
except Exception as e:
    out["discoverable_error"] = str(e)[:120]

bz = BlueZ(adapter)
out["address"] = bz.address
bz.set_class("0x002508")
name = b"Pro Controller" + b"\\x00" * 200
bz._send_hci_command(0x03, 0x0013, name[:248])
out["name"] = "Pro Controller"
out["class"] = "0x002508"
out["ok"] = True
print(json.dumps(out))
"""
    py = _cap_python()
    # CAP_PY needs nuxbt on PYTHONPATH when not the venv interpreter
    env = os.environ.copy()
    site = Path(os.environ.get("HOME", str(Path.home()))) / "code" / "nuxbt-host" / ".venv"
    for cand in (
        site / "lib" / "python3.14" / "site-packages",
        site / "lib" / "python3.12" / "site-packages",
    ):
        if cand.is_dir():
            env["PYTHONPATH"] = str(cand) + (
                (":" + env["PYTHONPATH"]) if env.get("PYTHONPATH") else ""
            )
            break
    proc = subprocess.run(
        [py, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    if proc.returncode != 0:
        return {
            "ok": False,
            "message": (proc.stderr or proc.stdout or f"exit {proc.returncode}")[:300],
            "rc": proc.returncode,
        }
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return {"ok": False, "message": "empty prepare output"}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"ok": False, "message": lines[-1][:300]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", default=ADAPTER)
    ap.add_argument(
        "--no-power-cycle",
        action="store_true",
        help="only ensure Powered=on (no off→on)",
    )
    ap.add_argument("--json", action="store_true", help="always print one JSON line")
    args = ap.parse_args()

    if os.environ.get("NUXBT_SKIP_RADIO_PREP", "").strip() in ("1", "true", "yes"):
        out = {"ok": True, "skipped": True, "message": "NUXBT_SKIP_RADIO_PREP"}
        print(json.dumps(out), flush=True)
        return 0

    power_cycle = not args.no_power_cycle
    if os.environ.get("NUXBT_RADIO_POWER_CYCLE", "1").strip() in ("0", "false", "no"):
        power_cycle = False

    bluez = _ensure_bluez()
    radio = _prepare(args.adapter, power_cycle=power_cycle)
    out = {
        "ok": bool(radio.get("ok")),
        "bluez": bluez,
        "radio": radio,
        "message": (
            f"radio ready {radio.get('address', '?')} "
            f"(power_cycle={power_cycle}, bluez={bluez.get('bluez')})"
            if radio.get("ok")
            else radio.get("message") or "radio prepare failed"
        ),
    }
    print(json.dumps(out), flush=True)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
