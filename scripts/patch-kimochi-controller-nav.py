#!/usr/bin/env python3
"""Keep Kimochi's Game Mode radial menu open on a Steam Machine.

Kimochi 0.8.1 (build 06109eda11891298e2084424ba0a8430e7b54bf4) cancels
controller navigation ~16ms after openControllerMenu when Gamescope is
active and the Steam Deck hidraw (`28de:1205` /input2) is missing:

    if navigating() && gamescope::active() && (!deck.connected() || system_menu)

JS logs every controller-nav-cancel as focus-elsewhere, so the overlay
closes even though the reason is "Steam system button or physical
controller disconnected". This host is not a Deck, so connected() is
always false.

Patch: after the gamescope::active() call, turn `test al,al` into
`xor eax,eax` so the following `je` always skips that cancel. Deck QAM
still yields via the separate system_menu rising-edge handler. A later
Kimochi build that does not match the opcode bytes is left untouched.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# movzx eax,[rip+navigating]; test al,al; je not_nav;
# call [rip+gamescope_active]; test al,al; je skip_cancel
NEEDLE = bytes.fromhex(
    "0fb6057bc59b01"  # movzx eax, BYTE PTR [rip+0x19bc57b]
    "84c0"  # test al,al
    "0f84d3010000"  # je +0x1d3
    "ff158d8b9a01"  # call QWORD PTR [rip+0x19a8b8d]
    "84c0"  # test al,al  ← patch to xor eax,eax
    "0f8465060000"  # je +0x665
)
PATCH_AT = NEEDLE.rfind(bytes.fromhex("84c0"))
PATCHED = bytes.fromhex("31c0")  # xor eax,eax
BUILD_ID = "06109eda11891298e2084424ba0a8430e7b54bf4"


def kimochi_pids() -> list[int]:
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
        except OSError:
            continue
        if comm == "kimochi":
            found.append(int(entry.name))
    return found


def maps_for(pid: int) -> list[tuple[int, int, int, str]]:
    """(start, end, file_offset, perms) for file-backed mappings of the kimochi ELF."""
    rows: list[tuple[int, int, int, str]] = []
    try:
        lines = Path(f"/proc/{pid}/maps").read_text().splitlines()
    except OSError:
        return rows
    for line in lines:
        if "/usr/bin/kimochi" not in line and "/kimochi" not in line:
            continue
        if "onnxruntime" in line or "/lib/" in line:
            continue
        parts = line.split()
        span, perms = parts[0], parts[1]
        off = int(parts[2], 16) if len(parts) > 2 else 0
        start_s, end_s = span.split("-")
        rows.append((int(start_s, 16), int(end_s, 16), off, perms))
    return rows


def file_offset_to_va(maps: list[tuple[int, int, int, str]], file_off: int) -> int | None:
    for start, end, off, _perms in maps:
        size = end - start
        if off <= file_off < off + size:
            return start + (file_off - off)
    return None


def find_in_bytes(blob: bytes) -> tuple[int, bool] | None:
    """Return (offset, already_patched) or None if this build is unknown."""
    idx = blob.find(NEEDLE)
    if idx >= 0:
        return idx, False
    patched = NEEDLE[:PATCH_AT] + PATCHED + NEEDLE[PATCH_AT + 2 :]
    idx = blob.find(patched)
    if idx >= 0:
        return idx, True
    return None


def read_exe(pid: int) -> bytes:
    return Path(f"/proc/{pid}/exe").read_bytes()


class _Iovec(ctypes.Structure):
    _fields_ = [("iov_base", ctypes.c_void_p), ("iov_len", ctypes.c_size_t)]


def write_mem(pid: int, addr: int, data: bytes) -> None:
    # /proc/pid/mem often allows writing r-x pages.
    try:
        with open(f"/proc/{pid}/mem", "r+b", buffering=0) as mem:
            mem.seek(addr)
            wrote = mem.write(data)
            if wrote == len(data):
                return
    except OSError:
        pass
    libc_name = ctypes.util.find_library("c") or "libc.so.6"
    libc = ctypes.CDLL(libc_name, use_errno=True)
    buf = ctypes.create_string_buffer(data, len(data))
    local_iov = _Iovec(ctypes.cast(buf, ctypes.c_void_p), len(data))
    remote_iov = _Iovec(addr, len(data))
    n = libc.process_vm_writev(
        ctypes.c_int(pid),
        ctypes.byref(local_iov),
        ctypes.c_ulong(1),
        ctypes.byref(remote_iov),
        ctypes.c_ulong(1),
        ctypes.c_ulong(0),
    )
    if n != len(data):
        err = ctypes.get_errno()
        raise OSError(err, f"process_vm_writev pid={pid} addr={addr:#x}: {os.strerror(err)}")


def patch_pid(pid: int) -> str:
    blob = read_exe(pid)
    found = find_in_bytes(blob)
    if found is None:
        return (
            f"pid {pid}: Kimochi binary does not match 0.8.1 "
            f"controller-nav cancel (build {BUILD_ID}); left unpatched"
        )
    file_off, already = found
    maps = maps_for(pid)
    addr = file_offset_to_va(maps, file_off + PATCH_AT)
    if addr is None:
        raise RuntimeError(f"pid {pid}: opcode at file {file_off:#x} is not mapped")
    if already:
        return f"pid {pid}: already patched at {addr:#x}"
    write_mem(pid, addr, PATCHED)
    return f"pid {pid}: patched controller-nav cancel at {addr:#x} (xor eax,eax)"


def patch_file(path: Path) -> str:
    blob = path.read_bytes()
    found = find_in_bytes(blob)
    if found is None:
        return (
            f"{path}: Kimochi binary does not match 0.8.1 "
            f"controller-nav cancel (build {BUILD_ID}); left unpatched"
        )
    off, already = found
    if already:
        return f"{path}: already patched at {off + PATCH_AT:#x}"
    mode = path.stat().st_mode
    path.chmod(mode | 0o200)
    with path.open("r+b") as handle:
        handle.seek(off + PATCH_AT)
        handle.write(PATCHED)
    path.chmod(mode | 0o111)
    return f"{path}: patched controller-nav cancel at {off + PATCH_AT:#x}"


def udev_joysticks() -> list[str]:
    """Joystick names in sysfs event order (gilrs udev enumerate is the same set)."""
    names: list[str] = []
    events = sorted(
        Path("/sys/class/input").glob("event*"),
        key=lambda path: int(path.name[5:]) if path.name[5:].isdigit() else 0,
    )
    for event in events:
        try:
            props = subprocess.check_output(
                ["udevadm", "info", "--query=property", str(event)],
                text=True,
                errors="replace",
            )
        except OSError:
            continue
        if "ID_INPUT_JOYSTICK=1" not in props:
            continue
        name_path = event / "device" / "name"
        names.append(name_path.read_text().strip() if name_path.exists() else event.name)
    return names


def prefer_stream_pad_index(names: list[str]) -> int | None:
    lowered = [name.lower() for name in names]
    for needle in (
        "sunshine",
        "odin",
        "thor",
        "libvirtualhid",
        "microsoft x-box 360 pad 0",
    ):
        for index, name in enumerate(lowered):
            if needle in name:
                return index
    return None


def write_preferred_pad(settings_path: Path, index: int) -> str:
    data = json.loads(settings_path.read_text())
    pads = data.setdefault("gamepadSettings", {})
    if not isinstance(pads, dict):
        pads = {}
        data["gamepadSettings"] = pads
    if pads.get("preferredGamepadIndex") == index:
        return f"{settings_path}: preferredGamepadIndex already {index}"
    pads["preferredGamepadIndex"] = index
    pads["enabled"] = pads.get("enabled", True)
    settings_path.write_text(json.dumps(data, indent=2) + "\n")
    return f"{settings_path}: preferredGamepadIndex={index}"


def prefer_pad(settings_path: Path) -> str:
    names = udev_joysticks()
    index = prefer_stream_pad_index(names)
    listing = ", ".join(f"{i}:{name}" for i, name in enumerate(names)) or "(none)"
    if index is None:
        return f"no Sunshine/Steam pad 0 among joysticks: {listing}"
    return write_preferred_pad(settings_path, index) + f" ({listing})"


def watch(timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pids = kimochi_pids()
        if pids:
            messages = [patch_pid(pid) for pid in pids]
            print("\n".join(messages))
            return 0 if any("patched" in m or "already patched" in m for m in messages) else 2
        time.sleep(0.05)
    print(f"timed out waiting {timeout:.0f}s for kimochi", file=sys.stderr)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, help="patch this on-disk kimochi ELF")
    parser.add_argument("--pid", type=int, help="patch this kimochi pid")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="wait for a kimochi process, then patch it (needs ptrace)",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--prefer-pad",
        action="store_true",
        help="point Kimochi at Steam pad 0 / Sunshine so the radial chord is heard",
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path.home() / ".local/share/dev.kimochi.app/settings.json",
    )
    args = parser.parse_args()
    try:
        if args.prefer_pad:
            print(prefer_pad(args.settings))
            return 0
        if args.elf:
            message = patch_file(args.elf)
            print(message)
            if "does not match" in message or "left unpatched" in message:
                return 2
            return 0
        if args.watch:
            return watch(args.timeout)
        pids = [args.pid] if args.pid else kimochi_pids()
        if not pids:
            print("no kimochi process", file=sys.stderr)
            return 2
        for pid in pids:
            print(patch_pid(pid))
        return 0
    except Exception as exc:  # noqa: BLE001 — launcher must not crash Steam
        print(f"patch-kimochi-controller-nav: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
