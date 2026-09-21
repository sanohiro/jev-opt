#!/usr/bin/env python3
"""One instrumented profile per pool candidate, reduced to selector features.

Experiment 1 (results.md section 68) ended with "the discriminating feature is
profile shape, and it is observable per-candidate at the same cost". This is
that observation, made once for the whole pool: every candidate is run once
under the frozen instrumented binary with its *own* `LLVM_PROFILE_FILE`, and
the resulting profraw is reduced to a row of features. Experiment 2's
deterministic selectors and the expert arm both choose from these rows, and an
arm's profile is then the `llvm-profdata merge` of the chosen profraws --- no
candidate is ever run twice.

Cost, measured: one run is a few milliseconds and one
`llvm-profdata show --all-functions --counts` straight off the profraw is
17 ms, so the whole 1182-item pool is a couple of minutes. That is the point:
a `jev-opt build` can afford this before it chooses.

Features per candidate
----------------------
  total_count      sum of all block counts in that candidate's profile
  max_block        the largest single block count, and the function holding it
                   (this is what scripts/profdata_sanity.py checks)
  hot20_*          against the reference profile's top 20 functions by max
                   block count --- the same reference set scripts/
                   profdata_cover.py uses. `share` is what ordered the arms in
                   Experiment 1 (results.md section 67).
  layers           block counts split into the crate/layer buckets below
  datapath_startup (hifijson + jaq_json) / (jaq_core::load + jaq_core::compile)

Layer attribution is an *ordered substring match on the demangled name*, first
match wins, because almost every interesting function here is a
monomorphisation carrying several crates in its name. The order splits
`jaq_json::read::parse::<hifijson::SliceLexer>` (json_read: the reader driving
the lexer) from `<hifijson::SliceLexer as ...>::write_until` (hifijson: the
byte loop itself), which results.md section 67's `--grep hifijson` lumped
together at 42.8%; `hifijson + json_read` reproduces that number. `other` is
reported so that anything the rule leaks is visible.

  hifijson      the JSON lexer crate itself (the 22.5% byte-search loop)
  json_read     jaq_json::read (text -> Val), including its lexer instances
  json_write    jaq_json::write, and std's BufWriter (Val -> text)
  json_val      the rest of jaq_json (Val arithmetic, ordering, indexing)
  core_load     jaq_core::load (lex/parse the *filter*, load the stdlib)
  core_compile  jaq_core::compile's Compiler (build the term tree)
  core_run      TermId::run and the rest of jaq_core / jaq_std / jaq_fmts,
                i.e. the interpreter. Note TermId::run *lives in*
                jaq_core::compile, so it is matched before it.
  alloc         mimalloc, alloc::, hashbrown, indexmap
  other         everything else (std, panic machinery, clap, ...)

Usage:
  scripts/jaq_candidate_profile.py \
      --binary target-jaq-pgo-gen/x86_64-unknown-linux-gnu/release/jaq \
      --ref pgo/jaq/merged.profdata \
      --profraw-dir <dir for the 1182 profraws, ~1.9 GB> \
      --out artifacts/jaq-exp2/candidates.jsonl

Python 3 standard library only.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jaq_pool_extract as pool_mod          # noqa: E402  (run_item, load_pool)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# First match wins. See the module docstring for why this is a substring rule.
LAYER_RULES = [
    ("json_read",    ("jaq_json::read",)),
    ("json_write",   ("jaq_json::write", "BufWriter")),
    ("hifijson",     ("hifijson",)),
    ("core_load",    ("jaq_core::load",)),
    ("core_run",     ("TermId::run", "jaq_std", "jaq_core::filter")),
    ("core_compile", ("jaq_core::compile",)),
    ("json_val",     ("jaq_json",)),
    ("core_run2",    ("jaq_core", "jaq_fmts", "jaq_all")),
    ("alloc",        ("mimalloc", "__rust_alloc", "__rust_dealloc",
                      "__rust_realloc", "alloc::", "hashbrown", "indexmap")),
]
LAYERS = ["hifijson", "json_read", "json_write", "json_val",
          "core_load", "core_compile", "core_run", "alloc", "other"]
DATA_LAYERS = ["hifijson", "json_read", "json_write", "json_val"]
START_LAYERS = ["core_load", "core_compile"]


def llvm_profdata_path():
    sysroot = subprocess.run(["rustc", "--print", "sysroot"], check=True,
                             capture_output=True, text=True).stdout.strip()
    triple = re.search(r"^host: (.*)$",
                       subprocess.run(["rustc", "-vV"], check=True,
                                      capture_output=True, text=True).stdout,
                       re.M).group(1)
    return f"{sysroot}/lib/rustlib/{triple}/bin/llvm-profdata"


NAME_RE = re.compile(r"^  (\S.*):$")
COUNTS_RE = re.compile(r"^    Block counts: \[(.*)\]$")


def show_counts(tool, path):
    """{function name -> [block counts]} for a .profraw or a .profdata."""
    out = subprocess.run([tool, "show", "--all-functions", "--counts", path],
                         capture_output=True, text=True, check=True).stdout
    funcs = {}
    name = None
    for line in out.splitlines():
        m = NAME_RE.match(line)
        if m:
            name = m.group(1)
            continue
        m = COUNTS_RE.match(line)
        if m and name is not None:
            funcs[name] = [int(x) for x in m.group(1).split(", ") if x.strip()]
            name = None
    return funcs


def demangle_all(names):
    """mangled -> demangled, one llvm-cxxfilt pass over the whole key set.

    The key set is a property of the instrumented binary, not of a candidate,
    so this is done once and reused for all 1182 rows.
    """
    # "<cgu>;<symbol>" for internal-linkage functions; only the symbol part is
    # manglable.
    syms = [n.split(";")[-1] for n in names]
    out = subprocess.run(["llvm-cxxfilt"], input="\n".join(syms),
                         capture_output=True, text=True, check=True).stdout
    dem = out.splitlines()
    if len(dem) != len(syms):
        sys.exit(f"llvm-cxxfilt returned {len(dem)} lines for {len(syms)}")
    return dict(zip(names, dem))


def layer_of(demangled):
    for layer, needles in LAYER_RULES:
        for nd in needles:
            if nd in demangled:
                return "core_run" if layer == "core_run2" else layer
    return "other"


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--binary", required=True,
                   help="the INSTRUMENTED jaq (-Cprofile-generate)")
    p.add_argument("--ref", required=True,
                   help="reference profdata whose top-N functions are the "
                        "hot set (pgo/jaq/merged.profdata, i.e. T_real)")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--profraw-dir", required=True,
                   help="one <id>.profraw is kept here per candidate; the "
                        "arms are llvm-profdata merges of subsets of these")
    p.add_argument("--out", required=True)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--llvm-profdata", default=None)
    p.add_argument("--limit", type=int, default=0, help="debug: first N only")
    p.add_argument("--progress", action="store_true")
    args = p.parse_args()

    tool = args.llvm_profdata or llvm_profdata_path()
    binary = os.path.abspath(args.binary)
    os.makedirs(args.profraw_dir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    # ---- the reference hot set -------------------------------------------
    ref = show_counts(tool, args.ref)
    ref_sum = {n: sum(c) for n, c in ref.items()}
    ref_total = sum(ref_sum.values())
    hot = sorted(ref, key=lambda n: -(max(ref[n]) if ref[n] else 0))[:args.top]
    hot_set = set(hot)

    names = sorted(ref)
    dem = demangle_all(names)
    layer = {n: layer_of(dem[n]) for n in names}

    meta = {
        "schema_version": 1,
        "kind": "meta",
        "reference": os.path.relpath(os.path.abspath(args.ref), REPO),
        "reference_total_count": ref_total,
        "hot_top": args.top,
        "hot_share_of_reference": sum(ref_sum[n] for n in hot) / ref_total,
        "hot_functions": [
            {"rank": i + 1, "demangled": dem[n], "layer": layer[n],
             "ref_sum": ref_sum[n], "ref_share": ref_sum[n] / ref_total,
             "name": n}
            for i, n in enumerate(hot)],
        "layer_rules": [[k, list(v)] for k, v in LAYER_RULES],
        "instrumented_binary": os.path.relpath(binary, REPO),
    }

    items = [i for i in pool_mod.load_pool()["items"]
             if not i.get("poisons_profile")]
    if args.limit:
        items = items[:args.limit]

    env = dict(os.environ)
    rows = []
    t_start = time.perf_counter()
    for n, it in enumerate(items, 1):
        raw = os.path.join(args.profraw_dir, it["id"] + ".profraw")
        if os.path.exists(raw):
            os.remove(raw)
        env["LLVM_PROFILE_FILE"] = raw
        r = pool_mod.run_item(binary, it, timeout=args.timeout, env=env)
        funcs = show_counts(tool, raw)

        by_layer = dict.fromkeys(LAYERS, 0)
        total = 0
        mx, mx_fn = 0, None
        for fn, counts in funcs.items():
            if not counts:
                continue
            s = sum(counts)
            if s:
                total += s
                by_layer[layer.get(fn) or layer_of(dem.get(fn) or fn)] += s
            m = max(counts)
            if m > mx:
                mx, mx_fn = m, fn
        hot_sum = sum(sum(funcs.get(h, ())) for h in hot)
        hot_zero = sum(1 for h in hot if not sum(funcs.get(h, ())))
        data = sum(by_layer[k] for k in DATA_LAYERS)
        start = sum(by_layer[k] for k in START_LAYERS)

        rows.append({
            "kind": "candidate",
            "id": it["id"], "source": it["source"], "origin": it["origin"],
            "filter": it.get("filter", ""), "argv": it["argv"],
            "input_bytes": it["input_bytes"], "dry_ms": it["dry_ms"],
            "inst_ms": round(r["ms"], 3), "inst_status": r["status"],
            "inst_rc": r["rc"],
            "total_count": total,
            "max_block": mx,
            "max_block_fn": dem.get(mx_fn, mx_fn) if mx_fn else None,
            "hot20_count": hot_sum,
            "hot20_share": hot_sum / total if total else 0.0,
            "hot20_zero": hot_zero,
            "layer_counts": by_layer,
            "layer_share": {k: (by_layer[k] / total if total else 0.0)
                            for k in LAYERS},
            "datapath_count": data, "startup_count": start,
            "datapath_startup": (data / start) if start else float("inf"),
        })
        if args.progress and n % 100 == 0:
            print(f"  {n}/{len(items)}  {time.perf_counter() - t_start:.0f}s",
                  file=sys.stderr, flush=True)

    meta["n_candidates"] = len(rows)
    meta["wall_s"] = time.perf_counter() - t_start
    meta["instrumented_wall_s"] = sum(r["inst_ms"] for r in rows) / 1000.0
    with open(args.out, "w") as fh:
        fh.write(json.dumps(meta) + "\n")
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    bad = [r["id"] for r in rows if r["inst_status"] != "ok"]
    print(f"{args.out}: {len(rows)} candidates, {meta['wall_s']:.1f} s wall "
          f"({meta['instrumented_wall_s']:.1f} s of it inside jaq), "
          f"{len(bad)} did not terminate normally")
    if bad:
        print("  " + " ".join(bad[:20]))


if __name__ == "__main__":
    main()
