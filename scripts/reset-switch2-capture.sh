#!/usr/bin/env bash
# Reset the MacroSilicon MS2109 capture stick (USB authorized cycle + usbreset).
# Uses playbook NOPASSWD hide-controllers-sysfs when available; falls back to usbreset.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="$ROOT/scripts/hide-controllers-sysfs.sh"
USB_VID="${SWITCH2_CAPTURE_USB_VID:-534d}"
USB_PID="${SWITCH2_CAPTURE_USB_PID:-2109}"

find_busid() {
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

BUSID="$(find_busid || true)"
if [ -z "$BUSID" ]; then
  echo "capture card ${USB_VID}:${USB_PID} not present" >&2
  exit 2
fi

echo "resetting USB $BUSID (${USB_VID}:${USB_PID})"

if [ -x "$HELPER" ] && sudo -n "$HELPER" usb-authorized "$BUSID" 0 2>/dev/null; then
  sleep 1
  if ! sudo -n "$HELPER" usb-authorized "$BUSID" 1; then
    echo "warn: could not re-authorize $BUSID — unplug/replug the capture stick or run:" >&2
    echo "  sudo sh -c 'echo 1 > /sys/bus/usb/devices/$BUSID/authorized'" >&2
    echo "  sudo usbreset ${USB_VID}:${USB_PID}" >&2
    exit 3
  fi
  sleep 1
fi

if command -v usbreset >/dev/null 2>&1; then
  if sudo -n usbreset "${USB_VID}:${USB_PID}" 2>/dev/null \
    || usbreset "${USB_VID}:${USB_PID}" 2>/dev/null; then
    echo "usbreset ok"
  else
    echo "note: usbreset needs a free device or: sudo usbreset ${USB_VID}:${USB_PID}"
  fi
fi

lsusb -d "${USB_VID}:${USB_PID}" || true
ls /dev/video* 2>/dev/null || true
echo "done"
