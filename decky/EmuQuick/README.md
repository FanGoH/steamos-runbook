# Emu Quick (Decky)

QAM toggles for **Eden**, **Azahar**, and **Cemu** graphics. Global or per-game (Eden / Azahar `custom/<titleid>.ini`). Cemu is global `settings.xml` only — resolution there is graphic packs, not these keys.

Install: `scripts/ensure-emu-quick-decky.sh`. PluginLoader is root — `main.py` calls `scripts/emu-quick-settings.py` as user `deck`. Never `sudo systemctl --user`. `~/homebrew/plugins` is often `root:root`; copy needs sudo, then reload Decky.

## What it changes

- **Eden:** docked / handheld, resolution scale, GPU accuracy, VSync, scaling filter, AA, anisotropic, speed limit, async shaders. Per-game writes `~/.config/eden/custom/<titleid>.ini` (`use_global=false`). Reset this game sets those keys back to global. Does **not** touch `fullscreen_mode`, pad GUIDs, or Engage’s 4GB `memory_layout_mode`.
- **Azahar:** internal resolution, VSync, frame limit, texture filter, renderer, async shaders, accurate mul, New 3DS. Per-game `custom/<titleid>.ini`. Does **not** touch `layout_option` (dual-screen Separate Windows).
- **Cemu:** VSync, upscale filter, FPS overlay, async compile in standalone + RetroDECK `settings.xml`. Does **not** touch `fullscreen` / GamePad geometry.

Changes are on disk. **Restart the game** to apply. Overlay / QAM can stay open; do not SIGSTOP the emulator.

## CLI

```bash
python3 scripts/emu-quick-settings.py status
python3 scripts/emu-quick-settings.py set --emu eden --scope game --title 0100A6301214E000 --key resolution_setup --value 2
python3 scripts/emu-quick-settings.py reset --emu eden --scope game --title 0100A6301214E000
```
