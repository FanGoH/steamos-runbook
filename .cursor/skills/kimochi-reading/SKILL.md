---
name: kimochi-reading
description: >-
  Use Kimochi on this Steam Machine without the broken Game Mode radial,
  and the daily 20:00 check for a new Kimochi build / GitHub #165.
  Use when the user mentions Kimochi, Trails from Zero reading, AnkiConnect
  18765, controller pie flash, or the 8pm Kimochi watchdog.
---

# Kimochi reading (Steam Machine)

**Host:** `steammachine` / `gpc`. **Do not wrap Kimochi. Do not SIGSTOP Steam. Do not rewrite `GAMESCOPECTRL_BASELAYER_APPID` / `GAMESCOPE_FOCUSED_APP`. Do not rebuild Kimochi. Do not switch Desktop ↔ Game Mode unless the user asks.**

Installed **0.9.0** (2026-11-14). AnkiConnect is headless `http://127.0.0.1:18765/` (`anki-connect.service`). Port **8765** is Decky Clipboard — never point Kimochi there.

## Locked facts (do not rediscover)

| Item | Value |
|------|--------|
| Game Mode tile | Steam non-Steam **Kimochi**, `AppId=4060279609`, vendor `~/.local/share/kimochi/gaming-mode/launch.sh` |
| Desktop app | `~/.local/share/kimochi/Kimochi.AppImage` (or the same tile if Steam is in Desktop) |
| Settings / logs | `~/.local/share/dev.kimochi.app/settings.json`, `evidence.jsonl` |
| Trails | Steam `1668510`, Proton `zero.exe`. Source id looks like `gamescope:window:1668510:<pid>` |
| Radial in Game Mode | **Broken.** `openControllerMenu` then `controller-cancelled` `focus-elsewhere` in ~30ms. Same as [hamstu/kimochi#165](https://github.com/hamstu/kimochi/issues/165). Overlay `STEAM_INPUT_FOCUS` does **not** fix it (tried; Kimochi writes `0` back). |
| Radial on Plasma | Opens. Pad still reaches the game. Docs: pick a chord the game does not use, or **Shift+F9**. |
| Guide / QAM | Works on vendor Kimochi. A leftover wrap + `kimochi-input` watchdog SIGSTOP'd Steam — **never revive that.** |
| Text hooker | Already on for Trails (`textHookerGames` → `zero.exe`). The **card still works** in Game Mode (#165). That is the reading path. |
| Primary pad | In Kimochi **Settings → Shortcuts & Controls → Connected gamepads → Set as primary** the row that lights on **Button test** (Odin = `Sunshine (libvirtualhid) Odin2_Portal`). Do not trust kernel `js*` indexes (ASRock / EmuPads shift them). |

Failed host experiments (do **not** rerun unless the user names them): wrap `launch.sh`, SIGSTOP Steam, `STEAM_INPUT_FOCUS` sidecar `scripts/kimochi-overlay-input-focus.py`.

---

## How to use it (human)

Use **Game Mode** for Trails. Ignore LS+RS / R4.

### Once per session

1. Moonlight to this host **`:48200`** if you are on Odin/Thor. Confirm the pad moves Steam.
2. **Library → Kimochi.** Wait for the Game Mode Source tab (three columns). Do not start Trails first.
3. **Settings → Shortcuts & Controls:** gamepad on; **Set as primary** the pad that lights in Button test.
4. Confirm **Settings → Text Hooker** (or Super Texthooker) Anki URL is `http://127.0.0.1:18765`. Scan after a button press can stay off.
5. **Steam → Trails from Zero** → start. When you are in-game, **Steam → Kimochi**.
6. Source tab: select **The Legend of Heroes: Trails from Zero**. Crop only if menus pollute OCR; hook does not need a crop.
7. Leave **Text Hooker** on. Optional: **Auto OCR** on if you also want overlay boxes (not required for hook).
8. **Steam → Trails.** Play.

### Reading (no radial)

- Dialogue should fill the **Text Hooker card** and **Log** while Trails is front. You do not need LS+RS.
- **Lookup / Anki:** **Steam → Kimochi** → tap the line/word in the Log or card → Add to Anki. Then **Steam → Trails**.
- **Scan now** on the Source tab if hook missed a line (OCR). Same switch back.
- **Do not** click both sticks (LS+RS) or expect R4. The pie flashes and dies (`focus-elsewhere`).
- **Guide / hold-Select / QAM (`...`)** are fine. If Steam ever freezes after a Kimochi experiment, that is SIGSTOP — `kill -CONT` the `steam` PIDs; do not mash Guide.

### Desktop (only if you are already on Plasma)

1. Start Kimochi as a desktop app (not the Game Mode `launch.sh` path — that needs `gamescope-0`).
2. Start Trails. Source = the Trails **window** (not a leftover `gamescope:window:…`).
3. Overlay on. **LS+RS** or **Shift+F9** opens the pie. The game **still gets the pad** — pick a chord Trails ignores, or use the keyboard shortcut.
4. “Click through text to the game” is **mouse** only.

---

## Daily 20:00 cloud-agent check

**Schedule:** every day **20:00 America/Chicago** (`0 20 * * *`, DST follows Chicago). Attach this skill. Prompt (paste):

```text
Read .cursor/skills/kimochi-reading/SKILL.md and run only the daily 20:00 check.
Do not patch Kimochi, wrap launch.sh, SIGSTOP Steam, or switch Desktop/Game Mode.
Report and stop.
```

### Do

1. Read this skill. Do not expand into dual-stream / EmuPads / Sunshine work.
2. **Version:** `lastSeenVersion` in `~/.local/share/dev.kimochi.app/settings.json` vs latest GitHub release `hamstu/kimochi` (and `https://docs.kimochiapp.com/changelog/` if the tag is newer).
3. **#165:** open/closed, new comments, linked PR/commit. If closed or a release notes “controller overlay” / gamescope pie: say **try Game Mode LS+RS tomorrow** — still do not patch.
4. **Live box (read-only):**
   - `pgrep -x gamescope-wl` / `pgrep -x kimochi` / `pgrep -x zero.exe` (never `pgrep -f` sunshine).
   - If `evidence.jsonl` grew today: count `openControllerMenu` vs `controller-cancelled` `focus-elsewhere`.
   - `curl -sS -m 2 -X POST http://127.0.0.1:18765 -H 'Content-Type: application/json' -d '{"action":"deckNames","version":6}'`
5. Write a short report: version local vs latest, #165 state, whether the pie is still cancelling if they used it, AnkiConnect ok/fail. **Stop.**

### Do not

- Wrap or restore a playbook `launch.sh` overlay, `steamos-kimochi-overlay.service`, or `kimochi-overlay-input-focus.py` unless the day’s user message names that file.
- `SIGSTOP` / `SIGCONT` Steam except if Steam is already `T` (stopped) **and** the user is stuck; then `kill -CONT` only, and say so.
- `steamos-session-select`, Game Mode ↔ Desktop, reboot, or shutdown.
- Rebuild Kimochi, Distrobox rust, or `setcap` anything.
- `pgrep -f` / `pkill -f` sunshine. Kill helpers by numeric PID only.
- Rewrite `shortcuts.vdf` while Game Mode is running.
- Post on GitHub/Discord unless the user asked that day.

### Pass / fail for “did Kimochi fix the pie?”

- **Still broken:** evidence still `focus-elsewhere` after `openControllerMenu`, or no new Kimochi release and #165 open.
- **Maybe fixed:** new release or #165 closed **and** you did not retest. Tell the user to try LS+RS in Game Mode; do not test unsupervised (needs their pad + Trails in front).
- **Fixed:** user already confirmed the pie stays with Trails focused. Update the “Locked facts” radial row in this skill.

Report template:

```text
Kimochi daily 20:00
- local: …
- latest GitHub: …
- #165: open|closed — …
- session: Game Mode|Plasma|unknown; kimochi …; trails …
- evidence today: N opens / N focus-elsewhere (or no file growth)
- AnkiConnect :18765: ok|fail
- action: none
```
