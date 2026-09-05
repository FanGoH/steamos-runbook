# Agent notes for steamos-playbook

Guidance for coding agents working in this repo. Personal machine details belong in
gitignored `rules_of_the_land.md`, not here.

## Architecture

- Independent, idempotent task scripts under `scripts/`
- Top-level orchestration: `bootstrap.sh` (fresh setup), `post-update.sh` (after SteamOS update), `health-check.sh` (status)
- Shared helpers in `scripts/common.sh` (`load_env`, `record_manual`, pacman/readonly helpers)
- Configuration via `.env` (gitignored); ship placeholders in `.env.example`
- Prefer checks before writes; safe to re-run

## SteamOS realities

- Updates can reset host state while keeping `/home/deck` (udev rules, enabled user services, pacman keyrings, packages on `/`)
- Root filesystem is small (~5G); prefer Flatpaks/`--user` installs over large AUR/pacman packages on `/`
- Do not use `sudo systemctl --user` (missing user bus). Over SSH:

  ```bash
  export XDG_RUNTIME_DIR=/run/user/$(id -u)
  ```

## Automation vs manual

**Auto when possible** (`ensure-*.sh` from `post-update.sh`):

- pacman keyrings (`archlinux` + `holo`) via `ensure-pacman.sh`
- `sshd`, WOL (`wol.service` → `enable-wol.sh`)
- OpenRGB udev rules from Flatpak + user service + SDK device rescan (DIMMs often need UI "Rescan devices" otherwise)
- Sunshine: disable Flatpak user-unit autostart; Decky Sunshine is the only starter (same Flatpak install). Make `$XDG_RUNTIME_DIR/pulse` mode 755 so Decky's setuid bwrap can bind-mount the socket (the boot EACCES). `steamos-sunshine-watch.path` runs that chmod when Pulse appears and starts Sunshine via Decky if GameStream is still down. Wait for PluginLoader on `:1337` before `startSunshine` so a Pulse-ready oneshot does not fail in milliseconds and hit systemd start-limit. `Restart=on-failure` on the oneshot covers leftover races. Do **not** enable the Flatpak systemd user unit; do **not** `/api/restart`; do **not** poll every N minutes. Clear stale `SUNSHINE_SERVER_BUSY` with `POST /api/apps/close`. Logs: `logs/sunshine-watch.log`.
- Gear Lever Flatpak (AppImage manager on `/home`)
- Cursor Agent worker user service (`agent worker start` on `CURSOR_WORKER_DIR` plus `CURSOR_WORKER_EXTRA_DIRS`; login is manual). Separate data dir so it does not fight an on-demand session worker.
- Switch 2 controllers (`ensure-switch2-controllers.sh`): user-space BLE → uinput bridge from `SWITCH2_CONTROLLERS_DIR` (default `~/code/switch2-controllers-linux`). Python 3.12 venv via uv (Steam OS 3.9 is 3.14). Steam Bluetooth.Enabled stays off; BlueZ adapter is powered. Game Mode hook is `gamescope-session.service`. Pairing is manual. Do **not** install the Bazzite Eden reorder hooks (playbook owns Eden/Cemu/RPCS3 binds).

**Manual only** (detect + print exact commands via `record_manual`):

- Tailscale / Headscale re-login (do **not** auto-login; do **not** add `--ssh` unless explicitly requested)
- Cursor `agent login` if the worker CLI is signed out (do **not** put API keys in the repo)
- Switch 2 controller pairing (`python -m ngc pair` / Decky plugin; hold Sync). Decky plugin copy into `~/homebrew/plugins` needs sudo when that dir is root-owned.

**Light checks** (no reinstall nag):

- Decky: success if `~/homebrew` / PluginLoader files exist; optional warn if missing

## Script conventions

- Small focused scripts; orchestrators collect `MANUAL_ACTIONS_FILE` and print a summary
- Exit `0` OK, `2` for “needs manual / warn”, other non-zero for hard failure
- NIC, Headscale URL, hostname, Flatpak IDs come from `.env` — no personal URLs or hostnames as code defaults
- `TAILSCALE_LOGIN_SERVER` must be set in `.env` (no hardcoded Headscale URL in repo)

## Docs split

| File | Commit? | Contents |
|------|---------|----------|
| `AGENTS.md` | yes | This file — general agent/playbook behavior |
| `README.md` | yes | Public setup/recovery docs (no personal infra) |
| `rules_of_the_land.md` | **no** (gitignored) | Personal hostname, hardware, LAN, Headscale URL, incident notes |
| `.env` | **no** (gitignored) | Real `TAILSCALE_LOGIN_SERVER`, NIC, etc. |
| `.env.example` | yes | Placeholders only |
