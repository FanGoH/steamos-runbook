#!/usr/bin/env bash
# Ensure /dev/uhid is usable by sunshine-ds (Switch Pro / DualSense / DS4).
# Xbox 360 gamepads use uinput and do not need this. SteamOS updates wipe
# /etc/udev/rules.d. Do not write /etc without steamos-readonly + sudo.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

UDEV_SRC="$ROOT/udev/99-libvirtualhid-uhid.rules"
UDEV_DEST="/etc/udev/rules.d/99-libvirtualhid-uhid.rules"
UHID_NODE="/dev/uhid"

uhid_writable() {
  python3 - <<'PY'
import os
path = "/dev/uhid"
try:
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
except OSError as exc:
    print(f"uhid not writable: {exc}")
    raise SystemExit(1)
os.close(fd)
print("uhid writable")
raise SystemExit(0)
PY
}

ask_install() {
  record_manual "install 99-libvirtualhid-uhid.rules (/dev/uhid for switch/ds5)" <<EOF
# Switch Pro / DualSense / DS4 Sunshine pads need /dev/uhid (x360 uses uinput).
# SteamOS root is readonly; a SteamOS update can wipe this rule.
# Rule must TAG+=seat + uaccess (uaccess alone does not ACL deck).
sudo steamos-readonly disable
sudo install -m 644 $UDEV_SRC $UDEV_DEST
sudo udevadm control --reload
sudo udevadm trigger --action=add --sysname-match=uhid
# Immediate ACL if trigger did not land user:deck yet:
sudo setfacl -m u:deck:rw /dev/uhid
# Optional persistence across weird boots (deck is not in input by default):
sudo usermod -aG input deck
sudo steamos-readonly enable
ls -l /dev/uhid
getfacl /dev/uhid
# New group membership needs a fresh login for existing sessions.
# Then: GAMESTREAM_PAD_PROFILE=switch, ensure-sunshine-ds-apps.sh,
# systemctl --user restart steamos-sunshine-ds-gamemode.service, reconnect.
EOF
}

install_uhid_udev() {
  local prev="none"
  if command -v steamos-readonly >/dev/null 2>&1; then
    if steamos-readonly status 2>/dev/null | grep -qi 'disabled\|disable'; then
      prev="disabled"
    else
      playbook_sudo steamos-readonly disable || return 1
      prev="enabled"
    fi
  fi
  playbook_sudo install -m 644 "$UDEV_SRC" "$UDEV_DEST" || return 1
  playbook_sudo udevadm control --reload || true
  playbook_sudo udevadm trigger --property-match=DEVNAME=/dev/uhid || true
  if [ "$prev" = "enabled" ]; then
    playbook_sudo steamos-readonly enable || true
  fi
  echo "Installed $UDEV_DEST."
}

if [ ! -f "$UDEV_SRC" ]; then
  echo "Missing $UDEV_SRC"
  exit 1
fi

if [ ! -e "$UHID_NODE" ]; then
  echo "$UHID_NODE missing — loading uhid module."
  if playbook_sudo modprobe uhid; then
    :
  else
    record_manual "modprobe uhid" <<EOF
sudo modprobe uhid
ls -l /dev/uhid
EOF
    exit 2
  fi
fi

if uhid_writable; then
  if [ -f "$UDEV_DEST" ]; then
    echo "/dev/uhid is writable; $UDEV_DEST present."
    exit 0
  fi
  echo "/dev/uhid is writable but $UDEV_DEST is missing (ACL may be ephemeral)."
  if install_uhid_udev; then
    exit 0
  fi
  ask_install
  exit 2
fi

echo "/dev/uhid is not writable by $(id -un) — Switch/ds5/ds4 pads will fail."
ls -l "$UHID_NODE" 2>/dev/null || true
getfacl "$UHID_NODE" 2>/dev/null || true

if [ ! -f "$UDEV_DEST" ]; then
  echo "Installing $UDEV_DEST."
  if install_uhid_udev && uhid_writable; then
    exit 0
  fi
fi

ask_install
exit 2
