#!/usr/bin/env python3
"""Whole-binary normalised code comparison, weighted by the PGO profile.

`scripts/func_code_diff.py` answers "did these named functions change";
this answers "which functions changed at all, and how much of the profile do
they hold" for every symbol in the binary at once. It is results.md section
31.4's per-symbol comparison, generalised and made the primary criterion for a
target whose raw `.text` hash is useless.

Why it exists: on jaq the `.text` hash changes between two builds of the
*same* configuration (results.md "Stage 0 (jaq)" section 53) --- the default
`mimalloc` feature compiles C that bakes `__TIME__` into `.rodata`, the
string constants after it shift, and the instructions that reference them
change their immediates. Section sizes, symbol order and symbol sizes all
stay identical, and only about 260 of 2.6 MB of `.text` move, but the hash is
gone. Normalising addresses away (the same rule as func_code_diff.py: any hex
literal of four or more digits becomes `A`) restores a usable criterion.

Usage:
  scripts/norm_code_diff.py BASE OTHER [OTHER...] [--profdata pgo/jaq/merged.profdata]
"""

import argparse
import bisect
import collections
import hashlib
import re
import subprocess
import sys

ADDR_RE = re.compile(r"\b(0x)?[0-9a-f]{4,}\b")


def norm_bodies(binary):
    """demangled symbol -> sha256 of its normalised instruction sequence."""
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
    dem = subprocess.run(["llvm-cxxfilt"],
                         input="\n".join(n for _, _, n in syms),
                         capture_output=True, text=True, check=True).stdout.splitlines()
    starts = [a for a, _, _ in syms]
    acc = {name: hashlib.sha256() for name in dem}
    sizes = collections.Counter()

    dis = subprocess.run(["objdump", "-d", "--no-show-raw-insn", binary],
                         capture_output=True, text=True, check=True).stdout
    cur = None
    for line in dis.splitlines():
        m = re.match(r"^\s+([0-9a-f]+):\t(.*)$", line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        if cur is None or not (cur[0] <= addr < cur[0] + cur[1]):
            i = bisect.bisect_right(starts, addr) - 1
            if i < 0:
                cur = None
                continue
            a, s, _ = syms[i]
            if not (a <= addr < a + s):
                cur = None
                continue
            cur = (a, s, dem[i])
        t = re.sub(r"\s+", " ", m.group(2).split("#")[0].strip())
        acc[cur[2]].update(ADDR_RE.sub("A", t).encode())
        acc[cur[2]].update(b"\n")
        sizes[cur[2]] += 1
    return {k: v.hexdigest() for k, v in acc.items()}, sizes


def load_shares(profdata):
    tool = None
    sysroot = subprocess.run(["rustc", "--print", "sysroot"],
                             capture_output=True, text=True, check=True).stdout.strip()
    triple = re.search(r"^host: (.*)$",
                       subprocess.run(["rustc", "-vV"], capture_output=True,
                                      text=True, check=True).stdout, re.M).group(1)
    tool = f"{sysroot}/lib/rustlib/{triple}/bin/llvm-profdata"
    out = subprocess.run([tool, "show", "--all-functions", "--counts", profdata],
                         capture_output=True, text=True, check=True).stdout
    raw = collections.Counter()
    name = None
    for line in out.splitlines():
        m = re.match(r"^  (\S.*):$", line)
        if m:
            name = m.group(1)
            continue
        m = re.match(r"^    Block counts: \[(.*)\]$", line)
        if m and name:
            counts = [int(x) for x in m.group(1).split(", ") if x.strip()]
            raw[name.split(";")[-1]] += sum(counts)
            name = None
    dem = subprocess.run(["llvm-cxxfilt"], input="\n".join(raw),
                         capture_output=True, text=True, check=True).stdout.splitlines()
    share = collections.Counter()
    for mangled, d in zip(list(raw), dem):
        share[d] += raw[mangled]
    total = sum(share.values())
    return {k: 100.0 * v / total for k, v in share.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("base")
    p.add_argument("others", nargs="+")
    p.add_argument("--profdata", default=None)
    p.add_argument("--top", type=int, default=8)
    args = p.parse_args()

    share = load_shares(args.profdata) if args.profdata else {}
    base, base_sizes = norm_bodies(args.base)
    whole = hashlib.sha256()
    for k in sorted(base):
        whole.update((k + base[k]).encode())
    print(f"{args.base}: {len(base)} symbols, normalised whole-code hash "
          f"{whole.hexdigest()[:16]}")

    for other in args.others:
        cur, cur_sizes = norm_bodies(other)
        w = hashlib.sha256()
        for k in sorted(cur):
            w.update((k + cur[k]).encode())
        changed = [k for k in base if k in cur and base[k] != cur[k]]
        gone = [k for k in base if k not in cur]
        new = [k for k in cur if k not in base]
        moved = sum(share.get(k, 0.0) for k in changed)
        print(f"\n{other}: hash {w.hexdigest()[:16]}  "
              f"{'IDENTICAL' if w.hexdigest() == whole.hexdigest() else 'DIFFERS'}")
        print(f"  symbols: {len(cur)} (base {len(base)}), changed {len(changed)}, "
              f"only-in-base {len(gone)}, only-here {len(new)}")
        if share:
            print(f"  profile share held by the changed symbols: {moved:.2f}%")
            for k in sorted(changed, key=lambda k: -share.get(k, 0.0))[:args.top]:
                print(f"     {share.get(k, 0.0):6.2f}%  "
                      f"{base_sizes[k]}->{cur_sizes[k]} insns  {k[:100]}")


if __name__ == "__main__":
    main()
