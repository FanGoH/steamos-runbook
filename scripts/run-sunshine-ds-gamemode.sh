#!/usr/bin/env bash
# Foreground launcher for sunshine-ds-kms. systemd ExecStart for
# steamos-sunshine-ds-gamemode.service. Also `--write-conf`.
# Does not touch Decky (:47989) or desktop sunshine-ds (:48100).
# Unsets DISPLAY (KMS) and LD_LIBRARY_PATH (AT_SECURE / file caps).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -S "${XDG_RUNTIME_DIR}/gamescope-1" ]; then
  export WAYLAND_DISPLAY=gamescope-1
elif [ -S "${XDG_RUNTIME_DIR}/gamescope-0" ]; then
  export WAYLAND_DISPLAY=gamescope-0
elif [ -S "${XDG_RUNTIME_DIR}/wayland-0" ]; then
  export WAYLAND_DISPLAY=wayland-0
else
  unset WAYLAND_DISPLAY
fi
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"
export PIPEWIRE_RUNTIME_DIR="${PIPEWIRE_RUNTIME_DIR:-$XDG_RUNTIME_DIR}"

KMS_BIN="${SUNSHINE_DS_KMS_BIN:-/home/${STEAMOS_USER:-deck}/.local/bin/sunshine-ds-kms}"
KMS_DIR="${SUNSHINE_DS_KMS_CONFIG_DIR:-/home/${STEAMOS_USER:-deck}/.config/sunshine-ds-gamemode}"
KMS_CONF="$KMS_DIR/sunshine/sunshine.conf"
KMS_PORT="${SUNSHINE_DS_KMS_PORT:-48200}"
KMS_LOG="${SUNSHINE_DS_KMS_LOG:-$ROOT/logs/sunshine-ds-gamemode.log}"

write_kms_conf() {
  local apps
  mkdir -p "$KMS_DIR/sunshine/credentials" "$(dirname "$KMS_LOG")"
  apps="$KMS_DIR/sunshine/apps.json"
  if [ ! -f "$apps" ]; then
    cat >"$apps" <<'EOF'
{
  "env": { "PATH": "$(PATH):$(HOME)/.local/bin" },
  "apps": [
    { "name": "Desktop", "image-path": "desktop.png" }
  ]
}
EOF
  fi
  cat >"$KMS_CONF" <<EOF
# Isolated Game Mode KMS experiment. Not sunshine-ds-dev.
port = ${KMS_PORT}
origin_web_ui_allowed = pc
capture = kms
output_name = HDMI-A-1
# gamescope-virtual = headless gamescope PipeWire on video/1 (not the KWin helper).
# HDMI-A-1 duplicates the TV. none keeps MaxVideoStreams 1. virtual is Plasma-only.
dual_display_source = ${SUNSHINE_DS_KMS_DUAL_SOURCE:-gamescope-virtual}
encoder = software
hevc_mode = 1
av1_mode = 1
gamepad = x360
# Hold Back/Select 500ms → HOME on the UHID x360. sunshine-ds then toggles
# gamescope STEAM_OVERLAY (Steam ignores UHID Guide). Default is -1 (off).
back_button_timeout = 500
min_log_level = info
file_state = ${KMS_DIR}/sunshine/sunshine_state.json
log_path = ${KMS_DIR}/sunshine/sunshine.log
file_apps = ${KMS_DIR}/sunshine/apps.json
pkey = ${KMS_DIR}/sunshine/credentials/cakey.pem
cert = ${KMS_DIR}/sunshine/credentials/cacert.pem
credentials_file = ${KMS_DIR}/sunshine/sunshine_state.json
EOF
}

if [ "${1:-}" = "--write-conf" ]; then
  write_kms_conf
  echo "Wrote $KMS_CONF"
  exit 0
fi

if [ -n "$(pgrep -x sunshine-ds || true)" ]; then
  echo "Desktop sunshine-ds is running. Stop it with ensure-sunshine-ds.sh --stop before Game Mode KMS." >&2
  exit 2
fi

if [ ! -x "$KMS_BIN" ]; then
  echo "Missing $KMS_BIN" >&2
  exit 2
fi

if ! getcap "$KMS_BIN" 2>/dev/null | grep -q 'cap_sys_admin'; then
  echo "Host $KMS_BIN has no cap_sys_admin (need sudo setcap on this copy only)." >&2
  exit 2
fi

write_kms_conf
# Idempotent. Heals a stale RemainAfterExit virtual unit if headless gamescope died.
bash "$ROOT/scripts/sunshine-ds-gamemode-virtual.sh" --start || exit 1
export CONFIGURATION_DIRECTORY="$KMS_DIR"
unset DISPLAY
unset LD_LIBRARY_PATH
exec "$KMS_BIN" "$KMS_CONF"
