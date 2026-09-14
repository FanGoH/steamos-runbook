#!/usr/bin/env python3
"""Tests for emu-quick-settings.py (temp HOME, no live emulator files)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile

spec = importlib.util.spec_from_file_location(
    "emu_quick_settings",
    Path(__file__).with_name("emu-quick-settings.py"),
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def _home() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_proc(root: Path, pid: str, comm: str, args: list[str]) -> None:
    proc = root / pid
    proc.mkdir(parents=True)
    (proc / "comm").write_text(comm + "\n", encoding="utf-8")
    (proc / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")


GLOBAL_EDEN = """[Core]
memory_layout_mode\\default=false
memory_layout_mode=2
use_speed_limit=true
speed_limit=100

[Renderer]
resolution_setup=3
use_vsync=2
scaling_filter=1
anti_aliasing=0
gpu_accuracy=0
fullscreen_mode=0
use_asynchronous_shaders=true

[System]
use_docked_mode=1
"""

ENGAGE = """[Core]
memory_layout_mode\\use_global=false
memory_layout_mode=0

[Renderer]
resolution_setup\\use_global=false
resolution_setup=6
"""


def test_ini_set_preserves_other_keys() -> None:
    out = mod.ini_set(GLOBAL_EDEN, "Renderer", "resolution_setup", value="4")
    assert "resolution_setup=4\n" in out
    assert "fullscreen_mode=0\n" in out
    assert "memory_layout_mode=2\n" in out


def test_per_game_override_and_effective() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        msgs = mod.set_eden(home, "game", "0100A6301214E000", "resolution_setup", "2")
        assert any("this game" in m for m in msgs)
        custom = (home / ".config/eden/custom/0100A6301214E000.ini").read_text()
        assert "resolution_setup=2" in custom
        assert "resolution_setup\\use_global=false" in custom
        packed = mod.read_eden(home, "0100A6301214E000")
        res = next(s for s in packed if s["key"] == "resolution_setup")
        assert res["value"] == "2"
        assert res["use_global"] is False
        docked = next(s for s in packed if s["key"] == "use_docked_mode")
        assert docked["use_global"] is True
        assert docked["display"] == "Docked"


def test_reset_game_keeps_engage_4gb() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        _write(home / ".config/eden/custom/0100A6301214E000.ini", ENGAGE)
        mod.reset_eden(home, "game", "0100A6301214E000")
        custom = (home / ".config/eden/custom/0100A6301214E000.ini").read_text()
        assert "memory_layout_mode=0" in custom
        assert "memory_layout_mode\\use_global=false" in custom
        assert "resolution_setup\\use_global=true" in custom
        packed = mod.read_eden(home, "0100A6301214E000")
        res = next(s for s in packed if s["key"] == "resolution_setup")
        assert res["use_global"] is True
        assert res["display"] == "1.5x"


def test_refuses_protected_keys() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        try:
            mod.set_eden(home, "global", "", "fullscreen_mode", "1")
        except (ValueError, KeyError):
            pass
        else:
            raise AssertionError("fullscreen_mode should be unknown/protected")
        assert "fullscreen_mode=0" in mod.eden_ini(home).read_text()


def test_global_reset_skips_memory_and_fullscreen() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        mod.reset_eden(home, "global", "")
        text = mod.eden_ini(home).read_text()
        assert "memory_layout_mode=2" in text
        assert "fullscreen_mode=0" in text
        assert "resolution_setup=2" in text


def test_azahar_does_not_touch_layout() -> None:
    with _home() as td:
        home = Path(td)
        ini = home / ".var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini"
        _write(
            ini,
            "[Renderer]\nlayout_option=4\nresolution_factor=3\nuse_vsync=true\n",
        )
        mod.set_azahar(home, "global", "", "resolution_factor", "2")
        text = ini.read_text()
        assert "layout_option=4" in text
        assert "resolution_factor=2" in text
        try:
            mod.setting_by_key("azahar", "layout_option")
        except KeyError:
            pass
        else:
            raise AssertionError("layout_option must not be a quick setting")


def test_azahar_per_game_resolution() -> None:
    with _home() as td:
        home = Path(td)
        ini = home / ".var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini"
        _write(ini, "[Renderer]\nresolution_factor=1\n")
        mod.set_azahar(home, "game", "0004000000054000", "resolution_factor", "4")
        custom = (ini.parent / "custom/0004000000054000.ini").read_text()
        assert "resolution_factor=4" in custom
        assert "resolution_factor\\use_global=false" in custom
        packed = mod.read_azahar(home, "0004000000054000")
        res = next(s for s in packed if s["key"] == "resolution_factor")
        assert res["display"] == "4x"
        assert res["use_global"] is False


def test_cemu_xml_and_protected_fullscreen() -> None:
    with _home() as td:
        home = Path(td)
        path = home / ".var/app/info.cemu.Cemu/config/Cemu/settings.xml"
        _write(
            path,
            """<?xml version="1.0" encoding="UTF-8"?>
<content>
    <fullscreen>false</fullscreen>
    <open_pad>true</open_pad>
    <Graphic>
        <VSync>0</VSync>
        <UpscaleFilter>1</UpscaleFilter>
        <AsyncCompile>true</AsyncCompile>
        <Overlay>
            <FPS>true</FPS>
        </Overlay>
    </Graphic>
</content>
""",
        )
        mod.set_cemu(home, "vsync", "1")
        text = path.read_text()
        assert "<VSync>1</VSync>" in text
        assert "<fullscreen>false</fullscreen>" in text
        assert "<open_pad>true</open_pad>" in text
        packed = mod.read_cemu(home)
        vsync = next(s for s in packed if s["key"] == "vsync")
        assert vsync["display"] == "On"


def test_detect_eden_title_from_proc() -> None:
    with _home() as td:
        home = Path(td)
        proc = home / "proc"
        rom = str(home / "games/Fire Emblem Engage[0100A6301214E000].xci")
        _fake_proc(proc, "42", "eden", ["eden", "-f", "-g", rom])
        detected = mod.detect_title("eden", home, proc)
        assert detected["title_id"] == "0100A6301214E000"
        assert "Engage" in detected["title"]
        assert mod.emu_running("eden", proc)


def test_cli_status_json() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        payload = mod.status_payload(home)
        assert payload["ok"] is True
        assert payload["emus"]["eden"]["per_game"] is True
        assert payload["emus"]["cemu"]["per_game"] is False
        res = next(
            s
            for s in payload["emus"]["eden"]["settings"]
            if s["key"] == "resolution_setup"
        )
        assert res["display"] == "1.5x"


def test_docked_label_aliases() -> None:
    spec = mod.setting_by_key("eden", "use_docked_mode")
    assert mod.normalize_value(spec, "handheld") == "false"
    assert mod.normalize_value(spec, "Docked") == "true"


def test_status_title_override() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        _write(home / ".config/eden/custom/0100A6301214E000.ini", ENGAGE)
        payload = mod.status_payload(home, emu="eden", title="0100A6301214E000")
        res = next(
            s
            for s in payload["emus"]["eden"]["settings"]
            if s["key"] == "resolution_setup"
        )
        assert payload["emus"]["eden"]["title_id"] == "0100A6301214E000"
        assert res["display"] == "4x"
        assert res["use_global"] is False


if __name__ == "__main__":
    tests = [
        test_ini_set_preserves_other_keys,
        test_per_game_override_and_effective,
        test_reset_game_keeps_engage_4gb,
        test_refuses_protected_keys,
        test_global_reset_skips_memory_and_fullscreen,
        test_azahar_does_not_touch_layout,
        test_azahar_per_game_resolution,
        test_cemu_xml_and_protected_fullscreen,
        test_detect_eden_title_from_proc,
        test_cli_status_json,
        test_docked_label_aliases,
        test_status_title_override,
    ]
    for fn in tests:
        fn()
        print(f"ok {fn.__name__}")
    print("ok")
