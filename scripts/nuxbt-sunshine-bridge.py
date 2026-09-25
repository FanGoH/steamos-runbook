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
  - HOME = Plus + L + D-Pad Down; Steam overlay/QAM/Home mute → idle packets
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
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
STEAM_UI_DISPLAYS = tuple(
    d.strip()
    for d in os.environ.get("NUXBT_STEAM_UI_DISPLAYS", ":0,:1").split(",")
    if d.strip()
)
STEAM_UI_POLL_S = float(os.environ.get("NUXBT_STEAM_UI_POLL_S", "0.05"))
STEAM_CLIENT_ID = "769"
# Runtime control (touch these while the bridge runs):
#   $XDG_RUNTIME_DIR/nuxbt-want-grip      → advertise + hold L+R (Grip/Order)
#   $XDG_RUNTIME_DIR/nuxbt-want-reconnect → MAC reconnect (no Grip menu)
_RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
WANT_GRIP = os.path.join(_RUNTIME, "nuxbt-want-grip")
WANT_RECONNECT = os.path.join(_RUNTIME, "nuxbt-want-reconnect")
WANT_TAP = os.path.join(_RUNTIME, "nuxbt-want-tap")  # pulse Switch A (~120ms) for latency tests
# Shared with inhibit-emu-input-on-steam-ui.py / EmuPads mux — prefer this when present.
EMU_MUTE_FILE = Path(_RUNTIME) / "emupads-mute"
DISCONNECT_GRACE_S = float(os.environ.get("NUXBT_DISCONNECT_GRACE_S", "2.0"))
RECONNECT_GIVEUP_S = float(os.environ.get("NUXBT_RECONNECT_GIVEUP_S", "25.0"))
# Grip/Order advertise must stay up while the user opens the Switch menu.
# Respawning every ~25s wedged BlueZ (DBus NoReply) and killed the bridge.
ADVERTISE_GIVEUP_S = float(os.environ.get("NUXBT_ADVERTISE_GIVEUP_S", "180.0"))
GRIP_HOLD_DEFAULT = float(os.environ.get("NUXBT_GRIP_HOLD_S", "5"))
# After Switch leaves Grip/Order the ACL dies (often as NUXBT "crashed").
# Rejoin in-process via MAC reconnect instead of exiting the bridge.
CRASH_RECONNECT_MAX = int(os.environ.get("NUXBT_CRASH_RECONNECT_MAX", "6"))
# Only clear the crash counter after the link has stayed up this long — otherwise
# connect→crash flaps reset the counter every time and never back off.
STABLE_LINK_S = float(os.environ.get("NUXBT_STABLE_LINK_S", "20.0"))
CRASH_BACKOFF_BASE_S = float(os.environ.get("NUXBT_CRASH_BACKOFF_S", "2.0"))
# Stable body/button colours (do not randomize — same look as the paired pad).
# Override with NUXBT_COLOUR_BODY / NUXBT_COLOUR_BUTTONS as "R,G,B".
_DEFAULT_BODY = (0x32, 0x32, 0x32)
_DEFAULT_BUTTONS = (0x0A, 0x0A, 0x0A)


def _parse_rgb(env_name: str, default: tuple[int, int, int]) -> list[int]:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return list(default)
    try:
        parts = [int(x.strip(), 0) for x in raw.split(",")]
        if len(parts) != 3 or any(p < 0 or p > 255 for p in parts):
            raise ValueError(raw)
        return parts
    except ValueError:
        print(
            f"warn: bad {env_name}={raw!r} — using default {default}",
            flush=True,
        )
        return list(default)


COLOUR_BODY = _parse_rgb("NUXBT_COLOUR_BODY", _DEFAULT_BODY)
COLOUR_BUTTONS = _parse_rgb("NUXBT_COLOUR_BUTTONS", _DEFAULT_BUTTONS)

# Steam virtual / EmuPads — never treat as the Moonlight source
SKIP_VID_PID = {
    (0x28DE, 0x11FF),  # Steam virtual
    (0x1209, 0xE301),  # EmuPads P1
    (0x1209, 0xE302),  # EmuPads P2
}

# Xbox/Sunshine face → Switch face by *physical position* (not Xbox labels).
FACE = {
    ecodes.BTN_SOUTH: "B",  # bottom
    ecodes.BTN_EAST: "A",   # right
    ecodes.BTN_WEST: "X",   # left
    ecodes.BTN_NORTH: "Y",  # top
}

_STEAM_UI_CACHE = (0.0, False, "")


def _log(msg: str) -> None:
    print(msg, flush=True)


def _x11_env(display: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DISPLAY"] = display
    return env


def _xprop_root(display: str, atom: str) -> str:
    try:
        out = subprocess.check_output(
            ["xprop", "-root", atom],
            env=_x11_env(display),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.35,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""
    if "=" not in out or "not found" in out.lower():
        return ""
    return out.split("=", 1)[1].strip().split(",")[0].strip()


def _overlay_on(display: str) -> bool:
    """STEAM_OVERLAY=1 on a steam window (root atom is often missing)."""
    if _xprop_root(display, "STEAM_OVERLAY") in ("1", "0x1"):
        return True
    ids: list[str] = []
    for kind, val in (("class", "steam"), ("class", "steamwebhelper"), ("name", "Steam")):
        try:
            ids += subprocess.check_output(
                ["xdotool", "search", f"--{kind}", val],
                env=_x11_env(display),
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=0.35,
            ).split()
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    seen: set[str] = set()
    for xid in ids:
        if xid in seen:
            continue
        seen.add(xid)
        try:
            out = subprocess.check_output(
                ["xprop", "-id", xid, "STEAM_OVERLAY"],
                env=_x11_env(display),
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=0.2,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
        if "=" in out and out.split("=", 1)[1].strip().split(",")[0].strip() in ("1", "0x1"):
            return True
    return False


def _blur_nonzero(raw: str) -> bool:
    if not raw:
        return False
    s = raw.strip().lower()
    if s in ("0", "0x0"):
        return False
    try:
        return int(s, 0) != 0
    except ValueError:
        return True


def steam_ui_kind() -> str:
    """overlay | qam | menu | file | '' — same rules as inhibit-emu-input-on-steam-ui.

    Prefer the shared ``emupads-mute`` file when the inhibit watcher is running
    (authoritative for QAM/overlay). Fall back to gamescope atoms; cheap root
    checks before the xdotool overlay walk.
    """
    if EMU_MUTE_FILE.is_file():
        return "file"
    if _blur_nonzero(_xprop_root(STEAM_UI_DISPLAY, "GAMESCOPE_BLUR_MODE")):
        return "qam"
    if _xprop_root(STEAM_UI_DISPLAY, "GAMESCOPE_FOCUSED_APP") == STEAM_CLIENT_ID:
        return "menu"
    for display in STEAM_UI_DISPLAYS:
        if _overlay_on(display):
            return "overlay"
    return ""


def steam_ui_active(display: str = STEAM_UI_DISPLAY) -> bool:
    """True while Steam overlay / QAM / Home-Library should not reach the Switch."""
    del display
    global _STEAM_UI_CACHE
    now = time.time()
    ts, cached, _kind = _STEAM_UI_CACHE
    if now - ts < STEAM_UI_POLL_S:
        return cached
    kind = steam_ui_kind()
    active = kind in ("overlay", "qam", "menu", "file")
    _STEAM_UI_CACHE = (now, active, kind)
    return active


def steam_ui_kind_cached() -> str:
    return _STEAM_UI_CACHE[2]


def _clear_pad_state(
    buttons: dict[int, int], abs_vals: dict[int, int]
) -> None:
    """Drop held QAM/overlay nav so it never reaches the Switch on unmute."""
    buttons.clear()
    for k in list(abs_vals.keys()):
        abs_vals[k] = 0


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
    # Sunshine/Odin: BTN_START/SELECT arrive inverted vs Xbox labels — map by
    # physical intent: Start → Plus (+), Select/Back → Minus (−).
    btn_start = bool(buttons.get(ecodes.BTN_START, 0))
    btn_select = bool(buttons.get(ecodes.BTN_SELECT, 0))
    plus = btn_select  # physical Start on this path
    minus = btn_start  # physical Select/Back on this path
    hat_x = abs_vals.get(ecodes.ABS_HAT0X, 0)
    hat_y = abs_vals.get(ecodes.ABS_HAT0Y, 0)
    dpad_down = hat_y > 0 or bool(buttons.get(ecodes.BTN_DPAD_DOWN, 0))
    # HOME = Plus + L + D-Pad Down (physical Start/+). Guide/Mode still works alone.
    # Suppress L/Plus/Down while the combo is active — Switch ignores Home if L stays held.
    home_combo = l and dpad_down and plus
    pkt["L"] = l and not home_combo
    pkt["R"] = r
    pkt["ZL"] = _trigger_pressed(buttons, abs_vals, ecodes.BTN_TL2, ecodes.ABS_Z)
    pkt["ZR"] = _trigger_pressed(buttons, abs_vals, ecodes.BTN_TR2, ecodes.ABS_RZ)
    pkt["PLUS"] = plus and not home_combo
    pkt["MINUS"] = minus
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
        colour_body=list(COLOUR_BODY),
        colour_buttons=list(COLOUR_BUTTONS),
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


def _recover_controller(
    nx: Nuxbt,
    old_idx: int | None,
    adapter: str,
    *,
    reconnect_address: str | None,
    log_path: str,
) -> tuple[Nuxbt, int]:
    """Respawn a controller; if the Nuxbt manager is dead, start a fresh one."""
    try:
        return nx, _respawn(nx, old_idx, adapter, reconnect_address=reconnect_address)
    except Exception as e:
        _log(f"respawn failed ({e}) — recreating Nuxbt manager")
    try:
        nx.shutdown()
    except Exception:
        pass
    time.sleep(0.6)
    fresh = Nuxbt(debug=False, log_file_path=log_path)
    adapters = fresh.get_available_adapters()
    if adapter not in adapters:
        raise RuntimeError(f"{adapter} missing after Nuxbt recreate (have {adapters})")
    idx = _spawn_controller(fresh, adapter, reconnect_address=reconnect_address)
    return fresh, idx


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
    _log(
        f"colours body={COLOUR_BODY} buttons={COLOUR_BUTTONS} "
        "(stable; set NUXBT_COLOUR_* to override)"
    )
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
    tap_until = 0.0
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
    ever_connected = False
    post_grip_paired = False  # True after L+R hold — leave Grip → MAC reconnect
    crash_reconnects = 0
    connected_since: float | None = None
    crash_paused = False  # too many flaps — wait for want-grip / want-reconnect

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
            try:
                nx, idx = _recover_controller(
                    nx, idx, args.adapter, reconnect_address=None, log_path=LOG
                )
            except Exception as e:
                _log(f"want-grip respawn failed ({e}) — exiting for hard restart")
                stop = True
                break
            use_advertise = True
            pending_grip_lr = True
            post_grip_paired = False
            crash_paused = False
            crash_reconnects = 0
            connected_since = None
            reconnect_attempt_since = now
            disconnected_since = None
            grip_until = 0.0
            grip_logged_done = False
        elif _consume_flag(WANT_RECONNECT):
            _log(f"nuxbt-want-reconnect → MAC {args.switch}")
            try:
                nx, idx = _recover_controller(
                    nx,
                    idx,
                    args.adapter,
                    reconnect_address=args.switch,
                    log_path=LOG,
                )
            except Exception as e:
                _log(f"want-reconnect respawn failed ({e}) — exiting for hard restart")
                stop = True
                break
            use_advertise = False
            pending_grip_lr = False
            crash_paused = False
            crash_reconnects = 0
            connected_since = None
            reconnect_attempt_since = now
            disconnected_since = None
            grip_until = 0.0
        elif _consume_flag(WANT_TAP):
            # Latency / Test Input Devices: pulse Switch A (hold via nuxbt-want-tap.hold).
            hold = 0.45
            hold_path = Path(str(WANT_TAP) + ".hold")
            try:
                raw = hold_path.read_text(encoding="utf-8").strip()
                hold_path.unlink(missing_ok=True)
                if raw:
                    v = float(raw)
                    hold = v / 1000.0 if v > 5 else v
            except (OSError, ValueError):
                pass
            tap_until = now + max(0.2, min(hold, 2.0))
            _log(f"nuxbt-want-tap → pulse A {tap_until - now:.2f}s")

        st = nx.state.get(idx, {}).get("state")
        if st != last_st:
            _log(f"state={st}")
            if st == "connecting":
                if use_advertise and not post_grip_paired:
                    _log(
                        "advertising — open Switch Controllers → Change Grip/Order "
                        "if it does not auto-join"
                    )
                else:
                    _log(f"connecting (MAC reconnect → {args.switch})")
            elif st == "reconnecting":
                _log(f"reconnecting → {args.switch}")
            last_st = st

        if st == "connected":
            if connected_since is None:
                connected_since = now
                _log("Switch link up")
            ever_connected = True
            # Only clear flap counter after a truly stable link — brief connects
            # were resetting attempt 1/8 forever and thrashing the Switch.
            if (
                crash_reconnects
                and connected_since is not None
                and (now - connected_since) >= STABLE_LINK_S
            ):
                _log(
                    f"link stable {STABLE_LINK_S:.0f}s — clearing crash counter "
                    f"(was {crash_reconnects})"
                )
                crash_reconnects = 0
            disconnected_since = None
            reconnect_attempt_since = None
            if pending_grip_lr and grip_until <= 0:
                grip_until = now + max(0.5, args.grip_hold)
                pending_grip_lr = False
                grip_logged_done = False
                _log(f"connected — holding L+R until {grip_until:.0f}")
        else:
            if connected_since is not None:
                up_for = now - connected_since
                connected_since = None
                if up_for < STABLE_LINK_S and st == "crashed":
                    _log(f"link dropped after only {up_for:.1f}s ({st})")
            if disconnected_since is None:
                disconnected_since = now
            down_for = now - disconnected_since

            # connecting/reconnecting = waiting for Switch. Never respawn on the
            # short DISCONNECT_GRACE (that killed Grip advertise every ~2s).
            waiting = st in ("connecting", "reconnecting")
            if waiting and reconnect_attempt_since is None:
                reconnect_attempt_since = now

            do_respawn = False
            # After a successful Grip pair (or any prior link), prefer MAC reconnect
            # so leaving Change Grip/Order rejoins without another Grip menu.
            prefer_mac = post_grip_paired or (ever_connected and not use_advertise)
            to_advertise = bool(use_advertise) and not prefer_mac
            if crash_paused:
                # Wait for explicit want-grip / want-reconnect (handled above).
                time.sleep(min(0.5, period * 4))
                continue
            if st == "crashed":
                do_respawn = True
                # Leaving Grip/Order often surfaces as "crashed" — rejoin by MAC.
                if post_grip_paired or ever_connected:
                    to_advertise = False
            elif waiting:
                giveup = ADVERTISE_GIVEUP_S if to_advertise else RECONNECT_GIVEUP_S
                if (now - (reconnect_attempt_since or now)) >= giveup:
                    do_respawn = True
                    if not to_advertise:
                        _log(
                            f"reconnect stuck {RECONNECT_GIVEUP_S:.0f}s — "
                            "falling back to advertise (open Grip/Order)"
                        )
                        to_advertise = True
                    else:
                        _log(
                            f"advertise still connecting after {ADVERTISE_GIVEUP_S:.0f}s — "
                            "respawning Pro Controller (stay on Change Grip/Order)"
                        )
            elif down_for >= DISCONNECT_GRACE_S:
                # Dropped after having been up (or never left idle)
                do_respawn = True

            if do_respawn:
                if st == "crashed":
                    crash_reconnects += 1
                    if crash_reconnects > CRASH_RECONNECT_MAX:
                        _log(
                            f"NUXBT crashed {crash_reconnects} times without a stable "
                            f"{STABLE_LINK_S:.0f}s link — pausing auto-reconnect. "
                            f"touch {WANT_GRIP} or {WANT_RECONNECT} (or QAM Grip/Reconnect)"
                        )
                        crash_paused = True
                        time.sleep(min(0.5, period * 4))
                        continue
                    backoff = min(
                        CRASH_BACKOFF_BASE_S * (2 ** (crash_reconnects - 1)),
                        20.0,
                    )
                    mode = "advertise" if to_advertise else f"MAC reconnect→{args.switch}"
                    _log(
                        f"NUXBT crashed — wait {backoff:.0f}s then {mode} "
                        f"(attempt {crash_reconnects}/{CRASH_RECONNECT_MAX})"
                    )
                    time.sleep(backoff)
                if to_advertise:
                    _log(f"link {st} — respawning advertise (Grip/Order)")
                    try:
                        nx, idx = _recover_controller(
                            nx,
                            idx,
                            args.adapter,
                            reconnect_address=None,
                            log_path=LOG,
                        )
                    except Exception as e:
                        _log(f"advertise respawn failed ({e}) — exiting for hard restart")
                        stop = True
                        break
                    use_advertise = True
                    pending_grip_lr = True
                    post_grip_paired = False
                else:
                    _log(f"link down ({st}) — respawning MAC reconnect → {args.switch}")
                    try:
                        nx, idx = _recover_controller(
                            nx,
                            idx,
                            args.adapter,
                            reconnect_address=args.switch,
                            log_path=LOG,
                        )
                    except Exception as e:
                        _log(f"reconnect respawn failed ({e}) — exiting for hard restart")
                        stop = True
                        break
                    use_advertise = False
                    pending_grip_lr = False
                reconnect_attempt_since = now
                disconnected_since = now
                grip_until = 0.0
                grip_logged_done = False

            time.sleep(min(0.5, period * 4))
            continue

        forcing_grip = now < grip_until
        if grip_until > 0 and not forcing_grip and not grip_logged_done:
            post_grip_paired = True
            use_advertise = False
            _log(
                "grip L+R hold done — MAC reconnect mode armed; "
                "press + on Switch to exit Grip/Order (we rejoin by MAC)"
            )
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

        # Mute *before* applying source events. While Steam QAM/overlay/Home is
        # up we still drain the Sunshine pad (no EVIOCGRAB — Steam needs it)
        # but must not accumulate those presses for a later unmute burst.
        muted = steam_ui_active() and not forcing_grip

        if source is not None:
            try:
                while True:
                    event = source.read_one()
                    if event is None:
                        break
                    if muted:
                        continue
                    if event.type == ecodes.EV_KEY:
                        buttons[event.code] = 1 if event.value else 0
                    elif event.type == ecodes.EV_ABS:
                        abs_vals[event.code] = event.value
            except OSError as e:
                _log(f"source read error ({e}); will rescan")
                source = None
                source_path = None
                _clear_pad_state(buttons, abs_vals)
                last_source_scan = 0.0

        no_source = source is None
        if muted != last_muted:
            kind = steam_ui_kind_cached() or "?"
            _log(
                f"steam UI mute ({kind}) — idle to Switch"
                if muted
                else "steam UI clear — bridging"
            )
            last_muted = muted
            # Clear both ways: QAM nav must not stick as a pressed A/B on unmute.
            _clear_pad_state(buttons, abs_vals)

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
        if (not forcing_grip) and now < tap_until:
            pkt["A"] = True
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
