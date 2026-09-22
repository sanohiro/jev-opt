#!/usr/bin/env python3
"""Score a hintbench search run against the oracle's measured ground truth.

Experiment 4 (`docs/experiments/hintbench/exp4.md`). The oracle
(`artifacts/hintbench-oracle/rounds.jsonl`, `docs/experiments/hintbench/
oracle.md`) measured every candidate alone at every one of the twelve sites,
each in two independent batches. This script reads that file --- never a
transcription of it --- and turns a run's per-round choices into a score.

Two things it computes, and they are not the same question:

  1. **Per site: exact / same-family / miss**, with `harmful` marked
     separately. The truth at a site is the rule of `oracle.md` 2 as the
     dated note amends it and as `scripts/hintbench_oracle_report.py`
     implements it: among the arms at that site that were **confirmed in two
     batches with a positive sign**, the one with the highest ratio on that
     site's own kernel workload, provided the effect also **cleared its own
     batch's MDE**; where no arm qualifies, the truth is `KEEP_DEFAULT`.
     This is decision 87's rule, so the scores here are comparable with the
     7/8 and 0/4 recorded there. `harmful` is the brief's definition and is
     deliberately looser: a hint whose own oracle arm was **confirmed below
     1**, MDE or no MDE. A pick can therefore be a miss and harmful, or a
     miss and merely inert.

  2. **Per plan: the share of the oracle combination it reached**, as
     `(plan - 1) / (combination - 1)` on like batches --- a run's training
     rounds against the combination's training ratio, a run's third batch
     against the combination's own third batch. The combination arm is the
     LAST round of the oracle's rounds.jsonl and its selection rule is the
     looser one (confirmed in two batches, ratio > 1, no MDE gate), so a
     plan can score 12/12 exact and still fall short of 100%: the
     combination also carries the sub-MDE gains at k4 and k5 that the
     scoring rule above calls KEEP_DEFAULT.

Usage:
  scripts/hintbench_exp4_score.py truth
  scripts/hintbench_exp4_score.py run  artifacts/hintbench-search/jev-v4-r5
  scripts/hintbench_exp4_score.py plan '{"fn:hbkernels::k2_mix": "inline_always"}'
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORACLE = os.path.join(REPO, "artifacts", "hintbench-oracle", "rounds.jsonl")
KEEP = "KEEP_DEFAULT"

# "Same hint kind, different value" (oracle.md 2). `unroll.disable` is in the
# unroll family; `inline_always` and `inline_never` are NOT one family --- they
# are opposite directions, and jev-oneshot-v4.md 3 scores them as a miss.
FAMILIES = (
    (re.compile(r"^unroll_(count_\d+|disable)$"), "unroll"),
    (re.compile(r"^vectorize_width_\d+$"), "vectorize"),
    (re.compile(r"^interleave_count_\d+$"), "interleave"),
    (re.compile(r"^align_\d+$"), "align"),
    (re.compile(r"^inline_always$"), "inline_always"),
    (re.compile(r"^inline_never$"), "inline_never"),
)


def family(candidate):
    for rx, name in FAMILIES:
        if rx.match(candidate or ""):
            return name
    return candidate


def kernel_of(site_id):
    m = re.search(r"\bk(\d+)_", site_id or "")
    return ("k" + m.group(1)) if m else None


def readout(rec):
    """The kernel reading where the target has one, the aggregate otherwise.

    Same rule as scripts/hintbench_oracle_report.py: results.md "Hint
    benchmark (design)" 103 freezes the per-kernel readout.
    """
    k = rec.get("kernel")
    if k:
        return k["ratio"], k.get("ci95")
    return rec.get("ratio"), rec.get("ci95")


def load_oracle(path=ORACLE):
    return [json.loads(l) for l in open(path) if l.strip()]


def truth_table(rows):
    """site_id -> {truth, ratio, mde, arms: {candidate: arm reading}}.

    `arms` carries every one-factor arm measured at that site, which is what
    `harmful` and "what would this pick have cost" are read off.
    """
    sites = {}
    for r in rows:
        arm = r.get("arm") or {}
        if arm.get("kind") != "one-factor" or not r.get("correct"):
            continue
        site, cand = arm["site"], arm["candidate"]
        ratio, ci = readout(r)
        e = sites.setdefault(site, {"site": site, "kernel": kernel_of(site),
                                    "kind": arm.get("site_kind"), "arms": {}})
        e["arms"][cand] = {
            "ratio": ratio, "ci95": ci, "round": r["round"],
            "code_class": r.get("code_class"),
            "status": r.get("status"),
            "mde": r.get("mde"),
            "confirmed": bool(r.get("confirmed")),
            "sign": r.get("confirmed_sign") or 0,
        }
    for e in sites.values():
        best, best_r = KEEP, None
        for cand, a in e["arms"].items():
            if not (a["confirmed"] and a["sign"] > 0):
                continue
            if abs(a["ratio"] - 1.0) < (a["mde"] or 0.03):
                continue                      # cleared nothing; decision 87
            if best_r is None or a["ratio"] > best_r:
                best, best_r = cand, a["ratio"]
        e["truth"] = best
        e["truth_ratio"] = best_r
        # The looser reading, for the record: confirmed positive, no MDE gate.
        loose, loose_r = KEEP, None
        for cand, a in e["arms"].items():
            if a["confirmed"] and a["sign"] > 0 and (loose_r is None
                                                     or a["ratio"] > loose_r):
                loose, loose_r = cand, a["ratio"]
        e["truth_no_mde"] = loose
        e["truth_no_mde_ratio"] = loose_r
        e["harmful"] = sorted(c for c, a in e["arms"].items()
                              if a["confirmed"] and a["sign"] < 0)
    return sites


def combination(rows):
    for r in reversed(rows):
        if (r.get("arm") or {}).get("kind") == "combination":
            return r
    return None


def score_pick(entry, pick):
    """exact | same-family | miss, plus the harmful flag and the arm reading."""
    truth = entry["truth"]
    arm = entry["arms"].get(pick) or {}
    harmful = bool(pick != KEEP and arm.get("confirmed")
                   and arm.get("sign", 0) < 0)
    if pick == truth:
        verdict = "exact"
    elif pick != KEEP and truth != KEEP and family(pick) == family(truth):
        verdict = "same-family"
    else:
        verdict = "miss"
    return {"site": entry["site"], "kernel": entry["kernel"],
            "kind": entry["kind"], "pick": pick, "truth": truth,
            "verdict": verdict, "harmful": harmful,
            "pick_ratio": arm.get("ratio"), "pick_ci95": arm.get("ci95"),
            "pick_confirmed": arm.get("confirmed"),
            "pick_mde": arm.get("mde"),
            "pick_code_class": arm.get("code_class"),
            "truth_ratio": entry["truth_ratio"]}


def score_choices(sites, choices, asked=None):
    """`choices`: site_id -> candidate, as a round record writes it.

    Sites the round asked about but left at KEEP_DEFAULT count: leaving a
    site alone is an answer. `asked` restricts the scoring to the sites the
    round really put a question at --- a loop site vanishes from phase B
    when a function attribute changes the inlining it lives in, and a site
    that was never asked is not a wrong answer.
    """
    out = []
    for site in sorted(sites):
        if asked is not None and site not in asked:
            continue
        out.append(score_pick(sites[site], choices.get(site, KEEP)))
    return out


def tally(rowscored):
    t = {"exact": 0, "same-family": 0, "miss": 0, "harmful": 0, "n": 0}
    for r in rowscored:
        t[r["verdict"]] += 1
        t["harmful"] += 1 if r["harmful"] else 0
        t["n"] += 1
    return t


def round_choices(rec):
    c = {}
    c.update((rec.get("phase_a") or {}).get("choices") or {})
    c.update((rec.get("phase_b") or {}).get("choices") or {})
    c.pop("__build__", None)
    return c


def round_asked(rec):
    return set(round_choices(rec))


def pct_of_combination(plan_ratio, comb_ratio):
    if plan_ratio is None or comb_ratio is None or comb_ratio <= 1.0:
        return None
    return 100.0 * (plan_ratio - 1.0) / (comb_ratio - 1.0)


# --- reporting -------------------------------------------------------------

def fmt(x, n=4):
    return "-" if x is None else ("%.*f" % (n, x))


def cmd_truth(argv):
    rows = load_oracle()
    sites = truth_table(rows)
    comb = combination(rows)
    print("| site | kind | kernel | truth (MDE-gated) | ratio | "
          "truth (no MDE gate) | ratio | harmful candidates |")
    print("|---|---|---|---|--:|---|--:|---|")
    for s in sorted(sites, key=lambda s: (sites[s]["kernel"] or "",
                                          sites[s]["kind"] or "")):
        e = sites[s]
        print("| `%s` | %s | %s | `%s` | %s | `%s` | %s | %s |"
              % (s, e["kind"], e["kernel"], e["truth"], fmt(e["truth_ratio"]),
                 e["truth_no_mde"], fmt(e["truth_no_mde_ratio"]),
                 ", ".join("`%s` %.4f" % (c, e["arms"][c]["ratio"])
                           for c in e["harmful"]) or "(none)"))
    if comb:
        print("\ncombination arm: round %d, training ratio %.4f %s, "
              "confirm %.4f" % (comb["round"], comb["ratio"],
                                comb.get("ci95"),
                                (comb.get("confirm") or {}).get("ratio", 0.0)))
        print("combination sites: %s"
              % json.dumps((comb["arm"] or {}).get("choices"), indent=1))


def cmd_run(argv):
    out_dir = argv[0]
    rows = load_oracle()
    sites = truth_table(rows)
    comb = combination(rows)
    comb_train = comb["ratio"] if comb else None
    recs = [json.loads(l)
            for l in open(os.path.join(out_dir, "rounds.jsonl")) if l.strip()]
    doc = {"run": out_dir, "rounds": [], "combination_training": comb_train}
    for rec in recs:
        ch = round_choices(rec)
        scored = score_choices(sites, ch, asked=round_asked(rec))
        t = tally(scored)
        doc["rounds"].append({
            "round": rec["round"], "status": rec.get("status"),
            "correct": rec.get("correct"), "code_class": rec.get("code_class"),
            "ratio": rec.get("ratio"), "ci95": rec.get("ci95"),
            "confirmed_aggregate": rec.get("confirmed_aggregate"),
            "accepted": rec.get("accepted"),
            "per_workload": {k: v["ratio"] for k, v
                             in (rec.get("per_workload") or {}).items()},
            "choices": ch, "scored": scored, "tally": t,
            "pct_of_combination": pct_of_combination(rec.get("ratio"),
                                                     comb_train)})
    hold_path = os.path.join(out_dir, "holdout", "holdout.json")
    if os.path.exists(hold_path):
        doc["holdout"] = json.load(open(hold_path))
    print(json.dumps(doc, indent=1))


def cmd_plan(argv):
    choices = json.loads(argv[0])
    rows = load_oracle()
    sites = truth_table(rows)
    scored = score_choices(sites, choices)
    print(json.dumps({"scored": scored, "tally": tally(scored)}, indent=1))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, argv = sys.argv[1], sys.argv[2:]
    {"truth": cmd_truth, "run": cmd_run, "plan": cmd_plan}[cmd](argv)


if __name__ == "__main__":
    main()
