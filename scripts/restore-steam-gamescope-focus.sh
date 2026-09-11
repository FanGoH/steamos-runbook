#!/usr/bin/env bash
# After Cemu / Azahar / Eden is gone, gamescope can keep FOCUSED_APP=<shortcut>
# on :1 with a dead xid (Wind Waker leftover after a 3DS session). Steam Exit
# then sits on "Exiting…". Put both session Xwaylands back on Steam (769).
#
# Do not call steam-guide-from-select.py --hide from here: with no Cemu TV it
# writes the leftover shortcut appid back onto :0.
set -uo pipefail

STEAM_CLIENT_ID=769
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

for d in :0 :1; do
  # Leave :1 alone if Cemu/Eden is still the in-game Xwayland (OoT + WWHD).
  if [ "$d" = ":1" ] && command -v xdotool >/dev/null 2>&1; then
    if DISPLAY=:1 xdotool search --name 'Cemu' >/dev/null 2>&1 \
      || DISPLAY=:1 xdotool search --class eden >/dev/null 2>&1; then
      continue
    fi
  fi
  DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$STEAM_CLIENT_ID" 2>/dev/null || true
  DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$STEAM_CLIENT_ID" 2>/dev/null || true
done
# Stale game xid on the in-game Xwayland; Steam BPM lives on :0.
if ! DISPLAY=:1 xdotool search --name 'Cemu' >/dev/null 2>&1; then
  DISPLAY=:1 xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW 0 2>/dev/null || true
fi
exit 0
