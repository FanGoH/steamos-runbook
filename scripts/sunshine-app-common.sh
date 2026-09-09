#!/usr/bin/env bash
# Shared helpers for sunshine-ds Moonlight apps. Sourced, not executed.
# sunshine-ds runs in Distrobox; KWin/kscreen live on the host.

reexec_on_host() {
  if [ -f /run/.containerenv ] && command -v distrobox-host-exec >/dev/null; then
    exec distrobox-host-exec /bin/bash "$1"
  fi
}

wait_for_sunshine_pad() {
  local match="${1:-Sunshine}"
  local timeout="${2:-45}"
  echo "Waiting up to ${timeout}s for a Sunshine pad (${match})…"
  python3 "$ROOT/scripts/bind-gamepad.py" wait-appear --match "$match" --timeout "$timeout"
}

wait_while_comm() {
  local matcher="$1"
  while ps -eo comm= | grep -Eq "$matcher"; do
    sleep 2
  done
}
