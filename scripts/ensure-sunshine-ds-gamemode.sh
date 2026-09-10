#!/usr/bin/env bash
# Isolated Game Mode KMS experiment for sunshine-ds.
# Does not touch Decky (:47989), desktop DS (:48100), or sunshine-ds-dev.
#
#   scripts/ensure-sunshine-ds-gamemode.sh --probe   # start, print capture log, stop
#   scripts/ensure-sunshine-ds-gamemode.sh --status
#   scripts/ensure-sunshine-ds-gamemode.sh --stop    # stop process; keeps the boot unit enabled
#   scripts/ensure-sunshine-ds-gamemode.sh --start   # gamescope up; also enables the boot unit
#   scripts/ensure-sunshine-ds-gamemode.sh --replace-bin  # Distrobox build -> kms, kms unit only
#   scripts/ensure-sunshine-ds-gamemode.sh --promote-new  # mv capped sunshine-ds-kms.new; keep :2
#   scripts/ensure-sunshine-ds-gamemode.sh --start-kms    # start kms unit if cap_sys_admin; keep :2
#   scripts/ensure-sunshine-ds-gamemode.sh               # install/enable boot unit
#   scripts/ensure-sunshine-ds-gamemode.sh --install-service
#
# Binary is sunshine-ds-kms (copy). Port 48200. Starts as user deck (no sudo).
# sudo is only setcap after copying/patchelf. Boot is gamescope-session, not Plasma.
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
# Game Mode is gamescope-0; Plasma is wayland-0. The KMS start script used to
# default wayland-0, which does not exist here — pwgrab then died before it
# attached to the headless gamescope PipeWire node.
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
KMS_SERVICE="${SUNSHINE_DS_KMS_SERVICE:-steamos-sunshine-ds-gamemode.service}"
KMS_VIRTUAL_SERVICE="${SUNSHINE_DS_KMS_VIRTUAL_SERVICE:-steamos-sunshine-ds-gamemode-virtual.service}"
UNIT_DIR="/home/${STEAMOS_USER:-deck}/.config/systemd/user"
RUNNER="$ROOT/scripts/run-sunshine-ds-gamemode.sh"
VIRTUAL_SCRIPT="$ROOT/scripts/sunshine-ds-gamemode-virtual.sh"

DO_STATUS=0
DO_STOP=0
DO_PROBE=0
DO_START=0
DO_FORCE_DESKTOP=0
DO_INSTALL_SERVICE=0
DO_REPLACE_BIN=0
DO_PROMOTE_NEW=0
DO_START_KMS=0
for arg in "$@"; do
  case "$arg" in
    --status) DO_STATUS=1 ;;
    --stop) DO_STOP=1 ;;
    --probe) DO_PROBE=1 ;;
    --start) DO_START=1 ;;
    --install-service) DO_INSTALL_SERVICE=1 ;;
    --force-desktop-kms) DO_FORCE_DESKTOP=1 ;;
    --replace-bin) DO_REPLACE_BIN=1 ;;
    --promote-new) DO_PROMOTE_NEW=1 ;;
    --start-kms) DO_START_KMS=1 ;;
    -h|--help)
      sed -n '2,16p' "$0"
      exit 0
      ;;
    *)
      echo "usage: $0 [--status] [--stop] [--probe] [--start] [--start-kms] [--replace-bin] [--promote-new] [--install-service] [--force-desktop-kms]" >&2
      exit 2
      ;;
  esac
done

if [ "$#" -eq 0 ]; then
  DO_INSTALL_SERVICE=1
fi

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
  echo "unit: $KMS_SERVICE $(systemctl --user is-enabled "$KMS_SERVICE" 2>/dev/null || echo disabled) / $(systemctl --user is-active "$KMS_SERVICE" 2>/dev/null || echo inactive)"
  echo "virtual unit: $KMS_VIRTUAL_SERVICE $(systemctl --user is-enabled "$KMS_VIRTUAL_SERVICE" 2>/dev/null || echo disabled) / $(systemctl --user is-active "$KMS_VIRTUAL_SERVICE" 2>/dev/null || echo inactive)"
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
# Do not cp onto a live kms ELF (ETXTBSY, and cp strips capability xattrs).
# Prefer setcap on the staged copy, then --promote-new (mv keeps the xattr):
# Optional (once): sudoers/zzz-sunshine-ds-kms-setcap (after wheel) so agents can sudo -n.
sudo setcap cap_sys_admin+ep ${KMS_BIN}.new
getcap ${KMS_BIN}.new
# After --replace-bin (or an in-place overwrite), cap the installed copy:
sudo setcap cap_sys_admin+ep $KMS_BIN
getcap $KMS_BIN
# Live Game Mode with headless :2 already up — do not --start:
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/\$(id -u)/bus
cd $ROOT
./scripts/ensure-sunshine-ds-gamemode.sh --start-kms
./scripts/test-gds-lifecycle.sh
# Moonlight: host :48200 (not :48100, not Decky :47989). Pair again if uniqueid is new.
# curl must stay one line:
curl -s --max-time 3 http://127.0.0.1:48200/serverinfo | grep -E 'state|uniqueid|MaxVideo'
# The process is user deck. sudo is only this setcap after copy/patchelf.
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

write_kms_bytes_inplace() {
  # Kernel clears security.capability when an unprivileged process writes
  # the ELF. This only keeps the dest inode (no ETXTBSY after stop).
  python3 - "$1" "$2" <<'PY'
from pathlib import Path
import sys

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
data = src.read_bytes()
with dst.open("r+b") as f:
    f.truncate(0)
    f.write(data)
PY
}

replace_kms_from_build() {
  local src="${SUNSHINE_DS_KMS_SRC:-/home/deck/code/sunshine-ds/build/sunshine}"
  local new="${KMS_BIN}.new"
  if [ ! -x "$src" ]; then
    echo "Missing Distrobox build $src"
    return 1
  fi
  if [ -n "$(desktop_ds_pid)" ]; then
    echo "Desktop sunshine-ds is running. Stop it with ensure-sunshine-ds.sh --stop first."
    return 2
  fi
  ensure_kms_libs || return 1
  install -m 0755 "$src" "$new"
  run_patchelf --set-rpath "$KMS_LIB_DIR" "$new" || return 1
  echo "Staged $new with RUNPATH $KMS_LIB_DIR"
  if [ -n "$(kms_ds_pid)" ]; then
    echo "Stopping $KMS_SERVICE only (headless :2 stays)."
    systemctl --user stop "$KMS_SERVICE" 2>/dev/null || true
    stop_kms_process
  fi
  if [ -f "$KMS_BIN" ]; then
    write_kms_bytes_inplace "$new" "$KMS_BIN"
    chmod 0755 "$KMS_BIN"
  else
    install -m 0755 "$new" "$KMS_BIN"
  fi
  if ! kms_has_sys_admin; then
    echo "Host $KMS_BIN has no cap_sys_admin."
    ask_kms_setcap
    return 2
  fi
  echo "getcap: $(getcap "$KMS_BIN")"
  return 0
}

promote_kms_new() {
  local new="${KMS_BIN}.new"
  if [ ! -x "$new" ]; then
    echo "Missing staged $new"
    return 1
  fi
  if ! getcap "$new" 2>/dev/null | grep -q 'cap_sys_admin'; then
    echo "Staged $new has no cap_sys_admin (inplace write / patchelf strip it)."
    record_manual "setcap sunshine-ds-kms.new then --promote-new" <<EOF
# mv keeps security.capability. Do not cp over the live ELF (strips caps).
# Headless :2 stays; do not --start.
sudo setcap cap_sys_admin+ep $new
getcap $new
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/\$(id -u)/bus
cd $ROOT
./scripts/ensure-sunshine-ds-gamemode.sh --promote-new
EOF
    return 2
  fi
  if [ -n "$(desktop_ds_pid)" ]; then
    echo "Desktop sunshine-ds is running. Stop it with ensure-sunshine-ds.sh --stop first."
    return 2
  fi
  if [ -n "$(kms_ds_pid)" ]; then
    echo "Stopping $KMS_SERVICE only (headless :2 stays)."
    systemctl --user stop "$KMS_SERVICE" 2>/dev/null || true
    stop_kms_process
  fi
  mv -f "$new" "$KMS_BIN"
  chmod 0755 "$KMS_BIN"
  if ! kms_has_sys_admin; then
    echo "mv lost cap_sys_admin on $KMS_BIN."
    ask_kms_setcap
    return 2
  fi
  echo "Promoted $KMS_BIN ($(getcap "$KMS_BIN"))"
  return 0
}

start_kms_unit_only() {
  if [ -n "$(desktop_ds_pid)" ]; then
    echo "Desktop sunshine-ds is running. Stop it with ensure-sunshine-ds.sh --stop first."
    return 2
  fi
  if [ ! -x "$KMS_BIN" ]; then
    echo "Missing $KMS_BIN"
    return 1
  fi
  if ! kms_has_sys_admin; then
    echo "Host $KMS_BIN has no cap_sys_admin (patchelf/cp strip it)."
    ask_kms_setcap
    return 2
  fi
  write_kms_conf
  systemctl --user reset-failed "$KMS_SERVICE" 2>/dev/null || true
  echo "Starting $KMS_SERVICE only (virtual unit / headless :2 stay)."
  systemctl --user start "$KMS_SERVICE"
}

write_kms_conf() {
  bash "$RUNNER" --write-conf
}

gamescope_up() {
  systemctl --user is-active gamescope-session.service >/dev/null 2>&1
}

install_gamemode_units() {
  mkdir -p "$UNIT_DIR" "$ROOT/logs"
  chmod +x "$RUNNER" "$VIRTUAL_SCRIPT" 2>/dev/null || true

  local virtual_unit kms_unit changed=0
  virtual_unit="$(cat <<EOS
[Unit]
Description=SteamOS playbook Game Mode headless gamescope (sunshine-ds-kms video/1)
After=gamescope-session.service pipewire.service
PartOf=gamescope-session.service
StartLimitIntervalSec=600
StartLimitBurst=8

[Service]
Type=oneshot
RemainAfterExit=yes
Nice=10
TimeoutStartSec=30
Environment=HOME=/home/${STEAMOS_USER:-deck}
Environment=XDG_RUNTIME_DIR=/run/user/%U
ExecStart=$VIRTUAL_SCRIPT --start
ExecStop=$VIRTUAL_SCRIPT --stop
StandardOutput=append:$ROOT/logs/sunshine-ds-gamemode-virtual.log
StandardError=append:$ROOT/logs/sunshine-ds-gamemode-virtual.log

[Install]
WantedBy=gamescope-session.target
EOS
)"

  kms_unit="$(cat <<EOS
[Unit]
Description=SteamOS playbook Game Mode sunshine-ds-kms (:48200)
After=gamescope-session.service pipewire.service $KMS_VIRTUAL_SERVICE
Requires=$KMS_VIRTUAL_SERVICE
PartOf=gamescope-session.service
ConditionPathExists=$KMS_BIN
StartLimitIntervalSec=600
StartLimitBurst=8

[Service]
Type=simple
Nice=10
Restart=on-failure
RestartSec=10
RestartPreventExitStatus=2
TimeoutStartSec=60
Environment=HOME=/home/${STEAMOS_USER:-deck}
Environment=XDG_RUNTIME_DIR=/run/user/%U
Environment=CONFIGURATION_DIRECTORY=$KMS_DIR
Environment=PATH=/home/${STEAMOS_USER:-deck}/.local/bin:/usr/bin:/bin
UnsetEnvironment=DISPLAY LD_LIBRARY_PATH
ExecStart=$RUNNER
KillMode=mixed
StandardOutput=append:$KMS_LOG
StandardError=append:$KMS_LOG

[Install]
WantedBy=gamescope-session.target
Also=$KMS_VIRTUAL_SERVICE
EOS
)"

  if [ ! -f "$UNIT_DIR/$KMS_VIRTUAL_SERVICE" ] || [ "$(cat "$UNIT_DIR/$KMS_VIRTUAL_SERVICE")" != "$virtual_unit" ]; then
    printf '%s\n' "$virtual_unit" >"$UNIT_DIR/$KMS_VIRTUAL_SERVICE"
    changed=1
  fi
  if [ ! -f "$UNIT_DIR/$KMS_SERVICE" ] || [ "$(cat "$UNIT_DIR/$KMS_SERVICE")" != "$kms_unit" ]; then
    printf '%s\n' "$kms_unit" >"$UNIT_DIR/$KMS_SERVICE"
    changed=1
  fi
  if [ "$changed" -eq 1 ]; then
    systemctl --user daemon-reload
    echo "Updated $KMS_SERVICE / $KMS_VIRTUAL_SERVICE."
  fi
  if ! systemctl --user is-enabled "$KMS_VIRTUAL_SERVICE" >/dev/null 2>&1; then
    systemctl --user enable "$KMS_VIRTUAL_SERVICE"
    echo "Enabled $KMS_VIRTUAL_SERVICE for gamescope-session.target."
  fi
  if ! systemctl --user is-enabled "$KMS_SERVICE" >/dev/null 2>&1; then
    systemctl --user enable "$KMS_SERVICE"
    echo "Enabled $KMS_SERVICE for gamescope-session.target (starts as deck; sudo is only setcap)."
  else
    echo "$KMS_SERVICE already enabled."
  fi
  return 0
}

stop_kms_process() {
  local pid leftover i
  pid="$(kms_ds_pid)"
  if [ -z "$pid" ]; then
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

stop_kms() {
  if systemctl --user cat "$KMS_SERVICE" >/dev/null 2>&1; then
    echo "Stopping $KMS_SERVICE (unit stays enabled for next Game Mode boot)."
    systemctl --user stop "$KMS_SERVICE" 2>/dev/null || true
  fi
  if systemctl --user cat "$KMS_VIRTUAL_SERVICE" >/dev/null 2>&1; then
    systemctl --user stop "$KMS_VIRTUAL_SERVICE" 2>/dev/null || true
  fi
  stop_kms_process
  bash "$VIRTUAL_SCRIPT" --stop >/dev/null 2>&1 || true
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
  install_gamemode_units
  systemctl --user reset-failed "$KMS_SERVICE" 2>/dev/null || true
  systemctl --user stop "$KMS_SERVICE" 2>/dev/null || true
  stop_kms_process
  echo "Starting $KMS_SERVICE on $KMS_URL (capture=kms, RUNPATH=$KMS_LIB_DIR, WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-unset})."
  mkdir -p "$(dirname "$KMS_LOG")"
  if ! systemctl --user start "$KMS_SERVICE"; then
    echo "systemctl --user start $KMS_SERVICE failed."
    systemctl --user status "$KMS_SERVICE" --no-pager -l || true
    return 1
  fi
  return 0
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
  grep -E 'KMS|kms|capture|Screencast|monitor|HDMI|Unable to initialize|Probably not permitted|CAP_SYS|Fatal|MaxVideo|shared libraries|not found|wayland|pwgrab|PipeWire node|gamescope-virtual' "$KMS_LOG" 2>/dev/null | tail -80 || true
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

if [ "$DO_REPLACE_BIN" -eq 1 ]; then
  replace_kms_from_build
  rc=$?
  if [ "$rc" -eq 0 ]; then
    start_kms_unit_only || exit $?
    if ! wait_for_kms; then
      print_probe_log
      print_status
      assert_desktop_untouched "$BEFORE_HASH" || exit 1
      exit 1
    fi
  fi
  print_status
  assert_desktop_untouched "$BEFORE_HASH" || exit 1
  exit "$rc"
fi

if [ "$DO_PROMOTE_NEW" -eq 1 ]; then
  promote_kms_new
  rc=$?
  if [ "$rc" -eq 0 ]; then
    start_kms_unit_only || exit $?
    if ! wait_for_kms; then
      print_probe_log
      print_status
      assert_desktop_untouched "$BEFORE_HASH" || exit 1
      exit 1
    fi
  fi
  print_status
  assert_desktop_untouched "$BEFORE_HASH" || exit 1
  exit "$rc"
fi

if [ "$DO_START_KMS" -eq 1 ]; then
  start_kms_unit_only || exit $?
  if ! wait_for_kms; then
    print_probe_log
    print_status
    assert_desktop_untouched "$BEFORE_HASH" || exit 1
    exit 1
  fi
  echo "sunshine-ds-kms is up pid $(kms_ds_pid) $KMS_URL ($(kms_state 2>/dev/null || echo DOWN))"
  print_status
  assert_desktop_untouched "$BEFORE_HASH" || exit 1
  exit 0
fi

if [ "$DO_PROBE" -eq 0 ] && [ "$DO_START" -eq 0 ] && [ "$DO_INSTALL_SERVICE" -eq 0 ]; then
  echo "usage: $0 [--probe] [--start] [--start-kms] [--replace-bin] [--install-service] [--status] [--stop]" >&2
  exit 2
fi

if [ "$DO_INSTALL_SERVICE" -eq 1 ] && [ "$DO_START" -eq 0 ] && [ "$DO_PROBE" -eq 0 ]; then
  install_gamemode_units
  if ! gamescope_up && [ "$DO_FORCE_DESKTOP" -eq 0 ]; then
    echo "Unit enabled for gamescope-session.target. Not starting on Plasma (desktop DS stays :48100)."
    print_status
    assert_desktop_untouched "$BEFORE_HASH" || exit 1
    if ! kms_has_sys_admin; then
      ask_kms_setcap
      exit 2
    fi
    exit 0
  fi
  if systemctl --user is-active "$KMS_SERVICE" >/dev/null 2>&1; then
    echo "$KMS_SERVICE already active."
    print_status
    assert_desktop_untouched "$BEFORE_HASH" || exit 1
    exit 0
  fi
  if [ -n "$(desktop_ds_pid)" ]; then
    echo "Desktop sunshine-ds is running. Unit is enabled; it starts on the next gamescope-session (after ensure-sunshine-ds.sh --stop)."
    print_status
    assert_desktop_untouched "$BEFORE_HASH" || exit 1
    exit 0
  fi
  if [ ! -x "$KMS_BIN" ]; then
    ensure_kms_binary || exit $?
  fi
  start_kms || exit $?
  if ! wait_for_kms; then
    print_probe_log
    print_status
    assert_desktop_untouched "$BEFORE_HASH" || exit 1
    exit 1
  fi
  echo "sunshine-ds-kms is up pid $(kms_ds_pid) $KMS_URL ($(kms_state 2>/dev/null || echo DOWN))"
  print_status
  assert_desktop_untouched "$BEFORE_HASH" || exit 1
  exit 0
fi

if [ "$DO_START" -eq 1 ] && [ "$DO_FORCE_DESKTOP" -eq 0 ] && ! gamescope_up; then
  echo "gamescope-session is not active. This experiment is for Game Mode."
  echo "Desktop dual-stream stays on :48100 (capture=kwin). Pass --probe to try KMS on Plasma without keeping it, or --start --force-desktop-kms."
  echo "To only enable the boot unit: $0 --install-service"
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
kms_up="$(kms_ds_pid)"
kms_now="$(kms_state 2>/dev/null || true)"
echo "sunshine-ds-kms is up pid ${kms_up} ${KMS_URL} (${kms_now:-DOWN})"
echo "uniqueid $(sunshine_xml_uniqueid "$xml")"
echo "MaxVideoStreams $(printf '%s' "$xml" | sed -n 's/.*<MaxVideoStreams>\([^<]*\)<\/MaxVideoStreams>.*/\1/p')"
print_probe_log

capture_ok=1
if grep -q 'Unable to initialize capture method' "$KMS_LOG" 2>/dev/null; then
  echo "KMS capture did not initialize (see CAP_SYS_ADMIN / empty monitor list)."
  capture_ok=0
fi

if [ "$DO_PROBE" -eq 1 ]; then
  echo "Probe done; stopping sunshine-ds-kms. Boot unit stays enabled for gamescope-session."
  stop_kms
fi

assert_desktop_untouched "$BEFORE_HASH" || exit 1
print_status
if [ "$capture_ok" -eq 0 ]; then
  exit 1
fi
exit 0
