---
name: emu-save-mesh
description: >-
  Keep Eden and Azahar saves on this Steam Machine in the official Syncthing
  mesh with lab, Odin, and Thor, and keep Game Mode Azahar on a real copy of
  that tree. Use when the user mentions Syncthing, EdenSaves, AzaharSaves,
  a missing 3DS/Switch save, Ocarina of Time not showing in Game Mode, or
  ensure-syncthing.
---

# Emulator save mesh (Steam Machine)

Official Syncthing v2 (`~/.local/bin/syncthing`, user unit + linger). Restore with `scripts/ensure-syncthing.sh` from `post-update.sh`. Peer IDs live in gitignored `.env` (`SYNCTHING_PEER_IDS`). Do not commit API keys.

Do **not** use pacman syncthing, Syncthing GTK, or decky-syncthing as the daemon. Decky autostart must stay `no`.

Lab-wide device table, handheld ADB, and folder IDs: on lab, `~/.cursor/skills/emu-save-mesh/SKILL.md`.

## What Syncthing shares on this box

- **Eden:** NAND **profile UUID dir**  
  `~/.local/share/eden/nand/user/save/0000000000000000/<SYNCTHING_EDEN_PROFILE_UUID>`  
  not RetroDECK copies, not the parent `save/` tree.
- **Azahar:** standalone Flatpak inner sdmc  
  `~/.var/app/org.azahar_emu.Azahar/data/azahar-emu/sdmc/Nintendo 3DS/00000000000000000000000000000000/00000000000000000000000000000000`

`ignorePerms: true`. Azahar `caseSensitiveFS: false`. One game on one device; close the emulator after a session.

Title folder `00033500` is **Ocarina of Time 3D** (`0004000000033500`), not Super Mario 3D Land. Slots: `save00.bin` File 1, `save01.bin` File 2, `save02.bin` File 3.

## Three Azahar sdmc trees (do not collapse with a symlink)

| Tree | Path | Who reads it |
| --- | --- | --- |
| Standalone Flatpak (mesh + dual-screen) | `~/.var/app/org.azahar_emu.Azahar/data/azahar-emu/sdmc/` | Syncthing, GameStream Azahar |
| RetroDECK Game Mode / Tender | `~/retrodeck/saves/n3ds/azahar/sdmc/` | Tender Play in Game Mode |
| RetroDECK Flatpak fallback | `~/.var/app/net.retrodeck.retrodeck/data/azahar-emu/sdmc/` | Azahar if configured sdmc is unusable |

Ignore `~/retrodeck/saves/n3ds/Azahar` (capital A) and `~/retrodeck/saves/n3ds/*.zip` (RomM dumps, not in-game saves).

`ensure-syncthing.sh` rsyncs standalone sdmc → the RetroDECK path and the fallback (**copy**, no `--delete`), then pins RetroDECK `qt-config.ini` `sdmc_directory=/home/deck/retrodeck/saves/n3ds/azahar/sdmc/`.

### Never symlink across Flatpaks

Do **not** point `~/retrodeck/saves/n3ds/azahar/sdmc` at `~/.var/app/org.azahar_emu.Azahar/…`. RetroDECK cannot use another app’s data dir. Azahar rewrites `sdmc_directory` to the fallback and creates **empty** title folders (`system.dat` only). Game Mode then logs that `save00.bin` / `save02.bin` cannot be opened.

If that symlink exists: `rm` it, copy the meshed standalone tree onto a real directory, copy the same tree into the fallback, set `sdmc_directory` as above. `ensure-syncthing.sh` does this.

Do not share the RetroDECK path over Syncthing unless the user asks to move the mesh.

## Debug: handheld save missing in Game Mode

1. Hash `title/00040000/00033500/data/00000001/save*.bin` on the standalone tree (mesh) vs RetroDECK sdmc vs fallback.
2. Read the Game Mode Azahar log for `sdmc_directory` and which `save*.bin` it opened.
3. Empty title dir after a “fix” → cross-Flatpak symlink. Recover from the standalone/mesh tree, not from `sdmc.bak-*` unless hashes match.

## Dual-screen vs Game Mode

`.cursor/skills/azahar-dual-screen/SKILL.md` is standalone Flatpak only. Game Mode is RetroDECK `azahar-launcher`. They must keep separate sdmc copies.
