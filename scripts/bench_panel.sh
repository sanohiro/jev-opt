#!/usr/bin/env bash
#
# One timing batch over N already-built binaries, with the target's frozen
# measurement conditions (SPEC.ja.md 2, 3).
#
# `scripts/target_aa.sh` builds a baseline and times two copies of it;
# `scripts/jev_search.py` times base/cand/aa inside a search round. This does
# neither: it takes binaries that already exist and measures them in one
# interleaved batch, which is what two jobs outside a search round need:
#
#   * the null panel --- four copies of one binary, so that the spread
#     between byte-identical builds under exactly the run's conditions is a
#     measured number and not an inference from one A/A pair
#     (results.md "Experiment 3 (jaq)" 99 saw 2.1 points on the holdout set);
#   * one measurement of a binary a search run did not promote to `best`, on
#     the holdout set, without touching the acceptance rule that decides what
#     `--measure-holdout` would have measured.
#
# The binaries are copied and stripped first, because SPEC.ja.md 3 evaluates
# stripped binaries and a copy per label is what keeps the file the kernel
# maps distinct per label.
#
# Usage:
#   TARGET=jaq BENCH_SET=training scripts/bench_panel.sh OUT RUNS WARMUP SEED \
#       label=/path/to/bin [label=/path/to/bin ...]
#
# The FIRST label is the base of the ratios. CPU, settle gap and stdout policy
# come from target_common.sh; nothing about the recipe is named here.
#
# bench.py execs every label through an 80-byte argv[0] alias (decision 97).
# BENCH_ARGV0_RAW=1 passes --argv0-raw, so the copies under $OUT/timing are
# exec'd as named (for studies that vary the path length on purpose). Each
# label's exec-path length and chunk class is appended to panel.txt.
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/target_common.sh"

OUT="$1"; RUNS="$2"; WARMUP="$3"; SEED="$4"; shift 4
[ "$#" -ge 2 ] || { echo "need at least two label=path arguments" >&2; exit 2; }

mkdir -p "$OUT/timing"
LABELS=()
BASE=""
for spec in "$@"; do
  name="${spec%%=*}"; src="${spec#*=}"
  [ -f "$src" ] || { echo "no such binary: $src" >&2; exit 2; }
  cp "$src" "$OUT/timing/$name"
  strip -s "$OUT/timing/$name"
  LABELS+=(--label "$name=$OUT/timing/$name")
  [ -z "$BASE" ] && BASE="$name"
done

{
  echo "== $TARGET, case set ${BENCH_SET:-holdout}, $RUNS runs, warmup $WARMUP =="
  echo "cpu $BENCH_CPU, gap $BENCH_GAP_MS ms, stdout $BENCH_STDOUT, shuffle $SEED"
  rustc -vV | sed -n '1p'
  sha256sum "$@" 2>/dev/null || true
  sha256sum "$OUT"/timing/*
} | tee "$OUT/panel.txt"

WL=()
for w in "${WORKLOADS[@]}"; do WL+=(--workload "$w"); done
RAW=()
[ "${BENCH_ARGV0_RAW:-}" = "1" ] && RAW=(--argv0-raw)

"$REPO/scripts/bench.py" run \
  --cpu "$BENCH_CPU" --warmup "$WARMUP" --runs "$RUNS" \
  --stdout "$BENCH_STDOUT" --gap-ms "$BENCH_GAP_MS" --shuffle "$SEED" \
  ${RAW[@]+"${RAW[@]}"} "${LABELS[@]}" "${WL[@]}" --out "$OUT/samples.json"

python3 -c '
import json, sys
h = json.load(open(sys.argv[1]))["header"]
print("argv0 mode %s" % h.get("argv0_mode"))
for n, d in (h.get("argv0") or {}).items():
    print("argv0 %s len %d class %d %s" % (n, d["len"], d["class"], d["path"]))
' "$OUT/samples.json" | tee -a "$OUT/panel.txt"

"$REPO/scripts/bench.py" stats "$OUT/samples.json" --base "$BASE" \
  --seed "$SEED" --resamples 10000 --json "$OUT/stats.json" \
  | tee "$OUT/stats.md"
