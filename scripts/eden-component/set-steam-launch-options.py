#!/usr/bin/env python3
"""Set Steam shortcut LaunchOptions by AppName in shortcuts.vdf.

Used when Tender/decky-romm-sync created a tile with an empty launch line
(Xenoblade, Luigi). Steam may rewrite the file while it is running; re-run
after a Steam restart if the tile is still empty.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def set_launch_options(data: bytes, app_name: str, new_lo: str) -> bytes:
    key = b"\x01AppName\x00" + app_name.encode("utf-8") + b"\x00"
    start = data.find(key)
    if start < 0:
        raise KeyError(app_name)
    nxt = data.find(b"\x01AppName\x00", start + len(key))
    end = nxt if nxt >= 0 else len(data)
    chunk = data[start:end]
    lo_key = b"\x01LaunchOptions\x00"
    k = chunk.find(lo_key)
    if k < 0:
        raise KeyError(f"LaunchOptions for {app_name}")
    val_start = k + len(lo_key)
    val_end = chunk.find(b"\x00", val_start)
    if val_end < 0:
        raise ValueError(f"unterminated LaunchOptions for {app_name}")
    new_chunk = chunk[:val_start] + new_lo.encode("utf-8") + chunk[val_end:]
    return data[:start] + new_chunk + data[end:]


def patch_file(path: Path, updates: dict[str, str]) -> None:
    data = path.read_bytes()
    orig = data
    for name, lo in updates.items():
        data = set_launch_options(data, name, lo)
    if data == orig:
        print(f"unchanged {path}")
        return
    bak = path.with_suffix(path.suffix + ".bak-eden-lo")
    if not bak.exists():
        shutil.copy2(path, bak)
    path.write_bytes(data)
    print(f"updated {path}")


SWITCH = Path("/home/deck/retrodeck/roms/switch")
RD = 'flatpak run net.retrodeck.retrodeck -e "%EMULATOR_RYUBING% %ROM%"'


def _rd(path: Path) -> str:
    return f'{RD} "{path}"'


def updates() -> dict[str, str]:
    luigi = next(
        SWITCH.joinpath("Luigi's Mansion 3").glob("*0100DCA0064A6000*.nsp")
    )
    kirby = SWITCH.joinpath(
        "Kirby's Return to Dream Land Deluxe",
        "Kirbys Return to Dream Land Deluxe [01006B601380E000][v0].nsp",
    )
    return {
        "Xenoblade Chronicles 3": _rd(
            SWITCH / "Xenoblade Chronicles 3" / "Xenoblade Chronicles 3.xci"
        ),
        "Luigi's Mansion 3": _rd(luigi),
        "Kirby's Return to Dream Land Deluxe": _rd(kirby),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} /path/to/shortcuts.vdf", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"skip: no {path}")
        return 0
    patch_file(path, updates())
    return 0


def _self_test() -> None:
    sample = (
        b"\x00shortcuts\x00\x000\x00\x01AppName\x00Xenoblade Chronicles 3\x00"
        b"\x01LaunchOptions\x00\x00\x08\x001\x00\x01AppName\x00Other\x00"
        b"\x01LaunchOptions\x00keep\x00\x08\x08"
    )
    out = set_launch_options(sample, "Xenoblade Chronicles 3", "flatpak run test")
    assert b"flatpak run test\x00" in out
    assert b"\x01LaunchOptions\x00keep\x00" in out


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        _self_test()
        print("ok")
        raise SystemExit(0)
    raise SystemExit(main())
