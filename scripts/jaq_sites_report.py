#!/usr/bin/env python3
"""Turn a `JEV_MODE=dump` report directory into targets/jaq/sites.{json,md}.

This is the CLI half of SPEC.ja.md 1 (1): the plugin dumps, and the list of
things Jev will be asked about is decided here. Decision 61 (a) restricts
that list to `loop_in_mark` --- the loops inside a marked function --- so
`mark_in_loop` rows are carried in the JSON for the record and are never
counted as sites.

It also does the oracle arithmetic of SPEC.ja.md 2: the one-factor sweep is
sum(sites x candidates) + 1 builds, and that number decides whether the
oracle arm is affordable before any of it is run.

Usage:
  scripts/jaq_sites_report.py --reports artifacts/jaq-sites/rep-dump \\
      --marks targets/jaq/jev-marks.txt \\
      --json targets/jaq/sites.json --md targets/jaq/sites.md \\
      [--flags-sha <sha>] [--baseline-text-sha <sha>] ...

No timing is involved anywhere in this script.
"""
import argparse
import collections
import datetime
import glob
import hashlib
import json
import os
import subprocess
import sys

# SPEC.ja.md 1 (2). Frozen before round 1 and not extended here: this script
# only counts them.
FN_CANDIDATES = ["inline", "inline(never)", "cold", "align=16", "align=32",
                 "align=64"]
LOOP_CANDIDATES = ["unroll.count=2", "unroll.count=4", "unroll.count=8",
                   "unroll.disable",
                   "vectorize.width=2", "vectorize.width=4",
                   "vectorize.width=8", "vectorize.width=16",
                   "interleave.count=1", "interleave.count=2",
                   "interleave.count=4"]

# Minutes per one-factor arm: a clean fat-LTO + PGO jaq build plus one timing
# block (n=15, warmup 3, three cases). Both are the brief's planning numbers,
# not measurements taken here.
BUILD_MIN = 2.5
TIME_MIN = 2.0


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def read_marks(p):
    out = []
    for line in open(p):
        line = line.rstrip("\n").rstrip()
        b = len(line) - len(line.lstrip(" \t"))
        line = line[b:]
        if not line or line[0] == "#":
            continue
        out.append(line)
    return out


def crate_of(module_id):
    """`jaq_json.fd679680fd5ee196-cgu.0` -> `jaq_json`."""
    return module_id.split(".")[0]


def load(reports):
    files = sorted(glob.glob(os.path.join(reports, "*.json")))
    if not files:
        sys.exit(f"no reports in {reports}")
    return [(os.path.basename(f), json.load(open(f))) for f in files]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", required=True)
    ap.add_argument("--marks", required=True)
    ap.add_argument("--json", required=True)
    ap.add_argument("--md", required=True)
    ap.add_argument("--profdata", default="pgo/jaq/merged.profdata")
    ap.add_argument("--plugin", default="plugin/build/libjevplugin.so")
    ap.add_argument("--plugin-src", default="plugin/jev/jev.cpp")
    ap.add_argument("--flags-sha", default="")
    ap.add_argument("--flags", default="")
    ap.add_argument("--baseline-text-sha", default="")
    ap.add_argument("--baseline-norm-hash", default="")
    ap.add_argument("--dump-text-sha", default="")
    ap.add_argument("--outputs", default="",
                    help="correctness file: one `name sha256` line per case")
    ap.add_argument("--topk", type=int, default=3,
                    help="K for the pre-registered per-mark hotness cap")
    args = ap.parse_args()

    marks = read_marks(args.marks)
    reps = load(args.reports)

    # ---- mark resolution ------------------------------------------------
    # A mark is unmatched only if every report that reached the loop
    # extension point says so (plugin/README.md).
    unmatched = None
    for _, r in reps:
        if r["loop_ep_ran"]:
            u = set(r["unmatched_marks"])
            unmatched = u if unmatched is None else (unmatched & u)
    unmatched = sorted(unmatched or [])

    fnrows = collections.defaultdict(list)
    for name, r in reps:
        for fn in r.get("functions", []):
            fnrows[fn["mark"]].append({
                "linkage": fn["linkage"],
                "demangled": fn["demangled"],
                "stage": r["stage"],
                "module_id": r["module_id"],
                "crate": crate_of(r["module_id"]),
                "inst_count": fn["inst_count"],
                "entry_count": fn.get("entry_count"),
                "attributes": fn["attributes"],
                "loops": fn.get("n_loops", fn.get("self_loops")),
            })

    # ---- sites ----------------------------------------------------------
    sites, other = [], []
    for name, r in reps:
        for s in r.get("sites", []):
            row = dict(s)
            row["stage"] = r["stage"]
            row["module_id"] = r["module_id"]
            if s["match"] != "loop_in_mark":
                # Excluded by decision 61 (a); kept for the record, but the
                # mangled inline chain is the bulk of the file and nothing
                # reads it for a row that is not a site.
                row["inline_chain_len"] = len(row.pop("inline_chain"))
            (sites if s["match"] == "loop_in_mark" else other).append(row)

    keycount = collections.Counter(s["key"] for s in sites)
    for s in sites:
        # A plan entry names a key, not a loop. When a key resolves to
        # more than one loop the plugin attaches the hint to all of them
        # and reports the key `ambiguous` as well (measured on jaq: 13
        # keys, 35 loops, results.md "Sites (jaq)"). A colliding key is
        # still one arm of the sweep --- an arm that moves several loops at
        # once and cannot separate them.
        s["key_copies"] = keycount[s["key"]]
        s["key_unique"] = keycount[s["key"]] == 1
    sites.sort(key=lambda s: -(s["hotness"] or 0))

    def flags_of(s):
        """Mechanical properties a pre-registered cap may key on."""
        why = []
        if not s["key_unique"]:
            why.append("shared_key")
        if (s["header_count"] or 0) == 0:
            why.append("no_profile")
        if s["trip_count"] is not None and s["trip_count"] < 2:
            why.append("trip_lt_2")
        if s["already_vectorized"]:
            why.append("already_vectorized")
        return why

    for s in sites:
        s["flags"] = flags_of(s)

    per_mark = collections.Counter(s["mark"] for s in sites)
    in_chain = collections.Counter()
    for s in sites:
        for m in s.get("marks_in_chain", []):
            in_chain[m] += 1
    per_mark_other = collections.Counter(s["mark"] for s in other)

    # ---- oracle arithmetic ----------------------------------------------
    n_fn = len(marks) - len(unmatched)
    distinct = sorted({s["key"] for s in sites})
    unique_keys = sorted({s["key"] for s in sites if s["key_unique"]})

    FN_BUILDS = n_fn * len(FN_CANDIDATES)

    def cost(n_loop_sites):
        builds = FN_BUILDS + n_loop_sites * len(LOOP_CANDIDATES) + 1
        return builds, builds * (BUILD_MIN + TIME_MIN) / 60.0

    # Pre-registered, mechanical reductions. Cumulative, in this order, and
    # none of them looks at a measured result.
    keep = {k: True for k in distinct}
    best = {}
    for s in sites:                       # sites are hotness-sorted
        if s["key"] not in best:
            best[s["key"]] = s
    steps = []
    steps.append(("every loop site its own arm (upper bound; unreachable, "
                  "because a plan addresses keys)", len(sites)))
    steps.append(("one arm per distinct site key", len(distinct)))
    for k in distinct:
        if keep[k] and (best[k]["header_count"] or 0) == 0:
            keep[k] = False
    steps.append(("drop sites the training profile never entered",
                  sum(keep.values())))
    for k in distinct:
        t = best[k]["trip_count"]
        if keep[k] and t is not None and t < 2:
            keep[k] = False
    steps.append(("drop trip count < 2", sum(keep.values())))
    kept_keys = [k for k in distinct if keep[k]]
    bymark = collections.defaultdict(list)
    for k in kept_keys:
        bymark[best[k]["mark"]].append(k)
    capped = []
    for m, ks in bymark.items():
        ks.sort(key=lambda k: -(best[k]["hotness"] or 0))
        capped += ks[:args.topk]
    steps.append((f"top {args.topk} by hotness per mark", len(capped)))
    # An alternative to the per-mark cap, offered because three marks own no
    # loop site at all and a per-mark K spends its budget unevenly.
    overall = sorted(kept_keys, key=lambda k: -(best[k]["hotness"] or 0))
    alt = [(f"top {n} by hotness overall (alternative to the per-mark cap)",
            min(n, len(overall))) for n in (20, 12)]

    table = [(label, n) + cost(n) for label, n in steps]
    alt_table = [(label, n) + cost(n) for label, n in alt]

    outputs = {}
    if args.outputs and os.path.exists(args.outputs):
        for line in open(args.outputs):
            p = line.split()
            if len(p) == 2:
                outputs[p[0]] = p[1]

    basis = {
        "profdata_sha256": sha_file(args.profdata),
        "fixed_flags": args.flags.split("\x1f") if args.flags else [],
        "fixed_flags_sha256": args.flags_sha,
        "plugin_sha256": sha_file(args.plugin),
        "plugin_source_sha256": sha_file(args.plugin_src),
        "marks_sha256": sha_file(args.marks),
        "n_marks": len(marks),
        "rustc": subprocess.run(["rustc", "-vV"], capture_output=True,
                                text=True).stdout.split("\n")[0],
        "jaq_commit": subprocess.run(
            ["git", "-C", "targets/jaq/src", "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip(),
        "baseline": {
            "text_sha256": args.baseline_text_sha,
            "norm_code_hash": args.baseline_norm_hash,
            "dump_build_text_sha256": args.dump_text_sha,
            "outputs": outputs,
        },
        "note": ("fixed_flags is the \\x1f-separated CARGO_ENCODED_RUSTFLAGS "
                 "build_variant assembles for TARGET=jaq with no extra knobs "
                 "(scripts/jaq_sites.sh flags); fixed_flags_sha256 is the "
                 "sha256 of that string as rustc receives it."),
    }

    doc = {
        "schema_version": 1,
        "target": "jaq",
        "generated_utc": datetime.datetime.now(datetime.timezone.utc)
                                  .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "basis": basis,
        "marks": [{
            "index": i + 1,
            "mark": m,
            "matched": m not in unmatched,
            "functions": fnrows.get(m, []),
            "n_function_rows": len(fnrows.get(m, [])),
            "n_linkage_names": len({f["linkage"] for f in fnrows.get(m, [])}),
            "n_sites_owned": per_mark.get(m, 0),
            "n_sites_in_chain": in_chain.get(m, 0),
            "n_mark_in_loop": per_mark_other.get(m, 0),
        } for i, m in enumerate(marks)],
        "unmatched_marks": unmatched,
        "sites": sites,
        "mark_in_loop_sites": other,
        "totals": {
            "loop_in_mark_sites": len(sites),
            "distinct_keys": len(distinct),
            "unique_keys": len(unique_keys),
            "shared_keys": len(distinct) - len(unique_keys),
            "loops_behind_shared_keys": sum(1 for s in sites
                                            if not s["key_unique"]),
            "mark_in_loop_sites": len(other),
            "already_vectorized": sum(1 for s in sites if s["already_vectorized"]),
            "no_profile": sum(1 for s in sites if (s["header_count"] or 0) == 0),
            "trip_lt_2": sum(1 for s in sites if s["trip_count"] is not None
                             and s["trip_count"] < 2),
            "has_calls": sum(1 for s in sites if s["has_calls"]),
            "has_fp_reduction": sum(1 for s in sites if s["has_fp_reduction"]),
        },
        "oracle": {
            "fn_candidates": FN_CANDIDATES,
            "loop_candidates": LOOP_CANDIDATES,
            "marked_functions": n_fn,
            "build_minutes": BUILD_MIN,
            "timing_minutes": TIME_MIN,
            "fn_attr_builds": FN_BUILDS,
            "steps": [{"rule": l, "loop_sites": n, "builds": b, "hours": h}
                      for l, n, b, h in table],
            "alternatives": [{"rule": l, "loop_sites": n, "builds": b,
                              "hours": h} for l, n, b, h in alt_table],
            "selected_keys_topk_per_mark": sorted(capped),
            "selected_keys_top20_overall": sorted(overall[:20]),
        },
    }
    with open(args.json, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")

    # ---- markdown -------------------------------------------------------
    def short(s, n=58):
        return s if len(s) <= n else s[:n - 1] + "…"

    o = []
    w = o.append
    w("# jaq optimization sites\n")
    w("Generated by `scripts/jaq_sites_report.py` from a `JEV_MODE=dump` "
      "build (`scripts/jaq_sites.sh dump`). Nothing here is a timing "
      "measurement.\n")
    w("## Basis\n")
    w("| item | value |")
    w("|---|---|")
    w(f"| marks | `{args.marks}` sha256 `{basis['marks_sha256'][:16]}` "
      f"({len(marks)} lines) |")
    w(f"| profdata | `{args.profdata}` sha256 "
      f"`{basis['profdata_sha256'][:16]}` |")
    w(f"| fixed flags | sha256 `{basis['fixed_flags_sha256'][:16]}` |")
    w(f"| plugin | `{args.plugin}` sha256 `{basis['plugin_sha256'][:16]}`, "
      f"source sha256 `{basis['plugin_source_sha256'][:16]}` |")
    w(f"| rustc | {basis['rustc']} |")
    w(f"| jaq | `{basis['jaq_commit']}` |")
    w(f"| baseline `.text` | `{args.baseline_text_sha}` |")
    w(f"| baseline normalised code | `{args.baseline_norm_hash}` |")
    w("")
    w("`fixed_flags` is the `\\x1f`-separated `CARGO_ENCODED_RUSTFLAGS` the "
      "build used, recovered from `build_variant` itself by "
      "`scripts/jaq_sites.sh flags`:\n")
    for f in basis["fixed_flags"]:
        w(f"    {f}")
    w("")
    if outputs:
        w("Baseline output checksums (all six cases):\n")
        for k in sorted(outputs):
            w(f"    {k:20s} {outputs[k]}")
        w("")

    w("## Marks\n")
    w("`fns` counts function-table rows, `link` the distinct linkage names "
      "behind them (monomorphizations; the rest are per-CGU copies of the "
      "same one). `owned` is the `loop_in_mark` sites whose owner is this "
      "mark, `chain` the sites that reach it anywhere in the loop's inline "
      "chain, `m_in_l` the `mark_in_loop` rows decision 61 (a) excludes.\n")
    w("| # | fns | link | insts | entry | owned | chain | m_in_l | mark |")
    w("|--:|--:|--:|--:|--:|--:|--:|--:|---|")
    for i, m in enumerate(marks, 1):
        rows = fnrows.get(m, [])
        lto = [r for r in rows if r["stage"] == "lto"]
        pick = lto or rows
        insts = "/".join(str(r["inst_count"]) for r in sorted(
            {r["linkage"]: r for r in pick}.values(),
            key=lambda r: -r["inst_count"])[:3])
        ent = [r["entry_count"] for r in pick if r["entry_count"] is not None]
        w(f"| {i} | {len(rows)} | {len({r['linkage'] for r in rows})} | "
          f"{insts or '-'} | {max(ent) if ent else '-'} | "
          f"{per_mark.get(m, 0)} | {in_chain.get(m, 0)} | "
          f"{per_mark_other.get(m, 0)} | `{short(m, 64)}` |")
    w("")
    w(f"Unmatched marks: **{len(unmatched)}**"
      + (" (" + ", ".join(f"`{u}`" for u in unmatched) + ")" if unmatched
         else " --- every mark resolved."))
    w("")
    w("Crate and module of each mark's function rows:\n")
    w("| # | stage:module (rows) |")
    w("|--:|---|")
    for i, m in enumerate(marks, 1):
        c = collections.Counter(f"{r['stage']}:{r['crate']}"
                                for r in fnrows.get(m, []))
        w(f"| {i} | " + ", ".join(f"`{k}`x{v}" for k, v in sorted(c.items()))
          + " |")
    w("")

    w("## Loop sites (`loop_in_mark` only, decision 61 (a))\n")
    t = doc["totals"]
    w(f"- **{t['loop_in_mark_sites']} sites** behind "
      f"**{t['distinct_keys']} distinct keys**. {t['shared_keys']} of those "
      f"keys resolve to more than one loop "
      f"({t['loops_behind_shared_keys']} loops between them): the plugin "
      f"attaches the hint to every copy and reports the key `ambiguous` as "
      f"well, so such a key is one arm that moves several loops at once and "
      f"cannot separate them.")
    w(f"- already vectorized at the dump: **{t['already_vectorized']}** "
      f"(the dump runs at `VectorizerStartEP`, before the only LoopVectorize "
      f"run of a fat-LTO build, so this column cannot be anything else).")
    w(f"- no profile count on the header: **{t['no_profile']}** "
      f"(`trip_count` and `hotness` are null/0 for exactly these).")
    w(f"- trip count < 2: **{t['trip_lt_2']}** of the "
      f"{t['loop_in_mark_sites'] - t['no_profile']} that have one.")
    w(f"- contains a call: **{t['has_calls']}**; FP reduction: "
      f"**{t['has_fp_reduction']}**.")
    w(f"- excluded `mark_in_loop` rows: **{t['mark_in_loop_sites']}**.")
    w("")
    w("### Per mark\n")
    w("| # | sites | keys | 1:1 keys | no profile | trip<2 | calls | "
      "depth 1/2/3+ | mark |")
    w("|--:|--:|--:|--:|--:|--:|--:|---|---|")
    for i, m in enumerate(marks, 1):
        ss = [s for s in sites if s["mark"] == m]
        d = collections.Counter(min(s["depth"], 3) for s in ss)
        w(f"| {i} | {len(ss)} | {len({s['key'] for s in ss})} | "
          f"{len({s['key'] for s in ss if s['key_unique']})} | "
          f"{sum(1 for s in ss if (s['header_count'] or 0) == 0)} | "
          f"{sum(1 for s in ss if s['trip_count'] is not None and s['trip_count'] < 2)} | "
          f"{sum(1 for s in ss if s['has_calls'])} | "
          f"{d[1]}/{d[2]}/{d[3]} | `{short(m, 52)}` |")
    w("")
    w("### The 30 hottest keys\n")
    w("One row per key, hottest copy first; `hot` is "
      "`header count x body instructions` (plugin/README.md) and `cp` is "
      "how many loops share the key --- a hint on that key lands on every "
      "one of them, so `sum` is the hotness they hold between them.\n")
    w("| key | mark | leaf | d | trip | insts | hot | sum | cp | calls |")
    w("|---|---|---|--:|--:|--:|--:|--:|--:|:-:|")
    hotsum = collections.Counter()
    for s in sites:
        hotsum[s["key"]] += s["hotness"] or 0
    seen = set()
    for s in sites:
        if s["key"] in seen:
            continue
        seen.add(s["key"])
        if len(seen) > 30:
            break
        leaf = f"{os.path.basename(s['leaf']['file'])}:{s['leaf']['line']}"
        trip = "-" if s["trip_count"] is None else f"{s['trip_count']:.1f}"
        w(f"| `{s['key']}` | {marks.index(s['mark']) + 1} | {leaf} | "
          f"{s['depth']} | {trip} | {s['body_inst_count']} | "
          f"{s['hotness']:.3g} | {hotsum[s['key']]:.3g} | {s['key_copies']} | "
          f"{'y' if s['has_calls'] else ''} |")
    w("")

    w("## Oracle sizing (SPEC.ja.md 2)\n")
    w(f"One-factor sweep: `sum(sites x candidates) + 1`, with "
      f"{len(FN_CANDIDATES)} function-attribute candidates on each of "
      f"{n_fn} marked functions and {len(LOOP_CANDIDATES)} loop candidates "
      f"on each loop site. At {BUILD_MIN} min per fat-LTO + PGO build and "
      f"{TIME_MIN} min of timing (n=15, 3 cases) an arm costs "
      f"{BUILD_MIN + TIME_MIN} min.\n")
    w("| rule (cumulative, pre-registered, result-blind) | loop sites | "
      "builds | wall clock |")
    w("|---|--:|--:|--:|")
    for label, n, b, h in table:
        w(f"| {label} | {n} | {b} | {h:.1f} h |")
    w("")
    w(f"The function-attribute half is fixed at **{FN_BUILDS} builds** "
      f"({FN_BUILDS * (BUILD_MIN + TIME_MIN) / 60.0:.1f} h) whatever the cap "
      f"does, and decision 61 (b) runs it first: the loop keys have to be "
      f"re-dumped from the IR the chosen attributes produced, so the loop "
      f"half of the sweep is priced against a site list that does not exist "
      f"until the attribute phase is over. The counts here are for the "
      f"baseline IR and are the planning number, not a promise.\n")
    w("| alternative cap | loop sites | builds | wall clock |")
    w("|---|--:|--:|--:|")
    for label, n, b, h in alt_table:
        w(f"| {label} | {n} | {b} | {h:.1f} h |")
    w("")
    print(f"sites.json -> {args.json}")
    print(f"sites.md   -> {args.md}")
    open(args.md, "w").write("\n".join(o) + "\n")


if __name__ == "__main__":
    main()
