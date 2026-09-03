#!/usr/bin/env python3
"""Bind RPCS3 player 1 to whichever real pad is plugged in at launch.

Same pick as Eden/Cemu: physical Xbox (not Sunshine), Switch Pro, Steam
virtual (28de:11ff), then Sunshine. RetroDECK's default Device is
``Steam Deck Controller 1`` — this box is not a Deck, so Uncharted
reports "Sixaxis controller not connected".

RetroDECK RPCS3 is SDL3. With ALLOW_STEAM_VIRTUAL_GAMEPAD=1 it lists the
Steam-wrapped pad as ``Xbox One S Controller`` (GUID still 28de:11ff,
VID/PID reported as 045e:02ea). Binding ``Steam Virtual Gamepad 1``
creates an empty device and Uncharted still says no Sixaxis.

RPCS3 SDL devices are ``{SDL gamepad name} {1-based duplicate}``. Match
by /dev/input/event path or Steam-virtual GUID, not by VID/PID. If SDL
cannot be queried, fall back to the SDL3 name for the picked VID/PID.
If no pad is present, leave Device as-is.
"""
from __future__ import annotations

from pathlib import Path
import ctypes
import os
import re
import sys

INPUT_ROOT = Path("/sys/class/input")
SKIP_VENDORS = {"0000", "001f", "26ce", "046d", "beef"}
STEAM_VIRTUAL = ("28de", "11ff")

SDL_INIT_JOYSTICK = 0x00000200
SDL_INIT_GAMECONTROLLER = 0x00002000

SDL3_CANDIDATES = (
    os.environ.get("RPCS3_SDL3_LIB", ""),
    "/app/retrodeck/components/rpcs3/lib/libSDL3.so.0",
    "/var/lib/flatpak/app/net.retrodeck.retrodeck/current/active/files/retrodeck/components/rpcs3/lib/libSDL3.so.0",
)


class SDL_GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_uint8 * 16)]


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _event_for_js(js: Path) -> str:
    try:
        parent = js.resolve().parent
    except OSError:
        return ""
    events = sorted(parent.glob("event*"))
    return events[0].name if events else ""


def list_joysticks(root: Path = INPUT_ROOT) -> list[dict[str, str]]:
    pads = []
    for js in sorted(root.glob("js*")):
        device = js / "device"
        vendor = _read(device / "id" / "vendor").lower().zfill(4)[-4:]
        product = _read(device / "id" / "product").lower().zfill(4)[-4:]
        name = _read(device / "name")
        if not vendor or vendor in SKIP_VENDORS:
            continue
        pads.append(
            {
                "vendor": vendor,
                "product": product,
                "name": name,
                "event": _event_for_js(js),
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
        if (pad["vendor"], pad["product"]) == STEAM_VIRTUAL:
            return pad
    for pad in pads:
        if _is_sunshine(pad):
            return pad
    return pads[0]


def _prepare_sdl_env() -> None:
    os.environ["SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD"] = "1"
    os.environ["SDL_JOYSTICK_ALLOW_STEAM_VIRTUAL_GAMEPAD"] = "1"
    os.environ["SDL_JOYSTICK_HIDAPI"] = "0"
    os.environ["SDL_HIDAPI_JOYSTICK"] = "0"
    os.environ.pop("SDL_GAMECONTROLLER_IGNORE_DEVICES", None)
    os.environ.pop("SDL_GAMEPAD_IGNORE_DEVICES", None)
    os.environ["SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT"] = (
        "0x28de/0x11ff,0x045e/0x02ea,0x045e/0x028e,0x045e/0x02fd,0x057e/0x2009"
    )


def _load_sdl() -> tuple[ctypes.CDLL | None, int]:
    for path in SDL3_CANDIDATES:
        if path and os.path.isfile(path):
            try:
                return ctypes.CDLL(path), 3
            except OSError:
                continue
    for lib in ("libSDL3.so.0", "libSDL3.so"):
        try:
            return ctypes.CDLL(lib), 3
        except OSError:
            continue
    for lib in ("libSDL2-2.0.so.0", "libSDL2-2.0.so"):
        try:
            return ctypes.CDLL(lib), 2
        except OSError:
            continue
    return None, 0


def _guid_hex(guid: SDL_GUID) -> str:
    return bytes(guid.data).hex()


def _guid_is_steam_virtual(guid: str) -> bool:
    g = guid.lower()
    return "de28" in g and "ff11" in g


def _enumerate_sdl3(sdl: ctypes.CDLL) -> list[dict[str, object]]:
    sdl.SDL_GetJoysticks.argtypes = [ctypes.POINTER(ctypes.c_int)]
    sdl.SDL_GetJoysticks.restype = ctypes.POINTER(ctypes.c_uint32)
    sdl.SDL_IsGamepad.argtypes = [ctypes.c_uint32]
    sdl.SDL_IsGamepad.restype = ctypes.c_bool
    sdl.SDL_GetGamepadNameForID.argtypes = [ctypes.c_uint32]
    sdl.SDL_GetGamepadNameForID.restype = ctypes.c_char_p
    sdl.SDL_GetJoystickNameForID.argtypes = [ctypes.c_uint32]
    sdl.SDL_GetJoystickNameForID.restype = ctypes.c_char_p
    sdl.SDL_GetJoystickPathForID.argtypes = [ctypes.c_uint32]
    sdl.SDL_GetJoystickPathForID.restype = ctypes.c_char_p
    sdl.SDL_GetJoystickVendorForID.argtypes = [ctypes.c_uint32]
    sdl.SDL_GetJoystickVendorForID.restype = ctypes.c_uint16
    sdl.SDL_GetJoystickProductForID.argtypes = [ctypes.c_uint32]
    sdl.SDL_GetJoystickProductForID.restype = ctypes.c_uint16
    sdl.SDL_GetJoystickGUIDForID.argtypes = [ctypes.c_uint32]
    sdl.SDL_GetJoystickGUIDForID.restype = SDL_GUID
    sdl.SDL_free.argtypes = [ctypes.c_void_p]

    count = ctypes.c_int(0)
    ids = sdl.SDL_GetJoysticks(ctypes.byref(count))
    if not ids:
        return []
    try:
        seen: dict[str, int] = {}
        out: list[dict[str, object]] = []
        for i in range(int(count.value)):
            jid = ids[i]
            if not sdl.SDL_IsGamepad(jid):
                continue
            raw = sdl.SDL_GetGamepadNameForID(jid) or sdl.SDL_GetJoystickNameForID(jid)
            name = raw.decode("utf-8", "replace") if raw else f"Controller {i}"
            seen[name] = seen.get(name, 0) + 1
            path_raw = sdl.SDL_GetJoystickPathForID(jid)
            path = path_raw.decode("utf-8", "replace") if path_raw else ""
            out.append(
                {
                    "name": name,
                    "vendor": f"{int(sdl.SDL_GetJoystickVendorForID(jid)):04x}",
                    "product": f"{int(sdl.SDL_GetJoystickProductForID(jid)):04x}",
                    "path": path,
                    "guid": _guid_hex(sdl.SDL_GetJoystickGUIDForID(jid)),
                    "rpcs3_device": f"{name} {seen[name]}",
                }
            )
        return out
    finally:
        sdl.SDL_free(ids)


def _enumerate_sdl2(sdl: ctypes.CDLL) -> list[dict[str, object]]:
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
        out.append(
            {
                "name": name,
                "vendor": f"{int(sdl.SDL_JoystickGetDeviceVendor(i)):04x}",
                "product": f"{int(sdl.SDL_JoystickGetDeviceProduct(i)):04x}",
                "path": "",
                "guid": "",
                "rpcs3_device": f"{name} {seen[name]}",
            }
        )
    return out


def list_sdl_controllers() -> list[dict[str, object]]:
    """Return SDL gamepads as {name, vendor, product, path, guid, rpcs3_device}."""
    _prepare_sdl_env()
    sdl, major = _load_sdl()
    if sdl is None:
        return []
    sdl.SDL_Init.argtypes = [ctypes.c_uint32]
    sdl.SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER)
    try:
        if major >= 3:
            return _enumerate_sdl3(sdl)
        return _enumerate_sdl2(sdl)
    finally:
        sdl.SDL_Quit()


def fallback_device(pad: dict[str, str]) -> str:
    # RetroDECK RPCS3 is SDL3: Steam virtual shows up as Xbox One S, not
    # "Steam Virtual Gamepad". The SDL2 name becomes an empty Pad 0.
    if (pad["vendor"], pad["product"]) == STEAM_VIRTUAL:
        return "Xbox One S Controller 1"
    if pad["vendor"] == "045e":
        return "Xbox One S Controller 1"
    if pad["vendor"] == "057e":
        return "Nintendo Switch Pro Controller 1"
    return "Xbox 360 Controller 1"


def _path_matches_event(path: str, event: str) -> bool:
    if not path or not event:
        return False
    return path.endswith("/" + event) or path.rstrip("/").endswith(event)


def device_for_pad(
    pad: dict[str, str], controllers: list[dict[str, object]] | None = None
) -> str:
    if controllers is None:
        try:
            controllers = list_sdl_controllers()
        except (OSError, AttributeError):
            controllers = []
    event = pad.get("event", "")
    for ctl in controllers:
        if _path_matches_event(str(ctl.get("path") or ""), event):
            return str(ctl["rpcs3_device"])
    if (pad["vendor"], pad["product"]) == STEAM_VIRTUAL:
        for ctl in controllers:
            if _guid_is_steam_virtual(str(ctl.get("guid") or "")):
                return str(ctl["rpcs3_device"])
        for ctl in controllers:
            if str(ctl.get("name") or "").startswith("Xbox One S"):
                return str(ctl["rpcs3_device"])
    else:
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
            set_player1_device(sample, "Xbox One S Controller 1")
        )
        assert "Device: Xbox One S Controller 1\n" in out
        assert 'Handler: "Null"' in out
        assert 'Device: "Null"' in out
        assert "Steam Deck Controller 2" not in out
        assert fallback_device(
            {"vendor": "28de", "product": "11ff", "name": "x"}
        ) == "Xbox One S Controller 1"
        steam = {
            "vendor": "28de",
            "product": "11ff",
            "name": "x",
            "event": "event26",
        }
        assert (
            device_for_pad(
                steam,
                [
                    {
                        "name": "Xbox One S Controller",
                        "vendor": "045e",
                        "product": "02ea",
                        "path": "/dev/input/event26",
                        "guid": "030079f6de280000ff11000001000000",
                        "rpcs3_device": "Xbox One S Controller 1",
                    }
                ],
            )
            == "Xbox One S Controller 1"
        )
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
        # Steam Virtual Gamepad 1 is an empty SDL3 device. If no pad is
        # enumerated yet, still replace that (and the Deck default) so the
        # next launch can attach Xbox One S Controller 1 when Steam Input
        # appears.
        text = path.read_text()
        if re.search(
            r"(?m)^  Device: (Steam Virtual Gamepad 1|Steam Deck Controller 1)$",
            text,
        ):
            device = "Xbox One S Controller 1"
        else:
            print(f"No joystick yet; left RPCS3 player 1 as-is in {path}")
            return 0
    else:
        device = device_for_pad(pad)
    if not patch_file(path, device):
        print(f"RPCS3 player 1 already bound to {device} in {path}")
        return 0
    src = pad["name"] if pad is not None else "no joystick yet"
    print(f"Bound RPCS3 player 1 to {device} ({src}) in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
