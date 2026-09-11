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
python3 scripts/bind-gamepad.py apply --emu cemu --all-sources --mode shared --cemu-p1 pro
python3 scripts/bind-gamepad.py apply --emu all --pads js3,js4 --mode multi
python3 scripts/bind-gamepad.py apply --emu all --match Thor,Odin --mode multi
python3 scripts/bind-gamepad.py cemu --match Thor
python3 scripts/bind-gamepad.py azahar --all-sources --mode shared
python3 scripts/bind-gamepad.py eden --all-sources --mode shared
# or, if names are still generic:
python3 scripts/bind-gamepad.py cemu --wait
```

## Decky: Emu Pads

Always-on mux (`scripts/emupads-mux.py`, `emupads-mux.service`): virtual **EmuPads P1** / **P2**. Every host pad is a source (Sunshine Thor/Odin, phone, tablet, local Xbox, Steam virtual). Emulators bind the sinks once; Apply only changes routing. Independent of dual-screen — works with vanilla Decky Sunshine.

- **Shared P1** (default): last pad that sent a press/stick move is the only one copied to P1 (no analog mix). Azahar uses this too. Steam virtual `28de:11ff` is skipped when a Sunshine / physical pad is present (Steam’s curve stacked on SDL made Cemu sticks feel short/wonky). The plugin list hides those wraps and the EmuPads sinks so only real host pads show. Shared / Multiplayer persists to `mux.json` on click. Axes are rescaled to the sink ±32767 range. Event loop copies first; `xprop` / rescan run on idle or every 250ms.
- **Multiplayer**: first selected → P1, second → P2 (Cemu Wii U Pro, Azahar profile 2, Eden `player_1_` with product `e302` so GUIDs differ).
- Do not list sinks as sources. Do not bind emulators to Sunshine pads. If the mux is down, start it — no fallback.
- Overlay/QAM/Home/Library mutes sinks (`$XDG_RUNTIME_DIR/emupads-mute`); Steam still reads real pads. `checkpoint-2026-09-11-steam-menu-mute`.

Install: `scripts/ensure-emupads-mux.sh` then `scripts/ensure-emu-pads-decky.sh`. Source `decky/EmuPads/` (see that README). `~/homebrew/plugins` is often root-owned — sudo is required to copy; then reload Decky plugins.

After `systemctl --user restart emupads-mux.service` (never `sudo systemctl --user`), **restart Cemu/Azahar/Eden** — the sinks are new uinput nodes. Routing lives in `~/.config/emupads/mux.json`.

## Do not lose

- **Cemu died on Home / Library** because inhibit treated `FOCUSED_APP=769` as Exit after 8s (`Steam Exit — FOCUSED_APP=769, quitting`). Cemu `log.txt` stopping mid-`FSGetVolumeState` is that SIGTERM, not a Cemu crash. Mute only. `checkpoint-2026-09-11-steam-menu-mute`.
- **Tender “RomM disconnected”** on 3DS = missing `rom_installs` (Download path) even when dumps are in `~/retrodeck/roms/n3ds`. Dest is **`n3ds`**, not `roms/3ds`. Dumps were **moved** from `~/emulation/3ds/games`. `--repair-tender`, then reopen Tender. Older Steam Exe `~/homebrew/plugins/decky-romm-sync/bin/rom-launcher` is gone after Tender replaced that plugin — sudo restore from `ensure-eden-component.sh` `record_manual`.
- **Azahar has no GamePad/Pro type.** The plugin toggle is Cemu-only; the next Cemu tile overwrites it.
- `~/.cursor/skills/*` on this box are **copies**, not symlinks of playbook `.cursor/skills/`. Edit the playbook copy.

## Players

- **Cemu** player 1 = **EmuPads P1** in `controller0.xml`. Tender **tiles** pick the type at launch: **Wii U GamePad** when the second screen is streamed (`CEMU_GAMEMODE_DS=1` / `:48200` BUSY + sidecar), **Wii U Pro Controller** for a local HDMI-only tile. Dual-screen scripts also force GamePad. The Emu Pads toggle / `--cemu-p1` still apply by hand; the next tile launch overwrites. Player 2 = Wii U Pro `controller1.xml` → **EmuPads P2** in multi. Extra `<controller>` nodes are extra devices, not extra players.
- **Azahar** player 1 = `profiles\1\` → P1. Player 2 = saved `profiles\2\` in multi (one active profile per instance). Shared P1 is the default even though Azahar barely does MP.
- **Eden** player 1 = `player_0_` CRC-less USB GUID of P1 (`1209:e301`). Player 2 = P2 (`1209:e302`) so GUIDs differ. Steam virtual (`28de:11ff`) stays a source, not a bind target.

Pad type is `GAMESTREAM_PAD_PROFILE` in `.env` (`scripts/pad_profile.py`). Default **x360**. `ds5`/`ds4`/`switch` enable Thor/Odin gyro but change VID/PID; after a switch, run `ensure-sunshine-ds-apps.sh`, restart sunshine-ds, reconnect Moonlight, then re-bind. Do not switch the profile unless the user asks to experiment with gyro.

Standalone Cemu XML: `~/.var/app/info.cemu.Cemu/config/Cemu/controllerProfiles/controller0.xml`.
RetroDECK Cemu XML: `~/.var/app/net.retrodeck.retrodeck/config/Cemu/controllerProfiles/controller0.xml`.
Standalone Azahar INI: `~/.var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini`.
RetroDECK Azahar INI: `~/.var/app/net.retrodeck.retrodeck/config/azahar-emu/qt-config.ini`.
Eden INI: `~/.config/eden/qt-config.ini`. Every Eden/Azahar launch rebinds those files to EmuPads P1 (same mux as Cemu). Maps for Azahar come from the active pad profile. x360 is a 15-button SDL joystick (not Steam xpad 11): A/B/X/Y = 0/1/3/4, L/R = 6/7, Select/Start/Home = 10/11/12, ZL/ZR = LT/RT. Do not use 4/5 for L/R on x360. Do not copy RetroDECK’s L=LT / ZL=LB swap.

Cemu `set_mapping` is last-write-wins: if Steam’s wrap is listed after Sunshine and both have `<mappings>`, every button is bound to the idle Steam pad. Reordering Sunshine first does **not** fix that. The script adds the named Sunshine pad and puts mappings **only** on it; Steam can stay listed with empty mappings. Drop stale `AYN20Thor`. Do not copy the same mappings onto every `<controller>`.

Steam overlay / QAM / Home / Library: `scripts/inhibit-emu-input-on-steam-ui.py` **mutes EmuPads sinks** (`$XDG_RUNTIME_DIR/emupads-mute`) while `STEAM_OVERLAY=1`, `GAMESCOPE_BLUR_MODE!=0` on `:0`, or `FOCUSED_APP=769` (Home / Library / other BPM menus). Do **not** SIGSTOP the emulator (that holds Steam's SIGTERM). Steam Exit is **SIGTERM pending** only — `--quit` on the first tick. Do not treat 769 as Exit (that quit Cemu when opening Home). When the emulator is gone, restore `FOCUSED_APP=769` on `:0`/`:1` (`scripts/restore-steam-gamescope-focus.sh`) or Steam stays on Exiting from a leftover `:1` shortcut (Wind Waker after 3DS). Do **not** EVIOCGRAB the Sunshine pad — Steam needs it for overlay navigation. Started from Tender `rom-launcher`, Game Mode dual-screen, Eden wrap. Never `pgrep -f` sunshine.

Game Mode RetroDECK Cemu **local** tiles (kms FREE) bind **EmuPads P1** via `scripts/ensure-cemu-input.sh` / `patch-cemu-input.py` and stay `-f`. Game Mode **GameStream dual-screen** (`:48200`, `checkpoint-2026-09-11-gamemode-tender-ds`): Tender Play detects `:48200` BUSY + the virtual sidecar and `--attach`es (no `-f`). Manual: `CEMU_PAD_MATCH=Thor ./scripts/ensure-cemu-gamemode-dual-screen.sh` (or `--match Odin`). Capture/overlay/screensaver: `.cursor/skills/sunshine-ds-gamemode/SKILL.md`. That script binds Cemu to the mux sinks (not `--match Thor` into XML). Use this skill for **desktop / GameStream** binds, shared vs multi routing, and the Decky plugin. Desktop dual-screen restore: `scripts/ensure-cemu-dual-screen.sh` / `scripts/ensure-azahar-dual-screen.sh`.

## Why Thor failed

Sunshine used to create every client pad as `Sunshine (libvirtualhid) X-Box 360 Controller` (`045e:028e`, same SDL GUID). Cemu player 0 uuid `0_<guid>` then attached to whichever pad enumerated first (often not Thor). Steam’s `Microsoft X-Box 360 pad N` wrap (`28de:11ff`) is a different device; on desktop GameStream it is often connected but silent (0 events). Copying `<mappings>` onto every controller then listing Steam last steals player 0.

sunshine-ds now names pads `Sunshine (libvirtualhid) <client>` (udev prefix kept). Moonlight sends a sanitized `Build.MODEL` as `devicename` on pair/launch (`AYN_Thor`, `Odin2_Portal`). `--match Thor` is then unique. If Moonlight is still the old APK, the host may show `AYN20Thor` — `--match Thor` still hits it; the script drops that stale uuid. Do not hardcode a generic `X-Box 360 Controller` GUID.

Keep SteamInput-P1-style GameController button IDs (SDL_GameController enums, not raw joystick indices).

Cemu’s dropdown can show **Xbox 360 EasySMX** for any Sunshine x360 pad (`045e:028e`) — that name is SDL’s community `gamecontrollerdb` entry, not a wrong device. The host pad is still `Sunshine (libvirtualhid) AYN_Thor` (Thor wins over Odin / `SM-A546E`). `bind-gamepad.py sdl-mapping` writes every x360 GUID variant (USB, USB+version, BT, live CRC) into `SDL_GAMECONTROLLERCONFIG_FILE` so the UI matches the client name. That map must be **15-button** libvirtualhid (`LB=b6`, `Back=b10`), not Steam xpad 11-button (`LB=b4`, `Back=b6`) — the 11-button file makes Thor bumpers fire Wii U Select/Start. With two Sunshine pads, `--match Sunshine` uses Thor then Odin; a leftover Samsung/Odin bind is not kept.

## After bind

Cemu reads uuid at start. If Cemu is running, restart standalone `info.cemu.Cemu` (keep sunshine-ds). Flatpak process `comm` is truncated to `Cemu_relwithdeb` — `pgrep -x Cemu_relwithdebinfo` misses it. Then re-place dual-screen with `scripts/ensure-cemu-dual-screen.sh`. Same restart rule for Azahar and Eden.

Dual-screen GamePad View needs **Wii U GamePad** on P1. The Cemu tile wrapper (`component_launcher.sh`) binds GamePad when the second screen is streamed and Pro when it is not. `ensure-cemu-*-dual-screen.sh` also passes `--cemu-p1 gamepad`. Do not bind `libvirtualhid Mouse` (`1209:0003`) or ASRock LED (`26ce`).

## Do not

- Hand-edit `controller0.xml` / `qt-config.ini`
- Reorder Sunshine first while Steam still has mappings
- `pgrep -f` / `pkill -f` sunshine (use `pgrep -x sunshine-ds`)
- Inherit Steam’s `SDL_GAMECONTROLLER_IGNORE_DEVICES`
- Write Steam xpad 11-button `_X360_SDL_MAP` (`LB=b4` `Back=b6`) — libvirtualhid is 15-button
- Pair/unpair Moonlight just to rename a pad (launch `devicename` updates the label)
- Bind Cemu/Azahar/Eden to Sunshine / physical Xbox / Steam virtual when the mux is up
- Treat `FOCUSED_APP=769` as Steam Exit
- `sudo systemctl --user restart emupads-mux.service`
