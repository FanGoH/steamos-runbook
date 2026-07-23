#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

if ! systemctl list-unit-files sshd.service >/dev/null 2>&1; then
  echo "sshd.service not found on this system."
  exit 1
fi

changed=0

if ! systemctl is-enabled sshd.service >/dev/null 2>&1; then
  sudo systemctl enable sshd.service
  changed=1
  echo "Enabled sshd.service."
else
  echo "sshd.service already enabled."
fi

if ! systemctl is-active sshd.service >/dev/null 2>&1; then
  sudo systemctl start sshd.service
  changed=1
  echo "Started sshd.service."
else
  echo "sshd.service already active."
fi

if [ "$changed" -eq 0 ]; then
  echo "sshd OK."
fi
