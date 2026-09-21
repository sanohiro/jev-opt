#!/usr/bin/env bash
#
# Enumerate the optimization sites of the jaq marks (SPEC.ja.md 1 (3) step 1,
# decision 61 (a)). Four builds, all on the frozen PGO baseline recipe of
# results.md "Stage 0 (jaq)" section 53 plus the pinned
# -Cllvm-args=-hints-allow-reordering=false that scripts/target_common.sh now
# puts in FIXED_RUSTFLAGS for jaq:
#
#   base       the baseline itself, no plugin. Its .text hash, normalised
#              code hash and six output checksums are what the site list is
#              relative to.
#   dump       the same build with -Zllvm-plugins and JEV_MODE=dump. The
#              plugin only reads, so this binary must be normalised-code
#              identical to `base`; the script checks that and says so.
#   allkeys    JEV_MODE=apply with a plan naming every key the dump
#              produced, so that `vanished` and `ambiguous` are measured
#              rather than predicted (results.md "Day 3 (plugin)" 7 is the
#              same test on the toy).
#   applydump  JEV_MODE=apply-dump with one fn_attrs entry
#              (`inline: never` on $AD_MARK), re-dumping the loops out of the
#              IR that attribute produced. Decision 61 (b)'s two-phase rule
#              assumes a function attribute moves only that function's own
#              loop keys; on the toy that held (results.md "Day 3 (plugin)"
#              8), and this is the same question asked on jaq.
#
# No timing of any kind is run here. `real` lines in the log are build wall
# time and are not a measurement of the program.
#
# Usage:
#   export TARGET=jaq
#   scripts/jaq_sites.sh [base|dump|allkeys|applydump|all]   # default: all
#
# Environment: AD_MARK (default jaq_json::write::write) is the mark the
# apply-dump run puts `inline: never` on. REPO, PROFDATA and the profile
# environment come from scripts/target_common.sh.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export TARGET="${TARGET:-jaq}"
[ "$TARGET" = jaq ] || { echo "TARGET must be jaq" >&2; exit 2; }
# shellcheck source=/dev/null
source "$REPO/scripts/target_common.sh"

PLUGIN="$REPO/plugin/build/libjevplugin.so"
MARKS="$REPO/targets/jaq/jev-marks.txt"
OUT="$REPO/artifacts/jaq-sites"
AD_MARK="${AD_MARK:-jaq_json::write::write}"
BIN_REL="x86_64-unknown-linux-gnu/release/jaq"
mkdir -p "$OUT"

[ -f "$PLUGIN" ] || { echo "no plugin: run scripts/build_plugin.sh" >&2; exit 2; }
[ -f "$PROFDATA" ] || { echo "no $PROFDATA" >&2; exit 2; }

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

say() { printf '\n========== %s ==========\n' "$*"; }

do_base() {
  say "a. baseline, no plugin, with the pinned -hints-allow-reordering=false"
  local td="$REPO/target-jaq-sites-base"
  build_variant "$td" "$OUT/build-base.log"
  local bin="$td/$BIN_REL"
  echo "  .text sha256   $(text_hash "$bin")"
  run_correctness "$bin" "$OUT/correctness-base.txt"
  cat "$OUT/correctness-base.txt"
}

do_dump() {
  say "b. JEV_MODE=dump: the function table and every loop touching a mark"
  local td="$REPO/target-jaq-sites-dump" rd="$OUT/rep-dump"
  rm -rf "$rd"; mkdir -p "$rd"
  JEV_MODE=dump JEV_MARKS="$MARKS" JEV_REPORT_DIR="$rd" \
    build_variant "$td" "$OUT/build-dump.log" "-Zllvm-plugins=$PLUGIN"
  local bin="$td/$BIN_REL"
  echo "  .text sha256   $(text_hash "$bin")"
  echo "  reports        $(ls "$rd" | wc -l)"
  run_correctness "$bin" "$OUT/correctness-dump.txt"
  say "b2. dump must not perturb codegen (normalised code, SPEC.ja.md 5)"
  "$REPO/scripts/norm_code_diff.py" "$REPO/target-jaq-sites-base/$BIN_REL" "$bin" \
      --profdata "$PROFDATA"
  diff "$OUT/correctness-base.txt" "$OUT/correctness-dump.txt" \
    && echo "  OUTPUTS: MATCH"
}

do_applydump() {
  say "c. JEV_MODE=apply-dump: inline(never) on one mark, then re-dump"
  local td="$REPO/target-jaq-sites-applydump" rd="$OUT/rep-applydump"
  local plan="$OUT/plan-applydump.json"
  rm -rf "$rd"; mkdir -p "$rd"
  # One non-generic mark, one attribute, no loop_md: the narrowest change
  # that can move a loop key at all.
  AD_MARK="$AD_MARK" python3 - "$plan" <<'PY'
import json, os, sys
json.dump({"schema_version": 1, "plan_id": "jaq-sites-applydump",
           "fn_attrs": [{"fn": os.environ["AD_MARK"], "inline": "never"}],
           "loop_md": []}, open(sys.argv[1], "w"), indent=2)
PY
  echo "  plan: $(cat "$plan" | tr -d '\n' | tr -s ' ')"
  JEV_MODE=apply-dump JEV_PLAN="$plan" JEV_PLAN_SHA="$(sha_of "$plan")" \
    JEV_MARKS="$MARKS" JEV_REPORT_DIR="$rd" \
    build_variant "$td" "$OUT/build-applydump.log" "-Zllvm-plugins=$PLUGIN"
  local bin="$td/$BIN_REL"
  echo "  .text sha256   $(text_hash "$bin")"
  run_correctness "$bin" "$OUT/correctness-applydump.txt"
  diff "$OUT/correctness-base.txt" "$OUT/correctness-applydump.txt" \
    && echo "  OUTPUTS: MATCH (the attribute did not change the answer)"
  say "c2. which marks kept their loop_in_mark keys"
  "$REPO/scripts/plugin_report.py" compare "$OUT/rep-dump" "$rd"
}

do_allkeys() {
  say "d. do the dumped keys resolve? a plan naming every one of them"
  local td="$REPO/target-jaq-sites-allkeys" rd="$OUT/rep-allkeys"
  local plan="$OUT/plan-allkeys.json"
  rm -rf "$rd"; mkdir -p "$rd"
  # results.md "Day 3 (plugin)" 7 on the toy, where every key resolved. The
  # least invasive entry the plugin still acts on is unroll_count=1, so the
  # outcome column is purely about key resolution.
  "$REPO/scripts/plugin_report.py" allkeys "$OUT/rep-dump" > "$plan"
  echo "  plan names $(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))['loop_md']))" "$plan") keys"
  JEV_MODE=apply JEV_PLAN="$plan" JEV_PLAN_SHA="$(sha_of "$plan")" \
    JEV_REPORT_DIR="$rd" \
    build_variant "$td" "$OUT/build-allkeys.log" "-Zllvm-plugins=$PLUGIN"
  echo "  .text sha256   $(text_hash "$td/$BIN_REL")"
  run_correctness "$td/$BIN_REL" "$OUT/correctness-allkeys.txt"
  diff "$OUT/correctness-base.txt" "$OUT/correctness-allkeys.txt" \
    && echo "  OUTPUTS: MATCH"
  "$REPO/scripts/plugin_report.py" apply "$rd" | tail -3
}

# The exact CARGO_ENCODED_RUSTFLAGS build_variant assembles for this target,
# recovered from build_variant itself rather than re-listed here, so the two
# cannot drift: `cargo` is shadowed by a function, and the env prefix on
# build_variant's `cargo build` line is what sets the variable it prints.
# `basis.fixed_flags_sha256` in targets/jaq/sites.json is the sha256 of this
# string, NUL-free and \x1f-separated exactly as rustc receives it.
do_flags() {
  cargo() { printf '%s' "$CARGO_ENCODED_RUSTFLAGS"; }
  local td lg; td="$(mktemp -d)"; lg="$(mktemp)"
  build_variant "$td" "$lg" "$@"        # build_variant sends cargo's stdout to the log
  cat "$lg"
  rm -f "$lg"; rmdir "$td" 2>/dev/null || true
  unset -f cargo
}

case "${1:-all}" in
  flags)     do_flags "${@:2}" ;;
  base)      do_base ;;
  dump)      do_dump ;;
  applydump) do_applydump ;;
  allkeys)   do_allkeys ;;
  all)       do_base; do_dump; do_allkeys; do_applydump ;;
  *) echo "usage: $0 [base|dump|applydump|all]" >&2; exit 2 ;;
esac
