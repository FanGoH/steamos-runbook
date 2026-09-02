#!/usr/bin/env python3
"""Persist Eden player 0 on the Xbox One / Sunshine pad and drop Joy-Con HID.

The working device in Game Mode + Moonlight is SDL GUID
030000005e040000ea02000008040000 (045e:02ea — Xbox One S and Sunshine's
"X-Box One (virtual) pad"). Do not strip that GUID on launch; Eden then
falls back to SDL port 0 (ASRock LED or Steam's wrapper) and the UI
device has to be re-picked every boot.
"""
from pathlib import Path
import re
import sys

# Eden's SDL GUID for 045e:02ea (no name-CRC). Matches what the UI writes
# when player 0 is set to Xbox One.
XBOX_GUID = "030000005e040000ea02000008040000"


def patch(text: str) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("enable_joycon_driver=") and "true" in line:
            line = "enable_joycon_driver=false\n"
        elif line.startswith("enable_joycon_driver\\default=") and "true" in line:
            line = "enable_joycon_driver\\default=false\n"
        elif line.startswith("player_0_") and "engine:sdl" in line:
            line = re.sub(r",guid:[0-9a-fA-F]+", "", line)
            if f"guid:{XBOX_GUID}" not in line:
                line = line.replace(
                    "engine:sdl,port:0,",
                    f"engine:sdl,port:0,guid:{XBOX_GUID},",
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
        print(f"Eden player 0 already bound to Xbox One in {path}")
        return 0
    bak = path.with_suffix(path.suffix + ".bak-steam-virtual")
    if not bak.exists():
        bak.write_text(text)
    path.write_text(new)
    print(f"Bound Eden player 0 to Xbox One GUID in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
