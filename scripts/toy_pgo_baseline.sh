#!/usr/bin/env bash
# Shim for results.md "Day 0 (toy)": scripts/toy_pgo_baseline.sh is now
# TARGET=toy scripts/target_pgo_baseline.sh.
exec env TARGET=toy "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/target_pgo_baseline.sh" "$@"
