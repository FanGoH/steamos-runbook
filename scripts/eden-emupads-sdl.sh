# Source from Eden launch wrappers. Pins the 15-button EmuPads SDL map
# and drops Steam's Switch 2 GAMECONTROLLERCONFIG / USE_BUTTON_LABELS.
# Steam injects a Switch 2 Procon line that does not match P1's GUID and
# leaves 1209:e301 unmapped (FE3H D-pad / stick feel wrong).
#
# shellcheck shell=bash
if [ -z "${_EDEN_EMUPADS_SDL_PLAYBOOK:-}" ]; then
  _EDEN_EMUPADS_SDL_PLAYBOOK="${STEAMOS_PLAYBOOK:-${PLAYBOOK:-${HOME}/steamos-playbook}}"
fi
unset SDL_GAMECONTROLLER_USE_BUTTON_LABELS
export SDL_JOYSTICK_HIDAPI_SWITCH2=0
_bind_py="${_EDEN_EMUPADS_SDL_PLAYBOOK}/scripts/bind-gamepad.py"
_cfg=""
if [ -f "$_bind_py" ]; then
  _cfg="$(python3 "$_bind_py" sdl-mapping --match EmuPads 2>/dev/null || true)"
fi
if [ -n "$_cfg" ]; then
  export SDL_GAMECONTROLLERCONFIG="$_cfg"
  _map_file="${XDG_RUNTIME_DIR:-/tmp}/eden-emupads-gamecontrollerdb.txt"
  printf '%s\n' "$_cfg" >"$_map_file" || true
  if [ -s "$_map_file" ]; then
    export SDL_GAMECONTROLLERCONFIG_FILE="$_map_file"
  fi
fi
unset _bind_py _cfg _map_file _EDEN_EMUPADS_SDL_PLAYBOOK
