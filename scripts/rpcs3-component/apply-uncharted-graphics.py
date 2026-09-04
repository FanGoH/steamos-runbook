#!/usr/bin/env python3
"""Per-game RPCS3 graphics for Uncharted: Drake's Fortune (BCUS98103).

Native output is 1280x720. Resolution Scale 150 is 1920x1080. Write Color /
Write Depth plus MSAA Disabled is the flicker/smoke fix. Do not write these
into global config.yml — other PS3 titles keep RetroDECK defaults.

Official Unlock FPS / Disable Motion Blur / Disable Depth of Field patches
are PPU-hashed to disc 01.10 (USA) / 01.01 (EU). A 01.00 ISO will not match;
do not invent 01.00 memory patches, and do not raise Vblank (that speeds the
game up). Enable the 01.10 patches so they apply if the update is installed.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import re
import shutil
import sys

SERIAL = "BCUS98103"
PPU_HASH = "PPU-8363904e0b8fc276380a8f0e158dd81d7a9cefc5"

# Longer keys first so "VSync" cannot eat "VSync Mode".
VIDEO_SETTINGS: list[tuple[str, str]] = [
    ("Resolution Scale", "150"),
    ("Anisotropic Filter Override", "16"),
    ("Write Color Buffers", "true"),
    ("Write Depth Buffer", "true"),
    ("VSync Mode", "Full"),
    ("Frame limit", "60"),
    ("Resolution", "1280x720"),
    ("MSAA", "Disabled"),
    ("VSync", "true"),
    ("Vblank Rate", "60"),
]

PATCH_BLOCK = f"""\
{PPU_HASH}:
  Unlock FPS:
    "Uncharted: Drake's Fortune":
      BCUS98103:
        01.10:
          Enabled: true
      BCES00065:
        01.01:
          Enabled: true
  Disable Motion Blur:
    "Uncharted: Drake's Fortune":
      BCUS98103:
        01.10:
          Enabled: true
      BCES00065:
        01.01:
          Enabled: true
  Disable Depth of Field:
    "Uncharted: Drake's Fortune":
      BCUS98103:
        01.10:
          Enabled: true
      BCES00065:
        01.01:
          Enabled: true
"""


def set_key(text: str, key: str, value: str) -> str:
    pat = re.compile(rf"^(  {re.escape(key)}: ).*$", re.M)
    if pat.search(text):
        return pat.sub(rf"\g<1>{value}", text, count=1)
    if re.search(r"^Video:\s*$", text, re.M):
        return re.sub(
            r"^Video:\s*$",
            f"Video:\n  {key}: {value}",
            text,
            count=1,
            flags=re.M,
        )
    return text.rstrip() + f"\nVideo:\n  {key}: {value}\n"


def apply_video_settings(text: str) -> str:
    for key, value in VIDEO_SETTINGS:
        text = set_key(text, key, value)
    return text


def video_settings_applied(text: str) -> bool:
    for key, value in VIDEO_SETTINGS:
        if not re.search(rf"^  {re.escape(key)}: {re.escape(value)}\s*$", text, re.M):
            if key == "VSync" and "VSync:" not in text:
                continue
            return False
    return True


def upsert_ppu_block(text: str, block: str) -> str:
    block = block.rstrip() + "\n"
    pat = re.compile(rf"^{re.escape(PPU_HASH)}:.*?(?=^PPU-|\Z)", re.M | re.S)
    if pat.search(text):
        return pat.sub(block, text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    if text.strip():
        return text + "\n" + block
    return block


def patches_enabled(text: str) -> bool:
    if PPU_HASH not in text:
        return False
    for name in ("Unlock FPS", "Disable Motion Blur", "Disable Depth of Field"):
        if not re.search(rf"^  {re.escape(name)}:", text, re.M):
            return False
    return bool(re.search(r"BCUS98103:\s*\n\s*01\.10:\s*\n\s*Enabled: true", text))


def ensure_custom_config(config_dir: Path, serial: str = SERIAL) -> Path:
    custom_dir = config_dir / "custom_configs"
    custom_dir.mkdir(parents=True, exist_ok=True)
    dest = custom_dir / f"config_{serial}.yml"
    global_cfg = config_dir / "config.yml"
    if dest.is_file():
        text = dest.read_text(encoding="utf-8")
    elif global_cfg.is_file():
        text = global_cfg.read_text(encoding="utf-8")
    else:
        text = "Video:\n"
    new = apply_video_settings(text)
    if new != text or not dest.is_file():
        dest.write_text(new, encoding="utf-8")
    return dest


def ensure_patch_yml(config_dir: Path, fallback: Path, source: Path | None) -> Path:
    dest = config_dir / "patches" / "patch.yml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and PPU_HASH in dest.read_text(encoding="utf-8", errors="replace"):
        return dest
    src = None
    if source and source.is_file():
        src = source
    elif fallback.is_file():
        src = fallback
    if src is None:
        raise FileNotFoundError(f"no patch.yml source for {dest}")
    if dest.resolve() != src.resolve():
        shutil.copy2(src, dest)
    return dest


def ensure_patch_config(config_dir: Path) -> Path:
    dest = config_dir / "patch_config.yml"
    text = dest.read_text(encoding="utf-8") if dest.is_file() else ""
    new = upsert_ppu_block(text, PATCH_BLOCK)
    if new != text or not dest.is_file():
        dest.write_text(new, encoding="utf-8")
    return dest


def apply(config_dir: Path, fallback: Path, source: Path | None) -> list[str]:
    done: list[str] = []
    custom = ensure_custom_config(config_dir)
    done.append(str(custom))
    patch_yml = ensure_patch_yml(config_dir, fallback, source)
    done.append(str(patch_yml))
    patch_cfg = ensure_patch_config(config_dir)
    done.append(str(patch_cfg))
    text = custom.read_text(encoding="utf-8")
    if not video_settings_applied(text):
        raise RuntimeError(f"Uncharted video settings missing in {custom}")
    if not patches_enabled(patch_cfg.read_text(encoding="utf-8")):
        raise RuntimeError(f"Uncharted patches not enabled in {patch_cfg}")
    if PPU_HASH not in patch_yml.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError(f"Uncharted PPU hash missing in {patch_yml}")
    return done


def self_test() -> None:
    import tempfile

    sample = (
        "Core:\n"
        "  PPU Decoder: Recompiler (LLVM)\n"
        "Video:\n"
        "  Frame limit: Auto\n"
        "  MSAA: Auto\n"
        "  Resolution: 1280x720\n"
        "  Resolution Scale: 100\n"
        "  VSync: false\n"
        "  VSync Mode: Disabled\n"
        "  Write Color Buffers: false\n"
        "  Write Depth Buffer: false\n"
        "  Anisotropic Filter Override: 0\n"
        "  Vblank Rate: 60\n"
    )
    out = apply_video_settings(sample)
    assert "  PPU Decoder: Recompiler (LLVM)\n" in out
    assert "  Resolution Scale: 150\n" in out
    assert "  Write Color Buffers: true\n" in out
    assert "  Write Depth Buffer: true\n" in out
    assert "  MSAA: Disabled\n" in out
    assert "  Frame limit: 60\n" in out
    assert "  VSync Mode: Full\n" in out
    assert "  VSync: true\n" in out
    assert "  Anisotropic Filter Override: 16\n" in out
    assert video_settings_applied(out)
    assert not video_settings_applied(sample)

    merged = upsert_ppu_block("PPU-deadbeef:\n  Other: true\n", PATCH_BLOCK)
    assert patches_enabled(merged)
    assert "PPU-deadbeef:" in merged
    again = upsert_ppu_block(merged, PATCH_BLOCK)
    assert again.count(PPU_HASH) == 1

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = root / "rpcs3"
        (cfg / "config.yml").parent.mkdir(parents=True)
        (cfg / "config.yml").write_text(sample, encoding="utf-8")
        fallback = Path(__file__).with_name("uncharted-patch.yml")
        apply(cfg, fallback, None)
        custom = (cfg / "custom_configs" / f"config_{SERIAL}.yml").read_text(
            encoding="utf-8"
        )
        assert video_settings_applied(custom)
        assert "  PPU Decoder: Recompiler (LLVM)\n" in custom
        global_text = (cfg / "config.yml").read_text(encoding="utf-8")
        assert "  Resolution Scale: 100\n" in global_text
        apply(cfg, fallback, None)
        assert video_settings_applied(
            (cfg / "custom_configs" / f"config_{SERIAL}.yml").read_text(
                encoding="utf-8"
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument(
        "--fallback-patch",
        type=Path,
        default=Path(__file__).with_name("uncharted-patch.yml"),
    )
    parser.add_argument("--patch-source", type=Path, default=None)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("ok")
        return 0
    if args.config_dir is None:
        print(f"usage: {sys.argv[0]} --config-dir /path/to/rpcs3", file=sys.stderr)
        return 2
    source = args.patch_source
    if source is None:
        home_src = Path.home() / ".config/rpcs3/patches/patch.yml"
        source = home_src if home_src.is_file() else None
    for path in apply(args.config_dir, args.fallback_patch, source):
        print(f"Uncharted RPCS3 graphics: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
