#!/usr/bin/env python3
"""Steam shortcut LaunchOptions helper, plus empty-argv dump lookup.

Tender/decky-romm-sync tiles (Xenoblade, Luigi) often have an empty launch
line. Steam Game Mode also rewrites shortcuts.vdf while it is running, so
writing LaunchOptions does not stick until a Steam restart.

`--rom-for-appid` maps SteamAppId → shortcuts.vdf AppName → a dump (Switch
folder, or Tender `rom_installs.file_path`). `--launch-options-for-appid`
prints the Steam LaunchOptions line so empty-argv tiles work for PS2 too.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import struct
import sys
import tempfile
from pathlib import Path


def set_launch_options(data: bytes, app_name: str, new_lo: str) -> bytes:
    key = b"\x01AppName\x00" + app_name.encode("utf-8") + b"\x00"
    start = data.find(key)
    if start < 0:
        raise KeyError(app_name)
    nxt = data.find(b"\x01AppName\x00", start + len(key))
    end = nxt if nxt >= 0 else len(data)
    chunk = data[start:end]
    lo_key = b"\x01LaunchOptions\x00"
    k = chunk.find(lo_key)
    if k < 0:
        raise KeyError(f"LaunchOptions for {app_name}")
    val_start = k + len(lo_key)
    val_end = chunk.find(b"\x00", val_start)
    if val_end < 0:
        raise ValueError(f"unterminated LaunchOptions for {app_name}")
    new_chunk = chunk[:val_start] + new_lo.encode("utf-8") + chunk[val_end:]
    return data[:start] + new_chunk + data[end:]


def patch_file(path: Path, updates: dict[str, str]) -> None:
    data = path.read_bytes()
    orig = data
    for name, lo in updates.items():
        data = set_launch_options(data, name, lo)
    if data == orig:
        print(f"unchanged {path}")
        return
    bak = path.with_suffix(path.suffix + ".bak-eden-lo")
    if not bak.exists():
        shutil.copy2(path, bak)
    path.write_bytes(data)
    print(f"updated {path}")


SWITCH = Path.home() / "retrodeck/roms/switch"
RD = 'flatpak run net.retrodeck.retrodeck -e "%EMULATOR_RYUBING% %ROM%"'


def _rd(path: Path) -> str:
    return f'{RD} "{path}"'


def updates() -> dict[str, str]:
    luigi = next(
        SWITCH.joinpath("Luigi's Mansion 3").glob("*0100DCA0064A6000*.nsp")
    )
    kirby = SWITCH.joinpath(
        "Kirby's Return to Dream Land Deluxe",
        "Kirbys Return to Dream Land Deluxe [01006B601380E000][v0].nsp",
    )
    return {
        "Xenoblade Chronicles 3": _rd(
            SWITCH / "Xenoblade Chronicles 3" / "Xenoblade Chronicles 3.xci"
        ),
        "Luigi's Mansion 3": _rd(luigi),
        "Kirby's Return to Dream Land Deluxe": _rd(kirby),
    }


def find_shortcut_vdfs(home: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for root in (
        home / ".local/share/Steam/userdata",
        home / ".steam/steam/userdata",
    ):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/config/shortcuts.vdf")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(path)
    return found


def _nul_str(data: bytes, start: int) -> tuple[str, int]:
    end = data.find(b"\x00", start)
    if end < 0:
        raise ValueError("unterminated vdf string")
    return data[start:end].decode("utf-8", "replace"), end + 1


def iter_shortcuts(data: bytes) -> list[dict[str, object]]:
    """Yield {appid, AppName, LaunchOptions} for each shortcuts.vdf entry."""
    key = b"\x01AppName\x00"
    out: list[dict[str, object]] = []
    i = 0
    while True:
        j = data.find(key, i)
        if j < 0:
            break
        name, after_name = _nul_str(data, j + len(key))
        nxt = data.find(key, after_name)
        look = data[max(0, j - 64) : j]
        appid = None
        k = look.rfind(b"\x02appid\x00")
        if k >= 0 and k + 7 + 4 <= len(look):
            appid = struct.unpack_from("<I", look, k + 7)[0]
        chunk = data[j : nxt if nxt >= 0 else len(data)]
        lo = ""
        lk = chunk.find(b"\x01LaunchOptions\x00")
        if lk >= 0:
            lo, _ = _nul_str(chunk, lk + len(b"\x01LaunchOptions\x00"))
        out.append({"appid": appid, "AppName": name, "LaunchOptions": lo})
        i = after_name
    return out


def normalize_appid(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("empty appid")
    n = int(text, 16) if text.lower().startswith("0x") else int(text, 10)
    if n > 0xFFFFFFFF:
        # Steam GameID: appid in the high 32 bits, type in bits 24-31
        # (shortcut = 0x02 → low half 0x02000000). Do not treat that flag as
        # the shortcut appid.
        hi = n >> 32
        n = hi if hi else (n & 0xFFFFFFFF)
    else:
        n = n & 0xFFFFFFFF
    if n == 0:
        raise ValueError("zero appid")
    return str(n)


def pick_switch_dump(target: Path) -> Path | None:
    if target.is_file() and target.suffix.lower() in {".xci", ".nsp"}:
        return target
    if not target.is_dir():
        return None
    xcis: list[Path] = []
    nsps: list[Path] = []
    for path in target.rglob("*"):
        if not path.is_file():
            continue
        suf = path.suffix.lower()
        name = path.name.lower()
        if suf == ".xci":
            xcis.append(path)
        elif suf == ".nsp":
            if "dlc" in name or "multiplayer pack" in name:
                continue
            nsps.append(path)
    if xcis:
        return max(xcis, key=lambda p: p.stat().st_size)
    if nsps:
        return max(nsps, key=lambda p: p.stat().st_size)
    return None


LAUNCHABLE_EXT = {
    ".xci",
    ".nsp",
    ".iso",
    ".chd",
    ".cso",
    ".zso",
    ".ciso",
    ".m3u",
    ".rvz",
    ".wux",
    ".wud",
    ".gba",
    ".z64",
    ".n64",
    ".3ds",
}
ARCHIVE_EXT = {".zip", ".rar", ".7z"}
TENDER_DB = Path("homebrew/data/romm-tender/romm_sync.db")


def pick_launchable_dump(target: Path) -> Path | None:
    """Largest emulator-readable dump under *target*, or the file itself."""
    switch = pick_switch_dump(target)
    if switch is not None:
        return switch
    if target.is_file() and target.suffix.lower() in LAUNCHABLE_EXT:
        return target
    if not target.is_dir():
        return None
    dumps = [
        path
        for path in target.rglob("*")
        if path.is_file() and path.suffix.lower() in LAUNCHABLE_EXT
    ]
    if not dumps:
        return None
    return max(dumps, key=lambda p: p.stat().st_size)


def _tender_launch_options(platform: str, dump: Path) -> str:
    if platform == "ps2":
        inner = "%EMULATOR_PCSX2% -batch %ROM%"
    elif platform == "ps3":
        inner = "%EMULATOR_RPCS3% --no-gui %ROM%"
    else:
        inner = "%EMULATOR_RYUBING% %ROM%"
    return f'flatpak run net.retrodeck.retrodeck -e "{inner}" "{dump}"'


def _tender_row_for_appid(appid: str, home: Path) -> sqlite3.Row | None:
    db = home / TENDER_DB
    if not db.is_file():
        return None
    try:
        want = int(normalize_appid(appid))
    except ValueError:
        return None
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(
            "SELECT r.rom_id, r.name, r.platform_slug, r.shortcut_app_id, "
            "r.applied_launch_options, i.file_path, i.rom_dir, i.launchable "
            "FROM roms r LEFT JOIN rom_installs i ON i.rom_id = r.rom_id "
            "WHERE r.shortcut_app_id = ?",
            (want,),
        ).fetchone()
    finally:
        con.close()


def launch_options_for_appid(appid: str, home: Path) -> str | None:
    """Steam LaunchOptions string for an empty-argv rom-launcher recovery."""
    row = _tender_row_for_appid(appid, home)
    if row is not None:
        applied = row["applied_launch_options"] or ""
        if applied.strip():
            return applied
        dump = None
        if row["file_path"]:
            dump = pick_launchable_dump(Path(row["file_path"]))
        if dump is None and row["rom_dir"]:
            dump = pick_launchable_dump(Path(row["rom_dir"]))
        if dump is not None:
            return _tender_launch_options(row["platform_slug"] or "", dump)
    dump = rom_for_appid(appid, home)
    if dump is None:
        return None
    return _tender_launch_options("switch", dump)


def rom_for_appid(appid: str, home: Path) -> Path | None:
    try:
        want = normalize_appid(appid)
    except ValueError:
        return None
    roots = (
        home / "retrodeck/roms/switch",
        home / "emulation/switch/games",
    )
    for vdf in find_shortcut_vdfs(home):
        try:
            shortcuts = iter_shortcuts(vdf.read_bytes())
        except (OSError, ValueError):
            continue
        for sc in shortcuts:
            if sc.get("appid") is None or str(sc["appid"]) != want:
                continue
            name = sc.get("AppName")
            if not isinstance(name, str) or not name:
                continue
            for base in roots:
                dump = pick_switch_dump(base / name)
                if dump is not None:
                    return dump
            for base in roots:
                if not base.is_dir():
                    continue
                folded = name.casefold()
                for child in sorted(base.iterdir()):
                    if child.name.casefold() == folded:
                        dump = pick_switch_dump(child)
                        if dump is not None:
                            return dump
    row = _tender_row_for_appid(appid, home)
    if row is not None:
        if row["file_path"]:
            dump = pick_launchable_dump(Path(row["file_path"]))
            if dump is not None:
                return dump
        if row["rom_dir"]:
            dump = pick_launchable_dump(Path(row["rom_dir"]))
            if dump is not None:
                return dump
    return None


def stash_switch_rars(home: Path) -> int:
    """Move leftover .rar sidecars out of Switch folders that already have a dump."""
    switch = home / "retrodeck/roms/switch"
    if not switch.is_dir():
        return 0
    stash_root = switch / "_archives"
    moved = 0
    for game in sorted(switch.iterdir()):
        if not game.is_dir() or game.name.startswith("_"):
            continue
        if pick_switch_dump(game) is None:
            continue
        for rar in game.rglob("*"):
            if not rar.is_file() or rar.suffix.lower() != ".rar":
                continue
            dest = stash_root / game.name / rar.relative_to(game)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest = dest.with_name(dest.name + ".bak")
            rar.rename(dest)
            print(f"stashed {rar} -> {dest}")
            moved += 1
    return moved


def _ps2_dump_for_archive(ps2: Path, archive: Path) -> Path | None:
    """Find the extracted ISO for a PS2 zip (folder name may drop the region)."""
    stem = archive.stem
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", stem)
    for cand in (ps2 / stem, ps2 / stripped):
        dump = pick_launchable_dump(cand)
        if dump is not None:
            return dump
    folded = stem.casefold()
    for child in sorted(ps2.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        name = child.name.casefold()
        if folded.startswith(name) or name in folded:
            dump = pick_launchable_dump(child)
            if dump is not None:
                return dump
    return None


def stash_ps2_archives(home: Path) -> int:
    """Move leftover .zip sidecars out of PS2 folders that already have an ISO."""
    ps2 = home / "retrodeck/roms/ps2"
    if not ps2.is_dir():
        return 0
    stash_root = ps2 / "_archives"
    moved = 0
    for path in sorted(ps2.iterdir()):
        if not path.is_file() or path.suffix.lower() not in ARCHIVE_EXT:
            continue
        if _ps2_dump_for_archive(ps2, path) is None:
            continue
        dest = stash_root / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_name(dest.name + ".bak")
        path.rename(dest)
        print(f"stashed {path} -> {dest}")
        moved += 1
    return moved


def repair_tender_ps2_installs(home: Path) -> int:
    """Tender withholds Play when launchable=0 (Xenosaga was recorded as a .zip)."""
    db = home / TENDER_DB
    if not db.is_file():
        return 0
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    fixed = 0
    try:
        rows = list(
            con.execute(
                "SELECT rom_id, file_path, rom_dir, launchable FROM rom_installs "
                "WHERE system = 'ps2' OR platform_slug = 'ps2'"
            )
        )
        ps2 = home / "retrodeck/roms/ps2"
        for row in rows:
            current = Path(row["file_path"]) if row["file_path"] else None
            dump = pick_launchable_dump(current) if current is not None else None
            if dump is None and current is not None:
                dump = _ps2_dump_for_archive(ps2, current)
            if dump is None and row["rom_dir"]:
                dump = pick_launchable_dump(Path(row["rom_dir"]))
            if dump is None:
                continue
            lo = _tender_launch_options("ps2", dump)
            fp = row["file_path"] or ""
            need = (
                not row["launchable"]
                or Path(fp) != dump
                or Path(fp).suffix.lower() in ARCHIVE_EXT
            )
            if not need:
                applied = con.execute(
                    "SELECT applied_launch_options FROM roms WHERE rom_id = ?",
                    (row["rom_id"],),
                ).fetchone()
                if applied and applied["applied_launch_options"]:
                    continue
            con.execute(
                "UPDATE rom_installs SET file_path = ?, rom_dir = ?, launchable = 1 "
                "WHERE rom_id = ?",
                (str(dump), str(dump.parent), row["rom_id"]),
            )
            con.execute(
                "UPDATE roms SET applied_launch_options = ?, fs_size_bytes = ?, "
                "fs_name = ? WHERE rom_id = ?",
                (lo, dump.stat().st_size, dump.name, row["rom_id"]),
            )
            print(f"tender rom_id={row['rom_id']} launchable {dump}")
            fixed += 1
        if fixed:
            con.commit()
    finally:
        con.close()
    return fixed


def repair_tender_switch_installs(home: Path) -> int:
    """Tender withholds Play when launchable=0 (Luigi was recorded as a .rar)."""
    db = home / "homebrew/data/romm-tender/romm_sync.db"
    if not db.is_file():
        return 0
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    fixed = 0
    try:
        rows = list(
            con.execute(
                "SELECT rom_id, file_path, rom_dir, launchable FROM rom_installs "
                "WHERE system = 'switch' OR platform_slug = 'switch'"
            )
        )
        for row in rows:
            rom_dir = Path(row["rom_dir"]) if row["rom_dir"] else None
            current = Path(row["file_path"]) if row["file_path"] else None
            dump = None
            if current is not None:
                dump = pick_switch_dump(current)
            if dump is None and rom_dir is not None:
                dump = pick_switch_dump(rom_dir)
            if dump is None:
                continue
            lo = _rd(dump)
            fp = row["file_path"] or ""
            need = (
                not row["launchable"]
                or Path(fp) != dump
                or not fp.lower().endswith((".nsp", ".xci"))
            )
            if not need:
                # Still refresh applied_launch_options if empty.
                applied = con.execute(
                    "SELECT applied_launch_options FROM roms WHERE rom_id = ?",
                    (row["rom_id"],),
                ).fetchone()
                if applied and applied["applied_launch_options"]:
                    continue
            con.execute(
                "UPDATE rom_installs SET file_path = ?, launchable = 1 WHERE rom_id = ?",
                (str(dump), row["rom_id"]),
            )
            con.execute(
                "UPDATE roms SET applied_launch_options = ?, fs_size_bytes = ? "
                "WHERE rom_id = ?",
                (lo, dump.stat().st_size, row["rom_id"]),
            )
            print(f"tender rom_id={row['rom_id']} launchable {dump}")
            fixed += 1
        if fixed:
            con.commit()
    finally:
        con.close()
    return fixed


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--rom-for-appid":
        if len(sys.argv) != 3:
            print(f"usage: {sys.argv[0]} --rom-for-appid APPID", file=sys.stderr)
            return 2
        dump = rom_for_appid(sys.argv[2], Path.home())
        if dump is None:
            print(
                f"no dump for SteamAppId={sys.argv[2]}",
                file=sys.stderr,
            )
            return 1
        print(dump)
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "--launch-options-for-appid":
        if len(sys.argv) != 3:
            print(
                f"usage: {sys.argv[0]} --launch-options-for-appid APPID",
                file=sys.stderr,
            )
            return 2
        lo = launch_options_for_appid(sys.argv[2], Path.home())
        if not lo:
            print(
                f"no launch options for SteamAppId={sys.argv[2]}",
                file=sys.stderr,
            )
            return 1
        print(lo)
        return 0
    if len(sys.argv) == 2 and sys.argv[1] == "--repair-tender":
        home = Path.home()
        stash_switch_rars(home)
        stash_ps2_archives(home)
        repair_tender_switch_installs(home)
        repair_tender_ps2_installs(home)
        return 0
    if len(sys.argv) != 2:
        print(
            f"usage: {sys.argv[0]} /path/to/shortcuts.vdf\n"
            f"       {sys.argv[0]} --rom-for-appid APPID\n"
            f"       {sys.argv[0]} --launch-options-for-appid APPID\n"
            f"       {sys.argv[0]} --repair-tender",
            file=sys.stderr,
        )
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"skip: no {path}")
        return 0
    stash_switch_rars(Path.home())
    stash_ps2_archives(Path.home())
    repair_tender_switch_installs(Path.home())
    repair_tender_ps2_installs(Path.home())
    patch_file(path, updates())
    return 0


def _self_test() -> None:
    sample = (
        b"\x00shortcuts\x00\x000\x00\x01AppName\x00Xenoblade Chronicles 3\x00"
        b"\x01LaunchOptions\x00\x00\x08\x001\x00\x01AppName\x00Other\x00"
        b"\x01LaunchOptions\x00keep\x00\x08\x08"
    )
    out = set_launch_options(sample, "Xenoblade Chronicles 3", "flatpak run test")
    assert b"flatpak run test\x00" in out
    assert b"\x01LaunchOptions\x00keep\x00" in out

    appid = 2479412558
    name = "Xenoblade Chronicles 3"
    vdf = (
        b"\x00shortcuts\x00\x000\x00"
        + b"\x02appid\x00"
        + struct.pack("<I", appid)
        + b"\x01AppName\x00"
        + name.encode("utf-8")
        + b"\x00\x01LaunchOptions\x00\x00\x08\x08"
    )
    parsed = iter_shortcuts(vdf)
    assert parsed[0]["appid"] == appid
    assert parsed[0]["AppName"] == name
    assert normalize_appid(str(appid << 32)) == str(appid)
    assert normalize_appid(str((appid << 32) | 0x02000000)) == str(appid)

    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        cfg = home / ".local/share/Steam/userdata/1/config"
        cfg.mkdir(parents=True)
        (cfg / "shortcuts.vdf").write_bytes(vdf)
        dump_dir = home / "retrodeck/roms/switch" / name
        dump_dir.mkdir(parents=True)
        xci = dump_dir / f"{name}.xci"
        nsp = dump_dir / f"{name} v2.nsp"
        xci.write_bytes(b"x" * 10)
        nsp.write_bytes(b"n" * 3)
        assert pick_switch_dump(dump_dir) == xci
        luigi_dir = home / "retrodeck/roms/switch" / "Luigi's Mansion 3"
        luigi_dir.mkdir()
        base = luigi_dir / "Luigi’s Mansion 3[0100DCA0064A6000][US][v0].nsp"
        dlc = luigi_dir / (
            "Luigi’s Mansion 3 [Luigi’s Mansion 3 Multiplayer Pack 1]"
            "[0100DCA0064A7001][US][v131072].nsp"
        )
        base.write_bytes(b"b" * 8)
        dlc.write_bytes(b"d" * 20)
        assert pick_switch_dump(luigi_dir) == base
        assert rom_for_appid(str(appid), home) == xci
        assert rom_for_appid("999", home) is None
        ps2_dir = home / "retrodeck/roms/ps2" / "Xenosaga Episode I - Der Wille zur Macht"
        ps2_dir.mkdir(parents=True)
        iso = ps2_dir / "Xenosaga Episode I - Der Wille zur Macht (USA).iso"
        iso.write_bytes(b"i" * 12)
        assert pick_launchable_dump(ps2_dir) == iso
        assert "%EMULATOR_PCSX2%" in _tender_launch_options("ps2", iso)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        _self_test()
        print("ok")
        raise SystemExit(0)
    raise SystemExit(main())
