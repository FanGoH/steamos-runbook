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
  local pid comm leftover i ppid pcomm seen
  local pids=()
  while read -r pid comm; do
    pid="${pid#"${pid%%[![:space:]]*}"}"
    [ -n "$pid" ] || continue
    if printf '%s\n' "$comm" | grep -Eq "$matcher"; then
      pids+=("$pid")
      echo "Stopping pid $pid ($comm)"
      ppid="$pid"
      while [ -n "$ppid" ] && [ "$ppid" -gt 1 ]; do
        ppid="$(ps -o ppid= -p "$ppid" 2>/dev/null | tr -d '[:space:]')"
        [ -n "$ppid" ] || break
        pcomm="$(ps -o comm= -p "$ppid" 2>/dev/null | awk '{print $1}')"
        [ "$pcomm" = bwrap ] || break
        seen=0
        for existing in "${pids[@]}"; do
          [ "$existing" = "$ppid" ] && seen=1 && break
        done
        if [ "$seen" -eq 0 ]; then
          pids+=("$ppid")
          echo "Stopping pid $ppid (bwrap parent)"
        fi
      done
    fi
  done < <(ps -eo pid=,comm=)
  if [ "${#pids[@]}" -eq 0 ]; then
    echo "No processes matched $matcher"
    return 0
  fi
  kill "${pids[@]}" 2>/dev/null || true
  # Event-ish: poll /proc, SIGKILL after ~0.3s. A 3s polite wait is what
  # made Steam Exiting… feel stuck after --quit.
  i=0
  while [ "$i" -lt 3 ]; do
    leftover=0
    for existing in "${pids[@]}"; do
      if kill -0 "$existing" 2>/dev/null; then
        leftover=1
      fi
    done
    [ "$leftover" -eq 0 ] && return 0
    sleep 0.1
    i=$((i + 1))
  done
  echo "Force-killing leftover $matcher"
  kill -9 "${pids[@]}" 2>/dev/null || true
}

wait_for_sunshine_pad() {
  local match="${1:-Sunshine}"
  local timeout="${2:-45}"
  echo "Waiting up to ${timeout}s for a Sunshine pad (${match})…"
  python3 "$ROOT/scripts/bind-gamepad.py" wait-appear --match "$match" --timeout "$timeout"
}

wait_while_comm() {
  local matcher="$1"
  local extra_pid="${2:-}"
  trap 'echo "Moonlight stopped the app; closing matching processes."; stop_matching_comm "'"$matcher"'"; [ -n "'"$extra_pid"'" ] && kill "'"$extra_pid"'" 2>/dev/null || true; trap - INT TERM; exit 0' INT TERM
  while ps -eo comm= | grep -Eq "$matcher"; do
    sleep 2
  done
  trap - INT TERM
  [ -n "$extra_pid" ] && kill "$extra_pid" 2>/dev/null || true
}
