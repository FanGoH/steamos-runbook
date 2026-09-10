#!/usr/bin/env python3
"""Play a Steam shortcut the same way Tender's handlePlay does.

steam://rungameid is accepted for the 64-bit non-Steam GameID but does not
run LaunchGameAction, so gamescope stays FOCUSED_APP=769 and Cemu stays a
10x10 InputOnly stub. Tender/QuickLaunch call SteamClient.Apps.RunGame
inside SharedJSContext. Game Mode steamwebhelper already listens on
127.0.0.1:8080 (--remote-debugging-port).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import urllib.error
import urllib.request

DEFAULT_APPID = os.environ.get("CEMU_STEAM_APPID", "2374129079")
DEFAULT_GAMEID = os.environ.get(
    "CEMU_STEAM_GAMEID",
    str((int(DEFAULT_APPID) << 32) | 0x02000000),
)
DEFAULT_CDP = os.environ.get("STEAM_CDP", "http://127.0.0.1:8080")


def list_targets(cdp: str) -> list[dict]:
    with urllib.request.urlopen(cdp.rstrip("/") + "/json", timeout=3) as resp:
        data = json.load(resp)
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected CDP /json: {type(data).__name__}")
    return data


def pick_shared_js(pages: list[dict]) -> dict | None:
    for page in pages:
        title = str(page.get("title") or "")
        url = str(page.get("url") or "")
        if title == "SharedJSContext" or "steamloopback.host" in url:
            return page
    for page in pages:
        if "Big Picture" in str(page.get("title") or ""):
            return page
    return None


def _ws_key() -> str:
    return base64.b64encode(os.urandom(16)).decode("ascii")


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("CDP websocket closed")
        buf += chunk
    return buf


def _read_ws_text(sock: socket.socket) -> str:
    while True:
        header = _recv_exact(sock, 2)
        opcode = header[0] & 0x0F
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", _recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
        payload = _recv_exact(sock, length)
        if opcode == 0x1:
            return payload.decode("utf-8")
        if opcode == 0x8:
            raise ConnectionError("CDP websocket close")
        # ping/pong/binary — ignore


def _send_ws_text(sock: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    header = bytearray([0x81])
    n = len(payload)
    mask = os.urandom(4)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", n))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", n))
    header.extend(mask)
    sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))


def ws_connect(ws_url: str) -> socket.socket:
    if not ws_url.startswith("ws://"):
        raise ValueError(f"only ws:// CDP is supported: {ws_url}")
    rest = ws_url[5:]
    hostport, _, path = rest.partition("/")
    host, _, port_s = hostport.partition(":")
    port = int(port_s or "80")
    path = "/" + path
    sock = socket.create_connection((host, port), timeout=8)
    key = _ws_key()
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(req.encode("ascii"))
    header = b""
    while b"\r\n\r\n" not in header:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("CDP HTTP upgrade failed")
        header += chunk
    if b" 101 " not in header.split(b"\r\n", 1)[0]:
        raise ConnectionError(header.split(b"\r\n", 1)[0].decode("ascii", "replace"))
    expect = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    )
    if expect not in header:
        raise ConnectionError("CDP websocket accept mismatch")
    leftover = header.split(b"\r\n\r\n", 1)[1]
    if leftover:
        raise ConnectionError("unexpected CDP data after upgrade")
    return sock


def runtime_evaluate(ws_url: str, expression: str) -> dict:
    sock = ws_connect(ws_url)
    try:
        _send_ws_text(
            sock,
            json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "awaitPromise": False,
                        "returnByValue": True,
                    },
                }
            ),
        )
        while True:
            msg = json.loads(_read_ws_text(sock))
            if msg.get("id") == 1:
                return msg
    finally:
        sock.close()


def run_game(gameid: str, cdp: str = DEFAULT_CDP) -> int:
    pages = list_targets(cdp)
    page = pick_shared_js(pages)
    if page is None:
        print("No Steam SharedJSContext CDP target.", file=sys.stderr)
        return 2
    ws = page.get("webSocketDebuggerUrl") or ""
    expr = f'SteamClient.Apps.RunGame("{gameid}", "", -1, 100)'
    result = runtime_evaluate(ws, expr)
    if result.get("error"):
        print(f"CDP error: {result['error']}", file=sys.stderr)
        return 1
    value = (result.get("result") or {}).get("result") or {}
    if value.get("subtype") == "error" or value.get("className") == "Error":
        print(f"RunGame threw: {value}", file=sys.stderr)
        return 1
    print(f"SteamClient.Apps.RunGame({gameid}) via {page.get('title')}")
    return 0


def _self_test() -> int:
    pages = [
        {"title": "QuickAccess_uid2", "url": "about:blank"},
        {
            "title": "SharedJSContext",
            "url": "https://steamloopback.host/routes/library/app/2374129079",
        },
    ]
    picked = pick_shared_js(pages)
    assert picked is not None
    assert picked["title"] == "SharedJSContext"
    bpm = pick_shared_js([{"title": "Steam Big Picture Mode", "url": "about:blank"}])
    assert bpm is not None and "Big Picture" in bpm["title"]
    print("steam-run-shortcut self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gameid", default=DEFAULT_GAMEID, help="64-bit shortcut GameID")
    parser.add_argument("--cdp", default=DEFAULT_CDP)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    try:
        return run_game(args.gameid, args.cdp)
    except (urllib.error.URLError, OSError, ConnectionError, TimeoutError) as exc:
        print(f"Steam CDP unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
