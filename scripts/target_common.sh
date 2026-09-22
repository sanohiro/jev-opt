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
# One knob selects the target: TARGET=toy (default), zopfli or jaq. The
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
# TRAIN_WORKLOADS the same three cases on the *training* inputs, selected by
#                 BENCH_SET=training (SPEC.ja.md 7 wants the sweep on the
#                 training data and the holdout measured once, after
#                 freezing). Default BENCH_SET=holdout keeps toy and zopfli
#                 behaving exactly as results.md sections 24-26 recorded.
# TRAIN_INPUTS    the training cases. Used once, by the instrumented build, to
#                 produce merged.profdata (SPEC.ja.md 3). Disjoint from the
#                 holdout by construction.
# CORRECTNESS_IN  every input whose output is checksummed by run_correctness.
#
# FIXED_RUSTFLAGS  flags every build of this target carries, the baseline
#                 included (SPEC.ja.md 8 `[project] fixed_rustflags`). Empty
#                 for a target that has never needed one. build_variant adds
#                 them to its own fixed list, so they are deduplicated
#                 against a caller that passes the same flag as a knob.
FIXED_RUSTFLAGS=()

case "$TARGET" in
  toy)
    MANIFEST="${MANIFEST:-$REPO/targets/toy/Cargo.toml}"
    BIN_NAME="${BIN_NAME:-toy}"
    CARGO_EXTRA=()
    WORKLOADS=(quotes special sum dot)
    TRAIN_ARGS=(all)
    CORRECTNESS_IN=()
    ;;
  hintbench)
    # The hint benchmark (targets/hintbench, results.md "Hint benchmark
    # (design)"): one kernel per hint in the frozen vocabulary, each shaped so
    # that exactly one hint has a mechanism. Same two-crate rlib + bin shape as
    # the toy, and like the toy it declares no TRAIN_WORKLOADS: the kernels are
    # their own inputs, so there is no training/holdout split to make and
    # jev_search.py records the set it used as `holdout-as-search`.
    MANIFEST="${MANIFEST:-$REPO/targets/hintbench/Cargo.toml}"
    BIN_NAME="${BIN_NAME:-hintbench}"
    CARGO_EXTRA=()
    # Two pinned flags, on the baseline and on every arm alike.
    #
    #   -hints-allow-reordering=false  SPEC.ja.md 2 / decision 60 (a): without
    #       it a vectorize.width hint on a floating-point reduction also
    #       authorises reassociating it. There is no FP in this target, but the
    #       flag is part of the frozen recipe and build_variant drops an exact
    #       duplicate, so pinning it here costs nothing and keeps the target
    #       comparable with jaq.
    #
    #   -Zcross-crate-inline-threshold=never  rustc's own MIR inliner deletes a
    #       small cross-crate callee before LLVM ever sees it, and a function
    #       that is not in the IR has nothing for a function attribute to
    #       attach to: without this flag six of the eight kernels vanish and
    #       six of the eight marks resolve to no function (measured;
    #       results.md). It changes no LLVM decision --- LLVM still inlines
    #       whatever its cost model likes --- it only stops the *frontend* from
    #       pre-empting the decision under test.
    FIXED_RUSTFLAGS=('-Cllvm-args=-hints-allow-reordering=false'
                     '-Zcross-crate-inline-threshold=never')
    # One workload per kernel: the ground truth for kernel N is the ratio on
    # workload kN, not the eight-way geometric mean (a 10% win on one kernel is
    # 1.2% in the mean, under the minimum detectable effect of decision 16).
    WORKLOADS=(k1 k2 k3 k4 k5 k6 k7 k8)
    TRAIN_ARGS=(all)
    CORRECTNESS_IN=()
    # Core 4 (CPU 8, SMT sibling CPU 9 left idle). Cores 1, 2 and 3 belong to
    # toy/zopfli, jaq and oxipng, so a hintbench run never shares a physical
    # core with a measurement on another target.
    BENCH_CPU="${BENCH_CPU:-8}"
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
  jaq)
    # A cargo workspace: build the `jaq` bin package only.
    MANIFEST="${MANIFEST:-$REPO/targets/jaq/src/jaq/Cargo.toml}"
    # SPEC.ja.md 2 and decision 60 (a): pinned for every jaq arm, the
    # baseline included. `LoopVectorizeHints` cannot tell a
    # `vectorize.width` metadata hint from the command-line option, so
    # without this a width hint on an FP reduction also authorises
    # reordering the additions and the program's answer changes (results.md
    # "Day 3 (plugin)" 5c). Pinning it moves the baseline, so the baseline
    # was rebuilt with it and re-hashed: results.md "Sites (jaq)" 87.
    FIXED_RUSTFLAGS=('-Cllvm-args=-hints-allow-reordering=false')
    BIN_NAME="${BIN_NAME:-jaq}"
    CARGO_EXTRA=(--locked)
    # The workspace's own [profile.release] sets `strip = true`, which would
    # remove the symbol table and DWARF from every build and silently break
    # every analysis script here (nm finds nothing, addr2line answers `??`).
    # SPEC.ja.md 3 freezes strip as a build dimension and evaluates stripped
    # binaries separately, so override it the same way the other profile
    # values are overridden. Exported, so the plain and instrumented builds in
    # target_pgo_baseline.sh get it too.
    export CARGO_PROFILE_RELEASE_STRIP=none
    # CPU 2 is where the zopfli measurements ran; jaq uses core 2 (CPU 4, SMT
    # sibling CPU 5 left idle) so a concurrent run on another target cannot
    # contend for the same physical core. Recorded in results.md.
    BENCH_CPU="${BENCH_CPU:-4}"
    # jaq writes its whole result to stdout (tens of MB per case), so the
    # timed runs must discard it; correctness is run_correctness's sha256.
    BENCH_STDOUT="${BENCH_STDOUT:-devnull}"
    # jaq leaves a few hundred MiB of resident set behind at exit and the
    # next process pays for reclaiming it; a short settle gap between timed
    # runs cuts the within-binary spread from about 8% to about 1%
    # (results.md "Stage 0 (jaq)" section 55).
    BENCH_GAP_MS="${BENCH_GAP_MS:-250}"
    WLDIR="$REPO/targets/jaq/workloads"
    # The three article workloads, each paired with the input kind it fits
    # (targets/jaq/workloads/gen.py). `-c` on the read/write case keeps the
    # re-serialised output the same shape as the input.
    F_SEARCH='.[] | select(.k == "v") | .id'
    F_STRING='[.[] | .name | ascii_downcase | length] | add'
    F_RW='.'
    # Each case names its input file several times: `jaq FILTER f f f f`
    # parses and filters each file in turn. This is how the cases reach a
    # second of work without giving jaq a single array so large that the
    # resident set turns the wall time bimodal (targets/jaq/workloads/gen.py
    # REPEATS, results.md "Stage 0 (jaq)" section 55). The repeat counts are
    # part of the frozen case set: objects x4, strings x8, ndjson x2.
    _jaq_rep() { local n="$1" f="$2" i; for ((i=0;i<n;i++)); do printf ' %s' "$f"; done; }
    # bench.py shlex-splits everything after the first `=`, so the filter is
    # wrapped in single quotes (no filter contains one).
    WORKLOADS=("objsearch='$F_SEARCH'$(_jaq_rep 4 "$WLDIR/hold-objects.json")"
               "strproc='$F_STRING'$(_jaq_rep 8 "$WLDIR/hold-strings.json")"
               "readwrite=-c '$F_RW'$(_jaq_rep 2 "$WLDIR/hold-ndjson.json")")
    TRAIN_WORKLOADS=("objsearch='$F_SEARCH'$(_jaq_rep 4 "$WLDIR/train-objects.json")"
                     "strproc='$F_STRING'$(_jaq_rep 8 "$WLDIR/train-strings.json")"
                     "readwrite=-c '$F_RW'$(_jaq_rep 2 "$WLDIR/train-ndjson.json")")
    # Training runs for the instrumented build: the same three cases, argv for
    # argv, on the training inputs (SPEC.ja.md 3). One entry per run, tab
    # separated.
    _jaq_treps() { local n="$1" f="$2" i; for ((i=0;i<n;i++)); do printf '\t%s' "$f"; done; }
    TRAIN_ARGS=("$F_SEARCH$(_jaq_treps 4 "$WLDIR/train-objects.json")"
                "$F_STRING$(_jaq_treps 8 "$WLDIR/train-strings.json")"
                "-c"$'\t'"$F_RW$(_jaq_treps 2 "$WLDIR/train-ndjson.json")")
    # Correctness: the sha256 of stdout for every case, training and holdout.
    CORRECTNESS_IN=("${TRAIN_ARGS[@]}"
                    "$F_SEARCH$(_jaq_treps 4 "$WLDIR/hold-objects.json")"
                    "$F_STRING$(_jaq_treps 8 "$WLDIR/hold-strings.json")"
                    "-c"$'\t'"$F_RW$(_jaq_treps 2 "$WLDIR/hold-ndjson.json")")
    ;;
  oxipng)
    MANIFEST="${MANIFEST:-$REPO/targets/oxipng/src/Cargo.toml}"
    BIN_NAME="${BIN_NAME:-oxipng}"
    # Features (results.md "Stage 0 (oxipng)" section 40 explains each):
    #   binary    the CLI itself (clap + env_logger); [[bin]] requires it.
    #   filetime  kept from the default set; inert without --preserve.
    #   parallel  DROPPED. oxipng ships its own single-threaded shim in
    #             src/rayon.rs for exactly this build, so dropping rayon makes
    #             the binary single-threaded by construction. Note that
    #             `--threads` only exists when `parallel` is on, so there is no
    #             flag to pass here.
    #   zopfli    DROPPED. It is the pure-Rust zopfli crate, not a C library,
    #             and it is dead code at -o 2 (only --zopfli selects it); it
    #             would add its loops to the remark landscape for nothing.
    # libdeflater is NOT optional in 9.1.5, so the C deflate core cannot be
    # switched off by any feature combination (section 32).
    CARGO_EXTRA=(--locked --no-default-features --features binary,filetime)
    # oxipng's own [profile.release] sets `strip = "symbols"`, which would
    # delete the symbol table and DWARF from every build and break every
    # analysis script here. SPEC.ja.md 3 freezes strip and evaluates stripped
    # copies separately, so override it like the other profile values.
    # Exported, so the plain and instrumented builds get it too.
    export CARGO_PROFILE_RELEASE_STRIP=none
    # Core 3 (CPU 6, SMT sibling CPU 7 left idle): core 1 (CPU 2) belongs to
    # toy/zopfli and core 2 (CPU 4) to jaq, so three targets can be measured
    # without ever sharing a physical core. Recorded in results.md.
    BENCH_CPU="${BENCH_CPU:-6}"
    WLDIR="$REPO/targets/oxipng/workloads"
    # `--out /dev/null` keeps the 3-6 MiB of output off the filesystem: the
    # timed quantity is the optimisation, not the write, and every arm does
    # the same thing. run_correctness below writes a real file and hashes it.
    WORKLOADS=("photo=-o 2 --out /dev/null $WLDIR/hold-photo.png"
               "alpha=-o 2 --out /dev/null $WLDIR/hold-alpha.png"
               "palette=-o 2 --out /dev/null $WLDIR/hold-palette.png")
    TRAIN_WORKLOADS=("photo=-o 2 --out /dev/null $WLDIR/train-photo.png"
                     "alpha=-o 2 --out /dev/null $WLDIR/train-alpha.png"
                     "palette=-o 2 --out /dev/null $WLDIR/train-palette.png")
    TRAIN_ARGS=("$WLDIR/train-photo.png" "$WLDIR/train-alpha.png"
                "$WLDIR/train-palette.png")
    CORRECTNESS_IN=("$WLDIR/train-photo.png" "$WLDIR/train-alpha.png"
                    "$WLDIR/train-palette.png" "$WLDIR/hold-photo.png"
                    "$WLDIR/hold-alpha.png" "$WLDIR/hold-palette.png")
    ;;
  *)
    echo "target_common.sh: unknown TARGET=$TARGET" >&2
    return 1 2>/dev/null || exit 1
    ;;
esac

# BENCH_SET selects which of the two case sets bench.py measures.
#   holdout   (default) the WORKLOADS above --- A/A and the final holdout.
#   training  the same filters on the training inputs --- what SPEC.ja.md 7
#             says the headroom sweep should use.
# Only defined for targets that declare TRAIN_WORKLOADS.
case "${BENCH_SET:-holdout}" in
  holdout) ;;
  training)
    if [ -z "${TRAIN_WORKLOADS+x}" ]; then
      echo "target_common.sh: TARGET=$TARGET has no TRAIN_WORKLOADS" >&2
      return 1 2>/dev/null || exit 1
    fi
    WORKLOADS=("${TRAIN_WORKLOADS[@]}")
    ;;
  *)
    echo "target_common.sh: unknown BENCH_SET=$BENCH_SET" >&2
    return 1 2>/dev/null || exit 1
    ;;
esac

# Root the SPEC.ja.md 6.1-2 source grep walks. The manifest's own directory
# for a single-crate target; for a workspace (jaq) the manifest is one member,
# so the grep has to start one level up or it sees only the bin crate.
FILTER_SRC_ROOT="${FILTER_SRC_ROOT:-$(dirname "$MANIFEST")}"
if [ "$TARGET" = jaq ]; then FILTER_SRC_ROOT="$REPO/targets/jaq/src"; fi

PGO_DIR="$REPO/pgo/$TARGET"
PROFDATA="${PROFDATA:-$PGO_DIR/merged.profdata}"
REMARK_DIR="$REPO/remarks/$TARGET"

# Physical core to pin measurements to (SPEC.ja.md 10). See results.md: WSL2
# reports a single L3 instance for all 32 CPUs, so the CCD boundary of the
# 5950X is not visible from inside the guest. CPU 2 is core 1; its SMT sibling
# CPU 3 is left unused.
BENCH_CPU="${BENCH_CPU:-2}"

# What bench.py does with each timed run's stdout (see bench.py --stdout).
# `pipe` keeps the toy's and zopfli's free cross-label output check.
BENCH_STDOUT="${BENCH_STDOUT:-pipe}"

# Idle time between timed runs, outside the timed window (bench.py --gap-ms).
# 0 is what the toy and zopfli measurements used.
BENCH_GAP_MS="${BENCH_GAP_MS:-0}"

# CARGO_ENCODED_RUSTFLAGS is \x1f-separated.
enc() { local out="$1"; shift; for a in "$@"; do out="$out$(printf '\x1f')$a"; done; printf '%s' "$out"; }

# build_variant <target-dir> <build-log> [extra knobs...]
#
# A knob is an LLVM cl::opt by default and is wrapped in -Cllvm-args=. A knob
# that already starts with `-C` is a rustc codegen option and is passed
# through untouched, which is what SPEC.ja.md 6.3 group 4 needs
# (-Ctarget-feature, -Ctarget-cpu); rustc takes the last occurrence of a
# repeated -Ctarget-cpu, so a group-4 value overrides the baseline's =native.
# `-Z` is passed through the same way, for -Zllvm-plugins (SPEC.ja.md 3).
#
# An extra knob that is already among the fixed flags, or that a caller passes
# twice, is dropped: an LLVM cl::opt is `cl::Optional`, so giving -Cllvm-args
# the same option twice aborts rustc with "may only occur zero or one times".
# That matters for -Cllvm-args=-hints-allow-reordering=false, which
# SPEC.ja.md 2 pins for every arm and which more than one caller may add.
# Exact string equality only, so nothing that is not literally a duplicate is
# affected.
#
# Clean build every time: cargo does not rebuild on an environment-variable
# change alone (SPEC.ja.md 4). Returns non-zero if the build fails; the caller
# decides whether that is fatal (a knob that cannot build is a result).
build_variant() {
  local td="$1" log="$2"; shift 2
  local fixed=('-Ctarget-cpu=native' '-Csymbol-mangling-version=v0'
               "-Cprofile-use=$PROFDATA"
               '-Cllvm-args=-pgo-warn-missing-function'
               '-Cllvm-args=-pass-remarks=.*'
               '-Cllvm-args=-pass-remarks-missed=.*'
               '-Cllvm-args=-pass-remarks-analysis=.*')
  fixed+=(${FIXED_RUSTFLAGS[@]+"${FIXED_RUSTFLAGS[@]}"})
  local extra=()
  local a f x dup
  for a in "$@"; do
    case "$a" in
      -C*|-Z*) f="$a" ;;
      *)       f="-Cllvm-args=$a" ;;
    esac
    dup=0
    for x in "${fixed[@]}" ${extra+"${extra[@]}"}; do
      [ "$x" = "$f" ] && { dup=1; break; }
    done
    [ "$dup" = 1 ] || extra+=("$f")
  done
  rm -rf "$td"
  CARGO_PROFILE_RELEASE_OPT_LEVEL=3 \
  CARGO_PROFILE_RELEASE_LTO=fat \
  CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
  CARGO_PROFILE_RELEASE_DEBUG=1 \
  CARGO_PROFILE_RELEASE_PANIC=unwind \
  CARGO_TARGET_DIR="$td" \
  CARGO_ENCODED_RUSTFLAGS="$(enc "${fixed[@]}" ${extra+"${extra[@]}"})" \
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
#  toy     prints a checksum block on stdout. hintbench does the same.
#  zopfli  writes <input>.gz beside its input and prints nothing, so each run
#          gets its own scratch copy of the input and the .gz is hashed. The
#          scratch copy also keeps concurrent correctness runs from colliding
#          and keeps the timed runs' output files out of the way.
run_correctness() {
  local bin="$1" out="$2"
  case "$TARGET" in
    toy|hintbench)
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
    jaq)
      # jaq writes its result to stdout, so correctness is the sha256 of
      # stdout for every case. The timed runs send stdout to /dev/null
      # (bench.py --stdout devnull), which is exactly SPEC.ja.md 10's
      # "discard stdout the same way in both variants and keep the
      # correctness check separate from the timing".
      #
      # CORRECTNESS_IN holds one tab-separated argv per case.
      : > "$out"
      local spec argv name
      for spec in "${CORRECTNESS_IN[@]}"; do
        IFS=$'\t' read -r -a argv <<< "$spec"
        name="$(basename "${argv[-1]}")"
        # sha256sum always succeeds, so propagate jaq's own status out of the
        # pipeline explicitly rather than relying on the caller's pipefail.
        local h rc=0
        h="$("$bin" "${argv[@]}" 2>/dev/null | sha256sum | cut -d' ' -f1
             exit "${PIPESTATUS[0]}")" || rc=$?
        if [ "$rc" = 0 ]; then
          printf '%s %s\n' "$name" "$h" >> "$out"
        else
          printf '%s RUN-FAILED\n' "$name" >> "$out"
        fi
      done
      ;;
    oxipng)
      # oxipng writes the optimised PNG to --out and prints only progress on
      # stderr, so correctness is the sha256 of the produced file. The input
      # is copied to a scratch directory first, so the workload directory
      # stays clean and two correctness runs cannot collide.
      #
      # The missing-file case matters here: oxipng does NOT write an output
      # file when it finds no improvement, and a silent "no file" would make
      # every configuration agree on nothing. It is recorded as NO-OUTPUT so
      # the checksum comparison fails loudly.
      local scratch; scratch="$(mktemp -d)"
      : > "$out"
      local f base
      for f in "${CORRECTNESS_IN[@]}"; do
        base="$(basename "$f")"
        cp "$f" "$scratch/in.png"
        rm -f "$scratch/out.png"
        if "$bin" -o 2 --out "$scratch/out.png" "$scratch/in.png" \
             >/dev/null 2>&1 && [ -f "$scratch/out.png" ]; then
          printf '%s %s\n' "$base" \
            "$(sha256sum "$scratch/out.png" | cut -d' ' -f1)" >> "$out"
        elif [ ! -f "$scratch/out.png" ]; then
          printf '%s NO-OUTPUT\n' "$base" >> "$out"
        else
          printf '%s RUN-FAILED\n' "$base" >> "$out"
        fi
      done
      rm -f "$scratch/in.png" "$scratch/out.png"
      rmdir "$scratch"
      ;;
    *)
      # Reachable if a caller did `TARGET=x source target_common.sh`: bash
      # restores the temporary assignment when the builtin returns, so TARGET
      # is empty again by the time this runs. Use `export TARGET=x` instead.
      echo "run_correctness: no procedure for TARGET='$TARGET'" >&2
      return 1
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
