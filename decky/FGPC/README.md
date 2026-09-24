# FGPC (Decky)

QAM front door for the same catalog as the SSH CLI `fgpc`. Stream is Game
Mode sunshine-ds-kms **:48200** (not Decky Sunshine :47989). Screen, pad
mode/apply, and pad-hide toggles call `scripts/fgpc-api.py`, which calls
the playbook scripts. This plugin does **not** replace Playbook (that is
only post-update) or Emu Pads / Second Screen / Pad Hide.

```bash
python3 scripts/fgpc-api.py dump --no-live
python3 scripts/fgpc-api.py run stream start-kms
python3 scripts/fgpc-api.py run hide off --id usb:045e:028e:5F19FC0A
```

`--force` hide is refused. host / mode / bootstrap / complete stay SSH
`fgpc` only.

Install: `scripts/ensure-fgpc-decky.sh`. PluginLoader is root — dump and
stream/screen/pad run as user `deck`; hide mutates as root (sysfs). Never
`sudo systemctl --user`. Never `pgrep -f` sunshine.

Skill: `.cursor/skills/fgpc/SKILL.md`. Reload: `.cursor/skills/decky-plugins/SKILL.md`.
