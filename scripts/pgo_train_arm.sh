#!/usr/bin/env bash
#
# One PGO training arm: run a chosen set of inputs under the already-built
# instrumented binary, merge the profile, and build the PGO binary from it.
#
# This is the Experiment 1 machinery (results.md "Experiment 1 (jaq)"): every
# arm differs ONLY in which inputs the instrumented binary saw. The
# instrumented binary, the merge tool, the PGO-use flags, the cargo profile
# and the toolchain are all the frozen Stage 0 ones.
#
# Usage: export TARGET=jaq; scripts/pgo_train_arm.sh <arm>
#
# Arms:
#   T0                   no PGO at all (plain release, same flags otherwise).
#   T_real               the Stage 0 training set. Its profile is the frozen
#                        pgo/<target>/merged.profdata, copied, not rebuilt:
#                        results.md section 53 records that only the binary
#                        id inside a profdata is irreproducible, and copying
#                        removes even that question.
#   T_allreal            llvm-profdata merge of T_all's profraw with the
#                        frozen profdata. Weighting is by absolute block
#                        count, not by invocation.
#   anything else        passed to scripts/jaq_pool_extract.py, which knows
#                        T_all, T_readme, T_big, T_bench and T_tests.
#
# Environment:
#   GEN_BIN     instrumented binary (default target-<target>-pgo-gen/...).
#   ITEM_TIMEOUT  per-invocation timeout in seconds (default 60; the dry run
#                 in jaq_pool_extract.py already used the repository's own
#                 bench.sh timeout of 10 s on an uninstrumented binary).
#   SKIP_BUILD=1  train and merge only.
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/target_common.sh"

ARM="${1:?usage: pgo_train_arm.sh <arm>}"
GEN_BIN="${GEN_BIN:-$REPO/target-$TARGET-pgo-gen/$TRIPLE/release/$BIN_NAME}"
ITEM_TIMEOUT="${ITEM_TIMEOUT:-60}"
SKIP_BUILD="${SKIP_BUILD:-0}"

ARM_DIR="$PGO_DIR/arms/$ARM"
RAW_DIR="$ARM_DIR/raw"
ARM_PROFDATA="$ARM_DIR/merged.profdata"
TD="$REPO/target-$TARGET-exp1-$ARM"
LOG_DIR="$REPO/artifacts/$TARGET-exp1"
FROZEN="$PGO_DIR/merged.profdata"

SYSROOT="$(rustc --print sysroot)"
LLVM_PROFDATA="$SYSROOT/lib/rustlib/$TRIPLE/bin/llvm-profdata"

mkdir -p "$RAW_DIR" "$LOG_DIR"
rm -f "$RAW_DIR"/*.profraw

banner() { printf '\n========== %s: %s ==========\n' "$ARM" "$*"; }

# ---------------------------------------------------------------------------
# a. the training run
# ---------------------------------------------------------------------------
if [ "$ARM" = T0 ]; then
  banner "no training run (no PGO)"
elif [ "$ARM" = T_real ]; then
  banner "profile = the frozen Stage 0 profdata, copied"
  cp "$FROZEN" "$ARM_PROFDATA"
  chmod u+w "$ARM_PROFDATA"
  echo "invocations: 3 (the Stage 0 training run, results.md section 53)"
elif [ "$ARM" = T_allreal ]; then
  banner "profile = merge(T_all profraw, frozen Stage 0 profdata)"
  ALL_RAW="$PGO_DIR/arms/T_all/raw"
  ls "$ALL_RAW"/*.profraw >/dev/null
  echo "\$ llvm-profdata merge -o $ARM_PROFDATA $ALL_RAW/*.profraw $FROZEN"
  "$LLVM_PROFDATA" merge -o "$ARM_PROFDATA" "$ALL_RAW"/*.profraw "$FROZEN"
else
  banner "training run under the instrumented binary"
  echo "instrumented binary: $GEN_BIN"
  # LLVM_PROFILE_FILE is mandatory: the instrumented binary's baked-in path
  # is the frozen pgo/<target>/profraw/, which must not be written to. %m is
  # LLVM's merge pooling, so N processes accumulate into one file instead of
  # overwriting each other.
  "$REPO/scripts/jaq_pool_extract.py" run "$ARM" \
    --binary "$GEN_BIN" \
    --profile-file "$RAW_DIR/%m.profraw" \
    --timeout "$ITEM_TIMEOUT" \
    --log "$LOG_DIR/train-$ARM.json" --progress
  ls -la "$RAW_DIR"
  banner "llvm-profdata merge"
  echo "\$ llvm-profdata merge -o $ARM_PROFDATA $RAW_DIR/*.profraw"
  "$LLVM_PROFDATA" merge -o "$ARM_PROFDATA" "$RAW_DIR"/*.profraw
fi

if [ "$ARM" != T0 ]; then
  sha256sum "$ARM_PROFDATA"
  "$LLVM_PROFDATA" show "$ARM_PROFDATA" | head -12
fi

# ---------------------------------------------------------------------------
# b. the PGO-use build (identical flags to the Stage 0 baseline)
# ---------------------------------------------------------------------------
[ "$SKIP_BUILD" = 1 ] && { echo "SKIP_BUILD=1, stopping"; exit 0; }

banner "build"
BUILD_LOG="$LOG_DIR/build-$ARM.log"
if [ "$ARM" = T0 ]; then
  # build_variant always passes -Cprofile-use, so T0 is spelled out here. It
  # is byte-for-byte the same recipe minus the profile: same opt-level, lto,
  # codegen-units, debug, panic, strip and -Ctarget-cpu=native.
  rm -rf "$TD"
  CARGO_PROFILE_RELEASE_OPT_LEVEL=3 \
  CARGO_PROFILE_RELEASE_LTO=fat \
  CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
  CARGO_PROFILE_RELEASE_DEBUG=1 \
  CARGO_PROFILE_RELEASE_PANIC=unwind \
  CARGO_TARGET_DIR="$TD" \
  CARGO_ENCODED_RUSTFLAGS="$(enc '-Ctarget-cpu=native' '-Csymbol-mangling-version=v0' \
      '-Cllvm-args=-pass-remarks=.*' \
      '-Cllvm-args=-pass-remarks-missed=.*' \
      '-Cllvm-args=-pass-remarks-analysis=.*')" \
    cargo build --manifest-path "$MANIFEST" --release --target "$TRIPLE" \
      "${CARGO_EXTRA[@]}" >"$BUILD_LOG" 2>&1
else
  PROFDATA="$ARM_PROFDATA" build_variant "$TD" "$BUILD_LOG"
fi
BIN="$TD/$TRIPLE/release/$BIN_NAME"
tail -2 "$BUILD_LOG"

echo "--- remark lines total ---              $(grep -c '^remark: ' "$BUILD_LOG" || true)"
echo "--- hash mismatch ---                   $(grep -c 'hash mismatch' "$BUILD_LOG" || true)"
echo "--- no profile data available for fn -- $(grep -c 'no profile data available for function' "$BUILD_LOG" || true)"
echo "--- all warning: lines ---              $(grep -c '^warning: ' "$BUILD_LOG" || true)"

banner "correctness (the three holdout + three training cases)"
run_correctness "$BIN" "$LOG_DIR/checksums-$ARM.txt"
cat "$LOG_DIR/checksums-$ARM.txt"

banner "done"
