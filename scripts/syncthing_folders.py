#!/usr/bin/env python3
"""Idempotently share emulator save folders on the local Syncthing daemon."""

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
DUSKLIGHT_ID = os.environ.get("SYNCTHING_DUSKLIGHT_FOLDER_ID", "dusklight-saves")
DUSKLIGHT_LABEL = os.environ.get("SYNCTHING_DUSKLIGHT_FOLDER_LABEL", "DusklightSaves")
DUSKLIGHT_PATH = os.environ.get("SYNCTHING_DUSKLIGHT_PATH", "").strip()
CEMU_ID = os.environ.get("SYNCTHING_CEMU_FOLDER_ID", "cemu-saves")
CEMU_LABEL = os.environ.get("SYNCTHING_CEMU_FOLDER_LABEL", "CemuSaves")
CEMU_PATH = os.environ.get("SYNCTHING_CEMU_PATH", "").strip()
PCSX2_ID = os.environ.get("SYNCTHING_PCSX2_FOLDER_ID", "pcsx2-saves")
PCSX2_LABEL = os.environ.get("SYNCTHING_PCSX2_FOLDER_LABEL", "Pcsx2Saves")
PCSX2_PATH = os.environ.get("SYNCTHING_PCSX2_PATH", "").strip()
UNCHARTED_ID = os.environ.get("SYNCTHING_UNCHARTED_FOLDER_ID", "uncharted-saves")
UNCHARTED_LABEL = os.environ.get("SYNCTHING_UNCHARTED_FOLDER_LABEL", "UnchartedSaves")
UNCHARTED_PATH = os.environ.get("SYNCTHING_UNCHARTED_PATH", "").strip()
WWHD_ID = os.environ.get("SYNCTHING_WWHD_FOLDER_ID", "wwhd-saves")
WWHD_LABEL = os.environ.get("SYNCTHING_WWHD_FOLDER_LABEL", "WwhdSaves")
WWHD_PATH = os.environ.get("SYNCTHING_WWHD_PATH", "").strip()
LAB_DEVICE_ID = os.environ.get("SYNCTHING_LAB_DEVICE_ID", "").strip()
LAB_DEVICE_NAME = os.environ.get("SYNCTHING_LAB_DEVICE_NAME", "lab").strip() or "lab"
UNCHARTED_PEER_IDS_RAW = os.environ.get("SYNCTHING_UNCHARTED_PEER_IDS", "").strip()


def parse_id_list(raw: str) -> list[str]:
    text = (raw or "").strip().strip('"').strip("'")
    return [p.strip().strip('"').strip("'") for p in text.split() if p.strip().strip('"').strip("'")]


PEER_IDS = parse_id_list(os.environ.get("SYNCTHING_PEER_IDS", ""))


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


def devices_for_folder(
    existing: list[dict], extra_ids: list[str], local_id: str, exclusive: bool = False
) -> list[dict]:
    if exclusive:
        return merge_devices([], extra_ids, local_id)
    return merge_devices(existing, extra_ids, local_id)


def lookup_device_id(devices: list[dict] | None, name: str) -> str | None:
    want = (name or "").strip().lower()
    if not want:
        return None
    for entry in devices or []:
        got = (entry.get("name") or "").strip().lower()
        if got == want:
            return entry.get("deviceID") or entry.get("deviceId")
    return None


def uncharted_peer_ids(lab_ids: list[str], extra: str = UNCHARTED_PEER_IDS_RAW) -> list[str]:
    override = parse_id_list(extra)
    if override:
        return override
    return [did for did in lab_ids if did]


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


def resolve_lab_id(devices: list[dict] | None) -> str:
    if LAB_DEVICE_ID:
        return LAB_DEVICE_ID
    found = lookup_device_id(devices, LAB_DEVICE_NAME)
    return found or ""


def main() -> int:
    if not AZAHAR_PATH and not EDEN_PATH and not DUSKLIGHT_PATH and not CEMU_PATH and not PCSX2_PATH and not UNCHARTED_PATH and not WWHD_PATH:
        print("No save-folder paths given; nothing to share")
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
    _, st_devices = request(key, "/rest/config/devices")
    lab_id = resolve_lab_id(st_devices or [])

    if EDEN_PATH:
        Path(EDEN_PATH).mkdir(parents=True, exist_ok=True)
        devices = devices_for_folder(by_id.get(EDEN_ID, {}).get("devices") or [], extra, local_id)
        ensure_folder(key, EDEN_ID, EDEN_LABEL, EDEN_PATH, devices)
        by_id[EDEN_ID] = {"devices": devices}

    if AZAHAR_PATH:
        Path(AZAHAR_PATH).mkdir(parents=True, exist_ok=True)
        devices = devices_for_folder(by_id.get(AZAHAR_ID, {}).get("devices") or [], extra, local_id)
        ensure_folder(key, AZAHAR_ID, AZAHAR_LABEL, AZAHAR_PATH, devices)
        by_id[AZAHAR_ID] = {"devices": devices}

    if DUSKLIGHT_PATH:
        Path(DUSKLIGHT_PATH).mkdir(parents=True, exist_ok=True)
        devices = devices_for_folder(by_id.get(DUSKLIGHT_ID, {}).get("devices") or [], extra, local_id)
        ensure_folder(key, DUSKLIGHT_ID, DUSKLIGHT_LABEL, DUSKLIGHT_PATH, devices)
        by_id[DUSKLIGHT_ID] = {"devices": devices}

    if CEMU_PATH:
        Path(CEMU_PATH).mkdir(parents=True, exist_ok=True)
        devices = devices_for_folder(by_id.get(CEMU_ID, {}).get("devices") or [], extra, local_id)
        ensure_folder(key, CEMU_ID, CEMU_LABEL, CEMU_PATH, devices)

    if PCSX2_PATH:
        Path(PCSX2_PATH).mkdir(parents=True, exist_ok=True)
        devices = devices_for_folder(by_id.get(PCSX2_ID, {}).get("devices") or [], extra, local_id)
        ensure_folder(key, PCSX2_ID, PCSX2_LABEL, PCSX2_PATH, devices)

    if UNCHARTED_PATH:
        Path(UNCHARTED_PATH).mkdir(parents=True, exist_ok=True)
        uncharted_ids = uncharted_peer_ids([lab_id] if lab_id else [])
        if not uncharted_ids:
            print(
                "Uncharted PC-port saves present, but no lab Syncthing device "
                f"(name {LAB_DEVICE_NAME!r} or SYNCTHING_LAB_DEVICE_ID). Skipping share."
            )
        else:
            devices = devices_for_folder(
                by_id.get(UNCHARTED_ID, {}).get("devices") or [],
                uncharted_ids,
                local_id,
                exclusive=True,
            )
            ensure_folder(key, UNCHARTED_ID, UNCHARTED_LABEL, UNCHARTED_PATH, devices)
            print("Uncharted PC-port saves are lab-only (not Thor / Odin).")

    if WWHD_PATH:
        Path(WWHD_PATH).mkdir(parents=True, exist_ok=True)
        devices = devices_for_folder(by_id.get(WWHD_ID, {}).get("devices") or [], extra, local_id)
        ensure_folder(key, WWHD_ID, WWHD_LABEL, WWHD_PATH, devices)
        print(
            "Note: Thor/Odin Android ZeldaWWHDRecomp should share the same folder "
            "(Android/data/org.wwhdrecomp.wwhd/files/save). Handheld Autostart is not this playbook."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
