#!/usr/bin/env python3
"""List host joysticks and bind Cemu/Azahar/Eden to chosen pads.

Sunshine x360 pads used to share one name/GUID, so emulators could not target
Thor vs Odin. After sunshine-ds names pads ``Sunshine (libvirtualhid) <client>``,
match on Thor / Odin / the device name. ``wait`` binds whichever pad receives
a button press. ``status`` / ``apply`` are the Decky EmuPads JSON API.

Cemu / Azahar / Eden bind to always-on ``EmuPads P1`` / ``P2`` uinput
sinks (``scripts/emupads-mux.py``). Apply / ``--match`` only changes mux
routing (shared = last pad used is player 1; multi = first two pads are
P1 and P2). Do not bind emulators to Sunshine pads directly.

Examples:

Azahar stores SDL joystick GUIDs in ``qt-config.ini``. Button indices come
from ``scripts/pad_profile.py`` (``GAMESTREAM_PAD_PROFILE``, default x360:
15 SDL buttons, L/R=6/7, Select/Start=10/11). Steam xpad 11-button numbering
puts Thor shoulders on Start/Select. Restart Azahar after a GUID or map change.
A second pad writes ``profiles\\2\\`` (saved profile named Player 2). Azahar
uses one active profile per instance.

Eden uses a CRC-less USB-bus GUID (``eden_guid``). ``player_0_`` is slot 0;
a second pad also rewrites ``player_1_`` and sets ``player_1_connected``.

Examples:
  python3 scripts/bind-gamepad.py list
  python3 scripts/bind-gamepad.py status
  python3 scripts/bind-gamepad.py apply --emu all --pads js3,js4 --mode multi
  python3 scripts/bind-gamepad.py apply --emu cemu --mode shared
  python3 scripts/bind-gamepad.py cemu --match Thor
  python3 scripts/bind-gamepad.py azahar --match Thor
"""
from __future__ import annotations

from pathlib import Path
import argparse
import copy
import json
import os
import re
import select
import signal
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from pad_profile import load_profile

INPUT_ROOT = Path("/sys/class/input")
SKIP_VENDORS = {"0000", "001f", "26ce", "046d", "beef"}
SKIP_PRODUCTS = {("1209", "0003")}  # libvirtualhid Mouse
SINK_VENDOR = "1209"
SINK_PRODUCTS = ("e301", "e302")
SINK_NAMES = ("EmuPads P1", "EmuPads P2")
MUX_SERVICE = "emupads-mux.service"
EV_KEY = 1
DEFAULT_CEMU_XML = Path.home() / ".var/app/info.cemu.Cemu/config/Cemu/controllerProfiles/controller0.xml"
DEFAULT_CEMU_XMLS = (
    DEFAULT_CEMU_XML,
    Path.home()
    / ".var/app/net.retrodeck.retrodeck/config/Cemu/controllerProfiles/controller0.xml",
)
DEFAULT_AZAHAR_INI = (
    Path.home() / ".var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini"
)
DEFAULT_EDEN_INI = Path.home() / ".config/eden/qt-config.ini"
EMUS = ("cemu", "azahar", "eden")

_CRC16_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0xA001 if _c & 1 else _c >> 1
    _CRC16_TABLE.append(_c)


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def sdl_crc16(data: bytes, crc: int = 0) -> int:
    for byte in data:
        crc = ((crc >> 8) ^ _CRC16_TABLE[(crc ^ byte) & 0xFF]) & 0xFFFF
    return crc


def sdl_guid(pad: dict[str, str]) -> str:
    crc = sdl_crc16(pad["name"].encode("utf-8"))
    raw = struct.pack(
        "<HHHHHHHH",
        int(pad["bustype"], 16),
        crc,
        int(pad["vendor"], 16),
        0,
        int(pad["product"], 16),
        0,
        int(pad.get("version") or "0", 16),
        0,
    )
    return raw.hex()


def cemu_uuid(pad: dict[str, str]) -> str:
    return f"{pad['index']}_{sdl_guid(pad)}"


def eden_guid(pad: dict[str, str]) -> str:
    """Eden/SDL3 USB-bus GUID: vendor/product/version, no name CRC."""
    raw = struct.pack(
        "<HHHHHHHH",
        0x0003,
        0,
        int(pad["vendor"], 16),
        0,
        int(pad["product"], 16),
        0,
        int(pad.get("version") or "0", 16),
        0,
    )
    return raw.hex()


# SDL community db names generic 045e:028e "Xbox 360 EasySMX" and uses Steam
# xpad 11-button numbers (LB=b4, Back=b6). libvirtualhid xbox_360 is 15-button
# (BTN_C/Z/TL2/TR2 reserved): 0A 1B 2C 3X 4Y 5Z 6LB 7RB 8TL2 9TR2 10Back
# 11Start 12Guide 13LS 14RS. The 11-button map makes Thor bumpers fire
# Select/Start. Same packing as pad_profile._AZAHAR_SPARSE_XBOX.
_X360_SDL_MAP = (
    "a:b0,b:b1,back:b10,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,dpup:h0.1,"
    "guide:b12,leftshoulder:b6,leftstick:b13,lefttrigger:a2,leftx:a0,lefty:a1,"
    "rightshoulder:b7,rightstick:b14,righttrigger:a5,rightx:a3,righty:a4,"
    "start:b11,x:b3,y:b4,platform:Linux,"
)
_EASYSMX_USB_GUID = "030000005e0400008e02000000010000"
_X360_USB_VERSION_GUID = "030000005e0400008e02000014010000"
_X360_BT_NOCRC_GUID = "050000005e0400008e02000014010000"
_THOR_SUNSHINE_NAME = "Sunshine (libvirtualhid) AYN_Thor"


def sdl_mapping_line(guid: str, name: str) -> str:
    label = name.replace(",", " ").replace("\n", " ").strip() or "Sunshine pad"
    return f"{guid},{label},{_X360_SDL_MAP}"


def sunshine_x360_pad(name: str, index: str = "0") -> dict[str, str]:
    pad = {
        "name": name,
        "bustype": "0005",
        "vendor": "045e",
        "product": "028e",
        "version": "0114",
        "index": index,
        "sunshine": "true",
        "steam": "false",
    }
    pad["guid"] = sdl_guid(pad)
    pad["eden_guid"] = eden_guid(pad)
    pad["cemu_uuid"] = cemu_uuid(pad)
    return pad


def sdl_override_guids(pad: dict[str, str] | None) -> list[str]:
    """Every 045e:028e GUID Cemu may look up, live CRC first."""
    seen: list[str] = []

    def add(guid: str | None) -> None:
        if guid and guid not in seen:
            seen.append(guid)

    if pad:
        add(pad.get("guid"))
        add(pad.get("eden_guid"))
    add(_EASYSMX_USB_GUID)
    add(_X360_USB_VERSION_GUID)
    add(_X360_BT_NOCRC_GUID)
    add(sunshine_x360_pad(_THOR_SUNSHINE_NAME)["guid"])
    return seen


def sdl_mapping_for_name(name: str, pad: dict[str, str] | None = None) -> str:
    return "".join(sdl_mapping_line(guid, name) + "\n" for guid in sdl_override_guids(pad))


def sdl_mapping_for_pad(pad: dict[str, str]) -> str:
    return sdl_mapping_for_name(pad["name"], pad)


def _event_node(device: Path) -> str:
    try:
        children = list(device.iterdir())
    except OSError:
        return ""
    for child in children:
        if child.name.startswith("event"):
            node = Path("/dev/input") / child.name
            if node.exists():
                return str(node)
    return ""


def list_joysticks(root: Path = INPUT_ROOT) -> list[dict[str, str]]:
    pads: list[dict[str, str]] = []
    index = 0
    for js in sorted(root.glob("js*/device"), key=lambda p: p.parent.name):
        vendor = _read(js / "id" / "vendor").lower().zfill(4)[-4:]
        product = _read(js / "id" / "product").lower().zfill(4)[-4:]
        version = _read(js / "id" / "version").lower().zfill(4)[-4:]
        bustype = _read(js / "id" / "bustype").lower().zfill(4)[-4:]
        name = _read(js / "name")
        if not vendor or vendor in SKIP_VENDORS:
            continue
        if (vendor, product) in SKIP_PRODUCTS:
            continue
        if name in SINK_NAMES or name.startswith("EmuPads P"):
            continue
        pad = {
            "js": js.parent.name,
            "name": name,
            "vendor": vendor,
            "product": product,
            "version": version or "0000",
            "bustype": bustype or "0003",
            "event": _event_node(js),
            "index": str(index),
            "sunshine": str("sunshine" in name.lower()).lower(),
            "steam": str(vendor == "28de" and product == "11ff").lower(),
        }
        pad["guid"] = sdl_guid(pad)
        pad["cemu_uuid"] = cemu_uuid(pad)
        pad["eden_guid"] = eden_guid(pad)
        pads.append(pad)
        index += 1
    return pads


def mux_config_path() -> Path:
    env = os.environ.get("EMUPADS_MUX_CONFIG")
    if env:
        return Path(env)
    cfg = os.environ.get("XDG_CONFIG_HOME")
    if cfg:
        return Path(cfg) / "emupads" / "mux.json"
    return Path.home() / ".config" / "emupads" / "mux.json"


def mux_pid_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "emupads-mux.pid"


def mux_mute_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "emupads-mute"


def mux_running() -> bool:
    path = mux_pid_path()
    if not path.is_file():
        return False
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def mux_muted() -> bool:
    return mux_mute_path().is_file()


def load_mux_config() -> dict:
    path = mux_config_path()
    if not path.is_file():
        return {"mode": "shared", "sources": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"mode": "shared", "sources": []}
    if not isinstance(data, dict):
        return {"mode": "shared", "sources": []}
    mode = str(data.get("mode") or "shared").lower()
    if mode not in ("shared", "multi"):
        mode = "shared"
    sources = data.get("sources") or []
    if not isinstance(sources, list):
        sources = []
    return {"mode": mode, "sources": sources}


def write_mux_routing(mode: str, sources: list) -> None:
    if mode not in ("shared", "multi"):
        raise SystemExit(f"unknown mux mode {mode!r} (shared|multi)")
    path = mux_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"mode": mode, "sources": sources}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if mux_running():
        try:
            pid = int(mux_pid_path().read_text(encoding="utf-8").strip())
            os.kill(pid, signal.SIGHUP)
        except (OSError, ValueError):
            pass


def mux_source_specs(pads: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for pad in pads:
        spec: dict[str, str] = {"name": pad.get("name", "")}
        event = pad.get("event") or ""
        if event:
            spec["event"] = event
        out.append(spec)
    return out


def sink_template(name: str, product: str, index: int) -> dict[str, str]:
    pad = {
        "js": "",
        "name": name,
        "vendor": SINK_VENDOR,
        "product": product,
        "version": "0114",
        "bustype": "0003",
        "event": "",
        "index": str(index),
        "sunshine": "false",
        "steam": "false",
    }
    pad["guid"] = sdl_guid(pad)
    pad["cemu_uuid"] = cemu_uuid(pad)
    pad["eden_guid"] = eden_guid(pad)
    return pad


def list_sink_joysticks(root: Path = INPUT_ROOT) -> list[dict[str, str]]:
    """EmuPads P1 / P2 bind targets. Never listed as plugin sources."""
    found: dict[str, dict[str, str]] = {}
    for js in sorted(root.glob("js*/device"), key=lambda p: p.parent.name):
        name = _read(js / "name")
        if name not in SINK_NAMES:
            continue
        vendor = _read(js / "id" / "vendor").lower().zfill(4)[-4:]
        product = _read(js / "id" / "product").lower().zfill(4)[-4:]
        version = _read(js / "id" / "version").lower().zfill(4)[-4:]
        bustype = _read(js / "id" / "bustype").lower().zfill(4)[-4:]
        index = 0 if name == "EmuPads P1" else 1
        pad = {
            "js": js.parent.name,
            "name": name,
            "vendor": vendor or SINK_VENDOR,
            "product": product or SINK_PRODUCTS[index],
            "version": version or "0114",
            "bustype": bustype or "0003",
            "event": _event_node(js),
            "index": str(index),
            "sunshine": "false",
            "steam": "false",
        }
        pad["guid"] = sdl_guid(pad)
        pad["cemu_uuid"] = cemu_uuid(pad)
        pad["eden_guid"] = eden_guid(pad)
        found[name] = pad
    out = []
    for i, name in enumerate(SINK_NAMES):
        out.append(found.get(name) or sink_template(name, SINK_PRODUCTS[i], i))
    if found:
        return [p for p in out if p.get("js")]
    return []


def bind_sinks_for_mode(mode: str, root: Path = INPUT_ROOT) -> list[dict[str, str]]:
    sinks = list_sink_joysticks(root)
    live = {s["name"]: s for s in sinks}
    p1 = live.get("EmuPads P1") or sink_template("EmuPads P1", SINK_PRODUCTS[0], 0)
    p2 = live.get("EmuPads P2") or sink_template("EmuPads P2", SINK_PRODUCTS[1], 1)
    if mode == "multi":
        return [p1, p2]
    return [p1]


def ensure_mux_running() -> None:
    if os.environ.get("EMUPADS_MUX_SKIP_START") == "1":
        return
    if mux_running() and list_sink_joysticks():
        return
    started = subprocess.run(
        ["systemctl", "--user", "start", MUX_SERVICE],
        capture_output=True,
        text=True,
    )
    if started.returncode == 0:
        for _ in range(20):
            if mux_running() and list_sink_joysticks():
                return
            time.sleep(0.25)
    if mux_running() and list_sink_joysticks():
        return
    log = Path.home() / "steamos-playbook" / "logs" / "emupads-mux.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    mux_script = Path(__file__).resolve().parent / "emupads-mux.py"
    env = os.environ.copy()
    env.setdefault("HOME", str(Path.home()))
    with log.open("a", encoding="utf-8") as fh:
        subprocess.Popen(
            [sys.executable, str(mux_script)],
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    for _ in range(40):
        if mux_running() and list_sink_joysticks():
            return
        time.sleep(0.25)
    raise SystemExit(
        "EmuPads mux is not running (P1/P2 missing). Start emupads-mux.service."
    )


def resolve_pads(
    pads: list[dict[str, str]], tokens: list[str]
) -> list[dict[str, str]] | None:
    """Resolve ordered ``jsN`` / GUID / uuid / name tokens. None if any miss."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in tokens:
        tok = raw.strip()
        if not tok:
            continue
        hit = None
        low = tok.lower()
        for pad in pads:
            keys = (
                pad.get("js", ""),
                pad.get("guid", ""),
                pad.get("cemu_uuid", ""),
                pad.get("eden_guid", ""),
            )
            if tok in keys or low == pad.get("name", "").lower():
                hit = pad
                break
        if hit is None:
            hit = match_pad(pads, tok)
        if hit is None:
            return None
        ident = hit.get("js") or hit.get("guid") or hit["name"]
        if ident in seen:
            continue
        seen.add(ident)
        out.append(hit)
    return out


def match_pad(pads: list[dict[str, str]], needle: str) -> dict[str, str] | None:
    n = needle.strip().lower()
    if not n:
        return None
    hits = [p for p in pads if n in p["name"].lower() or n in p.get("js", "")]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        named = [p for p in hits if n in p["name"].lower()]
        if len(named) == 1:
            return named[0]
        # Two Sunshine pads can share one client name (Thor + Thor wrap).
        names = {p["name"] for p in named or hits}
        if len(names) == 1:
            return (named or hits)[0]
        return None
    return None


def pick_live_sunshine_pad(pads: list[dict[str, str]]) -> dict[str, str] | None:
    """The Sunshine pad currently injected (not Mouse, not Steam virtual)."""
    live = [
        p
        for p in pads
        if p.get("sunshine") == "true" and "mouse" not in p["name"].lower()
    ]
    if not live:
        return None
    if len(live) == 1:
        return live[0]
    for needle in ("thor", "odin"):
        hits = [p for p in live if needle in p["name"].lower()]
        if len(hits) == 1:
            return hits[0]
    return live[0]


def wait_button(pads: list[dict[str, str]], timeout: float) -> dict[str, str] | None:
    event_fmt = struct.Struct("llHHi")
    fds: dict[int, dict[str, str]] = {}
    try:
        for pad in pads:
            path = pad.get("event") or ""
            if not path:
                continue
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            fds[fd] = pad
        if not fds:
            return None
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select(list(fds), [], [], remaining)
            for fd in ready:
                data = os.read(fd, event_fmt.size * 16)
                for off in range(0, len(data) - event_fmt.size + 1, event_fmt.size):
                    _sec, _usec, ev_type, _code, value = event_fmt.unpack_from(data, off)
                    if ev_type == EV_KEY and value == 1:
                        return fds[fd]
    finally:
        for fd in fds:
            os.close(fd)


def _controller_entries(controller: ET.Element) -> list[ET.Element]:
    mappings = controller.find("mappings")
    if mappings is None:
        return []
    return list(mappings.findall("entry"))


def _set_text(parent: ET.Element, tag: str, value: str) -> None:
    node = parent.find(tag)
    if node is None:
        node = ET.SubElement(parent, tag)
    node.text = value


def _set_mappings(controller: ET.Element, entries: list[ET.Element]) -> None:
    mappings = controller.find("mappings")
    if mappings is None:
        mappings = ET.SubElement(controller, "mappings")
    for child in list(mappings):
        mappings.remove(child)
    for entry in entries:
        mappings.append(copy.deepcopy(entry))


def _mapping_owner_uuids(root: ET.Element) -> list[str]:
    owners: list[str] = []
    for controller in root.findall("controller"):
        if _controller_entries(controller):
            owners.append(controller.findtext("uuid") or "")
    return owners


# SteamInput-P1 Wii U GamePad (SDL GameController). moonlight.xml is a Wii U
# Pro profile: it omits mapping 11 and rotates 15–25, so analog 7/8 look
# fine while hat/axis-splits fight the left stick.
CANONICAL_CEMU_GAMEPAD = (
    (1, 1),
    (2, 0),
    (3, 3),
    (4, 2),
    (5, 9),
    (6, 10),
    (7, 42),
    (8, 43),
    (9, 6),
    (10, 4),
    (11, 11),
    (12, 12),
    (13, 13),
    (14, 14),
    (15, 7),
    (16, 8),
    (17, 45),
    (18, 39),
    (19, 44),
    (20, 38),
    (21, 47),
    (22, 41),
    (23, 46),
    (24, 40),
    (25, 8),
)

# SteamInput-P2 Wii U Pro Controller (no GamePad display mapping 11).
CANONICAL_CEMU_PRO = (
    (1, 0),
    (2, 1),
    (3, 2),
    (4, 3),
    (5, 9),
    (6, 10),
    (7, 42),
    (8, 43),
    (9, 6),
    (10, 4),
    (12, 11),
    (13, 12),
    (14, 13),
    (15, 14),
    (16, 7),
    (17, 8),
    (18, 45),
    (19, 39),
    (20, 44),
    (21, 38),
    (22, 47),
    (23, 41),
    (24, 46),
    (25, 40),
)

MINIMAL_CEMU_PRO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<emulated_controller>
	<type>Wii U Pro Controller</type>
	<controller>
		<api>SDLController</api>
		<uuid>0_placeholder</uuid>
		<display_name>placeholder</display_name>
		<rumble>0</rumble>
		<mappings>
		</mappings>
	</controller>
</emulated_controller>
"""


def _mapping_ids(entries: list[ET.Element]) -> set[str]:
    return {(entry.findtext("mapping") or "") for entry in entries}


def _entries_from_pairs(pairs: tuple[tuple[int, int], ...]) -> list[ET.Element]:
    out: list[ET.Element] = []
    for mapping, button in pairs:
        entry = ET.Element("entry")
        m = ET.SubElement(entry, "mapping")
        m.text = str(mapping)
        b = ET.SubElement(entry, "button")
        b.text = str(button)
        out.append(entry)
    return out


def _load_steaminput_p1_mappings(xml_path: Path | None) -> list[ET.Element]:
    """Copy RetroDECK SteamInput-P1 button maps; never its Steam-virtual uuid."""
    if xml_path is None:
        return []
    p1 = xml_path.parent / "SteamInput-P1.xml"
    if not p1.is_file():
        return []
    try:
        root = ET.parse(p1).getroot()
    except ET.ParseError:
        return []
    for controller in root.findall("controller"):
        entries = _controller_entries(controller)
        ids = _mapping_ids(entries)
        if "7" in ids and "8" in ids and "11" in ids:
            return entries
    return []


def _gamepad_mappings(
    richest: list[ET.Element], xml_path: Path | None = None
) -> list[ET.Element]:
    template = _load_steaminput_p1_mappings(xml_path)
    if template:
        return template
    ids = _mapping_ids(richest)
    if "11" in ids and "7" in ids and "8" in ids:
        return richest
    return _entries_from_pairs(CANONICAL_CEMU_GAMEPAD)


def _load_steaminput_p2_mappings(xml_path: Path | None) -> list[ET.Element]:
    if xml_path is None:
        return []
    p2 = xml_path.parent / "SteamInput-P2.xml"
    if not p2.is_file():
        return []
    try:
        root = ET.parse(p2).getroot()
    except ET.ParseError:
        return []
    for controller in root.findall("controller"):
        entries = _controller_entries(controller)
        if _mapping_ids(entries):
            return entries
    return []


def _pro_mappings(
    richest: list[ET.Element], xml_path: Path | None = None
) -> list[ET.Element]:
    template = _load_steaminput_p2_mappings(xml_path)
    if template:
        return template
    ids = _mapping_ids(richest)
    if "7" in ids and "8" in ids:
        return richest
    return _entries_from_pairs(CANONICAL_CEMU_PRO)


def controller1_path(xml_path: Path) -> Path:
    if xml_path.name.startswith("controller0"):
        return xml_path.with_name(xml_path.name.replace("controller0", "controller1", 1))
    return xml_path.parent / "controller1.xml"


def patch_cemu_xml(
    text: str,
    uuid: str,
    display_name: str,
    xml_path: Path | None = None,
) -> str:
    """Add ``uuid`` to player 0 and attach GamePad mappings to that pad only."""
    root = ET.fromstring(text)
    type_node = root.find("type")
    if type_node is None:
        type_node = ET.Element("type")
        root.insert(0, type_node)
    type_node.text = "Wii U GamePad"

    controllers = root.findall("controller")
    if not controllers:
        raise ValueError("controller xml missing <controller>")

    richest: list[ET.Element] = []
    for controller in controllers:
        entries = _controller_entries(controller)
        if len(entries) > len(richest):
            richest = entries

    target = None
    for controller in list(controllers):
        name = controller.findtext("display_name") or ""
        # Old Moonlight Uri.encode turned "AYN Thor" into AYN20Thor.
        if "AYN20Thor" in name:
            root.remove(controller)
            continue
        # Sunshine also injects a mouse (1209:0003). Cemu prepends it as
        # controller 0 and GamePad sticks go to the mouse (inverted Y, dead X).
        if "libvirtualhid Mouse" in name:
            root.remove(controller)
            continue
        if (controller.findtext("uuid") or "") == uuid:
            target = controller
    remaining = root.findall("controller")
    if not remaining and target is None:
        raise ValueError("controller xml missing <controller>")
    if target is None:
        target = copy.deepcopy(remaining[0] if remaining else controllers[0])
        rumble = target.find("rumble")
        if rumble is None:
            rumble = ET.SubElement(target, "rumble")
        rumble.text = "0"
        root.append(target)

    _set_text(target, "api", "SDLController")
    _set_text(target, "uuid", uuid)
    _set_text(target, "display_name", display_name)

    mappings = _gamepad_mappings(richest, xml_path)
    for controller in root.findall("controller"):
        if controller is target:
            _set_mappings(controller, mappings)
        else:
            _set_mappings(controller, [])

    # Player 0 is the first <controller> uuid. Analog sticks follow that
    # device. Steam wrap must stay listed after Sunshine with empty mappings.
    ordered = root.findall("controller")
    for controller in ordered:
        root.remove(controller)
    root.append(target)
    for controller in ordered:
        if controller is not target:
            root.append(controller)

    ET.indent(root, space="\t")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    ) + "\n"


def patch_cemu_pro_xml(
    text: str,
    uuid: str,
    display_name: str,
    xml_path: Path | None = None,
) -> str:
    """Bind player 1 as a Wii U Pro Controller (``controller1.xml``)."""
    root = ET.fromstring(text)
    type_node = root.find("type")
    if type_node is None:
        type_node = ET.Element("type")
        root.insert(0, type_node)
    type_node.text = "Wii U Pro Controller"

    controllers = root.findall("controller")
    if not controllers:
        raise ValueError("controller xml missing <controller>")

    richest: list[ET.Element] = []
    for controller in controllers:
        entries = _controller_entries(controller)
        if len(entries) > len(richest):
            richest = entries

    target = None
    for controller in list(controllers):
        name = controller.findtext("display_name") or ""
        if "AYN20Thor" in name or "libvirtualhid Mouse" in name:
            root.remove(controller)
            continue
        if (controller.findtext("uuid") or "") == uuid:
            target = controller
    remaining = root.findall("controller")
    if not remaining and target is None:
        raise ValueError("controller xml missing <controller>")
    if target is None:
        target = copy.deepcopy(remaining[0] if remaining else controllers[0])
        rumble = target.find("rumble")
        if rumble is None:
            rumble = ET.SubElement(target, "rumble")
        rumble.text = "0"
        root.append(target)

    _set_text(target, "api", "SDLController")
    _set_text(target, "uuid", uuid)
    _set_text(target, "display_name", display_name)

    mappings = _pro_mappings(richest, xml_path)
    for controller in root.findall("controller"):
        if controller is target:
            _set_mappings(controller, mappings)
        else:
            _set_mappings(controller, [])

    ordered = root.findall("controller")
    for controller in ordered:
        root.remove(controller)
    root.append(target)
    for controller in ordered:
        if controller is not target:
            root.append(controller)

    ET.indent(root, space="\t")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    ) + "\n"


def is_cemu_comm(comm: str) -> bool:
    """Linux ``comm`` is 15 chars, so Flatpak Cemu shows as ``Cemu_relwithdeb``."""
    return comm.strip().lower().startswith("cemu")


def cemu_running() -> bool:
    try:
        import subprocess

        out = subprocess.check_output(["ps", "-eo", "comm="], text=True)
    except OSError:
        return False
    return any(is_cemu_comm(line) for line in out.splitlines())


def is_azahar_comm(comm: str) -> bool:
    return comm.strip() == "azahar"


def azahar_running() -> bool:
    try:
        import subprocess

        out = subprocess.check_output(["ps", "-eo", "comm="], text=True)
    except OSError:
        return False
    return any(is_azahar_comm(line) for line in out.splitlines())


def is_eden_comm(comm: str) -> bool:
    name = comm.strip().lower()
    return name in {"eden", "eden.desktop"} or name.startswith("eden")


def eden_running() -> bool:
    try:
        import subprocess

        out = subprocess.check_output(["ps", "-eo", "comm="], text=True)
    except OSError:
        return False
    return any(is_eden_comm(line) for line in out.splitlines())


def azahar_guids(text: str) -> list[str]:
    return re.findall(r"guid:([0-9a-f]{32})", text)


def azahar_guid_for_slot(text: str, slot: int) -> str:
    pat = re.compile(
        rf"^profiles\\{slot}\\button_a=.*guid:([0-9a-f]{{32}})",
        re.M,
    )
    match = pat.search(text)
    return match.group(1) if match else ""


def azahar_map_for_profile(name: str | None = None) -> dict[str, str]:
    return load_profile(name).azahar_map


def _set_ini_line(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    pat = re.compile(r"^" + re.escape(key) + r"=.*$", re.M)
    if pat.search(text):
        text = pat.sub(lambda _m: line, text, count=1)
    else:
        text += f"\n{line}\n"
    dkey = key + "\\default"
    dpat = re.compile(r"^" + re.escape(dkey) + r"=.*$", re.M)
    drepl = dkey + "=false"
    if dpat.search(text):
        text = dpat.sub(lambda _m: drepl, text, count=1)
    return text


def patch_azahar_ini(
    text: str,
    guid: str,
    profile_name: str | None = None,
    slot: int = 1,
) -> str:
    """Bind Azahar profile ``slot`` (1-based) to ``guid`` with the pad map."""
    if not re.fullmatch(r"[0-9a-f]{32}", guid):
        raise ValueError(f"bad SDL GUID {guid!r}")
    if slot < 1:
        raise ValueError(f"bad Azahar profile slot {slot}")
    if slot > 1:
        text = _ensure_azahar_profile_slot(text, slot)
    for name, tmpl in azahar_map_for_profile(profile_name).items():
        key = f"profiles\\{slot}\\" + name
        text = _set_ini_line(text, key, '"' + tmpl.format(guid=guid) + '"')
    if slot > 1:
        text = _set_ini_line(text, f"profiles\\{slot}\\name", f"Player {slot}")
        text = _set_ini_line(text, "profiles\\size", str(max(_azahar_profile_size(text), slot)))
    return text


def _azahar_profile_size(text: str) -> int:
    match = re.search(r"^profiles\\size=(\d+)\s*$", text, re.M)
    return int(match.group(1)) if match else 1


def _ensure_azahar_profile_slot(text: str, slot: int) -> str:
    prefix = f"profiles\\{slot}\\"
    if re.search(r"^" + re.escape(prefix), text, re.M):
        return text
    extras: list[str] = []
    for line in text.splitlines():
        if line.startswith("profiles\\1\\"):
            extras.append("profiles\\" + f"{slot}\\" + line[len("profiles\\1\\") :])
    if not extras:
        return text
    block = "\n".join(extras)
    size_pat = re.compile(r"^profiles\\size=.*$", re.M)
    if size_pat.search(text):
        return size_pat.sub(lambda _m: block + "\n" + _m.group(0), text, count=1)
    return text.rstrip() + "\n" + block + "\n"


def eden_guid_for_player(text: str, player: int) -> str:
    pat = re.compile(
        rf'^player_{player}_button_a=.*guid:([0-9a-fA-F]{{32}})',
        re.M,
    )
    match = pat.search(text)
    return (match.group(1).lower() if match else "")


def patch_eden_ini(text: str, pads: list[dict[str, str]]) -> str:
    """Rewrite Eden ``player_N_`` SDL bindings for the ordered pads."""
    guids = [eden_guid(pad) for pad in pads]
    if not guids:
        return text
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        handled = False
        for index, guid in enumerate(guids):
            prefix = f"player_{index}_"
            if not line.startswith(prefix) or "engine:sdl" not in line:
                continue
            stripped = re.sub(r",guid:[0-9a-fA-F]+", "", line)
            port = f"port:{index},"
            if f"guid:{guid}" not in stripped:
                if f"engine:sdl,{port}" in stripped:
                    stripped = stripped.replace(
                        f"engine:sdl,{port}",
                        f"engine:sdl,{port}guid:{guid},",
                    )
                elif "engine:sdl," in stripped:
                    stripped = stripped.replace(
                        "engine:sdl,",
                        f"engine:sdl,guid:{guid},",
                    )
            line = stripped
            handled = True
            break
        if not handled and len(guids) >= 2:
            if line.startswith("player_1_connected=") and not line.startswith(
                "player_1_connected\\"
            ):
                line = "player_1_connected=true\n"
            elif line.startswith("player_1_connected\\default="):
                line = "player_1_connected\\default=false\n"
        if not handled and len(guids) == 1:
            if line.startswith("player_1_connected=") and not line.startswith(
                "player_1_connected\\"
            ):
                line = "player_1_connected=false\n"
        out.append(line)
    return "".join(out)


def _write_changed(path: Path, old: str, new: str, bak_suffix: str) -> bool:
    if new == old:
        return False
    bak = path.with_suffix(path.suffix + bak_suffix)
    if not bak.exists():
        bak.write_text(old)
    path.write_text(new)
    return True


def _cemu_xml_paths(explicit: str | None) -> list[Path]:
    if explicit:
        return [Path(explicit)]
    return [path for path in DEFAULT_CEMU_XMLS if path.is_file()]


def _pad_summary(pad: dict[str, str] | None) -> dict[str, str]:
    if pad is None:
        return {}
    return {
        "js": pad.get("js", ""),
        "name": pad.get("name", ""),
        "guid": pad.get("guid", ""),
        "cemu_uuid": pad.get("cemu_uuid", ""),
        "eden_guid": pad.get("eden_guid", ""),
        "sunshine": pad.get("sunshine", "false"),
        "steam": pad.get("steam", "false"),
    }


def _find_pad(
    pads: list[dict[str, str]], *, guid: str = "", uuid: str = "", eden: str = ""
) -> dict[str, str] | None:
    guid = guid.lower()
    eden = eden.lower()
    for pad in pads:
        if uuid and pad.get("cemu_uuid") == uuid:
            return pad
        if guid and pad.get("guid", "").lower() == guid:
            return pad
        if eden and pad.get("eden_guid", "").lower() == eden:
            return pad
    return None


def cemu_players_from_xml(path: Path, pads: list[dict[str, str]]) -> list[dict]:
    players: list[dict] = []
    for slot, xml_path in ((0, path), (1, controller1_path(path))):
        if not xml_path.is_file():
            continue
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError:
            continue
        first = root.find("controller")
        uuid = (first.findtext("uuid") if first is not None else "") or ""
        name = (first.findtext("display_name") if first is not None else "") or ""
        pad = _find_pad(pads, uuid=uuid)
        players.append(
            {
                "slot": slot,
                "path": str(xml_path),
                "uuid": uuid,
                "name": name,
                "type": root.findtext("type") or "",
                "pad": _pad_summary(pad),
            }
        )
    return players


def azahar_players_from_ini(path: Path, pads: list[dict[str, str]]) -> list[dict]:
    if not path.is_file():
        return []
    text = path.read_text()
    players: list[dict] = []
    for slot in (1, 2):
        guid = azahar_guid_for_slot(text, slot)
        if not guid:
            continue
        pad = _find_pad(pads, guid=guid)
        players.append(
            {
                "slot": slot - 1,
                "guid": guid,
                "name": pad["name"] if pad else "",
                "pad": _pad_summary(pad),
            }
        )
    return players


def eden_players_from_ini(path: Path, pads: list[dict[str, str]]) -> list[dict]:
    if not path.is_file():
        return []
    text = path.read_text()
    players: list[dict] = []
    for slot in (0, 1):
        guid = eden_guid_for_player(text, slot)
        if not guid:
            continue
        pad = _find_pad(pads, eden=guid)
        players.append(
            {
                "slot": slot,
                "guid": guid,
                "name": pad["name"] if pad else "",
                "pad": _pad_summary(pad),
            }
        )
    return players


def status_payload(
    sysfs: Path,
    *,
    cemu_xml: str | None = None,
    azahar_ini: str | None = None,
    eden_ini: str | None = None,
) -> dict:
    pads = list_joysticks(sysfs)
    sinks = list_sink_joysticks(sysfs)
    lookup = pads + sinks
    cemu_paths = _cemu_xml_paths(cemu_xml)
    azahar_path = Path(azahar_ini) if azahar_ini else DEFAULT_AZAHAR_INI
    eden_path = Path(eden_ini) if eden_ini else DEFAULT_EDEN_INI
    cemu_players: list[dict] = []
    for path in cemu_paths:
        cemu_players.extend(cemu_players_from_xml(path, lookup))
    mux_cfg = load_mux_config()
    return {
        "pads": pads,
        "profile": load_profile().name,
        "mux": {
            "running": mux_running(),
            "muted": mux_muted(),
            "mode": mux_cfg.get("mode") or "shared",
            "sources": mux_cfg.get("sources") or [],
            "sinks": [_pad_summary(s) for s in sinks],
            "service": MUX_SERVICE,
        },
        "emus": {
            "cemu": {
                "running": cemu_running(),
                "paths": [str(p) for p in cemu_paths],
                "players": cemu_players,
                "p2": "Shared P1: last pad used. Multi: second selected pad → Wii U Pro in controller1.xml.",
            },
            "azahar": {
                "running": azahar_running(),
                "paths": [str(azahar_path)] if azahar_path.is_file() else [],
                "players": azahar_players_from_ini(azahar_path, lookup),
                "p2": "Shared P1 even if Azahar barely does MP. Multi writes profiles\\2\\ (one active profile per instance).",
            },
            "eden": {
                "running": eden_running(),
                "paths": [str(eden_path)] if eden_path.is_file() else [],
                "players": eden_players_from_ini(eden_path, lookup),
                "p2": "P2 uses product e302 so Eden GUIDs differ. Shared mode binds P1 only.",
            },
        },
    }


def _pick_ordered(args: argparse.Namespace) -> tuple[list[dict[str, str]] | None, str]:
    pads = list_joysticks(Path(args.sysfs))
    tokens: list[str] = []
    if getattr(args, "pads", None):
        tokens = [part for part in args.pads.split(",") if part.strip()]
    elif getattr(args, "match", None):
        tokens = [part for part in args.match.split(",") if part.strip()]
    if tokens:
        resolved = resolve_pads(pads, tokens)
        if resolved is None:
            names = ", ".join(p["name"] for p in pads) or "(none)"
            return None, f"No pad matched {tokens!r}. Connected: {names}"
        return resolved, ""
    if getattr(args, "wait", False):
        print("Press a button on the pad to bind…", file=sys.stderr)
        pad = wait_button(pads, args.timeout)
        if pad is None:
            return None, "No button press."
        return [pad], ""
    if getattr(args, "all_sources", False):
        return [], ""
    return None, ""


def apply_cemu_pads(
    paths: list[Path],
    ordered: list[dict[str, str]],
    *,
    force: bool,
) -> tuple[list[str], int, bool]:
    messages: list[str] = []
    rc = 0
    changed_any = False
    if not ordered:
        return messages, 2, False
    for path in paths:
        if not path.is_file():
            messages.append(f"Missing {path}")
            rc = max(rc, 1)
            continue
        text = path.read_text()
        p1 = ordered[0]
        new = patch_cemu_xml(text, cemu_uuid(p1), p1["name"], path)
        changed = _write_changed(path, text, new, ".bak-bind-gamepad")
        changed_any = changed_any or changed
        if changed:
            messages.append(f"Bound Cemu player 1 to {cemu_uuid(p1)} ({p1['name']}) in {path}")
        else:
            messages.append(f"Cemu player 1 already {cemu_uuid(p1)} ({p1['name']}) in {path}")
        if len(ordered) >= 2:
            p2 = ordered[1]
            p2_path = controller1_path(path)
            old = p2_path.read_text() if p2_path.is_file() else MINIMAL_CEMU_PRO_XML
            p2_xml = patch_cemu_pro_xml(old, cemu_uuid(p2), p2["name"], p2_path)
            p2_changed = _write_changed(p2_path, old if p2_path.is_file() else "", p2_xml, ".bak-bind-gamepad")
            changed_any = changed_any or p2_changed
            if p2_changed:
                messages.append(
                    f"Bound Cemu player 2 to {cemu_uuid(p2)} ({p2['name']}) in {p2_path}"
                )
            else:
                messages.append(
                    f"Cemu player 2 already {cemu_uuid(p2)} ({p2['name']}) in {p2_path}"
                )
    if changed_any and cemu_running() and not force:
        messages.append("Cemu is running; restart it for the bind to apply.")
        rc = max(rc, 2)
    return messages, rc, changed_any


def apply_azahar_pads(
    path: Path,
    ordered: list[dict[str, str]],
    *,
    force: bool,
) -> tuple[list[str], int, bool]:
    messages: list[str] = []
    if not path.is_file():
        return [f"Missing {path}"], 1, False
    if not ordered:
        return messages, 2, False
    text = path.read_text()
    new = text
    try:
        new = patch_azahar_ini(new, ordered[0]["guid"], slot=1)
        if len(ordered) >= 2:
            new = patch_azahar_ini(new, ordered[1]["guid"], slot=2)
    except ValueError as exc:
        return [str(exc)], 1, False
    names = " + ".join(p["name"] for p in ordered[:2])
    changed = _write_changed(path, text, new, ".bak-bind-gamepad")
    if changed:
        messages.append(f"Bound Azahar to {names} in {path}")
    else:
        messages.append(f"Azahar already bound to {names} in {path}")
    rc = 0
    if changed and azahar_running() and not force:
        messages.append("Azahar is running; restart it for the bind to apply.")
        rc = 2
    return messages, rc, changed


def apply_eden_pads(
    path: Path,
    ordered: list[dict[str, str]],
    *,
    force: bool,
) -> tuple[list[str], int, bool]:
    messages: list[str] = []
    if not path.is_file():
        return [f"Missing {path}"], 1, False
    if not ordered:
        return messages, 2, False
    text = path.read_text()
    new = patch_eden_ini(text, ordered[:2])
    names = " + ".join(f"{p['name']} ({eden_guid(p)})" for p in ordered[:2])
    changed = _write_changed(path, text, new, ".bak-bind-gamepad")
    if changed:
        messages.append(f"Bound Eden to {names} in {path}")
    else:
        messages.append(f"Eden already bound to {names} in {path}")
    rc = 0
    if changed and eden_running() and not force:
        messages.append("Eden is running; restart it for the bind to apply.")
        rc = 2
    return messages, rc, changed


def cmd_status(args: argparse.Namespace) -> int:
    payload = status_payload(
        Path(args.sysfs),
        cemu_xml=getattr(args, "xml", None),
        azahar_ini=getattr(args, "azahar_ini", None),
        eden_ini=getattr(args, "eden_ini", None),
    )
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if payload["pads"] else 2


def _emit_apply(
    *,
    rc: int,
    emu: str,
    ordered: list[dict[str, str]],
    messages: list[str],
    changed: bool = False,
    mode: str = "shared",
) -> int:
    payload = {
        "ok": rc == 0 or (rc == 2 and bool(ordered)),
        "rc": rc,
        "emu": emu,
        "mode": mode,
        "pads": [_pad_summary(p) for p in ordered[:2]],
        "messages": messages,
        "changed": changed,
        "restart": rc == 2 and changed,
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    for line in messages:
        print(line, file=sys.stderr)
    return rc


def cmd_apply(args: argparse.Namespace) -> int:
    picked, pick_err = _pick_ordered(args)
    emu = (getattr(args, "emu", None) or "all").strip().lower()
    if pick_err:
        return _emit_apply(rc=2, emu=emu, ordered=[], messages=[pick_err])
    if emu not in ("all", *EMUS):
        return _emit_apply(
            rc=1,
            emu=emu,
            ordered=[],
            messages=[f"Unknown emu {emu!r}. Use cemu, azahar, eden, or all."],
        )
    mode = (getattr(args, "mode", None) or "").strip().lower()
    if not mode:
        mode = str(load_mux_config().get("mode") or "shared")
    if mode not in ("shared", "multi"):
        return _emit_apply(
            rc=1,
            emu=emu,
            ordered=[],
            messages=[f"Unknown mux mode {mode!r}. Use shared or multi."],
        )
    sysfs = Path(args.sysfs)
    skip_mux = os.environ.get("EMUPADS_MUX_SKIP_START") == "1" or str(sysfs) != str(INPUT_ROOT)
    if not skip_mux:
        ensure_mux_running()
    if getattr(args, "all_sources", False) or picked == []:
        write_mux_routing(mode, [])
        messages_route = ["Mux routing: all host pads → " + ("shared P1" if mode == "shared" else "P1/P2")]
        picked_out: list[dict[str, str]] = []
    elif picked is None:
        cfg = load_mux_config()
        if not mux_config_path().is_file():
            write_mux_routing(mode, [])
            messages_route = ["Mux routing defaulted to all host pads (shared P1)" if mode == "shared" else "Mux routing defaulted to all host pads"]
        else:
            write_mux_routing(mode, cfg.get("sources") or [])
            messages_route = [f"Mux routing unchanged ({mode})"]
        picked_out = []
    else:
        write_mux_routing(mode, mux_source_specs(picked[:2] if mode == "multi" else picked))
        names = " + ".join(p["name"] for p in picked[:2])
        messages_route = [f"Mux routing {mode}: {names or 'all'}"]
        picked_out = picked
    sinks = bind_sinks_for_mode(mode, sysfs)
    if not skip_mux and not any(s.get("js") for s in list_sink_joysticks(sysfs)):
        return _emit_apply(
            rc=1,
            emu=emu,
            ordered=[],
            messages=["EmuPads mux is not running (P1/P2 missing)."],
            mode=mode,
        )
    targets = EMUS if emu == "all" else (emu,)
    messages: list[str] = list(messages_route)
    rc = 0
    changed_any = False
    force = bool(getattr(args, "force", False))
    for name in targets:
        if name == "cemu":
            paths = _cemu_xml_paths(getattr(args, "xml", None))
            if not paths:
                messages.append("No Cemu controller0.xml found.")
                rc = max(rc, 1)
                continue
            msgs, code, changed = apply_cemu_pads(paths, sinks, force=force)
        elif name == "azahar":
            ini = getattr(args, "ini", None) if emu == "azahar" else None
            path = Path(ini) if ini else DEFAULT_AZAHAR_INI
            msgs, code, changed = apply_azahar_pads(path, sinks, force=force)
        else:
            ini = getattr(args, "ini", None) if emu == "eden" else None
            path = Path(ini) if ini else DEFAULT_EDEN_INI
            msgs, code, changed = apply_eden_pads(path, sinks, force=force)
        messages.extend(msgs)
        rc = max(rc, code)
        changed_any = changed_any or changed
    return _emit_apply(
        rc=rc,
        emu=emu,
        ordered=sinks,
        messages=messages,
        changed=changed_any,
        mode=mode,
    )


def cmd_eden(args: argparse.Namespace) -> int:
    args.emu = "eden"
    return cmd_apply(args)


def cmd_list(args: argparse.Namespace) -> int:
    pads = list_joysticks(Path(args.sysfs))
    json.dump({"pads": pads}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if pads else 2


def cmd_wait(args: argparse.Namespace) -> int:
    pads = list_joysticks(Path(args.sysfs))
    if not pads:
        print("No joysticks.", file=sys.stderr)
        return 2
    print("Press a button on the pad to bind…", file=sys.stderr)
    pad = wait_button(pads, args.timeout)
    if pad is None:
        print("No button press.", file=sys.stderr)
        return 2
    json.dump(pad, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_wait_appear(args: argparse.Namespace) -> int:
    """Wait until a Sunshine/libvirtualhid pad shows up (after Moonlight connects)."""
    needle = (args.match or "Sunshine").strip()
    deadline = time.monotonic() + max(args.timeout, 0.0)
    last_names = ""
    while True:
        pads = list_joysticks(Path(args.sysfs))
        pad = match_pad(pads, needle)
        if pad is None and needle.lower() == "sunshine":
            pad = next((p for p in pads if p.get("sunshine") == "true"), None)
        if pad is not None:
            json.dump(pad, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        last_names = ", ".join(p["name"] for p in pads) or "(none)"
        if time.monotonic() >= deadline:
            print(f"No pad matched {needle!r} within {args.timeout:.0f}s. Connected: {last_names}", file=sys.stderr)
            return 2
        time.sleep(0.4)


def _pick_for_cemu(args: argparse.Namespace) -> dict[str, str] | None:
    pads = list_joysticks(Path(args.sysfs))
    if args.wait:
        print("Press a button on the pad to bind…", file=sys.stderr)
        return wait_button(pads, args.timeout)
    needle = (getattr(args, "match", None) or "").strip()
    if needle.lower() in ("", "sunshine", "auto"):
        pad = pick_live_sunshine_pad(pads)
        if pad is not None:
            return pad
        if needle.lower() == "sunshine":
            return next((p for p in pads if p.get("sunshine") == "true"), None)
        print("No live Sunshine pad.", file=sys.stderr)
        return None
    pad = match_pad(pads, needle)
    if pad is None:
        names = ", ".join(p["name"] for p in pads) or "(none)"
        print(f"No pad matched {needle!r}. Connected: {names}", file=sys.stderr)
    return pad


def cmd_sdl_mapping(args: argparse.Namespace) -> int:
    pads = list_joysticks(Path(args.sysfs))
    needle = (args.match or "Sunshine").strip()
    pad = None
    if needle.lower() in ("", "sunshine", "auto"):
        pad = pick_live_sunshine_pad(pads)
    else:
        pad = match_pad(pads, needle)
    if pad is None:
        pad = pick_live_sunshine_pad(pads)
    chunks: list[str] = []
    for i, name in enumerate(SINK_NAMES):
        live = next((s for s in list_sink_joysticks(Path(args.sysfs)) if s["name"] == name), None)
        sink = live or sink_template(name, SINK_PRODUCTS[i], i)
        chunks.append(sdl_mapping_line(sink["guid"], sink["name"]))
        chunks.append(sdl_mapping_line(sink["eden_guid"], sink["name"]))
    if pad is None:
        chunks.append(sdl_mapping_for_name(_THOR_SUNSHINE_NAME).rstrip("\n"))
    else:
        chunks.append(sdl_mapping_for_pad(pad).rstrip("\n"))
    sys.stdout.write("\n".join(chunks) + "\n")
    return 0


def cmd_cemu(args: argparse.Namespace) -> int:
    args.emu = "cemu"
    return cmd_apply(args)


def cmd_azahar(args: argparse.Namespace) -> int:
    args.emu = "azahar"
    return cmd_apply(args)


def _write_js(
    root: Path,
    js: str,
    *,
    name: str,
    vendor: str,
    product: str,
    version: str,
    bustype: str = "0003",
) -> None:
    device = root / js / "device" / "id"
    device.mkdir(parents=True)
    (root / js / "device" / "name").write_text(name)
    (device / "vendor").write_text(vendor)
    (device / "product").write_text(product)
    (device / "version").write_text(version)
    (device / "bustype").write_text(bustype)


def _self_test() -> int:
    import tempfile

    xml = """<?xml version="1.0" encoding="UTF-8"?>
<emulated_controller>
	<type>Wii U GamePad</type>
	<controller>
		<api>SDLController</api>
		<uuid>0_03009ffb091200000300000001000000</uuid>
		<display_name>libvirtualhid Mouse</display_name>
		<mappings>
			</mappings>
	</controller>
	<controller>
		<api>SDLController</api>
		<uuid>0_030079f6de280000ff11000001000000</uuid>
		<display_name>Microsoft X-Box 360 pad 0</display_name>
		<mappings>
			<entry>
				<mapping>1</mapping>
				<button>1</button>
			</entry>
			<entry>
				<mapping>2</mapping>
				<button>0</button>
			</entry>
		</mappings>
	</controller>
	<controller>
		<api>SDLController</api>
		<uuid>0_050007e45e0400008e02000014010000</uuid>
		<display_name>Sunshine (libvirtualhid) AYN20Thor</display_name>
		<mappings>
			<entry>
				<mapping>1</mapping>
				<button>1</button>
			</entry>
			<entry>
				<mapping>2</mapping>
				<button>0</button>
			</entry>
		</mappings>
	</controller>
</emulated_controller>
"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_js(
            root,
            "js0",
            name="ASRock LED Controller",
            vendor="26ce",
            product="01a2",
            version="0110",
        )
        _write_js(
            root,
            "js1",
            name="Sunshine (libvirtualhid) AYN_Thor",
            vendor="045e",
            product="028e",
            version="0114",
            bustype="0005",
        )
        _write_js(
            root,
            "js2",
            name="Sunshine (libvirtualhid) Odin2_Portal",
            vendor="045e",
            product="028e",
            version="0114",
            bustype="0005",
        )
        _write_js(
            root,
            "js5",
            name="Sunshine (libvirtualhid) SM-A546E",
            vendor="045e",
            product="028e",
            version="0114",
            bustype="0005",
        )
        pads = list_joysticks(root)
        assert [p["name"] for p in pads] == [
            "Sunshine (libvirtualhid) AYN_Thor",
            "Sunshine (libvirtualhid) Odin2_Portal",
            "Sunshine (libvirtualhid) SM-A546E",
        ], pads
        thor_pad = next(p for p in pads if "Thor" in p["name"])
        mapping = sdl_mapping_for_pad(thor_pad)
        assert "AYN_Thor" in mapping
        assert "EasySMX" not in mapping
        assert "leftshoulder:b6" in mapping
        assert "back:b10" in mapping
        assert "leftshoulder:b4" not in mapping
        assert "back:b6," not in mapping
        assert _EASYSMX_USB_GUID in mapping
        assert thor_pad["guid"] in mapping
        assert _X360_USB_VERSION_GUID in mapping
        fallback = sdl_mapping_for_name(_THOR_SUNSHINE_NAME)
        assert thor_pad["guid"] in fallback
        assert _EASYSMX_USB_GUID in fallback
        assert "EasySMX" not in fallback
        thor = match_pad(pads, "Thor")
        odin = match_pad(pads, "Odin")
        assert thor is not None and odin is not None
        auto = pick_live_sunshine_pad(pads)
        assert auto is not None
        assert auto["name"] == thor["name"]
        assert thor is not None and thor["index"] == "0", thor
        assert odin is not None and odin["index"] == "1", odin
        assert thor["guid"] != odin["guid"]
        assert thor["eden_guid"] == "030000005e0400008e02000014010000"
        assert odin["eden_guid"] == thor["eden_guid"]
        assert resolve_pads(pads, ["js1", "js2"]) == [thor, odin]
        assert resolve_pads(pads, ["Thor", "Odin"]) == [thor, odin]
        assert resolve_pads(pads, ["nope"]) is None
        patched = patch_cemu_xml(xml, cemu_uuid(thor), thor["name"])
        parsed = ET.fromstring(patched)
        assert parsed.findtext("type") == "Wii U GamePad"
        assert thor["cemu_uuid"] in patched
        assert "AYN_Thor" in patched
        assert "AYN20Thor" not in patched
        assert "libvirtualhid Mouse" not in patched
        assert _mapping_owner_uuids(parsed) == [thor["cemu_uuid"]]
        first = parsed.find("controller")
        assert first is not None
        assert first.findtext("uuid") == thor["cemu_uuid"]
        assert "AYN_Thor" in (first.findtext("display_name") or "")
        steam = next(
            c
            for c in parsed.findall("controller")
            if "X-Box 360 pad" in (c.findtext("display_name") or "")
        )
        assert steam.find("mappings") is not None
        assert steam.find("mappings").findall("entry") == []
        pairs = {
            (e.findtext("mapping"), e.findtext("button"))
            for e in first.find("mappings").findall("entry")
        }
        assert ("11", "11") in pairs
        assert ("7", "42") in pairs
        assert ("8", "43") in pairs
        assert ("25", "8") in pairs
        assert ("15", "7") in pairs
        moonlight = """<?xml version="1.0" encoding="UTF-8"?>
<emulated_controller>
	<type>Wii U GamePad</type>
	<controller>
		<api>SDLController</api>
		<uuid>0_old</uuid>
		<display_name>Sunshine (libvirtualhid) Odin2_Portal</display_name>
		<mappings>
			<entry><mapping>25</mapping><button>40</button></entry>
			<entry><mapping>7</mapping><button>42</button></entry>
			<entry><mapping>8</mapping><button>43</button></entry>
			<entry><mapping>15</mapping><button>14</button></entry>
		</mappings>
	</controller>
</emulated_controller>
"""
        fixed = ET.fromstring(patch_cemu_xml(moonlight, thor["cemu_uuid"], thor["name"]))
        fixed_pairs = {
            (e.findtext("mapping"), e.findtext("button"))
            for e in fixed.find("controller").find("mappings").findall("entry")
        }
        assert ("11", "11") in fixed_pairs
        assert ("25", "8") in fixed_pairs
        assert ("15", "7") in fixed_pairs
        assert ("15", "14") not in fixed_pairs
        p1_dir = Path(tmp) / "cemu-profiles"
        p1_dir.mkdir()
        (p1_dir / "SteamInput-P1.xml").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<emulated_controller>
	<type>Wii U GamePad</type>
	<controller>
		<api>SDLController</api>
		<uuid>0_steamvirtual</uuid>
		<display_name>Steam Virtual Gamepad</display_name>
		<mappings>
			<entry><mapping>7</mapping><button>42</button></entry>
			<entry><mapping>8</mapping><button>43</button></entry>
			<entry><mapping>11</mapping><button>99</button></entry>
			<entry><mapping>15</mapping><button>7</button></entry>
		</mappings>
	</controller>
</emulated_controller>
"""
        )
        from_p1 = ET.fromstring(
            patch_cemu_xml(
                moonlight,
                thor["cemu_uuid"],
                thor["name"],
                p1_dir / "controller0.xml",
            )
        )
        p1_first = from_p1.find("controller")
        p1_pairs = {
            (e.findtext("mapping"), e.findtext("button"))
            for e in p1_first.find("mappings").findall("entry")
        }
        assert p1_first.findtext("uuid") == thor["cemu_uuid"]
        assert "Steam Virtual" not in (p1_first.findtext("display_name") or "")
        assert ("11", "99") in p1_pairs
        assert ("11", "11") not in p1_pairs
        assert match_pad(pads, "nope") is None
        # Generic duplicate names must not silently pick the wrong client.
        _write_js(
            root,
            "js3",
            name="Sunshine (libvirtualhid) X-Box 360 Controller",
            vendor="045e",
            product="028e",
            version="0114",
            bustype="0005",
        )
        _write_js(
            root,
            "js4",
            name="Sunshine (libvirtualhid) X-Box 360 Controller",
            vendor="045e",
            product="028e",
            version="0114",
            bustype="0005",
        )
        dupes = [p for p in list_joysticks(root) if p["name"].endswith("Controller")]
        assert len(dupes) == 2
        # Identical client names (Thor + Thor wrap): first hit, not None.
        assert match_pad(dupes, "X-Box 360 Controller") is dupes[0]
        assert is_cemu_comm("Cemu_relwithdeb")
        assert is_cemu_comm("Cemu_relwithdebinfo")
        assert is_cemu_comm("cemu")
        assert not is_cemu_comm("sunshine-ds")
        assert is_azahar_comm("azahar")
        assert not is_azahar_comm("azahar-launcher")
        ini = (
            'profiles\\1\\button_a="button:1,engine:sdl,'
            "guid:03008d205e040000ea02000008040000,port:0\"\n"
            'profiles\\1\\button_b="button:0,engine:sdl,'
            "guid:03008d205e040000ea02000008040000,port:0\"\n"
        )
        az = patch_azahar_ini(ini, thor["guid"])
        assert f'guid:{thor["guid"]}' in az
        assert "03008d205e040000ea02000008040000" not in az
        assert 'profiles\\1\\button_a="button:0,' in az
        assert 'profiles\\1\\button_b="button:1,' in az
        assert 'profiles\\1\\button_x="button:3,' in az
        assert 'profiles\\1\\button_y="button:4,' in az
        assert 'profiles\\1\\button_l="button:6,' in az
        assert 'profiles\\1\\button_r="button:7,' in az
        assert 'profiles\\1\\button_select="button:10,' in az
        assert 'profiles\\1\\button_start="button:11,' in az
        assert "axis:2,direction:+" in az
        ds = patch_azahar_ini(ini, thor["guid"], "ds5")
        assert 'profiles\\1\\button_l="button:4,' in ds
        assert 'profiles\\1\\button_select="button:6,' in ds
        two = patch_azahar_ini(ini, thor["guid"], slot=1)
        two = patch_azahar_ini(two, odin["guid"], slot=2)
        assert azahar_guid_for_slot(two, 1) == thor["guid"]
        assert azahar_guid_for_slot(two, 2) == odin["guid"]
        assert "profiles\\2\\name=Player 2" in two
        assert "profiles\\size=2" in two
        pro = patch_cemu_pro_xml(MINIMAL_CEMU_PRO_XML, cemu_uuid(odin), odin["name"])
        pro_root = ET.fromstring(pro)
        assert pro_root.findtext("type") == "Wii U Pro Controller"
        assert pro_root.find("controller").findtext("uuid") == odin["cemu_uuid"]
        eden_src = (
            'player_0_button_a="engine:sdl,port:0,guid:03000000de280000ff11000001000000,button:1"\n'
            'player_1_connected=false\n'
            'player_1_connected\\default=true\n'
            'player_1_button_a="engine:sdl,port:1,guid:03000000de280000ff11000001000000,button:1"\n'
        )
        eden = patch_eden_ini(eden_src, [thor, odin])
        assert f"guid:{thor['eden_guid']}" in eden
        assert eden_guid_for_player(eden, 0) == thor["eden_guid"]
        assert eden_guid_for_player(eden, 1) == odin["eden_guid"]
        assert "player_1_connected=true\n" in eden
        cemu_dir = Path(tmp) / "cemu-apply"
        cemu_dir.mkdir()
        xml_path = cemu_dir / "controller0.xml"
        xml_path.write_text(xml)
        msgs, code, changed = apply_cemu_pads([xml_path], [thor, odin], force=True)
        assert code == 0
        assert changed
        assert (cemu_dir / "controller1.xml").is_file()
        assert "Wii U Pro Controller" in (cemu_dir / "controller1.xml").read_text()
        _write_js(
            root,
            "js8",
            name="EmuPads P1",
            vendor="1209",
            product="e301",
            version="0114",
        )
        _write_js(
            root,
            "js9",
            name="EmuPads P2",
            vendor="1209",
            product="e302",
            version="0114",
        )
        _write_js(
            root,
            "js6",
            name="libvirtualhid Mouse",
            vendor="1209",
            product="0003",
            version="0114",
        )
        listed = list_joysticks(root)
        assert all(not p["name"].startswith("EmuPads") for p in listed), listed
        assert all(p["product"] != "0003" for p in listed)
        sinks = list_sink_joysticks(root)
        assert [s["name"] for s in sinks] == ["EmuPads P1", "EmuPads P2"]
        assert sinks[0]["product"] == "e301"
        assert sinks[1]["product"] == "e302"
        assert sinks[0]["eden_guid"] != sinks[1]["eden_guid"]
        sink_xml = Path(tmp) / "sink-controller0.xml"
        sink_xml.write_text(xml)
        s_msgs, s_code, s_changed = apply_cemu_pads([sink_xml], bind_sinks_for_mode("shared", root), force=True)
        assert s_code == 0 and s_changed
        assert "EmuPads P1" in sink_xml.read_text()
        mux_cfg = Path(tmp) / "mux.json"
        os.environ["EMUPADS_MUX_CONFIG"] = str(mux_cfg)
        write_mux_routing("shared", [])
        assert json.loads(mux_cfg.read_text())["mode"] == "shared"
        os.environ.pop("EMUPADS_MUX_CONFIG", None)
        from pad_profile import main as pad_profile_main

        assert pad_profile_main(["self-test"]) == 0
    print("bind-gamepad self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sysfs", default=str(INPUT_ROOT), help="Joystick sysfs root")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="Print joysticks as JSON")
    p_list.set_defaults(func=cmd_list)

    p_status = sub.add_parser("status", help="Print pads plus current Cemu/Azahar/Eden binds")
    p_status.add_argument("--xml", default=None, help="Cemu controller0.xml (default: standalone + RetroDECK)")
    p_status.add_argument("--azahar-ini", dest="azahar_ini", default=None)
    p_status.add_argument("--eden-ini", dest="eden_ini", default=None)
    p_status.set_defaults(func=cmd_status)

    p_apply = sub.add_parser("apply", help="Route mux sources and bind Cemu/Azahar/Eden to EmuPads P1/P2")
    p_apply.add_argument("--emu", default="all", help="cemu, azahar, eden, or all")
    p_apply.add_argument("--pads", help="Comma-separated jsN / GUID / name (player 1, player 2)")
    p_apply.add_argument("--match", help="Comma-separated name substrings (Thor,Odin)")
    p_apply.add_argument("--wait", action="store_true", help="Select the pad that receives a button")
    p_apply.add_argument("--all-sources", dest="all_sources", action="store_true", help="Mux every host pad")
    p_apply.add_argument("--mode", default="", help="shared (last-active P1) or multi (P1+P2)")
    p_apply.add_argument("--timeout", type=float, default=20.0)
    p_apply.add_argument("--xml", default=None, help="Cemu controller0.xml only (skip other trees)")
    p_apply.add_argument("--ini", default=None, help="Azahar or Eden qt-config.ini when --emu is one of those")
    p_apply.add_argument("--force", action="store_true", help="Do not warn if the emu is running")
    p_apply.set_defaults(func=cmd_apply)

    p_wait = sub.add_parser("wait", help="Print the pad that receives the next button")
    p_wait.add_argument("--timeout", type=float, default=20.0)
    p_wait.set_defaults(func=cmd_wait)

    p_appear = sub.add_parser("wait-appear", help="Wait until a Sunshine pad is connected")
    p_appear.add_argument("--match", default="Sunshine", help="Name substring (default Sunshine)")
    p_appear.add_argument("--timeout", type=float, default=45.0)
    p_appear.set_defaults(func=cmd_wait_appear)

    p_map = sub.add_parser(
        "sdl-mapping",
        help="Print SDL_GAMECONTROLLERCONFIG so Cemu does not label x360 as EasySMX",
    )
    p_map.add_argument("--match", default="Sunshine", help="Substring (default live Sunshine)")
    p_map.set_defaults(func=cmd_sdl_mapping)

    p_cemu = sub.add_parser("cemu", help="Bind Cemu to EmuPads P1 (and P2 in multi)")
    p_cemu.add_argument("--match", help="Substring of the device name (Thor, Odin, Sunshine)")
    p_cemu.add_argument("--pads", help="Comma-separated jsN / GUID / name")
    p_cemu.add_argument("--wait", action="store_true", help="Select the pad that receives a button")
    p_cemu.add_argument("--all-sources", dest="all_sources", action="store_true")
    p_cemu.add_argument("--mode", default="")
    p_cemu.add_argument("--timeout", type=float, default=20.0)
    p_cemu.add_argument("--xml", default=str(DEFAULT_CEMU_XML))
    p_cemu.add_argument("--force", action="store_true", help="Do not warn if Cemu is running")
    p_cemu.set_defaults(func=cmd_cemu)

    p_azahar = sub.add_parser("azahar", help="Bind Azahar to EmuPads P1 (and P2 in multi)")
    p_azahar.add_argument("--match", help="Substring of the device name (Thor, Odin, Sunshine)")
    p_azahar.add_argument("--pads", help="Comma-separated jsN / GUID / name")
    p_azahar.add_argument("--wait", action="store_true", help="Select the pad that receives a button")
    p_azahar.add_argument("--all-sources", dest="all_sources", action="store_true")
    p_azahar.add_argument("--mode", default="")
    p_azahar.add_argument("--timeout", type=float, default=20.0)
    p_azahar.add_argument("--ini", default=str(DEFAULT_AZAHAR_INI))
    p_azahar.add_argument("--force", action="store_true", help="Do not warn if Azahar is running")
    p_azahar.set_defaults(func=cmd_azahar)

    p_eden = sub.add_parser("eden", help="Bind Eden to EmuPads P1 (and P2 in multi)")
    p_eden.add_argument("--match", help="Substring or comma-separated names (Thor,Odin)")
    p_eden.add_argument("--pads", help="Comma-separated jsN / GUID")
    p_eden.add_argument("--wait", action="store_true", help="Select the pad that receives a button")
    p_eden.add_argument("--all-sources", dest="all_sources", action="store_true")
    p_eden.add_argument("--mode", default="")
    p_eden.add_argument("--timeout", type=float, default=20.0)
    p_eden.add_argument("--ini", default=str(DEFAULT_EDEN_INI))
    p_eden.add_argument("--force", action="store_true", help="Do not warn if Eden is running")
    p_eden.set_defaults(func=cmd_eden)

    p_profile = sub.add_parser("profile", help="Print the active GAMESTREAM_PAD_PROFILE")
    p_profile.set_defaults(func=lambda _args: __import__("pad_profile").main(["json"]))

    p_test = sub.add_parser("self-test", help="Run offline GUID/XML checks")
    p_test.set_defaults(func=lambda _args: _self_test())

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
