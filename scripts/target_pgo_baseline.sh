#!/usr/bin/env bash
#
# Day 0: hand-run the PGO baseline end to end (SPEC.ja.md 3, 13-day-0).
#
# This is the manual version of what `jev-opt baseline` will later do:
#   plain release build -> instrumented build -> training run -> llvm-profdata
#   merge -> PGO baseline build (with remarks) -> checksum and .text checks.
#
# Nothing here is a conclusion; every step prints the command's raw output so
# results.md can quote it.
#
# Usage: TARGET=zopfli scripts/target_pgo_baseline.sh
#
# Environment:
#   TARGET=toy          which target (see scripts/target_common.sh).
#   REUSE_PROFDATA=1    keep an existing pgo/<target>/merged.profdata and skip
#                       the instrumented build and the training run. The
#                       training run happens once per target (SPEC.ja.md 3);
#                       re-running it is only allowed because the profdata was
#                       shown to be byte-reproducible.
#   REPRO=0             set to 1 to repeat the training run into a second
#                       directory and compare the merged profdata byte for
#                       byte (SPEC.ja.md 3's reproducibility requirement).
#   DEBUG0=1            also build with debuginfo=0 and compare .text.
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/target_common.sh"

PROFRAW_DIR="$PGO_DIR/profraw"
LOG_DIR="$REPO/artifacts/$TARGET-day0"
REUSE_PROFDATA="${REUSE_PROFDATA:-1}"
REPRO="${REPRO:-0}"
DEBUG0="${DEBUG0:-1}"

SYSROOT="$(rustc --print sysroot)"
LLVM_PROFDATA="$SYSROOT/lib/rustlib/$TRIPLE/bin/llvm-profdata"

# Every variant gets its own CARGO_TARGET_DIR and is built from scratch: cargo
# does not rebuild on an environment-variable change alone (SPEC.ja.md 4).
TD_PLAIN="$REPO/target-$TARGET-plain"
TD_GEN="$REPO/target-$TARGET-pgo-gen"
TD_USE="$REPO/target-$TARGET-pgo-use"
TD_USE_D0="$REPO/target-$TARGET-pgo-use-debug0"

# Fixed cargo release-profile values, identical to build_variant's. They are
# repeated here so the variants that must differ (debug, profile-generate)
# differ in exactly one place.
export CARGO_PROFILE_RELEASE_OPT_LEVEL=3
export CARGO_PROFILE_RELEASE_LTO=fat
export CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1
export CARGO_PROFILE_RELEASE_PANIC=unwind

banner() { printf '\n========== %s ==========\n' "$*"; }

# run_training <binary> --- the training workload, once (SPEC.ja.md 3).
# Runs in a scratch directory so a target that writes its output beside its
# input (zopfli) does not litter the workload directory.
run_training() {
  local bin="$1" scratch base f
  case "$TARGET" in
    toy|hintbench)
      "$bin" "${TRAIN_ARGS[@]}"
      ;;
    zopfli)
      scratch="$(mktemp -d)"
      for f in "${TRAIN_ARGS[@]}"; do
        base="$(basename "$f")"
        cp "$f" "$scratch/$base"
        "$bin" "$scratch/$base"
        echo "  trained on $base -> $(stat -c%s "$scratch/$base.gz") bytes"
        rm -f "$scratch/$base" "$scratch/$base.gz"
      done
      rmdir "$scratch"
      ;;
    jaq)
      # One run per case; TRAIN_ARGS holds a tab-separated argv each.
      local spec argv
      for spec in "${TRAIN_ARGS[@]}"; do
        IFS=$'\t' read -r -a argv <<< "$spec"
        "$bin" "${argv[@]}" > /dev/null
        echo "  trained on $(basename "${argv[-1]}")"
      done
      ;;
    oxipng)
      scratch="$(mktemp -d)"
      for f in "${TRAIN_ARGS[@]}"; do
        base="$(basename "$f")"
        cp "$f" "$scratch/in.png"
        rm -f "$scratch/out.png"
        "$bin" -o 2 --out "$scratch/out.png" "$scratch/in.png" >/dev/null 2>&1
        echo "  trained on $base -> $(stat -c%s "$scratch/out.png") bytes"
      done
      rm -f "$scratch/in.png" "$scratch/out.png"
      rmdir "$scratch"
      ;;
  esac
}

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
echo "target:         $TARGET"
echo "manifest:       $MANIFEST"
echo "bin:            $BIN_NAME"
echo "cargo extra:    ${CARGO_EXTRA[*]:-(none)}"
echo "host triple:    $TRIPLE"
echo "sysroot:        $SYSROOT"
echo "llvm-profdata:  $LLVM_PROFDATA"
"$LLVM_PROFDATA" --version

# ---------------------------------------------------------------------------
# Disqualification filter (SPEC.ja.md 6.1-2). Run before anything is built:
# a target that fails it is not worth a profdata.
# ---------------------------------------------------------------------------
banner "disqualification filter (hand-written SIMD)"
SRC_DIR="$(dirname "$MANIFEST")"
echo "\$ cargo tree -e normal | grep -iE 'memchr|simd|wide|std_detect'"
(cd "$SRC_DIR" && cargo tree -e normal "${CARGO_EXTRA[@]}" \
  | grep -iE 'memchr|simd|wide|std_detect') || echo "(no match)"
echo "\$ grep -rlE 'core::arch|_mm_|_mm256|target_feature' $FILTER_SRC_ROOT/src $FILTER_SRC_ROOT/*/src"
(grep -rlE 'core::arch|_mm_|_mm256|target_feature' "$FILTER_SRC_ROOT"/src \
  "$FILTER_SRC_ROOT"/*/src 2>/dev/null) || echo "(no match)"
# Third check, added for oxipng (results.md "Stage 0 (oxipng)" section 42).
# SPEC.ja.md 6.1-2's two greps are blind to a dependency that compiles C: the
# crate name need not contain "simd", and the C sources live in the cargo
# registry, not under the target's src/. Such code is invisible to
# -Cllvm-args, to -Ctarget-cpu and to -Cprofile-generate at the same time, so
# it is the strongest possible form of "out of reach".
# `-e build` alone lists only the root package's own build-dependencies and
# does not descend, so it reports nothing for a C dependency two levels down.
# `-e normal,build` is what actually finds it.
echo "\$ cargo tree -e normal,build | grep -iE 'cc v|-sys v|cmake v|bindgen v'"
(cd "$SRC_DIR" && cargo tree -e normal,build "${CARGO_EXTRA[@]}" \
  | grep -iE 'cc v|-sys v|cmake v|bindgen v' | sed 's/^[^a-zA-Z]*//' | sort -u) \
  || echo "(no match)"

# ---------------------------------------------------------------------------
# 0. Plain (non-PGO) release build. Reference checksums come from this one.
#    Same opt-level / lto / codegen-units / debug / native as the baseline;
#    the only differences are -Cprofile-use and the remark flags.
# ---------------------------------------------------------------------------
banner "0. plain release build (no PGO, no remarks)"
CARGO_PROFILE_RELEASE_DEBUG=1 \
CARGO_TARGET_DIR="$TD_PLAIN" \
CARGO_ENCODED_RUSTFLAGS="$(enc '-Ctarget-cpu=native' '-Csymbol-mangling-version=v0')" \
  cargo build --manifest-path "$MANIFEST" --release --target "$TRIPLE" \
    "${CARGO_EXTRA[@]}" 2>&1 | tail -3
BIN_PLAIN="$TD_PLAIN/$TRIPLE/release/$BIN_NAME"
run_correctness "$BIN_PLAIN" "$LOG_DIR/checksums-plain.txt"
cat "$LOG_DIR/checksums-plain.txt"

banner "0b. output determinism (same binary, same inputs, twice)"
run_correctness "$BIN_PLAIN" "$LOG_DIR/checksums-plain-2.txt"
if diff -q "$LOG_DIR/checksums-plain.txt" "$LOG_DIR/checksums-plain-2.txt" >/dev/null; then
  echo "OUTPUT DETERMINISM: MATCH"
else
  echo "OUTPUT DETERMINISM: MISMATCH"
  diff -u "$LOG_DIR/checksums-plain.txt" "$LOG_DIR/checksums-plain-2.txt" || true
fi

# ---------------------------------------------------------------------------
# a-c. Instrumented build, training run, merge. No remarks, no plugin
#      (SPEC.ja.md 3).
# ---------------------------------------------------------------------------
# The target's FIXED_RUSTFLAGS have to be here as well as in build_variant.
# `-Cprofile-use` matches a profile record to a function by a hash of the MIR
# the frontend produced, so any flag that changes what the frontend emits must
# be identical in the instrumented build and in the build that reads the
# profile. On hintbench, whose fixed flags include
# -Zcross-crate-inline-threshold=never, leaving them off here discarded the
# whole of `main`'s profile with "function control flow change detected (hash
# mismatch)" and left five of the eight kernels with no profile data at all
# (measured, results.md "Hint benchmark (design)"). For the targets whose fixed
# flags are only -Cllvm-args this changes nothing: the counters are inserted
# before any middle-end pass runs.
build_instrumented() {   # build_instrumented <target-dir> <profraw-dir>
  CARGO_PROFILE_RELEASE_DEBUG=1 \
  CARGO_TARGET_DIR="$1" \
  CARGO_ENCODED_RUSTFLAGS="$(enc '-Ctarget-cpu=native' '-Csymbol-mangling-version=v0' \
      "-Cprofile-generate=$2" ${FIXED_RUSTFLAGS[@]+"${FIXED_RUSTFLAGS[@]}"})" \
    cargo build --manifest-path "$MANIFEST" --release --target "$TRIPLE" \
      "${CARGO_EXTRA[@]}" 2>&1 | tail -3
}

if [ "$REUSE" = 1 ]; then
banner "a-c. reusing existing profdata (no instrumented build, no training run)"
echo "profdata: $PROFDATA"
sha256sum "$PROFDATA"
else
banner "a. instrumented build (-Cprofile-generate)"
build_instrumented "$TD_GEN" "$PROFRAW_DIR"
BIN_GEN="$TD_GEN/$TRIPLE/release/$BIN_NAME"

banner "b. training run (instrumented)"
GEN_START=$(date +%s%N)
run_training "$BIN_GEN"
GEN_END=$(date +%s%N)
echo "training run wall time: $(( (GEN_END - GEN_START) / 1000000 )) ms"
ls -la "$PROFRAW_DIR"

banner "c. llvm-profdata merge"
echo "\$ $LLVM_PROFDATA merge -o $PROFDATA $PROFRAW_DIR/*.profraw"
"$LLVM_PROFDATA" merge -o "$PROFDATA" "$PROFRAW_DIR"/*.profraw
sha256sum "$PROFDATA"
fi

"$LLVM_PROFDATA" show "$PROFDATA" | head -20
"$LLVM_PROFDATA" show --all-functions --counts "$PROFDATA" \
  > "$LOG_DIR/profdata-functions.txt"
echo "profdata function records: $(grep -c '^  Hash: ' "$LOG_DIR/profdata-functions.txt" || true)"
echo "(full listing: $LOG_DIR/profdata-functions.txt)"

if [ "$REPRO" = 1 ]; then
banner "c2. profdata reproducibility (second training run, separate directory)"
PROFRAW2="$PGO_DIR/profraw-repro"
PROFDATA2="$PGO_DIR/merged-repro.profdata"
rm -rf "$PROFRAW2"; mkdir -p "$PROFRAW2"
build_instrumented "$REPO/target-$TARGET-pgo-gen2" "$PROFRAW2"
run_training "$REPO/target-$TARGET-pgo-gen2/$TRIPLE/release/$BIN_NAME"
"$LLVM_PROFDATA" merge -o "$PROFDATA2" "$PROFRAW2"/*.profraw
sha256sum "$PROFDATA" "$PROFDATA2"
if cmp -s "$PROFDATA" "$PROFDATA2"; then
  echo "PROFDATA REPRODUCIBLE: byte-identical"
else
  echo "PROFDATA REPRODUCIBLE: NO --- the two merges differ"
fi
rm -rf "$REPO/target-$TARGET-pgo-gen2"
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
BUILD_LOG="$REMARK_DIR/baseline-build.log"
build_variant "$TD_USE" "$BUILD_LOG"
tail -3 "$BUILD_LOG"
BIN_USE="$TD_USE/$TRIPLE/release/$BIN_NAME"
cp "$BUILD_LOG" "$LOG_DIR/pgo-baseline-build.log"

echo "--- remark lines total ---"
grep -c '^remark: ' "$BUILD_LOG" || true
echo "--- -Cprofile-use warnings: hash mismatch ---"
grep -c 'hash mismatch' "$BUILD_LOG" || true
echo "--- -Cprofile-use warnings: no profile data available for function ---"
grep -c 'no profile data available for function' "$BUILD_LOG" || true
echo "--- all warning: lines ---"
grep -c '^warning: ' "$BUILD_LOG" || true
grep '^warning: ' "$BUILD_LOG" | sed 's/^/    /' | sort | uniq -c | sort -rn | head -20 || true
echo "--- .text sha256 ---"
text_hash "$BIN_USE"

# ---------------------------------------------------------------------------
# e. Correctness: PGO baseline must produce the plain build's output.
# ---------------------------------------------------------------------------
banner "e. checksum comparison (plain release vs PGO baseline)"
run_correctness "$BIN_USE" "$LOG_DIR/checksums-pgo.txt"
cat "$LOG_DIR/checksums-pgo.txt"
if diff -u "$LOG_DIR/checksums-plain.txt" "$LOG_DIR/checksums-pgo.txt"; then
  echo "CHECKSUMS: MATCH"
else
  echo "CHECKSUMS: MISMATCH"
fi

# ---------------------------------------------------------------------------
# f. .text hash with debuginfo=1 vs debuginfo=0 (SPEC.ja.md 3).
# ---------------------------------------------------------------------------
if [ "$DEBUG0" = 1 ]; then
banner "f. .text hash, debug=1 vs debug=0"
CARGO_PROFILE_RELEASE_DEBUG=0 \
CARGO_TARGET_DIR="$TD_USE_D0" \
CARGO_ENCODED_RUSTFLAGS="$(enc '-Ctarget-cpu=native' '-Csymbol-mangling-version=v0' \
    "-Cprofile-use=$PROFDATA" \
    '-Cllvm-args=-pgo-warn-missing-function' \
    '-Cllvm-args=-pass-remarks=.*' \
    '-Cllvm-args=-pass-remarks-missed=.*' \
    '-Cllvm-args=-pass-remarks-analysis=.*')" \
  cargo build --manifest-path "$MANIFEST" --release --target "$TRIPLE" \
    "${CARGO_EXTRA[@]}" >"$LOG_DIR/pgo-baseline-debug0-build.log" 2>&1
BIN_USE_D0="$TD_USE_D0/$TRIPLE/release/$BIN_NAME"

H1=$(text_hash "$BIN_USE")
H0=$(text_hash "$BIN_USE_D0")
echo "debug=1 .text sha256: $H1"
echo "debug=0 .text sha256: $H0"
if [ "$H1" = "$H0" ]; then echo "TEXT HASH: MATCH"; else echo "TEXT HASH: DIFFER"; fi
run_correctness "$BIN_USE_D0" "$LOG_DIR/checksums-pgo-debug0.txt"
diff -q "$LOG_DIR/checksums-pgo.txt" "$LOG_DIR/checksums-pgo-debug0.txt" \
  && echo "debug=0 checksums: MATCH" || echo "debug=0 checksums: MISMATCH"
fi

# ---------------------------------------------------------------------------
# g. Reference arm R (SPEC.ja.md 9): the target's own release profile, with no
#    override at all. Only the effective profile values are recorded here; the
#    arm itself is measured in Stage 1.
# ---------------------------------------------------------------------------
banner "g. reference arm R: the target's own [profile.release]"
sed -n '/^\[profile\.release\]/,/^\[/p' "$MANIFEST" | sed 's/^/    /' \
  || echo "    (the manifest sets no [profile.release])"

banner "done"
