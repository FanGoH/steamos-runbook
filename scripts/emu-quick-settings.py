#!/usr/bin/env python3
"""Read and write Eden / Azahar / Cemu quick settings (global or per-game).

Decky Emu Quick calls this as user deck. Do not touch pad binds, dual-screen
layout, fullscreen_mode, or Engage's 4GB memory pin.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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
        "label": "Console",
        "kind": "enum",
        "default": "true",
        "options": _enum([("false", "Handheld"), ("true", "Docked")]),
        "normalize": "bool",
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
    },
    {
        "key": "gpu_accuracy",
        "section": "Renderer",
        "label": "GPU accuracy",
        "kind": "enum",
        "default": "0",
        "options": _enum([("0", "Normal"), ("1", "High"), ("2", "Extreme")]),
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
    },
    {
        "key": "anti_aliasing",
        "section": "Renderer",
        "label": "Anti-aliasing",
        "kind": "enum",
        "default": "0",
        "options": _enum([("0", "None"), ("1", "FXAA"), ("2", "SMAA")]),
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
    },
    {
        "key": "use_speed_limit",
        "section": "Core",
        "label": "Limit speed",
        "kind": "bool",
        "default": "true",
        "normalize": "bool",
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
    },
    {
        "key": "use_vsync",
        "section": "Renderer",
        "label": "VSync",
        "kind": "bool",
        "default": "true",
        "normalize": "bool",
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
    },
    {
        "key": "graphics_api",
        "section": "Renderer",
        "label": "Renderer",
        "kind": "enum",
        "default": "2",
        "options": _enum([("1", "OpenGL"), ("2", "Vulkan")]),
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
    log = eden_log(home)
    if log.is_file():
        try:
            blob = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            blob = ""
        for match in BOOT_RE.finditer(blob):
            names.setdefault(match.group(1).upper(), match.group(2).strip())
    return names


def detect_title(emu: str, home: Path, proc_root: Path | None = None) -> dict[str, str]:
    names = scan_title_names(home)
    for args in running_cmdlines(emu, proc_root):
        rom = rom_from_args(args)
        if not rom:
            continue
        tid = title_id_from_text(rom, emu)
        if tid:
            return {
                "title_id": tid,
                "title": names.get(tid) or Path(rom).stem,
                "rom": rom,
            }
        stem = Path(rom).stem
        return {"title_id": "", "title": stem, "rom": rom}
    if emu == "eden":
        log = eden_log(home)
        if log.is_file() and emu_running(emu, proc_root):
            try:
                blob = log.read_text(encoding="utf-8", errors="replace")
            except OSError:
                blob = ""
            matches = list(BOOT_RE.finditer(blob))
            if matches:
                tid = matches[-1].group(1).upper()
                return {
                    "title_id": tid,
                    "title": matches[-1].group(2).strip(),
                    "rom": "",
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
                tid = title_id_from_text(rom, "cemu") or ""
                return {
                    "title_id": tid,
                    "title": names.get(tid) or Path(rom).stem,
                    "rom": rom,
                }
    return {"title_id": "", "title": "", "rom": ""}


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
    elif emu == "azahar":
        settings = read_azahar(home, title_id)
        per_game = True
    else:
        settings = read_cemu(home)
        per_game = False
    return {
        "running": running,
        "title_id": title_id,
        "title": detected.get("title") or "",
        "rom": detected.get("rom") or "",
        "per_game": per_game,
        "scope_default": "game" if running and title_id and per_game else "global",
        "games": known_games(emu, home),
        "settings": settings,
        "note": "Restart the game to apply. Dual-screen layout and pad binds stay untouched.",
    }


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
        "apply": "Restart the game to apply.",
        "emus": emus,
    }


def do_set(
    emu: str,
    scope: str,
    title_id: str,
    key: str,
    value: str,
    home: Path,
) -> dict:
    emu = emu.lower()
    scope = (scope or "global").lower()
    if scope not in {"global", "game"}:
        raise ValueError(f"Unknown scope {scope}")
    if emu == "cemu":
        messages = set_cemu(home, key, value)
    elif emu == "eden":
        messages = set_eden(home, scope, title_id, key, value)
    elif emu == "azahar":
        messages = set_azahar(home, scope, title_id, key, value)
    else:
        raise ValueError(f"Unknown emu {emu}")
    return {"ok": True, "messages": messages, "message": " ".join(messages)}


def do_reset(emu: str, scope: str, title_id: str, home: Path) -> dict:
    emu = emu.lower()
    scope = (scope or "global").lower()
    if emu == "cemu":
        messages = reset_cemu(home)
    elif emu == "eden":
        messages = reset_eden(home, scope, title_id)
    elif emu == "azahar":
        messages = reset_azahar(home, scope, title_id)
    else:
        raise ValueError(f"Unknown emu {emu}")
    return {"ok": True, "messages": messages, "message": " ".join(messages)}


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
    p_reset = sub.add_parser("reset", parents=[shared])
    p_reset.add_argument("--emu", required=True, choices=("eden", "azahar", "cemu"))
    p_reset.add_argument("--scope", default="global", choices=("global", "game"))
    p_reset.add_argument("--title", default="")
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
            data = do_set(args.emu, args.scope, args.title, args.key, args.value, home)
            data.update(status_payload(home, proc, emu=args.emu, title=args.title))
            data["ok"] = True
            return _print(data)
        if args.cmd == "reset":
            data = do_reset(args.emu, args.scope, args.title, home)
            data.update(status_payload(home, proc, emu=args.emu, title=args.title))
            data["ok"] = True
            return _print(data)
    except (ValueError, KeyError) as exc:
        return _print({"ok": False, "message": str(exc)}, 2)
    return _print({"ok": False, "message": "unknown command"}, 1)


if __name__ == "__main__":
    sys.exit(main())
