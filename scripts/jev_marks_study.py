#!/usr/bin/env python3
"""Marks study (API only): can Jev choose the marks from perf alone?

results.md 176 (pre-registration) and 177 (results). Nothing is built,
nothing is timed and no binary is run. The inputs are the perf tables
already on disk (zopfli: artifacts/zopfli-marks/perf-{self,inline}-*.tsv;
jaq: artifacts/jaq-marks/perf-{self,inline}.tsv; hintbench: no perf table,
eight kernels at an equal share by construction) plus `nm -S` of the
profiled binaries (whose .text hashes are checked). The state lists every
function uniformly and alphabetically; it carries no Stage 0, oracle or
marks knowledge (checked by `leak_check()`).

Subcommands:

  build              write the per-target function tables -> inputs.json
  render T Q         print the request(s) of target T, question Q1|Q2
  run                send targets x {Q1,Q2} x repeats, log JSONL + .log
  score              read the JSONL back; metrics for Jev and the controls
                     -> scores.json + report.md

The API client, retry policy and logging are `jev_search.JevClient`, as in
scripts/jev_prompt_study2.py (the Authorization header is never logged).
"""

import argparse
import collections
import csv
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jev_search as S          # noqa: E402

REPO = S.REPO
STUDY = "marks-study-2026-09-24"
OUT_DIR = os.path.join(REPO, "artifacts", "jev-marks-study")
DOC_DIR = os.path.join(REPO, "docs", "experiments", "jev-marks-study")
INPUTS = os.path.join(OUT_DIR, "inputs.json")
INPUTS_V2 = os.path.join(OUT_DIR, "inputs-v2.json")
INPUT_SET = "v1"             # --inputs; v2 = results.md 176.7 (amendment)
# 176.7: post-LTO structure per source function, from
# scripts/inline_structure.py over every sampled symbol (hintbench: every
# text symbol), written by `build --inputs v2` next to the inputs.
STRUCT_TSV = os.path.join(OUT_DIR, "%s-inline-structure.tsv")
# 176.7 hybrid (Q3): the mechanical rule, fixed before any v2 request.
HYB_MARK_REACH = 5.0         # training reach >= 5% and backedges > 0: mark
HYB_SKIP_REACH = 1.0         # training reach < 1%: skip
HYB_THUNK_INSNS = 8          # <= 8 instructions incl. inlined code: skip
CASES = {"jaq": ["objsearch", "readwrite", "strproc"],
         "zopfli": ["binary", "json", "text"]}

# Pre-registered (results.md 176.2): list floor and request size cap.
REACH_FLOOR = 1.0            # percent, max(training, holdout) reach
BODY_CAP = 60000             # bytes per request body (study 2, 174 dev.)
NAME_CAP_STATE = 300         # characters of a name shown in the state
NAME_CAP_Q = 160             # ... and in a question

TARGETS = {
    "jaq": dict(
        binary="target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/jaq",
        text_sha="642dd55e",
        self_tsv="artifacts/jaq-marks/perf-self.tsv",
        inline_tsv="artifacts/jaq-marks/perf-inline.tsv",
        marks="targets/jaq/jev-marks.txt",
        workloads=("three training cases (objsearch, readwrite, strproc) "
                   "and three holdout cases (the same filters on other "
                   "inputs), 6 runs each"),
        positives=["<jaq_json::Val as core::hash::Hash>::hash",
                   "<hifijson::SliceLexer as hifijson::write::Write>"
                   "::write_until"],
        positives_extra=[],
        harmful=["<hifijson::SliceLexer as hifijson::write::Write>"
                 "::write_until"]),
    "zopfli": dict(
        binary="target-zopfli-sites-base/x86_64-unknown-linux-gnu/release/"
               "zopfli",
        text_sha="9aca86fc",
        self_tsv="artifacts/zopfli-marks/perf-self-%s.tsv",
        inline_tsv="artifacts/zopfli-marks/perf-inline-%s.tsv",
        data="artifacts/zopfli-marks/%s-*.data",
        marks="targets/zopfli/jev-marks.txt",
        workloads=("three training cases (binary, json, text) and three "
                   "holdout cases (other files of the same three kinds), "
                   "6 runs each"),
        positives=["zopfli::squeeze::lz77_optimal"],
        positives_extra=["zopfli::lz77::find_longest_match_loop"],
        harmful=["zopfli::lz77::find_longest_match",
                 "zopfli::squeeze::get_best_lengths",
                 "zopfli::squeeze::lz77_optimal"]),
    "hintbench": dict(
        binary="target-hintbench-pgo-use/x86_64-unknown-linux-gnu/release/"
               "hintbench",
        text_sha="df5968bc",
        marks="targets/hintbench/jev-marks.txt",
        positives=["hbkernels::k2_mix", "hbkernels::k3_fill_run",
                   "hbkernels::k8_scale_add"],
        positives_extra=[],
        harmful=[]),
}

# ---------------------------------------------------------------------------
# fixed texts (identical for every function; results.md 176.3)
# ---------------------------------------------------------------------------

Q1_INSTR = (
    "Function {fid} of the table in the state (`{name}`). Decide whether to "
    "mark it. A marked function is one where a compiler hint (function "
    "attribute or loop metadata on its loops) could plausibly change the "
    "program's speed; unmarked functions are never touched.")
Q1_CRIT = {
    "mark": ("Mark this function: a compiler hint on it could plausibly "
             "change the program's speed."),
    "skip": ("Do not mark this function: no compiler hint on it is likely "
             "to change the program's speed, and it will never be touched."),
}
Q2_INSTR = (
    "Function {fid} of the table in the state (`{name}`). How likely is a "
    "hint on this function to change the program's speed? A hint is a "
    "compiler hint on this function: a function attribute, or loop "
    "metadata on its loops.")
Q2_LEVELS = [
    "Very unlikely: a hint on this function would almost certainly not "
    "change the program's speed.",
    "Unlikely: a hint on this function would probably not change the "
    "program's speed.",
    "Possible: a hint on this function may or may not change the program's "
    "speed.",
    "Likely: a hint on this function would probably change the program's "
    "speed.",
    "Very likely: a hint on this function would almost certainly change the "
    "program's speed.",
]

# ---------------------------------------------------------------------------
# phase 3 (results.md 176.8): verdict lines (M1), per-case questions (M2),
# a uniform criteria block (M3), and their combinations (M4 = M1+M3,
# M5 = M1+M2+M3). All on the v2 state; texts identical for every function.
# ---------------------------------------------------------------------------

OWN_CRATES = {"jaq": ("jaq", "jaq_json", "jaq_core", "jaq_std", "jaq_all"),
              "zopfli": ("zopfli",), "hintbench": ("hbkernels", "hintbench")}
P3_VERDICT_PREAMBLE = (
    "Mechanical readings for this function. Each line is produced by a tool "
    "from the table in the state, by the same rule for every function in "
    "this request; none of them is an opinion about whether to mark it.")
M3_CRIT = {
    "mark": ("Mark this function. A function attribute can change the "
             "program's speed only if the function is called (not inlined) "
             "or is inlined at a call with constant arguments; loop metadata "
             "can change it only if a machine-code loop survives LTO."),
    "skip": ("Do not mark this function. Neither condition holds for it: it "
             "is not called and not inlined at a call with constant "
             "arguments, and no machine-code loop of it survives LTO; it "
             "will never be touched."),
}
M2_PREFIX = "For the `{case}` workload only. "
P3_VARIANTS = ("M1", "M2", "M3", "M4", "M5")


def p3_parts(q):
    """'M5@strproc' -> ('M5', 'strproc'); 'M1' -> ('M1', None)."""
    v, _s, case = q.partition("@")
    return v, (case or None)


def p3_expand(target, qs):
    """M2 / M5 become one question set per case."""
    out = []
    for q in qs:
        if q in ("M2", "M5"):
            out += ["%s@%s" % (q, c) for c in CASES.get(target, [])]
        else:
            out.append(q)
    return out


def p3_ranks(b):
    rows = b["rows"]
    alpha = {d["name"]: i for i, d in enumerate(rows)}
    rr = sorted(rows, key=lambda d: (-d["reach_train"], alpha[d["name"]]))
    sr = sorted(rows, key=lambda d: (-(d["self_train"] or 0.0),
                                     alpha[d["name"]]))
    def comp(order, key):        # competition ranking: ties share a rank
        out, prev, rank = {}, None, 0
        for i, d in enumerate(order, 1):
            v = key(d)
            if v != prev:
                rank, prev = i, v
            out[d["name"]] = rank
        return out
    return (comp(rr, lambda d: d["reach_train"]),
            comp(sr, lambda d: d["self_train"] or 0.0))


def p3_verdict_lines(b, d, ranks):
    target = b["target"]
    rr, sr = ranks
    M = len(b["rows"])
    own = OWN_CRATES[target]
    lines = []
    be = d.get("backedges")
    lines.append("machine-code loops after LTO: %s" % (
        "unknown (none of its code is in a sampled symbol)" if be is None
        else ("yes (%d backward jumps)" % be if be > 0
              else "no (0 backward jumps)")))
    hosts = d.get("hosts") or 0
    if d["own_symbol"]:
        called = ("yes" if hosts <= 1 else
                  "yes, and copies are also inlined into %d other symbols"
                  % (hosts - 1))
    else:
        called = "no (its code is inlined into %d symbols)" % hosts
    lines.append("called, not inlined: %s" % called)
    lines.append("own symbol in the final binary: %s"
                 % ("yes" if d["own_symbol"] else "no"))
    crate = d.get("crate") or "?"
    from_other = crate not in own
    on_ours = any(("%s::" % c) in d["name"] for c in own)
    lines.append("generic from another crate instantiated inside this "
                 "program's LTO unit: %s" % (
                     "yes" if from_other and on_ours else "no"))
    if d.get("per_case"):
        lines.append("share of cycles per case (reach): " + ", ".join(
            "%s %.1f%%" % (c, d["per_case"][c]) for c in CASES[target]))
    else:
        lines.append("share of cycles per case (reach): not measured")
    lines.append("reach rank: %d of %d" % (rr[d["name"]], M))
    lines.append("self-time rank: %s" % (
        "%d of %d" % (sr[d["name"]], M) if d["self_train"] is not None
        else "not measured"))
    return lines


def p3_question(b, d, q, ranks):
    v, case = p3_parts(q)
    instr = Q1_INSTR.format(fid=d["id"], name=cut(d["name"], NAME_CAP_Q))
    if case:
        instr = M2_PREFIX.format(case=case) + instr.replace(
            "Decide whether to mark it.",
            "Decide whether to mark it for this workload.")
    if v in ("M1", "M4", "M5"):
        instr += ("\n\n" + P3_VERDICT_PREAMBLE + "\n" + "\n".join(
            "  - " + l for l in p3_verdict_lines(b, d, ranks)))
    crit = dict(M3_CRIT) if v in ("M3", "M4", "M5") else dict(Q1_CRIT)
    return {"type": "choice", "instructions": instr, "criteria": crit}


STATE_HEAD = """\
# Profile of the program `{target}`

The program is written in Rust and built for speed: opt-level 3,
target-cpu native, fat LTO, one codegen unit and profile-guided
optimisation. A compiler hint can be attached to a function before it is
compiled: a function attribute on the function itself, or loop metadata on
the loops inside it. This state lists the functions of the program with
what a profile says about each of them. Every function is described in the
same way, and the list is in alphabetical order, not in order of
importance.

## Where the numbers come from

{profile}

## Columns

- `id`: a label for the function in this list.
- `self train` / `self hold`: {self_col}
- `reach train` / `reach hold`: {reach_col}
- `own symbol`: `yes` if a symbol of this name exists in the final binary;
  `no` if the function survives only as code inlined into other functions.
- `size`: bytes of the function's own symbol(s) in the final binary; `-`
  when it has no own symbol.
- Call counts are not available (no call graphs were recorded).
- Names longer than {cap} characters are cut and end in `…`.

{excluded}

## Functions ({n})

id | function | self train | self hold | reach train | reach hold | own symbol | size
"""

PERF_PROFILE = (
    "`perf record -e cycles:u` sampled the instruction pointer of the "
    "baseline binary on {workloads}. The training numbers come from the "
    "training cases and the holdout numbers from the holdout cases. Every "
    "percentage is a share of the user-mode cycles spent inside the "
    "program's own binary (operating-system and C library time are left "
    "out). {agg}")
HB_PROFILE = (
    "No sampling profile was recorded. The program runs eight workloads "
    "back to back, each calibrated to the same wall time and each spent in "
    "one of the eight functions below, so each function's share is one "
    "eighth by construction; `self` is not measured.")
SELF_COL = ("percentage of cycles spent in the function's own symbol(s) in "
            "the final binary, all copies summed.")
REACH_COL = ("percentage of cycles running machine code that belongs to "
             "the function wherever the compiler placed it: its own body, "
             "everything inlined into it, and its code inlined into other "
             "functions. Reach values overlap: code inlined from one "
             "function into another counts for both.")
EXCLUDED = (
    "Functions with less than {floor:.1f}% reach in both the training and "
    "the holdout cases are not listed. Functions written in C are not "
    "listed (they cannot carry a hint).")

LEAK_RE = re.compile(
    r"inline\(|inline_|unroll|vectori[sz]|interleave|align|oracle|stage ?0|"
    r"claude|jev-marks|\+\d|MDE|marked function is one|hintbench|kernel",
    re.I)


def leak_check(text, allowed=("marked function is one",)):
    hits = []
    for m in LEAK_RE.finditer(text):
        if m.group(0).lower() in allowed:
            continue
        hits.append(m.group(0))
    return hits

# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------


def strip_generics(name):
    """Drop every `::<...>` group at bracket depth 0 (the marks files' own
    rule: names were copied with the generic suffix cut off)."""
    out, i, depth = [], 0, 0
    while i < len(name):
        if depth == 0 and name.startswith("::<", i):
            j, d = i + 3, 1
            while j < len(name) and d:
                d += {"<": 1, ">": -1}.get(name[j], 0)
                j += 1
            i = j
            continue
        c = name[i]
        depth += {"<": 1, ">": -1}.get(c, 0)
        out.append(c)
        i += 1
    return "".join(out)


def read_tsv(path):
    return list(csv.DictReader(open(os.path.join(REPO, path)),
                               delimiter="\t"))


def read_marks(path):
    return [l.strip() for l in open(os.path.join(REPO, path))
            if l.strip() and not l.lstrip().startswith("#")]


def text_sha(binary):
    tmp = os.path.join(OUT_DIR, "_text.bin")
    subprocess.run(["objcopy", "-O", "binary", "--only-section=.text",
                    binary, tmp], check=True)
    h = hashlib.sha256(open(tmp, "rb").read()).hexdigest()
    os.unlink(tmp)
    return h


def nm_sizes(binary):
    out = subprocess.run(["nm", "-C", "-S", "--defined-only", binary],
                         capture_output=True, text=True, check=True).stdout
    sizes = collections.Counter()
    for line in out.splitlines():
        p = line.split(None, 3)
        if len(p) == 4 and p[2].lower() == "t":
            sizes[p[3]] += int(p[1], 16)
    return sizes


def is_c(name):
    return "::" not in name and not name.startswith("<")


def build_target(target):
    t = TARGETS[target]
    binary = os.path.join(REPO, t["binary"])
    sha = text_sha(binary)
    if not sha.startswith(t["text_sha"]):
        sys.exit("%s: .text %s is not the profiled binary %s"
                 % (target, sha[:12], t["text_sha"]))
    sizes = nm_sizes(binary)
    rows = {}
    if target == "hintbench":
        for m in read_marks(t["marks"]):
            rows[m] = dict(name=m, self_train=None, self_hold=None,
                           reach_train=12.5, reach_hold=12.5)
    elif target == "jaq":
        # One table over six workloads: training / holdout = the equal
        # weight mean of the three per-case columns (results.md 176.2).
        tr = ["train-objsearch", "train-readwrite", "train-strproc"]
        ho = ["hold-objsearch", "hold-readwrite", "hold-strproc"]
        slf = {r["function"]: r for r in read_tsv(t["self_tsv"])}
        for r in read_tsv(t["inline_tsv"]):
            fn = r["function"]
            s = slf.get(fn)
            rows[fn] = dict(
                name=fn,
                reach_train=statistics.fmean(float(r["reach_" + c])
                                             for c in tr),
                reach_hold=statistics.fmean(float(r["reach_" + c])
                                            for c in ho),
                self_train=(statistics.fmean(float(s[c]) for c in tr)
                            if s else 0.0),
                self_hold=(statistics.fmean(float(s[c]) for c in ho)
                           if s else 0.0),
                reach_all=float(r["reach"]), leaf_all=float(r["leaf"]),
                self_all=float(s["share"]) if s else 0.0,
                lang=(s["lang"] if s else None))
    else:
        for split in ("train", "hold"):
            slf = {r["function"]: float(r["share"])
                   for r in read_tsv(t["self_tsv"] % split)}
            lang = {r["function"]: r["lang"]
                    for r in read_tsv(t["self_tsv"] % split)}
            for r in read_tsv(t["inline_tsv"] % split):
                fn = r["function"]
                d = rows.setdefault(fn, dict(name=fn, reach_train=0.0,
                                             reach_hold=0.0, self_train=0.0,
                                             self_hold=0.0, lang=None))
                d["reach_" + split] = float(r["reach"])
                d["self_" + split] = slf.get(fn, 0.0)
                d["lang"] = d["lang"] or lang.get(fn)
    listed, dropped_c, dropped_floor = [], [], 0
    for fn, d in rows.items():
        if is_c(fn) or d.get("lang") == "c":
            if max(d["reach_train"], d["reach_hold"]) >= REACH_FLOOR:
                dropped_c.append(fn)
            continue
        if max(d["reach_train"], d["reach_hold"]) < REACH_FLOOR:
            dropped_floor += 1
            continue
        d["own_symbol"] = fn in sizes
        d["size"] = sizes.get(fn)
        listed.append(d)
    listed.sort(key=lambda d: d["name"])
    for i, d in enumerate(listed, 1):
        d["id"] = "F%03d" % i
    if INPUT_SET == "v2":
        add_v2_facts(target, t, listed)
    marks = read_marks(t["marks"])
    stripped = {strip_generics(d["name"]) for d in listed}
    missing = [m for m in marks + t["positives"] + t["positives_extra"]
               if strip_generics(m) not in stripped]
    return dict(target=target, input_set=INPUT_SET, text_sha256=sha, n_listed=len(listed),
                dropped_c=sorted(dropped_c), dropped_below_floor=dropped_floor,
                marks=marks, N=len(marks), missing_from_list=missing,
                rows=listed)


def add_v2_facts(target, t, listed):
    """176.7: crate, per-case reach, post-LTO instructions / backedges /
    host count of the code that belongs to the function."""
    st = {r["function"]: r for r in csv.DictReader(
        open(STRUCT_TSV % target), delimiter="\t")}
    crate = {}
    per_case = collections.defaultdict(dict)
    if target == "jaq":
        for r in read_tsv(t["inline_tsv"]):
            crate[r["function"]] = r["crate"]
            for c in CASES[target]:
                per_case[r["function"]][c] = statistics.fmean(
                    float(r["reach_%s-%s" % (s, c)]) for s in ("train", "hold"))
    elif target == "zopfli":
        acc = collections.defaultdict(lambda: collections.defaultdict(list))
        for split in ("train", "hold"):
            for r in read_tsv(t["inline_tsv"] % split):
                crate[r["function"]] = r["crate"]
                for c in CASES[target]:
                    acc[r["function"]][c].append(
                        float(r["reach_%s-%s" % (split, c)]))
        for fn, cs in acc.items():
            for c in CASES[target]:
                v = cs[c] + [0.0] * (2 - len(cs[c]))
                per_case[fn][c] = statistics.fmean(v)
    for d in listed:
        s = st.get(d["name"])
        d["crate"] = (crate.get(d["name"]) or (s or {}).get("crate")
                      or "hbkernels")
        d["per_case"] = per_case.get(d["name"]) or None
        d["insns"] = int(s["reach"]) if s else None
        d["backedges"] = int(s["reachbe"]) if s else None
        d["hosts"] = int(s["nhosts"]) if s else None
        d["own_insns"] = int(s["own"]) if s else None
        # 176.7 hybrid rule
        if d["reach_train"] < HYB_SKIP_REACH or (
                d["insns"] is not None and d["insns"] <= HYB_THUNK_INSNS):
            d["rule"] = "skip"
        elif d["reach_train"] >= HYB_MARK_REACH and (d["backedges"] or 0) > 0:
            d["rule"] = "mark"
        else:
            d["rule"] = "gray"


def cmd_build(a):
    os.makedirs(OUT_DIR, exist_ok=True)
    out = {"study": STUDY, "reach_floor": REACH_FLOOR, "targets": {}}
    for target in TARGETS:
        b = build_target(target)
        out["targets"][target] = b
        print("%-9s listed %3d  C dropped %2d  below floor %4d  N %2d  "
              "missing %s" % (target, b["n_listed"], len(b["dropped_c"]),
                              b["dropped_below_floor"], b["N"],
                              b["missing_from_list"] or "none"))
        if INPUT_SET == "v2":
            print("          hybrid rule: %s" % dict(collections.Counter(
                d["rule"] for d in b["rows"])))
    out["input_set"] = INPUT_SET
    path = INPUTS_V2 if INPUT_SET == "v2" else INPUTS
    json.dump(out, open(path, "w"), indent=1)
    print("wrote", path)


def load_inputs():
    return json.load(open(INPUTS_V2 if INPUT_SET == "v2" else INPUTS))

# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------


def _pct(x):
    return "-" if x is None else "%.2f%%" % x


def cut(name, cap):
    return name if len(name) <= cap else name[:cap - 1] + "…"


V2_COLS = """\
- `crate`: the crate the function's name comes from (a generic function
  from a library crate is compiled inside this program).
- `reach per case`: reach in each of the three cases ({cases}), the mean of
  its training and holdout runs.
- `insns` / `loops`: machine instructions of the code that belongs to the
  function (its body plus everything inlined into it) in the symbols that
  received samples, and the number of backward jumps inside that code (a
  backward jump means a machine-code loop survived optimisation); `-` when
  none of its code is in a sampled symbol.
- `hosts`: how many symbols of the final binary hold its code (1 with `own
  symbol` `no` = inlined into one caller).
"""
V2_TABLE = ("id | function | crate | self train | self hold | reach train | "
            "reach hold | reach per case | own symbol | size | insns | loops "
            "| hosts\n")


def _v2_row(d):
    pc = ("/".join("%.1f" % d["per_case"][c] for c in sorted(d["per_case"]))
          if d.get("per_case") else "-")
    na = lambda x: "-" if x is None else str(x)   # noqa: E731
    return "%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s" % (
        d["id"], cut(d["name"], NAME_CAP_STATE), d["crate"],
        _pct(d["self_train"]), _pct(d["self_hold"]), _pct(d["reach_train"]),
        _pct(d["reach_hold"]), pc, "yes" if d["own_symbol"] else "no",
        d["size"] if d["size"] else "-", na(d["insns"]), na(d["backedges"]),
        na(d["hosts"]))


def render_state(b):
    if b.get("input_set") == "v2":
        return render_state_v2(b)
    return render_state_v1(b)


def render_state_v2(b):
    target = b["target"]
    s = render_state_v1(b)
    head, _sep, _rows = s.partition(
        "id | function | self train | self hold | reach train | reach hold "
        "| own symbol | size\n")
    cases = "/".join(sorted(CASES.get(target, [])))
    cols = (V2_COLS.format(cases=cases) if target in CASES else
            V2_COLS.split("- `reach per case`")[0] + "- `insns` / `loops`"
            + V2_COLS.split("- `insns` / `loops`")[1])
    head = head.replace("- Call counts are not available",
                        cols + "- Call counts are not available")
    return head + V2_TABLE + "\n".join(_v2_row(d) for d in b["rows"]) + "\n"


def render_state_v1(b):
    target = b["target"]
    if target == "hintbench":
        profile = HB_PROFILE
    else:
        agg = ("Training and holdout values are the equal-weight means of "
               "the three cases of each set." if target == "jaq" else
               "Training and holdout values sum the samples of the three "
               "cases of each set.")
        profile = PERF_PROFILE.format(workloads=TARGETS[target]["workloads"],
                                      agg=agg)
    head = STATE_HEAD.format(
        target=target, profile=profile, self_col=SELF_COL,
        reach_col=REACH_COL,
        excluded=(EXCLUDED.format(floor=REACH_FLOOR)
                  if target != "hintbench" else
                  "All functions the workloads are spent in are listed."),
        n=len(b["rows"]), cap=NAME_CAP_STATE)
    lines = []
    for d in b["rows"]:
        lines.append("%s | %s | %s | %s | %s | %s | %s | %s" % (
            d["id"], cut(d["name"], NAME_CAP_STATE), _pct(d["self_train"]), _pct(d["self_hold"]),
            _pct(d["reach_train"]), _pct(d["reach_hold"]),
            "yes" if d["own_symbol"] else "no",
            d["size"] if d["size"] else "-"))
    return head + "\n".join(lines) + "\n"


def questions(b, q):
    out, site_map = {}, {}
    if p3_parts(q)[0] in P3_VARIANTS:
        ranks = p3_ranks(b)
        for d in b["rows"]:
            qn = "%s_%s" % (q.lower().replace("@", "_"), d["id"])
            out[qn] = p3_question(b, d, q, ranks)
            site_map[qn] = {"site_id": d["name"], "fid": d["id"], "q": q}
        return out, site_map
    for d in b["rows"]:
        if q == "Q3" and d.get("rule") != "gray":
            continue
        qn = "%s_%s" % (q.lower(), d["id"])
        if q in ("Q1", "Q3"):
            out[qn] = {"type": "choice",
                       "instructions": Q1_INSTR.format(
                           fid=d["id"], name=cut(d["name"], NAME_CAP_Q)),
                       "criteria": dict(Q1_CRIT)}
        else:
            out[qn] = {"type": "score",
                       "instructions": Q2_INSTR.format(
                           fid=d["id"], name=cut(d["name"], NAME_CAP_Q)),
                       "criteria": list(Q2_LEVELS)}
        site_map[qn] = {"site_id": d["name"], "fid": d["id"], "q": q}
    return out, site_map


def build_requests(b, q):
    state = render_state(b)
    qs, sm = questions(b, q)
    base = len(json.dumps({"model": "typesafe-ai/jev", "state": state,
                           "questions": {}}))
    chunks, cur, size = [], {}, base
    for qn, qq in qs.items():
        n = len(json.dumps({qn: qq}))
        if cur and size + n > BODY_CAP:
            chunks.append(cur)
            cur, size = {}, base
        cur[qn] = qq
        size += n
    if cur:
        chunks.append(cur)
    return [{"tag": "%s.c%d" % (q, i), "state": state, "questions": c,
             "site_map": {k: sm[k] for k in c}} for i, c in enumerate(chunks)]


def all_request_text(b):
    parts = [render_state(b)]
    extra = (("Q3",) + tuple(p3_expand(b["target"], P3_VARIANTS))
             if b.get("input_set") == "v2" else ())
    for q in ("Q1", "Q2") + extra:
        qs, _ = questions(b, q)
        for qq in qs.values():
            parts.append(qq["instructions"])
            parts.extend(qq["criteria"].values() if isinstance(
                qq["criteria"], dict) else qq["criteria"])
    return "\n".join(parts)


def leak_report(b):
    """Leak check on everything except the function names themselves
    (a name is data: `hintbench`, `kernel`, `align` may occur in one)."""
    txt = all_request_text(b)
    for d in b["rows"]:
        for cap in (NAME_CAP_STATE, NAME_CAP_Q, 10 ** 9):
            txt = txt.replace(cut(d["name"], cap), "<name>")
        if d.get("crate"):
            txt = txt.replace("| %s |" % d["crate"], "| <crate> |")
    txt = txt.replace("`%s`" % b["target"], "`<target>`")
    for c in CASES.get(b["target"], []):
        txt = txt.replace("`%s`" % c, "`<case>`")
    return leak_check(txt)


def cmd_render(a):
    b = load_inputs()["targets"][a.target]
    reqs = build_requests(b, a.q)
    for r in reqs:
        body = json.dumps({"model": "typesafe-ai/jev", "state": r["state"],
                           "questions": r["questions"]})
        print("== %s %s: %d questions, %d bytes" % (a.target, r["tag"],
                                                     len(r["questions"]),
                                                     len(body)))
    print("[leak-check]", leak_report(b) or "clean")
    if a.full:
        print(reqs[0]["state"])
        print(json.dumps(reqs[0]["questions"], indent=1)[:3000])

# ---------------------------------------------------------------------------
# sending
# ---------------------------------------------------------------------------


def make_client(run_id):
    S.RETRY_JITTER = 0.0          # a fixed 2 s pause (as study 2)
    cfg = S.load_config(os.path.join(REPO, "jev-opt.toml"))
    os.makedirs(OUT_DIR, exist_ok=True)
    return S.JevClient(dict(cfg["jev"]), OUT_DIR, run_id,
                       source_comments="none")


def send(client, req, repeat):
    answers, line_no = client.ask(req["state"], req["questions"], repeat,
                                  req["tag"], req["site_map"])
    n = 0
    while answers is None and n < 2:          # [jev] phase_resend_max
        n += 1
        client.wait(10)
        answers, line_no = client.ask(req["state"], req["questions"], repeat,
                                      req["tag"] + ".retry%d" % n,
                                      req["site_map"])
    return answers, line_no


def cmd_run(a):
    inp = load_inputs()
    for target in a.targets:
        b = inp["targets"][target]
        hits = leak_report(b)
        print("[leak-check] %s: %s" % (target, hits or "clean"))
        if hits:
            sys.exit("leak check failed")
        run_id = "%s-%s" % (a.run_prefix, target)
        client = make_client(run_id)
        with open(client.log_path, "a") as f:
            f.write("# %s, target %s, %d functions, reach floor %.1f%%, "
                    "leak check clean\n" % (STUDY, target, len(b["rows"]),
                                            REACH_FLOOR))
        landed = set()
        if a.resume and os.path.isfile(client.jsonl_path):
            for line in open(client.jsonl_path):
                r = json.loads(line)
                if not r.get("exhausted"):
                    landed.add((r["round"], re.sub(r"\.retry\d*$", "",
                                                   r["phase"])))
            print("[resume] %d landed requests" % len(landed))
        t0 = time.time()
        for rep in range(1, a.repeats + 1):
            for q in p3_expand(target, a.questions):
                for req in build_requests(b, q):
                    if (rep, req["tag"]) in landed:
                        continue
                    ans, ln = send(client, req, rep)
                    print("[%s r%d] %s -> %s (line %d)"
                          % (target, rep, req["tag"],
                             "ok" if ans is not None else "LOST", ln))
        client.write_totals(time.time() - t0)
        print("[%s] totals %s gateway %s" % (
            target, client.totals,
            {k: v for k, v in client.gateway.items()
             if k != "attempts_by_phase"}))

# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def jev_answers(path, repeats):
    """{rep: {"Q1": {name: P(mark)}, "Q2": {name: score}}}"""
    out = {r: collections.defaultdict(dict, {
        "Q1": {}, "Q2": {}, "Q3": {}, "requests": 0,
        "questions": collections.Counter()})
           for r in range(1, repeats + 1)}
    for line in open(path):
        rec = json.loads(line)
        if rec.get("exhausted") or rec["round"] not in out:
            continue
        ans = (rec.get("response") or {}).get("answers") or {}
        out[rec["round"]]["requests"] += 1
        for qn, sm in rec["site_map"].items():
            out[rec["round"]]["questions"][sm["q"]] += 1
            a = ans.get(qn)
            if not a:
                continue
            if sm["q"] != "Q2":
                out[rec["round"]][sm["q"]][sm["site_id"]] = float(
                    (a.get("probabilities") or {}).get("mark", 0.0))
            else:
                out[rec["round"]]["Q2"][sm["site_id"]] = a.get("score")
    return out


def hits(sel, names):
    ss = {strip_generics(x) for x in sel}
    return [n for n in names if strip_generics(n) in ss]


class Coverage:
    """Union of in-binary cycles covered by a selection (marks-file rule).

    zopfli: exact, from the perf.data files (perf_hotness.py's own
    resolution). jaq: bounds from the six-workload table (perf.data not
    kept, results.md 86): lower = max(sum self, max reach), upper =
    min(100, sum reach). hintbench: 12.5% per selected function."""

    def __init__(self, target, b):
        self.target, self.b = target, b
        self.cases = None
        if target == "zopfli":
            import glob
            import perf_hotness as PH
            binary = os.path.join(REPO, TARGETS[target]["binary"])
            perf = PH.perf_path(REPO)
            segs = PH.load_segments(binary)
            self.cases = {}
            for split in ("train", "hold"):
                cs = []
                for p in sorted(glob.glob(os.path.join(
                        REPO, TARGETS[target]["data"] % split))):
                    inside, _o, _n = PH.read_case(perf, p, binary, segs)
                    cs.append(inside)
                self.cases[split] = cs
            addrs = set()
            for cs in self.cases.values():
                for c in cs:
                    addrs |= set(c)
            self.stacks = PH.inline_stacks(binary, addrs)

    def __call__(self, sel):
        if self.target == "hintbench":
            return {"train": 12.5 * len(sel), "hold": 12.5 * len(sel)}
        if self.target == "jaq":
            rows = {d["name"]: d for d in self.b["rows"]}
            ds = [rows[n] for n in sel]
            lo = max([sum(d["self_all"] for d in ds)]
                     + [d["reach_all"] for d in ds])
            hi = min(100.0, sum(d["reach_all"] for d in ds))
            return {"all_lo": lo, "all_hi": hi}
        marks = list(sel)

        def hit(f):
            return any(f == m or f.startswith(m + "::<")
                       or f.startswith(m + "::{closure") for m in marks)
        out = {}
        for split, cs in self.cases.items():
            tot = cov = 0
            memo = {}
            for c in cs:
                for vaddr, period in c.items():
                    tot += period
                    st = self.stacks.get(vaddr) or []
                    key = tuple(st)
                    if key not in memo:
                        memo[key] = any(hit(f) for f in st)
                    if memo[key]:
                        cov += period
            out[split] = 100.0 * cov / tot if tot else 0.0
        return out


def controls(target, b, N):
    rows = b["rows"]
    alpha = {d["name"]: i for i, d in enumerate(rows)}
    by_reach = sorted(rows, key=lambda d: (-d["reach_train"],
                                           alpha[d["name"]]))
    by_self = sorted(rows, key=lambda d: (-(d["self_train"] or 0.0),
                                          alpha[d["name"]]))
    out = {"top-N reach": [d["name"] for d in by_reach[:N]],
           "top-N self": [d["name"] for d in by_self[:N]]}
    return out, [d["name"] for d in by_reach]


def rule90(cov, by_reach, target):
    """The zopfli marks rule (rationale section 1): add in reach order until
    the union reaches >= 90% of in-binary training cycles. No existence
    gate (the plugin's view is not an input here)."""
    if target != "zopfli":
        return None
    sel = []
    for n in by_reach:
        sel.append(n)
        if cov(sel)["train"] >= 90.0:
            return sel
    return sel


def metrics(target, b, sel, cov):
    t = TARGETS[target]
    marks = b["marks"]
    ov = hits(marks, sel)          # marks hit by the selection
    m = {"size": len(sel),
         "overlap": len(set(strip_generics(x) for x in ov)) / b["N"],
         "overlap_n": len(set(strip_generics(x) for x in ov)),
         "pos": len(hits(sel, t["positives"])) / len(t["positives"]),
         "pos_hit": hits(sel, t["positives"]),
         "pos_extra": hits(sel, t["positives_extra"]),
         "harm_hit": hits(sel, t["harmful"])}
    m["cov"] = cov(sel)
    return m


def cmd_score(a):
    inp = load_inputs()
    out = {"study": STUDY, "targets": {}}
    for target in a.targets:
        b = inp["targets"][target]
        N = b["N"]
        cov = Coverage(target, b)
        alpha = {d["name"]: i for i, d in enumerate(b["rows"])}
        names = [d["name"] for d in b["rows"]]
        path = os.path.join(a.log_dir, "%s-%s.jsonl" % (a.run_prefix, target))
        ans = jev_answers(path, a.repeats)
        res = {"N": N, "arms": {}, "per_function": {}}
        sets = {}
        for rep in range(1, a.repeats + 1):
            p = ans[rep]["Q1"]
            sc = ans[rep]["Q2"]
            missing = ([n for n in names if n not in p],
                       [n for n in names if sc.get(n) is None])
            res.setdefault("missing", {})[rep] = [len(missing[0]),
                                                  len(missing[1])]
            sets["Q1 r%d" % rep] = [n for n in names if p.get(n, 0.0) > 0.5]
            sets["Q1top r%d" % rep] = sorted(
                names, key=lambda n: (-p.get(n, 0.0), alpha[n]))[:N]
            sets["Q2 r%d" % rep] = sorted(
                names, key=lambda n: (-(sc.get(n) if sc.get(n) is not None
                                        else -1), alpha[n]))[:N]
        rule = {d["name"]: d.get("rule") for d in b["rows"]}
        if any(ans[r]["Q3"] for r in ans):
            for rep_ in ans:
                p3 = ans[rep_]["Q3"]
                sets["Q3 hybrid r%d" % rep_] = [
                    n for n in names if rule[n] == "mark"
                    or (rule[n] == "gray" and p3.get(n, 0.0) > 0.5)]
            medP3 = {n: statistics.median(ans[r]["Q3"].get(n, 0.0)
                                          for r in ans) for n in names}
            sets["Q3 hybrid medP"] = [n for n in names if rule[n] == "mark"
                                      or (rule[n] == "gray"
                                          and medP3[n] > 0.5)]
            sets["hybrid rule only (gray skipped)"] = [
                n for n in names if rule[n] == "mark"]
            sets["hybrid rule + all gray marked"] = [
                n for n in names if rule[n] in ("mark", "gray")]
        # 176.8 phase 3: M1/M3/M4 = P > 0.5; M2/M5 = union over cases
        keys = sorted({k for r in ans for k in ans[r]
                       if p3_parts(k)[0] in P3_VARIANTS and ans[r][k]})
        for v in P3_VARIANTS:
            vk = [k for k in keys if p3_parts(k)[0] == v]
            if not vk:
                continue
            for rep_ in ans:
                sel = set()
                for k in vk:
                    pk = ans[rep_][k]
                    cs = {n for n in names if pk.get(n, 0.0) > 0.5}
                    if p3_parts(k)[1]:
                        sets["%s %s r%d" % (v, p3_parts(k)[1], rep_)] = [
                            n for n in names if n in cs]
                    sel |= cs
                sets["%s r%d" % (v, rep_)] = [n for n in names if n in sel]
            sel = set()
            for k in vk:
                mp = {n: statistics.median(ans[r][k].get(n, 0.0)
                                           for r in ans) for n in names}
                sel |= {n for n in names if mp[n] > 0.5}
                for n in names:
                    res["per_function"].setdefault(n, {})["P_" + k] = [
                        ans[r][k].get(n) for r in sorted(ans)]
            sets["%s medP" % v] = [n for n in names if n in sel]
        res["requests"] = {r: {"requests": ans[r]["requests"],
                               "questions": dict(ans[r]["questions"])}
                           for r in ans}
        medP = {n: statistics.median(ans[r]["Q1"].get(n, 0.0)
                                     for r in ans) for n in names}
        medS = {n: statistics.median((ans[r]["Q2"].get(n)
                                      if ans[r]["Q2"].get(n) is not None
                                      else -1) for r in ans) for n in names}
        sets["Q1 medP"] = [n for n in names if medP[n] > 0.5]
        sets["Q1top medP"] = sorted(names,
                                    key=lambda n: (-medP[n], alpha[n]))[:N]
        sets["Q2 medS"] = sorted(names, key=lambda n: (-medS[n],
                                                       alpha[n]))[:N]
        ctl, by_reach = controls(target, b, N)
        sets.update(ctl)
        r90 = rule90(cov, by_reach, target)
        if r90 is not None:
            sets["90%-reach rule"] = r90
        sets["Claude marks"] = [n for n in names
                                if strip_generics(n) in
                                {strip_generics(m) for m in b["marks"]}]
        refs = set()
        for k in ("top-N reach", "top-N self", "90%-reach rule",
                  "Claude marks"):
            refs |= {strip_generics(x) for x in sets.get(k, [])}
        for k, s in sets.items():
            res["arms"][k] = dict(metrics(target, b, s, cov), members=s)
            res["arms"][k]["false"] = sorted(
                x for x in {strip_generics(y) for y in s} if x not in refs)
        for n in names:
            d = next(x for x in b["rows"] if x["name"] == n)
            res["per_function"].setdefault(n, {}).update({
                "id": d["id"],
                "reach_rank": by_reach.index(n) + 1,
                "rule": rule.get(n),
                "P_mark": [ans[r]["Q1"].get(n) for r in sorted(ans)],
                "P_mark_Q3": [ans[r]["Q3"].get(n) for r in sorted(ans)],
                "score": [ans[r]["Q2"].get(n) for r in sorted(ans)]})
        out["targets"][target] = res
    json.dump(out, open(a.out, "w"), indent=1)
    print("wrote", a.out)
    if a.report:
        write_report(out, inp, a.report)


def _med(xs, fmt="%.2f"):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "-"
    if min(xs) == max(xs):
        return fmt % xs[0]
    return "%s (%s-%s)" % (fmt % statistics.median(xs), fmt % min(xs),
                           fmt % max(xs))


def _cov_str(c):
    if "all_lo" in c:
        return "%.1f-%.1f%%" % (c["all_lo"], c["all_hi"])
    return "%.1f / %.1f%%" % (c["train"], c["hold"])


def short(n, w=70):
    return n if len(n) <= w else n[:w - 1] + "…"


def write_report(out, inp, path):
    L = ["# Marks study: report (generated by scripts/jev_marks_study.py "
         "score)", ""]
    for target, res in out["targets"].items():
        b = inp["targets"][target]
        arms = res["arms"]
        L += ["## %s (N = %d, %d functions listed)" % (target, res["N"],
                                                        b["n_listed"]), ""]
        L += ["| arm | size | overlap | positives | extra | harmful | "
              "false | coverage |", "|---|--:|--:|--:|--:|--:|--:|--:|"]
        groups = collections.OrderedDict()
        for k in arms:
            g = re.sub(r" r\d+$", "", k)
            groups.setdefault(g, []).append(k)
        for g, ks in groups.items():
            ms = [arms[k] for k in ks]
            covs = [m["cov"] for m in ms]
            if len(ks) > 1:
                ck = list(covs[0].keys())
                cs = (" - " if "all_lo" in ck else " / ").join(
                    _med([c[x] for c in covs], "%.1f") for x in ck) + "%"
                L.append("| %s (3 repeats: median (range)) | %s | %s | %s | "
                         "%s | %s | %s | %s |" % (
                             g, _med([m["size"] for m in ms], "%d"),
                             _med([m["overlap"] for m in ms]),
                             _med([m["pos"] for m in ms]),
                             _med([len(m["pos_extra"]) for m in ms], "%d"),
                             _med([len(m["harm_hit"]) for m in ms], "%d"),
                             _med([len(m["false"]) for m in ms], "%d"),
                             cs))
            else:
                m = ms[0]
                L.append("| %s | %d | %.2f | %.2f | %d | %d | %d | %s |" % (
                    g, m["size"], m["overlap"], m["pos"],
                    len(m["pos_extra"]), len(m["harm_hit"]),
                    len(m["false"]), _cov_str(m["cov"])))
        L.append("")
        pf = res["per_function"]
        L += ["Per function (reach rank, P(mark) and Score per repeat), "
              "top 30 by median Score:", "",
              "| id | reach rank | P(mark) | Score | function |",
              "|---|--:|---|---|---|"]
        rank = sorted(pf, key=lambda n: -statistics.median(
            [s if s is not None else -1 for s in pf[n]["score"]]))
        marks = {strip_generics(m) for m in b["marks"]}
        for n in rank[:30]:
            d = pf[n]
            L.append("| %s | %d | %s | %s | %s%s |" % (
                d["id"], d["reach_rank"],
                " ".join("%.2f" % x if x is not None else "-"
                         for x in d["P_mark"]),
                " ".join("%.2f" % x if x is not None else "-"
                         for x in d["score"]),
                "**M** " if strip_generics(n) in marks else "",
                short(n, 90)))
        L.append("")
    open(path, "w").write("\n".join(L) + "\n")
    print("wrote", path)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--inputs", choices=("v1", "v2"), default="v1")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    r = sub.add_parser("render")
    r.add_argument("target", choices=sorted(TARGETS))
    r.add_argument("q")
    r.add_argument("--full", action="store_true")
    ru = sub.add_parser("run")
    ru.add_argument("--targets", nargs="+", default=list(TARGETS))
    ru.add_argument("--questions", nargs="+", default=["Q1", "Q2"])
    ru.add_argument("--repeats", type=int, default=3)
    ru.add_argument("--run-prefix", default="ms")
    ru.add_argument("--resume", action="store_true")
    sc = sub.add_parser("score")
    sc.add_argument("--targets", nargs="+", default=list(TARGETS))
    sc.add_argument("--repeats", type=int, default=3)
    sc.add_argument("--run-prefix", default="ms")
    sc.add_argument("--log-dir", default=OUT_DIR)
    sc.add_argument("--out", default=os.path.join(OUT_DIR, "scores.json"))
    sc.add_argument("--report", default=os.path.join(OUT_DIR, "report.md"))
    a = p.parse_args()
    global INPUT_SET
    INPUT_SET = a.inputs
    if a.inputs == "v2":      # separate logs and outputs for 176.7
        if getattr(a, "run_prefix", None) == "ms":
            a.run_prefix = "ms2"
        if getattr(a, "out", None) == os.path.join(OUT_DIR, "scores.json"):
            a.out = os.path.join(OUT_DIR, "scores-v2.json")
        if getattr(a, "report", None) == os.path.join(OUT_DIR, "report.md"):
            a.report = os.path.join(OUT_DIR, "report-v2.md")
    return {"build": cmd_build, "render": cmd_render, "run": cmd_run,
            "score": cmd_score}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
