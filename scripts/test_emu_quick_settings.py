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


def test_detect_eden_title_from_log_when_rom_has_no_hex() -> None:
    with _home() as td:
        home = Path(td)
        proc = home / "proc"
        rom = home / "retrodeck/roms/switch/dump.xci/dump.xci"
        _write(rom, "x")
        _write(
            mod.eden_log(home),
            "Booting game: 010093801237C000 | Metroid Dread | 1.0.0\n",
        )
        _fake_proc(proc, "42", "eden", ["eden", "-f", "-g", str(rom)])
        detected = mod.detect_title("eden", home, proc)
        assert detected["title_id"] == "010093801237C000"
        assert detected["title"] == "Metroid Dread"
        assert detected["rom"] == str(rom)


def test_save_fills_running_title_when_omitted() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        proc = home / "proc"
        rom = str(home / "games/Fire Emblem Engage[0100A6301214E000].xci")
        _fake_proc(proc, "42", "eden", ["eden", "-f", "-g", rom])
        result = mod.do_save(
            "eden",
            "game",
            "",
            {"resolution_setup": "4"},
            home,
            proc_root=proc,
        )
        assert result["ok"] is True
        custom = home / ".config/eden/custom/0100A6301214E000.ini"
        assert custom.is_file()
        assert "resolution_setup=4" in custom.read_text()


def test_detect_eden_title_from_library_name() -> None:
    with _home() as td:
        home = Path(td)
        proc = home / "proc"
        _write(
            home / "retrodeck/roms/switch/Metroid Dread [010093801237C000].xci",
            "x",
        )
        rom = home / "retrodeck/roms/switch/Metroid Dread.xci/Metroid Dread.xci"
        _write(rom, "x")
        _fake_proc(proc, "42", "eden", ["eden", "-f", "-g", str(rom)])
        detected = mod.detect_title("eden", home, proc)
        assert detected["title_id"] == "010093801237C000"
        assert detected["title"] == "Metroid Dread"


def test_title_id_from_name_requires_unique_match() -> None:
    names = {
        "010093801237C000": "Metroid Dread",
        "0100AAAA12345678": "Metroid Dread",
        "0100A6301214E000": "Fire Emblem Engage",
    }
    assert mod.title_id_from_name(names, "Fire Emblem Engage", "eden") == "0100A6301214E000"
    assert mod.title_id_from_name(names, "Metroid Dread", "eden") == ""
    assert mod.title_id_from_name(names, "missing", "eden") == ""


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


def test_qt_keyseq_and_hotswap_keys() -> None:
    assert mod.qt_keyseq_to_xdotool("Ctrl+U") == "ctrl+u"
    assert mod.qt_keyseq_to_xdotool("F10") == "F10"
    assert mod.qt_keyseq_to_xdotool('"Ctrl+,"') == "ctrl+comma"
    assert mod.eden_hotswap_keys("use_docked_mode", "false", "true") == ["F10"]
    assert mod.eden_hotswap_keys("use_docked_mode", "true", "true") == []
    assert mod.eden_hotswap_keys("scaling_filter", "0", "2") == ["F8", "F8"]
    assert mod.eden_hotswap_keys("scaling_filter", "6", "0") == ["F8"]
    assert mod.eden_hotswap_keys("gpu_accuracy", "0", "1") == ["F9"]
    assert mod.eden_hotswap_keys("gpu_accuracy", "0", "2") == []
    assert mod.eden_hotswap_keys("use_speed_limit", "true", "false") == ["ctrl+u"]
    assert mod.eden_hotswap_keys("resolution_setup", "2", "4") == []
    rebound = {
        name: mod.qt_keyseq_to_xdotool(seq)
        for name, seq in mod.EDEN_HOTKEY_DEFAULTS.items()
    }
    rebound["docked"] = "F7"
    assert mod.eden_hotswap_keys("use_docked_mode", "false", "true", rebound) == ["F7"]


def test_parse_shortcut_from_ini() -> None:
    text = (
        r"Shortcuts\Main%20Window\Change%20Docked%20Mode\KeySeq\default=false"
        "\n"
        r"Shortcuts\Main%20Window\Change%20Docked%20Mode\KeySeq=F7"
        "\n"
        r"Shortcuts\Main%20Window\Change%20Adapting%20Filter\KeySeq=F8"
        "\n"
    )
    keys = mod.load_eden_hotkeys(text)
    assert keys["docked"] == "F7"
    assert keys["filter"] == "F8"
    assert keys["speed"] == "ctrl+u"


def test_do_set_hotswap_skipped_with_proc() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        proc = home / "proc"
        rom = str(home / "games/Fire Emblem Engage[0100A6301214E000].xci")
        _fake_proc(proc, "42", "eden", ["eden", "-f", "-g", rom])
        result = mod.do_set(
            "eden", "global", "", "use_docked_mode", "false", home, proc_root=proc
        )
        assert result["ok"] is True
        assert result["hotswap_keys"] == ["F10"]
        assert result["hotswap"] == "skipped"
        assert result["hotswap_reason"] == "test_proc"
        text = mod.eden_ini(home).read_text()
        assert "use_docked_mode=false" in text
        res = mod.do_set(
            "eden", "global", "", "resolution_setup", "2", home, proc_root=proc
        )
        assert res["hotswap_keys"] == []
        assert res["hotswap_reason"] == "no_hotkey"
        assert "Close and reopen Eden" in res["message"]


def test_hotswap_skips_other_game_and_override() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        _write(
            home / ".config/eden/custom/0100A6301214E000.ini",
            "[System]\nuse_docked_mode\\use_global=false\nuse_docked_mode=true\n",
        )
        proc = home / "proc"
        rom = str(home / "games/Fire Emblem Engage[0100A6301214E000].xci")
        _fake_proc(proc, "42", "eden", ["eden", "-f", "-g", rom])
        global_set = mod.do_set(
            "eden", "global", "", "use_docked_mode", "false", home, proc_root=proc
        )
        assert global_set["hotswap_reason"] == "game_override"
        other = mod.do_set(
            "eden",
            "game",
            "0100F2C0115B6000",
            "use_docked_mode",
            "true",
            home,
            proc_root=proc,
        )
        assert other["hotswap_reason"] == "other_game"
        same = mod.do_set(
            "eden",
            "game",
            "0100A6301214E000",
            "use_docked_mode",
            "false",
            home,
            proc_root=proc,
        )
        assert same["hotswap_reason"] == "test_proc"
        assert same["hotswap_keys"] == ["F10"]


def test_status_marks_live_settings() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        payload = mod.status_payload(home)
        docked = next(
            s
            for s in payload["emus"]["eden"]["settings"]
            if s["key"] == "use_docked_mode"
        )
        res = next(
            s
            for s in payload["emus"]["eden"]["settings"]
            if s["key"] == "resolution_setup"
        )
        assert docked["hotswap"] == "live"
        assert res["hotswap"] == "restart"
        assert docked["widget"] == "toggle"
        assert res["widget"] == "slider"


def test_live_only_does_not_write_until_save() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        proc = home / "proc"
        rom = str(home / "games/Fire Emblem Engage[0100A6301214E000].xci")
        _fake_proc(proc, "42", "eden", ["eden", "-f", "-g", rom])
        live = mod.do_set(
            "eden",
            "global",
            "",
            "use_docked_mode",
            "false",
            home,
            proc_root=proc,
            live_only=True,
        )
        assert live["wrote"] is False
        assert live["hotswap_keys"] == ["F10"]
        text = mod.eden_ini(home).read_text()
        assert "use_docked_mode=1" in text
        saved = mod.do_save("eden", "global", "", {"use_docked_mode": "false"}, home)
        assert saved["wrote"] is True
        assert "use_docked_mode=false" in mod.eden_ini(home).read_text()


def test_live_session_tracks_filter_steps() -> None:
    with _home() as td:
        home = Path(td)
        _write(mod.eden_ini(home), GLOBAL_EDEN)
        proc = home / "proc"
        rom = str(home / "games/Fire Emblem Engage[0100A6301214E000].xci")
        _fake_proc(proc, "42", "eden", ["eden", "-f", "-g", rom])
        first = mod.do_set(
            "eden",
            "global",
            "",
            "scaling_filter",
            "3",
            home,
            proc_root=proc,
            live_only=True,
        )
        assert first["hotswap_keys"] == ["F8", "F8"]
        second = mod.do_set(
            "eden",
            "global",
            "",
            "scaling_filter",
            "4",
            home,
            proc_root=proc,
            live_only=True,
        )
        assert second["hotswap_keys"] == ["F8"]
        assert "scaling_filter=1" in mod.eden_ini(home).read_text()


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
        test_detect_eden_title_from_log_when_rom_has_no_hex,
        test_detect_eden_title_from_library_name,
        test_title_id_from_name_requires_unique_match,
        test_save_fills_running_title_when_omitted,
        test_cli_status_json,
        test_docked_label_aliases,
        test_status_title_override,
        test_qt_keyseq_and_hotswap_keys,
        test_parse_shortcut_from_ini,
        test_do_set_hotswap_skipped_with_proc,
        test_hotswap_skips_other_game_and_override,
        test_status_marks_live_settings,
        test_live_only_does_not_write_until_save,
        test_live_session_tracks_filter_steps,
    ]
    for fn in tests:
        fn()
        print(f"ok {fn.__name__}")
    print("ok")
