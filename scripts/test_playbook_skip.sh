#!/usr/bin/env bash
# Offline checks for playbook_step_skipped / require_playbook_user.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_skip() {
  playbook_step_skipped "$1" || fail "expected skip: $1"
}

assert_run() {
  if playbook_step_skipped "$1"; then
    fail "expected run: $1"
  fi
}

unset PLAYBOOK_SKIP
unset SKIP_ENSURE_SWITCH2_CONTROLLERS
unset SKIP_ENSURE_OPENRGB
unset SKIP_ENSURE_SUNSHINE

load_env "$ROOT"
# Default after load_env (unless .env emptied it).
if [ "${PLAYBOOK_SKIP-unset}" = "unset" ]; then
  fail "load_env left PLAYBOOK_SKIP unset"
fi

if [ "${PLAYBOOK_SKIP}" = "switch2-controllers" ]; then
  assert_skip "ensure-switch2-controllers"
  assert_skip "switch2-controllers"
  assert_run "ensure-openrgb"
  assert_run "ensure-sunshine"
elif [ -z "${PLAYBOOK_SKIP}" ]; then
  # .env set PLAYBOOK_SKIP= to run all
  assert_run "ensure-switch2-controllers"
else
  echo "note: PLAYBOOK_SKIP from .env is ${PLAYBOOK_SKIP}"
fi

PLAYBOOK_SKIP=""
assert_run "ensure-switch2-controllers"
assert_run "ensure-openrgb"

PLAYBOOK_SKIP="openrgb,sunshine"
assert_run "ensure-openrgb"
assert_run "openrgb"
assert_skip "ensure-sunshine"
assert_run "ensure-switch2-controllers"

PLAYBOOK_SKIP="ensure-emupads-mux"
assert_skip "ensure-emupads-mux"
assert_skip "emupads-mux"
assert_run "ensure-openrgb"

PLAYBOOK_SKIP=""
SKIP_ENSURE_OPENRGB=1
assert_run "ensure-openrgb"
assert_run "openrgb"
assert_run "ensure-sunshine"
unset SKIP_ENSURE_OPENRGB

SKIP_ENSURE_SWITCH2_CONTROLLERS=true
assert_skip "ensure-switch2-controllers"
unset SKIP_ENSURE_SWITCH2_CONTROLLERS

SKIP_ENSURE_SWITCH2_CONTROLLERS=yes
assert_skip "switch2-controllers"
unset SKIP_ENSURE_SWITCH2_CONTROLLERS

require_playbook_user || fail "require_playbook_user failed as uid $(id -u)"
[ -n "${XDG_RUNTIME_DIR:-}" ] || fail "require_playbook_user did not set XDG_RUNTIME_DIR"
[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] || fail "require_playbook_user did not set DBUS_SESSION_BUS_ADDRESS"

echo "test_playbook_skip ok"
