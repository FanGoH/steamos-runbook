#!/usr/bin/env bash
# Force-reset MacroSilicon MS2109 when authorized=0 / usbreset is EBUSY.
# Does NOT stop sunshine-ds-kms. Run:
#   sudo /home/deck/steamos-playbook/scripts/reset-switch2-capture-force.sh
set -uo pipefail

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

DEVPATH="/sys/bus/usb/devices/$BUSID"
echo "busid=$BUSID authorized=$(cat "$DEVPATH/authorized" 2>/dev/null || echo ?)"

# 1) Unbind UVC (ignore errors)
for iface in "$DEVPATH":*; do
  [ -e "$iface" ] || continue
  name="$(basename "$iface")"
  echo "unbind uvc $name"
  echo "$name" > /sys/bus/usb/drivers/uvcvideo/unbind 2>/dev/null || true
done
# Also snd-usb-audio / usbhid if bound
for drv in snd-usb-audio usbhid; do
  for iface in "$DEVPATH":*; do
    [ -e "$iface" ] || continue
    name="$(basename "$iface")"
    if [ -e "/sys/bus/usb/drivers/$drv/unbind" ]; then
      echo "$name" > "/sys/bus/usb/drivers/$drv/unbind" 2>/dev/null || true
    fi
  done
done
sleep 0.3

# 2) Port power-cycle (works when authorized write is EBUSY)
PORT_DIS="$DEVPATH/port/disable"
if [ -f "$PORT_DIS" ]; then
  echo "USB port disable 1"
  echo 1 > "$PORT_DIS" || true
  sleep 2
  echo "USB port disable 0"
  echo 0 > "$PORT_DIS" || true
  sleep 2
else
  echo "no port/disable — trying device remove"
  echo 1 > "$DEVPATH/remove" 2>/dev/null || true
  sleep 2
  # Rescan root hub for this bus (bus 5 only has this capture stick + hub)
  BUSNUM="$(cat /sys/bus/usb/devices/"$BUSID"/busnum 2>/dev/null || echo 5)"
  HUB="/sys/bus/usb/devices/usb${BUSNUM}"
  if [ -f "$HUB/authorized" ]; then
    echo 0 > "$HUB/authorized" || true
    sleep 1
    echo 1 > "$HUB/authorized" || true
    sleep 2
  fi
fi

# Re-find after re-enumerate
BUSID="$(find_busid || true)"
if [ -z "$BUSID" ]; then
  echo "card did not reappear — unplug/replug the capture stick now, then re-run this script" >&2
  exit 3
fi
DEVPATH="/sys/bus/usb/devices/$BUSID"
echo "after cycle: busid=$BUSID authorized=$(cat "$DEVPATH/authorized")"

# 3) Ensure authorized=1
if [ "$(cat "$DEVPATH/authorized")" != "1" ]; then
  echo 1 > "$DEVPATH/authorized" 2>/dev/null || echo "warn: still cannot set authorized=1"
fi

# 4) usbreset now that port is live
sleep 0.5
if command -v usbreset >/dev/null 2>&1; then
  if usbreset "${VID}:${PID}"; then
    echo "usbreset ok"
  else
    echo "usbreset still busy (often OK if port cycle already re-enumerated)"
  fi
fi

sleep 1
lsusb -d "${VID}:${PID}" || true
ls -l /dev/video* 2>/dev/null || true

# 5) STREAMON probe
DEV=""
for v in /sys/class/video4linux/video*; do
  [ -e "$v" ] || continue
  real="$(readlink -f "$v")"
  case "$real" in
    *"/$BUSID"*)
      if v4l2-ctl -d "/dev/${v##*/}" --list-formats-ext 2>/dev/null | grep -q MJPG; then
        DEV="/dev/${v##*/}"
        break
      fi
      ;;
  esac
done
if [ -n "$DEV" ]; then
  echo "probing $DEV"
  v4l2-ctl -d "$DEV" --set-fmt-video=width=1920,height=1080,pixelformat=MJPG 2>/dev/null || true
  if timeout 3 v4l2-ctl -d "$DEV" --stream-mmap=3 --stream-count=5 --stream-poll; then
    echo "STREAMON ok — Play Nintendo Switch 2 again"
  else
    echo "STREAMON still failing — confirm Switch HDMI is plugged into the capture card" >&2
    exit 4
  fi
else
  echo "no MJPG /dev/video* yet" >&2
  exit 5
fi
