#!/usr/bin/env bash
# sysstat (sar/sadc) + atop: common Linux resource history.
# SteamOS updates wipe / packages and /etc; re-run from post-update.
# Interval is 60s (stock sysstat/atop are 10 minutes). JSON later:
#   sadf -j -- -r -S -W
#   python3 scripts/host-metrics.py json
# Do not install prometheus/grafana/netdata (too big for ~5G root).
# Never sudo systemctl --user. Never prompt sudo on a TTY (post-update).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

TIMER_DROP="/etc/systemd/system/sysstat-collect.timer.d/playbook.conf"
ATOP_DEFAULT="/etc/default/atop"
OLD_WATCH="steamos-watch-resources.service"
OLD_WATCH_PATH="/home/${STEAMOS_USER}/.config/systemd/user/${OLD_WATCH}"

host_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
    return
  fi
  if [ -n "${SUDO_ASKPASS:-}" ] && [ -x "${SUDO_ASKPASS}" ]; then
    sudo -A "$@"
    return
  fi
  sudo -n "$@"
}

can_host_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    return 0
  fi
  if sudo -n true >/dev/null 2>&1; then
    return 0
  fi
  if [ -n "${SUDO_ASKPASS:-}" ] && [ -x "${SUDO_ASKPASS}" ]; then
    return 0
  fi
  return 1
}

manual_install() {
  record_manual "Install sysstat + atop (host metrics)" <<EOF
# SteamOS root is readonly and ~5G. sysstat+atop are ~2.5MiB.
# SteamOS updates wipe / packages — re-run this after an update.
sudo steamos-readonly disable
sudo pacman -Sy --noconfirm --needed sysstat atop
sudo mkdir -p /etc/systemd/system/sysstat-collect.timer.d
sudo tee /etc/systemd/system/sysstat-collect.timer.d/playbook.conf >/dev/null <<'UNIT'
[Timer]
OnCalendar=
OnCalendar=*:*:00
AccuracySec=10s
Persistent=true
UNIT
sudo tee /etc/default/atop >/dev/null <<'CONF'
LOGOPTS=""
LOGINTERVAL=60
LOGGENERATIONS=14
LOGPATH=/var/log/atop
CONF
sudo sed -i 's/^HISTORY=.*/HISTORY=14/' /etc/conf.d/sysstat || true
sudo systemctl daemon-reload
sudo systemctl enable --now sysstat.service sysstat-collect.timer atop.service atop-rotate.timer
sudo steamos-readonly enable
# Dump JSON later (does not need root if umask 0022):
sadf -j -- -r -S -W
python3 $ROOT/scripts/host-metrics.py json
EOF
}

remove_custom_watcher() {
  if systemctl --user is-enabled "$OLD_WATCH" >/dev/null 2>&1 \
    || systemctl --user is-active "$OLD_WATCH" >/dev/null 2>&1 \
    || [ -f "$OLD_WATCH_PATH" ]; then
    systemctl --user disable --now "$OLD_WATCH" >/dev/null 2>&1 || true
    rm -f "$OLD_WATCH_PATH"
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    echo "Removed leftover $OLD_WATCH"
  fi
}

write_config() {
  host_sudo mkdir -p /etc/systemd/system/sysstat-collect.timer.d || return 1
  local tmp
  tmp="$(mktemp)"
  cat >"$tmp" <<'UNIT'
[Timer]
OnCalendar=
OnCalendar=*:*:00
AccuracySec=10s
Persistent=true
UNIT
  host_sudo install -m 644 "$tmp" "$TIMER_DROP" || { rm -f "$tmp"; return 1; }
  cat >"$tmp" <<'CONF'
LOGOPTS=""
LOGINTERVAL=60
LOGGENERATIONS=14
LOGPATH=/var/log/atop
CONF
  host_sudo install -m 644 "$tmp" "$ATOP_DEFAULT" || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  if [ -f /etc/conf.d/sysstat ]; then
    host_sudo sed -i 's/^HISTORY=.*/HISTORY=14/' /etc/conf.d/sysstat || true
  fi
  return 0
}

enable_units() {
  host_sudo systemctl daemon-reload || return 1
  host_sudo systemctl enable --now sysstat.service sysstat-collect.timer \
    atop.service atop-rotate.timer
}

pkgs_ok() {
  pacman -Q sysstat >/dev/null 2>&1 && pacman -Q atop >/dev/null 2>&1
}

units_ok() {
  systemctl is-enabled sysstat-collect.timer >/dev/null 2>&1 \
    && systemctl is-enabled atop.service >/dev/null 2>&1 \
    && systemctl is-active atop.service >/dev/null 2>&1
}

disable_readonly() {
  if ! command -v steamos-readonly >/dev/null 2>&1; then
    echo "none"
    return 0
  fi
  if steamos-readonly status 2>/dev/null | grep -qi 'disabled\|disable'; then
    echo "disabled"
    return 0
  fi
  host_sudo steamos-readonly disable || return 1
  echo "enabled"
}

restore_readonly() {
  local previous="${1:-none}"
  if [ "$previous" = "enabled" ] && command -v steamos-readonly >/dev/null 2>&1; then
    host_sudo steamos-readonly enable || true
  fi
}

remove_custom_watcher

if pkgs_ok && [ -f "$TIMER_DROP" ] && [ -f "$ATOP_DEFAULT" ] && units_ok; then
  echo "sysstat + atop already collecting (60s). JSON: python3 $ROOT/scripts/host-metrics.py json"
  exit 0
fi

if ! can_host_sudo; then
  echo "sysstat/atop need sudo (SteamOS readonly root; QAM Playbook password or SSH sudo)."
  manual_install
  exit 2
fi

echo "Installing/enabling sysstat + atop (60s host metrics)..."
readonly_was="none"
set +e
readonly_was="$(disable_readonly)"
disable_rc=$?
if [ "$disable_rc" -eq 0 ]; then
  host_sudo pacman -Sy --noconfirm --needed sysstat atop
  pkg_rc=$?
else
  pkg_rc=1
fi
set -e

cfg_ok=0
if pkgs_ok && write_config && enable_units; then
  cfg_ok=1
fi
restore_readonly "$readonly_was"

if pkgs_ok && units_ok; then
  echo "sysstat + atop enabled (60s). JSON: python3 $ROOT/scripts/host-metrics.py json"
  exit 0
fi

echo "sysstat/atop install or enable failed (pacman exit ${pkg_rc:-?} cfg=${cfg_ok})."
manual_install
exit 2
