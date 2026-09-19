#!/usr/bin/env bash
# Detect the pad-hide sysfs sudoers drop-in (SSH). Decky PluginLoader is
# already root and does not need this. Do not write /etc (needs password +
# steamos-readonly). SteamOS updates wipe /etc/sudoers.d and udev.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

HELPER="$ROOT/scripts/hide-controllers-sysfs.sh"
SRC="$ROOT/sudoers/zzz-hide-controllers"
DEST="/etc/sudoers.d/zzz-hide-controllers"
UDEV_SRC="$ROOT/udev/99-hide-controllers.rules"
UDEV_DEST="/etc/udev/rules.d/99-hide-controllers.rules"

if [ ! -x "$HELPER" ]; then
  echo "Missing $HELPER"
  exit 1
fi

if ! python3 "$ROOT/scripts/hide-controllers.py" self-test >/dev/null; then
  echo "hide-controllers self-test failed."
  exit 1
fi

helper_nopasswd() {
  sudo -n "$HELPER" >/dev/null 2>&1
  rc=$?
  # usage error (2) still means sudo accepted the binary
  [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]
}

ask_install() {
  record_manual "install zzz-hide-controllers (after wheel) + udev" <<EOF
# Last sudoers match wins. zzz- sorts after wheel. Filename must not contain a dot.
# SteamOS root is readonly; a SteamOS update can wipe this drop-in.
sudo steamos-readonly disable
sudo install -m 440 $SRC $DEST
sudo visudo -cf $DEST
sudo install -m 644 $UDEV_SRC $UDEV_DEST
sudo udevadm control --reload
sudo steamos-readonly enable
sudo -n $HELPER
# Decky QAM does not need this (PluginLoader is root). SSH hide/show does.
EOF
}

# /etc writes need steamos-readonly. QAM Playbook sets SUDO_ASKPASS.
install_hide_etc() {
  local prev="none"
  if command -v steamos-readonly >/dev/null 2>&1; then
    if steamos-readonly status 2>/dev/null | grep -qi 'disabled\|disable'; then
      prev="disabled"
    else
      playbook_sudo steamos-readonly disable || return 1
      prev="enabled"
    fi
  fi
  playbook_sudo install -m 440 "$SRC" "$DEST" || return 1
  playbook_sudo visudo -cf "$DEST" || return 1
  playbook_sudo install -m 644 "$UDEV_SRC" "$UDEV_DEST" || return 1
  playbook_sudo udevadm control --reload || true
  if [ "$prev" = "enabled" ]; then
    playbook_sudo steamos-readonly enable || true
  fi
  echo "Installed $DEST and $UDEV_DEST."
}

if helper_nopasswd; then
  echo "sudo -n $HELPER works (SSH hide/show)."
  if [ -f "$UDEV_DEST" ]; then
    exit 0
  fi
  echo "udev $UDEV_DEST is missing; installing it."
  if install_hide_etc; then
    exit 0
  fi
  echo "Could not write $UDEV_DEST automatically (need sudo for steamos-readonly)."
  ask_install
  exit 2
fi

echo "sudo -n $HELPER is not allowed (SSH hide needs the sudoers drop-in)."
if install_hide_etc && helper_nopasswd; then
  echo "sudo -n $HELPER works after installing the drop-in."
  exit 0
fi
ask_install
exit 2
