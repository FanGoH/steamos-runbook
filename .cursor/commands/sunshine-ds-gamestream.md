# sunshine-ds GameStream

Diagnose or restore GameStream. Follow `.cursor/skills/sunshine-ds-gamestream/SKILL.md`.

- Plasma daily dual-screen: sunshine-ds `:48100` (`scripts/ensure-sunshine-ds.sh`). Not Decky `:47989`.
- Game Mode Cemu dual-screen (**THE standard** `checkpoint-2026-09-18-gamepad-xtest`): `sunshine-ds-kms` `:48200` (`scripts/ensure-sunshine-ds-gamemode.sh --start-kms` if `:2` is already up; `--start` only when `:2` is down), then Tender Cemu tile or `CEMU_PAD_MATCH=Thor ./scripts/ensure-cemu-gamemode-dual-screen.sh`. Recipe: `.cursor/skills/sunshine-ds-gamemode/SKILL.md`.
- Return to Game Mode from desktop: `scripts/switch-to-game-mode.sh`.
