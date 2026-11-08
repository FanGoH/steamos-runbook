#!/usr/bin/env python3
"""Offline checks for the Plasma sunshine-ds oneshot (no session switch)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENSURE = (ROOT / "scripts" / "ensure-sunshine-ds.sh").read_text()
RUNNER = (ROOT / "scripts" / "run-sunshine-ds-gamemode.sh").read_text()
ON_DESKTOP = (ROOT / "scripts" / "sunshine-ds-on-desktop.sh").read_text()


def test_plasma_unit_is_wanted_by_plasmashell() -> None:
    assert "WantedBy=plasma-plasmashell.service" in ENSURE
    assert "PartOf=plasma-plasmashell.service" in ENSURE
    assert "RemainAfterExit=yes" in ENSURE
    assert "ExecStop=" in ENSURE and "--stop" in ENSURE
    assert 'systemctl --user enable "$ON_DESKTOP_SERVICE"' in ENSURE
    assert "start on demand; not enabled at login" not in ENSURE


def test_stop_does_not_rewrite_units() -> None:
    stop_idx = ENSURE.index('if [ "$DO_STOP" -eq 1 ]; then')
    shortcut_idx = ENSURE.index("ensure_game_mode_shortcut", stop_idx)
    assert stop_idx < shortcut_idx
    stop_block = ENSURE[stop_idx:shortcut_idx]
    assert "stop_helpers" in stop_block
    assert "ensure_game_mode_shortcut" not in stop_block


def test_kms_runner_stops_desktop_ds() -> None:
    assert "Stopping desktop sunshine-ds so Game Mode kms can bind." in RUNNER
    assert "ensure-sunshine-ds.sh" in RUNNER and "--stop" in RUNNER
    assert "Stop it with ensure-sunshine-ds.sh --stop before Game Mode KMS." not in RUNNER


def test_on_desktop_script_waits_for_plasma() -> None:
    assert "WantedBy=plasma-plasmashell.service" in ON_DESKTOP
    assert "ensure-sunshine-ds.sh" in ON_DESKTOP
    assert "gamescope_up" in ON_DESKTOP


if __name__ == "__main__":
    test_plasma_unit_is_wanted_by_plasmashell()
    test_stop_does_not_rewrite_units()
    test_kms_runner_stops_desktop_ds()
    test_on_desktop_script_waits_for_plasma()
    print("ok")
