#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
source "$ROOT/.env"
set +a

BOX_NAME="${STEAMOS_DISTROBOX_NAME:-steamos-tools}"
BOX_IMAGE="${STEAMOS_DISTROBOX_IMAGE:-registry.fedoraproject.org/fedora:42}"

if ! command -v distrobox >/dev/null 2>&1; then
  echo "distrobox missing on host."
  exit 1
fi

if ! distrobox list | awk '{print $3}' | grep -Fxq "$BOX_NAME"; then
  echo "Creating distrobox: $BOX_NAME"
  distrobox create --name "$BOX_NAME" --image "$BOX_IMAGE" --yes
else
  echo "Distrobox already exists: $BOX_NAME"
fi

echo "Installing micro inside $BOX_NAME..."
distrobox enter "$BOX_NAME" -- bash -lc '
  set -euo pipefail

  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y micro
  elif command -v apt >/dev/null 2>&1; then
    sudo apt update
    sudo apt install -y micro
  else
    echo "Unsupported distro: no dnf or apt found."
    exit 1
  fi
'

echo "Exporting micro..."
distrobox enter "$BOX_NAME" -- bash -lc '
  set -euo pipefail
  distrobox-export --bin /usr/bin/micro
'

if [ -x "/home/$STEAMOS_USER/.local/bin/micro" ]; then
  echo "micro exported successfully."
else
  echo "micro export failed or not found at ~/.local/bin/micro"
  exit 1
fi
