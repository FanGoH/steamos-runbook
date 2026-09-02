#!/usr/bin/env python3
"""Sanity checks for patch-eden-input.py (no joysticks required)."""
from pathlib import Path
import importlib.util

spec = importlib.util.spec_from_file_location(
    "patch_eden_input",
    Path(__file__).with_name("patch-eden-input.py"),
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_borderless_and_async() -> None:
    src = (
        "fullscreen_mode\\default=true\n"
        "fullscreen_mode=1\n"
        "fullscreen\\default=true\n"
        "fullscreen=false\n"
        "use_asynchronous_shaders\\default=true\n"
        "use_asynchronous_shaders=false\n"
        "enable_joycon_driver=true\n"
    )
    out = mod.patch(src, None)
    assert "fullscreen_mode=0\n" in out
    assert "fullscreen_mode\\default=false\n" in out
    assert "fullscreen=true\n" in out
    assert "fullscreen\\default=false\n" in out
    assert "use_asynchronous_shaders=true\n" in out
    assert "enable_joycon_driver=false\n" in out


def test_sdl_guid_stable() -> None:
    assert mod.sdl_guid("28de", "11ff", "0001") == (
        "03000000de280000ff11000001000000"
    )


if __name__ == "__main__":
    test_borderless_and_async()
    test_sdl_guid_stable()
    print("ok")
