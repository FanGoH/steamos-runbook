---
name: fgpc
description: >-
  FanGoH Gaming PC CLI (fgpc) — pretty Typer/Rich wrapper around playbook
  scripts. Use when the user mentions fgpc, the playbook CLI, SSH command
  palette, autocomplete for scripts, or wants one command for pads, hide,
  stream, second screen, or post-update.
---

# fgpc

`fgpc` is the SSH-friendly front door. It does **not** reimplement hide, bind,
or stream logic — it calls `scripts/*.py` / `scripts/*.sh`.

```bash
fgpc
fgpc menu
fgpc tips
fgpc examples
fgpc pad list
fgpc hide list
fgpc stream gamemode start-kms
fgpc complete install
```

Install: `scripts/ensure-fgpc.sh` → `~/.local/bin/fgpc` (uv venv in
`~/.local/share/fgpc/venv`). Package source: `fgpc/`.

## Groups

| Group | Scripts |
|---|---|
| `host` | `health-check.sh`, `post-update.sh`, `bootstrap.sh` |
| `mode` | `ensure-sunshine-ds.sh`, `switch-to-game-mode.sh` |
| `stream` | desktop `:48100`, kms `:48200`, `sunshine-app-stop.sh` |
| `screen` | `second-screen-windows.py` |
| `pad` | `bind-gamepad.py`, `ensure-emupads-mux.sh` |
| `hide` | `hide-controllers.py` |
| `emu` | `emu-quick-settings.py` |
| `decky` | `ensure-*-decky.sh`, `decky_reload_plugin` |
| `saves` | `ensure-syncthing.sh` |

## Do not

- Put new hide/bind/stream code in `fgpc/` — extend the playbook script, then add a thin Typer command.
- `pgrep -f` / `pkill -f` sunshine.
- `sudo systemctl --user`.
- `--start` kms while `:2` is already up (`fgpc stream gamemode start-kms`).
- Pass `--force` on hide from Decky; `fgpc hide off --force` is SSH-only.

Skill for hide details: `.cursor/skills/pad-hide/SKILL.md`. Reload QAM: `.cursor/skills/decky-plugins/SKILL.md`.
