#!/usr/bin/env python3
"""Sanity checks for patch-rpcs3-input.py (no joysticks required)."""
from pathlib import Path
import importlib.util

spec = importlib.util.spec_from_file_location(
    "patch_rpcs3_input",
    Path(__file__).with_name("patch-rpcs3-input.py"),
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_pick_prefers_steam_virtual_over_sunshine() -> None:
    picked = mod.pick_pad(
        [
            {
                "vendor": "045e",
                "product": "02ea",
                "name": "Sunshine X-Box One (virtual) pad",
            },
            {
                "vendor": "28de",
                "product": "11ff",
                "name": "Microsoft X-Box 360 pad 0",
            },
        ]
    )
    assert picked is not None
    assert picked["vendor"] == "28de"
    assert picked["product"] == "11ff"


def test_pick_prefers_physical_xbox() -> None:
    picked = mod.pick_pad(
        [
            {
                "vendor": "045e",
                "product": "02ea",
                "name": "Sunshine X-Box One (virtual) pad",
            },
            {
                "vendor": "045e",
                "product": "0b13",
                "name": "Xbox Wireless Controller",
            },
            {
                "vendor": "28de",
                "product": "11ff",
                "name": "Microsoft X-Box 360 pad 0",
            },
        ]
    )
    assert picked is not None
    assert picked["product"] == "0b13"


def test_fallback_device_names() -> None:
    assert (
        mod.fallback_device(
            {"vendor": "28de", "product": "11ff", "name": "x"}
        )
        == "Xbox One S Controller 1"
    )
    assert (
        mod.fallback_device({"vendor": "045e", "product": "02ea", "name": "x"})
        == "Xbox One S Controller 1"
    )
    assert (
        mod.fallback_device({"vendor": "057e", "product": "2009", "name": "x"})
        == "Nintendo Switch Pro Controller 1"
    )


def test_device_for_pad_uses_event_path_not_vidpid() -> None:
    """SDL3 reports Steam virtual as 045e:02ea; match event26, not VID/PID."""
    pad = {
        "vendor": "28de",
        "product": "11ff",
        "name": "Microsoft X-Box 360 pad 0",
        "event": "event26",
    }
    name = mod.device_for_pad(
        pad,
        [
            {
                "name": "Xbox One S Controller",
                "vendor": "045e",
                "product": "02ea",
                "path": "/dev/input/event25",
                "guid": "030000005e040000ea02000000000000",
                "rpcs3_device": "Xbox One S Controller 1",
            },
            {
                "name": "Xbox One S Controller",
                "vendor": "045e",
                "product": "02ea",
                "path": "/dev/input/event26",
                "guid": "030079f6de280000ff11000001000000",
                "rpcs3_device": "Xbox One S Controller 2",
            },
        ],
    )
    assert name == "Xbox One S Controller 2"


def test_device_for_pad_uses_steam_virtual_guid() -> None:
    pad = {
        "vendor": "28de",
        "product": "11ff",
        "name": "Microsoft X-Box 360 pad 0",
        "event": "",
    }
    name = mod.device_for_pad(
        pad,
        [
            {
                "name": "Xbox One S Controller",
                "vendor": "045e",
                "product": "02ea",
                "path": "",
                "guid": "030079f6de280000ff11000001000000",
                "rpcs3_device": "Xbox One S Controller 1",
            }
        ],
    )
    assert name == "Xbox One S Controller 1"


def test_device_for_pad_sdl2_name_is_not_used_for_steam_virtual() -> None:
    pad = {"vendor": "28de", "product": "11ff", "name": "x", "event": "event25"}
    name = mod.device_for_pad(
        pad,
        [
            {
                "name": "Steam Virtual Gamepad",
                "vendor": "28de",
                "product": "11ff",
                "path": "/dev/input/event25",
                "guid": "030079f6de280000ff11000001000000",
                "rpcs3_device": "Steam Virtual Gamepad 1",
            }
        ],
    )
    # Path/GUID match the Steam-virtual node, but that SDL name is an empty
    # RPCS3 device. Bind the name RetroDECK RPCS3 actually lists.
    assert name == "Xbox One S Controller 1"


def test_guid_is_steam_virtual() -> None:
    assert mod._guid_is_steam_virtual("030079f6de280000ff11000001000000")
    assert not mod._guid_is_steam_virtual("030000005e040000ea02000000000000")
    assert not mod._guid_is_steam_virtual("")


def test_set_player1_keeps_emulated_vid_and_player2() -> None:
    sample = (
        "Player 1 Input:\n"
        "  Handler: SDL\n"
        "  Device: Steam Deck Controller 1\n"
        "  Vendor ID: 1356\n"
        "  Product ID: 616\n"
        "Player 2 Input:\n"
        "  Handler: SDL\n"
        "  Device: Steam Deck Controller 2\n"
        "  Vendor ID: 1356\n"
        "  Product ID: 616\n"
    )
    out = mod.null_extra_players(
        mod.set_player1_device(sample, "Xbox One S Controller 1")
    )
    assert "  Device: Xbox One S Controller 1\n" in out
    assert "Steam Deck Controller 1" not in out
    assert "Steam Deck Controller 2" not in out
    assert '  Handler: "Null"' in out
    assert '  Device: "Null"' in out
    assert "  Vendor ID: 1356\n" in out
    assert "  Product ID: 616\n" in out
    assert "  Handler: SDL\n" in out


if __name__ == "__main__":
    test_pick_prefers_steam_virtual_over_sunshine()
    test_pick_prefers_physical_xbox()
    test_fallback_device_names()
    test_device_for_pad_uses_event_path_not_vidpid()
    test_device_for_pad_uses_steam_virtual_guid()
    test_device_for_pad_sdl2_name_is_not_used_for_steam_virtual()
    test_guid_is_steam_virtual()
    test_set_player1_keeps_emulated_vid_and_player2()
    print("ok")
