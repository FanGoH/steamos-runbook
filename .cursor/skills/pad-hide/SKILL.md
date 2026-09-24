---
name: pad-hide
description: >-
  Hide extra USB/Bluetooth pads from Steam and games without unplugging
  them (kernel authorized=0 / HID unbind). Use when the user mentions Pad
  Hide, NMH3, No More Heroes 3, extra controllers, hide a pad, spoof
  unplugged, hide-controllers, or playing through Moonlight with a
  physical Xbox still connected.
---

# Pad Hide

Script `scripts/hide-controllers.py` is the JSON API. Decky **Pad Hide**, SSH,
and a later web wrapper are clients. Do **not** invent a second hide path
inside `main.py`.

```bash
python3 scripts/hide-controllers.py list
python3 scripts/hide-controllers.py hide --id usb:045e:028e:5F19FC0A
python3 scripts/hide-controllers.py show --id usb:045e:028e:5F19FC0A
python3 scripts/hide-controllers.py apply
```

Off = USB `authorized=0` on the **leaf** device (or HID unbind). Cable and
Bluetooth pairing stay. `/dev/input` nodes disappear so Steam / Eden / NMH3
act like the pad is gone.

## UI pad

The pad driving Steam/QAM (last press/stick) **cannot hide itself**.
Decky never passes `--force`. SSH may use `--force` only if the user asks.

## Do not

- Write `authorized=0` on a USB **hub** (`bDeviceClass=09`, Linux root hub
  `1d6b`). On this box the Xbox is `1-1.3`, not hub `1-1`.
- EVIOCGRAB the Sunshine pad. Steam needs it for overlay / QAM.
- Hide Sunshine / Steam virtual / EmuPads sinks (no USB/HID target).
- `pgrep -f` / `pkill -f` sunshine.
- `sudo systemctl --user`.
- Duplicate bind logic. Extra pads for emulators are Emu Pads routing
  (`.cursor/skills/bind-controller/SKILL.md`); this skill is kernel hide
  for native / NMH3 / “more than one pad”.

## Install

`scripts/ensure-hide-controllers.sh` then `scripts/ensure-pad-hide-decky.sh`.
Reload name is **Pad Hide** (skill `.cursor/skills/decky-plugins/SKILL.md`).
`~/homebrew/plugins` is often root-owned.

SSH as `deck` needs `sudoers/zzz-hide-controllers` (NOPASSWD on
`scripts/hide-controllers-sysfs.sh`). QAM does not — PluginLoader is root
and writes sysfs directly. SteamOS updates wipe `/etc/sudoers.d`.

Optional `udev/99-hide-controllers.rules` re-applies
`~/.config/pad-hide/hidden.json` on replug. `status` / `apply` also re-hide.

Source: `decky/PadHide/`. Config: `~/.config/pad-hide/hidden.json`.

## Debug

1. `python3 scripts/hide-controllers.py list` — physical pads show `method`
   `usb-authorized` or `hid-unbind`. `can_disable: false` + `ui: true` is
   the QAM pad.
2. After hide, `ls /sys/class/input/js*/device/name` must not list that pad.
   `authorized` on the USB leaf is `0`.
3. SSH `sudo: a password is required` → install `zzz-hide-controllers`
   after `wheel` (`scripts/ensure-hide-controllers.sh`).
4. QAM still on the old toggles → reload **Pad Hide**, close and reopen QAM.
