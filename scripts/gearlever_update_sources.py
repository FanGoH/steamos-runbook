#!/usr/bin/env python3
"""Pin Gear Lever update sources for AppImages that lack one.

Eden / citron / mpv already ship an AppImage `.upd_info` section; leave those
alone. Cursor self-updates. The Uncharted PC-port AppImage is an unofficial
launcher with no public AppImage release.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import os
import subprocess
import sys
from pathlib import Path

APPDIR = Path(os.environ.get("GEARLEVER_APPDIR", os.path.expanduser("~/AppImages")))
CONF = Path(
    os.environ.get(
        "GEARLEVER_CONF",
        os.path.expanduser("~/.var/app/it.mijorus.gearlever/config/gearlever.conf"),
    )
)

# Gear Lever GithubUpdater / GitlabUpdater / StaticFileUpdater keys.
SOURCES: list[dict] = [
    {
        "id": "rpcs3",
        "match": ("rpcs3",),
        "manager": "GithubUpdater",
        "config": {
            "repo": "RPCS3/rpcs3-binaries-linux",
            "repo_filename": "rpcs3-*_linux64.AppImage",
            "allow_prereleases": "false",
        },
    },
    {
        "id": "dusklight",
        "match": ("dusklight",),
        "manager": "GithubUpdater",
        "config": {
            "repo": "TwilitRealm/dusklight",
            "repo_filename": "Dusklight-*-linux-x86_64.AppImage",
            "allow_prereleases": "false",
        },
    },
    {
        "id": "wwhd",
        "match": ("wind_waker", "windwaker", "wwhd"),
        "manager": "GithubUpdater",
        "config": {
            "repo": "ZeldaWWHDRecomp/ZeldaWWHDRecomp",
            "repo_filename": "WindWakerHD-*-linux-x86_64.AppImage",
            "allow_prereleases": "false",
        },
    },
    {
        "id": "appimagelauncher",
        "match": ("appimagelauncher",),
        "manager": "GithubUpdater",
        "config": {
            "repo": "TheAssassin/AppImageLauncher",
            "repo_filename": "appimagelauncher-lite-*x86_64.AppImage",
            "allow_prereleases": "false",
        },
    },
    {
        "id": "ryujinx",
        "match": ("ryujinx",),
        "manager": "GitlabUpdater",
        "config": {
            "repo_url": "https://git.ryujinx.app/ryubing/ryujinx",
            "repo_filename": "*linux_x64.AppImage",
        },
    },
]

SKIP_NOTES = {
    "cursor": "Cursor self-updates; no stable AppImage URL for Gear Lever",
    "uncharted": "Unofficial SuperMedo launcher; no public AppImage release",
    "melonds": "zip archive, not an AppImage",
}


def app_hash(file_path: str) -> str:
    return hashlib.md5(file_path.encode()).hexdigest()


def is_appimage_name(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(".appimage") and not name.startswith(".")


def match_source(filename: str) -> dict | None:
    stem = filename.lower()
    for src in SOURCES:
        if any(token in stem for token in src["match"]):
            return src
    return None


def skip_note(filename: str) -> str | None:
    stem = filename.lower()
    for token, note in SKIP_NOTES.items():
        if token in stem:
            return note
    return None


def embedded_update_url(file_path: Path) -> str:
    try:
        out = subprocess.check_output(
            ["readelf", "--string-dump=.upd_info", "--wide", str(file_path)],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""
    for line in out.splitlines():
        if "gh-releases-zsync|" in line or "zsync|" in line:
            return line.strip()
    return ""


def list_appimages(appdir: Path) -> list[Path]:
    if not appdir.is_dir():
        return []
    return sorted(
        p for p in appdir.iterdir() if p.is_file() and is_appimage_name(p.name)
    )


def load_conf(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    if path.is_file():
        parser.read(path)
    return parser


def has_manager(parser: configparser.ConfigParser, file_path: str) -> str:
    section = f"app.{app_hash(file_path)}.update_manager"
    if parser.has_section(section):
        return (parser.get(section, "manager", fallback="") or "").strip()
    return ""


def set_update_source(
    parser: configparser.ConfigParser, file_path: Path, source: dict
) -> None:
    h = app_hash(str(file_path))
    app_section = f"app.{h}"
    um_section = f"app.{h}.update_manager"
    if not parser.has_section(app_section):
        parser.add_section(app_section)
    parser.set(app_section, "file_path", str(file_path))
    if not parser.get(app_section, "name", fallback=""):
        parser.set(app_section, "name", file_path.stem)
    if parser.has_section(um_section):
        parser.remove_section(um_section)
    parser.add_section(um_section)
    for key, value in source["config"].items():
        parser.set(um_section, key, str(value))
    parser.set(um_section, "manager", source["manager"])


def write_conf(parser: configparser.ConfigParser, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        parser.write(fh)


def pin_sources(appdir: Path, conf_path: Path, dry_run: bool = False) -> int:
    parser = load_conf(conf_path)
    changed = False
    images = list_appimages(appdir)
    if not images:
        print(f"No AppImages in {appdir}")
        return 0
    for path in images:
        src = match_source(path.name)
        manager = has_manager(parser, str(path))
        embedded = embedded_update_url(path)
        if embedded:
            print(f"OK embedded  {path.name}")
            continue
        if manager:
            print(f"OK manager   {path.name} ({manager})")
            continue
        note = skip_note(path.name)
        if note and src is None:
            print(f"SKIP         {path.name} — {note}")
            continue
        if src is None:
            print(f"SKIP         {path.name} — no known update source")
            continue
        print(f"PIN          {path.name} -> {src['manager']} {src['id']}")
        if not dry_run:
            set_update_source(parser, path, src)
            changed = True
    if changed:
        write_conf(parser, conf_path)
        print(f"Wrote {conf_path}")
    return 0


def report(appdir: Path, conf_path: Path) -> int:
    parser = load_conf(conf_path)
    missing = 0
    for path in list_appimages(appdir):
        manager = has_manager(parser, str(path))
        embedded = bool(embedded_update_url(path))
        note = skip_note(path.name)
        if embedded or manager or note:
            continue
        if match_source(path.name):
            print(f"missing {path.name}")
            missing += 1
    return 0 if missing == 0 else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="exit 2 if a known AppImage still lacks a source")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--appdir", type=Path, default=APPDIR)
    parser.add_argument("--conf", type=Path, default=CONF)
    args = parser.parse_args(argv)
    if args.report:
        return report(args.appdir, args.conf)
    return pin_sources(args.appdir, args.conf, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
