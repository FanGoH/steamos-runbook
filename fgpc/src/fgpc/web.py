"""Phone WebGUI for the fgpc catalog. Stdlib HTTP only.

Same refuse list as Decky / fgpc-api: no host, mode, bootstrap, or hide --force.
Does not reimplement hide/bind/stream — every action goes through ``fgpc.api``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fgpc.api import dump, run_action, self_test
from fgpc.catalog import WEB_GROUPS
from fgpc.playbook import playbook_root

STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".webmanifest": "application/manifest+json",
}


def static_root() -> Path:
    env = os.environ.get("FGPC_WEB_STATIC")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "web"


def default_port() -> int:
    raw = (os.environ.get("FGPC_WEB_PORT") or "8484").strip()
    try:
        return int(raw)
    except ValueError:
        return 8484


def tailnet_ipv4() -> str:
    env = (os.environ.get("FGPC_WEB_TAILNET_IP") or "").strip()
    if env:
        return env
    bin_path = os.environ.get("TAILSCALE_BIN") or "tailscale"
    try:
        proc = subprocess.run(
            [bin_path, "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").splitlines()[0].strip()


def listen_hosts() -> list[str]:
    raw = (os.environ.get("FGPC_WEB_BIND") or "").strip()
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    hosts = ["127.0.0.1"]
    ip = tailnet_ipv4()
    if ip and ip not in hosts:
        hosts.append(ip)
    return hosts


def _json_bytes(data: object, status: int = 200) -> tuple[int, bytes, str]:
    payload = json.dumps(data, indent=None).encode("utf-8")
    return status, payload, "application/json; charset=utf-8"


def handle_request(
    method: str,
    path: str,
    body: bytes = b"",
    *,
    live: bool = True,
) -> tuple[int, bytes, str]:
    """Pure request handler for tests and the HTTP server."""
    parsed = urlparse(path)
    route = parsed.path or "/"
    method = method.upper()

    if method == "GET" and route in ("/healthz", "/api/health"):
        return _json_bytes({"ok": True, "service": "fgpc-web"})
    if method == "GET" and route == "/api/self-test":
        data = self_test()
        return _json_bytes(data, 200 if data.get("ok") else 500)
    if method == "GET" and route == "/api/status":
        query = parse_qs(parsed.query)
        want_live = live
        if query.get("live", [""])[0] in ("0", "false", "no"):
            want_live = False
        data = dump(live=want_live)
        data.setdefault("web", list(WEB_GROUPS))
        return _json_bytes(data)
    if method == "POST" and route == "/api/run":
        if not body:
            return _json_bytes({"ok": False, "message": "Empty body"}, 400)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _json_bytes({"ok": False, "message": "Invalid JSON"}, 400)
        if not isinstance(payload, dict):
            return _json_bytes({"ok": False, "message": "JSON object required"}, 400)
        data = run_action(
            str(payload.get("group") or ""),
            str(payload.get("action") or ""),
            pad_id=str(payload.get("pad_id") or payload.get("id") or ""),
            mode=str(payload.get("mode") or ""),
            emu=str(payload.get("emu") or "all"),
            display=str(payload.get("display") or ""),
            window_id=str(
                payload.get("window_id")
                or payload.get("pad_id")
                or payload.get("id")
                or ""
            ),
            target=str(payload.get("target") or ""),
            hidden=payload.get("hidden"),
            force=payload.get("force"),
        )
        status = 200 if data.get("ok") is not False else 400
        return _json_bytes(data, status)
    if method in ("GET", "HEAD") and not route.startswith("/api/"):
        return _static(route)
    return _json_bytes({"ok": False, "message": f"unknown {method} {route}"}, 404)


def _static(route: str) -> tuple[int, bytes, str]:
    rel = "index.html" if route in ("/", "/index.html") else route.lstrip("/")
    if ".." in rel or rel.startswith("/"):
        return _json_bytes({"ok": False, "message": "bad path"}, 400)
    root = static_root().resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return _json_bytes({"ok": False, "message": "bad path"}, 400)
    if not path.is_file():
        return _missing_static(rel)
    data = path.read_bytes()
    ctype = STATIC_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return 200, data, ctype


def _missing_static(rel: str) -> tuple[int, bytes, str]:
    return _json_bytes({"ok": False, "message": f"missing {rel}"}, 404)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        status, body, ctype = handle_request("GET", self.path)
        self._send(status, body, ctype)

    def do_HEAD(self) -> None:  # noqa: N802
        status, body, ctype = handle_request("HEAD", self.path)
        self._send(status, body, ctype)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or "0")
        if length > 16_384:
            self._send(*_json_bytes({"ok": False, "message": "body too large"}, 413))
            return
        body = self.rfile.read(length) if length else b""
        status, payload, ctype = handle_request("POST", self.path, body)
        self._send(status, payload, ctype)


def _serve(host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def serve(hosts: list[str] | None = None, port: int | None = None) -> None:
    port = default_port() if port is None else port
    hosts = listen_hosts() if hosts is None else hosts
    if not hosts:
        hosts = ["127.0.0.1"]
    servers = [_serve(hosts[0], port)]
    threads: list[threading.Thread] = []
    for host in hosts[1:]:
        extra = _serve(host, port)
        servers.append(extra)
        thread = threading.Thread(target=extra.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    print(
        f"fgpc-web on {', '.join(f'http://{h}:{port}' for h in hosts)} "
        f"(playbook {playbook_root()})",
        flush=True,
    )
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers:
            server.shutdown()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("--self-test", "self-test"):
        data = self_test()
        print(json.dumps(data))
        return 0 if data.get("ok") else 1
    if args and args[0] in ("--print-bind", "print-bind"):
        print(json.dumps({"hosts": listen_hosts(), "port": default_port()}))
        return 0
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
