#!/usr/bin/env bash
# Stop a dual-screen emulator left running after Moonlight quits the app.
# sunshine-ds may invoke this from Distrobox; re-exec on the host.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/sunshine-app-common.sh
source "$ROOT/scripts/sunshine-app-common.sh"
reexec_on_host "$ROOT/scripts/sunshine-app-stop.sh" "$@"

target="${1:-}"
case "$target" in
  azahar) matcher='^azahar' ;;
  cemu) matcher='^[Cc]emu' ;;
  *)
    echo "usage: $0 azahar|cemu" >&2
    exit 2
    ;;
esac

stop_matching_comm "$matcher"
# Dead emulator + leftover :1 FOCUSED_APP=<shortcut> is Steam stuck on Exiting.
bash "$ROOT/scripts/restore-steam-gamescope-focus.sh" 2>/dev/null || true
exit 0
