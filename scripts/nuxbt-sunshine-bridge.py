#!/usr/bin/env python3
"""Bridge Sunshine/Moonlight pad → NUXBT Pro Controller (Switch 2).

Reads host Sunshine/Moonlight pads via evdev (no EVIOCGRAB — Steam needs them
for overlay/QAM) and feeds NUXBT set_controller_input at ~120 Hz.

Mux-like: NUXBT↔Switch is the long-lived sink. Sunshine/Odin pads are hotplug
sources — Moonlight drop sends idle to the Switch; when Odin reconnects, the
same NUXBT controller picks the new event node up without re-pairing.

USB note: NUXBT talks to the Switch over classic Bluetooth HID only. A USB
dongle here is the *host BT radio*, not a USB link to the Switch. USB gadget
HID would be a different stack (deferred fallback in the skill).

Locked rules (switch2-remote-play skill):
  - Prefer Sunshine libvirtualhid pad; skip Steam 28de:11ff and EmuPads
  - EmuPads should already be off for Switch RP
  - Face buttons map by *position* (Xbox south→Switch B, etc.)
  - HOME = LB + D-Pad Down + Plus; Steam overlay/QAM/Home mute → idle packets
"""
from __future__ import annotations

import argparse
import os
import random
import signal
import subprocess
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
# gamescope Steam UI atoms live on the session HDMI display
STEAM_UI_DISPLAY = os.environ.get("NUXBT_STEAM_UI_DISPLAY", ":0")
STEAM_UI_POLL_S = float(os.environ.get("NUXBT_STEAM_UI_POLL_S", "0.1"))
STEAM_CLIENT_ID = "769"
# Runtime control (touch these while the bridge runs):
#   $XDG_RUNTIME_DIR/nuxbt-want-grip      → advertise + hold L+R (Grip/Order)
#   $XDG_RUNTIME_DIR/nuxbt-want-reconnect → MAC reconnect (no Grip menu)
_RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
WANT_GRIP = os.path.join(_RUNTIME, "nuxbt-want-grip")
WANT_RECONNECT = os.path.join(_RUNTIME, "nuxbt-want-reconnect")
DISCONNECT_GRACE_S = float(os.environ.get("NUXBT_DISCONNECT_GRACE_S", "2.0"))
RECONNECT_GIVEUP_S = float(os.environ.get("NUXBT_RECONNECT_GIVEUP_S", "25.0"))
GRIP_HOLD_DEFAULT = float(os.environ.get("NUXBT_GRIP_HOLD_S", "5"))

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

_STEAM_UI_CACHE = (0.0, False)


def _log(msg: str) -> None:
    print(msg, flush=True)


def steam_ui_active(display: str = STEAM_UI_DISPLAY) -> bool:
    """True while Steam overlay / QAM / Home-Library should not reach the Switch.

    Same atoms as EmuPads mute: STEAM_OVERLAY=1, GAMESCOPE_BLUR_MODE!=0,
    or FOCUSED_APP=769. Polled lightly so 120 Hz input is not blocked on xprop.
    """
    global _STEAM_UI_CACHE
    now = time.time()
    ts, cached = _STEAM_UI_CACHE
    if now - ts < STEAM_UI_POLL_S:
        return cached
    active = False
    try:
        out = subprocess.check_output(
            [
                "xprop", "-display", display, "-root",
                "STEAM_OVERLAY", "GAMESCOPE_BLUR_MODE", "GAMESCOPE_FOCUSED_APP",
            ],
            timeout=0.2,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        out = ""
    overlay = ""
    blur = ""
    app = ""
    for line in out.splitlines():
        name = line.split("(", 1)[0].split(":", 1)[0].strip()
        if "not found" in line.lower():
            val = ""
        elif "=" in line:
            val = line.split("=", 1)[1].strip()
        else:
            continue
        if name == "STEAM_OVERLAY":
            overlay = val
        elif name == "GAMESCOPE_BLUR_MODE":
            blur = val
        elif name == "GAMESCOPE_FOCUSED_APP":
            app = val
    if overlay in ("1", "0x1"):
        active = True
    elif blur.isdigit() and int(blur) != 0:
        active = True
    elif app == STEAM_CLIENT_ID:
        active = True
    _STEAM_UI_CACHE = (now, active)
    return active


def idle_packet(nx: Nuxbt) -> dict:
    """Neutral report — no buttons/sticks (Steam UI mute)."""
    return nx.create_input_packet()


def find_sunshine_pad(prefer: str | None = None) -> InputDevice | None:
    """Pick the Sunshine Moonlight pad (hotplug source). Prefer libvirtualhid.

    Returns None while Moonlight is down — NUXBT↔Switch stays up (mux-like).
    """
    prefer = (prefer or os.environ.get("NUXBT_SOURCE_EVENT") or "").strip()
    if prefer:
        try:
            dev = InputDevice(prefer)
        except OSError:
            return None
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
        # Prefer Odin/Thor-named Sunshine pads when several exist
        ranked = sorted(
            sunshine,
            key=lambda d: (
                0 if any(x in (d.name or "") for x in ("Odin", "Thor", "Portal")) else 1,
                d.path,
            ),
        )
        return ranked[0]
    if candidates:
        return candidates[0]
    return None


def _bind_source(dev: InputDevice, want_abs: tuple[int, ...]) -> tuple[dict, dict[int, int]]:
    """Snapshot absinfo + zeroed abs state for a newly attached Sunshine pad."""
    present = _abs_codes(dev)
    absinfo: dict = {}
    for code in want_abs:
        if code not in present:
            continue
        try:
            absinfo[code] = dev.absinfo(code)
        except OSError:
            continue
    abs_vals: dict[int, int] = {
        ecodes.ABS_X: 0, ecodes.ABS_Y: 0, ecodes.ABS_RX: 0, ecodes.ABS_RY: 0,
        ecodes.ABS_Z: 0, ecodes.ABS_RZ: 0, ecodes.ABS_HAT0X: 0, ecodes.ABS_HAT0Y: 0,
    }
    for code, info in absinfo.items():
        try:
            abs_vals[code] = int(info.value)
        except Exception:
            pass
    _log(
        f"source: {dev.path} ({dev.name}) "
        f"vid={dev.info.vendor:04x} pid={dev.info.product:04x} "
        f"abs={sorted(absinfo.keys())}"
    )
    return absinfo, abs_vals


def _source_alive(dev: InputDevice | None) -> bool:
    if dev is None:
        return False
    try:
        return os.path.exists(dev.path)
    except Exception:
        return False


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

    l = bool(buttons.get(ecodes.BTN_TL, 0))
    r = bool(buttons.get(ecodes.BTN_TR, 0))
    start = bool(buttons.get(ecodes.BTN_START, 0))
    hat_x = abs_vals.get(ecodes.ABS_HAT0X, 0)
    hat_y = abs_vals.get(ecodes.ABS_HAT0Y, 0)
    dpad_down = hat_y > 0
    # HOME = LB + D-Pad Down + Plus/Start (x360 has no Home). Guide/Mode still works alone.
    home_combo = l and dpad_down and start
    pkt["L"] = l
    pkt["R"] = r
    pkt["ZL"] = _trigger_pressed(buttons, abs_vals, ecodes.BTN_TL2, ecodes.ABS_Z)
    pkt["ZR"] = _trigger_pressed(buttons, abs_vals, ecodes.BTN_TR2, ecodes.ABS_RZ)
    pkt["PLUS"] = start and not home_combo
    pkt["MINUS"] = bool(buttons.get(ecodes.BTN_SELECT, 0))
    pkt["HOME"] = home_combo or bool(buttons.get(ecodes.BTN_MODE, 0))
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

    pkt["DPAD_LEFT"] = hat_x < 0
    pkt["DPAD_RIGHT"] = hat_x > 0
    pkt["DPAD_UP"] = hat_y < 0
    pkt["DPAD_DOWN"] = dpad_down and not home_combo
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


def _consume_flag(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        os.remove(path)
    except OSError:
        pass
    return True


def _spawn_controller(
    nx: Nuxbt,
    adapter: str,
    *,
    reconnect_address: str | None,
) -> int:
    """Create a Pro Controller; reconnect_address=None means advertise (Grip/Order)."""
    idx = nx.create_controller(
        PRO_CONTROLLER,
        adapter,
        colour_body=[random.randint(0, 255) for _ in range(3)],
        colour_buttons=[random.randint(0, 255) for _ in range(3)],
        reconnect_address=reconnect_address,
    )
    mode = "advertise" if reconnect_address is None else f"reconnect→{reconnect_address}"
    _log(f"controller {idx} created ({mode})")
    return idx


def _respawn(
    nx: Nuxbt,
    old_idx: int | None,
    adapter: str,
    *,
    reconnect_address: str | None,
) -> int:
    if old_idx is not None:
        try:
            nx.remove_controller(old_idx)
            _log(f"removed controller {old_idx}")
        except Exception as e:
            _log(f"remove_controller({old_idx}): {e}")
        time.sleep(0.4)
    return _spawn_controller(nx, adapter, reconnect_address=reconnect_address)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", default=ADAPTER)
    ap.add_argument("--switch", default=SWITCH, help="Switch BT MAC for reconnect")
    ap.add_argument("--source", default=None, help="/dev/input/eventN override")
    ap.add_argument("--no-reconnect", action="store_true", help="advertise only (Grip/Order)")
    ap.add_argument(
        "--grip",
        action="store_true",
        help="Grip/Order pair: advertise (no reconnect), then hold L+R on NUXBT for a few seconds",
    )
    ap.add_argument(
        "--grip-hold",
        type=float,
        default=GRIP_HOLD_DEFAULT,
        help="Seconds to hold L+R after BT connect in grip mode (default 5)",
    )
    ap.add_argument("--hz", type=float, default=HZ)
    args = ap.parse_args()

    period = 1.0 / max(args.hz, 30.0)
    if args.grip:
        args.no_reconnect = True

    _log(f"NUXBT Sunshine bridge adapter={args.adapter} switch={args.switch}")
    _log(f"control: touch {WANT_GRIP} (advertise+L+R) or {WANT_RECONNECT} (MAC reconnect)")
    if args.grip:
        _log(
            "GRIP MODE: advertising Pro Controller — stay on Change Grip/Order. "
            f"After BT connects, holding L+R for {args.grip_hold:.0f}s on NUXBT "
            "(does not rely on Odin/Sunshine bumpers)."
        )

    nx = Nuxbt(debug=False, log_file_path=LOG)
    adapters = nx.get_available_adapters()
    _log(f"adapters: {adapters}")
    if args.adapter not in adapters:
        raise SystemExit(f"{args.adapter} missing")

    use_advertise = bool(args.no_reconnect)
    reconnect_addr: str | None = None if use_advertise else args.switch
    idx = _spawn_controller(nx, args.adapter, reconnect_address=reconnect_addr)
    # Do not block forever here — the main loop owns reconnect/advertise + want-grip.
    if nx.state.get(idx, {}).get("state") != "connected":
        _log(f"initial state={nx.state.get(idx, {}).get('state')} — entering loop (auto-recover / want-grip live)")

    grip_until = 0.0
    pending_grip_lr = bool(args.grip)
    if pending_grip_lr and nx.state.get(idx, {}).get("state") == "connected":
        grip_until = time.time() + max(0.5, args.grip_hold)
        pending_grip_lr = False
        _log(f"connected — holding L+R until {grip_until:.0f} (wall clock)")

    want_abs = (
        ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY,
        ecodes.ABS_Z, ecodes.ABS_RZ, ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y,
    )
    source: InputDevice | None = None
    absinfo: dict = {}
    buttons: dict[int, int] = {}
    abs_vals: dict[int, int] = {
        ecodes.ABS_X: 0, ecodes.ABS_Y: 0, ecodes.ABS_RX: 0, ecodes.ABS_RY: 0,
        ecodes.ABS_Z: 0, ecodes.ABS_RZ: 0, ecodes.ABS_HAT0X: 0, ecodes.ABS_HAT0Y: 0,
    }
    source_path: str | None = None
    last_source_scan = 0.0
    waiting_logged = False
    disconnected_since: float | None = None
    reconnect_attempt_since: float | None = None
    last_st: str | None = None
    grip_logged_done = False

    stop = False

    def _stop(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    _log(
        f"bridging at {args.hz:.0f} Hz (no EVIOCGRAB). "
        "Auto-reconnect on drop; --grip / nuxbt-want-grip for advertise. Ctrl-C to stop."
    )
    last_active = False
    last_muted: bool | None = None

    while not stop:
        now = time.time()

        # B) Explicit advertise / reconnect requests (no full process restart needed)
        if _consume_flag(WANT_GRIP):
            _log("nuxbt-want-grip → advertise + L+R hold")
            idx = _respawn(nx, idx, args.adapter, reconnect_address=None)
            use_advertise = True
            pending_grip_lr = True
            reconnect_attempt_since = now
            disconnected_since = None
            grip_until = 0.0
            grip_logged_done = False
        elif _consume_flag(WANT_RECONNECT):
            _log(f"nuxbt-want-reconnect → MAC {args.switch}")
            idx = _respawn(nx, idx, args.adapter, reconnect_address=args.switch)
            use_advertise = False
            pending_grip_lr = False
            reconnect_attempt_since = now
            disconnected_since = None
            grip_until = 0.0

        st = nx.state.get(idx, {}).get("state")
        if st != last_st:
            _log(f"state={st}")
            if st == "connecting":
                _log("advertising — open Switch Controllers → Change Grip/Order if it does not auto-join")
            last_st = st

        if st == "connected":
            if disconnected_since is not None or reconnect_attempt_since is not None:
                _log("Switch link up")
            disconnected_since = None
            reconnect_attempt_since = None
            if pending_grip_lr and grip_until <= 0:
                grip_until = now + max(0.5, args.grip_hold)
                pending_grip_lr = False
                grip_logged_done = False
                _log(f"connected — holding L+R until {grip_until:.0f}")
        else:
            if disconnected_since is None:
                disconnected_since = now
            down_for = now - disconnected_since

            # A) Auto-recover: after grace, respawn (reconnect first; advertise if stuck)
            if st == "crashed" or down_for >= DISCONNECT_GRACE_S:
                if reconnect_attempt_since is None:
                    if use_advertise:
                        _log("link down — respawning advertise (Grip/Order)")
                        idx = _respawn(nx, idx, args.adapter, reconnect_address=None)
                        pending_grip_lr = True
                    else:
                        _log(f"link down ({st}) — respawning MAC reconnect → {args.switch}")
                        idx = _respawn(nx, idx, args.adapter, reconnect_address=args.switch)
                        use_advertise = False
                        pending_grip_lr = False
                    reconnect_attempt_since = now
                    disconnected_since = now
                    grip_until = 0.0
                    grip_logged_done = False
                elif (now - reconnect_attempt_since) >= RECONNECT_GIVEUP_S and not use_advertise:
                    _log(
                        f"reconnect stuck {RECONNECT_GIVEUP_S:.0f}s — "
                        "falling back to advertise (open Grip/Order)"
                    )
                    idx = _respawn(nx, idx, args.adapter, reconnect_address=None)
                    use_advertise = True
                    pending_grip_lr = True
                    reconnect_attempt_since = now
                    grip_until = 0.0
                    grip_logged_done = False

            time.sleep(min(0.5, period * 4))
            continue

        forcing_grip = now < grip_until
        if grip_until > 0 and not forcing_grip and not grip_logged_done:
            _log("grip L+R hold done — continue bridging; press + on Switch to exit Grip/Order")
            grip_logged_done = True
            grip_until = 0.0  # latch so we don't re-enter
        # Sunshine hotplug source
        need_scan = not _source_alive(source) or (now - last_source_scan >= 2.0)
        if need_scan:
            last_source_scan = now
            found = find_sunshine_pad(args.source)
            if found is not None and found.path != source_path:
                source = found
                source_path = found.path
                absinfo, abs_vals = _bind_source(source, want_abs)
                buttons.clear()
                waiting_logged = False
            elif found is None and source_path is not None:
                _log(f"source lost ({source_path}); idle to Switch — waiting for Sunshine pad…")
                source = None
                source_path = None
                buttons.clear()
                abs_vals = {k: 0 for k in abs_vals}
                waiting_logged = True
            elif found is None and not waiting_logged:
                _log("no Sunshine pad yet — NUXBT stays connected; waiting for Moonlight…")
                waiting_logged = True

        if source is not None:
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
                _log(f"source read error ({e}); will rescan")
                source = None
                source_path = None
                buttons.clear()
                abs_vals = {k: 0 for k in abs_vals}
                last_source_scan = 0.0

        muted = steam_ui_active() and not forcing_grip
        no_source = source is None
        if muted != last_muted:
            _log("steam UI mute — idle to Switch" if muted else "steam UI clear — bridging")
            last_muted = muted
            if muted:
                buttons.clear()

        if muted:
            pkt = idle_packet(nx)
        elif forcing_grip:
            pkt = idle_packet(nx)
            pkt["L"] = True
            pkt["R"] = True
        elif no_source:
            pkt = idle_packet(nx)
        else:
            pkt = build_packet(nx, buttons, abs_vals, absinfo)
        try:
            nx.set_controller_input(idx, pkt)
        except ValueError:
            _log("controller index gone; will respawn")
            disconnected_since = now
            continue

        active = (not muted) and (
            forcing_grip or (
                (not no_source) and (
                    any(
                        pkt[k] for k in (
                            "A", "B", "X", "Y", "L", "R", "ZL", "ZR",
                            "PLUS", "MINUS", "HOME", "CAPTURE",
                            "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
                        )
                    ) or pkt["L_STICK"]["PRESSED"] or pkt["R_STICK"]["PRESSED"] or any(
                        abs(pkt[s][a]) > 0 for s in ("L_STICK", "R_STICK") for a in ("X_VALUE", "Y_VALUE")
                    )
                )
            )
        )
        if active != last_active:
            _log("input: active" if active else "input: idle")
            last_active = active

        time.sleep(period)

    _log("stopping")
    try:
        nx.remove_controller(idx)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
