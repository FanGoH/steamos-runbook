#!/usr/bin/env python3
"""Tests for chrome_remote_desktop.py (no live host install)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "chrome_remote_desktop",
    Path(__file__).with_name("chrome_remote_desktop.py"),
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_session_is_virtual_plasma() -> None:
    text = mod.session_file_text()
    assert "exec /usr/bin/startplasma-x11" in text
    assert "kwin_wayland --replace" not in text


def test_pam_is_arch() -> None:
    text = mod.pam_file_text()
    assert "system-remote-login" in text
    assert "@include common-auth" not in text


def test_unit_starts_official_host() -> None:
    text = mod.system_unit_text()
    assert "ExecStart=/opt/google/chrome-remote-desktop/chrome-remote-desktop --start --new-session" in text
    assert "CHROME_REMOTE_DESKTOP_USE_XVFB=1" in text
    assert "PAMName=chrome-remote-desktop" in text
    assert "WantedBy=multi-user.target" in text


def test_host_registered(tmp_path: Path) -> None:
    assert mod.host_registered(tmp_path) is False
    empty = tmp_path / "host#abc.json"
    empty.write_text("{}\n", encoding="utf-8")
    assert mod.host_registered(tmp_path) is False
    empty.write_text(json.dumps({"host_id": "abc", "private_key": "x"}), encoding="utf-8")
    assert mod.host_registered(tmp_path) is True


def test_usage_and_service() -> None:
    assert mod.service_name("deck") == "chrome-remote-desktop@deck.service"
    usage = mod.usage_text("deck")
    assert "remotedesktop.google.com/headless" in usage
    assert "remotedesktop.google.com/access" in usage
    assert "./scripts/crd.sh status" in usage
    assert "Sunshine" in usage


def test_self_test() -> None:
    assert mod.self_test() == 0


def main() -> int:
    test_session_is_virtual_plasma()
    test_pam_is_arch()
    test_unit_starts_official_host()
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        test_host_registered(Path(tmp))
    test_usage_and_service()
    test_self_test()
    print("test_chrome_remote_desktop ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
