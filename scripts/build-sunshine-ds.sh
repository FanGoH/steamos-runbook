#!/usr/bin/env bash
# Build sunshine-ds from the FanGoH Sunshine fork. Does not install over the
# Decky Flatpak.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

SRC="${SUNSHINE_DS_SRC:-/home/${STEAMOS_USER}/code/sunshine-ds}"
REPO="${SUNSHINE_DS_REPO:-https://github.com/FanGoH/Sunshine.git}"
BRANCH="${SUNSHINE_DS_BRANCH:-sunshine-ds-linux}"
BOX="${STEAMOS_DISTROBOX_NAME:-steamos-tools}"
BIN_DIR="${SUNSHINE_DS_BIN_DIR:-/home/${STEAMOS_USER}/.local/bin}"
BUILD_DIR="${SUNSHINE_DS_BUILD_DIR:-$SRC/build}"

if [ ! -d "$SRC/.git" ]; then
  echo "Cloning $REPO ($BRANCH) into $SRC"
  git clone --recurse-submodules -b "$BRANCH" "$REPO" "$SRC"
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

distrobox enter "$BOX" -- bash -lc "
set -euo pipefail
$(printf %q "$SRC/tools/kwin-virtual-output/build.sh") $(printf %q "$BIN_DIR/sunshine-ds-virtual-output")
"
chmod 0755 "$BIN_DIR/sunshine-ds-virtual-output"
echo "Installed $BIN_DIR/sunshine-ds and $BIN_DIR/sunshine-ds-virtual-output from $REPO ($BRANCH)."
echo "Production Flatpak Sunshine is unchanged."
