#!/usr/bin/env python3
"""Compare the machine code of named functions across two or more binaries.

The remark text says what the optimizer *decided*; this says whether the
bytes moved. Used in results.md section 31 to show that a knob which changes
nothing at a loop's DebugLoc also changes nothing in the function that
contains it.

Matching is on the demangled symbol name containing --match (repeatable).

Usage:
  scripts/func_code_diff.py --match try_get --match ZopfliHash6update \
      artifacts/zopfli-headroom/bin/baseline artifacts/zopfli-headroom/bin/g1-vw32
"""

import argparse
import hashlib
import re
import subprocess
import sys


def functions(binary, matches):
    out = subprocess.run(["nm", "-S", "--defined-only", binary],
                         capture_output=True, text=True, check=True).stdout
    found = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) < 4 or p[2].lower() != "t":
            continue
        addr, size, name = int(p[0], 16), int(p[1], 16), " ".join(p[3:])
        if size == 0 or not any(m in name for m in matches):
            continue
        found[name] = (addr, size)
    return found


ADDR_RE = re.compile(r"\b(0x)?[0-9a-f]{4,}\b")


def body(binary, addr, size):
    """Normalised instruction text: the address column, the branch targets
    and any absolute displacement are replaced by `A`, so a function that
    was only relocated does not look changed. What is left is the mnemonic
    and register sequence, which is what a knob has to move to matter."""
    out = subprocess.run(
        ["objdump", "-d", "--no-show-raw-insn",
         f"--start-address={addr}", f"--stop-address={addr + size}", binary],
        capture_output=True, text=True, check=True).stdout
    insns = []
    for line in out.splitlines():
        m = re.match(r"^\s+[0-9a-f]+:\t(.*)$", line)
        if m:
            t = re.sub(r"\s+", " ", m.group(1).split("#")[0].strip())
            insns.append(ADDR_RE.sub("A", t))
    return insns


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--match", action="append", required=True)
    p.add_argument("binaries", nargs="+")
    args = p.parse_args()

    base = args.binaries[0]
    names = sorted(functions(base, args.match))
    if not names:
        sys.exit("no symbol matched")
    for name in names:
        print(f"## {name}")
        for b in args.binaries:
            f = functions(b, args.match).get(name)
            if f is None:
                print(f"  {b:<60s} (absent)")
                continue
            insns = body(b, *f)
            h = hashlib.sha256("\n".join(insns).encode()).hexdigest()[:16]
            mn = {}
            for i in insns:
                mn[i.split()[0] if i else "?"] = mn.get(i.split()[0] if i else "?", 0) + 1
            vec = sum(1 for i in insns if re.search(r"\b[xyz]mm\d+\b", i))
            print(f"  {b:<60s} {len(insns):5d} insns, {vec:4d} vector, code {h}")
        print()


if __name__ == "__main__":
    main()
