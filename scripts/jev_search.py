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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(REPO, "scripts", "bench.py")
PLUGIN = os.path.join(REPO, "plugin", "build", "libjevplugin.so")

# The state template. v1 is Experiment 3's, frozen. v2 is decision 73: the
# same sections plus a platform block and a per-site verdict block, and the
# V2 wording of "What is being decided". `--vocab` selects both the
# vocabulary and the state template, because the two together are the one
# measurement condition the prompt study measured (`W7`).
STATE_FORMATS = {"v1": "state-v1-2026-09-22", "v2": "state-v2-2026-09-22"}
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
    },
    "jev": {
        "base_url": "https://ai-gateway.vercel.sh/typesafe",
        "endpoint": "/v1/systemone",
        "model": "typesafe-ai/jev",
        "api_key_env": "AI_GATEWAY_API_KEY",
        "request_timeout_s": 60,
        "retries": 3,
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


class SourceBook:
    """file:line -> a source excerpt, with the path resolution jaq needs.

    DWARF records the path the compiler saw. For a vendored submodule that is
    already an absolute path into targets/<t>/src; for a crates.io dependency
    it points into ~/.cargo/registry; for the standard library it points at a
    path that does not exist on this machine, and the excerpt is then simply
    absent from the state.
    """

    def __init__(self, roots):
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
        self.index = None
        self.paths = []

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
        try:
            lines = open(real, errors="replace").read().splitlines()
        except OSError:
            return None
        if int(line) > len(lines):
            return None          # resolved to the wrong file; say nothing
        lo = max(1, int(line) - ctx)
        hi = min(len(lines), int(line) + ctx)
        body = "\n".join("%5d %s%s" % (n, ">" if n == int(line) else " ",
                                       lines[n - 1])
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
        if not log_path or not os.path.isfile(log_path):
            return
        seen = set()
        for line in open(log_path, errors="replace"):
            m = REMARK_RE.match(line.strip())
            if not m:
                continue
            f, ln, _col, text = m.group(1), int(m.group(2)), m.group(3), m.group(4)
            key = (os.path.basename(f), ln, text)
            if key in seen:
                continue
            seen.add(key)
            self.by_file.setdefault(os.path.basename(f), []).append((ln, text))

    def near(self, path, line, span=40, limit=8):
        if not path or not line:
            return []
        rows = self.by_file.get(os.path.basename(path), [])
        hit = [(ln, t) for ln, t in rows if abs(ln - int(line)) <= span]
        hit.sort(key=lambda r: (abs(r[0] - int(line)), r[0]))
        return hit[:limit]


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
        <mark>::{closure#0}          an item defined inside it  -> inner
        <mark>::helper                       likewise           -> inner

    The naive test "does the name contain `::{`" is wrong: a
    monomorphization's generic arguments routinely contain a closure path
    (`...::seq::<hifijson::Error, jaq_json::read::ws_tk<...{closure#1}>>`),
    and on jaq it misfiled six of fifteen marks as inner items.
    """
    if demangled == mark or not demangled.startswith(mark + "::"):
        return False
    return not demangled[len(mark) + 2:].startswith("<")


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
    hist = render_history(ctx["history"])
    head = STATE_PREAMBLE.format(
        fmt=STATE_FORMAT_VERSION, vocab=V.VOCAB_VERSION,
        target=ctx["target"], binary=ctx["binary"],
        mde=ctx["mde_text"], ncases=len(ctx["cases"]),
        cases=", ".join(ctx["cases"]), reps=ctx["reps"],
        marks="\n".join(marks) or "  (none resolved)",
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


def render_history(history):
    if not history:
        return ("  This is round 1: nothing has been measured yet. The "
                "baseline is the build in which every site is KEEP_DEFAULT.")
    out = ["  | round | correct | aggregate speed ratio | 95% CI | accepted |",
           "  |---|---|---|---|---|"]
    for h in history:
        ci = ("[%.4f, %.4f]" % tuple(h["ci95"])) if h.get("ci95") else "-"
        ratio = ("%.4f" % h["ratio"]) if h.get("ratio") is not None else "-"
        out.append("  | %d | %s | %s | %s | %s |"
                   % (h["round"], "yes" if h["correct"] else "NO",
                      ratio, ci, "yes" if h["accepted"] else "no"))
    out.append("")
    out.append("  A round is accepted as the new best only if the lower end "
               "of its 95% CI is above the best point estimate so far.")
    return "\n".join(out)


def site_history_lines(history, site_id):
    rows = []
    for h in history:
        pick = h["choices"].get(site_id)
        if not pick:
            continue
        ratio = ("%.4f" % h["ratio"]) if h.get("ratio") is not None else "n/a"
        rows.append("    round %d: %s -> whole-build ratio %s%s"
                    % (h["round"], V.spec_spelling_safe(pick), ratio,
                       "" if h["correct"] else " (REJECTED: output changed)"))
    if not rows:
        return "    (this site was not asked about in an earlier round)"
    return "\n".join(rows)


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
        if m["share"] is not None:
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
        out.append("\n".join("  %s:%d: %s" % (os.path.basename(src_file), ln, t)
                             for ln, t in rem)
                   or "  (no remarks at this location)")
    elif item.kind == "loop":
        trip = m.get("trip_count")
        out.append("")
        out.append("site kind      one loop inside a marked function")
        out.append("marked function %s" % m.get("mark"))
        out.append("owner after inlining  %s" % m.get("owner_fn_demangled"))
        out.append("location       %s:%s (loop nesting depth %s)"
                   % (os.path.basename(m.get("leaf_file") or "?"),
                      m.get("leaf_line"), m.get("depth")))
        out.append("profile share of the marked function  %s"
                   % fmt_share(ctx["share_by_mark"].get(m.get("mark"))))
        out.append("average trip count (from the PGO profile)  %s"
                   % ("unknown" if trip is None else "%.0f" % trip))
        out.append("loop body      %s LLVM instructions, calls inside: %s, "
                   "floating-point reduction: %s"
                   % (m.get("body_inst_count"),
                      "yes" if m.get("has_calls") else "no",
                      "yes" if m.get("has_fp_reduction") else "no"))
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
        rem = ctx["remarks"].near(m.get("leaf_file"), m.get("leaf_line"), span=10)
        out.append("")
        out.append("what LLVM said about this region in the baseline build:")
        out.append("\n".join("  %s:%d: %s"
                             % (os.path.basename(m.get("leaf_file") or "?"), ln, t)
                             for ln, t in rem)
                   or "  (no remarks at this location)")
    else:
        out.append("")
        out.append("site kind      one compiler setting for the whole build")
        out.append("")
        out.append("  This is not a per-function decision: whatever is chosen "
                   "here applies to every function in the program, including "
                   "the ones nobody marked.")
    out.append("")
    out.append("  what earlier rounds chose here:")
    out.append(site_history_lines(ctx["history"], item.id))
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
    if insts:
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
    if all_hinted:
        L.append("no-op check: every copy already carries `inlinehint`, so "
                 "the candidate `inline` reproduces the state this site is "
                 "already in")
    elif has_hint:
        L.append("no-op check: some copies already carry `inlinehint`, so "
                 "the candidate `inline` reproduces, on those copies, the "
                 "state this site is already in")
    if has_cold:
        L.append("no-op check: `cold` already appears among the attribute "
                 "sets this site carries")
    share = m.get("share") if m.get("share") is not None else m.get("reach")
    if share is None:
        L.append("share of the program's user cycles: not recorded for this "
                 "mark, so no hotness class")
    else:
        L.append("share of the program's user cycles: %s; hotness class %s "
                 "(rule: %s)" % (fmt_share(share),
                                 classify(float(share), HOT_CLASSES), HOT_RULE))
    n_loops = ctx.get("loops_by_mark", {}).get(m.get("mark"))
    if n_loops is not None:
        L.append("loop sites inside it: %d (`loop_in_mark` sites of this "
                 "mark in the dump)" % n_loops)
    return L


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

    rem = [t for _ln, t in (ctx["remarks"].near(m.get("leaf_file"),
                                                m.get("leaf_line"), span=10)
                            if m.get("leaf_file") else [])]
    reasons, vf = [], []
    for t in rem:
        mm = re.search(r"loop not vectorized:\s*(.+)$", t)
        if mm and any(k in mm.group(1).lower() for k in LEGALITY_REASONS):
            r = mm.group(1).strip()
            if r not in reasons:
                reasons.append(r)
        vf += [int(x) for x in re.findall(r"vectorization width: (\d+)", t)]
    if not rem:
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
    if m.get("already_vectorized") and not vf:
        L.append("no-op check: the dump records this loop as already "
                 "vectorized at the point the hint is attached, so a "
                 "`vectorize_*` candidate may reproduce the state it is "
                 "already in")
    adv = [t.split(": ", 1)[1] for t in rem
           if "advising against unrolling" in t and ": " in t]
    if adv:
        L.append("unroller, from the baseline remarks at this line: %s"
                 % adv[0])
    if any("cost-model indicates that vectorization" in t for t in rem):
        L.append("cost model, from the baseline remarks at this line: "
                 "vectorization not beneficial")
    L.append("caveat that applies to every loop here: remarks are attributed "
             "by source location only, so several loops can share one line")
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


class JevClient:
    """One HTTP request per phase, logged as JSONL and as a readable line.

    SPEC.ja.md 6: the Authorization header is never written to either log.
    """

    def __init__(self, cfg, log_dir, run_id):
        self.cfg = cfg
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
        if not os.path.isfile(self.log_path):
            with open(self.log_path, "w") as f:
                f.write("# jev-opt request log, run %s\n" % run_id)
                f.write("# ts round phase questions http_status latency_ms "
                        "input_tokens output_tokens cost_usd\n")

    def ask(self, state, questions, round_no, phase, site_map):
        """Returns (answers dict, jsonl line number) or (None, line)."""
        if self.key is None:
            self.key = read_api_key(self.cfg["api_key_env"])
        body = {"model": self.model, "state": state, "questions": questions}
        payload = json.dumps(body).encode()
        status, resp, latency, err = None, None, 0.0, None
        attempts = []
        for attempt in range(1, int(self.cfg["retries"]) + 1):
            req = urllib.request.Request(
                self.url, data=payload, method="POST",
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + self.key})
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(
                        req, timeout=float(self.cfg["request_timeout_s"])) as r:
                    status = r.status
                    resp = json.loads(r.read().decode())
                latency = (time.monotonic() - t0) * 1e3
                err = None          # a retry that succeeded is not an error
                break
            except urllib.error.HTTPError as e:
                latency = (time.monotonic() - t0) * 1e3
                status = e.code
                try:
                    resp = json.loads(e.read().decode())
                except Exception:
                    resp = None
                err = "HTTP %d" % e.code
                attempts.append(err)
                if e.code < 500:
                    break
            except Exception as e:                       # timeout, DNS, ...
                latency = (time.monotonic() - t0) * 1e3
                err = "%s: %s" % (type(e).__name__, e)
                attempts.append(err)
            if attempt < int(self.cfg["retries"]):
                time.sleep(2.0 * attempt)

        usage = (resp or {}).get("usage") or {}
        gw = ((resp or {}).get("provider_metadata") or {}).get("gateway") or {}
        try:
            cost = float(gw.get("cost") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0

        self.n_lines += 1
        line_no = self.n_lines
        record = {"ts": datetime.datetime.now().astimezone().isoformat(),
                  "run_id": self.run_id, "round": round_no, "phase": phase,
                  "vocab_version": V.VOCAB_VERSION,
                  "state_format": STATE_FORMAT_VERSION,
                  "site_map": site_map, "request": body, "response": resp,
                  "http_status": status, "latency_ms": round(latency, 1),
                  "error": err, "failed_attempts": attempts}
        with open(self.jsonl_path, "a") as f:
            f.write(json.dumps(record) + "\n")

        self.totals["requests"] += 1
        self.totals["questions"] += len(questions)
        self.totals["latency_ms"] += latency
        self.totals["max_latency_ms"] = max(self.totals["max_latency_ms"], latency)
        self.totals["input_tokens"] += int(usage.get("input_tokens") or 0)
        self.totals["output_tokens"] += int(usage.get("output_tokens") or 0)
        self.totals["cost_usd"] += cost
        with open(self.log_path, "a") as f:
            f.write("%s r%d %-7s %3d %s %8.1f %7d %6d %.8f%s\n"
                    % (record["ts"], round_no, phase, len(questions),
                       status, latency, int(usage.get("input_tokens") or 0),
                       int(usage.get("output_tokens") or 0), cost,
                       ("  ERROR " + err) if err else
                       ("  (after %d failed attempt(s): %s)"
                        % (len(attempts), ", ".join(attempts))
                        if attempts else "")))

        if resp is None or "answers" not in (resp or {}):
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
                 readout="forced_top1"):
        self.client = client
        self.cfg = cfg
        self.knobs = knobs
        self.max_state_chars = max_state_chars
        self.readout = readout

    def choose(self, items, ctx, round_no, phase):
        picks, why = {}, {}
        for batch_i, batch in enumerate(self._batches(items, ctx)):
            questions, site_map = questions_for(batch, ctx, self.knobs)
            state = state_header(ctx, len(batch)) + \
                "".join(state_section(it, ctx) for it in batch)
            answers, line_no = self.client.ask(state, questions, round_no,
                                               "%s%s" % (phase, "" if batch_i == 0
                                                         else ".%d" % batch_i),
                                               site_map)
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
        self.read_out(items, picks, why, ctx, phase)
        return picks, why

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
        best = {}
        for h in history:
            if not h["correct"] or h.get("ratio") is None:
                continue
            for site, cand in h["choices"].items():
                if cand == V.KEEP_DEFAULT:
                    continue
                cur = best.get(site)
                if cur is None or h["ratio"] > cur[1]:
                    best[site] = (cand, h["ratio"], h.get("ci95") or [None, None])
        # A site joins the combination only if its best arm's 95% CI LOWER
        # bound is above 1. The point estimate alone is not evidence at this
        # noise floor: results.md "Experiment 3 (jaq)" 99 saw three copies of
        # one binary spread 2.1 points, so "ratio > 1" selects noise as
        # readily as it selects an effect. The point-estimate set is recorded
        # beside the chosen one so the difference is visible.
        chosen = {s: c for s, (c, r, ci) in best.items()
                  if ci[0] is not None and ci[0] > 1.0}
        point = {s: c for s, (c, r, ci) in best.items() if r > 1.0}
        return {"kind": "combination", "site": None, "candidate": None,
                "choices": chosen, "selected_by": "ci95_lower > 1",
                "per_site_best": {s: {"candidate": c, "ratio": r, "ci95": ci}
                                  for s, (c, r, ci) in best.items()},
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
            entries.append(e)
    entries.sort(key=lambda e: e["fn"])
    return entries


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


def measure(cand_bin, base_bin, shell, out_dir, reps, warmup, seed, resamples):
    """Interleaved timing of cand vs base vs an in-run A/A copy of base."""
    timing = os.path.join(out_dir, "timing")
    os.makedirs(timing, exist_ok=True)
    labels = [("base", strip_copy(base_bin, os.path.join(timing, "base"))),
              ("cand", strip_copy(cand_bin, os.path.join(timing, "cand"))),
              ("aa", strip_copy(base_bin, os.path.join(timing, "aa")))]
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
    return json.load(open(stats_json)), None


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
        self.state_v2 = (args.vocab == "v2")
        V.set_version(args.vocab)
        set_state_format(args.vocab)
        self.demangler = Demangler()
        self._platform = None
        self.marks = read_marks(args.marks)
        self.sidecar = load_sidecar(args.sites)
        self.shell = shell_config(self.target, args.bench_set)
        self.reps = args.n if args.n is not None else int(
            cfg["evaluation"]["repetitions"])
        self.warmup = args.warmup if args.warmup is not None else int(
            cfg["evaluation"]["warmup"])
        self.seed = int(cfg["evaluation"]["seed"])
        self.resamples = int(cfg["evaluation"]["resamples"])
        self.target_dir = os.path.join(REPO, "target-%s-jevsearch" % self.target)
        self.rounds_path = os.path.join(self.out, "rounds.jsonl")
        self.history = []
        self.best = {"round": 0, "ratio": 1.0, "plan": None,
                     "label": "baseline"}
        self.jev = None
        self.t0 = time.time()

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
        self.source = SourceBook(roots)
        self.remarks = RemarkBook(meta["log"])
        self.share_by_mark = {i.meta["mark"]: (i.meta["share"]
                                               if i.meta["share"] is not None
                                               else i.meta["reach"])
                              for i in self.fn_list}
        self.loops_by_mark = {}
        for s_ in self.base_sites:
            m = s_.get("mark")
            self.loops_by_mark[m] = self.loops_by_mark.get(m, 0) + 1
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
            arms = proposer.plan_arms(self.fn_list, self.base_loops,
                                      self.build_list, self.args.oracle_phase)
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
            return 0

        if self.args.print_state:
            for phase, items in (("A", self.fn_list + self.build_list),
                                 ("B", self.base_loops)):
                ctx = self.ctx({"arm": None,
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
            return 0

        self.load_resume()

        round_no = len(self.history)
        limit = (10 ** 9 if self.args.proposer == "oracle"
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
            self.history.append(self.history_entry(rec))
            self.update_best(rec)

        self.measure_holdout()
        self.finish()
        return 0

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
                             os.path.join(self.out, "jev-log"), self.run_id)
        return JevProposer(self.jev, self.cfg["jev"], self.knobs,
                           int(self.cfg["search"]["max_state_chars"]),
                           self.args.readout)

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
        c = {"target": self.target, "binary": self.shell["bin_name"],
             "fn_items": self.fn_list, "history": self.history,
             "cases": [w.split("=", 1)[0] for w in self.shell["workloads"]],
             "reps": self.reps, "mde_text": "3%",
             "source": self.source, "remarks": self.remarks,
             "share_by_mark": self.share_by_mark, "fn_source": self.fn_source,
             "loops_by_mark": self.loops_by_mark,
             "fn_choice_text": "",
             "knobs": self.knobs,
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
               "readout": self.args.readout,
               "case_set": self.shell["bench_set"], "arm": arm,
               "reps": self.reps, "warmup": self.warmup,
               "smoke": bool(self.args.smoke)}
        print("\n=== round %d (%s) ===" % (round_no, self.args.proposer))

        # -- phase A: function attributes (+ the build-wide knob) ---------
        items_a = self.fn_list + self.build_list
        ctx_a = self.ctx({"arm": arm})
        picks_a, why_a = proposer.choose(items_a, ctx_a, round_no, "A")
        fn_attrs = fn_attrs_from(picks_a, items_a, why_a, self.knobs)
        basis = basis_of(fn_attrs)
        plan_a = os.path.join(rdir, "plan-a.json")
        sha_a = write_plan(plan_a, "r%d-a" % round_no, fn_attrs, [], basis)
        knob_flags = build_knob_flags(picks_a, self.knobs)
        rec["phase_a"] = {"choices": picks_a, "why": why_a,
                          "readout": ctx_a.get("readout"),
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
        ctx_b = self.ctx({"arm": arm, "fn_choice_text": fn_text})
        picks_b, why_b = proposer.choose(items_b, ctx_b, round_no, "B")
        loop_md = loop_md_from(picks_b, items_b, why_b)
        plan_b = os.path.join(rdir, "plan-b.json")
        sha_b = write_plan(plan_b, "r%d-b" % round_no, fn_attrs, loop_md, basis)
        rec["phase_b"] = {"choices": picks_b, "why": why_b,
                          "readout": ctx_b.get("readout"),
                          "loop_md": loop_md, "plan_sha256": sha_b}
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

        stats, err = measure(binary, self.baseline_bin(), self.shell, rdir,
                             self.reps, self.warmup, self.seed + round_no,
                             self.resamples)
        if stats is None:
            rec["status"] = "measure-failed"
            rec["error"] = err
            rec["accepted"] = False
            print("[B] %s" % err)
            return rec
        agg = stats["aggregate"]
        rec["ratio"] = agg["cand"]["ratio"]
        rec["ci95"] = agg["cand"]["ci95"]
        rec["aa"] = {"ratio": agg["aa"]["ratio"], "ci95": agg["aa"]["ci95"],
                     "halfwidth": agg["aa"]["halfwidth"]}
        rec["mde"] = stats["mde"]
        rec["status"] = "measured"
        print("[B] ratio %.4f  CI [%.4f, %.4f]  (in-run A/A %.4f +-%.4f)"
              % (rec["ratio"], rec["ci95"][0], rec["ci95"][1],
                 rec["aa"]["ratio"], rec["aa"]["halfwidth"]))
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
        return {"round": rec["round"], "choices": choices,
                "correct": bool(rec.get("correct")),
                "ratio": rec.get("ratio"), "ci95": rec.get("ci95"),
                "accepted": bool(rec.get("accepted"))}

    def update_best(self, rec):
        """The pre-registered acceptance rule (docs/search-driver.md).

        A round becomes the new best only if it is correct, every plan entry
        took effect, and the LOWER end of its 95% CI is above the best point
        estimate so far. The baseline is the first best, at ratio 1.0.
        """
        ok = (rec.get("status") == "measured" and rec.get("correct")
              and rec["ci95"][0] > self.best["ratio"])
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
        self.best = {"round": rec["round"], "ratio": rec["ratio"],
                     "ci95": rec["ci95"],
                     "plan": os.path.join(self.out, "round-%02d" % rec["round"],
                                          "plan-b.json"),
                     "label": "round-%02d" % rec["round"]}
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
            self.history.append(self.history_entry(rec))
            if rec.get("accepted"):
                self.best = {"round": rec["round"], "ratio": rec["ratio"],
                             "ci95": rec.get("ci95"),
                             "plan": os.path.join(self.out, "round-%02d"
                                                  % rec["round"], "plan-b.json"),
                             "label": "round-%02d" % rec["round"]}
        print("[resume] %d rounds already recorded, best = %s (%.4f)"
              % (len(self.history), self.best["label"], self.best["ratio"]))

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
            "readout": self.args.readout,
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
            "seed": self.seed,
            "rustc": subprocess.run(["rustc", "-vV"], text=True,
                                    capture_output=True).stdout,
            "lscpu_e": subprocess.run(["lscpu", "-e"], text=True,
                                      capture_output=True).stdout,
            "best": self.best, "holdout": getattr(self, "holdout", None),
            "jev_totals": self.jev.totals if self.jev else None,
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
        out.append("Acceptance rule, fixed before the first round: a round "
                   "becomes the best so far only if its output matches the "
                   "baseline on every case, every plan entry was applied, and "
                   "the lower end of its 95% CI is above the best point "
                   "estimate so far (the baseline, 1.0000, is the first).")
        out.append("")
        out.append("| round | fn hints | loop hints | ambiguous keys | apply "
                   "problems | correct | ratio | 95% CI | in-run A/A | "
                   "accepted |")
        out.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            pa, pb = r.get("phase_a") or {}, r.get("phase_b") or {}
            ci = ("[%.4f, %.4f]" % tuple(r["ci95"])) if r.get("ci95") else "-"
            aa = ("%.4f ±%.4f" % (r["aa"]["ratio"], r["aa"]["halfwidth"])) \
                if r.get("aa") else "-"
            out.append("| %d | %d | %d | %d | %s | %s | %s | %s | %s | %s |"
                       % (r["round"], len(pa.get("fn_attrs") or []),
                          len(pb.get("loop_md") or []),
                          pb.get("n_ambiguous") or 0,
                          ", ".join("%s=%s" % kv for kv in
                                    (pb.get("bad_outcomes") or {}).items()) or "none",
                          "yes" if r.get("correct") else "NO",
                          ("%.4f" % r["ratio"]) if r.get("ratio") is not None
                          else r.get("status", "-"),
                          ci, aa, "yes" if r.get("accepted") else "no"))
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
    p.add_argument("--vocab", default="v2", choices=("v1", "v2"),
                   help="the frozen vocabulary AND state template: v1 is "
                        "Experiment 3's, v2 (default) is decision 73 --- the "
                        "prompt study's W7, i.e. the mechanical verdict "
                        "block in both phases, the applicability conditions "
                        "in the function criteria only, a neutral "
                        "KEEP_DEFAULT, the V2 question wording and the "
                        "platform block")
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
    p.add_argument("--rounds", type=int, default=None,
                   help="ignored for --proposer oracle, whose arm count is "
                        "determined by the site and candidate lists")
    p.add_argument("--out", required=True)
    p.add_argument("--run-id", default=None)
    p.add_argument("--config", default=os.path.join(REPO, "jev-opt.toml"))
    p.add_argument("-n", "--n", type=int, default=None,
                   help="timed repetitions per round (bench.py --runs)")
    p.add_argument("--warmup", type=int, default=None)
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
    p.add_argument("--ignore-apply-failures", action="store_true",
                   help="measure a round even if a plan entry was unmatched "
                        "or vanished (recorded either way)")
    args = p.parse_args()

    cfg = load_config(args.config)
    if args.proposer == "oracle" and args.rounds:
        print("[note] --rounds is ignored for the oracle")
    return Search(args, cfg).run()


if __name__ == "__main__":
    sys.exit(main())
