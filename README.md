# SteamOS Playbook

Idempotent bootstrap and recovery scripts for a SteamOS gaming desktop (`deck` user).

SteamOS updates can reset host state (udev rules, enabled services, pacman keyrings, packages on `/`) while keeping files under `/home`. This repo restores what it can automatically and prints copy-paste commands for the rest.

## First-time setup

```bash
cd ~/steamos-playbook
cp .env.example .env
# Edit .env — especially STEAMOS_NIC_INTERFACE and TAILSCALE_LOGIN_SERVER
./bootstrap.sh
./health-check.sh
```

## After SteamOS update

```bash
cd ~/steamos-playbook
git pull
./post-update.sh
```

`post-update.sh` restores services, then runs `health-check.sh` (the verification checklist) and prints failures / manual actions at the end.

`post-update.sh` restores when needed:

- pacman keyrings (`archlinux` + `holo`)
- `sshd`
- `wol.service` / Wake-on-LAN on `STEAMOS_NIC_INTERFACE`
- OpenRGB udev rules + user service + SDK device rescan (same as UI “Rescan devices”)
- Sunshine (Decky-owned; Pulse dir chmod 755 so bwrap can start; path unit starts Sunshine if GameStream is still down; waits for PluginLoader so boot does not hit systemd start-limit)
- Gear Lever Flatpak (AppImage manager; installs to `/home`)
- Cursor Agent worker user service (`agent worker start` against `CURSOR_WORKER_DIR`)
- Switch 2 wireless controllers (`~/code/switch2-controllers-linux` BLE → uinput bridge)
- Eden RetroDECK component + Tender wrap (huge Switch dumps skip RetroDECK and boot host Eden)
- RPCS3 player 1 bound to the current pad (not Steam Deck Controller)

Manual follow-ups (printed when needed):

- Tailscale / Headscale re-login (from `.env` values; no `--ssh` by default)
- Cursor `agent login` if the worker CLI is signed out
- Switch 2 controller pairing (hold Sync) and optional Decky plugin install (sudo into `~/homebrew/plugins`)
- Emu Pads Decky plugin (list/reorder/apply Cemu Azahar Eden) when `~/homebrew/plugins` is root-owned

Decky is only checked for files under `~/homebrew` (success if present; no reinstall reminder).

### Tailscale / Headscale re-login

When logged out, scripts print a command using your `.env`:

```bash
./deck-tailscale up \
  --login-server="$TAILSCALE_LOGIN_SERVER" \
  --operator="$TAILSCALE_OPERATOR" \
  --hostname="$TAILSCALE_HOSTNAME" \
  --accept-routes
```

Set `TAILSCALE_LOGIN_SERVER` (and related vars) in `.env` before relying on this.

## Scripts

| Script | Purpose |
|--------|---------|
| `bootstrap.sh` | Fresh machine setup |
| `post-update.sh` | Recovery after SteamOS update |
| `health-check.sh` | Status report with ✅/❌ + manual actions |
| `enable-wol.sh` | Apply Wake-on-LAN (used by `wol.service`) |
| `deck-tailscale` | Wrapper around `TAILSCALE_BIN` (default `/opt/tailscale/tailscale`) |
| `scripts/sunshine-watch.sh` | Pulse-ready oneshot: chmod Pulse dir, wait for PluginLoader, Decky start if GameStream is down |
| `scripts/sunshine-after-gamescope.sh` | After Game Mode: chmod Pulse, Decky-restart Sunshine so KMS binds to gamescope |
| `scripts/build-sunshine-ds.sh` | Build FanGoH Sunshine DS in Distrobox (does not replace Decky Sunshine) |
| `scripts/build-moonlight-ds.sh` | Build Moonlight DS debug APK (`com.fangoh.moonlight.debug`) |
| `scripts/test-sunshine-ds-desktop.sh` | Desktop dual-display smoke test for sunshine-ds (`:48100`) |
| `scripts/ensure-kwin-screencast.sh` | Last-resort: reinitialize KWin if desktop screenshots are all black |
| `scripts/run-cursor-agent-worker.sh` | Long-lived `agent worker start` for My Machines (systemd) |
| `scripts/ensure-cursor-agent.sh` | Cursor Agent worker user service |
| `scripts/ensure-switch2-controllers.sh` | Switch 2 BLE → uinput bridge (3.12 venv, user units, Steam BT scan off) |
| `scripts/ensure-eden-component.sh` | Eden in RetroDECK user slot; Tender wrap for Switch dumps over 6GiB (host AppImage `-f -g`, Engage 4GB pin) |
| `scripts/eden-from-retrodeck.sh` | Host-side Eden gamescope focus helper (overlay input, `-f`) |
| `scripts/bind-gamepad.py` | List pads; bind Cemu/Azahar/Eden (`status` / `apply --emu … --pads jsN,jsM`); `profile` prints `GAMESTREAM_PAD_PROFILE` |
| `scripts/ensure-emu-pads-decky.sh` | Install Decky **Emu Pads** (list/reorder/apply Cemu Azahar Eden). `~/homebrew/plugins` may need sudo |
| `decky/EmuPads/` | Emu Pads plugin source (`main.py` + `dist/index.js`) |
| `scripts/pad_profile.py` | GameStream pad profiles (`x360` default, `ds5`/`ds4`/`switch` for later gyro) |
| `scripts/ensure-cemu-dual-screen.sh` | Desktop GameStream Cemu: bind pad, write live HDMI/virtual geometry, KWin-place GamePad View |
| `scripts/ensure-cemu-gamemode-dual-screen.sh` | Game Mode `:48200` Cemu dual-screen (`checkpoint-2026-09-11-gamemode-tender-ds`): Tender tiles while streaming `--attach` GamePad from session `:1` onto `:2`; or Steam `RunGame` + `logs/cemu-gamemode-ds.want` (`CEMU_GAMEMODE_DS=1`, no `-f`), bind `--match Thor`, 15-button x360 map, `ffplay` `x11grab` onto `:2`. Exit `--quit`s immediately; leftover x11grab then `--paint` |
| `scripts/ensure-azahar-gamemode-dual-screen.sh` | Game Mode `:48200` Azahar: standalone Flatpak, SteamLaunch, `ffplay` `x11grab` Secondary Window onto `:2`. Tender 3DS Play while streaming execs this (not RetroDECK). `--attach` / leftover x11grab `--paint`. Manual pad `--match Odin`. |
| `scripts/ensure-azahar-dual-screen.sh` | Desktop GameStream Azahar: bind pad, Separate Windows, KWin-place 3DS top/bottom |
| `scripts/sunshine-app-cemu.sh` | Moonlight app wrapper: dual-screen Cemu, wait until Cemu exits |
| `scripts/sunshine-app-azahar.sh` | Moonlight app wrapper: dual-screen Azahar, wait until Azahar exits |
| `scripts/sunshine-app-stop.sh` | Kill leftover Cemu/Azahar after Moonlight Quit game (`azahar` or `cemu`) |
| `scripts/ensure-sunshine-ds-apps.sh` | Add those apps to sunshine-ds-dev `apps.json` (`:48100` only) and copy Cemu/Azahar Flatpak icons |
| `scripts/ensure-sunshine-ds.sh` | Start Distrobox + one Virtual-sunshine-ds helper + sunshine-ds (`:48100`). `--stop` tears down for Game Mode. `--install-shortcut` writes `~/Desktop/Return to Game Mode.desktop` without starting DS. `--restart` if idle. Not Decky `:47989`. |
| `scripts/switch-to-game-mode.sh` | Stop sunshine-ds + virtual output, set login mode to game, `steamosctl switch-to-game-mode`. Desktop icon: **Return to Game Mode**. |
| `scripts/ensure-sunshine-ds-gamemode.sh` | Isolated Game Mode KMS (`sunshine-ds-kms` host + RUNPATH, `:48200`). `--install-service` enables `steamos-sunshine-ds-gamemode.service` on `gamescope-session.target` (starts as `deck`; sudo is only `setcap`). `--start` also enables it. Does not touch `:48100` / `sunshine-ds-dev`. |
| `scripts/ensure-sunshine-ds-kms-setcap.sh` | Detect passwordless `setcap` for `sunshine-ds-kms` / `.new`. Drop-in must be `zzz-sunshine-ds-kms-setcap` (after `wheel`). Prints sudo lines after a SteamOS update. |
| `scripts/sunshine-ds-gamemode-virtual.sh` | Headless gamescope for Game Mode video/1 (`--start` / `--paint` idle screensaver clock on `:2`; sidecar `serial=` + `pw_node=`; `--smoke` / `--stop`). Not the KWin virtual-output helper. |
| `scripts/ensure-rpcs3-input.sh` | RPCS3 player 1 → current pad; Uncharted `--config` + `<iso>.yml` 1080p / flicker settings (01.10 Unlock FPS when that update is present) |
| `scripts/ensure-pcsx2-bios.sh` | PS2 BIOS via Tender `download_all_firmware` + pin USA 230 in `PCSX2.ini` |
| `scripts/eden-component/` | Eden launcher + ES-DE custom_systems templates |
| `scripts/ensure-*.sh` | Idempotent restore tasks |
| `scripts/check-*.sh` | Status / manual-action helpers |
| `.cursor/skills/sunshine-ds-gamemode/SKILL.md` | Game Mode `:48200` dual-stream checkpoint (`checkpoint-2026-09-11-gamemode-tender-ds`) |
| `AGENTS.md` | Conventions for coding agents |
| `rules_of_the_land.md` | Personal notes (gitignored) |

## Configuration

Copy `.env.example` to `.env`. Important variables:

| Variable | Purpose |
|----------|---------|
| `STEAMOS_NIC_INTERFACE` | Ethernet NIC for WOL |
| `TAILSCALE_LOGIN_SERVER` | Headscale (or Tailscale) login server URL |
| `TAILSCALE_HOSTNAME` | Hostname on the tailnet |
| `TAILSCALE_OPERATOR` | Operator user (usually `deck`) |
| `OPENRGB_FLATPAK_ID` | OpenRGB Flatpak id |
| `SUNSHINE_USER_SERVICE` | Sunshine systemd user unit (kept disabled; Decky starts the Flatpak) |
| `DECKY_LOADER_URL` | Decky PluginLoader URL used to call `start_sunshine` / `restart_sunshine` |
| `SUNSHINE_WATCH_PATH` | Fires when Pulse appears (chmod + start); not the Flatpak Sunshine unit |
| `SUNSHINE_AFTER_GAMESCOPE_SERVICE` | Restarts Sunshine via Decky after `gamescope-session` (KMS rebind) |
| `SUNSHINE_DS_KMS_SERVICE` | Game Mode `:48200` user unit (`WantedBy=gamescope-session.target`) |
| `GEARLEVER_FLATPAK_ID` | Gear Lever Flatpak id |
| `CURSOR_WORKER_DIR` | Folder the Cursor worker registers as its My Machines identity (default: this playbook). Must be a checkout of the repo you want to launch agents against. |
| `CURSOR_WORKER_EXTRA_DIRS` | Extra workspace roots, **space-separated** (paths with spaces are not supported). These are additional folders on the same worker, not extra repo registrations. |
| `CURSOR_WORKER_MGMT_ADDR` | Worker healthz listen address (default `127.0.0.1:18789`) |
| `CURSOR_WORKER_DATA_DIR` | Worker data dir (separate from the Cursor app's default lock) |
| `SWITCH2_CONTROLLERS_DIR` | Checkout of switch2-controllers-linux (default `~/code/switch2-controllers-linux`) |
| `GAMESTREAM_PAD_PROFILE` | sunshine-ds virtual pad: `x360` (default), later `ds5`/`ds4`/`switch` for gyro |
| `CEMU_PAD_MATCH` | Desktop GameStream Cemu pad substring (default `Thor`) |
| `CEMU_ROM` | Optional standalone Cemu ROM for dual-screen launch |
| `AZAHAR_PAD_MATCH` | Desktop GameStream Azahar pad substring (default `Thor`). Game Mode script defaults to `Odin`. |
| `AZAHAR_ROM` | Optional standalone Azahar ROM |

`CURSOR_WORKER_DIR` is the registered repo. Extra checkouts go in `CURSOR_WORKER_EXTRA_DIRS` as additional workspace roots (one line, paths separated by spaces):

```bash
CURSOR_WORKER_DIR=/home/deck/steamos-playbook
CURSOR_WORKER_EXTRA_DIRS=/home/deck/code
```

Then run `./scripts/ensure-cursor-agent.sh` so the worker restarts with the new roots.

`cursor-agent-worker.service` is a user systemd unit. It is not part of the Cursor AppImage and stays running when you quit the GUI. Confirm with:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user is-active cursor-agent-worker.service
curl -sf http://127.0.0.1:18789/healthz
```

## Sunshine DS / Moonlight DS

Sunshine DS source lives on https://github.com/FanGoH/Sunshine (`sunshine-ds-linux`). The playbook clones/builds/tests only. Production Decky Sunshine on `:47989` stays untouched; the side-by-side binary is `sunshine-ds` on **`:48100`**. Checkpoint SHAs: `.cursor/skills/sunshine-ds-gamestream/reference.md`.

Moonlight DS (https://github.com/FanGoH/moonlight-android `dual-display`) streams both displays. Build with `scripts/build-moonlight-ds.sh` (JDK 17 + Android SDK under `/home`). Pair the client to `HOST:48100`, not `:47989`.

## Manual checks

```bash
sudo systemctl status wol.service --no-pager
sudo ethtool "$STEAMOS_NIC_INTERFACE" | grep Wake-on
# Sunshine should NOT be enabled as a user unit (Decky starts it)
systemctl --user is-enabled app-dev.lizardbyte.app.Sunshine.service || true
systemctl --user is-enabled steamos-sunshine-watch.path
systemctl --user is-enabled steamos-sunshine-after-gamescope.service
systemctl --user is-enabled steamos-sunshine-ds-gamemode.service
systemctl --user status cursor-agent-worker.service --no-pager
systemctl --user status nso-gc.service --no-pager
curl -s http://127.0.0.1:47989/serverinfo
# Web UI login is checked by health-check.sh (Decky lastAuthHeader vs /api/apps)
```

Expected WOL: `Wake-on: g` (`active (exited)` is normal for the oneshot service).

If `systemctl --user` fails over SSH:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
```

## Legacy

- `run-after-update.sh` → use `post-update.sh`
- `health.sh` → use `health-check.sh`
