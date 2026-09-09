#!/usr/bin/env bash
# Isolated Game Mode KMS experiment for sunshine-ds.
# Does not touch Decky (:47989), desktop DS (:48100), or sunshine-ds-dev.
#
#   scripts/ensure-sunshine-ds-gamemode.sh --probe   # start, print capture log, stop
#   scripts/ensure-sunshine-ds-gamemode.sh --status
#   scripts/ensure-sunshine-ds-gamemode.sh --stop
#   scripts/ensure-sunshine-ds-gamemode.sh --start   # only if gamescope is up
#
# Binary is sunshine-ds-kms (copy). Port 48200. No virtual-output helper.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

BOX_NAME="${STEAMOS_DISTROBOX_NAME:-steamos-tools}"
DS_BIN="${SUNSHINE_DS_BIN:-/home/${STEAMOS_USER:-deck}/.local/bin/sunshine-ds}"
KMS_BIN="${SUNSHINE_DS_KMS_BIN:-/home/${STEAMOS_USER:-deck}/.local/bin/sunshine-ds-kms}"
KMS_DIR="${SUNSHINE_DS_KMS_CONFIG_DIR:-/home/${STEAMOS_USER:-deck}/.config/sunshine-ds-gamemode}"
KMS_CONF="$KMS_DIR/sunshine/sunshine.conf"
DEV_CONF="${SUNSHINE_DS_CONF:-/home/${STEAMOS_USER:-deck}/.config/sunshine-ds-dev/sunshine/sunshine.conf}"
KMS_PORT="${SUNSHINE_DS_KMS_PORT:-48200}"
KMS_URL="${SUNSHINE_DS_KMS_URL:-http://127.0.0.1:${KMS_PORT}}"
KMS_LOG="${SUNSHINE_DS_KMS_LOG:-$ROOT/logs/sunshine-ds-gamemode.log}"
WAIT_SECS="${SUNSHINE_DS_WAIT_SECS:-20}"
UID_NUM="$(id -u)"

DO_STATUS=0
DO_STOP=0
DO_PROBE=0
DO_START=0
DO_FORCE_DESKTOP=0
for arg in "$@"; do
  case "$arg" in
    --status) DO_STATUS=1 ;;
    --stop) DO_STOP=1 ;;
    --probe) DO_PROBE=1 ;;
    --start) DO_START=1 ;;
    --force-desktop-kms) DO_FORCE_DESKTOP=1 ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      echo "usage: $0 [--status] [--stop] [--probe] [--start] [--force-desktop-kms]" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$ROOT/logs"

desktop_ds_pid() {
  pgrep -x sunshine-ds || true
}

kms_ds_pid() {
  pgrep -x sunshine-ds-kms || true
}

dev_conf_hash() {
  sha256sum "$DEV_CONF" 2>/dev/null | awk '{print $1}'
}

assert_desktop_untouched() {
  local before="$1" after
  after="$(dev_conf_hash)"
  if [ -n "$before" ] && [ "$after" != "$before" ]; then
    echo "REFUSING: $DEV_CONF changed during the experiment ($before -> $after)." >&2
    return 1
  fi
  return 0
}

kms_serverinfo() {
  curl -sS --max-time 3 "${KMS_URL}/serverinfo" 2>/dev/null || true
}

kms_state() {
  local xml
  xml="$(kms_serverinfo)"
  if [ -z "$xml" ]; then
    printf '%s\n' "DOWN"
    return 1
  fi
  if printf '%s' "$xml" | grep -q 'SUNSHINE_SERVER_BUSY'; then
    printf '%s\n' "BUSY"
    return 0
  fi
  if printf '%s' "$xml" | grep -q 'SUNSHINE_SERVER_FREE'; then
    printf '%s\n' "FREE"
    return 0
  fi
  printf '%s\n' "UNKNOWN"
  return 1
}

print_status() {
  local pid state xml uid desk
  pid="$(kms_ds_pid)"
  state="$(kms_state 2>/dev/null || true)"; state="${state:-DOWN}"
  xml="$(kms_serverinfo)"
  uid="$(sunshine_xml_uniqueid "$xml")"
  desk="$(desktop_ds_pid)"
  echo "sunshine-ds-kms pid: ${pid:-none}"
  echo "state: $state"
  echo "url: $KMS_URL"
  [ -n "$uid" ] && echo "uniqueid: $uid"
  echo "desktop sunshine-ds pid: ${desk:-none} (must stay on :48100 / kwin)"
  echo "desktop conf: $DEV_CONF"
}

ensure_kms_binary() {
  if [ ! -x "$DS_BIN" ]; then
    echo "Missing desktop binary $DS_BIN"
    return 1
  fi
  if [ ! -x "$KMS_BIN" ] || [ "$DS_BIN" -nt "$KMS_BIN" ]; then
    echo "Copying $DS_BIN -> $KMS_BIN (separate comm, does not replace desktop DS)."
    cp -a "$DS_BIN" "$KMS_BIN"
    chmod 0755 "$KMS_BIN"
  fi
  return 0
}

write_kms_conf() {
  local apps
  mkdir -p "$KMS_DIR/sunshine/credentials"
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
# Explicit none (blank is ignored and the binary defaults to "virtual").
dual_display_source = none
encoder = software
hevc_mode = 1
av1_mode = 1
gamepad = x360
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

gamescope_up() {
  systemctl --user is-active gamescope-session.service >/dev/null 2>&1
}

stop_kms() {
  local pid leftover i
  pid="$(kms_ds_pid)"
  if [ -z "$pid" ]; then
    echo "No sunshine-ds-kms process."
    return 0
  fi
  echo "Stopping sunshine-ds-kms pid $pid."
  kill "$pid" 2>/dev/null || true
  i=0
  while [ "$i" -lt 20 ]; do
    [ -z "$(kms_ds_pid)" ] && break
    sleep 0.2
    i=$((i + 1))
  done
  leftover="$(kms_ds_pid)"
  if [ -n "$leftover" ]; then
    kill -9 "$leftover" 2>/dev/null || true
  fi
  return 0
}

start_kms() {
  if [ -n "$(desktop_ds_pid)" ]; then
    echo "Desktop sunshine-ds is running. Stop it with ensure-sunshine-ds.sh --stop before this experiment."
    return 2
  fi
  if [ ! -x "$KMS_BIN" ]; then
    echo "Missing $KMS_BIN"
    return 1
  fi
  if ! command -v podman >/dev/null 2>&1; then
    echo "podman missing."
    return 1
  fi
  if ! podman inspect -f '{{.State.Running}}' "$BOX_NAME" 2>/dev/null | grep -qx true; then
    echo "Starting Distrobox $BOX_NAME."
    podman start "$BOX_NAME" >/dev/null || return 1
  fi
  write_kms_conf
  echo "Starting sunshine-ds-kms in Distrobox $BOX_NAME on $KMS_URL (capture=kms, privileged exec for CAP_SYS_ADMIN)."
  : >"$KMS_LOG"
  # --privileged is only this exec, not the desktop kwin sunshine-ds path.
  # Distrobox uid 1000 can open /dev/dri (ACL) but has no CAP_SYS_ADMIN otherwise.
  podman exec --privileged --user "$UID_NUM" -d "$BOX_NAME" bash -lc \
    "export XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR WAYLAND_DISPLAY=$WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS PIPEWIRE_RUNTIME_DIR=$XDG_RUNTIME_DIR CONFIGURATION_DIRECTORY=$KMS_DIR HOME=/home/${STEAMOS_USER:-deck}; unset DISPLAY; exec $KMS_BIN $KMS_CONF >> $KMS_LOG 2>&1"
}

wait_for_kms() {
  local waited=0 state
  while [ "$waited" -lt "$WAIT_SECS" ]; do
    state="$(kms_state 2>/dev/null || true)"; state="${state:-DOWN}"
    if [ "$state" = "FREE" ] || [ "$state" = "BUSY" ]; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "sunshine-ds-kms did not answer $KMS_URL/serverinfo. See $KMS_LOG"
  return 1
}

print_probe_log() {
  echo "----- sunshine-ds-kms log (capture/KMS) -----"
  grep -E 'KMS|kms|capture|Screencast|monitor|HDMI|Unable to initialize|Probably not permitted|CAP_SYS|Fatal|MaxVideo' "$KMS_LOG" 2>/dev/null | tail -80 || true
  echo "----- end -----"
}

BEFORE_HASH="$(dev_conf_hash)"

if [ "$DO_STATUS" -eq 1 ]; then
  print_status
  state="$(kms_state 2>/dev/null || true)"; state="${state:-DOWN}"
  assert_desktop_untouched "$BEFORE_HASH" || exit 1
  case "$state" in
    FREE|BUSY) exit 0 ;;
    *) exit 2 ;;
  esac
fi

if [ "$DO_STOP" -eq 1 ]; then
  stop_kms
  print_status
  assert_desktop_untouched "$BEFORE_HASH" || exit 1
  exit 0
fi

if [ "$DO_PROBE" -eq 0 ] && [ "$DO_START" -eq 0 ]; then
  echo "usage: $0 [--probe] [--start] [--status] [--stop]" >&2
  exit 2
fi

if [ "$DO_START" -eq 1 ] && [ "$DO_FORCE_DESKTOP" -eq 0 ] && ! gamescope_up; then
  echo "gamescope-session is not active. This experiment is for Game Mode."
  echo "Desktop dual-stream stays on :48100 (capture=kwin). Pass --probe to try KMS on Plasma without keeping it, or --start --force-desktop-kms."
  exit 2
fi

ensure_kms_binary || exit $?
write_kms_conf

if [ -n "$(kms_ds_pid)" ]; then
  echo "sunshine-ds-kms already running."
else
  start_kms || exit $?
fi

if ! wait_for_kms; then
  print_probe_log
  print_status
  if [ "$DO_PROBE" -eq 1 ]; then
    stop_kms
  fi
  assert_desktop_untouched "$BEFORE_HASH" || exit 1
  exit 1
fi

xml="$(kms_serverinfo)"
echo "sunshine-ds-kms is up pid $(kms_ds_pid) $KMS_URL ($(kms_state))"
echo "uniqueid $(sunshine_xml_uniqueid "$xml")"
echo "MaxVideoStreams $(printf '%s' "$xml" | sed -n 's/.*<MaxVideoStreams>\([^<]*\)<\/MaxVideoStreams>.*/\1/p')"
print_probe_log

capture_ok=1
if grep -q 'Unable to initialize capture method' "$KMS_LOG" 2>/dev/null; then
  echo "KMS capture did not initialize (see CAP_SYS_ADMIN / empty monitor list)."
  capture_ok=0
fi

if [ "$DO_PROBE" -eq 1 ]; then
  echo "Probe done; stopping sunshine-ds-kms so :48100 kwin stays the daily path."
  stop_kms
fi

assert_desktop_untouched "$BEFORE_HASH" || exit 1
print_status
if [ "$capture_ok" -eq 0 ]; then
  exit 1
fi
exit 0
