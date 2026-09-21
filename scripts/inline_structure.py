#!/usr/bin/env python3
"""What is inside a hot post-LTO symbol, split by the source function the
machine code came from, with a machine-code backedge count per source
function.

scripts/interp_share.py counts instructions and backedges per *symbol*. Under
fat LTO a jaq symbol is an inline host holding a dozen source functions
(results.md "Stage 0 (jaq)" section 54 says so and calls function-level
classification meaningless there), and a compile-time mark names a *source
function*, not a symbol. This script closes that gap: it disassembles the
named symbols, asks llvm-symbolizer which source function each instruction
belongs to (innermost inlined frame), and counts, per source function,

  own        instructions whose innermost inlined frame is that function
  ownbe      backedges between two instructions that both have it as their
             innermost frame -- a loop written in that function's own body
  reach      instructions with that function anywhere in their inlined frame
             stack, i.e. its body plus everything inlined into it
  reachbe    backedges between two instructions that both have it in their
             stack -- a machine-code loop inside it, wherever the loop body
             came from. This is the number that says whether a loop hint
             placed on this function has anything to act on: an iterator
             chain like `write_until -> position -> try_fold` puts the
             backedge two frames below the function that reads as hot.
  hosts      the post-LTO symbols the code ended up in

Usage:
  scripts/inline_structure.py --binary target-jaq-pgo-use/.../jaq \\
      --names-from artifacts/jaq-marks/perf-self.tsv --top 20 \\
      --tsv artifacts/jaq-marks/inline-structure.tsv
"""

import argparse
import bisect
import collections
import csv
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from interp_share import crate_of, demangle  # noqa: E402

JMP_RE = re.compile(r"^(j[a-z]+|loop[a-z]*)\s+([0-9a-f]+)\b")


def text_symbols(binary):
    nm = subprocess.run(["nm", "-S", "--defined-only", binary],
                        capture_output=True, text=True, check=True).stdout
    raw = []
    for line in nm.splitlines():
        p = line.split()
        if len(p) < 4 or p[2].lower() != "t":
            continue
        try:
            a, s = int(p[0], 16), int(p[1], 16)
        except ValueError:
            continue
        if s:
            raw.append((a, s, " ".join(p[3:])))
    dem = demangle([n for _, _, n in raw])
    return [(a, s, dem[n]) for a, s, n in raw]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--names-from", required=True,
                    help="TSV with a `function` column, hottest first")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--print-top", type=int, default=40)
    ap.add_argument("--tsv", default=None)
    a = ap.parse_args()

    with open(a.names_from) as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    wanted, share = [], {}
    for r in rows:
        if len(wanted) >= a.top:
            break
        fn = r["function"]
        if r.get("lang") == "c":          # mimalloc has no Rust source function
            continue
        wanted.append(fn)
        share[fn] = float(r["share"])

    syms = text_symbols(a.binary)
    ranges = [(x, y, n) for x, y, n in syms if n in set(wanted)]
    ranges.sort()
    print("hosts: %d symbols / %d names, %d bytes"
          % (len(ranges), len(wanted), sum(s for _, s, _ in ranges)))

    # disassemble each host once
    insn = {}          # addr -> (text, host name)
    for lo, size, name in ranges:
        dis = subprocess.run(
            ["objdump", "-d", "--no-show-raw-insn",
             "--start-address=0x%x" % lo, "--stop-address=0x%x" % (lo + size),
             a.binary], capture_output=True, text=True, check=True).stdout
        for line in dis.splitlines():
            m = re.match(r"^\s+([0-9a-f]+):\t(.*)$", line)
            if m:
                addr = int(m.group(1), 16)
                if lo <= addr < lo + size:
                    insn[addr] = (m.group(2).strip(), name)
    addrs = sorted(insn)
    print("instructions: %d" % len(addrs))

    out = subprocess.run(["llvm-symbolizer", "--inlining", "--functions=linkage",
                          "--demangle", "--obj", a.binary],
                         input="\n".join("0x%x" % x for x in addrs),
                         capture_output=True, text=True, check=True).stdout
    owner, stack = {}, {}
    cur, i = [], 0

    def record(addr, frames):
        fns = [f for j, f in enumerate(frames) if j % 2 == 0 and f != "??"]
        if fns:
            owner[addr] = fns[0]
            stack[addr] = frozenset(fns)

    for line in out.splitlines():
        if line.strip() == "":
            if i < len(addrs) and cur:
                record(addrs[i], cur)
            cur, i = [], i + 1
            continue
        cur.append(line)
    if cur and i < len(addrs):
        record(addrs[i], cur)

    stat = collections.defaultdict(
        lambda: {"own": 0, "ownbe": 0, "reach": 0, "reachbe": 0,
                 "hosts": collections.Counter()})
    for addr in addrs:
        text, host = insn[addr]
        fn = owner.get(addr, "<no debug info>")
        st = stack.get(addr, frozenset([fn]))
        stat[fn]["own"] += 1
        for f in st:
            stat[f]["reach"] += 1
            stat[f]["hosts"][host] += 1
        m = JMP_RE.match(text)
        if m:
            tgt = int(m.group(2), 16)
            if tgt <= addr:
                if owner.get(tgt) == fn:
                    stat[fn]["ownbe"] += 1
                for f in st & stack.get(tgt, frozenset()):
                    stat[f]["reachbe"] += 1

    order = sorted(stat.items(), key=lambda kv: -kv[1]["reach"])
    print("\n   own ownbe  reach reachbe  crate        function  (top host)")
    for fn, s in order[:a.print_top]:
        host = (s["hosts"].most_common(1)[0][0] if s["hosts"] else "-")
        print("  %5d %5d  %5d %5d    %-12s %s\n%s(in %s)"
              % (s["own"], s["ownbe"], s["reach"], s["reachbe"],
                 crate_of(fn)[:12], fn[:145], " " * 37, host[:110]))

    if a.tsv:
        os.makedirs(os.path.dirname(a.tsv) or ".", exist_ok=True)
        with open(a.tsv, "w") as f:
            f.write("own\townbe\treach\treachbe\tnhosts\tcrate\tfunction"
                    "\ttop_host\n")
            for fn, s in order:
                f.write("%d\t%d\t%d\t%d\t%d\t%s\t%s\t%s\n"
                        % (s["own"], s["ownbe"], s["reach"], s["reachbe"],
                           len(s["hosts"]), crate_of(fn), fn,
                           s["hosts"].most_common(1)[0][0] if s["hosts"]
                           else "-"))
        print("\nwrote %s (%d rows)" % (a.tsv, len(order)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
