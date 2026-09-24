#!/usr/bin/env bash
# Fullscreen HDMI capture from the MacroSilicon MS2109 card (Switch 2 feed).
# Host mpv (AppImage/local) + V4L2 video, Pulse loopback of card audio → HDMI
# so Sunshine (audio_sink = HDMI leaf) / Moonlight hears Switch sound.
# Optional: SWITCH2_CAPTURE_DEV=/dev/videoN  SWITCH2_MPV=/path/to/mpv
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${SWITCH2_CAPTURE_LOG_DIR:-$ROOT/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/switch2-capture-viewer.log"
HELPER="$ROOT/scripts/hide-controllers-sysfs.sh"
LOCK="${XDG_RUNTIME_DIR:-/tmp}/switch2-capture-viewer.lock"
LOOP_MOD_FILE="${XDG_RUNTIME_DIR:-/tmp}/switch2-capture-loopback.module"

# Steam non-Steam launches inject a runtime that breaks host V4L2/mpv.
unset LD_PRELOAD || true
export LD_LIBRARY_PATH=""
export STEAM_RUNTIME="${STEAM_RUNTIME:-0}"
export PATH="/usr/bin:/bin:${HOME}/.local/bin:${PATH:-}"

USB_VID="${SWITCH2_CAPTURE_USB_VID:-534d}"
USB_PID="${SWITCH2_CAPTURE_USB_PID:-2109}"
# MS2109 is USB2: 1080p60 MJPEG only delivers ~30fps. 720p60 is real 60fps.
WIDTH="${SWITCH2_CAPTURE_WIDTH:-1280}"
HEIGHT="${SWITCH2_CAPTURE_HEIGHT:-720}"
FPS="${SWITCH2_CAPTURE_FPS:-60}"
AUDIO="${SWITCH2_CAPTURE_AUDIO:-1}"
AUDIO_LATENCY_MS="${SWITCH2_CAPTURE_AUDIO_LATENCY_MS:-20}"

log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG" >&2; }

find_mpv() {
  local c
  if [ -n "${SWITCH2_MPV:-}" ] && [ -x "${SWITCH2_MPV}" ]; then
    printf '%s\n' "$SWITCH2_MPV"
    return 0
  fi
  for c in \
    "${HOME}/.local/bin/mpv-switch2" \
    "${HOME}/.local/bin/mpv" \
    "$(command -v mpv 2>/dev/null || true)"
  do
    [ -n "$c" ] && [ -x "$c" ] || continue
    printf '%s\n' "$c"
    return 0
  done
  # Prefer a downloaded AppImage under ~/AppImages
  local img
  img="$(ls -1t "${HOME}/AppImages"/mpv*.AppImage 2>/dev/null | head -n1 || true)"
  if [ -n "$img" ] && [ -x "$img" ]; then
    printf '%s\n' "$img"
    return 0
  fi
  return 1
}

ensure_mpv() {
  if find_mpv >/dev/null; then
    return 0
  fi
  if [ -x "$ROOT/scripts/ensure-switch2-mpv.sh" ]; then
    log "mpv missing — running ensure-switch2-mpv.sh"
    "$ROOT/scripts/ensure-switch2-mpv.sh" || true
  fi
  find_mpv >/dev/null
}

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

find_capture_source() {
  # Prefer the MS2109 Pulse source (loopback wrapper or raw ALSA input).
  pactl list short sources 2>/dev/null | awk -F'\t' '
    $2 ~ /MACROSILICON|MS2109|USB_Video/ && $2 !~ /\.monitor$/ { print $2; exit }
  '
}

find_hdmi_sink() {
  # Same leaf Sunshine Game Mode captures — not sink-sunshine-*.
  pactl list short sinks 2>/dev/null | awk -F'\t' '
    $2 ~ /hdmi/ && $2 !~ /sink-sunshine-/ { print $2; exit }
  '
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

# Kill leftover capture viewers by cmdline (never pgrep -f script path — Steam reaper).
kill_stale_viewers() {
  local self=$$
  local pid cmd
  while read -r pid; do
    [ -n "$pid" ] || continue
    [ "$pid" = "$self" ] && continue
    if [ -r "/proc/$pid/stat" ]; then
      local walk=$self
      while [ "$walk" -gt 1 ]; do
        [ "$walk" = "$pid" ] && continue 2
        walk="$(awk '{print $4}' "/proc/$walk/stat" 2>/dev/null || echo 1)"
      done
    fi
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    case "$cmd" in
      *ffplay*|*mpv*|*mpv-Media-Player*|*mpv-switch2*)
        case "$cmd" in
          *v4l2*|*"/dev/video"*|*"$DEV"*|*av://v4l2*)
            log "stopping stale viewer pid $pid"
            kill "$pid" 2>/dev/null || true
            sleep 0.2
            kill -9 "$pid" 2>/dev/null || true
            ;;
        esac
        ;;
    esac
  done < <(
    {
      pgrep -x ffplay || true
      pgrep -x mpv || true
      # AppImage may keep a long argv0; scan /proc by cmdline without pgrep -f.
      for d in /proc/[0-9]*; do
        [ -r "$d/cmdline" ] || continue
        c="$(tr '\0' ' ' <"$d/cmdline" 2>/dev/null || true)"
        case "$c" in
          *mpv-Media-Player*|*mpv-switch2*|*av://v4l2*) basename "$d" ;;
        esac
      done
    } | sort -u
  )
  sleep 0.3
}

stop_audio_loopback() {
  local mid=""
  if [ -f "$LOOP_MOD_FILE" ]; then
    mid="$(cat "$LOOP_MOD_FILE" 2>/dev/null || true)"
    rm -f "$LOOP_MOD_FILE"
  fi
  if [ -n "$mid" ] && [[ "$mid" =~ ^[0-9]+$ ]]; then
    log "unloading capture→HDMI loopback module $mid"
    pactl unload-module "$mid" >/dev/null 2>&1 || true
  fi
}

start_audio_loopback() {
  local src sink mid
  [ "$AUDIO" = "1" ] || { log "audio disabled (SWITCH2_CAPTURE_AUDIO=$AUDIO)"; return 0; }
  command -v pactl >/dev/null 2>&1 || { log "warn: pactl missing — no capture audio"; return 0; }
  stop_audio_loopback
  src="$(find_capture_source || true)"
  sink="$(find_hdmi_sink || true)"
  if [ -z "$src" ] || [ -z "$sink" ]; then
    log "warn: capture audio source='$src' hdmi sink='$sink' — Moonlight will be silent"
    return 0
  fi
  # Route MS2109 into the HDMI leaf Sunshine monitors (not sink-sunshine-stereo).
  mid="$(pactl load-module module-loopback \
    source="$src" \
    sink="$sink" \
    latency_msec="$AUDIO_LATENCY_MS" \
    remix=false \
    2>/dev/null || true)"
  if [ -z "$mid" ] || ! [[ "$mid" =~ ^[0-9]+$ ]]; then
    log "warn: failed to load module-loopback ($src → $sink)"
    return 0
  fi
  printf '%s\n' "$mid" >"$LOOP_MOD_FILE"
  log "audio loopback #$mid: $src → $sink (latency ${AUDIO_LATENCY_MS}ms)"
}

cleanup() {
  stop_audio_loopback
}
trap cleanup EXIT INT TERM

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
  kill_stale_viewers
  release_pipewire_v4l "$dev"
  while [ "$tries" -lt 3 ]; do
    tries=$((tries + 1))
    if probe_stream "$dev"; then
      return 0
    fi
    log "probe $tries: $dev busy — reclaim"
    kill_stale_viewers
    release_pipewire_v4l "$dev"
    sleep 0.5
  done
  if pci_rebind_card; then
    sleep 1
    kill_stale_viewers
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
  kill_stale_viewers
  flock 9
fi

if ! ensure_mpv; then
  log "mpv missing — run: $ROOT/scripts/ensure-switch2-mpv.sh"
  exit 1
fi
MPV_BIN="$(find_mpv)"
log "using mpv: $MPV_BIN"

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

start_audio_loopback

log "starting fullscreen mpv on DISPLAY=${DISPLAY:-?} (video + HDMI audio loopback)"
# AppImage under gamescope often has no GLX/GBM (libsensors). Prefer vo=x11.
# Do NOT pass --length on live V4L2 (mpv treats the stream as ended immediately).
# Audio is Pulse loopback → HDMI leaf (Sunshine audio_sink), not mpv ao.
run_mpv() {
  local vo="$1"
  "$MPV_BIN" --no-config \
    --profile=low-latency --untimed --no-cache --cache=no \
    --demuxer-readahead-secs=0 --demuxer-max-bytes=512KiB \
    --vd-lavc-threads=1 --video-latency-hacks=yes \
    --vo="$vo" --ao=null \
    --fs --force-window=immediate --no-osc \
    --demuxer-lavf-o="input_format=mjpeg,video_size=${WIDTH}x${HEIGHT},framerate=${FPS}" \
    "av://v4l2:${DEV}" 2>>"$LOG"
}

run_ffplay_fallback() {
  log "mpv failed — falling back to ffplay (audio loopback stays)"
  command -v ffplay >/dev/null 2>&1 || return 1
  ffplay -hide_banner -loglevel warning \
    -fflags nobuffer -flags low_delay -framedrop \
    -fs -alwaysontop -an \
    -f v4l2 -input_format mjpeg -video_size "${WIDTH}x${HEIGHT}" -framerate "$FPS" \
    -i "$DEV" 2>>"$LOG"
}

set +e
rc=1
for vo in x11 xv gpu sdl; do
  log "mpv trying vo=$vo"
  run_mpv "$vo"
  rc=$?
  # SIGTERM/INT from Steam Exit are fine; treat as clean.
  if [ "$rc" -eq 0 ] || [ "$rc" -eq 143 ] || [ "$rc" -eq 130 ]; then
    break
  fi
  log "mpv vo=$vo exited rc=$rc"
  ensure_streamable "$DEV" || exit 3
  start_audio_loopback
done
if [ "$rc" -ne 0 ] && [ "$rc" -ne 143 ] && [ "$rc" -ne 130 ]; then
  if tail -n 20 "$LOG" | grep -qi 'Device or resource busy\|Cannot open video device\|avformat_open_input'; then
    log "mpv hit busy — reclaim and retry vo=x11 once"
    ensure_streamable "$DEV" || exit 3
    start_audio_loopback
    run_mpv x11
    rc=$?
  fi
fi
if [ "$rc" -ne 0 ] && [ "$rc" -ne 143 ] && [ "$rc" -ne 130 ]; then
  ensure_streamable "$DEV" || exit 3
  start_audio_loopback
  run_ffplay_fallback
  rc=$?
fi
set -e
log "viewer exited rc=$rc"
exit "$rc"
