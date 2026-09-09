#!/usr/bin/env python3
"""GameStream virtual-pad profiles (sunshine-ds ``gamepad`` + emulator binds).

One knob: ``GAMESTREAM_PAD_PROFILE`` in ``.env`` (default ``x360``). Cemu uses
SDL GameController labels, so a profile switch mainly changes GUID/VID/PID.
Azahar uses packed joystick indices, which differ between Xbox (15-button
sparse) and DualSense/DS4 (11-button dense). Do not change the profile without
rewriting Azahar maps and restarting sunshine-ds.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NAME = "x360"
SUNSHINE_DS_CONF = Path.home() / ".config/sunshine-ds-dev/sunshine/sunshine.conf"

# Always allow Steam wrap, Decky/DS Xbox variants, Switch Pro, and PS pads so
# a later gyro profile is visible without editing launch env.
_ALWAYS_EXCEPT = (
    ("28de", "11ff"),  # Steam virtual
    ("045e", "02ea"),  # Decky / InputTino Xbox One
    ("045e", "028e"),  # Xbox 360 (current GameStream)
    ("045e", "02fd"),  # Xbox One S
    ("045e", "0b13"),  # Xbox Series (DS auto)
    ("057e", "2009"),  # Switch Pro
    ("054c", "0ce6"),  # DualSense
    ("054c", "05c4"),  # DS4 (libvirtualhid)
    ("054c", "09cc"),  # DS4 CUH-ZCT2
)


def _btn(n: int) -> str:
    return f"button:{n},engine:sdl,guid:{{guid}},port:0"


def _axis(n: int) -> str:
    return f"axis:{n},direction:+,engine:sdl,guid:{{guid}},port:0,threshold:0.5"


def _hat(direction: str) -> str:
    return f"direction:{direction},engine:sdl,guid:{{guid}},hat:0,port:0"


def _stick(x: int, y: int) -> str:
    return f"axis_x:{x},axis_y:{y},deadzone:0.100000,engine:sdl,guid:{{guid}},port:0"


def _azahar_common(face: dict[str, str]) -> dict[str, str]:
    out = dict(face)
    out.update(
        {
            "button_up": _hat("up"),
            "button_down": _hat("down"),
            "button_left": _hat("left"),
            "button_right": _hat("right"),
            "circle_pad": _stick(0, 1),
            "c_stick": _stick(3, 4),
        }
    )
    return out


# libvirtualhid xbox_* enables reserved BTN_C/Z/TL2/TR2 so SDL packing is 15:
# 0A 1B 2C 3X 4Y 5Z 6LB 7RB 8TL2 9TR2 10Back 11Start 12Guide 13LS 14RS
_AZAHAR_SPARSE_XBOX = _azahar_common(
    {
        "button_a": _btn(0),
        "button_b": _btn(1),
        "button_x": _btn(3),
        "button_y": _btn(4),
        "button_l": _btn(6),
        "button_r": _btn(7),
        "button_zl": _axis(2),
        "button_zr": _axis(5),
        "button_select": _btn(10),
        "button_start": _btn(11),
        "button_home": _btn(12),
    }
)

# DualSense/DS4 Linux uinput does not reserve C/Z/TL2/TR2 (11-button pack):
# 0A 1B 2X 3Y 4LB 5RB 6Back 7Start 8Guide 9LS 10RS. Triggers stay ABS_Z/ABS_RZ.
_AZAHAR_DENSE_PS = _azahar_common(
    {
        "button_a": _btn(0),
        "button_b": _btn(1),
        "button_x": _btn(2),
        "button_y": _btn(3),
        "button_l": _btn(4),
        "button_r": _btn(5),
        "button_zl": _axis(2),
        "button_zr": _axis(5),
        "button_select": _btn(6),
        "button_start": _btn(7),
        "button_home": _btn(8),
    }
)

# Switch Pro: TL2/TR2 are digital buttons, not analog axes.
_AZAHAR_SWITCH = _azahar_common(
    {
        "button_a": _btn(1),
        "button_b": _btn(0),
        "button_x": _btn(2),
        "button_y": _btn(3),
        "button_l": _btn(4),
        "button_r": _btn(5),
        "button_zl": _btn(6),
        "button_zr": _btn(7),
        "button_select": _btn(8),
        "button_start": _btn(9),
        "button_home": _btn(10),
    }
)


@dataclass(frozen=True)
class PadProfile:
    name: str
    sunshine_gamepad: str
    vendor: str
    product: str
    supports_motion: bool
    steam_guide: bool
    azahar_map: dict[str, str]
    notes: str

    def sdl_pair(self) -> str:
        return f"0x{self.vendor}/0x{self.product}"


PROFILES: dict[str, PadProfile] = {
    "x360": PadProfile(
        name="x360",
        sunshine_gamepad="x360",
        vendor="045e",
        product="028e",
        supports_motion=False,
        steam_guide=True,
        azahar_map=_AZAHAR_SPARSE_XBOX,
        notes="Default. Steam Guide on uinput 360. No gyro.",
    ),
    "ds5": PadProfile(
        name="ds5",
        sunshine_gamepad="ds5",
        vendor="054c",
        product="0ce6",
        supports_motion=True,
        steam_guide=False,
        azahar_map=_AZAHAR_DENSE_PS,
        notes="DualSense. Gyro yes; Steam Guide and current Cemu/Azahar x360 binds break. Probe Azahar after first switch.",
    ),
    "ds4": PadProfile(
        name="ds4",
        sunshine_gamepad="ds4",
        vendor="054c",
        product="05c4",
        supports_motion=True,
        steam_guide=False,
        azahar_map=_AZAHAR_DENSE_PS,
        notes="DualShock 4. Same Azahar packing as ds5. Steam Guide breaks.",
    ),
    "switch": PadProfile(
        name="switch",
        sunshine_gamepad="switch",
        vendor="057e",
        product="2009",
        supports_motion=True,
        steam_guide=False,
        azahar_map=_AZAHAR_SWITCH,
        notes="Switch Pro. Gyro yes; Nintendo face packing. Untested on GameStream Azahar.",
    ),
}


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip("'\"")
    return out


def requested_profile_name() -> str:
    env = os.environ.get("GAMESTREAM_PAD_PROFILE", "").strip()
    if not env:
        env = _parse_env_file(ROOT / ".env").get("GAMESTREAM_PAD_PROFILE", "")
    name = (env or DEFAULT_NAME).strip().lower()
    if name in ("xbox", "xbox360", "360"):
        return "x360"
    if name in ("dualsense", "ps5"):
        return "ds5"
    if name in ("dualshock4", "ps4"):
        return "ds4"
    if name in ("switch_pro", "switchpro", "pro"):
        return "switch"
    return name


def load_profile(name: str | None = None) -> PadProfile:
    key = (name or requested_profile_name()).strip().lower()
    try:
        return PROFILES[key]
    except KeyError as exc:
        known = ", ".join(PROFILES)
        raise ValueError(f"unknown GAMESTREAM_PAD_PROFILE {key!r} (want {known})") from exc


def sdl_except(profile: PadProfile | None = None) -> str:
    """Whitelist Steam + every GameStream pad we might switch to."""
    pairs = list(_ALWAYS_EXCEPT)
    if profile is not None:
        extra = (profile.vendor, profile.product)
        if extra not in pairs:
            pairs.append(extra)
    return ",".join(f"0x{v}/0x{p}" for v, p in pairs)


def apply_sunshine_conf(path: Path | None = None) -> bool:
    """Set ``gamepad =`` from the active profile. Does not restart sunshine-ds."""
    profile = load_profile()
    conf = path or Path(
        os.environ.get("SUNSHINE_DS_CONF")
        or str(SUNSHINE_DS_CONF)
    )
    if not conf.is_file():
        print(f"Missing {conf}", file=sys.stderr)
        return False
    text = conf.read_text()
    line = f"gamepad = {profile.sunshine_gamepad}"
    pat = re.compile(r"^gamepad\s*=\s*.*$", re.M)
    if pat.search(text):
        new = pat.sub(line, text, count=1)
    else:
        new = text.rstrip() + "\n" + line + "\n"
    if new == text:
        print(f"{conf} already gamepad = {profile.sunshine_gamepad}")
        return False
    conf.write_text(new)
    print(
        f"Set {conf} gamepad = {profile.sunshine_gamepad} "
        f"(profile {profile.name}; restart sunshine-ds to apply)"
    )
    return True


def profile_public_dict(profile: PadProfile) -> dict[str, object]:
    return {
        "name": profile.name,
        "sunshine_gamepad": profile.sunshine_gamepad,
        "vendor": profile.vendor,
        "product": profile.product,
        "vid_pid": f"{profile.vendor}:{profile.product}",
        "supports_motion": profile.supports_motion,
        "steam_guide": profile.steam_guide,
        "sdl_except": sdl_except(profile),
        "notes": profile.notes,
    }


def _self_test() -> int:
    x360 = load_profile("x360")
    ds5 = load_profile("ds5")
    assert x360.vendor == "045e" and x360.product == "028e"
    assert not x360.supports_motion and x360.steam_guide
    assert ds5.supports_motion and ds5.vendor == "054c"
    assert "button:6" in x360.azahar_map["button_l"]
    assert "button:10" in x360.azahar_map["button_select"]
    assert "button:4" in ds5.azahar_map["button_l"]
    assert "button:6" in ds5.azahar_map["button_select"]
    except_s = sdl_except(x360)
    assert "0x045e/0x028e" in except_s
    assert "0x054c/0x0ce6" in except_s
    tmp = Path("/tmp/pad-profile-conf-test.conf")
    tmp.write_text("gamepad = auto\n")
    prev = os.environ.get("GAMESTREAM_PAD_PROFILE")
    os.environ["GAMESTREAM_PAD_PROFILE"] = "x360"
    assert apply_sunshine_conf(tmp) is True
    assert "gamepad = x360" in tmp.read_text()
    assert apply_sunshine_conf(tmp) is False
    tmp.unlink(missing_ok=True)
    if prev is None:
        os.environ.pop("GAMESTREAM_PAD_PROFILE", None)
    else:
        os.environ["GAMESTREAM_PAD_PROFILE"] = prev
    print("pad_profile self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "json"
    if cmd == "self-test":
        return _self_test()
    if cmd == "list":
        json.dump({"profiles": list(PROFILES)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    try:
        profile = load_profile(args[1] if cmd == "json" and len(args) > 1 else None)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if cmd in ("json", "show"):
        json.dump(profile_public_dict(profile), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if cmd in ("sdl-except", "except"):
        print(sdl_except(profile))
        return 0
    if cmd == "sunshine":
        print(profile.sunshine_gamepad)
        return 0
    if cmd == "name":
        print(profile.name)
        return 0
    if cmd == "apply-sunshine-conf":
        path = Path(args[1]) if len(args) > 1 else None
        apply_sunshine_conf(path)
        return 0
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
