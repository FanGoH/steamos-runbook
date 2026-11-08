#!/usr/bin/env python3
"""Poll steammachine sysstat JSON and serve a RAM chart on lab.

Binds 127.0.0.1 only. Caddy on Tailscale is the public entry
(https://lab.tailnet.fangoh.dev). SteamOS updates wipe /var/log/sa;
this process keeps a 14-day copy on the Pi.

Poll every 2 hours (full sa history each time), and again when someone
opens the dashboard if that last *successful* pull (cron or visit) is
older than 2 hours. A failed poll does not start the cooldown. Gaps in
the 60s sysstat series, or a failed poll, are reported as offline /
unreachable.
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
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
BIND = os.environ.get("GPC_METRICS_BIND", "127.0.0.1")
PORT = int(os.environ.get("GPC_METRICS_PORT", "8020"))
SOURCE = os.environ.get(
    "GPC_METRICS_SOURCE", "http://100.64.0.8:8484/api/host-metrics"
)
POLL_S = int(os.environ.get("GPC_METRICS_POLL_S", "7200"))
KEEP_DAYS = int(os.environ.get("GPC_METRICS_KEEP_DAYS", "14"))
SAMPLE_INTERVAL_S = int(os.environ.get("GPC_METRICS_SAMPLE_INTERVAL_S", "60"))
GAP_S = int(os.environ.get("GPC_METRICS_GAP_S", str(SAMPLE_INTERVAL_S * 3)))
DATA_DIR = Path(
    os.environ.get("GPC_METRICS_DATA", str(Path.home() / ".local/share/gpc-metrics"))
)
DB_PATH = DATA_DIR / "points.sqlite"

_lock = threading.Lock()
_fetch_lock = threading.Lock()
_state: dict[str, object] = {
    "ok": False,
    "last_fetch": None,
    "last_ok_fetch": None,
    "last_error": None,
    "source": SOURCE,
    "poll_s": POLL_S,
    "points_stored": 0,
    "pull": None,
}


def iso_to_epoch(stamp: str) -> float | None:
    text = (stamp or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def epoch_to_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def should_fetch(
    last_ok: float | None,
    now: float | None = None,
    poll_s: int | None = None,
) -> bool:
    """True unless a successful cron/visit pull is still inside the cooldown."""
    now = time.time() if now is None else now
    wait = POLL_S if poll_s is None else poll_s
    if last_ok is None:
        return True
    return (now - last_ok) >= wait


def sample_outages(
    points: list[dict],
    *,
    interval_s: int = SAMPLE_INTERVAL_S,
    gap_s: int = GAP_S,
    now: float | None = None,
    window_start: float | None = None,
    previous_t: float | None = None,
) -> list[dict]:
    """Host not collecting: missing sysstat samples longer than gap_s.

    Do not treat an empty history (fresh dashboard) as offline. A leading gap
    is only reported when a sample exists before the window.
    """
    now = time.time() if now is None else now
    times = sorted(
        t for t in (iso_to_epoch(str(p.get("t") or "")) for p in points) if t is not None
    )
    out: list[dict] = []
    if previous_t is not None:
        nxt = times[0] if times else now
        if nxt - previous_t >= gap_s:
            start = previous_t
            if window_start is not None:
                start = max(start, window_start)
            if nxt - start >= gap_s:
                out.append(
                    {
                        "start": epoch_to_iso(start),
                        "end": epoch_to_iso(nxt),
                        "kind": "offline",
                        "open": not times,
                        "seconds": int(nxt - start),
                    }
                )
    for left, right in zip(times, times[1:]):
        if right - left >= gap_s:
            out.append(
                {
                    "start": epoch_to_iso(left),
                    "end": epoch_to_iso(right),
                    "kind": "offline",
                    "open": False,
                    "seconds": int(right - left),
                }
            )
    if times and now - times[-1] >= gap_s:
        out.append(
            {
                "start": epoch_to_iso(times[-1]),
                "end": epoch_to_iso(now),
                "kind": "offline",
                "open": True,
                "seconds": int(now - times[-1]),
            }
        )
    _ = interval_s
    return out


def unreachable_outages(
    polls: list[dict],
    *,
    now: float | None = None,
    window_start: float | None = None,
) -> list[dict]:
    """Pi could not fetch the host API."""
    now = time.time() if now is None else now
    rows = []
    for poll in polls:
        ts = iso_to_epoch(str(poll.get("t") or ""))
        if ts is None:
            continue
        if window_start is not None and ts < window_start:
            continue
        rows.append((ts, bool(poll.get("ok"))))
    rows.sort()
    out: list[dict] = []
    start: float | None = None
    for ts, ok in rows:
        if not ok:
            if start is None:
                start = ts
        elif start is not None:
            out.append(
                {
                    "start": epoch_to_iso(start),
                    "end": epoch_to_iso(ts),
                    "kind": "unreachable",
                    "open": False,
                    "seconds": int(ts - start),
                }
            )
            start = None
    if start is not None:
        out.append(
            {
                "start": epoch_to_iso(start),
                "end": epoch_to_iso(now),
                "kind": "unreachable",
                "open": True,
                "seconds": int(now - start),
            }
        )
    return out


def host_status(
    points: list[dict],
    polls: list[dict],
    *,
    now: float | None = None,
    gap_s: int = GAP_S,
) -> dict:
    now = time.time() if now is None else now
    last_sample = None
    if points:
        last_sample = max(
            (str(p.get("t") or "") for p in points),
            default="",
        ) or None
    last_poll = polls[-1] if polls else None
    last_poll_ok = bool(last_poll.get("ok")) if last_poll else None
    last_poll_t = str(last_poll.get("t") or "") if last_poll else None
    sample_epoch = iso_to_epoch(last_sample or "")
    if last_poll is not None and not last_poll_ok:
        since = last_poll_t or last_sample
        return {
            "state": "unreachable",
            "since": since,
            "last_sample": last_sample,
            "last_poll": last_poll_t,
            "detail": "lab could not reach fgpc-web on the Steam Machine",
        }
    if sample_epoch is not None and now - sample_epoch >= gap_s:
        return {
            "state": "offline",
            "since": last_sample,
            "last_sample": last_sample,
            "last_poll": last_poll_t,
            "detail": "sysstat stopped producing 60s samples (host off, hung, or collector down)",
        }
    if last_sample:
        return {
            "state": "online",
            "since": last_sample,
            "last_sample": last_sample,
            "last_poll": last_poll_t,
            "detail": "sysstat samples are current",
        }
    return {
        "state": "unknown",
        "since": None,
        "last_sample": None,
        "last_poll": last_poll_t,
        "detail": "no samples yet",
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS polls (
            t TEXT PRIMARY KEY,
            ok INTEGER NOT NULL,
            error TEXT,
            last_sample TEXT
        )
        """
    )
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _cutoff_iso() -> str:
    return epoch_to_iso(time.time() - KEEP_DAYS * 86400)


def _upsert(points: list[dict]) -> int:
    cutoff = _cutoff_iso()
    with _db() as conn:
        if points:
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
        conn.execute("DELETE FROM polls WHERE t < ?", (cutoff,))
        count = conn.execute("SELECT COUNT(*) FROM points").fetchone()[0]
    return int(count)


def _record_poll(*, ok: bool, error: str | None, last_sample: str | None) -> None:
    now = epoch_to_iso(time.time())
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO polls (t, ok, error, last_sample)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(t) DO UPDATE SET
                ok=excluded.ok, error=excluded.error, last_sample=excluded.last_sample
            """,
            (now, 1 if ok else 0, error, last_sample),
        )
        conn.execute("DELETE FROM polls WHERE t < ?", (_cutoff_iso(),))


def _fetch() -> None:
    req = urllib.request.Request(
        SOURCE, headers={"Accept": "application/json", "User-Agent": "gpc-metrics/1"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        if not isinstance(raw, dict) or not raw.get("ok"):
            raise RuntimeError(
                (raw or {}).get("message") if isinstance(raw, dict) else "bad JSON"
            )
        points = list(raw.get("points") or [])
        stored = _upsert(points)
        last_sample = str(points[-1]["t"]) if points and points[-1].get("t") else None
        _record_poll(ok=True, error=None, last_sample=last_sample)
        stamp = epoch_to_iso(time.time())
        with _lock:
            _state.update(
                {
                    "ok": True,
                    "last_fetch": stamp,
                    "last_ok_fetch": stamp,
                    "last_error": None,
                    "host": raw.get("host"),
                    "interval_s": raw.get("interval_s") or SAMPLE_INTERVAL_S,
                    "points_stored": stored,
                }
            )
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        RuntimeError,
        OSError,
    ) as exc:
        _record_poll(ok=False, error=str(exc), last_sample=None)
        with _lock:
            _state["ok"] = False
            _state["last_error"] = str(exc)
            _state["last_fetch"] = epoch_to_iso(time.time())


def last_ok_fetch_epoch() -> float | None:
    with _lock:
        stamp = _state.get("last_ok_fetch")
    ts = iso_to_epoch(str(stamp or ""))
    if ts is not None:
        return ts
    with _db() as conn:
        row = conn.execute(
            "SELECT t FROM polls WHERE ok = 1 ORDER BY t DESC LIMIT 1"
        ).fetchone()
    ts = iso_to_epoch(row[0]) if row else None
    if ts is not None:
        with _lock:
            if _state.get("last_ok_fetch") is None:
                _state["last_ok_fetch"] = epoch_to_iso(ts)
    return ts


def maybe_fetch(*, now: float | None = None) -> str:
    """Pull unless a successful cron/visit fetch is still inside POLL_S."""
    now = time.time() if now is None else now
    with _fetch_lock:
        last = last_ok_fetch_epoch()
        if not should_fetch(last, now=now):
            with _lock:
                _state["pull"] = "skipped"
            return "skipped"
        _fetch()
        with _lock:
            ok = bool(_state.get("ok"))
            _state["pull"] = "fetched" if ok else "failed"
        return "fetched" if ok else "failed"


def _poll_sleep() -> None:
    last = last_ok_fetch_epoch()
    now = time.time()
    if last is None:
        time.sleep(max(15, POLL_S))
        return
    remain = POLL_S - (now - last)
    time.sleep(max(15, remain if remain > 0 else POLL_S))


def _poller() -> None:
    while True:
        maybe_fetch()
        _poll_sleep()


def _load_window(since: str) -> tuple[list[dict], list[dict], int, float | None, str | None]:
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT t, avail_kb, used_kb, used_pct,
                   swap_used_kb, swap_used_pct, total_kb
            FROM points WHERE t >= ? ORDER BY t
            """,
            (since,),
        ).fetchall()
        prev = conn.execute(
            "SELECT t FROM points WHERE t < ? ORDER BY t DESC LIMIT 1",
            (since,),
        ).fetchone()
        polls = conn.execute(
            "SELECT t, ok, error, last_sample FROM polls ORDER BY t"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM points").fetchone()[0]
        last_ever = conn.execute(
            "SELECT t FROM points ORDER BY t DESC LIMIT 1"
        ).fetchone()
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
    poll_rows = [
        {"t": r[0], "ok": bool(r[1]), "error": r[2], "last_sample": r[3]} for r in polls
    ]
    return (
        points,
        poll_rows,
        int(total),
        iso_to_epoch(prev[0]) if prev else None,
        str(last_ever[0]) if last_ever else None,
    )


def _clip_outages(
    outages: list[dict], window_start: float, now: float
) -> list[dict]:
    clipped: list[dict] = []
    for item in outages:
        start = iso_to_epoch(str(item.get("start") or ""))
        end = iso_to_epoch(str(item.get("end") or ""))
        if start is None or end is None:
            continue
        if end <= window_start or start >= now:
            continue
        start = max(start, window_start)
        end = min(end, now)
        if end - start < 1:
            continue
        clipped.append(
            {
                **item,
                "start": epoch_to_iso(start),
                "end": epoch_to_iso(end),
                "seconds": int(end - start),
            }
        )
    return clipped


def _series(hours: float) -> dict:
    now = time.time()
    window_start = now - max(0.25, hours) * 3600
    since = epoch_to_iso(window_start)
    points, polls, total, previous_t, last_ever = _load_window(since)
    interval = int(_state.get("interval_s") or SAMPLE_INTERVAL_S)
    outages = sample_outages(
        points,
        interval_s=interval,
        now=now,
        window_start=window_start,
        previous_t=previous_t,
    ) + unreachable_outages(polls, now=now, window_start=window_start)
    outages = _clip_outages(outages, window_start, now)
    outages.sort(key=lambda item: str(item.get("start") or ""))
    status_points = points or ([{"t": last_ever}] if last_ever else [])
    with _lock:
        meta = dict(_state)
    meta["ok"] = True
    meta["hours"] = hours
    meta["generated_at"] = epoch_to_iso(now)
    meta["window_start"] = since
    meta["points"] = points
    meta["points_stored"] = total
    meta["outages"] = outages
    meta["status"] = host_status(status_points, polls, now=now)
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
        maybe_fetch()
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
    print(
        f"gpc-metrics http://{BIND}:{PORT} source={SOURCE} poll={POLL_S}s",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
