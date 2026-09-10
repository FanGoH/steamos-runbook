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
# Sidecar: $XDG_RUNTIME_DIR/sunshine-ds-gamemode-virtual (serial/node/size).
# Does not touch :48100, sunshine-ds-dev, or the KWin helper.
# Does not restart gamescope-session.
#
#   scripts/sunshine-ds-gamemode-virtual.sh --start   # gamescope + damaging paint
#   scripts/sunshine-ds-gamemode-virtual.sh --status
#   scripts/sunshine-ds-gamemode-virtual.sh --smoke   # one PNG from the PipeWire node
#   scripts/sunshine-ds-gamemode-virtual.sh --stop
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

DO_STATUS=0
DO_STOP=0
DO_START=0
DO_SMOKE=0
for arg in "$@"; do
  case "$arg" in
    --status) DO_STATUS=1 ;;
    --stop) DO_STOP=1 ;;
    --start) DO_START=1 ;;
    --smoke) DO_SMOKE=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "usage: $0 [--start] [--status] [--smoke] [--stop]" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$ROOT/logs"

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

stop_paint() {
  local pid
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
}

# Static fullscreen publishes one PipeWire buffer then goes silent. Sunshine
# video/1 then encodes dummy_img() black. Keep a moving square so gamescope
# keeps damaging (Cemu/Azahar will do this for real content).
start_paint() {
  local gs_pid x11
  gs_pid="$(virtual_pid || true)"
  if [ -z "${gs_pid:-}" ]; then
    echo "No headless gamescope; not starting paint."
    return 1
  fi
  x11="$(x11_display "$gs_pid")"
  if [ -z "$x11" ]; then
    echo "No Xwayland display for paint."
    return 1
  fi
  if paint_pid >/dev/null; then
    echo "Virtual paint already pid $(paint_pid)."
    return 0
  fi
  # Cemu/Azahar ffplay already damages :2. Smoke paint covers the GamePad stream.
  if command -v xdotool >/dev/null 2>&1 &&
     DISPLAY="$x11" xdotool search --class ffplay >/dev/null 2>&1; then
    echo "ffplay already on $x11; not starting smoke paint."
    return 0
  fi
  # Isolated: inheriting WAYLAND_DISPLAY=gamescope-0 puts this on the TV.
  nohup env -u WAYLAND_DISPLAY DISPLAY="$x11" python3 - >>"$LOG" 2>&1 <<'PY' &
import tkinter as tk

root = tk.Tk()
root.configure(bg="#2244ff")
root.attributes("-fullscreen", True)
root.title("sunshine-ds-kms-virtual")
canvas = tk.Canvas(root, highlightthickness=0, bg="#2244ff")
canvas.pack(fill="both", expand=True)
box = canvas.create_rectangle(0, 0, 160, 160, fill="#ffcc00", outline="")
state = {"x": 40, "dx": 18}


def tick():
    width = max(canvas.winfo_width(), 320)
    height = max(canvas.winfo_height(), 320)
    state["x"] += state["dx"]
    if state["x"] <= 0 or state["x"] >= width - 160:
        state["dx"] *= -1
        state["x"] += state["dx"]
    y = max(height // 2 - 80, 0)
    canvas.coords(box, state["x"], y, state["x"] + 160, y + 160)
    root.after(200, tick)


root.after(50, tick)
root.mainloop()
PY
  printf '%s\n' "$!" >"$PAINT_PIDFILE"
  echo "Virtual paint pid $! on $x11 (damaging so PipeWire keeps emitting)."
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
node=${node}
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
    echo "paint pid: $(paint_pid || echo none)"
    echo "note: KMS cannot capture this plane. Set dual_display_source=gamescope-virtual on sunshine-ds-kms."
  elif [ -n "${pid:-}" ]; then
    echo "pid $pid is not a headless gamescope; ignoring pidfile."
  fi
}

stop_virtual() {
  local pid
  stop_paint
  pid="$(virtual_pid || true)"
  if [ -z "${pid:-}" ]; then
    echo "No headless gamescope virtual display."
    rm -f "$PIDFILE"
    return 0
  fi
  if ! is_headless_gamescope "$pid"; then
    echo "Refusing to kill pid $pid (not --backend headless)."
    return 1
  fi
  echo "Stopping headless gamescope pid $pid."
  kill "$pid" 2>/dev/null || true
  local i=0
  while [ "$i" -lt 20 ]; do
    [ ! -d "/proc/$pid" ] && break
    sleep 0.2
    i=$((i + 1))
  done
  if [ -d "/proc/$pid" ]; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
  rm -f "$NODEFILE"
  return 0
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
  # Isolated from the session compositor. Do not inherit WAYLAND_DISPLAY=gamescope-0
  # (that nests a window on the TV) or wayland-0 (missing in Game Mode).
  nohup env -u WAYLAND_DISPLAY -u DISPLAY \
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

if [ "$DO_START" -eq 1 ]; then
  start_virtual || exit $?
  exit 0
fi

echo "usage: $0 [--start] [--status] [--smoke] [--stop]" >&2
exit 2
