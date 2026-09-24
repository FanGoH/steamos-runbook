#!/usr/bin/env bash
# Fullscreen HDMI capture from the MacroSilicon MS2109 card (Switch 2 feed).
# Host ffplay + V4L2. Optional: SWITCH2_CAPTURE_DEV=/dev/videoN
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${SWITCH2_CAPTURE_LOG_DIR:-$ROOT/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/switch2-capture-viewer.log"
HELPER="$ROOT/scripts/hide-controllers-sysfs.sh"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/switch2-capture-viewer.lock"

# Steam non-Steam launches inject a runtime that breaks host V4L2/ffplay.
unset LD_PRELOAD || true
export LD_LIBRARY_PATH=""
export STEAM_RUNTIME="${STEAM_RUNTIME:-0}"
export PATH="/usr/bin:/bin:${PATH:-}"

USB_VID="${SWITCH2_CAPTURE_USB_VID:-534d}"
USB_PID="${SWITCH2_CAPTURE_USB_PID:-2109}"
# MS2109 is USB2: 1080p60 MJPEG only delivers ~30fps. 720p60 is real 60fps.
WIDTH="${SWITCH2_CAPTURE_WIDTH:-1280}"
HEIGHT="${SWITCH2_CAPTURE_HEIGHT:-720}"
FPS="${SWITCH2_CAPTURE_FPS:-60}"

log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG" >&2; }

find_capture_dev() {
  local vd resolved parent vid pid
  if [ -n "${SWITCH2_CAPTURE_DEV:-}" ]; then
    printf '%s\n' "$SWITCH2_CAPTURE_DEV"
    return 0
  fi
  for vd in /sys/class/video4linux/video*; do
    [ -e "$vd" ] || continue
    resolved="$(readlink -f "$vd" 2>/dev/null || true)"
    [ -n "$resolved" ] || resolved="$vd"
    parent="$resolved"
    vid="" pid=""
    while [ "$parent" != "/" ]; do
      if [ -f "$parent/idVendor" ]; then
        vid="$(cat "$parent/idVendor")"
        pid="$(cat "$parent/idProduct")"
        break
      fi
      parent="$(dirname "$parent")"
    done
    if [ "$vid" = "$USB_VID" ] && [ "$pid" = "$USB_PID" ]; then
      if v4l2-ctl -d "/dev/${vd##*/}" --list-formats-ext 2>/dev/null | grep -qE 'MJPG|Motion-JPEG|YUYV'; then
        printf '%s\n' "/dev/${vd##*/}"
        return 0
      fi
    fi
  done
  for vd in /sys/class/video4linux/video*; do
    [ -e "$vd" ] || continue
    resolved="$(readlink -f "$vd" 2>/dev/null || true)"
    [ -n "$resolved" ] || resolved="$vd"
    parent="$resolved"
    while [ "$parent" != "/" ]; do
      if [ -f "$parent/idVendor" ]; then
        vid="$(cat "$parent/idVendor")"
        pid="$(cat "$parent/idProduct")"
        if [ "$vid" = "$USB_VID" ] && [ "$pid" = "$USB_PID" ]; then
          printf '%s\n' "/dev/${vd##*/}"
          return 0
        fi
        break
      fi
      parent="$(dirname "$parent")"
    done
  done
  return 1
}

find_usb_busid() {
  local d
  for d in /sys/bus/usb/devices/*; do
    [ -f "$d/idVendor" ] || continue
    if [ "$(cat "$d/idVendor")" = "$USB_VID" ] && [ "$(cat "$d/idProduct")" = "$USB_PID" ]; then
      basename "$d"
      return 0
    fi
  done
  return 1
}

# PipeWire's V4L2 monitor can leave STREAMON EBUSY with no userspace opener.
release_pipewire_v4l() {
  local dev="$1" id
  command -v pw-cli >/dev/null 2>&1 || return 0
  command -v pw-dump >/dev/null 2>&1 || return 0
  while read -r id; do
    [ -n "$id" ] || continue
    log "releasing PipeWire node $id for $dev"
    pw-cli destroy "$id" >/dev/null 2>&1 || true
  done < <(DEV="$dev" pw-dump 2>/dev/null | python3 -c '
import json, os, sys
dev = os.environ.get("DEV", "")
try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit
for o in data:
    p = (o.get("info") or {}).get("props") or {}
    path = " ".join(
        str(p.get(k) or "")
        for k in ("object.path", "api.v4l2.path", "node.name", "device.name")
    )
    if dev and dev in path:
        print(o.get("id"))
')
  sleep 0.3
}

# Only kill leftover *ffplay* holders. Never pgrep -f the script name —
# Steam's reaper cmdline embeds this path; killing it looks like an instant crash.
kill_stale_ffplay() {
  local self=$$
  local pid cmd
  while read -r pid; do
    [ -n "$pid" ] || continue
    [ "$pid" = "$self" ] && continue
    # Skip anything in our own process tree (steam-launch-wrapper / reaper / bash).
    if [ -r "/proc/$pid/stat" ]; then
      # If pid is an ancestor of self, leave it alone.
      local walk=$self
      while [ "$walk" -gt 1 ]; do
        [ "$walk" = "$pid" ] && continue 2
        walk="$(awk '{print $4}' "/proc/$walk/stat" 2>/dev/null || echo 1)"
      done
    fi
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    case "$cmd" in
      *ffplay*)
        case "$cmd" in
          *v4l2*|*"/dev/video"*|*"$DEV"*)
            log "stopping stale ffplay pid $pid"
            kill "$pid" 2>/dev/null || true
            sleep 0.2
            kill -9 "$pid" 2>/dev/null || true
            ;;
        esac
        ;;
    esac
  done < <(pgrep -x ffplay || true)
  sleep 0.3
}

# v4l2-ctl often exits 0 even when STREAMON printed EBUSY — parse output.
probe_stream() {
  local dev="$1" out
  out="$(timeout 3 v4l2-ctl -d "$dev" --stream-mmap=1 --stream-count=2 --stream-poll 2>&1 || true)"
  if printf '%s' "$out" | grep -qiE 'busy|Device or resource|VIDIOC_STREAMON returned -1'; then
    return 1
  fi
  if printf '%s' "$out" | grep -qiE 'error|fail|No such device'; then
    return 1
  fi
  # Success if we saw any frame / no busy
  return 0
}

pci_rebind_card() {
  local busid
  busid="$(find_usb_busid || true)"
  [ -n "$busid" ] || return 1
  [ -x "$HELPER" ] || return 1
  log "STREAMON busy — PCI-rebinding capture USB $busid"
  sudo -n "$HELPER" usb-pci-rebind "$busid" >/dev/null 2>&1 || return 1
  sleep 2.5
  return 0
}

ensure_streamable() {
  local dev="$1" tries=0
  kill_stale_ffplay
  release_pipewire_v4l "$dev"
  while [ "$tries" -lt 3 ]; do
    tries=$((tries + 1))
    if probe_stream "$dev"; then
      return 0
    fi
    log "probe $tries: $dev busy — reclaim"
    kill_stale_ffplay
    release_pipewire_v4l "$dev"
    sleep 0.5
  done
  if pci_rebind_card; then
    # Device node path may stay the same after rebind.
    sleep 1
    kill_stale_ffplay
    release_pipewire_v4l "$dev"
    if probe_stream "$dev"; then
      return 0
    fi
  fi
  log "error: $dev still busy after reclaim — refusing to start (Steam would show a crash)"
  log "hint: $ROOT/scripts/reset-switch2-capture.sh"
  return 1
}

# Single Steam Play at a time (second Play used to SIGTERM the reaper via bad pgrep).
exec 9>"$LOCK"
if ! flock -n 9; then
  log "another Switch capture viewer holds $LOCK — taking over"
  # Soft: kill only ffplay; then wait for lock
  kill_stale_ffplay
  flock 9
fi

if ! command -v ffplay >/dev/null 2>&1; then
  log "ffplay missing"
  exit 1
fi

DEV="$(find_capture_dev)" || {
  log "MacroSilicon capture card ${USB_VID}:${USB_PID} not found (/dev/video*)"
  log "hint: $ROOT/scripts/reset-switch2-capture.sh"
  exit 2
}
log "capture device: $DEV (${WIDTH}x${HEIGHT}@${FPS} MJPG)"
if ! ensure_streamable "$DEV"; then
  exit 3
fi

# Game Mode: Steam usually sets DISPLAY=:0. Prefer it if unset.
if [ -z "${DISPLAY:-}" ]; then
  if [ -S /tmp/.X11-unix/X0 ]; then
    export DISPLAY=:0
  elif [ -S /tmp/.X11-unix/X1 ]; then
    export DISPLAY=:1
  fi
  log "DISPLAY unset — using $DISPLAY"
fi
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"

log "starting fullscreen ffplay on DISPLAY=${DISPLAY:-?} (video-only)"
# Note: ffplay multi -i (v4l2+pulse) mis-parses and exits immediately — keep video only.
set +e
ffplay -hide_banner -loglevel warning \
  -fflags nobuffer -flags low_delay -framedrop \
  -fs -alwaysontop -an \
  -f v4l2 -input_format mjpeg -video_size "${WIDTH}x${HEIGHT}" -framerate "$FPS" \
  -i "$DEV" 2>>"$LOG"
rc=$?
set -e
log "ffplay exited rc=$rc"
# Busy after probe race — one reclaim + retry
if [ "$rc" -eq 0 ] || [ "$rc" -eq 1 ]; then
  if tail -n 5 "$LOG" | grep -qi 'Device or resource busy'; then
    log "ffplay hit busy — reclaim and retry once"
    ensure_streamable "$DEV" || exit 3
    ffplay -hide_banner -loglevel warning \
      -fflags nobuffer -flags low_delay -framedrop \
      -fs -alwaysontop -an \
      -f v4l2 -input_format mjpeg -video_size "${WIDTH}x${HEIGHT}" -framerate "$FPS" \
      -i "$DEV" 2>>"$LOG"
    rc=$?
    log "ffplay retry exited rc=$rc"
  fi
fi
exit "$rc"
