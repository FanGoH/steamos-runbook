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

- Game Mode: Cemu works because it stays **inside** RetroDECK (`%EMULATOR_CEMU%` → `component_launcher.sh` under `reaper SteamLaunch`). ES-DE stays mapped on DISPLAY=:1; that window is Steam’s game identity. Overlay is `STEAM_OVERLAY=1` with `FOCUSED_APP=769` + `FOCUSED_APP_GFX=<game>`. Steam Exit kills the reaper tree. On each Cemu launch, bind player 0 in `controller0.xml` to the current joystick (same pick as Eden: physical Xbox, then Steam virtual, then Sunshine; skip ASRock LED). Steam Input wraps the held pad as `28de:11ff`; Sunshine injects a ghost `045e:02ea` even during local play, and Steam’s `IGNORE_DEVICES` hides that ID so a Sunshine bind shows as “not detected”. Do **not** inherit that list. Steam/Tender resolves `%EMULATOR_CEMU%` via bundled find-rules (`Cemu-wrapper` on PATH, then `/app/.../cemu`). Install the wrapper with `scripts/ensure-cemu-input.sh` (user-slot launcher + `flatpak override` PATH). Do **not** copy Cemu into the Flatpak `files/` dir. Force fullscreen on each launch (`-f` plus `settings.xml`). RPCS3 is the same PATH-wrapper trick: bundled linux `es_find_rules.xml` lists systempath `rpcs3` first, so `scripts/ensure-rpcs3-input.sh` installs `rpcs3` on RetroDECK PATH → user-slot launcher that rewrites `Default.yml` player 1 `Device` to the current **SDL3** pad name. RetroDECK RPCS3 lists Steam virtual `28de:11ff` as `Xbox One S Controller 1` when Sunshine `045e:02ea` is filtered out (GUID still `de28…ff11`). If Sunshine stays in `IGNORE_DEVICES_EXCEPT`, SDL3 keeps the string `Steam Virtual Gamepad 1` and RPCS3 loads an empty Sixaxis — never bind that name. Standalone AppImage saves live in `~/.config/rpcs3/.../savedata`; RetroDECK vfs is `~/retrodeck/saves/ps3/rpcs3`. `ensure-rpcs3-input.sh` moves leftover standalone save folders into that dest. USA Uncharted DF (`BCUS98103`) still lists saves as `BCES00065_NDI_UNCHARTED_DF_*` — alias the folder and patch `PARAM.SFO` `SAVEDATA_DIRECTORY` (same length) or Load shows zero entries. Per-game graphics go in `custom_configs/config_BCUS98103.yml` (Resolution Scale 150 = 1080p, Write Color/Depth Buffers, MSAA Disabled, Frame limit 60, VSync Full) — do **not** change global `config.yml`. Tender/ES-DE boots `rpcs3 --no-gui %ROM%`; that path does not reliably load `custom_configs/` on an ISO, so the wrapper must pass `--config` and write `<iso>.yml` next to the dump. Official Unlock FPS / Disable Motion Blur / DoF patches are PPU-hashed to disc **01.10**; this ISO is **01.00**, so Frame limit 60 still plays at 30 until that update. Do not invent 01.00 memory patches and do not raise Vblank (double-speed). Keep the emulated DualShock 3 / Sixaxis VID/PID `1356`/`616`. Do **not** copy RPCS3 into the Flatpak `files/` dir.

## Switch / Eden (this box)

Install Eden into RetroDECK’s **user** slot (`/var/data/retrodeck/external_components/eden/`) via `scripts/ensure-eden-component.sh` from `~/AppImages/eden.appimage`. Occupy `external_components/ryubing/` with the Eden shim: bundled linux `es_systems.xml` still lists `%EMULATOR_RYUBING%` first, and `run_game.sh` (Steam/Tender shortcuts without `-e`) uses that file, not `custom_systems`. ES-DE UI must use `%EMULATOR_EDEN%` — **not** `%EMULATOR_FLATPAK-SPAWN% --host`. Do **not** use [iAbuser/RetroInjector](https://github.com/iAbuser/RetroInjector). Do **not** copy Eden into the Flatpak `files/` dir. A Switch `.m3u` is unused (Tender/ES-DE ignore it; Eden applies sibling update NSPs). If `%ROM%` is a folder, recurse for the largest `.xci`, then the largest non-DLC `.nsp` — not a `.rar`. `ensure-eden-component.sh` also symlinks `~/retrodeck/roms/switch/*/` into `~/emulation/switch/games/` (no copy). Tender plugin updates overwrite `rom-launcher`; re-run `ensure-eden-component.sh` (also from `post-update.sh`).

**Every Eden launch** (in-sandbox and host): bind player 0 to the current joystick (physical Xbox `045e:*` that is not Sunshine, then Switch Pro, then Steam virtual `28de:11ff`, then Sunshine; skip ASRock LED). Do **not** inherit Steam’s `SDL_GAMECONTROLLER_IGNORE_DEVICES`. Use `ALLOW_STEAM_VIRTUAL_GAMEPAD=1`, hidapi off, `IGNORE_DEVICES_EXCEPT` for Steam virtual + Xbox + Switch Pro, `enable_joycon_driver=false`. If no pad is present yet, keep the last GUID. Keep **borderless** (`fullscreen_mode=0`, `fullscreen=true`), hide the status bar (`showStatusBar=false`), and pass `-f` on Eden launches. Exclusive+gamescope is still the Launching hang — do **not** set `fullscreen_mode=1`. If `%ROM%` is a folder, recurse for the largest `.xci` (then largest non-DLC `.nsp`); never launch a `.rar`. Empty Steam `LaunchOptions` (Xenoblade, Luigi) means the tile runs `rom-launcher` with no args — do **not** rely on rewriting `shortcuts.vdf` while Game Mode is running (Steam overwrites it). The wrap recovers `SteamAppId` / `SteamGameId` (shortcut ids are often `appid << 32`) → `shortcuts.vdf` AppName → `~/retrodeck/roms/switch/<name>/` via `set-steam-launch-options.py --rom-for-appid`. Dump over 6GiB still skips RetroDECK (`eden.appimage -f -g`); smaller dumps stay in-sandbox. `scripts/eden-from-retrodeck.sh` can reclaim gamescope focus / overlay on a host Eden window. Tender **Play is a no-op** when `rom_installs.launchable=0` (Luigi was a `.rar`; Xenosaga Episode I was a `.zip` of an `.iso`). Stash leftover archives and set `launchable=1` plus `applied_launch_options` (`--repair-tender`). PS2 launch is `%EMULATOR_PCSX2% -batch %ROM%`. PCSX2 needs a PS2 BIOS in `~/retrodeck/bios` (`Filenames BIOS=` in `PCSX2.ini`); PS1 `scph*.bin` files do not count. Pull BIOS through Tender’s firmware backend (`scripts/ensure-pcsx2-bios.sh` → Decky `Tender.download_all_firmware("ps2")`). Registry marks every PS2 BIOS `required: false`, so `download_required_firmware` is a no-op. Do **not** raw-curl RomM `/api/firmware/…/content` (403 without Tender’s token/User-Agent). Pin USA v2.30 `ps2-0230a-20080220.bin`. `~/retrodeck/bios/pcsx2/bios` is RetroDECK’s symlink back to `~/retrodeck/bios` — leave it so Tender dest paths land in the folder PCSX2 scans. Astral Chain 60fps is `load/01007300020FA000/Static-60fps/exefs/*.pchtxt` for **v1.0.1** (`@nsobid`); `exefs/exeFS/` nesting hides the patch and a 1.0.0 boot greys it out. Luigi 60fps is Atmosphere `exefs_patches/LM360FPS/*.ips` next to the dump — Eden does **not** read that. `patch-eden-input.py --ensure-fps-mods` copies it to `load/0100DCA0064A6000/LM360FPS/exefs/` (1.4.0 main build `79E5950F…`). Xenoblade `60-30fps` pchtxt is already under `load/010074F013262000/` (this dump’s title ID).

**RAM / earlyoom — do not rediscover.** RetroDECK does **not** memcpy the cart; Flatpak bind-mounts the same inode. A symlink of the `.xci` is the same file and does not lower RSS. RSS is Eden guest DRAM plus the cart working set. `memory_layout_mode`: `0` = 4GB, `1` = 6GB, `2` = 8GB. Global default is **8GB**. A per-game 4GB value is ignored while `use_global=true`. Swap is already 7.3G zram + 1G file; zram is compressed RAM, not a free dump buffer. Growing the swapfile needs root. Steam games often have `oom_score_adj` 900. Eden `-g` is the same `BootGame` as clicking the library list, but it runs in the MainWindow constructor **before** `show()` — that is why Steam sits on Launching. Eden is a plain `QApplication` (not single-instance); a second `eden -g` starts a second process, it does not forward into the open UI.

**Proven Engage Steam shortcut (2026-09-02):** skip RetroDECK, pin 4GB on `~/.config/eden/custom/0100A6301214E000.ini` (`use_global=false`, `memory_layout_mode=0`), exec `~/AppImages/eden.appimage -f -g <Engage.xci>`. Log: `Host OS: SteamOS`, `Core.memory_layout_mode: Memory_4Gb`, `Booting game: 0100A6301214E000 | Fire Emblem Engage | 2.0.0`. Earlier kills: in-sandbox `-g` ~12 GB RSS; `flatpak-spawn --host` still left the KDE Flatpak resident; host `-g` with **8GB** layout ~14 GB RSS and swap 0.

**Scope — not all Eden games.** The host AppImage `-f -g` wrap is for Switch dumps **over 6GiB** (MK8 ~6.77G, 13 Sentinels ~7.5G, Engage ~15G). The 4GB pin is **Engage’s** custom ini only; MK8 must stay **8GB / 64-bit** (`--pin-4gb` forced 32-bit and crashed). Do **not** apply 4GB globally. Do **not** re-test `eden -g` on the 15G Engage cart with the 8GB layout (earlyoom SIGTERMs the box).

## Automation vs manual

**Auto when possible** (`ensure-*.sh` from `post-update.sh`):

- pacman keyrings (`archlinux` + `holo`) via `ensure-pacman.sh`
- `sshd`, WOL (`wol.service` → `enable-wol.sh`)
- OpenRGB udev rules from Flatpak + user service + SDK device rescan (DIMMs often need UI "Rescan devices" otherwise)
- Sunshine: disable Flatpak user-unit autostart; Decky Sunshine is the only starter (same Flatpak install). Make `$XDG_RUNTIME_DIR/pulse` mode 755 so Decky's setuid bwrap can bind-mount the socket (the boot EACCES). `steamos-sunshine-watch.path` runs that chmod when Pulse appears and starts Sunshine via Decky if GameStream is still down. Wait for PluginLoader on `:1337` before `start_sunshine` so a Pulse-ready oneshot does not fail in milliseconds and hit systemd start-limit. `Restart=on-failure` on the oneshot covers leftover races. Call Decky with `loader/call_plugin_method` and snake_case names (`api_version` 1); the legacy kwargs route is rejected. `steamos-sunshine-after-gamescope.service` Decky-restarts Sunshine when `gamescope-session` starts so KMS rebinds after Desktop (KWin leaves Moonlight hanging on 503 / no monitor 0). Do **not** enable the Flatpak systemd user unit; do **not** `/api/restart`; do **not** poll every N minutes. Clear stale `SUNSHINE_SERVER_BUSY` with `POST /api/apps/close`. Logs: `logs/sunshine-watch.log`.
- Gear Lever Flatpak (AppImage manager on `/home`)
- Cemu player 0 → current pad (`ensure-cemu-input.sh`: user-slot wrapper + `Cemu-wrapper` on RetroDECK PATH)
- Desktop/GameStream Cemu: `scripts/bind-gamepad.py` (`list` / `cemu --match Thor` / `cemu --wait` / `profile`) then `scripts/ensure-cemu-dual-screen.sh` (live kscreen sizes; KWin-place TV on HDMI + GamePad View on Virtual-sunshine-ds). Moonlight app **Cemu Dual-Screen** (`scripts/sunshine-app-cemu.sh`, installed by `ensure-sunshine-ds-apps.sh` into sunshine-ds-dev `apps.json` only). Dual-screen has no chrome; Moonlight **Quit game** (or `scripts/sunshine-app-stop.sh cemu`) stops `Cemu_relwithdeb` / `Cemu-wrapper`. Pad type is `GAMESTREAM_PAD_PROFILE` in `.env` (`scripts/pad_profile.py`, default `x360`). Do not switch to `ds5`/`ds4`/`switch` without rebinding — those expose Thor/Odin gyro but change VID/PID and break Steam Guide. Skills `.cursor/skills/bind-controller/SKILL.md` and `.cursor/skills/cemu-dual-screen/SKILL.md`. Cemu `set_mapping` is last-write-wins: mappings only on the named Sunshine pad; Steam wrap may stay listed with empty mappings. Do not hand-edit `controller0.xml`. Do not reorder Sunshine first while Steam still has mappings. Optional `.env` `CEMU_ROM` / `CEMU_PAD_MATCH` (default Thor). Flatpak process `comm` is `Cemu_relwithdeb`.
- Desktop/GameStream Azahar (3DS): `scripts/bind-gamepad.py azahar --match Thor` then `scripts/ensure-azahar-dual-screen.sh`. Moonlight app **Azahar Dual-Screen** (`scripts/sunshine-app-azahar.sh`). Open shows an HDMI game list (`scripts/azahar-game-picker.py`, `AZAHAR_GAMES_DIR`) while prep runs, then launches the chosen ROM. Dual-screen windows have no chrome; 3DS Home does not quit Azahar. Moonlight overlay **Quit game** (or `scripts/sunshine-app-stop.sh azahar`) stops the process. Standalone Flatpak `org.azahar_emu.Azahar` (not RetroDECK `azahar-launcher`). Separate Windows (`layout_option=4`), bottom screen in the secondary window (`secondary_display_layout=2`), `screen_bottom_stretch` / `screen_top_stretch` true so 4:3 does not only fill 1920×1080 by height. Launch `QT_QPA_PLATFORM=xcb` — Qt Wayland dies on `drm_syncobj`. KWin-place caption `Primary Window` → HDMI, `Secondary Window` → Virtual-sunshine-ds; minimize the library window. Skill `.cursor/skills/azahar-dual-screen/SKILL.md`. Optional `.env` `AZAHAR_ROM` / `AZAHAR_PAD_MATCH` / `AZAHAR_GAMES_DIR`.
- RPCS3 player 1 → current pad (`ensure-rpcs3-input.sh`: user-slot wrapper + `rpcs3` on RetroDECK PATH; Device is the **SDL3** name, emulated Sixaxis VID/PID stays). RetroDECK RPCS3 hides Steam virtual `28de:11ff` unless `SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1` is in the environment (SetHint is not enough). Bind `Xbox One S Controller 1`, not `Steam Virtual Gamepad 1`. Null players 2–7. Do not bind Sunshine’s ghost Xbox as player 1 during local play. Same script writes Uncharted’s per-game `custom_configs/config_BCUS98103.yml` (1080p scale, Write Color/Depth Buffers, MSAA off, 60 fps cap), an `<iso>.yml` sidecar, and `--config` on `--no-gui` ISO boots. Official 01.10 patches are enabled; this dump is 01.00 so the game stays 30 fps until that update.
- PS2 BIOS via Tender (`ensure-pcsx2-bios.sh`: Decky `download_all_firmware("ps2")` + pin USA 230 in `PCSX2.ini`)
- Eden user slot + Tender `rom-launcher` wrap (`ensure-eden-component.sh`: host AppImage `-f -g` for Switch dumps over 6GiB, 4GB pin on Engage only, library symlinks)
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
- Repetitive host tasks get a script; agent skills and slash commands point at that script instead of hand-editing config
- Exit `0` OK, `2` for “needs manual / warn”, other non-zero for hard failure
- NIC, Headscale URL, hostname, Flatpak IDs come from `.env` — no personal URLs or hostnames as code defaults
- `TAILSCALE_LOGIN_SERVER` must be set in `.env` (no hardcoded Headscale URL in repo)

## Docs split

| File | Commit? | Contents |
|------|---------|----------|
| `AGENTS.md` | yes | This file — general agent/playbook behavior, including the proven Switch/Eden Game Mode recipe |
| `README.md` | yes | Public setup/recovery docs (no personal infra) |
| `rules_of_the_land.md` | **no** (gitignored) | Personal hostname, hardware, LAN, Headscale URL, incident notes |
| `.env` | **no** (gitignored) | Real `TAILSCALE_LOGIN_SERVER`, NIC, etc. |
| `.env.example` | yes | Placeholders only |
