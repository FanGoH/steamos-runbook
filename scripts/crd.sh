#!/usr/bin/env bash
# Use Chrome Remote Desktop on this Steam Machine.
# Virtual Plasma X11 session — not Game Mode HDMI / Sunshine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

HELPER="$ROOT/scripts/chrome_remote_desktop.py"
HOST="${CRD_HOST_BIN:-/opt/google/chrome-remote-desktop/chrome-remote-desktop}"
SERVICE="${CRD_SERVICE:-chrome-remote-desktop@${STEAMOS_USER}.service}"
CONFIG_DIR="${CRD_CONFIG_DIR:-/home/${STEAMOS_USER}/.config/chrome-remote-desktop}"
ACTION="${1:-status}"

usage() {
  python3 "$HELPER" usage --user "$STEAMOS_USER"
}

need_host() {
  if [ ! -x "$HOST" ]; then
    echo "Chrome Remote Desktop host is not installed at $HOST."
    echo "Run: ./scripts/ensure-chrome-remote-desktop.sh"
    exit 1
  fi
}

case "$ACTION" in
  status)
    echo "host: $HOST"
    if [ -x "$HOST" ]; then
      echo "host binary: present"
    else
      echo "host binary: missing"
    fi
    if python3 "$HELPER" registered --config-dir "$CONFIG_DIR"; then
      echo "host registration: yes ($CONFIG_DIR)"
    else
      echo "host registration: no (Google headless setup still needed)"
    fi
    if systemctl is-enabled "$SERVICE" >/dev/null 2>&1; then
      echo "$SERVICE: enabled"
    else
      echo "$SERVICE: not enabled"
    fi
    if systemctl is-active "$SERVICE" >/dev/null 2>&1; then
      echo "$SERVICE: active"
    else
      echo "$SERVICE: inactive"
    fi
    if [ -x "$HOST" ]; then
      echo -n "host --get-status: "
      "$HOST" --get-status 2>/dev/null || true
    fi
    ;;
  start)
    need_host
    if ! python3 "$HELPER" registered --config-dir "$CONFIG_DIR"; then
      echo "Host is not registered yet."
      usage
      exit 2
    fi
    sudo systemctl enable --now "$SERVICE"
    systemctl is-active "$SERVICE"
    ;;
  stop)
    sudo systemctl stop "$SERVICE"
    echo "Stopped $SERVICE."
    ;;
  restart)
    need_host
    sudo systemctl restart "$SERVICE"
    systemctl is-active "$SERVICE"
    ;;
  setup|usage|help|-h|--help)
    usage
    ;;
  *)
    echo "Usage: $0 status|start|stop|restart|setup"
    exit 1
    ;;
esac
