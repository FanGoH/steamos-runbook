#!/usr/bin/env python3
"""Bridge Sunshine/Moonlight pad → NUXBT Pro Controller (Switch 2).

Reads the host Sunshine virtual pad via evdev (no EVIOCGRAB — Steam needs it
for overlay/QAM) and feeds NUXBT set_controller_input at ~120 Hz.

USB note: NUXBT talks to the Switch over classic Bluetooth HID only. A USB
dongle here is the *host BT radio*, not a USB link to the Switch. USB gadget
HID would be a different stack (deferred fallback in the skill).

Locked rules (switch2-remote-play skill):
  - Prefer Sunshine libvirtualhid pad; skip Steam 28de:11ff and EmuPads
  - EmuPads should already be off for Switch RP
  - Face buttons map by *position* (Xbox south→Switch B, etc.)
"""
from __future__ import annotations

import argparse
import os
import random
import signal
import sys
import time
from typing import Any

from evdev import InputDevice, ecodes, list_devices
from nuxbt.nuxbt import PRO_CONTROLLER, Nuxbt

ADAPTER = os.environ.get("NUXBT_ADAPTER", "/org/bluez/hci1")
SWITCH = os.environ.get("NUXBT_SWITCH_MAC", "48:F1:EB:C3:F4:85")
HZ = float(os.environ.get("NUXBT_BRIDGE_HZ", "120"))
TRIGGER_AXIS_THRESHOLD = int(os.environ.get("NUXBT_TRIGGER_AXIS_THRESHOLD", "128"))
STICK_DEADZONE = float(os.environ.get("NUXBT_STICK_DEADZONE", "0.08"))
LOG = os.environ.get("NUXBT_BRIDGE_LOG", "/tmp/nuxbt-bridge.log")

# Steam virtual / EmuPads — never treat as the Moonlight source
SKIP_VID_PID = {
    (0x28DE, 0x11FF),  # Steam virtual
    (0x1209, 0xE301),  # EmuPads P1
    (0x1209, 0xE302),  # EmuPads P2
}

# Xbox/Sunshine face → Switch face by physical position
FACE = {
    ecodes.BTN_SOUTH: "B",  # A / south
    ecodes.BTN_EAST: "A",   # B / east
    ecodes.BTN_WEST: "Y",   # X / west
    ecodes.BTN_NORTH: "X",  # Y / north
}


def _log(msg: str) -> None:
    print(msg, flush=True)


def find_sunshine_pad(prefer: str | None = None) -> InputDevice:
    """Pick the Sunshine Moonlight pad. Prefer libvirtualhid Sunshine name."""
    prefer = (prefer or os.environ.get("NUXBT_SOURCE_EVENT") or "").strip()
    if prefer:
        dev = InputDevice(prefer)
        _log(f"source: forced {dev.path} ({dev.name})")
        return dev

    candidates: list[InputDevice] = []
    sunshine: list[InputDevice] = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        vid, pid = int(dev.info.vendor), int(dev.info.product)
        if (vid, pid) in SKIP_VID_PID:
            continue
        caps = dev.capabilities()
        if ecodes.EV_ABS not in caps or ecodes.EV_KEY not in caps:
            continue
        keys = caps.get(ecodes.EV_KEY, [])
        if ecodes.BTN_SOUTH not in keys and ecodes.BTN_A not in keys:
            continue
        name = dev.name or ""
        if "Sunshine" in name or "libvirtualhid" in name.lower():
            sunshine.append(dev)
        elif vid == 0x045E:  # Microsoft / Sunshine x360 ghost
            candidates.append(dev)
        elif "X-Box" in name or "Xbox" in name:
            candidates.append(dev)

    if sunshine:
        dev = sunshine[0]
        _log(f"source: {dev.path} ({dev.name}) vid={dev.info.vendor:04x} pid={dev.info.product:04x}")
        return dev
    if candidates:
        dev = candidates[0]
        _log(f"source: {dev.path} ({dev.name}) vid={dev.info.vendor:04x} pid={dev.info.product:04x}")
        return dev
    raise SystemExit(
        "No Sunshine/Xbox pad found. Connect Moonlight first "
        "(expect Sunshine libvirtualhid or 045e:*)."
    )


def _abs_codes(dev: InputDevice) -> set[int]:
    """EV_ABS codes for a device (evdev may return raw codes or (code, AbsInfo))."""
    raw = dev.capabilities().get(ecodes.EV_ABS, [])
    out: set[int] = set()
    for item in raw:
        if isinstance(item, tuple):
            out.add(int(item[0]))
        else:
            out.add(int(item))
    return out


def _axis_norm(value: int, info: Any, invert: bool = False) -> int:
    """Map abs axis to NUXBT stick -100..100 with deadzone."""
    # Prefer hardware min/max; fall back to signed int16 (Sunshine/x360).
    if info is not None:
        minimum = int(info.min)
        maximum = int(info.max)
    else:
        minimum, maximum = -32768, 32767
    if maximum == minimum:
        return 0
    # Symmetric signed axes: treat 0 as center (not (min+max)/2 == -0.5).
    if minimum < 0 < maximum and abs(minimum + maximum) <= 1:
        half = float(max(abs(minimum), abs(maximum)))
        ratio = value / half
    else:
        mid = (maximum + minimum) / 2.0
        half = (maximum - minimum) / 2.0
        if half <= 0:
            return 0
        ratio = (value - mid) / half
    if invert:
        ratio = -ratio
    if abs(ratio) < STICK_DEADZONE:
        return 0
    if ratio > 1.0:
        ratio = 1.0
    elif ratio < -1.0:
        ratio = -1.0
    return int(round(ratio * 100))


def _trigger_pressed(buttons: dict[int, int], abs_vals: dict[int, int], btn: int, axis: int) -> bool:
    if buttons.get(btn, 0):
        return True
    return abs_vals.get(axis, 0) >= TRIGGER_AXIS_THRESHOLD


def build_packet(nx: Nuxbt, buttons: dict[int, int], abs_vals: dict[int, int], absinfo: dict) -> dict:
    pkt = nx.create_input_packet()
    for code, name in FACE.items():
        pkt[name] = bool(buttons.get(code, 0))

    pkt["L"] = bool(buttons.get(ecodes.BTN_TL, 0))
    pkt["R"] = bool(buttons.get(ecodes.BTN_TR, 0))
    pkt["ZL"] = _trigger_pressed(buttons, abs_vals, ecodes.BTN_TL2, ecodes.ABS_Z)
    pkt["ZR"] = _trigger_pressed(buttons, abs_vals, ecodes.BTN_TR2, ecodes.ABS_RZ)
    pkt["PLUS"] = bool(buttons.get(ecodes.BTN_START, 0))
    pkt["MINUS"] = bool(buttons.get(ecodes.BTN_SELECT, 0))
    pkt["HOME"] = bool(buttons.get(ecodes.BTN_MODE, 0))
    # No Capture on x360 — leave False

    pkt["L_STICK"]["PRESSED"] = bool(buttons.get(ecodes.BTN_THUMBL, 0))
    pkt["R_STICK"]["PRESSED"] = bool(buttons.get(ecodes.BTN_THUMBR, 0))

    # Linux ABS_Y / ABS_RY: up is negative → invert for NUXBT (Y+ = up)
    pkt["L_STICK"]["X_VALUE"] = _axis_norm(abs_vals.get(ecodes.ABS_X, 0), absinfo.get(ecodes.ABS_X))
    pkt["L_STICK"]["Y_VALUE"] = _axis_norm(
        abs_vals.get(ecodes.ABS_Y, 0), absinfo.get(ecodes.ABS_Y), invert=True
    )
    pkt["R_STICK"]["X_VALUE"] = _axis_norm(abs_vals.get(ecodes.ABS_RX, 0), absinfo.get(ecodes.ABS_RX))
    pkt["R_STICK"]["Y_VALUE"] = _axis_norm(
        abs_vals.get(ecodes.ABS_RY, 0), absinfo.get(ecodes.ABS_RY), invert=True
    )

    hat_x = abs_vals.get(ecodes.ABS_HAT0X, 0)
    hat_y = abs_vals.get(ecodes.ABS_HAT0Y, 0)
    pkt["DPAD_LEFT"] = hat_x < 0
    pkt["DPAD_RIGHT"] = hat_x > 0
    pkt["DPAD_UP"] = hat_y < 0
    pkt["DPAD_DOWN"] = hat_y > 0
    return pkt


def wait_connected(nx: Nuxbt, idx: int, timeout: float = 0.0) -> None:
    """Wait until NUXBT reports connected. timeout=0 means wait forever."""
    start = time.time()
    last = None
    while True:
        st = nx.state[idx].get("state")
        if st != last:
            _log(f"state={st}")
            if st == "connecting":
                _log("advertising — open Switch Controllers → Change Grip/Order if it does not auto-join")
            last = st
        if st == "connected":
            return
        if st == "crashed":
            raise SystemExit(f"NUXBT crashed: {nx.state[idx].get('errors')}")
        if timeout > 0 and time.time() - start > timeout:
            raise SystemExit(f"timed out waiting for connected (last={st})")
        time.sleep(0.25)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", default=ADAPTER)
    ap.add_argument("--switch", default=SWITCH, help="Switch BT MAC for reconnect")
    ap.add_argument("--source", default=None, help="/dev/input/eventN override")
    ap.add_argument("--no-reconnect", action="store_true", help="advertise only (Grip/Order)")
    ap.add_argument("--hz", type=float, default=HZ)
    args = ap.parse_args()

    period = 1.0 / max(args.hz, 30.0)

    _log(f"NUXBT Sunshine bridge adapter={args.adapter} switch={args.switch}")
    nx = Nuxbt(debug=False, log_file_path=LOG)
    adapters = nx.get_available_adapters()
    _log(f"adapters: {adapters}")
    if args.adapter not in adapters:
        raise SystemExit(f"{args.adapter} missing")

    reconnect = None if args.no_reconnect else args.switch
    idx = nx.create_controller(
        PRO_CONTROLLER,
        args.adapter,
        colour_body=[random.randint(0, 255) for _ in range(3)],
        colour_buttons=[random.randint(0, 255) for _ in range(3)],
        reconnect_address=reconnect,
    )
    _log(f"controller {idx} created")
    wait_connected(nx, idx)

    # Source pad may appear only after Moonlight is up — retry briefly
    source = None
    for attempt in range(1, 31):
        try:
            source = find_sunshine_pad(args.source)
            break
        except SystemExit as e:
            if attempt == 30:
                raise
            _log(f"waiting for Sunshine pad ({attempt}/30): {e}")
            time.sleep(1.0)
    assert source is not None

    # Snapshot absinfo once; re-open if the node disappears
    want_abs = (
        ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY,
        ecodes.ABS_Z, ecodes.ABS_RZ, ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y,
    )
    present = _abs_codes(source)
    absinfo = {}
    for code in want_abs:
        if code not in present:
            continue
        try:
            absinfo[code] = source.absinfo(code)
        except OSError:
            continue
    _log(f"abs axes: {sorted(absinfo.keys())}")

    buttons: dict[int, int] = {}
    abs_vals: dict[int, int] = {
        ecodes.ABS_X: 0, ecodes.ABS_Y: 0, ecodes.ABS_RX: 0, ecodes.ABS_RY: 0,
        ecodes.ABS_Z: 0, ecodes.ABS_RZ: 0, ecodes.ABS_HAT0X: 0, ecodes.ABS_HAT0Y: 0,
    }
    # Seed current abs positions
    try:
        for code, info in absinfo.items():
            abs_vals[code] = int(info.value)
    except Exception:
        pass

    stop = False

    def _stop(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    _log(f"bridging at {args.hz:.0f} Hz (no EVIOCGRAB). Ctrl-C to stop.")
    last_active = False
    while not stop:
        # Drain pending events without blocking the 120 Hz loop
        try:
            while True:
                event = source.read_one()
                if event is None:
                    break
                if event.type == ecodes.EV_KEY:
                    buttons[event.code] = 1 if event.value else 0
                elif event.type == ecodes.EV_ABS:
                    abs_vals[event.code] = event.value
        except OSError as e:
            _log(f"source lost ({e}); reopening…")
            time.sleep(0.5)
            try:
                source = find_sunshine_pad(args.source)
                present = _abs_codes(source)
                absinfo = {}
                for code in want_abs:
                    if code not in present:
                        continue
                    try:
                        absinfo[code] = source.absinfo(code)
                    except OSError:
                        continue
            except SystemExit as err:
                _log(str(err))
                time.sleep(1.0)
                continue

        if nx.state[idx].get("state") != "connected":
            st = nx.state[idx].get("state")
            _log(f"NUXBT state={st}; waiting")
            if st == "crashed":
                return 1
            time.sleep(0.5)
            continue

        pkt = build_packet(nx, buttons, abs_vals, absinfo)
        nx.set_controller_input(idx, pkt)

        active = any(
            pkt[k] for k in (
                "A", "B", "X", "Y", "L", "R", "ZL", "ZR",
                "PLUS", "MINUS", "HOME", "CAPTURE",
                "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
            )
        ) or pkt["L_STICK"]["PRESSED"] or pkt["R_STICK"]["PRESSED"] or any(
            abs(pkt[s][a]) > 0 for s in ("L_STICK", "R_STICK") for a in ("X_VALUE", "Y_VALUE")
        )
        if active != last_active:
            _log("input: active" if active else "input: idle")
            last_active = active

        time.sleep(period)

    _log("stopping")
    return 0


if __name__ == "__main__":
    sys.exit(main())
