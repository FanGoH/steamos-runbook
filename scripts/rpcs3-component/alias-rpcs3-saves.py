#!/usr/bin/env python3
"""Point RetroDECK RPCS3 at standalone Uncharted saves.

The USA disc serial is BCUS98103, but the EBOOT lists saves as
BCES00065_NDI_UNCHARTED_DF_* (EU SKU the engine was built with). A folder
named BCUS98103_* is invisible to cellSaveDataListAutoLoad (save_entries=0).
"""
from __future__ import annotations

from pathlib import Path
import shutil
import sys

# Same length so PARAM.SFO SAVEDATA_DIRECTORY can be patched in place.
ALIASES = {
    "BCUS98103_NDI_UNCHARTED_DF_0": "BCES00065_NDI_UNCHARTED_DF_0",
}


def alias_save(src: Path, dest: Path) -> bool:
    if dest.exists() or not src.is_dir():
        return False
    if len(src.name) != len(dest.name):
        return False
    shutil.copytree(src, dest)
    sfo = dest / "PARAM.SFO"
    if sfo.is_file():
        data = sfo.read_bytes()
        sfo.write_bytes(data.replace(src.name.encode("ascii"), dest.name.encode("ascii")))
    return True


def alias_dir(root: Path) -> list[str]:
    done: list[str] = []
    for old, new in ALIASES.items():
        src = root / old
        dest = root / new
        if alias_save(src, dest):
            done.append(f"{old} -> {new}")
    return done


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "BCUS98103_NDI_UNCHARTED_DF_0"
            src.mkdir()
            (src / "PARAM.SFO").write_bytes(
                b"x" * 8 + b"BCUS98103_NDI_UNCHARTED_DF_0" + b"\x00" * 8
            )
            (src / "USR-DATA").write_bytes(b"save")
            assert alias_dir(root) == [
                "BCUS98103_NDI_UNCHARTED_DF_0 -> BCES00065_NDI_UNCHARTED_DF_0"
            ]
            dest = root / "BCES00065_NDI_UNCHARTED_DF_0"
            assert dest.is_dir()
            assert b"BCES00065_NDI_UNCHARTED_DF_0" in (dest / "PARAM.SFO").read_bytes()
            assert b"BCUS98103_NDI_UNCHARTED_DF_0" not in (dest / "PARAM.SFO").read_bytes()
            assert alias_dir(root) == []
        print("ok")
        return 0
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} /path/to/savedata", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"skip: no {root}")
        return 0
    done = alias_dir(root)
    if done:
        for line in done:
            print(f"Aliased RPCS3 save {line} in {root}")
    else:
        print(f"No standalone Uncharted save alias needed in {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
