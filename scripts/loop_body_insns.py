#!/usr/bin/env python3
"""Count the machine instructions that belong to one source line, per binary.

SPEC.ja.md 7's attribution run backwards: instead of asking "which function
does this remark belong to", ask "how many instructions in this binary come
from `src/cache.rs:108`, and what are they". Comparing that count across two
builds is direct evidence of whether a knob unrolled or vectorised that loop,
without trusting the remark text (results.md section 27: the remark diff does
not report scalar unrolling at all).

Every instruction of every symbol matching --sym-filter is disassembled and
run through `addr2line -i -f -p -C`; an instruction counts for a location if
that location is its INNERMOST frame.

Usage:
  scripts/loop_body_insns.py --loc src/cache.rs:108 --loc src/hash.rs:150 \
      --sym-filter zopfli artifacts/zopfli-headroom/bin/{baseline,g2-unroll-max2}
"""

import argparse
import collections
import os
import re
import subprocess
import sys
import tempfile

VEC_RE = re.compile(r"\b[xyz]mm\d+\b")
FRAME_RE = re.compile(r"^(?P<fn>.*?) at (?P<file>.*?):(?P<line>\d+|\?)")


def walk(binary, sym_filter):
    nm = subprocess.run(["nm", "-S", "--defined-only", binary],
                        capture_output=True, text=True, check=True).stdout
    syms = []
    for line in nm.splitlines():
        p = line.split()
        if len(p) < 4 or p[2].lower() != "t":
            continue
        a, s, name = int(p[0], 16), int(p[1], 16), " ".join(p[3:])
        if s and (not sym_filter or sym_filter in name or name == "main"):
            syms.append((a, s, name))
    insns = []
    for a, s, name in sorted(syms):
        out = subprocess.run(
            ["objdump", "-d", "--no-show-raw-insn",
             f"--start-address={a}", f"--stop-address={a + s}", binary],
            capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            m = re.match(r"^\s+([0-9a-f]+):\t(.*)$", line)
            if m:
                insns.append((int(m.group(1), 16), m.group(2).strip()))
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for a, _ in insns:
            f.write("0x%x\n" % a)
        listfile = f.name
    try:
        out = subprocess.run(["addr2line", "-i", "-f", "-p", "-C", "-e", binary,
                              "@" + listfile],
                             capture_output=True, text=True, check=True).stdout
    finally:
        os.unlink(listfile)
    chains, cur = [], None
    for line in out.splitlines():
        if line.startswith(" (inlined by)"):
            cur.append(line[len(" (inlined by)"):].strip())
        else:
            cur = [line.strip()]
            chains.append(cur)
    if len(chains) != len(insns):
        sys.exit(f"frame/instruction mismatch: {len(chains)} vs {len(insns)}")
    return insns, chains


def frame(text):
    m = FRAME_RE.match(text)
    if not m:
        return (text, "?", 0)
    ln = m.group("line")
    return (m.group("fn"), m.group("file"), int(ln) if ln.isdigit() else 0)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--loc", action="append", required=True, metavar="FILE:LINE")
    p.add_argument("--sym-filter", default="zopfli")
    p.add_argument("binaries", nargs="+")
    args = p.parse_args()

    wanted = []
    for loc in args.loc:
        f, _, l = loc.rpartition(":")
        wanted.append((f, int(l)))

    for b in args.binaries:
        insns, chains = walk(b, args.sym_filter)
        print(f"== {b}")
        for wf, wl in wanted:
            rows = []
            owners = collections.Counter()
            for (addr, text), chain in zip(insns, chains):
                fn, file, line = frame(chain[0])
                if line == wl and (file == wf or file.endswith("/" + wf)):
                    rows.append(text)
                    owners[frame(chain[-1])[0]] += 1
            mn = collections.Counter(t.split()[0] if t else "?" for t in rows)
            nvec = sum(1 for t in rows if VEC_RE.search(t))
            print(f"   {wf}:{wl}: {len(rows)} instructions, {nvec} with vector regs")
            if rows:
                print(f"      mnemonics: " +
                      ", ".join(f"{k}x{v}" for k, v in mn.most_common(10)))
                print(f"      owners: " +
                      ", ".join(f"{k} x{v}" for k, v in owners.most_common(4)))
        print()


if __name__ == "__main__":
    main()
