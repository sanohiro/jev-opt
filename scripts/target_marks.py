#!/usr/bin/env python3
"""Marks by rule: mechanical seed plus a Jev gray zone (decision 109).

Writes a marks file (`targets/<t>/jev-marks.jev.txt`) in the format the
plugin and scripts/jev_search.py read, and a rationale next to it. Never
writes `jev-marks.txt`: the frozen marks stay what the existing comparisons
used; whether a `.jev.txt` replaces one is the owner's call, per target, in
a new registration.

The rule (owner, 2026-09-25; results.md 179):

  listed     every row of the perf inline table with reach >= 1% or self
             >= 1% in the training or the holdout set (max over the two),
             minus the exclusions. The same table, ids and order as the
             marks study's input set v2 (results.md 176.7).
  excluded   never marked, never asked: code with no IR for the plugin (C,
             `lang c` or a name without `::`/`<`), thunks (<= --thunk-insns
             machine instructions including inlined code, the study's
             176.7 threshold), and the rows below the 1% floor.
  seed       always marked, no question: the union of the top N by training
             reach and the top N by training self time, ranked among the
             rows that are neither excluded nor compiler-generated
             (`drop_glue` / `drop_in_place`, vtable shims). Ties are broken
             alphabetically, never by hotness.
  gray       every other listed row whose marks line is not already matched
             by a seed line: one Jev Choice {mark, skip} each, the study's
             Q1 text on the v2 state (the whole listed table), sent
             --repeats times; marked if the median P(mark) over the landed
             repeats is >= --threshold (0.5).

A marks line is the row's name with the depth-0 `::<...>` groups removed
when that line still matches the row by the plugin's rule (equal, continues
with `::`, or ends with `::` + line; plugin/README.md "Marks file"),
otherwise the full name. A line matched by another selected line is folded
into it.

Inputs (all on disk; nothing is built, timed or run):
  --perf-tsv-self / --perf-tsv-inline  scripts/perf_hotness.py outputs. Either
      one table over all workloads with per-case columns `train-<case>` /
      `hold-<case>` (jaq), or one file per split with `{split}` in the path
      (`train` / `hold`, zopfli).
  --equal-shares FILE   no perf table: every function listed in FILE gets an
      equal reach, self "not measured" (hintbench, whose workloads are one
      function each by construction).
  --binary              the profiled binary (`nm` gives own symbol / size).
  --structure-tsv       scripts/inline_structure.py over that binary (insns,
      backward jumps, hosts). A new target needs it generated first.

Modes: --dry-run (default; seed / exclusions / gray lists, no HTTP, writes
nothing), --seed-only (writes the seed as the marks file, no HTTP), --jev
(asks the gray zone, then writes both files). Requests and responses are
logged by jev_search.JevClient (JSONL + .log, no Authorization header) in
artifacts/jev-marks/<target>/.
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
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jev_search as S            # noqa: E402
import jev_marks_study as MS      # noqa: E402

REPO = S.REPO
RULE = "rule-seed-union-jev-gray-v1 (decision 109)"

# Per-target defaults: the inputs the marks study used (results.md 176.1,
# 176.7) and the size of the frozen marks (Claude's N).
DEFAULTS = {
    "jaq": dict(n=15,
                self_tsv="artifacts/jaq-marks/perf-self.tsv",
                inline_tsv="artifacts/jaq-marks/perf-inline.tsv"),
    "zopfli": dict(n=6,
                   self_tsv="artifacts/zopfli-marks/perf-self-{split}.tsv",
                   inline_tsv="artifacts/zopfli-marks/perf-inline-{split}.tsv"),
    "hintbench": dict(n=8, equal_shares="targets/hintbench/jev-marks.txt"),
}

GENERATED_RE = re.compile(
    r"(^|::)drop_(glue|in_place)(::<|$)|\{vtable\.shim\}|\{shim:")


def rel(p):
    return os.path.relpath(p, REPO) if os.path.isabs(p) else p


def ab(p):
    return p if os.path.isabs(p) else os.path.join(REPO, p)


def read_tsv(path):
    return list(csv.DictReader(open(ab(path)), delimiter="\t"))


def sha256_file(path):
    return hashlib.sha256(open(ab(path), "rb").read()).hexdigest()


def text_sha(binary):
    with tempfile.NamedTemporaryFile(suffix=".text") as tmp:
        subprocess.run(["objcopy", "-O", "binary", "--only-section=.text",
                        binary, tmp.name], check=True)
        return hashlib.sha256(open(tmp.name, "rb").read()).hexdigest()


def plugin_match(mark, fn):
    """plugin/README.md "Marks file": equal, continues with `::`, or ends
    with `::` + the mark."""
    return fn == mark or fn.startswith(mark + "::") or fn.endswith("::" + mark)


def line_of(name):
    s = MS.strip_generics(name)
    return s if plugin_match(s, name) else name


# ---------------------------------------------------------------------------
# the table (the study's input set v2, from files given on the command line)
# ---------------------------------------------------------------------------

def load_rows(a):
    """{name: row} with the study's fields, before the floor."""
    rows = {}
    cases = []
    layout = None
    if a.equal_shares:
        layout = "equal"
        names = MS.read_marks(a.equal_shares)
        share = 100.0 / len(names)
        for m in names:
            rows[m] = dict(name=m, self_train=None, self_hold=None,
                           reach_train=share, reach_hold=share, lang=None)
        return rows, cases, layout
    if "{split}" not in a.perf_tsv_inline:
        layout = "single"
        inl = read_tsv(a.perf_tsv_inline)
        cols = [c[len("reach_"):] for c in inl[0] if c.startswith("reach_")]
        tr = sorted(c for c in cols if c.startswith("train-"))
        ho = sorted(c for c in cols if c.startswith("hold-"))
        if not tr or not ho:
            sys.exit("%s: no reach_train-*/reach_hold-* columns"
                     % a.perf_tsv_inline)
        cases = sorted({c.split("-", 1)[1] for c in tr + ho})
        slf = {r["function"]: r for r in read_tsv(a.perf_tsv_self)}
        for r in inl:
            fn = r["function"]
            s = slf.get(fn)
            rows[fn] = dict(
                name=fn,
                reach_train=statistics.fmean(float(r["reach_" + c]) for c in tr),
                reach_hold=statistics.fmean(float(r["reach_" + c]) for c in ho),
                self_train=(statistics.fmean(float(s[c]) for c in tr)
                            if s else 0.0),
                self_hold=(statistics.fmean(float(s[c]) for c in ho)
                           if s else 0.0),
                reach_all=float(r["reach"]),
                self_all=float(s["share"]) if s else 0.0,
                lang=(s["lang"] if s else None), crate=r.get("crate"),
                per_case={c: statistics.fmean(
                    float(r["reach_%s-%s" % (sp, c)]) for sp in ("train", "hold")
                    if ("reach_%s-%s" % (sp, c)) in r) for c in cases})
        return rows, cases, layout
    layout = "split"
    acc = collections.defaultdict(lambda: collections.defaultdict(list))
    for split in ("train", "hold"):
        sp = read_tsv(a.perf_tsv_self.replace("{split}", split))
        slf = {r["function"]: float(r["share"]) for r in sp}
        lang = {r["function"]: r["lang"] for r in sp}
        inl = read_tsv(a.perf_tsv_inline.replace("{split}", split))
        pre = "reach_%s-" % split
        cs = sorted(c[len(pre):] for c in inl[0] if c.startswith(pre))
        cases = sorted(set(cases) | set(cs))
        for r in inl:
            fn = r["function"]
            d = rows.setdefault(fn, dict(name=fn, reach_train=0.0,
                                         reach_hold=0.0, self_train=0.0,
                                         self_hold=0.0, lang=None, crate=None))
            d["reach_" + split] = float(r["reach"])
            d["self_" + split] = slf.get(fn, 0.0)
            d["lang"] = d["lang"] or lang.get(fn)
            d["crate"] = r.get("crate") or d["crate"]
            for c in cs:
                acc[fn][c].append(float(r[pre + c]))
    for fn, d in rows.items():
        d["per_case"] = {c: statistics.fmean(
            acc[fn][c] + [0.0] * (2 - len(acc[fn][c]))) for c in cases}
    return rows, cases, layout


def build_table(a):
    rows, cases, layout = load_rows(a)
    binary = ab(a.binary)
    tsha = text_sha(binary)
    if a.text_sha and not tsha.startswith(a.text_sha):
        sys.exit("%s: .text %s is not the profiled binary %s"
                 % (a.binary, tsha[:12], a.text_sha))
    sizes = MS.nm_sizes(binary)
    st = {r["function"]: r for r in read_tsv(a.structure_tsv)}
    listed, c_rows, below = [], [], 0
    for fn, d in rows.items():
        top = max(d["reach_train"], d["reach_hold"],
                  d["self_train"] or 0.0, d["self_hold"] or 0.0)
        if MS.is_c(fn) or d.get("lang") == "c":
            if top >= a.floor:
                c_rows.append(fn)
            continue
        if top < a.floor:
            below += 1
            continue
        d["own_symbol"] = fn in sizes
        d["size"] = sizes.get(fn)
        s = st.get(fn)
        d["crate"] = d.get("crate") or (s or {}).get("crate") or "?"
        if not d.get("per_case"):
            d["per_case"] = None
        d["insns"] = int(s["reach"]) if s else None
        d["backedges"] = int(s["reachbe"]) if s else None
        d["hosts"] = int(s["nhosts"]) if s else None
        d["own_insns"] = int(s["own"]) if s else None
        listed.append(d)
    listed.sort(key=lambda d: d["name"])
    for i, d in enumerate(listed, 1):
        d["id"] = "F%03d" % i
    return dict(target=a.target, input_set="v2", layout=layout, cases=cases,
                text_sha256=tsha, n_listed=len(listed),
                dropped_c=sorted(c_rows), dropped_below_floor=below,
                rows=listed)


# ---------------------------------------------------------------------------
# the rule
# ---------------------------------------------------------------------------

def classify(b, n, thunk_insns):
    rows = b["rows"]
    alpha = {d["name"]: i for i, d in enumerate(rows)}
    for d in rows:
        d["excl"] = None
        if d["insns"] is not None and d["insns"] <= thunk_insns:
            d["excl"] = "thunk (%d insns incl. inlined code <= %d)" % (
                d["insns"], thunk_insns)
        d["generated"] = bool(GENERATED_RE.search(d["name"]))
        d["line"] = line_of(d["name"])
    elig = [d for d in rows if not d["excl"] and not d["generated"]]
    by_reach = sorted(elig, key=lambda d: (-d["reach_train"], alpha[d["name"]]))
    measured = any(d["self_train"] is not None for d in rows)
    by_self = (sorted(elig, key=lambda d: (-(d["self_train"] or 0.0),
                                           alpha[d["name"]]))
               if measured else [])
    rr = {d["name"]: i for i, d in enumerate(by_reach, 1)}
    sr = {d["name"]: i for i, d in enumerate(by_self, 1)}
    for d in rows:
        d["reach_rank"], d["self_rank"] = rr.get(d["name"]), sr.get(d["name"])
        why = []
        if d["reach_rank"] and d["reach_rank"] <= n:
            why.append("reach rank %d" % d["reach_rank"])
        if d["self_rank"] and d["self_rank"] <= n:
            why.append("self rank %d" % d["self_rank"])
        d["seed_why"] = why
        d["rule"] = "seed" if why else None
    # would the ranking over *all* listed rows have seeded an excluded one?
    alls = sorted(rows, key=lambda d: (-d["reach_train"], alpha[d["name"]]))[:n]
    if measured:
        alls += sorted(rows, key=lambda d: (-(d["self_train"] or 0.0),
                                            alpha[d["name"]]))[:n]
    b["rank_note"] = sorted({d["name"] for d in alls
                             if d["excl"] or d["generated"]})
    seed_lines = sorted({d["line"] for d in rows if d["rule"] == "seed"})
    for d in rows:
        if d["rule"] == "seed":
            continue
        if d["excl"]:
            d["rule"] = "excluded"
            continue
        cov = [m for m in seed_lines if plugin_match(m, d["name"])]
        if cov:
            d["rule"], d["covered_by"] = "covered", cov[0]
        else:
            d["rule"] = "gray"
    return seed_lines


def final_lines(lines):
    """Fold a line into another selected line that matches it."""
    lines = sorted(set(lines))
    out, folded = [], {}
    for l in lines:
        host = [m for m in lines if m != l and plugin_match(m, l)]
        if host:
            folded[l] = host[0]
        else:
            out.append(l)
    return out, folded


# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------

def render_state(b, workloads):
    t = b["target"]
    MS.TARGETS.setdefault(t, {})
    if workloads:
        MS.TARGETS[t]["workloads"] = workloads
    if t not in MS.CASES and b["cases"]:
        MS.CASES[t] = list(b["cases"])
    if b["layout"] != "equal" and "workloads" not in MS.TARGETS[t]:
        sys.exit("--workloads is required for a new target (one sentence, "
                 "the study's form: 'three training cases (...) and ...')")
    if b["layout"] == "equal" and t != "hintbench":
        sys.exit("--equal-shares: the state text exists for hintbench only")
    s = MS.render_state(b)
    if b["layout"] == "single" and t != "jaq":
        s = s.replace("Training and holdout values sum the samples of the "
                      "three cases of each set.",
                      "Training and holdout values are the equal-weight "
                      "means of the cases of each set.")
    return s


def build_requests(b, state):
    qs, sm = MS.questions(b, "Q3")          # Q3 = the Q1 text, gray rows only
    base = len(json.dumps({"model": "typesafe-ai/jev", "state": state,
                           "questions": {}}))
    chunks, cur, size = [], {}, base
    for qn, qq in qs.items():
        k = len(json.dumps({qn: qq}))
        if cur and size + k > MS.BODY_CAP:
            chunks.append(cur)
            cur, size = {}, base
        cur[qn] = qq
        size += k
    if cur:
        chunks.append(cur)
    return [{"tag": "gray.c%d" % i, "state": state, "questions": c,
             "site_map": {k: sm[k] for k in c}} for i, c in enumerate(chunks)]


def leak_hits(b, reqs):
    txt = "\n".join([reqs[0]["state"]] + [
        q["instructions"] + "\n" + "\n".join(q["criteria"].values())
        for r in reqs for q in r["questions"].values()])
    for d in b["rows"]:
        for cap in (MS.NAME_CAP_STATE, MS.NAME_CAP_Q, 10 ** 9):
            txt = txt.replace(MS.cut(d["name"], cap), "<name>")
        if d.get("crate"):
            txt = txt.replace("| %s |" % d["crate"], "| <crate> |")
    txt = txt.replace("`%s`" % b["target"], "`<target>`")
    return MS.leak_check(txt)


def read_log(path, repeats):
    """{name: [P per repeat or None]}, request / 503 / cost counts."""
    p = collections.defaultdict(lambda: [None] * repeats)
    st = collections.Counter()
    if not os.path.isfile(path):
        return p, st
    for line in open(path):
        rec = json.loads(line)
        st["requests"] += 1
        st["attempts"] += rec.get("n_attempts") or 0
        st["http_503"] += sum(1 for x in rec.get("attempt_log") or []
                              if x.get("http_status") == 503)
        st["max_body"] = max(st["max_body"], rec.get("request_bytes") or 0)
        gw = ((rec.get("response") or {}).get("provider_metadata") or {}
              ).get("gateway") or {}
        st["billed_usd_e9"] += int(round(float(gw.get("cost") or 0) * 1e9))
        st["list_usd_e9"] += int(round(float(gw.get("marketCost") or 0) * 1e9))
        if rec.get("exhausted"):
            st["exhausted"] += 1
            continue
        ans = (rec.get("response") or {}).get("answers") or {}
        r = rec["round"]
        if not 1 <= r <= repeats:
            continue
        for qn, sm in rec["site_map"].items():
            a = ans.get(qn)
            if a:
                p[sm["site_id"]][r - 1] = float(
                    (a.get("probabilities") or {}).get("mark", 0.0))
    return p, st


def ask_gray(a, b, reqs):
    S.RETRY_JITTER = 0.0                   # a fixed 2 s pause (as the study)
    cfg = S.load_config(os.path.join(REPO, "jev-opt.toml"))
    client = S.JevClient(dict(cfg["jev"]), ab(a.log_dir), a.run_id,
                         source_comments="none")
    landed = set()
    if os.path.isfile(client.jsonl_path):
        if not a.resume:
            sys.exit("%s exists: pass --resume to reuse its landed requests, "
                     "or another --run-id" % client.jsonl_path)
        for line in open(client.jsonl_path):
            r = json.loads(line)
            if not r.get("exhausted"):
                landed.add((r["round"], re.sub(r"\.retry\d*$", "", r["phase"])))
    with open(client.log_path, "a") as f:
        f.write("# %s, target %s, %d listed, %d gray questions in %d "
                "request(s) x %d repeats, leak check clean\n"
                % (RULE, b["target"], b["n_listed"],
                   sum(len(r["questions"]) for r in reqs), len(reqs),
                   a.repeats))
    t0 = time.time()
    for rep in range(1, a.repeats + 1):
        for req in reqs:
            if (rep, req["tag"]) in landed:
                print("[%s r%d] %s landed earlier" % (b["target"], rep,
                                                      req["tag"]))
                continue
            ans, ln = MS.send(client, req, rep)
            print("[%s r%d] %s -> %s (line %d)" % (
                b["target"], rep, req["tag"],
                "ok" if ans is not None else "LOST", ln), flush=True)
    client.write_totals(time.time() - t0)
    return client.jsonl_path


# ---------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------

def _p(x):
    return "-" if x is None else "%.2f" % x


def _pct(x):
    return "n/m" if x is None else "%.2f%%" % x


def facts(d, b):
    pc = ""
    if d.get("per_case"):
        pc = "; per case %s" % ", ".join(
            "%s %.1f%%" % (c, v) for c, v in sorted(d["per_case"].items()))
    na = lambda x: "?" if x is None else str(x)       # noqa: E731
    return ("train self %s reach %s, holdout self %s reach %s%s; %s insns / "
            "%s backward jumps in %s symbol(s); own symbol %s; crate %s"
            % (_pct(d["self_train"]), _pct(d["reach_train"]),
               _pct(d["self_hold"]), _pct(d["reach_hold"]), pc,
               na(d["insns"]), na(d["backedges"]), na(d["hosts"]),
               "yes" if d["own_symbol"] else "no", d["crate"]))


def line_numbers(b, line):
    """share / reach of a marks line: its listed rows summed (distinct
    symbols for self; reach capped at 100). jaq: all six workloads, as the
    frozen file; otherwise the training set."""
    ds = [d for d in b["rows"] if plugin_match(line, d["name"])]
    if not ds:
        return None, None, ds
    if b["layout"] == "single":
        sh = sum(d["self_all"] for d in ds)
        re_ = min(100.0, sum(d["reach_all"] for d in ds))
    else:
        sh = (None if ds[0]["self_train"] is None
              else sum(d["self_train"] or 0.0 for d in ds))
        re_ = min(100.0, sum(d["reach_train"] for d in ds))
    return sh, re_, ds


def write_marks(a, b, lines, folded, med, pvals, stats):
    agg = ("all six workloads summed (the frozen jaq file's `share`)"
           if b["layout"] == "single" else
           "equal by construction (no perf table)" if b["layout"] == "equal"
           else "the training set, summed periods")
    L = ["# jev-opt marks --- %s (generated by scripts/target_marks.py; rule "
         "of decision 109)" % a.target, "#",
         "# WHAT THIS FILE IS. One function per line: where jev-opt works. It "
         "says WHERE,",
         "# nothing about what to do there; no hint, attribute or knob is "
         "named or implied.",
         "# This is NOT the frozen jev-marks.txt: the owner decides per target "
         "whether it",
         "# replaces that file, in a new registration.", "#",
         "# MATCHING RULE (plugin/README.md \"Marks file\"). A line matches a "
         "function whose",
         "# demangled v0 name equals it, continues with `::` (a generic "
         "instantiation, a",
         "# closure, any inner item), or ends with `::` + the line. `#` starts "
         "a comment only",
         "# as the first non-space character of a line.", "#",
         "# HOW THEY WERE CHOSEN (no per-function judgement by anyone):",
         "#   seed  = top %d by training reach  UNION  top %d by training self"
         % (a.n, a.n),
         "#           among the listed rows that are not excluded and not "
         "compiler-generated;",
         "#   gray  = every other listed row not matched by a seed line: Jev "
         "Choice mark/skip,",
         "#           %d repeats, marked if the median P(mark) >= %.2f;"
         % (a.repeats, a.threshold),
         "#   excluded (never marked, never asked): C / no IR, thunks (<= %d "
         "insns),"
         % a.thunk_insns,
         "#           reach < %.1f%% and self < %.1f%% in both sets."
         % (a.floor, a.floor),
         "# Inputs: %s" % ", ".join(x for x in (
             a.perf_tsv_self and rel(a.perf_tsv_self),
             a.perf_tsv_inline and rel(a.perf_tsv_inline),
             a.equal_shares and ("equal shares over " + rel(a.equal_shares)),
             rel(a.structure_tsv)) if x),
         "# binary %s (.text %s…)." % (rel(a.binary), b["text_sha256"][:12]),
         "# Counts: %d listed, %d seed rows, %d gray questions, %d excluded "
         "thunks, %d C rows," % (
             b["n_listed"], sum(d["rule"] == "seed" for d in b["rows"]),
             sum(d["rule"] == "gray" for d in b["rows"]),
             sum(d["rule"] == "excluded" for d in b["rows"]),
             len(b["dropped_c"])),
         "# %d rows below the floor. %d lines below (the set may exceed N)."
         % (b["dropped_below_floor"], len(lines)),
         "# `share` / `reach` in each comment: %s; a line's listed rows "
         "summed." % agg,
         "# Per line: the facts and why it is here. Details: %s."
         % rel(a.report), ""]
    rows_by_line = collections.defaultdict(list)
    for d in b["rows"]:
        rows_by_line[d["line"]].append(d)
    for line in lines:
        sh, re_, ds = line_numbers(b, line)
        src = []
        for d in ds:
            if d["rule"] == "seed":
                src.append("%s seed (%s)" % (d["id"], ", ".join(d["seed_why"])))
            elif d["rule"] == "gray" and med.get(d["name"]) is not None \
                    and med[d["name"]] >= a.threshold:
                src.append("%s gray zone, Jev P(mark) %s, median %.2f" % (
                    d["id"], " ".join(_p(x) for x in pvals[d["name"]]),
                    med[d["name"]]))
        L.append("# share %s, reach %s over %d listed row(s)." % (
            "n/m" if sh is None else "%.2f%%" % sh, "%.2f%%" % re_, len(ds)))
        for d in ds:
            L.append("#   %s: %s." % (d["id"], facts(d, b)))
        L.append("# Why: %s." % "; ".join(src))
        L.append(line)
        L.append("")
    if os.path.basename(a.out) == "jev-marks.txt":
        sys.exit("refusing to write the frozen jev-marks.txt")
    open(ab(a.out), "w").write("\n".join(L))
    print("wrote", rel(a.out))


def write_report(a, b, seed_lines, lines, folded, med, pvals, stats, mode):
    t = b["target"]
    rows = b["rows"]
    L = ["# Marks for `%s` by rule: seed ∪ Jev gray zone (decision 109)" % t,
         "",
         "Generated by `scripts/target_marks.py` (%s). Facts only: the "
         "profile, the binary, the rule and Jev's answers. No hint is named "
         "here, and nothing in this file was chosen by hand." % mode, "",
         "* rule: seed = top %d by training reach ∪ top %d by training self "
         "among rows neither excluded nor compiler-generated; gray = other "
         "listed rows not matched by a seed line, Jev Choice (the marks "
         "study's Q1 text on the v2 state), %d repeats, mark if median "
         "P(mark) >= %.2f; excluded = C / no IR, thunks (<= %d insns), below "
         "%.1f%% reach and self." % (a.n, a.n, a.repeats, a.threshold,
                                     a.thunk_insns, a.floor),
         "* inputs: %s; structure `%s`; binary `%s` (.text `%s…`)." % (
             ", ".join("`%s`" % rel(x) for x in (a.perf_tsv_self,
                                                 a.perf_tsv_inline,
                                                 a.equal_shares) if x),
             rel(a.structure_tsv), rel(a.binary), b["text_sha256"][:12]),
         "* %d rows listed (ids in alphabetical order, as the state), %d "
         "below the floor, %d C rows." % (b["n_listed"],
                                          b["dropped_below_floor"],
                                          len(b["dropped_c"])),
         "* result: **%d seed lines, %d gray questions, %d gray rows marked, "
         "%d lines in the marks file** (N = %d)." % (
             len(seed_lines), sum(d["rule"] == "gray" for d in rows),
             sum(1 for d in rows if d["rule"] == "gray"
                 and med.get(d["name"]) is not None
                 and med[d["name"]] >= a.threshold),
             len(lines), a.n)]
    if stats:
        L.append("* requests: %d landed of %d sent (%d exhausted), %d HTTP "
                 "attempts, %d HTTP 503, max body %d B, billed $%.4f, list "
                 "price $%.4f; log `%s`." % (
                     stats["requests"] - stats["exhausted"], stats["requests"],
                     stats["exhausted"], stats["attempts"], stats["http_503"],
                     stats["max_body"], stats["billed_usd_e9"] / 1e9,
                     stats["list_usd_e9"] / 1e9, stats["log"]))
    if b.get("rank_note"):
        L.append("* ranked over all listed rows instead, the top N would "
                 "also have held these excluded / compiler-generated rows "
                 "(not seeded): %s." % ", ".join("`%s`" % x
                                                  for x in b["rank_note"]))
    L += ["", "## Seed (always marked, no question)", "",
          "| id | why | reach train | self train | insns / jumps | own "
          "symbol | function |", "|---|---|--:|--:|--:|:-:|---|"]
    for d in sorted((d for d in rows if d["rule"] == "seed"),
                    key=lambda d: d["reach_rank"] or 10 ** 6):
        L.append("| %s | %s | %s | %s | %s / %s | %s | `%s` |" % (
            d["id"], ", ".join(d["seed_why"]), _pct(d["reach_train"]),
            _pct(d["self_train"]), d["insns"], d["backedges"],
            "yes" if d["own_symbol"] else "no", d["name"]))
    cov = [d for d in rows if d["rule"] == "covered"]
    if cov:
        L += ["", "Rows matched by a seed line (not asked): " + "; ".join(
            "%s `%s` (line `%s`)" % (d["id"], MS.cut(d["name"], 120),
                                     d["covered_by"]) for d in cov) + "."]
    L += ["", "## Gray zone (Jev Choice mark / skip)", ""]
    gray = [d for d in rows if d["rule"] == "gray"]
    if not gray:
        L.append("Empty: every listed row is seed, covered or excluded; no "
                 "request was sent.")
    else:
        L += ["| id | P(mark) per repeat | median | marked | reach train | "
              "self train | insns / jumps | own symbol | function |",
              "|---|---|--:|:-:|--:|--:|--:|:-:|---|"]
        for d in sorted(gray, key=lambda d: (-(med.get(d["name"]) or -1),
                                             d["id"])):
            m = med.get(d["name"])
            L.append("| %s | %s | %s | %s | %s | %s | %s / %s | %s | `%s` |"
                     % (d["id"], " ".join(_p(x) for x in pvals.get(
                         d["name"], [])) or "-", _p(m),
                        "**yes**" if m is not None and m >= a.threshold
                        else ("not asked" if mode != "jev" else "no"),
                        _pct(d["reach_train"]), _pct(d["self_train"]),
                        d["insns"], d["backedges"],
                        "yes" if d["own_symbol"] else "no",
                        MS.cut(d["name"], 160)))
        short = [d["id"] for d in gray if mode == "jev" and sum(
            x is not None for x in pvals.get(d["name"], [])) < a.repeats]
        if short:
            L.append("")
            L.append("Rows with fewer than %d answers (median over the "
                     "landed ones): %s." % (a.repeats, ", ".join(short)))
    L += ["", "## Excluded (never marked, never asked)", ""]
    ex = [d for d in rows if d["rule"] == "excluded"]
    for d in ex:
        L.append("* %s `%s`: %s." % (d["id"], d["name"], d["excl"]))
    for n in b["dropped_c"]:
        L.append("* `%s`: C / no IR (not in the listed table)." % n)
    L.append("* %d rows: reach and self below %.1f%% in both sets." % (
        b["dropped_below_floor"], a.floor))
    L += ["", "## The marks file", ""]
    L += ["* `%s`" % l for l in lines]
    if folded:
        L += ["", "Folded into another line that matches them: " + "; ".join(
            "`%s` -> `%s`" % (k, v) for k, v in sorted(folded.items())) + "."]
    open(ab(a.report), "w").write("\n".join(L) + "\n")
    print("wrote", rel(a.report))


def main():
    p = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--target", required=True)
    p.add_argument("--perf-tsv-self")
    p.add_argument("--perf-tsv-inline")
    p.add_argument("--equal-shares", help="function list, equal shares (no "
                   "perf table)")
    p.add_argument("--binary", help="the profiled binary (default: the "
                   "marks study's, for jaq / zopfli / hintbench)")
    p.add_argument("--text-sha", help=".text sha256 prefix to check")
    p.add_argument("--structure-tsv", help="scripts/inline_structure.py "
                   "output (default artifacts/jev-marks-study/<t>-inline-"
                   "structure.tsv)")
    p.add_argument("--workloads", help="state sentence for a new target")
    p.add_argument("--n", "--marks-n", dest="n", type=int)
    p.add_argument("--floor", type=float, default=1.0)
    p.add_argument("--thunk-insns", type=int, default=MS.HYB_THUNK_INSNS)
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--out")
    p.add_argument("--report")
    p.add_argument("--log-dir")
    p.add_argument("--run-id")
    p.add_argument("--resume", action="store_true",
                   help="reuse the landed requests of an existing log")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--seed-only", action="store_true")
    g.add_argument("--jev", action="store_true")
    p.add_argument("--json", help="also write the classified table here")
    a = p.parse_args()
    t = a.target
    dfl = DEFAULTS.get(t, {})
    st = MS.TARGETS.get(t, {})
    a.perf_tsv_self = a.perf_tsv_self or dfl.get("self_tsv")
    a.perf_tsv_inline = a.perf_tsv_inline or dfl.get("inline_tsv")
    if not (a.perf_tsv_self or a.perf_tsv_inline):
        a.equal_shares = a.equal_shares or dfl.get("equal_shares")
    if not a.equal_shares and not (a.perf_tsv_self and a.perf_tsv_inline):
        p.error("--perf-tsv-self and --perf-tsv-inline (or --equal-shares) "
                "are required for %s" % t)
    a.binary = a.binary or st.get("binary")
    if not a.binary:
        p.error("--binary is required for %s" % t)
    if a.text_sha is None and a.binary == st.get("binary"):
        a.text_sha = st.get("text_sha")
    a.structure_tsv = a.structure_tsv or os.path.join(
        "artifacts", "jev-marks-study", "%s-inline-structure.tsv" % t)
    if not os.path.isfile(ab(a.structure_tsv)):
        p.error("no %s: run scripts/inline_structure.py --binary %s "
                "--names-from <perf-self tsv> --top 300 --tsv %s first"
                % (a.structure_tsv, a.binary, a.structure_tsv))
    a.n = a.n or dfl.get("n")
    if not a.n:
        p.error("--n is required for %s" % t)
    a.out = a.out or os.path.join("targets", t, "jev-marks.jev.txt")
    a.report = a.report or os.path.join("targets", t,
                                        "jev-marks.jev.rationale.md")
    a.log_dir = a.log_dir or os.path.join("artifacts", "jev-marks", t)
    a.run_id = a.run_id or "tm-%s" % t
    if os.path.basename(a.out) == "jev-marks.txt":
        p.error("refusing to write the frozen jev-marks.txt; use "
                "jev-marks.jev.txt")
    mode = "jev" if a.jev else "seed-only" if a.seed_only else "dry-run"

    b = build_table(a)
    seed_lines = classify(b, a.n, a.thunk_insns)
    gray = [d for d in b["rows"] if d["rule"] == "gray"]
    state = render_state(b, a.workloads)
    reqs = build_requests(b, state) if gray else []
    hits = leak_hits(b, reqs) if reqs else []
    print("%s: %d listed (%d below floor, %d C), N %d, layout %s, .text %s…"
          % (t, b["n_listed"], b["dropped_below_floor"], len(b["dropped_c"]),
             a.n, b["layout"], b["text_sha256"][:12]))
    print("  state sha256 %s, %d bytes" % (
        hashlib.sha256(state.encode()).hexdigest()[:16], len(state)))
    for k in ("seed", "covered", "gray", "excluded"):
        ds = [d for d in b["rows"] if d["rule"] == k]
        print("  %-8s %3d rows" % (k, len(ds)))
        for d in ds:
            extra = {"seed": ", ".join(d["seed_why"]),
                     "covered": "by " + (d.get("covered_by") or ""),
                     "gray": "r%.2f s%s be %s own %s%s" % (
                         d["reach_train"], _p(d["self_train"]),
                         d["backedges"], "y" if d["own_symbol"] else "n",
                         " generated" if d["generated"] else ""),
                     "excluded": d["excl"] or ""}[k]
            print("    %s %-40s %s" % (d["id"], extra[:40],
                                       MS.cut(d["name"], 110)))
    print("  seed lines %d" % len(seed_lines))
    for l in seed_lines:
        print("    " + l)
    if reqs:
        print("  gray: %d questions in %d request(s) per repeat, bodies %s B;"
              " leak check %s" % (
                  len(gray), len(reqs), ", ".join(str(len(json.dumps({
                      "model": "typesafe-ai/jev", "state": r["state"],
                      "questions": r["questions"]}))) for r in reqs),
                  hits or "clean"))
    if b.get("rank_note"):
        print("  note: ranked over all rows, the top N would include "
              "excluded/generated %s" % b["rank_note"])
    if hits:
        sys.exit("leak check failed")

    med, pvals, stats = {}, {}, None
    if a.jev and reqs:
        path = ask_gray(a, b, reqs)
        pv, stc = read_log(path, a.repeats)
        stats = dict(stc)
        stats["log"] = rel(path)
        for d in gray:
            xs = pv.get(d["name"], [None] * a.repeats)
            pvals[d["name"]] = xs
            got = [x for x in xs if x is not None]
            med[d["name"]] = statistics.median(got) if got else None
        print("  requests %s" % stats)
    gray_lines = [d["line"] for d in gray if med.get(d["name"]) is not None
                  and med[d["name"]] >= a.threshold]
    lines, folded = final_lines(seed_lines + gray_lines)
    print("  final: %d lines (seed %d + gray-marked rows %d; folded %d)" % (
        len(lines), len(seed_lines), len(gray_lines), len(folded)))
    for l in lines:
        print("    " + l)
    if a.json:
        json.dump(dict(b, med=med, pvals=pvals, lines=lines, folded=folded,
                       stats=stats, state_sha256=hashlib.sha256(
                           state.encode()).hexdigest()),
                  open(ab(a.json), "w"), indent=1)
    if mode == "dry-run":
        print("  (dry run: nothing written, no request sent)")
        return 0
    if mode == "jev" and gray and not med:
        sys.exit("no answers")
    write_marks(a, b, lines, folded, med, pvals, stats)
    write_report(a, b, seed_lines, lines, folded, med, pvals, stats, mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
