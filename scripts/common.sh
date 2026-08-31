#!/usr/bin/env bash
# Shared helpers for steamos-playbook scripts.

playbook_root() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  printf '%s\n' "$here"
}

load_env() {
  local root="${1:-$(playbook_root)}"

  if [ -f "$root/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$root/.env"
    set +a
  fi

  # Sensible non-personal defaults; Headscale URL must come from .env
  STEAMOS_NIC_INTERFACE="${STEAMOS_NIC_INTERFACE:-enp8s0}"
  STEAMOS_USER="${STEAMOS_USER:-deck}"
  STEAMOS_PLAYBOOK_DIR="${STEAMOS_PLAYBOOK_DIR:-/home/deck/steamos-playbook}"
  STEAMOS_DISTROBOX_NAME="${STEAMOS_DISTROBOX_NAME:-steamos-tools}"
  STEAMOS_DISTROBOX_IMAGE="${STEAMOS_DISTROBOX_IMAGE:-registry.fedoraproject.org/fedora:42}"
  TAILSCALE_LOGIN_SERVER="${TAILSCALE_LOGIN_SERVER:-}"
  TAILSCALE_HOSTNAME="${TAILSCALE_HOSTNAME:-steamdeck}"
  TAILSCALE_OPERATOR="${TAILSCALE_OPERATOR:-deck}"
  TAILSCALE_BIN="${TAILSCALE_BIN:-/opt/tailscale/tailscale}"
  OPENRGB_FLATPAK_ID="${OPENRGB_FLATPAK_ID:-org.openrgb.OpenRGB}"
  OPENRGB_UDEV_RULES="${OPENRGB_UDEV_RULES:-/etc/udev/rules.d/60-openrgb.rules}"
  OPENRGB_PROFILE="${OPENRGB_PROFILE:-ramoff}"
  OPENRGB_SDK_HOST="${OPENRGB_SDK_HOST:-127.0.0.1}"
  OPENRGB_SDK_PORT="${OPENRGB_SDK_PORT:-6742}"
  SUNSHINE_USER_SERVICE="${SUNSHINE_USER_SERVICE:-app-dev.lizardbyte.app.Sunshine.service}"
  SUNSHINE_FLATPAK_ID="${SUNSHINE_FLATPAK_ID:-dev.lizardbyte.app.Sunshine}"
  SUNSHINE_LOG="${SUNSHINE_LOG:-/home/${STEAMOS_USER}/.var/app/dev.lizardbyte.app.Sunshine/config/sunshine/sunshine.log}"
  SUNSHINE_STATE="${SUNSHINE_STATE:-/home/${STEAMOS_USER}/.var/app/dev.lizardbyte.app.Sunshine/config/sunshine/sunshine_state.json}"
  SUNSHINE_GAMESTREAM_URL="${SUNSHINE_GAMESTREAM_URL:-http://127.0.0.1:47989}"
  SUNSHINE_UI_URL="${SUNSHINE_UI_URL:-https://127.0.0.1:47990}"
  DECKY_SUNSHINE_SETTINGS="${DECKY_SUNSHINE_SETTINGS:-/home/${STEAMOS_USER}/homebrew/settings/decky-sunshine/decky-sunshine.json}"
  AUR_HELPER="${AUR_HELPER:-paru}"
  GEARLEVER_FLATPAK_ID="${GEARLEVER_FLATPAK_ID:-it.mijorus.gearlever}"
  FLATPAK_REMOTE="${FLATPAK_REMOTE:-flathub}"
}

setup_user_dbus() {
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
}

# GameStream /serverinfo XML (empty if the host is down).
sunshine_serverinfo() {
  curl -sS --max-time 3 "${SUNSHINE_GAMESTREAM_URL:-http://127.0.0.1:47989}/serverinfo" 2>/dev/null || true
}

sunshine_serverinfo_state() {
  local xml
  xml="$(sunshine_serverinfo)"
  if [ -z "$xml" ]; then
    printf '%s\n' "DOWN"
    return 1
  fi
  if printf '%s' "$xml" | grep -q 'SUNSHINE_SERVER_BUSY'; then
    printf '%s\n' "BUSY"
    return 0
  fi
  if printf '%s' "$xml" | grep -q 'SUNSHINE_SERVER_FREE'; then
    printf '%s\n' "FREE"
    return 0
  fi
  printf '%s\n' "UNKNOWN"
  return 1
}

sunshine_currentgame() {
  sunshine_serverinfo | sed -n 's/.*<currentgame>\([^<]*\)<\/currentgame>.*/\1/p'
}

# UDP video/audio/control ports exist only during a live Moonlight stream.
sunshine_stream_udp_up() {
  awk '
    $2 ~ /:(BB7E|BB7F|BB80|BB82)$/ { found=1 }
    END { exit found ? 0 : 1 }
  ' /proc/net/udp /proc/net/udp6 2>/dev/null
}

# BUSY with no stream sockets: leftover Desktop app after a failed/teardown session.
sunshine_stale_busy() {
  [ "$(sunshine_serverinfo_state 2>/dev/null || true)" = "BUSY" ] && ! sunshine_stream_udp_up
}

sunshine_systemd_enabled() {
  systemctl --user is-enabled "${SUNSHINE_USER_SERVICE}" >/dev/null 2>&1
}

sunshine_systemd_active() {
  systemctl --user is-active "${SUNSHINE_USER_SERVICE}" >/dev/null 2>&1
}

# Probe the Web UI the same way Decky does (GET /api/apps).
# Prints one token: OK | DOWN | NO_CREDS | UNAUTH_HASH_OK | UNAUTH_MISMATCH | UNAUTH | UNEXPECTED
# Never prints the password or Authorization header.
sunshine_ui_login_state() {
  local settings="${DECKY_SUNSHINE_SETTINGS:-}"
  local state="${SUNSHINE_STATE:-}"
  local ui="${SUNSHINE_UI_URL:-https://127.0.0.1:47990}"
  python3 - "$ui" "${settings:-}" "${state:-}" <<'PY'
import base64, hashlib, json, ssl, sys, urllib.error, urllib.request

ui, settings, state_path = sys.argv[1], sys.argv[2], sys.argv[3]
ctx = ssl._create_unverified_context()

def get(path, auth=None):
    req = urllib.request.Request(ui.rstrip("/") + path)
    req.add_header("User-Agent", "steamos-playbook")
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

anon = get("/api/apps")
if anon is None:
    print("DOWN")
    sys.exit(0)

hdr = ""
user = ""
pwd = ""
if settings:
    try:
        raw = json.loads(open(settings, encoding="utf-8").read())
        hdr = raw.get("lastAuthHeader") or ""
    except (OSError, json.JSONDecodeError):
        hdr = ""
if hdr.startswith("Basic "):
    try:
        decoded = base64.b64decode(hdr[6:]).decode("utf-8")
        user, pwd = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        hdr, user, pwd = "", "", ""

if not hdr:
    print("NO_CREDS")
    sys.exit(0)

authed = get("/api/apps", hdr)
if 200 <= (authed or 0) < 400:
    print("OK")
    sys.exit(0)
if authed != 401:
    print("UNEXPECTED")
    sys.exit(0)

# 401 with stored creds: hash-check vs sunshine_state.json (sha256(password+salt)).
hash_ok = False
try:
    st = json.loads(open(state_path, encoding="utf-8").read()) if state_path else {}
    salt = st.get("salt") or ""
    stored = (st.get("password") or "").lower()
    uname = st.get("username") or ""
    digest = hashlib.sha256((pwd + salt).encode()).hexdigest().lower()
    hash_ok = bool(stored) and digest == stored and user.lower() == uname.lower()
except (OSError, json.JSONDecodeError, TypeError):
    hash_ok = False

print("UNAUTH_HASH_OK" if hash_ok else "UNAUTH_MISMATCH" if state_path else "UNAUTH")
PY
}

# POST a Sunshine Web UI path using Decky's stored Basic auth. Never prints the header.
# Usage: sunshine_ui_post /api/apps/close
# Exit 0 on HTTP 2xx or a dropped connection (some endpoints close the socket).
sunshine_ui_post() {
  local path="$1"
  local settings="${DECKY_SUNSHINE_SETTINGS:-}"
  local ui="${SUNSHINE_UI_URL:-https://127.0.0.1:47990}"
  [ -n "$path" ] && [ -n "$settings" ] && [ -f "$settings" ] || return 1
  python3 - "$settings" "$ui" "$path" <<'PY'
import json, ssl, sys, urllib.error, urllib.request

settings, ui, path = sys.argv[1], sys.argv[2], sys.argv[3]
if not path.startswith("/"):
    path = "/" + path
try:
    hdr = json.loads(open(settings, encoding="utf-8").read()).get("lastAuthHeader") or ""
except OSError:
    sys.exit(1)
if not hdr.startswith("Basic "):
    sys.exit(1)
ctx = ssl._create_unverified_context()
req = urllib.request.Request(ui.rstrip("/") + path, method="POST", data=b"")
req.add_header("Authorization", hdr)
req.add_header("User-Agent", "steamos-playbook")
req.add_header("Content-Type", "application/json")
try:
    with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
        sys.exit(0 if 200 <= resp.status < 400 else 1)
except urllib.error.HTTPError as e:
    sys.exit(0 if e.code in (200, 204) else 1)
except (urllib.error.URLError, TimeoutError, OSError):
    sys.exit(1)
PY
}

# Close the leftover Desktop/game (clears SUNSHINE_SERVER_BUSY). Do not use /api/restart
# on Decky's setuid instance — it kills listeners and leaves a defunct bwrap.
sunshine_close_app_via_api() {
  sunshine_ui_post "/api/apps/close"
}

# Restart the instance that owns :47990 using Decky's stored Basic auth. Never prints the header.
sunshine_restart_via_api() {
  local settings="${DECKY_SUNSHINE_SETTINGS:-}"
  local ui="${SUNSHINE_UI_URL:-https://127.0.0.1:47990}"
  [ -n "$settings" ] && [ -f "$settings" ] || return 1
  python3 - "$settings" "$ui" <<'PY'
import json, ssl, sys, urllib.error, urllib.request

settings, ui = sys.argv[1], sys.argv[2]
try:
    hdr = json.loads(open(settings, encoding="utf-8").read()).get("lastAuthHeader") or ""
except OSError:
    sys.exit(1)
if not hdr.startswith("Basic "):
    sys.exit(1)
ctx = ssl._create_unverified_context()
req = urllib.request.Request(ui.rstrip("/") + "/api/restart", method="POST")
req.add_header("Authorization", hdr)
req.add_header("User-Agent", "steamos-playbook")
try:
    with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
        sys.exit(0 if 200 <= resp.status < 400 else 1)
except urllib.error.HTTPError as e:
    # Sunshine may close the socket during platf::restart(); treat that as success.
    sys.exit(0 if e.code in (200, 204, 502, 503) else 1)
except (urllib.error.URLError, TimeoutError, OSError):
    sys.exit(0)
PY
}

# Record a copy-paste manual fix. Body is read from stdin.
# When MANUAL_ACTIONS_FILE is set (by post-update/bootstrap), also append there
# so the orchestrator can print a single summary at the end.
record_manual() {
  local title="$1"
  local body
  body="$(cat)"

  echo
  echo ">>> MANUAL ACTION NEEDED: $title"
  printf '%s\n' "$body"
  echo "<<<"
  echo

  if [ -n "${MANUAL_ACTIONS_FILE:-}" ]; then
    {
      echo "## $title"
      printf '%s\n' "$body"
      echo
    } >>"$MANUAL_ACTIONS_FILE"
  fi
}

print_manual_summary() {
  local file="${1:-${MANUAL_ACTIONS_FILE:-}}"
  if [ "${SKIP_MANUAL_SUMMARY:-0}" = "1" ]; then
    return 0
  fi
  if [ -z "$file" ] || [ ! -s "$file" ]; then
    echo "No manual actions needed."
    return 0
  fi

  echo "== Manual actions needed =="
  echo "These were detected but not auto-applied (safe / intentional)."
  echo
  cat "$file"
}

tailscale_up_command() {
  if [ -z "${TAILSCALE_LOGIN_SERVER:-}" ]; then
    cat <<'EOF'
# Set TAILSCALE_LOGIN_SERVER in .env first (see .env.example), then:
./deck-tailscale up \
  --login-server="$TAILSCALE_LOGIN_SERVER" \
  --operator="$TAILSCALE_OPERATOR" \
  --hostname="$TAILSCALE_HOSTNAME" \
  --accept-routes
EOF
    return 0
  fi
  cat <<EOF
./deck-tailscale up \\
  --login-server=${TAILSCALE_LOGIN_SERVER} \\
  --operator=${TAILSCALE_OPERATOR} \\
  --hostname=${TAILSCALE_HOSTNAME} \\
  --accept-routes
EOF
}

pacman_keyring_commands() {
  cat <<'EOF'
sudo steamos-readonly disable
sudo pacman-key --init
sudo pacman-key --populate archlinux
sudo pacman-key --populate holo
sudo steamos-readonly enable
EOF
}

# Return 0 if pacman trustdb looks usable; 1 if re-init is needed.
pacman_keyring_ok() {
  if ! command -v pacman >/dev/null 2>&1; then
    return 1
  fi
  if [ ! -d /etc/pacman.d/gnupg ]; then
    return 1
  fi
  if [ ! -e /etc/pacman.d/gnupg/pubring.gpg ] && [ ! -e /etc/pacman.d/gnupg/pubring.kbx ]; then
    return 1
  fi
  if ! pacman-key --list-keys >/dev/null 2>&1; then
    return 1
  fi
  local key_count
  key_count="$(pacman-key --list-keys 2>/dev/null | grep -c '^pub' || true)"
  if [ "${key_count:-0}" -lt 5 ]; then
    return 1
  fi
  return 0
}

# Disable SteamOS rootfs overlay if needed; prints previous state: enabled|disabled|none
steamos_readonly_disable_if_needed() {
  if ! command -v steamos-readonly >/dev/null 2>&1; then
    echo "none"
    return 0
  fi
  if steamos-readonly status 2>/dev/null | grep -qi 'disabled\|disable'; then
    echo "disabled"
    return 0
  fi
  sudo steamos-readonly disable
  echo "enabled"
}

steamos_readonly_restore() {
  local previous="${1:-none}"
  if [ "$previous" = "enabled" ] && command -v steamos-readonly >/dev/null 2>&1; then
    sudo steamos-readonly enable
  fi
}

# Current Wake-on mode for a NIC (exact "Wake-on:" line, not "Supports Wake-on:").
nic_wake_on() {
  local nic="$1"
  ethtool "$nic" 2>/dev/null | awk -F': ' '/^[[:space:]]*Wake-on:/{print $2; exit}'
}
