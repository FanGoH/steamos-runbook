# Cemu dual-screen

Plasma (`:48100`): standalone Cemu, TV on HDMI-A-1, GamePad View on Virtual-sunshine-ds. Follow `.cursor/skills/cemu-dual-screen/SKILL.md` and run `scripts/ensure-cemu-dual-screen.sh`.

Game Mode (`:48200`, Thor checkpoint `checkpoint-2026-09-14-gamemode-fill-exit`): Moonlight on `sunshine-ds-kms`, then Tender Cemu tile (or `CEMU_PAD_MATCH=Thor ./scripts/ensure-cemu-gamemode-dual-screen.sh`). GamePad `ffplay` grabs session `:1` and scales to 1920×1080. After overlay/refocus, `--place-only` puts GamePad back on `:2` (kills Tk paint, raises ffplay). Close a leftover Tender `-f` Cemu first (`scripts/sunshine-app-stop.sh cemu`). Do not run the KWin desktop script in Game Mode.
