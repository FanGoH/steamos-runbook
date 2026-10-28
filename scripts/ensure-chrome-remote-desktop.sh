#!/usr/bin/env bash
# Install / restore Chrome Remote Desktop host after a SteamOS update.
# Official Google .deb is extracted under /home; /opt/google is a symlink.
# Google account + PIN are never automated.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

HELPER="$ROOT/scripts/chrome_remote_desktop.py"
HOME_DIR="/home/${STEAMOS_USER}"
CRD_HOME="${CRD_HOME:-${HOME_DIR}/.local/share/chrome-remote-desktop}"
CRD_OPT_HOME="${CRD_HOME}/opt/google/chrome-remote-desktop"
CRD_OPT="${CRD_OPT:-/opt/google/chrome-remote-desktop}"
CRD_DEB_URL="${CRD_DEB_URL:-https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb}"
CRD_CACHE="${CRD_HOME}/cache/chrome-remote-desktop_current_amd64.deb"
CRD_SERVICE="${CRD_SERVICE:-chrome-remote-desktop@${STEAMOS_USER}.service}"
CRD_UNIT_PATH="${CRD_UNIT_PATH:-/etc/systemd/system/chrome-remote-desktop@.service}"
CRD_PAM_PATH="${CRD_PAM_PATH:-/etc/pam.d/chrome-remote-desktop}"
CRD_CONFIG_DIR="${CRD_CONFIG_DIR:-${HOME_DIR}/.config/chrome-remote-desktop}"
CRD_SESSION="${CRD_SESSION:-${HOME_DIR}/.chrome-remote-desktop-session}"
CRD_FLATPAK_ID="${CRD_FLATPAK_ID:-com.google.Chrome}"
XORG_DEBIAN="${CRD_XORG_DEBIAN:-/usr/lib/xorg/Xorg}"
XORG_ARCH="${CRD_XORG_ARCH:-/usr/lib/Xorg}"

if [ "${1:-}" = "--self-test" ]; then
  python3 "$HELPER" self-test
  python3 "$ROOT/scripts/test_chrome_remote_desktop.py"
  echo "ensure-chrome-remote-desktop self-test OK."
  exit 0
fi

if [ "${1:-}" = "--status" ]; then
  exec "$ROOT/scripts/crd.sh" status
fi

if [ "${1:-}" = "--usage" ]; then
  python3 "$HELPER" usage --user "$STEAMOS_USER"
  exit 0
fi

if [ ! -f "$HELPER" ]; then
  echo "Missing $HELPER"
  exit 1
fi

install_chrome_flatpak() {
  if flatpak info --user "$CRD_FLATPAK_ID" >/dev/null 2>&1 \
    || flatpak info "$CRD_FLATPAK_ID" >/dev/null 2>&1; then
    echo "Chrome Flatpak already installed ($CRD_FLATPAK_ID)."
    return 0
  fi
  if ! command -v flatpak >/dev/null 2>&1; then
    echo "flatpak missing; skip Chrome browser install (headless host does not need it)."
    return 0
  fi
  local remote="${FLATPAK_REMOTE:-flathub}"
  if ! flatpak remotes --user 2>/dev/null | awk '{print $1}' | grep -Fxq "$remote"; then
    if ! flatpak remotes 2>/dev/null | awk '{print $1}' | grep -Fxq "$remote"; then
      flatpak remote-add --user --if-not-exists "$remote" "https://dl.flathub.org/repo/flathub.flatpakrepo" || true
    fi
  fi
  echo "Installing Chrome Flatpak ($CRD_FLATPAK_ID) for the setup UI..."
  if flatpak install --user -y "$remote" "$CRD_FLATPAK_ID"; then
    echo "Installed $CRD_FLATPAK_ID."
    return 0
  fi
  echo "Chrome Flatpak install skipped (headless start-host still works)."
}

extract_host() {
  mkdir -p "$CRD_HOME/cache" "$CRD_HOME/extract"
  if [ ! -x "$CRD_OPT_HOME/chrome-remote-desktop" ] || [ ! -x "$CRD_OPT_HOME/start-host" ]; then
    if [ ! -s "$CRD_CACHE" ]; then
      echo "Downloading Chrome Remote Desktop host (.deb) to $CRD_CACHE"
      if ! curl -fsSL --max-time 120 -o "$CRD_CACHE.new" "$CRD_DEB_URL"; then
        rm -f "$CRD_CACHE.new"
        record_manual "Download Chrome Remote Desktop host .deb" <<EOF
curl -fsSL -o $CRD_CACHE $CRD_DEB_URL
./scripts/ensure-chrome-remote-desktop.sh
EOF
        return 1
      fi
      mv "$CRD_CACHE.new" "$CRD_CACHE"
    else
      echo "Using cached .deb $CRD_CACHE"
    fi
    echo "Extracting host into $CRD_OPT_HOME"
    rm -rf "$CRD_HOME/extract"
    mkdir -p "$CRD_HOME/extract"
    (
      cd "$CRD_HOME/extract"
      ar x "$CRD_CACHE"
      bsdtar -xf data.tar.*
    )
    mkdir -p "$(dirname "$CRD_OPT_HOME")"
    rm -rf "$CRD_OPT_HOME"
    cp -a "$CRD_HOME/extract/opt/google/chrome-remote-desktop" "$CRD_OPT_HOME"
    rm -rf "$CRD_HOME/extract"
    echo "Host extracted ($(du -sh "$CRD_OPT_HOME" | awk '{print $1}'))."
  else
    echo "Host already extracted at $CRD_OPT_HOME"
  fi
  if [ ! -x "$CRD_OPT_HOME/chrome-remote-desktop" ]; then
    echo "Extracted host is missing chrome-remote-desktop."
    return 1
  fi
}

install_root_bits() {
  local readonly_was desired
  readonly_was="$(steamos_readonly_disable_if_needed)"
  echo "steamos-readonly previous state: $readonly_was"

  sudo mkdir -p /opt/google /usr/lib/xorg /etc/pam.d /etc/systemd/system
  if [ ! -e "$CRD_OPT" ] || [ -L "$CRD_OPT" ]; then
    if [ "$(readlink -f "$CRD_OPT" 2>/dev/null || true)" != "$(readlink -f "$CRD_OPT_HOME")" ]; then
      sudo ln -sfn "$CRD_OPT_HOME" "$CRD_OPT"
      echo "Linked $CRD_OPT -> $CRD_OPT_HOME"
    else
      echo "$CRD_OPT already points at the /home host."
    fi
  elif [ ! -x "$CRD_OPT/chrome-remote-desktop" ]; then
    echo "$CRD_OPT exists and is not our symlink; leaving it."
  else
    echo "$CRD_OPT already has a host binary."
  fi

  if [ -x "$XORG_ARCH" ] && [ ! -e "$XORG_DEBIAN" ]; then
    sudo ln -s "$XORG_ARCH" "$XORG_DEBIAN"
    echo "Linked $XORG_DEBIAN -> $XORG_ARCH (CRD looks for the Debian path)."
  elif [ -e "$XORG_DEBIAN" ]; then
    echo "Xorg Debian path already present ($XORG_DEBIAN)."
  else
    echo "Warning: $XORG_ARCH missing; virtual session may fail."
  fi

  desired="$(python3 "$HELPER" pam)"
  if [ ! -f "$CRD_PAM_PATH" ] || [ "$(sudo cat "$CRD_PAM_PATH")" != "$desired" ]; then
    python3 "$HELPER" pam | sudo tee "$CRD_PAM_PATH" >/dev/null
    echo "Updated $CRD_PAM_PATH (Arch system-remote-login)."
  else
    echo "PAM $CRD_PAM_PATH already current."
  fi

  desired="$(python3 "$HELPER" unit)"
  if [ ! -f "$CRD_UNIT_PATH" ] || [ "$(sudo cat "$CRD_UNIT_PATH")" != "$desired" ]; then
    python3 "$HELPER" unit | sudo tee "$CRD_UNIT_PATH" >/dev/null
    sudo systemctl daemon-reload
    echo "Updated $CRD_UNIT_PATH"
  else
    echo "$CRD_UNIT_PATH already current."
  fi

  if ! getent group chrome-remote-desktop >/dev/null 2>&1; then
    sudo groupadd --system chrome-remote-desktop
    echo "Created group chrome-remote-desktop."
  else
    echo "Group chrome-remote-desktop already exists."
  fi
  if id -nG "$STEAMOS_USER" | tr ' ' '\n' | grep -Fxq chrome-remote-desktop; then
    echo "$STEAMOS_USER already in chrome-remote-desktop."
  else
    sudo usermod -aG chrome-remote-desktop "$STEAMOS_USER"
    echo "Added $STEAMOS_USER to chrome-remote-desktop (re-login to pick up the group)."
  fi

  if ! command -v Xvfb >/dev/null 2>&1 || ! python3 -c "from packaging import version" >/dev/null 2>&1; then
    echo "Installing xorg-server-xvfb and python-packaging (virtual session deps)..."
    if ! sudo pacman -S --needed --noconfirm xorg-server-xvfb python-packaging; then
      echo "pacman could not install xvfb/python-packaging."
      steamos_readonly_restore "$readonly_was"
      record_manual "Install Chrome Remote Desktop session deps" <<EOF
./scripts/ensure-pacman.sh
sudo steamos-readonly disable
sudo pacman -S --needed xorg-server-xvfb python-packaging
sudo steamos-readonly enable
./scripts/ensure-chrome-remote-desktop.sh
EOF
      return 1
    fi
  else
    echo "Xvfb and python-packaging already present."
  fi

  steamos_readonly_restore "$readonly_was"
}

write_session_file() {
  mkdir -p "$CRD_CONFIG_DIR"
  if [ -f "$CRD_SESSION" ]; then
    echo "Session file already present ($CRD_SESSION)."
    return 0
  fi
  python3 "$HELPER" session >"$CRD_SESSION"
  chmod 644 "$CRD_SESSION"
  echo "Wrote $CRD_SESSION (Plasma X11 virtual session)."
}

link_crd_wrapper() {
  mkdir -p "${HOME_DIR}/.local/bin"
  ln -sfn "$ROOT/scripts/crd.sh" "${HOME_DIR}/.local/bin/crd"
  echo "Linked ${HOME_DIR}/.local/bin/crd -> scripts/crd.sh"
}

install_chrome_flatpak
extract_host
install_root_bits
write_session_file
link_crd_wrapper

if [ ! -x "$CRD_OPT/chrome-remote-desktop" ]; then
  echo "Host binary missing at $CRD_OPT after install."
  record_manual "Retry Chrome Remote Desktop host install" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
./scripts/ensure-chrome-remote-desktop.sh
EOF
  exit 1
fi

echo "Host: $CRD_OPT/chrome-remote-desktop"
echo "Service: $CRD_SERVICE (system unit, not a user unit)"

if python3 "$HELPER" registered --config-dir "$CRD_CONFIG_DIR"; then
  echo "Host is registered ($CRD_CONFIG_DIR)."
  if ! systemctl is-enabled "$CRD_SERVICE" >/dev/null 2>&1; then
    sudo systemctl enable "$CRD_SERVICE"
    echo "Enabled $CRD_SERVICE."
  else
    echo "$CRD_SERVICE already enabled."
  fi
  if systemctl is-active "$CRD_SERVICE" >/dev/null 2>&1; then
    echo "$CRD_SERVICE already active."
  else
    sudo systemctl start "$CRD_SERVICE" || true
    echo "Started $CRD_SERVICE."
  fi
  if systemctl is-active "$CRD_SERVICE" >/dev/null 2>&1; then
    echo "Chrome Remote Desktop host is running."
    echo "Connect from https://remotedesktop.google.com/access (same Google account + PIN)."
    exit 0
  fi
  echo "Warning: $CRD_SERVICE is not active."
  record_manual "Start Chrome Remote Desktop host" <<EOF
sudo systemctl start $CRD_SERVICE
sudo journalctl -u $CRD_SERVICE -n 80 --no-pager
./scripts/crd.sh status
EOF
  exit 2
fi

echo "Host files are installed; Google registration is still needed."
record_manual "Register Chrome Remote Desktop (Google PIN)" <<EOF
$(python3 "$HELPER" setup-manual --user "$STEAMOS_USER")
EOF
exit 2
