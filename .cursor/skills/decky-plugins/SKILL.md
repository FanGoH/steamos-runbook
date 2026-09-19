---
name: decky-plugins
description: >-
  Reload a Decky plugin after editing. Otherwise the user cannot use it.
  Copying decky/<Name>/ into ~/homebrew/plugins is not enough — PluginLoader
  keeps the old Python and QAM bundle in memory. Use when editing
  decky/EmuPads, SecondScreen, EmuQuick, PadHide, sunshine-ds, Tailscale
  Control, main.py, dist/index.js, plugin.json, QAM UI, or running
  ensure-*-decky.sh.
---

# Reload Decky after every plugin edit

**Reload a Decky plugin after editing. Otherwise the user cannot use it.**

Playbook source (`decky/<Name>/`) is not what QAM runs. PluginLoader has the
previous `main.py` + `dist/index.js` in memory until `loader/reload_plugin`.
A file copy without reload leaves the old toggles, methods, and UI.

## After any edit

1. Change playbook `decky/<Name>/` (`main.py`, `plugin.json`, `dist/index.js`).
2. Run the matching `scripts/ensure-*-decky.sh` (copies into `~/homebrew/plugins`
   **and** reloads).
3. Close and reopen QAM if it was already open.

Do not stop after a `cp` into `~/homebrew/plugins`. Do not skip reload because
the files already looked installed.

| Source | Install + reload | `reload_plugin` name (`plugin.json` `name`) |
|---|---|---|
| `decky/EmuPads/` | `scripts/ensure-emu-pads-decky.sh` | `Emu Pads` |
| `decky/SecondScreen/` | `scripts/ensure-second-screen-decky.sh` | `Second Screen` |
| `decky/PadHide/` | `scripts/ensure-pad-hide-decky.sh` | `Pad Hide` |
| `decky/EmuQuick/` | `scripts/ensure-emu-quick-decky.sh` | `Emu Quick` |
| `decky/sunshine-ds/` | `scripts/ensure-sunshine-ds-decky.sh` | `Sunshine DS` |
| Tailscale Control | `scripts/ensure-tailscale-control.sh` | `Tailscale Control` |

`decky_reload_plugin` in `scripts/common.sh` talks to PluginLoader `:1337`
(`loader/reload_plugin`). Use the **display name**, not the folder
(`Pad Hide`, not `PadHide`).

If reload fails, print the Decky → reload plugins (or leave Game Mode and
come back) line from the ensure script. `~/homebrew/plugins` is often
`root:root` — `sudo -n` copy, else `record_manual` with the exact `sudo cp`.

Pad Hide recipe: `.cursor/skills/pad-hide/SKILL.md`. SSH front door: `fgpc decky reload 'Pad Hide'` (`.cursor/skills/fgpc/SKILL.md`).

## Do not

- Edit only the playbook tree and call the QAM UI done.
- `sudo systemctl --user`.
- `pgrep -f` / `pkill -f` sunshine.
- Add an npm build unless asked (`dist/index.js` is the frontend).
