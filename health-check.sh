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
if sunshine_systemd_enabled || sunshine_systemd_active; then
  fail "systemd $SUNSHINE_USER_SERVICE still enabled/active (duplicates Decky)"
  record_manual "Disable systemd Sunshine; leave Decky as the starter" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
./scripts/ensure-sunshine.sh
EOF
else
  ok "systemd Sunshine autostart disabled (Decky owns start)"
fi

if systemctl --user is-enabled "${SUNSHINE_WATCH_PATH:-steamos-sunshine-watch.path}" >/dev/null 2>&1 \
  && systemctl --user is-enabled "${SUNSHINE_WATCH_SERVICE:-steamos-sunshine-watch.service}" >/dev/null 2>&1; then
  ok "Pulse-ready start ${SUNSHINE_WATCH_PATH:-steamos-sunshine-watch.path} enabled"
else
  fail "Pulse-ready start units not enabled"
  record_manual "Enable Sunshine Pulse-ready start (not the Flatpak Sunshine unit)" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
./scripts/ensure-sunshine.sh
systemctl --user is-enabled ${SUNSHINE_WATCH_PATH:-steamos-sunshine-watch.path}
# Do not: systemctl --user enable --now $SUNSHINE_USER_SERVICE
EOF
fi
if systemctl --user is-enabled "${SUNSHINE_WATCH_TIMER:-steamos-sunshine-watch.timer}" >/dev/null 2>&1; then
  warn "old polling ${SUNSHINE_WATCH_TIMER:-steamos-sunshine-watch.timer} still enabled — re-run ensure-sunshine.sh"
fi

gs_state="$(sunshine_serverinfo_state 2>/dev/null || true)"
if [ "$gs_state" = "FREE" ]; then
  ok "GameStream SUNSHINE_SERVER_FREE"
elif [ "$gs_state" = "BUSY" ]; then
  if sunshine_stream_udp_up; then
    ok "GameStream BUSY with live stream UDP (in session)"
  else
    fail "GameStream stale BUSY (currentgame=$(sunshine_currentgame)) — Moonlight 503"
    record_manual "Clear stale Sunshine session" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
./scripts/ensure-sunshine.sh
curl -s $SUNSHINE_GAMESTREAM_URL/serverinfo
EOF
  fi
else
  fail "GameStream not answering (${SUNSHINE_GAMESTREAM_URL})"
  record_manual "Start Sunshine from Decky Sunshine" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
./scripts/ensure-sunshine.sh
# If that still exits 2: Decky → Sunshine → Start
# Do not: systemctl --user enable --now $SUNSHINE_USER_SERVICE
# Do not: curl .../api/restart
curl -s $SUNSHINE_GAMESTREAM_URL/serverinfo
EOF
fi

login_state="$(sunshine_ui_login_state 2>/dev/null || true)"
case "$login_state" in
  OK)
    ok "Web UI login works (Decky stored creds against ${SUNSHINE_UI_URL}/api/apps)"
    ;;
  DOWN)
    if [ "$gs_state" = "FREE" ] || [ "$gs_state" = "BUSY" ]; then
      fail "Web UI not answering (${SUNSHINE_UI_URL}) while GameStream is up"
    else
      warn "Web UI not answering (${SUNSHINE_UI_URL})"
    fi
    ;;
  NO_CREDS)
    warn "No Decky lastAuthHeader — cannot test Web UI login"
    ;;
  UNAUTH_HASH_OK)
    fail "Web UI 401 but Decky password still matches sunshine_state.json (not reset)"
    record_manual "Restart Sunshine — credentials are valid, UI is rejecting login" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
./scripts/ensure-sunshine.sh
# Then open ${SUNSHINE_UI_URL} as decky_sunshine with the existing Decky password.
# Do not generate a new password.
EOF
    ;;
  UNAUTH_MISMATCH|UNAUTH)
    fail "Web UI login failed (Decky stored creds rejected)"
    record_manual "Re-enter the existing Decky Sunshine password (do not generate a new one first)" <<EOF
# Decky → Sunshine → login with the existing password
# Confirm at ${SUNSHINE_UI_URL}
# Only set new credentials if the Web UI itself rejects that password.
EOF
    ;;
  *)
    warn "Web UI login probe returned ${login_state:-empty}"
    ;;
esac
echo

echo "[Cursor Agent]"
AGENT="$(cursor_agent_bin || true)"
if [ -n "$AGENT" ] && [ -x "$AGENT" ]; then
  ok "agent CLI present ($AGENT)"
else
  fail "Cursor agent CLI not found"
  record_manual "Install Cursor agent CLI" <<'EOF'
curl https://cursor.com/install -fsS | bash
export PATH="$HOME/.local/bin:$PATH"
EOF
fi

if [ -d "$CURSOR_WORKER_DIR" ]; then
  ok "Worker dir present ($CURSOR_WORKER_DIR)"
else
  fail "Worker dir missing ($CURSOR_WORKER_DIR)"
fi

if [ -f "/home/$STEAMOS_USER/.config/systemd/user/$CURSOR_WORKER_SERVICE" ]; then
  if systemctl --user is-enabled "$CURSOR_WORKER_SERVICE" >/dev/null 2>&1; then
    ok "$CURSOR_WORKER_SERVICE enabled"
  else
    fail "$CURSOR_WORKER_SERVICE not enabled"
    record_manual "Enable Cursor agent worker" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
./scripts/ensure-cursor-agent.sh
EOF
  fi
  if systemctl --user is-active "$CURSOR_WORKER_SERVICE" >/dev/null 2>&1; then
    ok "$CURSOR_WORKER_SERVICE active"
  else
    fail "$CURSOR_WORKER_SERVICE not active"
    record_manual "Start Cursor agent worker" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
agent login
systemctl --user enable --now $CURSOR_WORKER_SERVICE
EOF
  fi
else
  fail "Cursor agent worker unit not found"
  record_manual "Install Cursor agent worker user service" <<'EOF'
./scripts/ensure-cursor-agent.sh
EOF
fi

HEALTHZ="$(cursor_worker_healthz_url)"
if command -v curl >/dev/null 2>&1 && curl -sf --max-time 2 "$HEALTHZ" >/dev/null 2>&1; then
  ok "Worker healthz $HEALTHZ"
else
  warn "Worker healthz not answering ($HEALTHZ)"
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

echo "[Switch 2 controllers]"
S2_DIR="${SWITCH2_CONTROLLERS_DIR:-/home/$STEAMOS_USER/code/switch2-controllers-linux}"
S2_PY="$S2_DIR/.venv312/bin/python"
if [ -f "$S2_DIR/ngc/__main__.py" ]; then
  ok "checkout $S2_DIR"
else
  fail "Switch 2 controllers checkout missing ($S2_DIR)"
  record_manual "Install Switch 2 controller bridge" <<EOF
./scripts/ensure-switch2-controllers.sh
EOF
fi
if [ -x "$S2_PY" ] && "$S2_PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)'; then
  ok "venv CPython 3.12 (bleak 0.22.2)"
elif [ -x "$S2_PY" ]; then
  fail "venv is not CPython 3.12 ($("$S2_PY" -V 2>/dev/null || echo unknown))"
  record_manual "Recreate the 3.12 venv" <<EOF
./scripts/ensure-switch2-controllers.sh
EOF
else
  warn "Switch 2 venv not created yet"
fi
if systemctl --user is-enabled nso-gc.service >/dev/null 2>&1; then
  ok "nso-gc.service enabled"
else
  fail "nso-gc.service not enabled"
  record_manual "Enable nso-gc user service" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
./scripts/ensure-switch2-controllers.sh
EOF
fi
if systemctl --user is-active nso-gc.service >/dev/null 2>&1; then
  ok "nso-gc.service active"
else
  warn "nso-gc.service not active"
fi
if systemctl --user cat nso-gc-after-gamescope.service 2>/dev/null | grep -q 'After=gamescope-session.service'; then
  ok "after-gamescope hooked to gamescope-session.service"
else
  warn "nso-gc-after-gamescope.service not tied to gamescope-session.service"
fi
if python3 - <<'PY' 2>/dev/null
from pathlib import Path
import re, sys
home = Path.home()
paths = [
    home / ".steam/steam/config/config.vdf",
    home / ".local/share/Steam/config/config.vdf",
]
ok = False
for p in paths:
    if not p.is_file():
        continue
    text = p.read_text(errors="replace")
    m = re.search(r'"Bluetooth"\s*\{\s*"Enabled"\s*"([01])"', text)
    if m and m.group(1) == "0":
        ok = True
sys.exit(0 if ok else 1)
PY
then
  ok "Steam Bluetooth.Enabled is off (needed for Switch 2 L2CAP)"
else
  warn "Steam Bluetooth.Enabled is on or missing — Switch 2 connects may fail"
  record_manual "Disable Steam Bluetooth scan" <<EOF
python3 $S2_DIR/scripts/disable-steam-bluetooth.py
EOF
fi
if busctl get-property org.bluez /org/bluez/hci0 org.bluez.Adapter1 Powered 2>/dev/null | grep -q 'true'; then
  ok "BlueZ adapter powered"
else
  warn "BlueZ adapter powered=false (bridge ExecStartPre should turn it on)"
fi
if [ -f "/home/$STEAMOS_USER/.config/nso-gc/config.json" ]; then
  ok "paired controller config present"
else
  warn "no Switch 2 pads paired yet"
  record_manual "Pair each Switch 2 controller once (hold Sync)" <<EOF
cd $S2_DIR
.venv312/bin/python -m ngc pair
EOF
fi
if [ -f "$HOMEBREW_DIR/plugins/Switch2Controllers/main.py" ]; then
  ok "Decky Switch2Controllers plugin installed"
else
  warn "Decky Switch2Controllers plugin not installed"
  record_manual "Install Switch 2 Controllers Decky plugin" <<EOF
sudo bash $S2_DIR/scripts/install-decky.sh --install-only \$HOME/homebrew/plugins
EOF
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
