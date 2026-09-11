#!/usr/bin/env python3
"""Bind Cemu player 0 to EmuPads P1 (mux sink).

Host pads stay sources for ``emupads-mux``. Skip motherboard LED, the
libvirtualhid mouse, and every non-sink joystick. If P1 is missing, leave
controller0.xml as-is — do not fall back to Sunshine.

Cemu stores SDL2 GUIDs with a CRC-16 of the device name. uuid is
``{index}_{guid}``; with joystick blacklist-except sinks, player 0 is
index 0.
"""
from __future__ import annotations

from pathlib import Path
import re
import struct
import sys
import xml.sax.saxutils

INPUT_ROOT = Path("/sys/class/input")
SKIP_VENDORS = {"0000", "001f", "26ce", "046d", "beef"}
SKIP_PRODUCTS = {("1209", "0003")}

# SDL2 SDL_crc16 (CRC-16/IBM, poly 0x8005 reflected).
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


def list_joysticks(root: Path = INPUT_ROOT) -> list[dict[str, str]]:
    pads = []
    for js in sorted(root.glob("js*/device")):
        vendor = _read(js / "id" / "vendor").lower().zfill(4)[-4:]
        product = _read(js / "id" / "product").lower().zfill(4)[-4:]
        version = _read(js / "id" / "version").lower().zfill(4)[-4:]
        bustype = _read(js / "id" / "bustype").lower().zfill(4)[-4:]
        name = _read(js / "name")
        if not vendor or vendor in SKIP_VENDORS:
            continue
        if (vendor, product) in SKIP_PRODUCTS:
            continue
        pads.append(
            {
                "vendor": vendor,
                "product": product,
                "version": version or "0000",
                "bustype": bustype or "0003",
                "name": name,
            }
        )
    return pads


def _is_sunshine(pad: dict[str, str]) -> bool:
    return "sunshine" in pad["name"].lower()


def pick_pad(pads: list[dict[str, str]]) -> dict[str, str] | None:
    for pad in pads:
        if pad.get("name") == "EmuPads P1" or (
            pad.get("vendor") == "1209" and pad.get("product") == "e301"
        ):
            return pad
    return None


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
    return f"0_{sdl_guid(pad)}"


def current_pad(root: Path = INPUT_ROOT) -> dict[str, str] | None:
    return pick_pad(list_joysticks(root))


def patch(text: str, uuid: str, display_name: str) -> str:
    escaped = xml.sax.saxutils.escape(display_name)
    text, n_uuid = re.subn(
        r"(<uuid>)[^<]*(</uuid>)",
        rf"\g<1>{uuid}\g<2>",
        text,
        count=1,
    )
    text, n_name = re.subn(
        r"(<display_name>)[^<]*(</display_name>)",
        rf"\g<1>{escaped}\g<2>",
        text,
        count=1,
    )
    if n_uuid != 1 or n_name != 1:
        raise ValueError(
            f"controller xml missing uuid/display_name (uuid={n_uuid} name={n_name})"
        )
    return text


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["--self-test"]:
        return _self_test()
    if len(args) != 1:
        print(f"usage: {sys.argv[0]} /path/to/controller0.xml", file=sys.stderr)
        return 2
    path = Path(args[0])
    if not path.is_file():
        print(f"skip: no {path}")
        return 0
    pad = current_pad()
    if pad is None:
        print(f"No joystick yet; left Cemu player 0 as-is in {path}")
        return 0
    uuid = cemu_uuid(pad)
    text = path.read_text()
    new = patch(text, uuid, pad["name"])
    if new == text:
        print(f"Cemu player 0 already bound to {uuid} ({pad['name']}) in {path}")
        return 0
    bak = path.with_suffix(path.suffix + ".bak-current-pad")
    if not bak.exists():
        bak.write_text(text)
    path.write_text(new)
    print(f"Bound Cemu player 0 to {uuid} ({pad['name']}) in {path}")
    return 0


def _write_js(root: Path, js: str, *, name: str, vendor: str, product: str,
              version: str, bustype: str = "0003") -> None:
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
	<type>Wii U Pro Controller</type>
	<profile>moonlight</profile>
	<controller>
		<api>SDLController</api>
		<uuid>0_030079f6de280000ff11000001000000</uuid>
		<display_name>Steam Virtual Gamepad</display_name>
	</controller>
</emulated_controller>
"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_js(root, "js0", name="ASRock LED Controller", vendor="26ce",
                  product="01a2", version="0110")
        _write_js(root, "js1", name="Mouse passthrough (absolute)", vendor="beef",
                  product="dead", version="0111")
        _write_js(root, "js2", name="Sunshine X-Box One (virtual) pad",
                  vendor="045e", product="02ea", version="0408")
        _write_js(root, "js3", name="Microsoft X-Box 360 pad 0", vendor="28de",
                  product="11ff", version="0001")
        _write_js(root, "js4", name="EmuPads P1", vendor="1209",
                  product="e301", version="0114")
        _write_js(root, "js5", name="libvirtualhid Mouse", vendor="1209",
                  product="0003", version="0114")
        pad = pick_pad(list_joysticks(root))
        assert pad is not None and pad["name"] == "EmuPads P1", pad
        patched = patch(xml, cemu_uuid(pad), pad["name"])
        assert "EmuPads P1" in patched

        sunshine_only = Path(tmp) / "sunshine"
        _write_js(sunshine_only, "js0", name="ASRock LED Controller", vendor="26ce",
                  product="01a2", version="0110")
        _write_js(sunshine_only, "js1", name="Sunshine X-Box One (virtual) pad",
                  vendor="045e", product="02ea", version="0408")
        sun = pick_pad(list_joysticks(sunshine_only))
        assert sun is None, sun

        physical = Path(tmp) / "physical"
        _write_js(physical, "js0", name="Sunshine X-Box One (virtual) pad",
                  vendor="045e", product="02ea", version="0408")
        _write_js(physical, "js1", name="Xbox One S Controller", vendor="045e",
                  product="02ea", version="0408")
        _write_js(physical, "js2", name="EmuPads P1", vendor="1209",
                  product="e301", version="0114")
        real = pick_pad(list_joysticks(physical))
        assert real is not None and real["name"] == "EmuPads P1", real

        steam_only = Path(tmp) / "steam"
        _write_js(steam_only, "js0", name="ASRock LED Controller", vendor="26ce",
                  product="01a2", version="0110")
        _write_js(steam_only, "js1", name="Microsoft X-Box 360 pad 0",
                  vendor="28de", product="11ff", version="0001")
        steam = pick_pad(list_joysticks(steam_only))
        assert steam is None, steam

        xbox = {
            "name": "Xbox One S Controller",
            "vendor": "045e",
            "product": "02ea",
            "version": "0408",
            "bustype": "0003",
        }
        assert sdl_crc16(b"Xbox One S Controller") == 0x7982
        assert sdl_guid(xbox) != "03008d205e040000ea02000008040000"

    print("patch-cemu-input self-test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
