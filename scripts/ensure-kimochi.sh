#!/usr/bin/env bash
# Restore Kimochi's own Game Mode launcher. A leftover playbook wrap made
# Kimochi a Steam-managed overlay, SIGSTOP'd steam, and killed Guide/QAM.
# Steam's shortcut stays pointed at
# ~/.local/share/kimochi/gaming-mode/launch.sh — do not rewrite
# shortcuts.vdf while Game Mode is running.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
if ! require_playbook_user; then
  exit 2
fi
setup_user_dbus

KIMOCHI_ROOT="${KIMOCHI_GAMING_MODE_ROOT:-/home/${STEAMOS_USER}/.local/share/kimochi/gaming-mode}"
LAUNCH="$KIMOCHI_ROOT/launch.sh"
APPIMAGE="${KIMOCHI_APPIMAGE:-/home/${STEAMOS_USER}/.local/share/kimochi/Kimochi.AppImage}"
SERVICE="${KIMOCHI_OVERLAY_SERVICE:-steamos-kimochi-overlay.service}"
UNIT_PATH="/home/${STEAMOS_USER}/.config/systemd/user/$SERVICE"
WRAP_MARK="steamos-playbook kimochi-gaming-mode wrap"

if [ ! -e "$APPIMAGE" ] && [ ! -e "$KIMOCHI_ROOT/current/Kimochi.AppImage" ]; then
  echo "Kimochi AppImage not installed; skip Game Mode launcher restore."
  exit 0
fi

if [ ! -d "$KIMOCHI_ROOT/current" ] || [ ! -f "$KIMOCHI_ROOT/current/scripts/launch-from-steam.sh" ]; then
  echo "Kimochi Gaming Mode files missing under $KIMOCHI_ROOT"
  record_manual "Install Kimochi Gaming Mode" <<EOF
# From Kimochi: enable Gaming Mode.
EOF
  exit 2
fi

release_dir=$(CDPATH= cd -- "$KIMOCHI_ROOT/current" && pwd -P)
vendor_launcher="$release_dir/scripts/launch-from-steam.sh"
vendor_app="$release_dir/Kimochi.AppImage"
if [ ! -e "$vendor_app" ] && [ -e "$APPIMAGE" ]; then
  vendor_app="$APPIMAGE"
fi

desired=$(cat <<EOF
#!/bin/sh
# Kimochi Gaming Mode (vendor launch-from-steam.sh).
exec /bin/sh '$vendor_launcher' '$vendor_app' "\$@"
EOF
)

mkdir -p "$KIMOCHI_ROOT"
need_restore=0
if [ ! -f "$LAUNCH" ]; then
  need_restore=1
elif grep -q "$WRAP_MARK" "$LAUNCH" 2>/dev/null; then
  need_restore=1
elif grep -q 'kimochi-gaming-mode.sh\|kimochi-overlay.sh' "$LAUNCH" 2>/dev/null; then
  need_restore=1
fi
if [ "$need_restore" -eq 1 ]; then
  printf '%s\n' "$desired" >"$LAUNCH"
  chmod +x "$LAUNCH"
  echo "Restored Kimochi vendor launcher: $LAUNCH"
  echo "Existing Steam tile keeps LaunchOptions=$LAUNCH (no shortcuts.vdf rewrite)."
else
  echo "Kimochi Game Mode launcher is already vendor ($LAUNCH)."
fi

if [ -f "$UNIT_PATH" ] || systemctl --user is-enabled "$SERVICE" >/dev/null 2>&1 \
  || systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
  if systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
    systemctl --user stop "$SERVICE" || true
    echo "Stopped leftover $SERVICE."
  fi
  if systemctl --user is-enabled "$SERVICE" >/dev/null 2>&1; then
    systemctl --user disable "$SERVICE" || true
  fi
  rm -f "$UNIT_PATH"
  systemctl --user daemon-reload || true
  echo "Removed leftover $SERVICE."
fi

# Resume steam if a leftover overlay watchdog left it SIGSTOP'd.
for pid in $(ps -eo pid,comm | awk '$2=="kimochi-input"{print $1}'); do
  kill -TERM "$pid" 2>/dev/null || true
done
for pid in $(ps -eo pid,stat,comm | awk '$3=="steam" && $2 ~ /T/{print $1}'); do
  echo "SIGCONT steam pid $pid"
  kill -CONT "$pid" 2>/dev/null || true
done
exit 0
