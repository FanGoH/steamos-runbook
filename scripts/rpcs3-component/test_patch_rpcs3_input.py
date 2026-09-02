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
        == "Steam Virtual Gamepad 1"
    )
    assert (
        mod.fallback_device({"vendor": "045e", "product": "02ea", "name": "x"})
        == "Xbox One S Controller 1"
    )
    assert (
        mod.fallback_device({"vendor": "057e", "product": "2009", "name": "x"})
        == "Nintendo Switch Pro Controller 1"
    )


def test_device_for_pad_uses_sdl_name() -> None:
    pad = {"vendor": "28de", "product": "11ff", "name": "Microsoft X-Box 360 pad 0"}
    name = mod.device_for_pad(
        pad,
        [
            {
                "name": "Steam Virtual Gamepad",
                "vendor": "28de",
                "product": "11ff",
                "rpcs3_device": "Steam Virtual Gamepad 1",
            }
        ],
    )
    assert name == "Steam Virtual Gamepad 1"


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
        mod.set_player1_device(sample, "Steam Virtual Gamepad 1")
    )
    assert "  Device: Steam Virtual Gamepad 1\n" in out
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
    test_device_for_pad_uses_sdl_name()
    test_set_player1_keeps_emulated_vid_and_player2()
    print("ok")
