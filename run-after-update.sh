#!/usr/bin/env bash
echo "run-after-update.sh is deprecated; use ./post-update.sh" >&2
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/post-update.sh" "$@"
