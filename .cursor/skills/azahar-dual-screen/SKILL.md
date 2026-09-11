---
name: azahar-dual-screen
description: Put standalone Azahar in desktop dual-stream layout (3DS top screen on HDMI-A-1, bottom touch screen on Virtual-sunshine-ds) for Thor/Odin Moonlight. Use when the user asks to set up, restore, or place Azahar/Citra/3DS for two-screen GameStream, or after a working Thor Cemu session to replicate it on 3DS.
---

# Azahar dual-screen (desktop GameStream)

Run `scripts/ensure-azahar-dual-screen.sh` unless the user only wants a status read. Moonlight app **Azahar Dual-Screen** on sunshine-ds `:48100` runs `scripts/sunshine-app-azahar.sh` (install with `scripts/ensure-sunshine-ds-apps.sh`). Open launches the Azahar library immediately — no pad wait, no extra sleep before the window is placed. Optional `.env` `AZAHAR_ROM` boots a dump instead of the library.

This is **not** RetroDECK Azahar (`azahar-launcher`, fullscreen, `layout_option=0`). Dual-stream needs standalone Flatpak `org.azahar_emu.Azahar`, **Separate Windows**, X11/xcb.

## Desired layout

| Window | Caption contains | Output | Geometry |
|---|---|---|---|
| 3DS top | `Primary Window` | HDMI-A-1 | that output’s live origin × size |
| 3DS bottom (touch) | `Secondary Window` | Virtual-sunshine-ds | that output’s live origin × size |
| Azahar UI | `Azahar 2126` without Primary/Secondary | minimize | — |

Read live sizes from KWin `workspace.screens` (do not block on `kscreen-doctor -j`; it can hang with duplicate virtual outputs). Same Thor checkpoint as Cemu: HDMI-A-1 **1920×1080** at `0,0` plus Virtual-sunshine-ds **1920×1080** at `1920,0`. Do **not** kill `sunshine-ds-virtual-output`. Moonlight must already be on sunshine-ds `:48100`.

## Bind + settings

The script:

1. Sets `qt-config.ini`: `layout_option=4` (Separate Windows), `secondary_display_layout=2` (BottomScreenOnly), `fullscreen` false, `singleWindowMode` false, `confirmClose` false, **`screen_bottom_stretch` / `screen_top_stretch` true**. Without stretch, Azahar `MaxRectangle` fits 4:3 / 5:3 by **height** inside 1920×1080 (pillarbox). Cemu GamePad already filled that window; the 3DS bottom must stretch the same way or Thor’s GamePad fill looks like it only filled vertically.
2. Binds with `python3 scripts/bind-gamepad.py apply --emu azahar --force` onto **EmuPads P1**. Do not `--match Thor` into the INI. Button indices come from `GAMESTREAM_PAD_PROFILE` (`scripts/pad_profile.py`). Default x360 is a **15-button** SDL joystick (reserved C/Z/TL2/TR2), not Steam’s 11-button xpad map. 3DS A/B/X/Y = SDL 0/1/3/4, L/R = 6/7 (LB/RB), Select/Start/Home = 10/11/12, ZL/ZR = LT/RT axes. Restart Azahar after the first sink bind only.
3. KWin-places Primary → HDMI, Secondary → virtual, `noBorder` + `keepAbove`. Minimizes Steam. Library boot does not create Primary/Secondary until a game is chosen, and those views often appear as ~400×480 / ~400×240 *before* the captions are set — do not minimize untitled small Azahar windows. Keep the library on HDMI until a game view exists, then minimize it. `sunshine-app-azahar.sh` re-places (`--place-only`) until Azahar exits; the first place also watches `windowAdded` / `captionChanged`.

Do not hand-edit `qt-config.ini`. Restart Azahar after a GUID or button-map change. Do not copy RetroDECK’s L=LT / ZL=LB swap onto GameStream.

## Launch env

Qt Wayland hits `wp_linux_drm_syncobj_surface_v1` and dies. Launch **xcb only** (do not `--socket=wayland`):

```bash
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus DISPLAY=:0 QT_QPA_PLATFORM=xcb
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0 SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="$(python3 scripts/pad_profile.py sdl-except)"
flatpak run --env=QT_QPA_PLATFORM=xcb org.azahar_emu.Azahar "<3ds>"
```

If `AZAHAR_ROM` is set and Azahar is not running, the script launches. Example dump: `~/emulation/3ds/games/.../*.3ds`. Do not commit a personal ROM path. Do not inherit Steam’s ignore list. Do not use RetroDECK `-f` / `azahar-launcher`.

## Game Mode (`:48200`)

Host/capture/screensaver recipe is `.cursor/skills/sunshine-ds-gamemode/SKILL.md` (`checkpoint-2026-09-11-gamemode-tender-ds`). Do **not** run the KWin desktop script in Game Mode. Use `scripts/ensure-azahar-gamemode-dual-screen.sh` (standalone Azahar, SteamLaunch, Secondary Window `ffplay` `x11grab` onto `:2`). Tender 3DS Play while `:48200` is BUSY + virtual sidecar skips RetroDECK `azahar-launcher` and execs that script with the dump (`AZAHAR_PAD_MATCH` default **Thor** on that path). Local Play (kms FREE) stays RetroDECK. Manual default pad is **Odin**. `--attach` waits for an already-open Azahar (no second SteamLaunch). Restart Azahar after a GUID change. After `ensure-sunshine-ds-gamemode.sh --start`, re-run `--mirror-only` (kms recreates `:2` and the idle screensaver covers the 3DS bottom). On Azahar/mirror exit, leftover `:2` x11grab must die then `--paint` or the bottom stays frozen. Overlay is the Cemu recipe when Steam Big Picture is mapped; otherwise sunshine-ds sends `steam://overlay/toggle`. The Game Mode focus watcher must **not** reclaim Primary on `FOCUSED_APP=769` without `STEAM_OVERLAY` (that steals overlay ~2s later). Do **not** start `steam-guide-from-select.py`.

Process `comm` is `azahar`. `resourceClass` is `Azahar`. Dual-screen windows have no close button; 3DS Home does not quit Azahar. Playbook `reaper SteamLaunch` is a **systemd --user** child, so Steam Exit never SIGTERMs it — that is the OoT “Exiting…” hog. Overlay/QAM mute EmuPads sinks; Exit (`FOCUSED_APP=769`, no overlay, no QAM blur) runs `ensure-azahar-gamemode-dual-screen.sh --quit` after ~2s. Moonlight **Quit game** or `scripts/sunshine-app-stop.sh azahar` / `--quit`. Do not `pkill -f` sunshine. Do not wait for a Sunshine pad before launching.

## Do not

- RetroDECK `azahar-launcher` / fullscreen / default stacked layout
- Native Qt Wayland (`--socket=wayland`) — drm_syncobj protocol error
- Hand-edit `qt-config.ini` GUIDs
- Resize/kill the virtual-output helper
- Do **not** run `ensure-azahar-dual-screen.sh` in Game Mode (KWin). Use `ensure-azahar-gamemode-dual-screen.sh`.
