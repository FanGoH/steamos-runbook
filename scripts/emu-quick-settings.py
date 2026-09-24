#!/usr/bin/env python3
"""Read and write Eden / Azahar / Cemu quick settings (global or per-game).

Decky Emu Quick calls this as user deck. Do not touch pad binds, dual-screen
layout, fullscreen_mode, or Engage's 4GB memory pin.

Eden docked/handheld, scaling filter, GPU Normal/High, and speed limit can
apply live via hotkeys while Eden is running. Resolution has no hotkey.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TITLE_RE = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{16})(?![0-9A-Fa-f])")
BOOT_RE = re.compile(
    r"Booting game:\s*([0-9A-Fa-f]{16})\s*\|\s*([^|\n]+)", re.I
)
EDEN_TITLE_RE = re.compile(r"\b(0100[0-9A-Fa-f]{12})\b")
WIIU_TITLE_RE = re.compile(r"\b(00050000[0-9A-Fa-f]{8})\b", re.I)
N3DS_TITLE_RE = re.compile(r"\b(00040000[0-9A-Fa-f]{8})\b", re.I)

ENGAGE_TITLE = "0100A6301214E000"

EDEN_PROTECTED = {
    "fullscreen_mode",
    "fullscreen",
    "showStatusBar",
    "enable_joycon_driver",
    "memory_layout_mode",
    "player_0_type",
    "player_0_connected",
    "player_0_vibration_enabled",
}
AZAHAR_PROTECTED = {
    "layout_option",
    "singleWindowMode",
    "screen_bottom_stretch",
    "screen_top_stretch",
    "secondary_display_layout",
    "confirmClose",
}
CEMU_PROTECTED = {
    "fullscreen",
    "open_pad",
    "pad_position",
    "pad_size",
    "window_position",
    "window_size",
}


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on", "docked"}


def _as_bool_token(value: str) -> str:
    return "true" if _truthy(value) else "false"


def home_dir(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("HOME")
    return Path(env) if env else Path.home()


def eden_ini(home: Path) -> Path:
    return home / ".config/eden/qt-config.ini"


def eden_custom_dir(home: Path) -> Path:
    return home / ".config/eden/custom"


def eden_log(home: Path) -> Path:
    return home / ".local/share/eden/log/eden_log.txt"


def eden_log_paths(home: Path) -> list[Path]:
    paths = [
        eden_log(home),
        home / ".config/eden/log/eden_log.txt",
        home / ".local/share/yuzu/log/yuzu_log.txt",
        home / ".config/yuzu/log/yuzu_log.txt",
    ]
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def azahar_inis(home: Path) -> list[Path]:
    return [
        home / ".var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini",
        home / ".var/app/net.retrodeck.retrodeck/config/azahar-emu/qt-config.ini",
    ]


def cemu_settings(home: Path) -> list[Path]:
    return [
        home / ".var/app/info.cemu.Cemu/config/Cemu/settings.xml",
        home / ".var/app/net.retrodeck.retrodeck/config/Cemu/settings.xml",
    ]


def existing(paths: list[Path]) -> list[Path]:
    return [path for path in paths if path.is_file()]


# --- INI (Yuzu / Azahar switchable keys) -----------------------------------


def ini_get(text: str, key: str) -> dict[str, str | None]:
    value = None
    default = None
    use_global = None
    for line in text.splitlines():
        if line.startswith(f"{key}=") and not line.startswith(f"{key}\\"):
            value = line.split("=", 1)[1]
        elif line.startswith(f"{key}\\default="):
            default = line.split("=", 1)[1]
        elif line.startswith(f"{key}\\use_global="):
            use_global = line.split("=", 1)[1]
    return {"value": value, "default": default, "use_global": use_global}


def _ensure_section(text: str, section: str) -> str:
    header = f"[{section}]"
    if re.search(rf"^\[{re.escape(section)}\]\s*$", text, re.M):
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + f"\n{header}\n"


def _replace_or_insert(text: str, section: str, key: str, value: str) -> str:
    pat = re.compile(r"^" + re.escape(key) + r"=.*$", re.M)
    line = f"{key}={value}"
    if pat.search(text):
        return pat.sub(lambda _m: line, text, count=1)
    text = _ensure_section(text, section)
    header = re.compile(rf"^\[{re.escape(section)}\]\s*$", re.M)
    match = header.search(text)
    if match is None:
        return text + f"{line}\n"
    insert_at = match.end()
    return text[:insert_at] + f"\n{line}" + text[insert_at:]


def ini_set(
    text: str,
    section: str,
    key: str,
    *,
    value: str | None = None,
    use_global: bool | None = None,
    mark_user: bool = True,
) -> str:
    if value is not None:
        text = _replace_or_insert(text, section, key, value)
        if mark_user:
            text = _replace_or_insert(text, section, f"{key}\\default", "false")
    if use_global is not None:
        text = _replace_or_insert(
            text, section, f"{key}\\use_global", "true" if use_global else "false"
        )
    return text


def ini_uses_global(entry: dict[str, str | None], *, per_game: bool) -> bool:
    if not per_game:
        return True
    raw = entry.get("use_global")
    if raw is None:
        return entry.get("value") is None
    return _truthy(raw)


# --- XML (Cemu) ------------------------------------------------------------


def _xml_find(root: ET.Element, path: str, *, create: bool = False) -> ET.Element | None:
    cur = root
    for part in path.split("/"):
        nxt = cur.find(part)
        if nxt is None:
            if not create:
                return None
            nxt = ET.SubElement(cur, part)
        cur = nxt
    return cur


def xml_get(text: str, path: str) -> str | None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    el = _xml_find(root, path)
    if el is None or el.text is None:
        return None
    return el.text.strip()


def xml_set(text: str, path: str, value: str) -> str:
    root = ET.fromstring(text)
    el = _xml_find(root, path, create=True)
    assert el is not None
    el.text = value
    ET.indent(root, space="    ")
    body = ET.tostring(root, encoding="unicode")
    if text.lstrip().startswith("<?xml"):
        decl = text.lstrip().split("\n", 1)[0]
        if decl.startswith("<?xml"):
            return decl + "\n" + body + ("\n" if not body.endswith("\n") else "")
    return body + ("\n" if not body.endswith("\n") else "")


# --- Setting catalogs ------------------------------------------------------


def _enum(options: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in options]


EDEN_SETTINGS = [
    {
        "key": "use_docked_mode",
        "section": "System",
        "label": "Docked",
        "kind": "bool",
        "default": "true",
        "options": _enum([("false", "Handheld"), ("true", "Docked")]),
        "normalize": "bool",
        "hotswap": "live",
        "widget": "toggle",
    },
    {
        "key": "resolution_setup",
        "section": "Renderer",
        "label": "Resolution",
        "kind": "enum",
        "default": "2",
        "options": _enum(
            [
                ("0", "0.5x"),
                ("1", "0.75x"),
                ("2", "1x"),
                ("3", "1.5x"),
                ("4", "2x"),
                ("5", "3x"),
                ("6", "4x"),
                ("7", "5x"),
                ("8", "6x"),
            ]
        ),
        "hotswap": "restart",
        "widget": "slider",
    },
    {
        "key": "gpu_accuracy",
        "section": "Renderer",
        "label": "GPU accuracy",
        "kind": "enum",
        "default": "0",
        "options": _enum([("0", "Normal"), ("1", "High"), ("2", "Extreme")]),
        "hotswap": "live",
        "widget": "slider",
    },
    {
        "key": "use_vsync",
        "section": "Renderer",
        "label": "VSync",
        "kind": "enum",
        "default": "2",
        "options": _enum(
            [
                ("0", "Immediate"),
                ("1", "Mailbox"),
                ("2", "FIFO"),
                ("3", "FIFO Relaxed"),
            ]
        ),
        "widget": "slider",
    },
    {
        "key": "scaling_filter",
        "section": "Renderer",
        "label": "Scaling filter",
        "kind": "enum",
        "default": "1",
        "options": _enum(
            [
                ("0", "Nearest"),
                ("1", "Bilinear"),
                ("2", "Bicubic"),
                ("3", "Gaussian"),
                ("4", "ScaleForce"),
                ("5", "FSR"),
                ("6", "FSR 2"),
            ]
        ),
        "hotswap": "live",
        "widget": "slider",
    },
    {
        "key": "anti_aliasing",
        "section": "Renderer",
        "label": "Anti-aliasing",
        "kind": "enum",
        "default": "0",
        "options": _enum([("0", "None"), ("1", "FXAA"), ("2", "SMAA")]),
        "widget": "slider",
    },
    {
        "key": "max_anisotropy",
        "section": "Renderer",
        "label": "Anisotropic",
        "kind": "enum",
        "default": "0",
        "options": _enum(
            [
                ("0", "Auto"),
                ("1", "Default"),
                ("2", "2x"),
                ("3", "4x"),
                ("4", "8x"),
                ("5", "16x"),
            ]
        ),
        "widget": "slider",
    },
    {
        "key": "use_speed_limit",
        "section": "Core",
        "label": "Limit speed",
        "kind": "bool",
        "default": "true",
        "normalize": "bool",
        "hotswap": "live",
        "widget": "toggle",
    },
    {
        "key": "speed_limit",
        "section": "Core",
        "label": "Speed limit",
        "kind": "enum",
        "default": "100",
        "options": _enum(
            [
                ("50", "50%"),
                ("75", "75%"),
                ("100", "100%"),
                ("150", "150%"),
                ("200", "200%"),
            ]
        ),
        "widget": "slider",
    },
    {
        "key": "use_asynchronous_shaders",
        "section": "Renderer",
        "label": "Async shaders",
        "kind": "bool",
        "default": "true",
        "normalize": "bool",
    },
]

AZAHAR_SETTINGS = [
    {
        "key": "resolution_factor",
        "section": "Renderer",
        "label": "Resolution",
        "kind": "enum",
        "default": "1",
        "options": _enum(
            [(str(i), f"{i}x") for i in range(1, 11)]
        ),
        "widget": "slider",
    },
    {
        "key": "use_vsync",
        "section": "Renderer",
        "label": "VSync",
        "kind": "bool",
        "default": "true",
        "normalize": "bool",
        "widget": "toggle",
    },
    {
        "key": "frame_limit",
        "section": "Renderer",
        "label": "Frame limit",
        "kind": "enum",
        "default": "100",
        "options": _enum(
            [
                ("0", "Unlimited"),
                ("50", "50%"),
                ("100", "100%"),
                ("150", "150%"),
                ("200", "200%"),
            ]
        ),
        "widget": "slider",
    },
    {
        "key": "texture_filter",
        "section": "Renderer",
        "label": "Texture filter",
        "kind": "enum",
        "default": "0",
        "options": _enum(
            [
                ("0", "None"),
                ("1", "Anime4K"),
                ("2", "Bicubic"),
                ("3", "ScaleForce"),
                ("4", "xBRZ"),
                ("5", "MMPX"),
            ]
        ),
        "widget": "slider",
    },
    {
        "key": "graphics_api",
        "section": "Renderer",
        "label": "Renderer",
        "kind": "enum",
        "default": "2",
        "options": _enum([("1", "OpenGL"), ("2", "Vulkan")]),
        "widget": "slider",
    },
    {
        "key": "async_shader_compilation",
        "section": "Renderer",
        "label": "Async shaders",
        "kind": "bool",
        "default": "true",
        "normalize": "bool",
    },
    {
        "key": "shaders_accurate_mul",
        "section": "Renderer",
        "label": "Accurate multiply",
        "kind": "bool",
        "default": "true",
        "normalize": "bool",
    },
    {
        "key": "is_new_3ds",
        "section": "System",
        "label": "New 3DS",
        "kind": "bool",
        "default": "true",
        "normalize": "bool",
    },
]

CEMU_SETTINGS = [
    {
        "key": "vsync",
        "xml": "Graphic/VSync",
        "label": "VSync",
        "kind": "enum",
        "default": "0",
        "options": _enum([("0", "Off"), ("1", "On"), ("2", "Double")]),
    },
    {
        "key": "upscale_filter",
        "xml": "Graphic/UpscaleFilter",
        "label": "Upscale filter",
        "kind": "enum",
        "default": "1",
        "options": _enum(
            [
                ("0", "Bilinear"),
                ("1", "Bicubic"),
                ("2", "Hermite"),
                ("3", "Nearest"),
            ]
        ),
    },
    {
        "key": "overlay_fps",
        "xml": "Graphic/Overlay/FPS",
        "label": "FPS overlay",
        "kind": "bool",
        "default": "true",
        "normalize": "bool",
    },
    {
        "key": "async_compile",
        "xml": "Graphic/AsyncCompile",
        "label": "Async compile",
        "kind": "bool",
        "default": "true",
        "normalize": "bool",
    },
]


def catalog(emu: str) -> list[dict]:
    if emu == "eden":
        return EDEN_SETTINGS
    if emu == "azahar":
        return AZAHAR_SETTINGS
    if emu == "cemu":
        return CEMU_SETTINGS
    raise KeyError(emu)


def setting_by_key(emu: str, key: str) -> dict:
    for item in catalog(emu):
        if item["key"] == key:
            return item
    raise KeyError(key)


def normalize_value(spec: dict, value: str) -> str:
    raw = str(value).strip()
    if spec.get("normalize") == "bool" or spec.get("kind") == "bool":
        return _as_bool_token(raw)
    options = spec.get("options") or []
    allowed = {opt["value"] for opt in options}
    if allowed and raw not in allowed:
        # Accept labels too ("2x", "Docked").
        for opt in options:
            if opt["label"].lower() == raw.lower():
                return opt["value"]
        raise ValueError(f"Invalid {spec['key']}={raw!r}")
    return raw


def option_label(spec: dict, value: str) -> str:
    for opt in spec.get("options") or []:
        if opt["value"] == value:
            return opt["label"]
    if spec.get("kind") == "bool":
        return "On" if _truthy(value) else "Off"
    return value


def widget_for(spec: dict) -> str:
    if spec.get("widget"):
        return spec["widget"]
    if spec.get("kind") == "bool" or spec.get("normalize") == "bool":
        return "toggle"
    if spec.get("options"):
        return "slider"
    return "cycle"


# --- Process / title detection ---------------------------------------------


def _comm_ok(comm: str, emu: str) -> bool:
    name = comm.strip().lower()
    if emu == "cemu":
        return name.startswith("cemu")
    if emu == "azahar":
        return name == "azahar"
    if emu == "eden":
        return name in {"eden", "eden.desktop"} or name.startswith("eden")
    return False


def running_cmdlines(emu: str, proc_root: Path | None = None) -> list[list[str]]:
    root = proc_root or Path("/proc")
    found: list[list[str]] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return found
    for pid in entries:
        if not pid.name.isdigit():
            continue
        try:
            comm = (pid / "comm").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _comm_ok(comm, emu):
            continue
        try:
            raw = (pid / "cmdline").read_bytes()
        except OSError:
            found.append([])
            continue
        args = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
        found.append(args)
    return found


def emu_running(emu: str, proc_root: Path | None = None) -> bool:
    return bool(running_cmdlines(emu, proc_root))


def eden_pid(proc_root: Path | None = None) -> str:
    root = proc_root or Path("/proc")
    try:
        entries = list(root.iterdir())
    except OSError:
        return ""
    for pid in entries:
        if not pid.name.isdigit():
            continue
        try:
            comm = (pid / "comm").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _comm_ok(comm, "eden"):
            return pid.name
    return ""


def rom_from_args(args: list[str]) -> str | None:
    skip_next = False
    take_flags = {"-g", "--game", "--titleid", "--title-id"}
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg in take_flags and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--game="):
            return arg.split("=", 1)[1]
    for arg in reversed(args[1:]):
        if arg.startswith("-"):
            continue
        if "/" in arg:
            return arg
    return None


def title_id_from_text(text: str, emu: str) -> str | None:
    if emu == "eden":
        match = EDEN_TITLE_RE.search(text)
    elif emu == "cemu":
        match = WIIU_TITLE_RE.search(text)
    elif emu == "azahar":
        match = N3DS_TITLE_RE.search(text)
    else:
        match = TITLE_RE.search(text)
    return match.group(1).upper() if match else None


def _norm_title(text: str) -> str:
    raw = re.sub(
        r"\.(xci|nsp|nca|wux|wud|rpx|cia|3ds|cxi|app)$",
        "",
        (text or "").strip(),
        flags=re.I,
    )
    raw = raw.replace("_", " ").replace("-", " ")
    return " ".join(raw.lower().split())


def title_id_from_name(names: dict[str, str], title: str, emu: str) -> str:
    needle = _norm_title(title)
    if not needle:
        return ""
    hits: list[str] = []
    for tid, name in names.items():
        upper = tid.upper()
        if emu == "eden" and not upper.startswith("0100"):
            continue
        if emu == "azahar" and not upper.startswith("00040000"):
            continue
        if emu == "cemu" and not upper.startswith("00050000"):
            continue
        if _norm_title(name) == needle:
            hits.append(upper)
    uniq = list(dict.fromkeys(hits))
    return uniq[0] if len(uniq) == 1 else ""


def last_eden_boot(home: Path) -> dict[str, str] | None:
    logs = [path for path in eden_log_paths(home) if path.is_file()]
    logs.sort(key=lambda path: path.stat().st_mtime)
    last: dict[str, str] | None = None
    for log in logs:
        try:
            blob = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        matches = list(BOOT_RE.finditer(blob))
        if matches:
            match = matches[-1]
            last = {
                "title_id": match.group(1).upper(),
                "title": match.group(2).strip(),
            }
    return last


def _add_title_name(names: dict[str, str], filename: str) -> None:
    match = TITLE_RE.search(filename)
    if not match:
        return
    tid = match.group(1).upper()
    if tid in names:
        return
    pretty = TITLE_RE.sub("", filename)
    pretty = re.sub(r"[\[\]()_]+", " ", pretty)
    pretty = re.sub(
        r"\.(xci|nsp|nca|wux|wud|rpx|cia|3ds|cxi|app)$", "", pretty, flags=re.I
    )
    pretty = " ".join(pretty.split()).strip(" -_")
    if pretty:
        names[tid] = pretty


def scan_title_names(home: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    roots = [
        home / "emulation/switch/games",
        home / "retrodeck/roms/switch",
        home / "emulation/3ds/games",
        home / "retrodeck/roms/n3ds",
        home / "emulation/wiiu",
        home / "retrodeck/roms/wiiu",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            cur, depth = stack.pop()
            try:
                entries = list(cur.iterdir())
            except OSError:
                continue
            for entry in entries:
                _add_title_name(names, entry.name)
                if entry.is_dir() and depth < 2 and not entry.name.startswith("."):
                    stack.append((entry, depth + 1))
    for log in eden_log_paths(home):
        if not log.is_file():
            continue
        try:
            blob = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in BOOT_RE.finditer(blob):
            names.setdefault(match.group(1).upper(), match.group(2).strip())
    return names


def detect_title(emu: str, home: Path, proc_root: Path | None = None) -> dict[str, str]:
    names = scan_title_names(home)
    empty = {"title_id": "", "title": "", "rom": ""}
    candidate = dict(empty)

    def from_rom(rom: str) -> dict[str, str]:
        tid = title_id_from_text(rom, emu) or ""
        stem = Path(rom).stem
        if not tid:
            tid = title_id_from_name(names, stem, emu)
        return {
            "title_id": tid,
            "title": names.get(tid) or stem,
            "rom": rom,
        }

    for args in running_cmdlines(emu, proc_root):
        rom = rom_from_args(args)
        if not rom:
            continue
        hit = from_rom(rom)
        if hit["title_id"]:
            return hit
        candidate = hit
    if emu == "eden" and emu_running(emu, proc_root):
        boot = last_eden_boot(home)
        if boot:
            return {
                "title_id": boot["title_id"],
                "title": boot["title"]
                or names.get(boot["title_id"])
                or candidate.get("title")
                or "",
                "rom": candidate.get("rom") or "",
            }
    if emu == "cemu":
        for path in existing(cemu_settings(home)):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            recent = re.search(r"<RecentLaunchFiles>\s*<Entry>([^<]+)</Entry>", text)
            if recent:
                rom = recent.group(1)
                hit = from_rom(rom)
                if hit["title_id"] or not candidate["rom"]:
                    return hit
    if candidate["title"] and not candidate["title_id"]:
        tid = title_id_from_name(names, candidate["title"], emu)
        if tid:
            candidate["title_id"] = tid
            candidate["title"] = names.get(tid) or candidate["title"]
    return candidate if candidate["rom"] or candidate["title"] else empty


def known_games(emu: str, home: Path) -> list[dict[str, str]]:
    names = scan_title_names(home)
    games: dict[str, str] = {}
    if emu == "eden":
        custom = eden_custom_dir(home)
        if custom.is_dir():
            for path in custom.glob("*.ini"):
                tid = path.stem.upper()
                if TITLE_RE.fullmatch(tid):
                    games[tid] = names.get(tid, tid)
    elif emu == "azahar":
        for ini in azahar_inis(home):
            custom = ini.parent / "custom"
            if not custom.is_dir():
                continue
            for path in custom.glob("*.ini"):
                tid = path.stem.upper()
                if TITLE_RE.fullmatch(tid):
                    games[tid] = names.get(tid, tid)
    elif emu == "cemu":
        for settings in cemu_settings(home):
            profiles = settings.parent / "gameProfiles"
            if profiles.is_dir():
                for path in profiles.glob("*.ini"):
                    tid = path.stem.upper()
                    if TITLE_RE.fullmatch(tid):
                        games[tid] = names.get(tid, tid)
    for tid, name in names.items():
        if emu == "eden" and tid.startswith("0100"):
            games.setdefault(tid, name)
        elif emu == "azahar" and tid.startswith("00040000"):
            games.setdefault(tid, name)
        elif emu == "cemu" and tid.startswith("00050000"):
            games.setdefault(tid, name)
    return [{"id": tid, "name": games[tid]} for tid in sorted(games)]


# --- Read / write ----------------------------------------------------------


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write(path: Path, old: str, new: str) -> bool:
    if old == new:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and not path.with_name(path.name + ".bak-emu-quick").exists():
        try:
            path.with_name(path.name + ".bak-emu-quick").write_text(old, encoding="utf-8")
        except OSError:
            pass
    tmp = path.with_name(path.name + ".tmp-emu-quick")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(path)
    return True


def custom_path(emu: str, home: Path, title_id: str, *, sibling: Path | None = None) -> Path:
    tid = title_id.upper()
    if emu == "eden":
        return eden_custom_dir(home) / f"{tid}.ini"
    if emu == "azahar":
        base = sibling.parent if sibling is not None else azahar_inis(home)[0].parent
        return base / "custom" / f"{tid}.ini"
    raise KeyError(emu)


def effective_ini_value(
    spec: dict, global_text: str, custom_text: str, *, per_game: bool
) -> tuple[str, bool]:
    custom_entry = ini_get(custom_text, spec["key"]) if custom_text else {"value": None, "use_global": None}
    glob_entry = ini_get(global_text, spec["key"])
    uses_global = ini_uses_global(custom_entry, per_game=per_game)
    if not uses_global and custom_entry.get("value") is not None:
        return custom_entry["value"] or spec["default"], False
    return glob_entry.get("value") or spec["default"], True


def pack_setting(spec: dict, value: str, *, use_global: bool) -> dict:
    out = {
        "key": spec["key"],
        "label": spec["label"],
        "kind": spec["kind"],
        "value": value,
        "display": option_label(spec, value),
        "use_global": use_global,
        "default": spec["default"],
        "hotswap": spec.get("hotswap") or "restart",
        "widget": widget_for(spec),
    }
    if spec.get("options"):
        out["options"] = spec["options"]
    return out


def read_eden(home: Path, title_id: str = "") -> list[dict]:
    global_text = _read(eden_ini(home))
    custom_text = ""
    per_game = bool(title_id)
    if per_game:
        custom_text = _read(custom_path("eden", home, title_id))
    packed = []
    for spec in EDEN_SETTINGS:
        value, uses_global = effective_ini_value(spec, global_text, custom_text, per_game=per_game)
        if spec.get("normalize") == "bool":
            value = _as_bool_token(value)
        packed.append(pack_setting(spec, value, use_global=uses_global if per_game else True))
    return packed


def read_azahar(home: Path, title_id: str = "") -> list[dict]:
    inis = existing(azahar_inis(home)) or azahar_inis(home)
    global_text = _read(inis[0]) if inis else ""
    custom_text = ""
    per_game = bool(title_id)
    if per_game:
        custom_text = _read(custom_path("azahar", home, title_id, sibling=inis[0]))
    packed = []
    for spec in AZAHAR_SETTINGS:
        value, uses_global = effective_ini_value(spec, global_text, custom_text, per_game=per_game)
        if spec.get("normalize") == "bool":
            value = _as_bool_token(value)
        packed.append(pack_setting(spec, value, use_global=uses_global if per_game else True))
    return packed


def read_cemu(home: Path) -> list[dict]:
    paths = existing(cemu_settings(home))
    text = _read(paths[0]) if paths else ""
    packed = []
    for spec in CEMU_SETTINGS:
        raw = xml_get(text, spec["xml"]) if text else None
        value = raw if raw is not None else spec["default"]
        if spec.get("kind") == "bool":
            value = _as_bool_token(value)
        packed.append(pack_setting(spec, value, use_global=True))
    return packed


# --- Eden live hotkeys (in-process Settings::values) -----------------------
# Disk writes do not update a running Eden. F10/F8/F9/Ctrl+U mutate memory.
# There is no resolution hotkey in Eden 0.2.1; F6 Restart Emulation also
# reuses in-memory Settings, so resolution still needs a process restart.

EDEN_HOTKEY_DEFAULTS = {
    "docked": "F10",
    "gpu": "F9",
    "filter": "F8",
    "speed": "Ctrl+U",
}
EDEN_HOTKEY_NEEDLES = {
    "docked": ("Change%20Docked%20Mode", "Change Docked Mode"),
    "gpu": ("Change%20GPU%20Mode", "Change GPU Mode"),
    "filter": ("Change%20Adapting%20Filter", "Change Adapting Filter"),
    "speed": ("Toggle%20Framerate%20Limit", "Toggle Framerate Limit"),
}
_QT_MODS = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "meta": "super",
    "super": "super",
}
_QT_KEYS = {
    "esc": "Escape",
    "escape": "Escape",
    "return": "Return",
    "enter": "Return",
    "space": "space",
    "tab": "Tab",
    "backspace": "BackSpace",
    "plus": "plus",
    "minus": "minus",
    "=": "equal",
    "-": "minus",
    ",": "comma",
    ".": "period",
}


def qt_keyseq_to_xdotool(seq: str) -> str:
    raw = (seq or "").strip().strip('"').replace(" ", "")
    if not raw:
        return ""
    mods: list[str] = []
    key = ""
    for part in raw.split("+"):
        if not part:
            continue
        mapped = _QT_MODS.get(part.lower())
        if mapped:
            mods.append(mapped)
            continue
        key = _QT_KEYS.get(part, _QT_KEYS.get(part.lower(), part if len(part) > 1 else part.lower()))
    if not key:
        return ""
    return "+".join([*mods, key])


def eden_keyseq_from_ini(text: str, needles: tuple[str, ...], default: str) -> str:
    for needle in needles:
        token = f"{needle}\\KeySeq="
        for line in text.splitlines():
            stripped = line.strip()
            if token not in stripped:
                continue
            if "Controller_KeySeq" in stripped or "\\KeySeq\\default=" in stripped:
                continue
            _head, _sep, rest = stripped.partition(token)
            if rest.startswith("\\"):
                continue
            value = rest.strip().strip('"')
            if value:
                return value
    return default


def load_eden_hotkeys(ini_text: str) -> dict[str, str]:
    return {
        name: qt_keyseq_to_xdotool(
            eden_keyseq_from_ini(ini_text, needles, EDEN_HOTKEY_DEFAULTS[name])
        )
        for name, needles in EDEN_HOTKEY_NEEDLES.items()
    }


def eden_hotswap_keys(
    key: str,
    old: str,
    new: str,
    hotkeys: dict[str, str] | None = None,
    *,
    filter_count: int | None = None,
) -> list[str]:
    """Return xdotool key names that move Eden's in-memory setting from old to new."""
    keys = hotkeys or {name: qt_keyseq_to_xdotool(seq) for name, seq in EDEN_HOTKEY_DEFAULTS.items()}
    if str(old) == str(new):
        return []
    if key == "use_docked_mode":
        seq = keys.get("docked") or ""
        return [seq] if seq else []
    if key == "use_speed_limit":
        seq = keys.get("speed") or ""
        return [seq] if seq else []
    if key == "gpu_accuracy":
        if {str(old), str(new)} <= {"0", "1"}:
            seq = keys.get("gpu") or ""
            return [seq] if seq else []
        return []
    if key == "scaling_filter":
        spec = setting_by_key("eden", "scaling_filter")
        options = spec.get("options") or []
        n = filter_count if filter_count is not None else max(len(options), 1)
        try:
            src = int(old)
            dst = int(new)
        except (TypeError, ValueError):
            return []
        steps = (dst - src) % n
        seq = keys.get("filter") or ""
        if not seq or steps == 0:
            return []
        return [seq] * steps
    return []


def current_setting_value(emu: str, home: Path, title_id: str, key: str) -> str:
    if emu == "eden":
        packed = read_eden(home, title_id)
    elif emu == "azahar":
        packed = read_azahar(home, title_id)
    else:
        packed = read_cemu(home)
    for item in packed:
        if item["key"] == key:
            return str(item["value"])
    return ""


def live_state_path(home: Path, proc_root: Path | None = None) -> Path:
    if proc_root is not None:
        return home / "emu-quick-eden-live.json"
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "emu-quick-eden-live.json"


def load_eden_live_state(home: Path, proc_root: Path | None = None) -> dict:
    pid = eden_pid(proc_root)
    path = live_state_path(home, proc_root)
    data: dict = {"pid": pid, "values": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        raw = {}
    if str(raw.get("pid") or "") == str(pid) and pid:
        values = raw.get("values") if isinstance(raw.get("values"), dict) else {}
        data["values"] = {str(k): str(v) for k, v in values.items()}
    return data


def store_eden_live_value(
    home: Path, key: str, value: str, proc_root: Path | None = None
) -> None:
    pid = eden_pid(proc_root)
    if not pid:
        return
    path = live_state_path(home, proc_root)
    data = load_eden_live_state(home, proc_root)
    data["pid"] = pid
    data.setdefault("values", {})[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def live_old_value(
    home: Path,
    scope: str,
    title_id: str,
    key: str,
    proc_root: Path | None = None,
) -> str:
    state = load_eden_live_state(home, proc_root)
    if key in state.get("values", {}):
        return str(state["values"][key])
    read_title = title_id if scope == "game" else ""
    return current_setting_value("eden", home, read_title, key)


def clear_eden_live_state(home: Path, proc_root: Path | None = None) -> None:
    path = live_state_path(home, proc_root)
    try:
        path.unlink()
    except OSError:
        pass


def eden_running_title(home: Path, proc_root: Path | None) -> str:
    return (detect_title("eden", home, proc_root).get("title_id") or "").upper()


def eden_game_overrides_key(home: Path, title_id: str, key: str) -> bool:
    if not title_id:
        return False
    custom = _read(custom_path("eden", home, title_id))
    if not custom:
        return False
    entry = ini_get(custom, key)
    return not ini_uses_global(entry, per_game=True)


def _xdotool_env(display: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DISPLAY"] = display
    authority = Path.home() / ".Xauthority"
    if authority.is_file():
        env.setdefault("XAUTHORITY", str(authority))
    return env


def _xdotool_lines(xdotool: str, display: str, extra: list[str]) -> list[str]:
    try:
        proc = subprocess.run(
            [xdotool, *extra],
            env=_xdotool_env(display),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def find_eden_x11_window() -> tuple[str, str] | None:
    xdotool = shutil.which("xdotool")
    if not xdotool:
        return None
    displays: list[str] = []
    for display in (":1", ":0", os.environ.get("DISPLAY") or ""):
        if display and display not in displays:
            displays.append(display)
    for display in displays:
        ids = _xdotool_lines(xdotool, display, ["search", "--class", "eden"])
        named: list[str] = []
        for wid in ids:
            names = _xdotool_lines(xdotool, display, ["getwindowname", wid])
            title = names[0] if names else ""
            if title.startswith("Eden"):
                named.append(wid)
        pick = named or ids
        if pick:
            return display, pick[0]
        named_ids = _xdotool_lines(xdotool, display, ["search", "--name", "Eden |"])
        if named_ids:
            return display, named_ids[0]
    return None


def send_eden_hotkeys(keys: list[str]) -> dict:
    if not keys:
        return {"sent": False, "reason": "no_keys"}
    xdotool = shutil.which("xdotool")
    if not xdotool:
        return {"sent": False, "reason": "no_xdotool"}
    found = find_eden_x11_window()
    if found is None:
        return {"sent": False, "reason": "no_window"}
    display, wid = found
    env = _xdotool_env(display)

    def run(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            env=env,
            capture_output=True,
            text=True,
            timeout=8,
        )

    try:
        # Prefer targeting the Eden window so QAM keeps focus / EmuPads mute.
        direct = run([xdotool, "key", "--window", wid, "--delay", "80", *keys])
        if direct.returncode == 0:
            return {
                "sent": True,
                "display": display,
                "window": wid,
                "keys": keys,
                "method": "window",
            }
        previous = _xdotool_lines(xdotool, display, ["getwindowfocus"])
        run([xdotool, "windowfocus", wid])
        run([xdotool, "windowactivate", wid])
        proc = run([xdotool, "key", "--delay", "80", *keys])
        if previous and previous[0] != wid:
            run([xdotool, "windowfocus", previous[0]])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"sent": False, "reason": "xdotool_failed", "error": str(exc)[:200]}
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "xdotool failed").strip()[:200]
        return {"sent": False, "reason": "xdotool_failed", "error": err}
    return {
        "sent": True,
        "display": display,
        "window": wid,
        "keys": keys,
        "method": "focus",
    }


def apply_eden_hotswap(
    home: Path,
    scope: str,
    title_id: str,
    key: str,
    old: str,
    new: str,
    proc_root: Path | None = None,
) -> dict:
    spec = setting_by_key("eden", key)
    hotkeys = load_eden_hotkeys(_read(eden_ini(home)))
    filter_count = len(spec.get("options") or []) if key == "scaling_filter" else None
    if old == "":
        old = live_old_value(home, scope, title_id, key, proc_root)
    keys = eden_hotswap_keys(key, old, new, hotkeys, filter_count=filter_count)
    result: dict = {
        "hotswap": "none",
        "hotswap_keys": keys,
        "hotswap_reason": "unchanged" if old == new else "no_hotkey",
        "sent": False,
        "live_from": old,
        "live_to": new,
    }
    if not keys:
        if old == new:
            return result
        if key == "resolution_setup":
            result["hotswap_reason"] = "no_hotkey"
        elif key == "gpu_accuracy" and "2" in {str(old), str(new)}:
            result["hotswap_reason"] = "gpu_extreme"
        return result
    running = emu_running("eden", proc_root)
    if not running:
        result["hotswap_reason"] = "not_running"
        return result
    running_tid = eden_running_title(home, proc_root)
    want_tid = (title_id or "").upper()
    if scope == "game":
        if not want_tid or want_tid != running_tid:
            result["hotswap_reason"] = "other_game"
            return result
    elif running_tid and eden_game_overrides_key(home, running_tid, key):
        result["hotswap_reason"] = "game_override"
        return result
    result["hotswap_reason"] = "live"
    if proc_root is not None:
        result["hotswap"] = "skipped"
        result["hotswap_reason"] = "test_proc"
        store_eden_live_value(home, key, new, proc_root)
        return result
    sent = send_eden_hotkeys(keys)
    result.update(sent)
    if sent.get("sent"):
        result["hotswap"] = "live"
        result["hotswap_reason"] = "live"
        store_eden_live_value(home, key, new, proc_root)
    else:
        result["hotswap"] = "skipped"
        result["hotswap_reason"] = sent.get("reason") or "send_failed"
    return result


def hotswap_message(key: str, info: dict) -> str | None:
    reason = info.get("hotswap_reason") or ""
    keys = info.get("hotswap_keys") or []
    shown = "+".join(keys[:1]) if keys else ""
    if info.get("hotswap") == "live":
        return f"Applied live in Eden ({shown})"
    if reason == "not_running":
        return "Applies on the next Eden launch."
    if reason == "no_hotkey" and key == "resolution_setup":
        return "Close and reopen Eden to apply resolution (no live hotkey in this build)."
    if reason == "gpu_extreme":
        return "GPU Extreme needs an Eden restart (F9 only toggles Normal/High)."
    if reason == "no_hotkey":
        return "Restart Eden to apply."
    if reason == "other_game":
        return "Saved for that game. Not applied live (a different title is running)."
    if reason == "game_override":
        return "Saved global. Running game has its own override — not applied live."
    if reason == "no_xdotool":
        return "Saved. Install xdotool for live apply, or press the Eden hotkey."
    if reason == "no_window":
        return f"Saved. Could not find the Eden window for {shown or 'the hotkey'}."
    if reason == "xdotool_failed":
        err = info.get("error") or "xdotool failed"
        return f"Saved. Live hotkey failed ({err})."
    if reason == "test_proc":
        return "Hotkey planned (test proc; not sent)."
    if reason == "unchanged":
        return None
    return None


def set_eden(home: Path, scope: str, title_id: str, key: str, value: str) -> list[str]:
    spec = setting_by_key("eden", key)
    if key in EDEN_PROTECTED:
        raise ValueError(f"{key} is protected")
    value = normalize_value(spec, value)
    messages: list[str] = []
    if scope == "global":
        path = eden_ini(home)
        old = _read(path)
        new = ini_set(old, spec["section"], key, value=value, mark_user=True)
        changed = _write(path, old, new)
        messages.append(f"{'Wrote' if changed else 'Kept'} global {key}={value}")
        return messages
    if not title_id:
        raise ValueError("Per-game Eden settings need a title id")
    path = custom_path("eden", home, title_id)
    old = _read(path)
    new = ini_set(
        old, spec["section"], key, value=value, use_global=False, mark_user=True
    )
    changed = _write(path, old, new)
    messages.append(
        f"{'Wrote' if changed else 'Kept'} {title_id} {key}={value} (this game)"
    )
    return messages


def set_azahar(home: Path, scope: str, title_id: str, key: str, value: str) -> list[str]:
    spec = setting_by_key("azahar", key)
    if key in AZAHAR_PROTECTED:
        raise ValueError(f"{key} is protected")
    value = normalize_value(spec, value)
    messages: list[str] = []
    if scope == "global":
        for path in existing(azahar_inis(home)) or [azahar_inis(home)[0]]:
            old = _read(path)
            new = ini_set(old, spec["section"], key, value=value, mark_user=True)
            changed = _write(path, old, new)
            messages.append(f"{'Wrote' if changed else 'Kept'} {path.name} {key}={value}")
        return messages
    if not title_id:
        raise ValueError("Per-game Azahar settings need a title id")
    bases = existing(azahar_inis(home)) or [azahar_inis(home)[0]]
    for ini in bases:
        path = custom_path("azahar", home, title_id, sibling=ini)
        old = _read(path)
        new = ini_set(
            old, spec["section"], key, value=value, use_global=False, mark_user=True
        )
        changed = _write(path, old, new)
        messages.append(
            f"{'Wrote' if changed else 'Kept'} {path.name} {key}={value} (this game)"
        )
    return messages


def set_cemu(home: Path, key: str, value: str) -> list[str]:
    spec = setting_by_key("cemu", key)
    if key in CEMU_PROTECTED:
        raise ValueError(f"{key} is protected")
    value = normalize_value(spec, value)
    xml_value = value
    messages: list[str] = []
    for path in existing(cemu_settings(home)) or [cemu_settings(home)[0]]:
        old = _read(path) or (
            "<?xml version='1.0' encoding='UTF-8'?>\n<content>\n</content>\n"
        )
        new = xml_set(old, spec["xml"], xml_value)
        changed = _write(path, old, new)
        messages.append(f"{'Wrote' if changed else 'Kept'} {path.name} {key}={value}")
    return messages


def reset_ini_keys(
    path: Path, specs: list[dict], *, per_game: bool, protected: set[str]
) -> bool:
    if per_game and not path.is_file():
        return False
    old = _read(path)
    new = old
    for spec in specs:
        key = spec["key"]
        if key in protected:
            continue
        if per_game:
            new = ini_set(new, spec["section"], key, use_global=True, mark_user=False)
        else:
            new = ini_set(
                new,
                spec["section"],
                key,
                value=spec["default"],
                mark_user=True,
            )
    return _write(path, old, new)


def reset_eden(home: Path, scope: str, title_id: str) -> list[str]:
    if scope == "global":
        path = eden_ini(home)
        changed = reset_ini_keys(path, EDEN_SETTINGS, per_game=False, protected=EDEN_PROTECTED)
        return [f"{'Reset' if changed else 'Already'} global Eden quick settings"]
    if not title_id:
        raise ValueError("Per-game reset needs a title id")
    path = custom_path("eden", home, title_id)
    changed = reset_ini_keys(path, EDEN_SETTINGS, per_game=True, protected=EDEN_PROTECTED)
    return [f"{'Reset' if changed else 'Already'} {title_id} to global Eden settings"]


def reset_azahar(home: Path, scope: str, title_id: str) -> list[str]:
    messages: list[str] = []
    if scope == "global":
        for path in existing(azahar_inis(home)) or [azahar_inis(home)[0]]:
            changed = reset_ini_keys(
                path, AZAHAR_SETTINGS, per_game=False, protected=AZAHAR_PROTECTED
            )
            messages.append(
                f"{'Reset' if changed else 'Already'} {path.name} Azahar quick settings"
            )
        return messages
    if not title_id:
        raise ValueError("Per-game reset needs a title id")
    for ini in existing(azahar_inis(home)) or [azahar_inis(home)[0]]:
        path = custom_path("azahar", home, title_id, sibling=ini)
        changed = reset_ini_keys(
            path, AZAHAR_SETTINGS, per_game=True, protected=AZAHAR_PROTECTED
        )
        messages.append(
            f"{'Reset' if changed else 'Already'} {path.name} to global Azahar settings"
        )
    return messages


def reset_cemu(home: Path) -> list[str]:
    messages: list[str] = []
    for path in existing(cemu_settings(home)) or [cemu_settings(home)[0]]:
        old = _read(path)
        if not old:
            messages.append(f"Missing {path}")
            continue
        new = old
        for spec in CEMU_SETTINGS:
            new = xml_set(new, spec["xml"], spec["default"] if spec.get("kind") != "bool" else spec["default"])
        changed = _write(path, old, new)
        messages.append(f"{'Reset' if changed else 'Already'} {path.name} Cemu quick settings")
    return messages


# --- Status / CLI ----------------------------------------------------------


def emu_payload(
    emu: str,
    home: Path,
    proc_root: Path | None = None,
    title_id: str = "",
) -> dict:
    detected = detect_title(emu, home, proc_root)
    if title_id:
        tid = title_id.upper()
        names = scan_title_names(home)
        detected = {
            "title_id": tid,
            "title": names.get(tid) or detected.get("title") or tid,
            "rom": detected.get("rom") or "",
        }
    title_id = detected.get("title_id") or ""
    running = emu_running(emu, proc_root)
    if emu == "eden":
        settings = read_eden(home, title_id)
        per_game = True
        note = (
            "Console, scaling filter, GPU Normal/High, and speed limit apply live "
            "while Eden is running (not written until Save). Resolution needs a full Eden restart after Save."
            if running
            else "Save writes settings for the next Eden launch. Live rows apply in-game without saving."
        )
    elif emu == "azahar":
        settings = read_azahar(home, title_id)
        per_game = True
        note = "Restart Azahar to apply. Dual-screen layout stays untouched."
    else:
        settings = read_cemu(home)
        per_game = False
        note = "Restart Cemu to apply. Fullscreen and GamePad geometry stay untouched."
    return {
        "running": running,
        "title_id": title_id,
        "title": detected.get("title") or "",
        "rom": detected.get("rom") or "",
        "per_game": per_game,
        "scope_default": "game" if running and title_id and per_game else "global",
        "games": known_games(emu, home),
        "settings": settings,
        "note": note,
    }


def fill_title_id(
    emu: str,
    home: Path,
    title_id: str,
    proc_root: Path | None = None,
) -> str:
    tid = (title_id or "").strip().upper()
    if tid:
        return tid
    return (detect_title(emu, home, proc_root).get("title_id") or "").upper()


def status_payload(
    home: Path,
    proc_root: Path | None = None,
    *,
    emu: str = "",
    title: str = "",
) -> dict:
    titles = {emu: title} if emu and title else {}
    emus = {
        name: emu_payload(name, home, proc_root, titles.get(name, ""))
        for name in ("eden", "azahar", "cemu")
    }
    active = "eden"
    for name in ("eden", "azahar", "cemu"):
        if emus[name]["running"]:
            active = name
            break
    return {
        "ok": True,
        "active": active,
        "apply": emus[active]["note"],
        "emus": emus,
    }


def do_set(
    emu: str,
    scope: str,
    title_id: str,
    key: str,
    value: str,
    home: Path,
    proc_root: Path | None = None,
    *,
    live_only: bool = False,
    write: bool = True,
) -> dict:
    emu = emu.lower()
    scope = (scope or "global").lower()
    if scope not in {"global", "game"}:
        raise ValueError(f"Unknown scope {scope}")
    if scope == "game":
        title_id = fill_title_id(emu, home, title_id, proc_root)
    if live_only:
        write = False
    hotswap: dict = {"hotswap": "none", "hotswap_keys": [], "hotswap_reason": "not_eden"}
    messages: list[str] = []
    if emu == "cemu":
        if write:
            messages = set_cemu(home, key, value)
        hotswap["hotswap_reason"] = "restart"
    elif emu == "eden":
        spec = setting_by_key("eden", key)
        new = normalize_value(spec, value)
        old = live_old_value(home, scope, title_id, key, proc_root)
        if write:
            messages = set_eden(home, scope, title_id, key, value)
        hotswap = apply_eden_hotswap(
            home,
            scope,
            title_id,
            key,
            old,
            new,
            proc_root=proc_root,
        )
        extra = hotswap_message(key, hotswap)
        if extra and write:
            messages.append(extra)
        elif extra and live_only and hotswap.get("hotswap") not in {"live", "skipped"}:
            messages.append(extra)
        elif live_only and hotswap.get("hotswap") in {"live", "skipped"}:
            messages.append(f"Live {key}={new}")
    elif emu == "azahar":
        if write:
            messages = set_azahar(home, scope, title_id, key, value)
            messages.append("Restart Azahar to apply.")
        hotswap["hotswap_reason"] = "restart"
    else:
        raise ValueError(f"Unknown emu {emu}")
    if live_only and emu != "eden":
        messages = ["Not a live Eden setting"]
        hotswap["hotswap_reason"] = "not_eden"
    out = {"ok": True, "messages": messages, "message": " ".join(messages)}
    out.update(
        {
            "hotswap": hotswap.get("hotswap") or "none",
            "hotswap_keys": hotswap.get("hotswap_keys") or [],
            "hotswap_reason": hotswap.get("hotswap_reason") or "",
            "wrote": write,
        }
    )
    return out


def do_save(
    emu: str,
    scope: str,
    title_id: str,
    values: dict[str, str],
    home: Path,
    proc_root: Path | None = None,
) -> dict:
    emu = emu.lower()
    scope = (scope or "global").lower()
    if scope not in {"global", "game"}:
        raise ValueError(f"Unknown scope {scope}")
    if scope == "game":
        title_id = fill_title_id(emu, home, title_id, proc_root)
    if not values:
        return {"ok": True, "messages": ["Nothing to save"], "message": "Nothing to save", "wrote": False}
    messages: list[str] = []
    for key, value in values.items():
        if emu == "cemu":
            messages.extend(set_cemu(home, key, value))
        elif emu == "eden":
            messages.extend(set_eden(home, scope, title_id, key, value))
        elif emu == "azahar":
            messages.extend(set_azahar(home, scope, title_id, key, value))
        else:
            raise ValueError(f"Unknown emu {emu}")
    hint = "Saved for the next launch."
    if emu == "eden":
        hint = "Saved. Live settings already match in-game; others apply after an Eden restart."
    elif emu == "azahar":
        hint = "Saved. Restart Azahar to apply."
    else:
        hint = "Saved. Restart Cemu to apply."
    messages.append(hint)
    return {
        "ok": True,
        "messages": messages,
        "message": " ".join(messages),
        "wrote": True,
        "hotswap": "none",
    }


def do_reset(
    emu: str,
    scope: str,
    title_id: str,
    home: Path,
    proc_root: Path | None = None,
) -> dict:
    emu = emu.lower()
    scope = (scope or "global").lower()
    if scope == "game":
        title_id = fill_title_id(emu, home, title_id, proc_root)
    if emu == "cemu":
        messages = reset_cemu(home)
    elif emu == "eden":
        messages = reset_eden(home, scope, title_id)
    elif emu == "azahar":
        messages = reset_azahar(home, scope, title_id)
    else:
        raise ValueError(f"Unknown emu {emu}")
    return {"ok": True, "messages": messages, "message": " ".join(messages)}


def _load_bind():
    """bind-gamepad.py owns SIGTERM + Steam relaunch. Do not match Sunshine."""
    path = Path(__file__).with_name("bind-gamepad.py")
    spec = importlib.util.spec_from_file_location("bind_gamepad_restart", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def do_restart(
    emu: str,
    *,
    proc_root: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """SIGTERM Cemu / Azahar / Eden, then steam://rungameid or re-exec.

    Does not restart the mux. Does not match Sunshine / Steam / gamescope.
    """
    emu = (emu or "all").strip().lower()
    if emu not in ("all", "eden", "azahar", "cemu"):
        raise ValueError(f"Unknown emu {emu}")
    bind = _load_bind()
    targets = ("cemu", "azahar", "eden") if emu == "all" else (emu,)
    messages, ok = bind.restart_emulators(
        targets, proc_root=proc_root, dry_run=dry_run
    )
    return {
        "ok": ok,
        "emu": emu,
        "messages": messages,
        "message": " ".join(messages),
    }


def _print(data: dict, rc: int = 0) -> int:
    json.dump(data, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eden / Azahar / Cemu quick settings")
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--home", default=None)
    shared.add_argument("--proc", default=None, help="Fake /proc for tests")
    parser.add_argument("--home", default=None)
    parser.add_argument("--proc", default=None, help="Fake /proc for tests")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", parents=[shared])
    p_status.add_argument("--emu", default="", choices=("eden", "azahar", "cemu"))
    p_status.add_argument("--title", default="")
    p_set = sub.add_parser("set", parents=[shared])
    p_set.add_argument("--emu", required=True, choices=("eden", "azahar", "cemu"))
    p_set.add_argument("--scope", default="global", choices=("global", "game"))
    p_set.add_argument("--title", default="")
    p_set.add_argument("--key", required=True)
    p_set.add_argument("--value", required=True)
    p_set.add_argument(
        "--live",
        action="store_true",
        help="Send Eden hotkeys only; do not write INI",
    )
    p_save = sub.add_parser("save", parents=[shared])
    p_save.add_argument("--emu", required=True, choices=("eden", "azahar", "cemu"))
    p_save.add_argument("--scope", default="global", choices=("global", "game"))
    p_save.add_argument("--title", default="")
    p_save.add_argument(
        "--values",
        required=True,
        help="JSON object of key -> value to write",
    )
    p_reset = sub.add_parser("reset", parents=[shared])
    p_reset.add_argument("--emu", required=True, choices=("eden", "azahar", "cemu"))
    p_reset.add_argument("--scope", default="global", choices=("global", "game"))
    p_reset.add_argument("--title", default="")
    p_restart = sub.add_parser("restart", parents=[shared])
    p_restart.add_argument(
        "--emu",
        default="all",
        choices=("all", "eden", "azahar", "cemu"),
        help="Running emulator to SIGTERM then relaunch via Steam",
    )
    p_restart.add_argument("--dry-run", dest="dry_run", action="store_true")
    args = parser.parse_args(argv)
    home = home_dir(args.home)
    proc = Path(args.proc) if args.proc else None
    try:
        if args.cmd == "status":
            return _print(
                status_payload(
                    home, proc, emu=getattr(args, "emu", "") or "", title=args.title
                )
            )
        if args.cmd == "set":
            data = do_set(
                args.emu,
                args.scope,
                args.title,
                args.key,
                args.value,
                home,
                proc_root=proc,
                live_only=bool(getattr(args, "live", False)),
            )
            data.update(status_payload(home, proc, emu=args.emu, title=args.title))
            data["ok"] = True
            return _print(data)
        if args.cmd == "save":
            try:
                raw_values = json.loads(args.values)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid --values JSON: {exc}") from exc
            if not isinstance(raw_values, dict):
                raise ValueError("--values must be a JSON object")
            values = {str(k): str(v) for k, v in raw_values.items()}
            data = do_save(
                args.emu, args.scope, args.title, values, home, proc_root=proc
            )
            data.update(status_payload(home, proc, emu=args.emu, title=args.title))
            data["ok"] = True
            return _print(data)
        if args.cmd == "reset":
            data = do_reset(args.emu, args.scope, args.title, home, proc_root=proc)
            clear_eden_live_state(home, proc)
            data.update(status_payload(home, proc, emu=args.emu, title=args.title))
            data["ok"] = True
            return _print(data)
        if args.cmd == "restart":
            data = do_restart(
                getattr(args, "emu", "all") or "all",
                proc_root=proc,
                dry_run=bool(getattr(args, "dry_run", False)),
            )
            return _print(data, 0 if data.get("ok") else 1)
    except (ValueError, KeyError) as exc:
        return _print({"ok": False, "message": str(exc)}, 2)
    return _print({"ok": False, "message": "unknown command"}, 1)


if __name__ == "__main__":
    sys.exit(main())
