#!/usr/bin/env python3
"""Cemuhook/DSU motion bridge for Sunshine Switch Pro (and similar) IMU nodes.

Reads kernel ``… (IMU)`` evdev nodes created by hid-nintendo for libvirtualhid
Switch pads (phys ``libvirtualhid/uhid/*``) and serves cemuhook UDP on
``127.0.0.1:26760`` so Eden / Azahar / Cemu can use motion while buttons stay
on EmuPads sinks.

Accel: ABS_X/Y/Z with resolution units/g (hid-nintendo: 4096 = 1g).
Gyro: ABS_RX/RY/RZ with resolution units/(deg/s).

Never pgrep -f sunshine. Run via ``emupads-dsu.service`` (often under
``sg input`` so /dev/input/event* for IMU is openable).
"""
from __future__ import annotations

import os
import random
import select
import socket
import struct
import sys
import time
import zlib
from pathlib import Path

from evdev import InputDevice, ecodes, list_devices

DSU_HOST = os.environ.get("EMUPADS_DSU_HOST", "127.0.0.1")
DSU_PORT = int(os.environ.get("EMUPADS_DSU_PORT", "26760"))
LOG_PATH = Path(
    os.environ.get(
        "EMUPADS_DSU_LOG",
        Path.home() / "steamos-playbook/logs/emupads-dsu.log",
    )
)
PROTOCOL_VERSION = 1001
MSG_VERSION = 0x100000
MSG_PORTS = 0x100001
MSG_DATA = 0x100002
STATE_DISCONNECTED = 0
STATE_CONNECTED = 2
MODEL_FULL_GYRO = 2
CONN_BLUETOOTH = 2
CLIENT_TIMEOUT = 5.0
RESCAN_S = 1.0


def log(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%Y-%m-%dT%H:%M:%S") + " " + msg
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def is_imu_name(name: str) -> bool:
    low = name.lower()
    return "(imu)" in low or low.endswith(" imu") or " imu)" in low


def is_sunshine_imu(dev: InputDevice) -> bool:
    name = dev.name or ""
    if not is_imu_name(name):
        return False
    low = name.lower()
    return "sunshine" in low or "libvirtualhid" in low or getattr(dev, "phys", "") and "libvirtualhid/uhid" in (dev.phys or "")


def abs_resolution(dev: InputDevice, code: int, default: int) -> int:
    try:
        info = dev.absinfo(code)
        res = int(getattr(info, "resolution", 0) or 0)
        return res if res > 0 else default
    except (OSError, AttributeError, TypeError, ValueError):
        return default


class Slot:
    __slots__ = (
        "connected",
        "mac",
        "battery",
        "packet_number",
        "accel",
        "gyro",
        "motion_ts",
        "name",
    )

    def __init__(self) -> None:
        self.connected = False
        self.mac = b"\x00" * 6
        self.battery = 0x00
        self.packet_number = 0
        self.accel = (0.0, 0.0, 0.0)
        self.gyro = (0.0, 0.0, 0.0)
        self.motion_ts = 0
        self.name = ""


class DSUServer:
    def __init__(self, host: str = DSU_HOST, port: int = DSU_PORT) -> None:
        self.host = host
        self.port = port
        self.server_id = random.getrandbits(32)
        self.slots = [Slot() for _ in range(4)]
        self.sock: socket.socket | None = None
        self._clients: dict[tuple, float] = {}

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.setblocking(False)
        self.sock = sock
        log(f"DSU listening on {self.host}:{self.port}")

    def stop(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def set_connected(self, slot: int, connected: bool, name: str = "", mac: bytes | None = None) -> None:
        if not 0 <= slot < 4:
            return
        s = self.slots[slot]
        s.connected = connected
        s.name = name
        if mac is not None:
            s.mac = mac[:6].ljust(6, b"\x00")
        if not connected:
            s.accel = (0.0, 0.0, 0.0)
            s.gyro = (0.0, 0.0, 0.0)

    def update_motion(self, slot: int, accel: tuple[float, float, float], gyro: tuple[float, float, float]) -> None:
        if not 0 <= slot < 4:
            return
        s = self.slots[slot]
        s.accel = accel
        s.gyro = gyro
        s.motion_ts = time.monotonic_ns() // 1000
        self._broadcast(slot)

    def _finish(self, message_type: int, data: bytes) -> bytes:
        body = struct.pack("<I", message_type) + data
        header = b"DSUS" + struct.pack("<HH", PROTOCOL_VERSION, len(body))
        header += struct.pack("<I", 0) + struct.pack("<I", self.server_id)
        packet = bytearray(header + body)
        crc = zlib.crc32(packet) & 0xFFFFFFFF
        packet[8:12] = struct.pack("<I", crc)
        return bytes(packet)

    def _shared_header(self, slot: int) -> bytes:
        s = self.slots[slot]
        state = STATE_CONNECTED if s.connected else STATE_DISCONNECTED
        model = MODEL_FULL_GYRO if s.connected else 0
        conn = CONN_BLUETOOTH if s.connected else 0
        return struct.pack("<BBBB", slot, state, model, conn) + s.mac + struct.pack("<B", s.battery)

    def _port_info(self, slot: int) -> bytes:
        return self._finish(MSG_PORTS, self._shared_header(slot) + b"\x00")

    def _pad_data(self, slot: int) -> bytes:
        s = self.slots[slot]
        s.packet_number = (s.packet_number + 1) & 0xFFFFFFFF
        data = bytearray(self._shared_header(slot))
        data += struct.pack("<B", 1 if s.connected else 0)
        data += struct.pack("<I", s.packet_number)
        # Buttons unused — Eden takes buttons from EmuPads; zeros are fine.
        data += b"\x00" * 4  # d0,d1,home,touch
        data += bytes([128, 128, 128, 128])  # sticks
        data += b"\x00" * 4  # analog dpad
        data += b"\x00" * 4  # analog face
        data += b"\x00" * 4  # R1 L1 R2 L2
        data += b"\x00" * 12  # touches
        data += struct.pack("<Q", s.motion_ts)
        data += struct.pack("<fff", *s.accel)
        data += struct.pack("<fff", *s.gyro)
        return self._finish(MSG_DATA, bytes(data))

    def _broadcast(self, slot: int) -> None:
        if self.sock is None:
            return
        now = time.monotonic()
        stale = [a for a, t in self._clients.items() if now - t > CLIENT_TIMEOUT]
        for a in stale:
            del self._clients[a]
        if not self._clients:
            return
        packet = self._pad_data(slot)
        for addr in list(self._clients):
            try:
                self.sock.sendto(packet, addr)
            except OSError:
                pass

    def poll_requests(self) -> None:
        if self.sock is None:
            return
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
            except BlockingIOError:
                return
            except OSError:
                return
            if len(data) < 20 or data[:4] != b"DSUC":
                continue
            msg_type = struct.unpack_from("<I", data, 16)[0]
            payload = data[20:]
            try:
                if msg_type == MSG_VERSION:
                    self.sock.sendto(
                        self._finish(MSG_VERSION, struct.pack("<H", PROTOCOL_VERSION)),
                        addr,
                    )
                elif msg_type == MSG_PORTS:
                    if len(payload) >= 4:
                        count = max(0, min(struct.unpack_from("<i", payload, 0)[0], 4))
                        for i in range(count):
                            if 4 + i >= len(payload):
                                break
                            slot = payload[4 + i]
                            if 0 <= slot < 4:
                                self.sock.sendto(self._port_info(slot), addr)
                elif msg_type == MSG_DATA:
                    self._clients[addr] = time.monotonic()
                    for slot in range(4):
                        if self.slots[slot].connected:
                            self.sock.sendto(self._pad_data(slot), addr)
            except OSError:
                pass


class ImuSource:
    def __init__(self, dev: InputDevice) -> None:
        self.dev = dev
        self.path = dev.path
        self.name = dev.name or ""
        self.accel_res = (
            abs_resolution(dev, ecodes.ABS_X, 4096),
            abs_resolution(dev, ecodes.ABS_Y, 4096),
            abs_resolution(dev, ecodes.ABS_Z, 4096),
        )
        self.gyro_res = (
            abs_resolution(dev, ecodes.ABS_RX, 14247),
            abs_resolution(dev, ecodes.ABS_RY, 14247),
            abs_resolution(dev, ecodes.ABS_RZ, 14247),
        )
        self.raw = {
            ecodes.ABS_X: 0,
            ecodes.ABS_Y: 0,
            ecodes.ABS_Z: 0,
            ecodes.ABS_RX: 0,
            ecodes.ABS_RY: 0,
            ecodes.ABS_RZ: 0,
        }
        # Seed from current abs state when possible.
        for code in list(self.raw):
            try:
                self.raw[code] = int(dev.absinfo(code).value)
            except (OSError, AttributeError, TypeError, ValueError):
                pass

    def feed(self, ev) -> bool:
        if ev.type != ecodes.EV_ABS or ev.code not in self.raw:
            return False
        self.raw[ev.code] = ev.value
        return True

    def scaled(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        ax = self.raw[ecodes.ABS_X] / float(self.accel_res[0])
        ay = self.raw[ecodes.ABS_Y] / float(self.accel_res[1])
        az = self.raw[ecodes.ABS_Z] / float(self.accel_res[2])
        gx = self.raw[ecodes.ABS_RX] / float(self.gyro_res[0])
        gy = self.raw[ecodes.ABS_RY] / float(self.gyro_res[1])
        gz = self.raw[ecodes.ABS_RZ] / float(self.gyro_res[2])
        return (ax, ay, az), (gx, gy, gz)


def open_imu_sources() -> list[ImuSource]:
    out: list[ImuSource] = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        name = dev.name or ""
        phys = getattr(dev, "phys", "") or ""
        if not is_imu_name(name):
            continue
        if not (
            "sunshine" in name.lower()
            or "libvirtualhid" in name.lower()
            or "libvirtualhid/uhid" in phys
            or getattr(dev.info, "vendor", 0) == 0x057E
        ):
            continue
        try:
            src = ImuSource(dev)
        except OSError as exc:
            log(f"skip {path}: {exc}")
            continue
        out.append(src)
        log(f"imu + {src.name} {src.path}")
    return out


def enable_eden_udp(ini: Path | None = None) -> bool:
    path = ini or (Path.home() / ".config/eden/qt-config.ini")
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    changed = False
    out: list[str] = []
    seen_enable = False
    seen_servers = False
    for line in lines:
        if line.startswith("enable_udp_controller="):
            seen_enable = True
            if line.strip() != "enable_udp_controller=true":
                out.append("enable_udp_controller=true\n")
                changed = True
            else:
                out.append(line)
            continue
        if line.startswith("udp_input_servers="):
            seen_servers = True
            if "127.0.0.1:26760" not in line:
                out.append("udp_input_servers=127.0.0.1:26760\n")
                changed = True
            else:
                out.append(line)
            continue
        out.append(line)
    if not seen_enable:
        out.append("enable_udp_controller=true\n")
        changed = True
    if not seen_servers:
        out.append("udp_input_servers=127.0.0.1:26760\n")
        changed = True
    if changed:
        path.write_text("".join(out), encoding="utf-8")
        log(f"enabled Eden UDP motion in {path}")
    return changed


def self_test() -> int:
    assert is_imu_name("Sunshine (libvirtualhid) Odin2_Portal (IMU)")
    assert not is_imu_name("Sunshine (libvirtualhid) Odin2_Portal")
    srv = DSUServer(host="127.0.0.1", port=0)
    # bind ephemeral for finish/header packing only
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    srv.port = sock.getsockname()[1]
    sock.close()
    srv.start()
    srv.set_connected(0, True, name="test", mac=b"\x02\x00\x00\x00\x00\x01")
    srv.update_motion(0, (0.0, 0.0, 1.0), (0.1, -0.2, 0.3))
    assert srv.slots[0].accel[2] == 1.0
    pkt = srv._pad_data(0)
    assert pkt.startswith(b"DSUS")
    srv.stop()
    print("emupads-dsu self-test ok")
    return 0


def loop() -> int:
    enable_eden_udp()
    server = DSUServer()
    try:
        server.start()
    except OSError as exc:
        log(f"bind failed: {exc}")
        print(f"DSU bind failed: {exc}", file=sys.stderr)
        return 1

    sources: list[ImuSource] = []
    by_fd: dict[int, ImuSource] = {}
    last_scan = 0.0
    dirty = False

    try:
        while True:
            now = time.monotonic()
            if now - last_scan >= RESCAN_S:
                last_scan = now
                alive = []
                for src in sources:
                    if Path(src.path).exists():
                        alive.append(src)
                    else:
                        log(f"imu - {src.name} {src.path}")
                        try:
                            src.dev.close()
                        except OSError:
                            pass
                if len(alive) != len(sources):
                    sources = alive
                    by_fd = {src.dev.fd: src for src in sources}
                    if not sources:
                        server.set_connected(0, False)
                if not sources:
                    found = open_imu_sources()
                    if found:
                        sources = found
                        by_fd = {src.dev.fd: src for src in sources}
                        mac = b"\x02\x00\x00\x00\x00\x01"
                        server.set_connected(0, True, name=sources[0].name, mac=mac)
                        accel, gyro = sources[0].scaled()
                        server.update_motion(0, accel, gyro)

            server.poll_requests()
            if not sources:
                time.sleep(0.05)
                continue

            r, _, _ = select.select(
                [src.dev.fd for src in sources] + ([server.sock.fileno()] if server.sock else []),
                [],
                [],
                0.05,
            )
            if server.sock and server.sock.fileno() in r:
                server.poll_requests()
            for fd in r:
                src = by_fd.get(fd)
                if src is None:
                    continue
                try:
                    for ev in src.dev.read():
                        if src.feed(ev):
                            dirty = True
                        if ev.type == ecodes.EV_SYN and dirty:
                            accel, gyro = src.scaled()
                            # Slot 0 for first IMU (shared P1). Multi later.
                            slot = 0
                            server.update_motion(slot, accel, gyro)
                            dirty = False
                except BlockingIOError:
                    pass
                except OSError as exc:
                    log(f"imu read error {src.path}: {exc}")
                    sources = [s for s in sources if s.path != src.path]
                    by_fd = {s.dev.fd: s for s in sources}
                    if not sources:
                        server.set_connected(0, False)
    except KeyboardInterrupt:
        pass
    finally:
        for src in sources:
            try:
                src.dev.close()
            except OSError:
                pass
        server.stop()
        log("exit")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--self-test"]:
        return self_test()
    if args == ["--enable-eden"]:
        changed = enable_eden_udp()
        print("eden udp updated" if changed else "eden udp already enabled")
        return 0
    return loop()


if __name__ == "__main__":
    raise SystemExit(main())
