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
usb_iface_ok() { [[ "${1:-}" =~ ^[0-9]+-[0-9]+(\.[0-9]+)*:[0-9]+\.[0-9]+$ ]]; }
pci_ok() { [[ "${1:-}" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F]$ ]]; }

die() {
  echo "hide-controllers-sysfs: $*" >&2
  exit 2
}

refuse_hub() {
  local busid="$1" dev="$USB_ROOT/$busid"
  if [[ -f "$dev/bDeviceClass" ]] && [[ "$(cat "$dev/bDeviceClass")" == "09" ]]; then
    die "refusing USB hub $busid"
  fi
  if [[ -f "$dev/idVendor" ]] && [[ "$(tr '[:upper:]' '[:lower:]' < "$dev/idVendor")" == "1d6b" ]]; then
    die "refusing USB root hub $busid"
  fi
}

# True if this USB device is a hub or root hub.
is_hub() {
  local dev="$1"
  [[ -f "$dev/bDeviceClass" ]] && [[ "$(cat "$dev/bDeviceClass")" == "09" ]] && return 0
  [[ -f "$dev/idVendor" ]] && [[ "$(tr '[:upper:]' '[:lower:]' < "$dev/idVendor")" == "1d6b" ]] && return 0
  return 1
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
    refuse_hub "$busid"
    [[ -f "$dev/authorized" ]] || die "no authorized on $busid"
    printf '%s' "$val" > "$dev/authorized"
    ;;
  usb-port-disable)
    busid="${2:-}"
    val="${3:-}"
    usb_ok "$busid" || die "bad usb busid"
    [[ "$val" == "0" || "$val" == "1" ]] || die "disable must be 0 or 1"
    dev="$USB_ROOT/$busid"
    [[ -d "$dev" ]] || die "missing $dev"
    refuse_hub "$busid"
    port="$dev/port/disable"
    [[ -f "$port" ]] || die "no port/disable on $busid"
    printf '%s' "$val" > "$port"
    ;;
  usb-remove)
    busid="${2:-}"
    usb_ok "$busid" || die "bad usb busid"
    dev="$USB_ROOT/$busid"
    [[ -d "$dev" ]] || die "missing $dev"
    refuse_hub "$busid"
    [[ -f "$dev/remove" ]] || die "no remove on $busid"
    printf '1' > "$dev/remove"
    ;;
  usb-pci-reset)
    # PCI-function reset for the controller hosting this leaf device.
    # Refuses if any other non-hub leaf shares that PCI USB host.
    busid="${2:-}"
    usb_ok "$busid" || die "bad usb busid"
    dev="$USB_ROOT/$busid"
    [[ -e "$dev" ]] || die "missing $dev"
    # /sys/bus/usb/devices/N-M is a symlink — walk the real device path.
    dev="$(readlink -f "$dev")"
    refuse_hub "$busid"
    pci_dev=""
    cur="$dev"
    while [[ "$cur" != "/" ]]; do
      base="$(basename "$cur")"
      if pci_ok "$base" && [[ -f "$cur/reset" ]]; then
        pci_dev="$cur"
        break
      fi
      cur="$(dirname "$cur")"
    done
    [[ -n "$pci_dev" ]] || die "no PCI reset for $busid (resolved $dev)"
    # Safety: only allow reset if every other USB leaf under this PCI node
    # is absent (hubs OK). Capture stick alone on 0000:10:00.4 is the case.
    while IFS= read -r -d '' other; do
      [[ -f "$other/idVendor" ]] || continue
      is_hub "$other" && continue
      obase="$(basename "$other")"
      [[ "$obase" == "$busid" ]] && continue
      # skip interface dirs (contain ':')
      [[ "$obase" == *:* ]] && continue
      die "refusing PCI reset: other leaf $obase on same controller"
    done < <(find "$pci_dev" -mindepth 1 -maxdepth 8 -type d -name '[0-9]*-[0-9]*' ! -name '*:*' -print0 2>/dev/null)
    echo "pci-reset $(basename "$pci_dev") for usb $busid" >&2
    printf '1' > "$pci_dev/reset"
    ;;
  usb-pci-rebind)
    # Harder than reset: unbind + bind the xHCI PCI function hosting this leaf.
    busid="${2:-}"
    usb_ok "$busid" || die "bad usb busid"
    dev="$USB_ROOT/$busid"
    [[ -e "$dev" ]] || die "missing $dev"
    dev="$(readlink -f "$dev")"
    refuse_hub "$busid"
    pci_dev=""
    cur="$dev"
    while [[ "$cur" != "/" ]]; do
      base="$(basename "$cur")"
      if pci_ok "$base" && [[ -d "$cur/driver" || -L "$cur/driver" ]]; then
        pci_dev="$cur"
        break
      fi
      cur="$(dirname "$cur")"
    done
    [[ -n "$pci_dev" ]] || die "no PCI device for $busid"
    while IFS= read -r -d '' other; do
      [[ -f "$other/idVendor" ]] || continue
      is_hub "$other" && continue
      obase="$(basename "$other")"
      [[ "$obase" == "$busid" ]] && continue
      [[ "$obase" == *:* ]] && continue
      die "refusing PCI rebind: other leaf $obase on same controller"
    done < <(find "$pci_dev" -mindepth 1 -maxdepth 8 -type d -name '[0-9]*-[0-9]*' ! -name '*:*' -print0 2>/dev/null)
    drv_link="$pci_dev/driver"
    [[ -L "$drv_link" ]] || die "no driver link on $(basename "$pci_dev")"
    drv_dir="$(readlink -f "$drv_link")"
    slot="$(basename "$pci_dev")"
    echo "pci-unbind $slot from $(basename "$drv_dir")" >&2
    printf '%s' "$slot" > "$drv_dir/unbind"
    sleep 2
    echo "pci-bind $slot" >&2
    printf '%s' "$slot" > "$drv_dir/bind"
    ;;
  usb-driver-unbind)
    iface="${2:-}"
    drv="${3:-}"
    usb_iface_ok "$iface" || die "bad usb iface"
    drv_ok "$drv" || die "bad driver"
    [[ -d "/sys/bus/usb/drivers/$drv" ]] || die "missing usb driver $drv"
    printf '%s' "$iface" > "/sys/bus/usb/drivers/$drv/unbind"
    ;;
  usb-driver-bind)
    iface="${2:-}"
    drv="${3:-}"
    usb_iface_ok "$iface" || die "bad usb iface"
    drv_ok "$drv" || die "bad driver"
    [[ -d "/sys/bus/usb/drivers/$drv" ]] || die "missing usb driver $drv"
    printf '%s' "$iface" > "/sys/bus/usb/drivers/$drv/bind"
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
  fuser-dev)
    # List processes holding a /dev/videoN or /dev/bus/usb/BBB/DDD node.
    path="${2:-}"
    [[ "$path" =~ ^/dev/video[0-9]+$ || "$path" =~ ^/dev/bus/usb/[0-9]{3}/[0-9]{3}$ ]] \
      || die "bad device path"
    [[ -e "$path" ]] || die "missing $path"
    fuser -v "$path" 2>&1 || true
    ;;
  nuxbt-bluez)
    # Host BlueZ --compat --noplugin=* for NUXBT. Action is enable|disable|status only.
    action="${2:-status}"
    [[ "$action" == "enable" || "$action" == "disable" || "$action" == "status" ]] \
      || die "nuxbt-bluez action must be enable|disable|status"
    root="${STEAMOS_PLAYBOOK_DIR:-}"
    if [[ -z "$root" ]]; then
      root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    fi
    override="$root/scripts/nuxbt-bluez-override.sh"
    [[ -x "$override" || -f "$override" ]] || die "missing $override"
    exec bash "$override" "$action"
    ;;
  *)
    die "usage: usb-authorized|usb-port-disable|usb-remove|usb-pci-reset|usb-pci-rebind|usb-driver-*|hid-*|fuser-dev|nuxbt-bluez"
    ;;
esac
