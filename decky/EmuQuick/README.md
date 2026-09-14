# Emu Quick (Decky)

QAM toggles for **Eden**, **Azahar**, and **Cemu** graphics. Global or per-game (Eden / Azahar `custom/<titleid>.ini`). Cemu is global `settings.xml` only — resolution there is graphic packs, not these keys.

Install: `scripts/ensure-emu-quick-decky.sh`. PluginLoader is root — `main.py` calls `scripts/emu-quick-settings.py` as user `deck`. Never `sudo systemctl --user`. `~/homebrew/plugins` is often `root:root`; copy needs sudo, then reload Decky.

## What it changes

- **Eden:** docked / handheld, resolution scale, GPU accuracy, VSync, scaling filter, AA, anisotropic, speed limit, async shaders. Per-game writes `~/.config/eden/custom/<titleid>.ini` (`use_global=false`). Reset this game sets those keys back to global. Does **not** touch `fullscreen_mode`, pad GUIDs, or Engage’s 4GB `memory_layout_mode`.
- **Azahar:** internal resolution, VSync, frame limit, texture filter, renderer, async shaders, accurate mul, New 3DS. Per-game `custom/<titleid>.ini`. Does **not** touch `layout_option` (dual-screen Separate Windows).
- **Cemu:** VSync, upscale filter, FPS overlay, async compile in standalone + RetroDECK `settings.xml`. Does **not** touch `fullscreen` / GamePad geometry.

Sliders and toggles stay **unsaved** until **Save**. A toast appears only on Save (or Reset). **This game** needs a title id: the running dump, Eden’s `Booting game` log, a unique library name match, or Prev/Next. A folder dump with no id in the path used to show the name while Save still asked to pick a game.

## Live apply (Eden)

Live rows send the Eden hotkey immediately and **do not write INI**. Session state tracks the in-memory value so a second F8/F10 is computed from what was actually applied, not from disk. Save later writes the draft.

| Setting | Live | How |
|---|---|---|
| Docked | yes | F10 toggle (`Change Docked Mode`) |
| Scaling filter | yes | F8 cycles from the live session value |
| GPU accuracy Normal ↔ High | yes | F9. **Extreme still needs an Eden restart** |
| Limit speed | yes | Ctrl+U toggle |
| Resolution scale | no | no hotkey; Save then **close and reopen Eden** (F6 keeps in-memory Settings) |

Hotkeys come from `qt-config.ini`. Apply tries `xdotool key --window` first so QAM can keep focus; if gamescope drops that, it focuses Eden, sends the key, then restores the previous window. Live apply only if the running title matches. Do not SIGSTOP the emulator. Needs `xdotool`.

## CLI

```bash
python3 scripts/emu-quick-settings.py status
python3 scripts/emu-quick-settings.py set --live --emu eden --scope game --title 0100A6301214E000 --key use_docked_mode --value false
python3 scripts/emu-quick-settings.py save --emu eden --scope game --title 0100A6301214E000 --values '{"use_docked_mode":"false"}'
python3 scripts/emu-quick-settings.py reset --emu eden --scope game --title 0100A6301214E000
```
