#!/usr/bin/env bash
# Privileged sysfs writes for scripts/hide-controllers.py.
# Cable / pairing stay; authorized=0 or HID unbind makes the pad vanish.
# Validate every argument. Never touch USB hubs or paths outside /sys/bus.
set -euo pipefail

USB_ROOT="${PAD_HIDE_USB_ROOT:-/sys/bus/usb/devices}"
HID_ROOT="${PAD_HIDE_HID_ROOT:-/sys/bus/hid/devices}"
HID_DRV_ROOT="${PAD_HIDE_HID_DRV_ROOT:-/sys/bus/hid/drivers}"

usb_ok() { [[ "${1:-}" =~ ^[0-9]+-[0-9]+(\.[0-9]+)*$ ]]; }
hid_ok() { [[ "${1:-}" =~ ^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}$ ]]; }
drv_ok() { [[ "${1:-}" =~ ^[A-Za-z0-9_+:.-]+$ ]]; }

die() {
  echo "hide-controllers-sysfs: $*" >&2
  exit 2
}

cmd="${1:-}"
case "$cmd" in
  usb-authorized)
    busid="${2:-}"
    val="${3:-}"
    usb_ok "$busid" || die "bad usb busid"
    [[ "$val" == "0" || "$val" == "1" ]] || die "authorized must be 0 or 1"
    dev="$USB_ROOT/$busid"
    [[ -d "$dev" ]] || die "missing $dev"
    if [[ -f "$dev/bDeviceClass" ]] && [[ "$(cat "$dev/bDeviceClass")" == "09" ]]; then
      die "refusing USB hub $busid"
    fi
    if [[ -f "$dev/idVendor" ]] && [[ "$(tr '[:upper:]' '[:lower:]' < "$dev/idVendor")" == "1d6b" ]]; then
      die "refusing USB root hub $busid"
    fi
    [[ -f "$dev/authorized" ]] || die "no authorized on $busid"
    printf '%s' "$val" > "$dev/authorized"
    ;;
  hid-authorized)
    hid="${2:-}"
    val="${3:-}"
    hid_ok "$hid" || die "bad hid id"
    [[ "$val" == "0" || "$val" == "1" ]] || die "authorized must be 0 or 1"
    dest="$HID_ROOT/$hid/authorized"
    [[ -f "$dest" ]] || die "no hid authorized on $hid"
    printf '%s' "$val" > "$dest"
    ;;
  hid-unbind)
    hid="${2:-}"
    hid_ok "$hid" || die "bad hid id"
    drv_link="$HID_ROOT/$hid/driver"
    [[ -L "$drv_link" || -d "$drv_link" ]] || die "no hid driver for $hid"
    drv="$(basename "$(readlink -f "$drv_link")")"
    drv_ok "$drv" || die "bad hid driver"
    printf '%s' "$hid" > "$HID_DRV_ROOT/$drv/unbind"
    ;;
  hid-bind)
    hid="${2:-}"
    drv="${3:-}"
    hid_ok "$hid" || die "bad hid id"
    drv_ok "$drv" || die "bad hid driver"
    [[ -d "$HID_DRV_ROOT/$drv" ]] || die "missing hid driver $drv"
    printf '%s' "$hid" > "$HID_DRV_ROOT/$drv/bind"
    ;;
  *)
    die "usage: usb-authorized <busid> <0|1> | hid-authorized <id> <0|1> | hid-unbind <id> | hid-bind <id> <driver>"
    ;;
esac
