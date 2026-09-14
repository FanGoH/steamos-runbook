#!/usr/bin/env bash
# Official Syncthing v2 user daemon + Eden/Azahar save folders.
# SteamOS updates can drop linger and user-unit enablement while keeping /home/deck.
# Do not use pacman syncthing, Syncthing GTK, or decky-syncthing as the mesh daemon.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

SERVICE="${SYNCTHING_SERVICE:-syncthing.service}"
BIN="${SYNCTHING_BIN:-/home/${STEAMOS_USER}/.local/bin/syncthing}"
VERSION="${SYNCTHING_VERSION:-v2.1.5}"
UNIT_PATH="/home/${STEAMOS_USER}/.config/systemd/user/${SERVICE}"
GUI="${SYNCTHING_GUI:-127.0.0.1:8384}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) ST_ARCH=amd64 ;;
  aarch64) ST_ARCH=arm64 ;;
  *)
    echo "Unsupported architecture for Syncthing: $ARCH"
    exit 1
    ;;
esac

installed_version() {
  if [ -x "$BIN" ]; then
    "$BIN" --version 2>/dev/null | awk '{print $2; exit}'
  fi
}

want_version="${VERSION#v}"
have_version="$(installed_version || true)"
have_version="${have_version#v}"

if [ ! -x "$BIN" ] || [ "$have_version" != "$want_version" ]; then
  echo "Installing Syncthing ${VERSION} to $BIN (have: ${have_version:-none})"
  mkdir -p "$(dirname "$BIN")"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  tarball="syncthing-linux-${ST_ARCH}-${VERSION}.tar.gz"
  url="https://github.com/syncthing/syncthing/releases/download/${VERSION}/${tarball}"
  if ! curl -fsSL --max-time 120 -o "$tmp/$tarball" "$url"; then
    record_manual "Download official Syncthing ${VERSION}" <<EOF
curl -fsSL -o /tmp/${tarball} ${url}
tar -C /tmp -xzf /tmp/${tarball}
install -m 755 /tmp/syncthing-linux-${ST_ARCH}-${VERSION}/syncthing $BIN
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
./scripts/ensure-syncthing.sh
EOF
    exit 2
  fi
  tar -C "$tmp" -xzf "$tmp/$tarball"
  install -m 755 "$tmp/syncthing-linux-${ST_ARCH}-${VERSION}/syncthing" "$BIN"
  rm -rf "$tmp"
  trap - EXIT
  echo "Installed $($BIN --version | awk '{print $1,$2}')"
else
  echo "Syncthing already $VERSION at $BIN"
fi

mkdir -p "/home/${STEAMOS_USER}/.config/systemd/user" "/home/${STEAMOS_USER}/.local/state/syncthing"

desired_unit="$(cat <<EOS
[Unit]
Description=Syncthing - Open Source Continuous File Synchronization
Documentation=man:syncthing(1)
StartLimitIntervalSec=60
StartLimitBurst=4

[Service]
Environment="STLOGFORMATTIMESTAMP="
Environment="STLOGFORMATLEVELSTRING=false"
Environment="STLOGFORMATLEVELSYSLOG=true"
ExecStart=${BIN} serve --no-browser --no-restart
Restart=on-failure
RestartSec=1
SuccessExitStatus=3 4
RestartForceExitStatus=3 4
SystemCallArchitectures=native
MemoryDenyWriteExecute=true
NoNewPrivileges=true

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
    record_manual "Enable linger so Syncthing starts without a login" <<EOF
loginctl enable-linger $STEAMOS_USER
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user enable --now $SERVICE
EOF
    exit 2
  fi
else
  echo "Linger already enabled for $STEAMOS_USER."
fi

if [ "$unit_changed" -eq 1 ]; then
  systemctl --user restart "$SERVICE"
  echo "Restarted $SERVICE (unit changed)."
elif ! systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
  systemctl --user start "$SERVICE"
  echo "Started $SERVICE."
else
  echo "$SERVICE already active."
fi

# Keep Decky from launching a second Syncthing if the plugin settings exist.
DECKY_ST_SETTINGS="${DECKY_SYNCTHING_SETTINGS:-/home/${STEAMOS_USER}/homebrew/settings/decky-syncthing/decky-syncthing.json}"
if [ -f "$DECKY_ST_SETTINGS" ]; then
  python3 - "$DECKY_ST_SETTINGS" "$SERVICE" <<'PY'
import json, sys
path, service = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
changed = False
if data.get("autostart") not in ("no", False, None):
    data["autostart"] = "no"
    changed = True
if data.get("mode") == "systemd" and not data.get("service_name"):
    data["service_name"] = service
    changed = True
if changed:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
        f.write("\n")
    print(f"Pinned {path} to systemd {service}, autostart=no")
else:
    print(f"Decky Syncthing settings already leave autostart off ({path})")
PY
fi

eden_profile_dir() {
  local root="/home/${STEAMOS_USER}/.local/share/eden/nand/user/save/0000000000000000"
  local uuid="${SYNCTHING_EDEN_PROFILE_UUID:-}"
  local d best=""
  if [ -n "$uuid" ]; then
    printf '%s/%s\n' "$root" "$uuid"
    return
  fi
  [ -d "$root" ] || return 0
  for d in "$root"/*; do
    [ -d "$d" ] || continue
    case "$(basename "$d")" in
      00000000000000000000000000000000) continue ;;
    esac
    if [ -d "$d" ]; then
      best="$d"
      # Prefer a profile that already has title-ID folders.
      if find "$d" -mindepth 1 -maxdepth 1 -type d | grep -q .; then
        printf '%s\n' "$d"
        return
      fi
    fi
  done
  [ -n "$best" ] && printf '%s\n' "$best"
}

AZAHAR_PATH="${SYNCTHING_AZAHAR_PATH:-/home/${STEAMOS_USER}/.var/app/org.azahar_emu.Azahar/data/azahar-emu/sdmc/Nintendo 3DS/00000000000000000000000000000000/00000000000000000000000000000000}"
EDEN_PATH="${SYNCTHING_EDEN_PATH:-$(eden_profile_dir || true)}"

if [ -z "$EDEN_PATH" ]; then
  echo "Eden NAND profile not found yet; skipping eden-saves until Eden has run."
else
  mkdir -p "$EDEN_PATH"
  echo "Eden saves: $EDEN_PATH"
fi
mkdir -p "$AZAHAR_PATH"
echo "Azahar saves: $AZAHAR_PATH"

export SYNCTHING_GUI="$GUI"
export SYNCTHING_EDEN_PATH="${EDEN_PATH:-}"
export SYNCTHING_AZAHAR_PATH="$AZAHAR_PATH"
python3 "$ROOT/scripts/syncthing_folders.py"

# Game Mode / Tender Azahar cannot see another Flatpak's ~/.var/app tree.
# Copy the meshed standalone sdmc; never symlink into org.azahar_emu.Azahar.
sync_azahar_into_retrodeck() {
  local src="/home/${STEAMOS_USER}/.var/app/org.azahar_emu.Azahar/data/azahar-emu/sdmc"
  local dest="/home/${STEAMOS_USER}/retrodeck/saves/n3ds/azahar/sdmc"
  local fallback="/home/${STEAMOS_USER}/.var/app/net.retrodeck.retrodeck/data/azahar-emu/sdmc"
  local cfg="/home/${STEAMOS_USER}/.var/app/net.retrodeck.retrodeck/data/azahar-emu/config/azahar-emu/qt-config.ini"

  if [ ! -d "$src/Nintendo 3DS" ]; then
    echo "Standalone Azahar sdmc not present; skip RetroDECK copy."
    return 0
  fi

  if [ -L "$dest" ]; then
    echo "Replacing symlink $dest with a real copy (RetroDECK cannot use another Flatpak data dir)."
    rm -f "$dest"
  fi

  mkdir -p "$dest" "$fallback"
  if ! command -v rsync >/dev/null 2>&1; then
    record_manual "Install rsync to copy Azahar sdmc into RetroDECK Game Mode" <<EOF
# Need rsync, then:
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
./scripts/ensure-syncthing.sh
EOF
    return 0
  fi
  rsync -a "$src/" "$dest/"
  rsync -a "$src/" "$fallback/"
  echo "Copied standalone Azahar sdmc -> $dest and $fallback"

  if [ -f "$cfg" ]; then
    python3 - "$cfg" "$dest" <<'PY'
from pathlib import Path
import sys
cfg_path = Path(sys.argv[1])
sdmc = sys.argv[2]
if not sdmc.endswith("/"):
    sdmc += "/"
text = cfg_path.read_text(encoding="utf-8")
out = []
found = False
for line in text.splitlines(True):
    if line.strip().startswith("sdmc_directory="):
        out.append(f"sdmc_directory={sdmc}\n")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"sdmc_directory={sdmc}\n")
new = "".join(out)
if new != text:
    cfg_path.write_text(new, encoding="utf-8")
    print(f"Set RetroDECK sdmc_directory={sdmc}")
else:
    print(f"RetroDECK sdmc_directory already {sdmc}")
PY
  fi
}

sync_azahar_into_retrodeck

echo "Syncthing save mesh OK."
