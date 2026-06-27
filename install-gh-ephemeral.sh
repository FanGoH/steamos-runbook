#!/usr/bin/env bash
set -euo pipefail

BOX="gh-installer-temp"
IMAGE="registry.fedoraproject.org/fedora:42"

mkdir -p "$HOME/.local/bin"

distrobox rm --force "$BOX" >/dev/null 2>&1 || true
distrobox create --name "$BOX" --image "$IMAGE" --yes

distrobox enter "$BOX" -- bash -lc '
  set -euo pipefail
  sudo dnf install -y gh
'

distrobox enter "$BOX" -- bash -lc 'cat /usr/bin/gh' > "$HOME/.local/bin/gh"
chmod +x "$HOME/.local/bin/gh"

distrobox rm --force "$BOX"

echo "Installed gh to $HOME/.local/bin/gh"
"$HOME/.local/bin/gh" --version
