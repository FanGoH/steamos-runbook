#!/usr/bin/env python3
"""Tests for playbook-post-update.py (no live post-update.sh run)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "playbook_post_update",
    Path(__file__).with_name("playbook-post-update.py"),
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_summarize() -> None:
    empty = mod.summarize_results("")
    assert empty["overall"] == "idle"
    assert empty["ok"] == 0
    ok = mod.summarize_results("OK|ensure-pacman|0\nOK|ensure-sshd|0\n")
    assert ok["overall"] == "ok"
    assert ok["ok"] == 2
    warn = mod.summarize_results("OK|a|0\nWARN|b|2\n")
    assert warn["overall"] == "warn"
    fail = mod.summarize_results("OK|a|0\nFAIL|b|1\n")
    assert fail["overall"] == "fail"
    assert fail["fail"] == 1
    skipped = mod.summarize_results("OK|a|0\nSKIP|ensure-switch2-controllers|0\n")
    assert skipped["skip"] == 1
    assert skipped["overall"] == "ok"


def test_manual_excerpt() -> None:
    assert mod.manual_excerpt("") == []
    lines = mod.manual_excerpt("## A\n\n# b\n## C\n", limit=2)
    assert lines == ["## A", "# b"]


def test_parse_tender_output() -> None:
    parsed = mod.parse_tender_output(
        "Tender installed: 0.31.0\n"
        "Tender wanted: 0.33.0 (tender-v0.33.0)\n"
        "needs_update: yes\n"
    )
    assert parsed["installed"] == "0.31.0"
    assert parsed["wanted"] == "0.33.0"
    assert parsed["needs_update"] is True
    done = mod.parse_tender_output("Tender is 0.33.0 (was 0.31.0).\n")
    assert done["installed"] == "0.33.0"
    assert done["needs_update"] is False


def test_launcher_wrapped() -> None:
    assert mod.launcher_wrapped(Path("/missing/rom-launcher")) is False


def test_self_test() -> None:
    assert mod.self_test() == 0


def main() -> int:
    test_summarize()
    test_manual_excerpt()
    test_parse_tender_output()
    test_launcher_wrapped()
    test_self_test()
    print("test_playbook_post_update ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
