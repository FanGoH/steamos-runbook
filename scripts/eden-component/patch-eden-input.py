#!/usr/bin/env python3
"""Keep Eden player 0 on SDL port 0 and drop native Joy-Con HID.

Do not pin a GUID. Moonlight/Sunshine tears down Steam's virtual pad
(hid_read / "Destroyed virtual controller") and injects its own Xbox-like
device with a different GUID. Cemu can retarget; Eden with a stuck GUID
matches nothing. Port 0 without a GUID follows whichever pad SDL sees.
"""
from pathlib import Path
import re
import sys


def patch(text: str) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("enable_joycon_driver=") and "true" in line:
            line = "enable_joycon_driver=false\n"
        elif line.startswith("enable_joycon_driver\\default=") and "true" in line:
            line = "enable_joycon_driver\\default=false\n"
        elif line.startswith("player_0_") and "engine:sdl" in line:
            line = re.sub(r",guid:[0-9a-fA-F]+", "", line)
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
        print(f"Eden player 0 already has no GUID and joycon off in {path}")
        return 0
    bak = path.with_suffix(path.suffix + ".bak-steam-virtual")
    if not bak.exists():
        bak.write_text(text)
    path.write_text(new)
    print(f"Unbound Eden player 0 GUID (SDL port 0) in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
