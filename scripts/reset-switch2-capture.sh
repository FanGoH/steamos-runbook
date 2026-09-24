#!/usr/bin/env bash
# Recover stuck MacroSilicon MS2109 (authorized=0 / STREAMON EBUSY / no video nodes).
# Uses NOPASSWD hide-controllers-sysfs usb-pci-rebind.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="$ROOT/scripts/hide-controllers-sysfs.sh"
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

BUSID="$(find_busid || true)"
if [ -z "$BUSID" ]; then
  echo "capture card ${VID}:${PID} not present - plug it in first" >&2
  exit 2
fi

echo "pci-rebind $BUSID (${VID}:${PID})"
if ! sudo -n "$HELPER" usb-pci-rebind "$BUSID"; then
  echo "NOPASSWD helper failed - run: sudo $HELPER usb-pci-rebind $BUSID" >&2
  exit 3
fi
sleep 3

BUSID="$(find_busid || true)"
AUTH="?"
if [ -n "$BUSID" ] && [ -f "/sys/bus/usb/devices/${BUSID}/authorized" ]; then
  AUTH="$(cat "/sys/bus/usb/devices/${BUSID}/authorized")"
fi
echo "after: busid=${BUSID:-gone} auth=${AUTH}"
lsusb -d "${VID}:${PID}" || true
ls -l /dev/video* 2>/dev/null || echo "no /dev/video*"

if [ -z "$BUSID" ]; then
  echo "card did not reappear" >&2
  exit 4
fi

DEV=""
for v in /sys/class/video4linux/video*; do
  [ -e "$v" ] || continue
  real="$(readlink -f "$v")"
  case "$real" in
    *"/${BUSID}"*)
      if v4l2-ctl -d "/dev/${v##*/}" --list-formats-ext 2>/dev/null | grep -qE 'MJPG|Motion-JPEG'; then
        DEV="/dev/${v##*/}"
        break
      fi
      ;;
  esac
done

if [ -z "$DEV" ]; then
  echo "no MJPG node after rebind" >&2
  exit 5
fi

if command -v pw-dump >/dev/null 2>&1; then
  DEV="$DEV" pw-dump 2>/dev/null | python3 -c '
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
' | while read -r id; do
    [ -n "$id" ] || continue
    pw-cli destroy "$id" >/dev/null 2>&1 || true
  done
fi

echo "probing $DEV"
if timeout 3 v4l2-ctl -d "$DEV" --stream-mmap=3 --stream-count=5 --stream-poll; then
  echo "STREAMON ok - Play Nintendo Switch 2"
else
  echo "STREAMON failed - check Switch HDMI into the capture card" >&2
  exit 6
fi
