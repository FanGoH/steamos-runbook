#!/usr/bin/env python3
"""Hide host gamepads from Steam/games without unplugging them.

Kernel USB ``authorized=0`` (or HID unbind) drops the ``/dev/input`` nodes.
The cable and Bluetooth pairing stay. JSON on stdout is the API for Decky,
SSH, and a later web wrapper.

The pad currently driving Steam/QAM (last press/stick) cannot hide itself
unless ``--force``. Virtual pads (Sunshine, Steam wrap, EmuPads) have no
USB/HID target and are listed but not hideable.

Examples:
  python3 scripts/hide-controllers.py list
  python3 scripts/hide-controllers.py hide --id usb:045e:028e:5F19FC0A
  python3 scripts/hide-controllers.py show --id usb:045e:028e:5F19FC0A
  python3 scripts/hide-controllers.py apply
"""
from __future__ import annotations

import argparse
import json
import os
import re
import select
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

INPUT_ROOT = Path(os.environ.get("PAD_HIDE_INPUT_ROOT", "/sys/class/input"))
USB_ROOT = Path(os.environ.get("PAD_HIDE_USB_ROOT", "/sys/bus/usb/devices"))
HID_ROOT = Path(os.environ.get("PAD_HIDE_HID_ROOT", "/sys/bus/hid/devices"))
SKIP_VENDORS = {"0000", "001f", "26ce", "046d", "beef"}
SKIP_PRODUCTS = {("1209", "0003")}  # libvirtualhid Mouse
SINK_VENDOR = "1209"
SINK_PRODUCTS = ("e301", "e302")
SINK_NAMES = ("EmuPads P1", "EmuPads P2")
STEAM_VIRTUAL = ("28de", "11ff")
USB_DEV_RE = re.compile(r"^[0-9]+-[0-9]+(?:\.[0-9]+)*$")
HID_RE = re.compile(
    r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}$"
)
EV_KEY = 1
EV_ABS = 3
_STICK_ABS = {0x00, 0x01, 0x03, 0x04}  # X Y RX RY
INPUT_EVENT_FMT = "llHHi"
INPUT_EVENT_SIZE = struct.calcsize(INPUT_EVENT_FMT)
HELPER_NAME = "hide-controllers-sysfs.sh"


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def playbook_root() -> Path:
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    here = Path(__file__).resolve().parent.parent
    home = Path(os.environ.get("HOME") or "/home/deck")
    for cand in (
        Path(env) if env else None,
        here,
        home / "steamos-playbook",
        home / "homebrew" / "data" / "PadHide",
    ):
        if cand is None:
            continue
        if (cand / "scripts" / "hide-controllers.py").is_file():
            return cand
    return here


def helper_path() -> Path:
    env = os.environ.get("PAD_HIDE_HELPER")
    if env:
        return Path(env)
    return playbook_root() / "scripts" / HELPER_NAME


def config_path() -> Path:
    env = os.environ.get("PAD_HIDE_CONFIG")
    if env:
        return Path(env)
    home = os.environ.get("PAD_HIDE_HOME") or os.environ.get("HOME")
    if os.geteuid() == 0 and not os.environ.get("PAD_HIDE_HOME"):
        if not home or home in ("/", "/root"):
            home = "/home/deck"
    return Path(home or "/home/deck") / ".config" / "pad-hide" / "hidden.json"


def deck_uid_gid() -> tuple[int, int]:
    try:
        st = os.stat("/home/deck")
        return st.st_uid, st.st_gid
    except OSError:
        return 1000, 1000


def load_hidden(path: Path | None = None) -> list[dict]:
    dest = path or config_path()
    if not dest.is_file():
        return []
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        rows = data.get("hidden") or []
    elif isinstance(data, list):
        rows = data
    else:
        return []
    out: list[dict] = []
    for row in rows:
        if isinstance(row, dict) and row.get("id"):
            out.append(dict(row))
    return out


def write_hidden(rows: list[dict], path: Path | None = None) -> Path:
    dest = path or config_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "hidden": rows}
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if os.geteuid() == 0:
        uid, gid = deck_uid_gid()
        try:
            os.chown(dest, uid, gid)
            os.chown(dest.parent, uid, gid)
        except OSError:
            pass
    return dest


def usb_busid_from_path(path: Path | str) -> str | None:
    found = None
    for part in Path(path).parts:
        if USB_DEV_RE.fullmatch(part):
            found = part
    return found


def hid_id_from_path(path: Path | str) -> str | None:
    found = None
    for part in Path(path).parts:
        if HID_RE.fullmatch(part):
            found = part
    return found


def is_usb_hub(busid: str, usb_root: Path = USB_ROOT) -> bool:
    dev = usb_root / busid
    klass = _read(dev / "bDeviceClass").lower()
    vendor = _read(dev / "idVendor").lower().zfill(4)[-4:]
    return klass == "09" or vendor == "1d6b"


def is_steam_virtual(pad: dict) -> bool:
    return (pad.get("vendor"), pad.get("product")) == STEAM_VIRTUAL


def is_sink(pad: dict) -> bool:
    name = str(pad.get("name") or "")
    if name in SINK_NAMES or name.startswith("EmuPads P"):
        return True
    return pad.get("vendor") == SINK_VENDOR and pad.get("product") in SINK_PRODUCTS


def is_skipped(pad: dict) -> bool:
    vendor = str(pad.get("vendor") or "")
    product = str(pad.get("product") or "")
    name = str(pad.get("name") or "")
    if vendor in SKIP_VENDORS:
        return True
    if (vendor, product) in SKIP_PRODUCTS:
        return True
    if is_sink(pad):
        return True
    low = name.lower()
    if "mouse" in low or "led controller" in low:
        return True
    return False


def pad_kind(pad: dict) -> str:
    name = str(pad.get("name") or "")
    if "sunshine" in name.lower() or "libvirtualhid" in name.lower():
        return "Sunshine"
    if is_steam_virtual(pad):
        return "Steam virtual"
    vendor = str(pad.get("vendor") or "").lower()
    if vendor == "045e":
        return "Xbox"
    if vendor == "057e":
        return "Switch"
    if vendor == "054c":
        return "PlayStation"
    return "Pad"


def event_node(js_device: Path) -> str:
    for child in js_device.iterdir() if js_device.is_dir() else []:
        if child.name.startswith("event"):
            node = Path("/dev/input") / child.name
            if node.exists() or os.environ.get("PAD_HIDE_INPUT_ROOT"):
                return str(node)
    return ""


def resolve_sys_device(js_device: Path) -> Path:
    try:
        return js_device.resolve()
    except OSError:
        return js_device


def target_for_device(sys_device: Path) -> dict:
    """Pick USB authorized (preferred) or HID unbind for this input node."""
    busid = usb_busid_from_path(sys_device)
    if busid and not is_usb_hub(busid):
        usb = USB_ROOT / busid
        if (usb / "authorized").is_file() or os.environ.get("PAD_HIDE_ALLOW_MISSING_SYSFS"):
            serial = _read(usb / "serial") or _read(sys_device / "uniq")
            return {
                "method": "usb-authorized",
                "usb": busid,
                "serial": serial,
            }
    hid = hid_id_from_path(sys_device)
    if hid:
        hid_dir = HID_ROOT / hid
        driver = ""
        drv = hid_dir / "driver"
        if drv.exists():
            try:
                driver = Path(os.path.realpath(drv)).name
            except OSError:
                driver = ""
        serial = _read(hid_dir / "uniq") or _read(sys_device / "uniq")
        if (hid_dir / "authorized").is_file():
            return {
                "method": "hid-authorized",
                "hid": hid,
                "hid_driver": driver,
                "serial": serial,
            }
        return {
            "method": "hid-unbind",
            "hid": hid,
            "hid_driver": driver,
            "serial": serial,
        }
    return {"method": "", "serial": _read(sys_device / "uniq")}


def stable_id(pad: dict) -> str:
    vendor = pad.get("vendor") or "0000"
    product = pad.get("product") or "0000"
    serial = (pad.get("serial") or "").replace(":", "").strip()
    if pad.get("method", "").startswith("usb") and pad.get("usb"):
        if serial:
            return f"usb:{vendor}:{product}:{serial}"
        return f"usb:{vendor}:{product}:{pad['usb']}"
    if pad.get("hid"):
        if serial:
            return f"hid:{vendor}:{product}:{serial}"
        return f"hid:{vendor}:{product}:{pad['hid']}"
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(pad.get("name") or "pad")).strip("-")
    return f"virt:{vendor}:{product}:{name or 'pad'}"


def list_live_joysticks(root: Path = INPUT_ROOT) -> list[dict]:
    pads: list[dict] = []
    for js in sorted(root.glob("js*/device"), key=lambda p: p.parent.name):
        vendor = _read(js / "id" / "vendor").lower().zfill(4)[-4:]
        product = _read(js / "id" / "product").lower().zfill(4)[-4:]
        name = _read(js / "name")
        pad = {
            "js": js.parent.name,
            "name": name,
            "vendor": vendor,
            "product": product,
            "version": _read(js / "id" / "version").lower().zfill(4)[-4:] or "0000",
            "bustype": _read(js / "id" / "bustype").lower().zfill(4)[-4:] or "0003",
            "event": event_node(js),
            "sys": str(resolve_sys_device(js)),
        }
        if is_skipped(pad):
            continue
        target = target_for_device(Path(pad["sys"]))
        pad.update(target)
        if not pad.get("serial"):
            pad["serial"] = _read(js / "uniq")
        pad["id"] = stable_id(pad)
        pad["kind"] = pad_kind(pad)
        pad["connected"] = True
        pad["hidden"] = False
        pads.append(pad)
    real = [p for p in pads if not is_steam_virtual(p)]
    return real if real else pads


def ids_match(left: dict, right: dict) -> bool:
    if left.get("id") and left.get("id") == right.get("id"):
        return True
    if left.get("usb") and left.get("usb") == right.get("usb"):
        return True
    if left.get("hid") and left.get("hid") == right.get("hid"):
        return True
    serial = (left.get("serial") or "").strip()
    if (
        serial
        and serial == (right.get("serial") or "").strip()
        and left.get("vendor") == right.get("vendor")
        and left.get("product") == right.get("product")
    ):
        return True
    return False


def merge_pads(live: list[dict], hidden: list[dict]) -> list[dict]:
    out: list[dict] = []
    hidden_used: set[int] = set()
    for pad in live:
        match = None
        for i, row in enumerate(hidden):
            if ids_match(pad, row):
                match = row
                hidden_used.add(i)
                break
        item = dict(pad)
        if match:
            item["hidden"] = True
            item["id"] = match.get("id") or item["id"]
            item["method"] = match.get("method") or item.get("method")
            item["usb"] = match.get("usb") or item.get("usb")
            item["hid"] = match.get("hid") or item.get("hid")
            item["hid_driver"] = match.get("hid_driver") or item.get("hid_driver")
        out.append(item)
    for i, row in enumerate(hidden):
        if i in hidden_used:
            continue
        out.append(
            {
                "id": row.get("id"),
                "name": row.get("name") or row.get("id"),
                "vendor": row.get("vendor") or "",
                "product": row.get("product") or "",
                "serial": row.get("serial") or "",
                "usb": row.get("usb") or "",
                "hid": row.get("hid") or "",
                "hid_driver": row.get("hid_driver") or "",
                "method": row.get("method") or "",
                "js": "",
                "event": "",
                "kind": pad_kind(row),
                "connected": False,
                "hidden": True,
            }
        )
    return out


def recent_ui_ids(pads: list[dict], timeout: float = 0.28) -> list[str]:
    """Pads that sent a press or stick during the wait window (QAM / Steam)."""
    if os.environ.get("PAD_HIDE_UI_IDS") is not None:
        return [p for p in os.environ["PAD_HIDE_UI_IDS"].split(",") if p]
    watch: list[tuple[int, str]] = []
    fds: list[int] = []
    for pad in pads:
        if pad.get("hidden") or not pad.get("connected"):
            continue
        node = pad.get("event") or ""
        if not node or not Path(node).exists():
            continue
        try:
            fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        watch.append((fd, str(pad["id"])))
        fds.append(fd)
    if not fds:
        return []
    active: list[str] = []
    try:
        ready, _, _ = select.select(fds, [], [], timeout)
        seen: set[str] = set()
        for fd in ready:
            pid = next((p for f, p in watch if f == fd), "")
            try:
                raw = os.read(fd, INPUT_EVENT_SIZE * 8)
            except OSError:
                continue
            off = 0
            while off + INPUT_EVENT_SIZE <= len(raw):
                _sec, _usec, ev_type, ev_code, _value = struct.unpack_from(
                    INPUT_EVENT_FMT, raw, off
                )
                off += INPUT_EVENT_SIZE
                if ev_type == EV_KEY or (ev_type == EV_ABS and ev_code in _STICK_ABS):
                    if pid and pid not in seen:
                        seen.add(pid)
                        active.append(pid)
                    break
    finally:
        for fd, _pid in watch:
            try:
                os.close(fd)
            except OSError:
                pass
    return active


def helper_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PAD_HIDE_USB_ROOT"] = str(USB_ROOT)
    env["PAD_HIDE_HID_ROOT"] = str(HID_ROOT)
    drv = os.environ.get("PAD_HIDE_HID_DRV_ROOT")
    if drv:
        env["PAD_HIDE_HID_DRV_ROOT"] = drv
    return env


def run_helper(args: list[str]) -> tuple[bool, str]:
    helper = helper_path()
    if not helper.is_file():
        return False, f"missing {helper}"
    cmd = [str(helper), *args]
    if os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=8,
            env=helper_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        if "password is required" in err or "a terminal is required" in err:
            err = (
                "SSH hide needs sudoers/zzz-hide-controllers "
                "(QAM does not). " + err
            )
        return False, err
    return True, ""


def apply_hide_row(row: dict) -> tuple[bool, str]:
    method = row.get("method") or ""
    if method == "usb-authorized":
        busid = row.get("usb") or ""
        if not USB_DEV_RE.fullmatch(busid):
            return False, f"bad usb id {busid}"
        if is_usb_hub(busid):
            return False, f"refusing USB hub {busid}"
        return run_helper(["usb-authorized", busid, "0"])
    if method == "hid-authorized":
        hid = row.get("hid") or ""
        if not HID_RE.fullmatch(hid):
            return False, f"bad hid id {hid}"
        return run_helper(["hid-authorized", hid, "0"])
    if method == "hid-unbind":
        hid = row.get("hid") or ""
        if not HID_RE.fullmatch(hid):
            return False, f"bad hid id {hid}"
        return run_helper(["hid-unbind", hid])
    return False, "no kernel hide target (virtual pad)"


def apply_show_row(row: dict) -> tuple[bool, str]:
    method = row.get("method") or ""
    if method == "usb-authorized":
        busid = row.get("usb") or ""
        if not USB_DEV_RE.fullmatch(busid):
            return False, f"bad usb id {busid}"
        return run_helper(["usb-authorized", busid, "1"])
    if method == "hid-authorized":
        hid = row.get("hid") or ""
        if not HID_RE.fullmatch(hid):
            return False, f"bad hid id {hid}"
        return run_helper(["hid-authorized", hid, "1"])
    if method == "hid-unbind":
        hid = row.get("hid") or ""
        drv = row.get("hid_driver") or ""
        if not HID_RE.fullmatch(hid):
            return False, f"bad hid id {hid}"
        if not drv:
            return False, "missing hid driver to bind"
        return run_helper(["hid-bind", hid, drv])
    return False, "no kernel hide target (virtual pad)"


def find_pad(pads: list[dict], ident: str) -> dict | None:
    ident = (ident or "").strip()
    if not ident:
        return None
    for pad in pads:
        if pad.get("id") == ident:
            return pad
    for pad in pads:
        if pad.get("js") == ident or pad.get("usb") == ident or pad.get("hid") == ident:
            return pad
    low = ident.lower()
    hits = [p for p in pads if low in str(p.get("name") or "").lower()]
    if len(hits) == 1:
        return hits[0]
    return None


def annotate(pads: list[dict], ui_ids: list[str]) -> list[dict]:
    ui = set(ui_ids)
    out = []
    for pad in pads:
        item = dict(pad)
        method = item.get("method") or ""
        is_ui = item.get("id") in ui and bool(item.get("connected")) and not item.get("hidden")
        item["ui"] = is_ui
        if item.get("hidden"):
            item["can_disable"] = True
            item["reason"] = ""
        elif not method:
            item["can_disable"] = False
            item["reason"] = "virtual pad (Sunshine/Steam) — no USB/HID to unplug"
        elif is_ui:
            item["can_disable"] = False
            item["reason"] = "controlling Steam/QAM — will not hide itself"
        else:
            item["can_disable"] = True
            item["reason"] = ""
        item["sunshine"] = pad_kind(item) == "Sunshine"
        out.append(item)
    return out


def public_pad(pad: dict) -> dict:
    keys = (
        "id",
        "name",
        "js",
        "event",
        "vendor",
        "product",
        "serial",
        "usb",
        "hid",
        "method",
        "kind",
        "connected",
        "hidden",
        "can_disable",
        "ui",
        "reason",
        "sunshine",
    )
    return {k: pad.get(k) for k in keys if k in pad or k in (
        "connected", "hidden", "can_disable", "ui", "reason", "sunshine"
    )}


def sudo_ready() -> bool:
    if os.geteuid() == 0:
        return True
    helper = helper_path()
    if not helper.is_file():
        return False
    try:
        proc = subprocess.run(
            ["sudo", "-n", str(helper)],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    # usage error (2) still means sudo accepted the binary
    return proc.returncode in (0, 2)


def status_payload(apply_hidden: bool = False) -> dict:
    hidden = load_hidden()
    if apply_hidden:
        for row in hidden:
            apply_hide_row(row)
        hidden = load_hidden()
    live = list_live_joysticks()
    pads = merge_pads(live, hidden)
    ui_ids = recent_ui_ids(pads)
    pads = annotate(pads, ui_ids)
    return {
        "ok": True,
        "pads": [public_pad(p) for p in pads],
        "ui_pad": ui_ids[0] if ui_ids else "",
        "sudo": sudo_ready(),
        "config": str(config_path()),
    }


def persist_hidden_from_pad(pad: dict, hidden: list[dict]) -> list[dict]:
    row = {
        "id": pad["id"],
        "name": pad.get("name") or pad["id"],
        "vendor": pad.get("vendor") or "",
        "product": pad.get("product") or "",
        "serial": pad.get("serial") or "",
        "usb": pad.get("usb") or "",
        "hid": pad.get("hid") or "",
        "hid_driver": pad.get("hid_driver") or "",
        "method": pad.get("method") or "",
    }
    out = [r for r in hidden if not ids_match(r, row)]
    out.append(row)
    return out


def cmd_status(_args: argparse.Namespace) -> int:
    data = status_payload(apply_hidden=True)
    print(json.dumps(data))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    return cmd_status(args)


def parse_hidden_flag(value: object) -> bool | None:
    """True = hide. QAM toggle off / ``hide`` / ``hidden``. ``on`` = connected."""
    raw = str(value or "").strip().lower()
    if raw in ("hide", "hidden", "1", "true", "yes", "off"):
        return True
    if raw in ("show", "visible", "connected", "0", "false", "no", "on"):
        return False
    return None


def cmd_set(args: argparse.Namespace) -> int:
    ident = (args.id or "").strip()
    want_hidden = parse_hidden_flag(args.hidden)
    if want_hidden is None:
        print(json.dumps({"ok": False, "message": f"unknown --hidden {args.hidden}"}))
        return 1
    force = bool(getattr(args, "force", False))
    data = status_payload(apply_hidden=False)
    # Re-scan with full records for method fields
    live = list_live_joysticks()
    hidden = load_hidden()
    merged = annotate(merge_pads(live, hidden), recent_ui_ids(merge_pads(live, hidden)))
    pad = find_pad(merged, ident)
    if pad is None:
        print(json.dumps({"ok": False, "message": f"unknown pad {ident}", "pads": data["pads"]}))
        return 1
    if want_hidden:
        if not pad.get("method"):
            print(json.dumps({
                "ok": False,
                "message": pad.get("reason") or "virtual pad cannot be hidden",
                "pads": data["pads"],
            }))
            return 1
        if pad.get("ui") and not force:
            print(json.dumps({
                "ok": False,
                "message": (
                    f"{pad.get('name') or pad['id']} is controlling Steam/QAM "
                    "and will not hide itself"
                ),
                "pads": data["pads"],
            }))
            return 2
        ok, err = apply_hide_row(pad)
        if not ok:
            print(json.dumps({"ok": False, "message": err, "id": pad["id"]}))
            return 1
        write_hidden(persist_hidden_from_pad(pad, hidden))
        message = f"Hid {pad.get('name') or pad['id']}"
    else:
        ok, err = apply_show_row(pad)
        if not ok:
            print(json.dumps({"ok": False, "message": err, "id": pad["id"]}))
            return 1
        write_hidden([r for r in hidden if not ids_match(r, pad)])
        message = f"Restored {pad.get('name') or pad['id']}"
    out = status_payload(apply_hidden=False)
    out["message"] = message
    out["id"] = pad["id"]
    print(json.dumps(out))
    return 0


def cmd_hide(args: argparse.Namespace) -> int:
    args.hidden = "hide"
    return cmd_set(args)


def cmd_show(args: argparse.Namespace) -> int:
    args.hidden = "show"
    return cmd_set(args)


def cmd_apply(_args: argparse.Namespace) -> int:
    hidden = load_hidden()
    errors: list[str] = []
    for row in hidden:
        ok, err = apply_hide_row(row)
        if not ok:
            errors.append(f"{row.get('id')}: {err}")
    out = status_payload(apply_hidden=False)
    out["applied"] = len(hidden)
    if errors:
        out["ok"] = False
        out["message"] = "; ".join(errors)
        print(json.dumps(out))
        return 1
    out["message"] = f"Applied {len(hidden)} hidden pad(s)"
    print(json.dumps(out))
    return 0


def _write_tree(root: Path, rel: str, text: str) -> Path:
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    return dest


def self_test() -> int:
    assert usb_busid_from_path(
        Path(
            "/sys/devices/pci0000:00/usb1/1-1/1-1.3/1-1.3:1.0/input/input53"
        )
    ) == "1-1.3"
    assert hid_id_from_path(
        Path("/sys/devices/pci/0005:057E:2009.0008/input/input9")
    ) == "0005:057E:2009.0008"
    xbox = {
        "name": "Microsoft X-Box 360 pad",
        "vendor": "045e",
        "product": "028e",
        "serial": "5F19FC0A",
        "usb": "1-1.3",
        "method": "usb-authorized",
    }
    xbox["id"] = stable_id(xbox)
    assert xbox["id"] == "usb:045e:028e:5F19FC0A"
    assert pad_kind(xbox) == "Xbox"
    assert not is_skipped(xbox)
    assert is_skipped({"name": "ASRock LED Controller", "vendor": "26ce", "product": "01a2"})
    assert is_skipped({"name": "EmuPads P1", "vendor": "1209", "product": "e301"})
    assert is_skipped({"name": "libvirtualhid Mouse", "vendor": "1209", "product": "0003"})
    virt = {"name": "Sunshine (libvirtualhid) AYN_Thor", "vendor": "045e", "product": "028e"}
    assert pad_kind(virt) == "Sunshine"
    assert stable_id(virt).startswith("virt:")

    live = [
        {
            "id": "usb:045e:028e:5F19FC0A",
            "name": "Xbox",
            "vendor": "045e",
            "product": "028e",
            "serial": "5F19FC0A",
            "usb": "1-1.3",
            "method": "usb-authorized",
            "connected": True,
            "hidden": False,
        }
    ]
    hidden = [{"id": "usb:045e:028e:5F19FC0A", "name": "Xbox", "usb": "1-1.3"}]
    merged = merge_pads(live, hidden)
    assert merged[0]["hidden"] is True
    extra = merge_pads([], hidden)
    assert extra[0]["connected"] is False
    assert extra[0]["hidden"] is True

    annotated = annotate(
        [{"id": "usb:1", "method": "usb-authorized", "connected": True, "hidden": False, "name": "Xbox"}],
        ["usb:1"],
    )
    assert annotated[0]["ui"] is True
    assert annotated[0]["can_disable"] is False
    virt_a = annotate(
        [{"id": "virt:t", "method": "", "connected": True, "hidden": False, "name": "Thor"}],
        [],
    )
    assert virt_a[0]["can_disable"] is False
    assert parse_hidden_flag("hide") is True
    assert parse_hidden_flag("off") is True
    assert parse_hidden_flag("on") is False
    assert parse_hidden_flag("show") is False
    assert parse_hidden_flag("nope") is None

    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "hidden.json"
        os.environ["PAD_HIDE_CONFIG"] = str(cfg)
        write_hidden([xbox])
        loaded = load_hidden()
        assert loaded[0]["id"] == "usb:045e:028e:5F19FC0A"
        os.environ.pop("PAD_HIDE_CONFIG", None)

        usb = Path(td) / "usb"
        hub = usb / "1-1"
        _write_tree(hub, "bDeviceClass", "09\n")
        _write_tree(hub, "idVendor", "05e3\n")
        leaf = usb / "1-1.3"
        _write_tree(leaf, "bDeviceClass", "00\n")
        _write_tree(leaf, "idVendor", "045e\n")
        _write_tree(leaf, "authorized", "1")
        os.environ["PAD_HIDE_USB_ROOT"] = str(usb)
        assert is_usb_hub("1-1", usb)
        assert not is_usb_hub("1-1.3", usb)
        os.environ.pop("PAD_HIDE_USB_ROOT", None)

        helper = playbook_root() / "scripts" / HELPER_NAME
        if helper.is_file() and os.access(helper, os.X_OK):
            proc = subprocess.run(
                [str(helper), "usb-authorized", "evil", "0"],
                capture_output=True,
                text=True,
            )
            assert proc.returncode == 2
            proc = subprocess.run(
                [str(helper), "hid-unbind", "not-an-id"],
                capture_output=True,
                text=True,
            )
            assert proc.returncode == 2
            # helper refuses hubs even when the tree is fake
            proc = subprocess.run(
                [str(helper), "usb-authorized", "1-1", "0"],
                capture_output=True,
                text=True,
                env={**os.environ, "PAD_HIDE_USB_ROOT": str(usb)},
            )
            assert proc.returncode == 2
            assert "hub" in (proc.stderr or "").lower()
            leaf_auth = leaf / "authorized"
            proc = subprocess.run(
                [str(helper), "usb-authorized", "1-1.3", "0"],
                capture_output=True,
                text=True,
                env={**os.environ, "PAD_HIDE_USB_ROOT": str(usb)},
            )
            assert proc.returncode == 0, proc.stderr
            assert leaf_auth.read_text() == "0"
            proc = subprocess.run(
                [str(helper), "usb-authorized", "1-1.3", "1"],
                capture_output=True,
                text=True,
                env={**os.environ, "PAD_HIDE_USB_ROOT": str(usb)},
            )
            assert proc.returncode == 0
            assert leaf_auth.read_text() == "1"

    print("hide-controllers self-test ok")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("list").set_defaults(func=cmd_list)
    p_set = sub.add_parser("set")
    p_set.add_argument("--id", required=True)
    p_set.add_argument("--hidden", required=True)
    p_set.add_argument("--force", action="store_true")
    p_set.set_defaults(func=cmd_set)
    p_hide = sub.add_parser("hide")
    p_hide.add_argument("--id", required=True)
    p_hide.add_argument("--force", action="store_true")
    p_hide.set_defaults(func=cmd_hide)
    p_show = sub.add_parser("show")
    p_show.add_argument("--id", required=True)
    p_show.set_defaults(func=cmd_show)
    sub.add_parser("apply").set_defaults(func=cmd_apply)
    sub.add_parser("self-test").set_defaults(func=lambda _a: self_test())
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
