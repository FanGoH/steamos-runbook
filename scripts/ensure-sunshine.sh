#!/usr/bin/env bash
# Enable Sunshine user service if disabled. Do not use sudo systemctl --user.
# SteamOS updates can disable user services while Flatpak apps remain installed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

if ! systemctl --user list-unit-files "$SUNSHINE_USER_SERVICE" >/dev/null 2>&1; then
  echo "Sunshine user service not found: $SUNSHINE_USER_SERVICE"
  record_manual "Install Sunshine Flatpak / find user service" <<EOF
flatpak install flathub dev.lizardbyte.app.Sunshine
systemctl --user list-unit-files | grep -i sunshine
# Then:
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user enable --now $SUNSHINE_USER_SERVICE
EOF
  exit 0
fi

if systemctl --user is-enabled "$SUNSHINE_USER_SERVICE" >/dev/null 2>&1; then
  echo "$SUNSHINE_USER_SERVICE already enabled."
else
  systemctl --user enable --now "$SUNSHINE_USER_SERVICE"
  echo "Enabled and started $SUNSHINE_USER_SERVICE."
fi

if systemctl --user is-active "$SUNSHINE_USER_SERVICE" >/dev/null 2>&1; then
  echo "$SUNSHINE_USER_SERVICE is active."
else
  systemctl --user start "$SUNSHINE_USER_SERVICE" || true
  if systemctl --user is-active "$SUNSHINE_USER_SERVICE" >/dev/null 2>&1; then
    echo "Started $SUNSHINE_USER_SERVICE."
  else
    echo "Warning: $SUNSHINE_USER_SERVICE is not active."
    record_manual "Start Sunshine user service (no sudo)" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user enable --now $SUNSHINE_USER_SERVICE
systemctl --user status $SUNSHINE_USER_SERVICE --no-pager
EOF
    exit 1
  fi
fi
