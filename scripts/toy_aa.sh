#!/usr/bin/env bash
# Shim for results.md "Day 0 (toy)": scripts/toy_aa.sh is now
# TARGET=toy scripts/target_aa.sh.
exec env TARGET=toy "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/target_aa.sh" "$@"
