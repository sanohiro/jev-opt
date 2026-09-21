#!/usr/bin/env python3
"""Rank functions by PGO block counts, straight out of merged.profdata.

Stage 2's hotness comes from the plugin, which reads `!prof` in the IR and
multiplies a loop header's profile count by the loop body's instruction count
(SPEC.ja.md 8.2). The plugin does not exist at day 0, but the *same profile*
is already on disk, so a coarse ranking is free:

    max_count   the largest block count in the function --- the innermost hot
                loop's trip count, in practice
    sum_count   the sum of its block counts

Neither is the spec's `score`: there is no instruction count here, so a long
loop body and a short one with the same trip count rank the same. It is
enough to answer day-0 questions --- which functions the profile says are hot,
and whether a dependency flagged by the SPEC.ja.md 6.1-2 disqualification
filter is anywhere near the hot path.

Usage:
  scripts/profdata_hotness.py pgo/zopfli/merged.profdata [--top 25]
  scripts/profdata_hotness.py pgo/zopfli/merged.profdata --grep simd_adler32
"""

import argparse
import re
import subprocess
import sys


def load(profdata, llvm_profdata):
    out = subprocess.run([llvm_profdata, "show", "--all-functions", "--counts",
                          profdata],
                         capture_output=True, text=True, check=True).stdout
    funcs = []
    name = None
    for line in out.splitlines():
        m = re.match(r"^  (\S.*):$", line)
        if m:
            name = m.group(1)
            # "<cgu-name>;<symbol>" for internal-linkage functions.
            continue
        m = re.match(r"^    Block counts: \[(.*)\]$", line)
        if m and name:
            counts = [int(x) for x in m.group(1).split(", ") if x.strip()]
            funcs.append({"name": name,
                          "short": name.split(";")[-1],
                          "counts": counts,
                          "max": max(counts) if counts else 0,
                          "sum": sum(counts)})
            name = None
    return funcs


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("profdata")
    p.add_argument("--llvm-profdata", default=None)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--grep", default=None,
                   help="only print functions whose name contains this")
    args = p.parse_args()

    tool = args.llvm_profdata
    if tool is None:
        sysroot = subprocess.run(["rustc", "--print", "sysroot"],
                                 capture_output=True, text=True, check=True).stdout.strip()
        triple = subprocess.run(["rustc", "-vV"], capture_output=True, text=True,
                                check=True).stdout
        triple = re.search(r"^host: (.*)$", triple, re.M).group(1)
        tool = f"{sysroot}/lib/rustlib/{triple}/bin/llvm-profdata"

    funcs = load(args.profdata, tool)
    total = sum(f["sum"] for f in funcs)
    print(f"{len(funcs)} function records, total block count {total}")

    if args.grep:
        sel = [f for f in funcs if args.grep in f["name"]]
        got = sum(f["sum"] for f in sel)
        print(f"functions matching {args.grep!r}: {len(sel)}, "
              f"summed block count {got} "
              f"({100.0 * got / total if total else 0:.6f}% of the total)")
        for f in sorted(sel, key=lambda f: -f["sum"]):
            print(f"  sum={f['sum']:>14}  max={f['max']:>14}  {f['short']}")
        return

    print(f"\ntop {args.top} by max block count:")
    for f in sorted(funcs, key=lambda f: -f["max"])[:args.top]:
        print(f"  max={f['max']:>14}  sum={f['sum']:>14}  "
              f"({100.0 * f['sum'] / total if total else 0:5.2f}%)  {f['short']}")


if __name__ == "__main__":
    main()
