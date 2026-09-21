#!/usr/bin/env bash
#
# Day-3 plugin acceptance tests on the toy (results.md "Day 3 (plugin)").
#
#   5a  off-equivalence: unloaded vs JEV_MODE=off vs apply with an empty plan
#   5b  dump with all four toyloops functions marked
#   5c  loop metadata: vectorize.width on count_quotes, unroll.count on
#       sum_indexed, and the -hints-allow-reordering=false question on dot_f64
#   5d  function attributes: inline(never)+align on count_quotes, cold on
#       find_special
#   5e  fat+PGO: do the dump keys resolve in apply, and are unmatched marks
#       reported
#   5f  key stability: does changing a function attribute move the loop keys
#       of the *other* marked functions
#
# Usage: scripts/plugin_toy_tests.sh [5a|5b|5c|5d|5e|5f|all]
#
# Every build uses the frozen toy recipe of scripts/target_common.sh
# (opt-level 3, fat LTO, codegen-units 1, debug 1, panic unwind,
# -Ctarget-cpu=native, -Csymbol-mangling-version=v0, -Cprofile-use from
# pgo/toy/merged.profdata) plus -Cllvm-args=-hints-allow-reordering=false,
# which day 3 pins for every arm (SPEC.ja.md 8.1, decision 40).
#
# No timing is done here. Correctness is the toy's own checksum block and the
# normalised code hash.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO/artifacts/plugin-day3"
PLUGIN="$REPO/plugin/build/libjevplugin.so"
PROFDATA="$REPO/pgo/toy/merged.profdata"
MARKS_ALL="$OUT/marks/toy-all.txt"
TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
mkdir -p "$OUT"

enc() { local o="$1"; shift; for a in "$@"; do o="$o$(printf '\x1f')$a"; done; printf '%s' "$o"; }

# build_toy <tag> [extra rustflags...]
#
# Environment the caller may set: JEV_MODE, JEV_PLAN, JEV_PLAN_SHA,
# JEV_MARKS, JEV_REPORT_DIR, NO_PLUGIN=1, NO_REORDER_FLAG=0.
# Leaves the binary at $OUT/bin-<tag> and the build log at $OUT/build-<tag>.log.
build_toy() {
  local tag="$1"; shift
  local td="$REPO/target-toy-jev-$tag"
  local flags=('-Ctarget-cpu=native' '-Csymbol-mangling-version=v0'
               "-Cprofile-use=$PROFDATA"
               '-Cllvm-args=-pgo-warn-missing-function'
               '-Cllvm-args=-pass-remarks=.*'
               '-Cllvm-args=-pass-remarks-missed=.*'
               '-Cllvm-args=-pass-remarks-analysis=.*')
  [ "${NO_REORDER_FLAG:-0}" = 1 ] || flags+=('-Cllvm-args=-hints-allow-reordering=false')
  [ "${NO_PLUGIN:-0}" = 1 ] || flags+=("-Zllvm-plugins=$PLUGIN")
  flags+=("$@")

  rm -rf "$td"
  CARGO_PROFILE_RELEASE_OPT_LEVEL=3 \
  CARGO_PROFILE_RELEASE_LTO="${LTO:-fat}" \
  CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
  CARGO_PROFILE_RELEASE_DEBUG=1 \
  CARGO_PROFILE_RELEASE_PANIC=unwind \
  CARGO_TARGET_DIR="$td" \
  CARGO_ENCODED_RUSTFLAGS="$(enc "${flags[@]}")" \
    cargo build --manifest-path "$REPO/targets/toy/Cargo.toml" --release \
      --target "$TRIPLE" > "$OUT/build-$tag.log" 2>&1
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "BUILD FAILED ($tag), tail of $OUT/build-$tag.log:"
    tail -20 "$OUT/build-$tag.log"
    return $rc
  fi
  cp "$td/$TRIPLE/release/toy" "$OUT/bin-$tag"
}

text_hash() { objcopy -O binary --only-section=.text "$1" /dev/stdout | sha256sum | cut -d' ' -f1; }
out_hash()  { "$1" all 2>&1 | sha256sum | cut -d' ' -f1; }

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

# ---------------------------------------------------------------------------
# 5a  off-equivalence
# ---------------------------------------------------------------------------
test_5a() {
  echo "### 5a  off-equivalence"
  local empty="$OUT/plan-empty.json"
  cat > "$empty" <<'EOF'
{"schema_version": 1, "plan_id": "empty", "fn_attrs": [], "loop_md": []}
EOF
  local rd="$OUT/rep-5a"; rm -rf "$rd"; mkdir -p "$rd"

  # A determinism control first: the same configuration twice. Without it a
  # difference between arms cannot be attributed to the plugin
  # (results.md "Day 0" section 34).
  NO_PLUGIN=1 build_toy 5a-none1  || return 1
  NO_PLUGIN=1 build_toy 5a-none2  || return 1
  JEV_MODE=off build_toy 5a-off   || return 1
  JEV_MODE=apply JEV_PLAN="$empty" JEV_PLAN_SHA="$(sha_of "$empty")" \
    JEV_REPORT_DIR="$rd" build_toy 5a-applyempty || return 1

  printf '%-16s %-66s %s\n' arm text_sha256 output_sha256
  local t
  for t in 5a-none1 5a-none2 5a-off 5a-applyempty; do
    printf '%-16s %-66s %s\n' "$t" "$(text_hash "$OUT/bin-$t")" "$(out_hash "$OUT/bin-$t")"
  done
  echo
  echo "normalised code diff (scripts/norm_code_diff.py), baseline = 5a-none1:"
  for t in 5a-none2 5a-off 5a-applyempty; do
    printf '  %-16s ' "$t"
    python3 "$REPO/scripts/norm_code_diff.py" "$OUT/bin-5a-none1" "$OUT/bin-$t" 2>&1 \
      | tail -3 | tr '\n' ' '
    echo
  done
  echo "apply-empty reports written: $(ls "$rd" | wc -l)"
}

# ---------------------------------------------------------------------------
# 5b  dump
# ---------------------------------------------------------------------------
test_5b() {
  echo "### 5b  dump, marks = the four toyloops functions"
  local rd="$OUT/rep-5b"; rm -rf "$rd"; mkdir -p "$rd"
  JEV_MODE=dump JEV_MARKS="$MARKS_ALL" JEV_REPORT_DIR="$rd" build_toy 5b-dump || return 1
  python3 "$REPO/scripts/plugin_report.py" sites "$rd"
}

# ---------------------------------------------------------------------------
# 5c  loop metadata
# ---------------------------------------------------------------------------
test_5c() {
  echo "### 5c  loop metadata"
  local rd="$OUT/rep-5b"
  [ -d "$rd" ] || { echo "run 5b first"; return 1; }

  # Pick the loop that is *inside* each marked function (match=loop_in_mark),
  # not the driver's repeat loop around it.
  local kq ks kd
  kq="$(python3 "$REPO/scripts/plugin_report.py" key "$rd" toyloops::count_quotes)"
  ks="$(python3 "$REPO/scripts/plugin_report.py" key "$rd" toyloops::sum_indexed)"
  kd="$(python3 "$REPO/scripts/plugin_report.py" key "$rd" toyloops::dot_f64)"
  local lq ls_ ld
  lq="$(python3 "$REPO/scripts/plugin_report.py" leaf "$rd" toyloops::count_quotes)"
  ls_="$(python3 "$REPO/scripts/plugin_report.py" leaf "$rd" toyloops::sum_indexed)"
  ld="$(python3 "$REPO/scripts/plugin_report.py" leaf "$rd" toyloops::dot_f64)"
  echo "count_quotes loop key: $kq   at $lq"
  echo "sum_indexed  loop key: $ks   at $ls_"
  echo "dot_f64      loop key: $kd   at $ld"

  local plan="$OUT/plan-5c.json"
  python3 - "$plan" "$kq" "$ks" <<'PY'
import json, sys
plan = {"schema_version": 1, "plan_id": "5c-loopmd",
        "fn_attrs": [],
        "loop_md": [
            {"key": sys.argv[2], "stage": "lto", "vectorize_width": 8},
            {"key": sys.argv[3], "stage": "lto", "unroll_count": 4},
        ]}
open(sys.argv[1], "w").write(json.dumps(plan, indent=2) + "\n")
PY
  local ard="$OUT/rep-5c"; rm -rf "$ard"; mkdir -p "$ard"
  JEV_MODE=apply JEV_PLAN="$plan" JEV_PLAN_SHA="$(sha_of "$plan")" \
    JEV_REPORT_DIR="$ard" build_toy 5c-apply || return 1
  python3 "$REPO/scripts/plugin_report.py" apply "$ard"

  echo
  echo "-- remarks at the two sites"
  grep -E 'remark:.*(vectorized loop|unrolled loop|interleaved|COMPLETELY UNROLL)' \
       "$OUT/build-5c-apply.log" \
    | grep -E "$(printf '%s|%s' "$lq" "$ls_")" | sort -u | head -20
  echo "  (baseline, same two sites)"
  grep -E 'remark:.*(vectorized loop|unrolled loop|interleaved|COMPLETELY UNROLL)' \
       "$OUT/build-5a-none1.log" 2>/dev/null \
    | grep -E "$(printf '%s|%s' "$lq" "$ls_")" | sort -u | head -20
  echo
  echo "-- objdump: widest vector register in toy::main"
  objdump -d --no-show-raw-insn "$OUT/bin-5c-apply" \
    | awk '/<_RNvCs.*3toy4main>:/,/^$/' | grep -oE '%[yz]mm[0-9]+' | sort -u | tr '\n' ' '
  echo
  echo "-- checksums"
  printf '  baseline(5a-none1) %s\n' "$(out_hash "$OUT/bin-5a-none1")"
  printf '  5c-apply           %s\n' "$(out_hash "$OUT/bin-5c-apply")"

  echo
  echo "-- dot_f64 vectorize.width=8, with and without -hints-allow-reordering=false"
  local pland="$OUT/plan-5c-dot.json"
  python3 - "$pland" "$kd" <<'PY'
import json, sys
open(sys.argv[1], "w").write(json.dumps(
    {"schema_version": 1, "plan_id": "5c-dot",
     "fn_attrs": [],
     "loop_md": [{"key": sys.argv[2], "stage": "lto", "vectorize_width": 8}]},
    indent=2) + "\n")
PY
  local drd="$OUT/rep-5c-dot"; rm -rf "$drd"; mkdir -p "$drd"
  JEV_MODE=apply JEV_PLAN="$pland" JEV_PLAN_SHA="$(sha_of "$pland")" \
    JEV_REPORT_DIR="$drd" build_toy 5c-dot-guarded || return 1
  local drd2="$OUT/rep-5c-dot-unguarded"; rm -rf "$drd2"; mkdir -p "$drd2"
  NO_REORDER_FLAG=1 JEV_MODE=apply JEV_PLAN="$pland" JEV_PLAN_SHA="$(sha_of "$pland")" \
    JEV_REPORT_DIR="$drd2" build_toy 5c-dot-unguarded || return 1

  printf '  %-22s %-66s %s\n' arm text_sha256 output_sha256
  local t
  for t in 5a-none1 5c-dot-guarded 5c-dot-unguarded; do
    printf '  %-22s %-66s %s\n' "$t" "$(text_hash "$OUT/bin-$t")" "$(out_hash "$OUT/bin-$t")"
  done
  echo "  guarded   CantReorderFPOps remarks: $(grep -c 'cannot prove it is safe to reorder floating-point' "$OUT/build-5c-dot-guarded.log")"
  echo "  unguarded CantReorderFPOps remarks: $(grep -c 'cannot prove it is safe to reorder floating-point' "$OUT/build-5c-dot-unguarded.log")"
  echo "  guarded   'vectorized loop' at $ld: $(grep "$ld" "$OUT/build-5c-dot-guarded.log" | grep -c 'vectorized loop')"
  echo "  unguarded 'vectorized loop' at $ld: $(grep "$ld" "$OUT/build-5c-dot-unguarded.log" | grep -c 'vectorized loop')"
  echo "  apply outcome, guarded:"
  python3 "$REPO/scripts/plugin_report.py" apply "$drd"
  echo "  apply outcome, unguarded:"
  python3 "$REPO/scripts/plugin_report.py" apply "$drd2"
}

# ---------------------------------------------------------------------------
# 5d  function attributes
# ---------------------------------------------------------------------------
test_5d() {
  echo "### 5d  function attributes"
  local plan="$OUT/plan-5d.json"
  cat > "$plan" <<'EOF'
{
  "schema_version": 1,
  "plan_id": "5d-fnattrs",
  "fn_attrs": [
    {"fn": "toyloops::count_quotes", "inline": "never", "align": 64},
    {"fn": "toyloops::find_special", "cold": true}
  ],
  "loop_md": []
}
EOF
  local rd="$OUT/rep-5d"; rm -rf "$rd"; mkdir -p "$rd"
  JEV_MODE=apply JEV_PLAN="$plan" JEV_PLAN_SHA="$(sha_of "$plan")" \
    JEV_REPORT_DIR="$rd" build_toy 5d-apply || return 1
  python3 "$REPO/scripts/plugin_report.py" apply "$rd"

  echo
  echo "-- nm: does count_quotes survive as its own symbol, and where"
  nm -C "$OUT/bin-5d-apply" | grep -iE "count_quotes|find_special" | head
  echo "-- baseline for comparison"
  nm -C "$OUT/bin-5a-none1" | grep -iE "count_quotes|find_special" | head
  echo
  echo "-- alignment of count_quotes in the binary"
  local addr
  addr="$(nm "$OUT/bin-5d-apply" | grep -i 'count_quotes' | head -1 | cut -d' ' -f1)"
  if [ -n "$addr" ]; then
    python3 -c "a=int('$addr',16); print('  address 0x%x, 64-aligned: %s' % (a, a%64==0))"
  else
    echo "  (symbol not present)"
  fi
  echo
  echo "-- the attributes as they stand in the IR, read back with apply-dump"
  local rrd="$OUT/rep-5d-readback"; rm -rf "$rrd"; mkdir -p "$rrd"
  JEV_MODE=apply-dump JEV_PLAN="$plan" JEV_PLAN_SHA="$(sha_of "$plan")" \
    JEV_MARKS="$MARKS_ALL" JEV_REPORT_DIR="$rrd" build_toy 5d-readback || return 1
  python3 - "$rrd" <<'PY'
import json, glob, os, sys
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.json"))):
    d = json.load(open(f))
    for fn in d.get("functions", []):
        print("   %-9s %-36s attrs=%r" % (d["stage"], fn["demangled"], fn["attributes"]))
PY
  echo
  echo "-- checksums"
  printf '  baseline(5a-none1) %s\n' "$(out_hash "$OUT/bin-5a-none1")"
  printf '  5d-apply           %s\n' "$(out_hash "$OUT/bin-5d-apply")"
}

# ---------------------------------------------------------------------------
# 5e  key resolution under fat+PGO, and unmatched marks
# ---------------------------------------------------------------------------
test_5e() {
  echo "### 5e  key resolution under fat+PGO, unmatched marks"
  local rd="$OUT/rep-5b"
  [ -d "$rd" ] || { echo "run 5b first"; return 1; }
  local plan="$OUT/plan-5e.json"
  python3 "$REPO/scripts/plugin_report.py" allkeys "$rd" > "$plan"
  echo "plan covers $(python3 -c "import json;print(len(json.load(open('$plan'))['loop_md']))") keys (every site 5b dumped)"
  local ard="$OUT/rep-5e"; rm -rf "$ard"; mkdir -p "$ard"
  JEV_MODE=apply JEV_PLAN="$plan" JEV_PLAN_SHA="$(sha_of "$plan")" \
    JEV_REPORT_DIR="$ard" build_toy 5e-apply || return 1
  python3 "$REPO/scripts/plugin_report.py" apply "$ard"

  echo
  echo "-- unmatched marks: a bogus name added to the marks file"
  local bogus="$OUT/marks/toy-bogus.txt"
  cat "$MARKS_ALL" > "$bogus"
  echo "toyloops::no_such_function" >> "$bogus"
  local brd="$OUT/rep-5e-bogus"; rm -rf "$brd"; mkdir -p "$brd"
  JEV_MODE=dump JEV_MARKS="$bogus" JEV_REPORT_DIR="$brd" build_toy 5e-bogus || return 1
  python3 - "$brd" <<'PY'
import json, glob, os, sys
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.json"))):
    d = json.load(open(f))
    print("  %-12s loop_ep_ran=%-5s unmatched_marks=%s"
          % (d["stage"], d["loop_ep_ran"], d["unmatched_marks"]))
PY
}

# ---------------------------------------------------------------------------
# 5f  key stability when a function attribute changes
# ---------------------------------------------------------------------------
test_5f() {
  echo "### 5f  key stability when a function attribute changes"
  local rd="$OUT/rep-5b"
  [ -d "$rd" ] || { echo "run 5b first"; return 1; }
  local plan="$OUT/plan-5f.json"
  cat > "$plan" <<'EOF'
{
  "schema_version": 1,
  "plan_id": "5f-noinline-only",
  "fn_attrs": [{"fn": "toyloops::count_quotes", "inline": "never"}],
  "loop_md": []
}
EOF
  # JEV_MODE=apply-dump applies the fn_attrs half of the plan at
  # PipelineStart and then dumps the loops out of the IR those attributes
  # produced. That is the only way to ask the two-phase question inside one
  # build, and it is also the shape the CLI needs: a loop decision has to be
  # taken on the IR the attribute decision created.
  local ard="$OUT/rep-5f"; rm -rf "$ard"; mkdir -p "$ard"
  JEV_MODE=apply-dump JEV_PLAN="$plan" JEV_PLAN_SHA="$(sha_of "$plan")" \
    JEV_MARKS="$MARKS_ALL" JEV_REPORT_DIR="$ard" build_toy 5f-applydump || return 1
  python3 "$REPO/scripts/plugin_report.py" apply "$ard"
  echo
  python3 "$REPO/scripts/plugin_report.py" sites "$ard"
  echo "-- loop keys per mark: 5b (no attributes) vs 5f (count_quotes noinline)"
  python3 "$REPO/scripts/plugin_report.py" compare "$rd" "$ard"
}

case "${1:-all}" in
  5a) test_5a ;;
  5b) test_5b ;;
  5c) test_5c ;;
  5d) test_5d ;;
  5e) test_5e ;;
  5f) test_5f ;;
  all) test_5a; echo; test_5b; echo; test_5c; echo; test_5d; echo; test_5e; echo; test_5f ;;
  *) echo "usage: $0 [5a|5b|5c|5d|5e|5f|all]" >&2; exit 2 ;;
esac
