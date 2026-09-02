#!/usr/bin/env python3
"""Steam shortcut LaunchOptions helper, plus empty-argv dump lookup.

Tender/decky-romm-sync tiles (Xenoblade, Luigi) often have an empty launch
line. Steam Game Mode also rewrites shortcuts.vdf while it is running, so
writing LaunchOptions does not stick until a Steam restart.

`--rom-for-appid` maps SteamAppId → shortcuts.vdf AppName → the Switch dump
under ~/retrodeck/roms/switch/<name>/ so rom-launcher can recover with no
args.
"""
from __future__ import annotations

import shutil
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
    return str(n & 0xFFFFFFFF)


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
    return None


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--rom-for-appid":
        if len(sys.argv) != 3:
            print(f"usage: {sys.argv[0]} --rom-for-appid APPID", file=sys.stderr)
            return 2
        dump = rom_for_appid(sys.argv[2], Path.home())
        if dump is None:
            print(
                f"no Switch dump for SteamAppId={sys.argv[2]}",
                file=sys.stderr,
            )
            return 1
        print(dump)
        return 0
    if len(sys.argv) != 2:
        print(
            f"usage: {sys.argv[0]} /path/to/shortcuts.vdf\n"
            f"       {sys.argv[0]} --rom-for-appid APPID",
            file=sys.stderr,
        )
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"skip: no {path}")
        return 0
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
    assert normalize_appid(str(appid | (1 << 32))) == str(appid)

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


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        _self_test()
        print("ok")
        raise SystemExit(0)
    raise SystemExit(main())
