#!/usr/bin/env bash
# Fullscreen HDMI capture from the MacroSilicon MS2109 card (Switch 2 feed).
# Host ffplay + V4L2. Optional: SWITCH2_CAPTURE_DEV=/dev/videoN
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${SWITCH2_CAPTURE_LOG_DIR:-$ROOT/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/switch2-capture-viewer.log"
HELPER="$ROOT/scripts/hide-controllers-sysfs.sh"

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
    path = str(p.get("object.path") or "") + str(p.get("api.v4l2.path") or "")
    if dev and dev in path:
        print(o.get("id"))
')
}

ensure_streamable() {
  local dev="$1" busid
  release_pipewire_v4l "$dev"
  if timeout 2 v4l2-ctl -d "$dev" --stream-mmap=1 --stream-count=1 >/dev/null 2>&1; then
    return 0
  fi
  log "STREAMON busy — PCI-rebinding capture USB controller"
  busid="$(find_usb_busid || true)"
  if [ -n "$busid" ] && [ -x "$HELPER" ]; then
    sudo -n "$HELPER" usb-pci-rebind "$busid" >/dev/null 2>&1 || true
    sleep 2
    # Device node may keep the same path after rebind
    release_pipewire_v4l "$dev"
  fi
  if timeout 2 v4l2-ctl -d "$dev" --stream-mmap=1 --stream-count=1 >/dev/null 2>&1; then
    return 0
  fi
  log "warn: $dev still busy — Play may show black/no signal"
  log "warn: confirm Switch HDMI → capture card; then: sudo $HELPER usb-pci-rebind \$(…)"
  return 0
}

if ! command -v ffplay >/dev/null 2>&1; then
  log "ffplay missing"
  exit 1
fi

DEV="$(find_capture_dev)" || {
  log "MacroSilicon capture card ${USB_VID}:${USB_PID} not found (/dev/video*)"
  log "hint: sudo $HELPER usb-pci-rebind 5-2   # or unplug/replug the stick"
  exit 2
}
log "capture device: $DEV (${WIDTH}x${HEIGHT}@${FPS} MJPG)"
ensure_streamable "$DEV"

# gamescope / Steam set DISPLAY; do not override.
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"

log "starting fullscreen ffplay (video-only; capture audio deferred)"
# Note: ffplay multi -i (v4l2+pulse) mis-parses and exits immediately — keep video only.
exec ffplay -hide_banner -loglevel warning \
  -fflags nobuffer -flags low_delay -framedrop \
  -fs -alwaysontop -an \
  -f v4l2 -input_format mjpeg -video_size "${WIDTH}x${HEIGHT}" -framerate "$FPS" \
  -i "$DEV"
