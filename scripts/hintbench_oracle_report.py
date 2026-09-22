#!/usr/bin/env python3
"""Read the hint benchmark oracle's rounds.jsonl and write its tables.

The sweep (`scripts/hintbench_oracle.sh run`) records one JSON line per arm.
This turns those lines into the four things
`docs/experiments/hintbench/oracle.md` and results.md have to carry:

  arms        one table per kernel: every candidate at that kernel's sites,
              what the build differed in, the ratio on that kernel's own
              workload (the readout results.md 103 froze), the aggregate,
              and whether a second independent batch confirmed it.
  scorecard   EXPECTED.md's predicted winner against the measured one, by
              the rules pre-registered in oracle.md section 2.
  vocabulary  which candidates ever cleared the MDE here, and which never.
  combination the last arm, and what the weaker selection rules would have
              picked instead.

Usage: scripts/hintbench_oracle_report.py artifacts/hintbench-oracle [section]
"""

import json
import os
import re
import sys

# EXPECTED.md section 0 as revised by its section 4 (decision 77). The file
# is frozen; this is a transcription of it, and the transcription is what the
# scorecard scores against.
EXPECTED = {
    "k1": ("inline_never", "+2% to +10%", "low"),
    "k2": ("inline_always", "+2% to +10%", "medium"),
    "k3": ("unroll_disable", "+2% to +10%", "medium"),
    "k4": ("KEEP_DEFAULT", "width 16: 0% to -25%", "medium"),
    "k5": ("KEEP_DEFAULT", "IC 1: -50% to -75%", "high"),
    "k6": ("align_64", "+-0% to +-3%, sign unknown", "low"),
    "k7": ("inline_never", "0% to +5%", "medium"),
    "k8": ("KEEP_DEFAULT", "every hint <= 0%", "high"),
}

# oracle.md section 2: same hint kind, different value.
FAMILY = {
    "unroll": ("unroll_count_2", "unroll_count_4", "unroll_count_8",
               "unroll_disable"),
    "width": ("vectorize_width_2", "vectorize_width_4", "vectorize_width_8",
              "vectorize_width_16"),
    "interleave": ("interleave_count_1", "interleave_count_2",
                   "interleave_count_4"),
    "align": ("align_16", "align_32", "align_64"),
    "inline": ("inline_always", "inline_never"),
}


def family_of(cand):
    for fam, members in FAMILY.items():
        if cand in members:
            return fam
    return None


def excludes_one(ci):
    if not ci or ci[0] is None or ci[1] is None:
        return 0
    return 1 if ci[0] > 1.0 else (-1 if ci[1] < 1.0 else 0)


def kernel_of(site_id):
    m = re.search(r"\bk(\d+)_", site_id or "")
    return ("k" + m.group(1)) if m else None


def load(out_dir):
    rows = []
    with open(os.path.join(out_dir, "rounds.jsonl")) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fmt_ratio(r):
    return "%.4f" % r if r is not None else "-"


def fmt_ci(ci):
    return "[%.4f, %.4f]" % tuple(ci) if ci else "-"


def readout(rec):
    """(ratio, ci) on the arm's own kernel, falling back to the aggregate."""
    k = rec.get("kernel") or {}
    if k.get("ratio") is not None:
        return k["ratio"], k.get("ci95"), k.get("workload")
    return rec.get("ratio"), rec.get("ci95"), "aggregate"


def confirm_cell(rec):
    if rec.get("status") == "identical_to_baseline":
        return "n/a"
    if not rec.get("confirm_trigger"):
        return "not triggered"
    c = rec.get("confirm") or {}
    if "error" in c:
        return "batch failed"
    if rec.get("confirmed"):
        return "**yes (%s)**" % ("+" if rec["confirmed_sign"] > 0 else "-")
    return "no"


def arms_tables(rows, out):
    one = [r for r in rows if (r.get("arm") or {}).get("kind") == "one-factor"]
    by_kernel = {}
    for r in one:
        by_kernel.setdefault(kernel_of(r["arm"]["site"]) or "?", []).append(r)
    for kern in sorted(by_kernel):
        out.append("")
        out.append("### %s" % kern.upper())
        out.append("")
        out.append("| arm | site | candidate | build vs baseline | changed "
                   "syms | %s ratio | 95%% CI | confirmed | aggregate | "
                   "aggregate CI |" % kern)
        out.append("|---:|---|---|---|--:|--:|---|---|--:|---|")
        for r in sorted(by_kernel[kern],
                        key=lambda r: (r["arm"]["site_kind"], r["round"])):
            a = r["arm"]
            ratio, ci, _ = readout(r)
            klass = r.get("code_class") or "-"
            if r.get("status") == "identical_to_baseline":
                klass = "**identical**"
                ratio_s, ci_s = "1.0000*", "by construction"
            else:
                ratio_s, ci_s = fmt_ratio(ratio), fmt_ci(ci)
            out.append("| %d | %s | `%s` | %s | %s | %s | %s | %s | %s | %s |"
                       % (r["round"], a["site_kind"], a["candidate"], klass,
                          r.get("n_changed_symbols", "-"), ratio_s, ci_s,
                          confirm_cell(r), fmt_ratio(r.get("ratio")),
                          fmt_ci(r.get("ci95"))))
    return out


def best_per_kernel(rows):
    """oracle.md 2: the confirmed positive arm with the highest own ratio."""
    one = [r for r in rows if (r.get("arm") or {}).get("kind") == "one-factor"]
    best = {}
    for r in one:
        kern = kernel_of(r["arm"]["site"])
        if not kern or not r.get("correct"):
            continue
        ratio, ci, _ = readout(r)
        if not (r.get("confirmed") and r.get("confirmed_sign", 0) > 0):
            continue
        if kern not in best or ratio > best[kern][1]:
            best[kern] = (r["arm"]["candidate"], ratio, ci, r["round"])
    return best


def scorecard(rows, out):
    best = best_per_kernel(rows)
    one = [r for r in rows if (r.get("arm") or {}).get("kind") == "one-factor"]
    worst = {}
    for r in one:
        kern = kernel_of(r["arm"]["site"])
        if not kern or r.get("status") == "identical_to_baseline":
            continue
        ratio, _, _ = readout(r)
        if ratio is None:
            continue
        if kern not in worst or ratio < worst[kern][1]:
            worst[kern] = (r["arm"]["candidate"], ratio)
    out.append("")
    out.append("| kernel | Claude's expected winner | expected effect | "
               "confidence | measured best (confirmed) | measured ratio | "
               "score | worst arm |")
    out.append("|---|---|---|---|---|--:|---|---|")
    tally = {"hit": 0, "same-family": 0, "miss": 0}
    for kern in sorted(EXPECTED):
        exp, eff, conf = EXPECTED[kern]
        got = best.get(kern)
        got_cand = got[0] if got else "KEEP_DEFAULT"
        if got_cand == exp:
            score = "**hit**"
        elif (family_of(got_cand) and family_of(got_cand) == family_of(exp)):
            score = "same-family"
        else:
            score = "miss"
        tally[score.strip("*")] += 1
        w = worst.get(kern)
        out.append("| %s | `%s` | %s | %s | `%s` | %s | %s | `%s` %s |"
                   % (kern.upper(), exp, eff, conf, got_cand,
                      fmt_ratio(got[1]) if got else "--",
                      score, w[0] if w else "-",
                      fmt_ratio(w[1]) if w else ""))
    out.append("")
    out.append("**%d hit, %d same-family, %d miss of 8.**"
               % (tally["hit"], tally["same-family"], tally["miss"]))
    return out


def vocabulary(rows, out):
    one = [r for r in rows if (r.get("arm") or {}).get("kind") == "one-factor"]
    cands = {}
    for r in one:
        c = r["arm"]["candidate"]
        d = cands.setdefault(c, {"n": 0, "identical": 0, "layout": 0,
                                 "code": 0, "confirmed": [], "best": None,
                                 "worst": None})
        d["n"] += 1
        d[r.get("code_class", "code")] = d.get(r.get("code_class", "code"), 0) + 1
        if r.get("status") == "identical_to_baseline":
            continue
        ratio, _, _ = readout(r)
        if ratio is None:
            continue
        if d["best"] is None or ratio > d["best"][0]:
            d["best"] = (ratio, kernel_of(r["arm"]["site"]))
        if d["worst"] is None or ratio < d["worst"][0]:
            d["worst"] = (ratio, kernel_of(r["arm"]["site"]))
        if r.get("confirmed"):
            mde = r.get("mde") or 0.03
            cleared = abs(ratio - 1.0) >= mde
            d["confirmed"].append((kernel_of(r["arm"]["site"]), ratio,
                                   cleared, mde))
    out.append("")
    out.append("| candidate | arms | identical builds | best kernel ratio | "
               "worst kernel ratio | confirmed effects | cleared the MDE |")
    out.append("|---|--:|--:|--:|--:|---|---|")
    for c in sorted(cands, key=lambda c: (family_of(c) or "", c)):
        d = cands[c]
        cleared = [x for x in d["confirmed"] if x[2]]
        out.append("| `%s` | %d | %d | %s | %s | %s | %s |"
                   % (c, d["n"], d.get("identical", 0),
                      ("%.4f (%s)" % d["best"]) if d["best"] else "-",
                      ("%.4f (%s)" % d["worst"]) if d["worst"] else "-",
                      ", ".join("%s %.4f" % (k, r)
                                for k, r, _, _ in d["confirmed"]) or "none",
                      ", ".join("%s %.4f (MDE %.1f%%)" % (k, r, m * 100)
                                for k, r, _, m in cleared) or "**never**"))
    return out


def combination(rows, out):
    comb = [r for r in rows if (r.get("arm") or {}).get("kind") == "combination"]
    if not comb:
        out.append("")
        out.append("(no combination arm in this run)")
        return out
    r = comb[-1]
    a = r["arm"]
    out.append("")
    out.append("Selection rule: **%s**." % a.get("selected_by"))
    out.append("")
    out.append("| rule | sites it would combine |")
    out.append("|---|---|")
    for name, key in (("confirmed in two batches (used)", "choices"),
                      ("one batch, CI lower > 1", "one_batch_rule_would_pick"),
                      ("point estimate > 1", "point_rule_would_pick")):
        picked = a.get(key) or {}
        out.append("| %s | %s |"
                   % (name, ", ".join("`%s` %s" % (s.replace("fn:", ""), c)
                                      for s, c in sorted(picked.items()))
                      or "*(none)*"))
    out.append("")
    out.append("Measured: ratio %s %s, code class `%s`, correctness %s, "
               "confirmed %s."
               % (fmt_ratio(r.get("ratio")), fmt_ci(r.get("ci95")),
                  r.get("code_class"), "OK" if r.get("correct") else "MISMATCH",
                  confirm_cell(r)))
    return out


def overview(rows, out):
    one = [r for r in rows if (r.get("arm") or {}).get("kind") == "one-factor"]
    n_id = sum(1 for r in one if r.get("status") == "identical_to_baseline")
    n_lay = sum(1 for r in one if r.get("code_class") == "layout")
    n_code = sum(1 for r in one if r.get("code_class") == "code")
    n_trig = sum(1 for r in one if r.get("confirm_trigger"))
    n_conf = sum(1 for r in one if r.get("confirmed"))
    n_confagg = sum(1 for r in one if r.get("confirmed_aggregate"))
    bad = [r["round"] for r in one if not r.get("correct")]
    wall = sum(r.get("wall_s") or 0 for r in rows)
    # The in-run A/A is a second copy of the baseline timed in the same
    # batch. How often its own interval excludes 1 is the calibration
    # number: on jaq it was 41 of 90 (results.md "Oracle A (jaq)" 113).
    aa1 = [r for r in one if r.get("aa")]
    aa2 = [r for r in one if (r.get("confirm") or {}).get("aa")]
    n_aa1 = sum(1 for r in aa1 if excludes_one(r["aa"]["ci95"]))
    n_aa2 = sum(1 for r in aa2 if excludes_one(r["confirm"]["aa"]["ci95"]))
    kaa = [r for r in one if (r.get("kernel") or {}).get("aa_ci95")]
    n_kaa = sum(1 for r in kaa if excludes_one(r["kernel"]["aa_ci95"]))
    out.append("")
    out.append("| | |")
    out.append("|---|--:|")
    out.append("| one-factor arms | %d |" % len(one))
    out.append("| correctness held | %d of %d |" % (len(one) - len(bad), len(one)))
    out.append("| builds identical to the baseline (not timed) | **%d** |" % n_id)
    out.append("| builds that only moved code (layout) | %d |" % n_lay)
    out.append("| builds that changed instructions | %d |" % n_code)
    out.append("| arms whose first batch excluded 1 (confirmation run) | %d |"
               % n_trig)
    out.append("| confirmed on the kernel readout | **%d** |" % n_conf)
    out.append("| confirmed on the aggregate | %d |" % n_confagg)
    out.append("| in-run A/A intervals excluding 1, first batch (aggregate) "
               "| %d of %d |" % (n_aa1, len(aa1)))
    out.append("| in-run A/A intervals excluding 1, first batch (own kernel) "
               "| %d of %d |" % (n_kaa, len(kaa)))
    out.append("| in-run A/A intervals excluding 1, confirmation batch "
               "| %d of %d |" % (n_aa2, len(aa2)))
    out.append("| wall clock of the rounds | %.1f h |" % (wall / 3600.0))
    return out


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "artifacts/hintbench-oracle"
    want = sys.argv[2] if len(sys.argv) > 2 else "all"
    rows = load(out_dir)
    out = []
    for name, fn in (("overview", overview), ("arms", arms_tables),
                     ("scorecard", scorecard), ("vocabulary", vocabulary),
                     ("combination", combination)):
        if want in ("all", name):
            if want == "all":
                out.append("")
                out.append("## %s" % name)
            fn(rows, out)
    print("\n".join(out))


if __name__ == "__main__":
    main()
