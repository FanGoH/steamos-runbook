#!/usr/bin/env python3
"""Call Tender's firmware backend (same path as the Decky BIOS UI).

Raw urllib to RomM /api/firmware/.../content returns 403; Tender's
FirmwareService uses the stored token, firmware.read scope, and User-Agent.
This talks to the live plugin via PluginLoader (api_version 1):

    loader/call_plugin_method  ["Tender", "download_all_firmware", "<slug>"]

PS2 registry entries are all required=false, so download_required_firmware
downloads nothing. Use download_all_firmware. Never prints the Decky token
or romm_api_token.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import base64
import json
import os
import re
import socket
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request

PREFERRED_PS2_BIOS = "ps2-0230a-20080220.bin"
MIN_PS2_BIOS_BYTES = 4_000_000


def pin_pcsx2_bios(text: str, bios_name: str) -> str:
    new, n = re.subn(r"(?m)^BIOS =.*$", f"BIOS = {bios_name}", text, count=1)
    if n:
        return new
    if "[Filenames]" in text:
        return text.replace("[Filenames]\n", f"[Filenames]\nBIOS = {bios_name}\n", 1)
    return text.rstrip() + f"\n\n[Filenames]\nBIOS = {bios_name}\n"


def pick_ps2_bios(root: Path) -> Path | None:
    """Prefer USA v2.30, then any USA (…a-), then any 4 MiB ps2-*.bin."""
    found: dict[str, Path] = {}
    search = [root]
    nested = root / "pcsx2" / "bios"
    if nested.exists():
        search.append(nested)
    for folder in search:
        if not folder.is_dir():
            continue
        for path in folder.glob("ps2-*.bin"):
            try:
                if path.is_file() and path.stat().st_size >= MIN_PS2_BIOS_BYTES:
                    found[path.name] = path
            except OSError:
                continue
    if PREFERRED_PS2_BIOS in found:
        return found[PREFERRED_PS2_BIOS]
    usa = sorted(name for name in found if re.match(r"ps2-\d+a", name))
    if usa:
        return found[usa[-1]]
    if found:
        return found[sorted(found)[0]]
    return None


def ensure_visible_in_bios_folder(bios_file: Path, bios_dir: Path) -> Path:
    dest = bios_dir / bios_file.name
    if dest.exists():
        return dest
    dest.symlink_to(bios_file.resolve())
    return dest


def _decky_call(
    loader: str,
    plugin: str,
    method: str,
    *method_args: object,
    timeout: int = 90,
) -> object:
    parsed = urllib.parse.urlparse(loader)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with urllib.request.urlopen(loader.rstrip("/") + "/auth/token", timeout=5) as resp:
            token = resp.read().decode("utf-8", errors="replace").strip()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"PluginLoader not answering at {loader}: {exc.__class__.__name__}") from exc
    if not token:
        raise RuntimeError("PluginLoader /auth/token was empty")

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    path = "/ws?" + urllib.parse.urlencode({"auth": token})
    handshake = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    ).encode("ascii")

    sock = socket.create_connection((host, port), timeout=10)
    state = {"leftover": b""}
    try:
        sock.sendall(handshake)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("PluginLoader websocket handshake closed")
            buf += chunk
        header, leftover = buf.split(b"\r\n\r\n", 1)
        state["leftover"] = leftover
        status = header.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        if " 101 " not in status:
            raise RuntimeError(f"PluginLoader websocket handshake failed ({status})")

        def send_text(text: str) -> None:
            payload = text.encode("utf-8")
            n = len(payload)
            hdr = bytearray([0x81])
            if n < 126:
                hdr.append(0x80 | n)
            elif n < 65536:
                hdr.append(0x80 | 126)
                hdr.extend(struct.pack("!H", n))
            else:
                hdr.append(0x80 | 127)
                hdr.extend(struct.pack("!Q", n))
            mask = os.urandom(4)
            masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            sock.sendall(bytes(hdr) + mask + masked)

        def need(n: int) -> bytes:
            leftover = state["leftover"]
            while len(leftover) < n:
                chunk = sock.recv(max(4096, n - len(leftover)))
                if not chunk:
                    raise OSError("ws closed")
                leftover += chunk
            data, leftover = leftover[:n], leftover[n:]
            state["leftover"] = leftover
            return data

        def recv_message() -> dict | None:
            while True:
                header2 = need(2)
                opcode = header2[0] & 0x0F
                masked = bool(header2[1] & 0x80)
                length = header2[1] & 0x7F
                if length == 126:
                    length = struct.unpack("!H", need(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", need(8))[0]
                mask = need(4) if masked else b""
                payload = need(length)
                if masked:
                    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                if opcode == 0x8:
                    return None
                if opcode == 0x9:
                    pmask = os.urandom(4)
                    masked_payload = bytes(b ^ pmask[i % 4] for i, b in enumerate(payload))
                    sock.sendall(bytes([0x8A, 0x80 | len(payload)]) + pmask + masked_payload)
                    continue
                if opcode != 0x1:
                    continue
                return json.loads(payload.decode("utf-8"))

        call_id = 1
        sock.settimeout(timeout)
        send_text(
            json.dumps(
                {
                    "type": 0,
                    "id": call_id,
                    "route": "loader/call_plugin_method",
                    "args": [plugin, method, *method_args],
                }
            )
        )
        msg = recv_message()
        try:
            sock.sendall(bytes([0x88, 0x80]) + os.urandom(4))
        except OSError:
            pass
    finally:
        try:
            sock.close()
        except OSError:
            pass

    if not msg:
        raise RuntimeError(f"PluginLoader closed before {plugin}.{method} replied")
    if msg.get("id") != call_id:
        raise RuntimeError("PluginLoader reply id mismatch")
    if msg.get("type") == -1:
        err = (msg.get("error") or {}).get("message") or "unknown error"
        raise RuntimeError(f"Decky {plugin}.{method} failed: {err}")
    if msg.get("type") != 1:
        raise RuntimeError(f"Unexpected PluginLoader message type {msg.get('type')}")
    return msg.get("result")


def download_all_firmware(
    platform_slug: str,
    *,
    loader: str,
    plugin: str,
    timeout: int,
) -> dict:
    result = _decky_call(loader, plugin, "download_all_firmware", platform_slug, timeout=timeout)
    if not isinstance(result, dict):
        raise RuntimeError(f"Tender.download_all_firmware returned {type(result).__name__}")
    return result


def self_test() -> None:
    sample = "[Filenames]\nBIOS = \n\n[Framerate]\n"
    out = pin_pcsx2_bios(sample, PREFERRED_PS2_BIOS)
    assert f"BIOS = {PREFERRED_PS2_BIOS}\n" in out
    assert out.count("BIOS =") == 1
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scph1001.bin").write_bytes(b"ps1")
        assert pick_ps2_bios(root) is None
        dest = root / "pcsx2" / "bios"
        dest.mkdir(parents=True)
        usa = dest / PREFERRED_PS2_BIOS
        usa.write_bytes(b"x" * MIN_PS2_BIOS_BYTES)
        (dest / "ps2-0100j-20000117.bin").write_bytes(b"y" * MIN_PS2_BIOS_BYTES)
        picked = pick_ps2_bios(root)
        assert picked is not None and picked.name == PREFERRED_PS2_BIOS
        visible = ensure_visible_in_bios_folder(picked, root)
        assert visible == root / PREFERRED_PS2_BIOS
        assert visible.is_symlink() or visible.is_file()
    print("ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--download", metavar="SLUG", help="Tender download_all_firmware(slug)")
    parser.add_argument("--pin-pcsx2", action="store_true", help="Set PCSX2.ini BIOS to USA 230")
    parser.add_argument(
        "--loader",
        default=os.environ.get("DECKY_LOADER_URL", "http://127.0.0.1:1337"),
    )
    parser.add_argument(
        "--plugin",
        default=os.environ.get("TENDER_PLUGIN_NAME", "Tender"),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("TENDER_FIRMWARE_TIMEOUT", "900")),
    )
    parser.add_argument(
        "--bios-dir",
        default=os.environ.get("RETRODECK_BIOS_DIR", "/home/deck/retrodeck/bios"),
    )
    parser.add_argument(
        "--pcsx2-ini",
        default=os.environ.get(
            "PCSX2_INI",
            "/home/deck/.var/app/net.retrodeck.retrodeck/config/PCSX2/inis/PCSX2.ini",
        ),
    )
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    if args.download:
        try:
            result = download_all_firmware(
                args.download,
                loader=args.loader,
                plugin=args.plugin,
                timeout=args.timeout,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        downloaded = result.get("downloaded")
        message = result.get("message") or ""
        ok = bool(result.get("success"))
        print(f"Tender.download_all_firmware({args.download}): downloaded={downloaded} {message}")
        if not ok:
            return 2

    if args.pin_pcsx2:
        bios_dir = Path(args.bios_dir)
        picked = pick_ps2_bios(bios_dir)
        if picked is None:
            print(f"No PS2 BIOS under {bios_dir}", file=sys.stderr)
            return 2
        visible = ensure_visible_in_bios_folder(picked, bios_dir)
        ini = Path(args.pcsx2_ini)
        if not ini.is_file():
            print(f"No {ini}", file=sys.stderr)
            return 2
        text = ini.read_text()
        new = pin_pcsx2_bios(text, visible.name)
        if new != text:
            ini.write_text(new)
            print(f"Pinned PCSX2 BIOS = {visible.name} in {ini}")
        else:
            print(f"PCSX2 BIOS already {visible.name} in {ini}")
        return 0

    if not args.download:
        parser.print_usage(sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
