#!/usr/bin/env python3
"""Resolve scripts/ipsample.c's sampled instruction pointers to symbols.

The question this exists for (results.md "Stage 0 (oxipng)"): what share of a
target's CPU time runs in code rustc compiled, and what share runs in code a C
compiler compiled and linked in as a static archive? `-Cprofile-generate`
instruments Rust only, so `scripts/profdata_hotness.py` cannot see the second
kind at all and silently reports 100% Rust.

Classification is by symbol name, which is unambiguous here because the builds
use `-Csymbol-mangling-version=v0`: every Rust symbol starts with `_R`, and
nothing else does.

Usage:
  cc -O2 -fPIC -shared -o /tmp/ipsample.so scripts/ipsample.c
  IPSAMPLE_OUT=/tmp/s.txt LD_PRELOAD=/tmp/ipsample.so ./oxipng -o 2 ...
  scripts/ipsample.py --binary ./oxipng /tmp/s.txt [more.txt ...]
"""

import argparse
import bisect
import collections
import re
import subprocess
import sys


def symbols(binary):
    out = subprocess.run(["nm", "-S", "--defined-only", binary],
                         capture_output=True, text=True, check=True).stdout
    syms = []
    for line in out.splitlines():
        p = line.split()
        if len(p) < 4 or p[2].lower() != "t":
            continue
        try:
            addr, size = int(p[0], 16), int(p[1], 16)
        except ValueError:
            continue
        syms.append((addr, size, " ".join(p[3:])))
    syms.sort()
    return syms


def classify(name):
    """Rust / C / unknown, from the v0 mangling prefix."""
    if name.startswith("_R"):
        return "rust"
    if name.startswith("_ZN") or name.startswith("_Z"):
        return "cxx"
    return "c"


def demangle(names):
    if not names:
        return {}
    # rustfilt is not installed on this machine; llvm-cxxfilt from the pinned
    # toolchain understands the v0 mangling, and plain `nm -C` does not.
    for tool in (["rustfilt"], ["llvm-cxxfilt"], ["c++filt"]):
        try:
            out = subprocess.run(tool, input="\n".join(names),
                                 capture_output=True, text=True)
        except FileNotFoundError:
            continue
        if out.returncode == 0:
            got = out.stdout.splitlines()
            if len(got) == len(names):
                return dict(zip(names, got))
    return {n: n for n in names}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--binary", required=True,
                   help="the unstripped binary the samples came from")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--label", default="",
                   help="printed with the summary line")
    p.add_argument("samples", nargs="+")
    a = p.parse_args()

    syms = symbols(a.binary)
    starts = [s[0] for s in syms]

    per_sym = collections.Counter()
    per_class = collections.Counter()
    total = 0
    outside = 0
    for path in a.samples:
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("!"):
                outside += 1
                total += 1
                per_class["outside-exe"] += 1
                continue
            ip = int(line, 16)
            total += 1
            i = bisect.bisect_right(starts, ip) - 1
            if i < 0:
                per_class["unmapped"] += 1
                per_sym["<unmapped>"] += 1
                continue
            addr, size, name = syms[i]
            if size and ip >= addr + size:
                per_class["between-symbols"] += 1
                per_sym["<between-symbols>"] += 1
                continue
            per_sym[name] += 1
            per_class[classify(name)] += 1

    if total == 0:
        sys.exit("no samples")

    print("samples: %d%s" % (total, ("  (%s)" % a.label) if a.label else ""))
    for k in ("rust", "c", "cxx", "outside-exe", "between-symbols", "unmapped"):
        if per_class[k]:
            print("  %-16s %7d  %6.2f%%" % (k, per_class[k],
                                            100.0 * per_class[k] / total))
    print()
    names = [n for n, _ in per_sym.most_common(a.top)]
    dem = demangle(names)
    for name, c in per_sym.most_common(a.top):
        print("  %6.2f%%  %7d  [%-4s] %s"
              % (100.0 * c / total, c, classify(name), dem.get(name, name)))


if __name__ == "__main__":
    sys.exit(main())
