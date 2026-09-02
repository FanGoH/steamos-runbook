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

- Game Mode: Cemu works because it stays **inside** RetroDECK (`%EMULATOR_CEMU%` → `component_launcher.sh` under `reaper SteamLaunch`). ES-DE stays mapped on DISPLAY=:1; that window is Steam’s game identity. Overlay is `STEAM_OVERLAY=1` with `FOCUSED_APP=769` + `FOCUSED_APP_GFX=<game>`. Steam Exit kills the reaper tree. On each Cemu launch, bind player 0 in `controller0.xml` to the current joystick (same pick as Eden: physical Xbox, then Steam virtual, then Sunshine; skip ASRock LED). Steam Input wraps the held pad as `28de:11ff`; Sunshine injects a ghost `045e:02ea` even during local play, and Steam’s `IGNORE_DEVICES` hides that ID so a Sunshine bind shows as “not detected”. Do **not** inherit that list. Steam/Tender resolves `%EMULATOR_CEMU%` via bundled find-rules (`Cemu-wrapper` on PATH, then `/app/.../cemu`). Install the wrapper with `scripts/ensure-cemu-input.sh` (user-slot launcher + `flatpak override` PATH). Do **not** copy Cemu into the Flatpak `files/` dir.
- Switch on this box: install Eden into RetroDECK’s **user** slot (`/var/data/retrodeck/external_components/eden/`) via `scripts/ensure-eden-component.sh`, and a shim at `external_components/ryubing/` because bundled linux `es_systems.xml` still lists `%EMULATOR_RYUBING%` first and `run_game.sh` (Steam/Tender shortcuts without `-e`) uses that file, not `custom_systems`. Do **not** use [iAbuser/RetroInjector](https://github.com/iAbuser/RetroInjector). ES-DE UI must use `%EMULATOR_EDEN%` — **not** `%EMULATOR_FLATPAK-SPAWN% --host`. On each Eden launch, bind player 0 to the current joystick (prefer physical Xbox `045e:*` that is not Sunshine, then Switch Pro, then Steam virtual `28de:11ff`, then Sunshine; skip ASRock LED). Do **not** inherit Steam’s `SDL_GAMECONTROLLER_IGNORE_DEVICES`. Use `ALLOW_STEAM_VIRTUAL_GAMEPAD=1`, hidapi off, `IGNORE_DEVICES_EXCEPT` for Steam virtual + Xbox + Switch Pro, `enable_joycon_driver=false`. If no pad is present yet, keep the last GUID.

## Automation vs manual

**Auto when possible** (`ensure-*.sh` from `post-update.sh`):

- pacman keyrings (`archlinux` + `holo`) via `ensure-pacman.sh`
- `sshd`, WOL (`wol.service` → `enable-wol.sh`)
- OpenRGB udev rules from Flatpak + user service + SDK device rescan (DIMMs often need UI "Rescan devices" otherwise)
- Sunshine: disable Flatpak user-unit autostart; Decky Sunshine is the only starter (same Flatpak install). Make `$XDG_RUNTIME_DIR/pulse` mode 755 so Decky's setuid bwrap can bind-mount the socket (the boot EACCES). `steamos-sunshine-watch.path` runs that chmod when Pulse appears and starts Sunshine via Decky if GameStream is still down. Wait for PluginLoader on `:1337` before `startSunshine` so a Pulse-ready oneshot does not fail in milliseconds and hit systemd start-limit. `Restart=on-failure` on the oneshot covers leftover races. Do **not** enable the Flatpak systemd user unit; do **not** `/api/restart`; do **not** poll every N minutes. Clear stale `SUNSHINE_SERVER_BUSY` with `POST /api/apps/close`. Logs: `logs/sunshine-watch.log`.
- Gear Lever Flatpak (AppImage manager on `/home`)
- Cemu player 0 → current pad (`ensure-cemu-input.sh`: user-slot wrapper + `Cemu-wrapper` on RetroDECK PATH)
- Cursor Agent worker user service (`agent worker start` on `CURSOR_WORKER_DIR` plus `CURSOR_WORKER_EXTRA_DIRS`; login is manual). Separate data dir so it does not fight an on-demand session worker.

**Manual only** (detect + print exact commands via `record_manual`):

- Tailscale / Headscale re-login (do **not** auto-login; do **not** add `--ssh` unless explicitly requested)
- Cursor `agent login` if the worker CLI is signed out (do **not** put API keys in the repo)

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
