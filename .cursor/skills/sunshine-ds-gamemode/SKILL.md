---
name: sunshine-ds-gamemode
description: Restore and debug SteamOS Game Mode dual-stream on sunshine-ds-kms (:48200). HDMI/top is Steam or Cemu TV; bottom is the idle screensaver clock or Cemu GamePad. Use when the user mentions Game Mode GameStream, :48200, sunshine-ds-kms, gamescope-virtual, headless :2, bottom screensaver, Thor dual-panel Wind Waker, Steam overlay in Game Mode, or a black GamePad stream.
---

# Game Mode dual-stream (`:48200`)

Read this **before** changing capture, PipeWire, or Cemu launch. Desktop Thor/Odin daily dual-screen stays Plasma `:48100`. Do not merge kms into play / `:48100`. Stack/SHAs: [../sunshine-ds-gamestream/reference.md](../sunshine-ds-gamestream/reference.md). Host uniqueids: `~/.cursor/skills/sunshine-ds-gamestream/host.md`.

**THE Game Mode `:48200` standard is `checkpoint-2026-09-18-gamepad-xtest`** (user: “CHECKPOINT, WE DID IT”). Thor bottom taps reach Cemu GamePad and line up under Stretch (XTest after briefly clearing overlay/opacity; `:0` FOCUS_DISPLAY flush; linear `x/width`). 4K HDMI + 1080p GamePad. Live packets `ref=1239x1079` — do **not** unletterbox Fit bars (that sheared Y; packet y=332 is unit≈0.308, not the image top). Host `4ca50111`. QAM **preset 2** bar spans the TV. After `:2` respawns, kms rebinds video/1. Subsets: fill+Exit `checkpoint-2026-09-14-gamemode-fill-exit`; tile grab `checkpoint-2026-09-11-gamemode-tender-ds`; Home/Library mute `checkpoint-2026-09-11-steam-menu-mute`; HDMI-hud mangoapp isolation `checkpoint-2026-09-17-hdmi-hud`. Steam **audio** menu clicks still **pending**. Do not “improve” GamePad tap math, XTest inject, or Stretch mapping unless it breaks.

## Do not lose (conversation / box)

- **Cemu “crash” on Home** was inhibit treating `FOCUSED_APP=769` as Exit (`Steam Exit — FOCUSED_APP=769, quitting`). `log.txt` stopping mid-`FSGetVolumeState` is SIGTERM, not a Cemu fault. Mute only. Do not restore the 8s-769 `--quit` gate.
- **Tender “RomM disconnected”** on a 3DS tile usually means no `rom_installs` row (UI shows Download and hits RomM) even when the `.3ds` is already in `n3ds`. `set-steam-launch-options.py --repair-tender`, then **reopen Tender**. Empty Steam LaunchOptions recover via `SteamAppId` → Tender DB. Do not rewrite `shortcuts.vdf` in Game Mode.
- **Older tiles** still `exec` missing `~/homebrew/plugins/decky-romm-sync/bin/rom-launcher` (Tender replaced that plugin). `ensure-eden-component.sh` `record_manual` has the `sudo mkdir/cp/chmod/chown` — `~/homebrew/plugins` is often `root:root` and `sudo -n` fails.
- **Azahar Game Mode path:** Tender `rom-launcher` **runs** `ensure-azahar-gamemode-dual-screen.sh` (do not `exec`). Disown the focus watcher (same as Cemu). Wait for `azahar`, then `--quit`. Paint `:2` only after `azahar` is gone. `azahar_on_hdmi()` searches `:0` and `:1`. Inhibit `restore_bottom_screen()` paints `:2` when the last emu is gone (skip if Cemu/Azahar still up). Unset `LD_PRELOAD` in that script (Steam ELFCLASS32 spam).
- **Mux restart:** `systemctl --user restart emupads-mux.service` (never `sudo systemctl --user`). Then restart Cemu/Azahar/Eden — new uinput nodes. Config `~/.config/emupads/mux.json`.
- Bind Cemu/Azahar/Eden to **EmuPads P1/P2** only. The `wait-appear --match Thor` / `cemu --match Thor` lines below are wait-for-pad helpers, not XML bind targets.
- Game Mode `apps.json` is **Desktop only**. Do not re-add **Cemu Dual-Screen** — Tender tiles own Cemu.
- Azahar Steam Exit `--quit` must not paint until `azahar` is gone. A leftover `sunshine-ds-bottom-paint.service` fragment makes `systemd-run` fail ("already loaded"); the old in-process fallback left the clock in `app-steam-app*.scope` and Steam sat on Exiting. Drop that fragment before `--paint`. Do not start the clock in-tile.
- `--paint` must `systemd-run --user --no-block` the idle clock (`Type=oneshot`, `KillMode=process`). `setsid`/`disown` stay in `app-steam-app*.scope`; Steam's reaper waitpid on that clock is the Azahar “Exiting…” hang. Cemu usually avoids it because the tile `exec`s Cemu and the watcher paints after that process is already gone.
- Mux must incremental-rescan on pad reconnect (do not close every source fd each second).
- Mux mutes **and EVIOCGRAB**s P1/P2 while `FOCUSED_APP=769` / overlay / QAM so Steam’s menu only sees the Sunshine pad (glyph flicker was P1 duplicating Thor). Plugin `pads` list never includes sinks (`1209:e301` / `e302`) or Steam wraps (`28de:11ff`) when Thor/Odin are present. Shared / Multiplayer must persist; a status poll must not flip the toggle back to Shared P1.
- **QAM Render second screen** Off `--stop`s headless `:2` (HDMI stays). If the toggle already looks On but Thor bottom is dead, turn it Off then On, or `python3 scripts/second-screen-windows.py set-virtual-output --mode on`. **Screensaver** Off kills the idle clock without stopping `:2`. `steamos-sunshine-ds-gamemode-recover.service` (`virtual.sh --watch`) restarts `:2` / paints the clock when those prefs are on and the bottom is empty. Live Cemu/Azahar `ffplay` is left alone (clock is dropped so it cannot compete). Leftover `ffplay` with no emu is killed then painted. Do not `--start` kms from that watcher. After `:2` respawns it gets a new PipeWire `serial=`; live kms still AUTOCONNECTs the old node and video/1 falls through to HDMI (Thor bottom duplicates the TV). `start_virtual` then `systemctl --user restart steamos-sunshine-ds-gamemode.service` (`--start-kms` does the same if kms is already up). Keep `:2`.
- **4K HDMI + 1080p GamePad bottom taps**: GamePad View stays 1920×1080 at `0,0` on nested `:1` (now 3840×2160). wx/GTK drop `XSendEvent` (`send_event` is always True). Overlay-tag + opacity 0 also skip gamescope hit-test, so `XQueryPointer` stays on the 4K TV. Inject briefly clears those tags, `XTestFake*` a real click onto the GL child, then re-covers. Do **not** also uinput. `GAMESCOPE_FOCUS_DISPLAY` writes go to session `:0` and must `XFlush` that connection (GamePad Xlib talks to `:1`). Middle must stay **1** while Cemu is on `:1`. Thor Stretch fills the **1240×1080** panel; live packets are `ref=1239x1079`. `packet_to_unit` is linear `x/width` (Stretch). Do **not** unletterbox — Fit already shrinks the StreamView to 16:9. Do **not** run `client_to_touchport`. Log: `GamePad pkt … unit=…` then `abs … 1920x1080`. A tap at packet y=190 is ~18% down, not the image top.
- **4K HDMI + 1080p GamePad 1/4 flicker** (Thor clip `screen-20260917-140731`, **also in the Steam menu**): not only Cemu. Nested `:1` must stay HDMI native — shrinking it to 1080p quarters Steam itself. `mangoapp overlay window` **is Steam’s performance overlay** (QAM / Settings → Monitor performance, detail slider writes `preset=` / `no_display` in the gamescope `mangohud.config`). Do **not** set opacity 0 on it and do **not** `windowsize` it to 4K — mangoapp `glfwSetWindowSize`s itself to gamescope `outputWidth` when preset 2 is `horizontal`. Headless `:2` (`gamescope --backend headless -W 1920 -H 1080`) also `msgsnd`s that queue; a shared `ftok("mangoapp")` key keeps the overlay at 1080p so the stretched bar 1/4-flashes. `sunshine-ds-gamemode-virtual.sh` starts headless from `$XDG_RUNTIME_DIR/sunshine-ds-gamemode-headless` with its own `mangoapp` ftok file. `scripts/ensure-mangohud-presets.sh` installs `[preset 2]` `inherit` + `horizontal` + `horizontal_stretch=1` + `background_alpha=0.5` so the bar spans HDMI. Other presets stay stock. Cemu GamePad is a second 1080p focus candidate on `:1`; overlay-tag frame **and** GL children, opacity 0 on the **frame only** (child opacity 0 kills wx taps). `windowraise` not `windowactivate`. Do not park at `3840,0`. Stamp BASELAYER on **`:0`**. `FOCUS_DISPLAY` middle **1** while Cemu is on `:1`. Do not set MODE_CONTROL idx 2.

## What must be true

| Surface | Idle (Desktop `958645192`) | Cemu playing |
|---|---|---|
| HDMI / Thor top (video/0) | Steam Big Picture / focused game | Nested `:1` is **HDMI native** (4K). Cemu TV fills that. GamePad stays 1920×1080 at `0,0`, overlay-hidden. `:2` stays 1920×1080. |
| `:2` / Thor bottom (video/1) | Screensaver clock + moving bar (`sunshine-ds-bottom-screensaver.py`) | GamePad View via `ffplay` `x11grab` |
| Overlay | Hold Select 0.5s → `STEAM_OVERLAY=1` on BPM + `FOCUSED_APP=769` | Same; hide restores Cemu TV. **QAM** is Quick Access (`...`): `GAMESCOPE_BLUR_MODE!=0`, FOCUSED_APP stays the game. Home / Library / other BPM menus are `FOCUSED_APP=769` with the game still running — **mute** sinks, do not `--quit`. Focus watcher must not reclaim while overlay, QAM, or Steam menus are up. Mute is `scripts/inhibit-emu-input-on-steam-ui.py`. Steam Exit `--quit`s only on SIGTERM pending — do not SIGSTOP. After the emulator dies, restore `FOCUSED_APP=769` on `:0` (leave `:1` if Cemu is still there). Steam keeps the Sunshine pad for overlay / QAM / menus. |
| Audio | Pulse default HDMI (Steam UI; `STEAM_DISABLE_AUDIO_DEVICE_SWITCHING=1`). Cemu Cubeb → **Virtual Surround Sound** → that HDMI | Moonlight captures the **HDMI** sink monitor (leaf), not VSS and not `sink-sunshine-stereo`. Cemu on that sink is proven. **PENDING:** Steam menu / BPM nav clicks still silent on Thor after HDMI capture + unsuspend. Not a Moonlight record-stream bug (`sunshine-record` links; Cemu is audible). Steam has no UI playback stream. Check TV speakers while clicking menus: silent on TV = host/Steam (Game Mode **Settings → Audio**). Do **not** unmute WirePlumber `Notification` or edit Steam settings unless asked. |
| Thor pad | Sunshine x360 present after connect | Cemu binds **EmuPads P1** (mux copies Thor/Odin/phone). Uuid `{0}_{p1-guid}`. SDL map **15-button** (`LB=b6` `Back=b10`). WW first-person look is **L bumper**, not Select |

Moonlight host is **`:48200`** uniqueid `1075C8EF…`. App **Desktop** is `958645192`. Do **not** `/launch` desktop-DS `881448767` (kms: `Couldn't find app with ID`). Not Decky `:47989`. Two De-FanGoH tiles: white = `:48200`, grey warning = `:48100`.

## After reboot / SteamOS update

Reboot in Game Mode: `:48200` + `:2` clock + EmuPads mux start with `gamescope-session`. Pin Moonlight to `:48200` (not Decky `:47989`). Tender Play while `BUSY` is the working dual-screen path.

SteamOS update: `/home` stays; `/` can wipe sudoers / udev. Restore with `./post-update.sh` (it now passes `--install-service`). If kms is down after that:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
./scripts/ensure-sunshine-ds-gamemode.sh --start-kms   # when :2 is already up
# or --start when :2 is gone
./scripts/ensure-emupads-mux.sh
```

`getcap ~/.local/bin/sunshine-ds-kms` must be `cap_sys_admin=ep`. Passwordless setcap is `/etc/sudoers.d/zzz-sunshine-ds-kms-setcap` (wiped by updates). Tender updates overwrite `rom-launcher` — `ensure-eden-component.sh`.

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

Cemu is Steam `RunGame` (same as Tender Play). Dual-screen when **either** consume-on-read `logs/cemu-gamemode-ds.want` is fresh **or** Tender Play sees `:48200` `SUNSHINE_SERVER_BUSY` plus the gamescope-virtual sidecar **and** Moonlight is watching the bottom (`scripts/gamemode-second-screen-streaming.sh`, Decky **Second Screen** Auto). Top-only Moonlight stays `-f`. Force Dual-screen / HDMI only from Second Screen QAM (`mux.json` `dual_screen`). Local Play (kms FREE) stays `-f`. `rom-launcher` / `Cemu-wrapper` start `cemu-gamescope-focus.sh` **before** gtk_init (`FOCUSED_APP=<shortcut>`, `FOCUS_DISPLAY` middle **1**). A leftover want file windowed-10×10s every Play — delete it. Tender plugin updates overwrite `rom-launcher`; re-run `ensure-eden-component.sh`. `steam://`, host `flatpak run`, and RetroDECK `-f` stay a 10×10 InputOnly stub. Wait for the Sunshine pad with `bind-gamepad.py wait-appear --match Thor` if needed, then bind **EmuPads P1** (`apply --emu cemu --force --cemu-p1 gamepad`). Do not write Thor’s GUID into XML. Cemu uuid is `{sdl-index}_{guid}` — a stale `1_<guid>` when P1 is now index 0 means “controllers not mapped.” Cemu reads uuid at start; restart after bind.

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
- Cemu TV ≥64×64 InputOutput on session **`:1` at HDMI native** (`GAMESCOPE_XWAYLAND_MODE_CONTROL` `1, 3840, 2160, 0` on a 4K TV). GamePad View is the sibling at `0,0` 1920×1080 with `GAMESCOPE_EXTERNAL_OVERLAY=1`, opacity 0 on the **frame only** (GL child stays opaque — inject target), then `windowraise`. Steam BPM stays 4K on `:0`. A 10×10 InputOnly `Cemu_relwithdebinfo` is the hidden helper — do not make it HDMI BASELAYER. GamePad inject log must be `using :1` then `abs unit=` on the 1920×1080 GL child (not a 4K TV xid). HDMI / top taps: Cemu TV / Azahar Primary stay window-local abs on the TV GL child (~3840×~2160 minus chrome). **Eden** (`Eden | v…` on `:1`, often 1024×576) is a **trackpad** — relative `move_mouse` + `button_mouse` at the host cursor (`HDMI inject: trackpad` / `HDMI trackpad dx=`). Do not XTest the full 4K HDMI stream onto that small Qt window. Overlay hide still restores Eden as BASELAYER (`title_is_hdmi_surface`). Steam menu top taps stay overlay abs on `:0` (`HDMI inject: overlay on :0`). Bottom GamePad stays absolute XTest clicks (`checkpoint-2026-09-18-gamepad-xtest`). Do not route top taps through GamePad View. Do not uinput a GamePad click (4K TV steals it). Stamp BASELAYER on `:0`. `FOCUS_DISPLAY` middle **1**.
- Thor screencap: top `local:4630946441858561667`, bottom `local:4630946482288158084`. Bottom ~8KB PNG is pitch black. Clock / GamePad is tens–hundreds of KB.
- Title-screen GamePad often matches TV; unique pad UI is in-game.

## Do not

- Shrink nested `:1` to 1080p so the GamePad fills it — that 1/4-flashes the **Steam menu** on a 4K TV. Keep `:1` at HDMI native; overlay-hide the 1080p GamePad.
- Park GamePad at HDMI width,0 on a 4K nested `:1` — `XWarpPointer` clamps and bottom taps die
- Opacity 0 on the Cemu/Azahar **GL child** — that is the GamePad/Secondary inject target; overlay-tag it, but keep it opaque
- `GAMESCOPE_XWAYLAND_MODE_CONTROL` idx 2 — that is not headless `:2`; leave the virtual gamescope at 1920×1080
- Write stale `GAMESCOPE_FOCUS_DISPLAY` `12346, 1, 66` — preserve the live first/third cardinals and only change the middle index
- `windowlower` / `windowactivate` GamePad / Azahar Secondary every watcher tick — restack or activate flashes the 1080p quarter on 4K HDMI
- Switch Game Mode ↔ Desktop to “fix” capture
- Kill session gamescope (HDMI / `:0`/`:1`)
- `--start` kms while headless `:2` is already up
- Write sidecar `node=` (use `pw_node=`)
- `/launch` `881448767` or Low Res Desktop on kms
- Leave `logs/cemu-gamemode-ds.want` after a failed launch (Tender auto-DS does **not** write that file)
- Expect Tender Cemu Play to stay `-f` while `:48200` is BUSY and the virtual sidecar is up — that path is windowed `--attach`
- Expect Tender 3DS Play to stay RetroDECK `azahar-launcher` while `:48200` is BUSY — that path **runs** standalone `ensure-azahar-gamemode-dual-screen.sh` (do not `exec`; wait then `--quit`; `--paint` only after `azahar` is gone)
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
