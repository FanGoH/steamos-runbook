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
2. Binds player 0 with `python3 scripts/bind-gamepad.py cemu --match "${CEMU_PAD_MATCH:-Thor}" --force` (fallback `--match Sunshine`). Mappings go **only** on the named Sunshine pad; Steam wrap may stay listed with empty `<mappings>`. Last-write-wins: do not reorder Sunshine first while Steam still has mappings. Drop `AYN20Thor`. Pad type is `GAMESTREAM_PAD_PROFILE` (default x360).
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

## Game Mode (`:48200`)

One Cemu process cannot place windows on session gamescope (`:0`) and headless gamescope (`:2`). TV stays on `:0` (HDMI / video/0). GamePad View is opened windowed (`CEMU_GAMEMODE_DS=1`, no `-f`), parked off-screen at `1920,0`, and `ximagesrc` mirrors that xid onto `:2` (video/1).

```bash
# Moonlight already on sunshine-ds-kms :48200. Helper :2 already up.
scripts/ensure-cemu-gamemode-dual-screen.sh
```

Launch is `reaper SteamLaunch AppId=2374129079` (Wind Waker HD tile) plus the RetroDECK Cemu command with `--env=CEMU_GAMEMODE_DS=1`. Does **not** rewrite `shortcuts.vdf`. Overlay is Steam’s Game Mode overlay (`STEAM_OVERLAY=1` / focused shortcut), not host `LD_PRELOAD` of `gameoverlayrenderer.so` into the Flatpak.

`--stop` kills only the pad mirror. Steam Exit / Moonlight Quit still owns Cemu.

## Do not

- RetroDECK `-f` / fullscreen on desktop dual-stream, or on Game Mode dual-stream
- Wii U Pro Controller when the second stream should be GamePad
- Hand-edit `controller0.xml` or copy mappings onto every `<controller>`
- Resize/kill the virtual-output helper to “match” a client while another session is live
- Run `ensure-cemu-dual-screen.sh` in Game Mode (KWin)
- `sudo systemctl --user`, `kwin_wayland --replace`, `POST /api/restart`
