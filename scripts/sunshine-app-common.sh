#!/usr/bin/env bash
# Shared helpers for sunshine-ds Moonlight apps. Sourced, not executed.
# sunshine-ds runs in Distrobox; KWin/kscreen live on the host.

reexec_on_host() {
  local script="$1"
  shift || true
  if [ -f /run/.containerenv ] && command -v distrobox-host-exec >/dev/null; then
    exec distrobox-host-exec /bin/bash "$script" "$@"
  fi
}

stop_matching_comm() {
  local matcher="$1"
  local pid comm
  while read -r pid comm; do
    [ -n "$pid" ] || continue
    if printf '%s\n' "$comm" | grep -Eq "$matcher"; then
      echo "Stopping pid $pid ($comm)"
      kill "$pid" 2>/dev/null || true
    fi
  done < <(ps -eo pid=,comm=)
}

wait_for_sunshine_pad() {
  local match="${1:-Sunshine}"
  local timeout="${2:-45}"
  echo "Waiting up to ${timeout}s for a Sunshine pad (${match})…"
  python3 "$ROOT/scripts/bind-gamepad.py" wait-appear --match "$match" --timeout "$timeout"
}

wait_while_comm() {
  local matcher="$1"
  trap 'echo "Moonlight stopped the app; closing matching processes."; stop_matching_comm "$matcher"; trap - INT TERM; exit 0' INT TERM
  while ps -eo comm= | grep -Eq "$matcher"; do
    sleep 2
  done
  trap - INT TERM
}
