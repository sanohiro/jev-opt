#!/usr/bin/env python3
"""The jev-opt hint search loop (SPEC.ja.md 1(3), decision 62).

    scripts/jev_search.py --target jaq \
        --marks targets/jaq/jev-marks.txt --sites targets/jaq/sites.json \
        --proposer jev --rounds 5 --out artifacts/jaq-search/<run-id>/

One round is TWO builds, because a loop site key depends on the result of
inlining and therefore on the function attributes (SPEC.ja.md 8.4,
decision 61b):

  phase A   ask one Choice per marked function (plus the `__build__`
            pseudo-site, if [search] build_knobs is not empty)
            -> write plan A (fn_attrs only)
            -> build with JEV_MODE=apply-dump, which applies those attributes
               at PipelineStartEP and then dumps the loops out of the IR they
               produced
  phase B   ask one Choice per refreshed `loop_in_mark` site
            -> write plan B (the same fn_attrs + loop_md)
            -> build with JEV_MODE=apply
            -> correctness (sha256 of every case's output vs the baseline)
            -> timing (bench.py, interleaved with the baseline and an in-run
               A/A copy of it)

`basis` links the two: plan B carries the sha256 of the fn_attrs set the
dump that produced its loop keys was taken under, and the driver checks it
before building. SPEC.ja.md 8.4 asks the *plugin* to enforce this; the plugin
as built does not parse `basis` at all (it ignores unknown plan fields), so
the check lives here, and within one round it is a tautology --- the same
attribute set wrote both plans. It bites on `--resume` and on a hand-edited
plan, and `docs/search-driver.md` says so.

Proposers (--proposer):
  jev      one HTTP request per phase, one Choice question per site, state in
           the frozen format of `state_header`/`state_section` below
  random   uniform over the same candidate lists, seeded
  oracle   one-factor sweep (each candidate alone, everything else
           KEEP_DEFAULT) plus one arm combining the per-site winners

Everything that builds, measures or checks correctness is delegated:
scripts/target_common.sh owns the build recipe, the workload list, the pinned
core and the per-case output hashes; scripts/bench.py owns the interleaved
timing and the paired bootstrap; scripts/plugin_report.py owns reading the
plugin's per-module reports; scripts/jev_vocab.py owns the frozen vocabulary
and the frozen candidate descriptions.

Python 3 standard library only (`requests` is not installed; HTTP is urllib).
"""

import argparse
import copy
import datetime
import glob
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jev_vocab as V          # noqa: E402
import plugin_report           # noqa: E402
import bench as B              # noqa: E402  (argv[0] pin, decision 97)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(REPO, "scripts", "bench.py")
PLUGIN = os.path.join(REPO, "plugin", "build", "libjevplugin.so")

# The state template. v1 is Experiment 3's, frozen. v2 is decision 73: the
# same sections plus a platform block and a per-site verdict block, and the
# V2 wording of "What is being decided". `--vocab` selects both the
# vocabulary and the state template, because the two together are the one
# measurement condition the prompt study measured (`W7`).
#
# v3 (decision 77) is v2's template with two changes, both in the function
# phase: the candidate list loses `inline` and `cold` and gains
# `inline_always` (`jev_vocab.py` v3), and the verdict block states the
# mechanical fact that made that necessary. Everything else --- the loop
# phase, the platform block, the source excerpts, the remarks --- is v2's.
# v3.1 (decision 83) is v3's template with the three evidence defects of
# `docs/experiments/hintbench/jev-oneshot-v3.md` sections 5 and 14 repaired:
# a loop's legality comes from its own leaf location and says UNKNOWN when
# that location is shared, a function's verdict quotes the inliner's own
# decisions about it instead of an invented budget ratio, and a uniform
# placeholder share is reported as not measured instead of classified. The
# candidates, the descriptions and the questions are v3's, to the byte.
#
# v4 (decision 84) is v3.1's state with one change and only one: the
# function candidates' descriptions are rebalanced so that `inline_always`,
# `inline_never`, `align_*` and `KEEP_DEFAULT` are the same length and the
# same strength (`jev_vocab.py` v4). The candidate ids, the plan fragments,
# the loop half and every mechanical reading are v3.1's.
# v3.2 / v4.1 (Experiment 4): the round history reports what each round
# measured **per workload**, not only the eight-way aggregate, and a site's
# own history line quotes the ratio and the 95% CI on the case that site's
# kernel is timed by. Nothing else moves: the candidates, the descriptions,
# the questions, the verdict block and the source excerpts are v3.1's and
# v4's to the byte. On a target with no per-workload readout (jaq, zopfli,
# oxipng --- `own_workload_of` returns None there) and in round 1 of every
# run the rendered state is identical to its predecessor's apart from this
# header line, which is what the version bump is for (decision 19).
# v3.3 / v4.2 (decision 89, the four protocol gaps Experiment 4 exposed).
# Three things move, all of them evidence rather than wording, and all of
# them gated on `evidence_fixes` so that v1 and v2 stay byte-replayable:
#
#   (89 c) a site's history line now also says what the same hint measured on
#          the OTHER cases of the rounds it was in the plan. Per-kernel
#          feedback hides cross-kernel cost: `inline(always)` at `k6_hot_loop`
#          is inert on k6 and costs 2.8% on k3, and nothing in the v4.1 state
#          said so.
#   (89 d) where two sites are timed by one case, each of them says so, so
#          that neither is read as the sole cause of what that case did.
#   (87 c) the loop verdict block leads with what the plugin recorded at
#          VectorizerEnd --- vectorized or not, the width and interleave count
#          LLVM actually used --- which is a per-loop fact and replaces the
#          UNKNOWN that a shared remark line produced.
#
# The exploration Choice of decision 89 (b) is a fourth request per round and
# not part of the state template; the candidate lists, descriptions, question
# wordings, verdict rules and source excerpts are v3.2's and v4.1's to the
# byte.
#
# v5 (decision 85) reuses v4.2's state template as-is: the candidate table
# just has fewer rows (jev_vocab.py v5), and nothing about how a site's
# evidence is rendered changes. A separate change will add the v5
# post_vectorize line the plugin now records; until then "v5" and "v4" render
# byte-identical state for any site whose picks avoid the removed candidates.
STATE_FORMATS = {"v1": "state-v1-2026-09-22", "v2": "state-v2-2026-09-22",
                 "v3": "state-v3.3-2026-09-22", "v4": "state-v4.2-2026-09-22",
                 "v5": "state-v5.0-2026-09-23",
                 # v5 + `--pv-untried on` (decision 92 c): the
                 # post_vectorize width and interleave lines also name the
                 # vocabulary values not yet tried at the loop. Only legal
                 # with --vocab v5.
                 "v5.1": "state-v5.1-2026-09-23",
                 # v6 (decision 98) restores unroll_disable to the loop
                 # table; the template is otherwise v5.0's, so it gets its
                 # own name rather than reusing v5's.
                 "v6": "state-v6.0-2026-09-23"}
STATE_FORMAT_VERSION = STATE_FORMATS["v1"]


def set_state_format(version):
    global STATE_FORMAT_VERSION
    STATE_FORMAT_VERSION = STATE_FORMATS[version]
    return STATE_FORMAT_VERSION


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

DEFAULTS = {
    "search": {
        "rounds": 5,
        "max_sites": 40,
        "build_knobs": [],
        "max_state_chars": 120000,
        "stage": "separate",
    },
    "evaluation": {
        "repetitions": 15,
        "warmup": 3,
        "seed": 20260921,
        "resamples": 10000,
        # Measurement protocol v2 (results.md 170). The defaults are
        # protocol v1 (decision 80), so a config without these keys measures
        # exactly as before. `reps_oracle` None means "= repetitions".
        "confirm_when": "ci",
        "aa_leg": True,
        "reps_oracle": None,
    },
    "jev": {
        "base_url": "https://ai-gateway.vercel.sh/typesafe",
        "endpoint": "/v1/systemone",
        "model": "typesafe-ai/jev",
        "api_key_env": "AI_GATEWAY_API_KEY",
        # Decision 92 (d). A config written before these keys existed
        # gets these values, which are the policy's and not the old
        # 60 s / 3 attempts.
        "request_timeout_s": 20,
        "retries": 200,
        "retry_wall_budget_s": 600,
        "backoff_cap_s": 5.0,
        "phase_resend_max": 2,
        "min_confidence": 0.0,
        "api_cost_budget_usd": 5.0,
    },
}


def load_config(path):
    """jev-opt.toml, merged over DEFAULTS. A missing file is not an error.

    Only the keys this driver owns are read here. The build recipe
    (`[project] fixed_rustflags`, `profile_env`) stays in
    scripts/target_common.sh so that there is exactly one copy of it.
    """
    cfg = copy.deepcopy(DEFAULTS)
    sha = None
    if path and os.path.isfile(path):
        import tomllib
        raw = open(path, "rb").read()
        sha = hashlib.sha256(raw).hexdigest()
        doc = tomllib.loads(raw.decode())
        for section, values in doc.items():
            if section in cfg and isinstance(values, dict):
                cfg[section].update(values)
            else:
                cfg[section] = values
    cfg["_path"] = path if sha else None
    cfg["_sha256"] = sha
    return cfg


# ---------------------------------------------------------------------------
# the bash side: scripts/target_common.sh
# ---------------------------------------------------------------------------

def _bash(script, env=None, args=(), check=True, capture=True):
    full = dict(os.environ)
    full.update(env or {})
    p = subprocess.run(["bash", "-c", script, "jev_search"] + list(args),
                       env=full, text=True,
                       capture_output=capture)
    if check and p.returncode != 0:
        sys.exit("bash step failed (%d):\n%s\n%s"
                 % (p.returncode, p.stdout or "", p.stderr or ""))
    return p


_PREAMBLE = """
set -uo pipefail
export TARGET="$JS_TARGET"
source "%s/scripts/target_common.sh"
""" % REPO


def shell_config(target, bench_set):
    """Read the frozen per-target settings out of target_common.sh.

    Returns (dict, effective bench set). `training` is what SPEC.ja.md 7 wants
    for the search rounds; a target that declares no TRAIN_WORKLOADS (the toy)
    falls back to its single case set and the round record says so.
    """
    script = _PREAMBLE + r"""
for v in REPO TRIPLE MANIFEST BIN_NAME PROFDATA BENCH_CPU BENCH_STDOUT \
         BENCH_GAP_MS FILTER_SRC_ROOT PGO_DIR; do
  printf '%s\t%s\n' "$v" "${!v}"
done
for w in "${WORKLOADS[@]}"; do printf 'WORKLOAD\t%s\n' "$w"; done
"""
    env = {"JS_TARGET": target, "BENCH_SET": bench_set}
    p = _bash(script, env, check=False)
    if p.returncode != 0 and bench_set == "training":
        # The toy has no training case set; SPEC.ja.md 7's search/holdout
        # split does not exist for it.
        p = _bash(script, {"JS_TARGET": target, "BENCH_SET": "holdout"})
        bench_set = "holdout-as-search"
    elif p.returncode != 0:
        sys.exit("target_common.sh refused TARGET=%s BENCH_SET=%s:\n%s"
                 % (target, bench_set, p.stderr))
    out = {"workloads": []}
    for line in p.stdout.splitlines():
        k, _, v = line.partition("\t")
        if k == "WORKLOAD":
            out["workloads"].append(v)
        elif k:
            out[k.lower()] = v
    out["bench_set"] = bench_set
    return out


def sh_build(target, target_dir, log, knobs, jev_env):
    """build_variant with the plugin's environment set. Returns the rc."""
    script = _PREAMBLE + 'build_variant "$JS_TD" "$JS_LOG" "$@"\n'
    env = {"JS_TARGET": target, "JS_TD": target_dir, "JS_LOG": log}
    env.update(jev_env)
    return _bash(script, env, args=list(knobs), check=False).returncode


def sh_correctness(target, binary, out_file):
    script = _PREAMBLE + 'run_correctness "$JS_BIN" "$JS_OUT"\n'
    env = {"JS_TARGET": target, "JS_BIN": binary, "JS_OUT": out_file}
    return _bash(script, env, check=False).returncode


# ---------------------------------------------------------------------------
# plugin reports
# ---------------------------------------------------------------------------

def read_reports(directory):
    if not os.path.isdir(directory):
        return []
    return [rep for _, rep in plugin_report.load(directory)]


def merged_apply_outcomes(directory):
    """{entry (loop key or fn name): verdict} merged over every module.

    Same rule as `scripts/plugin_report.py apply`: a plan entry naming a
    function of one crate is legitimately `unmatched` in every other module,
    so an entry counts as unmatched only when no module resolved it.
    """
    merged = {}
    for rep in read_reports(directory):
        for r in rep.get("results", []):
            what = r.get("key") or r.get("fn")
            e = merged.setdefault(what, {"outcomes": [], "attached": ""})
            e["outcomes"].append(r["outcome"])
            if r.get("attached"):
                e["attached"] = r["attached"]
    out = {}
    for what, e in merged.items():
        real = [o for o in e["outcomes"] if o != "unmatched"]
        verdict = "unmatched"
        if real:
            verdict = real[0] if len(set(real)) == 1 else "+".join(sorted(set(real)))
        out[what] = {"outcome": verdict, "attached": e["attached"]}
    return out


def unmatched_marks(reports):
    """Marks no report of the build resolved (intersection, plugin/README)."""
    sets = [set(r.get("unmatched_marks", []))
            for r in reports if r.get("loop_ep_ran")]
    if not sets:
        return set()
    out = sets[0]
    for s in sets[1:]:
        out &= s
    return out


def marked_functions(reports):
    """{mark: [function record, ...]} from a dump's function table.

    The plugin emits the table only for marked functions, once per module; a
    generic function appears once per monomorphization, which is exactly the
    fan-out decision 61(c) wants a single Choice to cover.
    """
    by_mark = {}
    seen = set()
    for rep in reports:
        for fn in rep.get("functions", []):
            mark = fn.get("mark") or ""
            if not mark:
                continue
            ident = (mark, fn["linkage"])
            if ident in seen:
                continue
            seen.add(ident)
            by_mark.setdefault(mark, []).append(fn)
    return by_mark


def loop_sites(reports):
    """Deduplicated `loop_in_mark` site records (decision 61a)."""
    out, seen = [], set()
    for rep in reports:
        for s in rep.get("sites", []):
            if s.get("match") != "loop_in_mark":
                continue
            if s["key"] in seen:
                continue
            seen.add(s["key"])
            s = dict(s)
            s["stage"] = rep.get("stage", "")
            # Decision 87 (c): what LLVM did with this very loop, recorded by
            # the plugin's VectorizerEnd pass in the same build. Absent from
            # a report an older plugin wrote, which is why every reader of it
            # tolerates None.
            s["post_vectorize"] = (rep.get("post_vectorize")
                                   or {}).get(s["key"])
            out.append(s)
    out.sort(key=lambda s: -(s.get("hotness") or 0))
    return out


def site_id_of(site):
    """An identity for one loop that survives a change of function attributes.

    The site *key* is the plan's only legal handle on a loop, but it is a hash
    of the inlining result, so it changes whenever the attributes change
    (decision 61). Round-to-round history and the oracle's "best per site"
    therefore need a coarser identity: the mark, the innermost source
    location, and the loop depth.
    """
    leaf = site.get("leaf") or {}
    return "%s@%s:%s:%s#d%s" % (site.get("mark", "?"),
                                os.path.basename(leaf.get("file", "?")),
                                leaf.get("line", "?"), leaf.get("col", "?"),
                                site.get("depth", "?"))


# ---------------------------------------------------------------------------
# marks, source and remarks
# ---------------------------------------------------------------------------

def read_marks(path):
    marks = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        marks.append(line)
    return marks


COMMENT_MARKER = "// [comment removed]"

_RAW_STR_RE = re.compile(r'(?:b?r)(#*)"')
_CHAR_LIT_RE = re.compile(r"'(?:\\.|[^'\\])'")
_DOC_ATTR_RE = re.compile(r'^\s*#!?\[\s*doc\b')


def strip_rust_comments(lines, url_guard=False):
    """One entry per input line: its code with every comment removed, or
    `None` when the line held nothing but a comment or a doc attribute.

    A small lexer rather than a regex, because `//` is only a comment outside
    a string: `b'\\''`, `'"'` and `r#"http://x"#` all occur in the sources
    this driver quotes, and Rust's block comments nest. String, raw-string and
    block-comment state is carried across lines, so a window that starts in
    the middle of a `/* ... */` is handled by stripping the whole file and
    slicing afterwards.

    A blank line stays blank; the line count never changes, so the excerpt's
    line numbers and its `>` marker keep pointing at the same source lines.
    `url_guard` keeps `//` that directly follows a `:` (a URL scheme), for the
    compiler-remark text, which is prose rather than Rust.
    """
    out = []
    depth = 0            # /* */ nesting depth, carried across lines
    raw_hashes = None    # inside r#"..."#: how many `#` close it
    in_str = False       # inside a "..." literal
    for raw in lines:
        i, n = 0, len(raw)
        kept = []
        while i < n:
            c = raw[i]
            if depth > 0:
                if raw.startswith("*/", i):
                    depth -= 1
                    i += 2
                elif raw.startswith("/*", i):
                    depth += 1
                    i += 2
                else:
                    i += 1
                continue
            if raw_hashes is not None:
                if c == '"' and raw[i + 1:i + 1 + raw_hashes] == "#" * raw_hashes:
                    kept.append(raw[i:i + 1 + raw_hashes])
                    i += 1 + raw_hashes
                    raw_hashes = None
                else:
                    kept.append(c)
                    i += 1
                continue
            if in_str:
                if c == "\\":
                    kept.append(raw[i:i + 2])
                    i += 2
                elif c == '"':
                    kept.append(c)
                    in_str = False
                    i += 1
                else:
                    kept.append(c)
                    i += 1
                continue
            if raw.startswith("//", i) and not (url_guard and i > 0
                                                and raw[i - 1] == ":"):
                break                       # the rest of the line is a comment
            if raw.startswith("/*", i):
                depth = 1
                i += 2
                continue
            if c in "rb":
                m = _RAW_STR_RE.match(raw, i)
                if m and not (i > 0 and (raw[i - 1].isalnum()
                                         or raw[i - 1] == "_")):
                    raw_hashes = len(m.group(1))
                    kept.append(m.group(0))
                    i = m.end()
                    continue
            if c == '"':
                in_str = True
                kept.append(c)
                i += 1
                continue
            if c == "'":
                m = _CHAR_LIT_RE.match(raw, i)
                if m:                       # a char literal, not a lifetime
                    kept.append(m.group(0))
                    i = m.end()
                    continue
            kept.append(c)
            i += 1
        code = "".join(kept).rstrip()
        if not raw.strip():
            out.append(raw)                 # a blank line is not a comment
        elif not code or _DOC_ATTR_RE.match(code):
            out.append(None)                # nothing but a comment / #[doc]
        else:
            out.append(code)
    return out


def strip_comments_in_text(text):
    """The same strip applied to one line of compiler-remark prose."""
    got = strip_rust_comments([text], url_guard=True)[0]
    return text if got is None and not text.strip() else (got or "")


class SourceBook:
    """file:line -> a source excerpt, with the path resolution jaq needs.

    DWARF records the path the compiler saw. For a vendored submodule that is
    already an absolute path into targets/<t>/src; for a crates.io dependency
    it points into ~/.cargo/registry; for the standard library it points at a
    path that does not exist on this machine, and the excerpt is then simply
    absent from the state.
    """

    def __init__(self, roots, comments="strip"):
        # `comments`: "strip" (the default) removes every comment and doc
        # attribute from the excerpts this book renders, "keep" quotes the
        # file verbatim. A benchmark's own commentary can name the answer
        # (decision 81), and the source files must not be edited for it ---
        # editing them would move the line numbers a site key is built from.
        self.comments = comments
        # De-duplicated and with nested roots dropped, so REPO does not make
        # the index walk everything twice.
        seen = []
        for r in roots:
            if r and os.path.isdir(r) and not any(
                    os.path.abspath(r).startswith(os.path.abspath(s) + os.sep)
                    or os.path.abspath(r) == os.path.abspath(s) for s in seen):
                seen.append(r)
        self.roots = seen
        self.cache = {}
        self.lines_cache = {}
        self.index = None
        self.paths = []

    def lines_of(self, real):
        """The file's lines as the excerpts quote them, cached per path.

        Under `strip` a removed line is `None` here and is rendered as
        `COMMENT_MARKER`; the list is always as long as the file, so line
        numbers are the file's own.
        """
        if real not in self.lines_cache:
            try:
                lines = open(real, errors="replace").read().splitlines()
            except OSError:
                lines = None
            if lines is not None and self.comments == "strip":
                lines = strip_rust_comments(lines)
            self.lines_cache[real] = lines
        return self.lines_cache[real]

    def _resolve(self, path):
        if path in self.cache:
            return self.cache[path]
        found = None
        if os.path.isabs(path) and os.path.isfile(path):
            found = path
        if found is None:
            for root in self.roots:
                cand = os.path.join(root, path.lstrip("/"))
                if os.path.isfile(cand):
                    found = cand
                    break
        if found is None:
            # Suffix match: the longest tail of the recorded path that
            # identifies exactly one indexed file. A bare basename is not
            # enough --- `mod.rs` and `lib.rs` exist in every crate, and
            # matching one of them to a std path that is not on this machine
            # puts a stranger's source in the state.
            self._walk_index()
            parts = path.replace("\\", "/").split("/")
            for n in range(min(4, len(parts)), 1, -1):
                tail = "/".join(parts[-n:])
                hits = [q for q in self.paths if q.endswith("/" + tail)]
                if len(hits) == 1:
                    found = hits[0]
                    break
        self.cache[path] = found
        return found

    def _walk_index(self):
        if self.index is None:
            self.index = {}
            self.paths = []
            for root in self.roots:
                for dirpath, dirnames, files in os.walk(root):
                    dirnames[:] = [d for d in dirnames
                                   if d not in ("target", ".git")]
                    for f in files:
                        if f.endswith(".rs"):
                            full = os.path.join(dirpath, f)
                            self.index.setdefault(f, full)
                            self.paths.append(full)
        return self.paths

    def find_definition(self, mark):
        """(file, line) of `fn <name>` for a mark, searched in the roots.

        The plugin's dump carries no source location for a function (only
        loops have one), and a loop's own `leaf` location is usually inside
        core's iterator machinery rather than in the marked function. So the
        marked function's own source is found by looking for its definition:
        the last identifier of the mark, scored by how much of the mark's
        module path the file path repeats. A heuristic, and the state says
        "source:" with nothing under it when it fails.
        """
        ident, rest = None, mark
        while True:
            stripped = re.sub(r"<[^<>]*>", "", rest)
            if stripped == rest:
                break
            rest = stripped
        tail = [p for p in rest.split("::") if p and not p.startswith("{")]
        if tail:
            ident = re.sub(r"[^A-Za-z0-9_]", "", tail[-1])
        if not ident:
            return (None, None)
        pat = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:default\s+)?"
                         r"(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?"
                         r"(?:extern\s+\"[^\"]*\"\s+)?fn\s+" +
                         re.escape(ident) + r"\b")
        # Score by the identifiers of the whole mark --- including the ones
        # inside `<...>`, which for a trait-impl mark like
        # `<jaq_core::compile::TermId>::run` are the only thing that says
        # which crate and module to look in. `-` and `_` are the same
        # character for this purpose (crate `jaq_core`, directory
        # `jaq-core`). A best score of 0 means "found nothing that belongs
        # to this mark", and the state then says the source is unavailable
        # rather than showing an unrelated `fn` of the same name.
        hints = {h.lower() for h in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", mark)
                 if h.lower() not in ("core", "alloc", "std", "closure", "as",
                                      ident.lower())}
        best = None
        for path in self._walk_index():
            try:
                lines = open(path, errors="replace").read().splitlines()
            except OSError:
                continue
            key = path.lower().replace("-", "_")
            score = sum(1 for h in hints if h.replace("-", "_") in key)
            if score == 0 or (best and score < best[0]):
                continue
            for n, line in enumerate(lines, 1):
                if pat.match(line):
                    if best is None or score > best[0] or len(path) < len(best[1]):
                        best = (score, path, n)
                    break
        if best is None:
            return (None, None)
        return (best[1], best[2])

    def excerpt(self, path, line, ctx=40):
        real = self._resolve(path)
        if not real or not line:
            return None
        lines = self.lines_of(real)
        if lines is None:
            return None
        if int(line) > len(lines):
            return None          # resolved to the wrong file; say nothing
        lo = max(1, int(line) - ctx)
        hi = min(len(lines), int(line) + ctx)
        body = "\n".join("%5d %s%s" % (n, ">" if n == int(line) else " ",
                                       COMMENT_MARKER if lines[n - 1] is None
                                       else lines[n - 1])
                         for n in range(lo, hi + 1))
        return "%s:%d (lines %d-%d, the site's own line marked `>`)\n%s" % (
            os.path.relpath(real, REPO) if real.startswith(REPO) else real,
            int(line), lo, hi, body)


REMARK_RE = re.compile(r"^remark: ([^:]+):(\d+):(\d+): (.*)$")


class RemarkBook:
    """`remark:` lines of a build log, indexed by (basename, line).

    SPEC.ja.md 3: the remark lines carry no function name, only a source
    location, so this is the only attribution available without the heavier
    machinery of scripts/remark_attribution.py.
    """

    def __init__(self, log_path):
        self.by_file = {}
        # Exactly-located remarks: (basename, line, col) -> deduped texts,
        # in the order the log emitted them. `by_file` above keeps the v1
        # indexing byte for byte so that `near()` --- which every state
        # format uses for the *function* sections --- does not move.
        self.by_loc = {}
        # (basename, line, col, text) -> how many lines the log carries,
        # before dedup. A source location that several inlined loops share
        # emits the same verdict several times, and that count is the only
        # signal in the log which says the location is shared.
        self.at_count = {}
        if not log_path or not os.path.isfile(log_path):
            return
        seen = set()
        for line in open(log_path, errors="replace"):
            m = REMARK_RE.match(line.strip())
            if not m:
                continue
            f, ln, col, text = (m.group(1), int(m.group(2)), int(m.group(3)),
                                m.group(4))
            base = os.path.basename(f)
            self.at_count[(base, ln, col, text)] = \
                self.at_count.get((base, ln, col, text), 0) + 1
            loc = self.by_loc.setdefault((base, ln, col), [])
            if text not in loc:
                loc.append(text)
            key = (base, ln, text)
            if key in seen:
                continue
            seen.add(key)
            self.by_file.setdefault(base, []).append((ln, text))

    def near(self, path, line, span=40, limit=8):
        """Remarks within `span` lines of `line`, nearest first.

        The ±span window is the only attribution the log supports for a
        *function*, whose body covers many lines. It is deliberately NOT what
        a loop's legality is read from any more: see `at()`.
        """
        if not path or not line:
            return []
        rows = self.by_file.get(os.path.basename(path), [])
        hit = [(ln, t) for ln, t in rows if abs(ln - int(line)) <= span]
        hit.sort(key=lambda r: (abs(r[0] - int(line)), r[0]))
        return hit[:limit]

    def at(self, path, line, col=None):
        """Remarks whose location is exactly this one.

        A loop has one source location, not a ±10-line neighbourhood, so a
        statement about *this* loop may only be built from the remarks the
        compiler emitted at that location. The column is used when the caller
        has one (the dump records it for every loop leaf).
        """
        if not path or not line:
            return []
        base = os.path.basename(path)
        if col is not None:
            return list(self.by_loc.get((base, int(line), int(col)), []))
        out = []
        for (b, ln, _c), texts in self.by_loc.items():
            if b == base and ln == int(line):
                out += [t for t in texts if t not in out]
        return out

    def n_loops_at(self, path, line, col=None):
        """How many distinct loops the log reports at exactly this location.

        LoopVectorize emits one verdict per loop it looks at: either
        `vectorized loop (vectorization width: N, ...)` or the bare
        `loop not vectorized` missed-remark that accompanies the
        `loop not vectorized: <reason>` analysis. Counting those verdict
        lines *before* dedup therefore counts the loops that share the
        location. 1 means the remarks at that location are this loop's; more
        than 1 means they are several loops' and cannot be split apart.
        Returns None when the log has no vectoriser verdict there at all.
        """
        if not path or not line:
            return None
        base = os.path.basename(path)
        n, seen_any = 0, False
        for (b, ln, c, text), k in self.at_count.items():
            if b != base or ln != int(line):
                continue
            if col is not None and c != int(col):
                continue
            if text == "loop not vectorized" or \
                    text.startswith("vectorized loop ("):
                n += k
                seen_any = True
        return n if seen_any else None


INLINED_RE = re.compile(
    r"^remark: (?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+): "
    r"'(?P<callee>[^']+)' inlined into '(?P<caller>[^']+)'"
    r"(?: with \((?P<paren>[^)]*)\))?(?P<rest>.*)$")

NOT_INLINED_RE = re.compile(
    r"^remark: (?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+): "
    r"'(?P<callee>[^']+)' not inlined into '(?P<caller>[^']+)' "
    r"because (?P<why>.*)$")

COST_RE = re.compile(r"cost=(-?\d+)")
THRESHOLD_RE = re.compile(r"threshold=(-?\d+)")


class InlineBook:
    """LLVM's inline remarks of a build log, indexed by **callee** symbol.

    `RemarkBook` indexes by source location, and an inline remark's location
    is the *call site* --- a line in the caller. So the one remark that says
    what the inliner decided about a marked function is never found by a
    lookup around that function's own definition: on hintbench the k2 site's
    remark block is `std` backtrace noise and the decisive
    `cost=870, threshold=787` does not appear in the state at all
    (`docs/experiments/hintbench/jev-oneshot-v3.md` section 5).

    Parsing by callee name fixes that without any new machinery: the remark
    names the callee's linkage symbol, and the dump gives the mark's linkage
    symbols, so the two join exactly.
    """

    def __init__(self, log_path):
        self.by_callee = {}
        if not log_path or not os.path.isfile(log_path):
            return
        # A build log holds the pre-link compilation and the LTO one, so the
        # same decision can be printed twice, byte for byte. Dedup on the
        # whole line, as `RemarkBook` does, or a call site is counted twice.
        # Checked: no line of hintbench's eight marks is affected, and its
        # counts reproduce EXPECTED section 2a either way.
        seen = set()
        for raw in open(log_path, errors="replace"):
            line = raw.strip()
            if "inlined into" not in line:
                continue
            if line in seen:
                continue
            seen.add(line)
            m = NOT_INLINED_RE.match(line)
            if m:
                why = m.group("why")
                cost = COST_RE.search(why)
                thr = THRESHOLD_RE.search(why)
                reason = why.split(" (cost=")[0].strip()
                if ": " in why:
                    reason = why.rsplit(": ", 1)[1].strip()
                self._add(m, {"inlined": False,
                              "cost": int(cost.group(1)) if cost else None,
                              "threshold": int(thr.group(1)) if thr else None,
                              "too_costly": "too costly" in why,
                              "reason": reason})
                continue
            m = INLINED_RE.match(line)
            if m:
                paren = m.group("paren") or ""
                cost = COST_RE.search(paren)
                thr = THRESHOLD_RE.search(paren)
                always = ("cost=always" in paren
                          or "always inline attribute" in (m.group("rest") or ""))
                self._add(m, {"inlined": True,
                              "cost": int(cost.group(1)) if cost else None,
                              "threshold": int(thr.group(1)) if thr else None,
                              "always": always, "reason": None})

    def _add(self, m, rec):
        rec["callee"] = m.group("callee")
        rec["caller"] = m.group("caller")
        rec["loc"] = "%s:%s:%s" % (os.path.basename(m.group("file")),
                                   m.group("line"), m.group("col"))
        self.by_callee.setdefault(rec["callee"], []).append(rec)

    def outcomes(self, linkages):
        """Every inline decision the log records about these callees."""
        out = []
        for name in linkages or []:
            out += self.by_callee.get(name, [])
        return out


def _n_call_sites(n):
    return "1 call site" if n == 1 else "%d call sites" % n


def _tally(keys):
    """`a at 7 of them, b` --- the distinct readings, commonest first."""
    counts = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    return ", ".join("%s at %d of them" % (k, n) if n > 1 else k
                     for k, n in sorted(counts.items(),
                                        key=lambda kv: (-kv[1], kv[0])))


def inline_outcome_line(linkages, book):
    """The verdict line that replaces v3's `inline budget: ... fits`.

    v3 divided the body's instruction count by `-inline-threshold=225` and
    concluded "the body fits inside that budget". At k2 that sentence is the
    opposite of the truth --- LLVM measured cost 870 against threshold 787
    and declined --- because the instruction count is not an InlineCost and
    225 is not the threshold this recipe uses. The inliner already wrote
    down what it decided; this line quotes it instead of estimating it.
    """
    rows = book.outcomes(linkages) if book else []
    if not rows:
        return ("inliner outcomes for this function in the baseline: the "
                "build log records no inline decision naming this symbol, so "
                "the baseline neither inlined nor declined it at any call "
                "site the remarks cover")
    ins = [r for r in rows if r["inlined"]]
    dec = [r for r in rows if not r["inlined"]]
    parts = []
    if ins:
        parts.append("%s inlined (%s)"
                     % (_n_call_sites(len(ins)),
                        _tally(("always inline attribute at the call site"
                                if r.get("always") else
                                "cost=%s vs threshold=%s"
                                % (r["cost"], r["threshold"])) for r in ins)))
    else:
        parts.append("0 call sites inlined")
    if not dec:
        parts.append("0 declined")
    else:
        costly = [r for r in dec if r["too_costly"]]
        other = [r for r in dec if not r["too_costly"]]
        if costly:
            parts.append("%s declined as too costly (%s)"
                         % (_n_call_sites(len(costly)),
                            _tally("cost=%s > threshold=%s"
                                   % (r["cost"], r["threshold"])
                                   for r in costly)))
        if other:
            parts.append("%s declined for another reason (%s)"
                         % (_n_call_sites(len(other)),
                            _tally(r["reason"] or "unrecorded"
                                   for r in other)))
    return ("inliner outcomes for this function in the baseline, read off "
            "LLVM's own inline remarks by callee symbol: %s. (Each such "
            "remark is located at the *caller's* line, which is why they are "
            "not in the remark block above.)" % "; ".join(parts))


# ---------------------------------------------------------------------------
# sites.json produced outside this driver
# ---------------------------------------------------------------------------

def as_share(x):
    """A percentage as a float, from 29.29, "29.29", "29.29%" or None."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"-?\d+(?:\.\d+)?", str(x))
    return float(m.group(0)) if m else None


def load_sidecar(path):
    """Optional extra facts about the marks, produced by the marking step.

    Written against `targets/jaq/sites.json` as
    `scripts/jaq_sites_report.py` emits it:

        marks[]   {mark, matched, functions[], n_sites_owned, ...}
        sites[]   the plugin's `loop_in_mark` records plus stage, module_id,
                  key_copies, key_unique
        oracle.selected_keys_topk_per_mark / selected_keys_top20_overall
                  the mechanical caps on how many loop sites a sweep covers

    Everything is optional and everything unknown is ignored, so a differently
    shaped file degrades to "no extra facts" instead of failing. A few
    alternative spellings are accepted (`fn`/`name` for a mark, `share`/
    `profile_share`/`share_pct` for a share) and a plugin report directory is
    accepted in place of the file.
    """
    if not path:
        return {"marks": {}, "sites": {}, "caps": {}, "site_allow": set(),
                "raw": {}}
    docs = []
    if os.path.isdir(path):
        docs = [rep for _, rep in plugin_report.load(path)]
    else:
        docs = [json.load(open(path))]

    marks, sites, caps, allow = {}, {}, {}, set()
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        caps.update(doc.get("search") or doc.get("caps") or {})
        oracle = doc.get("oracle") or {}
        for field in ("selected_keys_topk_per_mark",
                      "selected_keys_top20_overall", "site_keys"):
            if field == "selected_keys_top20_overall" and allow:
                continue                       # the per-mark cap wins
            allow |= set(oracle.get(field) or (doc.get("search") or {}).get(field)
                         or [])
        rows = doc.get("marks") or doc.get("functions") or []
        if isinstance(rows, dict):
            rows = [dict(v, mark=k) for k, v in rows.items()]
        for r in rows:
            if not isinstance(r, dict):
                continue
            name = r.get("mark") or r.get("fn") or r.get("name") or r.get("demangled")
            if not name:
                continue
            cur = marks.setdefault(name, {})
            for src, dst in (("share", "share"), ("profile_share", "share"),
                             ("share_pct", "share"), ("reach", "reach"),
                             ("file", "file"), ("line", "line"),
                             ("insns", "insns"), ("notes", "notes")):
                if r.get(src) is not None and dst not in cur:
                    cur[dst] = (as_share(r[src]) if dst in ("share", "reach")
                                else r[src])
        for r in doc.get("sites") or []:
            if not isinstance(r, dict):
                continue
            ident = r.get("site_id") or r.get("key")
            if ident:
                sites[ident] = r
    return {"marks": marks, "sites": sites, "caps": caps, "site_allow": allow,
            "raw": docs[0] if len(docs) == 1 and isinstance(docs[0], dict)
                   else {}}


MARK_SHARE_RE = re.compile(r"\bshare\s+(\d+(?:\.\d+)?)%")
MARK_REACH_RE = re.compile(r"\breach\s+(\d+(?:\.\d+)?)%")


def shares_from_marks_file(path):
    """{mark: {share, reach}} from the comment block above each mark.

    targets/jaq/jev-marks.txt carries the profile numbers of
    targets/jaq/jev-marks.rationale.md in the comment that introduces each
    mark ("# share 29.29%, reach 29.29% (...)"). Reading them here is what
    puts a profile share in the state without a second source of truth.
    """
    out, block = {}, []
    if not path or not os.path.isfile(path):
        return out
    for line in open(path):
        t = line.strip()
        if not t:
            block = []
        elif t.startswith("#"):
            block.append(t)
        else:
            text = " ".join(block)
            sh, re_ = MARK_SHARE_RE.search(text), MARK_REACH_RE.search(text)
            if sh or re_:
                out[t] = {"share": float(sh.group(1)) if sh else None,
                          "reach": float(re_.group(1)) if re_ else None}
            block = []
    return out


# ---------------------------------------------------------------------------
# items: one question each
# ---------------------------------------------------------------------------

def registry_roots(lockfile, wanted):
    """Crate directories in ~/.cargo/registry for the named dependencies.

    DWARF records a registry crate's files by a path relative to that crate
    (`src/raw/mod.rs`), so the crate directory has to be in the search roots
    for such a path to resolve at all. Cargo.lock pins which version, so
    there is no guessing between the five hashbrown copies on this machine.
    """
    out = []
    if not (lockfile and os.path.isfile(lockfile)):
        return out
    name = ver = None
    pairs = []
    for line in open(lockfile):
        line = line.strip()
        if line.startswith("name = "):
            name = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("version = "):
            ver = line.split("=", 1)[1].strip().strip('"')
            if name:
                pairs.append((name, ver))
                name = None
    low = {w.lower().replace("_", "-") for w in wanted}
    for n, v in pairs:
        if n.lower().replace("_", "-") not in low:
            continue
        out += sorted(glob.glob(os.path.expanduser(
            "~/.cargo/registry/src/*/%s-%s" % (n, v))))
    return out


class DwarfDecl:
    """linkage name -> (file, line) of its definition, out of the binary.

    The plugin's function table has no source location, and searching the
    tree for `fn <name>` guesses. The baseline is built with
    `-Cdebuginfo=1` and `strip=none` (SPEC.ja.md 3) precisely so that this
    kind of question has an exact answer: `nm` for the address, `addr2line`
    for the file and line DWARF records for it. A function that fat LTO
    inlined everywhere has no symbol left and gets no answer here; the
    caller falls back.
    """

    def __init__(self, binary):
        self.binary = binary
        self.addr = None

    def _load(self):
        if self.addr is not None:
            return
        self.addr = {}
        if not (self.binary and os.path.isfile(self.binary)):
            return
        p = subprocess.run(["nm", "--defined-only", self.binary],
                           text=True, capture_output=True)
        for line in p.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1].lower() in ("t", "w"):
                self.addr.setdefault(parts[2], parts[0])

    def locate(self, linkages, limit=8):
        """The (file, line) most of the given symbols agree on."""
        self._load()
        want = [(n, self.addr[n]) for n in linkages if n in self.addr][:limit]
        if not want:
            return (None, None)
        p = subprocess.run(["addr2line", "-e", self.binary] +
                           ["0x" + a for _, a in want],
                           text=True, capture_output=True)
        best = {}
        for line in p.stdout.splitlines():
            f, _, ln = line.strip().rpartition(":")
            ln = ln.split(" ")[0]
            if not f or f == "??" or not ln.isdigit():
                continue
            best.setdefault(f, []).append(int(ln))
        if not best:
            return (None, None)
        f = max(best, key=lambda k: len(best[k]))
        return (f, min(best[f]))


def crate_roots_of(sites):
    """Crate directories of the source files a dump named, for the search.

    Ascends from each existing leaf file to the nearest directory holding a
    Cargo.toml, so a dependency's sources can be searched without walking
    the whole cargo registry.
    """
    out = []
    seen = set()
    for s in sites:
        f = (s.get("leaf") or {}).get("file")
        if not f or not os.path.isabs(f) or not os.path.isfile(f):
            continue
        d = os.path.dirname(f)
        for _ in range(6):
            if os.path.isfile(os.path.join(d, "Cargo.toml")):
                if d not in seen:
                    seen.add(d)
                    out.append(d)
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return out


class Item:
    """One site: a marked function, a loop, or the `__build__` pseudo-site."""

    def __init__(self, kind, ident, label, meta):
        self.kind = kind          # "fn" | "loop" | "build"
        self.id = ident           # stable across rounds
        self.label = label        # short human string
        self.meta = meta          # everything the state section prints
        self.qname = None         # assigned per request


def is_inner_item(demangled, mark):
    """Is this function an item defined *inside* the mark, not the mark?

    The plugin matches a mark against the full demangled name and accepts
    `mark::...` continuations, which is what makes a loop inside a closure a
    site of the marked function (plugin/README.md "Marks file"). For a
    function *attribute* the two have to be told apart, and the only honest
    signal is what follows the mark:

        <mark>                       the function itself
        <mark>::<...>                a monomorphization of it
        <mark>::<...>::{closure#0}   an item defined inside a
                                     monomorphization of it        -> inner
        <mark>::{closure#0}          an item defined inside it      -> inner
        <mark>::helper                       likewise               -> inner

    The naive test "does the name contain `::{`" is wrong: a
    monomorphization's generic arguments routinely contain a closure path
    (`...::seq::<hifijson::Error, jaq_json::read::ws_tk<...{closure#1}>>`),
    and on jaq it misfiled six of fifteen marks as inner items.

    Looking at the single character after the mark is wrong the other way,
    and that is what this function did until decision 80 (c): for a
    **generic** mark it saw the `<` of the generic arguments and called
    `read::parse::<SliceLexer>::{closure#0}` a monomorphization, so one
    Choice about `read::parse` put its attribute on every closure the
    function defines --- 103 of the 138 entries a full phase-A plan carried
    on jaq (results.md "Oracle A (jaq)" 112). The generic arguments are a
    balanced `<...>` group, so they can be skipped and the question asked
    of what follows *them*: another `::` segment is an inner item, nothing
    is the function itself.
    """
    if not demangled.startswith(mark):
        return False
    rest = demangled[len(mark):]
    while rest.startswith("::<"):
        depth, i = 0, rest.index("<")
        while i < len(rest):
            if rest[i] == "<":
                depth += 1
            elif rest[i] == ">":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            return False        # unbalanced: not a shape this can judge
        rest = rest[i + 1:]
    return rest.startswith("::")


def fn_items(by_mark, marks, sidecar, scope="own"):
    items = []
    for mark in marks:
        fns = by_mark.get(mark, [])
        if not fns:
            continue
        info = sidecar["marks"].get(mark, {})
        # The plugin's mark rule deliberately reaches inner items so that a
        # loop inside a closure is attributed to the marked function
        # (plugin/README.md "Marks file"). A function *attribute* must not
        # follow it there: `inline(never)` on a mark is a statement about
        # that function, and putting `noinline` on every closure it defines
        # would also stop LLVM inlining the closures into the mark's own
        # loops. So the attribute goes to the mark's own functions --- every
        # monomorphization, decision 61(c) --- and the inner items are
        # excluded and recorded.
        if scope == "all":
            own, inner = list(fns), []
        else:
            own = [f for f in fns
                   if not is_inner_item(f.get("demangled") or "", mark)]
            inner = sorted(f["linkage"] for f in fns
                           if is_inner_item(f.get("demangled") or "", mark))
        if not own:
            continue
        meta = {
            "mark": mark,
            "linkages": [f["linkage"] for f in own],
            "excluded_inner": inner,
            "demangled": sorted({f.get("demangled", "") for f in own}),
            "inst_count": sum(f.get("inst_count") or 0 for f in own),
            "self_loops": sum(f.get("self_loops") or 0 for f in own),
            "entry_count": max([f.get("entry_count") or 0 for f in own] + [0]),
            "attributes": sorted({f.get("attributes", "") for f in own}) or [""],
            "share": info.get("share"),
            "reach": info.get("reach"),
            "file": info.get("file"),
            "line": info.get("line"),
            "notes": info.get("notes"),
        }
        items.append(Item("fn", "fn:" + mark, mark, meta))
    # `share` is the mark's own post-LTO symbol, `reach` adds the code
    # inlined into it. A mark can have only the second (jev-marks.txt gives
    # `reach` alone for a function that is inlined everywhere), so the order
    # falls back to it.
    items.sort(key=lambda i: (-(i.meta["share"] or i.meta["reach"] or 0),
                              i.label))
    return items


def loop_items(sites, sidecar):
    items, used = [], {}
    for s in sites:
        ident = site_id_of(s)
        n = used.get(ident, 0)
        used[ident] = n + 1
        if n:
            ident = "%s~%d" % (ident, n + 1)
        info = sidecar["sites"].get(s["key"]) or sidecar["sites"].get(ident) or {}
        leaf = s.get("leaf") or {}
        meta = dict(s)
        meta["site_id"] = ident
        # The plugin's dump record carries no `key_copies`: it is added by
        # scripts/jaq_sites_report.py when it writes sites.json. It is put
        # under its own name so that the v1 state section, which looks for
        # `key_copies` in the dump record and has therefore never found one,
        # keeps rendering exactly what Experiment 3 sent.
        meta["key_copies_sidecar"] = info.get("key_copies")
        meta["notes"] = info.get("notes")
        meta["candidates"] = info.get("candidates")
        meta["leaf_file"] = leaf.get("file")
        meta["leaf_line"] = leaf.get("line")
        # The column is what makes the leaf location a *location*: two loops
        # can begin on one line. It is recorded from v3 on (decision 83) and
        # nothing before v3 reads it, so the v1/v2 state does not move.
        meta["leaf_col"] = leaf.get("col")
        label = "%s @ %s:%s" % (s.get("mark", "?"),
                                os.path.basename(leaf.get("file", "?")),
                                leaf.get("line", "?"))
        items.append(Item("loop", ident, label, meta))
    return items


def build_item(knobs):
    return Item("build", V.BUILD_SITE_ID, "build-wide compiler setting",
                {"knobs": list(knobs)})


def candidates_of(item, knobs):
    cands = V.candidates_for(item.kind, knobs)
    allow = item.meta.get("candidates")
    if allow:
        # A mechanical cap from sites.json: keep KEEP_DEFAULT plus whatever it
        # allows, in the frozen order.
        allow = set(allow) | {V.KEEP_DEFAULT}
        cands = {k: v for k, v in cands.items() if k in allow}
    return cands


# ---------------------------------------------------------------------------
# the frozen state format
# ---------------------------------------------------------------------------

STATE_PREAMBLE = """\
# jev-opt hint search --- state format {fmt}, vocabulary {vocab}

## What is being decided

A Rust program is compiled with one frozen recipe. The only thing that varies
between builds is a set of optimisation hints attached to named functions and
to the loops inside them; no source file is ever edited. You are shown one
site per question and you choose one hint for it from a fixed list. All the
questions in this request are answered independently and they all take effect
in the same build, which is then measured as a whole.

Picking KEEP_DEFAULT everywhere reproduces the baseline exactly. A hint is
worth choosing only if it is likely to make the WHOLE PROGRAM measurably
faster: the measurement is end-to-end wall time over the case set below, the
noise floor of this machine is about 1% aggregated, and nothing smaller than
{mde} counts as a change. Hints that change the program's output are
rejected regardless of speed.

## The build every arm shares

target        {target}
binary        {binary}
toolchain     rustc 1.100.0-nightly (bba531001), LLVM 23.1.1
machine       AMD Ryzen 9 5950X (znver3, AVX2, no AVX-512), one physical core
recipe        -Copt-level=3, fat LTO, 1 codegen unit, -Cdebuginfo=1,
              -Ctarget-cpu=native, PGO (-Cprofile-use, one shared profile),
              -Cllvm-args=-hints-allow-reordering=false
measurement   {ncases} case(s): {cases}
              {reps} interleaved repetitions, shuffled label order, paired
              bootstrap 95% CI, speed ratio = baseline time / this build's time
              (greater than 1 is faster)
source        {source_comments}

## Where the hints are applied

Function attributes are applied at PipelineStartEP, before any inlining.
Loop metadata is applied at VectorizerStartEP, after inlining and loop
canonicalisation and immediately before LoopVectorize, so a loop hint acts on
the loop as it exists after the function attributes of this same round have
already taken effect.

## The marked functions of this program

{marks}

## Results of the previous rounds

{history}
"""

STATE_SITES_HEADER = """
## The sites in this request ({n} of them)

Each section below is named after its question.
"""


def fmt_share(x):
    return "unknown" if x is None else ("%.2f%%" % float(x))


SOURCE_COMMENTS_TEXT = {
    "strip": ("source_comments: strip --- every comment and doc attribute is\n"
              "              removed from the source excerpts below before "
              "they are\n"
              "              quoted, and a line that held nothing else is "
              "shown as\n"
              "              `%s`. Line numbers are the file's\n"
              "              own and are unchanged." % COMMENT_MARKER),
    "keep": ("source_comments: keep --- the source excerpts below are quoted\n"
             "              verbatim from the file, comments included."),
}


def state_header(ctx, n_sites):
    marks = []
    for it in ctx["fn_items"]:
        marks.append("  %-60s  profile share %s, %d loop site(s)"
                     % (it.label[:60],
                        fmt_share(it.meta["share"] if it.meta["share"]
                                  is not None else it.meta["reach"]),
                        ctx["loops_by_mark"].get(it.meta["mark"], 0)))
    for mark in sorted(ctx["loops_by_mark"]):
        if mark not in {i.meta["mark"] for i in ctx["fn_items"]}:
            marks.append("  %-60s  no function of its own is left in the "
                         "program (it was inlined away); %d loop site(s)"
                         % (mark[:60], ctx["loops_by_mark"][mark]))
    hist = render_history(ctx["history"], evidence_fixes(ctx))
    head = STATE_PREAMBLE.format(
        fmt=STATE_FORMAT_VERSION, vocab=V.VOCAB_VERSION,
        target=ctx["target"], binary=ctx["binary"],
        mde=ctx["mde_text"], ncases=len(ctx["cases"]),
        cases=", ".join(ctx["cases"]), reps=ctx["reps"],
        marks="\n".join(marks) or "  (none resolved)",
        source_comments=SOURCE_COMMENTS_TEXT[ctx.get("source_comments",
                                                     "strip")],
        history=hist)
    if ctx.get("state_v2"):
        # Exactly the two whole-state changes the study's W7 makes: the V2
        # wording of what is being decided ("no change ... neither preferred
        # nor discouraged" instead of "picking KEEP_DEFAULT everywhere
        # reproduces the baseline"), and the platform block. Everything else
        # --- the marks table, the round history, the per-site sections ---
        # is the frozen v1 material, which is what V3 measured the cost of
        # removing.
        head = DECIDING_RE.sub(lambda _m: STATE_V2_DECIDING, head, count=1)
        head = head.replace(
            "## Where the hints are applied",
            ctx.get("platform", "") + "\n## Where the hints are applied", 1)
    return head + STATE_SITES_HEADER.format(n=n_sites)


HISTORY_OUTCOMES = {
    "measured": "measured",
    "identical_to_baseline": ("this build was instruction-for-instruction the "
                              "baseline, so it was not timed"),
    "output-mismatch": "the program printed something else; rejected",
    "apply-incomplete": "a hint in the plan did not take effect; rejected",
    "measure-failed": "the timing batch failed",
    "build-a-failed": "the build failed",
    "build-b-failed": "the build failed",
    "basis-mismatch": "the plan did not match the attributes it was built on",
}


def history_outcome(h):
    return HISTORY_OUTCOMES.get(h.get("status") or "", h.get("status") or "-")


def render_history(history, plan_rule=False):
    if not history:
        return ("  This is round 1: nothing has been measured yet. The "
                "baseline is the build in which every site is KEEP_DEFAULT.")
    out = ["  | round | correct | aggregate speed ratio | 95% CI | outcome "
           "| accepted |",
           "  |---|---|---|---|---|---|"]
    for h in history:
        ci = ("[%.4f, %.4f]" % tuple(h["ci95"])) if h.get("ci95") else "-"
        ratio = ("%.4f" % h["ratio"]) if h.get("ratio") is not None else "-"
        out.append("  | %d | %s | %s | %s | %s | %s |"
                   % (h["round"], "yes" if h["correct"] else "NO",
                      ratio, ci, history_outcome(h),
                      "yes" if h["accepted"] else "no"))
    names = []
    for h in history:
        for w in (h.get("per_workload") or {}):
            if w not in names:
                names.append(w)
    if names:
        out.append("")
        out.append("  The same rounds, per case. The aggregate above is the "
                   "geometric mean over all the cases, so a large effect on "
                   "one case is a small number there; this table is where a "
                   "single hint's effect is visible. A ratio greater than 1 "
                   "is faster than the baseline on that case, and `*` marks "
                   "a ratio whose own 95% CI excludes 1.")
        out.append("")
        out.append("  | round | " + " | ".join(names) + " |")
        out.append("  |---|" + "---|" * len(names))
        for h in history:
            pw = h.get("per_workload") or {}
            cells = []
            for w in names:
                r = pw.get(w)
                if not r:
                    cells.append("-")
                    continue
                ci = r.get("ci95") or [None, None]
                star = "*" if (ci[0] is not None
                               and (ci[0] > 1.0 or ci[1] < 1.0)) else " "
                cells.append("%.4f%s" % (r["ratio"], star))
            out.append("  | %d | %s |" % (h["round"], " | ".join(cells)))
    out.append("")
    if plan_rule:
        out.append("  A round is accepted as the new best only if its plan "
                   "differs from the best plan so far AND the lower end of "
                   "its 95% CI is above that plan's point estimate. A round "
                   "that rebuilds the plan already held is the same binary; "
                   "it is recorded as one more independent batch on it and "
                   "cannot replace it, so a row above that repeats an "
                   "earlier round's answers is telling you how much this "
                   "machine moves between batches, not that the plan got "
                   "better.")
    else:
        out.append("  A round is accepted as the new best only if the lower "
                   "end of its 95% CI is above the best point estimate so "
                   "far.")
    return "\n".join(out)


def sites_sharing_case(site_id, all_site_ids, cases):
    """Other sites whose own timing case is this site's own timing case.

    Decision 89 (2): hintbench times `k4_count_bytes` and the loop inside it
    on one workload, so after a round in which the loop cost 42% the function
    site's own history line said 42% too. The readout cannot separate them
    and the state has to say so rather than let each site be read as the sole
    cause of what its case did.
    """
    own = own_workload_of(site_id, list(cases))
    if not own:
        return []
    return [sid for sid in all_site_ids
            if sid != site_id and own_workload_of(sid, list(cases)) == own]


def shared_case_line(site_id, ctx):
    others = sites_sharing_case(site_id, ctx.get("all_site_ids") or [],
                                ctx.get("cases") or [])
    if not others:
        return None
    own = own_workload_of(site_id, list(ctx.get("cases") or []))
    return ("  this site's own timing case, %s, is also timed by %s: the "
            "case's ratio is the ratio of a build in which every one of them "
            "was answered, so a change in it cannot be attributed to one of "
            "them alone."
            % (own, ", ".join("`%s`" % o for o in others)))


def hint_cross_case(history, site_id, pick, own):
    """What one hint measured on the cases that are NOT this site's own.

    Decision 89 (3): a per-kernel readout answers "did the hint help where it
    was applied" and is silent about what it cost elsewhere. `inline(always)`
    at `k6_hot_loop` is 1.0011 on k6 --- free, by its own case --- and 0.972
    on k3, which is where the accepted plan of Experiment 4 lost most of what
    it did not win. Returns (rounds counted, [(case, geometric mean ratio,
    every round's own CI excluded 1), ...]) ordered by distance from 1.
    """
    acc, n = {}, 0
    for h in history:
        if h["choices"].get(site_id) != pick:
            continue
        pw = h.get("per_workload") or {}
        if not pw:
            continue
        n += 1
        for w, r in pw.items():
            if w == own or not r or not r.get("ratio"):
                continue
            a = acc.setdefault(w, {"logs": [], "excl": 0})
            a["logs"].append(math.log(float(r["ratio"])))
            ci = r.get("ci95") or [None, None]
            if ci[0] is not None and (ci[0] > 1.0 or ci[1] < 1.0):
                a["excl"] += 1
    rows = [(w, math.exp(sum(a["logs"]) / len(a["logs"])),
             a["excl"] == len(a["logs"]))
            for w, a in acc.items()]
    rows.sort(key=lambda r: -abs(math.log(r[1])))
    return n, rows


def site_history_lines(history, site_id, cases=(), cross_case=False):
    """What earlier rounds chose here, and what was measured when they did.

    Experiment 4: the whole-build ratio alone cannot say whether a hint at
    THIS site helped --- on a target with one case per site it is the eight-
    way geometric mean, in which a 40% loss at one site is 6%. Where the
    site has a case of its own (`own_workload_of`) the line quotes that
    case's ratio and 95% CI as well, and says whether the round was accepted.
    Where it does not, the line is what it always was.

    Decision 89 (c) adds one line per distinct hint tried here: the same
    hint's ratio on the cases this site is NOT timed by, which is the only
    place the state can show what a hint costs somewhere else.
    """
    own = own_workload_of(site_id, list(cases))
    rows = []
    for h in history:
        pick = h["choices"].get(site_id)
        if not pick:
            continue
        ratio = ("%.4f" % h["ratio"]) if h.get("ratio") is not None else "n/a"
        detail = ""
        pw = (h.get("per_workload") or {}).get(own) if own else None
        if pw:
            ci = pw.get("ci95") or [None, None]
            detail = ("; on case %s, the one case this site's own code is "
                      "timed by, %.4f" % (own, pw["ratio"]))
            if ci[0] is not None:
                detail += " with 95%% CI [%.4f, %.4f]" % (ci[0], ci[1])
        elif own and h.get("status") == "identical_to_baseline":
            detail = ("; that build was instruction-for-instruction the "
                      "baseline, so nothing was timed")
        rows.append("    round %d: %s -> whole-build ratio %s%s%s (%s)"
                    % (h["round"], V.spec_spelling_safe(pick), ratio, detail,
                       "" if h["correct"] else " (REJECTED: output changed)",
                       "accepted as the new best" if h.get("accepted")
                       else "not accepted"))
    if not rows:
        return "    (this site was not asked about in an earlier round)"
    if cross_case:
        seen = []
        for h in history:
            pick = h["choices"].get(site_id)
            if pick and pick != V.KEEP_DEFAULT and pick not in seen:
                seen.append(pick)
        for pick in seen:
            n, cells = hint_cross_case(history, site_id, pick, own)
            if not cells:
                continue
            rows.append(
                "    what %s at this site measured on the OTHER cases, over "
                "the %d round(s) it was in the plan (a hint can be free on "
                "the case its own site is timed by and still cost time in a "
                "kernel this site has nothing to do with; `*` marks a case "
                "whose own 95%% CI excluded 1 in every one of those rounds): "
                "%s"
                % (V.spec_spelling_safe(pick), n,
                   ", ".join("%s %.4f%s" % (w, r, "*" if e else "")
                             for w, r, e in cells)))
    return "\n".join(rows)


def remark_text(text, ctx):
    """A remark line as the state quotes it.

    Remark prose almost never carries source text, but when it does (a remark
    that echoes an expression) it would carry the comment with it, so the same
    strip is applied under `--source-comments strip`.
    """
    if ctx.get("source_comments", "strip") != "strip":
        return text
    return strip_comments_in_text(text)


def state_section(item, ctx):
    """The frozen per-site section. One of these per question."""
    m = item.meta
    out = ["### %s" % item.qname]
    if item.kind == "fn":
        out.append("")
        out.append("site kind      one marked function (function attribute)")
        out.append("function       %s" % item.label)
        if len(m["linkages"]) > 1:
            out.append("               %d monomorphizations of it exist in "
                       "this build; the attribute goes on all of them"
                       % len(m["linkages"]))
        if m.get("excluded_inner"):
            out.append("               (%d closure(s) defined inside it keep "
                       "their own attributes)" % len(m["excluded_inner"]))
        if m["share"] is not None and evidence_fixes(ctx) \
                and ctx.get("share_placeholder"):
            out.append("profile share  not measured on this target: the site "
                       "list carries the same value (%s) at every mark, by "
                       "construction rather than from a profile"
                       % fmt_share(m["share"]))
        elif m["share"] is not None:
            out.append("profile share  %s of the program's user cycles%s"
                       % (fmt_share(m["share"]),
                          "" if m["reach"] is None
                          else (", %s counting the code inlined into it"
                                % fmt_share(m["reach"]))))
        elif m["reach"] is not None:
            out.append("profile share  %s of the program's user cycles, "
                       "counting the code inlined into it wherever LTO put "
                       "it (it has no hot symbol of its own)"
                       % fmt_share(m["reach"]))
        else:
            out.append("profile share  unknown")
        if ctx.get("state_v2"):
            # `self_loops` is summed from a dump field the plugin does not
            # emit (it writes `n_loops`), so the v1 line has always printed
            # 0 here. v2 prints the mark's `loop_in_mark` site count from
            # the dump instead --- the same number the marks table above and
            # the verdict block use, so one request cannot contradict
            # itself. The v1 line is left exactly as Experiment 3 sent it.
            out.append("size after LTO %d LLVM instructions, %d loop site(s) "
                       "inside it"
                       % (m["inst_count"],
                          ctx["loops_by_mark"].get(m["mark"], 0)))
        else:
            out.append("size after LTO %d LLVM instructions, %d loop(s) "
                       "inside it" % (m["inst_count"], m["self_loops"]))
        attrs = " | ".join(a for a in m["attributes"] if a) or "(none)"
        out.append("attributes now %s%s"
                   % (attrs, "  (the distinct sets over all of them)"
                      if len(m["linkages"]) > 1 else ""))
        if m.get("notes"):
            out.append("note           %s" % m["notes"])
        src_file, src_line = m.get("file"), m.get("line")
        if not src_file:
            src_file, src_line = ctx["fn_source"].get(item.id, (None, None))
        excerpt = ctx["source"].excerpt(src_file, src_line) if src_file else None
        out.append("")
        out.append("source:")
        out.append(excerpt if excerpt else
                   "  (not available: this function's source file is not in "
                   "the vendored tree)")
        rem = ctx["remarks"].near(src_file, src_line) if src_file else []
        out.append("")
        out.append("what LLVM said about this region in the baseline build:")
        out.append("\n".join("  %s:%d: %s"
                             % (os.path.basename(src_file), ln, remark_text(t, ctx))
                             for ln, t in rem)
                   or "  (no remarks at this location)")
        if evidence_fixes(ctx):
            # The block above is a window around the *definition*, and an
            # inline remark is located at the *call site*, so the one remark
            # that says what the inliner did with this function is never in
            # it. Decision 83: quote them separately, matched by callee
            # symbol rather than by line.
            rows = (ctx["inlines"].outcomes(m["linkages"])
                    if ctx.get("inlines") else [])
            out.append("")
            out.append("what LLVM decided about calls to this function "
                       "(matched by callee symbol; each line is located at "
                       "the caller, which is why none of them is in the "
                       "block above):")
            if not rows:
                out.append("  (the build log records no inline decision "
                           "naming this symbol)")
            else:
                seen, shown = set(), []
                for r in rows[:12]:
                    if r["inlined"]:
                        t = ("inlined, %s"
                             % ("always inline attribute at the call site"
                                if r.get("always")
                                else "cost=%s, threshold=%s"
                                % (r["cost"], r["threshold"])))
                    else:
                        t = ("not inlined: %s (cost=%s, threshold=%s)"
                             % (r["reason"], r["cost"], r["threshold"]))
                    line = "  %s: %s" % (r["loc"], t)
                    if line in seen:
                        continue
                    seen.add(line)
                    shown.append(line)
                out += shown
                if len(rows) > 12:
                    out.append("  (%d further call sites not shown)"
                               % (len(rows) - 12))
    elif item.kind == "loop":
        trip = m.get("trip_count")
        out.append("")
        out.append("site kind      one loop inside a marked function")
        out.append("marked function %s" % m.get("mark"))
        out.append("owner after inlining  %s" % m.get("owner_fn_demangled"))
        out.append("location       %s:%s (loop nesting depth %s)"
                   % (os.path.basename(m.get("leaf_file") or "?"),
                      m.get("leaf_line"), m.get("depth")))
        if evidence_fixes(ctx) and ctx.get("share_placeholder"):
            out.append("profile share of the marked function  not measured "
                       "on this target (one uniform value for every mark)")
        else:
            out.append("profile share of the marked function  %s"
                       % fmt_share(ctx["share_by_mark"].get(m.get("mark"))))
        out.append("average trip count (from the PGO profile)  %s"
                   % ("unknown" if trip is None else "%.0f" % trip))
        out.append("loop body      %s LLVM instructions, calls inside: %s, "
                   "floating-point reduction: %s"
                   % (m.get("body_inst_count"),
                      "yes" if m.get("has_calls") else "no",
                      "yes" if m.get("has_fp_reduction") else "no"))
        if evidence_fixes(ctx):
            # The dump tests `llvm.loop.isvectorized` at VectorizerStartEP,
            # i.e. before LoopVectorize has run in this pipeline
            # (`plugin/jev/jev.cpp:1127`), so `no` is what every loop says
            # and it is not a statement that LLVM leaves the loop scalar.
            # The v3 line read as one. Decision 83.
            out.append("carries `llvm.loop.isvectorized` metadata already at "
                       "the point the hint is attached: %s (the hint is "
                       "attached before LoopVectorize runs, so `no` is the "
                       "normal answer and does not mean the loop stays "
                       "scalar)"
                       % ("yes" if m.get("already_vectorized") else "no"))
        else:
            out.append("already vectorized when the hint is attached: %s"
                       % ("yes" if m.get("already_vectorized") else "no"))
        copies = m.get("key_copies")
        if ctx.get("state_v2") and not copies:
            # As in `loop_items`: the dump record has no `key_copies`, so
            # under v1 this line has never fired. v2 uses the number
            # sites.json recorded for the same key when there is one.
            copies = m.get("key_copies_sidecar")
        if (copies or 1) > 1:
            out.append("this site key resolves to %d loops in the build; a "
                       "hint on it is attached to all of them and cannot be "
                       "given to one of them alone" % copies)
        others = [x for x in (m.get("marks_in_chain") or [])
                  if x != m.get("mark")]
        if others:
            out.append("other marked functions on this loop's inline chain: "
                       "%s" % ", ".join(others))
        out.append("function attributes this round already applied: %s"
                   % (ctx["fn_choice_text"] or "none"))
        if m.get("notes"):
            out.append("note           %s" % m["notes"])
        fn_file, fn_line = ctx["fn_source"].get("fn:" + (m.get("mark") or ""),
                                                (None, None))
        fn_src = ctx["source"].excerpt(fn_file, fn_line) if fn_file else None
        out.append("")
        out.append("source of the marked function this loop belongs to:")
        out.append(fn_src if fn_src else
                   "  (not available: the source file is not in the vendored "
                   "tree)")
        leaf_src = ctx["source"].excerpt(m.get("leaf_file"), m.get("leaf_line"),
                                         ctx=20)
        if leaf_src and (not fn_file or os.path.basename(fn_file)
                         != os.path.basename(m.get("leaf_file") or "")):
            out.append("")
            out.append("source at the loop's innermost location (this is where "
                       "the loop ended up after inlining, often inside the "
                       "iterator machinery rather than in the marked "
                       "function):")
            out.append(leaf_src)
        if evidence_fixes(ctx):
            # Exactly this loop's leaf location, column included, and a
            # header that says how many loops write to it. A +/-10-line
            # window around `macros.rs:180` collects every `for &x in
            # slice` in the program. Decision 83.
            base = os.path.basename(m.get("leaf_file") or "?")
            texts = ctx["remarks"].at(m.get("leaf_file"), m.get("leaf_line"),
                                      m.get("leaf_col"))
            n_here = ctx["remarks"].n_loops_at(m.get("leaf_file"),
                                               m.get("leaf_line"),
                                               m.get("leaf_col"))
            out.append("")
            if n_here and n_here > 1:
                out.append("what LLVM said at %s:%s:%s in the baseline build "
                           "--- CAUTION: %d different loops of this program "
                           "were compiled at that one location, so the lines "
                           "below are their remarks pooled together and none "
                           "of them can be assigned to this loop:"
                           % (base, m.get("leaf_line"), m.get("leaf_col"),
                              n_here))
            else:
                out.append("what LLVM said at %s:%s:%s --- this loop's own "
                           "leaf location --- in the baseline build:"
                           % (base, m.get("leaf_line"), m.get("leaf_col")))
            out.append("\n".join("  %s:%s: %s"
                                 % (base, m.get("leaf_line"),
                                    remark_text(t, ctx))
                                 for t in texts)
                       or "  (no remarks at this location)")
        else:
            rem = ctx["remarks"].near(m.get("leaf_file"), m.get("leaf_line"),
                                      span=10)
            out.append("")
            out.append("what LLVM said about this region in the baseline "
                       "build:")
            out.append("\n".join("  %s:%d: %s"
                                 % (os.path.basename(m.get("leaf_file") or "?"),
                                    ln, remark_text(t, ctx))
                                 for ln, t in rem)
                       or "  (no remarks at this location)")
    else:
        out.append("")
        out.append("site kind      one compiler setting for the whole build")
        out.append("")
        out.append("  This is not a per-function decision: whatever is chosen "
                   "here applies to every function in the program, including "
                   "the ones nobody marked.")
    if evidence_fixes(ctx):
        # Decision 89 (d). Printed whether or not there is a history: it is a
        # property of the case set, and a round-1 request needs it as much as
        # a round-5 one.
        shared = shared_case_line(item.id, ctx)
        if shared:
            out.append("")
            out.append(shared)
    out.append("")
    out.append("  what earlier rounds chose here:")
    out.append(site_history_lines(ctx["history"], item.id,
                                  ctx.get("cases") or [],
                                  cross_case=evidence_fixes(ctx)))
    out.append("")
    return "\n".join(out)


def _spelling_safe(candidate):
    for kind in ("fn", "loop"):
        try:
            return V.spec_spelling(kind, candidate)
        except KeyError:
            continue
    return candidate


V.spec_spelling_safe = _spelling_safe


# ---------------------------------------------------------------------------
# state v2 (decision 73): the platform block and the mechanical verdict block
# ---------------------------------------------------------------------------
#
# The prompt study (docs/experiments/jev-prompt-study/, round 2) measured
# eighteen plus seven framings of this same state and found two things that
# move Jev's answer onto the reference picks, and one that has to be kept off
# the loop phase:
#
#   * the mechanical VERDICT BLOCK next to the question (idea A). It states
#     as a finished reading what the state already carries as numbers --- the
#     size class, the inline budget, the lanes arithmetic, the legality of
#     vectorising this loop. W1 chose `vectorize.width=16` at the one loop
#     with a mechanism in all three repeats; no round-1 framing ever did,
#     including the two that carried the register width and the trip count as
#     a table. Jev does not do the arithmetic; it acts on it once it is done.
#   * the APPLICABILITY CONDITIONS in the `criteria` descriptions (idea B),
#     which live in `jev_vocab.py` v2 and are used for the FUNCTION phase
#     only (W1 against W3: the loop applicability text costs the L3 pick).
#   * the platform block, which changed no modal answer on its own (V7) and
#     is kept because the lanes line refers to the register width.
#
# Every line below is produced by one rule applied to every site. Nothing is
# special-cased, nothing names a site, and nothing says which hint to pick;
# where a reading is not derivable the line says so instead of guessing. The
# thresholds are the study's, and `docs/search-driver.md` records that they
# were written by someone who had already seen jaq's nine sites --- which is
# what the hintbench target (decision 72) exists to test.

STATE_V2_DECIDING = """\
## What is being decided

A Rust program is compiled with one frozen recipe. The only thing that varies
between builds is a set of optimisation hints attached to named functions and
to the loops inside them; no source file is ever edited. You are shown one
site per question and you choose one hint for it from a fixed list. All the
questions in this request are answered independently and they all take effect
in the same build, which is then measured as a whole.

One of the options at every site is "no change", which reproduces the
baseline at that site. It is one option among the others, neither preferred
nor discouraged. The measurement is end-to-end wall time over the case set
below; the noise floor of this machine is about 1% aggregated. Hints that
change the program's output are rejected regardless of speed.

"""

DECIDING_RE = re.compile(
    r"## What is being decided\n(?:.*\n)*?(?=## The build every arm shares)")

# --- the classification rules, stated once, applied to every site ----------
# Copied from scripts/jev_state_variants.py, where they were pre-registered.

SIZE_CLASSES = [(50, "tiny"), (300, "small"), (1000, "medium"),
                (2000, "large"), (None, "very large")]
SIZE_RULE = ("<50 tiny, <300 small, <1000 medium, <2000 large, "
             ">=2000 very large")

COPY_CLASSES = [(2, "single"), (9, "few"), (None, "many")]
COPY_RULE = "1 single, 2-8 few, >=9 many"

TRIP_CLASSES = [(2, "degenerate"), (16, "short"), (100, "medium"),
                (None, "long")]
TRIP_RULE = "<2 degenerate, <16 short, <100 medium, >=100 long"

HOT_CLASSES = [(1.0, "not hot"), (5.0, "hot"), (None, "very hot")]
HOT_RULE = "<1% not hot, 1-5% hot, >=5% very hot"

# LLVM's own defaults, not this driver's numbers: InlineCost.cpp's
# `-inline-threshold` and `-inlinehint-threshold` command-line defaults.
INLINE_THRESHOLD = 225
INLINEHINT_THRESHOLD = 325

# The frozen vocabulary stops at width 16; the register width comes from the
# platform readings and falls back to 256 bits when they are unavailable.
DEFAULT_VECTOR_REGISTER_BITS = 256
MAX_WIDTH_IN_VOCAB = 16

ELEM_BITS = {"u8": 8, "i8": 8, "u16": 16, "i16": 16, "u32": 32, "i32": 32,
             "f32": 32, "u64": 64, "i64": 64, "f64": 64, "usize": 64,
             "isize": 64, "bool": 8, "char": 32}

# A `loop not vectorized: <reason>` whose reason is one of these is a
# legality failure: a `vectorize.width` hint does not override it. Anything
# else after `loop not vectorized:` (a cost-model remark, `runtime pointer
# checks needed`) is not a legality failure and is reported separately.
LEGALITY_REASONS = (
    "early exit", "unsupported switch", "incorrect number of successors",
    "induction variable could not be identified",
    "could not determine number of loop iterations",
    "could not be identified as reduction",
)

VERDICT_PREAMBLE = (
    "Mechanical readings for this site. Each line is produced by a tool from "
    "the numbers and the compiler remarks already in the state, by the same "
    "rule at every site in this request; none of them is an opinion about "
    "which hint to choose."
)


def evidence_fixes(ctx=None):
    """Whether this state format renders the decision-83 evidence fixes.

    Three defects of the v3 state, all of them in the *evidence* rather than
    in the wording (`docs/experiments/hintbench/jev-oneshot-v3.md` sections 5
    and 14):

      1. a loop's legality was read from a +/-10-line remark window, so three
         of hintbench's four loop sites --- which sit on `macros.rs:180` and
         `range.rs:1103`, lines every `for &x in slice` in the program shares
         --- were told NOT VECTORIZABLE while the baseline vectorises them;
      2. the inliner's decision about a marked function was never shown,
         because an inline remark is located at the caller, and an invented
         `inline budget` line asserted the opposite of it;
      3. a uniform placeholder share was classified as `very hot` at every
         site, which separates nothing.

    v1 and v2 must stay byte-replayable (`jev_vocab.py` freezing rule), so
    the fixes are rendered for v3, v4 and v5 only. They change no candidate,
    no description and no question: only what the state says it knows.
    """
    return V.active_version() in ("v3", "v4", "v5", "v6")


def classify(value, table):
    if value is None:
        return None
    for bound, name in table:
        if bound is None or value < bound:
            return name
    return table[-1][1]


def best_width_for(bits, register_bits=DEFAULT_VECTOR_REGISTER_BITS):
    """The widest `vectorize.width` in the frozen vocabulary that one vector
    register holds for an element of `bits` bits, or None when even the
    narrowest width in the list needs more than one register (an element as
    wide as the register itself, for instance). None is a real answer here
    and the verdict block prints it as one."""
    if not bits:
        return None
    lanes = register_bits // bits
    for w in (16, 8, 4, 2):
        if w <= min(lanes, MAX_WIDTH_IN_VOCAB):
            return w
    return None


class Demangler:
    """Rust symbol names, demangled in one batch by `llvm-cxxfilt`.

    The dump records a loop's inline chain as mangled symbols. The element
    type the lanes arithmetic needs is inside them, so they are demangled
    once per run and cached. When the tool is missing every name maps to
    itself, `_elem_type` then finds nothing, and the verdict block says the
    element type is not derivable --- which is the honest line, not a guess.
    """

    def __init__(self, tool="llvm-cxxfilt"):
        self.tool = tool
        self.cache = {}
        self.ok = bool(shutil.which(tool))

    def many(self, names):
        todo = sorted({n for n in names if n and n not in self.cache})
        if todo and self.ok:
            try:
                out = subprocess.run([self.tool], input="\n".join(todo),
                                     capture_output=True, text=True,
                                     check=True).stdout.splitlines()
            except Exception:
                self.ok, out = False, []
            if len(out) == len(todo):
                self.cache.update(zip(todo, out))
        for n in todo:
            self.cache.setdefault(n, n)
        return [self.cache.get(n, n) for n in names]


# `core::slice::iter::Iter::<u8>`, `Iter<u8>`, `Copied::<Iter::<u8>>`: the
# innermost iterator's element type, with no nested generics inside it.
ITER_RE = re.compile(r"\bIter(?:::)?<([^<>]+)>")
ARRAY_RE = re.compile(r"^\[\s*(\w+)\s*;\s*(\d+)\s*\]$")


def _elem_type(chain_demangled):
    """The element type at the loop's iterator, read off the inline chain.

    The chain runs outermost first, so the last `Iter<...>` on it is the
    innermost one --- the iterator the loop actually steps. A chain with no
    `Iter<>` at all (a loop over format pieces, say) and a type parameter
    that was recorded as a placeholder both give None, and the verdict block
    then says the element type is unknown rather than guessing one.
    """
    hits = []
    for name in chain_demangled or []:
        hits += ITER_RE.findall(name or "")
    if not hits:
        return None
    t = hits[-1].strip().lstrip("&").strip()
    if t in ("", "_", "..") or " as " in t:
        return None
    return t


def _elem_bits(t):
    if t is None:
        return None
    if t in ELEM_BITS:
        return ELEM_BITS[t]
    m = ARRAY_RE.match(t)
    if m and m.group(1) in ELEM_BITS:
        return ELEM_BITS[m.group(1)] * int(m.group(2))
    return None


def fn_verdict_lines(item, ctx):
    """The mechanical readings for one marked function."""
    m = item.meta
    L = []
    insts = m.get("inst_count") or 0
    copies = len(m.get("linkages") or []) or 1
    attrs = [a for a in (m.get("attributes") or []) if a]
    attr_text = " | ".join(attrs) or "(none)"
    has_hint = any("inlinehint" in a for a in attrs)
    all_hinted = bool(attrs) and all("inlinehint" in a for a in attrs)
    has_cold = any("cold" in a for a in attrs)

    if insts:
        L.append("body size: %d LLVM instructions after LTO" % insts)
        L.append("size class: %s (rule: %s)"
                 % (classify(insts, SIZE_CLASSES), SIZE_RULE))
    else:
        L.append("body size: not recorded by the dump for this function, so "
                 "no size class")
    L.append("distinct copies in the binary: %d monomorphization(s); copy "
             "class %s (rule: %s)"
             % (copies, classify(copies, COPY_CLASSES), COPY_RULE))
    if evidence_fixes(ctx):
        # Decision 83. The `inline budget` line this replaces divided the
        # body's instruction count by `-inline-threshold=225` and announced
        # whether "the body fits inside that budget". It is not an
        # InlineCost, 225 is not the threshold this recipe uses, and at
        # hintbench's k2 it asserted the opposite of the inliner's own
        # measured answer. What the inliner decided is in the log.
        L.append(inline_outcome_line(m.get("linkages"), ctx.get("inlines")))
    elif insts:
        budget = INLINEHINT_THRESHOLD if has_hint else INLINE_THRESHOLD
        name = ("-inlinehint-threshold=%d" % INLINEHINT_THRESHOLD if has_hint
                else "-inline-threshold=%d" % INLINE_THRESHOLD)
        r = insts / float(budget)
        L.append("inline budget: LLVM's defaults are -inline-threshold=%d "
                 "and -inlinehint-threshold=%d cost units; body instructions "
                 "/ %s = %s (an order-of-magnitude comparison, not an "
                 "InlineCost computation --- the cost=/threshold= pairs in "
                 "the remarks above are the real ones, and they are about "
                 "this function's callees)"
                 % (INLINE_THRESHOLD, INLINEHINT_THRESHOLD, name,
                    ("%.1fx, i.e. the body fits inside that budget" % r)
                    if r < 1 else "%.0fx over" % r))
    L.append("attributes already on it: %s" % attr_text)
    if V.active_version() in ("v3", "v4", "v5", "v6"):
        # Decision 77. The same sentence at every function site: it is a
        # property of the recipe, not of this site, and it names nothing.
        # Without it the `inlinehint` an attribute list may carry reads as
        # evidence about the inliner's threshold, which under a profile it
        # is not.
        L.append("inliner mechanics of this recipe: with a profile present, "
                 "`inlinehint` and `cold` on a function do not change the "
                 "inliner's threshold for it, because the call site's own "
                 "hotness class assigns that threshold afterwards; "
                 "`alwaysinline` and `noinline` are decided before the cost "
                 "model runs and are always honoured")
    else:
        if all_hinted:
            L.append("no-op check: every copy already carries `inlinehint`, "
                     "so the candidate `inline` reproduces the state this "
                     "site is already in")
        elif has_hint:
            L.append("no-op check: some copies already carry `inlinehint`, "
                     "so the candidate `inline` reproduces, on those copies, "
                     "the state this site is already in")
        if has_cold:
            L.append("no-op check: `cold` already appears among the "
                     "attribute sets this site carries")
    share = m.get("share") if m.get("share") is not None else m.get("reach")
    if share is None:
        L.append("share of the program's user cycles: not recorded for this "
                 "mark, so no hotness class")
    elif evidence_fixes(ctx) and ctx.get("share_placeholder"):
        # Decision 83. hintbench's sites.json carries `share: 12.5` at all
        # eight marks --- the design's "one eighth each", not a measurement
        # --- and the old line turned it into `hotness class very hot` at
        # every site. A number that is the same everywhere cannot separate
        # anything, and calling all eight sites very hot is worse than
        # saying nothing, so the class is dropped rather than printed.
        L.append("share of the program's user cycles: not measured on this "
                 "target --- the site list carries one and the same value "
                 "(%s) for every mark, so there is no hotness class here"
                 % fmt_share(share))
    else:
        L.append("share of the program's user cycles: %s; hotness class %s "
                 "(rule: %s)" % (fmt_share(share),
                                 classify(float(share), HOT_CLASSES), HOT_RULE))
    n_loops = ctx.get("loops_by_mark", {}).get(m.get("mark"))
    if n_loops is not None:
        L.append("loop sites inside it: %d (`loop_in_mark` sites of this "
                 "mark in the dump)" % n_loops)
    return L


def post_vectorize_lines(item, ctx):
    """What LLVM did with THIS loop, from the plugin (decision 87 c).

    Decision 83 could only say UNKNOWN for a loop whose leaf location several
    inlined loops share, because a remark carries a source location and no
    function name --- three of hintbench's four loops, and the reason
    Experiment 4's loop answers were chosen from lane arithmetic alone
    (decision 87 b). The plugin now runs at `VectorizerEndEP`, after
    LoopVectorize, and records per site key whether the loop is still there,
    whether it carries `llvm.loop.isvectorized`, and the vector width and
    interleave count it ended up with. That is a statement about one loop, so
    it replaces the UNKNOWN rather than qualifying it.

    Returns [] when the report has no such record (a build made with an older
    plugin, or a loop whose owner function the pass never saw).
    """
    pv = item.meta.get("post_vectorize")
    if not isinstance(pv, dict) or not pv.get("watched"):
        return []
    head = ("what LLVM did with this loop in the baseline build, recorded by "
            "the plugin itself after LoopVectorize had run --- this is a "
            "fact about this one loop, not a remark attributed to a source "
            "line, and it is the primary evidence here: ")
    if pv.get("ambiguous_signature"):
        return [head + "UNKNOWN. Two of this function's loops cannot be told "
                "apart after the vectorizer rewrote them, so nothing "
                "recorded there can be assigned to this one."]
    if not pv.get("exists"):
        return [head + "the loop is no longer in the program by the time the "
                "vectorizer has finished with it (it was removed, merged or "
                "fully unrolled), so a hint attached to it has nothing left "
                "to act on."]
    if not pv.get("isvectorized"):
        line = (head + "LLVM did NOT vectorize it: after LoopVectorize the "
                "loop is still there and carries no `llvm.loop.isvectorized` "
                "metadata.")
        if pv.get("vector_width"):
            line += (" Vector values of %d lanes do appear in its body, but "
                     "they are the SLP vectorizer's or the unroller's, not a "
                     "vectorized loop." % pv["vector_width"])
        return [line, "a `vectorize.width` hint is not a permission slip: "
                "where LLVM declined to vectorize a loop, asking for a width "
                "does not make it legal or profitable. What it declined for "
                "is not recorded per loop; only the remarks below speak to "
                "that, and they speak about a source line."]
    vf, ic = pv.get("vector_width"), pv.get("interleave_count")
    out = [head + "LLVM vectorized it%s%s."
           % ("" if not vf else ", with vectors of %d lanes" % vf,
              "" if not ic else
              (", interleaved %d times (the vectorized loop's induction "
               "variable advances %s elements per iteration)"
               % (ic, pv.get("iv_step"))))]
    out.append("vectorisation legality: LEGAL, and already taken --- the "
               "baseline vectorizes this loop with no hint at all.")
    pv_untried = bool(ctx.get("pv_untried"))
    if vf and "vectorize_width_%d" % vf in candidates_of(item, ctx["knobs"]):
        out.append("no-op check: %d is the width LLVM already uses here, so "
                   "the candidate `vectorize_width_%d` asks for the state "
                   "this site is in and the build it produces can only be "
                   "the baseline's." % (vf, vf))
    if vf and pv_untried:
        out.append(pv_untried_line(item, ctx, vf, "vectorize_width_",
                                   "width"))
    if ic and "interleave_count_%d" % ic in candidates_of(item, ctx["knobs"]):
        out.append("no-op check: %d is the interleave count LLVM already "
                   "uses here, so `interleave_count_%d` asks for the state "
                   "this site is in." % (ic, ic))
    if ic and pv_untried:
        out.append(pv_untried_line(item, ctx, ic, "interleave_count_",
                                   "interleave count"))
    return out


PV_UNTRIED_TEMPLATE = (
    "%d is the %s LLVM's cost model picked for this loop with no hint; it is "
    "not a measurement of this program, and no other %s has been measured "
    "at this loop %s. Vocabulary values other than %d not yet tried here: "
    "%s. None of them is being proposed over another.")


def pv_untried_line(item, ctx, observed, prefix, noun):
    """Decision 92 (c), state v5.1 (`--pv-untried on`).

    Experiment 5: the post_vectorize fact killed a wrong answer (the k8
    width 8 fell from P 0.60 to 0.01) and produced no right one, because
    "LLVM picked 8" reads as "8 is right". This line says, mechanically,
    what that number is and which values of the same kind the vocabulary
    has that nothing in this run has tried at this loop: ALL of them, in
    numeric order, with none singled out."""
    def values(cands):
        out = set()
        for c in cands:
            if c.startswith(prefix) and c[len(prefix):].isdigit():
                out.add(int(c[len(prefix):]))
        return out
    vocab = values(candidates_of(item, ctx["knobs"]))
    tried = values(tried_at(ctx.get("history") or [], item.id))
    tried_other = sorted(v for v in tried if v != observed)
    untried = sorted(v for v in vocab if v != observed and v not in tried)
    where = ("in this run" if not tried_other else
             "except %s" % ", ".join(str(v) for v in tried_other))
    return PV_UNTRIED_TEMPLATE % (
        observed, noun, noun, where, observed,
        ", ".join(str(v) for v in untried) or "none")


def loop_verdict_lines(item, ctx):
    """The mechanical readings for one loop site."""
    m = item.meta
    L = []
    trip = m.get("trip_count")
    insts = m.get("body_inst_count")
    if trip is None:
        L.append("average trip count: not recorded in the training profile "
                 "for this loop, so no trip class")
    else:
        L.append("average trip count: %.1f; trip class %s (rule: %s)"
                 % (float(trip), classify(float(trip), TRIP_CLASSES),
                    TRIP_RULE))
    if insts is None:
        L.append("body size: not recorded by the dump for this loop, so no "
                 "size class")
    else:
        L.append("body size: %d LLVM instructions; size class %s (rule: %s)"
                 % (insts, classify(int(insts), SIZE_CLASSES), SIZE_RULE))
    copies = m.get("key_copies") or m.get("key_copies_sidecar")
    L.append("calls inside the body: %s; loop nesting depth %s; loops this "
             "site key names: %s"
             % ("yes" if m.get("has_calls") else "no", m.get("depth"),
                copies if copies else "not recorded for this key (a key can "
                "name several loops, and a hint on it would reach all of "
                "them)"))

    bits_reg = ctx.get("vector_register_bits") or DEFAULT_VECTOR_REGISTER_BITS
    chain = ctx["demangler"].many(m.get("inline_chain") or [])
    elem = _elem_type(chain)
    bits = _elem_bits(elem)
    width = best_width_for(bits, bits_reg)
    if elem and width:
        L.append("element type at the loop's iterator: %s (read off the "
                 "inline chain); one %d-bit vector register holds %d of "
                 "them, so the widest `vectorize.width` in this list that "
                 "fits one register is %d (the list stops at %d)"
                 % (elem, bits_reg, bits_reg // bits, width,
                    MAX_WIDTH_IN_VOCAB))
    elif elem and bits:
        L.append("element type at the loop's iterator: %s (read off the "
                 "inline chain); it is %d bits wide, so one %d-bit vector "
                 "register holds %d of them and no `vectorize.width` in this "
                 "list fits inside one register"
                 % (elem, bits, bits_reg, bits_reg // bits))
    elif elem:
        L.append("element type at the loop's iterator: %s (read off the "
                 "inline chain); its width in bits is not one this tool "
                 "knows, so the lane count for this loop is unknown" % elem)
    else:
        L.append("element type at the loop's iterator: not derivable from "
                 "the recorded inline chain, so the lane count for this "
                 "loop is unknown")
    if m.get("has_fp_reduction"):
        L.append("floating-point reduction in the body: yes --- the build "
                 "pins -hints-allow-reordering=false, so a width hint does "
                 "not authorise reassociating it and a non-reassociable "
                 "reduction is simply not widened")

    fixes = evidence_fixes(ctx)
    shared = False
    if fixes:
        # Decision 83. The loop's own leaf location, column included --- not
        # a +/-10-line window. `n_loops_at` counts the vectoriser verdicts
        # the log emitted at exactly that location: one verdict per loop, so
        # more than one means several inlined loops write to the same source
        # line and nothing there can be attributed to this one.
        leaf_col = (item.meta.get("leaf_col")
                    if item.meta.get("leaf_col") is not None else None)
        rem = (ctx["remarks"].at(m.get("leaf_file"), m.get("leaf_line"),
                                 leaf_col)
               if m.get("leaf_file") else [])
        n_here = (ctx["remarks"].n_loops_at(m.get("leaf_file"),
                                            m.get("leaf_line"), leaf_col)
                  if m.get("leaf_file") else None)
        shared = bool(n_here and n_here > 1)
    else:
        rem = [t for _ln, t in (ctx["remarks"].near(m.get("leaf_file"),
                                                    m.get("leaf_line"),
                                                    span=10)
                                if m.get("leaf_file") else [])]
        n_here = None
    reasons, vf = [], []
    for t in rem:
        mm = re.search(r"loop not vectorized:\s*(.+)$", t)
        if mm and any(k in mm.group(1).lower() for k in LEGALITY_REASONS):
            r = mm.group(1).strip()
            if r not in reasons:
                reasons.append(r)
        vf += [int(x) for x in re.findall(r"vectorization width: (\d+)", t)]
    if fixes:
        # What the plugin's dump knows about this loop is the primary
        # source: it is per-loop by construction, where a remark is only
        # per-source-location. It is also narrower than it looks, and the
        # line says exactly what it covers.
        L.append("from the plugin's dump, which is the primary source here "
                 "because it records this loop and not a source line: trip "
                 "count %s, calls in the body %s, `llvm.loop.isvectorized` "
                 "metadata at the point the hint is attached: %s --- the "
                 "hint goes in before LoopVectorize runs, so `no` is the "
                 "normal reading and says nothing about whether LLVM "
                 "vectorises this loop afterwards"
                 % ("unknown" if trip is None else "%.1f" % float(trip),
                    "yes" if m.get("has_calls") else "no",
                    "yes" if m.get("already_vectorized") else "no"))
    pv_lines = post_vectorize_lines(item, ctx) if fixes else []
    if pv_lines:
        # Decision 87 (c). The per-loop record answers the question the
        # remarks could not, so it comes first and the shared-line caveat
        # below is demoted to what it really covers: the *reason*.
        L += pv_lines
        if shared:
            L.append("the remarks cannot add to that: %s:%s carries %d "
                     "separate vectoriser verdicts in the baseline build, "
                     "because every loop inlined from that line lands on it, "
                     "so none of them can be read as a statement about this "
                     "loop."
                     % (os.path.basename(m.get("leaf_file") or "?"),
                        m.get("leaf_line"), n_here))
        elif reasons:
            L.append("what the remarks at this loop's own leaf location say, "
                     "as a secondary reading: %s" % "; ".join(reasons))
    elif fixes and shared:
        L.append("vectorisation legality: UNKNOWN (shared source line; "
                 "remarks not attributable to this loop) --- %s:%s carries "
                 "%d separate vectoriser verdicts in the baseline build, "
                 "because every loop inlined from that line lands on it. "
                 "Nothing in the remarks can be read as a statement about "
                 "this loop."
                 % (os.path.basename(m.get("leaf_file") or "?"),
                    m.get("leaf_line"), n_here))
    elif not rem:
        L.append("vectorisation legality: UNKNOWN --- no remarks were "
                 "recorded at this location, so nothing here says whether "
                 "vectorisation is legal")
    elif reasons:
        L.append("vectorisation legality, from the baseline remarks at this "
                 "line: NOT VECTORIZABLE --- %s. A `vectorize.width` hint is "
                 "not a permission slip: LLVM drops it when vectorisation is "
                 "illegal." % "; ".join(reasons))
    elif vf:
        cur = max(vf)
        L.append("vectorisation legality, from the baseline remarks at this "
                 "line: LEGAL --- the remarks include `vectorized loop "
                 "(vectorization width: %d)`, i.e. LLVM already vectorises "
                 "this line without any hint" % cur)
        if "vectorize_width_%d" % cur in candidates_of(item, ctx["knobs"]):
            L.append("no-op check: the width already in effect is %d, so the "
                     "candidate `vectorize_width_%d` reproduces the state "
                     "this site is already in" % (cur, cur))
    else:
        L.append("vectorisation legality, from the baseline remarks at this "
                 "line: no legality failure is reported and no vectorized "
                 "loop is reported")
    if m.get("already_vectorized") and not vf and not fixes:
        L.append("no-op check: the dump records this loop as already "
                 "vectorized at the point the hint is attached, so a "
                 "`vectorize_*` candidate may reproduce the state it is "
                 "already in")
    adv = [t.split(": ", 1)[1] for t in rem
           if "advising against unrolling" in t and ": " in t]
    if adv and not shared:
        L.append("unroller, from the baseline remarks at this line: %s"
                 % adv[0])
    if any("cost-model indicates that vectorization" in t for t in rem) \
            and not shared:
        L.append("cost model, from the baseline remarks at this line: "
                 "vectorization not beneficial")
    if fixes:
        L.append("caveat that applies to every loop here: remarks carry a "
                 "source location and no function name, so a line several "
                 "inlined loops share carries all of their remarks at once; "
                 "the readings above use this loop's own leaf location only, "
                 "and say UNKNOWN where that location is shared")
    else:
        L.append("caveat that applies to every loop here: remarks are "
                 "attributed by source location only, so several loops can "
                 "share one line")
    return L


def verdict_block(item, ctx):
    """The mechanical readings, as they ride next to the question."""
    if item.kind == "fn":
        lines = fn_verdict_lines(item, ctx)
    elif item.kind == "loop":
        lines = loop_verdict_lines(item, ctx)
    else:
        return ""
    return ("\n\n" + VERDICT_PREAMBLE + "\n"
            + "\n".join("  - " + l for l in lines))


# --- the platform block ----------------------------------------------------

CACHE_KIND = {"Data": "data", "Instruction": "instruction",
              "Unified": "unified"}


def platform_readings():
    """lscpu and /sys/devices/system/cpu/cpu0/cache, as read on this machine.

    Nothing is corrected: decision 17 recorded that the two CCDs of a 5950X
    are not visible from inside WSL2, so the L3 figure is reported as the
    guest kernel gives it and the block says so.
    """
    r = {"lscpu": {}, "caches": [], "target_cpu": None}
    try:
        out = subprocess.run(["lscpu"], capture_output=True, text=True,
                             check=True).stdout
    except Exception:
        out = ""
    for line in out.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            r["lscpu"][k.strip()] = v.strip()
    base = "/sys/devices/system/cpu/cpu0/cache"
    for d in sorted(glob.glob(os.path.join(base, "index*"))):
        c = {}
        for field in ("level", "type", "size", "ways_of_associativity",
                      "shared_cpu_list", "number_of_sets"):
            try:
                c[field] = open(os.path.join(d, field)).read().strip()
            except OSError:
                c[field] = None
        r["caches"].append(c)
    try:
        r["target_cpu"] = re.search(
            r'"-target-cpu" "([A-Za-z0-9_-]+)"',
            subprocess.run(["clang", "-march=native", "-E", "-", "-###"],
                           input="", capture_output=True, text=True).stderr
        ).group(1)
    except Exception:
        r["target_cpu"] = None
    return r


ISA_FLAGS = ["avx512f", "avx512bw", "avx512vl", "avx2", "avx", "fma", "bmi1",
             "bmi2", "aes", "sha_ni", "vaes", "vpclmulqdq", "popcnt", "movbe",
             "rdseed", "adx", "clwb", "clflushopt", "erms", "fsrm", "sse4_2"]


def _cache_size(text):
    """sysfs writes `32K` / `32768K`; say it in the units humans use."""
    if not text:
        return "?"
    m = re.match(r"^(\d+)([KM])$", text.strip())
    if not m:
        return text
    n, unit = int(m.group(1)), m.group(2)
    if unit == "K" and n >= 1024 and n % 1024 == 0:
        return "%d MiB" % (n // 1024)
    return "%d %siB" % (n, unit)


def render_platform_block(r, ctx):
    """The `## The machine this will run on` section of state v2."""
    cpu = r["lscpu"]
    flags = set((cpu.get("Flags") or "").split())
    have = [f for f in ISA_FLAGS if f in flags]
    if "avx512f" in flags:
        bits, regs = 512, 32
    elif "avx" in flags or "avx2" in flags:
        bits, regs = 256, 16
    else:
        bits, regs = 128, 16
    lanes = ", ".join("%d x %s" % (bits // b, t) for b, t in
                      ((8, "u8"), (16, "u16"), (32, "u32/f32"),
                       (64, "u64/f64")))
    out = ["## The machine this will run on", ""]
    out.append("  cpu model         %s, %s core(s) / %s logical cpu(s), "
               "family %s model %s"
               % (cpu.get("Model name", "unknown"),
                  cpu.get("Core(s) per socket", "?"), cpu.get("CPU(s)", "?"),
                  cpu.get("CPU family", "?"), cpu.get("Model", "?")))
    if r.get("target_cpu"):
        out.append("  llvm target-cpu   %s (what -Ctarget-cpu=native resolves "
                   "to on this machine)" % r["target_cpu"])
    out.append("  isa               %s" % (", ".join(have) or "not reported"))
    if "avx512f" not in flags:
        out.append("  no isa            **no AVX-512 of any kind**")
    out.append("  vector width      %d bit, %d architectural vector registers"
               % (bits, regs))
    out.append("                    one register holds %s" % lanes)
    for c in r["caches"]:
        if not c.get("level"):
            continue
        kind = CACHE_KIND.get(c.get("type") or "", (c.get("type") or "").lower())
        out.append("  l%s %-14s %s%s%s"
                   % (c["level"], kind, _cache_size(c.get("size")),
                      ", %s-way" % c["ways_of_associativity"]
                      if c.get("ways_of_associativity") else "",
                      ", shared by cpus %s" % c["shared_cpu_list"]
                      if c.get("shared_cpu_list") else ""))
    out.append("  how it is read    lscpu and "
               "/sys/devices/system/cpu/cpu0/cache on this machine, once per "
               "run. This is a WSL2 guest: the cache figures are the "
               "guest-visible ones and are reported as seen, not corrected.")
    out.append("  how it is timed   the process is pinned to one logical cpu "
               "(taskset -c %s) with a %s ms settle gap between runs, %d "
               "interleaved repetitions, shuffled label order, paired "
               "bootstrap 95%% CI"
               % (ctx.get("bench_cpu"), ctx.get("bench_gap_ms"),
                  ctx.get("reps", 0)))
    out.append("")
    return "\n".join(out)


def platform_block(ctx, cache_path=None):
    """The rendered block, computed once per run and cached in the run dir."""
    if cache_path and os.path.isfile(cache_path):
        try:
            return json.load(open(cache_path))["block"]
        except Exception:
            pass
    r = platform_readings()
    block = render_platform_block(r, ctx)
    if cache_path:
        try:
            with open(cache_path, "w") as f:
                json.dump({"ts": datetime.datetime.now().astimezone()
                           .isoformat(), "readings": r, "block": block},
                          f, indent=1)
        except OSError:
            pass
    return block


def vector_register_bits(cache_path):
    """The width the lanes arithmetic uses, from the cached readings."""
    try:
        flags = set((json.load(open(cache_path))["readings"]["lscpu"]
                     .get("Flags") or "").split())
    except Exception:
        return DEFAULT_VECTOR_REGISTER_BITS
    if "avx512f" in flags:
        return 512
    if "avx" in flags or "avx2" in flags:
        return 256
    return 128


# ---------------------------------------------------------------------------
# one request's questions
# ---------------------------------------------------------------------------

def questions_for(items, ctx, knobs):
    """The `questions` object and the site map for one request.

    `--print-state` and the Jev proposer both go through this, so what is
    printed is what is sent: under state v2 the verdict block rides in the
    question's `instructions`, which is where the study measured its effect
    (finding 2b: the same words in a state section make Jev uniformly
    cautious; attached to the options it is choosing between they make it
    discriminate).
    """
    questions, site_map = {}, {}
    for i, it in enumerate(items):
        it.qname = "q%d" % i
        site_map[it.qname] = {"site_id": it.id, "kind": it.kind,
                              "label": it.label}
        instructions = V.instructions_for(it.kind, it.qname)
        if ctx.get("verdicts"):
            instructions += verdict_block(it, ctx)
        questions[it.qname] = {"type": "choice",
                               "instructions": instructions,
                               "criteria": candidates_of(it, knobs)}
    return questions, site_map


EXPLORE_INSTRUCTIONS = (
    "Section `{qname}` of the state describes this site. No hint has ever "
    "been tried there: in every round of this run so far it was answered "
    "KEEP_DEFAULT, so nothing that has been measured says what any of the "
    "hints below would be worth, and the results table cannot say. One of "
    "the candidates below will be tried at this site in this round's build; "
    "which of them is most promising? The list is every candidate this site "
    "has not already been given, filtered mechanically --- KEEP_DEFAULT is "
    "not among them and nothing was left out on anyone's judgement."
)


# Decision 92 (b), revisit text "r1". Used only for the revisit questions of
# `--explore-revisit R`; EXPLORE_INSTRUCTIONS (v1) is untouched and still
# asks every never-tried site. It mirrors v1 and, like it, never ranks or
# recommends: it names what was tried (in the history's own spelling) and
# says the list below is the mechanical remainder.
EXPLORE_REVISIT_TEXT_VERSION = "r1"
EXPLORE_REVISIT_INSTRUCTIONS = (
    "Section `{qname}` of the state describes this site. Hints already "
    "tried at this site in this run: {tried}; their measured results are in "
    "this site's history above. They are not among the candidates below. "
    "None of the candidates below has been tried at this site, so nothing "
    "measured here says what any of them would be worth. One of the "
    "candidates below will be tried at this site in this round's build; "
    "which of them is most promising? The list is every candidate this site "
    "has not already been given, filtered mechanically --- KEEP_DEFAULT is "
    "not among them and nothing was left out on anyone's judgement."
)

# Decision 92 (b): a site is revisited while fewer than this many distinct
# hints have been tried there. 2 means "one more try after the first".
EXPLORE_MAX_VISITS = 2


def tried_at(history, site_id):
    """Every non-KEEP_DEFAULT candidate an earlier round put at this site.

    Accepted or not: a round that was measured and rejected has tried its
    hint just as much as one that was promoted, and the point of the filter
    is to stop re-offering what is already known.
    """
    out = []
    for h in history:
        pick = h["choices"].get(site_id)
        if pick and pick != V.KEEP_DEFAULT and pick not in out:
            out.append(pick)
    return out


def hotness_of(item, ctx=None):
    """One number per site, for ordering only.

    A loop carries the dump's own `hotness`, which is the profile's header
    count times the body size. A function carries its profile share, or its
    reach where it has no hot symbol of its own --- except on a target whose
    marks all declare the same share by construction (hintbench: one eighth
    each), where that number separates nothing and decision 83 already
    refuses to classify it. There the fallback is the summed hotness of the
    loops the dump found inside the mark, which is measured. With neither,
    the order is the site list's own, which is the marks file's.
    """
    if item.kind == "loop":
        return float(item.meta.get("hotness") or 0.0)
    share = item.meta.get("share")
    if share is None:
        share = item.meta.get("reach")
    if share is not None and not (ctx or {}).get("share_placeholder"):
        return float(share)
    by_mark = (ctx or {}).get("hotness_by_mark") or {}
    return float(by_mark.get(item.meta.get("mark")) or 0.0)


def exploration_sites(items, picks, ctx, knobs, k, revisit=0, record=None):
    """The sites this round adds an exploration Choice for (decision 89 b).

    Experiment 4's finding: feedback works as a filter and not as a search.
    It removed both harmful picks in one round and discovered nothing,
    because the state can only speak about hints that have been tried, and
    the one exploration mechanism the driver had (`forced_top1`) fires only
    when a whole phase is KEEP_DEFAULT --- which never happened, because one
    site alone kept phase A non-empty in all five rounds. The two hints the
    run never found, `unroll.count=4` at the k3 loop (+4.4%) and
    `vectorize.width=16` at k8 (+8.8%), were never tried once in 58 answers.

    A site is eligible when no earlier round put a non-KEEP_DEFAULT hint on
    it AND this round's own answer there is KEEP_DEFAULT. The second clause
    is what makes the extra Choice additive: a site that is already getting a
    hint this round will have been tried by the end of it, so there is
    nothing to explore, and no argmax is ever overridden. Eligible sites are
    ordered by hotness and the first `k` are taken.

    Decision 92 (b) adds `revisit` further slots, filled AFTER the `k`
    new-site slots so that a never-tried site is never starved: a site is
    eligible for a revisit when this round's answer there is KEEP_DEFAULT
    (the same clause, no argmax is overridden), 1 <= the number of distinct
    hints tried there < EXPLORE_MAX_VISITS, and an untried non-KEEP
    candidate remains. Revisits are ordered by fewest distinct hints tried,
    then hotness, then list position --- mechanical, and it chooses which
    site gets a slot, never which hint. With `revisit` 0 the result is the
    decision-89 result exactly.

    Returns [(item, {candidate: description}), ...], new sites first. When
    `record` is a dict it is filled with the eligible lists in their order
    (`eligible_new`, `eligible_revisit`) and a per-site `meta` entry (kind,
    visit_no, tried, candidates offered).
    """
    if k <= 0 and revisit <= 0:
        if record is not None:
            record.update({"eligible_new": [], "eligible_revisit": [],
                           "meta": {}})
        return []
    rows, rev = [], []
    for i, it in enumerate(items):
        if it.kind == "build":
            continue
        if picks.get(it.id, V.KEEP_DEFAULT) != V.KEEP_DEFAULT:
            continue
        tried_l = tried_at(ctx["history"], it.id)
        tried = set(tried_l)
        cands = {c: d for c, d in candidates_of(it, knobs).items()
                 if c != V.KEEP_DEFAULT and c not in tried}
        if not cands:
            continue
        if not tried:
            rows.append((hotness_of(it, ctx), i, it, cands, tried_l))
        elif len(tried) < EXPLORE_MAX_VISITS:
            rev.append((len(tried), hotness_of(it, ctx), i, it, cands,
                        tried_l))
    rows.sort(key=lambda r: (-r[0], r[1]))
    rev.sort(key=lambda r: (r[0], -r[1], r[2]))
    new = [(it, cands) for _h, _i, it, cands, _t in rows[:max(0, k)]]
    again = [(it, cands) for _n, _h, _i, it, cands, _t
             in rev[:max(0, revisit)]]
    if record is not None:
        record["eligible_new"] = [
            {"site_id": it.id, "hotness": h, "tried": t}
            for h, _i, it, _c, t in rows]
        record["eligible_revisit"] = [
            {"site_id": it.id, "n_tried": n, "hotness": h, "tried": t}
            for n, h, _i, it, _c, t in rev] if revisit > 0 else []
        meta = {}
        for kind, src in (("new", rows[:max(0, k)]), ):
            for h, _i, it, c, t in src:
                meta[it.id] = {"kind": kind, "visit_no": 1, "tried": t,
                               "candidates": list(c)}
        for n, h, _i, it, c, t in rev[:max(0, revisit)]:
            meta[it.id] = {"kind": "revisit", "visit_no": n + 1, "tried": t,
                           "candidates": list(c)}
        record["meta"] = meta
    return new + again


def exploration_questions(pairs, ctx, meta=None):
    """The `questions` object and site map for one exploration request.

    `meta` is `exploration_sites`' record["meta"]; a site it marks as a
    revisit gets EXPLORE_REVISIT_INSTRUCTIONS (r1), every other site the
    v1 text. Without `meta` every site gets the v1 text, as before."""
    questions, site_map = {}, {}
    for i, (it, cands) in enumerate(pairs):
        it.qname = "e%d" % i
        m = (meta or {}).get(it.id) or {}
        site_map[it.qname] = {"site_id": it.id, "kind": it.kind,
                              "label": it.label, "exploration": True}
        if m.get("kind") == "revisit":
            site_map[it.qname]["revisit"] = True
            instructions = EXPLORE_REVISIT_INSTRUCTIONS.format(
                qname=it.qname,
                tried=", ".join("`%s`" % V.spec_spelling_safe(t)
                                for t in m.get("tried") or []))
        else:
            instructions = EXPLORE_INSTRUCTIONS.format(qname=it.qname)
        if ctx.get("verdicts"):
            instructions += verdict_block(it, ctx)
        questions[it.qname] = {"type": "choice",
                               "instructions": instructions,
                               "criteria": dict(cands)}
    return questions, site_map


# ---------------------------------------------------------------------------
# the readout (decision 71)
# ---------------------------------------------------------------------------

def rank_by_non_keep(items, why, knobs):
    """Sites ordered by `1 - P(KEEP_DEFAULT)`, with their best non-KEEP hint.

    Decision 71: the argmax throws away the probabilities, and a round in
    which every site's argmax is `KEEP_DEFAULT` rebuilds the baseline and
    measures nothing. The ranking is the cheap lever: it says which site Jev
    is least sure about leaving alone, and which hint it would reach for
    there. `__build__` is not ranked --- forcing a build-wide compiler flag
    is not "one entry at one site".
    """
    rows = []
    for it in items:
        if it.kind == "build":
            continue
        w = why.get(it.id) or {}
        # A site whose answer was thrown away by `[jev] min_confidence` is
        # not a site the readout may put a hint on: the gate said the answer
        # is not worth acting on, and forcing it back in would undo it.
        if str(w.get("source") or "").startswith("confidence "):
            continue
        p = w.get("probabilities") or {}
        if not isinstance(p, dict) or not p:
            continue
        cands = [c for c in candidates_of(it, knobs) if c != V.KEEP_DEFAULT]
        if not cands:
            continue
        def prob(c):
            try:
                return float(p.get(c) or 0.0)
            except (TypeError, ValueError):
                return 0.0
        try:
            keep = float(p.get(V.KEEP_DEFAULT) or 0.0)
        except (TypeError, ValueError):
            keep = 0.0
        best = max(cands, key=lambda c: (prob(c), -cands.index(c)))
        rows.append({"site_id": it.id, "kind": it.kind, "label": it.label,
                     "p_keep": keep, "score": 1.0 - keep,
                     "best_non_keep": best, "p_best": prob(best)})
    rows.sort(key=lambda r: (-r["score"], -r["p_best"], r["site_id"]))
    return rows


# ---------------------------------------------------------------------------
# Jev
# ---------------------------------------------------------------------------

def read_api_key(env_name):
    if os.environ.get(env_name):
        return os.environ[env_name]
    path = os.path.join(REPO, ".env")
    if os.path.isfile(path):
        for line in open(path):
            line = line.strip()
            if line.startswith(env_name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("no %s in the environment or in %s/.env" % (env_name, REPO))


# Decision 92 (d): the gateway's retry policy. Every 503 of Experiment 5 came
# back from the provider (typesafe-ai) in 120-340 ms with no tokens used and
# no fallback, re-sends were byte-identical, and whether a request landed
# tracked its body size, not the time of day: a probe of the same bodies
# landed phase A (85 KB) 0 of 6, phase B (51 KB) 4 of 18 and exploration
# (24 KB) 5 of 6. A longer wait therefore buys nothing and the policy spends
# attempts instead: a fixed short pause between them, many of them, inside a
# wall-clock budget. The jitter is drawn from an RNG seeded by the request
# body's sha256, so the same request waits the same way every time it is
# sent.
RETRY_BACKOFF_S = 2.0
RETRY_JITTER = 0.2


def retry_policy(cfg):
    """The retry parameters one run uses, as the manifest records them."""
    return {"backoff": RETRY_BACKOFF_S,
            "cap_s": float(cfg["backoff_cap_s"]),
            "jitter": RETRY_JITTER,
            "timeout_s": float(cfg["request_timeout_s"]),
            "wall_budget_s": float(cfg["retry_wall_budget_s"]),
            "retries_cap": int(cfg["retries"]),
            "phase_resend_max": int(cfg["phase_resend_max"])}


def backoff_s(attempt, rng, cap_s):
    """Sleep after failed attempt `attempt` (1-based), jitter included.

    Fixed, not growing (see RETRY_BACKOFF_S); `attempt` is kept in the
    signature so that a schedule that does grow can be recorded as a new
    policy without changing the callers."""
    return min(float(cap_s),
               RETRY_BACKOFF_S * (1.0 + RETRY_JITTER
                                  * (2.0 * rng.random() - 1.0)))


def phase_kind(phase):
    """`A`, `A.1`, `A.retry` -> "A"; `B...` -> "B"; any `.explore` -> "explore"."""
    if ".explore" in str(phase):
        return "explore"
    return str(phase).split(".", 1)[0]


def parse_retry_after(value):
    """`Retry-After` in seconds (delta-seconds or an HTTP-date), or None."""
    if value is None:
        return None
    value = str(value).strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        import email.utils
        when = email.utils.parsedate_to_datetime(value)
        now = datetime.datetime.now(when.tzinfo or datetime.timezone.utc)
        return max(0.0, (when - now).total_seconds())
    except Exception:
        return None


def gateway_trace(resp, headers):
    """What the gateway says about one attempt: its generation id and the
    provider attempts it made, from the body (`providerMetadata` on an
    error, `provider_metadata` on a success) and a few response headers.
    Nothing from the request is read here, so the Authorization header
    cannot reach the log through this path."""
    out = {}
    meta = {}
    if isinstance(resp, dict):
        meta = resp.get("providerMetadata") or resp.get("provider_metadata") \
            or {}
    gw = (meta or {}).get("gateway") or {}
    if isinstance(gw, dict):
        if gw.get("generationId"):
            out["generation_id"] = gw["generationId"]
        routing = gw.get("routing") or {}
        pa = []
        for ma in routing.get("modelAttempts") or []:
            for a in (ma or {}).get("providerAttempts") or []:
                try:
                    ms = float(a["endTime"]) - float(a["startTime"])
                except (KeyError, TypeError, ValueError):
                    ms = None
                pa.append({"provider": a.get("provider"),
                           "status": a.get("statusCode"),
                           "success": a.get("success"), "ms": ms})
        if pa:
            out["provider_attempts"] = pa
        if routing.get("totalProviderAttemptCount") is not None:
            out["provider_attempt_count"] = \
                routing["totalProviderAttemptCount"]
    hdr = {}
    for k, v in (headers or {}).items():
        lk = k.lower()
        if lk == "retry-after" or "generation" in lk or lk in (
                "x-vercel-id", "x-request-id"):
            hdr[lk] = v
    if hdr:
        out["headers"] = hdr
    return out


class JevClient:
    """One HTTP request per phase, logged as JSONL and as a readable line.

    SPEC.ja.md 6: the Authorization header is never written to either log.

    Decision 92 (d): a request is retried on a 5xx, on a 429 (honouring
    `Retry-After`) and on a transport error, with a fixed pause of
    `RETRY_BACKOFF_S` +-`RETRY_JITTER` (capped at `[jev] backoff_cap_s`)
    between attempts, until either
    `[jev] retries` attempts have been made or the next sleep would take the
    request past `[jev] retry_wall_budget_s` of wall clock. Any other status
    ends the request at once. Every attempt is logged.
    """

    def __init__(self, cfg, log_dir, run_id, source_comments="strip"):
        self.cfg = cfg
        # Recorded on every request line: a run has no manifest until it
        # finishes, and the API-only passes never write one at all.
        self.source_comments = source_comments
        self.url = cfg["base_url"].rstrip("/") + cfg["endpoint"]
        self.model = cfg["model"]
        self.key = None
        os.makedirs(log_dir, exist_ok=True)
        self.jsonl_path = os.path.join(log_dir, run_id + ".jsonl")
        self.log_path = os.path.join(log_dir, run_id + ".log")
        self.run_id = run_id
        self.n_lines = sum(1 for _ in open(self.jsonl_path)) \
            if os.path.isfile(self.jsonl_path) else 0
        self.totals = {"requests": 0, "questions": 0, "latency_ms": 0,
                       "max_latency_ms": 0, "input_tokens": 0,
                       "output_tokens": 0, "cost_usd": 0.0}
        # Decision 92 (d): what the gateway did to this run, for the
        # manifest. `requests` counts calls to ask() (a phase re-send is a
        # request of its own), `attempts` the HTTP attempts inside them.
        # `lost_phases` and `lost_rounds` are the proposer's and the round
        # loop's to fill in; `seconds_waiting` is every backoff sleep plus
        # every re-send pause.
        self.gateway = {"requests": 0, "attempts": 0, "landed": 0,
                        "exhausted": 0, "lost_phases": 0, "lost_rounds": 0,
                        "seconds_waiting": 0.0,
                        # Landing tracked body size in Experiment 5; this
                        # is what makes that measurable in the next run.
                        "attempts_by_phase": {
                            k: {"requests": 0, "attempts": 0, "landed": 0,
                                "body_bytes_total": 0,
                                "mean_body_bytes": None}
                            for k in ("A", "B", "explore")}}
        # Injectable for the unit check; nothing else replaces them.
        self._sleep = time.sleep
        self._now = time.monotonic
        if not os.path.isfile(self.log_path):
            with open(self.log_path, "w") as f:
                f.write("# jev-opt request log, run %s\n" % run_id)
                f.write("# ts round phase questions http_status latency_ms "
                        "input_tokens output_tokens cost_usd\n")

    def wait(self, seconds):
        """A pause the gateway made us take, counted in `seconds_waiting`."""
        self._sleep(seconds)
        self.gateway["seconds_waiting"] += seconds

    def _post(self, payload, timeout):
        """One POST. Returns (status, response headers, body bytes); raises
        on a transport error or a timeout."""
        req = urllib.request.Request(
            self.url, data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.key})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers.items()), r.read()
        except urllib.error.HTTPError as e:
            try:
                raw = e.read()
            except Exception:
                raw = b""
            return e.code, dict((e.headers or {}).items()), raw

    def ask(self, state, questions, round_no, phase, site_map):
        """Returns (answers dict, jsonl line number) or (None, line)."""
        if self.key is None:
            self.key = read_api_key(self.cfg["api_key_env"])
        body = {"model": self.model, "state": state, "questions": questions}
        payload = json.dumps(body).encode()
        body_sha = hashlib.sha256(payload).hexdigest()
        cap_n = max(1, int(self.cfg["retries"]))
        budget = float(self.cfg["retry_wall_budget_s"])
        timeout = float(self.cfg["request_timeout_s"])
        rng = random.Random(body_sha)
        status, resp, latency, err = None, None, 0.0, None
        attempts = []            # "HTTP 503", ... as before (failed only)
        attempt_log = []         # one dict per attempt, decision 92 (d)
        waited = 0.0
        t_start = self._now()
        for attempt in range(1, cap_n + 1):
            t0 = self._now()
            ts = datetime.datetime.now().astimezone().isoformat()
            headers, retry_after, retryable = {}, None, True
            try:
                status, headers, raw = self._post(payload, timeout)
                latency = (self._now() - t0) * 1e3
                try:
                    resp = json.loads(raw.decode())
                except Exception:
                    resp = None
                if 200 <= int(status) < 300 and resp is not None:
                    err = None      # a retry that succeeded is not an error
                elif 200 <= int(status) < 300:
                    err = "HTTP %d with a body that is not JSON" % status
                else:
                    err = "HTTP %d" % status
                    retryable = int(status) >= 500 or int(status) == 429
                    if int(status) == 429:
                        retry_after = parse_retry_after(
                            {k.lower(): v for k, v in headers.items()}
                            .get("retry-after"))
            except Exception as e:                       # timeout, DNS, ...
                latency = (self._now() - t0) * 1e3
                status, resp = None, None
                err = "%s: %s" % (type(e).__name__, e)
            a = {"attempt": attempt, "ts": ts, "http_status": status,
                 "latency_ms": round(latency, 1), "error": err,
                 "request_sha256": body_sha, "request_bytes": len(payload),
                 "retry_after": retry_after, "sleep_s": None}
            a.update(gateway_trace(resp, headers))
            attempt_log.append(a)
            if err is None:
                break
            attempts.append(err)
            if not retryable:
                break
            if attempt >= cap_n:
                break
            # `Retry-After` wins over the backoff when it asks for longer;
            # it never shortens it.
            sleep = backoff_s(attempt, rng, self.cfg["backoff_cap_s"])
            if retry_after is not None:
                sleep = max(sleep, retry_after)
            if (self._now() - t_start) + sleep > budget:
                break
            a["sleep_s"] = round(sleep, 3)
            waited += sleep
            self.wait(sleep)

        usage = (resp or {}).get("usage") or {}
        gw = ((resp or {}).get("provider_metadata") or {}).get("gateway") or {}
        try:
            cost = float(gw.get("cost") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        landed = err is None and isinstance(resp, dict) and "answers" in resp

        self.n_lines += 1
        line_no = self.n_lines
        record = {"ts": datetime.datetime.now().astimezone().isoformat(),
                  "run_id": self.run_id, "round": round_no, "phase": phase,
                  "vocab_version": V.VOCAB_VERSION,
                  "state_format": STATE_FORMAT_VERSION,
                  "source_comments": self.source_comments,
                  "site_map": site_map, "request": body, "response": resp,
                  "http_status": status, "latency_ms": round(latency, 1),
                  "error": err, "failed_attempts": attempts,
                  # Decision 92 (d), added fields only.
                  "request_sha256": body_sha, "request_bytes": len(payload),
                  "n_attempts": len(attempt_log), "attempt_log": attempt_log,
                  "seconds_waiting": round(waited, 3),
                  "exhausted": not landed}
        with open(self.jsonl_path, "a") as f:
            f.write(json.dumps(record) + "\n")

        self.totals["requests"] += 1
        self.totals["questions"] += len(questions)
        self.totals["latency_ms"] += latency
        self.totals["max_latency_ms"] = max(self.totals["max_latency_ms"], latency)
        self.totals["input_tokens"] += int(usage.get("input_tokens") or 0)
        self.totals["output_tokens"] += int(usage.get("output_tokens") or 0)
        self.totals["cost_usd"] += cost
        self.gateway["requests"] += 1
        self.gateway["attempts"] += len(attempt_log)
        self.gateway["landed" if landed else "exhausted"] += 1
        kind = phase_kind(phase)
        if kind in self.gateway["attempts_by_phase"]:
            bp = self.gateway["attempts_by_phase"][kind]
            bp["requests"] += 1
            bp["attempts"] += len(attempt_log)
            bp["landed"] += int(landed)
            bp["body_bytes_total"] += len(payload)
            bp["mean_body_bytes"] = round(bp["body_bytes_total"]
                                          / bp["requests"], 1)
        with open(self.log_path, "a") as f:
            f.write("%s r%d %-7s %3d %s %8.1f %7d %6d %.8f%s\n"
                    % (record["ts"], round_no, phase, len(questions),
                       status, latency, int(usage.get("input_tokens") or 0),
                       int(usage.get("output_tokens") or 0), cost,
                       ("  ERROR " + err) if err else
                       ("  (after %d failed attempt(s): %s)"
                        % (len(attempts), ", ".join(attempts))
                        if attempts else "")))
            # Per-attempt detail as comment lines, so a reader of the
            # one-line-per-request format is not disturbed by it.
            if len(attempt_log) > 1 or err:
                f.write("#   request %d bytes sha256 %s, %d attempt(s), "
                        "%.1f s waited\n" % (len(payload), body_sha[:16],
                                             len(attempt_log), waited))
                for a in attempt_log:
                    f.write("#   attempt %d %s http %s %.1f ms%s%s%s\n"
                            % (a["attempt"], a["ts"], a["http_status"],
                               a["latency_ms"],
                               (" gen %s" % a["generation_id"])
                               if a.get("generation_id") else "",
                               (" retry-after %.1f s" % a["retry_after"])
                               if a.get("retry_after") is not None else "",
                               (" then sleep %.1f s" % a["sleep_s"])
                               if a.get("sleep_s") is not None else ""))

        if not landed:
            return None, line_no
        return resp["answers"], line_no

    def write_totals(self, wall_s):
        t = self.totals
        n = max(1, t["requests"])
        with open(self.log_path, "a") as f:
            f.write("\n# totals for run %s\n" % self.run_id)
            f.write("# http requests      %d\n" % t["requests"])
            f.write("# choice questions   %d\n" % t["questions"])
            f.write("# latency total/avg/max ms  %.1f / %.1f / %.1f\n"
                    % (t["latency_ms"], t["latency_ms"] / n, t["max_latency_ms"]))
            f.write("# tokens in/out      %d / %d\n"
                    % (t["input_tokens"], t["output_tokens"]))
            f.write("# cost usd           %.8f\n" % t["cost_usd"])
            f.write("# wall clock of the run s   %.1f\n" % wall_s)
            f.write("# jev share of the run      %.4f%%\n"
                    % (100.0 * (t["latency_ms"] / 1e3) / max(1e-9, wall_s)))


# ---------------------------------------------------------------------------
# proposers
# ---------------------------------------------------------------------------

class RandomProposer:
    name = "random"

    def __init__(self, seed, knobs):
        self.seed = seed
        self.knobs = knobs

    def choose(self, items, ctx, round_no, phase):
        rng = random.Random("%d|%d|%s" % (self.seed, round_no, phase))
        out, why = {}, {}
        for it in items:
            cands = list(candidates_of(it, self.knobs))
            out[it.id] = rng.choice(cands)
            why[it.id] = {"source": "random"}
        return out, why


class JevProposer:
    name = "jev"

    def __init__(self, client, cfg, knobs, max_state_chars,
                 readout="forced_top1", explore=2, explore_revisit=0):
        self.client = client
        self.cfg = cfg
        self.knobs = knobs
        self.max_state_chars = max_state_chars
        self.readout = readout
        self.explore = int(explore)
        self.explore_revisit = int(explore_revisit)

    def choose(self, items, ctx, round_no, phase):
        """The phase's answers, or a lost phase (decision 92 d).

        `_ask` re-sends an exhausted request unchanged up to
        `[jev] phase_resend_max` times. If one of the phase's requests is
        still lost after that, the phase is LOST: `ctx["phase_lost"]` says
        so, no readout and no exploration are run on answers that do not
        exist, and the round loop does not build. Experiment 5 built two
        "half plans" (a phase's answers missing and treated as KEEP_DEFAULT)
        and ran exploration on sites Jev had never answered; neither can
        happen now.
        """
        picks, why, gate = self._ask(items, ctx, round_no, phase)
        ctx["gate"] = gate
        if gate["lost"]:
            ctx["phase_lost"] = gate
            ctx["readout"] = None
            ctx["exploration"] = None
            # The one line printed for it is the round loop's `[gate]`.
            self.client.gateway["lost_phases"] += 1
            return picks, why
        self.read_out(items, picks, why, ctx, phase)
        self.explore_round(items, picks, why, ctx, round_no, phase)
        return picks, why

    def send(self, state, questions, round_no, phase, site_map):
        """One request, re-sent UNCHANGED while it is exhausted, at most
        `[jev] phase_resend_max` more times (decision 92 d).

        No build happens between the sends, so the state is the same state
        and nothing about the request may change; the exhausted lines stay
        in the JSONL. The re-sends are logged as `<phase>.retry`,
        `<phase>.retry2`, ... Returns (answers or None, line_no, gate)."""
        resend_max = int(self.cfg.get("phase_resend_max", 2))
        g0 = dict(self.client.gateway)
        lines = []
        answers, line_no = self.client.ask(state, questions, round_no, phase,
                                           site_map)
        lines.append(line_no)
        n = 0
        while answers is None and n < resend_max:
            n += 1
            print("[%s] the request never got through; re-sending it "
                  "unchanged (%d of %d)" % (phase, n, resend_max))
            self.client.wait(10)
            answers, line_no = self.client.ask(
                state, questions, round_no,
                "%s.retry%s" % (phase, "" if n == 1 else n), site_map)
            lines.append(line_no)
        g1 = self.client.gateway
        gate = {"phase": phase, "lost": answers is None, "sends": n + 1,
                "attempts": g1["attempts"] - g0["attempts"],
                "seconds_waited": round(g1["seconds_waiting"]
                                        - g0["seconds_waiting"], 3),
                "jsonl_lines": lines}
        return answers, line_no, gate

    def explore_round(self, items, picks, why, ctx, round_no, phase):
        """Decision 89 (b): one extra Choice per untried hot site, per round.

        Sent as its own request, after the phase's own answers are in, so
        that the eligible set can require this round's answer at the site to
        be KEEP_DEFAULT. The hint chosen here goes into this round's plan
        beside the argmax entries; it never replaces one.

        A site whose answer does not come back --- a 503, or a choice that is
        not one of the candidates --- is left as it was. Exploration must not
        be able to turn a phase into something the model did not say.
        """
        elig = {}
        pairs = exploration_sites(items, picks, ctx, self.knobs, self.explore,
                                  self.explore_revisit, record=elig)
        rec = {"k": self.explore, "phase": phase,
               "sites": [it.id for it, _c in pairs], "picks": {},
               # Decision 92 (b).
               "revisit": self.explore_revisit,
               "max_visits": EXPLORE_MAX_VISITS,
               "eligible_new": elig.get("eligible_new"),
               "eligible_revisit": elig.get("eligible_revisit"),
               "asked": elig.get("meta"), "pick_detail": {}}
        ctx["exploration"] = rec
        if not pairs:
            return rec
        questions, site_map = exploration_questions(pairs, ctx,
                                                    elig.get("meta"))
        state = state_header(ctx, len(pairs)) + \
            "".join(state_section(it, ctx) for it, _c in pairs)
        # The same unchanged re-send a phase gets (Experiment 4, 1.4 b;
        # decision 92 d): a request that never got through leaves every
        # eligible site at KEEP_DEFAULT, and because the site is then still
        # untried it costs the round its whole exploration slot. A lost
        # exploration request does NOT lose the round --- the argmax plan is
        # whole without it --- and is recorded as `lost` here and as
        # `explore_lost` on the round.
        answers, line_no, gate = self.send(state, questions, round_no,
                                           "%s.explore" % phase, site_map)
        rec["gate"] = gate
        rec["lost"] = gate["lost"]
        if gate["lost"]:
            self.client.gateway["lost_phases"] += 1
            print("[%s.explore] LOST after %d send(s), %d HTTP attempt(s), "
                  "%.1f s waited; the round is built without exploration"
                  % (phase, gate["sends"], gate["attempts"],
                     gate["seconds_waited"]))
        ref = "%s.jsonl#%d" % (self.client.run_id, line_no)
        for it, cands in pairs:
            a = (answers or {}).get(it.qname) or {}
            pick = a.get("choice")
            if pick not in cands:
                print("[%s.explore] %s: no usable answer (%r), the site "
                      "stays KEEP_DEFAULT" % (phase, it.label, pick))
                continue
            picks[it.id] = pick
            w = why.setdefault(it.id, {})
            w["argmax"] = V.KEEP_DEFAULT
            w["source"] = "exploration"
            w["exploration"] = True
            w["readout"] = "exploration"
            w["answer_ref"] = ref
            w["confidence"] = a.get("confidence")
            w["probabilities"] = a.get("probabilities")
            rec["picks"][it.id] = pick
            m = (elig.get("meta") or {}).get(it.id) or {}
            probs = a.get("probabilities") if isinstance(
                a.get("probabilities"), dict) else {}
            def p_of(c):
                try:
                    return float(probs.get(c) or 0.0)
                except (TypeError, ValueError):
                    return 0.0
            offered = list(cands)
            order = sorted(offered, key=lambda c: (-p_of(c),
                                                   offered.index(c)))
            detail = {"kind": m.get("kind", "new"),
                      "visit_no": m.get("visit_no", 1),
                      "tried_before": m.get("tried") or [],
                      "candidates": offered,
                      "pick_rank": order.index(pick) + 1,
                      "pick_p": p_of(pick) if probs else None}
            rec["pick_detail"][it.id] = detail
            w["exploration_kind"] = detail["kind"]
            w["visit_no"] = detail["visit_no"]
            w["candidates_offered"] = offered
            w["pick_rank"] = detail["pick_rank"]
            w["pick_p"] = detail["pick_p"]
            if detail["kind"] == "revisit":
                print("[%s.explore] %s: revisit %d, tried here so far %s; "
                      "trying %s" % (phase, it.label, detail["visit_no"],
                                     ", ".join(V.spec_spelling_safe(t) for t
                                               in detail["tried_before"]),
                                     V.spec_spelling_safe(pick)))
            else:
                print("[%s.explore] %s: nothing has been tried here; trying "
                      "%s" % (phase, it.label, V.spec_spelling_safe(pick)))
        return rec

    def _ask(self, items, ctx, round_no, phase):
        """Returns (picks, why, gate). A phase split into several requests
        (SPEC.ja.md 6) is lost if any one of them is: half a phase is half
        a plan."""
        picks, why = {}, {}
        gate = {"phase": phase, "lost": False, "sends": 0, "attempts": 0,
                "seconds_waited": 0.0, "jsonl_lines": [], "requests": []}
        for batch_i, batch in enumerate(self._batches(items, ctx)):
            questions, site_map = questions_for(batch, ctx, self.knobs)
            state = state_header(ctx, len(batch)) + \
                "".join(state_section(it, ctx) for it in batch)
            answers, line_no, g = self.send(
                state, questions, round_no,
                "%s%s" % (phase, "" if batch_i == 0 else ".%d" % batch_i),
                site_map)
            gate["requests"].append(g)
            gate["lost"] = gate["lost"] or g["lost"]
            gate["sends"] += g["sends"]
            gate["attempts"] += g["attempts"]
            gate["seconds_waited"] = round(gate["seconds_waited"]
                                           + g["seconds_waited"], 3)
            gate["jsonl_lines"] += g["jsonl_lines"]
            ref = "%s.jsonl#%d" % (self.client.run_id, line_no)
            for it in batch:
                a = (answers or {}).get(it.qname) or {}
                pick = a.get("choice")
                conf = a.get("confidence")
                reason = "jev"
                if pick not in candidates_of(it, self.knobs):
                    pick, reason = V.KEEP_DEFAULT, (
                        "no answer" if answers is None else
                        "answer %r is not a candidate" % (pick,))
                elif conf is not None and conf < float(self.cfg["min_confidence"]):
                    pick, reason = V.KEEP_DEFAULT, \
                        "confidence %.3f below %.3f" % (conf, float(
                            self.cfg["min_confidence"]))
                picks[it.id] = pick
                why[it.id] = {"source": reason, "answer_ref": ref,
                              "confidence": conf,
                              "probabilities": a.get("probabilities")}
        return picks, why, gate

    def read_out(self, items, picks, why, ctx, phase):
        """Decision 71: rank by `1 - P(KEEP_DEFAULT)`; never leave a phase
        empty.

        The argmax alone throws the probabilities away, and a phase in which
        every argmax is `KEEP_DEFAULT` writes no plan entry, rebuilds the
        baseline and measures nothing --- which is how Experiment 3 spent
        five rounds. `forced_top1` (the default) keeps the argmax wherever
        Jev reached for a hint, and where it did not it applies the ONE hint
        Jev came closest to reaching for: the top-ranked site's own
        highest-probability non-`KEEP_DEFAULT` candidate. This is not a
        better search, it is a search that moves; whether the hint it tries
        is worth anything is the oracle's question.

        The whole ranking is recorded either way, so `--readout argmax` runs
        the old behaviour with the same record attached.
        """
        ranking = rank_by_non_keep(items, why, self.knobs)
        for it in items:
            why.setdefault(it.id, {})["readout"] = "argmax"
        asked = [it for it in items if it.kind != "build"]
        all_keep = bool(asked) and all(
            picks.get(it.id, V.KEEP_DEFAULT) == V.KEEP_DEFAULT
            for it in asked)
        rec = {"rule": self.readout, "phase": phase,
               "all_keep_default": all_keep, "forced": None,
               "ranking": ranking}
        if all_keep and self.readout == "forced_top1" and ranking:
            top = ranking[0]
            sid = top["site_id"]
            picks[sid] = top["best_non_keep"]
            w = why.setdefault(sid, {})
            w["readout"] = "forced_top1"
            w["argmax"] = V.KEEP_DEFAULT
            w["readout_rank"] = 1
            w["readout_score"] = top["score"]
            rec["forced"] = top
            print("[%s] every answer was KEEP_DEFAULT; readout applies %s at "
                  "%s (1-P(KEEP) = %.3f, P(hint) = %.3f)"
                  % (phase, top["best_non_keep"], top["label"],
                     top["score"], top["p_best"]))
        elif all_keep and ranking:
            print("[%s] every answer was KEEP_DEFAULT; --readout argmax "
                  "leaves the phase empty (top of the ranking was %s at %s)"
                  % (phase, ranking[0]["best_non_keep"], ranking[0]["label"]))
        ctx["readout"] = rec
        return rec

    def _batches(self, items, ctx):
        """Split only when the state would be too large (SPEC.ja.md 6)."""
        if not items:
            return []
        overhead = len(state_header(ctx, len(items)))
        batches, cur, size = [], [], overhead
        for it in items:
            n = len(state_section(it, ctx))
            if cur and size + n > self.max_state_chars:
                batches.append(cur)
                cur, size = [], overhead
            cur.append(it)
            size += n
        if cur:
            batches.append(cur)
        return batches


class OracleProposer:
    """One-factor sweep plus one combination arm (SPEC.ja.md 2).

    The arm list is not known up front: the combination arm needs the results
    of the sweep, and the loop sites of the sweep are the ones the
    all-KEEP_DEFAULT build dumps. `next_arm` therefore returns one arm at a
    time and `None` when the sweep and the combination are both done.

    Build count is sum(sites x candidates) + 1 combination + 1 baseline, which
    is why `[search] max_sites` is a hard error rather than a warning.
    """
    name = "oracle"

    def __init__(self, knobs):
        self.knobs = knobs
        self.arms = None
        self.emitted = 0
        self.combination_done = False

    def plan_arms(self, fn_list, loop_list, build_list, phase="all"):
        """The one-factor arms, optionally restricted to one phase.

        `phase` is `--oracle-phase`: `A` sweeps the function attributes (and
        the `__build__` pseudo-site, which is part of phase A's plan), `B`
        sweeps the loop hints, `all` is both. Restricting is a way to run the
        two halves of the sweep as separate jobs on a machine that may only
        build one thing at a time --- it changes nothing about an arm: every
        arm is still one candidate at one site with every other site at
        KEEP_DEFAULT, and a phase-A run's rounds still build both phases.
        """
        groups = {"A": list(fn_list) + list(build_list),
                  "B": list(loop_list),
                  "all": list(fn_list) + list(build_list) + list(loop_list)}
        if phase not in groups:
            raise ValueError("unknown oracle phase %r" % phase)
        arms = []
        for it in groups[phase]:
            for cand in candidates_of(it, self.knobs):
                if cand == V.KEEP_DEFAULT:
                    continue
                arms.append({"kind": "one-factor", "site": it.id,
                             "site_kind": it.kind, "candidate": cand,
                             "choices": {it.id: cand}})
        self.arms = arms
        return arms

    def next_arm(self, history):
        if self.emitted < len(self.arms):
            arm = self.arms[self.emitted]
            self.emitted += 1
            return arm
        if self.combination_done:
            return None
        self.combination_done = True
        # The readout a site is ranked on: its own kernel's workload where
        # the target has one (results.md "Hint benchmark (design)" 103), the
        # aggregate everywhere else. `readout` records which was used.
        best, best_conf = {}, {}
        for h in history:
            if not h["correct"]:
                continue
            r = h.get("kernel_ratio")
            readout = h.get("own_workload") if r is not None else "aggregate"
            if r is None:
                r = h.get("ratio")
            if r is None:
                continue
            ci = (h.get("kernel_ci95") if h.get("kernel_ratio") is not None
                  else h.get("ci95")) or [None, None]
            # The confirmation flag has to come from the same readout the
            # ranking uses. `score_confirmation` scores the two separately:
            # `confirmed` is the arm's own kernel workload, `confirmed_
            # aggregate` is the eight-way (three-way on jaq) mean. On a
            # target with no per-site workload --- every target but
            # hintbench, because `own_workload_of` returns None there ---
            # `kernel` is never populated, so `confirmed` is False for every
            # arm and reading it here would leave `best_conf` empty and make
            # the combination arm an empty plan, i.e. the baseline. Ranking
            # on the aggregate and confirming on the kernel is also simply
            # inconsistent. So: whichever readout `r` came from, that is the
            # one that has to have survived two batches.
            for site, cand in h["choices"].items():
                if cand == V.KEEP_DEFAULT:
                    continue
                per_kernel = h.get("kernel_ratio") is not None
                row = {"candidate": cand, "ratio": r, "ci95": ci,
                       "readout": readout, "aggregate_ratio": h.get("ratio"),
                       "confirmed": bool(h.get("confirmed") if per_kernel
                                         else h.get("confirmed_aggregate")),
                       "confirm_ratio": (h.get("confirm_kernel_ratio")
                                         if per_kernel
                                         else h.get("confirm_ratio")),
                       "code_class": h.get("code_class"),
                       "status": h.get("status")}
                if site not in best or r > best[site]["ratio"]:
                    best[site] = row
                if row["confirmed"] and (site not in best_conf
                                         or r > best_conf[site]["ratio"]):
                    best_conf[site] = row
        # A site joins the combination only if its best arm was **confirmed**
        # --- its interval excluded 1 with the same sign in two independent
        # batches (decision 80 a) --- and the effect is a gain. One batch is
        # not evidence at this noise floor: on jaq 20 of 48 provably
        # code-identical builds produced an interval that excluded 1
        # (results.md "Oracle A (jaq)" 113), and the one-batch rule this
        # replaces combined twelve such arms into a plan worth +2.15% where
        # the twelve claims multiplied to +22.4%. Both weaker rules are
        # recorded beside the chosen set so the difference stays visible.
        chosen = {s: d["candidate"] for s, d in best_conf.items()
                  if d["ratio"] > 1.0}
        one_batch = {s: d["candidate"] for s, d in best.items()
                     if d["ci95"][0] is not None and d["ci95"][0] > 1.0}
        point = {s: d["candidate"] for s, d in best.items()
                 if d["ratio"] > 1.0}
        return {"kind": "combination", "site": None, "candidate": None,
                "choices": chosen,
                "selected_by": "confirmed in two batches, ratio > 1",
                "per_site_best": best,
                "per_site_best_confirmed": best_conf,
                "one_batch_rule_would_pick": one_batch,
                "point_rule_would_pick": point}

    def choose(self, items, ctx, round_no, phase):
        arm = ctx["arm"]
        picks, why = {}, {}
        for it in items:
            pick = arm["choices"].get(it.id, V.KEEP_DEFAULT)
            if pick not in candidates_of(it, self.knobs):
                pick = V.KEEP_DEFAULT
            picks[it.id] = pick
            why[it.id] = {"source": "oracle/" + arm["kind"]}
        return picks, why


# ---------------------------------------------------------------------------
# plans
# ---------------------------------------------------------------------------

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def fn_attrs_from(picks, items, why, knobs):
    """Plan `fn_attrs`: one entry per resolved linkage name (decision 61c).

    The plugin matches a `fn` string against the linkage name first and
    against the mark rule second (jev.cpp JevApplyFnAttrs). Naming the
    resolved linkage names is exact: a generic mark fans out to one entry per
    monomorphization, which is what "apply to every monomorphization" means,
    and no unrelated function can match by accident.
    """
    entries = []
    for it in items:
        if it.kind != "fn":
            continue
        pick = picks.get(it.id, V.KEEP_DEFAULT)
        if pick == V.KEEP_DEFAULT:
            continue
        frag = V.fragment_for("fn", pick)
        for linkage in sorted(it.meta["linkages"]):
            e = {"fn": linkage}
            e.update(frag)
            e["jev_site_id"] = it.id
            e["jev_choice"] = pick
            e["jev_readout"] = (why.get(it.id) or {}).get("readout")
            e["answer_ref"] = (why.get(it.id) or {}).get("answer_ref")
            # Decision 89 (b): this entry is here because nothing had
            # ever been tried at the site, not because it was the
            # argmax of the phase's own question.
            if (why.get(it.id) or {}).get("exploration"):
                e["exploration"] = True
            entries.append(e)
    entries.sort(key=lambda e: e["fn"])
    return entries


def plan_signature(fn_attrs, loop_md):
    """What makes two rounds the same build (decision 89 a).

    sha256 of the hints alone: the annotation fields (`jev_site_id`,
    `jev_choice`, `jev_readout`, `answer_ref`, `exploration`) record how a
    plan was arrived at and the `plan_id` records which round wrote it, and
    neither changes a single instruction. Rounds 2 to 5 of Experiment 4 are
    one binary with four different `plan_sha256` values, which is exactly why
    the acceptance rule could promote the same plan twice.
    """
    keep_fn = ("fn", "inline", "cold", "hot", "align")
    keep_loop = ("key", "stage", "unroll_count", "unroll_disable",
                 "vectorize_width", "interleave_count", "vectorize_enable")
    core = {
        "fn_attrs": sorted(({k: v for k, v in e.items() if k in keep_fn}
                            for e in fn_attrs), key=lambda e: e["fn"]),
        "loop_md": sorted(({k: v for k, v in e.items() if k in keep_loop}
                           for e in loop_md), key=lambda e: e["key"]),
    }
    return hashlib.sha256(canonical(core).encode()).hexdigest()


def basis_of(fn_attrs):
    """sha256 of the applied attribute set, ignoring the annotation fields."""
    core = sorted(({k: v for k, v in e.items()
                    if k in ("fn", "inline", "cold", "hot", "align")}
                   for e in fn_attrs), key=lambda e: e["fn"])
    return hashlib.sha256(canonical(core).encode()).hexdigest()


def loop_md_from(picks, items, why):
    entries = []
    for it in items:
        if it.kind != "loop":
            continue
        pick = picks.get(it.id, V.KEEP_DEFAULT)
        if pick == V.KEEP_DEFAULT:
            continue
        e = {"key": it.meta["key"]}
        if it.meta.get("stage"):
            e["stage"] = it.meta["stage"]
        e.update(V.fragment_for("loop", pick))
        e["jev_site_id"] = it.id
        e["jev_choice"] = pick
        e["jev_readout"] = (why.get(it.id) or {}).get("readout")
        e["answer_ref"] = (why.get(it.id) or {}).get("answer_ref")
        # Decision 89 (b): this entry is here because nothing had
        # ever been tried at the site, not because it was the
        # argmax of the phase's own question.
        if (why.get(it.id) or {}).get("exploration"):
            e["exploration"] = True
        entries.append(e)
    entries.sort(key=lambda e: e["key"])
    return entries


def write_plan(path, plan_id, fn_attrs, loop_md, basis):
    doc = {"schema_version": 1, "plan_id": plan_id,
           "vocab_version": V.VOCAB_VERSION, "basis": basis,
           "fn_attrs": fn_attrs, "loop_md": loop_md}
    text = json.dumps(doc, indent=2) + "\n"
    with open(path, "w") as f:
        f.write(text)
    return hashlib.sha256(text.encode()).hexdigest()


def build_knob_flags(picks, knobs):
    flags = []
    pick = picks.get(V.BUILD_SITE_ID, V.KEEP_DEFAULT)
    flag = V.fragment_for("build", pick, knobs) if knobs else None
    if flag:
        flags.append(flag)
    return flags


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

def strip_copy(src, dst):
    shutil.copy2(src, dst)
    subprocess.run(["strip", "-s", dst], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dst


# Measurement protocols (results.md 170). v1 is decision 80 as it has run
# since jaq's oracle A; v2 is selected explicitly and changes only cost:
# a confirmation batch only where the first batch reached the MDE, no A/A
# leg in the oracle's one-factor arm batches, and `reps_oracle` repetitions
# there. `--protocol` is a preset; an explicit key or flag wins over it.
PROTOCOLS = {
    "v1": {"confirm_when": "ci", "aa_leg": True, "reps_oracle": None},
    "v2": {"confirm_when": "mde", "aa_leg": False, "reps_oracle": 8},
}
CONFIRM_RULES = ("ci", "mde")


def batch_labels(aa=True):
    """The label names of one timing batch. `aa` False drops the in-run
    A/A copy of the baseline (protocol v2, oracle arm batches only)."""
    return ["base", "cand", "aa"] if aa else ["base", "cand"]


def confirm_trigger(rec, own_wl, rule, mde=None):
    """Which readouts of a first batch call for a confirmation batch.

    rule "ci" (protocol v1, decision 80 a): the 95% CI excludes 1.
    rule "mde" (protocol v2): |ratio - 1| >= MDE, where MDE is `mde` if
    given (the frozen `[evaluation] mde` / `--mde`) and otherwise the
    batch's own `rec["mde"]` = max(2 x worst half-width, 3%) from bench.py
    stats. A difference below the MDE is reported as flat with one batch.
    Returns the list of readouts that fired ("aggregate" and/or own_wl).
    """
    if rule not in CONFIRM_RULES:
        raise ValueError("unknown confirm rule %r" % rule)
    thr = mde if mde is not None else rec.get("mde")
    thr = max(float(thr if thr is not None else 0.03), 0.03)

    def fires(ratio, ci):
        if rule == "ci":
            return bool(excludes_one(ci))
        return ratio is not None and abs(ratio - 1.0) >= thr
    fired = []
    if fires(rec.get("ratio"), rec.get("ci95")):
        fired.append("aggregate")
    k = rec.get("kernel")
    if k and fires(k.get("ratio"), k.get("ci95")):
        fired.append(own_wl)
    return fired


def measure(cand_bin, base_bin, shell, out_dir, reps, warmup, seed, resamples,
            aa=True):
    """Interleaved timing of cand vs base vs an in-run A/A copy of base.

    `aa` False times base and cand only (protocol v2's oracle arm batches);
    every consumer then sees `aa: null`."""
    timing = os.path.join(out_dir, "timing")
    os.makedirs(timing, exist_ok=True)
    labels = [("base", strip_copy(base_bin, os.path.join(timing, "base"))),
              ("cand", strip_copy(cand_bin, os.path.join(timing, "cand")))]
    if aa:
        labels.append(("aa", strip_copy(base_bin, os.path.join(timing, "aa"))))
    samples = os.path.join(out_dir, "samples.json")
    argv = [sys.executable, BENCH, "run", "--out", samples,
            "--cpu", shell["bench_cpu"], "--warmup", str(warmup),
            "--runs", str(reps), "--shuffle", str(seed),
            "--gap-ms", shell["bench_gap_ms"], "--stdout", shell["bench_stdout"]]
    for name, path in labels:
        argv += ["--label", "%s=%s" % (name, path)]
    for w in shell["workloads"]:
        argv += ["--workload", w]
    p = subprocess.run(argv, text=True, capture_output=True)
    if p.returncode != 0:
        return None, "bench.py run failed: %s\n%s" % (p.stdout[-2000:],
                                                      p.stderr[-2000:])
    stats_json = os.path.join(out_dir, "stats.json")
    p = subprocess.run([sys.executable, BENCH, "stats", samples,
                        "--base", "base", "--json", stats_json,
                        "--resamples", str(resamples), "--seed", str(seed)],
                       text=True, capture_output=True)
    if p.returncode != 0:
        return None, "bench.py stats failed: %s" % p.stderr[-2000:]
    with open(os.path.join(out_dir, "stats.md"), "w") as f:
        f.write(p.stdout)
    stats = json.load(open(stats_json))
    # Decision 97: a batch whose exec paths are not all in the pinned argv[0]
    # class reads a different k5 mode on hintbench; it is not a measurement.
    want = B.chunk(B.ARGV0_LEN)
    if stats.get("argv0_class") != want:
        return None, ("argv0 class check failed (want len %d class %d for "
                      "every label): %s" % (B.ARGV0_LEN, want, ", ".join(
                          "%s len %s class %s" % (n, d.get("len"), d.get("class"))
                          for n, d in (stats.get("argv0") or {}).items())
                          or "no argv0 in stats.json"))
    return stats, None


def argv0_record(stats):
    """The batch's argv[0] length and class, for rounds.jsonl (decision 97)."""
    a0 = stats.get("argv0") or {}
    lens = sorted({d["len"] for d in a0.values()})
    return {"len": lens[0] if len(lens) == 1 else lens,
            "class": stats.get("argv0_class")}


def nm_table(binary):
    """`nm -S --defined-only`, sorted: every symbol's address, size and name.

    `norm_code_diff.py` normalises addresses away on purpose, so it is blind
    to a build that moved code without changing an instruction --- which is
    exactly what `align=N` does. The pair "same normalised instructions AND
    same symbol table" is the no-op test of decision 80 (b); the symbol table
    alone separates the alignment arms from the ones that changed nothing at
    all (results.md "Oracle A (jaq)" 113 split the 90 arms that way).
    """
    out = subprocess.run(["nm", "-S", "--defined-only", binary],
                         capture_output=True, text=True, check=True).stdout
    return sorted(line.rstrip() for line in out.splitlines() if line.strip())


def code_class(base_bin, cand_bin, base_norm=None, base_nm=None):
    """Classify a build against the baseline, without timing it.

    Returns (klass, changed_symbols, detail):

      "identical"  same normalised instruction sequence for every symbol and
                   the same symbol table: the arm is the baseline, and
                   decision 80 (b) says do not spend a batch on it.
      "layout"     same instructions, different addresses or sizes: the code
                   moved but did not change.
      "code"       at least one symbol's instruction sequence changed.
    """
    import norm_code_diff as N
    if base_norm is None:
        base_norm = N.norm_bodies(base_bin)[0]
    if base_nm is None:
        base_nm = nm_table(base_bin)
    cur, _ = N.norm_bodies(cand_bin)
    changed = sorted(k for k in base_norm if k in cur and base_norm[k] != cur[k])
    gone = sorted(k for k in base_norm if k not in cur)
    new = sorted(k for k in cur if k not in base_norm)
    cur_nm = nm_table(cand_bin)
    detail = {"n_symbols": len(cur), "n_symbols_base": len(base_norm),
              "changed": len(changed), "only_in_base": len(gone),
              "only_here": len(new), "symbol_table_same": cur_nm == base_nm}
    if changed or gone or new:
        return "code", changed + gone + new, detail
    if cur_nm != base_nm:
        return "layout", [], detail
    return "identical", [], detail


def excludes_one(ci):
    """+1 if the interval is wholly above 1, -1 if wholly below, else 0."""
    if not ci or ci[0] is None or ci[1] is None:
        return 0
    if ci[0] > 1.0:
        return 1
    if ci[1] < 1.0:
        return -1
    return 0


def own_workload_of(site_id, workloads):
    """The workload a one-factor arm's own site is measured on, or None.

    `targets/hintbench` has one workload per kernel and results.md "Hint
    benchmark (design)" 103 freezes the readout: "the ground truth for kernel
    N is the ratio on workload kN, not the eight-way geometric mean (a 10%
    win on one kernel is 1.2% in the mean, under the minimum detectable
    effect of decision 16)". So an arm at a `k5_*` site is read off workload
    `k5`. On every other target no workload is named after the site and this
    returns None, which puts the aggregate back in charge --- the behaviour
    every run before this one had.
    """
    if not site_id:
        return None
    m = re.search(r"\bk(\d+)_", site_id)
    if not m:
        return None
    name = "k" + m.group(1)
    return name if name in workloads else None


def read_correctness(path):
    """The whole of run_correctness's output, line for line.

    Not a parse: the per-target procedures in target_common.sh write
    different shapes (`name sha256` for jaq/zopfli/oxipng, the toy's own
    checksum block for the toy), so anything that picks a field out of a line
    silently stops checking on some target. Comparing the lines themselves is
    the correctness gate of SPEC.ja.md 2 for every target at once.
    """
    return [line.rstrip("\n") for line in open(path)]


# ---------------------------------------------------------------------------
# the search
# ---------------------------------------------------------------------------

class Search:

    def __init__(self, args, cfg):
        self.args = args
        self.cfg = cfg
        self.target = args.target
        self.out = os.path.abspath(args.out)
        os.makedirs(self.out, exist_ok=True)
        self.run_id = args.run_id or os.path.basename(self.out.rstrip("/"))
        self.knobs = list(cfg["search"]["build_knobs"])
        self.vocab = args.vocab
        # v3's state template is v2's (see STATE_FORMATS): the verdict block,
        # the platform block and the V2 wording are shared, only the function
        # candidates and one verdict line differ.
        self.state_v2 = (args.vocab in ("v2", "v3", "v4", "v5", "v6"))
        V.set_version(args.vocab)
        set_state_format(args.vocab)
        # Decision 92 (c): the post_vectorize untried line is its own state
        # format, v5.1, and exists only on top of vocabulary v5.
        self.pv_untried = getattr(args, "pv_untried", "off") == "on"
        if self.pv_untried:
            if args.vocab != "v5":
                sys.exit("--pv-untried on is only defined for --vocab v5 "
                         "(state format %s); got --vocab %s"
                         % (STATE_FORMATS["v5.1"], args.vocab))
            set_state_format("v5.1")
        self.demangler = Demangler()
        self._platform = None
        self.marks = read_marks(args.marks)
        self.sidecar = load_sidecar(args.sites)
        self.shell = shell_config(self.target, args.bench_set)
        self.reps = args.n if args.n is not None else int(
            cfg["evaluation"]["repetitions"])
        self.warmup = args.warmup if args.warmup is not None else int(
            cfg["evaluation"]["warmup"])
        self.resolve_protocol(args, cfg["evaluation"])
        # --seed-offset (default 0, identical behaviour) shifts the base
        # seed for the random proposer, the per-round shuffle (self.seed +
        # round_no) and the confirmation batch (self.seed + 100000 +
        # round_no) alike, so offsets 0/1000/2000 cannot collide as long as
        # a run stays under 1000 rounds (decision 98).
        self.seed_offset = getattr(args, "seed_offset", 0) or 0
        self.seed = int(cfg["evaluation"]["seed"]) + self.seed_offset
        self.resamples = int(cfg["evaluation"]["resamples"])
        self.target_dir = os.path.join(REPO, "target-%s-jevsearch" % self.target)
        self.rounds_path = os.path.join(self.out, "rounds.jsonl")
        self.history = []
        # Every round record written so far, lost ones included.
        self.n_rounds = 0
        # `plan_sig` is the empty plan's: the incumbent at round 0 is the
        # baseline, and a round whose plan is empty rebuilds it (decision
        # 89 a). `batches` collects every independent batch measured on the
        # incumbent's own binary, which is what makes the batch-to-batch
        # spread reportable.
        self.best = {"round": 0, "ratio": 1.0, "plan": None,
                     "label": "baseline",
                     "plan_sig": plan_signature([], []), "batches": []}
        self.jev = None
        self.t0 = time.time()

    def resolve_protocol(self, args, ev):
        """confirm_when / aa_leg / reps_oracle / mde: flag > config >
        --protocol preset > protocol v1 (results.md 170)."""
        preset = PROTOCOLS[getattr(args, "protocol", None) or "v1"]
        explicit = {"confirm_when": getattr(args, "confirm_when", None),
                    "aa_leg": {"on": True, "off": False}.get(
                        getattr(args, "aa_leg", None)),
                    "reps_oracle": getattr(args, "reps_oracle", None)}
        got = {}
        for k in ("confirm_when", "aa_leg", "reps_oracle"):
            if explicit[k] is not None:
                got[k] = explicit[k]
            elif getattr(args, "protocol", None):
                got[k] = preset[k]
            else:
                got[k] = ev.get(k, DEFAULTS["evaluation"][k])
        if got["confirm_when"] not in CONFIRM_RULES:
            sys.exit("[evaluation] confirm_when must be one of %s, got %r"
                     % (CONFIRM_RULES, got["confirm_when"]))
        if isinstance(got["aa_leg"], str):
            got["aa_leg"] = got["aa_leg"].lower() in ("true", "on", "1")
        self.confirm_when = got["confirm_when"]
        self.aa_leg = bool(got["aa_leg"])
        self.reps_oracle = int(got["reps_oracle"]) if got["reps_oracle"] \
            else self.reps
        mde = getattr(args, "mde", None)
        if mde is None:
            mde = ev.get("mde")
        self.mde = float(mde) if mde is not None else None
        v1 = (self.confirm_when == "ci" and self.aa_leg
              and self.reps_oracle == self.reps)
        v2 = (self.confirm_when == "mde" and not self.aa_leg
              and self.reps_oracle < self.reps)
        self.protocol = {"name": "v1" if v1 else ("v2" if v2 else "custom"),
                         "preset": getattr(args, "protocol", None),
                         "confirm_when": self.confirm_when,
                         "aa_leg_oracle_arms": self.aa_leg,
                         "reps": self.reps, "reps_oracle": self.reps_oracle,
                         "mde": self.mde,
                         "mde_source": ("frozen" if self.mde is not None
                                        else "per batch, max(2 x worst "
                                        "half-width, 3%)")}
        if not v1:
            print("[protocol] %s: confirm_when=%s, A/A leg in oracle "
                  "one-factor arms %s, reps %d (oracle arms %d), MDE %s"
                  % (self.protocol["name"], self.confirm_when,
                     "on" if self.aa_leg else "off", self.reps,
                     self.reps_oracle, "%.4f" % self.mde if self.mde
                     else "per batch"))

    # -- baseline ---------------------------------------------------------

    def baseline(self):
        bdir = self.args.baseline_dir or os.path.join(self.out, "baseline")
        bdir = os.path.abspath(bdir)
        meta_path = os.path.join(bdir, "baseline.json")
        if os.path.isfile(meta_path):
            print("[baseline] reusing %s" % bdir)
            self.base_dir = bdir
            return json.load(open(meta_path))
        os.makedirs(bdir, exist_ok=True)
        reports = os.path.join(bdir, "reports")
        shutil.rmtree(reports, ignore_errors=True)
        os.makedirs(reports)
        log = os.path.join(bdir, "build.log")
        print("[baseline] building with JEV_MODE=dump ...")
        rc = sh_build(self.target, self.target_dir, log,
                      self.plugin_knobs(),
                      {"JEV_MODE": "dump",
                       "JEV_MARKS": os.path.abspath(self.args.marks),
                       "JEV_REPORT_DIR": reports})
        if rc != 0:
            sys.exit("baseline build failed; see %s" % log)
        src = os.path.join(self.target_dir, self.shell["triple"], "release",
                           self.shell["bin_name"])
        binary = os.path.join(bdir, "bin")
        shutil.copy2(src, binary)
        corr = os.path.join(bdir, "correctness.txt")
        sh_correctness(self.target, binary, corr)
        meta = {"dir": bdir, "bin": binary, "correctness": corr,
                "reports": reports, "log": log,
                "bin_sha256": sha256_file(binary)}
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=1)
        self.base_dir = bdir
        return meta

    def site_set_keys(self):
        """The frozen loop-site set for the experiment.

        SPEC.ja.md 2 compares jev, random and oracle over the SAME site set,
        and `targets/jaq/sites.json` carries the pre-registered mechanical
        rule that produced it (drop keys the training profile never entered,
        drop trip count < 2, keep the top 3 by hotness per mark: 16 keys).
        `--site-set` names which list in that file to use; without it the
        per-mark cap is preferred and the driver falls back to every
        `loop_in_mark` site when the file carries none.
        """
        doc = self.sidecar["raw"]
        name = self.args.site_set
        if not name:
            return self.sidecar["site_allow"]
        node, path = doc, []
        for part in name.split("."):
            path.append(part)
            node = (node or {}).get(part) if isinstance(node, dict) else None
        if not isinstance(node, list):
            avail = []
            for section, body in (doc or {}).items():
                if isinstance(body, dict):
                    avail += ["%s.%s" % (section, k) for k, v in body.items()
                              if isinstance(v, list) and v
                              and isinstance(v[0], str)]
            # One alias, because the frozen site set is referred to by the
            # rule that made it ("top 3 by hotness per mark") and by the
            # field scripts/jaq_sites_report.py writes it under.
            alias = {"oracle.selected_keys_top3":
                     "oracle.selected_keys_topk_per_mark",
                     "selected_keys_top3":
                     "oracle.selected_keys_topk_per_mark"}.get(name)
            if alias and alias in avail:
                sec, _, field = alias.partition(".")
                node = doc[sec][field]
                print("[sites] --site-set %s resolved to %s" % (name, alias))
            else:
                sys.exit("--site-set %s is not a list of keys in %s; "
                         "available: %s" % (name, self.args.sites,
                                            ", ".join(sorted(avail)) or "none"))
        return set(node)

    def pick_loops(self, sites):
        items = loop_items(sites, self.sidecar)
        if self.site_allow is None:
            return items
        return [i for i in items if i.id in self.site_allow]

    def batch_plan(self, arm):
        """(repetitions, A/A leg?) of a round's first timing batch. Only an
        oracle one-factor arm takes `reps_oracle` and may drop the A/A leg
        (protocol v2); search rounds and the combination arm do not."""
        one_factor = (arm or {}).get("kind") == "one-factor"
        return ((self.reps_oracle if one_factor else self.reps),
                bool(self.aa_leg or not one_factor))

    def oracle_loops(self, loops):
        """`--site-filter vectorized`: the oracle's loop arms only at the
        loops the baseline dump's `post_vectorize` record says LLVM
        vectorized (results.md 170, staging). Arms only: the round's plan
        and its phase-B items are unchanged, so an arm is still one
        candidate at one site with every other site at KEEP_DEFAULT.

        This filter is lossy by construction: on zopfli the only gains and
        losses were `unroll_count` arms on UNvectorized loops (results.md
        168), so it is meant for the width / interleave / unroll_disable
        stage, not for a whole loop sweep (docs/search-driver.md)."""
        mode = getattr(self.args, "site_filter", "all") or "all"
        if mode == "all":
            return loops
        if self.args.proposer != "oracle":
            sys.exit("--site-filter is an oracle staging option; jev, random "
                     "and oracle must share one site set (SPEC.ja.md 2)")
        recs = [i for i in loops
                if isinstance(i.meta.get("post_vectorize"), dict)
                and i.meta["post_vectorize"].get("watched")]
        if not recs:
            sys.exit("--site-filter vectorized: no loop in the baseline dump "
                     "carries a post_vectorize record (baseline built with an "
                     "older plugin?); rebuild the baseline or use --site-set")
        kept = [i for i in recs
                if i.meta["post_vectorize"].get("exists")
                and i.meta["post_vectorize"].get("isvectorized")]
        print("[sites] --site-filter vectorized keeps %d of %d loop sites "
              "for the oracle's arms: %s" % (len(kept), len(loops),
                                              ", ".join(i.id for i in kept)
                                              or "none"))
        return kept

    def plugin_knobs(self, extra=()):
        # -Zllvm-plugins and the pinned reordering flag. build_variant drops
        # an exact duplicate, so passing the reordering flag here is safe even
        # when the recipe already carries it (SPEC.ja.md 2).
        return ["-Zllvm-plugins=" + PLUGIN,
                "-Cllvm-args=-hints-allow-reordering=false"] + list(extra)

    # -- one round --------------------------------------------------------

    def run(self):
        if not os.path.isfile(PLUGIN):
            sys.exit("no plugin at %s (scripts/build_plugin.sh)" % PLUGIN)
        if (getattr(self.args, "site_filter", "all") != "all"
                or getattr(self.args, "oracle_candidates", None)) \
                and self.args.proposer != "oracle":
            sys.exit("--site-filter / --oracle-candidates are oracle staging "
                     "options; jev, random and oracle must share one site "
                     "set and vocabulary (SPEC.ja.md 2)")
        meta = self.baseline()
        base_reports = read_reports(meta["reports"])
        missing = unmatched_marks(base_reports)
        by_mark = marked_functions(base_reports)
        self.base_sites = loop_sites(base_reports)
        # SPEC.ja.md 1(1): a mark that resolves to nothing is a hard error. A
        # mark can resolve to a loop without resolving to a function: the toy's
        # `sum_indexed` has no function of its own in the module (MIR inlined
        # it away) but its loop is still attributed to it, so it gets a loop
        # question and no function question.
        with_sites = {s.get("mark") for s in self.base_sites}
        unresolved = [m for m in self.marks
                      if m not in by_mark and m not in with_sites]
        if unresolved:
            msg = ("these marks resolved to no function in the baseline dump: "
                   + ", ".join(unresolved)
                   + (" (plugin also reports unmatched: %s)" % sorted(missing)
                      if missing else ""))
            if not self.args.allow_unresolved:
                sys.exit("SPEC.ja.md 1(1): " + msg)
            print("[warn] " + msg)

        for mark, info in shares_from_marks_file(self.args.marks).items():
            cur = self.sidecar["marks"].setdefault(mark, {})
            for k, v in info.items():
                if cur.get(k) is None and v is not None:
                    cur[k] = v
        # A mechanical cap on the loop sites, from sites.json. Keys move
        # between rounds (decision 61), so the cap is translated to site_ids
        # once, against the baseline dump, and applied by site_id after that.
        self.site_allow = None
        allow_keys = set() if self.args.no_site_cap else self.site_set_keys()
        if allow_keys:
            # Through loop_items, so the `~2` suffix a repeated site_id gets
            # is the same string on both sides.
            self.site_allow = {i.id for i in loop_items(self.base_sites,
                                                        self.sidecar)
                               if i.meta["key"] in allow_keys}
            print("[sites] sites.json caps the loop sweep at %d of %d sites"
                  % (len(self.site_allow), len(self.base_sites)))

        self.fn_list = fn_items(by_mark, self.marks, self.sidecar,
                                self.args.fn_attr_scope)
        self.base_loops = self.pick_loops(self.base_sites)
        self.build_list = [build_item(self.knobs)] if self.knobs else []

        cap = self.sidecar["caps"].get("max_sites",
                                       int(self.cfg["search"]["max_sites"]))
        n_sites = len(self.fn_list) + len(self.base_loops) + len(self.build_list)
        if n_sites > int(cap):
            sys.exit("%d sites (%d functions + %d loops + %d build) exceeds "
                     "[search] max_sites = %s (SPEC.ja.md 2)"
                     % (n_sites, len(self.fn_list), len(self.base_loops),
                        len(self.build_list), cap))

        # The vendored tree, plus the crate directory of every source file
        # the dump actually named: jaq's hot marks live in hifijson, indexmap
        # and hashbrown, which cargo keeps in ~/.cargo/registry. REPO itself
        # is NOT a root --- it holds 70 target-* build trees.
        roots = [self.shell.get("filter_src_root"),
                 os.path.join(REPO, "targets", self.target)]
        roots += crate_roots_of(self.base_sites)
        crates = {re.split(r"[^A-Za-z0-9_]", m.lstrip("<&"))[0]
                  for m in self.marks}
        crates |= {w for m in self.marks
                   for w in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", m)}
        roots += registry_roots(
            os.path.join(os.path.dirname(self.shell["manifest"]), "Cargo.lock"),
            crates)
        roots += registry_roots(
            os.path.join(self.shell.get("filter_src_root") or "", "Cargo.lock"),
            crates)
        self.source = SourceBook(
            roots, comments=getattr(self.args, "source_comments",
                                    "strip"))
        self.remarks = RemarkBook(meta["log"])
        self.inlines = InlineBook(meta["log"])
        self.share_by_mark = {i.meta["mark"]: (i.meta["share"]
                                               if i.meta["share"] is not None
                                               else i.meta["reach"])
                              for i in self.fn_list}
        # Decision 83. A share that is the same number at every mark is a
        # design statement ("one eighth each"), not a measurement, and the
        # hotness class computed from it separates nothing. Detected rather
        # than hardcoded per target: jaq's shares run 1.10% to 29.29% and
        # are unaffected.
        known = [v for v in self.share_by_mark.values() if v is not None]
        self.share_placeholder = bool(len(known) > 1
                                      and len(set(known)) == 1)
        if self.share_placeholder and evidence_fixes():
            print("[state] every mark carries the same profile share (%s): "
                  "reported as `not measured`, no hotness class"
                  % fmt_share(known[0]))
        self.loops_by_mark = {}
        # Summed loop hotness per mark. Used only to order the exploration
        # Choices of decision 89 (b) where the profile share is a
        # placeholder; nothing in the state quotes it.
        self.hotness_by_mark = {}
        for s_ in self.base_sites:
            m = s_.get("mark")
            self.loops_by_mark[m] = self.loops_by_mark.get(m, 0) + 1
            self.hotness_by_mark[m] = (self.hotness_by_mark.get(m, 0)
                                       + int(s_.get("hotness") or 0))
        # Where each mark's own source is. The dump gives a source location
        # only for loops, and a loop's leaf location is usually in core's
        # iterator machinery, so the definition search comes first and the
        # leaf location is the last resort.
        self.fn_source = {}
        dwarf = DwarfDecl(meta.get("bin"))
        by_id = {i.id: i for i in self.fn_list}
        for mark in sorted(set(self.marks)):
            info = self.sidecar["marks"].get(mark, {})
            if info.get("file"):
                self.fn_source["fn:" + mark] = (info["file"], info.get("line"))
                continue
            it = by_id.get("fn:" + mark)
            f, ln = dwarf.locate(it.meta["linkages"]) if it else (None, None)
            if not f:
                f, ln = self.source.find_definition(mark)
            if f:
                self.fn_source["fn:" + mark] = (f, ln)
        for s in self.base_sites:
            key = "fn:" + s.get("mark", "")
            leaf = s.get("leaf") or {}
            if key not in self.fn_source and leaf.get("file"):
                self.fn_source[key] = (leaf["file"], leaf.get("line"))
        self.base_correctness = read_correctness(meta["correctness"])

        proposer = self.make_proposer()
        if self.args.proposer == "oracle":
            arms = proposer.plan_arms(self.fn_list,
                                      self.oracle_loops(self.base_loops),
                                      self.build_list, self.args.oracle_phase)
            cand_glob = getattr(self.args, "oracle_candidates", None)
            if cand_glob:
                import fnmatch
                pats = [g.strip() for g in cand_glob.split(",") if g.strip()]
                kept = [a for a in arms if any(fnmatch.fnmatchcase(
                    a["candidate"], g) for g in pats)]
                print("[oracle] --oracle-candidates %s keeps %d of %d arms "
                      "(the same filter at every site)"
                      % (cand_glob, len(kept), len(arms)))
                proposer.arms = arms = kept
            print("[oracle] phase %s: %d one-factor arms + 1 combination arm "
                  "(+1 baseline build already done)"
                  % (self.args.oracle_phase, len(arms)))
            if self.args.dry_run:
                for i, a in enumerate(arms, 1):
                    print("  arm %3d  %-8s %-60s %s"
                          % (i, a["site_kind"], a["site"], a["candidate"]))
                print("  arm %3d  combination of the per-site winners"
                      % (len(arms) + 1))
                return 0
        elif self.args.dry_run:
            print("[dry-run] %d function sites, %d loop sites, %d build site"
                  % (len(self.fn_list), len(self.base_loops),
                     len(self.build_list)))
            for it in self.fn_list + self.base_loops + self.build_list:
                print("  %-6s %s" % (it.kind, it.id))
            print("[dry-run] seed_offset=%d seed=%d (effective base seed = "
                  "config seed + seed_offset)" % (self.seed_offset, self.seed))
            return 0

        if self.args.print_state:
            # With --resume this prints the state of the NEXT round, history
            # and all, which is the only way to see what a round other than
            # the first one is sent.
            self.load_resume()
            for phase, items in (("A", self.fn_list + self.build_list),
                                 ("B", self.base_loops)):
                ctx = self.ctx({"arm": None,
                                "loop_items": self.base_loops,
                                "fn_choice_text": "(none: this is a preview)"})
                # Through the same function the proposer uses, so what is
                # printed is what would be sent, verdict block included.
                questions, _ = questions_for(items, ctx, self.knobs)
                print("=" * 72)
                print("### phase %s state (%d questions, vocabulary %s, "
                      "state format %s) ###"
                      % (phase, len(items), V.VOCAB_VERSION,
                         STATE_FORMAT_VERSION))
                print("=" * 72)
                print(state_header(ctx, len(items))
                      + "".join(state_section(it, ctx) for it in items))
                print("=" * 72)
                print("### phase %s questions ###" % phase)
                print("=" * 72)
                for it in items:
                    q = questions[it.qname]
                    print("--- %s  %s  [%s] ---" % (it.qname, it.id, it.kind))
                    print(q["instructions"])
                    print("criteria:")
                    for cid, desc in q["criteria"].items():
                        print("  %s: %s" % (cid, desc))
                    print("")
                # The exploration request of decision 89 (b). It is sent
                # after the phase's own answers are in, so the preview has
                # to assume one: KEEP_DEFAULT everywhere, which is the case
                # the mechanism exists for.
                revisit = getattr(self.args, "explore_revisit", 0)
                elig = {}
                pairs = exploration_sites(items, {}, ctx, self.knobs,
                                          self.args.explore, revisit,
                                          record=elig)
                print("=" * 72)
                print("### phase %s exploration request (%d question(s), "
                      "--explore %d%s; the preview assumes this phase "
                      "answered KEEP_DEFAULT everywhere) ###"
                      % (phase, len(pairs), self.args.explore,
                         (", --explore-revisit %d" % revisit)
                         if revisit else ""))
                print("=" * 72)
                if not pairs:
                    print("(no site is eligible: every site of this phase "
                          "has already been given a hint in an earlier "
                          "round, or --explore is 0)")
                    print("")
                    continue
                eq, _ = exploration_questions(pairs, ctx, elig.get("meta"))
                print(state_header(ctx, len(pairs))
                      + "".join(state_section(it, ctx) for it, _c in pairs))
                for it, _c in pairs:
                    q = eq[it.qname]
                    print("--- %s  %s  [%s] ---" % (it.qname, it.id, it.kind))
                    print(q["instructions"])
                    print("criteria:")
                    for cid, desc in q["criteria"].items():
                        print("  %s: %s" % (cid, desc))
                    print("")
            return 0

        if not self.history:
            self.load_resume()

        # Not len(self.history): a lost round (decision 92 d) is recorded
        # and counted but is not history.
        round_no = self.n_rounds
        # For the oracle --rounds is a cap on the arms (results.md 170: a
        # single-arm verification); without it the whole sweep runs, as
        # before. Frozen oracle runs never passed it.
        limit = ((self.args.rounds or 10 ** 9)
                 if self.args.proposer == "oracle"
                 else int(self.args.rounds or self.cfg["search"]["rounds"]))
        while round_no < limit:
            arm = None
            if self.args.proposer == "oracle":
                # Skip the arms a --resume already measured.
                while proposer.emitted < len(self.history):
                    if proposer.next_arm(self.history) is None:
                        break
                arm = proposer.next_arm(self.history)
                if arm is None:
                    break
            round_no += 1
            t_round = time.time()
            rec = self.one_round(round_no, proposer, arm)
            # Wall clock of the round, recorded here rather than inside
            # one_round because that function has several early returns and
            # every one of them has to carry the number (results.md asks for
            # per-round wall clock). Records only: nothing reads it back.
            rec["wall_s"] = round(time.time() - t_round, 1)
            with open(self.rounds_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
            self.n_rounds = round_no
            if rec.get("status") == "lost":
                continue
            self.history.append(self.history_entry(rec))
            self.update_best(rec)
            if self.args.proposer == "oracle":
                self.oracle_progress(proposer, limit)

        self.measure_holdout()
        self.finish()
        return 0

    def oracle_progress(self, proposer, limit):
        """One line per oracle arm: skipped / measured / remaining and an
        ETA from the running mean wall clock of each kind (results.md 170).
        A no-op arm still costs a build + correctness + code_class."""
        try:
            rows = [json.loads(l) for l in open(self.rounds_path)]
        except OSError:
            return
        sk = [r["wall_s"] for r in rows
              if r.get("status") == "identical_to_baseline" and "wall_s" in r]
        me = [r["wall_s"] for r in rows if r.get("measured") and "wall_s" in r]
        other = len(rows) - len(sk) - len(me)
        # every one-factor arm plus the combination arm, or the --rounds cap
        total = min(len(proposer.arms) + 1, limit)
        left = max(total - len(rows), 0)
        mean = lambda xs: sum(xs) / len(xs) if xs else None
        done = len(sk) + len(me)
        if done:
            p_skip = len(sk) / done
            ms, mm = mean(sk) or 0.0, mean(me) or (mean(sk) or 0.0)
            eta = left * (p_skip * ms + (1 - p_skip) * mm)
        else:
            ms = mm = eta = None
        print("[oracle] progress: %d skipped (no-op, mean %s s), %d measured "
              "(mean %s s), %d other, %d remaining, ETA %s"
              % (len(sk), "%.0f" % ms if sk else "-", len(me),
                 "%.0f" % mm if me else "-", other, left,
                 ("%.0f min" % (eta / 60.0)) if eta is not None else "-"))

    def measure_holdout(self):
        """The one holdout measurement of SPEC.ja.md 7, opt-in.

        The search rounds run on the training cases; the holdout is measured
        once, after the best plan is frozen, and never during the search. It
        is a flag rather than the default so that a run can stop short of it
        and a later command can take it.
        """
        self.holdout = None
        if not self.args.measure_holdout:
            return
        # When no round was accepted the run's best is the baseline itself.
        # Measuring the baseline against the baseline is not a speed claim ---
        # it is the in-sweep null panel of SPEC.ja.md 7 on the holdout set, and
        # it is the only way to get the holdout A/A half-width and the MDE that
        # the report has to quote. The acceptance rule is untouched.
        null_arm = self.best["plan"] is None
        if null_arm:
            print("[holdout] no round beat the baseline; measuring the "
                  "baseline as the run's null arm (A/A and MDE only)")
            best_bin = self.baseline_bin()
        else:
            best_bin = os.path.join(self.out, self.best["label"], "bin")
            if not os.path.isfile(best_bin):
                print("[holdout] %s is gone (--keep-binaries)" % best_bin)
                return
        shell = shell_config(self.target, "holdout")
        hdir = os.path.join(self.out, "holdout")
        os.makedirs(hdir, exist_ok=True)
        print("[holdout] measuring %s on %s"
              % (self.best["label"], shell["bench_set"]))
        stats, err = measure(best_bin, self.baseline_bin(), shell, hdir,
                             self.reps, self.warmup, self.seed, self.resamples)
        if stats is None:
            print("[holdout] %s" % err)
            self.holdout = {"error": err}
            return
        agg = stats["aggregate"]
        self.holdout = {"plan": self.best["label"], "null_arm": null_arm,
                        "case_set": shell["bench_set"],
                        "cases": shell["workloads"],
                        "ratio": agg["cand"]["ratio"], "ci95": agg["cand"]["ci95"],
                        "aa": {"ratio": agg["aa"]["ratio"],
                               "halfwidth": agg["aa"]["halfwidth"]},
                        "argv0": argv0_record(stats),
                        "mde": stats["mde"]}
        with open(os.path.join(hdir, "holdout.json"), "w") as f:
            json.dump(self.holdout, f, indent=1)
        print("[holdout] ratio %.4f CI [%.4f, %.4f]"
              % (self.holdout["ratio"], *self.holdout["ci95"]))

    def make_proposer(self):
        if self.args.proposer == "random":
            return RandomProposer(self.seed, self.knobs)
        if self.args.proposer == "oracle":
            return OracleProposer(self.knobs)
        self.jev = JevClient(self.cfg["jev"],
                             os.path.join(self.out, "jev-log"), self.run_id,
                             self.args.source_comments)
        return JevProposer(self.jev, self.cfg["jev"], self.knobs,
                           int(self.cfg["search"]["max_state_chars"]),
                           self.args.readout, self.args.explore,
                           getattr(self.args, "explore_revisit", 0))

    def platform(self):
        """The platform block, read from the machine once and cached in the
        run directory (`platform.json`, readings and rendered text)."""
        if self._platform is None:
            path = os.path.join(self.out, "platform.json")
            self._platform = platform_block(
                {"bench_cpu": self.shell["bench_cpu"],
                 "bench_gap_ms": self.shell["bench_gap_ms"],
                 "reps": self.reps}, path)
            self._vector_bits = vector_register_bits(path)
        return self._platform

    def ctx(self, extra=None):
        # Decision 89 (d): a site has to be able to name the other sites its
        # timing case is shared with, which means knowing every site of the
        # round and not just its own phase's.
        loops = (extra or {}).get("loop_items")
        if loops is None:
            loops = getattr(self, "base_loops", [])
        c = {"target": self.target, "binary": self.shell["bin_name"],
             "all_site_ids": ([i.id for i in self.fn_list]
                              + [i.id for i in loops]),
             "fn_items": self.fn_list, "history": self.history,
             "cases": [w.split("=", 1)[0] for w in self.shell["workloads"]],
             "reps": self.reps, "mde_text": "3%",
             "source": self.source, "remarks": self.remarks,
             "inlines": getattr(self, "inlines", None),
             "share_placeholder": getattr(self, "share_placeholder", False),
             "share_by_mark": self.share_by_mark, "fn_source": self.fn_source,
             "loops_by_mark": self.loops_by_mark,
             "hotness_by_mark": getattr(self, "hotness_by_mark", {}),
             "fn_choice_text": "",
             "source_comments": getattr(self.args,
                                        "source_comments", "strip"),
             "knobs": self.knobs,
             "pv_untried": getattr(self, "pv_untried", False),
             "state_v2": self.state_v2, "verdicts": self.state_v2,
             "demangler": self.demangler,
             "bench_cpu": self.shell["bench_cpu"],
             "bench_gap_ms": self.shell["bench_gap_ms"],
             "platform": self.platform() if self.state_v2 else "",
             "vector_register_bits": (getattr(self, "_vector_bits", None)
                                      if self.state_v2 else None)}
        c.update(extra or {})
        return c

    def one_round(self, round_no, proposer, arm):
        rdir = os.path.join(self.out, "round-%02d" % round_no)
        os.makedirs(rdir, exist_ok=True)
        rec = {"round": round_no, "proposer": self.args.proposer,
               "ts": datetime.datetime.now().astimezone().isoformat(),
               "vocab_version": V.VOCAB_VERSION,
               "state_format": STATE_FORMAT_VERSION,
               "source_comments": self.args.source_comments,
               "readout": self.args.readout,
               "case_set": self.shell["bench_set"], "arm": arm,
               "reps": self.reps, "warmup": self.warmup,
               "protocol": self.protocol["name"],
               "confirm_rule": self.confirm_when,
               "smoke": bool(self.args.smoke)}
        print("\n=== round %d (%s) ===" % (round_no, self.args.proposer))

        # -- phase A: function attributes (+ the build-wide knob) ---------
        items_a = self.fn_list + self.build_list
        ctx_a = self.ctx({"arm": arm})
        picks_a, why_a = proposer.choose(items_a, ctx_a, round_no, "A")
        if ctx_a.get("phase_lost"):
            return self.lost_round(rec, "A", ctx_a, picks_a, why_a)
        fn_attrs = fn_attrs_from(picks_a, items_a, why_a, self.knobs)
        basis = basis_of(fn_attrs)
        plan_a = os.path.join(rdir, "plan-a.json")
        sha_a = write_plan(plan_a, "r%d-a" % round_no, fn_attrs, [], basis)
        knob_flags = build_knob_flags(picks_a, self.knobs)
        rec["phase_a"] = {"choices": picks_a, "why": why_a,
                          "readout": ctx_a.get("readout"),
                          "exploration": ctx_a.get("exploration"),
                          "gate": ctx_a.get("gate"),
                          "fn_attrs": fn_attrs, "basis": basis,
                          "plan_sha256": sha_a, "build_knobs": knob_flags,
                          "fn_fanout": {i.meta["mark"]: {
                              "linkages": i.meta["linkages"],
                              "excluded_inner": i.meta["excluded_inner"]}
                              for i in self.fn_list}}
        print("[A] %d/%d functions hinted, build knobs %s"
              % (sum(1 for k, v in picks_a.items() if v != V.KEEP_DEFAULT
                     and k != V.BUILD_SITE_ID), len(self.fn_list),
                 knob_flags or "none"))

        reports_a = os.path.join(rdir, "rep-a")
        shutil.rmtree(reports_a, ignore_errors=True)
        os.makedirs(reports_a)
        log_a = os.path.join(rdir, "build-a.log")
        rc = sh_build(self.target, self.target_dir, log_a,
                      self.plugin_knobs(knob_flags),
                      {"JEV_MODE": "apply-dump",
                       "JEV_MARKS": os.path.abspath(self.args.marks),
                       "JEV_PLAN": plan_a, "JEV_PLAN_SHA": sha_a,
                       "JEV_REPORT_DIR": reports_a})
        rec["phase_a"]["build_rc"] = rc
        if rc != 0:
            rec["status"] = "build-a-failed"
            rec["accepted"] = False
            rec["correct"] = False
            print("[A] BUILD FAILED, see %s" % log_a)
            return rec
        rec["phase_a"]["apply"] = merged_apply_outcomes(reports_a)

        reps_a = read_reports(reports_a)
        sites_b = loop_sites(reps_a)
        if not sites_b and not fn_attrs:
            # An empty plan makes apply-dump write nothing in some pipelines;
            # the sites are then the baseline's, by construction.
            sites_b = self.base_sites
            rec["phase_a"]["sites_from"] = "baseline dump (apply-dump wrote none)"
        items_b = self.pick_loops(sites_b)
        rec["phase_a"]["n_loop_sites"] = len(items_b)
        print("[A] refreshed loop sites: %d" % len(items_b))

        # -- phase B: loop hints ------------------------------------------
        fn_text = ", ".join(
            "%s -> %s" % (i.label, V.spec_spelling("fn", picks_a[i.id]))
            for i in self.fn_list if picks_a.get(i.id, V.KEEP_DEFAULT)
            != V.KEEP_DEFAULT) or "none"
        ctx_b = self.ctx({"arm": arm, "fn_choice_text": fn_text,
                          "loop_items": items_b})
        picks_b, why_b = proposer.choose(items_b, ctx_b, round_no, "B")
        if ctx_b.get("phase_lost"):
            # Phase A was built (its dump is what phase B's state is made
            # of) and is kept in the record as data; the round's own build
            # is not made.
            return self.lost_round(rec, "B", ctx_b, picks_b, why_b)
        loop_md = loop_md_from(picks_b, items_b, why_b)
        plan_b = os.path.join(rdir, "plan-b.json")
        sha_b = write_plan(plan_b, "r%d-b" % round_no, fn_attrs, loop_md, basis)
        rec["phase_b"] = {"choices": picks_b, "why": why_b,
                          "readout": ctx_b.get("readout"),
                          "exploration": ctx_b.get("exploration"),
                          "gate": ctx_b.get("gate"),
                          "loop_md": loop_md, "plan_sha256": sha_b}
        # A lost exploration request does not lose the round: the argmax
        # plan is whole without it (decision 92 d).
        rec["explore_lost"] = any(
            bool((c.get("exploration") or {}).get("lost"))
            for c in (ctx_a, ctx_b))
        # Decision 89 (a): what makes this round's build different from
        # another round's, with the annotations left out.
        rec["plan_sig"] = plan_signature(fn_attrs, loop_md)
        if basis_of(fn_attrs) != basis:
            rec["status"] = "basis-mismatch"
            rec["accepted"] = rec["correct"] = False
            return rec
        print("[B] %d/%d loops hinted" % (len(loop_md), len(items_b)))

        reports_b = os.path.join(rdir, "rep-b")
        shutil.rmtree(reports_b, ignore_errors=True)
        os.makedirs(reports_b)
        log_b = os.path.join(rdir, "build-b.log")
        rc = sh_build(self.target, self.target_dir, log_b,
                      self.plugin_knobs(knob_flags),
                      {"JEV_MODE": "apply", "JEV_PLAN": plan_b,
                       "JEV_PLAN_SHA": sha_b, "JEV_REPORT_DIR": reports_b})
        rec["phase_b"]["build_rc"] = rc
        if rc != 0:
            rec["status"] = "build-b-failed"
            rec["accepted"] = rec["correct"] = False
            print("[B] BUILD FAILED, see %s" % log_b)
            return rec

        outcomes = merged_apply_outcomes(reports_b)
        rec["phase_b"]["apply"] = outcomes
        # `ambiguous` is NOT a failure. On jaq 13 of 127 site keys resolve
        # to 2-9 loops; the plugin attaches the hint to every copy and says
        # so (results.md "Sites (jaq)"). A plan entry is an instruction about
        # a key, so such an arm moves several loops at once and cannot
        # separate them --- which is a property of the arm, recorded as a
        # count. `vanished` and `unmatched` are failures: the hint went
        # nowhere.
        wanted = ([e["fn"] for e in fn_attrs] + [e["key"] for e in loop_md])
        got = {w: outcomes.get(w, {"outcome": "no-report"})["outcome"]
               for w in wanted}
        ok = ("attached", "consumed", "already_vectorized",
              "skipped_idempotent")
        bad = {w: o for w, o in got.items()
               if not all(part in ok or part == "ambiguous"
                          for part in o.split("+"))}
        ambiguous = sorted(w for w, o in got.items()
                           if "ambiguous" in o.split("+") and w not in bad)
        rec["phase_b"]["bad_outcomes"] = bad
        rec["phase_b"]["ambiguous_entries"] = ambiguous
        rec["phase_b"]["n_ambiguous"] = len(ambiguous)
        if ambiguous:
            print("[B] %d plan entries named a key that resolves to several "
                  "loops (attached to all of them, recorded not failed)"
                  % len(ambiguous))
        if bad:
            print("[B] plan entries that did not take: %s" % bad)

        binary = os.path.join(rdir, "bin")
        shutil.copy2(os.path.join(self.target_dir, self.shell["triple"],
                                  "release", self.shell["bin_name"]), binary)
        rec["bin_sha256"] = sha256_file(binary)

        corr = os.path.join(rdir, "correctness.txt")
        sh_correctness(self.target, binary, corr)
        got = read_correctness(corr)
        correct = (got == self.base_correctness)
        rec["correct"] = correct
        rec["correctness_diff"] = None if correct else [
            {"line": i, "baseline": b, "candidate": c}
            for i, (b, c) in enumerate(
                zip(self.base_correctness + [None] * len(got),
                    got + [None] * len(self.base_correctness)))
            if b != c][:20]
        print("[B] correctness: %s" % ("OK" if correct else "MISMATCH"))

        # Decision 80 (b): what the build actually differs in, before any
        # timing. Recorded for every arm that produced a binary, including
        # the ones the gates below refuse.
        klass, changed, detail = code_class(self.baseline_bin(), binary,
                                            self.base_norm(), self.base_nm())
        rec["code_class"] = klass
        rec["code_detail"] = detail
        rec["changed_symbols"] = changed[:40]
        rec["n_changed_symbols"] = len(changed)
        print("[B] code vs baseline: %s (%d symbols changed, symbol table %s)"
              % (klass, len(changed),
                 "same" if detail["symbol_table_same"] else "moved"))

        if not correct:
            rec["status"] = "output-mismatch"
            rec["accepted"] = False
            self.drop_binary(binary)
            return rec
        if bad and not self.args.ignore_apply_failures:
            rec["status"] = "apply-incomplete"
            rec["accepted"] = False
            self.drop_binary(binary)
            return rec

        # Decision 80 (b): an arm whose binary is the baseline's is not
        # measured. Its ratio is 1.0 by construction and a batch spent on it
        # measures the machine, not the hint --- on jaq 48 such arms were
        # measured anyway and 20 of them came back with a 95% CI that
        # excluded 1.0 (results.md "Oracle A (jaq)" 113). `ci95` stays null,
        # which every consumer of a round record already tolerates, so
        # nothing downstream can mistake a construction for a measurement.
        if klass == "identical" and not self.args.no_noop_skip:
            rec["status"] = "identical_to_baseline"
            rec["ratio"] = 1.0
            rec["ci95"] = None
            rec["measured"] = False
            rec["accepted"] = False
            print("[B] identical to the baseline: ratio 1.0 by construction, "
                  "no timing batch")
            return rec

        own_wl = own_workload_of((arm or {}).get("site"),
                                 [w.split("=", 1)[0]
                                  for w in self.shell["workloads"]])
        rec["own_workload"] = own_wl
        # Protocol v2 (results.md 170): an oracle one-factor arm may be timed
        # without the A/A leg and with `reps_oracle` repetitions. Search
        # rounds, the combination arm, confirmation batches and the holdout
        # keep the A/A leg; the combination and search rounds keep `reps`.
        reps, aa = self.batch_plan(arm)
        rec["reps"] = reps
        rec["confirm_rule"] = self.confirm_when
        stats, err = measure(binary, self.baseline_bin(), self.shell, rdir,
                             reps, self.warmup, self.seed + round_no,
                             self.resamples, aa=aa)
        if stats is None:
            rec["status"] = "measure-failed"
            rec["error"] = err
            rec["accepted"] = False
            print("[B] %s" % err)
            return rec
        rec["measured"] = True
        self.record_batch(rec, stats, own_wl, key=None)
        rec["mde"] = stats["mde"]
        rec["status"] = "measured"
        print("[B] ratio %.4f  CI [%.4f, %.4f]  %s  [n=%d, %d labels]"
              % (rec["ratio"], rec["ci95"][0], rec["ci95"][1],
                 ("(in-run A/A %.4f +-%.4f)"
                  % (rec["aa"]["ratio"], rec["aa"]["halfwidth"]))
                 if rec.get("aa") else "(no A/A leg)",
                 reps, len(rec.get("labels") or [])))
        if rec.get("kernel"):
            k = rec["kernel"]
            print("[B] %s only: ratio %.4f CI [%.4f, %.4f]  (A/A %s)"
                  % (own_wl, k["ratio"], k["ci95"][0], k["ci95"][1],
                     "%.4f" % k["aa_ratio"] if k.get("aa_ratio") is not None
                     else "-"))

        # Decision 80 (a): one batch does not decide. An arm whose interval
        # excludes 1 --- on the aggregate, or on its own kernel's workload,
        # which is this target's readout (results.md "Hint benchmark
        # (design)" 103) --- is measured a second time, in an independent
        # batch with a fresh shuffle seed over the same two binaries, and is
        # only believed if both batches exclude 1 with the same sign. The
        # second batch lives inside the same round record: a round is still
        # one arm, and `--resume` still counts rounds.
        # Protocol v2 replaces "the interval excludes 1" by "the difference
        # reached the MDE" (`confirm_when = "mde"`). What v1 would have
        # fired is recorded beside it, so the saving can be counted.
        fired = confirm_trigger(rec, own_wl, self.confirm_when, self.mde)
        rec["confirm_trigger"] = fired
        if self.confirm_when != "ci":
            ci_fired = confirm_trigger(rec, own_wl, "ci")
            rec["confirm_trigger_ci_rule"] = ci_fired
            rec["confirm_mde"] = max(float(self.mde if self.mde is not None
                                           else rec.get("mde") or 0.03), 0.03)
            if ci_fired and not fired:
                rec["flat_below_mde"] = True
                print("[B] CI excludes 1 but |ratio - 1| < MDE %.4f: "
                      "reported flat, no confirmation batch (confirm_when "
                      "= mde)" % rec["confirm_mde"])
        if fired and not self.args.no_confirm_batch:
            cdir = os.path.join(rdir, "confirm")
            os.makedirs(cdir, exist_ok=True)
            cseed = self.seed + 100000 + round_no
            print("[B] confirmation batch (%s %s), fresh seed %d"
                  % ("+".join(fired), "excluded 1" if self.confirm_when ==
                     "ci" else "reached the MDE", cseed))
            # A confirmation batch always carries the A/A leg; it uses the
            # first batch's repetitions.
            cstats, cerr = measure(binary, self.baseline_bin(), self.shell,
                                   cdir, reps, self.warmup, cseed,
                                   self.resamples, aa=True)
            if cstats is None:
                rec["confirm"] = {"error": cerr, "seed": cseed}
                print("[B] confirmation batch failed: %s" % cerr)
            else:
                rec["confirm"] = {"seed": cseed, "mde": cstats["mde"]}
                self.record_batch(rec["confirm"], cstats, own_wl, key=None)
                print("[B] confirm: ratio %.4f CI [%.4f, %.4f]%s"
                      % (rec["confirm"]["ratio"], rec["confirm"]["ci95"][0],
                         rec["confirm"]["ci95"][1],
                         ("  %s only %.4f [%.4f, %.4f]"
                          % (own_wl, rec["confirm"]["kernel"]["ratio"],
                             *rec["confirm"]["kernel"]["ci95"]))
                         if rec["confirm"].get("kernel") else ""))
        self.score_confirmation(rec)
        return rec

    def lost_round(self, rec, phase, ctx, picks, why):
        """Decision 92 (d): a round one of whose phases never got through.

        It is not built and not measured, and it does not enter the history
        (the state of the next round is the state this round would have
        been sent, less nothing); the round counter still advances, so a
        run's round budget is spent by the gateway as well as by builds."""
        gate = ctx.get("phase_lost") or {}
        key = "phase_a" if phase == "A" else "phase_b"
        rec[key] = dict(rec.get(key) or {}, choices=picks, why=why,
                        gate=gate)
        rec["status"] = "lost"
        rec["lost_phase"] = phase
        rec["lost_attempts"] = gate.get("attempts")
        rec["lost_sends"] = gate.get("sends")
        rec["lost_seconds_waited"] = gate.get("seconds_waited")
        rec["accepted"] = False
        rec["correct"] = False
        if self.jev:
            self.jev.gateway["lost_rounds"] += 1
        print("[gate] round %d lost in phase %s (%d send(s), %d HTTP "
              "attempt(s), %.1f s waited): not built, not measured, history "
              "unchanged" % (rec["round"], phase, gate.get("sends") or 0,
                             gate.get("attempts") or 0,
                             gate.get("seconds_waited") or 0.0))
        return rec

    # -- batch bookkeeping -------------------------------------------------

    def base_norm(self):
        if getattr(self, "_base_norm", None) is None:
            import norm_code_diff as N
            self._base_norm = N.norm_bodies(self.baseline_bin())[0]
        return self._base_norm

    def base_nm(self):
        if getattr(self, "_base_nm", None) is None:
            self._base_nm = nm_table(self.baseline_bin())
        return self._base_nm

    @staticmethod
    def record_batch(into, stats, own_wl, key=None):
        """Copy one batch's aggregate and own-kernel readings into a record."""
        agg = stats["aggregate"]
        into["argv0"] = argv0_record(stats)
        into["ratio"] = agg["cand"]["ratio"]
        into["ci95"] = agg["cand"]["ci95"]
        into["labels"] = list(stats.get("labels") or [])
        into["aa"] = ({"ratio": agg["aa"]["ratio"], "ci95": agg["aa"]["ci95"],
                       "halfwidth": agg["aa"]["halfwidth"]}
                      if "aa" in agg else None)
        # Experiment 4: every case's own reading, not only the arm's. A
        # search round moves several sites at once, so `own_workload_of` has
        # nothing to key on (`arm` is None) and the per-site feedback the
        # rounds are supposed to carry would otherwise not exist. `kernel`
        # below is unchanged and is still what the confirmation and the
        # oracle's per-site readout use.
        percase, aacase = (stats.get("per_workload") or {}).get("cand") or {}, \
            (stats.get("per_workload") or {}).get("aa") or {}
        into["per_workload"] = {
            w: {"ratio": c["ratio_vs_base"], "ci95": c["ci95"],
                "halfwidth": c["halfwidth"],
                "aa_ratio": (aacase.get(w) or {}).get("ratio_vs_base")}
            for w, c in sorted(percase.items())}
        if own_wl and own_wl in percase:
            c = percase[own_wl]
            a = aacase.get(own_wl) or {}
            into["kernel"] = {"workload": own_wl, "ratio": c["ratio_vs_base"],
                              "ci95": c["ci95"], "halfwidth": c["halfwidth"],
                              "aa_ratio": a.get("ratio_vs_base"),
                              "aa_ci95": a.get("ci95")}
        return into

    @staticmethod
    def score_confirmation(rec):
        """Decision 80 (a): believed only if both batches agree and exclude 1.

        Scored separately on the aggregate and on the arm's own kernel, so a
        target with a per-site readout and a target without one are both
        served, and neither number is derived from the other.
        """
        c = rec.get("confirm") or {}
        for name, first, second in (
                ("confirmed_aggregate", rec.get("ci95"), c.get("ci95")),
                ("confirmed", (rec.get("kernel") or {}).get("ci95"),
                 (c.get("kernel") or {}).get("ci95"))):
            s1, s2 = excludes_one(first), excludes_one(second)
            rec[name] = bool(s1 and s1 == s2)
            rec[name + "_sign"] = s1 if rec[name] else 0
        return rec

    def drop_binary(self, path):
        if self.args.keep_binaries == "all":
            return
        try:
            os.remove(path)
        except OSError:
            pass

    def baseline_bin(self):
        return os.path.join(self.base_dir, "bin")

    def history_entry(self, rec):
        choices = {}
        choices.update((rec.get("phase_a") or {}).get("choices") or {})
        choices.update((rec.get("phase_b") or {}).get("choices") or {})
        k = rec.get("kernel") or {}
        ck = (rec.get("confirm") or {}).get("kernel") or {}
        return {"round": rec["round"], "choices": choices,
                "correct": bool(rec.get("correct")),
                "ratio": rec.get("ratio"), "ci95": rec.get("ci95"),
                "status": rec.get("status"),
                "code_class": rec.get("code_class"),
                "own_workload": rec.get("own_workload"),
                "per_workload": rec.get("per_workload"),
                "confirm_per_workload": (rec.get("confirm")
                                         or {}).get("per_workload"),
                "kernel_ratio": k.get("ratio"), "kernel_ci95": k.get("ci95"),
                "confirm_kernel_ratio": ck.get("ratio"),
                "confirm_ratio": (rec.get("confirm") or {}).get("ratio"),
                "confirmed": bool(rec.get("confirmed")),
                "confirmed_sign": rec.get("confirmed_sign") or 0,
                "confirmed_aggregate": bool(rec.get("confirmed_aggregate")),
                "accepted": bool(rec.get("accepted"))}

    def update_best(self, rec):
        """The pre-registered acceptance rule (docs/search-driver.md).

        A round becomes the new best only if it is correct, every plan entry
        took effect, and the LOWER end of its 95% CI is above the best point
        estimate so far. The baseline is the first best, at ratio 1.0.
        """
        # Decision 80 (a) adds the fourth condition: the interval that beat
        # the incumbent has to survive a second, independent batch over the
        # same two binaries. Rule 3 by itself is satisfiable by noise at this
        # n --- it accepted three arms of jaq's oracle A, all of which the
        # holdout reversed.
        # Decision 89 (a) adds the fifth: a round is compared with the
        # incumbent only when its plan is a DIFFERENT plan. Rounds 2 to 5 of
        # Experiment 4 were the identical binary measured in four
        # independent batches at 1.0628 to 1.0679, and round 5 was
        # "accepted as the new best" over round 2 because the luckier batch
        # cleared the unluckier one's point estimate. Rules 3 and 4 never
        # ask whether the plan moved; this does, and an identical plan is
        # recorded as one more batch on the incumbent instead.
        same_plan = (rec.get("status") == "measured"
                     and rec.get("plan_sig") == self.best.get("plan_sig"))
        rec["same_plan_as_best"] = bool(same_plan)
        if same_plan:
            self.best.setdefault("batches", []).append(
                {"round": rec["round"], "ratio": rec["ratio"],
                 "ci95": rec.get("ci95"), "batch": "round"})
            if (rec.get("confirm") or {}).get("ratio") is not None:
                self.best["batches"].append(
                    {"round": rec["round"], "ratio": rec["confirm"]["ratio"],
                     "ci95": rec["confirm"].get("ci95"),
                     "batch": "confirmation"})
            rs = [b["ratio"] for b in self.best["batches"]]
            rec["best_plan_batches"] = list(self.best["batches"])
            rec["best_plan_spread"] = (max(rs) - min(rs)) if rs else 0.0
            print("[accept] round %d builds the same plan as %s: recorded as "
                  "%d further batch(es) on it (%.4f..%.4f, spread %.2f pt), "
                  "not compared and not promoted"
                  % (rec["round"], self.best["label"], len(rs),
                     min(rs), max(rs), 100.0 * (max(rs) - min(rs))))
        ok = (rec.get("status") == "measured" and rec.get("correct")
              and not same_plan
              and rec["ci95"][0] > self.best["ratio"]
              and (self.args.no_confirm_batch
                   or rec.get("confirmed_aggregate")))
        rec["accepted"] = bool(ok)
        self.history[-1]["accepted"] = bool(ok)
        with open(self.rounds_path) as f:
            lines = f.read().splitlines()
        lines[-1] = json.dumps(rec)
        with open(self.rounds_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        if not ok:
            if rec.get("status") == "measured" and rec.get("correct"):
                self.drop_binary(os.path.join(
                    self.out, "round-%02d" % rec["round"], "bin"))
            return
        batches = [{"round": rec["round"], "ratio": rec["ratio"],
                    "ci95": rec.get("ci95"), "batch": "round"}]
        if (rec.get("confirm") or {}).get("ratio") is not None:
            batches.append({"round": rec["round"],
                            "ratio": rec["confirm"]["ratio"],
                            "ci95": rec["confirm"].get("ci95"),
                            "batch": "confirmation"})
        self.best = {"round": rec["round"], "ratio": rec["ratio"],
                     "ci95": rec["ci95"],
                     "plan": os.path.join(self.out, "round-%02d" % rec["round"],
                                          "plan-b.json"),
                     "label": "round-%02d" % rec["round"],
                     "plan_sig": rec.get("plan_sig"), "batches": batches}
        shutil.copy2(self.best["plan"], os.path.join(self.out, "best-plan.json"))
        print("[accept] round %d is the new best (%.4f)"
              % (rec["round"], rec["ratio"]))

    def load_resume(self):
        if not (self.args.resume and os.path.isfile(self.rounds_path)):
            return
        for line in open(self.rounds_path):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            self.n_rounds = max(self.n_rounds, int(rec["round"]))
            if rec.get("status") == "lost":
                continue
            self.history.append(self.history_entry(rec))
            if rec.get("accepted"):
                self.best = {"round": rec["round"], "ratio": rec["ratio"],
                             "ci95": rec.get("ci95"),
                             "plan": os.path.join(self.out, "round-%02d"
                                                  % rec["round"], "plan-b.json"),
                             "label": "round-%02d" % rec["round"],
                             "plan_sig": rec.get("plan_sig"),
                             "batches": rec.get("best_plan_batches") or []}
            elif rec.get("same_plan_as_best") and rec.get("best_plan_batches"):
                self.best["batches"] = rec["best_plan_batches"]
        print("[resume] %d rounds already recorded (%d of them lost), best = "
              "%s (%.4f)" % (self.n_rounds, self.n_rounds - len(self.history),
                             self.best["label"], self.best["ratio"]))

    # -- output -----------------------------------------------------------

    def finish(self):
        wall = time.time() - self.t0
        if self.jev:
            self.jev.write_totals(wall)
        manifest = {
            "run_id": self.run_id, "target": self.target,
            "proposer": self.args.proposer,
            "oracle_phase": (self.args.oracle_phase
                             if self.args.proposer == "oracle" else None),
            "ts": datetime.datetime.now().astimezone().isoformat(),
            "smoke": bool(self.args.smoke),
            "vocab_version": V.VOCAB_VERSION,
            "state_format": STATE_FORMAT_VERSION,
            "source_comments": self.args.source_comments,
            "readout": self.args.readout,
            "explore": self.args.explore,
            # Decision 92 (b, c).
            "exploration": {
                "k": self.args.explore,
                "revisit": getattr(self.args, "explore_revisit", 0),
                "max_visits": EXPLORE_MAX_VISITS,
                "revisit_text": (EXPLORE_REVISIT_TEXT_VERSION
                                 if getattr(self.args, "explore_revisit", 0)
                                 else None),
                "pv_untried": getattr(self.args, "pv_untried", "off")},
            "platform_block": (os.path.join(self.out, "platform.json")
                               if self.state_v2 else None),
            "config": self.cfg["_path"], "config_sha256": self.cfg["_sha256"],
            "marks": os.path.abspath(self.args.marks),
            "marks_sha256": sha256_file(self.args.marks),
            "sites": os.path.abspath(self.args.sites) if self.args.sites else None,
            "plugin_sha256": sha256_file(PLUGIN),
            "profdata_sha256": sha256_file(self.shell["profdata"]),
            "baseline_bin_sha256": sha256_file(self.baseline_bin()),
            "case_set": self.shell["bench_set"],
            "workloads": self.shell["workloads"],
            "taskset_cpu": self.shell["bench_cpu"],
            "gap_ms": self.shell["bench_gap_ms"],
            "repetitions": self.reps, "warmup": self.warmup,
            # results.md 170: which measurement protocol the run used.
            "protocol": self.protocol,
            # "seed" is the effective base seed (config seed + seed_offset);
            # seed_offset is recorded separately so a manifest shows both
            # what was configured and what --seed-offset shifted it by
            # (decision 98).
            "seed": self.seed, "seed_offset": self.seed_offset,
            # Decision 97: every timed exec path is an alias of this length.
            "argv0": {"len": B.ARGV0_LEN, "class": B.chunk(B.ARGV0_LEN),
                      "root": B.ALIAS_ROOT},
            "rustc": subprocess.run(["rustc", "-vV"], text=True,
                                    capture_output=True).stdout,
            "lscpu_e": subprocess.run(["lscpu", "-e"], text=True,
                                      capture_output=True).stdout,
            "best": self.best, "holdout": getattr(self, "holdout", None),
            "jev_totals": self.jev.totals if self.jev else None,
            # Decision 92 (d).
            "retry_policy": (retry_policy(self.cfg["jev"])
                             if self.args.proposer == "jev" else None),
            "gateway": self.jev.gateway if self.jev else None,
            "wall_s": round(wall, 1),
        }
        with open(os.path.join(self.out, "run-manifest.json"), "w") as f:
            json.dump(manifest, f, indent=1)
        self.summary(manifest)
        print("\nwrote %s" % os.path.join(self.out, "summary.md"))

    def summary(self, manifest):
        rows = []
        for line in open(self.rounds_path):
            rows.append(json.loads(line))
        out = []
        out.append("# jev-opt search run `%s`" % self.run_id)
        out.append("")
        if self.args.smoke:
            out.append("**SMOKE RUN.** n=%d, warmup=%d: this run exists to "
                       "check that the driver works end to end. No speed "
                       "claim may be made from it." % (self.reps, self.warmup))
            out.append("")
        out.append("target `%s`, proposer `%s`, case set `%s` (%s), "
                   "%d repetitions, warmup %d, pinned to CPU %s, gap %s ms, "
                   "vocabulary `%s`, state format `%s`, readout `%s`."
                   % (self.target, self.args.proposer,
                      self.shell["bench_set"],
                      ", ".join(w.split("=", 1)[0] for w in self.shell["workloads"]),
                      self.reps, self.warmup, self.shell["bench_cpu"],
                      self.shell["bench_gap_ms"], V.VOCAB_VERSION,
                      STATE_FORMAT_VERSION, self.args.readout))
        out.append("")
        pr = self.protocol
        out.append("Measurement protocol %s (results.md 170): confirmation "
                   "batch when %s; oracle one-factor arms timed %s, n=%d. "
                   "Search rounds, the combination arm, confirmation "
                   "batches and the holdout keep the A/A leg."
                   % (pr["name"], "the 95% CI excludes 1" if
                      pr["confirm_when"] == "ci" else
                      "|ratio - 1| >= MDE (sub-MDE differences are reported "
                      "flat without a second batch)",
                      "with base + cand + aa" if pr["aa_leg_oracle_arms"]
                      else "with base + cand only (no A/A leg)",
                      pr["reps_oracle"]))
        out.append("")
        out.append("Acceptance rule, fixed before the first round: a round "
                   "becomes the best so far only if its plan differs from "
                   "the incumbent's, its output matches the baseline on "
                   "every case, every plan entry was applied, and the lower "
                   "end of its 95% CI is above the best point estimate so "
                   "far (the baseline, 1.0000, is the first). A round whose "
                   "plan is the incumbent's plan is the incumbent's binary: "
                   "it is recorded as one more independent batch on it and "
                   "cannot re-promote it (decision 89 a).")
        out.append("")
        batches = self.best.get("batches") or []
        if len(batches) > 1:
            rs = [b["ratio"] for b in batches]
            out.append("Batches measured on the best plan\'s own binary: %d "
                       "(%s), spread %.2f points. Nothing inside that spread "
                       "separates two plans."
                       % (len(rs), ", ".join("%.4f" % r for r in rs),
                          100.0 * (max(rs) - min(rs))))
            out.append("")
        out.append("| round | site | candidate | code vs base | fn hints | "
                   "loop hints | explored | plan | apply problems | correct | "
                   "ratio | 95% CI | own kernel | own-kernel CI | confirmed | "
                   "in-run A/A | accepted |")
        out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
                   "---|---|---|")
        for r in rows:
            pa, pb = r.get("phase_a") or {}, r.get("phase_b") or {}
            arm = r.get("arm") or {}
            k = r.get("kernel") or {}
            ci = ("[%.4f, %.4f]" % tuple(r["ci95"])) if r.get("ci95") else "-"
            kci = ("[%.4f, %.4f]" % tuple(k["ci95"])) if k.get("ci95") else "-"
            aa = ("%.4f ±%.4f" % (r["aa"]["ratio"], r["aa"]["halfwidth"])) \
                if r.get("aa") else "-"
            conf = ("yes (%s)" % ("+" if r.get("confirmed_sign", 0) > 0
                                  else "-")) if r.get("confirmed") else (
                "no" if r.get("confirm") else
                ("n/a" if r.get("status") == "identical_to_baseline"
                 else ("flat (<MDE)" if r.get("flat_below_mde")
                       else "not triggered")))
            explored = []
            for ph in (pa, pb):
                for sid, pick in ((ph.get("exploration") or {})
                                  .get("picks") or {}).items():
                    explored.append("%s=%s" % (sid, pick))
            out.append("| %d | %s | %s | %s | %d | %d | %s | %s | %s | %s | %s | %s | "
                       "%s | %s | %s | %s | %s |"
                       % (r["round"],
                          (arm.get("site") or "combination"),
                          (arm.get("candidate") or "-"),
                          r.get("code_class") or "-",
                          len(pa.get("fn_attrs") or []),
                          len(pb.get("loop_md") or []),
                          ", ".join(explored) or "none",
                          ("same as best" if r.get("same_plan_as_best")
                           else (r.get("plan_sig") or "-")[:8]),
                          ", ".join("%s=%s" % kv for kv in
                                    (pb.get("bad_outcomes") or {}).items()) or "none",
                          "yes" if r.get("correct") else "NO",
                          ("%.4f" % r["ratio"]) if r.get("ratio") is not None
                          else r.get("status", "-"),
                          ci,
                          ("%.4f" % k["ratio"]) if k.get("ratio") is not None
                          else "-",
                          kci, conf, aa,
                          "yes" if r.get("accepted") else "no"))
        out.append("")
        out.append("Best plan: %s (round %s, ratio %.4f). `best-plan.json` is "
                   "a copy of it."
                   % (self.best["label"], self.best["round"], self.best["ratio"]))
        out.append("")
        if self.jev:
            t = self.jev.totals
            out.append("Jev: %d HTTP requests, %d Choice questions, %.1f s of "
                       "latency in total (max %.0f ms), %d input + %d output "
                       "tokens, $%.8f, %.2f%% of the run's wall clock."
                       % (t["requests"], t["questions"], t["latency_ms"] / 1e3,
                          t["max_latency_ms"], t["input_tokens"],
                          t["output_tokens"], t["cost_usd"],
                          100.0 * (t["latency_ms"] / 1e3)
                          / max(1e-9, manifest["wall_s"])))
            g = self.jev.gateway
            out.append("Gateway (decision 92 d): %d requests in %d HTTP "
                       "attempts, %d landed, %d exhausted; %d phase(s) lost, "
                       "%d round(s) lost and not built; %.1f s spent "
                       "waiting between attempts and re-sends."
                       % (g["requests"], g["attempts"], g["landed"],
                          g["exhausted"], g["lost_phases"], g["lost_rounds"],
                          g["seconds_waiting"]))
            out.append("")
        h = getattr(self, "holdout", None)
        if h and "ratio" in h:
            out.append("Holdout (%s, measured once, after the best plan was "
                       "frozen): ratio %.4f, 95%% CI [%.4f, %.4f], in-run A/A "
                       "%.4f ±%.4f, MDE %.4f."
                       % (h["case_set"], h["ratio"], h["ci95"][0], h["ci95"][1],
                          h["aa"]["ratio"], h["aa"]["halfwidth"], h["mde"]))
        else:
            out.append("The holdout has NOT been measured by this run "
                       "(SPEC.ja.md 7: the holdout is measured once, after "
                       "the best plan is frozen; pass --measure-holdout).")
        out.append("")
        with open(os.path.join(self.out, "summary.md"), "w") as f:
            f.write("\n".join(out))


def sha256_file(path):
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="jev-opt hint search (SPEC.ja.md 1(3), decision 62)")
    p.add_argument("--target", required=True,
                   help="a TARGET scripts/target_common.sh knows")
    p.add_argument("--marks", required=True, help="jev-marks.txt")
    p.add_argument("--sites", default=None,
                   help="optional sites.json with profile shares and caps")
    p.add_argument("--proposer", required=True,
                   choices=("jev", "random", "oracle"))
    p.add_argument("--vocab", default="v3",
                   choices=("v1", "v2", "v3", "v4", "v5", "v6"),
                   help="the frozen vocabulary AND state template: v1 is "
                        "Experiment 3's, v2 is decision 73 --- the prompt "
                        "study's W7, i.e. the mechanical verdict block in "
                        "both phases, the applicability conditions in the "
                        "function criteria only, a neutral KEEP_DEFAULT, "
                        "the V2 question wording and the platform block. "
                        "v3 (default, decision 77) is v2 with the function "
                        "candidates `inline` and `cold` replaced by "
                        "`inline_always`, the two of them being inert under "
                        "O3 + PGO + fat LTO; its state is v3.1 since "
                        "decision 83 (per-loop legality, the inliner's own "
                        "decisions, no hotness class on a placeholder "
                        "share). v4 (decision 84) is v3 with the function "
                        "descriptions rebalanced so that no candidate is "
                        "described at greater length or strength than "
                        "another. v5 (decision 85): v4 minus the three "
                        "`align` candidates and minus `unroll.disable`, "
                        "both measured dead or duplicate in the hintbench "
                        "oracle. v6 (decision 98): v5 with `unroll.disable` "
                        "restored to the loop half only, for a loop LLVM "
                        "does not vectorize (the oracle's merge of it into "
                        "`interleave.count=1` held for vectorized loops "
                        "only)")
    p.add_argument("--readout", default="forced_top1",
                   choices=("forced_top1", "argmax"),
                   help="how a phase's answers become plan entries "
                        "(decision 71). forced_top1 (default): the argmax, "
                        "except that a phase whose every answer is "
                        "KEEP_DEFAULT still applies one hint --- the "
                        "top-ranked site by 1-P(KEEP_DEFAULT), with its own "
                        "best non-KEEP candidate. argmax: the old behaviour, "
                        "which leaves such a phase empty. The ranking is "
                        "recorded either way."
                   )
    p.add_argument("--explore", type=int, default=2, metavar="K",
                   help="decision 89 (b): how many extra Choices a round "
                        "adds for sites nothing has ever been tried at. "
                        "After each phase's own answers are in, the K "
                        "hottest sites that no earlier round gave a hint to "
                        "and that this round answered KEEP_DEFAULT are asked "
                        "once more, with only the candidates they have not "
                        "been given (mechanically filtered, no KEEP_DEFAULT) "
                        "and the question `one of these will be tried this "
                        "round`. The answer joins this round's plan beside "
                        "the argmax entries and never replaces one. "
                        "--explore 0 is the behaviour of Experiment 4, whose "
                        "feedback filtered and never discovered. Applies to "
                        "--proposer jev only: random already draws non-"
                        "KEEP_DEFAULT candidates by construction, and the "
                        "oracle's arms are enumerated")
    p.add_argument("--explore-revisit", type=int, default=0, metavar="R",
                   help="decision 92 (b): R further exploration slots per "
                        "phase for sites that have been tried, filled after "
                        "the K new-site slots and sent in the same request. "
                        "A site is eligible when this round answered "
                        "KEEP_DEFAULT there, fewer than %d distinct hints "
                        "have been tried there, and an untried candidate "
                        "remains; order: fewest hints tried, then hotness. "
                        "Candidates are every untried non-KEEP candidate, "
                        "and the question names what was tried (text %s). "
                        "0 (default) is Experiment 5's behaviour exactly"
                        % (EXPLORE_MAX_VISITS, EXPLORE_REVISIT_TEXT_VERSION))
    p.add_argument("--pv-untried", default="off", choices=("off", "on"),
                   help="decision 92 (c): on adds, beside the post_vectorize "
                        "width and interleave lines of a vectorized loop, "
                        "which vocabulary values of that kind have not been "
                        "tried at the loop in this run (all of them, "
                        "numeric order). State format %s; --vocab v5 only"
                        % STATE_FORMATS["v5.1"])
    p.add_argument("--source-comments", default="strip",
                   choices=("strip", "keep"),
                   help="how the source excerpts in the state are rendered "
                        "(decision 81). strip (default): every comment "
                        "(`//`, `///`, `//!`, `/* */`) and doc attribute is "
                        "removed and a line that held nothing else is shown "
                        "as `%s`, so a source tree that "
                        "documents the answer cannot hand it to the model; "
                        "line numbers are unchanged and no source file is "
                        "edited. keep: quote the file verbatim, which is "
                        "what every run before 2026-09-22 did"
                        % COMMENT_MARKER)
    p.add_argument("--rounds", type=int, default=None,
                   help="ignored for --proposer oracle, whose arm count is "
                        "determined by the site and candidate lists")
    p.add_argument("--out", required=True)
    p.add_argument("--run-id", default=None)
    p.add_argument("--config", default=os.path.join(REPO, "jev-opt.toml"))
    p.add_argument("-n", "--n", type=int, default=None,
                   help="timed repetitions per round (bench.py --runs)")
    p.add_argument("--warmup", type=int, default=None)
    p.add_argument("--seed-offset", type=int, default=0, metavar="N",
                   help="added to jev-opt.toml [evaluation].seed before it "
                        "seeds the random proposer, the per-round shuffle "
                        "and the confirmation batch (decision 98); default "
                        "0 is identical to no offset, recorded in "
                        "run-manifest.json as `seed` (the effective base "
                        "seed) and `seed_offset`")
    p.add_argument("--bench-set", default="training",
                   choices=("training", "holdout"),
                   help="search rounds use the training cases (SPEC.ja.md 7)")
    p.add_argument("--baseline-dir", default=None,
                   help="reuse a baseline built by an earlier run")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="list the sites (or the oracle's arms) and stop")
    p.add_argument("--print-state", action="store_true",
                   help="print the round-1 state of both phases and stop; no "
                        "HTTP request is made")
    p.add_argument("--smoke", action="store_true",
                   help="mark this run as a smoke test in every artifact")
    p.add_argument("--measure-holdout", action="store_true",
                   help="after the rounds, measure the best plan once on the "
                        "holdout cases (SPEC.ja.md 7)")
    p.add_argument("--keep-binaries", default="best",
                   choices=("best", "all"))
    p.add_argument("--site-set", default=None, metavar="DOTTED.PATH",
                   help="the list of loop site keys in sites.json that this "
                        "experiment is frozen to, e.g. "
                        "oracle.selected_keys_topk_per_mark. All three "
                        "proposers must use the same one (SPEC.ja.md 2)")
    p.add_argument("--oracle-phase", default="all", choices=("A", "B", "all"),
                   help="restrict --proposer oracle to the function-attribute "
                        "arms (A), the loop arms (B) or both (default). The "
                        "rounds themselves are unchanged: both phases are "
                        "still built.")
    p.add_argument("--site-filter", default="all",
                   choices=("all", "vectorized"),
                   help="oracle only: vectorized restricts the loop ARMS to "
                        "loops the baseline dump's post_vectorize record "
                        "says LLVM vectorized. Lossy (zopfli's only moving "
                        "arms were unroll_count on unvectorized loops); a "
                        "staging aid, see docs/search-driver.md")
    p.add_argument("--oracle-candidates", default=None, metavar="GLOB[,GLOB]",
                   help="oracle only: keep the one-factor arms whose "
                        "candidate matches one of these fnmatch globs "
                        "(e.g. 'unroll_count_*'), at every site alike")
    p.add_argument("--protocol", default=None, choices=sorted(PROTOCOLS),
                   help="measurement protocol preset (results.md 170): v1 = "
                        "decision 80 (confirm when the CI excludes 1, A/A leg "
                        "everywhere, oracle reps = reps); v2 = confirm_when "
                        "mde, no A/A leg in oracle one-factor arms, "
                        "reps_oracle 8. Without it the [evaluation] keys "
                        "decide (default v1)")
    p.add_argument("--confirm-when", default=None, choices=CONFIRM_RULES,
                   help="override [evaluation] confirm_when: ci (v1) or mde")
    p.add_argument("--aa-leg", default=None, choices=("on", "off"),
                   help="override [evaluation] aa_leg for the oracle's "
                        "one-factor arm batches")
    p.add_argument("--reps-oracle", type=int, default=None, metavar="N",
                   help="override [evaluation] reps_oracle: repetitions of "
                        "an oracle one-factor arm batch and its confirmation")
    p.add_argument("--mde", type=float, default=None,
                   help="frozen MDE for confirm_when=mde (floor 0.03); "
                        "default [evaluation] mde, else each batch's own "
                        "max(2 x worst half-width, 3%%)")
    p.add_argument("--fn-attr-scope", default="own", choices=("own", "all"),
                   help="own (default): a function attribute goes on the "
                        "mark's own functions and every monomorphization, "
                        "not on the closures defined inside it. all: on "
                        "every function the plugin's mark rule reaches")
    p.add_argument("--no-site-cap", action="store_true",
                   help="ignore the loop-site cap sites.json carries and "
                        "sweep every loop_in_mark site")
    p.add_argument("--allow-unresolved", action="store_true",
                   help="do not stop when a mark resolves to nothing")
    p.add_argument("--no-noop-skip", action="store_true",
                   help="time an arm even when its binary is byte-for-byte "
                        "the baseline's work (decision 80 b: such an arm's "
                        "ratio is 1.0 by construction and the batch measures "
                        "the machine). The classification is recorded either "
                        "way, as `code_class`")
    p.add_argument("--no-confirm-batch", action="store_true",
                   help="do not re-measure an arm whose interval excluded 1 "
                        "in a second independent batch (decision 80 a), and "
                        "fall back to the one-batch acceptance rule")
    p.add_argument("--ignore-apply-failures", action="store_true",
                   help="measure a round even if a plan entry was unmatched "
                        "or vanished (recorded either way)")
    args = p.parse_args()

    cfg = load_config(args.config)
    if args.proposer == "oracle" and args.rounds:
        print("[note] --rounds %d caps the oracle's arms" % args.rounds)
    return Search(args, cfg).run()


if __name__ == "__main__":
    sys.exit(main())
