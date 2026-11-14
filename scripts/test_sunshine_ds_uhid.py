#!/usr/bin/env python3
"""Offline check for the Distrobox /dev/uhid udev rule."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULE = (ROOT / "udev" / "99-sunshine-uhid.rules").read_text()
ENSURE = (ROOT / "scripts" / "ensure-sunshine-ds-uhid.sh").read_text()
POST = (ROOT / "post-update.sh").read_text()
BOOT = (ROOT / "bootstrap.sh").read_text()
HEALTH = (ROOT / "health-check.sh").read_text()
DS = (ROOT / "scripts" / "ensure-sunshine-ds.sh").read_text()


def test_rule_tags_uaccess() -> None:
    assert 'KERNEL=="uhid"' in RULE
    assert 'TAG+="uaccess"' in RULE
    assert "static_node=uhid" in RULE
    assert "chmod 666" not in RULE
    assert "GROUP=" not in RULE


def test_ensure_installs_and_records_manual() -> None:
    assert "/etc/udev/rules.d/99-sunshine-uhid.rules" in ENSURE
    assert "record_manual" in ENSURE
    assert "ensure-sunshine-ds.sh --restart --force" in ENSURE
    assert "chmod 666" not in ENSURE


def test_wired_from_post_update_and_ds_start() -> None:
    assert "ensure-sunshine-ds-uhid.sh" in POST
    assert "ensure-sunshine-ds-uhid.sh" in BOOT
    assert "/dev/uhid" in HEALTH
    assert "ensure-sunshine-ds-uhid.sh" in DS


if __name__ == "__main__":
    test_rule_tags_uaccess()
    test_ensure_installs_and_records_manual()
    test_wired_from_post_update_and_ds_start()
    print("ok")
