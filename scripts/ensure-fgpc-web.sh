#!/usr/bin/env bash
# Phone WebGUI for the fgpc catalog, hosted on this Steam Machine.
# Listens on localhost + tailnet IPv4. Extra MagicDNS name is Headscale-only.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

SERVICE="${FGPC_WEB_SERVICE:-fgpc-web.service}"
UNIT_PATH="/home/${STEAMOS_USER}/.config/systemd/user/$SERVICE"
PORT="${FGPC_WEB_PORT:-8484}"
HOSTNAME_LABEL="${FGPC_WEB_HOSTNAME:-fgpc}"
RUNNER="$ROOT/scripts/fgpc-web.py"
LOG="$ROOT/logs/fgpc-web.log"

if [ ! -f "$ROOT/fgpc/src/fgpc/web.py" ] || [ ! -f "$ROOT/fgpc/web/index.html" ]; then
  echo "Missing fgpc web files under $ROOT/fgpc."
  exit 1
fi

if ! python3 "$ROOT/scripts/fgpc-api.py" self-test >/dev/null; then
  echo "fgpc-api self-test failed."
  python3 "$ROOT/scripts/fgpc-api.py" self-test || true
  exit 1
fi

if ! python3 "$RUNNER" --self-test >/dev/null; then
  echo "fgpc-web self-test failed."
  python3 "$RUNNER" --self-test || true
  exit 1
fi

mkdir -p "/home/${STEAMOS_USER}/.config/systemd/user" "$ROOT/logs"

UID_NUM="$(id -u "$STEAMOS_USER")"
desired_unit="$(cat <<EOS
[Unit]
Description=FGPC phone WebGUI (tailnet)
Documentation=file://$ROOT/fgpc/web/index.html
After=default.target
StartLimitIntervalSec=120
StartLimitBurst=8

[Service]
Type=simple
ExecStart=/usr/bin/python3 $RUNNER
Restart=always
RestartSec=5
Environment=HOME=/home/$STEAMOS_USER
Environment=USER=$STEAMOS_USER
Environment=STEAMOS_PLAYBOOK_DIR=$ROOT
Environment=XDG_RUNTIME_DIR=/run/user/$UID_NUM
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$UID_NUM/bus
Environment=PATH=/home/$STEAMOS_USER/.local/bin:/usr/bin:/bin
Environment=FGPC_WEB_PORT=$PORT
Environment=FGPC_WEB_HOSTNAME=$HOSTNAME_LABEL
Environment=TAILSCALE_BIN=${TAILSCALE_BIN:-/opt/tailscale/tailscale}
StandardOutput=append:$LOG
StandardError=append:$LOG

[Install]
WantedBy=default.target
EOS
)"

unit_changed=0
if [ ! -f "$UNIT_PATH" ] || [ "$(cat "$UNIT_PATH")" != "$desired_unit" ]; then
  printf '%s\n' "$desired_unit" >"$UNIT_PATH"
  systemctl --user daemon-reload
  unit_changed=1
  echo "Updated $SERVICE unit."
fi

if ! systemctl --user is-enabled "$SERVICE" >/dev/null 2>&1; then
  systemctl --user enable "$SERVICE"
  echo "Enabled $SERVICE."
else
  echo "$SERVICE already enabled."
fi

if [ "$(loginctl show-user "$STEAMOS_USER" -p Linger --value 2>/dev/null || true)" != "yes" ]; then
  if loginctl enable-linger "$STEAMOS_USER" 2>/dev/null; then
    echo "Enabled linger for $STEAMOS_USER."
  else
    record_manual "Enable linger so fgpc-web survives logout" <<EOF
loginctl enable-linger $STEAMOS_USER
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user restart $SERVICE
EOF
  fi
fi

if [ "$unit_changed" -eq 1 ] || ! systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
  systemctl --user restart "$SERVICE"
  echo "Restarted $SERVICE."
else
  echo "$SERVICE already active."
fi

ok=0
for _ in 1 2 3 4 5 6 7 8; do
  if curl -sf --max-time 2 "http://127.0.0.1:${PORT}/healthz" >/dev/null; then
    ok=1
    break
  fi
  sleep 1
done
if [ "$ok" -ne 1 ]; then
  echo "fgpc-web did not answer http://127.0.0.1:${PORT}/healthz"
  echo "See $LOG"
  exit 1
fi

TS="${TAILSCALE_BIN:-/opt/tailscale/tailscale}"
tailnet_ip=""
suffix=""
if [ -x "$TS" ]; then
  tailnet_ip="$("$TS" ip -4 2>/dev/null | head -1 || true)"
  suffix="$(
    "$TS" dns status 2>/dev/null \
      | sed -n 's/.*suffix = \([^ )]*\).*/\1/p' \
      | head -1 || true
  )"
fi
suffix="${TAILSCALE_DNS_SUFFIX:-$suffix}"
pretty=""
if [ -n "$suffix" ]; then
  pretty="${HOSTNAME_LABEL}.${suffix}"
fi

echo "FGPC WebGUI is up on this Steam Machine (not lab)."
echo "  local   http://127.0.0.1:${PORT}/"
if [ -n "$tailnet_ip" ]; then
  echo "  tailnet http://${tailnet_ip}:${PORT}/"
fi
node="${TAILSCALE_HOSTNAME:-steammachine}"
if [ -n "$suffix" ]; then
  echo "  node    http://${node}.${suffix}:${PORT}/"
fi
if [ -n "$pretty" ]; then
  echo "  extra   http://${pretty}:${PORT}/  (needs Headscale extra A record)"
fi

if [ -n "$pretty" ] && [ -n "$tailnet_ip" ]; then
  if ! getent hosts "$pretty" >/dev/null 2>&1; then
    record_manual "Add Headscale extra DNS for ${pretty}" <<EOF
# On the Headscale VPS, append to /etc/headscale/extra_records.json
# (dns.extra_records_path — no Headscale restart). HTTP only, not https.
#   {"name": "${pretty}", "type": "A", "value": "${tailnet_ip}"}
# Do not change TAILSCALE_HOSTNAME ($node). Until that record exists, use:
#   http://${tailnet_ip}:${PORT}/
#   http://${node}.${suffix}:${PORT}/
EOF
  else
    echo "MagicDNS already resolves $pretty."
  fi
fi

echo "Phone UI: tabs Stream / Screen / Pad / Hide / More. Buttons only."
echo "SSH-only (not on the phone): bootstrap, post-update, mode switch, hide --force."
exit 0
