#!/usr/bin/env python3
"""The oracle sweep's arm table, in markdown (results.md "Oracle A (jaq)").

Reads what the run already wrote --- `rounds.jsonl` from
`scripts/jev_search.py --proposer oracle` and the output of
`scripts/norm_code_diff.py baseline/bin round-*/bin --profdata ...` --- and
joins them into one table plus the per-mark summary. It computes nothing
about speed that `bench.py` did not already compute: `ratio`, `ci95` and
`mde` are copied out of the round records.

    scripts/jaq_oracle_table.py --run artifacts/jaq-search/oracle-A \
        --normdiff artifacts/jaq-search/oracle-A/norm-code-diff.txt \
        --mde 0.03 --out docs/experiments/jaq-oracle-A/arms.md
"""

import argparse
import collections
import json
import os
import re

# The short names results.md already uses for jaq's fifteen marks. Matched on
# a distinctive substring of the full mark, so a spelling change in the marks
# file shows up as a missing short name rather than a wrong one.
SHORT = [
    ("jaq_json::read::parse", "read::parse"),
    ("hifijson::token::Lex>::seq", "Lex::seq"),
    ("str::LexWrite>::str_fold", "str_fold"),
    ("write::Write>::write_until", "write_until"),
    ("jaq_core::compile::TermId>::run", "TermId::run"),
    ("jaq_json::write::write", "write::write"),
    ("jaq_json::funs::base<", "funs::base{closure#3}"),
    ("jaq_core::path::Path<jaq_json::Val>>::run::{closure#0}",
     "Path::run{closure#0}"),
    ("default_write_fmt::Adapter", "Adapter::write_str"),
    ("reserve_rehash", "reserve_rehash"),
    ("Rc<indexmap::map::IndexMap", "Rc<IndexMap>::drop_slow"),
    ("jaq_std::base_run<", "base_run{closure#7}"),
    ("jaq_core::path::run", "path::run"),
    ("jaq_json::Val as core::hash::Hash", "Val::hash"),
    ("&alloc::string::String as core::fmt::Display", "String::fmt"),
]


def short(mark):
    for needle, name in SHORT:
        if needle in mark:
            return name
    return mark[:40]


def parse_normdiff(path):
    """{binary path: {identical, changed, share, symbols}} from the tool's output."""
    out, cur = {}, None
    if not path or not os.path.isfile(path):
        return out
    for line in open(path):
        m = re.match(r"^(\S+): hash \S+\s+(IDENTICAL|DIFFERS)\s*$", line)
        if m:
            cur = {"identical": m.group(2) == "IDENTICAL", "changed": None,
                   "share": None, "symbols": None}
            out[os.path.abspath(m.group(1))] = cur
            continue
        m = re.match(r"^\s+symbols: (\d+) \(base \d+\), changed (\d+),", line)
        if m and cur is not None:
            cur["symbols"] = int(m.group(1))
            cur["changed"] = int(m.group(2))
            continue
        m = re.match(r"^\s+profile share held by the changed symbols: "
                     r"([0-9.]+)%", line)
        if m and cur is not None:
            cur["share"] = float(m.group(1))
    return out


def outcome_counts(apply_map, entries):
    c = collections.Counter()
    for e in entries:
        c[(apply_map.get(e) or {"outcome": "no-report"})["outcome"]] += 1
    return ", ".join("%s x%d" % (k, v) for k, v in sorted(c.items())) or "-"


def excl(ci):
    if not ci:
        return "-"
    if ci[0] > 1.0:
        return "yes (+)"
    if ci[1] < 1.0:
        return "yes (-)"
    return "no"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--normdiff", default=None)
    p.add_argument("--layout", default=None,
                   help="layout.json: per round, whether the symbol table "
                        "(addresses and sizes) is identical to the baseline's. "
                        "norm_code_diff.py normalises addresses away, so an "
                        "alignment change is invisible to it; this tells a "
                        "build that changed nothing from one that only moved.")
    p.add_argument("--mde", type=float, default=0.03)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    rows = [json.loads(l) for l in open(os.path.join(args.run, "rounds.jsonl"))
            if l.strip()]
    nd = parse_normdiff(args.normdiff)
    lay = json.load(open(args.layout)) if args.layout else {}

    out = []
    out.append("| arm | mark | candidate | apply | correct | ratio | 95% CI | "
               "CI excludes 1 | changed syms | profile share | build vs baseline |")
    out.append("|---:|---|---|---|---|--:|---|---|--:|--:|---|")
    per_mark = collections.defaultdict(list)
    over, under, ident, one_factor = [], [], [], []
    noop, layout_only = [], []
    for r in rows:
        arm = r.get("arm") or {}
        pa, pb = r.get("phase_a") or {}, r.get("phase_b") or {}
        fn_entries = [e["fn"] for e in (pa.get("fn_attrs") or [])]
        binpath = os.path.abspath(os.path.join(args.run,
                                               "round-%02d" % r["round"], "bin"))
        d = nd.get(binpath, {})
        mark = arm.get("site", "") or ""
        mark = mark[3:] if mark.startswith("fn:") else mark
        name = short(mark) if mark else "(combination)"
        cand = arm.get("candidate") or "-"
        ratio = r.get("ratio")
        ci = r.get("ci95")
        L = lay.get("round-%02d" % r["round"]) or {}
        cat = ("?" if not L else
               ("code changed" if not L["norm_identical"] else
                ("no-op build" if L["layout_same"] else "layout only")))
        out.append("| %d | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                   % (r["round"], name, cand,
                      outcome_counts(pb.get("apply") or {}, fn_entries),
                      "yes" if r.get("correct") else "NO",
                      ("%.4f" % ratio) if ratio is not None
                      else r.get("status", "-"),
                      ("[%.4f, %.4f]" % tuple(ci)) if ci else "-",
                      excl(ci),
                      "identical" if d.get("identical") else
                      (str(d["changed"]) if d.get("changed") is not None else "?"),
                      ("%.2f%%" % d["share"]) if d.get("share") is not None
                      else "-", cat))
        if arm.get("kind") != "one-factor" or ratio is None:
            continue
        one_factor.append(r)
        per_mark[name].append((ratio, cand, ci))
        if ratio > 1.0 + args.mde:
            over.append((name, cand, ratio))
        if ratio < 1.0 - args.mde:
            under.append((name, cand, ratio))
        if d.get("identical"):
            ident.append((name, cand, ratio))
        if cat == "no-op build":
            noop.append((name, cand, ratio, ci))
        elif cat == "layout only":
            layout_only.append((name, cand, ratio, ci))

    out.append("")
    out.append("## Per mark: the best of its six candidates")
    out.append("")
    out.append("| mark | best candidate | ratio | 95% CI | CI excludes 1 | "
               "worst candidate | ratio |")
    out.append("|---|---|--:|---|---|---|--:|")
    for name in [s for _, s in SHORT if s in per_mark]:
        arms = sorted(per_mark[name], reverse=True)
        best, worst = arms[0], arms[-1]
        out.append("| %s | %s | %.4f | [%.4f, %.4f] | %s | %s | %.4f |"
                   % (name, best[1], best[0], best[2][0], best[2][1],
                      excl(best[2]), worst[1], worst[0]))
    out.append("")
    out.append("%d one-factor arms measured. Above +%.0f%%: %d. Below -%.0f%%: "
               "%d. Normalised-code-identical to the baseline: %d."
               % (len(one_factor), args.mde * 100, len(over), args.mde * 100,
                  len(under), len(ident)))
    if over:
        out.append("")
        out.append("Above the MDE: " + ", ".join("%s %s %.4f" % o for o in over))
    if under:
        out.append("")
        out.append("Below the MDE: " + ", ".join("%s %s %.4f" % u for u in under))
    if noop:
        n_excl = sum(1 for _, _, _, ci in noop if ci and (ci[0] > 1 or ci[1] < 1))
        rs = [x[2] for x in noop]
        out.append("")
        out.append("**The in-sweep null panel.** %d of the %d arms produced a "
                   "build whose normalised instruction text AND whose symbol "
                   "table (addresses and sizes) are identical to the "
                   "baseline's: the attribute was applied and changed nothing. "
                   "Those %d builds are the in-sweep null panel of "
                   "SPEC.ja.md 7. Their ratios run %.4f to %.4f (%.2f points), "
                   "and %d of them have a 95%% CI that excludes 1."
                   % (len(noop), len(one_factor), len(noop), min(rs), max(rs),
                      100 * (max(rs) - min(rs)), n_excl))
        out.append("")
        out.append("| null arm | ratio | 95% CI | CI excludes 1 |")
        out.append("|---|--:|---|---|")
        for name, cand, ratio, ci in sorted(noop, key=lambda x: -x[2]):
            out.append("| %s %s | %.4f | [%.4f, %.4f] | %s |"
                       % (name, cand, ratio, ci[0], ci[1], excl(ci)))
    if layout_only:
        rs = [x[2] for x in layout_only]
        out.append("")
        out.append("%d further arms changed no instruction, only where the "
                   "code sits (an alignment that moved the symbols): ratios "
                   "%.4f to %.4f." % (len(layout_only), min(rs), max(rs)))
    text = "\n".join(out) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            f.write(text)
    print(text)


if __name__ == "__main__":
    main()
