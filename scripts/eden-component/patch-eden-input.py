#!/usr/bin/env python3
"""Bind Eden player 0 to whichever real pad is plugged in at launch.

Skip motherboard LED and gamescope mouse js nodes. Prefer a physical
Xbox (not Sunshine), then Switch Pro, then Steam's virtual pad (the
wrapped held controller), then Sunshine, then the first remaining
joystick. Sunshine is a fallback — it is injected even during local
play, and Steam hides that Xbox ID from SDL. SDL GUID is USB bus +
vendor/product/version with no name-CRC — the form Eden's UI writes
for Xbox One.

If nothing is present, leave the existing player-0 GUID (last session)
and only keep the Joy-Con HID driver off.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import struct
import sys

INPUT_ROOT = Path("/sys/class/input")
SKIP_VENDORS = {"0000", "001f", "26ce", "046d", "beef"}


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def list_joysticks(root: Path = INPUT_ROOT) -> list[dict[str, str]]:
    pads = []
    for js in sorted(root.glob("js*/device")):
        vendor = _read(js / "id" / "vendor").lower().zfill(4)[-4:]
        product = _read(js / "id" / "product").lower().zfill(4)[-4:]
        version = _read(js / "id" / "version").lower().zfill(4)[-4:]
        name = _read(js / "name")
        if not vendor or vendor in SKIP_VENDORS:
            continue
        pads.append(
            {
                "vendor": vendor,
                "product": product,
                "version": version or "0000",
                "name": name,
            }
        )
    return pads


def _is_sunshine(pad: dict[str, str]) -> bool:
    return "sunshine" in pad["name"].lower()


def pick_pad(pads: list[dict[str, str]]) -> dict[str, str] | None:
    if not pads:
        return None
    for pad in pads:
        if pad["vendor"] == "045e" and not _is_sunshine(pad):
            return pad
    for pad in pads:
        if pad["vendor"] == "057e" and pad["product"] == "2009":
            return pad
    for pad in pads:
        if pad["vendor"] == "28de" and pad["product"] == "11ff":
            return pad
    for pad in pads:
        if _is_sunshine(pad):
            return pad
    return pads[0]


def sdl_guid(vendor: str, product: str, version: str = "0000") -> str:
    raw = struct.pack(
        "<HHHHHHHH",
        0x0003,
        0,
        int(vendor, 16),
        0,
        int(product, 16),
        0,
        int(version or "0", 16),
        0,
    )
    return raw.hex()


def guid_for_current_pad(root: Path = INPUT_ROOT) -> str | None:
    pad = pick_pad(list_joysticks(root))
    if pad is None:
        return None
    return sdl_guid(pad["vendor"], pad["product"], pad["version"])


def _set_kv(line: str, key: str, value: str) -> str:
    if line.startswith(f"{key}=") and not line.startswith(f"{key}\\"):
        return f"{key}={value}\n"
    if line.startswith(f"{key}\\default="):
        return f"{key}\\default=false\n"
    if line.startswith(f"{key}\\use_global="):
        return f"{key}\\use_global=false\n"
    return line


def pin_4gb_layout(text: str) -> str:
    """Force 4GB guest DRAM so a 15G cart can boot on 14GB hosts.

    Per-game `memory_layout_mode=0` is ignored while use_global=true, and
    the global default is 8GB — that plus the cart working set is what
    earlyoom SIGTERMs at ~12–16 GB RSS. 0 = 4GB, 1 = 6GB, 2 = 8GB.
    """
    out = []
    for line in text.splitlines(keepends=True):
        line = _set_kv(line, "memory_layout_mode", "0")
        out.append(line)
    return "".join(out)


def patch(text: str, guid: str | None) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("enable_joycon_driver=") and "true" in line:
            line = "enable_joycon_driver=false\n"
        elif line.startswith("enable_joycon_driver\\default=") and "true" in line:
            line = "enable_joycon_driver\\default=false\n"
        elif guid and line.startswith("player_0_") and "engine:sdl" in line:
            line = re.sub(r",guid:[0-9a-fA-F]+", "", line)
            if f"guid:{guid}" not in line:
                line = line.replace(
                    "engine:sdl,port:0,",
                    f"engine:sdl,port:0,guid:{guid},",
                )
        else:
            # Exclusive fullscreen on gamescope leaves Steam on Launching
            # while RSS climbs until earlyoom SIGTERMs Eden. Borderless
            # still fills the nested window. Async shaders let a frame
            # present before the pipeline cache is finished.
            line = _set_kv(line, "fullscreen_mode", "0")
            line = _set_kv(line, "fullscreen", "true")
            line = _set_kv(line, "showStatusBar", "false")
            line = _set_kv(line, "use_asynchronous_shaders", "true")
        out.append(line)
    return "".join(out)


TITLE_ID_RE = re.compile(r"\[(0100[0-9A-Fa-f]{12})\]")
FPS_DIR_RE = re.compile(r"(60[-_]?fps|60-30fps|lm360)", re.I)
PATCH_SUFFIXES = {".ips", ".pchtxt"}


def _title_ids_in(game_dir: Path) -> set[str]:
    found: set[str] = set()
    for path in game_dir.rglob("*"):
        match = TITLE_ID_RE.search(path.name)
        if match:
            found.add(match.group(1).upper())
        if path.is_file() and path.suffix.lower() == ".pchtxt":
            try:
                head = path.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                continue
            for match in TITLE_ID_RE.finditer(head):
                found.add(match.group(1).upper())
    return found


def _already_have(load_root: Path, title_id: str, filename: str, data: bytes) -> bool:
    root = load_root / title_id
    if not root.is_dir():
        return False
    for existing in root.rglob(filename):
        try:
            if existing.read_bytes() == data:
                return True
        except OSError:
            continue
    return False


def _copy_patch_dir(
    src: Path, load_root: Path, title_ids: set[str], mod_name: str
) -> list[str]:
    files = [
        p
        for p in src.iterdir()
        if p.is_file() and p.suffix.lower() in PATCH_SUFFIXES
    ]
    if not files or not title_ids:
        return []
    installed: list[str] = []
    for title_id in sorted(title_ids):
        dest = load_root / title_id / mod_name / "exefs"
        dest.mkdir(parents=True, exist_ok=True)
        for src_file in files:
            data = src_file.read_bytes()
            if _already_have(load_root, title_id, src_file.name, data):
                continue
            target = dest / src_file.name
            shutil.copy2(src_file, target)
            installed.append(str(target))
    return installed


def ensure_fps_mods(home: Path) -> list[str]:
    """Copy ROM-folder 60fps patches into Eden's load/<title>/ tree.

    Atmosphere `exefs_patches/` and loose `*60fps*/exefs/` next to a dump are
    not read by Eden. Luigi's 1.4.0 IPS never applied for that reason.
    """
    load_root = home / ".local/share/eden/load"
    installed: list[str] = []
    for switch in (
        home / "retrodeck/roms/switch",
        home / "emulation/switch/games",
    ):
        if not switch.is_dir():
            continue
        for game_dir in sorted(switch.iterdir()):
            if not game_dir.is_dir() or game_dir.name.startswith("_"):
                continue
            title_ids = _title_ids_in(game_dir)
            bases = {tid for tid in title_ids if tid.endswith("000")}
            if bases:
                title_ids = bases
            patches = game_dir / "exefs_patches"
            if patches.is_dir():
                for mod_dir in sorted(patches.iterdir()):
                    if not mod_dir.is_dir():
                        continue
                    if not FPS_DIR_RE.search(mod_dir.name):
                        continue
                    installed.extend(
                        _copy_patch_dir(mod_dir, load_root, title_ids, mod_dir.name)
                    )
            for child in game_dir.iterdir():
                if not child.is_dir() or not FPS_DIR_RE.search(child.name):
                    continue
                exefs = child / "exefs"
                src = exefs if exefs.is_dir() else child
                installed.extend(
                    _copy_patch_dir(src, load_root, title_ids, child.name)
                )
    return installed


def _write_if_changed(path: Path, text: str, new: str, msg: str) -> int:
    if new == text:
        print(msg)
        return 0
    bak = path.with_suffix(path.suffix + ".bak-steam-virtual")
    if not bak.exists():
        bak.write_text(text)
    path.write_text(new)
    print(msg)
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--pin-4gb":
        path = Path(sys.argv[2])
        if not path.is_file():
            print(f"skip: no {path}")
            return 0
        text = path.read_text()
        new = pin_4gb_layout(text)
        return _write_if_changed(
            path, text, new, f"Pinned 4GB memory layout in {path}"
        )
    if len(sys.argv) == 2 and sys.argv[1] == "--ensure-fps-mods":
        placed = ensure_fps_mods(Path.home())
        if placed:
            for path in placed:
                print(f"installed Eden 60fps patch {path}")
        else:
            print("Eden 60fps patches already in load/")
        return 0
    if len(sys.argv) != 2:
        print(
            f"usage: {sys.argv[0]} /path/to/qt-config.ini\n"
            f"       {sys.argv[0]} --pin-4gb /path/to/custom.ini\n"
            f"       {sys.argv[0]} --ensure-fps-mods",
            file=sys.stderr,
        )
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"skip: no {path}")
        return 0
    guid = guid_for_current_pad()
    text = path.read_text()
    new = patch(text, guid)
    for placed in ensure_fps_mods(Path.home()):
        print(f"installed Eden 60fps patch {placed}")
    if new == text:
        if guid:
            print(f"Eden player 0 already bound to {guid} in {path}")
        else:
            print(f"No joystick yet; left Eden player 0 as-is in {path}")
        return 0
    return _write_if_changed(
        path, text, new, f"Bound Eden player 0 to current pad {guid} in {path}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
