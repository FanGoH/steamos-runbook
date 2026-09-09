#!/usr/bin/env bash
# Bring up desktop GameStream sunshine-ds (:48100) in Distrobox.
# Starts the Distrobox, exactly one Virtual-sunshine-ds helper, and sunshine-ds.
# Does not touch Decky Sunshine (:47989). Safe to re-run.
#
#   scripts/ensure-sunshine-ds.sh           # start if down
#   scripts/ensure-sunshine-ds.sh --status  # print pid/state only
#   scripts/ensure-sunshine-ds.sh --stop    # stop DS + virtual helper (Game Mode teardown)
#   scripts/ensure-sunshine-ds.sh --restart # idle restart (refuses BUSY)
#   scripts/ensure-sunshine-ds.sh --restart --force  # restart even if BUSY
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
DS_HELPER="${SUNSHINE_DS_HELPER:-/home/${STEAMOS_USER:-deck}/.local/bin/sunshine-ds-virtual-output}"
DS_CONF="${SUNSHINE_DS_CONF:-/home/${STEAMOS_USER:-deck}/.config/sunshine-ds-dev/sunshine/sunshine.conf}"
DS_CONFIG_DIR="${SUNSHINE_DS_CONFIG_DIR:-/home/${STEAMOS_USER:-deck}/.config/sunshine-ds-dev}"
DS_URL="${SUNSHINE_DS_URL:-http://127.0.0.1:48100}"
DS_LOG="${SUNSHINE_DS_LOG:-$ROOT/logs/sunshine-ds.log}"
HELPER_LOG="${SUNSHINE_DS_HELPER_LOG:-$ROOT/logs/sunshine-ds-virtual-output.log}"
WAIT_SECS="${SUNSHINE_DS_WAIT_SECS:-20}"
UID_NUM="$(id -u)"

DO_RESTART=0
DO_FORCE=0
DO_STATUS=0
DO_STOP=0
for arg in "$@"; do
  case "$arg" in
    --restart) DO_RESTART=1 ;;
    --force) DO_FORCE=1 ;;
    --status) DO_STATUS=1 ;;
    --stop) DO_STOP=1 ;;
    -h|--help)
      sed -n '2,13p' "$0"
      exit 0
      ;;
    *)
      echo "usage: $0 [--status] [--stop] [--restart] [--force]" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$ROOT/logs"

ds_pid() {
  pgrep -x sunshine-ds || true
}

# comm is truncated to 15 chars: sunshine-ds-vir. Do not pgrep -f the helper.
helper_pids() {
  local pid comm
  while read -r pid comm; do
    pid="${pid#"${pid%%[![:space:]]*}"}"
    [ -n "$pid" ] || continue
    [ "$comm" = "sunshine-ds-vir" ] || continue
    printf '%s\n' "$pid"
  done < <(ps -eo pid=,comm=)
}

print_status() {
  local pid state xml uid helpers
  pid="$(ds_pid)"
  state="$(sunshine_ds_serverinfo_state 2>/dev/null || echo DOWN)"
  xml="$(sunshine_ds_serverinfo)"
  uid="$(sunshine_xml_uniqueid "$xml")"
  helpers="$(helper_pids | tr '\n' ' ')"
  echo "sunshine-ds pid: ${pid:-none}"
  echo "state: $state"
  echo "url: $DS_URL"
  [ -n "$uid" ] && echo "uniqueid: $uid"
  echo "virtual-output helper pid(s): ${helpers:-none}"
}

port_listener_pid() {
  local line
  line="$(ss -ltnp 2>/dev/null | grep -E ':48100\b' | head -1 || true)"
  [ -n "$line" ] || return 0
  printf '%s' "$line" | sed -n 's/.*pid=\([0-9]*\).*/\1/p'
}

ensure_container() {
  if ! command -v podman >/dev/null 2>&1; then
    echo "podman missing; cannot start Distrobox $BOX_NAME."
    return 1
  fi
  if ! podman container exists "$BOX_NAME" 2>/dev/null; then
    record_manual "Create Distrobox $BOX_NAME for sunshine-ds" <<EOF
$ROOT/scripts/040-distrobox-tools.sh
EOF
    echo "Distrobox $BOX_NAME does not exist."
    return 2
  fi
  if ! podman inspect -f '{{.State.Running}}' "$BOX_NAME" 2>/dev/null | grep -qx true; then
    echo "Starting Distrobox $BOX_NAME."
    if ! podman start "$BOX_NAME" >/dev/null; then
      echo "podman start $BOX_NAME failed."
      return 1
    fi
  else
    echo "Distrobox $BOX_NAME already running."
  fi
  return 0
}

ensure_helper() {
  local pids keep extra
  if [ ! -x "$DS_HELPER" ]; then
    echo "Missing helper $DS_HELPER"
    return 1
  fi
  pids="$(helper_pids)"
  if [ -z "$pids" ]; then
    if [ ! -S "${XDG_RUNTIME_DIR}/wayland-0" ] && [ ! -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]; then
      echo "No Wayland socket at ${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}."
      return 2
    fi
    echo "Starting Virtual-sunshine-ds helper."
    nohup "$DS_HELPER" --name sunshine-ds --width 1920 --height 1080 --scale 1 \
      >>"$HELPER_LOG" 2>&1 &
    sleep 0.3
    if [ -z "$(helper_pids)" ]; then
      echo "Helper did not stay running. See $HELPER_LOG"
      return 1
    fi
    echo "Helper pid $(helper_pids | tr '\n' ' ')"
    return 0
  fi
  keep="$(printf '%s\n' "$pids" | awk 'NR==1{print; exit}')"
  extra="$(printf '%s\n' "$pids" | awk 'NR>1')"
  if [ -n "$extra" ]; then
    echo "Extra virtual-output helpers (keeping $keep): $extra"
    # shellcheck disable=SC2086
    kill $extra 2>/dev/null || true
  else
    echo "Virtual-output helper already running ($keep)."
  fi
  return 0
}

stop_ds_if_idle() {
  local state pid leftover
  state="$(sunshine_ds_serverinfo_state 2>/dev/null || echo DOWN)"
  pid="$(ds_pid)"
  if [ "$state" = "BUSY" ] && [ "$DO_FORCE" -eq 0 ]; then
    echo "sunshine-ds is BUSY; not restarting a live stream. Pass --force to drop it."
    return 2
  fi
  if [ -n "$pid" ]; then
    echo "Stopping sunshine-ds pid $pid (helper stays)."
    kill "$pid" 2>/dev/null || true
    local i=0
    while [ "$i" -lt 20 ]; do
      [ -z "$(ds_pid)" ] && break
      sleep 0.2
      i=$((i + 1))
    done
    if [ -n "$(ds_pid)" ]; then
      kill -9 "$(ds_pid)" 2>/dev/null || true
    fi
  fi
  leftover="$(port_listener_pid)"
  if [ -n "$leftover" ] && [ -z "$(ds_pid)" ]; then
    case " $(helper_pids | tr '\n' ' ') " in
      *" $leftover "*) echo "Port 48100 still listed on helper pid $leftover; leaving it." ;;
      *)
        echo "Clearing leftover pid $leftover on :48100."
        kill "$leftover" 2>/dev/null || true
        ;;
    esac
  fi
  return 0
}

stop_helpers() {
  local pids leftover i
  pids="$(helper_pids | tr '\n' ' ')"
  pids="${pids% }"
  if [ -z "$pids" ]; then
    echo "No virtual-output helper running."
    return 0
  fi
  echo "Stopping virtual-output helper(s): $pids"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  i=0
  while [ "$i" -lt 15 ]; do
    [ -z "$(helper_pids)" ] && break
    sleep 0.2
    i=$((i + 1))
  done
  leftover="$(helper_pids | tr '\n' ' ')"
  leftover="${leftover% }"
  if [ -n "$leftover" ]; then
    echo "Force-killing leftover helper(s): $leftover"
    # shellcheck disable=SC2086
    kill -9 $leftover 2>/dev/null || true
  fi
  return 0
}

start_ds() {
  if [ ! -x "$DS_BIN" ]; then
    echo "Missing $DS_BIN"
    return 1
  fi
  if [ ! -f "$DS_CONF" ]; then
    echo "Missing $DS_CONF — start sunshine-ds once so it creates the conf."
    return 2
  fi
  echo "Starting sunshine-ds in Distrobox $BOX_NAME."
  podman exec --user "$UID_NUM" -d "$BOX_NAME" bash -lc \
    "export XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR WAYLAND_DISPLAY=$WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS PIPEWIRE_RUNTIME_DIR=$XDG_RUNTIME_DIR CONFIGURATION_DIRECTORY=$DS_CONFIG_DIR HOME=/home/${STEAMOS_USER:-deck} KWIN_WAYLAND_NO_PERMISSION_CHECKS=1; unset DISPLAY; exec $DS_BIN $DS_CONF >> $DS_LOG 2>&1"
}

wait_for_ds() {
  local waited=0 state
  while [ "$waited" -lt "$WAIT_SECS" ]; do
    state="$(sunshine_ds_serverinfo_state 2>/dev/null || echo DOWN)"
    if [ "$state" = "FREE" ] || [ "$state" = "BUSY" ]; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "sunshine-ds did not answer $DS_URL/serverinfo. See $DS_LOG"
  return 1
}

report_ready() {
  local xml uid decky state pid
  xml="$(sunshine_ds_serverinfo)"
  uid="$(sunshine_xml_uniqueid "$xml")"
  state="$(sunshine_ds_serverinfo_state 2>/dev/null || echo DOWN)"
  pid="$(ds_pid)"
  decky="$(sunshine_xml_uniqueid "$(sunshine_serverinfo)")"
  echo "sunshine-ds is up pid ${pid:-?} $DS_URL ($state)"
  if [ -n "$uid" ] && [ -n "$decky" ] && [ "$uid" = "$decky" ]; then
    echo "uniqueid matches Decky Sunshine — Moonlight may be on the wrong server."
    return 2
  fi
  if [ -n "$uid" ]; then
    echo "dev uniqueid $uid (not Decky :47989)"
  fi
  echo "Connect Moonlight to this host :48100, not Decky :47989."
  return 0
}

if [ "$DO_STATUS" -eq 1 ]; then
  print_status
  state="$(sunshine_ds_serverinfo_state 2>/dev/null || echo DOWN)"
  case "$state" in
    FREE|BUSY) exit 0 ;;
    *) exit 2 ;;
  esac
fi

if [ "$DO_STOP" -eq 1 ]; then
  DO_FORCE=1
  stop_ds_if_idle || true
  stop_helpers
  echo "sunshine-ds torn down for Game Mode (Decky :47989 untouched)."
  print_status
  exit 0
fi

if [ ! -S "${XDG_RUNTIME_DIR}/wayland-0" ] && [ ! -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" ]; then
  record_manual "Export the user session bus before starting sunshine-ds" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u) WAYLAND_DISPLAY=wayland-0
$ROOT/scripts/ensure-sunshine-ds.sh
EOF
  echo "Need a Plasma Wayland session (missing ${WAYLAND_DISPLAY} socket)."
  exit 2
fi

if [ "$DO_RESTART" -eq 0 ] && [ -n "$(ds_pid)" ]; then
  state="$(sunshine_ds_serverinfo_state 2>/dev/null || echo DOWN)"
  if [ "$state" = "FREE" ] || [ "$state" = "BUSY" ]; then
    echo "sunshine-ds already running."
    ensure_helper || true
    report_ready
    exit 0
  fi
  echo "sunshine-ds pid exists but $DS_URL is down; restarting that pid."
  DO_RESTART=1
  DO_FORCE=1
fi

ensure_container || exit $?
ensure_helper || exit $?

if [ "$DO_RESTART" -eq 1 ]; then
  stop_ds_if_idle || exit $?
fi

if [ -z "$(ds_pid)" ]; then
  start_ds || exit $?
else
  echo "sunshine-ds already running pid $(ds_pid)."
fi

wait_for_ds || exit 1
report_ready
exit $?
