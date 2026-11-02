#!/usr/bin/env python3
"""Status + JSON dump for sysstat (sar) and atop.

  python3 scripts/host-metrics.py status
  python3 scripts/host-metrics.py series        # compact points for the Pi webapp
  python3 scripts/host-metrics.py json          # sadf -j memory/swap/paging
  python3 scripts/host-metrics.py json --all    # whole sa file
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


SA_DIR = Path("/var/log/sa")
ATOP_DIR = Path("/var/log/atop")


def _run(cmd: list[str], timeout: float = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )


def _unit(name: str) -> dict[str, object]:
    enabled = _run(["systemctl", "is-enabled", name]).returncode == 0
    active = _run(["systemctl", "is-active", "--quiet", name]).returncode == 0
    return {"enabled": enabled, "active": active}


def _pkg(name: str) -> str | None:
    got = _run(["pacman", "-Q", name])
    if got.returncode != 0:
        return None
    return (got.stdout or "").strip() or name


def sa_file(when: float | None = None) -> Path:
    day = time.strftime("%d", time.localtime(when or time.time()))
    return SA_DIR / f"sa{day}"


def atop_file(when: float | None = None) -> Path:
    stamp = time.strftime("%Y%m%d", time.localtime(when or time.time()))
    return ATOP_DIR / f"atop_{stamp}"


def cmd_status() -> int:
    sa = sa_file()
    atop = atop_file()
    data = {
        "ok": True,
        "sysstat": _pkg("sysstat"),
        "atop": _pkg("atop"),
        "sysstat_service": _unit("sysstat.service"),
        "sysstat_collect_timer": _unit("sysstat-collect.timer"),
        "atop_service": _unit("atop.service"),
        "sa_file": str(sa) if sa.is_file() else None,
        "atop_file": str(atop) if atop.is_file() else None,
        "interval_s": 60,
        "json": "python3 scripts/host-metrics.py json",
        "sadf": "sadf -j -- -r -S -W",
    }
    if not data["sysstat"] or not data["atop"]:
        data["ok"] = False
        data["message"] = "packages missing; ./scripts/ensure-host-metrics.sh"
    elif not data["sysstat_collect_timer"]["enabled"] or not data["atop_service"]["active"]:
        data["ok"] = False
        data["message"] = "collectors not running; ./scripts/ensure-host-metrics.sh"
    print(json.dumps(data, indent=2))
    return 0 if data["ok"] else 2


def series_from_sadf(data: dict) -> dict:
    """Compact memory/swap points from ``sadf -j -- -r -S -W`` JSON."""
    hosts = ((data.get("sysstat") or {}).get("hosts")) or []
    nodename = ""
    interval = 60
    points: list[dict[str, object]] = []
    for host in hosts:
        if not isinstance(host, dict):
            continue
        nodename = str(host.get("nodename") or nodename)
        for row in host.get("statistics") or []:
            if not isinstance(row, dict):
                continue
            ts = row.get("timestamp") or {}
            mem = row.get("memory") or {}
            if not isinstance(ts, dict) or not isinstance(mem, dict):
                continue
            date = str(ts.get("date") or "")
            clock = str(ts.get("time") or "")
            if not date or not clock:
                continue
            tz = str(ts.get("tz") or "UTC")
            iso = f"{date}T{clock}Z" if tz == "UTC" else f"{date}T{clock}"
            try:
                interval = int(ts.get("interval") or interval)
            except (TypeError, ValueError):
                pass
            used = mem.get("memused")
            pct = mem.get("memused-percent")
            avail = mem.get("avail")
            total = None
            if isinstance(used, (int, float)) and isinstance(pct, (int, float)) and pct:
                total = int(round(float(used) / (float(pct) / 100.0)))
            elif isinstance(used, (int, float)) and isinstance(avail, (int, float)):
                total = int(used + avail)
            points.append(
                {
                    "t": iso,
                    "avail_kb": mem.get("avail"),
                    "used_kb": mem.get("memused"),
                    "used_pct": mem.get("memused-percent"),
                    "swap_used_kb": mem.get("swpused"),
                    "swap_used_pct": mem.get("swpused-percent"),
                    "total_kb": total,
                }
            )
    return {
        "ok": True,
        "host": nodename or "steammachine",
        "unit": "kB",
        "interval_s": interval,
        "points": points,
    }


def series_payload() -> dict:
    sa = sa_file()
    if not sa.is_file():
        return {
            "ok": False,
            "message": f"no {sa} yet (sysstat-collect.timer every 60s)",
        }
    got = _run(["sadf", "-j", str(sa), "--", "-r", "-S", "-W"], timeout=60)
    if got.returncode != 0:
        return {
            "ok": False,
            "message": (got.stderr or got.stdout or "sadf failed").strip(),
            "rc": got.returncode,
        }
    try:
        data = json.loads(got.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {"ok": False, "message": f"sadf JSON: {exc}"}
    out = series_from_sadf(data if isinstance(data, dict) else {})
    out["sa_file"] = str(sa)
    return out


def cmd_series() -> int:
    data = series_payload()
    print(json.dumps(data))
    return 0 if data.get("ok") else 2


def cmd_json(all_metrics: bool) -> int:
    sa = sa_file()
    if not sa.is_file():
        print(
            json.dumps(
                {
                    "ok": False,
                    "message": f"no {sa} yet (sysstat-collect.timer every 60s)",
                }
            )
        )
        return 2
    args = ["sadf", "-j", str(sa)]
    if not all_metrics:
        args.extend(["--", "-r", "-S", "-W"])
    got = _run(args, timeout=60)
    if got.returncode != 0:
        print(
            json.dumps(
                {
                    "ok": False,
                    "message": (got.stderr or got.stdout or "sadf failed").strip(),
                    "rc": got.returncode,
                }
            )
        )
        return 2
    sys.stdout.write(got.stdout or "")
    if not (got.stdout or "").endswith("\n"):
        sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="sysstat + atop status / JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("series", help="Compact memory/swap points for the Pi webapp")
    jp = sub.add_parser("json", help="sadf -j memory/swap (today's sa file)")
    jp.add_argument(
        "--all",
        action="store_true",
        help="Whole sa file, not just -r -S -W",
    )
    args = parser.parse_args(argv)
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "series":
        return cmd_series()
    if args.cmd == "json":
        return cmd_json(bool(args.all))
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
