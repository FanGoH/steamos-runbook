#!/usr/bin/env python3
"""Offline tests for host-metrics.py (no sysstat required)."""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "host_metrics",
    Path(__file__).with_name("host-metrics.py"),
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def test_sa_and_atop_names() -> None:
    ts = time.mktime((2026, 11, 2, 12, 0, 0, 0, 0, -1))
    assert mod.sa_file(ts).name == "sa02"
    assert mod.atop_file(ts).name == "atop_20261102"


if __name__ == "__main__":
    test_sa_and_atop_names()
    print("ok")
