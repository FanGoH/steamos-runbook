#!/usr/bin/env python3
"""Poll steammachine sysstat JSON and serve a RAM chart on lab.

Binds 127.0.0.1 only. Caddy on Tailscale is the public entry
(https://ram.tailnet.fangoh.dev). SteamOS updates wipe /var/log/sa;
this process keeps a 14-day copy on the Pi.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
BIND = os.environ.get("GPC_METRICS_BIND", "127.0.0.1")
PORT = int(os.environ.get("GPC_METRICS_PORT", "8020"))
SOURCE = os.environ.get(
    "GPC_METRICS_SOURCE", "http://100.64.0.8:8484/api/host-metrics"
)
POLL_S = int(os.environ.get("GPC_METRICS_POLL_S", "60"))
KEEP_DAYS = int(os.environ.get("GPC_METRICS_KEEP_DAYS", "14"))
DATA_DIR = Path(
    os.environ.get("GPC_METRICS_DATA", str(Path.home() / ".local/share/gpc-metrics"))
)
DB_PATH = DATA_DIR / "points.sqlite"

_lock = threading.Lock()
_state: dict[str, object] = {
    "ok": False,
    "last_fetch": None,
    "last_error": None,
    "source": SOURCE,
    "points_stored": 0,
}


def _db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points (
            t TEXT PRIMARY KEY,
            avail_kb INTEGER,
            used_kb INTEGER,
            used_pct REAL,
            swap_used_kb INTEGER,
            swap_used_pct REAL,
            total_kb INTEGER
        )
        """
    )
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _upsert(points: list[dict]) -> int:
    if not points:
        return 0
    cutoff = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - KEEP_DAYS * 86400)
    )
    with _db() as conn:
        conn.executemany(
            """
            INSERT INTO points (
                t, avail_kb, used_kb, used_pct,
                swap_used_kb, swap_used_pct, total_kb
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(t) DO UPDATE SET
                avail_kb=excluded.avail_kb,
                used_kb=excluded.used_kb,
                used_pct=excluded.used_pct,
                swap_used_kb=excluded.swap_used_kb,
                swap_used_pct=excluded.swap_used_pct,
                total_kb=excluded.total_kb
            """,
            [
                (
                    p.get("t"),
                    p.get("avail_kb"),
                    p.get("used_kb"),
                    p.get("used_pct"),
                    p.get("swap_used_kb"),
                    p.get("swap_used_pct"),
                    p.get("total_kb"),
                )
                for p in points
                if p.get("t")
            ],
        )
        conn.execute("DELETE FROM points WHERE t < ?", (cutoff,))
        count = conn.execute("SELECT COUNT(*) FROM points").fetchone()[0]
    return int(count)


def _fetch() -> None:
    req = urllib.request.Request(
        SOURCE, headers={"Accept": "application/json", "User-Agent": "gpc-metrics/1"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        if not isinstance(raw, dict) or not raw.get("ok"):
            raise RuntimeError((raw or {}).get("message") if isinstance(raw, dict) else "bad JSON")
        stored = _upsert(list(raw.get("points") or []))
        with _lock:
            _state.update(
                {
                    "ok": True,
                    "last_fetch": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "last_error": None,
                    "host": raw.get("host"),
                    "interval_s": raw.get("interval_s"),
                    "points_stored": stored,
                }
            )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError, OSError) as exc:
        with _lock:
            _state["ok"] = False
            _state["last_error"] = str(exc)
            _state["last_fetch"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _poller() -> None:
    while True:
        _fetch()
        time.sleep(max(15, POLL_S))


def _series(hours: float) -> dict:
    since = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - max(0.25, hours) * 3600)
    )
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT t, avail_kb, used_kb, used_pct,
                   swap_used_kb, swap_used_pct, total_kb
            FROM points WHERE t >= ? ORDER BY t
            """,
            (since,),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM points").fetchone()[0]
    points = [
        {
            "t": r[0],
            "avail_kb": r[1],
            "used_kb": r[2],
            "used_pct": r[3],
            "swap_used_kb": r[4],
            "swap_used_pct": r[5],
            "total_kb": r[6],
        }
        for r in rows
    ]
    with _lock:
        meta = dict(_state)
    meta["ok"] = True
    meta["hours"] = hours
    meta["points"] = points
    meta["points_stored"] = int(total)
    return meta


def _json(data: object, status: int = 200) -> tuple[int, bytes, str]:
    body = json.dumps(data).encode("utf-8")
    return status, body, "application/json; charset=utf-8"


def handle(method: str, path: str) -> tuple[int, bytes, str]:
    parsed = urlparse(path)
    route = parsed.path or "/"
    method = method.upper()
    if method == "GET" and route in ("/healthz", "/api/health"):
        with _lock:
            data = dict(_state)
        return _json(data, 200)
    if method == "GET" and route == "/api/series":
        query = parse_qs(parsed.query)
        try:
            hours = float((query.get("hours") or ["24"])[0])
        except ValueError:
            hours = 24.0
        hours = min(max(hours, 0.25), KEEP_DAYS * 24)
        return _json(_series(hours))
    if method in ("GET", "HEAD") and route in ("/", "/index.html"):
        html = (HERE / "index.html").read_bytes()
        return 200, html, "text/html; charset=utf-8"
    return _json({"ok": False, "message": f"unknown {method} {route}"}, 404)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._send(*handle("GET", self.path))

    def do_HEAD(self) -> None:  # noqa: N802
        self._send(*handle("HEAD", self.path))


def main() -> int:
    if "--self-test" in sys.argv:
        status, body, _ = handle("GET", "/")
        print(json.dumps({"ok": status == 200, "bytes": len(body)}))
        return 0 if status == 200 else 1
    _db().close()
    threading.Thread(target=_poller, daemon=True).start()
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    server.daemon_threads = True
    print(f"gpc-metrics http://{BIND}:{PORT} source={SOURCE}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
