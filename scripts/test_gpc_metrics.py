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


def test_should_fetch_uses_last_success_only() -> None:
    now = mod.iso_to_epoch("2026-11-08T17:00:00Z")
    hour_ago = mod.iso_to_epoch("2026-11-08T16:00:00Z")
    assert mod.should_fetch(hour_ago, now=now, poll_s=7200) is False
    assert mod.should_fetch(hour_ago, now=now, poll_s=3600) is True
    assert mod.should_fetch(None, now=now, poll_s=7200) is True


def test_maybe_fetch_skips_recent_success() -> None:
    calls: list[str] = []
    orig = mod._fetch

    def fake_fetch() -> None:
        calls.append("fetch")
        stamp = "2026-11-08T19:00:00Z"
        with mod._lock:
            mod._state["ok"] = True
            mod._state["last_fetch"] = stamp
            mod._state["last_ok_fetch"] = stamp

    mod._fetch = fake_fetch  # type: ignore[method-assign]
    try:
        with mod._lock:
            mod._state["last_ok_fetch"] = "2026-11-08T16:30:00Z"
            mod._state["ok"] = True
        now = mod.iso_to_epoch("2026-11-08T17:00:00Z")
        assert mod.maybe_fetch(now=now) == "skipped"
        assert calls == []
        later = mod.iso_to_epoch("2026-11-08T19:00:00Z")
        assert mod.maybe_fetch(now=later) == "fetched"
        assert calls == ["fetch"]
    finally:
        mod._fetch = orig  # type: ignore[method-assign]


if __name__ == "__main__":
    test_gap_between_samples()
    test_trailing_offline_and_fresh_history_is_not_leading_gap()
    test_unreachable_merges_failed_polls()
    test_host_status_unreachable_beats_samples()
    test_host_status_online()
    test_should_fetch_uses_last_success_only()
    test_maybe_fetch_skips_recent_success()
    print("ok")
