# Second Screen (Decky)

Game Mode QAM for **emulator dual-screen** and **putting a gamescope window on the Moonlight bottom stream**. Game Mode `:48200` standard: **`checkpoint-2026-09-18-gamepad-xtest`**. Recipe: `.cursor/skills/sunshine-ds-gamemode/SKILL.md`.

Install: `scripts/ensure-second-screen-decky.sh`. PluginLoader is root — `main.py` calls `scripts/second-screen-windows.py` as user `deck`. Never `sudo systemctl --user`. Never `pgrep -f` sunshine. `~/homebrew/plugins` is often `root:root`; copy needs sudo, then reload Decky.

## Emulator dual-screen

Same `mux.json` `dual_screen` key as the bind path (`auto` / `on` / `off`):

- **Auto** (default): Tender Cemu/Azahar GamePad layout only when a connected Moonlight client is watching the host second display (`video/1` or GamePad-only). Top-only clients stay HDMI `-f`. Open **Second Screen** in QAM (not Emu Pads): the plugin title is `Second Screen · Thor`, and the first panel lists each client as a Field (`Thor` / Dual-screen size, `Odin` / top-only). A toast fires on connect/disconnect (skip the first poll). Tiles read that live at Play (`rom-launcher` logs `reason` + `clients`); Steam LaunchOptions stay the RetroDECK line. Close and reopen QAM after a plugin reload.
- **Dual-screen**: force that path while `:48200` is BUSY.
- **HDMI only**: never dual-screen.

## Windows

Lists mapped windows on session gamescope (`:0`, `:1`) and headless `:2`. A window cannot move across X servers. **Show on second screen** keeps the source mapped and `ffplay` `x11grab`s it onto `:2` at 1920×1080 (same as Cemu/Azahar GamePad). A window already on `:2` is maximized in place. **Moonlight Screensaver** stops that grab and `--paint`s the idle clock.

Do not use this to `--start` kms while `:2` is up. Do not grab the Sunshine pad.
