---
name: sunshine-ds-gamestream
description: Diagnose SteamOS GameStream on sunshine-ds vs Decky Sunshine (black screen, Moonlight 503, Starting Desktop hang, Starting connection spinner, reconnect after drop, Thor/Odin Moonlight DS, KWin screencast, Cemu GamePad dual-screen). Use when the user mentions Sunshine, sunshine-ds, GameStream, Moonlight, 503, black capture, Starting Desktop, Starting connection, encoder probe, KWin PipeWire, dual-stream HDMI/virtual, stacked dual-display, Odin Portal, or Cemu GamePad on the bottom screen.
---

# sunshine-ds GameStream debug

Read this **before** tracing capture or `/launch` from scratch. Host uniqueids and LAN IPs live in gitignored `.env` / `rules_of_the_land.md` (this box: `~/.cursor/skills/sunshine-ds-gamestream/host.md`). Checkpoint SHAs and the DS/Moonlight/playbook stack: [reference.md](reference.md).

## Start here (do not rediscover)

1. Confirm which HTTP the client hits. Decky Flatpak and dev sunshine-ds are different processes.

```bash
curl -s --max-time 3 http://127.0.0.1:48100/serverinfo | grep -E 'uniqueid|currentgame|state'
curl -s --max-time 3 http://127.0.0.1:48200/serverinfo | grep -E 'uniqueid|currentgame|state'
curl -s --max-time 3 http://127.0.0.1:47989/serverinfo | grep -E 'uniqueid|currentgame|state'
```

Plasma Thor/Odin daily dual-screen uses the **dev** uniqueid / `:48100`. Game Mode Cemu dual-screen uses `sunshine-ds-kms` / `:48200` (uniqueid `1075C8EF…`). `:47989` is Decky KMS — black on Plasma **and** black (or mouse-only) in Game Mode. Do not debug Game Mode Cemu against Decky.

2. Confirm the **running** pid is the installed binary (`pgrep -x sunshine-ds` only — never `pgrep -f` / `pkill -f`):

```bash
ps -o pid,lstart,cmd -p "$(pgrep -x sunshine-ds)"
ls -l /home/deck/.local/bin/sunshine-ds
```

If `lstart` is older than the binary mtime, the process does not have the latest fixes.

3. Match the log to the table below. Apply that fix. Do not start a new capture theory.

## Known-good checkpoint

This is the working GameStream baseline. Do not “improve” it unless the user asks.

- Conf `~/.config/sunshine-ds-dev/sunshine/sunshine.conf`: `capture = kwin`, `encoder = software`, `hevc_mode = 1`, `av1_mode = 1`, `port = 48100`, `output_name = HDMI-A-1`. `back_button_timeout = 500` (hold Back/Select 0.5s → Guide). `gamepad = x360` so that Guide is a uinput Xbox 360 `045e:028e` (Steam Big Picture). DS `auto` is Xbox Series UHID `045e:0b13`; Decky Linux `auto` is Xbox One uinput `045e:02ea`. Do not leave DS on `xseries`. `dual_display_source = Virtual-sunshine-ds`.
- **One virtual display only.** HDMI-A-1 is the physical TV (Decky Sunshine uses that too). Linux DS serves at most one `Virtual-sunshine-ds` for Azahar/Cemu/other dual-screen mods. Playbook helper: `/home/deck/.local/bin/sunshine-ds-virtual-output --name sunshine-ds --width 1920 --height 1080 --scale 1`. It must stay running across connect/disconnect (one client, the other, or both). DS must not spawn a second `--name sunshine-ds` and must not SIGTERM the helper when a stream ends. Do not use `kscreen-doctor` to decide if the output exists (hangs with duplicates). Live layout is usually HDMI 1920×1080 at `0,0` plus Virtual-sunshine-ds 1920×1080 at `1920,0`.
- Dual-stream checkpoint: HDMI primary + that one virtual second stream. Log: `Second display: reusing Virtual-sunshine-ds` (or `capturing existing`) and `Screencasting output name Virtual-sunshine-ds`. A second client must join the **shared** second-display capture, not open another KWin screencast of the same output.
- Thor/Odin connect+disconnect: `/resume` of desktop `881448767` is how the second device joins. Each client keeps its own pad; disconnecting one must not destroy the other's pad and must not tear down HDMI or the virtual output. `ControllerNumber already allocated [0]` on the **same** client is a duplicate arrival (keep the pad). If it appears for the **other** client at join, they are sharing a session id — quit the first client and reconnect both to `:48100`.
- Thor mouse checkpoint: top-panel touches must stay on HDMI. `getLocationOnScreen()` is per-display (both origin 0,0); the landscape 1920-wide top activity used to hit-test the 1080-wide bottom Presentation and send display index 1. Dual-panel routes by the view’s display; stacked mode still hit-tests. Moonlight branch `cursor/top-touch-hit-test-f15e`.
- Thor dual-panel restore: Back can dismiss the bottom Presentation while the top stream stays up. Tapping Moonlight DS on the bottom panel should re-show that Presentation and keep Game on the top display, not move the primary stream. Moonlight branch `cursor/restore-bottom-presentation-f15e`.
- Thor Cemu dual-screen: standalone Flatpak `info.cemu.Cemu`, **not** RetroDECK. TV on HDMI-A-1, GamePad View on Virtual-sunshine-ds. Type **Wii U GamePad**. Bind with `scripts/bind-gamepad.py`; place with `scripts/ensure-cemu-dual-screen.sh`. Recipe in **Cemu dual-screen (Thor)** below.
- Thor Azahar dual-screen: standalone Flatpak `org.azahar_emu.Azahar`, Separate Windows, `QT_QPA_PLATFORM=xcb`. Primary Window → HDMI, Secondary Window → Virtual-sunshine-ds. Recipe in **Azahar dual-screen (Thor)** below.
- Odin stacked checkpoint (user: “fixed!”): Portal only exposes Android `Display id=0`, so Auto is **STACKED** (TV + GamePad on that one screen), not Thor dual-panel. STACKED streams both GameStream videos. Dual-panel and stacked are alternate layouts, not a mix; Portal cannot target the other LCD until Android advertises a Presentation display. Moonlight `f4eca72d` (`cursor/stacked-secondary-surface-f15e`, tag `checkpoint-odin-stacked-dual-stream`) binds the in-layout `surfaceViewSecondary`. Settings: Dual display **Auto** or **Stack both**. GamePad only is the single-stream option. Do not rebuild sunshine-ds to “fix” the spinner.
- Game Mode `:48200` Cemu dual-screen checkpoint (2026-09-09, user: working, tag `checkpoint-2026-09-09-gamemode-cemu-ds`, sunshine-ds `119d7452`): Thor **dual-panel** Wind Waker — HDMI picture + GamePad stream + Thor pad. Host `sunshine-ds-kms` (`cap_sys_admin=ep`), `capture = kms`, `dual_display_source = gamescope-virtual`. Recipe: `CEMU_PAD_MATCH=Thor ./scripts/ensure-cemu-gamemode-dual-screen.sh` (**no** `-f`). HDMI DCC is decoded (`[kmsgrab] DMA-BUF copied` + I-frame ~17–23KB). Earlier touch-only tag `checkpoint-2026-09-09-gamemode-cemu-touch-v2` (`be45fc0f`) is superseded for picture. Do not merge kms into play / `:48100`. Azahar Game Mode (`970550cd`) injects onto **Secondary Window** and restores **Primary Window**; overlay falls back to `STEAM_GAME=769` when BPM has no title.
- Start env: Distrobox `steamos-tools`, `CONFIGURATION_DIRECTORY=/home/deck/.config/sunshine-ds-dev`, `KWIN_WAYLAND_NO_PERMISSION_CHECKS=1`, `WAYLAND_DISPLAY=wayland-0`, `unset DISPLAY`.
- After `/launch` the log must contain `Skipping encoder re-probe; using [software]` (not a vulkan/vaapi walk).
- Capture health: `cpu frame type=2` + high `pixel_diffs`. Probe I-frame ~1KB / 0% coded is `dummy_img()`, ignore it.
- Reconnect must keep the same pid. If log shows `drop_elevated_privileges` then `zkde_screencast_unstable_v1 not found`, that pid is dead for capture — restart DS.
- Do **not** replace Decky Sunshine. Do **not** `POST /api/restart`. Do **not** `sudo systemctl --user`. Do **not** `kwin_wayland --replace`.

Code that must stay in the running binary: skip software `ALWAYS_REPROBE` on `/launch`; flush KWin Close before PipeWire stop; async `pw_stream_destroy`; never `drop_elevated_privileges` after KWin was bound this process; null-safe `net::host_create` / `free_host`; `net::set_cloexec` on RTSP/video/audio fds; virtual-output child `addclose_inet_sockets` (keep AF_UNIX); singleton `Virtual-sunshine-ds` (detect helper via `/proc`, never SIGTERM on disconnect, never spawn a second `--name sunshine-ds`); shared `capture_thread_sync2` for the GamePad stream; pin `capture_thread_async` so HDMI kmsgrab/EGL survives the last client; kwingrab first sized match on duplicate names. `POSIX_SPAWN_CLOEXEC_DEFAULT` is **not** defined on this glibc without `_GNU_SOURCE`.

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

### Game Mode `:48200` Starting Desktop (no new log)

Desktop placebo stayed `BUSY` and `rtsp_stream::session_count()` joined Pulse `pa_simple_read` on the nvhttp thread. Last client gone must `terminate_if_placebo()` so `/launch` is allowed. `rtsp::clear` joins in the background. Host gate: `scripts/test-gds-lifecycle.sh`. Close leftover BUSY with GDS `POST https://127.0.0.1:48201/api/apps/close` (`sunshine_gds_close_app`), not Decky `/api/restart`.

The same `pa_simple_read` hang leaves `session::audio` + `session::join` after disconnect. Moonlight then logs **Initial Ping Timeout** with no `CLIENT CONNECTED` — that is **failed to start stream / control establishment error**. Two layers:

1. Pulse `pa_mainloop_poll` can ignore its timeout on a silent Game Mode monitor, so join never finishes and `running_sessions` stays > 0.
2. Cemu/app exit logged `Process terminated` and **left `stream::controlBroadcast`**. The broadcast object stayed alive (join still held a ref), so the next `/launch` reused a host that nobody called `enet_host_service` on.

Do **not** `systemctl restart` the live pid to “clear” that — deploy non-blocking Pulse iterate (`pa_mainloop_iterate(..., 0)`) plus keep the control loop while `running_sessions > 0`, then SIGTERM timeout `_Exit(0)`. Live ELF must contain `sunshine-record`, must **not** still export `pa_simple_read() failed`, and after a disconnect+app-exit the next connect must log `CLIENT CONNECTED`. Host gate: leftover `session::join` fails `scripts/test-gds-lifecycle.sh`. Close leftover BUSY with GDS `POST https://127.0.0.1:48201/api/apps/close` (`sunshine_gds_close_app`), not Decky `/api/restart`.

### Black Moonlight / ~1KB I-frames

| Check | Meaning |
|---|---|
| Spectacle screenshot all black | KWin FBO wedged. **Last resort:** `qdbus org.kde.KWin /Compositor org.kde.kwin.Compositing.reinitialize`. That can restart `kwin_wayland`, kill the virtual-output helper, and crash Azahar. First: restart PipeWire (user bus, not `sudo systemctl --user`) then DS; respawn **one** helper if it died. Playbook: `scripts/ensure-kwin-screencast.sh`. |
| Probe I-frame ~1200 bytes / 0% coded | `dummy_img()`, not live capture |
| Game Mode `:48200` HDMI **black except the mouse**, I-frame ~700B / skip 100% | Stale ELF without `119d7452` (or `getcap` missing). AMD **DCC** HDMI FB (`modifier=0x200000000082305`) used to download as zeros via `GetTextureSubImage`; cursor plane is linear. Proven fix: kmsgrab shader sample + ReadPixels. Live health: `[kmsgrab] DMA-BUF copied 1920x1080 nonzero=<large>` and HDMI I-frame **~17–23KB**. Stage `sunshine-ds-kms.new` + `sudo setcap cap_sys_admin+ep` + `--start`. Stock Moonlight on Decky `:47989` is still black here. Host **`:48200`**. |
| Game Mode `:48200` HDMI **went black after reconnect**, GamePad still fine, log `GL: graphics.cpp:664: [00000501]` | Last client destroyed kmsgrab EGL; the next capture thread imported DCC with no current context. **Proven 2026-09-09 evening** (`checkpoint-2026-09-09-hdmi-reconnect`): pin HDMI capture + `eglMakeCurrent` every snapshot. Live pid must be newer than the ELF mtime. Healthy reconnect: `HDMI capture idle` then `HDMI capture resumed`, `[kmsgrab] DMA-BUF copied`, I-frame ~17–23KB. |
| Game Mode `:48200` **Cemu stays on Steam Launching / never Init** | gamescope left Cemu as a 10×10 InputOnly stub. It needs `FOCUSED_APP=<shortcut>` + `STEAM_GAME` on the window + `GAMESCOPE_FOCUS_DISPLAY` middle cardinal **1** *before* gtk_init. Holding 769 forever is the spinner. Tender `rom-launcher` starts `scripts/cemu-gamescope-focus.sh` on the host before RetroDECK. |
| Game Mode `:48200` **Cemu boot is black, no Steam Launching logo** | `GAMESCOPECTRL_BASELAYER_WINDOW` was the 10×10 InputOnly stub. Tag `STEAM_GAME` on the stub so it can convert, keep Steam BPM as the `:0` baselayer, and only switch HDMI to Cemu once the window is ≥64×64 InputOutput. Bottom idle clock stays until `ffplay` is mapped. |
| Game Mode `:48200` **bottom pitch black**, log `cpu frame type=2` full nonzero, video/1 I-frame ~1KB / 0% coded | Capture has pixels; encoder still has `dummy_img()` zeros. Headless gamescope often emits **one** MemFd then goes silent (static blue / Cemu). Fix is in sunshine-ds `pipewire.cpp`: seed dummy from last CPU frame and re-present it. Solid-color smoke has `pixel_diffs=0` but must not look black. Stage `sunshine-ds-kms.new` + `setcap` + `--start`. |
| Game Mode `:48200` **“second display ended”**, HDMI still live, log `[pipewire] stream stayed connecting for 3s; failing the second display` | Host aborted video/1. Game Mode `gamescope-virtual` stays `connecting` until the first buffer (DMA-BUF probe `nonzero=0`). Do **not** fail capture for that. Snapshot timeouts re-present. |
| Game Mode `:48200` systemd stop **SIGTRAP** / Moonlight **control establishment error** / reconnect **Initial Ping Timeout**, leftover `session::audio` + `session::join`, **no** `stream::controlBroadcast` | Pulse poll blocked; app exit killed the ENet thread while join still owned the broadcast. Record with non-blocking `pa_mainloop_iterate`; keep control loop while `running_sessions > 0`; SIGTERM timeout `_Exit(0)`. |
| `cpu frame type=2` + high `pixel_diffs` | SHM/MemFd is capturing (animated content) |
| DMA-BUF DCC modifier + mmap EPERM | Do not offer DMA-BUF for software encode |
| PipeWire `connecting` forever, no `cpu frame type=2` | Second client opened another screencast of `Virtual-sunshine-ds`. Restart PipeWire + DS; keep exactly one helper. Do not compositor-reinitialize first. |

### Thor shows the TV on both panels while Odin GamePad is correct

Odin GamePad-only (`x-ml-video[0].source=secondary`, no `video/1`) used to SIGTERM `sunshine-ds-virtual-output` to resize 1080×1240 → 1920×1080. Thor’s second PipeWire stream died; kwingrab then **fell back to HDMI-A-1**, so both Thor panels encoded the TV. Log:

- `Primary stream will capture the GamePad display` then `Screencasting output name HDMI-A-1` with `Streaming display 'Virtual-sunshine-ds' offset: 0x0`
- Healthy Thor second stream is `Screencasting output name Virtual-sunshine-ds` at `1920x0`

Do not kill the helper to change mode while another session is live. Scale to the client instead. kwingrab must not fall back to the first output when a named GamePad display was requested.

### Odin stuck on “Starting connection”

Moonlight `Game` spinner stays until `connectionStarted` / `stageFailed`. AUTO on a one-display device is STACKED, which waits for `secondarySurfaceReady`. Before `f4eca72d` only the dual-panel Presentation bound that surface, so `conn.start()` never ran. After that commit, LimeLog should show `Secondary stream surface ready` then RTSP. If the spinner still never moves, Thor still owns the session — quit Thor; do not rebuild DS.

### Ghost BUSY / wrong app

Desktop placebo app stays BUSY until `POST /api/apps/close`. HTTPS `/cancel` needs client cert. Use Decky `lastAuthHeader`; CSRF skipped if no Origin/Referer. Playbook helper: `sunshine_close_app_via_api`. Do not tap a Low Res Desktop app unless asked.

### sunshine-ds dies on disconnect; :48100 still listening

`rtsp::handler` used to SIGSEGV when `enet_host_create` returned null (`host->socket`). After death a leftover helper could keep `:48100`. Spawn CLOEXEC was a no-op on this glibc (`POSIX_SPAWN_CLOEXEC_DEFAULT` undefined without `_GNU_SOURCE`), so the helper inherited INET listen/UDP sockets.

If `pgrep -x sunshine-ds` is empty but `ss -ltnp | grep 48100` still shows a listener, kill that leftover helper by **numeric PID**. Never `pgrep -f` / `pkill -f` sunshine. Never put `sunshine-ds-virtual-output` in a `pgrep -f` pattern. Keep the long-lived helper that holds `Virtual-sunshine-ds` (`--name sunshine-ds --width 1920 --height 1080`).

### Odin stacked GamePad is black, touch still works

A second client joining a live Thor dual-stream used to spawn **another** `sunshine-ds-virtual-output --name sunshine-ds`. KWin then has several `Virtual-sunshine-ds` outputs. kwingrab used to bind the last one (empty → black video). Touch still hits Azahar on the original output. `kscreen-doctor -j` / `-o` hang, which made DS think the output was missing.

Do **not** kill the long-lived helper. Kill extra helper PIDs by number. DS must reuse the attached output via `/proc` (not `kscreen-doctor` / throwaway KWin enumerations), share one GamePad screencast, and scale. Exactly one Virtual-sunshine-ds.

`ControllerNumber already allocated [0] for <client>` means that client already has pad 0 (duplicate arrival or `/resume` of the same cert). The other device should get a new global slot. Azahar’s profile is one SDL GUID — bind `--match Odin` if that client should drive the game.

### Thor bumpers fire 3DS Start/Select

libvirtualhid xbox_360 is a 15-button SDL joystick (reserved C/Z/TL2/TR2). Steam xpad is 11 buttons. Azahar uses packed joystick indices, so L/R at 4/5 and Select/Start at 6/7 maps shoulders onto Start/Select. Use `scripts/bind-gamepad.py azahar` (L/R=6/7, Select/Start=10/11). Cemu uses GameController labels and is not affected.

## Restart sunshine-ds

```bash
scripts/ensure-sunshine-ds.sh            # start Distrobox + one helper + DS if down
scripts/ensure-sunshine-ds.sh --status
scripts/ensure-sunshine-ds.sh --stop     # Game Mode teardown: stop DS + virtual helper
scripts/ensure-sunshine-ds.sh --install-shortcut  # ~/Desktop/Return to Game Mode.desktop only
scripts/switch-to-game-mode.sh           # --stop, set login mode game, steamosctl switch-to-game-mode
scripts/ensure-sunshine-ds-gamemode.sh --install-service  # :48200 boot unit (gamescope-session)
scripts/ensure-sunshine-ds-gamemode.sh --start
scripts/ensure-sunshine-ds-gamemode.sh --status
# Live Game Mode with headless :2 already up — do not --start (KillMode can kill the helper):
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
systemctl --user restart steamos-sunshine-ds-gamemode.service
./scripts/test-gds-lifecycle.sh
# After a Distrobox rebuild, stage then cap (cp onto kms strips file caps):
./scripts/ensure-sunshine-ds-gamemode.sh --replace-bin
sudo setcap cap_sys_admin+ep ~/.local/bin/sunshine-ds-kms
./scripts/ensure-sunshine-ds-gamemode.sh --start-kms
```

Do not paste the Distrobox `podman exec` by hand. Never `pgrep -f` / `pkill -f`. Keep the long-lived virtual-output helper. Wait until `:48100` `/serverinfo` is `FREE` or `BUSY` with the **dev** uniqueid (not Decky). Confirm `:48100` is owned by `sunshine-ds`. Game Mode `:48200` is `sunshine-ds-kms` via `steamos-sunshine-ds-gamemode.service` (user `deck`, no sudo).

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

From Moonlight on `:48100`, tap **Cemu Dual-Screen** (`scripts/sunshine-app-cemu.sh`; box art is the Cemu Flatpak icon). It waits for the Sunshine pad, runs `ensure-cemu-dual-screen.sh` (Wii U GamePad bind + place), and stays BUSY until Cemu exits. Dual-screen has no chrome; overlay **Quit game** kills `Cemu_relwithdeb` / `Cemu-wrapper` the same way Azahar is stopped. Optional `.env` `CEMU_ROM`; otherwise the Cemu library opens. Do not add this app to Decky `:47989`.

Game Mode `:48200` is the **Cemu dual-screen checkpoint** (`checkpoint-2026-09-09-gamemode-cemu-ds`). Moonlight already on `sunshine-ds-kms` (not Decky). Last client gone must leave Desktop `FREE`; then tap **Desktop** or **Cemu Dual-Screen** (`scripts/sunshine-app-cemu-gamemode.sh`). Close any Tender/rom-launcher Cemu that still has `-f`, then:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
CEMU_PAD_MATCH=Sunshine ./scripts/ensure-cemu-gamemode-dual-screen.sh
```

That is SteamLaunch RetroDECK Cemu, `CEMU_GAMEMODE_DS=1`, **no** `-f`, mappings on the live Sunshine pad (Thor if present, else Odin), GamePad `ffplay` `x11grab` onto headless `:2`. Refocus Cemu: `./scripts/ensure-cemu-gamemode-dual-screen.sh --place-only` (GamePad under TV, ffplay on `:2`). Do not run `ensure-cemu-dual-screen.sh` in Game Mode.

Or run the playbook script from the host; do not hand-edit XML.

```bash
# optional: CEMU_ROM=... CEMU_PAD_MATCH=Thor
./scripts/ensure-cemu-dual-screen.sh
```

Recipe: `.cursor/skills/cemu-dual-screen/SKILL.md` and `.cursor/skills/bind-controller/SKILL.md`. Do not “simplify” to RetroDECK fullscreen or Wii U Pro Controller.

Layout: read **live** `kscreen-doctor`. Current Thor checkpoint is HDMI-A-1 **1920×1080** at `0,0` plus Virtual-sunshine-ds **1920×1080** at `1920,0`. Older notes said 1080×1240. Helper must stay running.

Use standalone Flatpak **`info.cemu.Cemu`**. Process `comm` is truncated to `Cemu_relwithdeb`. RetroDECK `component_launcher.sh` forces `-f` / `<fullscreen>true</fullscreen>` and cannot keep a second GamePad window on the virtual output.

### Settings

`~/.var/app/info.cemu.Cemu/config/Cemu/settings.xml`: `fullscreen` false, `open_pad` true. TV / pad geometry = live HDMI / virtual sizes. Wayland still ignores those coordinates sometimes; the script KWin-places:

- caption contains `GamePad View` → `Virtual-sunshine-ds`, live geometry, `noBorder`, `keepAbove`
- `resourceClass` `info.cemu.Cemu` → `HDMI-A-1`, live geometry
- Minimize Steam Big Picture first or it covers HDMI

### Controller

Do **not** hand-edit `controller0.xml`. `python3 scripts/bind-gamepad.py cemu --match Thor`.

- `<type>Wii U GamePad</type>` — required for GamePad screen / game input. Pro Controller is the failure mode.
- Cemu `set_mapping` is last-write-wins. Put mappings **only** on the named Sunshine pad (`Sunshine (libvirtualhid) AYN_Thor`). Default profile `x360` is `045e:028e` bus `0005` (`GAMESTREAM_PAD_PROFILE`). Steam wrap `Microsoft X-Box 360 pad N` (`28de:11ff`) may stay listed with **empty** `<mappings>`. Reordering Sunshine first while Steam still has mappings still steals player 0.
- Do not hardcode generic `X-Box 360 Controller` GUID `0_050017945e0400008e02000014010000`. Drop stale `AYN20Thor`.
- Game Mode `patch-cemu-input.py` pick order is still physical Xbox → Switch Pro → Steam virtual → Sunshine. Desktop GameStream uses bind-gamepad. Do not bind `libvirtualhid Mouse` (`1209:0003`).
- Changing uuid/type while Cemu is running does nothing. Stop Cemu, write the file, start again.

Default `GAMESTREAM_PAD_PROFILE=x360` (`back_button_timeout = 500`). `auto` is Xbox Series UHID `045e:0b13`; Steam Big Picture Guide needs uinput 360 `045e:028e`. DS `xone` is still UHID `0B20`, not Decky’s InputTino `045e:02ea`. Do not flip the profile unless the user wants gyro.

### Launch

Close the smoke HUDs. Moonlight already on `:48100`. Then either set `CEMU_ROM` and run the script, or:

```bash
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus DISPLAY=:0
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0 SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="$(python3 scripts/pad_profile.py sdl-except)"
# Wind Waker HD often lives at ~/emulation/wiiu/windwakerhd/*.wux
flatpak run info.cemu.Cemu -g "<wux>"
```

Do not inherit Steam’s `SDL_GAMECONTROLLER_IGNORE_DEVICES`. Do not change Moonlight controller mapping.

### Steam Guide / Big Picture (related)

`back_button_timeout = 500` alone is not enough. Hold Select 0.5s pulses Guide on the **virtual pad**. Steam only honors that on uinput x360. Silent autostart (`steam -silent -steamdeck`) swallows `steam://open/*` with no window; start `/usr/bin/steam` without `-silent` if you need a visible client.

## Azahar dual-screen (Thor)

From Moonlight on `:48100`, tap **Azahar Dual-Screen** (`scripts/sunshine-app-azahar.sh`; box art is the Azahar Flatpak icon). Same dual-stream as Cemu, for 3DS. Recipe: **`.cursor/skills/azahar-dual-screen/SKILL.md`** and `scripts/ensure-azahar-dual-screen.sh`.

- Standalone Flatpak `org.azahar_emu.Azahar`, **not** RetroDECK `azahar-launcher`.
- `layout_option=4` Separate Windows, `secondary_display_layout=2` BottomScreenOnly, `screen_bottom_stretch` / `screen_top_stretch` true (otherwise 4:3 fills the 1920×1080 GamePad window by height only).
- Caption `Primary Window` → HDMI-A-1 (top screen). `Secondary Window` → Virtual-sunshine-ds (touch). Minimize the library window.
- Bind: `python3 scripts/bind-gamepad.py azahar --match Thor` (map from `pad_profile.py`; x360 L/R = SDL 6/7, Select/Start = 10/11). Restart Azahar after the bind.
- Close: dual-screen windows have no chrome; 3DS Home does not quit Azahar. Moonlight overlay **Quit game**, or `scripts/sunshine-app-stop.sh azahar`.
- Launch `QT_QPA_PLATFORM=xcb`. Qt Wayland dies (`wp_linux_drm_syncobj_surface_v1`).
- Process `comm` is `azahar`. `resourceClass` is `Azahar`.

## Gyro / motion (Thor and Odin)

Moonlight can send the handheld IMU (`Allow use of gamepad motion sensors`, and **Emulate gamepad motion sensor support** to use the device gyro when the pad has none). The host pad is `GAMESTREAM_PAD_PROFILE` (`scripts/pad_profile.py`). Default **x360** cannot expose motion. `ds5` / `ds4` / `switch` can, but they change VID/PID and break Steam Guide plus current Cemu/Azahar binds. To experiment later: set the env var, run `ensure-sunshine-ds-apps.sh`, restart sunshine-ds, reconnect Moonlight, re-bind. Stay on x360 until the user asks.

## Do not

- Treat probe I-frame size as capture health
- Enable Flatpak Sunshine systemd user unit
- Poll `/api/restart` or restart Decky to “fix” DS
- Hardcode Headscale URLs or print `.auth` / certs / passwords
- Install Bazzite Eden reorder hooks
- Use RetroDECK Cemu (`-f` / fullscreen) for Thor dual-screen GamePad
- Use RetroDECK Azahar (`azahar-launcher` / fullscreen) for Thor dual-screen 3DS
- Launch Azahar on Qt Wayland (`--socket=wayland`) — drm_syncobj protocol error
- Emulate Wii U Pro Controller when the bottom stream should be the GamePad
- Hand-edit `controller0.xml` or copy mappings onto every `<controller>`
- Reorder Sunshine first while Steam still has mappings
- Leave sunshine-ds on `gamepad = auto` / `xseries` if Select-hold must open Steam Big Picture
- Kill `sunshine-ds-virtual-output` while dual-stream is the checkpoint, or when a client disconnects
- Spawn a second virtual-output helper named `sunshine-ds` (Linux DS supports **one** virtual display; HDMI is the TV)
- Call `kscreen-doctor` to decide whether `Virtual-sunshine-ds` exists (hangs with duplicates)
- Compositor `reinitialize` as the first fix for “connecting never streaming” (kills the helper / can restart KWin). Restart PipeWire then DS first.
- Map Azahar L/R to SDL 4/5 on a Sunshine pad (those are Y/Z; shoulders are 6/7)
- `pgrep -f` / `pkill -f` sunshine, or `pgrep -f` a command that contains `sunshine-ds-virtual-output`
- Rebuild sunshine-ds to “fix” Odin “Starting connection” (that was Moonlight STACKED never binding the in-layout second surface)
- Expect Thor dual-panel on the Portal, or stacked plus a separate Android display at once
- `export LD_LIBRARY_PATH` to run `sunshine-ds-kms` after `setcap` (AT_SECURE ignores it; use RUNPATH)
- `setcap` `~/.local/bin/sunshine-ds` (desktop Distrobox path). Game Mode KMS is the `sunshine-ds-kms` copy on `:48200` only
- `sudo` `sunshine-ds-kms` or `sudo systemctl --user` (start as `deck`; sudo is only `setcap`)
- Set `dual_display_source = virtual` on `:48200` (KWin helper). Game Mode video/1 is `gamescope-virtual` plus `scripts/sunshine-ds-gamemode-virtual.sh`
- `ensure-sunshine-ds-gamemode.sh --start` while headless `:2` is already up (`KillMode=mixed` can kill the helper). Restart kms with `systemctl --user restart steamos-sunshine-ds-gamemode.service`
