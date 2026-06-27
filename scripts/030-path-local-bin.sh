#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a
source "$ROOT/.env"
set +a

line='export PATH="$HOME/.local/bin:$PATH"'

for file in "/home/$STEAMOS_USER/.bashrc" "/home/$STEAMOS_USER/.bash_profile"; do
  touch "$file"
  if grep -Fxq "$line" "$file"; then
    echo "$file already configured."
  else
    echo "$line" >> "$file"
    echo "Added ~/.local/bin to PATH in $file."
  fi
done
