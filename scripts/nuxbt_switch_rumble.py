#!/usr/bin/env python3
"""Switch HD rumble decode + Sunshine (libvirtualhid) FF forward helpers.

Switch → NUXBT output reports carry 8 rumble bytes (L then R). We decode a
coarse amplitude and upload FF_RUMBLE on the Sunshine pad so Moonlight clients
feel it (libvirtualhid maps EV_FF → gamepad feedback → control stream).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
RUMBLE_FILE = RUNTIME / "nuxbt-switch-rumble"
# Neutral / idle patterns (per-side 4 bytes) from Switch / nuxbt pairing
_IDLE = {
    bytes([0x00, 0x01, 0x40, 0x40]),
    bytes([0x00, 0x00, 0x00, 0x00]),
}


def decode_side_amp(data: bytes) -> float:
    """Approximate 0.0–1.0 amplitude from one motor's 4-byte HD rumble block."""
    if len(data) < 4:
        return 0.0
    b = bytes(data[:4])
    if b in _IDLE:
        return 0.0
    b0, b1, b2, b3 = b[0], b[1], b[2], b[3]
    # Packed HF/LF amp (community / dekuNukem-style bitfields). Exact inverse of
    # the Switch encoder varies by frequency band — take the stronger cue.
    hf = ((b1 & 0xFE) << 2) | ((b2 >> 6) & 0x03)
    lf = (b3 & 0x7F) | ((b3 & 0x80) >> 1)
    amp = max(hf, lf & 0xFF)
    if amp < 2 and (b0 or b1 not in (0, 1)):
        amp = max(b0 & 0x7F, b1 & 0x7F, b2 & 0x7F, b3 & 0x7F)
    return min(1.0, amp / 200.0)


def decode_switch_rumble(packet: bytes) -> tuple[int, int]:
    """Return (strong/lowfreq, weak/highfreq) as 0–65535 for FF_RUMBLE.

    Expects raw Switch HID output starting with 0xA2, rumble at bytes [2:10].
    Also accepts a bare 8-byte rumble blob.
    """
    if not packet:
        return 0, 0
    if packet[0] == 0xA2 and len(packet) >= 10:
        blob = packet[2:10]
    elif len(packet) >= 8:
        blob = packet[:8]
    else:
        return 0, 0
    left = decode_side_amp(blob[0:4])
    right = decode_side_amp(blob[4:8])
    # Map L/R → Xbox-style strong/weak (avg + max keeps one-sided hits felt)
    strong = max(left, right)
    weak = (left + right) * 0.5
    return int(strong * 0xFFFF), int(weak * 0xFFFF)


def write_rumble_file(packet: bytes, path: Path = RUMBLE_FILE) -> None:
    try:
        if packet and packet[0] == 0xA2 and len(packet) >= 10:
            path.write_bytes(bytes(packet[2:10]))
        elif packet and len(packet) >= 8:
            path.write_bytes(bytes(packet[:8]))
    except OSError:
        pass


def read_rumble_file(path: Path = RUMBLE_FILE) -> tuple[int, int]:
    try:
        data = path.read_bytes()
    except OSError:
        return 0, 0
    return decode_switch_rumble(data)


class SunshineRumble:
    """Upload/play FF_RUMBLE on the current Sunshine libvirtualhid pad."""

    def __init__(self) -> None:
        self._dev = None
        self._effect_id: int | None = None
        self._last = (0, 0)
        self._last_path: str | None = None
        self._last_scan = 0.0

    def close(self) -> None:
        self._stop()
        self._dev = None
        self._effect_id = None

    def _find_pad(self):
        try:
            from evdev import InputDevice, ecodes, list_devices
        except ImportError:
            return None
        for path in list_devices():
            try:
                d = InputDevice(path)
            except OSError:
                continue
            name = d.name or ""
            if "libvirtualhid" not in name or "Sunshine" not in name:
                continue
            caps = d.capabilities()
            if ecodes.EV_FF in caps and ecodes.FF_RUMBLE in caps[ecodes.EV_FF]:
                return d
        return None

    def _ensure(self) -> bool:
        now = time.time()
        if self._dev is not None:
            # Rescan occasionally — Moonlight reconnect renumbers event nodes.
            if now - self._last_scan < 5.0:
                return True
        if now - self._last_scan < 1.0 and self._dev is None:
            return False
        self._last_scan = now
        self._stop()
        self._dev = self._find_pad()
        self._effect_id = None
        self._last = (0, 0)
        if self._dev is not None:
            self._last_path = self._dev.path
        return self._dev is not None

    def _stop(self) -> None:
        if self._dev is None or self._effect_id is None:
            return
        try:
            from evdev import ecodes

            self._dev.write(ecodes.EV_FF, self._effect_id, 0)
            self._dev.erase_effect(self._effect_id)
        except OSError:
            pass
        self._effect_id = None

    def apply(self, strong: int, weak: int) -> None:
        strong = max(0, min(0xFFFF, int(strong)))
        weak = max(0, min(0xFFFF, int(weak)))
        if not self._ensure():
            return
        if (strong, weak) == self._last:
            return
        self._last = (strong, weak)
        if strong == 0 and weak == 0:
            self._stop()
            return
        try:
            from evdev import ecodes, ff

            assert self._dev is not None
            if self._effect_id is not None:
                try:
                    self._dev.write(ecodes.EV_FF, self._effect_id, 0)
                    self._dev.erase_effect(self._effect_id)
                except OSError:
                    pass
                self._effect_id = None
            effect = ff.Effect(
                ecodes.FF_RUMBLE,
                -1,
                0,
                ff.Trigger(0, 0),
                # Long replay; we replace/stop on next update
                ff.Replay(2000, 0),
                ff.EffectType(
                    ff_rumble_effect=ff.Rumble(
                        strong_magnitude=strong,
                        weak_magnitude=weak,
                    )
                ),
            )
            eid = self._dev.upload_effect(effect)
            self._dev.write(ecodes.EV_FF, eid, 1)
            self._effect_id = eid
        except OSError:
            self._dev = None
            self._effect_id = None
