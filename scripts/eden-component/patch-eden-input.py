#!/usr/bin/env python3
"""Bind Eden player 0 to whichever real pad is plugged in at launch.

Skip motherboard LED and gamescope mouse js nodes. Prefer a physical
Xbox (not Sunshine), then Switch Pro, then Steam's virtual pad (the
wrapped held controller), then Sunshine, then the first remaining
joystick. Sunshine is a fallback — it is injected even during local
play, and Steam hides that Xbox ID from SDL. SDL GUID is USB bus +
vendor/product/version with no name-CRC — the form Eden's UI writes
for Xbox One.

If nothing is present, leave the existing player-0 GUID (last session)
and only keep the Joy-Con HID driver off.
"""
from __future__ import annotations

from pathlib import Path
import re
import struct
import sys

INPUT_ROOT = Path("/sys/class/input")
SKIP_VENDORS = {"0000", "001f", "26ce", "046d", "beef"}


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def list_joysticks(root: Path = INPUT_ROOT) -> list[dict[str, str]]:
    pads = []
    for js in sorted(root.glob("js*/device")):
        vendor = _read(js / "id" / "vendor").lower().zfill(4)[-4:]
        product = _read(js / "id" / "product").lower().zfill(4)[-4:]
        version = _read(js / "id" / "version").lower().zfill(4)[-4:]
        name = _read(js / "name")
        if not vendor or vendor in SKIP_VENDORS:
            continue
        pads.append(
            {
                "vendor": vendor,
                "product": product,
                "version": version or "0000",
                "name": name,
            }
        )
    return pads


def _is_sunshine(pad: dict[str, str]) -> bool:
    return "sunshine" in pad["name"].lower()


def pick_pad(pads: list[dict[str, str]]) -> dict[str, str] | None:
    if not pads:
        return None
    for pad in pads:
        if pad["vendor"] == "045e" and not _is_sunshine(pad):
            return pad
    for pad in pads:
        if pad["vendor"] == "057e" and pad["product"] == "2009":
            return pad
    for pad in pads:
        if pad["vendor"] == "28de" and pad["product"] == "11ff":
            return pad
    for pad in pads:
        if _is_sunshine(pad):
            return pad
    return pads[0]


def sdl_guid(vendor: str, product: str, version: str = "0000") -> str:
    raw = struct.pack(
        "<HHHHHHHH",
        0x0003,
        0,
        int(vendor, 16),
        0,
        int(product, 16),
        0,
        int(version or "0", 16),
        0,
    )
    return raw.hex()


def guid_for_current_pad(root: Path = INPUT_ROOT) -> str | None:
    pad = pick_pad(list_joysticks(root))
    if pad is None:
        return None
    return sdl_guid(pad["vendor"], pad["product"], pad["version"])


def _set_kv(line: str, key: str, value: str) -> str:
    if line.startswith(f"{key}=") and not line.startswith(f"{key}\\"):
        return f"{key}={value}\n"
    if line.startswith(f"{key}\\default="):
        return f"{key}\\default=false\n"
    return line


def patch(text: str, guid: str | None) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("enable_joycon_driver=") and "true" in line:
            line = "enable_joycon_driver=false\n"
        elif line.startswith("enable_joycon_driver\\default=") and "true" in line:
            line = "enable_joycon_driver\\default=false\n"
        elif guid and line.startswith("player_0_") and "engine:sdl" in line:
            line = re.sub(r",guid:[0-9a-fA-F]+", "", line)
            if f"guid:{guid}" not in line:
                line = line.replace(
                    "engine:sdl,port:0,",
                    f"engine:sdl,port:0,guid:{guid},",
                )
        else:
            # Exclusive fullscreen on gamescope leaves Steam on Launching
            # while RSS climbs until earlyoom SIGTERMs Eden. Borderless
            # still fills the nested window. Async shaders let a frame
            # present before the pipeline cache is finished.
            line = _set_kv(line, "fullscreen_mode", "0")
            line = _set_kv(line, "use_asynchronous_shaders", "true")
        out.append(line)
    return "".join(out)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} /path/to/qt-config.ini", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"skip: no {path}")
        return 0
    guid = guid_for_current_pad()
    text = path.read_text()
    new = patch(text, guid)
    if new == text:
        if guid:
            print(f"Eden player 0 already bound to {guid} in {path}")
        else:
            print(f"No joystick yet; left Eden player 0 as-is in {path}")
        return 0
    bak = path.with_suffix(path.suffix + ".bak-steam-virtual")
    if not bak.exists():
        bak.write_text(text)
    path.write_text(new)
    print(f"Bound Eden player 0 to current pad {guid} in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
