---
name: sunshine-ds-gamemode
description: Restore and debug SteamOS Game Mode dual-stream on sunshine-ds-kms (:48200). HDMI/top is Steam or Cemu TV; bottom is the idle screensaver clock or Cemu GamePad. Use when the user mentions Game Mode GameStream, :48200, sunshine-ds-kms, gamescope-virtual, headless :2, bottom screensaver, Thor dual-panel Wind Waker, Steam overlay in Game Mode, or a black GamePad stream.
---

# Game Mode dual-stream (`:48200`)

Read this **before** changing capture, PipeWire, or Cemu launch. Desktop Thor/Odin daily dual-screen stays Plasma `:48100`. Do not merge kms into play / `:48100`. Stack/SHAs: [../sunshine-ds-gamestream/reference.md](../sunshine-ds-gamestream/reference.md). Host uniqueids: `~/.cursor/skills/sunshine-ds-gamestream/host.md`.

**Checkpoint (user 2026-09-10: “it works!”): `checkpoint-2026-09-10-gamemode-works`.** Both screens, Steam overlay (Cemu windows listed), bottom screensaver, Thor pad. Do not “improve” it unless it breaks. Screens-only subset: `checkpoint-2026-09-10-gamemode-dual-stream`.

## What must be true

| Surface | Idle (Desktop `958645192`) | Cemu playing |
|---|---|---|
| HDMI / Thor top (video/0) | Steam Big Picture / focused game | Cemu TV (`------- Init Cemu`, 1920×1080 InputOutput) |
| `:2` / Thor bottom (video/1) | Screensaver clock + moving bar (`sunshine-ds-bottom-screensaver.py`) | GamePad View via `ffplay` `x11grab` |
| Overlay | Hold Select 0.5s → `STEAM_OVERLAY=1` on BPM + `FOCUSED_APP=769` | Same; hide restores Cemu TV. Overlay lists Cemu TV + GamePad View. Focus watcher must not reclaim while overlay is up |
| Audio | Pulse default **Virtual Surround Sound** → HDMI | Same. Moonlight must capture `Virtual Surround Sound.monitor`, **not** `sink-sunshine-stereo` (Cemu Cubeb never follows `set-default-sink`; the null sink is SUSPENDED → `PulseAudio record stream not ready` and Thor is silent while the TV still plays). Log: `Capturing host sink [Virtual Surround Sound]` / `Found default monitor by name: Virtual Surround Sound.monitor`. Conf pins `audio_sink = Virtual Surround Sound` when that sink exists. |
| Thor pad | Sunshine x360 present after connect | SteamInput-P1 maps on `Sunshine (libvirtualhid) AYN_Thor` only. Uuid `{live-index}_{guid}` (`0_0500b2ca…` when Thor is js3). SDL map **15-button** (`LB=b6` `Back=b10`), not xpad 11-button (`LB=b4` `Back=b6`). WW first-person look is **L bumper**, not Select |

Moonlight host is **`:48200`** uniqueid `1075C8EF…`. App **Desktop** is `958645192`. Do **not** `/launch` desktop-DS `881448767` (kms: `Couldn't find app with ID`). Not Decky `:47989`. Two De-FanGoH tiles: white = `:48200`, grey warning = `:48100`.

## Bring-up (do not rediscover)

Headless `:2` already up (helper + screensaver) — start kms only:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
# Sidecar must be serial= / pw_node= (not node=).
cat "$XDG_RUNTIME_DIR/sunshine-ds-gamemode-virtual"
./scripts/ensure-sunshine-ds-gamemode.sh --start-kms
curl -s --max-time 3 http://127.0.0.1:48200/serverinfo | grep -E 'state|uniqueid|MaxVideo'
CEMU_PAD_MATCH=Thor ./scripts/ensure-cemu-gamemode-dual-screen.sh   # no -f
```

Cold start (no `:2`): `./scripts/ensure-sunshine-ds-gamemode.sh --start` then the Cemu line. **`--start` while `:2` is live can KillMode the helper.** Restart kms with `systemctl --user restart steamos-sunshine-ds-gamemode.service` or `--start-kms`.

Cemu is Steam `RunGame` (same as Tender Play) + consume-on-read `logs/cemu-gamemode-ds.want` → `CEMU_GAMEMODE_DS=1`. `rom-launcher` / `Cemu-wrapper` start `cemu-gamescope-focus.sh` **before** gtk_init (`FOCUSED_APP=<shortcut>`, `FOCUS_DISPLAY` middle **1**). A leftover want file windowed-10×10s every Play — delete it. `steam://`, host `flatpak run`, and RetroDECK `-f` stay a 10×10 InputOnly stub. Bind with `bind-gamepad.py wait-appear --match Thor` then `cemu --match Thor --force` (mappings only on `Sunshine (libvirtualhid) AYN_Thor`). Cemu uuid is `{sdl-index}_{guid}` — a stale `1_<guid>` when Thor is now index 0 means “controllers not mapped.” Cemu reads uuid at start; restart after bind.

On Cemu/mirror exit: `./scripts/sunshine-ds-gamemode-virtual.sh --paint` restores the clock. `--place-only` re-asserts GamePad under TV + ffplay on `:2` without relaunch.

## Capture path that works

Sep 9 `119d7452` / this checkpoint: **`PW_KEY_TARGET_OBJECT` = sidecar `object.serial` + `PW_STREAM_FLAG_AUTOCONNECT`**.

```
[pwgrab] sidecar … serial=<N> node=4294967295
[pipewire] Create PW stream … object_serial=<N> target=serial
[pipewire] Connect PW stream PW_ID_ANY serial=<N>
[pipewire] cpu frame type=2 … nonzero=8294400/8294400 pixel_diffs=<moving>
[kmsgrab] DMA-BUF copied 1920x1080 nonzero≈8.2M
```

PipeWire: gamescope Video/Source **running**, a Link to the Sunshine consumer. `--smoke` (`gst-launch pipewiresrc target-object=$serial`) must write `logs/sunshine-ds-gamemode-virtual.png` before blaming kms.

`f8d9968c` skipped AUTOCONNECT when sidecar had `node=`. The sidecar **always** has a node id, so video/1 stayed dummy black. Writer must use `pw_node=`. sunshine-ds `9e07d39e` restores AUTOCONNECT even if `node=` is present; live capped ELF may still be the skip build — keep `pw_node=`. Do not skip AUTOCONNECT “because we have a node id.”

If a **new** headless gamescope never logs `stream available on node ID` and stays `connecting`: PipeWire is wedged. `systemctl --user restart pipewire.service pipewire-pulse.service` (not `sudo systemctl --user`). Session gamescope (HDMI) must stay up.

## Health (ADB + host)

- `pgrep -x sunshine-ds-kms` only. Never `pgrep -f` / `pkill -f` sunshine.
- getcap `sunshine-ds-kms` is `cap_sys_admin=ep`. `--replace-bin` / `cp` / `patchelf` strip it. Stage `sunshine-ds-kms.new`, `sudo setcap cap_sys_admin+ep` on **`.new`**, then `--promote-new` (mv keeps the xattr). Never `setcap` `sunshine-ds`. Never `LD_LIBRARY_PATH` (AT_SECURE).
- Cemu TV ≥64×64 InputOutput on session **`:1`**, title has `Init` / `TitleId` / FPS. GamePad View is the sibling on `:1` (`FOCUS_DISPLAY=1`). Steam BPM stays on `:0`. A 10×10 InputOnly `Cemu_relwithdebinfo` is the hidden helper — do not make it HDMI BASELAYER. GamePad inject log must be `using :1`, not `no GamePad View … on :0`. HDMI / top taps are a **separate** display-0 inject: Cemu TV on `:1` while playing, Steam Big Picture on `:0` while hold-Select overlay is up (`HDMI inject: overlay on :0`). Do not route top taps through GamePad View. Odin GamePad-only (`primary_from_secondary`) must not take the HDMI path. Live WW HD: TV frame `0x800003` 1920×1080, GL child ~1920×1051+0+29; GamePad frame `0x800016`, GL child `0x800040` 1920×1080.
- Thor screencap: top `local:4630946441858561667`, bottom `local:4630946482288158084`. Bottom ~8KB PNG is pitch black. Clock / GamePad is tens–hundreds of KB.
- Title-screen GamePad often matches TV; unique pad UI is in-game.

## Do not

- Switch Game Mode ↔ Desktop to “fix” capture
- Kill session gamescope (HDMI / `:0`/`:1`)
- `--start` kms while headless `:2` is already up
- Write sidecar `node=` (use `pw_node=`)
- `/launch` `881448767` or Low Res Desktop on kms
- Leave `logs/cemu-gamemode-ds.want` after a failed launch
- Set `:0` `GAMESCOPECTRL_BASELAYER_WINDOW` to a 10×10 Cemu stub
- RetroDECK `-f` / `ensure-cemu-dual-screen.sh` (KWin) in Game Mode
- `sudo systemctl --user`, `POST /api/restart`, `kwin_wayland --replace`, Decky `:47989`
- Start `steam-guide-from-select.py` as a watcher (`--hide` is debug-only)
- Rewrite `shortcuts.vdf` while Game Mode is running
- Write Steam xpad 11-button `_X360_SDL_MAP` (`LB=b4` `Back=b6`) — libvirtualhid is 15-button
- `XOpenDisplay(":0")` only for GamePad or HDMI inject — Cemu is on `:1`. Never `$DISPLAY` / `:2`
- Change `inject_gamepad_view_*` / `abs_targets_gamepad_view` while fixing HDMI touch — HDMI is a parallel display-0 path
