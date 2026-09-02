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
        "showStatusBar\\default=true\n"
        "showStatusBar=true\n"
        "use_asynchronous_shaders\\default=true\n"
        "use_asynchronous_shaders=false\n"
        "enable_joycon_driver=true\n"
    )
    out = mod.patch(src, None)
    assert "fullscreen_mode=0\n" in out
    assert "fullscreen_mode\\default=false\n" in out
    assert "fullscreen=true\n" in out
    assert "fullscreen\\default=false\n" in out
    assert "showStatusBar=false\n" in out
    assert "use_asynchronous_shaders=true\n" in out
    assert "enable_joycon_driver=false\n" in out


def test_pin_4gb_overrides_global() -> None:
    src = (
        "memory_layout_mode\\use_global=true\n"
        "memory_layout_mode\\default=true\n"
        "memory_layout_mode=2\n"
    )
    out = mod.pin_4gb_layout(src)
    assert "memory_layout_mode\\use_global=false\n" in out
    assert "memory_layout_mode\\default=false\n" in out
    assert "memory_layout_mode=0\n" in out


def test_ensure_fps_mods_copies_atmosphere_ips() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        game = home / "retrodeck/roms/switch/Luigi's Mansion 3"
        ips_dir = game / "exefs_patches/LM360FPS"
        ips_dir.mkdir(parents=True)
        (game / "Luigi’s Mansion 3[0100DCA0064A6000][US][v0].nsp").write_bytes(
            b"nsp"
        )
        (game / "Luigi’s Mansion 3[0100DCA0064A6800][US][v327680].nsp").write_bytes(
            b"upd"
        )
        ips = (
            ips_dir
            / "79E5950FFA85ACF63E28C9AEC051EAC27D6F7F8D000000000000000000000000.ips"
        )
        ips.write_bytes(b"IPS32stub")
        placed = mod.ensure_fps_mods(home)
        dest = (
            home
            / ".local/share/eden/load/0100DCA0064A6000/LM360FPS/exefs"
            / ips.name
        )
        assert dest.is_file()
        assert dest.read_bytes() == b"IPS32stub"
        assert any("LM360FPS" in p for p in placed)
        assert not (home / ".local/share/eden/load/0100DCA0064A6800").exists()
        assert mod.ensure_fps_mods(home) == []


def test_sdl_guid_stable() -> None:
    assert mod.sdl_guid("28de", "11ff", "0001") == (
        "03000000de280000ff11000001000000"
    )


if __name__ == "__main__":
    test_borderless_and_async()
    test_pin_4gb_overrides_global()
    test_sdl_guid_stable()
    test_ensure_fps_mods_copies_atmosphere_ips()
    print("ok")
