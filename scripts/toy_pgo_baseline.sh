#!/usr/bin/env bash
#
# Day 0, toy target: hand-run the PGO baseline end to end (SPEC.ja.md 3, 13-day-0).
#
# This is the manual version of what `jev-opt baseline` will later do:
#   plain release build -> instrumented build -> training run -> llvm-profdata
#   merge -> PGO baseline build (with remarks) -> checksum and .text checks.
#
# Nothing here is a conclusion; every step prints the command's raw output so
# results.md can quote it.
#
# Usage: scripts/toy_pgo_baseline.sh
#
# Environment:
#   TARGET=toy          target name; only the artifact paths are parameterised
#                       (pgo/<target>/, remarks/<target>/), the build itself is
#                       still the toy workspace.
#   REUSE_PROFDATA=1    keep an existing pgo/<target>/merged.profdata and skip
#                       the instrumented build and the training run. The
#                       training run happens once per target (SPEC.ja.md 3);
#                       re-running it is only allowed because the toy's
#                       profdata was shown to be byte-reproducible.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${TARGET:-toy}"
TOY="$REPO/targets/toy"
PGO_DIR="$REPO/pgo/$TARGET"
PROFRAW_DIR="$PGO_DIR/profraw"
PROFDATA="$PGO_DIR/merged.profdata"
REMARK_DIR="$REPO/remarks/$TARGET"
LOG_DIR="$REPO/artifacts/$TARGET-day0"
REUSE_PROFDATA="${REUSE_PROFDATA:-1}"

TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
SYSROOT="$(rustc --print sysroot)"
LLVM_PROFDATA="$SYSROOT/lib/rustlib/$TRIPLE/bin/llvm-profdata"

# Every variant gets its own CARGO_TARGET_DIR and is built from scratch: cargo
# does not rebuild on an environment-variable change alone (SPEC.ja.md 4).
TD_PLAIN="$REPO/target-toy-plain"
TD_GEN="$REPO/target-toy-pgo-gen"
TD_USE="$REPO/target-toy-pgo-use"
TD_USE_D0="$REPO/target-toy-pgo-use-debug0"

# Fixed cargo release-profile values. The toy's own Cargo.toml already sets
# these; they are repeated here so the variants that must differ (debug) differ
# in exactly one place.
export CARGO_PROFILE_RELEASE_OPT_LEVEL=3
export CARGO_PROFILE_RELEASE_LTO=fat
export CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1
export CARGO_PROFILE_RELEASE_PANIC=unwind

# CARGO_ENCODED_RUSTFLAGS is \x1f-separated.
enc() { local out="$1"; shift; for a in "$@"; do out="$out$(printf '\x1f')$a"; done; printf '%s' "$out"; }

banner() { printf '\n========== %s ==========\n' "$*"; }

rm -rf "$TD_PLAIN" "$TD_GEN" "$TD_USE" "$TD_USE_D0" "$REMARK_DIR" "$LOG_DIR"
if [ "$REUSE_PROFDATA" = 1 ] && [ -f "$PROFDATA" ]; then
  REUSE=1
else
  REUSE=0
  rm -rf "$PGO_DIR"
fi
mkdir -p "$PROFRAW_DIR" "$REMARK_DIR" "$LOG_DIR"

banner "toolchain"
rustc -vV
echo "host triple:    $TRIPLE"
echo "sysroot:        $SYSROOT"
echo "llvm-profdata:  $LLVM_PROFDATA"
"$LLVM_PROFDATA" --version

# ---------------------------------------------------------------------------
# 0. Plain (non-PGO) release build. Reference checksums come from this one.
# ---------------------------------------------------------------------------
banner "0. plain release build (no PGO)"
CARGO_PROFILE_RELEASE_DEBUG=1 \
CARGO_TARGET_DIR="$TD_PLAIN" \
CARGO_ENCODED_RUSTFLAGS="$(enc '-Ctarget-cpu=native' '-Csymbol-mangling-version=v0')" \
  cargo build --manifest-path "$TOY/Cargo.toml" --release --target "$TRIPLE" 2>&1 | tail -3
BIN_PLAIN="$TD_PLAIN/$TRIPLE/release/toy"
"$BIN_PLAIN" all | tee "$LOG_DIR/checksums-plain.txt"

# ---------------------------------------------------------------------------
# a. Instrumented build. No remarks, no plugin (SPEC.ja.md 3).
# ---------------------------------------------------------------------------
if [ "$REUSE" = 1 ]; then
banner "a-c. reusing existing profdata (no instrumented build, no training run)"
echo "profdata: $PROFDATA"
sha256sum "$PROFDATA"
"$LLVM_PROFDATA" show --all-functions "$PROFDATA" | tail -12
else
banner "a. instrumented build (-Cprofile-generate)"
CARGO_PROFILE_RELEASE_DEBUG=1 \
CARGO_TARGET_DIR="$TD_GEN" \
CARGO_ENCODED_RUSTFLAGS="$(enc '-Ctarget-cpu=native' '-Csymbol-mangling-version=v0' "-Cprofile-generate=$PROFRAW_DIR")" \
  cargo build --manifest-path "$TOY/Cargo.toml" --release --target "$TRIPLE" 2>&1 | tail -3
BIN_GEN="$TD_GEN/$TRIPLE/release/toy"

# ---------------------------------------------------------------------------
# b. Training run. `all` is the training workload for the toy.
# ---------------------------------------------------------------------------
banner "b. training run (instrumented, workload=all)"
GEN_START=$(date +%s%N)
"$BIN_GEN" all | tee "$LOG_DIR/checksums-instrumented.txt"
GEN_END=$(date +%s%N)
echo "training run wall time: $(( (GEN_END - GEN_START) / 1000000 )) ms"
ls -la "$PROFRAW_DIR"

# ---------------------------------------------------------------------------
# c. Merge with the pinned toolchain's llvm-profdata.
# ---------------------------------------------------------------------------
banner "c. llvm-profdata merge"
echo "\$ $LLVM_PROFDATA merge -o $PROFDATA $PROFRAW_DIR/*.profraw"
"$LLVM_PROFDATA" merge -o "$PROFDATA" "$PROFRAW_DIR"/*.profraw
sha256sum "$PROFDATA"
"$LLVM_PROFDATA" show --all-functions "$PROFDATA" | tail -12

fi

# ---------------------------------------------------------------------------
# d. PGO baseline build, with remarks and the missing-function warning on.
#
# Remark mechanism: -Cremark=all -Zremark-dir writes per-CGU YAML but loses
# every middle-end remark of the fat-LTO stage (the .lto.opt.yaml comes out
# empty), and LLVM 23 has no -pass-remarks-output cl::opt any more. The
# stderr remarks below are what actually reach us; the build log is the
# remark artifact.
# ---------------------------------------------------------------------------
banner "d. PGO baseline build (-Cprofile-use) + remarks"
BUILD_LOG="$LOG_DIR/pgo-baseline-build.log"
CARGO_PROFILE_RELEASE_DEBUG=1 \
CARGO_TARGET_DIR="$TD_USE" \
CARGO_ENCODED_RUSTFLAGS="$(enc '-Ctarget-cpu=native' '-Csymbol-mangling-version=v0' \
    "-Cprofile-use=$PROFDATA" \
    '-Cllvm-args=-pgo-warn-missing-function' \
    '-Cllvm-args=-pass-remarks=.*' \
    '-Cllvm-args=-pass-remarks-missed=.*' \
    '-Cllvm-args=-pass-remarks-analysis=.*')" \
  cargo build --manifest-path "$TOY/Cargo.toml" --release --target "$TRIPLE" >"$BUILD_LOG" 2>&1
tail -3 "$BUILD_LOG"
BIN_USE="$TD_USE/$TRIPLE/release/toy"

echo "--- remark lines total ---"
grep -c '^remark: ' "$BUILD_LOG" || true
echo "--- loop-vectorize remarks for the toyloops loops ---"
grep '^remark: .*toyloops/src/lib.rs' "$BUILD_LOG" | sort -u || true
echo "--- -Cprofile-use warnings: hash mismatch ---"
grep -c 'hash mismatch' "$BUILD_LOG" || true
echo "--- -Cprofile-use warnings: no profile data available for function ---"
grep -c 'no profile data available for function' "$BUILD_LOG" || true
echo "--- all warning: lines ---"
grep -c '^warning: ' "$BUILD_LOG" || true
grep '^warning: ' "$BUILD_LOG" | sed 's/^/    /' | sort | uniq -c | sort -rn | head -20 || true

# ---------------------------------------------------------------------------
# e. Correctness: PGO baseline must produce the plain build's checksums.
# ---------------------------------------------------------------------------
banner "e. checksum comparison (plain release vs PGO baseline)"
"$BIN_USE" all | tee "$LOG_DIR/checksums-pgo.txt"
if diff -u "$LOG_DIR/checksums-plain.txt" "$LOG_DIR/checksums-pgo.txt"; then
  echo "CHECKSUMS: MATCH"
else
  echo "CHECKSUMS: MISMATCH"
fi

# ---------------------------------------------------------------------------
# f. .text hash with debuginfo=1 vs debuginfo=0 (SPEC.ja.md 3).
# ---------------------------------------------------------------------------
banner "f. .text hash, debug=1 vs debug=0"
CARGO_PROFILE_RELEASE_DEBUG=0 \
CARGO_TARGET_DIR="$TD_USE_D0" \
CARGO_ENCODED_RUSTFLAGS="$(enc '-Ctarget-cpu=native' '-Csymbol-mangling-version=v0' \
    "-Cprofile-use=$PROFDATA" \
    '-Cllvm-args=-pgo-warn-missing-function' \
    '-Cllvm-args=-pass-remarks=.*' \
    '-Cllvm-args=-pass-remarks-missed=.*' \
    '-Cllvm-args=-pass-remarks-analysis=.*')" \
  cargo build --manifest-path "$TOY/Cargo.toml" --release --target "$TRIPLE" >"$LOG_DIR/pgo-baseline-debug0-build.log" 2>&1
BIN_USE_D0="$TD_USE_D0/$TRIPLE/release/toy"

H1=$(objcopy -O binary --only-section=.text "$BIN_USE" /dev/stdout | sha256sum | cut -d' ' -f1)
H0=$(objcopy -O binary --only-section=.text "$BIN_USE_D0" /dev/stdout | sha256sum | cut -d' ' -f1)
echo "debug=1 .text sha256: $H1"
echo "debug=0 .text sha256: $H0"
if [ "$H1" = "$H0" ]; then echo "TEXT HASH: MATCH"; else echo "TEXT HASH: DIFFER"; fi
"$BIN_USE_D0" all > "$LOG_DIR/checksums-pgo-debug0.txt"
diff -q "$LOG_DIR/checksums-pgo.txt" "$LOG_DIR/checksums-pgo-debug0.txt" \
  && echo "debug=0 checksums: MATCH" || echo "debug=0 checksums: MISMATCH"

# ---------------------------------------------------------------------------
# Disqualification filter (SPEC.ja.md 6.1-2). Trivially clean for the toy, but
# run it here so the same command is on record for zopfli and jaq.
# ---------------------------------------------------------------------------
banner "disqualification filter (hand-written SIMD)"
echo "\$ cargo tree -e normal | grep -iE 'memchr|simd|wide|std_detect'"
(cd "$TOY" && cargo tree -e normal | grep -iE 'memchr|simd|wide|std_detect') || echo "(no match)"
echo "\$ grep -rlE 'core::arch|_mm_|_mm256|target_feature' targets/toy/*/src"
(cd "$REPO" && grep -rlE 'core::arch|_mm_|_mm256|target_feature' targets/toy/*/src) || echo "(no match)"

banner "done"
