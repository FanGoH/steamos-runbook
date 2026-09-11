---
name: bind-controller
description: Bind Cemu, Azahar, or Eden to a host gamepad (Thor, Odin, Sunshine pad, Steam virtual). Use when the user says the controller is not working, asks to change Cemu/Azahar/3DS/Eden/Switch controllers, switch pads, experiment with gyro, reorder pads, or install the Emu Pads Decky plugin.
---

# Bind controller

Do **not** hand-edit `controller0.xml` or emulator INI. Run the script (or the Decky plugin, which calls it).

```bash
python3 scripts/bind-gamepad.py list
python3 scripts/bind-gamepad.py status
python3 scripts/bind-gamepad.py profile
python3 scripts/bind-gamepad.py apply --emu cemu --pads js3
python3 scripts/bind-gamepad.py apply --emu all --match Thor,Odin
python3 scripts/bind-gamepad.py cemu --match Thor
python3 scripts/bind-gamepad.py azahar --match Thor
python3 scripts/bind-gamepad.py eden --match Thor
# or, if names are still generic:
python3 scripts/bind-gamepad.py cemu --wait
```

## Decky: Emu Pads

`decky/EmuPads/` lists every host pad (Sunshine names like `Sunshine (libvirtualhid) AYN_Thor`), lets you skip/reorder, and Apply for **Cemu**, **Azahar**, and **Eden**. Player 1 is the first selected pad; player 2 is the second when two are selected.

Install: `scripts/ensure-emu-pads-decky.sh`. `~/homebrew/plugins` is often root-owned — sudo is required to copy; then reload Decky plugins.

## Players

- **Cemu** player 1 = Wii U GamePad `controller0.xml`. Player 2 = Wii U Pro `controller1.xml` (standalone and RetroDECK trees). Extra `<controller>` nodes on the GamePad are extra devices, not extra players. Mappings only on the named pad; Steam wrap may stay listed empty.
- **Azahar** player 1 = `profiles\1\`. Player 2 = saved `profiles\2\` named Player 2. Azahar uses **one** active profile per instance.
- **Eden** player 1 = `player_0_` CRC-less USB GUID (`eden_guid`). Player 2 = `player_1_` + `player_1_connected`. Two Sunshine x360 pads share one Eden GUID; player 2 is SDL port 1 (best-effort). Steam virtual (`28de:11ff`) is a different GUID.

Pad type is `GAMESTREAM_PAD_PROFILE` in `.env` (`scripts/pad_profile.py`). Default **x360**. `ds5`/`ds4`/`switch` enable Thor/Odin gyro but change VID/PID; after a switch, run `ensure-sunshine-ds-apps.sh`, restart sunshine-ds, reconnect Moonlight, then re-bind. Do not switch the profile unless the user asks to experiment with gyro.

Standalone Cemu XML: `~/.var/app/info.cemu.Cemu/config/Cemu/controllerProfiles/controller0.xml`.
RetroDECK Cemu XML: `~/.var/app/net.retrodeck.retrodeck/config/Cemu/controllerProfiles/controller0.xml`.
Azahar INI: `~/.var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini`.
Eden INI: `~/.config/eden/qt-config.ini`. Maps for Azahar come from the active pad profile. x360 is a 15-button SDL joystick (not Steam xpad 11): A/B/X/Y = 0/1/3/4, L/R = 6/7, Select/Start/Home = 10/11/12, ZL/ZR = LT/RT. Do not use 4/5 for L/R on x360. Do not copy RetroDECK’s L=LT / ZL=LB swap.

Cemu `set_mapping` is last-write-wins: if Steam’s wrap is listed after Sunshine and both have `<mappings>`, every button is bound to the idle Steam pad. Reordering Sunshine first does **not** fix that. The script adds the named Sunshine pad and puts mappings **only** on it; Steam can stay listed with empty mappings. Drop stale `AYN20Thor`. Do not copy the same mappings onto every `<controller>`.

Steam overlay / qAM: `scripts/inhibit-emu-input-on-steam-ui.py` SIGSTOPs Cemu / Azahar / Eden while `STEAM_OVERLAY=1` or `FOCUSED_APP=769` (qAM / Exit, after the emulator has been up 8s). SIGCONT when Steam UI closes. Do **not** EVIOCGRAB the Sunshine pad — Steam and the emulator share that fd, so a grab also kills overlay navigation. Started from Tender `rom-launcher`, Game Mode dual-screen, Eden wrap. Never `pgrep -f` sunshine.

Game Mode RetroDECK Cemu **local** tiles (kms FREE) still auto-pick on launch via `scripts/ensure-cemu-input.sh` (physical Xbox → Switch Pro → Steam virtual → Sunshine) and stay `-f`. Game Mode **GameStream dual-screen** (`:48200`, `checkpoint-2026-09-10-gamemode-tender-ds`): Tender Play detects `:48200` BUSY + the virtual sidecar and `--attach`es (no `-f`). Manual: `CEMU_PAD_MATCH=Thor ./scripts/ensure-cemu-gamemode-dual-screen.sh` (or `--match Odin`). Capture/overlay/screensaver: `.cursor/skills/sunshine-ds-gamemode/SKILL.md`. That script calls `bind-gamepad.py` on RetroDECK `controller0.xml` and puts mappings **only** on `Sunshine (libvirtualhid) AYN_Thor`. A leftover Tender `-f` Cemu (started while kms was FREE) will keep the Steam wrap. Use this skill for **desktop / GameStream** binds, explicit Thor/Odin, two-player assigns, and the Decky plugin. Desktop dual-screen restore: `scripts/ensure-cemu-dual-screen.sh` / `scripts/ensure-azahar-dual-screen.sh` (bind with `CEMU_PAD_MATCH` / `AZAHAR_PAD_MATCH`, default Thor).

## Why Thor failed

Sunshine used to create every client pad as `Sunshine (libvirtualhid) X-Box 360 Controller` (`045e:028e`, same SDL GUID). Cemu player 0 uuid `0_<guid>` then attached to whichever pad enumerated first (often not Thor). Steam’s `Microsoft X-Box 360 pad N` wrap (`28de:11ff`) is a different device; on desktop GameStream it is often connected but silent (0 events). Copying `<mappings>` onto every controller then listing Steam last steals player 0.

sunshine-ds now names pads `Sunshine (libvirtualhid) <client>` (udev prefix kept). Moonlight sends a sanitized `Build.MODEL` as `devicename` on pair/launch (`AYN_Thor`, `Odin2_Portal`). `--match Thor` is then unique. If Moonlight is still the old APK, the host may show `AYN20Thor` — `--match Thor` still hits it; the script drops that stale uuid. Do not hardcode a generic `X-Box 360 Controller` GUID.

Keep SteamInput-P1-style GameController button IDs (SDL_GameController enums, not raw joystick indices).

Cemu’s dropdown can show **Xbox 360 EasySMX** for any Sunshine x360 pad (`045e:028e`) — that name is SDL’s community `gamecontrollerdb` entry, not a wrong device. The host pad is still `Sunshine (libvirtualhid) AYN_Thor` (Thor wins over Odin / `SM-A546E`). `bind-gamepad.py sdl-mapping` writes every x360 GUID variant (USB, USB+version, BT, live CRC) into `SDL_GAMECONTROLLERCONFIG_FILE` so the UI matches the client name. That map must be **15-button** libvirtualhid (`LB=b6`, `Back=b10`), not Steam xpad 11-button (`LB=b4`, `Back=b6`) — the 11-button file makes Thor bumpers fire Wii U Select/Start. With two Sunshine pads, `--match Sunshine` uses Thor then Odin; a leftover Samsung/Odin bind is not kept.

## After bind

Cemu reads uuid at start. If Cemu is running, restart standalone `info.cemu.Cemu` (keep sunshine-ds). Flatpak process `comm` is truncated to `Cemu_relwithdeb` — `pgrep -x Cemu_relwithdebinfo` misses it. Then re-place dual-screen with `scripts/ensure-cemu-dual-screen.sh`. Same restart rule for Azahar and Eden.

Type must stay **Wii U GamePad** for the GamePad View. Do not bind `libvirtualhid Mouse` (`1209:0003`) or ASRock LED (`26ce`).

## Do not

- Hand-edit `controller0.xml` / `qt-config.ini`
- Reorder Sunshine first while Steam still has mappings
- `pgrep -f` / `pkill -f` sunshine (use `pgrep -x sunshine-ds`)
- Inherit Steam’s `SDL_GAMECONTROLLER_IGNORE_DEVICES`
- Write Steam xpad 11-button `_X360_SDL_MAP` (`LB=b4` `Back=b6`) — libvirtualhid is 15-button
- Pair/unpair Moonlight just to rename a pad (launch `devicename` updates the label)
