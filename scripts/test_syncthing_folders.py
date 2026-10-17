#!/usr/bin/env python3
"""Tests for syncthing_folders.py helpers (no live Syncthing)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "syncthing_folders",
    Path(__file__).with_name("syncthing_folders.py"),
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_lookup_lab_device() -> None:
    devices = [
        {"deviceID": "AAA", "name": "thor"},
        {"deviceID": "BBB", "name": "lab"},
        {"deviceID": "CCC", "name": "odin"},
    ]
    assert mod.lookup_device_id(devices, "lab") == "BBB"
    assert mod.lookup_device_id(devices, "LAB") == "BBB"
    assert mod.lookup_device_id(devices, "missing") is None


def test_parse_id_list() -> None:
    assert mod.parse_id_list('AAA BBB') == ["AAA", "BBB"]
    assert mod.parse_id_list('"AAA BBB"') == ["AAA", "BBB"]
    assert mod.parse_id_list("") == []


def test_exclusive_devices_drop_extras() -> None:
    existing = [
        {"deviceID": "LOCAL"},
        {"deviceID": "THOR"},
        {"deviceID": "ODIN"},
        {"deviceID": "LAB"},
    ]
    devices = mod.devices_for_folder(existing, ["LAB"], "LOCAL", exclusive=True)
    ids = {d["deviceID"] for d in devices}
    assert ids == {"LOCAL", "LAB"}


def test_mesh_devices_keep_existing() -> None:
    existing = [{"deviceID": "LOCAL"}, {"deviceID": "FANGOHV"}]
    devices = mod.devices_for_folder(existing, ["LAB", "THOR"], "LOCAL", exclusive=False)
    ids = {d["deviceID"] for d in devices}
    assert "FANGOHV" in ids
    assert "LAB" in ids
    assert "THOR" in ids
    assert "LOCAL" in ids


def test_uncharted_peer_ids() -> None:
    assert mod.uncharted_peer_ids(["LAB"], extra="") == ["LAB"]
    assert mod.uncharted_peer_ids(["LAB"], extra="AAA BBB") == ["AAA", "BBB"]
    assert mod.uncharted_peer_ids([], extra="") == []


def main() -> int:
    test_lookup_lab_device()
    test_parse_id_list()
    test_exclusive_devices_drop_extras()
    test_mesh_devices_keep_existing()
    test_uncharted_peer_ids()
    print("test_syncthing_folders ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
