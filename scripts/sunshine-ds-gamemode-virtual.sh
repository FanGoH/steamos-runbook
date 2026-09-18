#!/usr/bin/env bash
# Game Mode virtual display for sunshine-ds-kms (:48200).
#
# Desktop DS uses KWin sunshine-ds-virtual-output (zkde_screencast). Gamescope
# has no that protocol — the helper prints "not in the registry".
#
# This holds a *headless* gamescope instead: Wayland gamescope-1, Xwayland :2,
# PipeWire Video/Source. KMS cannot see that plane. sunshine-ds-kms video/1
# grabs the node when dual_display_source = gamescope-virtual.
#
# Sidecar: $XDG_RUNTIME_DIR/sunshine-ds-gamemode-virtual (serial/size).
# Do not write `node=<id>`: sunshine-ds-kms built from f8d9968c then skips
# AUTOCONNECT + TARGET_OBJECT, and video/1 stays dummy_img() black. Sep 9
# checkpoint 119d7452 links by object.serial. Keep the node id as `pw_node=`.
# Does not touch :48100, sunshine-ds-dev, or the KWin helper.
# Does not restart gamescope-session.
#
#   scripts/sunshine-ds-gamemode-virtual.sh --start   # gamescope + idle screensaver
#   scripts/sunshine-ds-gamemode-virtual.sh --paint   # restart screensaver only (:2 stays)
#   scripts/sunshine-ds-gamemode-virtual.sh --recover # one-shot: start :2 / paint clock if prefs on
#   scripts/sunshine-ds-gamemode-virtual.sh --watch   # loop --recover (Game Mode user unit)
#   scripts/sunshine-ds-gamemode-virtual.sh --status
#   scripts/sunshine-ds-gamemode-virtual.sh --smoke   # one PNG from the PipeWire node
#   scripts/sunshine-ds-gamemode-virtual.sh --stop
# QAM Second screen Off writes ~/.config/sunshine-ds-gamemode/virtual-output
# (off) so --start is a no-op until the toggle is on again.
# Empty :2 (no clock, no ffplay) encodes dummy-black; --watch paints it back.
# Start headless from its own cwd with a `mangoapp` ftok file so it does not
# share Steam's mangoapp SysV queue (1080p outputWidth 1/4-flashes preset 2).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

LOG="${SUNSHINE_DS_KMS_VIRTUAL_LOG:-$ROOT/logs/sunshine-ds-gamemode-virtual.log}"
PIDFILE="${SUNSHINE_DS_KMS_VIRTUAL_PIDFILE:-$ROOT/logs/sunshine-ds-gamemode-virtual.pid}"
PAINT_PIDFILE="${SUNSHINE_DS_KMS_VIRTUAL_PAINT_PIDFILE:-$ROOT/logs/sunshine-ds-gamemode-virtual-paint.pid}"
SMOKE_PNG="${SUNSHINE_DS_KMS_VIRTUAL_SMOKE:-$ROOT/logs/sunshine-ds-gamemode-virtual.png}"
NODEFILE="${SUNSHINE_DS_GAMESCOPE_VIRTUAL_FILE:-${XDG_RUNTIME_DIR}/sunshine-ds-gamemode-virtual}"
WIDTH="${SUNSHINE_DS_KMS_VIRTUAL_WIDTH:-1920}"
HEIGHT="${SUNSHINE_DS_KMS_VIRTUAL_HEIGHT:-1080}"
# ftok("mangoapp") is cwd-relative. Steam mangoapp uses the session cwd; this
# file gives headless a different IPC key so 1080p frames do not resize HDMI HUD.
HEADLESS_CWD="${SUNSHINE_DS_KMS_VIRTUAL_CWD:-${XDG_RUNTIME_DIR}/sunshine-ds-gamemode-headless}"
WATCH_SECS="${SUNSHINE_DS_KMS_VIRTUAL_WATCH_SECS:-3}"
VIRTUAL_OUTPUT_PREF="${SUNSHINE_DS_VIRTUAL_OUTPUT_PREF:-${HOME:-/home/deck}/.config/sunshine-ds-gamemode/virtual-output}"
SCREENSAVER_PREF="${SUNSHINE_DS_SCREENSAVER_PREF:-${HOME:-/home/deck}/.config/sunshine-ds-gamemode/screensaver}"

DO_STATUS=0
DO_STOP=0
DO_START=0
DO_SMOKE=0
DO_PAINT=0
DO_RECOVER=0
DO_WATCH=0
for arg in "$@"; do
  case "$arg" in
    --status) DO_STATUS=1 ;;
    --stop) DO_STOP=1 ;;
    --start) DO_START=1 ;;
    --paint) DO_PAINT=1 ;;
    --recover) DO_RECOVER=1 ;;
    --watch) DO_WATCH=1 ;;
    --smoke) DO_SMOKE=1 ;;
    -h|--help)
      sed -n '2,26p' "$0"
      exit 0
      ;;
    *)
      echo "usage: $0 [--start] [--paint] [--recover] [--watch] [--status] [--smoke] [--stop]" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$ROOT/logs"

_on_off_pref() {
  local file="$1" raw
  if [ ! -f "$file" ]; then
    echo on
    return 0
  fi
  raw="$(tr -d '[:space:]' <"$file" 2>/dev/null | tr '[:upper:]' '[:lower:]')"
  case "$raw" in
    off|0|false|no|pause) echo off ;;
    *) echo on ;;
  esac
}

virtual_output_pref() {
  _on_off_pref "$VIRTUAL_OUTPUT_PREF"
}

screensaver_pref() {
  _on_off_pref "$SCREENSAVER_PREF"
}

virtual_pid() {
  local pid
  if [ -f "$PIDFILE" ]; then
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
      printf '%s\n' "$pid"
      return 0
    fi
  fi
  return 1
}

is_headless_gamescope() {
  local pid="$1" cmd
  [ -r "/proc/$pid/cmdline" ] || return 1
  cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline")"
  case "$cmd" in
    *'--backend headless'*) return 0 ;;
    *) return 1 ;;
  esac
}

wayland_name() {
  sed -n "s/.*Running compositor on wayland display '\([^']*\)'.*/\1/p" "$LOG" | tail -1
}

x11_display() {
  sed -n 's/.*Starting Xwayland on :\([0-9][0-9]*\).*/:\1/p' "$LOG" | tail -1
}

pw_node_for_pid() {
  local pid="$1" logged=""
  python3 - "$pid" <<'PY'
import json, subprocess, sys
want = sys.argv[1]
data = json.loads(subprocess.check_output(["pw-dump"]))
client_ids = {
    str(obj.get("id"))
    for obj in data
    if obj.get("type") == "PipeWire:Interface:Client"
    and str(((obj.get("info") or {}).get("props") or {}).get("application.process.id") or "") == want
}
for obj in data:
    if obj.get("type") != "PipeWire:Interface:Node":
        continue
    props = (obj.get("info") or {}).get("props") or {}
    if props.get("media.class") != "Video/Source":
        continue
    if str(props.get("client.id") or "") not in client_ids:
        continue
    print(obj.get("id"), props.get("object.serial") or "", props.get("node.name") or "")
    break
PY
}

paint_pid() {
  local pid
  if [ -f "$PAINT_PIDFILE" ]; then
    pid="$(cat "$PAINT_PIDFILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
      printf '%s\n' "$pid"
      return 0
    fi
  fi
  return 1
}

# Steam's reaper waitpid()s every descendant in app-steam-app*.scope.
# A leftover clock there is the Azahar "Exiting…" hang.
in_steam_tile_cgroup() {
  local proc="${1:-self}"
  grep -q 'app-steam-app' "/proc/${proc}/cgroup" 2>/dev/null
}

# Leftover GamePad x11grab keeps the last frame on :2 after Cemu exits.
# pgrep -x ffplay, then inspect argv / DISPLAY — never pgrep -f sunshine.
kill_x11grab_ffplay() {
  local x11="${1:-}" pid cmd disp
  if [ -z "$x11" ]; then
    x11="$(x11_display || true)"
  fi
  [ -n "$x11" ] || x11=":2"
  command -v pgrep >/dev/null 2>&1 || return 0
  for pid in $(pgrep -x ffplay || true); do
    [ -r "/proc/$pid/cmdline" ] || continue
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    case "$cmd" in
      *x11grab*) ;;
      *) continue ;;
    esac
    disp="$(tr '\0' '\n' <"/proc/$pid/environ" 2>/dev/null | sed -n 's/^DISPLAY=//p' | head -1 || true)"
    case "$disp" in
      "$x11"|"${x11}.0"|":2"|":2.0")
        echo "Stopping leftover x11grab ffplay pid $pid on ${disp:-?}."
        kill "$pid" 2>/dev/null || true
        ;;
    esac
  done
}

stop_paint() {
  local pid x11
  pid="$(paint_pid || true)"
  if [ -n "${pid:-}" ]; then
    kill "$pid" 2>/dev/null || true
    local i=0
    while [ "$i" -lt 10 ] && [ -d "/proc/$pid" ]; do
      sleep 0.1
      i=$((i + 1))
    done
    if [ -d "/proc/$pid" ]; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$PAINT_PIDFILE"
  # Leftover Tk stays mapped after the python pid dies and covers :2.
  x11="$(x11_display || true)"
  if [ -n "${x11:-}" ] && command -v xdotool >/dev/null 2>&1; then
    DISPLAY="$x11" xdotool search --name 'sunshine-ds-kms-virtual' windowkill 2>/dev/null || true
  fi
}

# Static fullscreen publishes one PipeWire buffer then goes silent. Sunshine
# video/1 then encodes dummy_img() black. Keep damaging :2 when idle
# (Cemu/Azahar ffplay does this for real GamePad content). Title stays
# sunshine-ds-kms-virtual so existing windowkill paths still work.
start_paint() {
  local gs_pid x11 saver pid
  if [ "$(screensaver_pref)" = off ]; then
    echo "Screensaver disabled; not painting :2."
    return 0
  fi
  gs_pid="$(virtual_pid || true)"
  if [ -z "${gs_pid:-}" ]; then
    echo "No headless gamescope; not starting screensaver."
    return 1
  fi
  x11="$(x11_display "$gs_pid")"
  if [ -z "$x11" ]; then
    echo "No Xwayland display for screensaver."
    return 1
  fi
  if paint_pid >/dev/null; then
    pid="$(paint_pid)"
    if in_steam_tile_cgroup "$pid"; then
      echo "Bottom screensaver pid $pid is in a Steam tile cgroup; restarting."
      stop_paint
    else
      echo "Bottom screensaver already pid $pid."
      present_idle_screensaver "$x11" || true
      return 0
    fi
  fi
  # Live Cemu/Azahar ffplay already damages :2. A mapped Tk covers the GamePad.
  # --paint kills leftover x11grab first so this skip does not freeze the clock.
  if command -v xdotool >/dev/null 2>&1 &&
     timeout 1 env DISPLAY="$x11" xdotool search --class ffplay >/dev/null 2>&1; then
    echo "ffplay already on $x11; not starting screensaver."
    return 0
  fi
  saver="$ROOT/scripts/sunshine-ds-bottom-screensaver.py"
  if [ ! -f "$saver" ]; then
    echo "Missing $saver"
    return 1
  fi
  # Isolated: inheriting WAYLAND_DISPLAY=gamescope-0 puts this on the TV.
  # --paint hops out of Steam's reaper via systemd-run (see DO_PAINT).
  # setsid here is only extra isolation for the in-process fallback.
  setsid env -u WAYLAND_DISPLAY DISPLAY="$x11" \
    python3 "$saver" --display "$x11" >>"$LOG" 2>&1 </dev/null &
  printf '%s\n' "$!" >"$PAINT_PIDFILE"
  disown $! 2>/dev/null || true
  echo "Bottom screensaver pid $! on $x11 (idle clock; withdraws for ffplay)."
  present_idle_screensaver "$x11" || true
}

# PipeWire / Moonlight video/1 encodes the gamescope root. A mapped Tk with
# pixels is still black on Thor until it is GAMESCOPECTRL_BASELAYER_WINDOW.
present_idle_screensaver() {
  local x11="${1:-}" wid i
  if [ -z "$x11" ]; then
    x11="$(x11_display "$(virtual_pid || true)" || true)"
  fi
  [ -n "$x11" ] || return 1
  command -v xdotool >/dev/null 2>&1 || return 1
  for i in 1 2 3 4 5 6 7 8 9 10; do
    wid="$(DISPLAY="$x11" xdotool search --name 'sunshine-ds-kms-virtual' 2>/dev/null | head -1 || true)"
    if [ -n "${wid:-}" ]; then
      DISPLAY="$x11" xdotool windowmap "$wid" windowraise "$wid" 2>/dev/null || true
      DISPLAY="$x11" xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW "$wid" 2>/dev/null || true
      DISPLAY="$x11" xprop -root -f GAMESCOPECTRL_BASELAYER_WINDOW 32c -set GAMESCOPECTRL_BASELAYER_WINDOW "$wid" 2>/dev/null || true
      return 0
    fi
    sleep 0.1
  done
  return 1
}

pad_has_ffplay() {
  local x11="${1:-}"
  [ -n "$x11" ] || x11="$(x11_display || true)"
  [ -n "$x11" ] || x11=":2"
  command -v xdotool >/dev/null 2>&1 || return 1
  timeout 1 env DISPLAY="$x11" xdotool search --class ffplay >/dev/null 2>&1
}

emu_running() {
  pgrep -x cemu >/dev/null 2>&1 && return 0
  pgrep -x azahar >/dev/null 2>&1 && return 0
  pgrep -x Cemu-wrapper >/dev/null 2>&1 && return 0
  return 1
}

xid_dec() {
  printf '%d' "$1" 2>/dev/null || printf '%s' "$1"
}

baselayer_xid() {
  DISPLAY="${1:-:2}" xprop -root GAMESCOPECTRL_BASELAYER_WINDOW 2>/dev/null \
    | awk -F'= ' '{print $2}' | tr -d ' '
}

idle_clock_present() {
  local x11="${1:-}" wid
  [ -n "$x11" ] || x11="$(x11_display || true)"
  [ -n "$x11" ] || x11=":2"
  paint_pid >/dev/null && return 0
  command -v xdotool >/dev/null 2>&1 || return 1
  wid="$(timeout 1 env DISPLAY="$x11" xdotool search --name 'sunshine-ds-kms-virtual' 2>/dev/null | head -1 || true)"
  [ -n "${wid:-}" ]
}

present_ffplay_baselayer() {
  local x11="${1:-}" wid want cur
  [ -n "$x11" ] || x11="$(x11_display || true)"
  [ -n "$x11" ] || x11=":2"
  command -v xdotool >/dev/null 2>&1 || return 1
  wid="$(timeout 1 env DISPLAY="$x11" xdotool search --class ffplay 2>/dev/null | tail -1 || true)"
  [ -n "${wid:-}" ] || return 1
  # Headless gamescope remaps SDL ffplay at 640x480 after a kms restart.
  # Skipping this when BASELAYER already points at ffplay left Thor's
  # GamePad panel looking tiny (640x480 in a 1920x1080 stream).
  DISPLAY="$x11" xdotool windowmap "$wid" 2>/dev/null || true
  x11_resize_if_needed "$x11" "$wid" "$WIDTH" "$HEIGHT"
  x11_move_if_needed "$x11" "$wid" 0 0
  want="$(xid_dec "$wid")"
  cur="$(baselayer_xid "$x11")"
  if [ -n "$cur" ] && [ "$cur" = "$want" ]; then
    return 0
  fi
  DISPLAY="$x11" xdotool windowraise "$wid" 2>/dev/null || true
  DISPLAY="$x11" xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW "$want" 2>/dev/null || true
  DISPLAY="$x11" xprop -root -f GAMESCOPECTRL_BASELAYER_WINDOW 32c -set GAMESCOPECTRL_BASELAYER_WINDOW "$want" 2>/dev/null || true
}

# Pref on + :2 missing → start. Pref on + empty :2 (no ffplay, no clock) → paint.
# Live Cemu/Azahar ffplay: drop a competing Tk clock (withdrawn windows still
# trip the Cemu watcher) and keep ffplay as BASELAYER. Leftover x11grab with
# no emu → kill, then paint. Screensaver Off stops a leftover clock.
# Never --start kms. Never pgrep -f sunshine.
recover_virtual() {
  if [ "$(virtual_output_pref)" != on ]; then
    return 0
  fi
  local pid x11
  pid="$(virtual_pid || true)"
  if [ -z "${pid:-}" ] || ! is_headless_gamescope "$pid"; then
    echo "Recover: headless :2 gone; starting."
    start_virtual || return 1
    return 0
  fi
  write_nodefile || true
  x11="$(x11_display || true)"
  x11="${x11:-:2}"
  if pad_has_ffplay "$x11"; then
    if emu_running; then
      if idle_clock_present "$x11"; then
        echo "Recover: live GamePad mirror; dropping idle clock."
        stop_paint
      fi
      present_ffplay_baselayer "$x11" || true
      return 0
    fi
    echo "Recover: leftover x11grab on $x11 with no Cemu/Azahar; painting."
    kill_x11grab_ffplay "$x11"
    if command -v xdotool >/dev/null 2>&1; then
      timeout 1 env DISPLAY="$x11" xdotool search --class ffplay windowkill 2>/dev/null || true
    fi
    start_paint || true
    return 0
  fi
  if [ "$(screensaver_pref)" = off ]; then
    if paint_pid >/dev/null; then
      echo "Recover: screensaver pref off; stopping leftover clock."
      stop_paint
    fi
    return 0
  fi
  if paint_pid >/dev/null; then
    present_idle_screensaver "$x11" || true
    return 0
  fi
  echo "Recover: idle clock missing on $x11; painting."
  start_paint || true
}

watch_virtual() {
  echo "Watching :2 / idle clock every ${WATCH_SECS}s."
  while true; do
    recover_virtual || true
    sleep "$WATCH_SECS"
  done
}

write_nodefile() {
  local pid node_info node serial
  pid="$(virtual_pid || true)"
  if [ -z "${pid:-}" ]; then
    rm -f "$NODEFILE"
    return 1
  fi
  node_info="$(pw_node_for_pid "$pid" | head -1)"
  node="$(printf '%s\n' "$node_info" | awk '{print $1}')"
  serial="$(printf '%s\n' "$node_info" | awk '{print $2}')"
  if [ -z "$serial" ] && [ -z "$node" ]; then
    rm -f "$NODEFILE"
    return 1
  fi
  umask 077
  cat >"$NODEFILE" <<EOF
serial=${serial}
pw_node=${node}
width=${WIDTH}
height=${HEIGHT}
wayland=$(wayland_name || true)
x11=$(x11_display || true)
pid=${pid}
EOF
}

print_status() {
  local pid wl x11 node
  pid="$(virtual_pid || true)"
  echo "headless gamescope pid: ${pid:-none}"
  echo "second screen: $(virtual_output_pref)"
  echo "screensaver: $(screensaver_pref)"
  echo "pidfile: $PIDFILE"
  echo "log: $LOG"
  echo "sidecar: $NODEFILE"
  if [ -n "${pid:-}" ] && is_headless_gamescope "$pid"; then
    wl="$(wayland_name "$pid" || true)"
    x11="$(x11_display "$pid" || true)"
    node="$(pw_node_for_pid "$pid" | head -1 || true)"
    write_nodefile || true
    echo "wayland: ${wl:-unknown}"
    echo "x11: ${x11:-unknown}"
    echo "pipewire: ${node:-none}"
    echo "screensaver pid: $(paint_pid || echo none)"
    echo "note: KMS cannot capture this plane. Set dual_display_source=gamescope-virtual on sunshine-ds-kms."
  elif [ -n "${pid:-}" ]; then
    echo "pid $pid is not a headless gamescope; ignoring pidfile."
  fi
}

stop_virtual() {
  local pid p i
  stop_paint
  pid="$(virtual_pid || true)"
  # Reap every --backend headless gamescope. Recover --watch can start a
  # second copy on the next display while pidfile still points at the first.
  for p in $(pgrep -x gamescope || true); do
    if is_headless_gamescope "$p"; then
      echo "Stopping headless gamescope pid $p."
      kill "$p" 2>/dev/null || true
    fi
  done
  i=0
  while [ "$i" -lt 20 ]; do
    leftover=0
    for p in $(pgrep -x gamescope || true); do
      if is_headless_gamescope "$p"; then
        leftover=1
        break
      fi
    done
    [ "$leftover" -eq 0 ] && break
    sleep 0.2
    i=$((i + 1))
  done
  for p in $(pgrep -x gamescope || true); do
    if is_headless_gamescope "$p"; then
      kill -9 "$p" 2>/dev/null || true
    fi
  done
  if [ -n "${pid:-}" ] && [ -d "/proc/$pid" ] && ! is_headless_gamescope "$pid"; then
    echo "Refusing to kill pid $pid (not --backend headless)."
    return 1
  fi
  rm -f "$PIDFILE"
  rm -f "$NODEFILE"
  return 0
}

# A new headless gamescope gets a new PipeWire object.serial. Live kms keeps
# AUTOCONNECT on the old serial; PipeWire then negotiates session gamescope-0
# (HDMI 4K) and Thor bottom duplicates the TV. Restart kms only — never
# --start (that KillModes :2).
rebind_kms_video1() {
  local unit="${SUNSHINE_DS_KMS_SERVICE:-steamos-sunshine-ds-gamemode.service}"
  if ! systemctl --user is-active "$unit" >/dev/null 2>&1; then
    return 0
  fi
  echo "Rebinding $unit video/1 to sidecar serial (keep :2)."
  systemctl --user restart "$unit"
}

start_virtual() {
  local pid
  pid="$(virtual_pid || true)"
  if [ -n "${pid:-}" ] && is_headless_gamescope "$pid"; then
    echo "Already running pid $pid."
    start_paint || true
    print_status
    return 0
  fi
  if ! command -v gamescope >/dev/null 2>&1; then
    echo "gamescope missing."
    return 1
  fi
  : >"$LOG"
  mkdir -p "$HEADLESS_CWD"
  : >"$HEADLESS_CWD/mangoapp"
  # Isolated from the session compositor. Do not inherit WAYLAND_DISPLAY=gamescope-0
  # (that nests a window on the TV) or wayland-0 (missing in Game Mode).
  # cwd + mangoapp file: separate ftok key from Steam's mangoapp queue.
  nohup env -u WAYLAND_DISPLAY -u DISPLAY -u STEAM_USE_MANGOAPP --chdir="$HEADLESS_CWD" \
    gamescope --backend headless -W "$WIDTH" -H "$HEIGHT" --xwayland-count 1 \
    -- sleep infinity >>"$LOG" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" >"$PIDFILE"
  local waited=0
  while [ "$waited" -lt 8 ]; do
    if grep -q 'stream available on node ID' "$LOG" 2>/dev/null; then
      echo "Started headless gamescope pid $pid."
      start_paint || true
      print_status
      rebind_kms_video1 || true
      return 0
    fi
    if [ ! -d "/proc/$pid" ]; then
      echo "headless gamescope exited. See $LOG"
      rm -f "$PIDFILE"
      return 1
    fi
    sleep 0.25
    waited=$((waited + 1))
  done
  echo "headless gamescope pid $pid started; PipeWire line not seen yet. See $LOG"
  start_paint || true
  print_status
  rebind_kms_video1 || true
  return 0
}

smoke() {
  local pid x11 node_id
  start_virtual || return 1
  pid="$(virtual_pid)" || return 1
  x11="$(x11_display "$pid")"
  if [ -z "$x11" ]; then
    echo "No Xwayland display in $LOG"
    return 1
  fi
  node_info="$(pw_node_for_pid "$pid" | head -1)"
  node_id="$(printf '%s\n' "$node_info" | awk '{print $1}')"
  node_serial="$(printf '%s\n' "$node_info" | awk '{print $2}')"
  if [ -z "$node_id" ]; then
    echo "No PipeWire Video/Source for pid $pid"
    return 1
  fi
  echo "Drawing blue fullscreen on $x11, grabbing PipeWire node $node_id serial $node_serial."
  DISPLAY="$x11" python3 - <<'PY' &
import tkinter as tk
r = tk.Tk()
r.configure(bg="#2244ff")
r.attributes("-fullscreen", True)
r.title("sunshine-ds-kms-virtual")
r.after(8000, r.destroy)
r.mainloop()
PY
  local py=$!
  sleep 1.2
  rm -f "$SMOKE_PNG"
  if ! timeout 8 gst-launch-1.0 -e \
    "pipewiresrc" "target-object=$node_serial" do-timestamp=true num-buffers=6 \
    ! videoconvert \
    ! pngenc snapshot=true \
    ! filesink "location=$SMOKE_PNG" >>"$LOG" 2>&1; then
    echo "gst-launch pipewiresrc target-object=$node_serial failed. See $LOG"
    kill "$py" 2>/dev/null || true
    return 1
  fi
  kill "$py" 2>/dev/null || true
  wait "$py" 2>/dev/null || true
  if [ ! -s "$SMOKE_PNG" ]; then
    echo "Smoke PNG missing: $SMOKE_PNG"
    return 1
  fi
  echo "Wrote $SMOKE_PNG ($(wc -c <"$SMOKE_PNG") bytes)"
  file "$SMOKE_PNG"
  return 0
}

if [ "$DO_STATUS" -eq 1 ]; then
  print_status
  pid="$(virtual_pid || true)"
  if [ -n "${pid:-}" ] && is_headless_gamescope "$pid"; then
    exit 0
  fi
  exit 2
fi

if [ "$DO_STOP" -eq 1 ]; then
  stop_virtual
  print_status
  exit 0
fi

if [ "$DO_SMOKE" -eq 1 ]; then
  smoke || exit 1
  exit 0
fi

# Steam's reaper is a subreaper and waitpid()s every descendant in the
# tile cgroup. setsid/disown do not leave app-steam-app*.scope, so a clock
# started from rom-launcher / --quit / inhibit-in-tile leaves Steam on
# "Exiting…". Hop the whole --paint oneshot onto the user bus; KillMode=
# process so the Tk child survives after this script exits.
#
# --collect leaves the transient fragment loaded after the oneshot dies.
# Reusing --unit=sunshine-ds-bottom-paint then fails ("already loaded or
# has a fragment file") and the old fallback started the clock in-process
# inside the tile. Drop that leftover before systemd-run. --no-block so a
# timeout --paint cannot SIGTERM the hop and fall through in-tile.
drop_paint_unit() {
  systemctl --user stop sunshine-ds-bottom-paint.service 2>/dev/null || true
  systemctl --user reset-failed sunshine-ds-bottom-paint.service 2>/dev/null || true
  rm -f "${XDG_RUNTIME_DIR}/systemd/transient/sunshine-ds-bottom-paint.service"
  systemctl --user daemon-reload 2>/dev/null || true
}

paint_outside_steam_scope() {
  if ! command -v systemd-run >/dev/null 2>&1; then
    return 1
  fi
  drop_paint_unit
  systemd-run --user --collect --quiet --no-block \
    --unit=sunshine-ds-bottom-paint \
    --property=Type=oneshot \
    --property=KillMode=process \
    --setenv=SUNSHINE_DS_PAINT_INNER=1 \
    --setenv=XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR}" \
    --setenv=HOME="${HOME:-/home/deck}" \
    --setenv=DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}" \
    /bin/bash "$ROOT/scripts/sunshine-ds-gamemode-virtual.sh" --paint
}

if [ "$DO_PAINT" -eq 1 ]; then
  # Hop out of Steam tiles only. QAM / agent --paint must stay in-process
  # (setsid + disown) so the clock actually maps; systemd-run --no-block
  # used to return before Tk existed and Thor stayed dummy-black.
  if [ -z "${SUNSHINE_DS_PAINT_INNER:-}" ] && in_steam_tile_cgroup self; then
    if paint_outside_steam_scope; then
      echo "Bottom screensaver armed outside Steam scope."
      exit 0
    fi
    echo "systemd-run --paint unavailable; refusing in-process --paint inside a Steam tile."
    exit 1
  fi
  # Frozen GamePad after Cemu exit is leftover x11grab on :2. Kill it
  # before start_paint's "ffplay already here" skip.
  x11="$(x11_display || true)"
  kill_x11grab_ffplay "${x11:-:2}"
  if [ -n "${x11:-}" ] && command -v xdotool >/dev/null 2>&1; then
    timeout 1 env DISPLAY="$x11" xdotool search --class ffplay windowkill 2>/dev/null || true
  fi
  stop_paint
  if [ "$(screensaver_pref)" = off ]; then
    echo "Screensaver disabled; not painting :2."
    print_status
    exit 0
  fi
  start_paint || exit $?
  print_status
  exit 0
fi

if [ "$DO_START" -eq 1 ]; then
  if [ "$(virtual_output_pref)" = off ]; then
    echo "Second screen disabled; not starting headless :2."
    stop_virtual || true
    print_status
    exit 0
  fi
  start_virtual || exit $?
  exit 0
fi

if [ "$DO_RECOVER" -eq 1 ]; then
  recover_virtual || exit $?
  print_status
  exit 0
fi

if [ "$DO_WATCH" -eq 1 ]; then
  watch_virtual
  exit 0
fi

echo "usage: $0 [--start] [--paint] [--recover] [--watch] [--status] [--smoke] [--stop]" >&2
exit 2
