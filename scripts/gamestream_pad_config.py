#!/usr/bin/env python3
"""Host GameStream pad profile + DSU motion calibration.

Config: ``~/.config/emupads/gamestream-pad.json`` (overrides ``GAMESTREAM_PAD_PROFILE`` in ``.env`` when ``profile`` is set).

Moonlight DS fetches ``GET /api/moonlight/pad-profile`` on fgpc (:8484) when the client preference is **Use host profile**.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(
    os.environ.get(
        "GAMESTREAM_PAD_CONFIG",
        Path.home() / ".config/emupads/gamestream-pad.json",
    )
)

PROFILE_NAMES = ("x360", "auto", "switch", "ds5", "ds4")
REPORT_TYPES = ("host", "auto", "xbox", "nintendo", "ps", "unknown")

_DEFAULT_DSU = {
    "gyro_gain": [1.0, 1.15, 1.4],
    "gyro_deadzone": [0.35, 0.35, 0.22],
    "accel_gain": [1.0, 1.0, 1.25],
    "gyro_bias": [0.0, 0.0, 0.0],
    "gravity": [0.0, -1.0, 0.0],
    "bias_ready": False,
}

MOONLIGHT_REPORT_MAP = {
    "xbox": 0x01,
    "ps": 0x02,
    "nintendo": 0x03,
    "unknown": 0x00,
    "auto": None,
    "host": None,
}


def _default_config() -> dict[str, Any]:
    return {
        "profile": None,
        "moonlight_report_type": "host",
        "moonlight_fgpc_port": int(os.environ.get("FGPC_WEB_PORT", "8484")),
        "dsu": dict(_DEFAULT_DSU),
    }


def load_config() -> dict[str, Any]:
    cfg = _default_config()
    if not CONFIG_PATH.is_file():
        return cfg
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return cfg
    if not isinstance(raw, dict):
        return cfg
    if raw.get("profile") is not None:
        cfg["profile"] = str(raw["profile"]).strip().lower() or None
    if "moonlight_report_type" in raw:
        cfg["moonlight_report_type"] = str(raw["moonlight_report_type"]).strip().lower()
    if "moonlight_fgpc_port" in raw:
        try:
            cfg["moonlight_fgpc_port"] = int(raw["moonlight_fgpc_port"])
        except (TypeError, ValueError):
            pass
    dsu = raw.get("dsu")
    if isinstance(dsu, dict):
        merged = dict(cfg["dsu"])
        for key in _DEFAULT_DSU:
            if key in dsu:
                merged[key] = dsu[key]
        cfg["dsu"] = merged
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def dsu_settings() -> dict[str, Any]:
    return dict(load_config().get("dsu") or _DEFAULT_DSU)


def _parse_triplet(raw: object, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        try:
            return (float(raw[0]), float(raw[1]), float(raw[2]))
        except (TypeError, ValueError):
            pass
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) == 3:
            try:
                return (float(parts[0]), float(parts[1]), float(parts[2]))
            except ValueError:
                pass
    return default


def dsu_triplets() -> dict[str, tuple[float, float, float]]:
    d = dsu_settings()
    return {
        "gyro_gain": _parse_triplet(d.get("gyro_gain"), (1.0, 1.15, 1.4)),
        "gyro_deadzone": _parse_triplet(d.get("gyro_deadzone"), (0.35, 0.35, 0.22)),
        "accel_gain": _parse_triplet(d.get("accel_gain"), (1.0, 1.0, 1.25)),
        "gyro_bias": _parse_triplet(d.get("gyro_bias"), (0.0, 0.0, 0.0)),
        "gravity": _parse_triplet(d.get("gravity"), (0.0, -1.0, 0.0)),
    }


def dsu_bias_ready() -> bool:
    return bool(dsu_settings().get("bias_ready"))


def moonlight_api_payload() -> dict[str, Any]:
    """JSON for Moonlight DS + fgpc status."""
    # Import here so ``pad_profile self-test`` works without circular issues at module load.
    sys.path.insert(0, str(ROOT / "scripts"))
    import pad_profile as pp  # noqa: WPS433

    cfg = load_config()
    eff = pp.effective_profile()
    req = pp.requested_profile_name()
    report = str(cfg.get("moonlight_report_type") or "host").lower()
    if report not in REPORT_TYPES:
        report = "host"
    li_type = MOONLIGHT_REPORT_MAP.get(report)
    if report == "host":
        # Host picks the LI type that matches the effective Sunshine profile.
        li_type = {
            "switch": 0x03,
            "ds5": 0x02,
            "ds4": 0x02,
            "x360": 0x01,
            "auto": None,
        }.get(eff.name, 0x03 if eff.supports_motion else 0x01)
    return {
        "ok": True,
        "profile": eff.name,
        "requested_profile": req,
        "sunshine_gamepad": eff.sunshine_gamepad,
        "supports_motion": eff.supports_motion,
        "moonlight_report_type": report,
        "li_ctype": li_type,
        "fgpc_port": int(cfg.get("moonlight_fgpc_port") or 8484),
        "config_path": str(CONFIG_PATH),
        "dsu": dsu_settings(),
    }


def set_profile(name: str) -> dict[str, Any]:
    key = name.strip().lower()
    if key in ("xbox", "xbox360", "360"):
        key = "x360"
    if key not in PROFILE_NAMES:
        known = ", ".join(PROFILE_NAMES)
        return {"ok": False, "message": f"unknown profile {name!r} (want {known})"}
    cfg = load_config()
    cfg["profile"] = key
    save_config(cfg)
    return {"ok": True, "profile": key, "message": f"saved profile={key} in {CONFIG_PATH}"}


def set_moonlight_report(kind: str) -> dict[str, Any]:
    key = kind.strip().lower()
    if key not in REPORT_TYPES:
        return {"ok": False, "message": f"moonlight_report_type must be one of {', '.join(REPORT_TYPES)}"}
    cfg = load_config()
    cfg["moonlight_report_type"] = key
    save_config(cfg)
    return {"ok": True, "moonlight_report_type": key}


def apply_sunshine(*, restart_gamemode: bool = False) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import pad_profile as pp  # noqa: WPS433

    kms = Path.home() / ".config/sunshine-ds-gamemode/sunshine.conf"
    desk = Path.home() / ".config/sunshine-ds-dev/sunshine/sunshine.conf"
    changed = False
    for path in (desk, kms):
        if path.is_file():
            changed = pp.apply_sunshine_conf(path) or changed
    out: dict[str, Any] = {
        "ok": True,
        "changed": changed,
        "effective": pp.effective_profile().name,
        "sunshine_gamepad": pp.effective_profile().sunshine_gamepad,
    }
    if restart_gamemode:
        proc = subprocess.run(
            [
                "systemctl",
                "--user",
                "restart",
                "steamos-sunshine-ds-gamemode.service",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={
                **os.environ,
                "XDG_RUNTIME_DIR": os.environ.get(
                    "XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"
                ),
            },
        )
        out["restart_rc"] = proc.returncode
        out["restart_message"] = (proc.stdout or proc.stderr or "").strip()[-400:]
        out["ok"] = proc.returncode == 0
    return out


def _joycond_remap(raw_ax: float, raw_ay: float, raw_az: float, raw_gx: float, raw_gy: float, raw_gz: float):
    """hid-nintendo scaled → cemuhook pitch/yaw/roll (joycond-cemuhook)."""
    accel = (raw_ay, -raw_az, raw_ax)
    gyro = (-raw_gy, -raw_gz, raw_gx)
    return accel, gyro


def recalibrate_dsu(*, seconds: float = 2.0) -> dict[str, Any]:
    try:
        from evdev import InputDevice, ecodes, list_devices
    except ImportError:
        return {"ok": False, "message": "python-evdev missing"}

    path = None
    for dev_path in list_devices():
        try:
            dev = InputDevice(dev_path)
        except OSError:
            continue
        name = (dev.name or "").lower()
        phys = getattr(dev, "phys", "") or ""
        if "(imu)" not in name:
            continue
        if "sunshine" in name or "libvirtualhid" in phys:
            path = dev_path
            break
    if not path:
        return {"ok": False, "message": "No Sunshine (IMU) node — reconnect Moonlight with motion on."}

    dev = InputDevice(path)
    res_a = 4096.0
    res_g = 14247.0
    raw = {ecodes.ABS_X: 0, ecodes.ABS_Y: 0, ecodes.ABS_Z: 0, ecodes.ABS_RX: 0, ecodes.ABS_RY: 0, ecodes.ABS_RZ: 0}
    for code in raw:
        try:
            raw[code] = int(dev.absinfo(code).value)
        except (OSError, AttributeError, TypeError, ValueError):
            pass

    accels: list[tuple[float, float, float]] = []
    gyros: list[tuple[float, float, float]] = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        try:
            dirty = False
            for ev in dev.read():
                if ev.type == ecodes.EV_ABS and ev.code in raw:
                    raw[ev.code] = ev.value
                    dirty = True
                if ev.type == ecodes.EV_SYN and dirty:
                    ax = raw[ecodes.ABS_X] / res_a
                    ay = raw[ecodes.ABS_Y] / res_a
                    az = raw[ecodes.ABS_Z] / res_a
                    gx = raw[ecodes.ABS_RX] / res_g
                    gy = raw[ecodes.ABS_RY] / res_g
                    gz = raw[ecodes.ABS_RZ] / res_g
                    a, g = _joycond_remap(ax, ay, az, gx, gy, gz)
                    accels.append(a)
                    gyros.append(g)
        except BlockingIOError:
            time.sleep(0.005)

    if len(accels) < 20:
        return {"ok": False, "message": "Too few IMU samples — hold the device still and retry."}

    n = float(len(accels))
    grav = tuple(sum(v[i] for v in accels) / n for i in range(3))
    bias = tuple(sum(v[i] for v in gyros) / n for i in range(3))
    gmag = (grav[0] ** 2 + grav[1] ** 2 + grav[2] ** 2) ** 0.5
    if abs(gmag - 1.0) > 0.25:
        return {
            "ok": False,
            "message": f"Hold the controller level and still (|g|={gmag:.2f}, want ~1.0).",
        }

    cfg = load_config()
    dsu = dict(cfg.get("dsu") or _DEFAULT_DSU)
    dsu["gravity"] = [round(grav[0], 5), round(grav[1], 5), round(grav[2], 5)]
    dsu["gyro_bias"] = [round(bias[0], 5), round(bias[1], 5), round(bias[2], 5)]
    dsu["bias_ready"] = True
    cfg["dsu"] = dsu
    save_config(cfg)

    subprocess.run(
        ["systemctl", "--user", "restart", "emupads-dsu.service"],
        capture_output=True,
        timeout=15,
    )
    return {
        "ok": True,
        "message": "DSU neutral pose saved; emupads-dsu restarted.",
        "gravity": dsu["gravity"],
        "gyro_bias": dsu["gyro_bias"],
        "samples": len(accels),
    }


def _self_test() -> int:
    global CONFIG_PATH
    tmp = Path("/tmp/gamestream-pad-config-selftest.json")
    prev_path = CONFIG_PATH
    CONFIG_PATH = tmp
    try:
        save_config(_default_config())
        assert load_config()["moonlight_report_type"] == "host"
        r = set_profile("switch")
        assert r["ok"] and load_config()["profile"] == "switch"
        api = moonlight_api_payload()
        assert api["ok"] and "li_ctype" in api
        assert _parse_triplet([1, 2, 3], (0, 0, 0)) == (1.0, 2.0, 3.0)
    finally:
        CONFIG_PATH = prev_path
        tmp.unlink(missing_ok=True)
    print("gamestream-pad-config self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args == ["json"]:
        json.dump(moonlight_api_payload(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if args == ["self-test"]:
        return _self_test()
    if args[0] == "set-profile" and len(args) >= 2:
        out = set_profile(args[1])
        print(out.get("message", out))
        return 0 if out.get("ok") else 2
    if args[0] == "set-moonlight-report" and len(args) >= 2:
        out = set_moonlight_report(args[1])
        print(out.get("message", out))
        return 0 if out.get("ok") else 2
    if args[0] == "recalibrate-dsu":
        out = recalibrate_dsu()
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 2
    if args[0] == "apply":
        restart = "--restart-gamemode" in args
        out = apply_sunshine(restart_gamemode=restart)
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1
    print(
        "usage: gamestream-pad-config.py [json|self-test|set-profile NAME|"
        "set-moonlight-report TYPE|recalibrate-dsu|apply [--restart-gamemode]]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
