#!/usr/bin/env bash
# Give Distrobox sunshine-ds (uid deck) access to /dev/uhid.
# gamepad=switch / auto / xseries use libvirtualhid UHID; uinput x360 does not.
# SteamOS updates wipe /etc/udev/rules.d.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

SRC="$ROOT/udev/99-sunshine-uhid.rules"
DEST="/etc/udev/rules.d/99-sunshine-uhid.rules"

uhid_ok() {
  [ -e /dev/uhid ] && [ -w /dev/uhid ]
}

ask_install() {
  record_manual "udev uaccess for /dev/uhid (Switch / Lichii raw pad)" <<EOF
# Distrobox sunshine-ds is uid deck. /dev/uhid is 600 root without this.
# gamepad=switch then logs: create libvirtualhid gamepad: failed to open /dev/uhid
# Lichii Raw Gamepad stays empty until the Nintendo HID node exists.
sudo steamos-readonly disable
sudo install -m 644 $SRC $DEST
sudo udevadm control --reload
sudo udevadm trigger --name-match=uhid
sudo steamos-readonly enable
# Confirm: test -w /dev/uhid && echo uhid writable
# Then restart desktop DS (drops a live Moonlight session):
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
$ROOT/scripts/ensure-sunshine-ds.sh --restart --force
EOF
}

install_udev() {
  local prev="none"
  if command -v steamos-readonly >/dev/null 2>&1; then
    if steamos-readonly status 2>/dev/null | grep -qi 'disabled\|disable'; then
      prev="disabled"
    else
      playbook_sudo steamos-readonly disable || return 1
      prev="enabled"
    fi
  fi
  playbook_sudo install -m 644 "$SRC" "$DEST" || return 1
  playbook_sudo udevadm control --reload || true
  playbook_sudo udevadm trigger --name-match=uhid || true
  if [ "$prev" = "enabled" ]; then
    playbook_sudo steamos-readonly enable || true
  fi
  echo "Installed $DEST."
}

if [ ! -f "$SRC" ]; then
  echo "Missing $SRC"
  exit 1
fi

if uhid_ok; then
  echo "/dev/uhid is writable by $(id -un) (Switch / Lichii raw pad)."
  exit 0
fi

echo "/dev/uhid is not writable by $(id -un) (mode $(stat -c '%a' /dev/uhid 2>/dev/null || echo ?))."
if [ -f "$DEST" ] && cmp -s "$SRC" "$DEST"; then
  echo "udev rule is installed; trigger it: sudo udevadm trigger --name-match=uhid"
  ask_install
  exit 2
fi

if install_udev && uhid_ok; then
  echo "/dev/uhid is writable after udev install."
  exit 0
fi

ask_install
exit 2
