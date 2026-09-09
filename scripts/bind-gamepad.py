#!/usr/bin/env python3
"""List host joysticks and bind Cemu/Azahar to a chosen pad.

Sunshine x360 pads used to share one name/GUID, so emulators could not target
Thor vs Odin. After sunshine-ds names pads ``Sunshine (libvirtualhid) <client>``,
match on Thor / Odin / the device name. ``wait`` binds whichever pad receives
a button press.

Cemu uuid is ``{guid-index}_{guid}`` (SDL2 CRC-16 of the kernel name). Player 0
is the Wii U GamePad. Each GamePad button maps to **one** physical controller;
later ``<controller>`` blocks overwrite earlier mappings. This script adds the
chosen pad and puts the mappings on it (Steam wrap can stay listed with empty
``<mappings>``). Cemu must restart to pick up a uuid/mapping change.

Azahar stores SDL joystick GUIDs in ``qt-config.ini``. Write the GameStream
libvirtualhid xbox_360 map (15 SDL buttons: L/R=6/7, Select/Start=10/11).
Steam xpad 11-button numbering puts Thor shoulders on Start/Select. Restart
Azahar after a GUID or button-map change.

Examples:
  python3 scripts/bind-gamepad.py list
  python3 scripts/bind-gamepad.py wait
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
import struct
import sys
import time
import xml.etree.ElementTree as ET

INPUT_ROOT = Path("/sys/class/input")
SKIP_VENDORS = {"0000", "001f", "26ce", "046d", "beef", "1209"}
EV_KEY = 1
DEFAULT_CEMU_XML = Path.home() / ".var/app/info.cemu.Cemu/config/Cemu/controllerProfiles/controller0.xml"
DEFAULT_AZAHAR_INI = (
    Path.home() / ".var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini"
)

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
        pads.append(pad)
        index += 1
    return pads


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
        return None
    return None


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


def patch_cemu_xml(text: str, uuid: str, display_name: str) -> str:
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

    for controller in root.findall("controller"):
        if controller is target:
            _set_mappings(controller, richest)
        else:
            _set_mappings(controller, [])

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


def azahar_guids(text: str) -> list[str]:
    return re.findall(r"guid:([0-9a-f]{32})", text)


# libvirtualhid xbox_360 enables reserved BTN_C/Z/TL2/TR2 so SDL joystick
# packing is 15 buttons, not Steam's 11-button xpad layout:
# 0A 1B 2C 3X 4Y 5Z 6LB 7RB 8TL2 9TR2 10Back 11Start 12Guide 13LS 14RS
# Mapping L/R to 4/5 and Select/Start to 6/7 makes Thor shoulders fire
# Start/Select. ZL/ZR stay analog LT/RT (axes 2/5). Face labels are Xbox.
_AZAHAR_X360 = {
    "button_a": "button:0,engine:sdl,guid:{guid},port:0",
    "button_b": "button:1,engine:sdl,guid:{guid},port:0",
    "button_x": "button:3,engine:sdl,guid:{guid},port:0",
    "button_y": "button:4,engine:sdl,guid:{guid},port:0",
    "button_l": "button:6,engine:sdl,guid:{guid},port:0",
    "button_r": "button:7,engine:sdl,guid:{guid},port:0",
    "button_zl": "axis:2,direction:+,engine:sdl,guid:{guid},port:0,threshold:0.5",
    "button_zr": "axis:5,direction:+,engine:sdl,guid:{guid},port:0,threshold:0.5",
    "button_select": "button:10,engine:sdl,guid:{guid},port:0",
    "button_start": "button:11,engine:sdl,guid:{guid},port:0",
    "button_home": "button:12,engine:sdl,guid:{guid},port:0",
    "button_up": "direction:up,engine:sdl,guid:{guid},hat:0,port:0",
    "button_down": "direction:down,engine:sdl,guid:{guid},hat:0,port:0",
    "button_left": "direction:left,engine:sdl,guid:{guid},hat:0,port:0",
    "button_right": "direction:right,engine:sdl,guid:{guid},hat:0,port:0",
    "circle_pad": "axis_x:0,axis_y:1,deadzone:0.100000,engine:sdl,guid:{guid},port:0",
    "c_stick": "axis_x:3,axis_y:4,deadzone:0.100000,engine:sdl,guid:{guid},port:0",
}


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


def patch_azahar_ini(text: str, guid: str) -> str:
    """Bind the Default profile to ``guid`` with the GameStream x360 map."""
    if not re.fullmatch(r"[0-9a-f]{32}", guid):
        raise ValueError(f"bad SDL GUID {guid!r}")
    for name, tmpl in _AZAHAR_X360.items():
        key = "profiles\\1\\" + name
        text = _set_ini_line(text, key, '"' + tmpl.format(guid=guid) + '"')
    return text


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


def _pick_for_cemu(args: argparse.Namespace) -> dict[str, str] | None:
    pads = list_joysticks(Path(args.sysfs))
    if args.wait:
        print("Press a button on the pad to bind…", file=sys.stderr)
        return wait_button(pads, args.timeout)
    if args.match:
        pad = match_pad(pads, args.match)
        if pad is None:
            names = ", ".join(p["name"] for p in pads) or "(none)"
            print(f"No pad matched {args.match!r}. Connected: {names}", file=sys.stderr)
        return pad
    print("Pass --match NAME or --wait.", file=sys.stderr)
    return None


def cmd_cemu(args: argparse.Namespace) -> int:
    path = Path(args.xml)
    if not path.is_file():
        print(f"Missing {path}", file=sys.stderr)
        return 1
    pad = _pick_for_cemu(args)
    if pad is None:
        return 2
    uuid = cemu_uuid(pad)
    text = path.read_text()
    try:
        owners = _mapping_owner_uuids(ET.fromstring(text))
    except ET.ParseError:
        owners = []
    new = patch_cemu_xml(text, uuid, pad["name"])
    if owners == [uuid]:
        print(f"Cemu player 0 already bound to {uuid} ({pad['name']})")
        return 0
    bak = path.with_suffix(path.suffix + ".bak-bind-gamepad")
    if not bak.exists():
        bak.write_text(text)
    path.write_text(new)
    print(f"Bound Cemu player 0 to {uuid} ({pad['name']}) in {path}")
    if cemu_running() and not args.force:
        print("Cemu is running; restart it for the bind to apply.", file=sys.stderr)
        return 2
    return 0


def cmd_azahar(args: argparse.Namespace) -> int:
    path = Path(args.ini)
    if not path.is_file():
        print(f"Missing {path}", file=sys.stderr)
        return 1
    pad = _pick_for_cemu(args)
    text = path.read_text()
    if pad is None:
        existing = azahar_guids(text)
        if not existing:
            return 2
        guid = existing[0]
        name = "existing qt-config.ini guid"
        print(f"No live pad matched; rewriting libvirtualhid map on {guid}", file=sys.stderr)
    else:
        guid = pad["guid"]
        name = pad["name"]
    try:
        new = patch_azahar_ini(text, guid)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if new == text:
        print(f"Azahar already bound to {guid} ({name}) with libvirtualhid x360 map")
        return 0
    bak = path.with_suffix(path.suffix + ".bak-bind-gamepad")
    if not bak.exists():
        bak.write_text(text)
    path.write_text(new)
    print(f"Bound Azahar to {guid} ({name}) in {path}")
    if azahar_running() and not args.force:
        print("Azahar is running; restart it for the bind to apply.", file=sys.stderr)
        return 2
    return 0


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
        pads = list_joysticks(root)
        assert [p["name"] for p in pads] == [
            "Sunshine (libvirtualhid) AYN_Thor",
            "Sunshine (libvirtualhid) Odin2_Portal",
        ], pads
        thor = match_pad(pads, "Thor")
        odin = match_pad(pads, "Odin")
        assert thor is not None and thor["index"] == "0", thor
        assert odin is not None and odin["index"] == "1", odin
        assert thor["guid"] != odin["guid"]
        patched = patch_cemu_xml(xml, cemu_uuid(thor), thor["name"])
        parsed = ET.fromstring(patched)
        assert parsed.findtext("type") == "Wii U GamePad"
        assert thor["cemu_uuid"] in patched
        assert "AYN_Thor" in patched
        assert "AYN20Thor" not in patched
        assert _mapping_owner_uuids(parsed) == [thor["cemu_uuid"]]
        steam = next(
            c
            for c in parsed.findall("controller")
            if "X-Box 360 pad" in (c.findtext("display_name") or "")
        )
        assert steam.find("mappings") is not None
        assert steam.find("mappings").findall("entry") == []
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
        assert match_pad(dupes, "X-Box 360 Controller") is None
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
    print("bind-gamepad self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sysfs", default=str(INPUT_ROOT), help="Joystick sysfs root")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="Print joysticks as JSON")
    p_list.set_defaults(func=cmd_list)

    p_wait = sub.add_parser("wait", help="Print the pad that receives the next button")
    p_wait.add_argument("--timeout", type=float, default=20.0)
    p_wait.set_defaults(func=cmd_wait)

    p_cemu = sub.add_parser("cemu", help="Bind Cemu player 0 in controller0.xml")
    p_cemu.add_argument("--match", help="Substring of the device name (Thor, Odin, Sunshine)")
    p_cemu.add_argument("--wait", action="store_true", help="Bind the pad that receives a button")
    p_cemu.add_argument("--timeout", type=float, default=20.0)
    p_cemu.add_argument("--xml", default=str(DEFAULT_CEMU_XML))
    p_cemu.add_argument("--force", action="store_true", help="Do not warn if Cemu is running")
    p_cemu.set_defaults(func=cmd_cemu)

    p_azahar = sub.add_parser("azahar", help="Bind Azahar SDL mappings in qt-config.ini")
    p_azahar.add_argument("--match", help="Substring of the device name (Thor, Odin, Sunshine)")
    p_azahar.add_argument("--wait", action="store_true", help="Bind the pad that receives a button")
    p_azahar.add_argument("--timeout", type=float, default=20.0)
    p_azahar.add_argument("--ini", default=str(DEFAULT_AZAHAR_INI))
    p_azahar.add_argument("--force", action="store_true", help="Do not warn if Azahar is running")
    p_azahar.set_defaults(func=cmd_azahar)

    p_test = sub.add_parser("self-test", help="Run offline GUID/XML checks")
    p_test.set_defaults(func=lambda _args: _self_test())

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
