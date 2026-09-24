#!/usr/bin/env bash
# Force-reset MacroSilicon MS2109 when usbreset says "Device or resource busy".
# Run: sudo /home/deck/steamos-playbook/scripts/reset-switch2-capture-force.sh
set -euo pipefail

VID=534d
PID=2109

find_busid() {
  local d
  for d in /sys/bus/usb/devices/*; do
    [ -f "$d/idVendor" ] || continue
    if [ "$(cat "$d/idVendor")" = "$VID" ] && [ "$(cat "$d/idProduct")" = "$PID" ]; then
      basename "$d"
      return 0
    fi
  done
  return 1
}

if [ "$(id -u)" -ne 0 ]; then
  echo "re-run as root: sudo $0" >&2
  exit 1
fi

BUSID="$(find_busid || true)"
if [ -z "$BUSID" ]; then
  echo "capture card ${VID}:${PID} not plugged in" >&2
  exit 2
fi

echo "busid=$BUSID authorized=$(cat /sys/bus/usb/devices/$BUSID/authorized)"

# Drop PipeWire camera claim (best-effort, as calling user if SUDO_USER set)
if [ -n "${SUDO_USER:-}" ]; then
  sudo -u "$SUDO_USER" -H systemctl --user stop wireplumber.service 2>/dev/null || true
  sleep 0.5
fi

# Unbind UVC interfaces so the USB device node can be opened/reset
for iface in /sys/bus/usb/devices/"$BUSID":*; do
  [ -e "$iface" ] || continue
  name="$(basename "$iface")"
  if [ -e /sys/bus/usb/drivers/uvcvideo/unbind ]; then
    echo "unbind uvc $name"
    echo "$name" > /sys/bus/usb/drivers/uvcvideo/unbind 2>/dev/null || true
  fi
done
sleep 0.5

# Re-authorize if stuck at 0 (pad-hide / earlier cycle)
echo 1 > /sys/bus/usb/devices/"$BUSID"/authorized
echo "authorized=$(cat /sys/bus/usb/devices/$BUSID/authorized)"
sleep 0.5

# Kernel USB reset
if command -v usbreset >/dev/null 2>&1; then
  usbreset "${VID}:${PID}" || usbreset "/dev/bus/usb/$(printf '%03d' "$(cat /sys/bus/usb/devices/$BUSID/busnum)")/$(printf '%03d' "$(cat /sys/bus/usb/devices/$BUSID/devnum)")" || true
fi

# Re-bind UVC
sleep 1
for iface in /sys/bus/usb/devices/"$BUSID":*; do
  [ -e "$iface" ] || continue
  name="$(basename "$iface")"
  # Only video control / streaming interfaces (class e0/0e-ish); bind all under uvc
  if [ -d /sys/bus/usb/drivers/uvcvideo ]; then
    echo "bind uvc $name"
    echo "$name" > /sys/bus/usb/drivers/uvcvideo/bind 2>/dev/null || true
  fi
done

sleep 1
lsusb -d "${VID}:${PID}" || true
ls -l /dev/video* 2>/dev/null || true

if [ -n "${SUDO_USER:-}" ]; then
  sudo -u "$SUDO_USER" -H systemctl --user start wireplumber.service 2>/dev/null || true
fi

# Quick STREAMON probe
DEV=""
for v in /sys/class/video4linux/video*; do
  [ -e "$v" ] || continue
  real="$(readlink -f "$v")"
  case "$real" in
    *"/usb"*"/$BUSID"*) 
      if v4l2-ctl -d "/dev/${v##*/}" --list-formats-ext 2>/dev/null | grep -q MJPG; then
        DEV="/dev/${v##*/}"
        break
      fi
      ;;
  esac
done
if [ -n "$DEV" ]; then
  echo "probing $DEV"
  v4l2-ctl -d "$DEV" --set-fmt-video=width=1920,height=1080,pixelformat=MJPG || true
  if timeout 3 v4l2-ctl -d "$DEV" --stream-mmap=3 --stream-count=5 --stream-poll; then
    echo "STREAMON ok"
  else
    echo "STREAMON still failing — check HDMI cable from Switch into capture card" >&2
  fi
else
  echo "no MJPG video node yet" >&2
fi
