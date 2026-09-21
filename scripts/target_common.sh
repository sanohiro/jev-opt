#!/usr/bin/env bash
#
# Shared build helper for the day-0 scripts (A/A and headroom sweep).
# Sourced, not executed.
#
# Everything here is the PGO baseline recipe of SPEC.ja.md 3: the same
# merged.profdata, the same debuginfo, the same panic strategy and the same
# remark flags for every configuration. The only thing a caller varies is the
# list of extra -Cllvm-args knobs.
#
# One knob selects the target: TARGET=toy (default) or TARGET=zopfli. The
# case block below is the only place a target name appears; SPEC.ja.md 11
# requires that switching targets touch nothing else. Everything downstream
# (build recipe, remark handling, .text hash, bench.py invocation) is target
# independent.
#
# Was scripts/toy_common.sh through results.md "Day 0 (toy)"; renamed when
# zopfli became the second target. scripts/toy_*.sh are shims that set
# TARGET=toy, so every command quoted in that section still runs.

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${TARGET:-toy}"
TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"

# --- per-target configuration ----------------------------------------------
#
# MANIFEST        cargo manifest to build (never edited; SPEC.ja.md 0 requires
#                 that neither the sources nor the Cargo.toml of a target be
#                 touched, so everything is driven by environment variables).
# BIN_NAME        binary produced by that manifest.
# CARGO_EXTRA     extra cargo arguments (a vendored submodule gets --locked so
#                 its Cargo.lock cannot drift under us).
# WORKLOADS       bench.py --workload specs, NAME=ARGS. These are the holdout
#                 cases: A/A and the headroom timing run on them.
# TRAIN_INPUTS    the training cases. Used once, by the instrumented build, to
#                 produce merged.profdata (SPEC.ja.md 3). Disjoint from the
#                 holdout by construction.
# CORRECTNESS_IN  every input whose output is checksummed by run_correctness.
case "$TARGET" in
  toy)
    MANIFEST="${MANIFEST:-$REPO/targets/toy/Cargo.toml}"
    BIN_NAME="${BIN_NAME:-toy}"
    CARGO_EXTRA=()
    WORKLOADS=(quotes special sum dot)
    TRAIN_ARGS=(all)
    CORRECTNESS_IN=()
    ;;
  zopfli)
    MANIFEST="${MANIFEST:-$REPO/targets/zopfli/src/Cargo.toml}"
    BIN_NAME="${BIN_NAME:-zopfli}"
    # The bin needs the gzip + std + zlib features; they are the crate's
    # default features, so no --features is required. --locked pins the
    # vendored Cargo.lock.
    CARGO_EXTRA=(--locked)
    WLDIR="$REPO/targets/zopfli/workloads"
    WORKLOADS=("text=$WLDIR/hold-text.dat"
               "binary=$WLDIR/hold-binary.dat"
               "json=$WLDIR/hold-json.dat")
    TRAIN_ARGS=("$WLDIR/train-text.dat" "$WLDIR/train-binary.dat" "$WLDIR/train-json.dat")
    CORRECTNESS_IN=("$WLDIR/train-text.dat" "$WLDIR/train-binary.dat" "$WLDIR/train-json.dat"
                    "$WLDIR/hold-text.dat" "$WLDIR/hold-binary.dat" "$WLDIR/hold-json.dat")
    ;;
  *)
    echo "target_common.sh: unknown TARGET=$TARGET" >&2
    return 1 2>/dev/null || exit 1
    ;;
esac

PGO_DIR="$REPO/pgo/$TARGET"
PROFDATA="${PROFDATA:-$PGO_DIR/merged.profdata}"
REMARK_DIR="$REPO/remarks/$TARGET"

# Physical core to pin measurements to (SPEC.ja.md 10). See results.md: WSL2
# reports a single L3 instance for all 32 CPUs, so the CCD boundary of the
# 5950X is not visible from inside the guest. CPU 2 is core 1; its SMT sibling
# CPU 3 is left unused.
BENCH_CPU="${BENCH_CPU:-2}"

# CARGO_ENCODED_RUSTFLAGS is \x1f-separated.
enc() { local out="$1"; shift; for a in "$@"; do out="$out$(printf '\x1f')$a"; done; printf '%s' "$out"; }

# build_variant <target-dir> <build-log> [extra knobs...]
#
# A knob is an LLVM cl::opt by default and is wrapped in -Cllvm-args=. A knob
# that already starts with `-C` is a rustc codegen option and is passed
# through untouched, which is what SPEC.ja.md 6.3 group 4 needs
# (-Ctarget-feature, -Ctarget-cpu); rustc takes the last occurrence of a
# repeated -Ctarget-cpu, so a group-4 value overrides the baseline's =native.
#
# Clean build every time: cargo does not rebuild on an environment-variable
# change alone (SPEC.ja.md 4). Returns non-zero if the build fails; the caller
# decides whether that is fatal (a knob that cannot build is a result).
build_variant() {
  local td="$1" log="$2"; shift 2
  local extra=()
  local a
  for a in "$@"; do
    case "$a" in
      -C*) extra+=("$a") ;;
      *)   extra+=("-Cllvm-args=$a") ;;
    esac
  done
  rm -rf "$td"
  CARGO_PROFILE_RELEASE_OPT_LEVEL=3 \
  CARGO_PROFILE_RELEASE_LTO=fat \
  CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
  CARGO_PROFILE_RELEASE_DEBUG=1 \
  CARGO_PROFILE_RELEASE_PANIC=unwind \
  CARGO_TARGET_DIR="$td" \
  CARGO_ENCODED_RUSTFLAGS="$(enc '-Ctarget-cpu=native' '-Csymbol-mangling-version=v0' \
      "-Cprofile-use=$PROFDATA" \
      '-Cllvm-args=-pgo-warn-missing-function' \
      '-Cllvm-args=-pass-remarks=.*' \
      '-Cllvm-args=-pass-remarks-missed=.*' \
      '-Cllvm-args=-pass-remarks-analysis=.*' \
      "${extra[@]}")" \
    cargo build --manifest-path "$MANIFEST" --release --target "$TRIPLE" \
      "${CARGO_EXTRA[@]}" >"$log" 2>&1
}

# run_correctness <binary> <out-file>
#
# Writes one "name sha256" line per case. SPEC.ja.md 10 makes output equality
# the correctness check, and results.md Day 0 section 13 makes it a
# *precondition* of the headroom judgement: the toy's largest measured
# "speedup" was a binary that computed a different answer.
#
#  toy     prints a checksum block on stdout.
#  zopfli  writes <input>.gz beside its input and prints nothing, so each run
#          gets its own scratch copy of the input and the .gz is hashed. The
#          scratch copy also keeps concurrent correctness runs from colliding
#          and keeps the timed runs' output files out of the way.
run_correctness() {
  local bin="$1" out="$2"
  case "$TARGET" in
    toy)
      "$bin" all > "$out" 2>&1 || echo "RUN FAILED" >> "$out"
      ;;
    zopfli)
      local scratch; scratch="$(mktemp -d)"
      : > "$out"
      local f base
      for f in "${CORRECTNESS_IN[@]}"; do
        base="$(basename "$f")"
        cp "$f" "$scratch/$base"
        if "$bin" "$scratch/$base" >/dev/null 2>&1; then
          printf '%s %s\n' "$base" \
            "$(sha256sum "$scratch/$base.gz" | cut -d' ' -f1)" >> "$out"
        else
          printf '%s RUN-FAILED\n' "$base" >> "$out"
        fi
        rm -f "$scratch/$base" "$scratch/$base.gz"
      done
      rmdir "$scratch"
      ;;
  esac
}

# remark_set <build-log> <out-file>
#
# The remark line SET is deterministic; the ORDER is not, because several rustc
# processes write to the same stderr (SPEC.ja.md 6.3). Sort before diffing.
remark_set() {
  grep '^remark: ' "$1" | sort -u > "$2"
  grep -c '^remark: ' "$1" > "$2.count" || true
}

# remark_set_normalized <build-log> <out-file>
#
# Same, with only the cost-model numbers masked out. Without this every
# -inline-threshold config differs from the baseline on
# "(cost=-14995, threshold=525)" alone, which says nothing about a changed
# decision. Vectorization width / interleave count and file:line:col are NOT
# masked: those are the decision.
remark_set_normalized() {
  grep '^remark: ' "$1" \
    | sed -E 's/cost=-?[0-9]+/cost=C/g; s/threshold=-?[0-9]+/threshold=T/g;
              s/cost -?[0-9]+/cost C/g; s/threshold -?[0-9]+/threshold T/g;
              s/tree size [0-9]+/tree size S/g' \
    | sort -u > "$2"
}

# vec_decisions <normalized-remark-set> <out-file>
#
# The subset of the normalized remark set that is a vectorizer *decision*:
# a loop that was vectorized (with its width and interleave count), or one
# that was refused. Target independent, which is what replaces the toy's
# hand-written table of four DebugLocs.
vec_decisions() {
  grep -E 'vectorized loop|loop not vectorized|interleaved count|Vectorizing ordered reduction|Vectorized horizontal reduction' \
    "$1" | sort -u > "$2" || true
}

text_hash() {
  objcopy -O binary --only-section=.text "$1" /dev/stdout | sha256sum | cut -d' ' -f1
}
