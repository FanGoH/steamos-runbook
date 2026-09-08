---
name: sunshine-ds-gamestream
description: Diagnose SteamOS GameStream on sunshine-ds vs Decky Sunshine (black screen, Moonlight 503, Starting Desktop hang, Starting connection spinner, reconnect after drop, Thor/Odin Moonlight DS, KWin screencast, Cemu GamePad dual-screen). Use when the user mentions Sunshine, sunshine-ds, GameStream, Moonlight, 503, black capture, Starting Desktop, Starting connection, encoder probe, KWin PipeWire, dual-stream HDMI/virtual, stacked dual-display, Odin Portal, or Cemu GamePad on the bottom screen.
---

# sunshine-ds GameStream debug

Read this **before** tracing capture or `/launch` from scratch. Host uniqueids and LAN IPs live in gitignored `.env` / `rules_of_the_land.md` (this box: `~/.cursor/skills/sunshine-ds-gamestream/host.md`).

## Start here (do not rediscover)

1. Confirm which HTTP the client hits. Decky Flatpak and dev sunshine-ds are different processes.

```bash
curl -s --max-time 3 http://127.0.0.1:48100/serverinfo | grep -E 'uniqueid|currentgame|state'
curl -s --max-time 3 http://127.0.0.1:47989/serverinfo | grep -E 'uniqueid|currentgame|state'
```

Thor and Odin must use the **dev** uniqueid / `:48100`. `:47989` is Decky KMS and is black on Plasma desktop.

2. Confirm the **running** pid is the installed binary (`pgrep -x sunshine-ds` only — never `pgrep -f` / `pkill -f`):

```bash
ps -o pid,lstart,cmd -p "$(pgrep -x sunshine-ds)"
ls -l /home/deck/.local/bin/sunshine-ds
```

If `lstart` is older than the binary mtime, the process does not have the latest fixes.

3. Match the log to the table below. Apply that fix. Do not start a new capture theory.

## Known-good checkpoint

This is the working GameStream baseline. Do not “improve” it unless the user asks.

- Conf `~/.config/sunshine-ds-dev/sunshine/sunshine.conf`: `capture = kwin`, `encoder = software`, `hevc_mode = 1`, `av1_mode = 1`, `port = 48100`, `output_name = HDMI-A-1`. `back_button_timeout = 500` (hold Back/Select 0.5s → Guide). `gamepad = x360` so that Guide is a uinput Xbox 360 `045e:028e` (Steam Big Picture). DS `auto` is Xbox Series UHID `045e:0b13`; Decky Linux `auto` is Xbox One uinput `045e:02ea`. Do not leave DS on `xseries`. `dual_display_source = Virtual-sunshine-ds` when the helper is holding that output; otherwise HDMI twice.
- Virtual GamePad panel: `/home/deck/.local/bin/sunshine-ds-virtual-output --name sunshine-ds --width 1080 --height 1240` must stay running. KWin 6.7 `stream_virtual_output` fails with `Could not find output`; the helper holds the stream anyway and `kscreen-doctor` enables `Virtual-sunshine-ds`. Killing the helper removes the output. Checkpoint rollback: `dual_display_source = HDMI-A-1` and stop the helper.
- Dual-stream checkpoint (Thor): HDMI-A-1 1920×1080 primary + Virtual-sunshine-ds 1080×1240 second stream. Log: `Second display: capturing Virtual-sunshine-ds` and `Screencasting output name Virtual-sunshine-ds`. Mouse can move between streams. sunshine-ds binary is still the reconnect checkpoint (`ad60bc52` + skip-reprobe / async PW teardown / no cap drop). Do not rebuild it to “fix” dual-stream.
- Thor mouse checkpoint: top-panel touches must stay on HDMI. `getLocationOnScreen()` is per-display (both origin 0,0); the landscape 1920-wide top activity used to hit-test the 1080-wide bottom Presentation and send display index 1. Dual-panel routes by the view’s display; stacked mode still hit-tests. Moonlight branch `cursor/top-touch-hit-test-f15e`.
- Thor dual-panel restore: Back can dismiss the bottom Presentation while the top stream stays up. Tapping Moonlight DS on the bottom panel should re-show that Presentation and keep Game on the top display, not move the primary stream. Moonlight branch `cursor/restore-bottom-presentation-f15e`.
- Thor Cemu dual-screen (user: “THIS IS AMAZING, Exactly what I wanted”): standalone Flatpak `info.cemu.Cemu`, **not** RetroDECK. TV on HDMI-A-1, GamePad View on Virtual-sunshine-ds. Emulated type **must** be `Wii U GamePad`. Pro Controller is wrong. Restart Cemu after changing type. Recipe in **Cemu dual-screen (Thor)** below.
- Odin stacked checkpoint (user: “fixed!”): Portal only exposes Android `Display id=0`, so Auto is **STACKED** (TV + GamePad on that one screen), not Thor dual-panel. STACKED streams both GameStream videos. Dual-panel and stacked are alternate layouts, not a mix; Portal cannot target the other LCD until Android advertises a Presentation display. Moonlight `f4eca72d` (`cursor/stacked-secondary-surface-f15e`, tag `checkpoint-odin-stacked-dual-stream`) binds the in-layout `surfaceViewSecondary`. Settings: Dual display **Auto** or **Stack both**. Quit Thor first (`ControllerNumber already allocated [0]` / `/resume` of Thor’s `881448767`). GamePad only is the single-stream option. Do not rebuild sunshine-ds to “fix” the spinner.
- Start env: Distrobox `steamos-tools`, `CONFIGURATION_DIRECTORY=/home/deck/.config/sunshine-ds-dev`, `KWIN_WAYLAND_NO_PERMISSION_CHECKS=1`, `WAYLAND_DISPLAY=wayland-0`, `unset DISPLAY`.
- After `/launch` the log must contain `Skipping encoder re-probe; using [software]` (not a vulkan/vaapi walk).
- Capture health: `cpu frame type=2` + high `pixel_diffs`. Probe I-frame ~1KB / 0% coded is `dummy_img()`, ignore it.
- Reconnect must keep the same pid. If log shows `drop_elevated_privileges` then `zkde_screencast_unstable_v1 not found`, that pid is dead for capture — restart DS.
- Do **not** replace Decky Sunshine. Do **not** `POST /api/restart`. Do **not** `sudo systemctl --user`. Do **not** `kwin_wayland --replace`.

Code that must stay in the running binary: skip software `ALWAYS_REPROBE` on `/launch`; flush KWin Close before PipeWire stop; async `pw_stream_destroy`; never `drop_elevated_privileges` after KWin was bound this process.

## Symptom → cause → fix

### Moonlight 503 on reconnect

`/launch` failed: no display/encoder. Log:

- `KWin screencasting unavailable after init` then `drop_elevated_privileges`
- then `zkde_screencast_unstable_v1 not found in registry`
- then `Fatal: Unable to find display or encoder`

Privilege drop is **process-wide**. `/serverinfo` can still be `FREE`. Restart sunshine-ds (new pid).

### “Starting Desktop” for ~75s

Encoder probe opened a KWin screencast; destructor did not Close before PipeWire stop; KWin held the node ~75s. DS HTTP was down, so clients fell through to Decky.

If it returns, the running pid is older than the skip-reprobe / async-teardown install.

### Black Moonlight / ~1KB I-frames

| Check | Meaning |
|---|---|
| Spectacle screenshot all black | KWin FBO wedged. `qdbus org.kde.KWin /Compositor org.kde.kwin.Compositing.reinitialize`. Playbook: `scripts/ensure-kwin-screencast.sh`. |
| Probe I-frame ~1200 bytes / 0% coded | `dummy_img()`, not live capture |
| `cpu frame type=2` + high `pixel_diffs` | SHM/MemFd is capturing |
| DMA-BUF DCC modifier + mmap EPERM | Do not offer DMA-BUF for software encode |

### Thor shows the TV on both panels while Odin GamePad is correct

Odin GamePad-only (`x-ml-video[0].source=secondary`, no `video/1`) used to SIGTERM `sunshine-ds-virtual-output` to resize 1080×1240 → 1920×1080. Thor’s second PipeWire stream died; kwingrab then **fell back to HDMI-A-1**, so both Thor panels encoded the TV. Log:

- `Primary stream will capture the GamePad display` then `Screencasting output name HDMI-A-1` with `Streaming display 'Virtual-sunshine-ds' offset: 0x0`
- Healthy Thor second stream is `Screencasting output name Virtual-sunshine-ds` at `1920x0`

Do not kill the helper to change mode while another session is live. Scale to the client instead. kwingrab must not fall back to the first output when a named GamePad display was requested.

### Odin stuck on “Starting connection”

Moonlight `Game` spinner stays until `connectionStarted` / `stageFailed`. AUTO on a one-display device is STACKED, which waits for `secondarySurfaceReady`. Before `f4eca72d` only the dual-panel Presentation bound that surface, so `conn.start()` never ran. After that commit, LimeLog should show `Secondary stream surface ready` then RTSP. If the spinner still never moves, Thor still owns the session — quit Thor; do not rebuild DS.

### Ghost BUSY / wrong app

Desktop placebo app stays BUSY until `POST /api/apps/close`. HTTPS `/cancel` needs client cert. Use Decky `lastAuthHeader`; CSRF skipped if no Origin/Referer. Playbook helper: `sunshine_close_app_via_api`. Do not tap a Low Res Desktop app unless asked.

## Restart sunshine-ds

```bash
pgrep -x sunshine-ds   # never pgrep -f / pkill -f
kill <pid>
podman exec --user 1000 -d steamos-tools bash -lc 'export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus PIPEWIRE_RUNTIME_DIR=/run/user/1000 CONFIGURATION_DIRECTORY=/home/deck/.config/sunshine-ds-dev HOME=/home/deck KWIN_WAYLAND_NO_PERMISSION_CHECKS=1; unset DISPLAY; exec /home/deck/.local/bin/sunshine-ds /home/deck/.config/sunshine-ds-dev/sunshine/sunshine.conf >> /home/deck/steamos-playbook/logs/sunshine-ds.log 2>&1'
```

Wait until `:48100` `/serverinfo` is `SUNSHINE_SERVER_FREE` with the **dev** uniqueid.

```bash
podman exec --user 1000 steamos-tools ninja -C /home/deck/code/sunshine-ds/build -j2 sunshine
install -m 0755 /home/deck/code/sunshine-ds/build/sunshine /home/deck/.local/bin/sunshine-ds
```

Over SSH: `export XDG_RUNTIME_DIR=/run/user/$(id -u)`.

## Client / protocol

- Moonlight DS package and Thor/Odin ADB: `rules_of_the_land.md` / `host.md`. Do not `adb kill-server`. Portal stacked APK: `com.fangoh.moonlight.debug` at `f4eca72d` / `checkpoint-odin-stacked-dual-stream`.
- `/serverinfo` must advertise `<MaxVideoStreams>2</MaxVideoStreams>`.
- SETUP `streamid=video/1/0` before ANNOUNCE.
- Distrobox Pulse often `Access denied` — video can work without DS audio.

## Capture smoke pages

`/tmp/sunshine-ds-smoke` on `http://127.0.0.1:18080` (repo: `tools/sunshine-ds-smoke/`).

- `primary.html` — HDMI, red, bouncing box + Gamepad API HUD
- `gamepad.html` — second stream, blue; left stick moves the box
- Live HUDs (close these before Cemu): `python3 /tmp/sunshine-ds-smoke/primary_hud.py` and `gamepad_hud.py`
- Chrome Gamepad API is empty until a button press

## Cemu dual-screen (Thor)

Proven 2026-09-08 with Wind Waker HD. Do not “simplify” to RetroDECK fullscreen or to Wii U Pro Controller.

Layout (`kscreen-doctor`): HDMI-A-1 **1920×1080** at `0,0` (TV / top Moonlight panel) + Virtual-sunshine-ds **1080×1240** at `1920,0` (GamePad / bottom). Helper must stay running.

Use standalone Flatpak **`info.cemu.Cemu`**. RetroDECK `component_launcher.sh` forces `-f` / `<fullscreen>true</fullscreen>` and cannot keep a second GamePad window on the virtual output.

### Settings

`~/.var/app/info.cemu.Cemu/config/Cemu/settings.xml`:

- `fullscreen` false, `open_pad` true
- `window_position` 0,0 and `window_size` 1920×1080
- `pad_position` 1920,0 and `pad_size` 1080×1240

Wayland still ignores those coordinates sometimes. After launch, KWin-place:

- caption contains `GamePad View` → output `Virtual-sunshine-ds`, geometry `1920,0 1080x1240`, `noBorder`, `keepAbove`
- `resourceClass` `info.cemu.Cemu` (TV / `Cemu 2.6` / Wind Waker) → `HDMI-A-1`, `0,0 1920x1080`
- Minimize Steam Big Picture first or it covers HDMI

### Controller

`~/.var/app/info.cemu.Cemu/config/Cemu/controllerProfiles/controller0.xml`:

- `<type>Wii U GamePad</type>` — required for GamePad screen / game input. Pro Controller is the failure mode.
- Copy mappings from RetroDECK `SteamInput-P1.xml` (includes mapping 25).
- Player 0 uuid `0_030079f6de280000ff11000001000000` (`Microsoft X-Box 360 pad 0`, Steam Input wrap `28de:11ff`). Cemu SDL CRC is of the **device name**.
- Fallback uuid `0_050017945e0400008e02000014010000` (`Sunshine (libvirtualhid) X-Box 360 Controller`, bus `0005`, `045e:028e`, version `0114`). Only present while Moonlight is streaming.
- `patch-cemu-input.py` pick order is physical Xbox → Switch Pro → Steam virtual → Sunshine. On a Thor stream there is no physical Xbox, so Steam virtual wins. Do not bind `libvirtualhid Mouse` (`1209:0003`).
- Changing type in the XML while Cemu is running does nothing. Stop Cemu, write the file, start again.

sunshine-ds must stay `gamepad = x360` (`back_button_timeout = 500`). `auto` is Xbox Series UHID `045e:0b13`; Steam Big Picture Guide needs uinput 360 `045e:028e`. DS `xone` is still UHID `0B20`, not Decky’s InputTino `045e:02ea`.

### Launch

Close the smoke HUDs. Moonlight already on `:48100`. Then:

```bash
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus DISPLAY=:0
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0 SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT='0x28de/0x11ff,0x045e/0x02ea,0x045e/0x028e,0x045e/0x02fd,0x057e/0x2009'
# Wind Waker HD lives at ~/emulation/wiiu/windwakerhd/*.wux (also ~/retrodeck/roms/wiiu/)
flatpak run info.cemu.Cemu -g "<wux>"
```

Do not inherit Steam’s `SDL_GAMECONTROLLER_IGNORE_DEVICES`. Do not change Moonlight controller mapping.

### Steam Guide / Big Picture (related)

`back_button_timeout = 500` alone is not enough. Hold Select 0.5s pulses Guide on the **virtual pad**. Steam only honors that on uinput x360. Silent autostart (`steam -silent -steamdeck`) swallows `steam://open/*` with no window; start `/usr/bin/steam` without `-silent` if you need a visible client.

## Do not

- Treat probe I-frame size as capture health
- Enable Flatpak Sunshine systemd user unit
- Poll `/api/restart` or restart Decky to “fix” DS
- Hardcode Headscale URLs or print `.auth` / certs / passwords
- Install Bazzite Eden reorder hooks
- Use RetroDECK Cemu (`-f` / fullscreen) for Thor dual-screen GamePad
- Emulate Wii U Pro Controller when the bottom stream should be the GamePad
- Leave sunshine-ds on `gamepad = auto` / `xseries` if Select-hold must open Steam Big Picture
- Kill `sunshine-ds-virtual-output` while dual-stream is the checkpoint
- Rebuild sunshine-ds to “fix” Odin “Starting connection” (that was Moonlight STACKED never binding the in-layout second surface)
- Expect Thor dual-panel on the Portal, or stacked plus a separate Android display at once
