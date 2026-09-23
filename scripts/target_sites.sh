#!/usr/bin/env bash
#
# Enumerate the optimization sites of a target's marks and assemble the
# baseline directory scripts/jev_search.py --baseline-dir reuses. The
# target-generic version of scripts/jaq_sites.sh (and of the dump half of
# scripts/hintbench_oracle.sh); both of those stay as they are, because
# results.md quotes their commands and their outputs are frozen.
#
# Every build is the target's PGO baseline recipe from scripts/target_common.sh
# (build_variant: FIXED_RUSTFLAGS included) plus the pinned
# -Cllvm-args=-hints-allow-reordering=false that jev_search.py's
# plugin_knobs() adds to every arm (build_variant drops an exact duplicate).
# The profile is the target's existing $PROFDATA; nothing here generates one.
# Never run scripts/target_pgo_baseline.sh from here.
#
# Subcommands, in the order a new target runs them:
#
#   flags     print the effective CARGO_ENCODED_RUSTFLAGS (one per line) and
#             the plugin/profile env. No build.
#   base      plugin-off build of the baseline. Its .text hash and output
#             checksums are what the site list is relative to. Prints the
#             build wall time (not a program measurement).
#   dump      the same build with -Zllvm-plugins and JEV_MODE=dump: the
#             function table and every loop touching a mark. Checks that the
#             dump did not perturb codegen (norm_code_diff against `base`) and
#             that the outputs match.
#   allkeys   JEV_MODE=apply with a plan naming every dumped key
#             (unroll_count=1), so `ambiguous` / `unmatched` / `vanished` are
#             measured rather than predicted.
#   sites     run scripts/target_sites_report.py: targets/$TARGET/sites.json
#             and sites.md, with the loop-site cap $SITE_CAP_RULE.
#   baseline  assemble $OUT/baseline/{bin,reports,correctness.txt,build.log,
#             baseline.json} from the `dump` build, in the shape
#             jev_search.py's baseline() writes and reads. It is the dump
#             build, not the plugin-off one, because the driver needs the
#             dump's reports; the plugin only reads, and `dump` checked the
#             two builds are normalised-code identical. baseline.json also
#             records the plugin-off build's hashes and that verdict.
#   all       base, dump, allkeys, sites, baseline.
#
# No timing of any kind is run here.
#
# Usage:
#   export TARGET=zopfli          # `export`, not a temporary assignment (decision 31)
#   scripts/target_sites.sh flags|base|dump|allkeys|sites|baseline|all
#
# Environment:
#   TARGET          required, exported. jaq and hintbench are refused unless
#                   ALLOW_EXISTING=1: their site sets are frozen.
#   PROFDATA        the profile (default from target_common.sh:
#                   pgo/$TARGET/merged.profdata). Must exist; never generated.
#   SITE_CAP_TOP    L, default 6.
#   SITE_CAP_RULE   the pre-registered, result-blind loop-site cap, a comma
#                   list applied in order (target_sites_report.py --cap-rule).
#                   Default: no_profile,trip_lt_2,per_mark:2,top:$SITE_CAP_TOP
#                   = drop keys the training profile never entered, drop trip
#                   count < 2, keep the top 2 by hotness per mark, then the top
#                   L by hotness overall -> oracle.selected_keys_top$L.
#   SITES_VOCAB     vocabulary pricing the sweep in sites.md (default v6; the
#                   report falls back to v5 with a note if v6 is undefined).
#   OUT             artifacts dir (default artifacts/$TARGET-sites).
#   SITES_JSON/SITES_MD  outputs (default targets/$TARGET/sites.{json,md}).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${TARGET:?export TARGET=<target> first (decision 31)}"
case "$TARGET" in
  jaq|hintbench)
    if [ "${ALLOW_EXISTING:-0}" != 1 ]; then
      echo "TARGET=$TARGET has a frozen site set; refusing (ALLOW_EXISTING=1 to override)" >&2
      exit 2
    fi ;;
esac
export TARGET
# shellcheck source=/dev/null
source "$REPO/scripts/target_common.sh"

PLUGIN="$REPO/plugin/build/libjevplugin.so"
MARKS="$REPO/targets/$TARGET/jev-marks.txt"
OUT="${OUT:-$REPO/artifacts/$TARGET-sites}"
SITES_JSON="${SITES_JSON:-$REPO/targets/$TARGET/sites.json}"
SITES_MD="${SITES_MD:-$REPO/targets/$TARGET/sites.md}"
SITE_CAP_TOP="${SITE_CAP_TOP:-6}"
SITE_CAP_RULE="${SITE_CAP_RULE:-no_profile,trip_lt_2,per_mark:2,top:$SITE_CAP_TOP}"
SITES_VOCAB="${SITES_VOCAB:-v6}"
SRC_DIR="${SRC_DIR:-$(dirname "$MANIFEST")}"
BIN_REL="$TRIPLE/release/$BIN_NAME"
TD_BASE="$REPO/target-$TARGET-sites-base"
TD_DUMP="$REPO/target-$TARGET-sites-dump"
TD_ALLKEYS="$REPO/target-$TARGET-sites-allkeys"
RD="$OUT/rep-dump"
PIN='-Cllvm-args=-hints-allow-reordering=false'

sha_of() { sha256sum "$1" | cut -d' ' -f1; }
say() { printf '\n========== %s ==========\n' "$*"; }

need_profile() {
  [ -f "$PROFDATA" ] || {
    echo "no $PROFDATA: set PROFDATA= to the target's frozen profile" \
         "(this script never generates one; do not run target_pgo_baseline.sh)" >&2
    exit 2; }
}
need_plugin() {
  [ -f "$PLUGIN" ] || { echo "no plugin: run scripts/build_plugin.sh" >&2; exit 2; }
}
need_marks() {
  [ -f "$MARKS" ] || { echo "no $MARKS" >&2; exit 2; }
}

# build_variant with the wall time printed. Build time only.
timed_build() {
  local td="$1" log="$2"; shift 2
  local t0=$SECONDS rc=0
  build_variant "$td" "$log" "$@" || rc=$?
  echo "  build time     $((SECONDS - t0)) s (rc=$rc, log $log)"
  [ "$rc" = 0 ] || { tail -20 "$log" >&2; exit "$rc"; }
}

do_base() {
  need_profile
  mkdir -p "$OUT"
  say "a. $TARGET baseline, no plugin, profile $PROFDATA"
  timed_build "$TD_BASE" "$OUT/build-base.log" "$PIN"
  local bin="$TD_BASE/$BIN_REL"
  text_hash "$bin" > "$OUT/text-base.sha256"
  echo "  .text sha256   $(cat "$OUT/text-base.sha256")"
  run_correctness "$bin" "$OUT/correctness-base.txt"
  cat "$OUT/correctness-base.txt"
}

do_dump() {
  need_profile; need_plugin; need_marks
  mkdir -p "$OUT"
  say "b. JEV_MODE=dump: the function table and every loop touching a mark"
  rm -rf "$RD"; mkdir -p "$RD"
  JEV_MODE=dump JEV_MARKS="$MARKS" JEV_REPORT_DIR="$RD" \
    timed_build "$TD_DUMP" "$OUT/build-dump.log" "-Zllvm-plugins=$PLUGIN" "$PIN"
  local bin="$TD_DUMP/$BIN_REL"
  text_hash "$bin" > "$OUT/text-dump.sha256"
  echo "  .text sha256   $(cat "$OUT/text-dump.sha256")"
  echo "  reports        $(ls "$RD" | wc -l)"
  run_correctness "$bin" "$OUT/correctness-dump.txt"
  say "b2. dump must not perturb codegen (normalised code, SPEC.ja.md 5)"
  if [ -f "$TD_BASE/$BIN_REL" ]; then
    local rc=0
    "$REPO/scripts/norm_code_diff.py" "$TD_BASE/$BIN_REL" "$bin" \
        --profdata "$PROFDATA" | tee "$OUT/norm-base-vs-dump.txt" || rc=$?
    echo "$rc" > "$OUT/norm-base-vs-dump.rc"
    if diff "$OUT/correctness-base.txt" "$OUT/correctness-dump.txt"; then
      echo "  OUTPUTS: MATCH"
    else
      echo "  OUTPUTS: MISMATCH (dump build vs plugin-off build)"
    fi
  else
    echo "  (no $TD_BASE/$BIN_REL: run '$0 base' first; check skipped)"
    rm -f "$OUT/norm-base-vs-dump.txt" "$OUT/norm-base-vs-dump.rc"
  fi
}

do_allkeys() {
  need_profile; need_plugin
  [ -d "$RD" ] || { echo "no $RD: run '$0 dump' first" >&2; exit 2; }
  say "c. do the dumped keys resolve? a plan naming every one of them"
  local rd="$OUT/rep-allkeys" plan="$OUT/plan-allkeys.json"
  rm -rf "$rd"; mkdir -p "$rd"
  "$REPO/scripts/plugin_report.py" allkeys "$RD" > "$plan"
  echo "  plan names $(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))['loop_md']))" "$plan") keys"
  JEV_MODE=apply JEV_PLAN="$plan" JEV_PLAN_SHA="$(sha_of "$plan")" \
    JEV_REPORT_DIR="$rd" \
    timed_build "$TD_ALLKEYS" "$OUT/build-allkeys.log" "-Zllvm-plugins=$PLUGIN" "$PIN"
  echo "  .text sha256   $(text_hash "$TD_ALLKEYS/$BIN_REL")"
  run_correctness "$TD_ALLKEYS/$BIN_REL" "$OUT/correctness-allkeys.txt"
  diff "$OUT/correctness-dump.txt" "$OUT/correctness-allkeys.txt" \
    && echo "  OUTPUTS: MATCH" || echo "  OUTPUTS: MISMATCH"
  # Per key: attached/consumed are fine, `ambiguous` means the key names
  # several loops, `unmatched`/`vanished` mean it does not resolve.
  "$REPO/scripts/plugin_report.py" apply "$rd" \
    | grep -E 'ambiguous|unmatched|vanished|totals' || true
}

# The exact CARGO_ENCODED_RUSTFLAGS build_variant assembles, recovered from
# build_variant itself (cargo shadowed by a function), as in jaq_sites.sh.
encoded_flags() {
  cargo() { printf '%s' "$CARGO_ENCODED_RUSTFLAGS"; }
  local td lg; td="$(mktemp -d)"; lg="$(mktemp)"
  build_variant "$td" "$lg" "$@"
  cat "$lg"
  rm -f "$lg"; rmdir "$td" 2>/dev/null || true
  unset -f cargo
}

do_flags() {
  local f
  echo "TARGET=$TARGET  MANIFEST=$MANIFEST  BIN=$BIN_REL"
  echo "PROFDATA=$PROFDATA $([ -f "$PROFDATA" ] && echo '(present)' || echo '(MISSING)')"
  echo "FIXED_RUSTFLAGS: ${FIXED_RUSTFLAGS[*]:-(none)}"
  echo "CARGO_EXTRA: ${CARGO_EXTRA[*]:-(none)}"
  echo "profile env: OPT_LEVEL=3 LTO=fat CODEGEN_UNITS=1 DEBUG=1 PANIC=unwind" \
       "STRIP=${CARGO_PROFILE_RELEASE_STRIP:-(cargo default)}"
  echo "base (plugin off) CARGO_ENCODED_RUSTFLAGS:"
  { encoded_flags "$PIN"; echo; } | tr '\037' '\n' | sed 's/^/    /'
  echo "dump: the same plus -Zllvm-plugins=$PLUGIN, env JEV_MODE=dump" \
       "JEV_MARKS=$MARKS JEV_REPORT_DIR=$RD"
  echo "cap: SITE_CAP_RULE=$SITE_CAP_RULE  vocab=$SITES_VOCAB"
  echo "outputs: $SITES_JSON $SITES_MD $OUT/baseline"
}

do_sites() {
  need_marks
  [ -d "$RD" ] || { echo "no $RD: run '$0 dump' first" >&2; exit 2; }
  say "d. sites.json / sites.md (cap: $SITE_CAP_RULE)"
  local flags; flags="$(encoded_flags "$PIN")"
  local ak=()
  [ -d "$OUT/rep-allkeys" ] && ak=(--allkeys-reports "$OUT/rep-allkeys")
  local bt="" dt=""
  [ -f "$OUT/text-base.sha256" ] && bt="$(cat "$OUT/text-base.sha256")"
  [ -f "$OUT/text-dump.sha256" ] && dt="$(cat "$OUT/text-dump.sha256")"
  local outs="$OUT/correctness-base.txt"
  [ -f "$outs" ] || outs="$OUT/correctness-dump.txt"
  (cd "$REPO" && python3 scripts/target_sites_report.py \
    --target "$TARGET" --marks "$MARKS" --reports "$RD" \
    --profdata "$PROFDATA" --src-dir "$SRC_DIR" \
    --out-json "$SITES_JSON" --out-md "$SITES_MD" \
    --vocab "$SITES_VOCAB" --cap-rule "$SITE_CAP_RULE" \
    --flags "$flags" --flags-sha "$(printf '%s' "$flags" | sha256sum | cut -d' ' -f1)" \
    --baseline-text-sha "$bt" --dump-text-sha "$dt" --outputs "$outs" \
    ${ak[@]+"${ak[@]}"})
}

do_baseline() {
  local bin="$TD_DUMP/$BIN_REL"
  [ -f "$bin" ] && [ -d "$RD" ] && [ -f "$OUT/correctness-dump.txt" ] \
    || { echo "no dump build: run '$0 dump' first" >&2; exit 2; }
  say "e. baseline directory for scripts/jev_search.py --baseline-dir"
  local bd="$OUT/baseline"
  rm -rf "$bd"; mkdir -p "$bd"
  cp "$bin" "$bd/bin"
  cp -r "$RD" "$bd/reports"
  cp "$OUT/correctness-dump.txt" "$bd/correctness.txt"
  cp "$OUT/build-dump.log" "$bd/build.log"
  local flags; flags="$(encoded_flags "$PIN")"
  BD="$bd" OUTD="$OUT" TGT="$TARGET" PD="$PROFDATA" FLAGS="$flags" \
    BASEBIN="$TD_BASE/$BIN_REL" python3 - <<'PY'
import hashlib, json, os
e = os.environ
bd, out = e["BD"], e["OUTD"]
def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.isfile(p) else None
def rd(p):
    return open(p).read().strip() if os.path.isfile(p) else None
b = os.path.join(bd, "bin")
meta = {"dir": bd, "bin": b,
        "correctness": os.path.join(bd, "correctness.txt"),
        "reports": os.path.join(bd, "reports"),
        "log": os.path.join(bd, "build.log"),
        "bin_sha256": sha(b),
        # Extra fields; jev_search.py reads only the six above.
        "target": e["TGT"],
        "built_by": "scripts/target_sites.sh dump (JEV_MODE=dump)",
        "profdata": e["PD"], "profdata_sha256": sha(e["PD"]),
        "encoded_rustflags": e["FLAGS"].split("\x1f"),
        "dump_text_sha256": rd(os.path.join(out, "text-dump.sha256")),
        "plugin_off": {
            "bin_sha256": sha(e["BASEBIN"]),
            "text_sha256": rd(os.path.join(out, "text-base.sha256")),
            "norm_code_diff_rc": rd(os.path.join(out, "norm-base-vs-dump.rc")),
            "outputs_match": (rd(os.path.join(out, "correctness-base.txt"))
                              == rd(os.path.join(out, "correctness-dump.txt")))
                             if os.path.isfile(os.path.join(out, "correctness-base.txt"))
                             else None}}
json.dump(meta, open(os.path.join(bd, "baseline.json"), "w"), indent=1)
print("  wrote %s/baseline.json" % bd)
print("  plugin-off vs dump: norm_code_diff rc=%s, outputs_match=%s"
      % (meta["plugin_off"]["norm_code_diff_rc"], meta["plugin_off"]["outputs_match"]))
PY
}

case "${1:-}" in
  flags)    do_flags ;;
  base)     do_base ;;
  dump)     do_dump ;;
  allkeys)  do_allkeys ;;
  sites)    do_sites ;;
  baseline) do_baseline ;;
  all)      do_base; do_dump; do_allkeys; do_sites; do_baseline ;;
  *) echo "usage: TARGET=<t> $0 flags|base|dump|allkeys|sites|baseline|all" >&2; exit 2 ;;
esac
