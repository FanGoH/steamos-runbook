#!/usr/bin/env python3
"""Always-on virtual pads for Emu Pads (Cemu / Azahar / Eden).

Creates ``EmuPads P1`` / ``EmuPads P2`` uinput sinks. Host pads (Sunshine,
local Xbox, Steam virtual, phones) stay sources. Emulators bind the sinks
once; Decky only changes routing.

Shared mode: last source that sent a press/stick move is the only one copied
to P1 (no analog mix). Multi: first selected source → P1, second → P2.

Overlay/QAM: ``$XDG_RUNTIME_DIR/emupads-mute`` present → sinks emit zeros.
Steam still sees the real Sunshine pads. Do not EVIOCGRAB those.

Native games (Dusklight, Steam titles) also see P1/P2 as extra pads, so
Thor + the mux copy fire twice. Hide sinks unless Cemu / Azahar / Eden
is running. Do not match Sunshine / Steam / gamescope.

Never pgrep -f sunshine.
"""
from __future__ import annotations

import fcntl
import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

from evdev import AbsInfo, InputDevice, UInput, ecodes, list_devices

SINK_VENDOR = 0x1209
SINK_PRODUCTS = (0xE301, 0xE302)
SINK_NAMES = ("EmuPads P1", "EmuPads P2")
SINK_VERSION = 0x0114
SKIP_VENDORS = {0x0000, 0x001F, 0x26CE, 0x046D, 0xBEEF}
SKIP_PRODUCTS = {
    (0x1209, 0x0002),  # libvirtualhid Keyboard
    (0x1209, 0x0003),  # libvirtualhid Mouse
    (0x1209, 0x0004),  # libvirtualhid Touchscreen
    (0x1209, 0x0006),  # libvirtualhid Pen Tablet
}
STEAM_VIRTUAL = (0x28DE, 0x11FF)  # Steam Input wrap; duplicates Sunshine / physical
CONFIG_PATH = Path(os.environ.get("EMUPADS_MUX_CONFIG", Path.home() / ".config/emupads/mux.json"))
PID_NAME = "emupads-mux.pid"
MUTE_NAME = "emupads-mute"
LOG_PATH = Path(os.environ.get("EMUPADS_MUX_LOG", Path.home() / "steamos-playbook/logs/emupads-mux.log"))

_BTN = [
    ecodes.BTN_A,
    ecodes.BTN_B,
    ecodes.BTN_C,
    ecodes.BTN_X,
    ecodes.BTN_Y,
    ecodes.BTN_Z,
    ecodes.BTN_TL,
    ecodes.BTN_TR,
    ecodes.BTN_TL2,
    ecodes.BTN_TR2,
    ecodes.BTN_SELECT,
    ecodes.BTN_START,
    ecodes.BTN_MODE,
    ecodes.BTN_THUMBL,
    ecodes.BTN_THUMBR,
]
_ABS = [
    ecodes.ABS_X,
    ecodes.ABS_Y,
    ecodes.ABS_Z,
    ecodes.ABS_RX,
    ecodes.ABS_RY,
    ecodes.ABS_RZ,
    ecodes.ABS_HAT0X,
    ecodes.ABS_HAT0Y,
]
_STICK_ABS = {ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY}
# After a hat press, Moonlight often keeps a leftover left-stick deflection
# for several packets. FE3H menus treat that as D-pad and skip. Lock the
# stick out until both axes recenter (below ~0.19 / Eden's 0.15 deadzone).
_STICK_CENTER = 6144
_RELOAD = False


def runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))


def pid_path() -> Path:
    return runtime_dir() / PID_NAME


def mute_path() -> Path:
    return runtime_dir() / MUTE_NAME


def log(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%dT%H:%M:%S") + " " + msg
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _abs_info(code: int) -> AbsInfo:
    if code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
        return AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)
    if code in (ecodes.ABS_Z, ecodes.ABS_RZ):
        return AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)
    return AbsInfo(value=0, min=-32768, max=32767, fuzz=16, flat=128, resolution=0)


_ABS_DST = {code: _abs_info(code) for code in _ABS}


def scale_axis(value: int, src_min: int, src_max: int, dst_min: int, dst_max: int) -> int:
    """Map a source axis sample onto the sink range (fixes 0–255 vs ±32767)."""
    if src_max == src_min:
        return 0
    t = (value - src_min) / float(src_max - src_min)
    out = dst_min + t * (dst_max - dst_min)
    return int(round(max(dst_min, min(dst_max, out))))


def clamp_hat(value: int) -> int:
    """Hats must stay -1/0/1. Scaling a ±1 sample through a stick range zeros it."""
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def trigger_source_range(rng: tuple[int, int] | None) -> tuple[int, int]:
    """ABS_Z is often advertised as a stick (±32767) while xpad/Sunshine emit 0–255.

    Scaling 0–255 through a signed stick range compresses LT to ~half of RT.
    """
    if rng is None:
        return (0, 255)
    src_min, src_max = rng
    if src_min < 0:
        if src_max <= 255:
            return (0, 255)
        if src_max <= 1023:
            return (0, 1023)
        return (0, 255)
    return (src_min, src_max)


def vid_pid(dev) -> tuple[int, int] | None:
    try:
        return int(dev.info.vendor), int(dev.info.product)
    except (AttributeError, TypeError, ValueError):
        return None


def is_steam_virtual(dev) -> bool:
    pair = vid_pid(dev)
    return pair == STEAM_VIRTUAL


def is_sunshine_source(dev) -> bool:
    """Moonlight pads only — not libvirtualhid mouse / tablet / keyboard."""
    low = (dev.name or "").lower()
    if "sunshine" in low:
        return True
    if "libvirtualhid" not in low:
        return False
    if any(part in low for part in ("mouse", "keyboard", "tablet", "touch", "pen")):
        return False
    return True


def is_local_usb_pad(dev) -> bool:
    """Physical Xbox / xpad on the host — not a Sunshine Moonlight pad."""
    if is_sunshine_source(dev) or is_steam_virtual(dev):
        return False
    pair = vid_pid(dev)
    if pair is not None and pair[0] == 0x045E:
        return True
    name = (dev.name or "").lower()
    return "x-box" in name or "xbox" in name


def sink_capabilities() -> dict:
    return {
        ecodes.EV_KEY: list(_BTN),
        ecodes.EV_ABS: [(code, _abs_info(code)) for code in _ABS],
    }


def open_sink(index: int) -> UInput:
    name = SINK_NAMES[index]
    product = SINK_PRODUCTS[index]
    return UInput(
        sink_capabilities(),
        name=name,
        vendor=SINK_VENDOR,
        product=product,
        version=SINK_VERSION,
        bustype=ecodes.BUS_USB,
        phys=f"emupads/p{index + 1}",
    )


def is_sink_name(name: str) -> bool:
    return name in SINK_NAMES or name.startswith("EmuPads P")


def is_source_name(name: str) -> bool:
    low = name.lower()
    if is_sink_name(name):
        return False
    if any(part in low for part in ("mouse", "keyboard", "tablet", "touchscreen", "pen", "steamos-manager")):
        return False
    if "(imu)" in low or low.endswith(" imu"):
        return False
    return True


def is_source_device(dev) -> bool:
    if not is_source_name(dev.name or ""):
        return False
    pair = vid_pid(dev)
    if pair is None:
        return True
    vendor, product = pair
    if vendor in SKIP_VENDORS:
        return False
    if (vendor, product) in SKIP_PRODUCTS:
        return False
    return True


def enabled_from(data: dict | None) -> bool:
    """QAM Off unplugs P1/P2. Missing key stays on (always-on default)."""
    if not isinstance(data, dict) or "enabled" not in data:
        return True
    val = data.get("enabled")
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() not in ("0", "false", "no", "off")


def load_config(path: Path = CONFIG_PATH) -> dict:
    empty = {"mode": "shared", "sources": [], "enabled": True}
    if not path.is_file():
        return dict(empty)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return dict(empty)
    if not isinstance(data, dict):
        return dict(empty)
    mode = data.get("mode") or "shared"
    if mode not in ("shared", "multi"):
        mode = "shared"
    sources = data.get("sources") or []
    if not isinstance(sources, list):
        sources = []
    return {"mode": mode, "sources": sources, "enabled": enabled_from(data)}


def write_config(mode: str, sources: list[dict], path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prev_file: dict = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text())
            if isinstance(raw, dict):
                prev_file = raw
        except (OSError, json.JSONDecodeError):
            prev_file = {}
    payload = {
        "mode": mode if mode in ("shared", "multi") else "shared",
        "sources": sources,
        "enabled": enabled_from(prev_file if prev_file else {"enabled": True}),
    }
    for key in ("cemu_p1", "dual_screen"):
        if key in prev_file:
            payload[key] = prev_file[key]
    path.write_text(json.dumps(payload, indent=2) + "\n")


def source_spec_matches(spec: dict, name: str, path: str) -> bool:
    if spec.get("event") and spec["event"] == path:
        return True
    if spec.get("name") and spec["name"] == name:
        return True
    return False


def selected_sources(cfg: dict, devices: list[InputDevice]) -> list[InputDevice]:
    specs = cfg.get("sources") or []
    eligible = [dev for dev in devices if is_source_device(dev)]
    # Steam Input wraps the held pad (Sunshine / Xbox). Prefer the real
    # device so Cemu does not see Steam's deadzone/curve on top of SDL.
    non_steam = [dev for dev in eligible if not is_steam_virtual(dev)]
    if non_steam:
        eligible = non_steam
    # Moonlight + a desk USB Xbox both feeding P1 made NMH3 / Eden fight
    # itself (last-activity steal). Keep Sunshine; drop the local pad.
    if any(is_sunshine_source(dev) for dev in eligible):
        eligible = [dev for dev in eligible if not is_local_usb_pad(dev)]
    if not specs:
        return eligible
    out: list[InputDevice] = []
    seen: set[str] = set()
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        for dev in eligible:
            if dev.path in seen:
                continue
            if source_spec_matches(spec, dev.name or "", dev.path):
                out.append(dev)
                seen.add(dev.path)
                break
    return out


def is_activity(ev) -> bool:
    if ev.type == ecodes.EV_KEY and ev.value == 1:
        return True
    if ev.type != ecodes.EV_ABS:
        return False
    if ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
        return ev.value != 0
    if ev.code in (ecodes.ABS_Z, ecodes.ABS_RZ):
        return ev.value > 8
    return abs(ev.value) > 4096


def zero_sink(
    ui: UInput,
    hat: dict | None = None,
    last_abs: dict | None = None,
    gate: dict | None = None,
) -> None:
    for code in _BTN:
        ui.write(ecodes.EV_KEY, code, 0)
    for code in _ABS:
        ui.write(ecodes.EV_ABS, code, 0)
    ui.syn()
    if hat is not None:
        hat["x"] = 0
        hat["y"] = 0
    if last_abs is not None:
        last_abs.clear()
    if gate is not None:
        gate.update(new_stick_gate())


_ABS_RANGE_CACHE: dict[tuple[str, int], tuple[int, int] | None] = {}


def source_abs_range(dev, code: int) -> tuple[int, int] | None:
    path = getattr(dev, "path", None) or ""
    key = (path, code)
    if key in _ABS_RANGE_CACHE:
        return _ABS_RANGE_CACHE[key]
    try:
        info = dev.absinfo(code)
    except (OSError, AttributeError, KeyError):
        _ABS_RANGE_CACHE[key] = None
        return None
    if info is None:
        _ABS_RANGE_CACHE[key] = None
        return None
    rng = (int(info.min), int(info.max))
    _ABS_RANGE_CACHE[key] = rng
    return rng


def hat_held(hat: dict | None) -> bool:
    return bool(hat and (hat.get("x") or hat.get("y")))


def new_stick_gate() -> dict:
    return {"lock": False, "x": 0, "y": 0}


def stick_near_center(gate: dict | None) -> bool:
    if gate is None:
        return True
    x = gate.get("x")
    y = gate.get("y")
    if x is None or y is None:
        return False
    return abs(int(x)) <= _STICK_CENTER and abs(int(y)) <= _STICK_CENTER


def note_stick_axis(gate: dict | None, code: int, value: int) -> None:
    if gate is None:
        return
    if code == ecodes.ABS_X:
        gate["x"] = value
    elif code == ecodes.ABS_Y:
        gate["y"] = value
    if gate.get("lock") and stick_near_center(gate):
        gate["lock"] = False


def lock_stick_gate(gate: dict | None) -> None:
    if gate is None:
        return
    gate["lock"] = True
    gate["x"] = None
    gate["y"] = None


def write_hat_pair(ui: UInput, hat: dict, last_abs: dict | None = None) -> None:
    """SDL hats need both axes in one report or the direction looks stuck."""
    hx = clamp_hat(int(hat.get("x") or 0))
    hy = clamp_hat(int(hat.get("y") or 0))
    ui.write(ecodes.EV_ABS, ecodes.ABS_HAT0X, hx)
    ui.write(ecodes.EV_ABS, ecodes.ABS_HAT0Y, hy)
    if last_abs is not None:
        last_abs[ecodes.ABS_HAT0X] = hx
        last_abs[ecodes.ABS_HAT0Y] = hy


def forward_event(
    ui: UInput,
    ev,
    src=None,
    hat: dict | None = None,
    last_abs: dict | None = None,
    gate: dict | None = None,
) -> bool:
    """Copy one event. False = dropped (duplicate / suppressed). Caller SYNs."""
    if ev.type == ecodes.EV_SYN:
        return False
    if ev.type == ecodes.EV_KEY and ev.code in _BTN:
        ui.write(ev.type, ev.code, ev.value)
        return True
    if ev.type == ecodes.EV_ABS and ev.code in _ABS:
        if ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
            value = clamp_hat(ev.value)
            if hat is not None:
                key = "x" if ev.code == ecodes.ABS_HAT0X else "y"
                if hat.get(key) == value:
                    return False
                hat[key] = value
                ui.write(ecodes.EV_ABS, ecodes.ABS_X, 0)
                ui.write(ecodes.EV_ABS, ecodes.ABS_Y, 0)
                if last_abs is not None:
                    last_abs[ecodes.ABS_X] = 0
                    last_abs[ecodes.ABS_Y] = 0
                lock_stick_gate(gate)
                write_hat_pair(ui, hat, last_abs)
                return True
            ui.write(ev.type, ev.code, value)
            return True
        dst = _ABS_DST[ev.code]
        src_range = source_abs_range(src, ev.code) if src is not None else None
        if ev.code in (ecodes.ABS_Z, ecodes.ABS_RZ):
            src_range = trigger_source_range(src_range)
            value = scale_axis(ev.value, src_range[0], src_range[1], dst.min, dst.max)
        elif src_range is not None:
            value = scale_axis(ev.value, src_range[0], src_range[1], dst.min, dst.max)
        else:
            value = max(dst.min, min(dst.max, ev.value))
        if ev.code in (ecodes.ABS_X, ecodes.ABS_Y):
            if hat is not None and hat_held(hat):
                lock_stick_gate(gate)
                return False
            note_stick_axis(gate, ev.code, value)
            if gate is not None and gate.get("lock"):
                return False
        if last_abs is not None and last_abs.get(ev.code) == value:
            return False
        if last_abs is not None:
            last_abs[ev.code] = value
        ui.write(ev.type, ev.code, value)
        return True
    return False


def forward_batch(ui: UInput, events, src=None, hat=None, last_abs=None, gate=None) -> None:
    """Hats first. Moonlight often sends stick, then hat, in one report.

    Forwarding that stick spike makes Eden menus skip before the hat lands.
    After a hat, keep the stick locked until both axes recenter.
    """
    events = list(events)
    hat_changed = False
    if hat is not None:
        for ev in events:
            if ev.type != ecodes.EV_ABS or ev.code not in (
                ecodes.ABS_HAT0X,
                ecodes.ABS_HAT0Y,
            ):
                continue
            key = "x" if ev.code == ecodes.ABS_HAT0X else "y"
            value = clamp_hat(ev.value)
            if hat.get(key) == value:
                continue
            hat[key] = value
            hat_changed = True
        if hat_changed:
            ui.write(ecodes.EV_ABS, ecodes.ABS_X, 0)
            ui.write(ecodes.EV_ABS, ecodes.ABS_Y, 0)
            if last_abs is not None:
                last_abs[ecodes.ABS_X] = 0
                last_abs[ecodes.ABS_Y] = 0
            lock_stick_gate(gate)
            write_hat_pair(ui, hat, last_abs)
    suppress_stick = hat_held(hat) or hat_changed
    wrote = hat_changed
    for ev in events:
        if ev.type == ecodes.EV_SYN:
            if wrote:
                ui.syn()
                wrote = False
            continue
        if ev.type == ecodes.EV_ABS and ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
            continue
        if suppress_stick and ev.type == ecodes.EV_ABS and ev.code in (
            ecodes.ABS_X,
            ecodes.ABS_Y,
        ):
            continue
        if forward_event(ui, ev, src=src, hat=hat, last_abs=last_abs, gate=gate):
            wrote = True
    if wrote:
        ui.syn()


_STEAM_UI_CACHE = (0.0, False)
_EMU_CACHE = (0.0, False)
_STEAM_UI_ATOMS = (
    "GAMESCOPE_FOCUSED_APP",
    "STEAM_OVERLAY",
    "GAMESCOPE_BLUR_MODE",
)
# Linux comm is 15 chars (Flatpak Cemu → Cemu_relwithdeb). Do not match
# Sunshine / Steam / gamescope. Native AppImages (dusklight) are not emus.
_EMU_COMM_EXACT = {"azahar"}
_EMU_COMM_PREFIXES = ("cemu", "eden")


def parse_xprop_atoms(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        name = line.split("(", 1)[0].split(":", 1)[0].strip()
        if "=" in line:
            out[name] = line.split("=", 1)[1].strip()
        elif "not found" in line.lower():
            out[name] = ""
    return out


def xprop_root_atoms(display: str, atoms: tuple[str, ...]) -> dict[str, str]:
    try:
        out = subprocess.check_output(
            ["xprop", "-display", display, "-root", *atoms],
            timeout=0.2,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {}
    return parse_xprop_atoms(out)


def steam_ui_from_props(props: dict[str, str]) -> bool:
    app = props.get("GAMESCOPE_FOCUSED_APP", "")
    overlay = props.get("STEAM_OVERLAY", "")
    blur = props.get("GAMESCOPE_BLUR_MODE", "")
    return app == "769" or overlay in ("1", "0x1") or (blur.isdigit() and int(blur) != 0)


def steam_ui_active(now: float | None = None) -> bool:
    """Steam Home/Library/overlay/QAM — sinks must not drive that UI."""
    global _STEAM_UI_CACHE
    ts = time.monotonic() if now is None else now
    cached_at, cached = _STEAM_UI_CACHE
    if ts - cached_at < 0.25:
        return cached
    active = steam_ui_from_props(xprop_root_atoms(":0", _STEAM_UI_ATOMS))
    _STEAM_UI_CACHE = (ts, active)
    return active


def is_emulator_comm(comm: str) -> bool:
    name = comm.strip().lower()
    if not name or name.startswith("sunshine"):
        return False
    if name in _EMU_COMM_EXACT:
        return True
    return any(name.startswith(prefix) for prefix in _EMU_COMM_PREFIXES)


def emulator_comms(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if is_emulator_comm(line)]


def _proc_comms() -> str:
    """Read /proc without spawning `ps` on the housekeep timer."""
    parts: list[str] = []
    try:
        for ent in os.listdir("/proc"):
            if not ent.isdigit():
                continue
            try:
                parts.append(Path(f"/proc/{ent}/comm").read_text())
            except OSError:
                continue
    except OSError:
        return ""
    return "".join(parts)


def emulator_wants_sinks(now: float | None = None) -> bool:
    """Cemu / Azahar / Eden read P1/P2. Dusklight and other native games must not."""
    global _EMU_CACHE
    ts = time.monotonic() if now is None else now
    cached_at, cached = _EMU_CACHE
    if ts - cached_at < 0.25:
        return cached
    wanted = bool(emulator_comms(_proc_comms()))
    _EMU_CACHE = (ts, wanted)
    return wanted


def hide_sinks_from_host(now: float | None = None) -> bool:
    """Grab + mute P1/P2 unless an emulator needs them."""
    if steam_ui_active(now):
        return True
    return not emulator_wants_sinks(now)


def sink_event_reader(ui: UInput):
    try:
        path = ui.device.path if ui.device is not None else None
    except AttributeError:
        path = None
    if not path:
        return None
    try:
        return InputDevice(path)
    except OSError:
        return None


def grab_sinks(readers: list, hide: bool, grabbed: list[bool]) -> None:
    """EVIOCGRAB the sink event nodes so Steam cannot read them."""
    for i, reader in enumerate(readers):
        if reader is None:
            continue
        want = bool(hide)
        if grabbed[i] == want:
            continue
        try:
            if want:
                reader.grab()
            else:
                reader.ungrab()
            grabbed[i] = want
        except OSError:
            pass


def request_reload(_signum=None, _frame=None) -> None:
    global _RELOAD
    _RELOAD = True


def close_uinput(sinks: list, readers: list, grabbed: list[bool]) -> None:
    grab_sinks(readers, False, grabbed)
    for reader in readers:
        if reader is None:
            continue
        try:
            reader.close()
        except OSError:
            pass
    for ui in sinks:
        if ui is None:
            continue
        try:
            zero_sink(ui)
            ui.close()
        except OSError:
            pass


def make_sinks() -> tuple[list, list, list[bool], set[str]]:
    sinks = [open_sink(0), open_sink(1)]
    readers = [sink_event_reader(ui) for ui in sinks]
    grabbed = [False, False]
    skip = {ui.device.path for ui in sinks if ui.device is not None}
    log(f"sinks {SINK_NAMES[0]} {SINK_NAMES[1]}")
    return sinks, readers, grabbed, skip


def write_pid() -> None:
    path = pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()) + "\n")


def replace_leftover_mux() -> None:
    """SIGTERM any other emupads-mux.py. bind-gamepad used to Popen a second copy."""
    path = pid_path()
    if not path.is_file():
        return
    try:
        old = int(path.read_text().strip())
    except (OSError, ValueError):
        return
    if old <= 0 or old == os.getpid():
        return
    try:
        os.kill(old, 0)
    except OSError:
        return
    try:
        os.kill(old, signal.SIGTERM)
        log(f"replaced leftover mux pid {old}")
    except OSError:
        return
    for _ in range(40):
        try:
            os.kill(old, 0)
        except OSError:
            return
        time.sleep(0.05)
    try:
        os.kill(old, signal.SIGKILL)
        log(f"killed leftover mux pid {old}")
    except OSError:
        return


def acquire_mux_lock() -> int:
    path = runtime_dir() / "emupads-mux.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another mux already holds emupads-mux.lock")
        os.close(fd)
        raise SystemExit(0)
    return fd


def scan_devices(skip_paths: set[str]) -> list[InputDevice]:
    out: list[InputDevice] = []
    for node in list_devices():
        if node in skip_paths:
            continue
        try:
            dev = InputDevice(node)
        except OSError:
            continue
        phys = (dev.phys or "").lower()
        if phys.startswith("emupads/"):
            continue
        if not is_source_device(dev):
            continue
        out.append(dev)
    return out


def device_alive(dev) -> bool:
    path = getattr(dev, "path", None)
    if not path or not Path(path).exists():
        return False
    try:
        fd = int(dev.fd)
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    return fd >= 0


def rescan_devices(devices: list[InputDevice], skip_paths: set[str]) -> list[InputDevice]:
    """Keep open fds. Only close vanished nodes and open new ones.

    A full close/reopen every scan made pads hitch when Thor/Odin
    reconnected (the live Sunshine fd was torn down for a second).
    """
    kept: list[InputDevice] = []
    for dev in devices:
        if device_alive(dev):
            kept.append(dev)
            continue
        try:
            dev.close()
        except OSError:
            pass
        path = getattr(dev, "path", None)
        if path:
            for key in list(_ABS_RANGE_CACHE):
                if key[0] == path:
                    _ABS_RANGE_CACHE.pop(key, None)
    have = {dev.path for dev in kept}
    for node in list_devices():
        if node in skip_paths or node in have:
            continue
        try:
            dev = InputDevice(node)
        except OSError:
            continue
        phys = (dev.phys or "").lower()
        if phys.startswith("emupads/"):
            try:
                dev.close()
            except OSError:
                pass
            continue
        if not is_source_device(dev):
            try:
                dev.close()
            except OSError:
                pass
            continue
        kept.append(dev)
        log(f"source + {dev.name} {dev.path}")
    return kept


def loop() -> int:
    global _RELOAD
    signal.signal(signal.SIGHUP, request_reload)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    replace_leftover_mux()
    _lock_fd = acquire_mux_lock()
    write_pid()
    sinks: list = []
    sink_readers: list = []
    sink_grabbed: list[bool] = []
    skip: set[str] = set()
    devices: list[InputDevice] = []
    cfg = load_config()
    last_scan = 0.0
    last_cfg_mtime = 0.0
    last_house = 0.0
    active: list[str | None] = [None, None]
    hats: list[dict] = [{"x": 0, "y": 0}, {"x": 0, "y": 0}]
    last_abs: list[dict] = [{}, {}]
    gates: list[dict] = [new_stick_gate(), new_stick_gate()]
    muted = False
    selected: list[InputDevice] = []
    fds: dict[int, InputDevice] = {}

    def sync_sinks(want: bool) -> None:
        nonlocal sinks, sink_readers, sink_grabbed, skip
        have = bool(sinks)
        if want and not have:
            sinks, sink_readers, sink_grabbed, skip = make_sinks()
        elif not want and have:
            close_uinput(sinks, sink_readers, sink_grabbed)
            sinks, sink_readers, sink_grabbed, skip = [], [], [], set()
            log("sinks disconnected")

    def housekeep(now: float) -> None:
        global _RELOAD
        nonlocal cfg, devices, selected, fds, muted, last_scan, last_cfg_mtime
        mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.is_file() else 0.0
        if _RELOAD or mtime != last_cfg_mtime or now - last_scan > 1.0 or not devices:
            _RELOAD = False
            last_cfg_mtime = mtime
            last_scan = now
            cfg = load_config()
            sync_sinks(bool(cfg.get("enabled", True)))
            if not devices:
                devices = scan_devices(skip)
            else:
                devices = rescan_devices(devices, skip)
            selected = selected_sources(cfg, devices)
            fds = {dev.fd: dev for dev in selected}
        if not sinks:
            muted = False
            return
        hide = hide_sinks_from_host(now)
        grab_sinks(sink_readers, hide, sink_grabbed)
        want_mute = mute_path().is_file() or hide
        if want_mute and not muted:
            for i, ui in enumerate(sinks):
                zero_sink(
                    ui,
                    hats[i] if i < len(hats) else None,
                    last_abs[i] if i < len(last_abs) else None,
                    gates[i] if i < len(gates) else None,
                )
            muted = True
            log("muted (no emulator / Steam UI)")
        elif not want_mute and muted:
            muted = False
            log("unmuted")

    try:
        housekeep(time.monotonic())
        last_house = time.monotonic()
        while True:
            if not sinks:
                time.sleep(0.2)
                now = time.monotonic()
                if now - last_house >= 0.25:
                    housekeep(now)
                    last_house = now
                continue
            if not fds:
                time.sleep(0.05)
                now = time.monotonic()
                if now - last_house >= 0.25:
                    housekeep(now)
                    last_house = now
                continue
            ready, _, _ = select.select(list(fds), [], [], 0.05)
            if ready and muted:
                for fd in ready:
                    try:
                        for _ev in fds[fd].read():
                            pass
                    except OSError:
                        pass
            elif ready:
                mode = cfg.get("mode") or "shared"
                for fd in ready:
                    dev = fds[fd]
                    try:
                        events = list(dev.read())
                    except OSError:
                        continue
                    if mode == "multi":
                        slot = None
                        if len(selected) >= 1 and dev is selected[0]:
                            slot = 0
                        elif len(selected) >= 2 and dev is selected[1]:
                            slot = 1
                        if slot is None:
                            continue
                        ui = sinks[slot]
                        if any(is_activity(ev) for ev in events):
                            if active[slot] not in (None, dev.path):
                                zero_sink(ui, hats[slot], last_abs[slot], gates[slot])
                            active[slot] = dev.path
                        if active[slot] == dev.path:
                            forward_batch(
                                ui,
                                events,
                                src=dev,
                                hat=hats[slot],
                                last_abs=last_abs[slot],
                                gate=gates[slot],
                            )
                        continue
                    ui = sinks[0]
                    if any(is_activity(ev) for ev in events):
                        if active[0] not in (None, dev.path):
                            zero_sink(ui, hats[0], last_abs[0], gates[0])
                        active[0] = dev.path
                    if active[0] == dev.path:
                        forward_batch(
                            ui,
                            events,
                            src=dev,
                            hat=hats[0],
                            last_abs=last_abs[0],
                            gate=gates[0],
                        )
            now = time.monotonic()
            if now - last_house >= 0.25:
                housekeep(now)
                last_house = now
    finally:
        close_uinput(sinks, sink_readers, sink_grabbed)
        for dev in devices:
            try:
                dev.close()
            except OSError:
                pass
        try:
            if pid_path().read_text().strip() == str(os.getpid()):
                pid_path().unlink()
        except OSError:
            pass
        log("exit")
    return 0


def self_test() -> int:
    cfg = {"mode": "shared", "sources": []}
    class FakeInfo:
        def __init__(self, vendor=0x045E, product=0x028E):
            self.vendor = vendor
            self.product = product

    class Fake:
        def __init__(self, name, path, vendor=0x045E, product=0x028E):
            self.name = name
            self.path = path
            self.info = FakeInfo(vendor, product)

    devices = [
        Fake("Sunshine (libvirtualhid) AYN_Thor", "/dev/input/event10"),
        Fake("EmuPads P1", "/dev/input/event20", 0x1209, 0xE301),
        Fake("Sunshine (libvirtualhid) Mouse", "/dev/input/event11", 0x1209, 0x0003),
        Fake("libvirtualhid Keyboard", "/dev/input/event17", 0x1209, 0x0002),
        Fake("libvirtualhid Touchscreen", "/dev/input/event18", 0x1209, 0x0004),
        Fake("libvirtualhid Pen Tablet", "/dev/input/event19", 0x1209, 0x0006),
        Fake("Odin2_Portal", "/dev/input/event12", 0x37D7, 0x0001),
        Fake("ASRock LED Controller", "/dev/input/event13", 0x26CE, 0x01A2),
        Fake("Microsoft X-Box 360 pad 0", "/dev/input/event14", 0x28DE, 0x11FF),
        Fake("Microsoft X-Box 360 pad", "/dev/input/event16", 0x045E, 0x028E),
        Fake("steamos-manager", "/dev/input/event21", 0x28DE, 0x0000),
    ]
    # selected_sources expects InputDevice; duck-type name/path
    got = selected_sources(cfg, devices)  # type: ignore[arg-type]
    names = [d.name for d in got]
    assert "EmuPads P1" not in names
    assert "Sunshine (libvirtualhid) Mouse" not in names
    assert "libvirtualhid Keyboard" not in names
    assert "libvirtualhid Touchscreen" not in names
    assert "libvirtualhid Pen Tablet" not in names
    assert "steamos-manager" not in names
    assert "ASRock LED Controller" not in names
    assert "Sunshine (libvirtualhid) AYN_Thor" in names
    assert "Odin2_Portal" in names
    assert "Microsoft X-Box 360 pad 0" not in names
    assert "Microsoft X-Box 360 pad" not in names
    assert is_sunshine_source(Fake("Sunshine (libvirtualhid) AYN_Thor", "/dev/input/event10"))
    assert not is_sunshine_source(Fake("libvirtualhid Pen Tablet", "/dev/input/event19", 0x1209, 0x0006))
    assert not is_source_name("libvirtualhid Keyboard")
    assert not is_source_name("Sunshine (libvirtualhid) AYN_Thor (IMU)")
    usb_only = [Fake("Microsoft X-Box 360 pad", "/dev/input/event16", 0x045E, 0x028E)]
    usb_got = selected_sources(cfg, usb_only)  # type: ignore[arg-type]
    assert [d.name for d in usb_got] == ["Microsoft X-Box 360 pad"]
    steam_only = [Fake("Microsoft X-Box 360 pad 0", "/dev/input/event14", 0x28DE, 0x11FF)]
    steam_got = selected_sources(cfg, steam_only)  # type: ignore[arg-type]
    assert [d.name for d in steam_got] == ["Microsoft X-Box 360 pad 0"]
    assert clamp_hat(0) == 0
    assert clamp_hat(1) == 1
    assert clamp_hat(-1) == -1
    assert clamp_hat(32767) == 1
    assert clamp_hat(-32768) == -1
    # A ±1 hat through a stick absinfo used to scale to 0.
    assert scale_axis(1, -32768, 32767, -1, 1) == 0
    assert scale_axis(0, -32768, 32767, -32768, 32767) == 0
    assert scale_axis(32767, -32768, 32767, -32768, 32767) == 32767
    assert scale_axis(-32768, -32768, 32767, -32768, 32767) == -32768
    assert abs(scale_axis(128, 0, 255, -32768, 32767)) < 256
    assert scale_axis(0, 0, 255, -32768, 32767) == -32768
    assert scale_axis(255, 0, 255, -32768, 32767) == 32767
    assert scale_axis(255, 0, 255, 0, 255) == 255
    assert scale_axis(0, 0, 255, 0, 255) == 0
    # Signed stick absinfo + unsigned 0–255 samples used to pin LT at ~128.
    assert scale_axis(255, -32768, 32767, 0, 255) == 128
    assert trigger_source_range((-32768, 32767)) == (0, 255)
    assert trigger_source_range((0, 255)) == (0, 255)
    assert trigger_source_range((0, 1023)) == (0, 1023)
    assert scale_axis(255, *trigger_source_range((-32768, 32767)), 0, 255) == 255
    cfg2 = {
        "mode": "multi",
        "sources": [{"name": "Odin2_Portal"}, {"name": "Sunshine (libvirtualhid) AYN_Thor"}],
    }
    got2 = selected_sources(cfg2, devices)  # type: ignore[arg-type]
    assert [d.name for d in got2] == [
        "Odin2_Portal",
        "Sunshine (libvirtualhid) AYN_Thor",
    ]
    assert is_sink_name("EmuPads P2")
    assert not is_source_name("EmuPads P1")
    assert enabled_from({}) is True
    assert enabled_from({"enabled": True}) is True
    assert enabled_from({"enabled": False}) is False
    assert enabled_from({"enabled": "off"}) is False
    assert replace_leftover_mux() is None
    tmp_cfg = Path("/tmp/emupads-mux-self-test-enabled.json")
    try:
        tmp_cfg.write_text(
            json.dumps(
                {
                    "mode": "shared",
                    "sources": [],
                    "cemu_p1": "pro",
                    "dual_screen": "auto",
                    "enabled": False,
                },
                indent=2,
            )
            + "\n"
        )
        write_config("multi", [], path=tmp_cfg)
        saved = json.loads(tmp_cfg.read_text())
        assert saved["enabled"] is False
        assert saved["mode"] == "multi"
        assert saved["cemu_p1"] == "pro"
        assert saved["dual_screen"] == "auto"
    finally:
        tmp_cfg.unlink(missing_ok=True)
    global _STEAM_UI_CACHE, _EMU_CACHE
    parsed = parse_xprop_atoms(
        "GAMESCOPE_FOCUSED_APP(CARDINAL) = 769\n"
        "STEAM_OVERLAY:  not found.\n"
        "GAMESCOPE_BLUR_MODE(CARDINAL) = 0\n"
    )
    assert parsed["GAMESCOPE_FOCUSED_APP"] == "769"
    assert steam_ui_from_props(parsed) is True
    assert steam_ui_from_props({"GAMESCOPE_FOCUSED_APP": "2896033129"}) is False
    _STEAM_UI_CACHE = (time.monotonic(), True)
    assert steam_ui_active() is True
    assert is_emulator_comm("Cemu_relwithdeb")
    assert is_emulator_comm("Cemu_relwithdebinfo")
    assert is_emulator_comm("azahar")
    assert is_emulator_comm("eden")
    assert is_emulator_comm("eden.appimage")
    assert not is_emulator_comm("dusklight")
    assert not is_emulator_comm("steam")
    assert not is_emulator_comm("sunshine-ds")
    assert not is_emulator_comm("sunshine-ds-kms")
    assert emulator_comms("steam\ndusklight\ngamescope\n") == []
    assert emulator_comms("steam\nazahar\ndusklight\n") == ["azahar"]
    _STEAM_UI_CACHE = (time.monotonic(), False)
    _EMU_CACHE = (time.monotonic(), False)
    assert hide_sinks_from_host() is True
    _EMU_CACHE = (time.monotonic(), True)
    assert hide_sinks_from_host() is False
    _STEAM_UI_CACHE = (time.monotonic(), True)
    _EMU_CACHE = (time.monotonic(), True)
    assert hide_sinks_from_host() is True

    class Alive:
        def __init__(self, path):
            self.path = path
            self.fd = 3
            self.closed = False

        def close(self):
            self.closed = True

    kept_path = "/tmp/emupads-mux-self-test-kept"
    Path(kept_path).write_text("")
    try:
        live = Alive(kept_path)
        dead = Alive("/tmp/emupads-mux-self-test-missing")
        out = rescan_devices([live, dead], skip_paths=set())  # type: ignore[arg-type]
        assert live in out and not live.closed
        assert dead.closed
        assert dead not in out
    finally:
        Path(kept_path).unlink(missing_ok=True)

    class FakeUI:
        def __init__(self) -> None:
            self.writes: list[tuple[int, int, int]] = []

        def write(self, typ: int, code: int, value: int) -> None:
            self.writes.append((typ, code, value))

        def syn(self) -> None:
            self.writes.append((ecodes.EV_SYN, 0, 0))

    class Ev:
        def __init__(self, typ: int, code: int, value: int) -> None:
            self.type = typ
            self.code = code
            self.value = value

    hat = {"x": 0, "y": 0}
    last = {}
    gate = new_stick_gate()
    ui = FakeUI()
    assert forward_event(
        ui, Ev(ecodes.EV_ABS, ecodes.ABS_HAT0X, 1), hat=hat, last_abs=last, gate=gate
    )
    assert hat["x"] == 1
    assert gate["lock"] is True
    assert (ecodes.EV_ABS, ecodes.ABS_HAT0X, 1) in ui.writes
    assert (ecodes.EV_ABS, ecodes.ABS_HAT0Y, 0) in ui.writes
    assert (ecodes.EV_ABS, ecodes.ABS_X, 0) in ui.writes
    n = len(ui.writes)
    assert not forward_event(
        ui, Ev(ecodes.EV_ABS, ecodes.ABS_HAT0X, 1), hat=hat, last_abs=last, gate=gate
    )
    assert len(ui.writes) == n
    assert not forward_event(
        ui, Ev(ecodes.EV_ABS, ecodes.ABS_X, 20000), hat=hat, last_abs=last, gate=gate
    )
    assert (ecodes.EV_ABS, ecodes.ABS_X, 20000) not in ui.writes
    assert forward_event(
        ui, Ev(ecodes.EV_ABS, ecodes.ABS_HAT0X, 0), hat=hat, last_abs=last, gate=gate
    )
    assert hat["x"] == 0
    # Leftover analog after hat release stays dropped until recenter.
    assert not forward_event(
        ui, Ev(ecodes.EV_ABS, ecodes.ABS_X, 20000), hat=hat, last_abs=last, gate=gate
    )
    assert (ecodes.EV_ABS, ecodes.ABS_X, 20000) not in ui.writes
    assert not forward_event(
        ui, Ev(ecodes.EV_ABS, ecodes.ABS_Y, 0), hat=hat, last_abs=last, gate=gate
    )
    assert gate["lock"] is True
    forward_event(
        ui, Ev(ecodes.EV_ABS, ecodes.ABS_X, 0), hat=hat, last_abs=last, gate=gate
    )
    assert gate["lock"] is False
    assert forward_event(
        ui, Ev(ecodes.EV_ABS, ecodes.ABS_X, 20000), hat=hat, last_abs=last, gate=gate
    )
    assert (ecodes.EV_ABS, ecodes.ABS_X, 20000) in ui.writes
    n = len(ui.writes)
    assert not forward_event(
        ui, Ev(ecodes.EV_ABS, ecodes.ABS_X, 20000), hat=hat, last_abs=last, gate=gate
    )
    assert len(ui.writes) == n
    ui = FakeUI()
    hat = {"x": 0, "y": 0}
    last = {}
    gate = new_stick_gate()
    forward_batch(
        ui,
        [
            Ev(ecodes.EV_ABS, ecodes.ABS_Y, -30000),
            Ev(ecodes.EV_ABS, ecodes.ABS_HAT0Y, -1),
            Ev(ecodes.EV_SYN, 0, 0),
        ],
        hat=hat,
        last_abs=last,
        gate=gate,
    )
    assert hat["y"] == -1
    assert gate["lock"] is True
    assert (ecodes.EV_ABS, ecodes.ABS_Y, -30000) not in ui.writes
    assert (ecodes.EV_ABS, ecodes.ABS_HAT0Y, -1) in ui.writes
    assert (ecodes.EV_ABS, ecodes.ABS_HAT0X, 0) in ui.writes
    ui = FakeUI()
    forward_batch(
        ui,
        [
            Ev(ecodes.EV_ABS, ecodes.ABS_HAT0Y, 0),
            Ev(ecodes.EV_ABS, ecodes.ABS_Y, -28000),
            Ev(ecodes.EV_SYN, 0, 0),
        ],
        hat=hat,
        last_abs=last,
        gate=gate,
    )
    assert hat["y"] == 0
    assert (ecodes.EV_ABS, ecodes.ABS_Y, -28000) not in ui.writes
    ui = FakeUI()
    forward_batch(
        ui,
        [
            Ev(ecodes.EV_ABS, ecodes.ABS_X, 0),
            Ev(ecodes.EV_ABS, ecodes.ABS_Y, 0),
            Ev(ecodes.EV_SYN, 0, 0),
        ],
        hat=hat,
        last_abs=last,
        gate=gate,
    )
    assert gate["lock"] is False
    ui = FakeUI()
    forward_batch(
        ui,
        [
            Ev(ecodes.EV_ABS, ecodes.ABS_Y, -28000),
            Ev(ecodes.EV_SYN, 0, 0),
        ],
        hat=hat,
        last_abs=last,
        gate=gate,
    )
    assert (ecodes.EV_ABS, ecodes.ABS_Y, -28000) in ui.writes

    print("emupads-mux self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--self-test"]:
        return self_test()
    return loop()


if __name__ == "__main__":
    raise SystemExit(main())
