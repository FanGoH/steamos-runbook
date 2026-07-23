#!/usr/bin/env bash
# Ensure pacman keyrings are initialized after SteamOS updates.
# Auto-runs: steamos-readonly disable → pacman-key --init → populate archlinux+holo → restore readonly.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

if ! command -v pacman >/dev/null 2>&1; then
  echo "pacman not found on PATH."
  record_manual "Install / restore pacman (unexpected on SteamOS)" <<'EOF'
# SteamOS normally ships pacman. If it is missing, something is very wrong
# with the rootfs. Re-check after a SteamOS update or recovery image.
EOF
  exit 1
fi

if pacman_keyring_ok; then
  echo "pacman keyring already OK."
  exit 0
fi

echo "pacman keyring needs re-init (archlinux + holo)."
echo "SteamOS updates often reset pacman trust; applying fix..."

readonly_was="$(steamos_readonly_disable_if_needed)"
echo "steamos-readonly previous state: $readonly_was"

sudo pacman-key --init
init_rc=$?
sudo pacman-key --populate archlinux
arch_rc=$?
holo_rc=0
if [ -f /usr/share/pacman/keyrings/holo.gpg ]; then
  sudo pacman-key --populate holo
  holo_rc=$?
else
  echo "Warning: /usr/share/pacman/keyrings/holo.gpg not found; skipping holo populate."
fi

steamos_readonly_restore "$readonly_was"


if [ "$init_rc" -ne 0 ] || [ "$arch_rc" -ne 0 ] || [ "$holo_rc" -ne 0 ]; then
  echo "pacman-key commands failed (init=$init_rc arch=$arch_rc holo=$holo_rc)."
  record_manual "Retry pacman keyring init manually" <<EOF
# If this fails with read-only errors, unmerge systemd-sysext overlays first, then:
$(pacman_keyring_commands)
EOF
  exit 1
fi

if pacman_keyring_ok; then
  echo "pacman keyring re-initialized successfully."
  exit 0
fi

echo "pacman-key ran but trustdb still looks unhealthy."
record_manual "Retry pacman keyring init manually" <<EOF
$(pacman_keyring_commands)
EOF
exit 1
