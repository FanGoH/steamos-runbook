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
- Eden RetroDECK component + Tender wrap (huge Switch dumps skip RetroDECK and boot host Eden)
- RPCS3 player 1 bound to the current pad (not Steam Deck Controller)

Manual follow-ups (printed when needed):

- Tailscale / Headscale re-login (from `.env` values; no `--ssh` by default)
- Cursor `agent login` if the worker CLI is signed out

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
| `scripts/run-cursor-agent-worker.sh` | Long-lived `agent worker start` for My Machines (systemd) |
| `scripts/ensure-eden-component.sh` | Eden in RetroDECK user slot; Tender wrap for Switch dumps over 8GiB (host AppImage `-f -g`, Engage 4GB pin) |
| `scripts/ensure-rpcs3-input.sh` | RPCS3 player 1 → current pad (`rpcs3` on RetroDECK PATH; Uncharted Sixaxis) |
| `scripts/eden-component/` | Eden launcher + ES-DE custom_systems templates |
| `scripts/ensure-*.sh` | Idempotent restore tasks |
| `scripts/check-*.sh` | Status / manual-action helpers |
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
| `DECKY_LOADER_URL` | Decky PluginLoader URL used to call `startSunshine` when GameStream is down |
| `SUNSHINE_WATCH_PATH` | Fires when Pulse appears (chmod + start); not the Flatpak Sunshine unit |
| `GEARLEVER_FLATPAK_ID` | Gear Lever Flatpak id |
| `CURSOR_WORKER_DIR` | Folder the Cursor worker registers as its My Machines identity (default: this playbook). Must be a checkout of the repo you want to launch agents against. |
| `CURSOR_WORKER_EXTRA_DIRS` | Extra workspace roots, **space-separated** (paths with spaces are not supported). These are additional folders on the same worker, not extra repo registrations. |
| `CURSOR_WORKER_MGMT_ADDR` | Worker healthz listen address (default `127.0.0.1:18789`) |
| `CURSOR_WORKER_DATA_DIR` | Worker data dir (separate from the Cursor app's default lock) |

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

## Manual checks

```bash
sudo systemctl status wol.service --no-pager
sudo ethtool "$STEAMOS_NIC_INTERFACE" | grep Wake-on
# Sunshine should NOT be enabled as a user unit (Decky starts it)
systemctl --user is-enabled app-dev.lizardbyte.app.Sunshine.service || true
systemctl --user is-enabled steamos-sunshine-watch.path
systemctl --user status cursor-agent-worker.service --no-pager
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
