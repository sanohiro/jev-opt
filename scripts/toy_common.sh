#!/usr/bin/env bash
#
# Shared build helper for the day-0 toy scripts (A/A and headroom sweep).
# Sourced, not executed.
#
# Everything here is the PGO baseline recipe of SPEC.ja.md 3: the same
# merged.profdata, the same debuginfo, the same panic strategy and the same
# remark flags for every configuration. The only thing a caller varies is the
# list of extra -Cllvm-args knobs.
#
# Parameterised by TARGET so zopfli can reuse it for the paths; the cargo
# manifest is still the toy's (a zopfli script overrides MANIFEST/BIN_NAME).

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${TARGET:-toy}"
MANIFEST="${MANIFEST:-$REPO/targets/toy/Cargo.toml}"
BIN_NAME="${BIN_NAME:-toy}"
PGO_DIR="$REPO/pgo/$TARGET"
PROFDATA="${PROFDATA:-$PGO_DIR/merged.profdata}"
REMARK_DIR="$REPO/remarks/$TARGET"
TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"

# Physical core to pin measurements to (SPEC.ja.md 10). See results.md: WSL2
# reports a single L3 instance for all 32 CPUs, so the CCD boundary of the
# 5950X is not visible from inside the guest. CPU 2 is core 1; its SMT sibling
# CPU 3 is left unused.
BENCH_CPU="${BENCH_CPU:-2}"

WORKLOADS=(quotes special sum dot)

# CARGO_ENCODED_RUSTFLAGS is \x1f-separated.
enc() { local out="$1"; shift; for a in "$@"; do out="$out$(printf '\x1f')$a"; done; printf '%s' "$out"; }

# build_variant <target-dir> <build-log> [extra -Cllvm-args values...]
#
# Clean build every time: cargo does not rebuild on an environment-variable
# change alone (SPEC.ja.md 4). Returns non-zero if the build fails; the caller
# decides whether that is fatal (a knob that cannot build is a result).
build_variant() {
  local td="$1" log="$2"; shift 2
  local extra=()
  local a
  for a in "$@"; do extra+=("-Cllvm-args=$a"); done
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
      >"$log" 2>&1
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

text_hash() {
  objcopy -O binary --only-section=.text "$1" /dev/stdout | sha256sum | cut -d' ' -f1
}
