#!/usr/bin/env python3
"""The arm table of an oracle sweep run with the decision-80 driver.

`scripts/jaq_oracle_table.py` reads the records oracle A wrote: every arm
timed, one batch each, `ratio` and `ci95` always present, and the
no-op/layout classification supplied after the fact by
`norm_code_diff.py` plus a hand-made `layout.json`. The driver those
records came from no longer exists. Since decision 80 it

  * classifies every build against the baseline itself (`code_class`,
    `code_detail`) and does **not time** an `identical` one
    (`status: identical_to_baseline`, `ratio: 1.0`, `ci95: null`),
  * re-measures any arm whose interval excluded 1 in a second independent
    batch and records the verdict (`confirm`, `confirmed_aggregate`).

So a table of such a run has to say which arms were measured at all, and
an effect is the pair (batch 1, confirmation), not one interval. This
script reads only what the run wrote, plus --- for the profile-share
column --- the output of

    scripts/norm_code_diff.py <baseline>/bin <run>/round-*/bin \\
        --profdata pgo/jaq/merged.profdata

It computes nothing about speed: every ratio, interval and MDE is copied
out of a round record.

    scripts/jaq_oracle_table2.py --run artifacts/jaq-search/oracle-A2 \\
        --normdiff artifacts/jaq-search/oracle-A2/norm-code-diff.txt \\
        --mde 0.03 --out docs/experiments/jaq-oracle-A2/arms.md
"""

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jaq_oracle_table as T1                       # noqa: E402  (short())


def parse_normdiff(path):
    """{binary path: {identical, changed, share}} --- T1's parser, reused."""
    return T1.parse_normdiff(path)


def excl(ci):
    if not ci:
        return "-"
    if ci[0] > 1.0:
        return "yes (+)"
    if ci[1] < 1.0:
        return "yes (-)"
    return "no"


def fmt_ci(ci):
    return ("[%.4f, %.4f]" % tuple(ci)) if ci else "-"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--normdiff", default=None)
    p.add_argument("--mde", type=float, default=0.03)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    rows = [json.loads(l) for l in open(os.path.join(args.run, "rounds.jsonl"))
            if l.strip()]
    nd = parse_normdiff(args.normdiff)

    out, per_mark = [], collections.defaultdict(list)
    measured, identical, layout, changed = [], [], [], []
    over, under, confirmed_arms = [], [], []
    fanout, cand_seen = {}, collections.defaultdict(list)
    comb = None

    out.append("| arm | mark | candidate | plan entries | apply | correct | "
               "build vs baseline | ratio | 95% CI | excl 1 | confirm | "
               "confirmed | changed syms | profile share |")
    out.append("|---:|---|---|--:|---|---|---|--:|---|---|--:|---|--:|--:|")
    for r in rows:
        arm = r.get("arm") or {}
        pa, pb = r.get("phase_a") or {}, r.get("phase_b") or {}
        fn_entries = [e["fn"] for e in (pa.get("fn_attrs") or [])]
        binpath = os.path.abspath(os.path.join(args.run,
                                               "round-%02d" % r["round"], "bin"))
        d = nd.get(binpath, {})
        site = arm.get("site") or ""
        mark = site[3:] if site.startswith("fn:") else site
        name = T1.short(mark) if mark else "(combination)"
        cand = arm.get("candidate") or "-"
        klass = r.get("code_class") or "?"
        ratio, ci = r.get("ratio"), r.get("ci95")
        c = r.get("confirm") or {}
        conf_ok = r.get("confirmed_aggregate")
        nch = r.get("n_changed_symbols")
        if nch is None:
            nch = (r.get("code_detail") or {}).get("changed")
        share = d.get("share")
        if klass == "identical":
            share = 0.0
        out.append("| %d | %s | %s | %d | %s | %s | %s | %s | %s | %s | %s | "
                   "%s | %s | %s |"
                   % (r["round"], name, cand, len(fn_entries),
                      T1.outcome_counts(pb.get("apply") or {}, fn_entries),
                      "yes" if r.get("correct") else "NO", klass,
                      ("%.4f" % ratio) if ratio is not None else "-",
                      fmt_ci(ci) if r.get("measured") else "not timed",
                      excl(ci), ("%.4f" % c["ratio"]) if c.get("ratio") else "-",
                      ("yes (%+d)" % (r.get("confirmed_aggregate_sign") or 0))
                      if conf_ok else ("no" if r.get("measured") else "-"),
                      "0" if klass == "identical" else
                      (str(nch) if nch is not None else "?"),
                      ("%.2f%%" % share) if share is not None else "-"))

        if arm.get("kind") == "combination":
            comb = r
            continue
        if arm.get("kind") != "one-factor":
            continue
        fanout[name] = len(fn_entries)
        rec = {"mark": name, "cand": cand, "ratio": ratio, "ci95": ci,
               "klass": klass, "confirmed": bool(conf_ok),
               "confirm_ratio": c.get("ratio"), "confirm_ci95": c.get("ci95"),
               "measured": bool(r.get("measured")), "share": share,
               "n_changed": nch, "round": r["round"],
               "aa": (r.get("aa") or {}).get("ratio"),
               "mde": r.get("mde")}
        cand_seen[cand].append(rec)
        {"identical": identical, "layout": layout,
         "code": changed}.get(klass, []).append(rec)
        if rec["measured"]:
            measured.append(rec)
        if ratio is None:
            continue
        per_mark[name].append(rec)
        if ratio > 1.0 + args.mde:
            over.append(rec)
        if ratio < 1.0 - args.mde:
            under.append(rec)
        if rec["confirmed"]:
            confirmed_arms.append(rec)

    one_factor = [r for r in rows
                  if (r.get("arm") or {}).get("kind") == "one-factor"]
    out.append("")
    out.append("## What the builds were")
    out.append("")
    out.append("| what the build differs in | arms | ratio range |")
    out.append("|---|--:|---|")
    for label, group in (("nothing: same instructions, same symbol table "
                          "(not timed)", identical),
                         ("only where the code sits", layout),
                         ("instructions changed", changed)):
        rs = [g["ratio"] for g in group if g["ratio"] is not None]
        out.append("| %s | %d | %s |"
                   % (label, len(group),
                      ("%.4f -- %.4f" % (min(rs), max(rs))) if rs else "--"))
    out.append("")
    out.append("%d one-factor arms: %d identical to the baseline and not "
               "timed, %d measured." % (len(one_factor), len(identical),
                                        len(measured)))

    out.append("")
    out.append("## By candidate")
    out.append("")
    out.append("| candidate | arms | identical | layout | code | measured "
               "mean | min | max | confirmed |")
    out.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for cand in sorted(cand_seen):
        g = cand_seen[cand]
        m = [x["ratio"] for x in g if x["measured"] and x["ratio"] is not None]
        out.append("| %s | %d | %d | %d | %d | %s | %s | %s | %d |"
                   % (cand, len(g),
                      sum(1 for x in g if x["klass"] == "identical"),
                      sum(1 for x in g if x["klass"] == "layout"),
                      sum(1 for x in g if x["klass"] == "code"),
                      ("%.4f" % (sum(m) / len(m))) if m else "--",
                      ("%.4f" % min(m)) if m else "--",
                      ("%.4f" % max(m)) if m else "--",
                      sum(1 for x in g if x["confirmed"])))

    out.append("")
    out.append("## Per mark: the best of its five candidates")
    out.append("")
    out.append("| mark | plan entries | best candidate | ratio | 95% CI | "
               "excl 1 | confirmed | worst candidate | ratio |")
    out.append("|---|--:|---|--:|---|---|---|---|--:|")
    for name in [s for _, s in T1.SHORT if s in per_mark]:
        arms = sorted(per_mark[name], key=lambda x: x["ratio"], reverse=True)
        best, worst = arms[0], arms[-1]
        out.append("| %s | %d | %s | %.4f | %s | %s | %s | %s | %.4f |"
                   % (name, fanout.get(name, 0), best["cand"], best["ratio"],
                      fmt_ci(best["ci95"]) if best["measured"]
                      else "not timed", excl(best["ci95"]),
                      "yes" if best["confirmed"] else "no",
                      worst["cand"], worst["ratio"]))

    out.append("")
    out.append("## The MDE gate and the confirmation")
    out.append("")
    out.append("MDE %.0f%%. Arms above it: %d. Below it: %d. Arms whose "
               "interval excluded 1 in **both** batches with the same sign: "
               "%d." % (args.mde * 100, len(over), len(under),
                        len(confirmed_arms)))
    if over or under:
        out.append("")
        out.append("| arm | mark | candidate | ratio | 95% CI | confirm | "
                   "confirm 95% CI | confirmed | in-run A/A |")
        out.append("|---:|---|---|--:|---|--:|---|---|--:|")
        for rec in sorted(over + under, key=lambda x: -x["ratio"]):
            out.append("| %d | %s | %s | %.4f | %s | %s | %s | %s | %s |"
                       % (rec["round"], rec["mark"], rec["cand"], rec["ratio"],
                          fmt_ci(rec["ci95"]),
                          ("%.4f" % rec["confirm_ratio"])
                          if rec["confirm_ratio"] else "-",
                          fmt_ci(rec["confirm_ci95"]),
                          "yes" if rec["confirmed"] else "no",
                          ("%.4f" % rec["aa"]) if rec["aa"] else "-"))
    if confirmed_arms:
        out.append("")
        out.append("Confirmed arms (both batches exclude 1, same sign):")
        out.append("")
        out.append("| arm | mark | candidate | batch 1 | 95% CI | batch 2 | "
                   "95% CI | clears MDE |")
        out.append("|---:|---|---|--:|---|--:|---|---|")
        for rec in sorted(confirmed_arms, key=lambda x: -x["ratio"]):
            out.append("| %d | %s | %s | %.4f | %s | %s | %s | %s |"
                       % (rec["round"], rec["mark"], rec["cand"], rec["ratio"],
                          fmt_ci(rec["ci95"]),
                          ("%.4f" % rec["confirm_ratio"])
                          if rec["confirm_ratio"] else "-",
                          fmt_ci(rec["confirm_ci95"]),
                          "yes" if abs(rec["ratio"] - 1.0) > args.mde
                          else "no"))

    # The in-run A/A is this run's null panel: decision 80 (b) removed the
    # in-sweep one by not timing the arms that built the baseline.
    aas = [(r["round"], (r.get("aa") or {}).get("ratio"),
            (r.get("aa") or {}).get("ci95"))
           for r in rows if r.get("measured") and r.get("aa")]
    caas = [(r["round"], ((r.get("confirm") or {}).get("aa") or {}).get("ratio"),
             ((r.get("confirm") or {}).get("aa") or {}).get("ci95"))
            for r in rows if (r.get("confirm") or {}).get("aa")]
    allaa = [x for x in aas + caas if x[1] is not None]
    if allaa:
        vals = [x[1] for x in allaa]
        n_excl = sum(1 for _, _, ci in allaa if ci and (ci[0] > 1 or ci[1] < 1))
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)) ** 0.5
        out.append("")
        out.append("## The null panel this run has: the in-run A/A")
        out.append("")
        out.append("Every timed batch carries a third label that is a second "
                   "copy of the baseline binary. Over the %d batches of this "
                   "run (%d first batches, %d confirmations) that label ran "
                   "**%.4f to %.4f (%.2f points), sd %.2f%%, and %d of %d of "
                   "its intervals exclude 1.0**."
                   % (len(allaa), len(aas), len(caas), min(vals), max(vals),
                      100 * (max(vals) - min(vals)), 100 * sd, n_excl,
                      len(allaa)))

    if comb is not None:
        arm = comb.get("arm") or {}
        out.append("")
        out.append("## The combination arm")
        out.append("")
        out.append("Selected by: %s. %d sites."
                   % (arm.get("selected_by", "?"), len(arm.get("choices") or {})))
        out.append("")
        for site, cand in sorted((arm.get("choices") or {}).items()):
            m = site[3:] if site.startswith("fn:") else site
            out.append("* `%s` %s" % (T1.short(m), cand))
        for label, key in (("The one-batch rule would have chosen",
                            "one_batch_rule_would_pick"),
                           ("The point-estimate rule would have chosen",
                            "point_rule_would_pick")):
            sel = arm.get(key) or {}
            out.append("")
            out.append("%s %d sites: %s"
                       % (label, len(sel),
                          ", ".join("%s %s" % (T1.short(s[3:] if
                                                        s.startswith("fn:")
                                                        else s), c)
                                    for s, c in sorted(sel.items())) or "none"))
        out.append("")
        out.append("Training: %s %s, %s. Correctness %s, build %s."
                   % (("%.4f" % comb["ratio"]) if comb.get("ratio") else "-",
                      fmt_ci(comb.get("ci95")),
                      ("confirmation %.4f %s"
                       % (((comb.get("confirm") or {}).get("ratio") or 0),
                          fmt_ci((comb.get("confirm") or {}).get("ci95"))))
                      if (comb.get("confirm") or {}).get("ratio")
                      else "no confirmation batch",
                      "OK" if comb.get("correct") else "MISMATCH",
                      comb.get("code_class")))

    text = "\n".join(out) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            f.write(text)
        print("wrote %s" % args.out)
    else:
        print(text)


if __name__ == "__main__":
    main()
