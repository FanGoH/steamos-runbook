---
name: fgpc
description: >-
  FanGoH Gaming PC CLI (fgpc) — pretty Typer/Rich wrapper around playbook
  scripts, plus the phone WebGUI on the tailnet. Use when the user mentions
  fgpc, the playbook CLI, SSH command palette, phone remote, WebGUI, or wants
  one command for pads, hide, stream, second screen, or post-update.
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
| `decky` | `ensure-*-decky.sh`, `decky_reload_plugin` (Playbook runs `post-update.sh`; **FGPC** is the catalog QAM) |
| `saves` | `ensure-syncthing.sh` |

Decky **FGPC** (`ensure-fgpc-decky.sh`, reload name `FGPC`) is the QAM
catalog: Game Mode `:48200` start-kms / paint / stop / close Cemu|Azahar,
second screen, pad mode/apply, hide toggles, tips. JSON:
`python3 scripts/fgpc-api.py dump`. It does **not** run bootstrap,
post-update, or mode switch (SSH `fgpc` only). Playbook QAM stays
post-update only.

Phone **WebGUI** (`ensure-fgpc-web.sh`, user unit `fgpc-web.service`) is the
same catalog on this Steam Machine. Tabs: Stream / Screen / Pad / Hide / More.
Buttons only (no free-text commands). Binds `127.0.0.1` plus the tailnet IPv4
on `FGPC_WEB_PORT` (default 8484). Extra name `fgpc.tailnet.fangoh.dev` →
`100.64.0.8` is Headscale `/etc/headscale/extra_records.json` on the VPS
(`dns.extra_records_path`, no restart). Do **not** change `--hostname=steammachine`.
Browsers that upgrade to `https://` hit HTTP 400 (TLS ClientHello). Use
`http://` or the WebView APK.

```bash
./scripts/ensure-fgpc-web.sh
python3 scripts/test_fgpc_web.py
curl -s http://127.0.0.1:8484/healthz
```

Thin **Android APK** (`com.fangoh.fgpc`) is a WebView of that same HTTP URL. Tabs stay on the host — do not put catalog buttons in Kotlin. Build + sideload:

```bash
./scripts/build-fgpc-apk.sh
./scripts/install-fgpc-apk.sh
```

Use `http://` (cleartext). Do not `adb kill-server`. Phone/Odin wireless ports change; set `FGPC_APK_ADB` in `.env` or `adb connect HOST:PORT`. Odin usually appears as mDNS `_adb-tls-connect._tcp`. The A54 needs Wireless debugging on (the LAN port changes).

## Do not

- Put new hide/bind/stream code in `fgpc/` — extend the playbook script, then add a thin Typer command.
- `pgrep -f` / `pkill -f` sunshine.
- `sudo systemctl --user`.
- `--start` kms while `:2` is already up (`fgpc stream gamemode start-kms`).
- Pass `--force` on hide from Decky / `fgpc-api.py` / the WebGUI; `fgpc hide off --force` is SSH-only.
- Merge FGPC into the Playbook plugin (Playbook is post-update only).
- Change `TAILSCALE_HOSTNAME` to publish the phone UI.

Skill for hide details: `.cursor/skills/pad-hide/SKILL.md`. Reload QAM: `.cursor/skills/decky-plugins/SKILL.md`.
