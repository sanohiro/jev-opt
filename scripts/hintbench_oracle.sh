#!/usr/bin/env bash
#
# The oracle sweep for the hint benchmark (targets/hintbench).
#
# The benchmark exists to produce ground truth cheaply: one kernel per hint in
# the frozen vocabulary (SPEC.ja.md 1(2)), each shaped so that exactly one hint
# has a mechanism, and `targets/hintbench/EXPECTED.md` written down before any
# timing. The oracle of SPEC.ja.md 2 --- one candidate at one site with every
# other site at KEEP_DEFAULT, plus one combination arm --- is what decides
# whether each mechanism is real, and therefore what Claude's and Jev's picks
# are scored against.
#
# Subcommands:
#   dump    build the baseline with JEV_MODE=dump, check that loading the
#           plugin did not perturb codegen, and write the site list and the
#           frozen loop-site set to artifacts/hintbench-sites/sites.json.
#   sites   regenerate sites.json from the reports an earlier `dump` wrote,
#           without rebuilding anything.
#   arms    dry-run scripts/jev_search.py --proposer oracle: print the arm
#           count and one line per arm. No build, no timing.
#   smoke   one JEV_MODE=apply build carrying EXPECTED.md's expected hint for
#           every kernel at once, to show that each hint is consumed and that
#           the checksums do not move. No timing.
#   run     the sweep itself. This one measures.
#
# Everything but `run` is free of timing. `dump` and `smoke` are one build
# each.
#
# Usage:  scripts/hintbench_oracle.sh [dump|sites|arms|smoke|run]  (default: arms)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export TARGET=hintbench
# shellcheck source=/dev/null
source "$REPO/scripts/target_common.sh"

PLUGIN="$REPO/plugin/build/libjevplugin.so"
MARKS="$REPO/targets/hintbench/jev-marks.txt"
OUT="$REPO/artifacts/hintbench-sites"
SITES="$OUT/sites.json"
BIN_REL="x86_64-unknown-linux-gnu/release/hintbench"
BASE_BIN="$REPO/target-hintbench-pgo-use/$BIN_REL"
RD="$OUT/rep-dump"

# The frozen loop-site set, pre-registered here before the sweep runs. The
# oracle's build count is sum(sites x candidates), so SPEC.ja.md 2 requires the
# site set to be fixed in advance and the same for every proposer.
#
# Rule, in two parts:
#
#   (1) keep only the marks whose hint under test is a loop hint --- k3
#       (unroll), k4 (vectorize.width), k5 (interleave.count) and k8 (the
#       control). This drops k6's loop, whose kernel's hint under test is
#       `align=64`, a function attribute.
#   (2) within a mark, keep the single hottest `loop_in_mark` key. This
#       matters for k3, which produces two: the fill loop itself (leaf
#       lib.rs:174, trip 11.5, hotness 5.5e9) and a second key whose leaf is
#       the `while` line and whose trip count is the *driver's* 4096 --- the
#       caller's loop, picked up because the debug location of its latch comes
#       from the inlined callee. The hotter of the two is the fill loop, which
#       is the one the kernel is about.
#
# Together: 4 loop sites, so 12 sites in total with the 8 marked functions, and
# 8x5 + 4x11 = 84 one-factor arms plus one combination arm. (It was 8x6 + 4x11
# = 92 until vocabulary v3 dropped two inert function candidates, decision 77.)
#
# The set is stored as keys but selected by mark and hotness, because keys move
# when a function attribute changes (decision 61) and the driver re-resolves
# them against the dump it built from.
LOOP_MARKS='hbkernels::k3_fill_run hbkernels::k4_count_bytes hbkernels::k5_mul_reduce hbkernels::k8_scale_add'

say() { printf '\n========== %s ==========\n' "$*"; }
sha_of() { sha256sum "$1" | cut -d' ' -f1; }

need_plugin() {
  [ -f "$PLUGIN" ] || { echo "no plugin: run scripts/build_plugin.sh" >&2; exit 2; }
  [ -f "$PROFDATA" ] || { echo "no $PROFDATA: run TARGET=hintbench scripts/target_pgo_baseline.sh" >&2; exit 2; }
}

do_dump() {
  need_plugin
  say "a. baseline build with JEV_MODE=dump"
  local td="$REPO/target-hintbench-sites-dump" rd="$RD"
  rm -rf "$rd"; mkdir -p "$rd" "$OUT"
  JEV_MODE=dump JEV_MARKS="$MARKS" JEV_REPORT_DIR="$rd" \
    build_variant "$td" "$OUT/build-dump.log" "-Zllvm-plugins=$PLUGIN"
  local bin="$td/$BIN_REL"
  echo "  .text sha256   $(text_hash "$bin")"
  echo "  reports        $(ls "$rd" | wc -l)"

  say "b. the dump must not perturb codegen (normalised code, SPEC.ja.md 5)"
  if [ -f "$BASE_BIN" ]; then
    "$REPO/scripts/norm_code_diff.py" "$BASE_BIN" "$bin" --profdata "$PROFDATA" || true
  else
    echo "  (no $BASE_BIN; run scripts/target_pgo_baseline.sh first)"
  fi

  say "c. correctness"
  run_correctness "$bin" "$OUT/correctness-dump.txt"
  cat "$OUT/correctness-dump.txt"

  do_sites

  # Hand jev_search.py the baseline it would otherwise build for itself: this
  # dump IS that build (same recipe, same plugin, same JEV_MODE=dump), so
  # reusing it saves a build per proposer and guarantees that every proposer
  # resolves its site keys against one and the same dump.
  say "e. baseline directory for scripts/jev_search.py --baseline-dir"
  local bd="$OUT/baseline"
  rm -rf "$bd"; mkdir -p "$bd"
  cp "$bin" "$bd/bin"
  cp -r "$rd" "$bd/reports"
  cp "$OUT/correctness-dump.txt" "$bd/correctness.txt"
  cp "$OUT/build-dump.log" "$bd/build.log"
  python3 - "$bd" <<'PY2'
import hashlib, json, os, sys
bd = sys.argv[1]
b = os.path.join(bd, "bin")
json.dump({"dir": bd, "bin": b,
           "correctness": os.path.join(bd, "correctness.txt"),
           "reports": os.path.join(bd, "reports"),
           "log": os.path.join(bd, "build.log"),
           "bin_sha256": hashlib.sha256(open(b, "rb").read()).hexdigest()},
          open(os.path.join(bd, "baseline.json"), "w"), indent=1)
print("  wrote %s/baseline.json" % bd)
PY2
}

do_sites() {
  say "sites.json: the site list and the frozen loop-site set"
  LOOP_MARKS="$LOOP_MARKS" python3 - "$RD" "$SITES" <<'PY'
import json, os, sys, glob
rd, out = sys.argv[1], sys.argv[2]
keep_marks = os.environ["LOOP_MARKS"].split()
funcs, sites = {}, []
for p in sorted(glob.glob(os.path.join(rd, "*.json"))):
    doc = json.load(open(p))
    for f in doc.get("functions") or []:
        if f.get("mark"):
            funcs.setdefault(f["mark"], []).append(
                {"linkage": f["linkage"], "stage": doc.get("stage"),
                 "inst_count": f.get("inst_count"),
                 "entry_count": f.get("entry_count"),
                 "attributes": f.get("attributes")})
    for s in doc.get("sites") or []:
        if s.get("match") == "loop_in_mark":
            r = dict(s); r["stage"] = doc.get("stage"); r["module_id"] = doc.get("module_id")
            sites.append(r)
# One entry per key; the loop rounds run on the merged-LTO stage.
by_key = {}
for s in sites:
    by_key.setdefault(s["key"], s)
# (1) marks whose hint under test is a loop hint, (2) the hottest key of each.
best = {}
for k, s in by_key.items():
    m = s.get("mark")
    if m not in keep_marks:
        continue
    cur = best.get(m)
    if cur is None or (s.get("hotness") or 0) > (by_key[cur].get("hotness") or 0):
        best[m] = k
selected = sorted(best.values())
doc = {
    "schema_version": 1,
    "target": "hintbench",
    "note": ("Site list for the hint benchmark. `oracle.selected_keys_loop_"
             "hint_kernels` is the frozen loop-site set: the loop of each "
             "kernel whose hint under test is a loop hint (k3, k4, k5, k8). "
             "It is pre-registered in scripts/hintbench_oracle.sh and is the "
             "same for every proposer (SPEC.ja.md 2)."),
    "marks": [{"mark": m, "matched": True, "functions": v,
               "share": 12.5, "reach": 12.5}
              for m, v in sorted(funcs.items())],
    "sites": sorted(by_key.values(), key=lambda s: s["key"]),
    "oracle": {"selected_keys_loop_hint_kernels": selected,
               "selected_keys_topk_per_mark": selected},
    "search": {"max_sites": 40},
}
json.dump(doc, open(out, "w"), indent=1)
print("  marks resolved to a function: %d" % len(funcs))
for m, v in sorted(funcs.items()):
    print("    %-32s %d copies, %s" % (m, len(v), v[0].get("attributes") or "(no attributes)"))
print("  loop_in_mark keys: %d, frozen set: %d" % (len(by_key), len(selected)))
for k, s in sorted(by_key.items()):
    leaf = s.get("leaf") or {}
    print("    %-52s %-30s trip=%s hot=%s vec=%s %s:%s"
          % (k, s.get("mark"), s.get("trip_count"), s.get("hotness"),
             s.get("already_vectorized"), os.path.basename(leaf.get("file") or "?"),
             leaf.get("line")))
print("  wrote %s" % out)
PY
}

do_arms() {
  [ -f "$SITES" ] || { echo "no $SITES: run '$0 dump' first" >&2; exit 2; }
  say "oracle arm count (dry run --- no build, no timing)"
  python3 "$REPO/scripts/jev_search.py" --target hintbench --marks "$MARKS" \
    --sites "$SITES" --site-set oracle.selected_keys_loop_hint_kernels \
    --proposer oracle --out "$REPO/artifacts/hintbench-oracle" \
    --baseline-dir "$OUT/baseline" --dry-run
}

# The plan the smoke test applies: EXPECTED.md's expected winner for every
# kernel at once. It is not a measurement, it is the check that each hint is
# reachable --- that the plugin reports it `consumed` / `attached` and that the
# program still prints the same checksums.
do_smoke() {
  need_plugin
  [ -f "$SITES" ] || { echo "no $SITES: run '$0 dump' first" >&2; exit 2; }
  say "a. build the plan from EXPECTED.md's expected winners"
  local plan="$OUT/plan-smoke.json" rd="$OUT/rep-smoke"
  rm -rf "$rd"; mkdir -p "$rd"
  LOOP_MARKS="$LOOP_MARKS" python3 - "$SITES" "$plan" <<'PY'
import json, sys
sites = json.load(open(sys.argv[1]))
# One hint per kernel, exactly as EXPECTED.md predicts --- section 0, as
# revised by section 4 (decision 77): k2 carries `inline(always)` and k7
# carries `inline(never)`, the two kernels' `inline`/`cold` originals having
# left the vocabulary at v3 because they cannot move a decision under this
# recipe. The two kernels whose expected winner is KEEP_DEFAULT (k4, k5) and
# the control (k8) carry the *challenger* here instead, because the point of
# the smoke test is that the hint is reachable, not that it is good.
fn_attrs = [
    {"fn": "hbkernels::k1_step", "inline": "never"},
    {"fn": "hbkernels::k2_mix", "inline": "always"},
    {"fn": "hbkernels::k6_hot_loop", "align": 64},
    {"fn": "hbkernels::k7_error_path", "inline": "never"},
]
loop_hint = {
    "hbkernels::k3_fill_run": {"unroll_disable": True},
    "hbkernels::k4_count_bytes": {"vectorize_width": 16},
    "hbkernels::k5_mul_reduce": {"interleave_count": 4},
    "hbkernels::k8_scale_add": {"unroll_count": 2},
}
loop_md = []
for s in sites["sites"]:
    frag = loop_hint.get(s.get("mark"))
    if frag and s["key"] in sites["oracle"]["selected_keys_loop_hint_kernels"]:
        loop_md.append(dict({"key": s["key"], "stage": "lto"}, **frag))
json.dump({"schema_version": 1, "plan_id": "hintbench-smoke",
           "fn_attrs": fn_attrs, "loop_md": loop_md},
          open(sys.argv[2], "w"), indent=1)
print("  fn_attrs %d, loop_md %d" % (len(fn_attrs), len(loop_md)))
PY
  cat "$plan"

  say "b. JEV_MODE=apply with that plan"
  local td="$REPO/target-hintbench-smoke"
  JEV_MODE=apply JEV_PLAN="$plan" JEV_PLAN_SHA="$(sha_of "$plan")" \
    JEV_REPORT_DIR="$rd" \
    build_variant "$td" "$OUT/build-smoke.log" "-Zllvm-plugins=$PLUGIN"
  echo "  .text sha256   $(text_hash "$td/$BIN_REL")"

  say "c. outcomes"
  "$REPO/scripts/plugin_report.py" apply "$rd"

  say "d. correctness: the checksums must not move"
  run_correctness "$td/$BIN_REL" "$OUT/correctness-smoke.txt"
  if diff -u "$OUT/correctness-dump.txt" "$OUT/correctness-smoke.txt"; then
    echo "  CHECKSUMS: MATCH"
  else
    echo "  CHECKSUMS: MISMATCH --- a hint changed the program's answer"
  fi
}

do_run() {
  need_plugin
  [ -f "$SITES" ] || { echo "no $SITES: run '$0 dump' first" >&2; exit 2; }
  say "oracle sweep (this one measures)"
  python3 "$REPO/scripts/jev_search.py" --target hintbench --marks "$MARKS" \
    --sites "$SITES" --site-set oracle.selected_keys_loop_hint_kernels \
    --proposer oracle --out "$REPO/artifacts/hintbench-oracle" \
    --baseline-dir "$OUT/baseline" "$@"
}

case "${1:-arms}" in
  dump)  do_dump ;;
  sites) do_sites ;;
  arms)  do_arms ;;
  smoke) do_smoke ;;
  run)   shift; do_run "$@" ;;
  *) echo "usage: $0 [dump|sites|arms|smoke|run]" >&2; exit 2 ;;
esac
