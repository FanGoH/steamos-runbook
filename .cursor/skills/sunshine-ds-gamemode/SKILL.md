---
name: sunshine-ds-gamemode
description: Restore and debug SteamOS Game Mode dual-stream on sunshine-ds-kms (:48200). HDMI/top is Steam or Cemu TV; bottom is the idle screensaver clock or Cemu GamePad. Use when the user mentions Game Mode GameStream, :48200, sunshine-ds-kms, gamescope-virtual, headless :2, bottom screensaver, Thor dual-panel Wind Waker, Steam overlay in Game Mode, or a black GamePad stream.
---

# Game Mode dual-stream (`:48200`)

Read this **before** changing capture, PipeWire, or Cemu launch. Desktop Thor/Odin daily dual-screen stays Plasma `:48100`. Do not merge kms into play / `:48100`. Stack/SHAs: [../sunshine-ds-gamestream/reference.md](../sunshine-ds-gamestream/reference.md). Host uniqueids: `~/.cursor/skills/sunshine-ds-gamestream/host.md`.

**Checkpoint `checkpoint-2026-09-11-3ds-n3ds`:** 3DS dumps live in `~/retrodeck/roms/n3ds` (moved from `~/emulation/3ds/games`, not copied; dest is **`n3ds`**, not `roms/3ds`); Tender marks them launchable. Azahar dual-stream Play works. Home/Library mute remains `checkpoint-2026-09-11-steam-menu-mute`. Mux + tile GamePad-vs-Pro + overlay/QAM mute remain `checkpoint-2026-09-11-emupads-mux`. Tile/GamePad grab recipe is still `checkpoint-2026-09-11-gamemode-tender-ds` (`--attach`, no `-f`, x11grab session `:1`). Local Play (kms FREE) stays `-f`. Steam **audio** menu clicks still **pending**. Azahar exit must `--paint` `:2` (do not leave the last 3DS bottom frame).

## Do not lose (conversation / box)

- **Cemu “crash” on Home** was inhibit treating `FOCUSED_APP=769` as Exit (`Steam Exit — FOCUSED_APP=769, quitting`). `log.txt` stopping mid-`FSGetVolumeState` is SIGTERM, not a Cemu fault. Mute only. Do not restore the 8s-769 `--quit` gate.
- **Tender “RomM disconnected”** on a 3DS tile usually means no `rom_installs` row (UI shows Download and hits RomM) even when the `.3ds` is already in `n3ds`. `set-steam-launch-options.py --repair-tender`, then **reopen Tender**. Empty Steam LaunchOptions recover via `SteamAppId` → Tender DB. Do not rewrite `shortcuts.vdf` in Game Mode.
- **Older tiles** still `exec` missing `~/homebrew/plugins/decky-romm-sync/bin/rom-launcher` (Tender replaced that plugin). `ensure-eden-component.sh` `record_manual` has the `sudo mkdir/cp/chmod/chown` — `~/homebrew/plugins` is often `root:root` and `sudo -n` fails.
- **Azahar Game Mode path:** Tender `rom-launcher` **runs** `ensure-azahar-gamemode-dual-screen.sh` (do not `exec`). Disown the focus watcher (same as Cemu). Wait for `azahar`, then `--quit`/`--paint`. `azahar_on_hdmi()` searches `:0` and `:1`. Inhibit `restore_bottom_screen()` paints `:2` when the last emu is gone (skip if Cemu/Azahar still up). Unset `LD_PRELOAD` in that script (Steam ELFCLASS32 spam).
- **Mux restart:** `systemctl --user restart emupads-mux.service` (never `sudo systemctl --user`). Then restart Cemu/Azahar/Eden — new uinput nodes. Config `~/.config/emupads/mux.json`.
- Bind Cemu/Azahar/Eden to **EmuPads P1/P2** only. The `wait-appear --match Thor` / `cemu --match Thor` lines below are wait-for-pad helpers, not XML bind targets.

## What must be true

| Surface | Idle (Desktop `958645192`) | Cemu playing |
|---|---|---|
| HDMI / Thor top (video/0) | Steam Big Picture / focused game | Cemu TV (`------- Init Cemu`, 1920×1080 InputOutput) |
| `:2` / Thor bottom (video/1) | Screensaver clock + moving bar (`sunshine-ds-bottom-screensaver.py`) | GamePad View via `ffplay` `x11grab` |
| Overlay | Hold Select 0.5s → `STEAM_OVERLAY=1` on BPM + `FOCUSED_APP=769` | Same; hide restores Cemu TV. **QAM** is Quick Access (`...`): `GAMESCOPE_BLUR_MODE!=0`, FOCUSED_APP stays the game. Home / Library / other BPM menus are `FOCUSED_APP=769` with the game still running — **mute** sinks, do not `--quit`. Focus watcher must not reclaim while overlay, QAM, or Steam menus are up. Mute is `scripts/inhibit-emu-input-on-steam-ui.py`. Steam Exit `--quit`s only on SIGTERM pending — do not SIGSTOP. After the emulator dies, restore `FOCUSED_APP=769` on `:0` (leave `:1` if Cemu is still there). Steam keeps the Sunshine pad for overlay / QAM / menus. |
| Audio | Pulse default HDMI (Steam UI; `STEAM_DISABLE_AUDIO_DEVICE_SWITCHING=1`). Cemu Cubeb → **Virtual Surround Sound** → that HDMI | Moonlight captures the **HDMI** sink monitor (leaf), not VSS and not `sink-sunshine-stereo`. Cemu on that sink is proven. **PENDING:** Steam menu / BPM nav clicks still silent on Thor after HDMI capture + unsuspend. Not a Moonlight record-stream bug (`sunshine-record` links; Cemu is audible). Steam has no UI playback stream. Check TV speakers while clicking menus: silent on TV = host/Steam (Game Mode **Settings → Audio**). Do **not** unmute WirePlumber `Notification` or edit Steam settings unless asked. |
| Thor pad | Sunshine x360 present after connect | Cemu binds **EmuPads P1** (mux copies Thor/Odin/phone). Uuid `{0}_{p1-guid}`. SDL map **15-button** (`LB=b6` `Back=b10`). WW first-person look is **L bumper**, not Select |

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

Cemu is Steam `RunGame` (same as Tender Play). Dual-screen when **either** consume-on-read `logs/cemu-gamemode-ds.want` is fresh **or** Tender Play sees `:48200` `SUNSHINE_SERVER_BUSY` plus the gamescope-virtual sidecar (`scripts/gamemode-second-screen-streaming.sh`) → `CEMU_GAMEMODE_DS=1` and `ensure-cemu-gamemode-dual-screen.sh --attach` (no second RunGame). Local Play (kms FREE) stays `-f`. `rom-launcher` / `Cemu-wrapper` start `cemu-gamescope-focus.sh` **before** gtk_init (`FOCUSED_APP=<shortcut>`, `FOCUS_DISPLAY` middle **1**). A leftover want file windowed-10×10s every Play — delete it. Tender plugin updates overwrite `rom-launcher`; re-run `ensure-eden-component.sh`. `steam://`, host `flatpak run`, and RetroDECK `-f` stay a 10×10 InputOnly stub. Wait for the Sunshine pad with `bind-gamepad.py wait-appear --match Thor` if needed, then bind **EmuPads P1** (`apply --emu cemu --force --cemu-p1 gamepad`). Do not write Thor’s GUID into XML. Cemu uuid is `{sdl-index}_{guid}` — a stale `1_<guid>` when P1 is now index 0 means “controllers not mapped.” Cemu reads uuid at start; restart after bind.

On Cemu/mirror exit the focus watcher `stop_mirror`s leftover `:2` `ffplay` `x11grab` (pidfile **and** `pgrep -x ffplay` + argv) then `./scripts/sunshine-ds-gamemode-virtual.sh --paint` restores the clock. `--paint` must kill that x11grab first or it skips and the bottom stays frozen. `--place-only` re-asserts GamePad under TV + ffplay on `:2` without relaunch. `--attach` starts the same watcher so Tender Play exit always paints.

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
- getcap `sunshine-ds-kms` is `cap_sys_admin=ep`. `--replace-bin` / `cp` / `patchelf` strip it. Stage `sunshine-ds-kms.new`, `sudo setcap cap_sys_admin+ep` on **`.new`**, then `--promote-new` (mv keeps the xattr). Optional passwordless agent path: `sudoers/zzz-sunshine-ds-kms-setcap` → `/etc/sudoers.d/zzz-sunshine-ds-kms-setcap` (must sort after `wheel`). `scripts/ensure-sunshine-ds-kms-setcap.sh` from post-update. SteamOS readonly must be disabled to write that file; a SteamOS update can wipe it. Never `setcap` `sunshine-ds`. Never `LD_LIBRARY_PATH` (AT_SECURE).
- Cemu TV ≥64×64 InputOutput on session **`:1`**, title has `Init` / `TitleId` / FPS. GamePad View is the sibling on `:1` (`FOCUS_DISPLAY=1`). Steam BPM stays on `:0`. A 10×10 InputOnly `Cemu_relwithdebinfo` is the hidden helper — do not make it HDMI BASELAYER. GamePad inject log must be `using :1`, not `no GamePad View … on :0`. HDMI / top taps are a **separate** display-0 inject: Cemu TV on `:1` while playing, Steam Big Picture on `:0` while hold-Select overlay is up (`HDMI inject: overlay on :0`). Do not route top taps through GamePad View. Odin GamePad-only (`primary_from_secondary`) must not take the HDMI path. Live WW HD: TV frame `0x800003` 1920×1080, GL child ~1920×1051+0+29; GamePad frame `0x800016`, GL child `0x800040` 1920×1080.
- Thor screencap: top `local:4630946441858561667`, bottom `local:4630946482288158084`. Bottom ~8KB PNG is pitch black. Clock / GamePad is tens–hundreds of KB.
- Title-screen GamePad often matches TV; unique pad UI is in-game.

## Do not

- Switch Game Mode ↔ Desktop to “fix” capture
- Kill session gamescope (HDMI / `:0`/`:1`)
- `--start` kms while headless `:2` is already up
- Write sidecar `node=` (use `pw_node=`)
- `/launch` `881448767` or Low Res Desktop on kms
- Leave `logs/cemu-gamemode-ds.want` after a failed launch (Tender auto-DS does **not** write that file)
- Expect Tender Cemu Play to stay `-f` while `:48200` is BUSY and the virtual sidecar is up — that path is windowed `--attach`
- Expect Tender 3DS Play to stay RetroDECK `azahar-launcher` while `:48200` is BUSY — that path **runs** standalone `ensure-azahar-gamemode-dual-screen.sh` (do not `exec`; wait then `--quit`/`--paint`)
- Treat `FOCUSED_APP=769` as Steam Exit / `--quit` after 8s — that killed Cemu on Home
- Bind Cemu/Azahar/Eden to a Sunshine pad when the mux is down — start `emupads-mux.service` instead
- Set `:0` `GAMESCOPECTRL_BASELAYER_WINDOW` to a 10×10 Cemu stub
- `$(find_pad_wid)` / `$(find_tv_wid)` / `$(find_wid)` — command substitution is a subshell and drops `TV_DISPLAY`; x11grab then uses `:0` for a `:1` xid
- RetroDECK `-f` / `ensure-cemu-dual-screen.sh` (KWin) in Game Mode
- `sudo systemctl --user`, `POST /api/restart`, `kwin_wayland --replace`, Decky `:47989`
- Start `steam-guide-from-select.py` as a watcher (`--hide` is debug-only)
- Rewrite `shortcuts.vdf` while Game Mode is running (empty LaunchOptions / RomM-disconnected tiles recover via Tender DB)
- Write Steam xpad 11-button `_X360_SDL_MAP` (`LB=b4` `Back=b6`) — libvirtualhid is 15-button
- `XOpenDisplay(":0")` only for GamePad or HDMI inject — Cemu is on `:1`. Never `$DISPLAY` / `:2`
- Change `inject_gamepad_view_*` / `abs_targets_gamepad_view` while fixing HDMI touch — HDMI is a parallel display-0 path
