#!/usr/bin/env bash
#
# Record a `perf` profile of the PGO baseline binary on every frozen workload
# of a target, holdout and training alike, and write one perf.data per case.
#
# This is the "where are the cycles" step decision 58 puts in front of the
# marks file: the human's proxy picks the functions to mark from a wall-clock
# profile, not from the PGO counters. The two differ on jaq for two reasons
# the profile has to be able to see -- mimalloc is C, which -Cprofile-generate
# cannot instrument at all, and a profdata record is a *pre-inlining* IR
# function while a perf sample lands in the post-LTO symbol that absorbed it.
#
# Usage:
#   export TARGET=jaq                 # NOT `TARGET=jaq scripts/...` for the
#                                     # sourced common file's sake (sec. 31.6)
#   scripts/perf_marks_profile.sh OUTDIR [REPEATS] [FREQ]
#
# Environment:
#   BIN         binary to profile (default: the pgo-use build of $TARGET)
#   CALLGRAPH   unset (flat, default) or `dwarf,<size>` for a callchain pass
#   SETS        `both` (default), `holdout` or `training`
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:?usage: perf_marks_profile.sh OUTDIR [REPEATS] [FREQ]}"
REPEATS="${2:-6}"
FREQ="${3:-5000}"
SETS="${SETS:-both}"

export TARGET="${TARGET:-jaq}"
# shellcheck source=/dev/null
source "$REPO/scripts/target_common.sh"

PERF="$("$REPO/scripts/perf_local.sh" path)"
[ -x "$PERF" ] || PERF="$("$REPO/scripts/perf_local.sh" setup)"
BIN="${BIN:-$REPO/target-$TARGET-pgo-use/$TRIPLE/release/$BIN_NAME}"
[ -x "$BIN" ] || { echo "no binary at $BIN" >&2; exit 1; }

mkdir -p "$OUT"
echo "perf:    $PERF ($("$PERF" --version))"
echo "binary:  $BIN"
echo "cpu:     $BENCH_CPU   repeats: $REPEATS   freq: $FREQ   callgraph: ${CALLGRAPH:-none}"

record_one() {                      # record_one <label> <spec>
  local label="$1" spec="$2" name args argv=() q i loop
  name="${spec%%=*}"; args="${spec#*=}"
  eval "argv=($args)"
  q="$(printf '%q ' "$BIN" "${argv[@]}")"
  loop="for i in \$(seq 1 $REPEATS); do $q >/dev/null; done"
  local cg=()
  [ -n "${CALLGRAPH:-}" ] && cg=(--call-graph "$CALLGRAPH")
  taskset -c "$BENCH_CPU" "$PERF" record -e cycles:u -F "$FREQ" \
      "${cg[@]}" --no-buildid-cache -o "$OUT/$label-$name.data" \
      -- bash -c "$loop" 2>&1 | sed "s/^/  [$label-$name] /"
}

if [ "$SETS" = both ] || [ "$SETS" = holdout ]; then
  for spec in "${WORKLOADS[@]}"; do record_one hold "$spec"; done
fi
if [ "$SETS" = both ] || [ "$SETS" = training ]; then
  for spec in "${TRAIN_WORKLOADS[@]}"; do record_one train "$spec"; done
fi
ls -la "$OUT"
