#!/usr/bin/env bash
# Full post-update verification checklist (run by post-update.sh and standalone).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

MANUAL_ACTIONS_FILE="${MANUAL_ACTIONS_FILE:-$ROOT/logs/manual-actions-health.txt}"
export MANUAL_ACTIONS_FILE
mkdir -p "$ROOT/logs"
# Only truncate when we own a dedicated health file (post-update may already have one)
if [ "$MANUAL_ACTIONS_FILE" = "$ROOT/logs/manual-actions-health.txt" ]; then
  : >"$MANUAL_ACTIONS_FILE"
fi

ok() { echo "✅ $1"; }
warn() { echo "⚠️  $1"; }
fail() { echo "❌ $1"; FAILED=1; }

FAILED=0

echo "== SteamOS health check =="
echo

echo "[SteamOS]"
if [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  if [ -n "${VERSION_ID:-}" ]; then
    ok "SteamOS ${VERSION_ID} (${NAME:-SteamOS})"
  else
    ok "${PRETTY_NAME:-SteamOS detected}"
  fi
else
  warn "Could not read /etc/os-release"
fi
echo

echo "[Pacman]"
bash "$ROOT/scripts/check-pacman.sh" >/tmp/steamos-playbook-pacman-check.out 2>&1
pacman_rc=$?
if [ "$pacman_rc" -eq 0 ]; then
  ok "pacman keyring looks OK"
elif [ "$pacman_rc" -eq 2 ]; then
  fail "pacman keyring needs re-init"
  record_manual "Re-initialize pacman keyrings" <<'EOF'
./scripts/ensure-pacman.sh
EOF
else
  fail "pacman check failed"
fi
grep -E '^(pacman |  - )' /tmp/steamos-playbook-pacman-check.out 2>/dev/null | sed 's/^/  /' || true
echo

echo "[Networking]"
if command -v ip >/dev/null 2>&1; then
  ip -br addr show 2>/dev/null | sed 's/^/  /' || true
  ip -4 addr show scope global 2>/dev/null | awk '/inet / {print "  inet " $2 " on " $NF}' || true
  default_route="$(ip route show default 2>/dev/null | head -1)"
  if [ -n "$default_route" ]; then
    ok "Default route: $default_route"
  else
    fail "No default route"
  fi
else
  fail "ip command missing"
fi
echo

echo "[SSH]"
if systemctl is-active sshd.service >/dev/null 2>&1; then
  ok "sshd active"
else
  fail "sshd not active"
  record_manual "Enable/start sshd" <<'EOF'
sudo systemctl enable --now sshd.service
EOF
fi
if systemctl is-enabled sshd.service >/dev/null 2>&1; then
  ok "sshd enabled"
else
  fail "sshd not enabled"
fi
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -qE ':22\s'; then
  ok "sshd listening on :22"
else
  warn "Could not confirm sshd listening on :22"
fi
echo

echo "[Tailscale]"
TS="${TAILSCALE_BIN}"
if [ ! -x "$TS" ]; then
  TS="$(command -v tailscale 2>/dev/null || true)"
fi
if [ -n "$TS" ] && [ -x "$TS" ]; then
  if "$TS" status >/dev/null 2>&1; then
    ok "Tailscale connected"
    tailnet_ip="$("$TS" ip -4 2>/dev/null | head -1 || true)"
    if [ -n "$tailnet_ip" ]; then
      ok "Tailnet IP: $tailnet_ip"
    else
      warn "Tailscale up but no IPv4 tailnet address"
    fi
  else
    fail "Tailscale not connected"
    record_manual "Re-login Tailscale to Headscale (do not use --ssh yet)" <<EOF
$(tailscale_up_command)
EOF
  fi
else
  fail "Tailscale not installed"
  record_manual "Install Tailscale via deck-tailscale" <<'EOF'
cd ~/deck-tailscale
sudo bash tailscale.sh
source /etc/profile.d/tailscale.sh
EOF
fi
echo

echo "[Wake-on-LAN]"
if [ ! -d "/sys/class/net/$STEAMOS_NIC_INTERFACE" ]; then
  fail "NIC $STEAMOS_NIC_INTERFACE not found"
elif command -v ethtool >/dev/null 2>&1; then
  wol="$(sudo ethtool "$STEAMOS_NIC_INTERFACE" 2>/dev/null | awk -F': ' '/^[[:space:]]*Wake-on:/{print $2; exit}' | tr -d '[:space:]')"
  if [ "$wol" = "g" ]; then
    ok "Wake-on: g on $STEAMOS_NIC_INTERFACE"
  else
    fail "Wake-on not g on $STEAMOS_NIC_INTERFACE (${wol:-unknown})"
    record_manual "Enable Wake-on-LAN" <<EOF
./scripts/ensure-wol.sh
sudo ethtool $STEAMOS_NIC_INTERFACE | grep -E '^[[:space:]]*Wake-on:'
EOF
  fi
  if systemctl is-enabled wol.service >/dev/null 2>&1; then
    ok "wol.service enabled"
  else
    fail "wol.service not enabled"
  fi
  if systemctl is-active wol.service >/dev/null 2>&1; then
    ok "wol.service active (exited is normal for oneshot)"
  else
    warn "wol.service not active"
  fi
else
  fail "ethtool missing"
  record_manual "Install ethtool" <<'EOF'
./scripts/010-ethtool-present.sh
EOF
fi
echo

echo "[OpenRGB]"
if flatpak info "$OPENRGB_FLATPAK_ID" >/dev/null 2>&1; then
  ok "OpenRGB Flatpak installed ($OPENRGB_FLATPAK_ID)"
else
  fail "OpenRGB Flatpak not installed"
fi

if [ -f "$OPENRGB_UDEV_RULES" ]; then
  ok "OpenRGB udev rules present ($OPENRGB_UDEV_RULES)"
else
  fail "OpenRGB udev rules missing"
  record_manual "Install OpenRGB udev rules" <<'EOF'
./scripts/ensure-openrgb.sh
EOF
fi

if systemctl --user is-enabled openrgb.service >/dev/null 2>&1; then
  ok "openrgb.service enabled"
else
  fail "openrgb.service not enabled"
  record_manual "Enable OpenRGB user service" <<'EOF'
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user enable --now openrgb.service
EOF
fi

if systemctl --user is-active openrgb.service >/dev/null 2>&1; then
  ok "openrgb.service active"
else
  warn "openrgb.service inactive"
fi

if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -qE ":${OPENRGB_SDK_PORT:-6742}\\s"; then
  ok "OpenRGB SDK listening on :${OPENRGB_SDK_PORT:-6742}"
else
  warn "OpenRGB SDK port :${OPENRGB_SDK_PORT:-6742} not listening"
fi
echo

echo "[Sunshine]"
if systemctl --user list-unit-files "$SUNSHINE_USER_SERVICE" >/dev/null 2>&1; then
  if systemctl --user is-enabled "$SUNSHINE_USER_SERVICE" >/dev/null 2>&1; then
    ok "$SUNSHINE_USER_SERVICE enabled"
  else
    fail "$SUNSHINE_USER_SERVICE not enabled"
    record_manual "Enable Sunshine user service" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user enable --now $SUNSHINE_USER_SERVICE
EOF
  fi
  if systemctl --user is-active "$SUNSHINE_USER_SERVICE" >/dev/null 2>&1; then
    ok "$SUNSHINE_USER_SERVICE active"
  else
    fail "$SUNSHINE_USER_SERVICE not active"
  fi
else
  warn "Sunshine user service not found (optional)"
fi
echo

echo "[Gear Lever]"
if flatpak info --user "${GEARLEVER_FLATPAK_ID:-it.mijorus.gearlever}" >/dev/null 2>&1 \
  || flatpak info "${GEARLEVER_FLATPAK_ID:-it.mijorus.gearlever}" >/dev/null 2>&1; then
  ok "Gear Lever installed ($GEARLEVER_FLATPAK_ID)"
else
  fail "Gear Lever not installed"
  record_manual "Install Gear Lever Flatpak" <<'EOF'
./scripts/ensure-gearlever.sh
EOF
fi
echo

echo "[Decky]"
HOMEBREW_DIR="${DECKY_HOMEBREW_DIR:-/home/$STEAMOS_USER/homebrew}"
if [ -e "$HOMEBREW_DIR/services/PluginLoader" ] || [ -d "$HOMEBREW_DIR" ]; then
  ok "Decky files present ($HOMEBREW_DIR)"
else
  warn "Decky files not found (optional)"
fi
echo

print_manual_summary "$MANUAL_ACTIONS_FILE"
echo

if [ "$FAILED" -eq 0 ]; then
  echo "Health: ✅ OK"
else
  echo "Health: ❌ issues found"
fi

exit "$FAILED"
