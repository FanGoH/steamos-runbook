# sunshine-ds GameStream

Diagnose or restore GameStream. Follow `.cursor/skills/sunshine-ds-gamestream/SKILL.md`.

- Plasma daily dual-screen: sunshine-ds `:48100` (`scripts/ensure-sunshine-ds.sh`). Not Decky `:47989`.
- Game Mode Cemu dual-screen (Thor checkpoint): `sunshine-ds-kms` `:48200` (`scripts/ensure-sunshine-ds-gamemode.sh --start`), then `CEMU_PAD_MATCH=Thor ./scripts/ensure-cemu-gamemode-dual-screen.sh`.
- Return to Game Mode from desktop: `scripts/switch-to-game-mode.sh`.
