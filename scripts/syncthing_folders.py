#!/usr/bin/env python3
"""Idempotently share Eden/Azahar save folders on the local Syncthing daemon."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

GUI = os.environ.get("SYNCTHING_GUI", "127.0.0.1:8384")
CONFIG = Path(
    os.environ.get(
        "SYNCTHING_CONFIG",
        os.path.expanduser("~/.local/state/syncthing/config.xml"),
    )
)
EDEN_ID = os.environ.get("SYNCTHING_EDEN_FOLDER_ID", "eden-saves")
AZAHAR_ID = os.environ.get("SYNCTHING_AZAHAR_FOLDER_ID", "azahar-saves")
EDEN_LABEL = os.environ.get("SYNCTHING_EDEN_FOLDER_LABEL", "EdenSaves")
AZAHAR_LABEL = os.environ.get("SYNCTHING_AZAHAR_FOLDER_LABEL", "AzaharSaves")
EDEN_PATH = os.environ.get("SYNCTHING_EDEN_PATH", "").strip()
AZAHAR_PATH = os.environ.get("SYNCTHING_AZAHAR_PATH", "").strip()
PEER_IDS = [
    p.strip()
    for p in os.environ.get("SYNCTHING_PEER_IDS", "").split()
    if p.strip()
]


def api_key() -> str:
    if not CONFIG.is_file():
        raise SystemExit(f"Syncthing config missing: {CONFIG}")
    root = ET.parse(CONFIG).getroot()
    gui = root.find("gui")
    if gui is None or not gui.findtext("apikey"):
        raise SystemExit("Syncthing config has no GUI API key")
    return gui.findtext("apikey") or ""


def request(key: str, path: str, method: str = "GET", data=None):
    url = f"http://{GUI}{path}"
    headers = {"X-API-Key": key}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


def wait_ready(key: str, tries: int = 30) -> None:
    last = None
    for _ in range(tries):
        try:
            request(key, "/rest/system/ping")
            return
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(1)
    raise SystemExit(f"Syncthing GUI not ready at {GUI}: {last}")


def device_entry(device_id: str) -> dict:
    return {
        "deviceID": device_id,
        "introducedBy": "",
        "encryptionPassword": "",
    }


def empty_versioning() -> dict:
    return {
        "type": "",
        "params": {},
        "cleanupIntervalS": 3600,
        "fsPath": "",
        "fsType": "basic",
    }


def folder_template(folder_id: str, label: str, path: str, devices: list[dict], existing: dict | None) -> dict:
    folder = dict(existing) if existing else {}
    folder.update(
        {
            "id": folder_id,
            "label": label,
            "path": path,
            "type": "sendreceive",
            "paused": False,
            "ignorePerms": True,
            "caseSensitiveFS": False,
            "rescanIntervalS": int(folder.get("rescanIntervalS") or 60),
            "fsWatcherEnabled": True,
            "devices": devices,
        }
    )
    folder.setdefault("versioning", empty_versioning())
    folder.setdefault("filesystemType", "basic")
    folder.setdefault("markerName", ".stfolder")
    return folder


def merge_devices(existing: list[dict], extra_ids: list[str], local_id: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for entry in existing:
        did = entry.get("deviceID") or entry.get("deviceId")
        if did:
            seen[did] = device_entry(did)
    for did in extra_ids:
        seen[did] = device_entry(did)
    seen[local_id] = device_entry(local_id)
    return list(seen.values())


def ensure_peer_devices(key: str, peer_ids: list[str], local_id: str) -> None:
    status, devices = request(key, "/rest/config/devices")
    known = {d.get("deviceID") for d in (devices or [])}
    for did in peer_ids:
        if did == local_id or did in known:
            continue
        payload = {
            "deviceID": did,
            "name": "",
            "addresses": ["dynamic"],
            "compression": "metadata",
            "introducer": False,
            "paused": False,
            "autoAcceptFolders": False,
        }
        request(key, f"/rest/config/devices/{did}", method="PUT", data=payload)
        print(f"Added Syncthing device {did}")
        known.add(did)


def ensure_folder(key: str, folder_id: str, label: str, path: str, devices: list[dict]) -> None:
    existing = None
    try:
        _, existing = request(key, f"/rest/config/folders/{folder_id}")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    folder = folder_template(folder_id, label, path, devices, existing)
    same = (
        existing
        and existing.get("path") == path
        and existing.get("label") == label
        and existing.get("ignorePerms") is True
        and existing.get("caseSensitiveFS") is False
        and existing.get("paused") is False
        and {d.get("deviceID") for d in existing.get("devices") or []}
        == {d["deviceID"] for d in devices}
    )
    if same:
        print(f"Folder {folder_id} already OK at {path}")
        return
    request(key, f"/rest/config/folders/{folder_id}", method="PUT", data=folder)
    print(f"Upserted folder {folder_id} -> {path}")


def ensure_gui_listen(key: str, wanted: str) -> None:
    _, gui = request(key, "/rest/config/gui")
    if not gui:
        return
    if gui.get("address") == wanted:
        return
    gui["address"] = wanted
    request(key, "/rest/config/gui", method="PUT", data=gui)
    print(f"Bound Syncthing GUI to {wanted}")


def main() -> int:
    if not AZAHAR_PATH and not EDEN_PATH:
        print("No Eden/Azahar paths given; nothing to share")
        return 0
    key = api_key()
    wait_ready(key)
    _, status = request(key, "/rest/system/status")
    local_id = (status or {}).get("myID")
    if not local_id:
        raise SystemExit("Could not read local Syncthing device ID")
    ensure_gui_listen(key, GUI)
    ensure_peer_devices(key, PEER_IDS, local_id)

    _, folders = request(key, "/rest/config/folders")
    by_id = {f.get("id"): f for f in (folders or [])}
    extra = list(PEER_IDS)

    if EDEN_PATH:
        Path(EDEN_PATH).mkdir(parents=True, exist_ok=True)
        devices = merge_devices(by_id.get(EDEN_ID, {}).get("devices") or [], extra, local_id)
        ensure_folder(key, EDEN_ID, EDEN_LABEL, EDEN_PATH, devices)
        by_id[EDEN_ID] = {"devices": devices}

    if AZAHAR_PATH:
        Path(AZAHAR_PATH).mkdir(parents=True, exist_ok=True)
        devices = merge_devices(by_id.get(AZAHAR_ID, {}).get("devices") or [], extra, local_id)
        ensure_folder(key, AZAHAR_ID, AZAHAR_LABEL, AZAHAR_PATH, devices)

    return 0


if __name__ == "__main__":
    sys.exit(main())
