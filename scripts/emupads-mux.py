#!/usr/bin/env python3
"""Always-on virtual pads for Emu Pads (Cemu / Azahar / Eden).

Creates ``EmuPads P1`` / ``EmuPads P2`` uinput sinks. Host pads (Sunshine,
local Xbox, Steam virtual, phones) stay sources. Emulators bind the sinks
once; Decky only changes routing.

Shared mode: last source that sent a press/stick move is the only one copied
to P1 (no analog mix). Multi: first selected source → P1, second → P2.

Overlay/QAM: ``$XDG_RUNTIME_DIR/emupads-mute`` present → sinks emit zeros.
Steam still sees the real Sunshine pads. Do not EVIOCGRAB those.

Never pgrep -f sunshine.
"""
from __future__ import annotations

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
SKIP_PRODUCTS = {(0x1209, 0x0003)}  # libvirtualhid Mouse
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


def vid_pid(dev) -> tuple[int, int] | None:
    try:
        return int(dev.info.vendor), int(dev.info.product)
    except (AttributeError, TypeError, ValueError):
        return None


def is_steam_virtual(dev) -> bool:
    pair = vid_pid(dev)
    return pair == STEAM_VIRTUAL


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
    if "mouse" in low:
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


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.is_file():
        return {"mode": "shared", "sources": []}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"mode": "shared", "sources": []}
    if not isinstance(data, dict):
        return {"mode": "shared", "sources": []}
    mode = data.get("mode") or "shared"
    if mode not in ("shared", "multi"):
        mode = "shared"
    sources = data.get("sources") or []
    if not isinstance(sources, list):
        sources = []
    return {"mode": mode, "sources": sources}


def write_config(mode: str, sources: list[dict], path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode if mode in ("shared", "multi") else "shared",
        "sources": sources,
    }
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


def zero_sink(ui: UInput) -> None:
    for code in _BTN:
        ui.write(ecodes.EV_KEY, code, 0)
    for code in _ABS:
        ui.write(ecodes.EV_ABS, code, 0)
    ui.syn()


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


def forward_event(ui: UInput, ev, src=None) -> None:
    if ev.type == ecodes.EV_SYN:
        ui.syn()
        return
    if ev.type == ecodes.EV_KEY and ev.code in _BTN:
        ui.write(ev.type, ev.code, ev.value)
        return
    if ev.type == ecodes.EV_ABS and ev.code in _ABS:
        dst = _ABS_DST[ev.code]
        src_range = source_abs_range(src, ev.code) if src is not None else None
        if src_range is not None:
            value = scale_axis(ev.value, src_range[0], src_range[1], dst.min, dst.max)
        else:
            value = max(dst.min, min(dst.max, ev.value))
        ui.write(ev.type, ev.code, value)


_STEAM_UI_CACHE = (0.0, False)
_STEAM_UI_ATOMS = (
    "GAMESCOPE_FOCUSED_APP",
    "STEAM_OVERLAY",
    "GAMESCOPE_BLUR_MODE",
)


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


def write_pid() -> None:
    path = pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()) + "\n")


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
    write_pid()
    sinks = [open_sink(0), open_sink(1)]
    sink_readers = [sink_event_reader(ui) for ui in sinks]
    sink_grabbed = [False, False]
    skip = {ui.device.path for ui in sinks if ui.device is not None}
    log(f"sinks {SINK_NAMES[0]} {SINK_NAMES[1]}")
    devices: list[InputDevice] = []
    cfg = load_config()
    last_scan = 0.0
    last_cfg_mtime = 0.0
    last_house = 0.0
    active: list[str | None] = [None, None]
    muted = False
    selected: list[InputDevice] = []
    fds: dict[int, InputDevice] = {}

    def housekeep(now: float) -> None:
        global _RELOAD
        nonlocal cfg, devices, selected, fds, muted, last_scan, last_cfg_mtime
        mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.is_file() else 0.0
        if _RELOAD or mtime != last_cfg_mtime or now - last_scan > 1.0 or not devices:
            _RELOAD = False
            last_cfg_mtime = mtime
            last_scan = now
            cfg = load_config()
            if not devices:
                devices = scan_devices(skip)
            else:
                devices = rescan_devices(devices, skip)
            selected = selected_sources(cfg, devices)
            fds = {dev.fd: dev for dev in selected}
        steam_ui = steam_ui_active(now)
        grab_sinks(sink_readers, steam_ui, sink_grabbed)
        want_mute = mute_path().is_file() or steam_ui
        if want_mute and not muted:
            for ui in sinks:
                zero_sink(ui)
            muted = True
            log("muted (Steam UI / overlay)")
        elif not want_mute and muted:
            muted = False
            log("unmuted")

    try:
        housekeep(time.monotonic())
        last_house = time.monotonic()
        while True:
            if not fds:
                time.sleep(0.05)
                housekeep(time.monotonic())
                last_house = time.monotonic()
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
                                zero_sink(ui)
                            active[slot] = dev.path
                        if active[slot] == dev.path:
                            for ev in events:
                                forward_event(ui, ev, src=dev)
                        continue
                    ui = sinks[0]
                    if any(is_activity(ev) for ev in events):
                        if active[0] not in (None, dev.path):
                            zero_sink(ui)
                        active[0] = dev.path
                    if active[0] == dev.path:
                        for ev in events:
                            forward_event(ui, ev, src=dev)
            now = time.monotonic()
            if not ready or now - last_house >= 0.25:
                housekeep(now)
                last_house = now
    finally:
        grab_sinks(sink_readers, False, sink_grabbed)
        for reader in sink_readers:
            if reader is None:
                continue
            try:
                reader.close()
            except OSError:
                pass
        for ui in sinks:
            try:
                zero_sink(ui)
                ui.close()
            except OSError:
                pass
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
        Fake("Odin2_Portal", "/dev/input/event12"),
        Fake("ASRock LED Controller", "/dev/input/event13", 0x26CE, 0x01A2),
        Fake("Microsoft X-Box 360 pad 0", "/dev/input/event14", 0x28DE, 0x11FF),
    ]
    # selected_sources expects InputDevice; duck-type name/path
    got = selected_sources(cfg, devices)  # type: ignore[arg-type]
    names = [d.name for d in got]
    assert "EmuPads P1" not in names
    assert "Sunshine (libvirtualhid) Mouse" not in names
    assert "ASRock LED Controller" not in names
    assert "Sunshine (libvirtualhid) AYN_Thor" in names
    assert "Odin2_Portal" in names
    assert "Microsoft X-Box 360 pad 0" not in names
    steam_only = [Fake("Microsoft X-Box 360 pad 0", "/dev/input/event14", 0x28DE, 0x11FF)]
    steam_got = selected_sources(cfg, steam_only)  # type: ignore[arg-type]
    assert [d.name for d in steam_got] == ["Microsoft X-Box 360 pad 0"]
    assert scale_axis(0, -32768, 32767, -32768, 32767) == 0
    assert scale_axis(32767, -32768, 32767, -32768, 32767) == 32767
    assert scale_axis(-32768, -32768, 32767, -32768, 32767) == -32768
    assert abs(scale_axis(128, 0, 255, -32768, 32767)) < 256
    assert scale_axis(0, 0, 255, -32768, 32767) == -32768
    assert scale_axis(255, 0, 255, -32768, 32767) == 32767
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
    global _STEAM_UI_CACHE
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

    print("emupads-mux self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--self-test"]:
        return self_test()
    return loop()


if __name__ == "__main__":
    raise SystemExit(main())
