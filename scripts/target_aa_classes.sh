#!/usr/bin/env bash
# argv[0] length-class A/A check on a real target (HANDOFF 4 row 3e,
# decision 97, results.md 163 pre-registration).
#
# On hintbench the same binary reads ~9% apart on k5 depending on the byte
# length of the exec path (glibc chunk class c = max(32, (len+23) & ~15):
# c96/c128 slow, c80/c112 fast). jaq and zopfli also copy argv onto the heap
# before reading their input. This script times ONE panel of four hard links
# to ONE stripped inode of the target's frozen PGO baseline, exec'd raw from
# paths of length 64 / 80 / 96 / 112 (classes 80 / 96 / 112 / 128), with the
# target's own CPU, settle gap, stdout policy and case set, and reads the
# ratios against the c96 leg (len 80 = the pinned alias of decision 97).
#
# Nothing is built and nothing is sent over HTTP. Output:
#   artifacts/<target>-aa-classes/{bin/,paths.tsv,panel.txt,cmd.txt,
#     samples.json,stats.json,stats.md,readout.txt}
#
# Usage:
#   scripts/target_aa_classes.sh <jaq|zopfli> [--dry-run]
#       [--runs N] [--warmup N] [--seed S]
#
# --dry-run does everything except exec bench.py: gate, source hash, strip,
# stripped hash, hard links, length / class / inode asserts, paths.tsv,
# panel.txt, cmd.txt, and prints the bench.py command. The defaults of
# --runs/--warmup/--seed are the pre-registered values; overriding them is a
# deviation and must be written down in results.md.
#
# bench.py prints "WARNING: --argv0-raw and the exec paths fall in different
# argv[0] chunk classes" on stderr. That is the point of this panel, not a
# failure.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH="$REPO/scripts/bench.py"
READOUT="$REPO/scripts/target_aa_classes_readout.py"

die() { echo "target_aa_classes: $*" >&2; exit "${RC:-2}"; }

[ "$#" -ge 1 ] || die "usage: $0 <jaq|zopfli> [--dry-run] [--runs N] [--warmup N] [--seed S]"
T="$1"; shift
DRY=0; RUNS=""; WARMUP=""; SEED=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --runs)    [ "$#" -ge 2 ] || die "--runs needs a value";   RUNS="$2";   shift 2 ;;
    --warmup)  [ "$#" -ge 2 ] || die "--warmup needs a value"; WARMUP="$2"; shift 2 ;;
    --seed)    [ "$#" -ge 2 ] || die "--seed needs a value";   SEED="$2";   shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done
for v in "$RUNS" "$WARMUP" "$SEED"; do
  [ -z "$v" ] || [[ "$v" =~ ^[0-9]+$ ]] || die "not a non-negative integer: $v"
done

# Per-target frozen inputs (results.md 163). SRC is the unstripped frozen
# baseline; SRC_SHA its sha256; STRIP_SHA the sha256 of `strip -s` of it,
# which is the binary every earlier timing batch of the target measured.
case "$T" in
  jaq)
    # jev_search.py baseline of every jaq search/oracle run
    # (artifacts/jaq-search/jev-r5/baseline/baseline.json bin_sha256);
    # stripped = artifacts/jaq-search/oracle-A2-holdout/timing/base.
    SRC="$REPO/artifacts/jaq-search/jev-r5/baseline/bin"
    SRC_SHA=e183c81d1d7e9177720b0ac03cb67095984e3fe168ecabd9a1959ccc9f1f4d02
    STRIP_SHA=83f7eb239c786c8c988b80944b609cf959a9e2c80bc2dbbf7f43df94b683c13b
    SET=training          # the case set of every jaq search/oracle round
    D_RUNS=35; D_WARMUP=3; D_SEED=20260925
    ;;
  zopfli)
    # Stage 0 PGO baseline (results.md 24-26); stripped = artifacts/zopfli-aa/A1
    # and artifacts/zopfli-headroom/strip/baseline.
    SRC="$REPO/artifacts/zopfli-headroom/bin/baseline"
    SRC_SHA=8b0ba235be9bf45c167f7cbf39edb096668e0f2eb1d320dcbd1718d1f97ea8a4
    STRIP_SHA=79c3322677aa336f8fab45c449559cac9568277636afdfc998e9d07bae887a98
    SET=holdout           # Stage 0's case set (zopfli has no TRAIN_WORKLOADS)
    D_RUNS=18; D_WARMUP=3; D_SEED=20260926
    ;;
  *) die "target must be jaq or zopfli, got '$T'" ;;
esac
RUNS="${RUNS:-$D_RUNS}"; WARMUP="${WARMUP:-$D_WARMUP}"; SEED="${SEED:-$D_SEED}"

# decision 31: `export`, not a temporary assignment, before sourcing.
export TARGET="$T"
export BENCH_SET="$SET"
# shellcheck source=target_common.sh
source "$REPO/scripts/target_common.sh" || die "sourcing target_common.sh failed"
[ "$TARGET" = "$T" ] || die "TARGET changed while sourcing ($TARGET)"

# One timing job at a time (AGENTS.md). Bracket trick: grep never matches itself.
if ps -eo cmd | grep -E '[b]ench\.py|[j]ev_search|[c]argo (build|rustc)' >/dev/null; then
  echo "another bench.py / jev_search / cargo build is running; refusing" >&2
  ps -eo pid,cmd | grep -E '[b]ench\.py|[j]ev_search|[c]argo (build|rustc)' >&2
  RC=3 die "machine busy"
fi

OUT="$REPO/artifacts/$T-aa-classes"
BDIR="$OUT/bin"
[ -e "$OUT/samples.json" ] && RC=4 die "$OUT/samples.json exists; this panel runs once (move it away to re-run, and say so in results.md)"
[ -f "$SRC" ] || die "no baseline binary at $SRC"
mkdir -p "$BDIR" || die "cannot create $BDIR"
cd "$REPO" || die "cannot cd $REPO"

sha() { sha256sum "$1" | cut -d' ' -f1; }
chunk() { python3 -c "import sys; n=int(sys.argv[1]); print(max(32,(n+23)&~15))" "$1"; }

got="$(sha "$SRC")"
[ "$got" = "$SRC_SHA" ] || die "source sha256 $got != frozen $SRC_SHA ($SRC)"
rm -f "$BDIR"/*
cp "$SRC" "$BDIR/src" && strip -s "$BDIR/src" || die "copy/strip failed"
got="$(sha "$BDIR/src")"
[ "$got" = "$STRIP_SHA" ] || die "stripped sha256 $got != frozen $STRIP_SHA"

# name_for LEN PREFIX: file name so that len("$BDIR/<name>") == LEN (bytes).
name_for() {
  python3 - "$BDIR" "$1" "$2" <<'PY'
import os, sys
d, t, p = os.fsencode(sys.argv[1]), int(sys.argv[2]), sys.argv[3].encode()
n = t - len(d) - 1
if n < len(p):
    sys.exit(f"dir {d.decode()} ({len(d)} bytes) too long for an exec path of "
             f"{t} bytes with prefix {p.decode()}")
name = p + b"x" * (n - len(p))
assert len(d + b"/" + name) == t
print(name.decode())
PY
}

# Legs: label:class:len. c96 FIRST (the base of every ratio); len 80 is
# exactly the length of bench.py's pinned alias. 64/96/112 put the four legs
# in four distinct glibc classes (80/96/112/128). jaq's global allocator is
# mimalloc, where the glibc class means nothing; by mimalloc's bin table (not
# measured) the four lengths also fall in four distinct bins (64/80/96/112).
# The hintbench study used 70 for c80; 64 is the same glibc class.
LEGS=(c96:96:80 c80:80:64 c112:112:96 c128:128:112)
LABELS=(); PATHS=()
for leg in "${LEGS[@]}"; do
  IFS=: read -r lab cls len <<< "$leg"
  [ "$(chunk "$len")" = "$cls" ] || die "class assert failed: len $len is class $(chunk "$len"), not $cls"
  n="$(name_for "$len" "$(printf 'c%03d' "$cls")")" || die "name_for failed for $leg"
  p="$BDIR/$n"
  ln -f "$BDIR/src" "$p" || die "ln failed: $p"
  plen="$(printf '%s' "$p" | wc -c)"
  [ "$plen" = "$len" ] || die "length assert failed: $p is $plen bytes, not $len"
  LABELS+=(--label "$lab=$p"); PATHS+=("$p")
done

# Every leg is the same inode as src (byte identity is structural).
ino="$(stat -c %i "$BDIR/src")"
for p in "${PATHS[@]}"; do
  [ "$(stat -c %i "$p")" = "$ino" ] || die "inode assert failed: $p"
done
{
  printf 'label\tpath\tlen\tclass\tinode\tsha256\n'
  i=0
  for leg in "${LEGS[@]}"; do
    p="${PATHS[$i]}"; l="${#p}"
    printf '%s\t%s\t%d\t%d\t%s\t%s\n' "${leg%%:*}" "$p" "$l" "$(chunk "$l")" \
      "$(stat -c %i "$p")" "$(sha "$p")"
    i=$((i+1))
  done
} > "$OUT/paths.tsv"

WL=(); for w in "${WORKLOADS[@]}"; do WL+=(--workload "$w"); done
CMD=(python3 -u "$BENCH" run --cpu "$BENCH_CPU" --warmup "$WARMUP" --runs "$RUNS"
     --stdout "$BENCH_STDOUT" --gap-ms "$BENCH_GAP_MS" --shuffle "$SEED"
     --argv0-raw "${LABELS[@]}" "${WL[@]}" --out "$OUT/samples.json")
STATS=(python3 -u "$BENCH" stats "$OUT/samples.json" --base c96 --seed "$SEED"
       --resamples 10000 --json "$OUT/stats.json")

{
  echo "== $T argv0 class panel, case set $BENCH_SET, $RUNS runs, warmup $WARMUP =="
  echo "cpu $BENCH_CPU, gap $BENCH_GAP_MS ms, stdout $BENCH_STDOUT, shuffle $SEED, argv0 raw"
  echo "started $(date '+%Y-%m-%dT%H:%M:%S%z') load $(cut -d' ' -f1-3 /proc/loadavg) git $(git -C "$REPO" rev-parse --short HEAD)"
  rustc -vV | sed -n '1p'
  echo "source $SRC $SRC_SHA"
  echo "stripped $BDIR/src $STRIP_SHA inode $ino"
  cat "$OUT/paths.tsv"
  echo "workloads (${#WORKLOADS[@]}):"; for w in "${WORKLOADS[@]}"; do echo "  ${w:0:160}"; done
} > "$OUT/panel.txt"
printf '%q ' "${CMD[@]}" > "$OUT/cmd.txt"; echo >> "$OUT/cmd.txt"
printf '%q ' "${STATS[@]}" >> "$OUT/cmd.txt"; echo >> "$OUT/cmd.txt"
cat "$OUT/panel.txt"

if [ "$DRY" = 1 ]; then
  echo "--- dry run: would execute (cmd.txt) ---"
  cat "$OUT/cmd.txt"
  exit 0
fi

"${CMD[@]}" || RC=5 die "bench.py run failed"
"${STATS[@]}" > "$OUT/stats.md" || RC=6 die "bench.py stats failed"
echo "finished $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "$OUT/panel.txt"
python3 -u "$READOUT" "$OUT" --target "$T" | tee "$OUT/readout.txt"
