#!/usr/bin/env python3
"""Request OpenRGB to rescan devices (same action as UI "Rescan devices").

OpenRGB has no `--rescan` CLI flag. Rescan is exposed only via the native
OpenRGB SDK on TCP port 6742 (not HTTP) — the same channel the GUI uses.

Protocol: https://gitlab.com/CalcProgrammer1/OpenRGB/-/blob/master/Documentation/OpenRGBSDK.md
Uses only the Python stdlib.
"""
from __future__ import annotations

import argparse
import socket
import struct
import sys
import time

MAGIC = b"ORGB"
PKT_REQUEST_PROTOCOL_VERSION = 40
PKT_SET_CLIENT_NAME = 50
PKT_REQUEST_RESCAN_DEVICES = 140
PKT_LOAD_PROFILE = 152


def header(dev_id: int, pkt_id: int, size: int) -> bytes:
    return MAGIC + struct.pack("<III", dev_id, pkt_id, size)


def send_packet(sock: socket.socket, pkt_id: int, payload: bytes = b"", dev_id: int = 0) -> None:
    sock.sendall(header(dev_id, pkt_id, len(payload)) + payload)


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed while reading")
        buf += chunk
    return buf


def drain_briefly(sock: socket.socket, seconds: float = 0.3) -> None:
    sock.settimeout(seconds)
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
    except socket.timeout:
        pass
    finally:
        sock.settimeout(5.0)


def negotiate(sock: socket.socket, client_version: int = 5) -> int:
    send_packet(sock, PKT_REQUEST_PROTOCOL_VERSION, struct.pack("<I", client_version))
    sock.settimeout(2.0)
    try:
        hdr = recv_exact(sock, 16)
        magic, _dev, pkt_id, size = struct.unpack_from("<4sIII", hdr)
        if magic != MAGIC or pkt_id != PKT_REQUEST_PROTOCOL_VERSION or size != 4:
            return 0
        (server_version,) = struct.unpack("<I", recv_exact(sock, 4))
        return int(server_version)
    except (socket.timeout, ConnectionError, struct.error):
        return 0
    finally:
        sock.settimeout(5.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenRGB SDK rescan helper")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6742)
    parser.add_argument("--profile", default="", help="Optional profile to load after rescan")
    parser.add_argument("--wait", type=float, default=2.0, help="Seconds to wait after rescan")
    args = parser.parse_args()

    last_err: Exception | None = None
    for attempt in range(1, 16):
        try:
            with socket.create_connection((args.host, args.port), timeout=2.0) as sock:
                sock.settimeout(5.0)
                version = negotiate(sock)
                if version < 5 and version != 0:
                    print(f"OpenRGB protocol {version} may not support rescan (need >= 5).", file=sys.stderr)
                name = b"steamos-playbook\0"
                send_packet(sock, PKT_SET_CLIENT_NAME, name)
                send_packet(sock, PKT_REQUEST_RESCAN_DEVICES)
                print(f"Requested OpenRGB device rescan on {args.host}:{args.port} (protocol~{version}).")
                time.sleep(args.wait)
                drain_briefly(sock, 0.5)
                if args.profile:
                    payload = args.profile.encode("utf-8") + b"\0"
                    send_packet(sock, PKT_LOAD_PROFILE, payload)
                    print(f"Requested load profile: {args.profile}")
                    time.sleep(0.5)
                    drain_briefly(sock, 0.5)
                return 0
        except OSError as exc:
            last_err = exc
            time.sleep(0.5)

    print(f"Could not reach OpenRGB SDK at {args.host}:{args.port}: {last_err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
