#!/usr/bin/env python3
"""Offline tests for watch-resources.py (fake /proc, no live watcher)."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile

spec = importlib.util.spec_from_file_location(
    "watch_resources",
    Path(__file__).with_name("watch-resources.py"),
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_roots() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory()


def _install_fake(root: Path) -> None:
    proc = root / "proc"
    sysfs = root / "sys"
    _write(
        proc / "meminfo",
        "MemTotal:       15396228 kB\n"
        "MemAvailable:   10322848 kB\n"
        "SwapTotal:       8746488 kB\n"
        "SwapFree:        8746488 kB\n",
    )
    _write(
        proc / "pressure" / "memory",
        "some avg10=0.00 avg60=0.00 avg300=0.00 total=124\n"
        "full avg10=0.00 avg60=0.00 avg300=0.00 total=89\n",
    )
    _write(
        proc / "vmstat",
        "pgmajfault 11338\n"
        "pgscan_kswapd 0\n"
        "pgscan_direct 0\n"
        "pswpin 0\n"
        "pswpout 0\n",
    )
    _write(proc / "loadavg", "0.42 0.50 0.60 1/200 99\n")
    _write(
        proc / "cpuinfo",
        "processor\t: 0\n"
        "model name\t: AMD Ryzen 5 9600X 6-Core Processor\n",
    )
    _write(sysfs / "class" / "dmi" / "id" / "board_name", "B650M Pro RS WiFi\n")
    _write(sysfs / "class" / "dmi" / "id" / "board_vendor", "ASRock\n")
    _write(sysfs / "block" / "zram0" / "mm_stat", "4096 64 20480 0 20480 0 0 0 0\n")
    _write(sysfs / "class" / "drm" / "card1" / "device" / "mem_info_vram_used", str(3 * 1024**3) + "\n")
    _write(sysfs / "class" / "drm" / "card1" / "device" / "mem_info_vram_total", str(16 * 1024**3) + "\n")
    eden = proc / "4242"
    _write(eden / "comm", "eden\n")
    (eden / "cmdline").write_bytes(b"eden.appimage\x00-f\x00-g\x00BotW.xci\x00")
    _write(eden / "status", "Name:\teden\nVmRSS:\t8388608 kB\nVmSwap:\t0 kB\n")
    steam = proc / "100"
    _write(steam / "comm", "steam\n")
    (steam / "cmdline").write_bytes(b"steam\x00-gamepadui\x00")
    _write(steam / "status", "Name:\tsteam\nVmRSS:\t900000 kB\nVmSwap:\t0 kB\n")
    helper = proc / "101"
    _write(helper / "comm", "steamwebhelper\n")
    (helper / "cmdline").write_bytes(b"steamwebhelper\x00")
    _write(helper / "status", "Name:\tsteamwebhelper\nVmRSS:\t100000 kB\nVmSwap:\t0 kB\n")
    os.environ["WATCH_RESOURCES_PROC"] = str(proc)
    os.environ["WATCH_RESOURCES_SYS"] = str(sysfs)
    os.environ["WATCH_RESOURCES_OUT"] = str(root / "out")
    os.environ["WATCH_RESOURCES_RUNTIME"] = str(root / "run")


def test_parse_meminfo() -> None:
    mem = mod.parse_meminfo(
        "MemTotal: 15396228 kB\nMemAvailable: 512000 kB\nSwapTotal: 100 kB\n"
    )
    assert mem["MemTotal"] == 15396228
    assert mem["MemAvailable"] == 512000


def test_parse_pressure() -> None:
    psi = mod.parse_pressure(
        "some avg10=1.50 avg60=0.20 avg300=0.00 total=9\n"
        "full avg10=0.40 avg60=0.00 avg300=0.00 total=3\n"
    )
    assert psi["some_avg10"] == 1.5
    assert psi["full_avg10"] == 0.4


def test_parse_earlyoom_argv() -> None:
    got = mod.parse_earlyoom_argv(
        ["/usr/bin/earlyoom", "-M", "409600,307200", "-S", "409600,307200"]
    )
    assert got["earlyoom_notify_kib"] == 409600
    assert got["earlyoom_kill_kib"] == 307200


def test_label_proc() -> None:
    assert mod.label_proc("AppRun.wrapped", "/home/deck/AppImages/eden.appimage -f") == "eden"
    assert mod.label_proc("sunshine-ds-kms", "anything") == "sunshine-ds-kms"
    assert mod.label_proc("Cemu_relwithdeb", "") == "cemu"
    assert mod.label_proc("steamwebhelper", "") == "steam"


def test_channel_note_ryzen_is_dual() -> None:
    note = mod.channel_note("AMD Ryzen 5 9600X 6-Core Processor")
    assert "dual-channel" in note
    assert "not four-channel" in note


def test_verdict_headroom() -> None:
    host = {
        "mem_total_kib": 16 * 1024 * 1024,
        "earlyoom_notify_kib": 409600,
        "earlyoom_kill_kib": 307200,
        "cpu": "AMD Ryzen 5 9600X 6-Core Processor",
        "channel_note": mod.channel_note("AMD Ryzen 5 9600X 6-Core Processor"),
    }
    samples = [
        {
            "t": 1,
            "iso": "2026-11-02T13:00:00",
            "mem_used_kib": 6 * 1024 * 1024,
            "mem_available_kib": 10 * 1024 * 1024,
            "swap_used_kib": 0,
            "zram_orig_kib": 0,
            "psi_some_avg10": 0.0,
            "psi_full_avg10": 0.0,
            "top": [{"label": "eden", "rss_kib": 4 * 1024 * 1024}],
        }
    ]
    summary = mod.summarize(samples, host)
    assert summary["capacity"] == "headroom"
    assert "did not top RAM" in summary["headline"]


def test_verdict_topped_by_available() -> None:
    host = {
        "mem_total_kib": 16 * 1024 * 1024,
        "earlyoom_kill_kib": 307200,
        "earlyoom_notify_kib": 409600,
        "cpu": "AMD Ryzen 5 9600X 6-Core Processor",
        "channel_note": "dual",
    }
    samples = [
        {
            "t": 1,
            "iso": "a",
            "mem_used_kib": 15 * 1024 * 1024,
            "mem_available_kib": 200000,
            "swap_used_kib": 0,
            "zram_orig_kib": 0,
            "psi_some_avg10": 0.0,
            "psi_full_avg10": 0.0,
            "top": [{"label": "eden", "rss_kib": 12 * 1024 * 1024}],
        }
    ]
    summary = mod.summarize(samples, host)
    assert summary["capacity"] == "topped"
    assert "More GB" in summary["headline"]


def test_verdict_close_on_high_use() -> None:
    host = {
        "mem_total_kib": 16 * 1024 * 1024,
        "earlyoom_kill_kib": 307200,
        "earlyoom_notify_kib": 409600,
        "cpu": "AMD Ryzen 5 9600X",
        "channel_note": "dual",
    }
    samples = [
        {
            "t": 1,
            "iso": "a",
            "mem_used_kib": int(15.2 * 1024 * 1024),
            "mem_available_kib": int(0.8 * 1024 * 1024),
            "swap_used_kib": 80 * 1024,
            "zram_orig_kib": 80 * 1024,
            "psi_some_avg10": 1.2,
            "psi_full_avg10": 0.0,
            "top": [],
        }
    ]
    summary = mod.summarize(samples, host)
    assert summary["capacity"] == "close"


def test_sample_and_html_from_fake_proc() -> None:
    with _fake_roots() as td:
        root = Path(td)
        _install_fake(root)
        sample = mod.take_sample()
        assert sample["mem_total_kib"] == 15396228
        assert sample["mem_available_kib"] == 10322848
        labels = {row["label"] for row in sample["top"]}
        assert "eden" in labels
        steam = next(row for row in sample["top"] if row["label"] == "steam")
        assert steam["rss_kib"] == 1000000
        host = mod.hardware_snapshot()
        assert "9600X" in host["cpu"]
        assert host["vram_total_kib"] == 16 * 1024 * 1024
        jsonl = root / "out" / "session.jsonl"
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        sample["top"][0]["label"] = "eden"
        jsonl.write_text(json.dumps(sample) + "\n", encoding="utf-8")
        summary = mod.write_report(jsonl, host)
        html = Path(summary["html"]).read_text(encoding="utf-8")
        assert "Resource session" in html
        assert "did not top RAM" in html or summary["capacity"] == "headroom"
        assert "dual-channel" in html
        assert "<svg" in html
        assert "eden" in html


def test_watch_duration_writes_jsonl() -> None:
    with _fake_roots() as td:
        root = Path(td)
        _install_fake(root)
        jsonl = root / "out" / "timed.jsonl"
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            rc = mod.cmd_watch(interval=0.5, duration=0.6, jsonl=jsonl)
        assert rc == 0
        samples = mod.load_jsonl(jsonl)
        assert len(samples) >= 1
        html = jsonl.with_suffix(".html")
        assert html.is_file()
        assert "Resource session" in html.read_text(encoding="utf-8")


if __name__ == "__main__":
    tests = [
        test_parse_meminfo,
        test_parse_pressure,
        test_parse_earlyoom_argv,
        test_label_proc,
        test_channel_note_ryzen_is_dual,
        test_verdict_headroom,
        test_verdict_topped_by_available,
        test_verdict_close_on_high_use,
        test_sample_and_html_from_fake_proc,
        test_watch_duration_writes_jsonl,
    ]
    for fn in tests:
        fn()
        print(f"ok {fn.__name__}")
    print("ok")
