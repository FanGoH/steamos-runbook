#!/usr/bin/env bash
echo "health.sh is deprecated; use ./health-check.sh" >&2
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/health-check.sh" "$@"
