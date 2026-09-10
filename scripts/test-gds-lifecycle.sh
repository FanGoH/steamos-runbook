#!/usr/bin/env bash
# Host-side Game Mode GDS (:48200) lifecycle gate. No Thor tap.
# Exit 0 when FREE, no leftover session workers, uniqueid matches GDS.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
KMS_URL="${SUNSHINE_DS_KMS_URL:-http://127.0.0.1:48200}"
GDS_ID='1075C8EF-343E-7E20-281E-89FDA05BC0C1'

# python - "$info" <<'PY' puts the script on stdin — parse argv[1], not stdin.
parse_serverinfo() {
  python3 -c '
import sys, xml.etree.ElementTree as ET
state = currentgame = uniqueid = ""
raw = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    r = ET.fromstring(raw)
    def g(t):
        e = r.find(t)
        return (e.text or "") if e is not None else ""
    state, currentgame, uniqueid = g("state"), g("currentgame"), g("uniqueid")
except Exception as ex:
    print(f"parse_error={ex!r}", file=sys.stderr)
print(f"state={state!r}")
print(f"currentgame={currentgame!r}")
print(f"uniqueid={uniqueid!r}")
' "$1"
}

info=""
for _ in 1 2 3 4 5 6 7 8; do
  info="$(curl -sS --max-time 3 "$KMS_URL/serverinfo?uniqueid=1&uuid=1" 2>/dev/null || true)"
  if [ -n "$info" ]; then
    break
  fi
  sleep 0.4
done
if [ -z "$info" ]; then
  echo "GDS :48200 is down."
  exit 1
fi

state=""
currentgame=""
uniqueid=""
eval "$(parse_serverinfo "$info")"

if [ -z "$uniqueid" ]; then
  echo "GDS :48200 returned unparseable serverinfo."
  exit 1
fi

if [ "$uniqueid" != "$GDS_ID" ]; then
  echo "Wrong uniqueid $uniqueid (want GDS $GDS_ID)."
  exit 1
fi

if [ "$state" = "SUNSHINE_SERVER_BUSY" ] && [ "$currentgame" != "0" ]; then
  echo "BUSY currentgame=$currentgame — closing leftover Desktop via GDS UI."
  sunshine_gds_close_app || true
  sleep 0.4
  info="$(curl -sS --max-time 3 "$KMS_URL/serverinfo?uniqueid=1&uuid=1" 2>/dev/null || true)"
  eval "$(parse_serverinfo "$info")"
fi

if [ "$state" != "SUNSHINE_SERVER_FREE" ] || [ "$currentgame" != "0" ]; then
  echo "GDS is not FREE (state=$state currentgame=$currentgame)."
  exit 1
fi

kms="$(pgrep -x sunshine-ds-kms || true)"
if [ -z "$kms" ]; then
  echo "sunshine-ds-kms is not running."
  exit 1
fi

leftover="$(ps -T -o comm= -p "$kms" | grep -E 'session::audio|session::video|session::join|stream::control' || true)"
if [ -n "$leftover" ]; then
  echo "Leftover session threads:"
  echo "$leftover"
  exit 1
fi

if [ -n "$(pgrep -x sunshine-ds || true)" ]; then
  echo "Desktop sunshine-ds must stay down in Game Mode."
  exit 1
fi

echo "GDS lifecycle gate: FREE pid=$kms uniqueid=$uniqueid"
exit 0
