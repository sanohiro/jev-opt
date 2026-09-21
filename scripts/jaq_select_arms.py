#!/usr/bin/env python3
"""Group the candidate pool, and turn it into Experiment 2's training arms.

Input is scripts/jaq_candidate_profile.py's `candidates.jsonl` (one profile
per pool item) and scripts/jaq_scale_probe.py's `candidates-scaled.jsonl`
(the parametric benches re-run as large as they go). Output is one *arm spec*
per selector: a JSON list of (candidate, stdin) pairs that
scripts/jaq_arm_profile.py merges into a profdata.

Nothing here looks at a holdout, a timing or a built binary: every selector
sees exactly what a `jev-opt build` would see before it chooses.

  groups   the mechanical grouping shared by every selector and, later, by
           Jev: (source, which layers exceed --layer-threshold of that
           candidate's own block counts).

  select   write the arm specs.

    B_cover         greedy weighted set cover, exactly as stated: the
                    universe is the reference profile's top-20 functions,
                    each weighted by its share of the reference, a candidate
                    "covers" a function if its own count on that function is
                    nonzero, and the greedy stops when the marginal gain is
                    below --cover-eps of the total weight or at
                    --cover-max picks.
    B_cover_scaled  the same procedure on the universe where every parametric
                    bench is at its scaled n.
    B_datapath      the --datapath-k candidates with the largest
                    (hifijson + jaq_json) / (jaq_core::load + ::compile),
                    among those whose dry run exited 0. The exit-status
                    filter is hygiene, not tuning: 36 of the literal top 50
                    are pool items that fail immediately (`jaq -1` with an
                    empty filter), whose whole profile is 264 counts of
                    startup teardown and whose startup denominator is
                    therefore 0. A selector that trains on invocations that
                    crashed is not a selector.
    B_shape         the steelman mechanical selector, and the only one that
                    can use the scale knob: greedy maximisation of the
                    histogram intersection between the merged profile's
                    distribution over (top-20 functions + rest) and the
                    reference's. Its universe contains both the repository's
                    n and the scaled n for every parametric bench. Where
                    B_cover asks "is this function ever executed", B_shape
                    asks "is it executed in the right proportion", which is
                    the number that ordered Experiment 1's arms.
    E_expert        the hand-picked set; see EXPERT below. Its reasoning was
                    written into this file before anything was built.
    E_expert_noscale  the same picks at the repository's own n, which is the
                    only pair in the experiment that isolates the scale knob.

Usage:
  scripts/jaq_select_arms.py groups
  scripts/jaq_select_arms.py select --out-dir artifacts/jaq-exp2/arms
"""

import argparse
import collections
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAND = os.path.join(REPO, "artifacts/jaq-exp2/candidates.jsonl")
SCALED = os.path.join(REPO, "artifacts/jaq-exp2/candidates-scaled.jsonl")

LAYERS = ["hifijson", "json_read", "json_write", "json_val",
          "core_load", "core_compile", "core_run", "alloc", "other"]

# ---------------------------------------------------------------------------
# The expert arm. Written down before any Experiment 2 binary was built or
# timed; results.md "Experiment 2 (jaq)" quotes this block verbatim.
#
# What the holdout does: read a 20-25 MiB JSON document, walk every value,
# and (in one of the three cases) write it all back out. In the reference
# profile that is hifijson 27.6% + jaq_json::read 15.3% + jaq_json::write
# 8.3% + Val 20.9% + allocator 11.4%, against jaq_core::load 0.01%.
#
# What the pool offers, from candidates.jsonl:
#
#  1. Exactly one candidate makes jaq parse a large JSON *text*:
#     examples/benches/to-fromjson.jq,
#       [range(.) | tojson] | join(",") | "[" + . + "]" | fromjson
#     It serialises n numbers, concatenates them into one document and parses
#     it back. It is the only pool item whose hifijson count is above 2.2 k
#     (1.9 M at the repository's n = 65536; the runner-up is 2.2 k), and at
#     n = 1048576 it is 531 M counts shaped hifijson 6.7% / read 3.8% /
#     write 1.6% / Val 40.0% / load 0.02%. That is the closest thing to the
#     production shape the repository can produce, and the scale knob is what
#     makes it large enough to dominate a merge. It is pick 1, at the largest
#     n in bench.sh's range.
#
#  2. Everything else in the pool is startup: the median candidate spends 78%
#     of its counts in jaq_core::load + ::compile, i.e. lexing the filter and
#     loading ~200 stdlib definitions, which is 3.3% of production. Adding
#     such items cannot improve the shape, and adding *heavy* ones actively
#     destroys it, because the merge is weighted by absolute counts: the pool
#     without to-fromjson is 5.05e9 counts of interpreter work and would
#     drown pick 1 ten to one. So the expert's second decision is a negative
#     one --- do not add the other 26 benches, and do not scale them.
#
#  3. to-fromjson prints only `length`, so the buffered writer to stdout
#     (BufWriter::write, 1.6% of the reference, the function section 67 saw
#     lose 80% of its instructions) never runs hot. The pool items that do
#     print JSON through it are the doccli/clitest ones that pipe a real JSON
#     producer into jaq. They are ~5 k counts each, i.e. 0.001% of the arm,
#     so they cannot shift a share; they are included as the cheapest
#     available insurance that no hot-set function is left at zero, and the
#     expert's own prediction is that they change nothing.
#
# Total: 10 candidates, one of them scaled. Predicted training wall ~1 s.
# ---------------------------------------------------------------------------
EXPERT = [
    # (id, why)
    ("bench-0022",   "to-fromjson: the only candidate that parses a large "
                     "JSON text; scaled to the top of bench.sh's range"),
    ("clitest-0018", "golden CLI test: object literal in, -c JSON out"),
    ("clitest-0019", "golden CLI test: the same values through --tab"),
    ("clitest-0016", "golden CLI test: JSON in, JSON out"),
    ("clitest-0017", "golden CLI test: JSON in, JSON out"),
    ("doccli-0013",  "docs/cli.dj: a JSON producer piped into jaq"),
    ("doccli-0014",  "docs/cli.dj: a JSON producer piped into jaq"),
    ("doccli-0028",  "docs/formats.dj: a JSON document read from a file"),
    ("doccli-0012",  "docs/cli.dj: JSON in, JSON out"),
    ("doccli-0031",  "docs/formats.dj: JSON in, JSON out"),
]
EXPERT_SCALE = {"bench-0022"}


def load(path, kind):
    rows = [json.loads(l) for l in open(path)]
    assert rows[0]["kind"] == "meta", path
    return rows[0], [r for r in rows[1:] if r["kind"] == kind]


def signature(row, thr):
    return tuple(k for k in LAYERS if row["layer_share"][k] > thr)


def cmd_groups(args):
    meta, cands = load(CAND, "candidate")
    groups = collections.defaultdict(list)
    for r in cands:
        groups[(r["source"], signature(r, args.layer_threshold))].append(r)
    print(f"{len(cands)} candidates, layer threshold "
          f"{100 * args.layer_threshold:.0f}% of the candidate's own counts")
    print(f"{len(groups)} groups\n")
    print(f"{'n':>5s} {'source':9s} {'counts':>12s} {'hot20':>7s} "
          f"{'dp/su':>8s}  layers > threshold")
    rows = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    for (src, sig), rs in rows:
        tot = sum(r["total_count"] for r in rs)
        hot = sum(r["hot20_count"] for r in rs)
        dp = sum(r["datapath_count"] for r in rs)
        su = sum(r["startup_count"] for r in rs)
        print(f"{len(rs):5d} {src:9s} {tot:>12d} {100 * hot / tot:6.2f}% "
              f"{(dp / su if su else float('inf')):8.2f}  "
              f"{' '.join(sig) if sig else '(none above threshold)'}")
        if args.members and len(rs) <= args.members:
            for r in rs:
                print(f"        {r['id']:14s} {r['origin'][:56]}")
    return groups


def greedy_cover(cands, hot, eps, kmax):
    """Weighted set cover; returns (picks, trace)."""
    weight = {h["name"]: h["ref_share"] for h in hot}
    total_w = sum(weight.values())
    covers = {r["id"]: {h["name"] for h in hot
                        if r["hot_counts"].get(h["name"], 0) > 0}
              for r in cands}
    by_id = {r["id"]: r for r in cands}
    done, picks, trace = set(), [], []
    while len(picks) < kmax:
        best, best_gain = None, 0.0
        for cid in sorted(covers):
            g = sum(weight[f] for f in covers[cid] - done)
            # Deterministic tie-break: larger gain, then cheaper to run,
            # then id.
            key = (g, -by_id[cid]["inst_ms"], cid)
            if best is None or key > best[1]:
                best, best_gain = (cid, key), g
        cid = best[0]
        if best_gain < eps * total_w:
            trace.append(f"stop: best marginal gain {100 * best_gain:.4f}pp "
                         f"< {100 * eps * total_w:.4f}pp")
            break
        done |= covers[cid]
        picks.append(cid)
        trace.append(f"{len(picks):2d}. {cid:14s} +{100 * best_gain:6.3f}pp "
                     f"-> {100 * sum(weight[f] for f in done):6.3f}pp of "
                     f"{100 * total_w:.3f}pp, "
                     f"{len(done)}/{len(hot)} functions")
    return picks, trace


def greedy_shape(universe, hot, ref_share, eps, kmax):
    """Greedy histogram intersection against the reference's shape.

    Bins are the reference's top-20 functions plus one "rest" bin, so the
    objective is bounded by 1 and a candidate that is all startup scores
    badly however many counts it brings. The merge is a sum of counts, so
    adding a candidate is exact, not an approximation.
    """
    names = [h["name"] for h in hot]
    ref = [ref_share[n] for n in names]
    ref.append(1.0 - sum(ref))
    by_key = {(r["id"], r.get("scaled_n")): r for r in universe}

    def vec(r):
        v = [r["hot_counts"].get(n, 0) for n in names]
        v.append(max(0, r["total_count"] - sum(v)))
        return v

    vecs = {k: vec(r) for k, r in by_key.items()}

    def score(acc):
        t = sum(acc)
        if not t:
            return 0.0
        return sum(min(a / t, b) for a, b in zip(acc, ref))

    acc = [0] * (len(names) + 1)
    picks, trace, chosen_ids = [], [], set()
    cur = 0.0
    while len(picks) < kmax:
        best, best_s = None, cur
        for k in sorted(vecs, key=lambda k: (k[0], k[1] or 0)):
            if k[0] in chosen_ids:
                continue
            s = score([a + b for a, b in zip(acc, vecs[k])])
            if s > best_s + 1e-15:
                best, best_s = k, s
        if best is None or best_s - cur < eps:
            trace.append(f"stop: best gain {100 * ((best_s - cur) if best else 0):.4f}pp "
                         f"< {100 * eps:.4f}pp  (intersection {100 * cur:.2f}%)")
            break
        acc = [a + b for a, b in zip(acc, vecs[best])]
        chosen_ids.add(best[0])
        picks.append(best)
        trace.append(f"{len(picks):2d}. {best[0]:14s} "
                     f"n={best[1] if best[1] else '-':>8} "
                     f"+{100 * (best_s - cur):6.3f}pp -> intersection "
                     f"{100 * best_s:6.2f}% of the reference shape")
        cur = best_s
    return picks, trace


def hot_counts_for(rows, hot_names, profraw_of):
    """Attach per-candidate counts on the hot set.

    candidates.jsonl stores the aggregate, not the per-function vector, so
    the vector is recomputed from the cached profraw. That is 17 ms each.
    """
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import jaq_candidate_profile as CP
    tool = CP.llvm_profdata_path()
    for r in rows:
        f = CP.show_counts(tool, profraw_of(r))
        r["hot_counts"] = {n: sum(f.get(n, ())) for n in hot_names}
    return rows


def cmd_select(args):
    meta, cands = load(CAND, "candidate")
    smeta, scaled = load(SCALED, "candidate_scaled")
    hot = meta["hot_functions"]
    hot_names = [h["name"] for h in hot]
    by_id = {r["id"]: r for r in cands}
    scaled_by_id = {r["id"]: r for r in scaled}

    def raw_plain(r):
        return os.path.join(args.profraw_dir, r["id"] + ".profraw")

    def raw_scaled(r):
        return os.path.join(args.scaled_profraw_dir,
                            r["id"] + f".n{r['scaled_n']}.profraw")

    os.makedirs(args.out_dir, exist_ok=True)
    specs = {}

    # ---- B_cover -----------------------------------------------------
    hot_counts_for(cands, hot_names, raw_plain)
    picks, trace = greedy_cover(cands, hot, args.cover_eps, args.cover_max)
    print("=== B_cover")
    print("\n".join(trace))
    for i in picks:
        r = by_id[i]
        print(f"     {i:14s} tot={r['total_count']:>10d} "
              f"hot20={100 * r['hot20_share']:5.2f}%  {r['origin'][:48]}")
    specs["B_cover"] = [{"id": i} for i in picks]

    # ---- B_cover_scaled ----------------------------------------------
    universe = [dict(r) for r in cands if r["id"] not in scaled_by_id]
    hot_counts_for(scaled, hot_names, raw_scaled)
    universe += [dict(r) for r in scaled]
    picks_s, trace_s = greedy_cover(universe, hot, args.cover_eps,
                                    args.cover_max)
    print("\n=== B_cover_scaled")
    print("\n".join(trace_s))
    specs["B_cover_scaled"] = [
        {"id": i, "stdin": scaled_by_id[i]["stdin"]} if i in scaled_by_id
        else {"id": i} for i in picks_s]

    # ---- B_shape ------------------------------------------------------
    ref_share = {h["name"]: h["ref_share"] for h in hot}
    picks_h, trace_h = greedy_shape(universe, hot, ref_share,
                                    args.shape_eps, args.cover_max)
    print("\n=== B_shape")
    print("\n".join(trace_h))
    specs["B_shape"] = [
        {"id": i, "stdin": scaled_by_id[i]["stdin"]} if n else {"id": i}
        for i, n in picks_h]

    # ---- B_datapath ---------------------------------------------------
    rc0 = {i["id"] for i in json.load(
        open(os.path.join(REPO, "targets/jaq/pool/pool.json")))["items"]
        if i["dry_rc"] == 0}
    literal = sorted(cands, key=lambda r: (-r["datapath_startup"], r["id"]))
    nbad = sum(1 for r in literal[:args.datapath_k] if r["id"] not in rc0)
    ranked = [r for r in literal if r["id"] in rc0]
    top = ranked[:args.datapath_k]
    print(f"\n=== B_datapath (top {args.datapath_k} by data-path / startup "
          f"among the {len(ranked)} candidates whose dry run exited 0; "
          f"{nbad} of the literal top {args.datapath_k} did not, holding "
          f"{sum(r['total_count'] for r in literal[:args.datapath_k] if r['id'] not in rc0)}"
          f" counts between them)")
    print(f"  training {sum(r['inst_ms'] for r in top) / 1000:.2f} s, "
          f"{sum(r['total_count'] for r in top)} counts")
    for r in top[:12]:
        print(f"  {r['id']:14s} ratio={r['datapath_startup']:10.2f} "
              f"tot={r['total_count']:>10d} hot20={100 * r['hot20_share']:5.2f}%"
              f"  {r['origin'][:44]}")
    print(f"  ... ({len(top)} items)")
    specs["B_datapath"] = [{"id": r["id"]} for r in top]

    # ---- E_expert / E_expert_noscale ----------------------------------
    print("\n=== E_expert")
    exp, exp_ns = [], []
    for cid, why in EXPERT:
        if cid in EXPERT_SCALE:
            s = scaled_by_id[cid]
            exp.append({"id": cid, "stdin": s["stdin"], "why": why})
            print(f"  {cid:14s} n={s['repo_n']} -> {s['scaled_n']}  {why}")
        else:
            exp.append({"id": cid, "why": why})
            print(f"  {cid:14s} {' ' * 18}{why}")
        exp_ns.append({"id": cid, "why": why})
    specs["E_expert"] = exp
    specs["E_expert_noscale"] = exp_ns

    # ---- S_sample1 -----------------------------------------------------
    # Not a pool arm: the one 2 MiB file a user drops into jev-opt/samples/,
    # run with the three Stage 0 filters, one invocation each. Generated by
    # targets/jaq/workloads/gen.py --sample (a seed shared with neither the
    # training nor the holdout inputs).
    sample = "targets/jaq/workloads/sample-objects.json"
    specs["S_sample1"] = [
        {"id": "sample-objsearch", "cwd": ".",
         "argv": ['.[] | select(.k == "v") | .id', sample]},
        {"id": "sample-strproc", "cwd": ".",
         "argv": ["[.[] | .name | ascii_downcase | length] | add", sample]},
        {"id": "sample-readwrite", "cwd": ".", "argv": ["-c", ".", sample]},
    ]
    print(f"\n=== S_sample1: {sample}, the three Stage 0 filters")

    for name, items in specs.items():
        path = os.path.join(args.out_dir, name + ".json")
        with open(path, "w") as fh:
            json.dump({"arm": name, "reference": meta["reference"],
                       "selector": name, "n_items": len(items),
                       "items": items}, fh, indent=1)
        print(f"wrote {os.path.relpath(path, REPO)}  ({len(items)} items)")


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("groups")
    g.add_argument("--layer-threshold", type=float, default=0.05)
    g.add_argument("--members", type=int, default=0,
                   help="also list the members of groups this small")
    g.set_defaults(fn=cmd_groups)
    s = sub.add_parser("select")
    s.add_argument("--out-dir", default="artifacts/jaq-exp2/arms")
    s.add_argument("--profraw-dir", required=True)
    s.add_argument("--scaled-profraw-dir", required=True)
    s.add_argument("--cover-eps", type=float, default=0.01,
                   help="stop when the marginal gain is below this fraction "
                        "of the hot set's total weight (default 1%%)")
    s.add_argument("--cover-max", type=int, default=50)
    s.add_argument("--shape-eps", type=float, default=0.001,
                   help="B_shape stops when one more candidate adds less "
                        "than this to the histogram intersection")
    s.add_argument("--datapath-k", type=int, default=50)
    s.set_defaults(fn=cmd_select)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
