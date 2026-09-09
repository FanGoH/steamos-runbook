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
  azahar)
    stop_matching_comm '^azahar'
    stop_azahar_picker
    exit 0
    ;;
  cemu)
    stop_matching_comm '^[Cc]emu'
    exit 0
    ;;
  *)
    echo "usage: $0 azahar|cemu" >&2
    exit 2
    ;;
esac
