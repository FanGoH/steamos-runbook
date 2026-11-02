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


def test_series_from_sadf() -> None:
    data = {
        "sysstat": {
            "hosts": [
                {
                    "nodename": "De-FanGoH",
                    "statistics": [
                        {
                            "timestamp": {
                                "date": "2026-11-02",
                                "time": "20:34:00",
                                "tz": "UTC",
                                "interval": 60,
                            },
                            "memory": {
                                "avail": 10169272,
                                "memused": 5226956,
                                "memused-percent": 33.95,
                                "swpused": 596888,
                                "swpused-percent": 6.82,
                            },
                        }
                    ],
                }
            ]
        }
    }
    got = mod.series_from_sadf(data)
    assert got["ok"] is True
    assert got["host"] == "De-FanGoH"
    assert got["interval_s"] == 60
    assert len(got["points"]) == 1
    point = got["points"][0]
    assert point["t"] == "2026-11-02T20:34:00Z"
    assert point["avail_kb"] == 10169272
    assert point["total_kb"] == 15396041


if __name__ == "__main__":
    test_sa_and_atop_names()
    test_series_from_sadf()
    print("ok")
