#!/usr/bin/env python3
"""Turn the prompt study's `log.jsonl` into the tables the README carries.

Reads nothing but the log and `jev_state_variants.py`; writes markdown to
stdout. Every number it prints is a count over the answers actually received,
and the request count it obtained is printed beside every rate, because the
gateway loses requests to HTTP 503 in bursts.

    scripts/jev_prompt_study_report.py --log docs/experiments/jev-prompt-study/log.jsonl
"""

import argparse
import collections
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import jev_state_variants as V  # noqa: E402

KEEP = "KEEP_DEFAULT"

# V0 re-sends the Experiment 3 request verbatim, so its question names are
# that request's, not the study's. These four (phase A) and four (phase B)
# are the study's sites inside it; the rest of the request is asked but not
# analysed. L5 is not in it at all.
V0_MAP = {
    "V0-phaseA": {"q0": "F1", "q4": "F2", "q5": "F3", "q11": "F4"},
    "V0-phaseB": {"q0": "L1", "q8": "L2", "q7": "L3", "q4": "L4"},
}

REF = {s["id"]: s["ref"] for s in V.SITES}
SITE_ORDER = [s["id"] for s in V.SITES]


def family(cand):
    if cand is None:
        return None
    if cand == KEEP:
        return "none"
    if cand in ("inline", "inline_never"):
        return "inline"
    if cand == "cold":
        return "cold"
    if cand.startswith("align"):
        return "align"
    if cand.startswith("unroll"):
        return "unroll"
    if cand.startswith("vectorize"):
        return "vectorize"
    if cand.startswith("interleave"):
        return "interleave"
    return "?"


REF_FAMILY = {k: family(v) for k, v in REF.items()}


def load(path):
    rows = []
    for line in open(path):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def derive_v5(rec_by_repeat):
    """V5: score per candidate + one noul per site -> one derived choice.

    The rule, fixed before V5's answers were looked at --- this script was
    written while the run was still on V2 --- rather than before the run
    started: if the site's `noul` is below 0.5 the derived choice is
    KEEP_DEFAULT; otherwise it is the candidate with the highest score, and
    ties go to the higher confidence.
    """
    out = {}
    for sid, (noul, scores) in rec_by_repeat.items():
        if noul is not None and noul < 0.5:
            out[sid] = (KEEP, noul)
            continue
        if not scores:
            out[sid] = (None, noul)
            continue
        best = max(scores.items(), key=lambda kv: (kv[1][0], kv[1][1]))
        out[sid] = (best[0], noul)
    return out


def derive_w5(pairs):
    """W5: independent 2-way Choices -> one winner per site, by round-robin.

    The rule, pre-registered in this file before the first W5 request was
    sent: each pair that a candidate wins (it is that Choice's argmax) is one
    win; the winner is the candidate with the most wins; a tie goes to the
    candidate with the higher probability summed over the pairs it appears
    in, and a tie that survives that goes to KEEP_DEFAULT if KEEP_DEFAULT is
    among the tied and to the lexicographically first id otherwise.

    `pairs` is {(a, b): (choice, probabilities)} for one site of one repeat.
    Returns (winner, mean confidence of the pairs).
    """
    wins = collections.Counter()
    mass = collections.Counter()
    seen = set()
    for (a, b), (choice, p) in pairs.items():
        seen.update((a, b))
        if choice:
            wins[choice] += 1
        tot = sum((p or {}).values()) or 1.0
        for c in (a, b):
            mass[c] += (p or {}).get(c, 0.0) / tot
    if not seen:
        return None
    best = max(seen, key=lambda c: (wins[c], mass[c]))
    tied = [c for c in seen
            if (wins[c], round(mass[c], 6)) == (wins[best], round(mass[best], 6))]
    if len(tied) > 1:
        best = KEEP if KEEP in tied else sorted(tied)[0]
    return best


def w5_mass(pairs):
    """The synthetic probability vector W5 contributes to the mass table: the
    mean of the two-candidate distributions over the pairs that contain
    KEEP_DEFAULT. It is comparable to the other variants' `1 - P(KEEP)` only
    as an ordering, and the README says so."""
    acc = collections.Counter()
    n = 0
    for (a, b), (_, p) in pairs.items():
        if KEEP not in (a, b):
            continue
        tot = sum((p or {}).values()) or 1.0
        n += 1
        for c, v in (p or {}).items():
            acc[c] += v / tot
    if not n:
        return {}
    return {c: v / n for c, v in acc.items()}


def collect(rows):
    """-> {variant: {repeat: {site_id: (choice, confidence)}}} plus extras."""
    picks = collections.defaultdict(lambda: collections.defaultdict(dict))
    probs = collections.defaultdict(lambda: collections.defaultdict(dict))
    v5raw = collections.defaultdict(lambda: collections.defaultdict(
        lambda: [None, {}]))
    w5raw = collections.defaultdict(lambda: collections.defaultdict(dict))
    w5conf = collections.defaultdict(dict)
    v12stage1 = collections.defaultdict(dict)

    for r in rows:
        if r["http_status"] != 200 or not r.get("response"):
            continue
        var, rep, tag = r["variant"], r["repeat"], r["tag"]
        smap = r.get("site_map") or {}
        answers = r["response"].get("answers", {})

        if var == "V0":
            smap = V0_MAP.get(tag, {})

        for q, ans in answers.items():
            if var == "V5":
                base = q.split("_")[0]
                sid = smap.get(base) or smap.get(q, "").split("/")[0]
                if not sid:
                    continue
                if ans.get("type") == "noul":
                    v5raw[rep][sid][0] = ans.get("noul")
                elif ans.get("type") == "score":
                    cand = (smap.get(q) or "").split("/", 1)[-1]
                    v5raw[rep][sid][1][cand] = (ans.get("score"),
                                                ans.get("confidence"))
                continue

            if var == "W5":
                tag_ = smap.get(q) or ""
                sid, _, pair = tag_.partition("/")
                if not pair or sid not in REF or ans.get("type") != "choice":
                    continue
                a, _, b = pair.partition("|")
                w5raw[rep][sid][(a, b)] = (ans.get("choice"),
                                           ans.get("probabilities") or {})
                w5conf[rep].setdefault(sid, []).append(ans.get("confidence"))
                continue

            sid = smap.get(q)
            if not sid or sid not in REF:
                continue
            if ans.get("type") != "choice":
                continue
            if var == "V12" and r.get("stage") == 1:
                v12stage1[rep][sid] = ans.get("choice")
                continue
            picks[var][rep][sid] = (ans.get("choice"), ans.get("confidence"))
            probs[var][rep][sid] = ans.get("probabilities") or {}

    # W5: derive one winner per site from the pairwise answers
    for rep, per in w5raw.items():
        for sid, pairs in per.items():
            w = derive_w5(pairs)
            if w:
                cs = [c for c in w5conf[rep].get(sid, []) if c is not None]
                picks["W5"][rep][sid] = (w, (sum(cs) / len(cs)) if cs else None)
                probs["W5"][rep][sid] = w5_mass(pairs)

    # V5: derive
    for rep, per in v5raw.items():
        d = derive_v5({k: (v[0], v[1]) for k, v in per.items()})
        for sid, (c, noul) in d.items():
            if c:
                picks["V5"][rep][sid] = (c, noul)

    # V12: stage 1 "leave_alone" is the KEEP_DEFAULT answer; a family with one
    # member is its own answer; otherwise stage 2 decided.
    for rep, fams in v12stage1.items():
        for sid, fam in fams.items():
            if fam == "leave_alone":
                picks["V12"][rep].setdefault(sid, (KEEP, None))
            else:
                members = V.FAMILY_MEMBERS.get(fam, [])
                if len(members) == 1:
                    picks["V12"][rep].setdefault(sid, (members[0], None))
    return picks, probs, v5raw, v12stage1, w5raw


def agreement(choice, sid):
    if choice is None:
        return "-"
    if choice == REF[sid]:
        return "exact"
    if family(choice) == REF_FAMILY[sid]:
        return "family"
    return "different"


FOCUS = [
    ("F2 -> inline_never?", "F2", lambda c: c == "inline_never"),
    ("F3 -> inline_never?", "F3", lambda c: c == "inline_never"),
    ("L3 -> vectorize_width_16/8?", "L3",
     lambda c: c in ("vectorize_width_16", "vectorize_width_8")),
    ("F4 avoids inline?", "F4", lambda c: c != "inline"),
]
KEEP_SITES = ["F1", "F4", "L1", "L2", "L4", "L5"]


def _modal(reps, sid):
    got = [reps[rep][sid][0] for rep in reps if sid in reps[rep]]
    if not got:
        return None
    return collections.Counter(got).most_common(1)[0][0]


def round2_sections(order, picks, probs, w5raw):
    print("\n## The four sites the round-2 question is about\n")
    print("| variant | " + " | ".join(t for t, _, _ in FOCUS)
          + " | the six KEEP sites still KEEP |")
    print("|---" * (len(FOCUS) + 2) + "|")
    for var in order:
        reps = picks[var]
        cells = []
        for _, sid, ok in FOCUS:
            c = _modal(reps, sid)
            cells.append("-" if c is None
                         else ("**yes** (%s)" % c if ok(c) else "no (%s)" % c))
        kept = [s for s in KEEP_SITES if _modal(reps, s) == KEEP]
        cells.append("%d/6" % len(kept))
        print("| %s | %s |" % (var, " | ".join(cells)))

    print("\n## The decision-71 readout: which site would be tried first, "
          "and with which hint\n")
    print("Sites ranked by `1 - P(KEEP_DEFAULT)` averaged over the repeats; "
          "the hint is that site's own highest-probability non-`KEEP` "
          "candidate, also averaged over the repeats.\n")
    print("| variant | first site | its best non-KEEP hint | 1-P(KEEP) | "
          "second site | reference pick at the first site |")
    print("|---|---|---|--:|---|---|")
    for var in order:
        rank = []
        for sid in SITE_ORDER:
            acc, n = collections.Counter(), 0
            for rep in probs.get(var, {}):
                p = probs[var][rep].get(sid)
                if not p:
                    continue
                tot = sum(p.values()) or 1.0
                n += 1
                for k, v in p.items():
                    acc[k] += v / tot
            if not n:
                continue
            mean = {k: v / n for k, v in acc.items()}
            rank.append((1.0 - mean.get(KEEP, 0.0), sid, mean))
        if not rank:
            print("| %s | - | - | - | - | - |" % var)
            continue
        if all(abs(r[0] - 1.0) < 1e-9 for r in rank):
            print("| %s | n/a --- no KEEP_DEFAULT candidate in this variant "
                  "| | | | |" % var)
            continue
        rank.sort(reverse=True)
        top, sid, mean = rank[0]
        rest = {k: v for k, v in mean.items() if k != KEEP}
        hint = max(rest.items(), key=lambda kv: kv[1])[0] if rest else "-"
        print("| %s | %s | `%s` | %.2f | %s | `%s` |"
              % (var, sid, hint, top, rank[1][1] if len(rank) > 1 else "-",
                 REF[sid]))

    if not w5raw:
        return
    print("\n## W5: every pairwise answer\n")
    print("| site | pair | winner (3 repeats) |")
    print("|---|---|---|")
    order_pairs = {}
    for rep in w5raw:
        for sid, pairs in w5raw[rep].items():
            for pr, (c, _) in pairs.items():
                order_pairs.setdefault(sid, {}).setdefault(pr, []).append(c)
    for sid in SITE_ORDER:
        for pr, cs in order_pairs.get(sid, {}).items():
            print("| %s | `%s` vs `%s` | %s |"
                  % (sid, pr[0], pr[1],
                     ", ".join("`%s`" % c for c in cs)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(
        REPO, "docs", "experiments", "jev-prompt-study", "log.jsonl"),
        help="one path, or several separated by commas")
    ap.add_argument("--variants", default=None,
                    help="comma-separated subset, in this order")
    ap.add_argument("--round2", action="store_true",
                    help="add the round-2 sections (readout ranking, the "
                         "four focus sites, W5's pairwise detail)")
    a = ap.parse_args()
    rows = []
    for path in a.log.split(","):
        rows += load(path.strip())
    picks, probs, v5raw, v12s1, w5raw = collect(rows)

    if a.variants:
        want = [v.strip() for v in a.variants.split(",")]
        order = [v for v in want if v in picks]
    else:
        order = [v for v in V.VARIANTS if v in picks]
    rows = [r for r in rows if r["variant"] in order]

    print("## Per-variant summary\n")
    print("| variant | answers | KEEP_DEFAULT rate | mean confidence | "
          "stable sites (3/3 identical) | exact | same family | different |")
    print("|---|--:|--:|--:|--:|--:|--:|--:|")
    per_variant = {}
    for var in order:
        reps = picks[var]
        cells = [(sid, c) for rep in reps for sid, (c, _) in reps[rep].items()]
        confs = [cf for rep in reps for _, (_, cf) in reps[rep].items()
                 if cf is not None]
        n = len(cells)
        if not n:
            continue
        keep = sum(1 for _, c in cells if c == KEEP)
        ag = collections.Counter(agreement(c, sid) for sid, c in cells)
        stable = tot = 0
        for sid in SITE_ORDER:
            got = [reps[rep][sid][0] for rep in reps if sid in reps[rep]]
            if len(got) >= 2:
                tot += 1
                if len(set(got)) == 1:
                    stable += 1
        per_variant[var] = dict(n=n, keep=keep, ag=ag, stable=(stable, tot),
                                conf=(sum(confs) / len(confs)) if confs else
                                None)
        print("| %s | %d | %.0f%% | %s | %d/%d | %d | %d | %d |" % (
            var, n, 100.0 * keep / n,
            ("%.2f" % (sum(confs) / len(confs))) if confs else "n/a",
            stable, tot, ag["exact"], ag["family"], ag["different"]))

    print("\n## Choice per site, per variant (modal answer of the repeats; "
          "`!` when the three repeats did not agree)\n")
    print("| variant | " + " | ".join(SITE_ORDER) + " |")
    print("|---" * (len(SITE_ORDER) + 1) + "|")
    print("| **reference** | " + " | ".join(REF[s] for s in SITE_ORDER) + " |")
    for var in order:
        reps = picks[var]
        row = []
        for sid in SITE_ORDER:
            got = [reps[rep][sid][0] for rep in reps if sid in reps[rep]]
            if not got:
                row.append("-")
                continue
            c = collections.Counter(got)
            mod, k = c.most_common(1)[0]
            row.append((mod or "?") + ("" if k == len(got) else " !"))
        print("| %s | %s |" % (var, " | ".join(row)))

    print("\n## What came second in V0\n")
    seconds = collections.Counter()
    for rep in probs.get("V0", {}):
        for sid, p in probs["V0"][rep].items():
            rest = {k: v for k, v in p.items() if k != KEEP}
            if rest:
                seconds[max(rest.items(), key=lambda kv: kv[1])[0]] += 1
    for k, v in seconds.most_common():
        print("- `%s` %d" % (k, v))

    print("\n## Does the choice track the site information?\n")
    print("| variant | L3 trip 222, vectorizable | L5 trip 1 | "
          "L1/L2/L4 reported illegal to vectorize | F2 10496 insts |")
    print("|---|---|---|---|---|")
    for var in order:
        reps = picks[var]

        def modal(sid):
            got = [reps[rep][sid][0] for rep in reps if sid in reps[rep]]
            if not got:
                return "-"
            return collections.Counter(got).most_common(1)[0][0] or "?"
        illegal = []
        for sid in ("L1", "L2", "L4"):
            got = [reps[rep][sid][0] for rep in reps if sid in reps[rep]]
            illegal += [g for g in got if g]
        nvec = sum(1 for g in illegal if family(g) in ("vectorize",
                                                       "interleave"))
        print("| %s | %s | %s | %d/%d vector-family answers | %s |" % (
            var, modal("L3"), modal("L5"), nvec, len(illegal), modal("F2")))

    print("\n## Where the probability mass sat, not just the argmax\n")
    print("A Choice answer carries a probability for every candidate. The "
          "argmax can stay on KEEP_DEFAULT while the mass behind it moves, "
          "and that is the sensitive measure of whether a section of the "
          "state was read at all. Each cell is the mean probability the "
          "repeats put on **anything other than KEEP_DEFAULT**, and, for "
          "the loop sites, the mean mass on the vectorize family in "
          "parentheses.\n")
    print("| variant | " + " | ".join(SITE_ORDER) + " |")
    print("|---" * (len(SITE_ORDER) + 1) + "|")
    for var in order:
        row = []
        for sid in SITE_ORDER:
            vals, vecs = [], []
            for rep in probs.get(var, {}):
                p = probs[var][rep].get(sid)
                if not p:
                    continue
                tot = sum(p.values()) or 1.0
                vals.append(1.0 - (p.get(KEEP, 0.0) / tot))
                vecs.append(sum(v for k, v in p.items()
                                if family(k) == "vectorize") / tot)
            if not vals:
                row.append("-")
            elif sid.startswith("L"):
                row.append("%.2f (%.2f)" % (sum(vals) / len(vals),
                                            sum(vecs) / len(vecs)))
            else:
                row.append("%.2f" % (sum(vals) / len(vals)))
        print("| %s | %s |" % (var, " | ".join(row)))

    if a.round2:
        round2_sections(order, picks, probs, w5raw)

    print("\n## API reliability\n")
    att = sum(r["attempts"] for r in rows)
    ok = [r for r in rows if r["http_status"] == 200]
    fail = [r for r in rows if r["http_status"] != 200]
    lat = [r["latency_ms"] for r in ok]
    tin = sum(r.get("input_tokens") or 0 for r in ok)
    tout = sum(r.get("output_tokens") or 0 for r in ok)
    cost = sum(float(r.get("cost_usd") or 0) for r in ok)
    mkt = sum(float(r.get("market_cost_usd") or 0) for r in ok)
    nq = 0
    for r in ok:
        nq += len((r["response"] or {}).get("answers", {}))
    print("- requests attempted %d, answered %d, never answered %d"
          % (len(rows), len(ok), len(fail)))
    print("- HTTP attempts %d for %d requests (%.2f per request); "
          "%d were retries after a retryable status"
          % (att, len(rows), att / max(1, len(rows)), att - len(rows)))
    print("- questions answered %d" % nq)
    if lat:
        lat_sorted = sorted(lat)
        print("- latency ms: total %.0f, mean %.0f, median %.0f, max %.0f"
              % (sum(lat), sum(lat) / len(lat),
                 lat_sorted[len(lat) // 2], max(lat)))
    print("- tokens in/out %d / %d" % (tin, tout))
    print("- cost billed $%.8f, list price $%.8f" % (cost, mkt))
    if fail:
        c = collections.Counter(str(r["http_status"]) for r in fail)
        print("- requests that never answered, by status: %s"
              % ", ".join("%s x%d" % kv for kv in c.items()))


if __name__ == "__main__":
    main()
