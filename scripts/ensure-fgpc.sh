#!/usr/bin/env bash
# Install ~/.local/bin/fgpc (Typer + Rich playbook CLI).
# Prefers a uv venv under ~/.local/share/fgpc so / stays small.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

PKG="$ROOT/fgpc"
BIN_DIR="/home/${STEAMOS_USER:-deck}/.local/bin"
VENV="${FGPC_VENV:-/home/${STEAMOS_USER:-deck}/.local/share/fgpc/venv}"
WRAPPER="$BIN_DIR/fgpc"

if [ ! -f "$PKG/pyproject.toml" ] || [ ! -f "$PKG/src/fgpc/app.py" ]; then
  echo "Missing $PKG (fgpc package)."
  exit 1
fi

mkdir -p "$BIN_DIR" "$(dirname "$VENV")"

# sudo ./post-update.sh leaves root-owned dist-info; pip cannot upgrade.
if [ -d "$VENV" ] && find "$VENV" -user root -print -quit 2>/dev/null | grep -q .; then
  echo "Fixing root-owned files in $VENV (leftover from sudo ./post-update.sh)."
  if ! playbook_sudo chown -R "${STEAMOS_USER}:${STEAMOS_USER}" "$VENV"; then
    VENV="${VENV}-deck"
    echo "Could not chown; using $VENV instead."
  fi
fi
if [ ! -x "$VENV/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV" --python python3
  else
    python3 -m venv "$VENV"
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$VENV/bin/python" -e "$PKG"
else
  "$VENV/bin/pip" install -e "$PKG"
fi

if ! "$VENV/bin/python" -c 'import fgpc, typer, rich' >/dev/null; then
  echo "fgpc import failed in $VENV"
  exit 1
fi

cat >"$WRAPPER" <<EOF
#!/usr/bin/env bash
export STEAMOS_PLAYBOOK_DIR="${ROOT}"
export XDG_RUNTIME_DIR="\${XDG_RUNTIME_DIR:-/run/user/\$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="\${DBUS_SESSION_BUS_ADDRESS:-unix:path=\${XDG_RUNTIME_DIR}/bus}"
exec "${VENV}/bin/fgpc" "\$@"
EOF
chmod +x "$WRAPPER"

if ! "$WRAPPER" self-test >/dev/null; then
  echo "fgpc self-test failed."
  exit 1
fi

echo "Installed $WRAPPER (venv $VENV)."
echo "Try: fgpc    fgpc tips    fgpc pad list    fgpc complete install"
if ! command -v fgpc >/dev/null 2>&1; then
  echo "fgpc is not on PATH yet. Open a new shell or:"
  echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
exit 0
