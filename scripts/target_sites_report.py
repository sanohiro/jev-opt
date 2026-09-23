#!/usr/bin/env python3
"""Turn a `JEV_MODE=dump` report directory into targets/<t>/sites.{json,md}.

The target-generic successor of scripts/jaq_sites_report.py (which stays as
it is: results.md "Sites (jaq)" quotes its command). Same JSON schema, so
`scripts/jev_search.py --sites ... --site-set DOTTED.PATH` reads the output
unchanged, plus a few per-site fields the driver has since learned to use:

  profile_share   the owning mark's `share` (else `reach`) from the comment
                  block above the mark in the marks file ("# share 12.5%,
                  reach 12.5% (...)"), the same regex jev_search.py's
                  shares_from_marks_file uses. The plugin report carries no
                  per-loop share, so this is a per-mark number repeated on
                  each of the mark's loops; `hot_share` is the loop's own
                  fraction of the summed hotness of all loop_in_mark loops.
  trip            alias of the plugin's `trip_count`.
  ambiguous       key_copies > 1: the key names more than one loop in the
                  dump, so a plan entry on it attaches to all of them. This
                  is the dump-side prediction; the measured verdict is the
                  `ambiguous` outcome of `target_sites.sh allkeys`, recorded
                  as `allkeys_outcome` when --allkeys-reports is given.
  post_vectorize  the plugin's VectorizerEnd record for this key in the same
                  report (plugin/README.md), or null; `vectorized` is its
                  `isvectorized`.

Decision 61 (a) restricts sites to `loop_in_mark`; `mark_in_loop` rows are
carried for the record and never counted.

The loop-site cap is passed in (--cap-rule), never hard-coded. It is a comma
list applied in order, all result-blind and mechanical:

  no_profile      drop keys whose hottest copy has header_count 0 (the
                  training profile never entered the loop)
  trip_lt_2       drop keys whose hottest copy has a profile trip count < 2
                  (trip_lt:N for another bound)
  per_mark:K      keep the top K keys by hotness per owning mark
  top:L           keep the top L keys by hotness overall

The final list is written to `oracle.selected_keys_top<L>` (or
`oracle.selected_keys_capped` without a top:L step) AND to
`oracle.selected_keys_topk_per_mark`, because the driver uses the latter
when --site-set is omitted and it must then get the same set.

No timing is involved anywhere in this script.
"""
import argparse
import collections
import datetime
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jev_vocab as V          # noqa: E402

# Minutes per one-factor arm: planning numbers carried over from
# jaq_sites_report.py, not measurements. Overridable per target.
BUILD_MIN = 2.5
TIME_MIN = 2.0

DEFAULT_CAP_RULE = "no_profile,trip_lt_2,per_mark:2,top:6"

SHARE_RE = re.compile(r"\bshare\s+(\d+(?:\.\d+)?)%")
REACH_RE = re.compile(r"\breach\s+(\d+(?:\.\d+)?)%")


def sha_file(p):
    if not p or not os.path.isfile(p):
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def read_marks(p):
    out = []
    for line in open(p):
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def shares_from_marks_file(p):
    """{mark: {share, reach}}, same rule as jev_search.shares_from_marks_file."""
    out, block = {}, []
    for line in open(p):
        t = line.strip()
        if not t:
            block = []
        elif t.startswith("#"):
            block.append(t)
        else:
            text = " ".join(block)
            sh, re_ = SHARE_RE.search(text), REACH_RE.search(text)
            if sh or re_:
                out[t] = {"share": float(sh.group(1)) if sh else None,
                          "reach": float(re_.group(1)) if re_ else None}
            block = []
    return out


def crate_of(module_id):
    return (module_id or "").split(".")[0]


def load(reports):
    files = sorted(glob.glob(os.path.join(reports, "*.json")))
    if not files:
        sys.exit(f"no reports in {reports}")
    return [(os.path.basename(f), json.load(open(f))) for f in files]


def allkeys_outcomes(d):
    """{key: merged verdict} from an allkeys apply report dir (plugin_report
    apply's rule: unmatched only if no module resolved it)."""
    merged = collections.defaultdict(list)
    for _, rep in load(d):
        for r in rep.get("results", []):
            if r.get("key"):
                merged[r["key"]].append(r["outcome"])
    out = {}
    for k, oc in merged.items():
        real = sorted({o for o in oc if o != "unmatched"})
        out[k] = "+".join(real) if real else "unmatched"
    return out


def parse_cap_rule(rule):
    steps = []
    for tok in [t.strip() for t in rule.split(",") if t.strip()]:
        name, _, arg = tok.partition(":")
        if name == "no_profile" and not arg:
            steps.append(("no_profile", None))
        elif name == "trip_lt_2" and not arg:
            steps.append(("trip_lt", 2.0))
        elif name == "trip_lt" and arg:
            steps.append(("trip_lt", float(arg)))
        elif name in ("per_mark", "top") and arg.isdigit() and int(arg) > 0:
            steps.append((name, int(arg)))
        else:
            sys.exit(f"--cap-rule: bad step {tok!r} (have no_profile, "
                     f"trip_lt_2, trip_lt:N, per_mark:K, top:L)")
    return steps


def select_vocab(requested):
    try:
        return V.set_version(requested), requested, None
    except ValueError as e:
        note = (f"vocabulary {requested} is not defined in scripts/"
                f"jev_vocab.py ({e}); cost sums use v5 instead")
        print("[note] " + note, file=sys.stderr)
        return V.set_version("v5"), "v5", note


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--target", required=True)
    ap.add_argument("--marks", required=True)
    ap.add_argument("--reports", required=True,
                    help="JEV_MODE=dump report directory")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--profdata", default="")
    ap.add_argument("--src-dir", default="",
                    help="target source checkout, for `git rev-parse HEAD`")
    ap.add_argument("--vocab", default="v6",
                    help="vocabulary whose candidates price the sweep "
                         "(falls back to v5 if not defined)")
    ap.add_argument("--cap-rule", default=DEFAULT_CAP_RULE)
    ap.add_argument("--allkeys-reports", default="",
                    help="report dir of `target_sites.sh allkeys` (optional)")
    ap.add_argument("--plugin", default="plugin/build/libjevplugin.so")
    ap.add_argument("--plugin-src", default="plugin/jev/jev.cpp")
    ap.add_argument("--flags", default="",
                    help="\\x1f-separated CARGO_ENCODED_RUSTFLAGS")
    ap.add_argument("--flags-sha", default="")
    ap.add_argument("--baseline-text-sha", default="")
    ap.add_argument("--baseline-norm-hash", default="")
    ap.add_argument("--dump-text-sha", default="")
    ap.add_argument("--outputs", default="",
                    help="correctness file: one `name sha256` line per case")
    ap.add_argument("--build-min", type=float, default=BUILD_MIN)
    ap.add_argument("--time-min", type=float, default=TIME_MIN)
    args = ap.parse_args()

    vocab_id, vocab_used, vocab_note = select_vocab(args.vocab)
    fn_cands = [c for c in V.candidates_for("fn") if c != V.KEEP_DEFAULT]
    loop_cands = [c for c in V.candidates_for("loop") if c != V.KEEP_DEFAULT]
    cap_steps = parse_cap_rule(args.cap_rule)

    marks = read_marks(args.marks)
    shares = shares_from_marks_file(args.marks)
    reps = load(args.reports)
    ak = allkeys_outcomes(args.allkeys_reports) if args.allkeys_reports else {}

    # ---- mark resolution ------------------------------------------------
    unmatched = None
    for _, r in reps:
        if r.get("loop_ep_ran"):
            u = set(r.get("unmatched_marks") or [])
            unmatched = u if unmatched is None else (unmatched & u)
    unmatched = sorted(unmatched or [])

    fnrows = collections.defaultdict(list)
    for _, r in reps:
        for fn in r.get("functions", []):
            fnrows[fn["mark"]].append({
                "linkage": fn["linkage"],
                "demangled": fn.get("demangled"),
                "stage": r.get("stage"),
                "module_id": r.get("module_id"),
                "crate": crate_of(r.get("module_id")),
                "inst_count": fn.get("inst_count"),
                "entry_count": fn.get("entry_count"),
                "attributes": fn.get("attributes"),
                "loops": fn.get("n_loops", fn.get("self_loops")),
            })

    def mark_share(m):
        s = shares.get(m) or {}
        return s.get("share") if s.get("share") is not None else s.get("reach")

    # ---- sites ----------------------------------------------------------
    sites, other = [], []
    for _, r in reps:
        pv = r.get("post_vectorize") or {}
        for s in r.get("sites", []):
            row = dict(s)
            row["stage"] = r.get("stage")
            row["module_id"] = r.get("module_id")
            if s.get("match") != "loop_in_mark":
                row["inline_chain_len"] = len(row.pop("inline_chain", []) or [])
                other.append(row)
                continue
            p = pv.get(s["key"])
            row["post_vectorize"] = p
            row["vectorized"] = None if p is None else p.get("isvectorized")
            row["trip"] = s.get("trip_count")
            row["profile_share"] = mark_share(s.get("mark"))
            sites.append(row)

    keycount = collections.Counter(s["key"] for s in sites)
    hot_total = sum(s.get("hotness") or 0 for s in sites) or 0
    for s in sites:
        s["key_copies"] = keycount[s["key"]]
        s["key_unique"] = keycount[s["key"]] == 1
        s["ambiguous"] = keycount[s["key"]] > 1
        s["hot_share"] = ((s.get("hotness") or 0) / hot_total
                          if hot_total else None)
        if ak:
            s["allkeys_outcome"] = ak.get(s["key"])
    sites.sort(key=lambda s: (-(s.get("hotness") or 0), s["key"]))

    def flags_of(s):
        why = []
        if not s["key_unique"]:
            why.append("shared_key")
        if (s.get("header_count") or 0) == 0:
            why.append("no_profile")
        if s.get("trip_count") is not None and s["trip_count"] < 2:
            why.append("trip_lt_2")
        if s.get("already_vectorized"):
            why.append("already_vectorized")
        if s.get("vectorized"):
            why.append("vectorized_post")
        return why

    for s in sites:
        s["flags"] = flags_of(s)

    per_mark = collections.Counter(s["mark"] for s in sites)
    in_chain = collections.Counter()
    for s in sites:
        for m in s.get("marks_in_chain", []):
            in_chain[m] += 1
    per_mark_other = collections.Counter(s["mark"] for s in other)

    # ---- the cap (pre-registered, result-blind) -------------------------
    n_fn = len(marks) - len(unmatched)
    distinct = sorted({s["key"] for s in sites})
    unique_keys = sorted({s["key"] for s in sites if s["key_unique"]})
    best = {}
    for s in sites:                       # hotness-sorted: first is hottest
        best.setdefault(s["key"], s)

    def hot(k):
        return (-(best[k].get("hotness") or 0), k)

    FN_BUILDS = n_fn * len(fn_cands)

    def cost(n):
        b = FN_BUILDS + n * len(loop_cands) + 1
        return b, b * (args.build_min + args.time_min) / 60.0

    steps = [("every loop site its own arm (upper bound; a plan addresses "
              "keys)", len(sites)),
             ("one arm per distinct site key", len(distinct))]
    kept = sorted(distinct, key=hot)
    top_l = None
    for name, arg in cap_steps:
        if name == "no_profile":
            kept = [k for k in kept if (best[k].get("header_count") or 0) > 0]
            label = "drop keys the training profile never entered"
        elif name == "trip_lt":
            kept = [k for k in kept if best[k].get("trip_count") is None
                    or best[k]["trip_count"] >= arg]
            label = f"drop trip count < {arg:g}"
        elif name == "per_mark":
            seen = collections.Counter()
            nk = []
            for k in kept:
                m = best[k].get("mark")
                if seen[m] < arg:
                    nk.append(k)
                    seen[m] += 1
            kept = nk
            label = f"top {arg} by hotness per mark"
        else:
            kept = kept[:arg]
            top_l = arg
            label = f"top {arg} by hotness overall"
        steps.append((label, len(kept)))
    selected = sorted(kept)
    field = f"selected_keys_top{top_l}" if top_l else "selected_keys_capped"
    table = [(label, n) + cost(n) for label, n in steps]

    outputs = {}
    if args.outputs and os.path.exists(args.outputs):
        for line in open(args.outputs):
            p = line.split()
            if len(p) == 2:
                outputs[p[0]] = p[1]

    commit = ""
    if args.src_dir:
        commit = subprocess.run(["git", "-C", args.src_dir, "rev-parse",
                                 "HEAD"], capture_output=True,
                                text=True).stdout.strip()
    basis = {
        "profdata": args.profdata,
        "profdata_sha256": sha_file(args.profdata),
        "fixed_flags": args.flags.split("\x1f") if args.flags else [],
        "fixed_flags_sha256": args.flags_sha,
        "plugin_sha256": sha_file(args.plugin),
        "plugin_source_sha256": sha_file(args.plugin_src),
        "marks_sha256": sha_file(args.marks),
        "n_marks": len(marks),
        "rustc": subprocess.run(["rustc", "-vV"], capture_output=True,
                                text=True).stdout.split("\n")[0],
        "target_commit": commit,
        "src_dir": args.src_dir,
        "reports": args.reports,
        "baseline": {
            "text_sha256": args.baseline_text_sha,
            "norm_code_hash": args.baseline_norm_hash,
            "dump_build_text_sha256": args.dump_text_sha,
            "outputs": outputs,
        },
        "note": ("fixed_flags is the \\x1f-separated CARGO_ENCODED_RUSTFLAGS "
                 "build_variant assembles for this target "
                 "(scripts/target_sites.sh flags); fixed_flags_sha256 is the "
                 "sha256 of that string as rustc receives it. A null sha "
                 "means the file was absent when this ran."),
    }

    doc = {
        "schema_version": 1,
        "target": args.target,
        "generated_utc": datetime.datetime.now(datetime.timezone.utc)
                                  .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "scripts/target_sites_report.py",
        "basis": basis,
        "marks": [{
            "index": i + 1,
            "mark": m,
            "matched": m not in unmatched,
            "share": (shares.get(m) or {}).get("share"),
            "reach": (shares.get(m) or {}).get("reach"),
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
            "already_vectorized": sum(1 for s in sites
                                      if s.get("already_vectorized")),
            "vectorized_post": sum(1 for s in sites if s.get("vectorized")),
            "no_post_vectorize": sum(1 for s in sites
                                     if s["post_vectorize"] is None),
            "no_profile": sum(1 for s in sites
                              if (s.get("header_count") or 0) == 0),
            "trip_lt_2": sum(1 for s in sites if s.get("trip_count") is not None
                             and s["trip_count"] < 2),
            "has_calls": sum(1 for s in sites if s.get("has_calls")),
            "has_fp_reduction": sum(1 for s in sites
                                    if s.get("has_fp_reduction")),
        },
        "oracle": {
            "vocab_requested": args.vocab,
            "vocab_used": vocab_used,
            "vocab_version": vocab_id,
            "vocab_note": vocab_note,
            "fn_candidates": fn_cands,
            "loop_candidates": loop_cands,
            "marked_functions": n_fn,
            "build_minutes": args.build_min,
            "timing_minutes": args.time_min,
            "fn_attr_builds": FN_BUILDS,
            "cap_rule": args.cap_rule,
            "steps": [{"rule": l, "loop_sites": n, "builds": b, "hours": h}
                      for l, n, b, h in table],
            field: selected,
            "selected_keys_topk_per_mark": selected,
            "selected_keys_note": (
                f"`{field}` is the result of cap_rule; "
                "`selected_keys_topk_per_mark` is the same list, because "
                "jev_search.py uses that field when --site-set is omitted."),
        },
    }
    if ak:
        doc["totals"]["allkeys_outcomes"] = dict(collections.Counter(
            ak.values()))
    with open(args.out_json, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")

    # ---- markdown -------------------------------------------------------
    def short(s, n=58):
        return s if len(s) <= n else s[:n - 1] + "…"

    def pct(x):
        return "-" if x is None else f"{x:g}%"

    o = []
    w = o.append
    w(f"# {args.target} optimization sites\n")
    w("Generated by `scripts/target_sites_report.py` from a `JEV_MODE=dump` "
      "build (`scripts/target_sites.sh dump`). Nothing here is a timing "
      "measurement.\n")
    w("## Basis\n")
    w("| item | value |")
    w("|---|---|")
    w(f"| marks | `{args.marks}` sha256 `{(basis['marks_sha256'] or '-')[:16]}` "
      f"({len(marks)} marks) |")
    w(f"| profdata | `{args.profdata or '-'}` sha256 "
      f"`{(basis['profdata_sha256'] or 'absent')[:16]}` |")
    w(f"| fixed flags | sha256 `{(basis['fixed_flags_sha256'] or '-')[:16]}` |")
    w(f"| plugin | sha256 `{(basis['plugin_sha256'] or 'absent')[:16]}`, "
      f"source sha256 `{(basis['plugin_source_sha256'] or 'absent')[:16]}` |")
    w(f"| rustc | {basis['rustc']} |")
    w(f"| {args.target} source | `{commit or '-'}` |")
    w(f"| baseline `.text` | `{args.baseline_text_sha or '-'}` |")
    w(f"| dump-build `.text` | `{args.dump_text_sha or '-'}` |")
    w(f"| vocabulary | {vocab_used} (`{vocab_id}`), requested {args.vocab} |")
    w("")
    if vocab_note:
        w(f"Note: {vocab_note}.\n")
    if basis["fixed_flags"]:
        w("`fixed_flags` (from `scripts/target_sites.sh flags`):\n")
        for f in basis["fixed_flags"]:
            w(f"    {f}")
        w("")
    if outputs:
        w("Baseline output checksums:\n")
        for k in sorted(outputs):
            w(f"    {k:24s} {outputs[k]}")
        w("")

    w("## Marks\n")
    w("`share`/`reach` are read from the marks file's comment block. `fns` "
      "counts function-table rows, `link` the distinct linkage names. "
      "`owned` is the `loop_in_mark` sites owned by the mark, `chain` those "
      "reaching it anywhere in the inline chain, `m_in_l` the excluded "
      "`mark_in_loop` rows.\n")
    w("| # | share | reach | fns | link | owned | chain | m_in_l | mark |")
    w("|--:|--:|--:|--:|--:|--:|--:|--:|---|")
    for i, m in enumerate(marks, 1):
        rows = fnrows.get(m, [])
        sh = shares.get(m) or {}
        w(f"| {i} | {pct(sh.get('share'))} | {pct(sh.get('reach'))} | "
          f"{len(rows)} | {len({r['linkage'] for r in rows})} | "
          f"{per_mark.get(m, 0)} | {in_chain.get(m, 0)} | "
          f"{per_mark_other.get(m, 0)} | `{short(m, 64)}` |")
    w("")
    w(f"Unmatched marks: **{len(unmatched)}**"
      + (" (" + ", ".join(f"`{u}`" for u in unmatched) + ")" if unmatched
         else " --- every mark resolved."))
    w("")

    t = doc["totals"]
    w("## Loop sites (`loop_in_mark` only, decision 61 (a))\n")
    w(f"- **{t['loop_in_mark_sites']} sites** behind **{t['distinct_keys']} "
      f"distinct keys**; {t['shared_keys']} keys name more than one loop "
      f"({t['loops_behind_shared_keys']} loops) and are `ambiguous`.")
    w(f"- no profile count: **{t['no_profile']}**; trip < 2: "
      f"**{t['trip_lt_2']}**; contains a call: **{t['has_calls']}**; FP "
      f"reduction: **{t['has_fp_reduction']}**.")
    w(f"- vectorized after LoopVectorize (`post_vectorize`): "
      f"**{t['vectorized_post']}**; no `post_vectorize` record: "
      f"**{t['no_post_vectorize']}**.")
    if ak:
        w(f"- allkeys apply outcomes: " + ", ".join(
            f"{k}={v}" for k, v in sorted(t["allkeys_outcomes"].items())))
    w(f"- excluded `mark_in_loop` rows: **{t['mark_in_loop_sites']}**.")
    w("")
    w("### Keys by hotness (hottest copy per key, at most 40)\n")
    w("`hot` is header count x body instructions; `hot%` the loop's share of "
      "all loop_in_mark hotness; `share` the owning mark's profile share; "
      "`vec` post-vectorize width (`-` if not vectorized); `sel` marks the "
      "capped set.\n")
    w("| key | mark | leaf | d | trip | hot | hot% | share | cp | vec | sel |")
    w("|---|--:|---|--:|--:|--:|--:|--:|--:|--:|:-:|")
    for k in sorted(distinct, key=hot)[:40]:
        s = best[k]
        leaf = s.get("leaf") or {}
        leaf = f"{os.path.basename(leaf.get('file') or '?')}:{leaf.get('line')}"
        trip = "-" if s.get("trip_count") is None else f"{s['trip_count']:.1f}"
        hs = "-" if s["hot_share"] is None else f"{100 * s['hot_share']:.2f}"
        vec = (s["post_vectorize"] or {}).get("vector_width") \
            if s.get("vectorized") else None
        mi = marks.index(s["mark"]) + 1 if s.get("mark") in marks else "?"
        w(f"| `{k}` | {mi} | {leaf} | {s.get('depth')} | {trip} | "
          f"{(s.get('hotness') or 0):.3g} | {hs} | "
          f"{pct(s['profile_share'])} | {s['key_copies']} | "
          f"{vec if vec else '-'} | {'y' if k in selected else ''} |")
    w("")
    w("## Loop-site cap and oracle sizing (SPEC.ja.md 2)\n")
    w(f"Cap rule (pre-registered, result-blind): `{args.cap_rule}`. "
      f"Selected **{len(selected)}** keys -> `oracle.{field}` (and "
      f"`oracle.selected_keys_topk_per_mark`).\n")
    w(f"One-factor sweep: `sum(sites x candidates) + 1`, with "
      f"{len(fn_cands)} function candidates on each of {n_fn} marked "
      f"functions and {len(loop_cands)} loop candidates per loop site "
      f"(vocabulary {vocab_used}), at {args.build_min} + {args.time_min} min "
      f"per arm (planning numbers).\n")
    w("| rule (cumulative) | loop sites | builds | wall clock |")
    w("|---|--:|--:|--:|")
    for label, n, b, h in table:
        w(f"| {label} | {n} | {b} | {h:.1f} h |")
    w("")
    w("Selected keys:\n")
    for k in selected:
        w(f"    {k}  ({best[k].get('mark')})")
    w("")
    open(args.out_md, "w").write("\n".join(o) + "\n")
    print(f"sites.json -> {args.out_json}")
    print(f"sites.md   -> {args.out_md}")
    print(f"distinct keys {len(distinct)}, selected {len(selected)} "
          f"({field}, rule {args.cap_rule})")


if __name__ == "__main__":
    main()
