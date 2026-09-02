#!/usr/bin/env python3
"""Point Eden player 0 at Steam Virtual Gamepad and drop native HID drivers.

Cemu/Azahar in this RetroDECK install bind SDL to
guid 030079f6de280000ff11000001000000 ("Steam Virtual Gamepad"). Overlay
keeps the physical Xbox; Eden's joycon HID driver must not steal it
(Steam then hits hid_read failure and destroys the virtual pad).
"""
from pathlib import Path
import re
import sys

STEAM_GUID = "030079f6de280000ff11000001000000"


def patch(text: str) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("enable_joycon_driver=") and "true" in line:
            line = "enable_joycon_driver=false\n"
        elif line.startswith("enable_joycon_driver\\default=") and "true" in line:
            line = "enable_joycon_driver\\default=false\n"
        elif line.startswith("player_0_") and "engine:sdl" in line:
            line = re.sub(r",guid:[0-9a-fA-F]+", "", line)
            if f"guid:{STEAM_GUID}" not in line:
                line = line.replace(
                    "engine:sdl,port:0,",
                    f"engine:sdl,port:0,guid:{STEAM_GUID},",
                )
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
    text = path.read_text()
    new = patch(text)
    if new == text:
        print(f"Eden input already uses Steam Virtual Gamepad in {path}")
        return 0
    bak = path.with_suffix(path.suffix + ".bak-steam-virtual")
    if not bak.exists():
        bak.write_text(text)
    path.write_text(new)
    print(f"Pointed Eden player 0 at Steam Virtual Gamepad in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
