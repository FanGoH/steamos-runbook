---
name: cemu-dual-screen
description: Put standalone Cemu in desktop dual-stream layout (TV on HDMI-A-1, Wii U GamePad View on Virtual-sunshine-ds) for Thor/Odin Moonlight. Use when the user asks to set up, restore, or place Cemu for two-screen GameStream, GamePad on the Odin/Thor, or Wind Waker dual-screen.
---

# Cemu dual-screen (desktop GameStream)

Run `scripts/ensure-cemu-dual-screen.sh` unless the user only wants a status read.

This is **not** RetroDECK Game Mode Cemu (`ensure-cemu-input.sh`, `-f`). Dual-stream needs standalone Flatpak `info.cemu.Cemu`, windowed, emulated **Wii U GamePad**.

## Desired layout

| Window | Output | Geometry |
|---|---|---|
| Cemu TV (`resourceClass` `info.cemu.Cemu`, caption is not GamePad View) | HDMI-A-1 | `0,0` × that output |
| GamePad View | Virtual-sunshine-ds | that output’s current origin × size |

Read live sizes from `kscreen-doctor`. Do **not** kill `sunshine-ds-virtual-output`. Do **not** `pgrep -f` / `pkill -f` sunshine. Moonlight must already be on sunshine-ds `:48100`.

## Settings

`~/.var/app/info.cemu.Cemu/config/Cemu/settings.xml` (stop Cemu first if changing type; pad/window size can be written while running then KWin-placed):

- `fullscreen` false, `open_pad` true
- TV `window_position` / `window_size` = HDMI
- `pad_position` / `pad_size` = virtual output

`controllerProfiles/controller0.xml`: `<type>Wii U GamePad</type>`. Player 0 uuid `0_030079f6de280000ff11000001000000` (Steam wrap `28de:11ff`), fallback Sunshine x360 `0_050017945e0400008e02000014010000`. Pro Controller is the failure mode.

## Launch env

```bash
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus DISPLAY=:0
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0 SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT='0x28de/0x11ff,0x045e/0x02ea,0x045e/0x028e,0x045e/0x02fd,0x057e/0x2009'
flatpak run info.cemu.Cemu -g "<wux>"
```

ROM path is the user’s; Wind Waker HD often lives under `~/emulation/wiiu/windwakerhd/*.wux`. Do not inherit Steam’s ignore list.

## After launch

1. Minimize Steam Big Picture.
2. Load a KWin script: GamePad View → virtual output, `noBorder` + `keepAbove`; other `info.cemu.Cemu` → HDMI, same flags.
3. Persistent KWin rule `wmclass=info.cemu.Cemu` keep above + no border is OK.

## Do not

- RetroDECK `-f` / fullscreen
- Wii U Pro Controller when the second stream should be GamePad
- Resize/kill the virtual-output helper to “match” a client while another session is live
- `sudo systemctl --user`, `kwin_wayland --replace`, `POST /api/restart`
