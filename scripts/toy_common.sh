#!/usr/bin/env bash
# Shim: the day-0 toy scripts' shared helper moved to target_common.sh when
# zopfli became the second target. Sourced, not executed.
TARGET="${TARGET:-toy}"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/target_common.sh"
