#!/usr/bin/env bash
# Shim for results.md "Day 0 (toy)": scripts/toy_headroom.sh is now
# TARGET=toy scripts/target_headroom.sh.
exec env TARGET=toy "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/target_headroom.sh" "$@"
