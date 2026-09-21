#!/usr/bin/env bash
#
# Deliverable 3 of the day-3 plugin work: which PassBuilder extension point
# rustc actually invokes, in which stage, for each of the four build shapes
# the project cares about, and how many loops already carry
# llvm.loop.isvectorized by then.
#
# SPEC.ja.md 8.2 picks VectorizerStart as its first candidate and says not to
# freeze it without measuring. This is that measurement.
#
# Arms (toy crate, otherwise the frozen flags of scripts/target_common.sh):
#   off      lto = off, no PGO
#   thin     lto = thin, no PGO
#   fat      lto = fat, no PGO
#   fatpgo   lto = fat + -Cprofile-use=pgo/toy/merged.profdata
#
# Stage. Under fat LTO rustc keeps the *same* module identifier and the same
# process for the merged module as for the primary CGU, so "which file" does
# not separate pre-link from merged. What does separate them is
# FullLinkTimeOptimizationEarly: everything a process logs after it belongs to
# the merged LTO module. For thin LTO the ThinOrFullLTOPhase argument the
# module EPs carry is authoritative and is used instead.
#
# Output: artifacts/plugin-day3/ep-<arm>/*.log  (raw probe records)
#         artifacts/plugin-day3/ep-<arm>.tsv    (the table for results.md)
#         artifacts/plugin-day3/build-<arm>.log
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN="$REPO/plugin/build/libjevprobe.so"
PROFDATA="$REPO/pgo/toy/merged.profdata"
OUTROOT="$REPO/artifacts/plugin-day3"
TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"

[ -f "$PLUGIN" ] || { echo "build the probe first: scripts/build_plugin.sh probe" >&2; exit 1; }

enc() { local out="$1"; shift; for a in "$@"; do out="$out$(printf '\x1f')$a"; done; printf '%s' "$out"; }

summarize() {  # summarize <report-dir> -> stdout
  python3 - "$1" <<'PY'
import sys, os, glob, collections

rows = collections.OrderedDict()
for path in sorted(glob.glob(os.path.join(sys.argv[1], "*.log"))):
    stage = "prelink"
    for line in open(path):
        f = dict(p.split("=", 1) for p in line.split() if "=" in p)
        ep = f.get("ep")
        if ep is None:
            continue
        # Everything this process logs from FullLinkTimeOptimizationEarly on
        # belongs to the merged fat-LTO module.
        if ep == "FullLinkTimeOptimizationEarly":
            stage = "lto"
        phase = f.get("phase", "-")
        st = stage
        if phase.startswith("ThinLTOPost"):
            st = "thin-postlink"
        elif phase.startswith("ThinLTOPre") or phase == "None":
            st = stage
        k = (ep, f.get("scope"), phase, st)
        r = rows.setdefault(k, {"n": 0, "mods": set(), "vec": []})
        r["n"] += 1
        r["mods"].add((f.get("module"), f.get("pid")))
        v = f.get("nisvec", f.get("isvec"))
        if v is not None:
            r["vec"].append(int(v))

print("ep\tscope\tphase_arg\tstage\tfires\tmodules\tisvec_min\tisvec_max")
for k in sorted(rows, key=lambda t: tuple(x or "" for x in t)):
    r = rows[k]
    v = r["vec"] or [0]
    print("\t".join([*(x or "-" for x in k), str(r["n"]), str(len(r["mods"])),
                     str(min(v)), str(max(v))]))
PY
}

run_arm() {
  local arm="$1" lto="$2" pgo="$3"
  local rd="$OUTROOT/ep-$arm"
  local td="$REPO/target-toy-probe-$arm"
  rm -rf "$rd" "$td"; mkdir -p "$rd"

  local flags=('-Ctarget-cpu=native' '-Csymbol-mangling-version=v0'
               '-Cllvm-args=-hints-allow-reordering=false'
               "-Zllvm-plugins=$PLUGIN")
  [ "$pgo" = yes ] && flags+=("-Cprofile-use=$PROFDATA" '-Cllvm-args=-pgo-warn-missing-function')

  echo "== arm $arm (lto=$lto pgo=$pgo)"
  # The build log goes beside the report directory, not into it: the
  # summariser globs *.log.
  JEV_REPORT_DIR="$rd" \
  CARGO_PROFILE_RELEASE_OPT_LEVEL=3 \
  CARGO_PROFILE_RELEASE_LTO="$lto" \
  CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
  CARGO_PROFILE_RELEASE_DEBUG=1 \
  CARGO_PROFILE_RELEASE_PANIC=unwind \
  CARGO_TARGET_DIR="$td" \
  CARGO_ENCODED_RUSTFLAGS="$(enc "${flags[@]}")" \
    cargo build --manifest-path "$REPO/targets/toy/Cargo.toml" --release \
      --target "$TRIPLE" > "$OUTROOT/build-$arm.log" 2>&1

  summarize "$rd" > "$OUTROOT/ep-$arm.tsv"
  cat "$OUTROOT/ep-$arm.tsv"
  echo
}

mkdir -p "$OUTROOT"
run_arm off    off  no
run_arm thin   thin no
run_arm fat    fat  no
run_arm fatpgo fat  yes
