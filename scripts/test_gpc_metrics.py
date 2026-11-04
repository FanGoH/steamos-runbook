#!/usr/bin/env python3
"""Offline tests for lab/gpc-metrics outage detection."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gpc_metrics",
    ROOT / "lab" / "gpc-metrics" / "server.py",
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_gap_between_samples() -> None:
    points = [
        {"t": "2026-11-02T12:00:00Z"},
        {"t": "2026-11-02T12:01:00Z"},
        {"t": "2026-11-02T15:00:00Z"},
    ]
    now = mod.iso_to_epoch("2026-11-02T15:01:00Z")
    got = mod.sample_outages(points, now=now, gap_s=180)
    assert len(got) == 1
    assert got[0]["kind"] == "offline"
    assert got[0]["start"] == "2026-11-02T12:01:00Z"
    assert got[0]["end"] == "2026-11-02T15:00:00Z"
    assert got[0]["open"] is False


def test_trailing_offline_and_fresh_history_is_not_leading_gap() -> None:
    points = [{"t": "2026-11-02T12:00:00Z"}]
    now = mod.iso_to_epoch("2026-11-02T14:00:00Z")
    window_start = mod.iso_to_epoch("2026-11-01T14:00:00Z")
    got = mod.sample_outages(
        points, now=now, window_start=window_start, previous_t=None, gap_s=180
    )
    assert len(got) == 1
    assert got[0]["open"] is True
    assert got[0]["start"] == "2026-11-02T12:00:00Z"


def test_unreachable_merges_failed_polls() -> None:
    polls = [
        {"t": "2026-11-02T12:00:00Z", "ok": True},
        {"t": "2026-11-02T14:00:00Z", "ok": False},
        {"t": "2026-11-02T16:00:00Z", "ok": False},
        {"t": "2026-11-02T18:00:00Z", "ok": True},
    ]
    now = mod.iso_to_epoch("2026-11-02T19:00:00Z")
    got = mod.unreachable_outages(polls, now=now)
    assert len(got) == 1
    assert got[0]["kind"] == "unreachable"
    assert got[0]["start"] == "2026-11-02T14:00:00Z"
    assert got[0]["end"] == "2026-11-02T18:00:00Z"
    assert got[0]["open"] is False


def test_host_status_unreachable_beats_samples() -> None:
    points = [{"t": "2026-11-02T17:59:00Z"}]
    polls = [{"t": "2026-11-02T18:00:00Z", "ok": False}]
    now = mod.iso_to_epoch("2026-11-02T18:01:00Z")
    got = mod.host_status(points, polls, now=now, gap_s=180)
    assert got["state"] == "unreachable"


def test_host_status_online() -> None:
    points = [{"t": "2026-11-02T18:00:00Z"}]
    polls = [{"t": "2026-11-02T18:00:00Z", "ok": True}]
    now = mod.iso_to_epoch("2026-11-02T18:01:00Z")
    got = mod.host_status(points, polls, now=now, gap_s=180)
    assert got["state"] == "online"


if __name__ == "__main__":
    test_gap_between_samples()
    test_trailing_offline_and_fresh_history_is_not_leading_gap()
    test_unreachable_merges_failed_polls()
    test_host_status_unreachable_beats_samples()
    test_host_status_online()
    print("ok")
