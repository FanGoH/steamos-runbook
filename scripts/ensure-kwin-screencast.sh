#!/usr/bin/env bash
# Unstick KWin's screenshot/screencast framebuffer when it is all black.
#
# On AMD GFX12 (RDNA4) + KWin 6.7, the compositor can keep scanning out a
# visible desktop while ScreenShot2 and PipeWire screencast buffers are zeros.
# Reinitializing compositing recreates the FBO. Do not kwin_wayland --replace.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

png_has_pixels() {
  local path="$1"
  python3 - "$path" <<'PY'
import struct, sys, zlib
from pathlib import Path
p = Path(sys.argv[1])
if not p.is_file() or p.stat().st_size < 64:
    sys.exit(1)
data = p.read_bytes()
if data[:8] != b"\x89PNG\r\n\x1a\n":
    sys.exit(1)
i = 8
idat = b""
while i + 12 <= len(data):
    ln = struct.unpack(">I", data[i:i + 4])[0]
    typ = data[i + 4:i + 8]
    chunk = data[i + 8:i + 8 + ln]
    if typ == b"IDAT":
        idat += chunk
    elif typ == b"IEND":
        break
    i += 12 + ln
if not idat:
    sys.exit(1)
raw = zlib.decompress(idat)
sys.exit(0 if any(raw) else 1)
PY
}

take_screenshot() {
  local dest="$1"
  rm -f "$dest"
  timeout 40 spectacle -b -n -o "$dest" >/dev/null 2>&1 || true
  [ -s "$dest" ]
}

reinit_compositor() {
  qdbus org.kde.KWin /Compositor org.kde.kwin.Compositing.reinitialize >/dev/null
  sleep 2
}

if [ "${XDG_SESSION_TYPE:-}" = "x11" ]; then
  echo "X11 session — KWin Wayland screencast not used."
  exit 0
fi

if systemctl --user is-active gamescope-session.service >/dev/null 2>&1; then
  echo "Game Mode session — KWin screencast not used."
  exit 0
fi

if ! systemctl --user is-active plasma-plasmashell.service >/dev/null 2>&1 \
  && ! qdbus org.kde.KWin /Compositor org.kde.kwin.Compositing.active >/dev/null 2>&1; then
  echo "Plasma / KWin not active; skip screencast recovery."
  exit 0
fi

if ! command -v spectacle >/dev/null 2>&1; then
  echo "spectacle not installed; reinitializing KWin compositor as a precaution."
  if reinit_compositor; then
    echo "KWin compositor reinitialized."
    exit 0
  fi
  record_manual "Reinitialize KWin compositor (black screencast)" <<'EOF'
export XDG_RUNTIME_DIR=/run/user/$(id -u)
qdbus org.kde.KWin /Compositor org.kde.kwin.Compositing.reinitialize
# Do not: kwin_wayland --replace
EOF
  exit 2
fi

shot="$(mktemp /tmp/steamos-kwin-screencast.XXXXXX.png)"
trap 'rm -f "$shot"' EXIT

if take_screenshot "$shot" && png_has_pixels "$shot"; then
  echo "KWin screenshot has pixels; screencast FBO looks OK."
  exit 0
fi

echo "KWin screenshot is missing or all black; reinitializing compositor."
if ! reinit_compositor; then
  record_manual "Reinitialize KWin compositor (black screencast)" <<'EOF'
export XDG_RUNTIME_DIR=/run/user/$(id -u)
qdbus org.kde.KWin /Compositor org.kde.kwin.Compositing.reinitialize
# Do not: kwin_wayland --replace
EOF
  exit 2
fi

if take_screenshot "$shot" && png_has_pixels "$shot"; then
  echo "KWin screenshot has pixels after compositor reinitialize."
  exit 0
fi

echo "KWin screenshot still black after reinitialize."
record_manual "KWin screencast still black after compositor reinitialize" <<'EOF'
export XDG_RUNTIME_DIR=/run/user/$(id -u)
qdbus org.kde.KWin /Compositor org.kde.kwin.Compositing.reinitialize
# Optional: cap the output at 8 bpc, then reinitialize again
# kscreen-doctor output.HDMI-A-1.maxbpc.8
# Do not: kwin_wayland --replace
EOF
exit 2
