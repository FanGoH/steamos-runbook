---
name: emu-save-mesh
description: >-
  Keep Eden and Azahar saves on this Steam Machine in the official Syncthing
  mesh with lab, Odin, and Thor. Use when the user mentions Syncthing,
  EdenSaves, AzaharSaves, Game Mode saves not reaching a handheld, or
  ensure-syncthing.
---

# Emulator save mesh (Steam Machine)

Official Syncthing v2 (`~/.local/bin/syncthing`, user unit + linger). Restore with `scripts/ensure-syncthing.sh` from `post-update.sh`. Peer IDs live in gitignored `.env` (`SYNCTHING_PEER_IDS`). Do not commit API keys.

Do **not** use pacman syncthing, Syncthing GTK, or decky-syncthing as the daemon. Decky autostart must stay `no`.

Lab-wide device table and handheld ADB: on lab, `~/.cursor/skills/emu-save-mesh/SKILL.md`.

## What Syncthing shares on this box

- **Eden:** NAND **profile UUID dir**  
  `~/.local/share/eden/nand/user/save/0000000000000000/<SYNCTHING_EDEN_PROFILE_UUID>`  
  Host AppImage and Game Mode already write here, so they land on the mesh themselves.
- **Azahar:** Game Mode / Tender sdmc (same tree as dual-screen after the Flatpak override)  
  `~/retrodeck/saves/n3ds/azahar/sdmc/Nintendo 3DS/00000000000000000000000000000000/00000000000000000000000000000000`

`ignorePerms: true`. Azahar `caseSensitiveFS: false`. One game on one device; close the emulator after a session.

Title folder `00033500` is **Ocarina of Time 3D** (`0004000000033500`), not Super Mario 3D Land. Slots: `save00.bin` File 1, `save01.bin` File 2, `save02.bin` File 3.

## One Azahar sdmc on this box

Game Mode, standalone Flatpak (dual-screen), and Syncthing all use **`~/retrodeck/saves/n3ds/azahar/sdmc`**. `ensure-syncthing.sh` sets both `qt-config.ini` `sdmc_directory`s there and `flatpak override --user --filesystem=/home/deck/retrodeck/saves/n3ds/azahar` because standalone Azahar ships `host:ro`.

Do **not** symlink `~/retrodeck/saves/n3ds/azahar/sdmc` into `~/.var/app/org.azahar_emu.Azahar/…`. RetroDECK cannot use another app’s data dir; Azahar then resets to `~/.var/app/net.retrodeck.retrodeck/data/azahar-emu/sdmc/` and creates empty title folders.

Ignore `~/retrodeck/saves/n3ds/Azahar` (capital A) and `~/retrodeck/saves/n3ds/*.zip` (RomM dumps, not in-game saves). Leftover files under `~/.var/app/org.azahar_emu.Azahar/data/azahar-emu/sdmc/` are **not** the mesh after unification.

## Debug

1. Syncthing folder path must be the RetroDECK inner `Nintendo 3DS/0000…/0000…` dir.
2. Hash `title/00040000/00033500/data/00000001/save*.bin` on that path vs lab vs Thor.
3. Empty title dir after a “fix” → cross-Flatpak symlink. Recover from lab `/mnt/storage/syncthing/azahar-saves`.
4. If Game Mode saves still miss handhelds: Azahar rewrote `sdmc_directory` to the RetroDECK fallback — re-run `ensure-syncthing.sh`.
