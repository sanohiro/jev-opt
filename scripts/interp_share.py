#!/usr/bin/env python3
"""The SPEC.ja.md 6.1-4 interpreter-layer share, without the plugin.

SPEC.ja.md 6.1-4 asks, for jaq: what fraction of `total_score` sits in
functions that contain no loop, or whose work is indirect calls, reference
counting, map lookup and allocation. No loop hint reaches that layer, and the
gate is 70%.

The spec sources that from the Stage 2 plugin dump (profile count x loop-body
instruction count, SPEC.ja.md 8.2). The plugin does not exist yet, so this
script builds the closest thing the profdata and the binary can give:

  * `sum_count`  the sum of a function's PGO block counts --- the weight used
                 throughout results.md section 31.5 for the same question on
                 zopfli.
  * `entry`      the function's PGO entry count. LLVM's IR instrumentation
                 puts it in counter 0 (that is what llvm-profdata's "Maximum
                 function count" reads), and `llvm-profdata show` does not
                 print it separately, so it is taken from `Block counts[0]`.
  * `maxblk`     its largest block count.
  * `trip`       maxblk / entry, a per-function trip-count proxy. About 1 means
                 straight-line glue; a large value means a loop that really
                 iterates. (It is a proxy: `maxblk` is the hottest block, which
                 for a nested loop is the inner one.)
  * `insns`, `vec`  its own machine code, and how much of it uses a vector
                 register.
  * `backedges`  jumps inside the symbol whose target is at a lower address
                 inside the same symbol, i.e. machine-code loops. **A function
                 with zero backedges cannot be reached by any loop hint**,
                 which is the one part of the (a)/(b) split that needs no
                 judgement.

Under fat LTO a hot symbol is an inline host and can hold both glue and a real
byte loop (results.md section 31.5 says so for zopfli's `lz77_optimal`), so
the final (a)/(b) call is still made by hand in results.md; this script
supplies the evidence and the arithmetic.

Usage:
  scripts/interp_share.py pgo/jaq/merged.profdata \\
      --binary target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/jaq \\
      --top 20
  scripts/interp_share.py pgo/jaq/per-case/objsearch.profdata --crates
"""

import argparse
import bisect
import collections
import re
import subprocess
import sys

VEC_RE = re.compile(r"\b[xyz]mm\d+\b")
JMP_RE = re.compile(r"^(j[a-z]+|loop[a-z]*)\s+([0-9a-f]+)\b")


def llvm_tool(name):
    sysroot = subprocess.run(["rustc", "--print", "sysroot"],
                             capture_output=True, text=True, check=True).stdout.strip()
    triple = re.search(r"^host: (.*)$",
                       subprocess.run(["rustc", "-vV"], capture_output=True,
                                      text=True, check=True).stdout, re.M).group(1)
    return f"{sysroot}/lib/rustlib/{triple}/bin/{name}"


# ---------------------------------------------------------------------------
# profdata
# ---------------------------------------------------------------------------

def load_profile(profdata, tool):
    out = subprocess.run([tool, "show", "--all-functions", "--counts", profdata],
                         capture_output=True, text=True, check=True).stdout
    funcs = {}
    name = None
    for line in out.splitlines():
        m = re.match(r"^  (\S.*):$", line)
        if m:
            name = m.group(1)
            continue
        m = re.match(r"^    Block counts: \[(.*)\]$", line)
        if m and name is not None:
            counts = [int(x) for x in m.group(1).split(", ") if x.strip()]
            short = name.split(";")[-1]
            rec = funcs.setdefault(short, {"name": short, "entry": 0,
                                           "max": 0, "sum": 0})
            rec["entry"] += counts[0] if counts else 0
            rec["max"] = max(rec["max"], max(counts) if counts else 0)
            rec["sum"] += sum(counts)
            name = None
    return funcs


# ---------------------------------------------------------------------------
# binary
# ---------------------------------------------------------------------------

def load_code(binary):
    """demangled symbol -> dict(insns, vec, backedges), one objdump pass.

    Keyed by the DEMANGLED name on purpose. A v0 symbol for a generic
    instantiation carries the *instantiating crate* as a trailing
    `Cs<hash>_<crate>` node, and the profdata record and the surviving LTO
    symbol routinely disagree about which crate that was (jaq's hottest
    function, hifijson's `write_until`, is recorded under `jaq_fmts` and
    emitted under `jaq`). Demangling drops that node, so the two sides join.
    """
    nm = subprocess.run(["nm", "-S", "--defined-only", binary],
                        capture_output=True, text=True, check=True).stdout
    syms = []
    for line in nm.splitlines():
        p = line.split()
        if len(p) < 4 or p[2].lower() != "t":
            continue
        try:
            a, s = int(p[0], 16), int(p[1], 16)
        except ValueError:
            continue
        if s:
            syms.append((a, s, " ".join(p[3:])))
    syms.sort()
    starts = [a for a, _, _ in syms]
    dem_sym = demangle([n for _, _, n in syms])
    raw = {name: {"insns": 0, "vec": 0, "backedges": 0} for _, _, name in syms}

    dis = subprocess.run(["objdump", "-d", "--no-show-raw-insn", binary],
                         capture_output=True, text=True, check=True).stdout
    cur = None
    for line in dis.splitlines():
        m = re.match(r"^\s+([0-9a-f]+):\t(.*)$", line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        text = m.group(2).strip()
        if cur is None or not (cur[0] <= addr < cur[0] + cur[1]):
            i = bisect.bisect_right(starts, addr) - 1
            if i < 0:
                continue
            a, s, name = syms[i]
            if not (a <= addr < a + s):
                cur = None
                continue
            cur = (a, s, name)
        c = raw[cur[2]]
        c["insns"] += 1
        if VEC_RE.search(text):
            c["vec"] += 1
        jm = JMP_RE.match(text)
        if jm:
            tgt = int(jm.group(2), 16)
            if cur[0] <= tgt <= addr:
                c["backedges"] += 1

    code = {}
    for name, c in raw.items():
        d = code.setdefault(dem_sym[name],
                            {"insns": 0, "vec": 0, "backedges": 0})
        for k in d:
            d[k] += c[k]
    return code


# ---------------------------------------------------------------------------
# crate attribution
# ---------------------------------------------------------------------------

def demangle(names, tool="llvm-cxxfilt"):
    out = subprocess.run([tool], input="\n".join(names), capture_output=True,
                         text=True, check=True).stdout.splitlines()
    return dict(zip(names, out))


CRATE_RE = re.compile(r"^[<(]*([A-Za-z_][A-Za-z0-9_]*)")


def crate_of(demangled):
    """The leading path component of the demangled name.

    `<hifijson::SliceLexer as hifijson::write::Write>::write_until` -> hifijson
    `core::ptr::drop_glue::<jaq_json::Val>`                         -> core
    The second case is real work for jaq_json attributed to core; results.md
    says so where it matters.
    """
    m = CRATE_RE.match(demangled)
    return m.group(1) if m else "?"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("profdata")
    p.add_argument("--binary", default=None)
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--crates", action="store_true",
                   help="also print the share held by each crate")
    p.add_argument("--llvm-profdata", default=None)
    p.add_argument("--tsv", default=None, help="write the full table here")
    args = p.parse_args()

    tool = args.llvm_profdata or llvm_tool("llvm-profdata")
    funcs = load_profile(args.profdata, tool)
    total = sum(f["sum"] for f in funcs.values())
    code = load_code(args.binary) if args.binary else {}

    rows = sorted(funcs.values(), key=lambda f: -f["sum"])
    dem = demangle([f["name"] for f in rows])

    print(f"{len(funcs)} function records, total weight {total}")
    print("weight = sum of PGO block counts per function; "
          "entry = block count 0; trip = max / entry")
    print()
    hdr = (f"{'share':>7} {'sum_count':>13} {'entry':>12} {'trip':>8} "
           f"{'insns':>7} {'vec':>6} {'bedge':>6}  function")
    print(hdr)
    covered = 0.0
    for f in rows[:args.top]:
        share = 100.0 * f["sum"] / total if total else 0.0
        covered += share
        c = code.get(dem[f["name"]])
        trip = (f["max"] / f["entry"]) if f["entry"] else float("nan")
        insns = c["insns"] if c else -1
        vec = c["vec"] if c else -1
        be = c["backedges"] if c else -1
        tr = f"{trip:8.2f}" if f["entry"] else "       -"
        print(f"{share:6.2f}% {f['sum']:>13} {f['entry']:>12} {tr} "
              f"{insns:>7} {vec:>6} {be:>6}  {dem[f['name']]}")
    print(f"\nthese {args.top} functions hold {covered:.2f}% of the weight")

    if code:
        noloop = sum(f["sum"] for f in rows
                     if code.get(dem[f["name"]])
                     and code[dem[f["name"]]]["backedges"] == 0)
        nosym = sum(f["sum"] for f in rows if dem[f["name"]] not in code)
        novec = sum(f["sum"] for f in rows
                    if code.get(dem[f["name"]])
                    and code[dem[f["name"]]]["vec"] == 0)
        print(f"\nweight in symbols with NO machine-code backedge (no loop at "
              f"all, so no loop hint can reach them): {100.0*noloop/total:.2f}%")
        print(f"weight in symbols with no vector-register instruction: "
              f"{100.0*novec/total:.2f}%")
        print(f"weight in profdata records with no symbol in this binary "
              f"(inlined away or renamed): {100.0*nosym/total:.2f}%")

    if args.crates:
        by = collections.Counter()
        for f in rows:
            by[crate_of(dem[f["name"]])] += f["sum"]
        print("\nshare by leading crate of the demangled name:")
        for k, v in by.most_common(20):
            print(f"  {100.0*v/total:6.2f}%  {k}")

    if args.tsv:
        with open(args.tsv, "w") as fh:
            fh.write("share\tsum_count\tentry\tmax\ttrip\tinsns\tvec\tbackedges\t"
                     "crate\tfunction\n")
            for f in rows:
                c = code.get(dem[f["name"]], {})
                trip = (f["max"] / f["entry"]) if f["entry"] else 0.0
                fh.write("%.6f\t%d\t%d\t%d\t%.3f\t%d\t%d\t%d\t%s\t%s\n" % (
                    100.0 * f["sum"] / total if total else 0.0,
                    f["sum"], f["entry"], f["max"], trip,
                    c.get("insns", -1), c.get("vec", -1), c.get("backedges", -1),
                    crate_of(dem[f["name"]]), dem[f["name"]]))
        print(f"\nfull table: {args.tsv}")


if __name__ == "__main__":
    main()
