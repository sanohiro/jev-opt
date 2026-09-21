#!/usr/bin/env python3
"""How well does one profile cover another profile's hot functions?

Experiment 1 needs a cheap, build-free answer to "did this training set even
execute the code that matters". The reference is the top-N functions of a
reference profile (by max block count, the same ranking
scripts/profdata_hotness.py prints); for every other profile this reports

  zero      how many of those N functions have a summed block count of 0
  share     what fraction of that profile's own total those N functions hold
  rel       that share divided by the reference profile's own share

`zero` is the blunt question SPEC.ja.md's day-0 checklist asks. On a target
whose every path runs some JSON lexing it can be 0 for every arm and still
hide a 100x difference in weight, so `share` is the discriminating number.

Usage:
  scripts/profdata_cover.py REF.profdata ARM=path.profdata [ARM=...] \
      [--top 20] [--binary unstripped-binary]
"""

import argparse
import re
import subprocess
import sys


def load(profdata, tool):
    out = subprocess.run([tool, "show", "--all-functions", "--counts",
                          profdata], capture_output=True, text=True,
                         check=True).stdout
    funcs = {}
    name = None
    for line in out.splitlines():
        m = re.match(r"^  (\S.*):$", line)
        if m:
            name = m.group(1)
            continue
        m = re.match(r"^    Block counts: \[(.*)\]$", line)
        if m and name:
            c = [int(x) for x in m.group(1).split(", ") if x.strip()]
            funcs[name] = (max(c) if c else 0, sum(c))
            name = None
    return funcs


def default_tool():
    sysroot = subprocess.run(["rustc", "--print", "sysroot"],
                             capture_output=True, text=True,
                             check=True).stdout.strip()
    triple = re.search(r"^host: (.*)$",
                       subprocess.run(["rustc", "-vV"], capture_output=True,
                                      text=True, check=True).stdout,
                       re.M).group(1)
    return f"{sysroot}/lib/rustlib/{triple}/bin/llvm-profdata"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ref")
    p.add_argument("arms", nargs="+", help="NAME=path.profdata")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--llvm-profdata", default=None)
    p.add_argument("--crate", action="store_true",
                   help="also break the reference set down by crate")
    args = p.parse_args()

    tool = args.llvm_profdata or default_tool()
    ref = load(args.ref, tool)
    hot = sorted(ref, key=lambda n: -ref[n][0])[:args.top]
    ref_total = sum(v[1] for v in ref.values())
    ref_share = sum(ref[n][1] for n in hot) / ref_total

    print(f"reference profile: {args.ref}")
    print(f"its top {args.top} functions by max block count hold "
          f"{100 * ref_share:.2f}% of its own {ref_total} block counts\n")
    for i, n in enumerate(hot, 1):
        print(f"  {i:2d}. max={ref[n][0]:>14} sum={ref[n][1]:>14} "
              f"({100 * ref[n][1] / ref_total:5.2f}%)  {n.split(';')[-1][:78]}")

    print(f"\n{'arm':12s} {'total count':>16s} {'zero of ' + str(args.top):>10s}"
          f" {'share':>8s} {'rel to ref':>11s}")
    for spec in args.arms:
        name, _, path = spec.partition("=")
        f = load(path, tool)
        total = sum(v[1] for v in f.values())
        got = sum(f.get(n, (0, 0))[1] for n in hot)
        zero = sum(1 for n in hot if f.get(n, (0, 0))[1] == 0)
        share = got / total if total else 0.0
        print(f"{name:12s} {total:>16d} {zero:>10d} {100 * share:7.2f}% "
              f"{share / ref_share:10.3f}x")

    if args.crate:
        print("\nper-function share, every arm (percent of that arm's own "
              "total):")
        loaded = [(s.partition("=")[0], load(s.partition("=")[2], tool))
                  for s in args.arms]
        tots = [(n, sum(v[1] for v in f.values())) for n, f in loaded]
        hdr = "".join(f"{n:>10s}" for n, _ in loaded)
        print(f"{'function':60s}{hdr}")
        for n in hot:
            row = "".join(
                f"{100 * f.get(n, (0, 0))[1] / t:9.3f}%"
                for (_, f), (_, t) in zip(loaded, tots))
            print(f"{n.split(';')[-1][:58]:60s}{row}")


if __name__ == "__main__":
    main()
