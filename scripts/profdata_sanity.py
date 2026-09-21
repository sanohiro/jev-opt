#!/usr/bin/env python3
"""Is this profile a count, or is it a wild write? One llvm-profdata show.

results.md section 63: three ordinary items in jaq's repository --- two of
them plain `cargo test` unit tests --- make the `-Cprofile-generate` binary
store a *heap pointer* (mimalloc's 2 TiB arena region) into one of its own
`__llvm_prf_cnts` slots while formatting a big integer. One block then holds
99.999% of the merged profile, every ProfileSummary percentile lands on it,
the whole program is cold relative to the hot/cold cutoff, and the binary
built from that profile is 9.9% *slower* than no PGO at all. None of this is
visible in the shipped binary, and `-Cprofile-use` emits no warning.

The check is arithmetic: a block cannot have been executed more often than
the training run had cycles to execute it. With `--max-ipc` instructions
retired per second as the ceiling,

    plausible = wall_seconds * max_ipc

and any block above that is not a count. The default 5e9/s is roughly one
instruction per cycle on a 5 GHz core, i.e. generous by a factor of several
for a single-threaded program: results.md section 63's real counts top out
at 1.8e8 for a 5.6 s run, and the corrupted one is 3.5e13, so there is no
borderline case to tune against.

decisions.ja.md entry 47 makes this a mandatory step of `jev-opt build`:
train, check, then use. This is that step, as a script.

Usage:
  scripts/profdata_sanity.py --wall 13.1 pgo/jaq/arms/T_all/merged.profdata
  scripts/profdata_sanity.py --wall-from-manifest pgo/jaq/arms/*/merged.profdata
  scripts/profdata_sanity.py --wall 13.1 --max-ipc 1e10 ...

Exit status is 1 if any profile fails, so it can gate a build.
"""

import argparse
import json
import os
import re
import subprocess
import sys


def llvm_profdata_path():
    sysroot = subprocess.run(["rustc", "--print", "sysroot"], check=True,
                             capture_output=True, text=True).stdout.strip()
    triple = re.search(r"^host: (.*)$",
                       subprocess.run(["rustc", "-vV"], check=True,
                                      capture_output=True, text=True).stdout,
                       re.M).group(1)
    return f"{sysroot}/lib/rustlib/{triple}/bin/llvm-profdata"


def summary(tool, path):
    out = subprocess.run([tool, "show", path], capture_output=True,
                         text=True, check=True).stdout
    def get(k):
        m = re.search(rf"^{re.escape(k)}: (\d+)$", out, re.M)
        return int(m.group(1)) if m else 0
    return {"functions": get("Total functions"),
            "max_function": get("Maximum function count"),
            "max_block": get("Maximum internal block count"),
            "total": get("Total count")}


def culprit(tool, path, threshold):
    """The function (and counter index) holding the impossible value."""
    out = subprocess.run([tool, "show", "--all-functions", "--counts", path],
                         capture_output=True, text=True, check=True).stdout
    name, worst = None, None
    for line in out.splitlines():
        m = re.match(r"^  (\S.*):$", line)
        if m:
            name = m.group(1)
            continue
        m = re.match(r"^    Block counts: \[(.*)\]$", line)
        if m and name:
            cs = [int(x) for x in m.group(1).split(", ") if x.strip()]
            for i, c in enumerate(cs):
                if c >= threshold and (worst is None or c > worst[2]):
                    worst = (name, i, c, len(cs))
            name = None
    if not worst:
        return None
    dem = subprocess.run(["llvm-cxxfilt"], input=worst[0].split(";")[-1],
                         capture_output=True, text=True).stdout.strip()
    return {"function": dem, "counter": worst[1], "of": worst[3],
            "count": worst[2], "hex": hex(worst[2])}


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("profdata", nargs="+")
    p.add_argument("--wall", type=float, default=None,
                   help="training wall time in seconds, for every profile")
    p.add_argument("--wall-from-manifest", action="store_true",
                   help="read run_wall_s out of <profdata>.manifest.json "
                        "(written by scripts/jaq_arm_profile.py)")
    p.add_argument("--max-ipc", type=float, default=5e9,
                   help="ceiling on retired instructions per second "
                        "(default 5e9)")
    p.add_argument("--json", default=None)
    args = p.parse_args()

    tool = llvm_profdata_path()
    rows, bad = [], 0
    print(f"{'profile':34s} {'wall s':>7s} {'limit':>11s} "
          f"{'max block':>16s} {'total':>16s}  verdict")
    for path in args.profdata:
        wall = args.wall
        man = path + ".manifest.json"
        if args.wall_from_manifest and os.path.exists(man):
            wall = json.load(open(man)).get("run_wall_s") or wall
        if wall is None:
            sys.exit("need --wall or --wall-from-manifest")
        limit = wall * args.max_ipc
        s = summary(tool, path)
        ok = s["max_block"] <= limit
        row = dict(s, path=path, wall_s=wall, limit=limit, ok=ok)
        if not ok:
            bad += 1
            row["culprit"] = culprit(tool, path, limit)
        rows.append(row)
        name = os.path.relpath(path).replace("pgo/jaq/arms/", "")
        print(f"{name[:34]:34s} {wall:7.2f} {limit:11.3g} "
              f"{s['max_block']:>16d} {s['total']:>16d}  "
              f"{'ok' if ok else 'POISONED'}")
        if not ok and row["culprit"]:
            c = row["culprit"]
            print(f"{'':34s} culprit: counter {c['counter']} of {c['of']} in "
                  f"{c['function'][:80]}")
            print(f"{'':34s}          {c['count']} = {c['hex']} "
                  f"({s['max_block'] / limit:.3g}x the limit)")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"max_ipc": args.max_ipc, "profiles": rows}, fh,
                      indent=1)
    print(f"\n{len(rows)} profiles, {bad} poisoned")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
