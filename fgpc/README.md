# fgpc — FanGoH Gaming PC

Pretty SSH CLI for this Steam Machine playbook. Typer + Rich: grouped help,
examples, arrow menu, shell completion. Every action calls an existing
playbook script (do not reimplement hide/bind/stream logic here).

```bash
fgpc
fgpc tips
fgpc examples
fgpc pad list
fgpc hide list
fgpc stream status
fgpc --help
fgpc pad --help
```

Install: `scripts/ensure-fgpc.sh` (uv venv + `~/.local/bin/fgpc`).
Completion: `fgpc complete install` or `eval "$(fgpc --show-completion bash)"`.

Skill: `.cursor/skills/fgpc/SKILL.md`.
