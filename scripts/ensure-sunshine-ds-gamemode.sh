#!/usr/bin/env bash
# Isolated Game Mode KMS experiment for sunshine-ds.
# Does not touch Decky (:47989), desktop DS (:48100), or sunshine-ds-dev.
#
#   scripts/ensure-sunshine-ds-gamemode.sh --probe   # start, print capture log, stop
#   scripts/ensure-sunshine-ds-gamemode.sh --status
#   scripts/ensure-sunshine-ds-gamemode.sh --stop
#   scripts/ensure-sunshine-ds-gamemode.sh --start   # only if gamescope is up
#
# Binary is sunshine-ds-kms (copy). Port 48200.
# Second stream: gamescope-virtual (headless gamescope PipeWire) by default.
# SUNSHINE_DS_KMS_DUAL_SOURCE=HDMI-A-1 duplicates the TV; none is single-stream.
# Do not set virtual (KWin helper). Host launch only.
# File caps set AT_SECURE, so ld.so ignores LD_LIBRARY_PATH — RUNPATH + staged
# Fedora libs under ~/.local/lib/sunshine-ds-kms. Never setcap sunshine-ds.
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
KMS_LIB_DIR="${SUNSHINE_DS_KMS_LIB_DIR:-/home/${STEAMOS_USER:-deck}/.local/lib/sunshine-ds-kms}"
KMS_DIR="${SUNSHINE_DS_KMS_CONFIG_DIR:-/home/${STEAMOS_USER:-deck}/.config/sunshine-ds-gamemode}"
KMS_CONF="$KMS_DIR/sunshine/sunshine.conf"
DEV_CONF="${SUNSHINE_DS_CONF:-/home/${STEAMOS_USER:-deck}/.config/sunshine-ds-dev/sunshine/sunshine.conf}"
KMS_PORT="${SUNSHINE_DS_KMS_PORT:-48200}"
KMS_URL="${SUNSHINE_DS_KMS_URL:-http://127.0.0.1:${KMS_PORT}}"
KMS_LOG="${SUNSHINE_DS_KMS_LOG:-$ROOT/logs/sunshine-ds-gamemode.log}"
WAIT_SECS="${SUNSHINE_DS_WAIT_SECS:-20}"

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
  local pid state xml uid desk caps eff
  pid="$(kms_ds_pid)"
  state="$(kms_state 2>/dev/null || true)"; state="${state:-DOWN}"
  xml="$(kms_serverinfo)"
  uid="$(sunshine_xml_uniqueid "$xml")"
  desk="$(desktop_ds_pid)"
  caps="$(getcap "$KMS_BIN" 2>/dev/null || true)"
  echo "sunshine-ds-kms pid: ${pid:-none}"
  echo "state: $state"
  echo "url: $KMS_URL"
  [ -n "$uid" ] && echo "uniqueid: $uid"
  echo "getcap: ${caps:-none (need sudo setcap on this copy only)}"
  if [ -n "$pid" ] && [ -r "/proc/$pid/status" ]; then
    eff="$(grep -E 'CapPrm|CapEff' "/proc/$pid/status" | tr '\n' ' ')"
    echo "caps: $eff"
    # After KMS init Sunshine drops effective caps. CapPrm 0x200000 is SYS_ADMIN.
    if printf '%s' "$eff" | grep -q 'CapPrm:[[:space:]]*0000000000200000' &&
      printf '%s' "$eff" | grep -q 'CapEff:[[:space:]]*0000000000000000'; then
      echo "caps note: CapEff 0 after drop is expected if the log mapped HDMI-A-1."
    fi
  fi
  echo "desktop sunshine-ds pid: ${desk:-none} (must stay on :48100 / kwin)"
  echo "desktop conf: $DEV_CONF"
  if [ -x "${KMS_BIN}.new" ]; then
    echo "staged: ${KMS_BIN}.new ($(getcap "${KMS_BIN}.new" 2>/dev/null || echo 'no cap_sys_admin — sudo setcap then mv over sunshine-ds-kms'))"
  fi
}

run_patchelf() {
  if command -v patchelf >/dev/null 2>&1; then
    patchelf "$@"
    return $?
  fi
  if command -v podman >/dev/null 2>&1; then
    if ! podman inspect -f '{{.State.Running}}' "$BOX_NAME" 2>/dev/null | grep -qx true; then
      podman start "$BOX_NAME" >/dev/null || return 1
    fi
    podman exec "$BOX_NAME" patchelf "$@"
    return $?
  fi
  echo "patchelf missing (host and Distrobox $BOX_NAME)."
  return 1
}

kms_lib_ok() {
  [ -e "$KMS_LIB_DIR/libminiupnpc.so.19" ] &&
    [ -e "$KMS_LIB_DIR/libicudata.so.76" ] &&
    [ -e "$KMS_LIB_DIR/libicui18n.so.76" ] &&
    [ -e "$KMS_LIB_DIR/libicuuc.so.76" ]
}

ensure_kms_libs() {
  local src dest soname
  mkdir -p "$KMS_LIB_DIR"
  if kms_lib_ok; then
    return 0
  fi
  if ! command -v podman >/dev/null 2>&1; then
    echo "Missing Fedora libs in $KMS_LIB_DIR and podman is not available to copy them."
    return 1
  fi
  if ! podman inspect -f '{{.State.Running}}' "$BOX_NAME" 2>/dev/null | grep -qx true; then
    echo "Starting Distrobox $BOX_NAME to copy sunshine-ds-kms libs."
    podman start "$BOX_NAME" >/dev/null || return 1
  fi
  echo "Copying Fedora sonames into $KMS_LIB_DIR (host SteamOS lacks libminiupnpc.so.19)."
  for soname in libminiupnpc.so.19 libicudata.so.76 libicui18n.so.76 libicuuc.so.76; do
    if [ -e "$KMS_LIB_DIR/$soname" ]; then
      continue
    fi
    src="$(podman exec "$BOX_NAME" bash -lc "readlink -f /usr/lib64/$soname 2>/dev/null || readlink -f /usr/lib/$soname")"
    if [ -z "$src" ]; then
      echo "Distrobox $BOX_NAME has no $soname"
      return 1
    fi
    dest="$KMS_LIB_DIR/$(basename "$src")"
    podman cp "$BOX_NAME:$src" "$dest" || return 1
    chmod 0755 "$dest"
    ln -sfn "$(basename "$dest")" "$KMS_LIB_DIR/$soname"
  done
  kms_lib_ok
}

kms_rpath() {
  readelf -d "$KMS_BIN" 2>/dev/null | awk '/RPATH|RUNPATH/ {gsub(/[\[\]]/, "", $NF); print $NF; exit}'
}

ensure_kms_rpath() {
  local current
  current="$(kms_rpath)"
  if [ "$current" = "$KMS_LIB_DIR" ]; then
    return 0
  fi
  echo "Setting RUNPATH $KMS_LIB_DIR on $KMS_BIN (file caps ignore LD_LIBRARY_PATH)."
  run_patchelf --set-rpath "$KMS_LIB_DIR" "$KMS_BIN" || return 1
  echo "patchelf rewrote the ELF; re-apply setcap on this copy only."
  return 0
}

kms_has_sys_admin() {
  getcap "$KMS_BIN" 2>/dev/null | grep -q 'cap_sys_admin'
}

ask_kms_setcap() {
  record_manual "setcap sunshine-ds-kms (Game Mode KMS copy only)" <<EOF
# File capabilities set AT_SECURE: ld.so ignores LD_LIBRARY_PATH.
# RUNPATH is already $KMS_LIB_DIR. Do not export LD_LIBRARY_PATH.
# Never setcap ~/.local/bin/sunshine-ds (desktop Distrobox path).
# If ${KMS_BIN}.new exists (PipeWire video/1 build), cap that copy then replace:
#   sudo setcap cap_sys_admin+ep ${KMS_BIN}.new
#   getcap ${KMS_BIN}.new
#   mv ${KMS_BIN}.new $KMS_BIN
sudo setcap cap_sys_admin+ep $KMS_BIN
getcap $KMS_BIN
# Headless gamescope first, then Game Mode KMS (gamescope-session active):
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
cd $ROOT
./scripts/sunshine-ds-gamemode-virtual.sh --start
./scripts/ensure-sunshine-ds-gamemode.sh --start
# Moonlight: host :48200 (not :48100, not Decky :47989). Pair again if uniqueid is new.
# curl must stay one line:
curl -s --max-time 3 http://127.0.0.1:48200/serverinfo | grep -E 'state|uniqueid|MaxVideo'
EOF
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
  ensure_kms_libs || return 1
  ensure_kms_rpath || return 1
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
# gamescope-virtual = headless gamescope PipeWire on video/1 (not the KWin helper).
# HDMI-A-1 duplicates the TV. none keeps MaxVideoStreams 1. virtual is Plasma-only.
dual_display_source = ${SUNSHINE_DS_KMS_DUAL_SOURCE:-gamescope-virtual}
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
  if ! kms_has_sys_admin; then
    echo "Host $KMS_BIN has no cap_sys_admin (patchelf strips it; Distrobox user ns never has it)."
    ask_kms_setcap
    return 2
  fi
  write_kms_conf
  echo "Starting host sunshine-ds-kms on $KMS_URL (capture=kms, RUNPATH=$KMS_LIB_DIR)."
  mkdir -p "$(dirname "$KMS_LOG")"
  : >"$KMS_LOG"
  # AT_SECURE: do not export LD_LIBRARY_PATH. Unset DISPLAY so KMS is not X11.
  export PIPEWIRE_RUNTIME_DIR="${PIPEWIRE_RUNTIME_DIR:-$XDG_RUNTIME_DIR}"
  export CONFIGURATION_DIRECTORY="$KMS_DIR"
  unset DISPLAY
  unset LD_LIBRARY_PATH
  nohup "$KMS_BIN" "$KMS_CONF" >>"$KMS_LOG" 2>&1 &
  disown || true
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
  grep -E 'KMS|kms|capture|Screencast|monitor|HDMI|Unable to initialize|Probably not permitted|CAP_SYS|Fatal|MaxVideo|shared libraries|not found' "$KMS_LOG" 2>/dev/null | tail -80 || true
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
  echo "Restarting sunshine-ds-kms so sunshine.conf is loaded."
  stop_kms
fi
start_kms || exit $?

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
