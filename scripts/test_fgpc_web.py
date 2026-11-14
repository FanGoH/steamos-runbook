#!/usr/bin/env python3
"""Offline tests for the fgpc phone WebGUI (no kms start, no hide)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "fgpc" / "src"
sys.path.insert(0, str(SRC))

from fgpc.api import self_test  # noqa: E402
from fgpc.catalog import WEB_GROUPS  # noqa: E402
from fgpc.web import handle_request, listen_hosts, static_root  # noqa: E402


def _json(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    raw = b"" if body is None else json.dumps(body).encode()
    status, payload, ctype = handle_request(method, path, raw, live=False)
    assert "json" in ctype
    return status, json.loads(payload.decode())


def test_api_self_test() -> None:
    data = self_test()
    assert data.get("ok") is True, data
    assert list(data.get("qam") or [])


def test_healthz() -> None:
    status, data = _json("GET", "/healthz")
    assert status == 200
    assert data["ok"] is True
    assert data["service"] == "fgpc-web"


def test_status_catalog() -> None:
    status, data = _json("GET", "/api/status?live=0")
    assert status == 200
    assert data["ok"] is True
    assert data["web"] == list(WEB_GROUPS)
    assert "stream" in data["help"]
    assert data["tips"]


def test_index() -> None:
    status, body, ctype = handle_request("GET", "/", live=False)
    assert status == 200
    assert "text/html" in ctype
    text = body.decode()
    assert "FGPC" in text
    assert "/app.js" in text
    assert "/app.css" in text


def test_static_files() -> None:
    root = static_root()
    assert (root / "index.html").is_file()
    assert (root / "app.css").is_file()
    assert (root / "app.js").is_file()
    status, body, ctype = handle_request("GET", "/app.js", live=False)
    assert status == 200
    assert "javascript" in ctype
    assert b"Start kms" in body
    assert b"bootstrap" not in body.lower()


def test_refuse_host_mode_force() -> None:
    status, data = _json("POST", "/api/run", {"group": "host", "action": "bootstrap"})
    assert status == 400
    assert data["ok"] is False
    assert "SSH-only" in data["message"]

    status, data = _json("POST", "/api/run", {"group": "mode", "action": "game"})
    assert status == 400
    assert data["ok"] is False

    status, data = _json(
        "POST",
        "/api/run",
        {"group": "hide", "action": "off", "pad_id": "usb:0000:0000:nope", "force": True},
    )
    assert status == 400
    assert data["ok"] is False
    assert "force" in data["message"].lower()

    status, data = _json("POST", "/api/run", {"group": "stream", "action": "start"})
    assert status == 400
    assert data["ok"] is False


def test_moonlight_pad_profile() -> None:
    status, data = _json("GET", "/api/moonlight/pad-profile")
    assert status == 200
    assert data["ok"] is True
    assert data["profile"] in ("x360", "ds5", "ds4", "switch")
    assert data["li_ctype"] in (1, 2, 3)
    assert data["session"] in ("gamemode", "desktop", "unknown")



def test_listen_hosts_lan() -> None:
    os.environ["FGPC_WEB_BIND"] = "127.0.0.1,192.0.2.8"
    try:
        assert listen_hosts() == ["127.0.0.1", "192.0.2.8"]
    finally:
        os.environ.pop("FGPC_WEB_BIND", None)
    os.environ.pop("FGPC_WEB_BIND", None)
    os.environ["FGPC_WEB_TAILNET_IP"] = "100.64.0.8"
    os.environ["FGPC_WEB_LAN_IP"] = "192.0.2.65"
    try:
        hosts = listen_hosts()
        assert hosts[0] == "127.0.0.1"
        assert "100.64.0.8" in hosts
        assert "192.0.2.65" in hosts
    finally:
        os.environ.pop("FGPC_WEB_TAILNET_IP", None)
        os.environ.pop("FGPC_WEB_LAN_IP", None)


def test_unknown_route() -> None:
    status, data = _json("GET", "/api/nope")
    assert status == 404
    assert data["ok"] is False


def main() -> int:
    os.environ.setdefault("STEAMOS_PLAYBOOK_DIR", str(ROOT))
    tests = [
        test_api_self_test,
        test_healthz,
        test_status_catalog,
        test_index,
        test_static_files,
        test_refuse_host_mode_force,
        test_moonlight_pad_profile,
        test_listen_hosts_lan,
        test_unknown_route,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"ok  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001 — show the failing test
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    if failed:
        print(f"{failed}/{len(tests)} failed")
        return 1
    print(f"{len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
