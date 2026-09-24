#!/usr/bin/env python3
"""Prompt study 2 (API only): can Jev find the loop truths?

results.md 173 (pre-registration) and 174 (results). Nothing is built and
nothing is timed. The baseline request of every target is rendered by
`scripts/jev_search.py`'s own objects (the round-1 setup of `--print-state`,
reusing the frozen baseline dump), exactly as `scripts/jev_oneshot.py` does:
vocabulary v6, state format v6.0, phase A = every function site in one
Choice request, phase B = every loop site in one Choice request. Each variant
is a transform of that request that is the SAME RULE at every site; the
variant texts name no site, kernel, file or measured number (checked by
`leak_check()` and printed into the log).

Subcommands:

  truth                derive the per-site truth table from the oracles'
                       own records (MDE v2, decision 106) -> truth.json
  render  T V PHASE    print the request(s) variant V would send (no HTTP)
  run                  send variants x repeats, log JSONL + .log
  score                read the JSONL back, score against truth.json

The candidate texts of variant L1 (a possible vocabulary v7) live in this
file on purpose: adding them to `jev_vocab.py` would make them selectable by
the driver, which is de facto freezing (HANDOFF 4 proposes, the owner
decides).
"""

import argparse
import contextlib
import copy
import io
import json
import os
import random
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jev_search as S          # noqa: E402
import jev_vocab as V           # noqa: E402

REPO = S.REPO
STUDY = "prompt-study-2-2026-09-24"
OUT_DIR = os.path.join(REPO, "artifacts", "jev-prompt-study-2")
DOC_DIR = os.path.join(REPO, "docs", "experiments", "jev-prompt-study-2")
TRUTH_PATH = os.path.join(DOC_DIR, "truth.json")
KEEP = V.KEEP_DEFAULT

TARGETS = {
    "hintbench": dict(
        marks="targets/hintbench/jev-marks.txt",
        sites="artifacts/hintbench-sites/sites.json",
        site_set="oracle.selected_keys_loop_hint_kernels",
        baseline_dir="artifacts/hintbench-sites/baseline", phases="AB"),
    "zopfli": dict(
        marks="targets/zopfli/jev-marks.txt",
        sites="targets/zopfli/sites.json",
        site_set="oracle.selected_keys_top6",
        baseline_dir="artifacts/zopfli-sites/baseline", phases="AB"),
    # Loops skipped: no loop oracle (decision 103) and a 5 MB loop state.
    "jaq": dict(
        marks="targets/jaq/jev-marks.txt",
        sites="targets/jaq/sites.json",
        site_set="oracle.selected_keys_top3",
        baseline_dir="artifacts/jaq-search/jev-r5/baseline", phases="A",
        # results.md 173.7 (4): a whole-phase jaq request is 119-126 KB and
        # did not land; sites are batched the driver's way (`_batches`) at
        # this state size instead, for every jaq variant alike.
        batch_chars=40000),
}

# ---------------------------------------------------------------------------
# truth (decision 106: MDE v2 final)
# ---------------------------------------------------------------------------

HB_MDE_CASE = {"k1": 0.0158, "k2": 0.0135, "k3": 0.0224, "k4": 0.0163,
               "k5": 0.0170, "k6": 0.0100, "k7": 0.0253, "k8": 0.0318}
ZOPFLI_MDE = 0.0100
JAQ_MDE = 0.0113


def _verdict(r1, r2, mde):
    if r1 is None or r2 is None:
        return "flat"
    if r1 > 1 + mde and r2 > 1 + mde:
        return "good"
    if r1 < 1 - mde and r2 < 1 - mde:
        return "harmful"
    return "flat"


def derive_truth():
    out = {"rule": ("MDE v2 final (decision 106): good/harmful = round batch "
                    "AND confirmation batch beyond the MDE on the same side; "
                    "identical build = noop; else flat. Truth best = "
                    "highest-ratio good arm, else KEEP_DEFAULT."),
           "targets": {}}
    # hintbench: own-kernel ratios from each round's stats.json (cand vs
    # base) and its confirm/stats.json; per-kernel MDEs of 172.1.
    hb = {}
    root = os.path.join(REPO, "artifacts", "hintbench-oracle")
    for line in open(os.path.join(root, "rounds.jsonl")):
        r = json.loads(line)
        arm = r["arm"]
        if arm["kind"] != "one-factor":
            continue
        site, cand = arm["site"], arm["candidate"]
        k = re.search(r"::(k\d)_", site).group(1)
        rec = {"round": r["round"], "code_class": r["code_class"]}
        if r["status"] == "identical_to_baseline":
            rec.update(verdict="noop", r1=1.0, r2=None)
        else:
            d = os.path.join(root, "round-%02d" % r["round"])
            r1 = json.load(open(os.path.join(d, "stats.json")))[
                "per_workload"]["cand"][k]["ratio_vs_base"]
            cp = os.path.join(d, "confirm", "stats.json")
            r2 = (json.load(open(cp))["per_workload"]["cand"][k]
                  ["ratio_vs_base"] if os.path.isfile(cp) else None)
            rec.update(r1=r1, r2=r2, verdict=_verdict(r1, r2, HB_MDE_CASE[k]))
        rec["mde"] = HB_MDE_CASE[k]
        hb.setdefault(site, {})[cand] = rec
    out["targets"]["hintbench"] = hb
    for tname, path, mde in (
            ("zopfli", "artifacts/zopfli-search/oracle/rounds.jsonl",
             ZOPFLI_MDE),
            ("jaq", "artifacts/jaq-search/oracle-A2/rounds.jsonl", JAQ_MDE)):
        t = {}
        for line in open(os.path.join(REPO, path)):
            r = json.loads(line)
            arm = r["arm"]
            if arm["kind"] != "one-factor":
                continue
            site, cand = arm["site"], arm["candidate"]
            rec = {"round": r["round"], "code_class": r["code_class"],
                   "mde": mde}
            if r["status"] == "identical_to_baseline" or \
                    r["code_class"] == "identical":
                rec.update(verdict="noop", r1=1.0, r2=None)
            else:
                r1 = r.get("ratio")
                r2 = (r.get("confirm") or {}).get("ratio")
                rec.update(r1=r1, r2=r2, verdict=_verdict(r1, r2, mde))
            t.setdefault(site, {})[cand] = rec
        out["targets"][tname] = t
    # Per-site summary.
    for tname, t in out["targets"].items():
        for site, arms in t.items():
            good = {c: a for c, a in arms.items() if a["verdict"] == "good"}
            best = (max(good, key=lambda c: min(good[c]["r1"], good[c]["r2"]))
                    if good else KEEP)
            arms["_summary"] = {
                "best": best, "good": sorted(good),
                "harmful": sorted(c for c, a in arms.items()
                                  if a["verdict"] == "harmful"),
                "noop": sorted(c for c, a in arms.items()
                               if a["verdict"] == "noop")}
    os.makedirs(DOC_DIR, exist_ok=True)
    with open(TRUTH_PATH, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    return out


def print_truth(truth):
    for tname, t in truth["targets"].items():
        print("== %s" % tname)
        for site in sorted(t):
            s = t[site]["_summary"]
            detail = ", ".join(
                "%s %.4f/%s" % (c, a["r1"], "-" if a["r2"] is None
                                else "%.4f" % a["r2"])
                for c, a in sorted(t[site].items())
                if c != "_summary" and a["verdict"] in ("good", "harmful"))
            print("  %-60s best=%-18s good=%s harmful=%s  [%s]"
                  % (site[:60], s["best"], s["good"], s["harmful"], detail))


# ---------------------------------------------------------------------------
# setting up the driver's own objects (no build: the baseline dir exists)
# ---------------------------------------------------------------------------

class _Args:
    def __init__(self, **kw):
        d = dict(target=None, marks=None, sites=None, site_set=None,
                 baseline_dir=None, vocab="v6", readout="forced_top1",
                 explore=0, explore_revisit=0, pv_untried="off",
                 source_comments="strip", proposer="jev", out=None,
                 run_id=None, rounds=None, n=None, warmup=None,
                 bench_set="training", dry_run=False, print_state=True,
                 smoke=False, measure_holdout=False, keep_binaries="best",
                 oracle_phase="all", fn_attr_scope="own", no_site_cap=False,
                 allow_unresolved=False, no_noop_skip=False,
                 no_confirm_batch=False, ignore_apply_failures=False,
                 resume=False, seed_offset=0, site_filter="all",
                 oracle_candidates=None, protocol=None, confirm_when=None,
                 aa_leg=None, reps_oracle=None, mde=None, mde_floor=None,
                 mde_from=None, mde_case=None,
                 config=os.path.join(REPO, "jev-opt.toml"))
        d.update(kw)
        self.__dict__.update(d)


def setup(target):
    spec = TARGETS[target]
    os.environ["TARGET"] = target
    scratch = os.path.join(OUT_DIR, "_driver-%s" % target)
    args = _Args(target=target, marks=os.path.join(REPO, spec["marks"]),
                 sites=os.path.join(REPO, spec["sites"]),
                 site_set=spec["site_set"],
                 baseline_dir=os.path.join(REPO, spec["baseline_dir"]),
                 out=scratch, run_id="ps2-setup-%s" % target)
    cfg = S.load_config(args.config)
    search = S.Search(args, cfg)
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        rc = search.run()
    if rc != 0:
        sys.exit("driver setup failed:\n" + buf.getvalue())
    assert V.VOCAB_VERSION == "v6-2026-09-23", V.VOCAB_VERSION
    assert S.STATE_FORMAT_VERSION == "state-v6.0-2026-09-23"
    return search, cfg


def phase_items(search, phase):
    return search.fn_list if phase == "A" else search.base_loops


def phase_ctx(search, phase):
    # jev_oneshot.py's round-1 strings: phase A shows no fn-choice line,
    # phase B says `none` (this pass builds nothing).
    if phase == "A":
        return search.ctx({"arm": None})
    return search.ctx({"arm": None, "fn_choice_text": "none"})


# ---------------------------------------------------------------------------
# variant texts (uniform; no site, file, kernel or number in any of them)
# ---------------------------------------------------------------------------

V7_LOOP = {
    KEEP: (
        "Attach no metadata to this loop. LLVM's vectoriser and unroller then "
        "choose the vector width, the interleave count and the unroll factor "
        "with their own cost model, exactly as in the baseline build. It helps "
        "where that cost model already picked what this loop's trip count, "
        "body and element type call for. It hurts where the cost model, which "
        "estimates trip counts and costs rather than measuring them, picked a "
        "width, count or factor that leaves speed unused on this machine."),
    "unroll_count": (
        "Attach `llvm.loop.unroll.count = {n}`. LLVM's unroller then copies "
        "the loop body {n} times per iteration, replacing whatever factor its "
        "own cost model chose (including none), and adds a remainder for trip "
        "counts that are not a multiple of {n}; it runs after vectorisation, "
        "so on a vectorised loop it copies the vector body. It helps where the "
        "body is short and loop overhead or a dependent chain limits speed, "
        "and the trip count leaves few iterations to the remainder. It hurts "
        "where the body is large or has calls, or where the remainder or the "
        "code growth costs more than the saved branches."),
    "unroll_disable": (
        "Attach `llvm.loop.unroll.disable`. LLVM's unroller then leaves this "
        "loop at one body copy per iteration whatever its cost model would "
        "have chosen, and on a vectorised loop the vectoriser also stops "
        "interleaving. It helps where LLVM unrolled or interleaved a loop "
        "whose trip count is too short or too irregular for the copies to pay "
        "for themselves, or where code growth costs instruction cache. It "
        "hurts where the copies LLVM made were hiding latency or loop "
        "overhead, which on a long loop they usually are."),
    "vectorize_width": (
        "Attach `llvm.loop.vectorize.width = {n}` (and `vectorize.enable`). "
        "The vectoriser then processes {n} elements per vector iteration "
        "instead of the width its cost model chose; if {n} elements do not "
        "fit one 256-bit register it uses several registers per value, and it "
        "keeps choosing its own interleave count. It helps where the loop is "
        "long, the body is short and legal to vectorise, and more elements "
        "in flight per iteration raise throughput. It hurts where the trip "
        "count is short, where the extra lanes only add shuffles or a longer "
        "remainder, or where the loop cannot be vectorised (the hint is then "
        "dropped)."),
    "interleave_count": (
        "Attach `llvm.loop.interleave.count = {n}`. The vectoriser then runs "
        "{n} independent copies of the vector body per iteration ({n} "
        "separate accumulator chains for a reduction) instead of the count "
        "its cost model chose, a count of 1 meaning a single chain. It helps "
        "where the latency of a dependent chain, not throughput, limits the "
        "loop and registers are free. It hurts where more chains spill "
        "registers or lengthen the remainder, or where fewer chains than "
        "LLVM chose expose that latency on a long loop; on a loop LLVM does "
        "not vectorise it has little or nothing to act on."),
}


def v7_loop_candidates(cands):
    out = {}
    for cid in cands:
        if cid == KEEP:
            out[cid] = V7_LOOP[KEEP]
        elif cid == "unroll_disable":
            out[cid] = V7_LOOP["unroll_disable"]
        else:
            name, _, n = cid.rpartition("_")
            out[cid] = V7_LOOP[name].format(n=n)
    return out


NO_HINT_MEASURED = (
    "\n\nNo hint has been measured at this site in this run: nothing in this "
    "state says what any of the hints below would be worth here, in either "
    "direction.")

RAW_FACTS_PREAMBLE = (
    "Recorded facts for this site, as raw values. Each line is read from the "
    "plugin's dump or copied from the compiler's remarks by the same rule at "
    "every site in this request; no rule has been applied to them and none "
    "of them is an opinion about which hint to choose.")

SOURCE_OMITTED = "  (source excerpt omitted from this request)"

PV_NOT_FOUND_NEUTRAL = (
    "what LLVM did with this loop in the baseline build, recorded by the "
    "plugin itself after LoopVectorize had run: the plugin did not find this "
    "loop by its signature after LoopVectorize (it may have been removed, "
    "merged, fully unrolled, or rewritten so that the signature no longer "
    "matches). Hints are attached before LoopVectorize, and this record does "
    "not establish whether a hint attached there has anything to act on.")

REMARKS_IN_Q_LOOP = (
    "\n\nWhat LLVM's remarks say at this loop's own leaf location in the "
    "baseline build, copied verbatim from the build log{shared}:\n")
REMARKS_IN_Q_FN = (
    "\n\nWhat LLVM decided about calls to this function in the baseline "
    "build, copied verbatim from the build log's inline remarks (matched by "
    "callee symbol):\n")

UNROLL_ARITH = (
    "unroll arithmetic (mechanical, from the average trip count {trip}): "
    "{rows}. Whole-number parts are iterations of the unrolled body, the "
    "rest runs in the remainder; this is arithmetic, not a measurement.")

SCORE_LEVELS = [
    "Much slower: the whole program loses more than 5%.",
    "Slower: the whole program loses between 1% and 5%.",
    "No measurable change: within 1% either way, or the build is the "
    "baseline's.",
    "Faster: the whole program gains between 1% and 5%.",
    "Much faster: the whole program gains more than 5%.",
]
SCORE_Q = (
    "Section `{qname}` of the state describes one site of this program. If "
    "the build applied `{cand}` there and nothing else changed, how would "
    "the program's measured time change against the baseline? `{cand}`: "
    "{desc}")

TWO_STEP_Q1 = {
    "fn": ("Section `{qname}` of the state describes one marked function of "
           "this program. Is any hint from this site's list likely to make "
           "the program measurably faster?"),
    "loop": ("Section `{qname}` of the state describes one loop inside a "
             "marked function of this program. Is any hint from this site's "
             "list likely to make the program measurably faster?"),
}
TWO_STEP_OPTS = {
    "HINT": ("Yes: at least one hint in this site's list is likely to make "
             "the program measurably faster than the baseline."),
    KEEP: ("No: no hint in this site's list is likely to make the program "
           "measurably faster than the baseline; keep the site as it is."),
}
TWO_STEP_Q2 = {
    "fn": ("Section `{qname}` of the state describes one marked function of "
           "this program. Suppose one hint from the list below will be "
           "applied to it. Which one is most likely to make this function "
           "faster on this workload?"),
    "loop": ("Section `{qname}` of the state describes one loop inside a "
             "marked function of this program. Suppose one hint from the list "
             "below will be applied to it. Which one is most likely to make "
             "this loop faster on this workload?"),
}
INVERSE_Q = {
    "fn": ("Section `{qname}` of the state describes one marked function of "
           "this program. Which single hint from the list is most likely to "
           "make the program SLOWER on this workload?"),
    "loop": ("Section `{qname}` of the state describes one loop inside a "
             "marked function of this program. Which single hint from the "
             "list is most likely to make the program SLOWER on this "
             "workload?"),
}

RANDOM_ORDER_SEED = 20260924
SCORE_CHUNK_BYTES = 60000

# Phase 2 (false positives): the known ways each hint hurts, appended to its
# description identically at every site (H1).
HURTS_WHEN = {
    ("loop", "unroll_count"): (
        "Known ways it hurts, stated the same at every site: on a loop whose "
        "body is large or contains calls the copies grow the hot code past "
        "what the instruction cache held, and on a loop LLVM left "
        "un-unrolled because of its size or its calls, forcing copies "
        "undoes that decision."),
    ("loop", "unroll_disable"): (
        "Known ways it hurts, stated the same at every site: on a loop LLVM "
        "vectorised and interleaved it removes the interleaving (the same "
        "code as an interleave count of 1), and on a loop LLVM unrolled it "
        "removes the unrolling that was hiding loop overhead."),
    ("loop", "vectorize_width"): (
        "Known ways it hurts, stated the same at every site: below the width "
        "LLVM chose it processes fewer elements per iteration, and above it, "
        "where LLVM's width already fills a register and LLVM interleaves, "
        "the extra lanes can replace interleaving with shuffles and cut "
        "throughput."),
    ("loop", "interleave_count"): (
        "Known ways it hurts, stated the same at every site: below the count "
        "LLVM chose on a long loop it removes independent chains that were "
        "hiding latency (a count of 1 leaves one chain), and above it it "
        "adds register pressure and a longer remainder."),
    ("fn", "inline_always"): (
        "Known ways it hurts, stated the same at every site: on a function "
        "the baseline already inlines at its call sites it changes nothing, "
        "and on one the baseline declined because its cost exceeds the "
        "threshold, forcing it grows every caller's hot code."),
    ("fn", "inline_never"): (
        "Known ways it hurts, stated the same at every site: on a function "
        "the baseline inlines into a hot caller it adds a call and a return "
        "per use and removes the scheduling and constant folding the inlined "
        "copy had, and on one the baseline already keeps out of line it "
        "changes nothing."),
}


def hurts_when(kind, cid):
    if kind == "fn":
        return HURTS_WHEN[("fn", cid)]
    if cid == "unroll_disable":
        return HURTS_WHEN[("loop", "unroll_disable")]
    return HURTS_WHEN[("loop", cid.rpartition("_")[0])]


KEEP_FIRST_Q = {
    "fn": ("Section `{qname}` of the state describes one marked function of "
           "this program. Answer KEEP_DEFAULT unless a fact in that section "
           "or below says that a hint from the list will make the program "
           "measurably faster; otherwise pick that hint."),
    "loop": ("Section `{qname}` of the state describes one loop inside a "
             "marked function of this program. Answer KEEP_DEFAULT unless a "
             "fact in that section or below says that a hint from the list "
             "will make the program measurably faster; otherwise pick that "
             "hint."),
}

# Variant registry: name -> (phases it changes, description). A variant
# that changes only phase B reuses B0's phase A answers (it sends nothing
# for A), which is the pre-registered reading of its function half.
VARIANTS = {
    "B0": ("AB", "baseline: v6 vocabulary and state as the driver sends"),
    "L1": ("B", "v7 loop candidate texts (mechanism + helps/hurts)"),
    "L2": ("B", "verdict block -> raw labelled facts, no inferences"),
    "L3": ("B", "verdict block without the lane-count conclusion"),
    "L4": ("B", "neutral text for 'loop not found after LoopVectorize'"),
    "L5": ("B", "verdict block + unroller outcome and unroll arithmetic"),
    "L6": ("AB", "leaf-location remarks / inline remarks copied into the "
                 "question"),
    "L7": ("AB", "one Score question per (site, candidate)"),
    "L8": ("AB", "two-step: worth-a-hint? x which hint (KEEP removed)"),
    "L9": ("AB", "inverse: which hint is most likely HARMFUL"),
    "L10": ("AB", "one request per site"),
    "L11": ("AB", "candidates in one fixed random order"),
    "L12": ("AB", "'no hint has been measured here' line in the question"),
    "L13": ("AB", "source excerpts dropped from the state"),
    # phase 2 (false positives), results.md 173 follow-up
    "H1": ("AB", "known ways each hint hurts, appended to every description"),
    "H2": ("AB", "explicit facts behind those ways (inlining / VF-IC lines)"),
    "H3": ("AB", "KEEP-first question wording"),
}


def variant_phases(variant):
    ph = set()
    for part in variant.split("+"):
        ph |= set(VARIANTS[part][0])
    return "".join(sorted(ph))

# The static texts a variant adds, for the leak check.
STATIC_TEXTS = ([V7_LOOP[k] for k in V7_LOOP] + [NO_HINT_MEASURED,
                RAW_FACTS_PREAMBLE, SOURCE_OMITTED, PV_NOT_FOUND_NEUTRAL,
                REMARKS_IN_Q_LOOP, REMARKS_IN_Q_FN, UNROLL_ARITH, SCORE_Q]
                + SCORE_LEVELS + list(TWO_STEP_Q1.values())
                + list(TWO_STEP_OPTS.values()) + list(TWO_STEP_Q2.values())
                + list(INVERSE_Q.values())
                + list(HURTS_WHEN.values()) + list(KEEP_FIRST_Q.values()))

LEAK_RE = re.compile(
    r"\bk[1-8]\b|hbkernels|hintbench|zopfli|squeeze|lz77|jaq|hifijson|"
    r"index\.rs|range\.rs|macros\.rs|lib\.rs|\b(?:325|275|563|530|184)\b|"
    r"8\.8|4\.4|2\.65|1\.3%|find_longest|get_best|Val::hash|write_until",
    re.I)


def leak_check():
    hits = []
    for t in STATIC_TEXTS:
        for m in LEAK_RE.finditer(t):
            hits.append(m.group(0))
    return hits


# ---------------------------------------------------------------------------
# rendering helpers
# ---------------------------------------------------------------------------

def base_request(search, phase, items=None, ctx=None):
    ctx = ctx or phase_ctx(search, phase)
    items = items if items is not None else phase_items(search, phase)
    questions, site_map = S.questions_for(items, ctx, search.knobs)
    state = S.state_header(ctx, len(items)) + "".join(
        S.state_section(it, ctx) for it in items)
    return state, questions, site_map, ctx


def _verdict_split(instr):
    """(question text, verdict block or '')."""
    i = instr.find("\n\n" + S.VERDICT_PREAMBLE)
    if i < 0:
        return instr, ""
    return instr[:i], instr[i:]


def _block(lines, preamble=S.VERDICT_PREAMBLE):
    return "\n\n" + preamble + "\n" + "\n".join("  - " + l for l in lines)


def leaf_remarks(it, ctx):
    m = it.meta
    if not m.get("leaf_file"):
        return [], None
    texts = ctx["remarks"].at(m.get("leaf_file"), m.get("leaf_line"),
                              m.get("leaf_col"))
    n = ctx["remarks"].n_loops_at(m.get("leaf_file"), m.get("leaf_line"),
                                  m.get("leaf_col"))
    return texts, n


def unroll_outcome(it, ctx):
    texts, n = leaf_remarks(it, ctx)
    base = os.path.basename(it.meta.get("leaf_file") or "?")
    if n and n > 1:
        return None, ("unroller in the baseline build: UNKNOWN for this loop "
                      "--- its leaf location is shared by %d loops, so an "
                      "unroll remark there cannot be assigned to it" % n)
    for t in texts:
        mm = re.search(r"unrolled loop by a factor of (\d+)( with run-time "
                       r"trip count)?", t)
        if mm:
            return int(mm.group(1)), (
                "unroller in the baseline build, from the remark at this "
                "loop's own leaf location: unrolled by a factor of %s%s"
                % (mm.group(1), " with a run-time trip count"
                   if mm.group(2) else ""))
        if "completely unrolled" in t:
            return None, ("unroller in the baseline build, from the remark "
                          "at this loop's own leaf location: %s" % t)
        if "advising against unrolling" in t:
            return 1, ("unroller in the baseline build, from the remark at "
                       "this loop's own leaf location: %s" % t)
    return 1, ("unroller in the baseline build: no unroll remark at this "
               "loop's own leaf location (%s:%s), i.e. LLVM did not report "
               "unrolling it" % (base, it.meta.get("leaf_line")))


def unroll_arith(it, ctx):
    trip = it.meta.get("trip_count")
    if trip is None:
        return None
    rows = []
    for u in (2, 4, 8):
        rows.append("factor %d -> %.1f unrolled + %.1f remainder"
                    % (u, float(int(trip // u)), float(trip - u * int(trip // u))))
    return UNROLL_ARITH.format(trip="%.1f" % float(trip), rows="; ".join(rows))


def raw_fact_lines(it, ctx):
    m = it.meta
    L = []
    trip = m.get("trip_count")
    L.append("average trip count (PGO profile): %s"
             % ("not recorded" if trip is None else "%.1f" % float(trip)))
    L.append("loop body: %s LLVM instructions" % m.get("body_inst_count"))
    L.append("calls inside the body: %s" % ("yes" if m.get("has_calls")
                                           else "no"))
    L.append("floating-point reduction in the body: %s"
             % ("yes" if m.get("has_fp_reduction") else "no"))
    L.append("loop nesting depth: %s" % m.get("depth"))
    chain = ctx["demangler"].many(m.get("inline_chain") or [])
    elem = S._elem_type(chain)
    L.append("element type at the loop's iterator: %s"
             % (elem or "not derivable from the inline chain"))
    pv = m.get("post_vectorize")
    if isinstance(pv, dict) and pv.get("watched"):
        if pv.get("ambiguous_signature"):
            L.append("after LoopVectorize (plugin record): unknown, two "
                     "loops share a signature")
        elif not pv.get("exists"):
            L.append("after LoopVectorize (plugin record): loop not found "
                     "by its signature")
        elif pv.get("isvectorized"):
            L.append("after LoopVectorize (plugin record): vectorized = yes")
            L.append("vector width LLVM chose: %s" % pv.get("vector_width"))
            L.append("interleave count LLVM chose: %s"
                     % pv.get("interleave_count"))
        else:
            L.append("after LoopVectorize (plugin record): vectorized = no")
    else:
        L.append("after LoopVectorize (plugin record): not recorded")
    texts, n = leaf_remarks(it, ctx)
    if n and n > 1:
        L.append("remarks at this loop's leaf location: shared by %d loops, "
                 "not attributable to this one" % n)
    else:
        L.append("remarks at this loop's leaf location: %s"
                 % (" | ".join(texts) if texts else "none"))
    return L


class _NoSource:
    def __init__(self, real):
        self.real = real

    def excerpt(self, path, line, ctx=40):
        return SOURCE_OMITTED if path else None

    def __getattr__(self, name):
        return getattr(self.real, name)


# ---------------------------------------------------------------------------
# building the requests of one (variant, phase)
# ---------------------------------------------------------------------------

def _split_q(instr):
    """(the one-paragraph question, everything after it)."""
    i = instr.find("\n\n")
    return (instr, "") if i < 0 else (instr[:i], instr[i:])


def _fn_inline_lines(it, ctx):
    rows = (ctx["inlines"].outcomes(it.meta["linkages"])
            if ctx.get("inlines") else [])
    seen, lines = set(), []
    for r in rows:
        if r["inlined"]:
            t = ("inlined, %s" % ("always inline attribute at the call site"
                                  if r.get("always") else
                                  "cost=%s, threshold=%s"
                                  % (r["cost"], r["threshold"])))
        else:
            t = ("not inlined: %s (cost=%s, threshold=%s)"
                 % (r["reason"], r["cost"], r["threshold"]))
        ln = "  %s: %s" % (r["loc"], t)
        if ln not in seen:
            seen.add(ln)
            lines.append(ln)
    return rows, lines


def h2_fact_lines(it, ctx, kind):
    """Phase 2, H2: the facts behind the known ways a hint hurts, as
    mechanical lines (same rule everywhere)."""
    L = []
    if kind == "fn":
        rows, _l = _fn_inline_lines(it, ctx)
        n_in = sum(1 for r in rows if r["inlined"])
        n_out = len(rows) - n_in
        if not rows:
            L.append("baseline inlining of this function: no inline remark "
                     "names it, so whether the baseline inlines it is not "
                     "recorded")
        elif n_out == 0:
            L.append("baseline inlining of this function: inlined at all %d "
                     "recorded call sites, so `inline_always` asks for what "
                     "the baseline already does there, and `inline_never` "
                     "would take %d inlined copies out of line" % (n_in, n_in))
        elif n_in == 0:
            L.append("baseline inlining of this function: declined at all "
                     "%d recorded call sites, so `inline_never` asks for "
                     "what the baseline already does there, and "
                     "`inline_always` would paste it into %d callers against "
                     "the cost model" % (n_out, n_out))
        else:
            L.append("baseline inlining of this function: inlined at %d and "
                     "declined at %d recorded call sites" % (n_in, n_out))
        return L
    pv = it.meta.get("post_vectorize") or {}
    chain = ctx["demangler"].many(it.meta.get("inline_chain") or [])
    bits = S._elem_bits(S._elem_type(chain))
    if pv.get("exists") and pv.get("isvectorized") and pv.get("vector_width"):
        vf, ic = pv.get("vector_width"), pv.get("interleave_count") or 1
        L.append("what a width or interleave hint changes here: LLVM chose "
                 "width %d and interleave count %d, i.e. %d elements per "
                 "vector iteration; a width below %d or an interleave count "
                 "below %d does less per iteration than the baseline, a "
                 "width above %d or a count above %d does more with more "
                 "registers" % (vf, ic, vf * ic, vf, ic, vf, ic))
        if bits:
            L.append("register arithmetic: at %d bits per element, width %d "
                     "is %d bits per vector value (%s of a 256-bit "
                     "register)" % (bits, vf, bits * vf,
                                    "%.2g" % (bits * vf / 256.0)))
    elif pv.get("exists") and not pv.get("isvectorized"):
        L.append("what a width or interleave hint changes here: LLVM did "
                 "not vectorize this loop, so there is no vector width or "
                 "interleave count of the baseline's to change")
    return L


def apply_qt(v, search, items, ctx, questions, kind, req):
    """Question-level transforms; composable, the same rule at every site."""
    for it in items:
        q = questions[it.qname]
        head, rest = _split_q(q["instructions"])
        if v == "L1":
            if kind == "loop":
                q["criteria"] = v7_loop_candidates(q["criteria"])
        elif v in ("L2", "L3", "L4", "L5"):
            if kind != "loop":
                continue
            _h, block = _verdict_split(q["instructions"])
            tail = q["instructions"][len(_h) + len(block):]
            lines = S.loop_verdict_lines(it, ctx)
            if v == "L2":
                q["instructions"] = head + _block(raw_fact_lines(it, ctx),
                                                  RAW_FACTS_PREAMBLE) + tail
                continue
            if v == "L3":
                lines = [re.sub(r"^(element type at the loop's iterator: "
                                r"\S+ \(read off the inline chain\)).*$",
                                r"\1", l) for l in lines]
            if v == "L4":
                lines = [PV_NOT_FOUND_NEUTRAL
                         if "is no longer in the program" in l else l
                         for l in lines]
            if v == "L5":
                _f, uline = unroll_outcome(it, ctx)
                lines = lines + [uline]
                ar = unroll_arith(it, ctx)
                if ar:
                    lines.append(ar)
            q["instructions"] = head + _block(lines) + tail
        elif v == "L6":
            if kind == "loop":
                texts, n = leaf_remarks(it, ctx)
                shared = ("" if not (n and n > 1) else
                          " (CAUTION: %d loops share this location, so these "
                          "lines are pooled and none can be assigned to this "
                          "loop)" % n)
                body = "\n".join("  %s" % t for t in texts) or "  (none)"
                q["instructions"] += REMARKS_IN_Q_LOOP.format(
                    shared=shared) + body
            else:
                _r, lines = _fn_inline_lines(it, ctx)
                q["instructions"] += REMARKS_IN_Q_FN + (
                    "\n".join(lines[:12]) or "  (none recorded)")
        elif v == "L11":
            order = list(V.candidates_for(kind))
            random.Random(RANDOM_ORDER_SEED).shuffle(order)
            req.setdefault("meta", {})["order"] = order
            c = q["criteria"]
            q["criteria"] = {k: c[k] for k in order if k in c}
        elif v == "L12":
            q["instructions"] += NO_HINT_MEASURED
        elif v == "H1":
            q["criteria"] = {c: (d if c == KEEP else
                                 d + " " + hurts_when(kind, c))
                             for c, d in q["criteria"].items()}
        elif v == "H2":
            extra = h2_fact_lines(it, ctx, kind)
            if extra:
                q["instructions"] += "\n" + "\n".join(
                    "  - " + l for l in extra)
        elif v == "H3":
            q["instructions"] = KEEP_FIRST_Q[kind].format(
                qname=it.qname) + rest
        else:
            raise ValueError("not a question transform: %r" % v)


QT = ("L1", "L2", "L3", "L4", "L5", "L6", "L11", "L12", "H1", "H2", "H3")
STRUCT = ("B0", "L13", "L7", "L8", "L9", "L10")


def parse_variant(variant):
    """'L5' -> ([], 'B0', ['L5']); 'C1=L5+H1' style composites as
    'L5+H1' -> question transforms in order, one structural shape."""
    parts = variant.split("+")
    qts = [p for p in parts if p in QT]
    st = [p for p in parts if p in STRUCT and p != "B0"]
    if len(st) > 1 or len(qts) + len(st) != len([p for p in parts
                                                 if p != "B0"]):
        raise ValueError("bad variant %r" % variant)
    return qts, (st[0] if st else "B0")


def site_batches(search, phase, items, ctx):
    cap = TARGETS[search.target].get("batch_chars")
    if not cap:
        return [items]
    overhead = len(S.state_header(ctx, len(items)))
    out, cur, size = [], [], overhead
    for it in items:
        n = len(S.state_section(it, ctx))
        if cur and size + n > cap:
            out.append(cur)
            cur, size = [], overhead
        cur.append(it)
        size += n
    if cur:
        out.append(cur)
    return out


def build_requests(search, variant, phase):
    """A list of {tag, state, questions, site_map, readout, meta} dicts."""
    items = phase_items(search, phase)
    if not items:
        return []
    _qts, shape = parse_variant(variant)
    ctx0 = phase_ctx(search, phase)
    batches = ([items] if shape == "L10"
               else site_batches(search, phase, items, ctx0))
    if len(batches) == 1:
        return _build_requests(search, variant, phase, items)
    out = []
    for bi, b in enumerate(batches):
        for r in _build_requests(search, variant, phase, b):
            r["tag"] = r["tag"].replace(phase, "%s.b%d" % (phase, bi), 1)
            out.append(r)
    return out


def _build_requests(search, variant, phase, items):
    kind = "fn" if phase == "A" else "loop"
    qts, shape = parse_variant(variant)
    ctx = phase_ctx(search, phase)
    if shape == "L13":
        ctx = dict(ctx)
        ctx["source"] = _NoSource(ctx["source"])

    def one(sub):
        state, questions, site_map, _c = base_request(search, phase, sub, ctx)
        req = {"tag": phase, "state": state, "questions": questions,
               "site_map": site_map, "readout": "choice"}
        for v in qts:
            apply_qt(v, search, sub, ctx, questions, kind, req)
        return req

    if shape == "L10":
        out = []
        for it in items:
            r = one([it])
            r["tag"] = "%s.%s" % (phase, it.id)
            out.append(r)
        return out
    req = one(items)
    questions, state, site_map = req["questions"], req["state"], \
        req["site_map"]
    if shape in ("B0", "L13"):
        return [req]
    if shape == "L7":
        qs, sm = {}, {}
        for it in items:
            head, rest = _split_q(questions[it.qname]["instructions"])
            for j, (cid, desc) in enumerate(
                    questions[it.qname]["criteria"].items()):
                qn = "%s_c%d" % (it.qname, j)
                qs[qn] = {"type": "score",
                          "instructions": SCORE_Q.format(
                              qname=it.qname, cand=cid, desc=desc) + rest,
                          "criteria": list(SCORE_LEVELS)}
                sm[qn] = {"site_id": it.id, "kind": it.kind,
                          "label": it.label, "candidate": cid}
        # results.md 174 deviation: Score requests above ~60 KB did not land
        # (503/429 for 30 min per send), so the SAME questions are split
        # into chunks that share the same state; questions in one request
        # are answered independently anyway (docs/jev-samples/README.md).
        chunks, cur = [], {}
        base = len(json.dumps({"model": "typesafe-ai/jev", "state": state}))
        size = base
        for qn, q in qs.items():
            n = len(json.dumps({qn: q}))
            if cur and size + n > SCORE_CHUNK_BYTES:
                chunks.append(cur)
                cur, size = {}, base
            cur[qn] = q
            size += n
        if cur:
            chunks.append(cur)
        return [{"tag": phase if len(chunks) == 1 else "%s.c%d" % (phase, i),
                 "state": state, "questions": c,
                 "site_map": {k: sm[k] for k in c}, "readout": "score"}
                for i, c in enumerate(chunks)]
    if shape == "L8":
        q1, q2 = {}, {}
        for it in items:
            base_q = questions[it.qname]
            _h, rest = _split_q(base_q["instructions"])
            q1[it.qname] = {"type": "choice",
                            "instructions": TWO_STEP_Q1[kind].format(
                                qname=it.qname) + rest,
                            "criteria": dict(TWO_STEP_OPTS)}
            q2[it.qname] = {"type": "choice",
                            "instructions": TWO_STEP_Q2[kind].format(
                                qname=it.qname) + rest,
                            "criteria": {k: v for k, v in
                                         base_q["criteria"].items()
                                         if k != KEEP}}
        return [{"tag": phase + ".step1", "state": state, "questions": q1,
                 "site_map": site_map, "readout": "step1"},
                {"tag": phase + ".step2", "state": state, "questions": q2,
                 "site_map": site_map, "readout": "step2"}]
    if shape == "L9":
        for it in items:
            q = questions[it.qname]
            _h, rest = _split_q(q["instructions"])
            q["instructions"] = INVERSE_Q[kind].format(qname=it.qname) + rest
            q["criteria"] = {k: v for k, v in q["criteria"].items()
                             if k != KEEP}
        req["readout"] = "inverse"
        return [req]
    raise ValueError(shape)


# ---------------------------------------------------------------------------
# sending
# ---------------------------------------------------------------------------

def make_client(cfg, run_id):
    S.RETRY_JITTER = 0.0          # a fixed 2 s pause (task statement)
    jc = dict(cfg["jev"])
    os.makedirs(OUT_DIR, exist_ok=True)
    return S.JevClient(jc, OUT_DIR, run_id, source_comments="strip")


def send(client, req, repeat, variant):
    phase = "%s.%s" % (variant, req["tag"])
    answers, line_no = client.ask(req["state"], req["questions"], repeat,
                                  phase, req["site_map"])
    n = 0
    while answers is None and n < 2:          # [jev] phase_resend_max
        n += 1
        client.wait(10)
        answers, line_no = client.ask(req["state"], req["questions"], repeat,
                                      phase + ".retry%d" % n, req["site_map"])
    return answers, line_no


def cmd_run(a):
    hits = leak_check()
    print("[leak-check] static variant texts: %s"
          % ("clean" if not hits else "HITS %r" % hits))
    if hits:
        sys.exit("leak check failed")
    for target in a.targets:
        search, cfg = setup(target)
        run_id = "%s-%s" % (a.run_prefix, target)
        client = make_client(cfg, run_id)
        with open(client.log_path, "a") as f:
            f.write("# %s, target %s, vocab %s, state %s, leak check %s\n"
                    % (STUDY, target, V.VOCAB_VERSION,
                       S.STATE_FORMAT_VERSION, "clean" if not hits else hits))
        t0 = time.time()
        landed = set()
        if a.resume and os.path.isfile(client.jsonl_path):
            for line in open(client.jsonl_path):
                r = json.loads(line)
                if not r.get("exhausted"):
                    landed.add((r["round"], re.sub(r"\.retry\d*$", "",
                                                   r["phase"])))
            print("[resume] %d landed requests already in %s"
                  % (len(landed), client.jsonl_path))
        for rep in range(1, a.repeats + 1):
            for variant in a.variants:
                vph = variant_phases(variant)
                for phase in TARGETS[target]["phases"]:
                    if phase not in vph or (a.smoke and phase != "A"):
                        continue
                    reqs = build_requests(search, variant, phase)
                    if a.smoke:
                        reqs = reqs[:1]
                    for req in reqs:
                        if (rep, "%s.%s" % (variant, req["tag"])) in landed:
                            continue
                        ans, ln = send(client, req, rep, variant)
                        print("[%s r%d] %s %s -> %s (line %d)"
                              % (target, rep, variant, req["tag"][:40],
                                 "ok" if ans is not None else "LOST", ln))
        client.write_totals(time.time() - t0)
        print("[%s] totals %s gateway %s" % (target, client.totals,
                                             {k: v for k, v in
                                              client.gateway.items()
                                              if k != "attempts_by_phase"}))


def cmd_render(a):
    search, _cfg = setup(a.target)
    for req in build_requests(search, a.variant, a.phase):
        print("=" * 72)
        print("### %s %s (%d questions, readout %s, %d state chars)"
              % (a.variant, req["tag"], len(req["questions"]),
                 req["readout"], len(req["state"])))
        if a.full:
            print(req["state"])
        for qn, q in req["questions"].items():
            print("--- %s %s" % (qn, req["site_map"][qn]))
            print(q["instructions"])
            crit = q["criteria"]
            if isinstance(crit, dict):
                for k, v in crit.items():
                    print("  %s: %s" % (k, v))
            else:
                for i, v in enumerate(crit):
                    print("  [%d] %s" % (i, v))
            if not a.full:
                break


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def read_jsonl(path):
    return [json.loads(l) for l in open(path)]


def site_dists(records, variant, repeat, phase):
    """{site_id: {"P": {cand: p}, "pick": cand, "extra": {...}}}."""
    recs = [r for r in records if r["round"] == repeat
            and r["phase"].split(".")[0] == variant
            and r["phase"].split(".")[1] == phase
            and not r.get("exhausted")]
    # A later retry supersedes an exhausted line; keep landed lines only.
    # results.md 174 deviation: a Score (L7) request sent whole before the
    # chunking rule is superseded by the chunked requests of the same round.
    chunked = {re.sub(r"\.c\d+.*$", "", r["phase"]) for r in recs
               if re.search(r"\.c\d+", r["phase"])}
    recs = [r for r in recs if re.search(r"\.c\d+", r["phase"])
            or re.sub(r"\.retry\d*$", "", r["phase"]) not in chunked]
    out = {}
    step1, step2 = {}, {}
    for r in recs:
        ans = (r.get("response") or {}).get("answers") or {}
        tag = r["phase"]
        for qn, sm in r["site_map"].items():
            a = ans.get(qn) or {}
            sid = sm["site_id"]
            if a.get("type") == "score" or "candidate" in sm:
                pr = {int(k): float(v) for k, v in
                      (a.get("probabilities") or {}).items()}
                d = out.setdefault(sid, {"score": {}, "p_gain": {},
                                         "p_loss": {}})
                c = sm["candidate"]
                d["score"][c] = a.get("score")
                d["p_gain"][c] = pr.get(3, 0.0) + pr.get(4, 0.0)
                d["p_loss"][c] = pr.get(0, 0.0) + pr.get(1, 0.0)
            elif ".step1" in tag:
                step1[sid] = a.get("probabilities") or {}
            elif ".step2" in tag:
                step2[sid] = a.get("probabilities") or {}
            else:
                out[sid] = {"P": {k: float(v) for k, v in
                                  (a.get("probabilities") or {}).items()},
                            "choice": a.get("choice")}
    for sid in set(step1) | set(step2):
        p1 = step1.get(sid) or {}
        p2 = step2.get(sid) or {}
        ph = float(p1.get("HINT", 0.0))
        P = {KEEP: float(p1.get(KEEP, 1.0 - ph))}
        for c, v in p2.items():
            P[c] = ph * float(v)
        out[sid] = {"P": P, "p_hint": ph}
    return out


def readout(d, kind):
    """(P over candidates or None, pick) under the pre-registered rule."""
    if "score" in d:
        sc = {c: (s if s is not None else 2.0) for c, s in d["score"].items()}
        pick = max(sc, key=lambda c: (sc[c], c == KEEP))
        return None, pick
    P = d["P"]
    if kind == "inverse":
        # complement pick: the non-KEEP candidate Jev finds least likely to
        # be harmful (vocabulary order breaks ties)
        pick = min(P, key=lambda c: P[c]) if P else KEEP
        return P, pick
    pick = max(P, key=lambda c: P[c]) if P else KEEP
    return P, pick


def score_target(truth_t, records, variant, repeats, phase, inverse=False,
                 score=False):
    rows = []
    for rep in range(1, repeats + 1):
        ds = site_dists(records, variant, rep, phase)
        per = {}
        for sid, d in ds.items():
            t = truth_t.get(sid)
            if t is None:
                continue
            s = t["_summary"]
            P, pick = readout(d, "inverse" if inverse else "choice")
            good, harm = set(s["good"]), set(s["harmful"])
            noop = set(s["noop"]) | {KEEP}
            rec = {"best": s["best"], "pick": pick}
            if score:
                rec["score_best"] = d["score"].get(s["best"])
                rec["pgain_best"] = d["p_gain"].get(s["best"])
                rec["score_keep"] = d["score"].get(KEEP)
            elif P is not None:
                rec["P_best"] = P.get(s["best"], 0.0)
                rec["P_good"] = sum(P.get(c, 0.0) for c in good)
                rec["P_harm"] = sum(P.get(c, 0.0) for c in harm)
                rec["P_keep"] = P.get(KEEP, 0.0)
                rec["P_keepeq"] = sum(P.get(c, 0.0) for c in noop)
                rec["P"] = P
            if s["best"] == KEEP:
                rec["hit"] = pick == KEEP
                rec["hit_eq"] = pick in noop
            else:
                rec["hit"] = pick in good
                rec["hit_eq"] = pick in good
            rec["harm_pick"] = pick in harm
            per[sid] = rec
        rows.append(per)
    return rows


def med_range(xs, fmt="%.2f"):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "-"
    return (fmt + " [" + fmt + "-" + fmt + "]") % (
        statistics.median(xs), min(xs), max(xs))


def cmd_score(a):
    truth = json.load(open(TRUTH_PATH))
    out = {}
    for target in a.targets:
        path = os.path.join(a.log_dir, "%s-%s.jsonl" % (a.run_prefix, target))
        if not os.path.isfile(path):
            print("no log for %s" % target)
            continue
        records = read_jsonl(path)
        truth_t = {k: v for k, v in truth["targets"][target].items()}
        # Truth keys: the oracle's site ids are the driver's ids.
        out[target] = {}
        for variant in a.variants:
            for phase in TARGETS[target]["phases"]:
                src = variant if phase in VARIANTS[variant][0] else "B0"
                rows = score_target(truth_t, records, src, a.repeats, phase,
                                    inverse=(src == "L9"),
                                    score=(src == "L7"))
                out[target]["%s.%s" % (variant, phase)] = {
                    "source": src, "rows": rows}
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print("wrote %s" % a.out)


NAMED_FP = {
    "hintbench": {
        "hbkernels::k4_count_bytes@macros.rs:180:28#d2": ["vectorize_width_16",
                                                          "interleave_count_2"],
        "hbkernels::k5_mul_reduce@macros.rs:180:28#d2": ["interleave_count_1"],
        "hbkernels::k8_scale_add@range.rs:1103:12#d2": ["interleave_count_1",
                                                        "interleave_count_2"],
        "fn:hbkernels::k1_step": ["inline_never"]},
    "zopfli": {
        "fn:zopfli::lz77::find_longest_match": ["inline_always",
                                                "inline_never"],
        "fn:zopfli::squeeze::get_best_lengths": ["inline_never"],
        "fn:zopfli::squeeze::lz77_optimal": ["inline_always"],
        "fn:zopfli::squeeze::lz77_optimal_run": ["inline_never"],
        "zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2": [
            "unroll_count_4", "unroll_count_8"]},
    "jaq": {
        "fn:<hifijson::SliceLexer as hifijson::write::Write>::write_until": [
            "inline_never"]},
}

LOOP_TARGETS = {
    "hintbench": ["hbkernels::k3_fill_run@lib.rs:174:9#d3",
                  "hbkernels::k5_mul_reduce@macros.rs:180:28#d2",
                  "hbkernels::k8_scale_add@range.rs:1103:12#d2"],
    "zopfli": ["zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3"],
    "jaq": [],
}
FN_TARGETS = {
    "hintbench": ["fn:hbkernels::k2_mix"],
    "zopfli": [],
    "jaq": ["fn:<jaq_json::Val as core::hash::Hash>::hash",
            "fn:<hifijson::SliceLexer as hifijson::write::Write>::write_until"],
}


def short_site(sid):
    m = re.search(r"::(k\d)_", sid)
    if m:
        return m.group(1) + ("" if sid.startswith("fn:") else " loop")
    m = re.search(r"@(\w+\.rs):(\d+)", sid)
    if m:
        return "%s:%s" % m.groups()
    if "Val as core::hash" in sid:
        return "Val::hash"
    if "write_until" in sid:
        return "write_until"
    return sid[:30]


def dists_for(records, variant, rep, phase):
    """Per-site readout dicts under the pre-registered rule of `variant`."""
    if variant == "H4":
        b = site_dists(records, "B0", rep, phase)
        h = site_dists(records, "L9", rep, phase)
        out = {}
        for sid, d in b.items():
            if sid not in h:
                continue
            P = dict(d["P"])
            ph = h[sid].get("P") or {}
            for c in list(P):
                if c != KEEP:
                    P[c] = P[c] * (1.0 - ph.get(c, 0.0))
            z = sum(P.values()) or 1.0
            out[sid] = {"P": {c: v / z for c, v in P.items()}}
        return out
    if variant == "H5":
        return site_dists(records, "L8", rep, phase)
    return site_dists(records, variant, rep, phase)


def metrics(truth_t, records, variant, rep, phase, target):
    src = variant if phase in variant_phases_ro(variant) else "B0"
    ds = dists_for(records, src, rep, phase)
    shape = src.split("+")
    inverse = "L9" in shape
    score = "L7" in shape
    M = {"n": 0, "hits": 0, "hits_eq": 0, "harm_sites": 0, "harm_mass": [],
         "harm_argmax": 0, "keep_sites": 0, "keep_argmax": 0, "keep_P": [],
         "named_mass": [], "P": {}, "pick": {}, "missing": 0, "src": src}
    sites = [sid for sid in truth_t if (sid.startswith("fn:")) == (phase == "A")]
    for sid in sites:
        if sid not in ds:
            M["missing"] += 1
            continue
        su = truth_t[sid]["_summary"]
        P, pick = readout(ds[sid], "inverse" if inverse else "choice")
        good, harm = set(su["good"]), set(su["harmful"])
        noop = set(su["noop"]) | {KEEP}
        M["n"] += 1
        M["pick"][sid] = pick
        if su["best"] == KEEP:
            hit = pick == KEEP
            M["keep_sites"] += 1
            M["keep_argmax"] += int(pick == KEEP)
            if P is not None and not inverse:
                M["keep_P"].append(P.get(KEEP, 0.0))
        else:
            hit = pick in good
        M["hits"] += int(hit)
        M["hits_eq"] += int(hit or (su["best"] == KEEP and pick in noop))
        if harm:
            M["harm_sites"] += 1
            M["harm_argmax"] += int(pick in harm)
            if P is not None:
                M["harm_mass"].append(sum(P.get(c, 0.0) for c in harm))
        named = NAMED_FP.get(target, {}).get(sid)
        if named and P is not None:
            M["named_mass"].append(sum(P.get(c, 0.0) for c in named))
        if score:
            d = ds[sid]
            M["P"][sid] = d["score"].get(su["best"])
        elif P is not None:
            M["P"][sid] = P.get(su["best"], 0.0)
    return M


def variant_phases_ro(variant):
    if variant in ("H4", "H5"):
        return "AB"
    return variant_phases(variant)


def _mr(xs, fmt="%.2f"):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "-"
    if len(xs) == 1:
        return fmt % xs[0]
    return (fmt + " [" + fmt + ", " + fmt + "]") % (
        statistics.median(xs), min(xs), max(xs))


def cmd_report(a):
    truth = json.load(open(TRUTH_PATH))
    lines = []
    summary = {}
    for target in a.targets:
        path = os.path.join(a.log_dir, "%s-%s.jsonl" % (a.run_prefix, target))
        if not os.path.isfile(path):
            continue
        records = read_jsonl(path)
        truth_t = {k: v for k, v in truth["targets"][target].items()}
        summary[target] = {}
        for phase in TARGETS[target]["phases"]:
            tsites = LOOP_TARGETS[target] if phase == "B" else FN_TARGETS[target]
            head = (["variant"] + ["P(best) %s" % short_site(s)
                                   for s in tsites]
                    + ["argmax hits", "harm mass", "harm argmax",
                       "KEEP argmax @KEEP", "P(KEEP) @KEEP",
                       "named-FP mass", "missing"])
            lines.append("\n**%s, phase %s (%s)**\n" % (
                target, phase, "loops" if phase == "B" else "functions"))
            lines.append("| " + " | ".join(head) + " |")
            lines.append("|" + "---|" * len(head))
            for variant in a.variants:
                Ms = [metrics(truth_t, records, variant, r, phase, target)
                      for r in range(1, a.repeats + 1)]
                Ms = [m for m in Ms if m["n"]]
                if not Ms:
                    continue
                summary[target]["%s.%s" % (variant, phase)] = Ms
                row = [variant + ("" if Ms[0]["src"] == variant else
                                  " (=%s)" % Ms[0]["src"])]
                for s in tsites:
                    row.append(_mr([m["P"].get(s) for m in Ms]))
                n = Ms[0]["n"]
                row.append(_mr([m["hits"] for m in Ms], "%d") + "/%d" % n)
                row.append(_mr([statistics.mean(m["harm_mass"])
                                if m["harm_mass"] else None for m in Ms]))
                row.append(_mr([m["harm_argmax"] for m in Ms], "%d")
                           + "/%d" % Ms[0]["harm_sites"])
                row.append(_mr([m["keep_argmax"] for m in Ms], "%d")
                           + "/%d" % Ms[0]["keep_sites"])
                row.append(_mr([statistics.mean(m["keep_P"])
                                if m["keep_P"] else None for m in Ms]))
                row.append(_mr([sum(m["named_mass"])
                                if m["named_mass"] else None for m in Ms]))
                row.append(str(sum(m["missing"] for m in Ms)))
                lines.append("| " + " | ".join(row) + " |")
    txt = "\n".join(lines)
    print(txt)
    if a.out:
        open(a.out, "w").write(txt + "\n")
        with open(a.out.replace(".md", ".json"), "w") as f:
            json.dump(summary, f, indent=1, default=list)


def cmd_stability(a):
    """request_sha256 identity across repeats, max |dP| and argmax flips."""
    for target in a.targets:
        path = os.path.join(a.log_dir, "%s-%s.jsonl" % (a.run_prefix, target))
        if not os.path.isfile(path):
            continue
        recs = [r for r in read_jsonl(path) if not r.get("exhausted")]
        by = {}
        for r in recs:
            key = re.sub(r"\.retry\d*$", "", r["phase"])
            by.setdefault(key, {})[r["round"]] = r
        print("== %s" % target)
        agg = {}
        for key, reps in sorted(by.items()):
            v = key.split(".")[0]
            shas = {x["request_sha256"] for x in reps.values()}
            dmax, flips = 0.0, 0
            per_q = {}
            for x in reps.values():
                for qn, ans in ((x.get("response") or {}).get("answers")
                                or {}).items():
                    per_q.setdefault(qn, []).append(ans)
            for qn, lst in per_q.items():
                if lst and lst[0].get("type") == "choice":
                    ch = {x.get("choice") for x in lst}
                    flips += int(len(ch) > 1)
                    keys = set().union(*[set((x.get("probabilities") or {}))
                                         for x in lst])
                    for k in keys:
                        vals = [float((x.get("probabilities") or {}).get(k, 0))
                                for x in lst]
                        dmax = max(dmax, max(vals) - min(vals))
            g = agg.setdefault(v, {"reqs": 0, "same_sha": 0, "dmax": 0.0,
                                   "flips": 0, "n_rep": 0})
            g["reqs"] += 1
            g["same_sha"] += int(len(shas) == 1)
            g["dmax"] = max(g["dmax"], dmax)
            g["flips"] += flips
            g["n_rep"] = max(g["n_rep"], len(reps))
        for v, g in agg.items():
            print("  %-8s requests %2d, byte-identical across repeats %2d, "
                  "repeats %d, max|dP| %.2f, argmax flips %d"
                  % (v, g["reqs"], g["same_sha"], g["n_rep"], g["dmax"],
                     g["flips"]))


def cmd_gateway(a):
    """Request / attempt / 503 / 429 / token / cost totals from the JSONL."""
    for path in sorted(a.paths):
        recs = read_jsonl(path)
        att = [x for r in recs for x in (r.get("attempt_log") or [])]
        tin = sum(int(((r.get("response") or {}).get("usage") or {})
                      .get("input_tokens") or 0) for r in recs)
        tout = sum(int(((r.get("response") or {}).get("usage") or {})
                       .get("output_tokens") or 0) for r in recs)
        cost = 0.0
        for r in recs:
            try:
                cost += float((((r.get("response") or {}).get(
                    "provider_metadata") or {}).get("gateway") or {})
                    .get("cost") or 0)
            except (TypeError, ValueError):
                pass
        print("%-40s requests %4d landed %4d exhausted %3d attempts %5d "
              "503 %5d 429 %3d waited %6.0f s tokens %d/%d cost $%.4f"
              % (os.path.basename(path), len(recs),
                 sum(1 for r in recs if not r.get("exhausted")),
                 sum(1 for r in recs if r.get("exhausted")), len(att),
                 sum(1 for x in att if x.get("http_status") == 503),
                 sum(1 for x in att if x.get("http_status") == 429),
                 sum(float(r.get("seconds_waiting") or 0) for r in recs),
                 tin, tout, cost))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("truth")
    r = sub.add_parser("render")
    r.add_argument("target", choices=sorted(TARGETS))
    r.add_argument("variant")
    r.add_argument("phase", choices=("A", "B"))
    r.add_argument("--full", action="store_true")
    sub.add_parser("leak")
    ru = sub.add_parser("run")
    ru.add_argument("--targets", nargs="+", default=list(TARGETS))
    ru.add_argument("--variants", nargs="+", default=list(VARIANTS))
    ru.add_argument("--repeats", type=int, default=3)
    ru.add_argument("--run-prefix", default="ps2")
    ru.add_argument("--resume", action="store_true",
                    help="skip (repeat, variant, tag) requests that landed")
    ru.add_argument("--smoke", action="store_true",
                    help="one request per (variant, phase): wire check")
    sc = sub.add_parser("score")
    sc.add_argument("--targets", nargs="+", default=list(TARGETS))
    sc.add_argument("--variants", nargs="+", default=list(VARIANTS))
    sc.add_argument("--repeats", type=int, default=3)
    sc.add_argument("--run-prefix", default="ps2")
    sc.add_argument("--log-dir", default=OUT_DIR)
    sc.add_argument("--out", default=os.path.join(OUT_DIR, "scores.json"))
    for name in ("report", "stability"):
        rp = sub.add_parser(name)
        rp.add_argument("--targets", nargs="+", default=list(TARGETS))
        rp.add_argument("--variants", nargs="+",
                        default=list(VARIANTS) + ["H4", "H5"])
        rp.add_argument("--repeats", type=int, default=3)
        rp.add_argument("--run-prefix", default="ps2")
        rp.add_argument("--log-dir", default=OUT_DIR)
        rp.add_argument("--out", default=None)
    gw = sub.add_parser("gateway")
    gw.add_argument("paths", nargs="+")
    a = p.parse_args()
    if a.cmd == "gateway":
        return cmd_gateway(a)
    if a.cmd == "report":
        return cmd_report(a)
    if a.cmd == "stability":
        return cmd_stability(a)
    if a.cmd == "truth":
        print_truth(derive_truth())
    elif a.cmd == "render":
        cmd_render(a)
    elif a.cmd == "leak":
        h = leak_check()
        print("clean" if not h else "HITS %r" % h)
    elif a.cmd == "run":
        cmd_run(a)
    elif a.cmd == "score":
        cmd_score(a)


if __name__ == "__main__":
    main()
