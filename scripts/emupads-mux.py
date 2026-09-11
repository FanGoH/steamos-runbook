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


def source_abs_range(dev, code: int) -> tuple[int, int] | None:
    try:
        info = dev.absinfo(code)
    except (OSError, AttributeError, KeyError):
        return None
    if info is None:
        return None
    return int(info.min), int(info.max)


def forward_event(ui: UInput, ev, src=None) -> None:
    if ev.type == ecodes.EV_SYN:
        ui.syn()
        return
    if ev.type == ecodes.EV_KEY and ev.code in _BTN:
        ui.write(ev.type, ev.code, ev.value)
        return
    if ev.type == ecodes.EV_ABS and ev.code in _ABS:
        dst = _abs_info(ev.code)
        src_range = source_abs_range(src, ev.code) if src is not None else None
        if src_range is not None:
            value = scale_axis(ev.value, src_range[0], src_range[1], dst.min, dst.max)
        else:
            value = max(dst.min, min(dst.max, ev.value))
        ui.write(ev.type, ev.code, value)


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


def loop() -> int:
    global _RELOAD
    signal.signal(signal.SIGHUP, request_reload)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    write_pid()
    sinks = [open_sink(0), open_sink(1)]
    skip = {ui.device.path for ui in sinks if ui.device is not None}
    log(f"sinks {SINK_NAMES[0]} {SINK_NAMES[1]}")
    devices: list[InputDevice] = []
    cfg = load_config()
    last_scan = 0.0
    last_cfg_mtime = 0.0
    active: list[str | None] = [None, None]
    muted = False
    try:
        while True:
            now = time.monotonic()
            mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.is_file() else 0.0
            if _RELOAD or mtime != last_cfg_mtime or now - last_scan > 1.0:
                _RELOAD = False
                last_cfg_mtime = mtime
                last_scan = now
                cfg = load_config()
                for dev in devices:
                    try:
                        dev.close()
                    except OSError:
                        pass
                devices = scan_devices(skip)
            want_mute = mute_path().is_file()
            if want_mute and not muted:
                for ui in sinks:
                    zero_sink(ui)
                muted = True
                log("muted (overlay/QAM)")
            elif not want_mute and muted:
                muted = False
                log("unmuted")
            selected = selected_sources(cfg, devices)
            fds = {dev.fd: dev for dev in selected}
            if not fds:
                time.sleep(0.05)
                continue
            ready, _, _ = select.select(list(fds), [], [], 0.05)
            if muted:
                for fd in ready:
                    try:
                        for _ev in fds[fd].read():
                            pass
                    except OSError:
                        pass
                continue
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
    finally:
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
    print("emupads-mux self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--self-test"]:
        return self_test()
    return loop()


if __name__ == "__main__":
    raise SystemExit(main())
