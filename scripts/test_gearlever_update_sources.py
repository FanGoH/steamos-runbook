#!/usr/bin/env python3
"""Tests for gearlever_update_sources.py (no live Gear Lever UI)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "gearlever_update_sources",
    Path(__file__).with_name("gearlever_update_sources.py"),
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_match_source() -> None:
    rpcs3 = mod.match_source("rpcs3.appimage")
    assert rpcs3 is not None
    assert rpcs3["id"] == "rpcs3"
    assert rpcs3["config"]["repo"] == "RPCS3/rpcs3-binaries-linux"
    dusk = mod.match_source("dusklight.appimage")
    assert dusk is not None and dusk["id"] == "dusklight"
    wwhd = mod.match_source("wind_waker_hd.appimage")
    assert wwhd is not None and wwhd["id"] == "wwhd"
    assert wwhd["config"]["repo"] == "ZeldaWWHDRecomp/ZeldaWWHDRecomp"
    ryu = mod.match_source("ryujinx-1.3.3-x64.appimage")
    assert ryu is not None and ryu["manager"] == "GitlabUpdater"
    ail = mod.match_source("appimagelauncher.appimage")
    assert ail is not None and ail["id"] == "appimagelauncher"
    assert mod.match_source("eden.appimage") is None
    assert mod.match_source("citron.appimage") is None


def test_skip_notes() -> None:
    assert "self-update" in (mod.skip_note("Cursor-3.17.21-x86_64.appimage") or "")
    assert "no public AppImage" in (mod.skip_note("uncharted_nathan_drake_collection_pc_port.appimage") or "")
    assert mod.skip_note("rpcs3.appimage") is None


def test_pin_does_not_overwrite(tmp_path: Path) -> None:
    appdir = tmp_path / "AppImages"
    appdir.mkdir(parents=True)
    img = appdir / "rpcs3.appimage"
    img.write_bytes(b"not-a-real-appimage")
    conf = tmp_path / "gearlever.conf"
    h = mod.app_hash(str(img))
    conf.write_text(
        f"[app.{h}.update_manager]\nmanager = GithubUpdater\nrepo = already/set\n",
        encoding="utf-8",
    )
    assert mod.pin_sources(appdir, conf, dry_run=False) == 0
    text = conf.read_text(encoding="utf-8")
    assert "already/set" in text
    assert "RPCS3/rpcs3-binaries-linux" not in text


def test_pin_writes_missing(tmp_path: Path) -> None:
    appdir = tmp_path / "AppImages"
    appdir.mkdir(parents=True)
    img = appdir / "wind_waker_hd.appimage"
    img.write_bytes(b"not-a-real-appimage")
    conf = tmp_path / "gearlever.conf"
    assert mod.pin_sources(appdir, conf, dry_run=False) == 0
    text = conf.read_text(encoding="utf-8")
    assert "ZeldaWWHDRecomp/ZeldaWWHDRecomp" in text
    assert "GithubUpdater" in text
    assert "WindWakerHD-*-linux-x86_64.AppImage" in text


def test_skip_uncharted(tmp_path: Path) -> None:
    appdir = tmp_path / "AppImages"
    appdir.mkdir(parents=True)
    (appdir / "uncharted_nathan_drake_collection_pc_port.appimage").write_bytes(b"x")
    conf = tmp_path / "gearlever.conf"
    assert mod.pin_sources(appdir, conf, dry_run=False) == 0
    assert not conf.exists() or "GithubUpdater" not in conf.read_text(encoding="utf-8")


def main() -> int:
    test_match_source()
    test_skip_notes()
    tmp = Path("/tmp/gearlever-update-tests")
    if tmp.exists():
        import shutil

        shutil.rmtree(tmp)
    tmp.mkdir()
    try:
        test_pin_does_not_overwrite(tmp / "keep")
        test_pin_writes_missing(tmp / "write")
        test_skip_uncharted(tmp / "skip")
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
    print("test_gearlever_update_sources ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
