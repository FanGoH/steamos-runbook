#!/usr/bin/env bash
# Fullscreen HDMI capture from the MacroSilicon MS2109 card (Switch 2 feed).
# Prefer host ffplay (V4L2 + Pulse). Optional: SWITCH2_CAPTURE_DEV=/dev/videoN
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${SWITCH2_CAPTURE_LOG_DIR:-$ROOT/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/switch2-capture-viewer.log"

USB_VID="${SWITCH2_CAPTURE_USB_VID:-534d}"
USB_PID="${SWITCH2_CAPTURE_USB_PID:-2109}"
WIDTH="${SWITCH2_CAPTURE_WIDTH:-1920}"
HEIGHT="${SWITCH2_CAPTURE_HEIGHT:-1080}"
FPS="${SWITCH2_CAPTURE_FPS:-60}"
AUDIO="${SWITCH2_CAPTURE_AUDIO:-1}"

log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG" >&2; }

find_capture_dev() {
  local vd name parent vid pid
  if [ -n "${SWITCH2_CAPTURE_DEV:-}" ]; then
    printf '%s\n' "$SWITCH2_CAPTURE_DEV"
    return 0
  fi
  for vd in /sys/class/video4linux/video*; do
    [ -e "$vd" ] || continue
    name="$(cat "$vd/name" 2>/dev/null || true)"
    parent="$vd"
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
      # Prefer the capture node (video0); skip metadata-only siblings when possible.
      if v4l2-ctl -d "/dev/${vd##*/}" --all 2>/dev/null | grep -q 'Video Capture'; then
        # Prefer MJPG-capable capture (not the empty metadata node).
        if v4l2-ctl -d "/dev/${vd##*/}" --list-formats-ext 2>/dev/null | grep -q "MJPG\|Motion-JPEG\|YUYV"; then
          printf '%s\n' "/dev/${vd##*/}"
          return 0
        fi
      fi
    fi
  done
  # Fallback: first node matching USB id
  for vd in /sys/class/video4linux/video*; do
    [ -e "$vd" ] || continue
    parent="$vd"
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

find_pulse_source() {
  # Prefer the MacroSilicon / MS2109 analog input.
  pactl list short sources 2>/dev/null \
    | awk '/MACROSILICON|MS2109|usb-MACROSILICON_USB_Video/ && $2 !~ /\.monitor$/ {print $2; exit}'
}

wait_for_device() {
  local dev="$1" i
  for i in $(seq 1 30); do
    [ -e "$dev" ] || { sleep 0.2; continue; }
    if timeout 1 v4l2-ctl -d "$dev" --stream-mmap=1 --stream-count=1 >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  log "warn: $dev STREAMON busy — check Switch HDMI into the capture card,"
  log "warn:   or: sudo usbreset 534d:2109  (then relaunch)"
  return 0
}

# Drop unused FF_AUDIO array remnant
:

if ! command -v ffplay >/dev/null 2>&1; then
  log "ffplay missing"
  exit 1
fi

DEV="$(find_capture_dev)" || {
  log "MacroSilicon capture card ${USB_VID}:${USB_PID} not found"
  exit 2
}
log "capture device: $DEV (${WIDTH}x${HEIGHT}@${FPS} MJPG)"
wait_for_device "$DEV" || true

PULSE_SRC=""
FF_AUDIO=(-an)
if [ "$AUDIO" = "1" ] && command -v pactl >/dev/null 2>&1; then
  PULSE_SRC="$(find_pulse_source || true)"
  if [ -n "$PULSE_SRC" ]; then
    log "audio source: $PULSE_SRC"
    FF_AUDIO=(-f pulse -i "$PULSE_SRC")
  else
    log "warn: no MacroSilicon Pulse source; video only"
  fi
fi

# gamescope / Steam set DISPLAY; do not override.
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"

log "starting fullscreen ffplay"
# Dual-input: video from V4L2, optional Pulse. -fs for fullscreen under gamescope.
# -use_libv4l2 0: avoid libv4l convert quirks on MS2109.
if [ -n "$PULSE_SRC" ]; then
  exec ffplay -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay -framedrop -sync ext \
    -fs -alwaysontop \
    -f v4l2 -use_libv4l2 0 -input_format mjpeg -video_size "${WIDTH}x${HEIGHT}" -framerate "$FPS" \
    -i "$DEV" \
    -f pulse -i "$PULSE_SRC"
else
  exec ffplay -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay -framedrop \
    -fs -alwaysontop -an \
    -f v4l2 -use_libv4l2 0 -input_format mjpeg -video_size "${WIDTH}x${HEIGHT}" -framerate "$FPS" \
    -i "$DEV"
fi
