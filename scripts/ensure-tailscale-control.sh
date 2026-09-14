#!/usr/bin/env bash
# Pin Decky Tailscale Control Advanced Settings to this Steam Machine.
# Custom flags match the manual ./deck-tailscale up command (hostname from .env).
# Never --reset or --ssh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

PLUGIN_DIR="${DECKY_HOMEBREW_DIR:-/home/$STEAMOS_USER/homebrew}/plugins/tailscale-control"
SETTINGS_DIR="${DECKY_HOMEBREW_DIR:-/home/$STEAMOS_USER/homebrew}/settings/tailscale-control"
MAIN="$PLUGIN_DIR/main.py"
INDEX="$PLUGIN_DIR/dist/index.js"
SETTINGS="$SETTINGS_DIR/playbook.json"
PATCH="$ROOT/scripts/patch_tailscale_control.py"

if ! python3 "$PATCH" --self-test >/dev/null; then
  echo "patch_tailscale_control self-test failed."
  exit 1
fi

if [ ! -f "$MAIN" ] || [ ! -f "$INDEX" ]; then
  echo "Tailscale Control plugin not installed ($PLUGIN_DIR)."
  record_manual "Install Decky Tailscale Control, then re-run" <<EOF
$ROOT/scripts/ensure-tailscale-control.sh
EOF
  exit 2
fi

patch_args=(--main "$MAIN" --index "$INDEX" --settings "$SETTINGS")
if [ -n "${TAILSCALE_LOGIN_SERVER:-}" ]; then
  patch_args+=(--login-server "$TAILSCALE_LOGIN_SERVER")
fi
if [ -n "${TAILSCALE_HOSTNAME:-}" ]; then
  patch_args+=(--hostname "$TAILSCALE_HOSTNAME")
fi

if [ ! -w "$MAIN" ] || [ ! -w "$INDEX" ]; then
  if sudo -n true 2>/dev/null; then
    sudo python3 "$PATCH" "${patch_args[@]}"
  else
    echo "Tailscale Control plugin files are not writable."
    record_manual "Patch Tailscale Control so it does not override steammachine" <<EOF
sudo python3 $PATCH --main $MAIN --index $INDEX --settings $SETTINGS --login-server "\$TAILSCALE_LOGIN_SERVER" --hostname "\$TAILSCALE_HOSTNAME"
EOF
    exit 2
  fi
else
  python3 "$PATCH" "${patch_args[@]}"
fi

if ! python3 - "$MAIN" <<'PY'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
if 'cmd_list.append("--reset")' in text:
    sys.exit(1)
if "def _playbook_hostname(" not in text:
    sys.exit(1)
if "--hostname={playbook_hostname}" not in text:
    sys.exit(1)
PY
then
  echo "Tailscale Control main.py is missing hostname pin or still --reset."
  exit 1
fi

if [ -x "${TAILSCALE_BIN:-}" ]; then
  TS="$TAILSCALE_BIN"
elif command -v tailscale >/dev/null 2>&1; then
  TS="$(command -v tailscale)"
else
  TS=""
fi
if [ -n "$TS" ]; then
  current="$("$TS" debug prefs 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('Hostname') or '')" || true)"
  if [ -n "${TAILSCALE_HOSTNAME:-}" ] && [ "$current" != "$TAILSCALE_HOSTNAME" ]; then
    echo "Setting Tailscale hostname to $TAILSCALE_HOSTNAME (was ${current:-empty}); not passing --reset/--ssh."
    "$TS" set --hostname="$TAILSCALE_HOSTNAME"
  fi
fi

if decky_reload_plugin "Tailscale Control"; then
  echo "Patched Tailscale Control and reloaded the plugin."
else
  echo "Patched Tailscale Control; reload Decky plugins (or leave Game Mode and come back) to pick up Advanced Settings."
fi
