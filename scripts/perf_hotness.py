#!/usr/bin/env python3
"""Per-symbol wall-clock (user-CPU) shares from the perf.data files that
scripts/perf_marks_profile.sh records, per workload and aggregated.

This is the profdata-free twin of scripts/interp_share.py, and the two
disagree on jaq for two structural reasons rather than by noise:

  * `-Cprofile-generate` instruments Rust only. mimalloc is C (results.md
    "Stage 0 (jaq)" section 51), so the PGO profile reduces the whole
    allocator to two one-instruction thunks. perf samples the instruction
    pointer and sees `mi_free` for what it is.
  * A profdata record is a *pre-inlining* IR function; a perf sample lands in
    the post-fat-LTO symbol that absorbed it.

Shares are of **user** CPU time: perf_event_paranoid is 2, so `cycles:u` is
all this machine can sample and kernel time is invisible. Sample periods are
summed (what `perf report`'s Overhead column does).

Addresses are resolved here rather than by perf, because the binary contains
761 demangled names with more than one definition (`jaq_json::read::parse`
has four) and the marks file names *source functions*, so the copies must be
summed. Each sample's ip is turned into a link-time vaddr through the
PERF_RECORD_MMAP2 event of its own process and the binary's LOAD headers,
then resolved against `nm`.

`--inline` additionally resolves every sample to its full inlined frame stack
with llvm-symbolizer, giving the share of time whose machine code *belongs
to* a source function wherever fat LTO placed it. That is the unit a
compile-time mark names, so it is the table the marks file is built from.

Usage:
  scripts/perf_hotness.py --binary target-jaq-pgo-use/.../jaq --inline \\
      --top 30 --tsv artifacts/jaq-marks/perf-self.tsv \\
      --inline-tsv artifacts/jaq-marks/perf-inline.tsv /tmp/perf-flat/*.data
"""

import argparse
import bisect
import collections
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from interp_share import load_code, crate_of, demangle  # noqa: E402

MMAP_RE = re.compile(
    r"PERF_RECORD_MMAP2 (\d+)/\d+: \[(0x[0-9a-f]+)\((0x[0-9a-f]+)\) @ "
    r"(0x[0-9a-f]+|0)[^\]]*\]: ([-a-z]+) (.*)$")
SAMPLE_RE = re.compile(r"^\s*(\S+)\s+(\d+)\s+(\d+)\s+([0-9a-f]+)\s+\((.*)\)\s*$")


def perf_path(repo):
    return subprocess.run([os.path.join(repo, "scripts/perf_local.sh"), "path"],
                          capture_output=True, text=True,
                          check=True).stdout.strip()


def load_segments(binary):
    """[(p_offset, p_filesz, p_vaddr)] of the LOAD segments."""
    out = subprocess.run(["readelf", "-lW", binary], capture_output=True,
                         text=True, check=True).stdout
    segs = []
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 6 and p[0] == "LOAD":
            segs.append((int(p[1], 16), int(p[4], 16), int(p[2], 16)))
    return segs


def load_symbols(binary):
    """sorted [(vaddr, size, demangled)] of the text symbols."""
    nm = subprocess.run(["nm", "-S", "--defined-only", binary],
                        capture_output=True, text=True, check=True).stdout
    raw = []
    for line in nm.splitlines():
        p = line.split()
        if len(p) < 4 or p[2].lower() != "t":
            continue
        try:
            raw.append((int(p[0], 16), int(p[1], 16), " ".join(p[3:])))
        except ValueError:
            continue
    dem = demangle([n for _, _, n in raw])
    syms = sorted((a, s, dem[n]) for a, s, n in raw)
    # Anything whose mangled name does not start with `_R` was not compiled by
    # rustc: on jaq that is mimalloc's C (results.md "Stage 0 (jaq)" sec. 51),
    # which -Cprofile-generate cannot instrument and interp_share.py cannot
    # see. Keep the class so the tables can say how much of the time it is.
    cls = {dem[n]: ("rust" if n.startswith("_R") else "c") for _, _, n in raw}
    return syms, [a for a, _, _ in syms], cls


def read_case(perf, data, binary, segs):
    """(Counter vaddr->period, Counter dso->period outside the binary)."""
    out = subprocess.run(
        [perf, "script", "-i", data, "--show-mmap-events",
         "-F", "comm,pid,period,ip,dso"],
        capture_output=True, text=True, check=True).stdout
    want = os.path.realpath(binary)
    maps = collections.defaultdict(list)     # pid -> [(lo, hi, pgoff)]
    inside, outside = collections.Counter(), collections.Counter()
    nsamples = [0]
    for line in out.splitlines():
        m = MMAP_RE.search(line)
        if m:
            pid, start, length, pgoff, perms, path = m.groups()
            if "x" in perms and path.startswith("/") \
                    and os.path.realpath(path) == want:
                lo = int(start, 16)
                maps[int(pid)].append((lo, lo + int(length, 16),
                                       int(pgoff, 16)))
            continue
        m = SAMPLE_RE.match(line)
        if not m:
            continue
        _comm, pid, period, ip, dso = m.groups()
        period, pid, ip = int(period), int(pid), int(ip, 16)
        nsamples[0] += 1
        hit = None
        for lo, hi, pgoff in maps.get(pid, ()):
            if lo <= ip < hi:
                hit = ip - lo + pgoff
                break
        if hit is None:
            outside[dso] += period
            continue
        for off, size, vaddr in segs:
            if off <= hit < off + size:
                inside[hit - off + vaddr] += period
                break
        else:
            outside["<no LOAD segment>"] += period
    return inside, outside, nsamples[0]


def resolve(vaddr, syms, starts):
    i = bisect.bisect_right(starts, vaddr) - 1
    if i < 0:
        return "<unmapped>"
    a, s, name = syms[i]
    if s and vaddr >= a + s:
        return "<between symbols>"
    return name


def inline_stacks(binary, addrs):
    """vaddr -> [innermost .. outermost] source function names."""
    if not addrs:
        return {}
    addrs = sorted(addrs)
    inp = "\n".join("0x%x" % a for a in addrs)
    try:
        out = subprocess.run(["llvm-symbolizer", "--inlining",
                              "--functions=linkage", "--demangle",
                              "--obj", binary],
                             input=inp, capture_output=True, text=True,
                             check=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print("llvm-symbolizer unavailable (%s)" % e, file=sys.stderr)
        return {}
    res, cur, i = {}, [], 0
    for line in out.splitlines():
        if line.strip() == "":
            if i < len(addrs):
                res[addrs[i]] = cur
            cur, i = [], i + 1
            continue
        cur.append(line)
    if cur and i < len(addrs):
        res[addrs[i]] = cur
    # llvm-symbolizer prints FUNCTION then FILE:LINE for each frame
    return {a: [f for j, f in enumerate(v) if j % 2 == 0 and f != "??"]
            for a, v in res.items()}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", nargs="+")
    ap.add_argument("--binary", required=True)
    ap.add_argument("--perf", default=None)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--tsv", default=None)
    ap.add_argument("--inline-tsv", default=None)
    ap.add_argument("--inline", action="store_true")
    ap.add_argument("--crates", action="store_true")
    ap.add_argument("--marks", default=None,
                    help="a jev-marks.txt; print the share of samples whose "
                         "inlined frame stack contains a marked function")
    a = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    perf = a.perf or perf_path(repo)
    segs = load_segments(a.binary)
    syms, starts, sym_class = load_symbols(a.binary)
    code = load_code(a.binary)

    per_case, per_out, per_n = {}, {}, {}
    for path in a.data:
        label = os.path.basename(path).rsplit(".", 1)[0]
        per_case[label], per_out[label], per_n[label] = \
            read_case(perf, path, a.binary, segs)
    labels = sorted(per_case)

    # ---- self time by symbol -------------------------------------------
    sym_case = {}
    for label, c in per_case.items():
        s = collections.Counter()
        for vaddr, period in c.items():
            s[resolve(vaddr, syms, starts)] += period
        sym_case[label] = s
    agg = collections.Counter()
    for s in sym_case.values():
        agg.update(s)
    total = sum(agg.values())
    case_tot = {l: sum(sym_case[l].values()) or 1 for l in labels}
    eq = collections.Counter()
    for l in labels:
        for k, v in sym_case[l].items():
            eq[k] += 100.0 * v / case_tot[l] / len(labels)

    print("cases: %d   in-binary periods: %d" % (len(labels), total))
    for l in labels:
        o = sum(per_out[l].values())
        t = case_tot[l]
        print("  %-18s samples %7d  addrs %6d  in-binary %5.2f%% of user cycles"
              % (l, per_n[l], len(per_case[l]),
                 100.0 * t / (t + o) if t + o else 0))
    out_all = collections.Counter()
    for o in per_out.values():
        out_all.update(o)
    tot_incl = total + sum(out_all.values())
    print("  outside the binary: %.2f%%  (%s)"
          % (100.0 * sum(out_all.values()) / tot_incl,
             ", ".join("%s %.2f%%" % (os.path.basename(k) or k,
                                      100.0 * v / tot_incl)
                       for k, v in out_all.most_common(3))))
    print()

    rows = []
    for sym, v in agg.most_common():
        cd = code.get(sym, {"insns": 0, "vec": 0, "backedges": 0})
        r = {"share": 100.0 * v / total, "eq": eq[sym], "period": v,
             "insns": cd["insns"], "vec": cd["vec"],
             "backedges": cd["backedges"],
             "crate": (crate_of(sym) if sym_class.get(sym, "rust") == "rust"
                       else "C:mimalloc"),
             "lang": sym_class.get(sym, "?"), "function": sym}
        for l in labels:
            r[l] = 100.0 * sym_case[l][sym] / case_tot[l]
        rows.append(r)

    print("  #   share    eq-w  insns  vec  bedge  crate        function")
    for i, r in enumerate(rows[:a.top], 1):
        print("  %-3d %6.2f%% %6.2f%% %6d %4d %6d  %-12s %s"
              % (i, r["share"], r["eq"], r["insns"], r["vec"],
                 r["backedges"], r["crate"][:12], r["function"][:160]))
    print()
    for k in (5, 10, 20, 30):
        if k <= len(rows):
            print("  top %-3d %6.2f%%" % (k, sum(x["share"] for x in rows[:k])))

    if a.crates:
        cr = collections.Counter()
        for r in rows:
            cr[r["crate"]] += r["share"]
        print("\n  crates:")
        for k, v in cr.most_common(18):
            print("    %8.2f%%  %s" % (v, k))

    if a.tsv:
        os.makedirs(os.path.dirname(a.tsv) or ".", exist_ok=True)
        cols = ["share", "eq", "period", "insns", "vec", "backedges"] \
            + labels + ["lang", "crate", "function"]
        with open(a.tsv, "w") as f:
            f.write("\t".join(cols) + "\n")
            for r in rows:
                f.write("\t".join(("%.6f" % r[c]) if isinstance(r[c], float)
                                  else str(r[c]) for c in cols) + "\n")
        print("\nwrote %s (%d rows)" % (a.tsv, len(rows)))

    if a.marks and not a.inline:
        a.inline = True
    if not a.inline:
        return 0

    all_addrs = set()
    for c in per_case.values():
        all_addrs |= set(c)
    stacks = inline_stacks(a.binary, all_addrs)
    if not stacks:
        return 0
    inl_case, self_case = {}, {}
    for label, c in per_case.items():
        ic, sc = collections.Counter(), collections.Counter()
        for vaddr, period in c.items():
            st = stacks.get(vaddr) or []
            for fn in set(st):
                ic[fn] += period
            if st:
                sc[st[0]] += period
        inl_case[label], self_case[label] = ic, sc
    inl, slf = collections.Counter(), collections.Counter()
    for c in inl_case.values():
        inl.update(c)
    for c in self_case.values():
        slf.update(c)

    print("\n  inline-aware: `reach` = share of user cycles running machine "
          "code that belongs to this source function, wherever fat LTO put "
          "it; `leaf` = share where it is the innermost frame")
    print("  #   reach    leaf   crate        function")
    for i, (fn, v) in enumerate(inl.most_common(a.top), 1):
        print("  %-3d %6.2f%% %6.2f%%  %-12s %s"
              % (i, 100.0 * v / total, 100.0 * slf[fn] / total,
                 crate_of(fn)[:12], fn[:160]))

    if a.marks:
        # `#` starts a comment only at the start of a line: a v0 demangled
        # name contains `{closure#3}`.
        marks = [l.rstrip("\n") for l in open(a.marks)]
        marks = [m.strip() for m in marks
                 if m.strip() and not m.lstrip().startswith("#")]
        print("\n  marks: %d from %s" % (len(marks), a.marks))
        hit = {}
        for fn in set().union(*[set(c) for c in inl_case.values()]) \
                if inl_case else set():
            hit[fn] = any(fn == m or fn.startswith(m + "::<")
                          or fn.startswith(m + "::{closure") for m in marks)
        per_mark = collections.Counter()
        cov = collections.Counter()      # label -> covered periods
        for label, c in per_case.items():
            for vaddr, period in c.items():
                st = stacks.get(vaddr) or []
                if any(hit.get(f) for f in st):
                    cov[label] += period
                # one credit per MARK per sample, not per matching frame: a
                # stack holds both `f` and `f::{closure#1}` and both match
                # the same line.
                matched = {m for f in set(st) for m in marks
                           if f == m or f.startswith(m + "::<")
                           or f.startswith(m + "::{closure")}
                for m in matched:
                    per_mark[m] += period
        print("  %-8s %7s %7s" % ("", "reach", "of case"))
        for m in marks:
            print("  %6.2f%%  %s" % (100.0 * per_mark[m] / total, m[:140]))
        print("\n  union coverage %6.2f%% of in-binary user cycles"
              % (100.0 * sum(cov.values()) / total))
        for l in labels:
            print("    %-18s %6.2f%%" % (l, 100.0 * cov[l] / case_tot[l]))
        unmark = collections.Counter()
        for label, c in per_case.items():
            for vaddr, period in c.items():
                st = stacks.get(vaddr) or []
                if not any(hit.get(f) for f in st):
                    unmark[resolve(vaddr, syms, starts)] += period
        rest = sum(unmark.values())
        c_rest = sum(v for k, v in unmark.items()
                     if sym_class.get(k, "rust") == "c")
        print("  not covered: %6.2f%%, of which mimalloc's C %6.2f%%"
              % (100.0 * rest / total, 100.0 * c_rest / total))
        print("  markable (Rust) cycles covered: %6.2f%%"
              % (100.0 * sum(cov.values())
                 / (total - sum(v for k, v in agg.items()
                                if sym_class.get(k, "rust") == "c"))))
        for k, v in unmark.most_common(8):
            print("    %6.2f%%  %s" % (100.0 * v / total, k[:120]))

    if a.inline_tsv:
        os.makedirs(os.path.dirname(a.inline_tsv) or ".", exist_ok=True)
        with open(a.inline_tsv, "w") as f:
            f.write("\t".join(["reach", "leaf", "period"] +
                              ["reach_" + l for l in labels] +
                              ["crate", "function"]) + "\n")
            for fn, v in inl.most_common():
                per = [100.0 * inl_case[l][fn] / case_tot[l] for l in labels]
                f.write("\t".join(["%.6f" % (100.0 * v / total),
                                   "%.6f" % (100.0 * slf[fn] / total), str(v)]
                                  + ["%.6f" % x for x in per]
                                  + [crate_of(fn), fn]) + "\n")
        print("\nwrote %s (%d rows)" % (a.inline_tsv, len(inl)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
