---
name: emu-save-mesh
description: >-
  Keep Eden, Azahar, Dusklight, Cemu, and PCSX2/NetherSX2 saves on this Steam Machine in the
  official Syncthing mesh with lab, Odin, and Thor. Use when the user mentions
  Syncthing, EdenSaves, AzaharSaves, Dusklight, Twilight Princess recomp, Cemu, Wind Waker HD, PCSX2, NetherSX2, Game Mode saves not reaching a handheld, or ensure-syncthing.
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
- **Dusklight:** memory-card saves only  
  `~/.local/share/TwilitRealm/Dusklight/USA/Card A`  
  (`01-GZ2E-gczelda2.gci`). Do **not** share `config.json`, logs, shaders, or `.controller` files.
- **Cemu:** user title saves only (`00050000`, not system `00050010`)  
  `~/retrodeck/saves/wiiu/cemu/00050000`  
  Standalone Flatpak `mlc_path` is RetroDECK `~/retrodeck/bios/cemu` (whose `usr/save` already symlinks at that RetroDECK saves dir).
- **PCSX2 / NetherSX2:** file memory cards only  
  `~/retrodeck/saves/ps2/pcsx2/memcards` (`Mcd001.ps2` / `Mcd002.ps2`). Do **not** share `~/retrodeck/bios/pcsx2/memcards` (that symlink is empty RetroArch LRPS2).

`ignorePerms: true`. Azahar/Cemu `caseSensitiveFS: false`. One game on one device; close the emulator after a session.

Title folder `00033500` is **Ocarina of Time 3D** (`0004000000033500`), not Super Mario 3D Land. Slots: `save00.bin` File 1, `save01.bin` File 2, `save02.bin` File 3.

Title folder `10143500` is **The Wind Waker HD**.

## One Azahar sdmc on this box

Game Mode, standalone Flatpak (dual-screen), and Syncthing all use **`~/retrodeck/saves/n3ds/azahar/sdmc`**. `ensure-syncthing.sh` sets both `qt-config.ini` `sdmc_directory`s there and `flatpak override --user --filesystem=/home/deck/retrodeck/saves/n3ds/azahar` because standalone Azahar ships `host:ro`.

Do **not** symlink `~/retrodeck/saves/n3ds/azahar/sdmc` into `~/.var/app/org.azahar_emu.Azahar/…`. RetroDECK cannot use another app’s data dir; Azahar then resets to `~/.var/app/net.retrodeck.retrodeck/data/azahar-emu/sdmc/` and creates empty title folders.

Ignore `~/retrodeck/saves/n3ds/Azahar` (capital A) and `~/retrodeck/saves/n3ds/*.zip` (RomM dumps, not in-game saves). Leftover files under `~/.var/app/org.azahar_emu.Azahar/data/azahar-emu/sdmc/` are **not** the mesh after unification.

## One Cemu mlc on this box

Game Mode, standalone Flatpak (dual-screen), and Syncthing all use **RetroDECK `bios/cemu` + `saves/wiiu/cemu`**. `ensure-syncthing.sh` pins both `settings.xml` `mlc_path`s to `/home/deck/retrodeck/bios/cemu` and `flatpak override --user --filesystem=/home/deck/retrodeck/bios/cemu --filesystem=/home/deck/retrodeck/saves/wiiu/cemu` because standalone Cemu ships `host:ro`.

Do **not** symlink `~/retrodeck/saves/wiiu/cemu` into `~/.var/app/info.cemu.Cemu/…`. Keep RetroDECK’s own `bios/cemu/usr/save` → `~/retrodeck/saves/wiiu/cemu` symlink. Leftover files under `~/.var/app/info.cemu.Cemu/data/Cemu/mlc01/usr/save/00050000` are **not** the mesh after unification. `ensure-cemu-dual-screen.sh` must not clear `mlc_path`.

## Debug

1. Syncthing folder path must be the RetroDECK inner `Nintendo 3DS/0000…/0000…` dir (Azahar) or `saves/wiiu/cemu/00050000` (Cemu).
2. Hash `title/00040000/00033500/data/00000001/save*.bin` on that path vs lab vs Thor.
3. Empty title dir after a “fix” → cross-Flatpak symlink. Recover from lab `/mnt/storage/syncthing/azahar-saves`.
4. If Game Mode saves still miss handhelds: Azahar rewrote `sdmc_directory` to the RetroDECK fallback — re-run `ensure-syncthing.sh`.
5. Dusklight on Android: `Android/data/dev.twilitrealm.dusk/files` is empty (scoped storage). Point **Settings → Data Folder** at `/storage/emulated/0/Sync/Dusklight` so Card A is the mesh. RetroArch Dolphin `*.gci` under `RetroArch/saves/` is a **different** save — do not mix it into Dusklight.
6. Cemu on Android cannot open `Sync/CemuMLC` (no all-files access). Syncthing watches Cemu’s default `Android/data/info.cemu.cemu/files/mlc01/usr/save/00050000`. Leave `mlc_path` empty. Do **not** share `00050010` or `system/`.
7. NetherSX2 (`xyz.aethersx2.android`) memcards are the same PCSX2 `Mcd001.ps2` files. Syncthing watches `Android/data/xyz.aethersx2.android/files/memcards`. Do not mix folder memcards.

## Tender vs Argosy vs this mesh

Tender launches RetroDECK (and host Eden/Dusklight). Argosy (`EmulatorRegistry.kt`) launches Android packages. The mesh only joins matching save trees.

Already meshed: Eden, Azahar, Cemu `00050000`, PCSX2 file memcards, Dusklight Card A.

Not meshed (do not invent folders):

- **NDS** — Tender has melonDS `.dsv` under `~/retrodeck/saves/nds`; handhelds have MelonDualDS. Confirm format before sharing.
- **PS Vita** — RetroDECK Vita3K + Argosy `vita3k`; Odin only, not Thor.
- **GameCube Dolphin** — Tender has Twilight Princess as NGC; Argosy lists Dolphin but the APK is not installed. Dusklight is a different save.
- **RPCS3** — Steam Machine only.
- **RetroArch cores** (GBA/GBC/NES/SNES/N64/PSX) — skip. DuckStation/PPSSPP APKs are not installed.

Argosy does **not** list Dusklight (`dev.twilitrealm.dusk`). Tender `save_sync_enabled` and Argosy RomM save sync can fight Syncthing on the same files — one game, one device.
