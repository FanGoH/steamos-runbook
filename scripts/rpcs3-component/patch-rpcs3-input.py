#!/usr/bin/env python3
"""Bind RPCS3 player 1 to whichever real pad is plugged in at launch.

Same pick as Eden/Cemu: physical Xbox (not Sunshine), Switch Pro, Steam
virtual (28de:11ff), then Sunshine. RetroDECK's default Device is
``Steam Deck Controller 1`` — this box is not a Deck, so Uncharted
reports "Sixaxis controller not connected".

RPCS3 SDL devices are ``{SDL_GameControllerName} {1-based duplicate}``.
If SDL cannot be queried, fall back to the usual names for the picked
VID/PID. If no pad is present, leave Device as-is.
"""
from __future__ import annotations

from pathlib import Path
import ctypes
import os
import re
import sys

INPUT_ROOT = Path("/sys/class/input")
SKIP_VENDORS = {"0000", "001f", "26ce", "046d", "beef"}

SDL_INIT_JOYSTICK = 0x00000200
SDL_INIT_GAMECONTROLLER = 0x00002000


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
        name = _read(js / "name")
        if not vendor or vendor in SKIP_VENDORS:
            continue
        pads.append({"vendor": vendor, "product": product, "name": name})
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


def _prepare_sdl_env() -> None:
    os.environ["SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD"] = "1"
    os.environ["SDL_JOYSTICK_HIDAPI"] = "0"
    os.environ["SDL_HIDAPI_JOYSTICK"] = "0"
    os.environ.pop("SDL_GAMECONTROLLER_IGNORE_DEVICES", None)
    os.environ["SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT"] = (
        "0x28de/0x11ff,0x045e/0x02ea,0x045e/0x028e,0x045e/0x02fd,0x057e/0x2009"
    )


def list_sdl_controllers() -> list[dict[str, object]]:
    """Return SDL gamecontrollers as {name, vendor, product, rpcs3_device}."""
    _prepare_sdl_env()
    sdl = None
    for lib in ("libSDL2-2.0.so.0", "libSDL2-2.0.so"):
        try:
            sdl = ctypes.CDLL(lib)
            break
        except OSError:
            continue
    if sdl is None:
        return []
    sdl.SDL_Init.argtypes = [ctypes.c_uint32]
    sdl.SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER)
    try:
        n = int(sdl.SDL_NumJoysticks())
        sdl.SDL_IsGameController.argtypes = [ctypes.c_int]
        sdl.SDL_IsGameController.restype = ctypes.c_int
        sdl.SDL_GameControllerNameForIndex.argtypes = [ctypes.c_int]
        sdl.SDL_GameControllerNameForIndex.restype = ctypes.c_char_p
        sdl.SDL_JoystickNameForIndex.argtypes = [ctypes.c_int]
        sdl.SDL_JoystickNameForIndex.restype = ctypes.c_char_p
        sdl.SDL_JoystickGetDeviceVendor.argtypes = [ctypes.c_int]
        sdl.SDL_JoystickGetDeviceVendor.restype = ctypes.c_uint16
        sdl.SDL_JoystickGetDeviceProduct.argtypes = [ctypes.c_int]
        sdl.SDL_JoystickGetDeviceProduct.restype = ctypes.c_uint16
        seen: dict[str, int] = {}
        out: list[dict[str, object]] = []
        for i in range(n):
            if not sdl.SDL_IsGameController(i):
                continue
            raw = sdl.SDL_GameControllerNameForIndex(i) or sdl.SDL_JoystickNameForIndex(i)
            name = raw.decode("utf-8", "replace") if raw else f"Controller {i}"
            seen[name] = seen.get(name, 0) + 1
            vendor = f"{int(sdl.SDL_JoystickGetDeviceVendor(i)):04x}"
            product = f"{int(sdl.SDL_JoystickGetDeviceProduct(i)):04x}"
            out.append(
                {
                    "name": name,
                    "vendor": vendor,
                    "product": product,
                    "rpcs3_device": f"{name} {seen[name]}",
                }
            )
        return out
    finally:
        sdl.SDL_Quit()


def fallback_device(pad: dict[str, str]) -> str:
    if pad["vendor"] == "28de" and pad["product"] == "11ff":
        return "Steam Virtual Gamepad 1"
    if pad["vendor"] == "045e":
        return "Xbox One S Controller 1"
    if pad["vendor"] == "057e":
        return "Nintendo Switch Pro Controller 1"
    return "Xbox 360 Controller 1"


def device_for_pad(
    pad: dict[str, str], controllers: list[dict[str, object]] | None = None
) -> str:
    if controllers is None:
        try:
            controllers = list_sdl_controllers()
        except (OSError, AttributeError):
            controllers = []
    for ctl in controllers:
        if ctl["vendor"] == pad["vendor"] and ctl["product"] == pad["product"]:
            return str(ctl["rpcs3_device"])
    return fallback_device(pad)


def set_player1_device(text: str, device: str) -> str:
    parts = text.split("Player 2 Input:", 1)
    head = parts[0]
    new_head, n = re.subn(
        r"(?m)^  Device:.*$",
        f"  Device: {device}",
        head,
        count=1,
    )
    if n == 0:
        new_head = head.replace(
            "Player 1 Input:\n",
            f"Player 1 Input:\n  Device: {device}\n",
            1,
        )
    if len(parts) == 1:
        return new_head
    return new_head + "Player 2 Input:" + parts[1]


def null_extra_players(text: str) -> str:
    """Drop fake Steam Deck pads on players 2–7 so Uncharted sees one Sixaxis."""

    def _null_block(match: re.Match[str]) -> str:
        block = match.group(0)
        if re.search(r"(?m)^  Handler:", block):
            block = re.sub(r"(?m)^  Handler:.*$", '  Handler: "Null"', block, count=1)
        else:
            block = re.sub(
                r"(?m)^(Player [2-7] Input:\n)",
                r'\1  Handler: "Null"\n',
                block,
                count=1,
            )
        block = re.sub(r"(?m)^  Device:.*$", '  Device: "Null"', block, count=1)
        return block

    return re.sub(
        r"(?ms)^Player [2-7] Input:.*?(?=^Player [2-7] Input:|\Z)",
        _null_block,
        text,
    )


def patch_file(path: Path, device: str) -> bool:
    text = path.read_text()
    new = null_extra_players(set_player1_device(text, device))
    if new == text:
        return False
    bak = path.with_suffix(path.suffix + ".bak-current-pad")
    if not bak.exists():
        bak.write_text(text)
    path.write_text(new)
    return True


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        sample = (
            "Player 1 Input:\n  Handler: SDL\n  Device: Steam Deck Controller 1\n"
            "Player 2 Input:\n  Handler: SDL\n  Device: Steam Deck Controller 2\n"
        )
        out = null_extra_players(
            set_player1_device(sample, "Steam Virtual Gamepad 1")
        )
        assert "Device: Steam Virtual Gamepad 1\n" in out
        assert 'Handler: "Null"' in out
        assert 'Device: "Null"' in out
        assert "Steam Deck Controller 2" not in out
        assert fallback_device(
            {"vendor": "28de", "product": "11ff", "name": "x"}
        ) == "Steam Virtual Gamepad 1"
        print("ok")
        return 0
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} /path/to/Default.yml", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"skip: no {path}")
        return 0
    pad = pick_pad(list_joysticks())
    if pad is None:
        print(f"No joystick yet; left RPCS3 player 1 as-is in {path}")
        return 0
    device = device_for_pad(pad)
    if not patch_file(path, device):
        print(f"RPCS3 player 1 already bound to {device} in {path}")
        return 0
    print(f"Bound RPCS3 player 1 to {device} ({pad['name']}) in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
