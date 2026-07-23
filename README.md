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
./health-check.sh
```

`post-update.sh` restores when needed:

- pacman keyrings (`archlinux` + `holo`)
- `sshd`
- `wol.service` / Wake-on-LAN on `STEAMOS_NIC_INTERFACE`
- OpenRGB udev rules + user service
- Sunshine user service
- Gear Lever Flatpak (AppImage manager; installs to `/home`)

Manual follow-ups (printed when needed):

- Tailscale / Headscale re-login (from `.env` values; no `--ssh` by default)
- Decky Loader reinstall if the Game Mode menu is missing

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
| `SUNSHINE_USER_SERVICE` | Sunshine systemd user unit |
| `GEARLEVER_FLATPAK_ID` | Gear Lever Flatpak id |

## Manual checks

```bash
sudo systemctl status wol.service --no-pager
sudo ethtool "$STEAMOS_NIC_INTERFACE" | grep Wake-on
systemctl --user list-unit-files | grep -i sunshine
```

Expected WOL: `Wake-on: g` (`active (exited)` is normal for the oneshot service).

If `systemctl --user` fails over SSH:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
```

## Legacy

- `run-after-update.sh` → use `post-update.sh`
- `health.sh` → use `health-check.sh`
