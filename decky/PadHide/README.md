# Pad Hide (Decky)

Unplug extra host pads from Steam / games **without pulling the cable**.
Use case: No More Heroes 3 via Moonlight freaks out when a physical Xbox is
still enumerated next to the Sunshine pad.

Kernel USB `authorized=0` (or HID unbind) drops `/dev/input` nodes. Pairing
and the cable stay. The pad driving Steam/QAM cannot hide itself.

## Script first (SSH / later web)

JSON on stdout is the API. Decky is one client.

```bash
python3 scripts/hide-controllers.py list
python3 scripts/hide-controllers.py hide --id usb:045e:028e:5F19FC0A
python3 scripts/hide-controllers.py show --id usb:045e:028e:5F19FC0A
python3 scripts/hide-controllers.py apply
```

`--force` on `hide` / `set` bypasses the UI-pad guard (SSH only). The plugin
never passes `--force`.

SSH as `deck` needs `sudoers/zzz-hide-controllers` (NOPASSWD on
`scripts/hide-controllers-sysfs.sh`). QAM does not — PluginLoader is root.
Optional `udev/99-hide-controllers.rules` re-applies the hide list on replug.

Config: `~/.config/pad-hide/hidden.json`.

## Install

`scripts/ensure-hide-controllers.sh` then `scripts/ensure-pad-hide-decky.sh`.
`~/homebrew/plugins` is often root-owned; copy needs sudo, then reload Decky.

Skill: `.cursor/skills/pad-hide/SKILL.md`. Reload after edit: `.cursor/skills/decky-plugins/SKILL.md`.
