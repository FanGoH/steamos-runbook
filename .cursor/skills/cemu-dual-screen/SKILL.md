---
name: cemu-dual-screen
description: Put standalone Cemu in desktop dual-stream layout (TV on HDMI-A-1, Wii U GamePad View on Virtual-sunshine-ds) for Thor/Odin Moonlight. Use when the user asks to set up, restore, or place Cemu for two-screen GameStream, GamePad on the Odin/Thor, Wind Waker dual-screen, or after a working Thor Cemu session.
---

# Cemu dual-screen (desktop GameStream)

Run `scripts/ensure-cemu-dual-screen.sh` unless the user only wants a status read. Moonlight app **Cemu Dual-Screen** on sunshine-ds `:48100` runs `scripts/sunshine-app-cemu.sh` (install with `scripts/ensure-sunshine-ds-apps.sh`).

Desktop dual-stream is **not** RetroDECK Game Mode Cemu (`ensure-cemu-input.sh`, `-f`). Plasma needs standalone Flatpak `info.cemu.Cemu`, windowed, emulated **Wii U GamePad**. Game Mode `:48200` uses `scripts/ensure-cemu-gamemode-dual-screen.sh` instead — do **not** run this desktop script there (`kscreen-doctor` / KWin fail).

## Desired layout

| Window | Output | Geometry |
|---|---|---|
| Cemu TV (`resourceClass` `info.cemu.Cemu`, caption is not GamePad View) | HDMI-A-1 | that output’s live origin × size |
| GamePad View | Virtual-sunshine-ds | that output’s live origin × size |

Read live sizes from `kscreen-doctor`. Current Thor checkpoint is HDMI-A-1 **1920×1080** at `0,0` plus Virtual-sunshine-ds **1920×1080** at `1920,0`. Older notes said 1080×1240 — do not hardcode that. Do **not** kill `sunshine-ds-virtual-output`. Do **not** `pgrep -f` / `pkill -f` sunshine. Moonlight must already be on sunshine-ds `:48100`.

## Bind + settings

The script:

1. Writes `settings.xml` from live kscreen (`fullscreen` false, `open_pad` true).
2. Binds player 0 with `python3 scripts/bind-gamepad.py apply --emu cemu --force --cemu-p1 gamepad` onto **EmuPads P1** (mux). Tender tiles pick GamePad vs Pro from whether the second screen is streamed. Do not `--match Thor` into XML (that would narrow mux sources). Pad type is `GAMESTREAM_PAD_PROFILE` (default x360).
3. KWin-places GamePad View → virtual output, other `info.cemu.Cemu` → HDMI, `noBorder` + `keepAbove`. Minimizes Steam.

`controller0.xml` type must stay **Wii U GamePad**. Do not hand-edit the XML. Do not hardcode uuid `0_050017945e0400008e02000014010000` or generic `X-Box 360 Controller`. Cemu uuid is `{guid-index}_{sdl2-crc16-of-kernel-name}`. Named pads: `Sunshine (libvirtualhid) AYN_Thor` / `Odin2_Portal`. SDL GameControllerName is still `Xbox 360 Controller`.

Process `comm` is truncated: `Cemu_relwithdeb`. `pgrep -x Cemu_relwithdebinfo` fails. Dual-screen windows have no chrome. Moonlight overlay **Quit game** SIGTERMs the app wrapper, which kills `Cemu_relwithdeb` / `Cemu-wrapper` (`scripts/sunshine-app-stop.sh cemu`). Same path as Azahar.

## Launch env

If Cemu is not running and `CEMU_ROM` is set in `.env`, the script launches standalone Cemu with:

```bash
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus DISPLAY=:0
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0 SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="$(python3 scripts/pad_profile.py sdl-except)"
flatpak run info.cemu.Cemu -g "<wux>"
```

ROM path is the user’s; Wind Waker HD often lives under `~/emulation/wiiu/windwakerhd/*.wux`. Do not commit a personal ROM path. Do not inherit Steam’s ignore list. Do not use RetroDECK `-f`.

If uuid/mappings changed, restart Cemu (keep sunshine-ds) then re-run the script.

## Game Mode (`:48200`) — checkpoint `checkpoint-2026-09-11-gamemode-tender-ds`

User confirmed 2026-09-11: “amazing, cemu works correctly” — Tender Cemu **tiles** while streaming `:48200` put GamePad on the Thor bottom (`ffplay` x11grab from session `:1`, not `:0`). Overlay/QAM mute EmuPads sinks; Steam Exit `--quit`s immediately. Earlier `checkpoint-2026-09-10-gamemode-tender-ds` attached but grabbed `:0` for a `:1` xid. Do not “improve” this unless it breaks. Full recipe: `.cursor/skills/sunshine-ds-gamemode/SKILL.md`. Screens-only subset: `checkpoint-2026-09-10-gamemode-dual-stream`. Sep 9 `checkpoint-2026-09-09-gamemode-cemu-ds` is the HDMI DCC / Cemu-picture baseline.

One Cemu process cannot place windows on session gamescope (`:0`) and headless gamescope (`:2`). TV stays on `:0` (HDMI / video/0). GamePad View is opened windowed (`CEMU_GAMEMODE_DS=1`, no `-f`), kept mapped on-screen under the raised TV (off-screen `ximagesrc` is MIT-SHM `BadMatch`), and ffplay `-window_id` mirrors that drawable onto `:2` (video/1). Force `SDL_VIDEODRIVER=x11` and **windowmap** ffplay plus `GAMESCOPECTRL_BASELAYER_WINDOW` on `:2` — SDL Wayland leaves the X11 window `IsUnMapped` and PipeWire encodes a black root even though the GamePad pixmap has pixels. Kill leftover `sunshine-ds-kms-virtual` Tk (idle screensaver) or it covers the mirror. On Cemu/mirror exit, `sunshine-ds-gamemode-virtual.sh --paint` restores the clock on video/1. Title screen GamePad often matches TV; unique pad UI is in-game.

A Tender / `rom-launcher` Cemu that still has **`-f`** is the wrong instance (HDMI-only, no GamePad stream). Close it first:

```bash
# Moonlight already on sunshine-ds-kms :48200 (not Decky :47989). Helper :2 already up.
export XDG_RUNTIME_DIR=/run/user/$(id -u)
./scripts/sunshine-app-stop.sh cemu
CEMU_PAD_MATCH=Thor ./scripts/ensure-cemu-gamemode-dual-screen.sh
```

Launch is `scripts/steam-run-shortcut.py` → `SteamClient.Apps.RunGame` (same as Tender Play on the Wind Waker HD tile). `steam://rungameid` / `reaper SteamLaunch` / a host `flatpak run` from GDS or SSH stay a 10×10 InputOnly stub (`FOCUSED_APP` stays 769). Tender `rom-launcher` starts `scripts/cemu-gamescope-focus.sh` **before** RetroDECK so gtk_init sees `FOCUSED_APP=<shortcut>`, `STEAM_GAME` on the Cemu window, and `FOCUS_DISPLAY` middle cardinal **1**. Holding 769 forever is the spinning logo. Setting `GAMESCOPECTRL_BASELAYER_WINDOW` to the stub blacks HDMI — keep Steam BPM as the `:0` baselayer until the TV window is ≥64×64 InputOutput. Steam RunGame does not inherit `CEMU_GAMEMODE_DS`. `ensure-cemu-gamemode-dual-screen.sh` touches `logs/cemu-gamemode-ds.want` immediately before Play; `rom-launcher` / `Cemu-wrapper` consume it (120s max, then delete) and pass `--env=CEMU_GAMEMODE_DS=1` into Flatpak. A leftover file must not survive — that is the spinning logo (windowed 10×10). Steam tile Play without the flag stays `-f`. Dual-stream only for that consume-on-read window. Overlay identity is `STEAM_GAME=<AppId>` on the TV window (`STEAM_OVERLAY=1`). Bind mappings only on `Sunshine (libvirtualhid) AYN_Thor` (Steam wrap may stay listed empty). `SDL_GAMECONTROLLERCONFIG_FILE` overrides community-db **Xbox 360 EasySMX**. Cemu reads uuid at start — bind then launch, do not expect a live rebind.

The script tags the TV window `STEAM_GAME=<AppId>`, sets `GAMESCOPECTRL_BASELAYER_WINDOW` / `GAMESCOPE_FOCUSED_*` to that xid, and `windowactivate`s it (same reclaim as `eden-from-retrodeck.sh`). Do **not** treat `windowraise` alone as enough. Do **not** force Cemu `-f`. On Cemu refocus, GamePad View must stay **under** the TV on session `:1` (x11grab `-i :1.0`) and **ffplay** must be the `:2` baselayer (Thor bottom panel). Do not capture `find_pad_wid` in `$(…)` — that drops `TV_DISPLAY`. Tk `sunshine-ds-kms-virtual` paint covers that stream — kill it. `./scripts/ensure-cemu-gamemode-dual-screen.sh --place-only` re-asserts the layout without relaunching Cemu. The focus watcher must **not** reclaim while Steam overlay is up. GDS `back_button_timeout = 500` pulses HOME on UHID bluetooth x360; Steam ignores that Guide. **sunshine-ds** then toggles `STEAM_OVERLAY=1` on Steam Big Picture plus `FOCUSED_APP=769` / `FOCUSED_APP_GFX=<game>`. Hold Select again to close. `scripts/steam-guide-from-select.py` is debug-only (`--show` / `--hide`); do not start the Python watcher. Fangoh Moonlight GamePad taps are **absolute mouse** (native LI_TOUCH is off). sunshine-ds opens session **`:1` then `:0`** (Cemu `FOCUS_DISPLAY=1`; kms unsets `$DISPLAY`; never headless `:2`), warps onto **GamePad View**, then still emits the uinput click at that cursor. `:0`-only misses GamePad View and every tap lands HDMI `0,0`. Dual-stream/stacked use display 1; Odin **GamePad only** is display 0 with `primary_from_secondary`. Checkpoint **`checkpoint-2026-09-10-gamemode-works`**: both screens + overlay + screensaver + Thor 15-button pad (`LB=b6` `Back=b10`). HDMI DCC baseline is still `119d7452`. Earlier **`checkpoint-2026-09-09-gamemode-cemu-touch-v2`** (`be45fc0f`) is touch/overlay only (HDMI was still DCC-black).

Player 0 maps come from RetroDECK `SteamInput-P1.xml` (the working Wii U GamePad layout). They are copied onto the named Sunshine pad; the Steam virtual uuid is **not** copied. `moonlight.xml` is a Wii U Pro profile — using it on GamePad type leaves analog 7/8 looking fine while d-pad and axis-splits fight the sticks.

`--stop` kills the pad mirror and the gamescope focus watcher only. Overlay/QAM mute EmuPads sinks; Steam Exit (`FOCUSED_APP=769` after 8s, or SIGTERM pending) `--quit`s on the first tick. Moonlight Quit / `sunshine-app-stop.sh cemu` / `--quit` end the game.

## Do not

- RetroDECK `-f` / fullscreen on desktop dual-stream, or on Game Mode dual-stream
- Wii U Pro Controller when the second stream should be GamePad
- Hand-edit `controller0.xml` or copy mappings onto every `<controller>`
- Resize/kill the virtual-output helper to “match” a client while another session is live
- Run `ensure-cemu-dual-screen.sh` in Game Mode (KWin)
- Connect Game Mode Cemu to Decky `:47989` (black / mouse-only). Host is `:48200`.
- `sudo systemctl --user`, `kwin_wayland --replace`, `POST /api/restart`
