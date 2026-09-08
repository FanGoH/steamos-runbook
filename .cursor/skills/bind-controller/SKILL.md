---
name: bind-controller
description: Bind Cemu player 0 to a host gamepad (Thor, Odin, Sunshine x360, Steam virtual). Use when the user says the controller is not working, asks to change Cemu controllers, switch pads, or bind Thor/Odin/Moonlight input.
---

# Bind controller

Do **not** hand-edit `controller0.xml`. Run the script.

```bash
python3 scripts/bind-gamepad.py list
python3 scripts/bind-gamepad.py cemu --match Thor
# or, if names are still generic:
python3 scripts/bind-gamepad.py cemu --wait
```

Standalone Cemu XML: `~/.var/app/info.cemu.Cemu/config/Cemu/controllerProfiles/controller0.xml`.

Player 0 is the **Wii U GamePad**. Extra `<controller>` nodes are extra devices on that GamePad, not extra players. Cemu `set_mapping` is last-write-wins: if Steam’s wrap is listed after Sunshine and both have `<mappings>`, every button is bound to the idle Steam pad. The script adds the named Sunshine Xbox pad (`045e:028e`) and moves mappings onto it; Steam can stay listed with empty mappings.

Game Mode RetroDECK Cemu still auto-picks on launch via `scripts/ensure-cemu-input.sh` (physical Xbox → Switch Pro → Steam virtual → Sunshine). Use this skill for **desktop / GameStream** binds and any explicit “use the Thor/Odin pad” request.

## Why Thor failed

Sunshine used to create every client pad as `Sunshine (libvirtualhid) X-Box 360 Controller` (`045e:028e`, same SDL GUID). Cemu player 0 uuid `0_<guid>` then attached to whichever pad enumerated first (often not Thor). Steam’s `Microsoft X-Box 360 pad N` wrap (`28de:11ff`) is a different device; on desktop GameStream it is often connected but silent (0 events). Copying the same `<mappings>` onto every controller then listing Steam last steals player 0.

sunshine-ds now names pads `Sunshine (libvirtualhid) <client>` (udev prefix kept). Moonlight sends a sanitized `Build.MODEL` as `devicename` on pair/launch (`AYN_Thor`, `Odin2_Portal`). `--match Thor` is then unique. If Moonlight is still the old APK, the host may show `AYN20Thor` — `--match Thor` still hits it; the script drops that stale uuid.

## After bind

Cemu reads uuid at start. If `cemu` is running, restart standalone `info.cemu.Cemu` (keep sunshine-ds). Then re-place dual-screen with `scripts/ensure-cemu-dual-screen.sh` when that script exists.

Type must stay **Wii U GamePad** for the GamePad View. Do not bind `libvirtualhid Mouse` (`1209:0003`) or ASRock LED (`26ce`).

## Do not

- `pgrep -f` / `pkill -f` sunshine (use `pgrep -x sunshine-ds`)
- Inherit Steam’s `SDL_GAMECONTROLLER_IGNORE_DEVICES`
- Pair/unpair Moonlight just to rename a pad (launch `devicename` updates the label)
