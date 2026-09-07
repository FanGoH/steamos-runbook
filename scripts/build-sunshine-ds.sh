#!/usr/bin/env bash
# Build sunshine-ds in Distrobox. Does not install over the Decky Flatpak.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

SRC="${SUNSHINE_DS_SRC:-/home/${STEAMOS_USER}/code/sunshine-ds}"
BOX="${STEAMOS_DISTROBOX_NAME:-steamos-tools}"
BIN_DIR="${SUNSHINE_DS_BIN_DIR:-/home/${STEAMOS_USER}/.local/bin}"
BUILD_DIR="${SUNSHINE_DS_BUILD_DIR:-$SRC/build}"

if [ ! -d "$SRC/.git" ]; then
  echo "Missing Sunshine DS tree at $SRC"
  echo "Clone LizardByte/Sunshine and apply patches/sunshine-ds/000*.patch"
  exit 1
fi

mkdir -p "$BIN_DIR" "$BUILD_DIR"

distrobox enter "$BOX" -- bash -lc "
set -euo pipefail
export CC=gcc CXX=g++
cmake -B $(printf %q "$BUILD_DIR") -G Ninja -S $(printf %q "$SRC") \\
  -DCMAKE_BUILD_TYPE=Release \\
  -DSUNSHINE_ENABLE_CUDA=OFF \\
  -DCUDA_FAIL_ON_MISSING=OFF \\
  -DSUNSHINE_ENABLE_VULKAN=OFF \\
  -DSUNSHINE_ENABLE_TRAY=OFF \\
  -DBUILD_DOCS=OFF \\
  -DBUILD_TESTS=OFF \\
  -DBOOST_USE_STATIC=OFF \\
  -DSUNSHINE_ENABLE_KWIN=ON \\
  -DSUNSHINE_ENABLE_WAYLAND=ON \\
  -DSUNSHINE_ENABLE_DRM=ON \\
  -DSUNSHINE_ENABLE_VAAPI=ON
ninja -C $(printf %q "$BUILD_DIR") sunshine
"

install -m 0755 "$BUILD_DIR/sunshine" "$BIN_DIR/sunshine-ds"

HELPER_SRC="$ROOT/tools/kwin-virtual-output"
GEN="$(mktemp -d /tmp/sunshine-ds-wayland-proto.XXXXXX)"
distrobox enter "$BOX" -- bash -lc "
set -euo pipefail
wayland-scanner client-header $(printf %q "$HELPER_SRC/zkde-screencast-unstable-v1.xml") $(printf %q "$GEN/zkde-screencast-unstable-v1.h")
wayland-scanner private-code $(printf %q "$HELPER_SRC/zkde-screencast-unstable-v1.xml") $(printf %q "$GEN/zkde-screencast-unstable-v1.c")
gcc -O2 -Wall -Wextra -o $(printf %q "$BIN_DIR/sunshine-ds-virtual-output") \\
  $(printf %q "$HELPER_SRC/kwin-virtual-output.c") $(printf %q "$GEN/zkde-screencast-unstable-v1.c") \\
  -I$(printf %q "$GEN") -lwayland-client -lm
"
rm -rf "$GEN"
chmod 0755 "$BIN_DIR/sunshine-ds-virtual-output"
echo "Installed $BIN_DIR/sunshine-ds and $BIN_DIR/sunshine-ds-virtual-output (production Flatpak Sunshine is unchanged)."
