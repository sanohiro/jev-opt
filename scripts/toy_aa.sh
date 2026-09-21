#!/usr/bin/env bash
#
# A/A noise floor on the toy PGO baseline (SPEC.ja.md 10, 13 day-0 item 5).
#
# Build the PGO baseline once, copy the same binary to two labels A1 and A2,
# and measure them interleaved. Any difference between two copies of one
# binary is measurement noise, so the 95% CI half-width of the A1/A2 speed
# ratio is the noise floor, and the minimum detectable effect is
# max(2 x half-width, 3%).
#
# Usage: scripts/toy_aa.sh [runs] [warmup]        (defaults 30 / 5)
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/toy_common.sh"

RUNS="${1:-30}"
WARMUP="${2:-5}"
OUT="$REPO/artifacts/$TARGET-aa"
TD="$REPO/target-$TARGET-aa"

rm -rf "$OUT"; mkdir -p "$OUT" "$REMARK_DIR"

echo "== toolchain =="
rustc -vV | sed -n '1p;$p'
echo "profdata: $PROFDATA"
sha256sum "$PROFDATA"

echo "== topology =="
lscpu -e | head -8
echo "L3 shared_cpu_list for cpu0: $(cat /sys/devices/system/cpu/cpu0/cache/index3/shared_cpu_list)"
echo "thread siblings of cpu$BENCH_CPU: $(cat /sys/devices/system/cpu/cpu$BENCH_CPU/topology/thread_siblings_list)"
echo "ASLR randomize_va_space: $(cat /proc/sys/kernel/randomize_va_space)"

echo "== build PGO baseline =="
build_variant "$TD" "$REMARK_DIR/baseline-build.log"
BIN="$TD/$TRIPLE/release/$BIN_NAME"
echo ".text sha256: $(text_hash "$BIN")"
remark_set "$REMARK_DIR/baseline-build.log" "$OUT/baseline-remarks.txt"
echo "remark lines: $(wc -l < "$OUT/baseline-remarks.txt")"

# Two labels, same bytes. Stripped, because SPEC.ja.md 3 evaluates stripped
# binaries; both copies are stripped the same way so the A/A is unaffected.
cp "$BIN" "$OUT/A1"
cp "$BIN" "$OUT/A2"
strip -s "$OUT/A1" "$OUT/A2"
sha256sum "$OUT/A1" "$OUT/A2"

echo "== interleaved A/A, warmup $WARMUP, $RUNS rounds, pinned to cpu $BENCH_CPU =="
WL=()
for w in "${WORKLOADS[@]}"; do WL+=(--workload "$w"); done
"$REPO/scripts/bench.py" run \
  --cpu "$BENCH_CPU" --warmup "$WARMUP" --runs "$RUNS" \
  --label "A1=$OUT/A1" --label "A2=$OUT/A2" \
  "${WL[@]}" --out "$OUT/aa.json" --progress

"$REPO/scripts/bench.py" stats "$OUT/aa.json" --base A1 \
  --seed 20260921 --resamples 10000 --json "$OUT/aa-stats.json" \
  | tee "$OUT/aa-stats.md"
