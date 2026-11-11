#!/usr/bin/env bash
# Kimochi Game Mode overlay sidecar. Steam's existing shortcut stays pointed
# at ~/.local/share/kimochi/gaming-mode/launch.sh — do not rewrite
# shortcuts.vdf while Game Mode is running. The tile starts
# steamos-kimochi-overlay.service (Kimochi is not a Steam-managed game and
# does not auto-start with Game Mode — that SIGSTOP'd steam).
# Kimochi updates restore launch.sh; re-run this (also from post-update.sh).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
if ! require_playbook_user; then
  exit 2
fi
setup_user_dbus

LAUNCHER="$ROOT/scripts/kimochi-gaming-mode.sh"
OVERLAY="$ROOT/scripts/kimochi-overlay.sh"
KIMOCHI_ROOT="${KIMOCHI_GAMING_MODE_ROOT:-/home/${STEAMOS_USER}/.local/share/kimochi/gaming-mode}"
WRAP="$KIMOCHI_ROOT/launch.sh"
APPIMAGE="${KIMOCHI_APPIMAGE:-/home/${STEAMOS_USER}/.local/share/kimochi/Kimochi.AppImage}"
MARK="steamos-playbook kimochi-gaming-mode wrap"
SERVICE="${KIMOCHI_OVERLAY_SERVICE:-steamos-kimochi-overlay.service}"
UNIT_PATH="/home/${STEAMOS_USER}/.config/systemd/user/$SERVICE"
LOG="$ROOT/logs/kimochi-overlay.log"
UID_NUM="$(id -u "$STEAMOS_USER")"

chmod +x "$LAUNCHER" "$OVERLAY" 2>/dev/null || true

if [ ! -e "$APPIMAGE" ] && [ ! -e "$KIMOCHI_ROOT/current/Kimochi.AppImage" ]; then
  echo "Kimochi AppImage not installed; skip Game Mode wrap."
  exit 0
fi

if [ ! -d "$KIMOCHI_ROOT/current" ] || [ ! -f "$KIMOCHI_ROOT/current/scripts/launch-from-steam.sh" ]; then
  echo "Kimochi Gaming Mode files missing under $KIMOCHI_ROOT"
  record_manual "Install Kimochi Gaming Mode, then wrap the Steam launcher" <<EOF
# From Kimochi: enable Gaming Mode, then:
$ROOT/scripts/ensure-kimochi.sh
EOF
  exit 2
fi

if [ ! -x "$LAUNCHER" ] || [ ! -x "$OVERLAY" ]; then
  echo "Missing $LAUNCHER or $OVERLAY"
  exit 1
fi

desired=$(cat <<EOF
#!/bin/sh
# $MARK
# Steam tile kicks the overlay sidecar. Restore via $ROOT/scripts/ensure-kimochi.sh.
exec /bin/sh '$LAUNCHER' "\$@"
EOF
)

mkdir -p "$KIMOCHI_ROOT" "/home/${STEAMOS_USER}/.config/systemd/user" "$ROOT/logs"
if [ -f "$WRAP" ] && [ "$(cat "$WRAP")" = "$desired" ]; then
  echo "Kimochi Game Mode wrap already in place ($WRAP)."
else
  printf '%s\n' "$desired" >"$WRAP"
  chmod +x "$WRAP"
  echo "Wrapped Kimochi Steam launcher: $WRAP -> $LAUNCHER"
  echo "Existing Steam tile keeps LaunchOptions=$WRAP (no shortcuts.vdf rewrite)."
fi

# 0.8.1 radial menu: extract AppDir and patch !deck.connected() cancel.
# Empty/placeholder AppImages (offline tests) are skipped.
PATCHER="$ROOT/scripts/patch-kimochi-controller-nav.py"
EXTRACT="$KIMOCHI_ROOT/extracted"
real_app="$APPIMAGE"
if [ ! -e "$real_app" ]; then
  real_app="$KIMOCHI_ROOT/current/Kimochi.AppImage"
fi
app_size=0
if [ -e "$real_app" ]; then
  app_size=$(stat -c%s "$real_app" 2>/dev/null || echo 0)
fi
if [ -f "$PATCHER" ] && [ "${app_size:-0}" -gt 1000000 ]; then
  if [ ! -x "$EXTRACT/usr/bin/kimochi" ] || [ "$real_app" -nt "$EXTRACT/usr/bin/kimochi" ]; then
    tmp=$(mktemp -d)
    if (CDPATH= cd -- "$tmp" && PATH="/usr/bin:/bin:${PATH:-}" "$real_app" --appimage-extract); then
      rm -rf "$EXTRACT"
      mv "$tmp/squashfs-root" "$EXTRACT"
      chmod -R u+w "$EXTRACT" 2>/dev/null || true
      echo "Extracted Kimochi AppDir for controller-nav patch: $EXTRACT"
    else
      echo "Could not extract Kimochi AppImage for controller-nav patch."
    fi
    rm -rf "$tmp"
  fi
  if [ -x "$EXTRACT/usr/bin/kimochi" ]; then
    /usr/bin/python3 "$PATCHER" --elf "$EXTRACT/usr/bin/kimochi" || true
  fi
fi

# Placeholder AppImages (ensure tests) skip the user unit.
if [ "${app_size:-0}" -le 1000000 ]; then
  echo "Kimochi AppImage is a placeholder; skip overlay unit."
  exit 0
fi

desired_unit="$(cat <<EOS
[Unit]
Description=Kimochi Game Mode overlay sidecar
Documentation=file://$ROOT/scripts/ensure-kimochi.sh
After=gamescope-session.service
PartOf=gamescope-session.service
ConditionPathExists=$OVERLAY
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
ExecStart=$OVERLAY
ExecStopPost=$ROOT/scripts/kimochi-cont-steam.sh
Restart=on-failure
RestartSec=3
RestartPreventExitStatus=1 2
TimeoutStopSec=15
KillMode=mixed
Environment=HOME=/home/$STEAMOS_USER
Environment=USER=$STEAMOS_USER
Environment=XDG_RUNTIME_DIR=/run/user/$UID_NUM
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$UID_NUM/bus
Environment=DISPLAY=:0
Environment=PATH=/usr/bin:/bin
Environment=KIMOCHI_GAMING_MODE_ROOT=$KIMOCHI_ROOT
UnsetEnvironment=SteamAppId SteamGameId SteamOverlayGameId LD_PRELOAD KIMOCHI_STEAM_MANAGED KIMOCHI_STEAM_APP_ID
StandardOutput=append:$LOG
StandardError=append:$LOG
EOS
)"

unit_changed=0
if [ ! -f "$UNIT_PATH" ] || [ "$(cat "$UNIT_PATH")" != "$desired_unit" ]; then
  printf '%s\n' "$desired_unit" >"$UNIT_PATH"
  systemctl --user daemon-reload
  unit_changed=1
  echo "Updated $SERVICE unit."
fi

# Drop a leftover gamescope-session.target.wants symlink. Auto-start
# SIGSTOP'd steam and left Guide/QAM dead when the overlay exited mid-pause.
if systemctl --user is-enabled "$SERVICE" >/dev/null 2>&1; then
  systemctl --user disable "$SERVICE" || true
  echo "Disabled $SERVICE auto-start (Steam tile starts it; Guide/QAM stay alive)."
fi
if systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
  systemctl --user stop "$SERVICE" || true
  echo "Stopped $SERVICE so steam is not left SIGSTOP'd."
fi
/bin/sh "$ROOT/scripts/kimochi-cont-steam.sh" || true
echo "$SERVICE installed. Steam tile restarts it; it does not start with Game Mode."
exit 0
