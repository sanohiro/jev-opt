#!/usr/bin/env python3
"""Read the jev plugin's per-module reports.

The plugin writes one JSON per (module, stage, pid) because several rustc
processes run concurrently and, under fat LTO, one process optimises two
stages of the same module identifier (SPEC.ja.md 8.2). Merging them is the
CLI's job; this is the part of that job the day-3 tests need.

Subcommands:
  sites   <dir>                 human-readable table of the dumped loops
  key     <dir> <mark>          the site key of the hottest loop that is
                                *inside* that mark (match = loop_in_mark)
  leaf    <dir> <mark>          that loop's file:line, as remarks spell it
  allkeys <dir>                 a plan naming every dumped site, one
                                vectorize_width-free entry each, for the
                                key-resolution test
  apply   <dir>                 outcome counts from apply reports
  compare <dirA> <dirB>         which marks kept their site keys
"""
import glob
import json
import os
import sys


def load(d):
    out = []
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        with open(f) as fh:
            out.append((os.path.basename(f), json.load(fh)))
    return out


def cmd_sites(d):
    for name, rep in load(d):
        print(f"-- {name}")
        print(f"   stage={rep['stage']} loop_ep_ran={rep['loop_ep_ran']} "
              f"profile_summary={rep['profile_summary']} "
              f"unmatched_marks={rep['unmatched_marks']}")
        for fn in rep.get("functions", []):
            print("   FN  %-34s inst=%-5s entry=%-10s attrs=%r"
                  % (fn["demangled"], fn["inst_count"], fn["entry_count"],
                     fn["attributes"]))
        sites = rep.get("sites", [])
        if sites:
            print("   %-42s %-13s %-22s %-8s %-11s %-6s %-13s %s"
                  % ("key", "match", "mark", "depth", "trip", "insts",
                     "hotness", "leaf"))
        for s in sorted(sites, key=lambda x: -(x["hotness"] or 0)):
            leaf = "%s:%d" % (os.path.basename(s["leaf"]["file"]),
                              s["leaf"]["line"])
            trip = "-" if s["trip_count"] is None else "%.0f" % s["trip_count"]
            print("   %-42s %-13s %-22s %-8d %-11s %-6d %-13d %s%s"
                  % (s["key"], s["match"], s["mark"].replace("toyloops::", "tl::"),
                     s["depth"], trip, s["body_inst_count"], s["hotness"], leaf,
                     "  [fp-reduction]" if s["has_fp_reduction"] else ""))
        print()


def all_sites(d):
    for _, rep in load(d):
        for s in rep.get("sites", []):
            yield rep["stage"], s


def cmd_key(d, mark):
    best = None
    for stage, s in all_sites(d):
        if s["mark"] != mark or s["match"] != "loop_in_mark":
            continue
        if best is None or (s["hotness"] or 0) > (best["hotness"] or 0):
            best = s
    if best is None:
        sys.exit(f"no loop_in_mark site for {mark} in {d}")
    print(best["key"])


def cmd_leaf(d, mark):
    """basename:line of the hottest loop_in_mark site, as remarks spell it."""
    best = None
    for _, s in all_sites(d):
        if s["mark"] != mark or s["match"] != "loop_in_mark":
            continue
        if best is None or (s["hotness"] or 0) > (best["hotness"] or 0):
            best = s
    if best is None:
        sys.exit(f"no loop_in_mark site for {mark} in {d}")
    print("%s:%d" % (os.path.basename(best["leaf"]["file"]), best["leaf"]["line"]))


def cmd_allkeys(d):
    entries, seen = [], set()
    for stage, s in all_sites(d):
        if s["key"] in seen:
            continue
        seen.add(s["key"])
        # unroll_count=1 is the least invasive thing a plan can say that
        # still makes the plugin attach metadata, so every key has to resolve
        # for the report to come back clean.
        entries.append({"key": s["key"], "stage": stage, "unroll_count": 1})
    json.dump({"schema_version": 1, "plan_id": "allkeys",
               "fn_attrs": [], "loop_md": entries}, sys.stdout, indent=2)
    print()


def cmd_apply(d):
    """Merged outcome per entry.

    The plugin reports per module, and a plan entry naming a function that
    lives in one crate is legitimately `unmatched` in every other module. The
    verdict that matters is the merged one: an entry is unmatched only if no
    module resolved it. Same for loop keys.
    """
    merged = {}
    for _, rep in load(d):
        for r in rep.get("results", []):
            what = r.get("key") or r.get("fn")
            e = merged.setdefault(what, {"outcomes": [], "attached": "",
                                         "stages": set()})
            e["outcomes"].append(r["outcome"])
            e["stages"].add(rep["stage"])
            if r.get("attached"):
                e["attached"] = r["attached"]

    counts = {}
    for what, e in sorted(merged.items()):
        real = [o for o in e["outcomes"] if o != "unmatched"]
        verdict = real[0] if real else "unmatched"
        if len(set(real)) > 1:
            verdict = "+".join(sorted(set(real)))
        counts[verdict] = counts.get(verdict, 0) + 1
        print("   %-9s %-46s %-20s %s"
              % (",".join(sorted(e["stages"])), what, verdict, e["attached"]))
    print("   totals: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


def cmd_compare(a, b):
    def bymark(d):
        m = {}
        for _, s in all_sites(d):
            if s["match"] != "loop_in_mark":
                continue
            m.setdefault(s["mark"], set()).add(s["key"])
        return m
    ma, mb = bymark(a), bymark(b)
    for mark in sorted(set(ma) | set(mb)):
        ka, kb = ma.get(mark, set()), mb.get(mark, set())
        same = "SAME" if ka == kb else "CHANGED"
        print(f"   {mark:<26} {same}")
        if ka != kb:
            for k in sorted(ka - kb):
                print(f"      only in A: {k}")
            for k in sorted(kb - ka):
                print(f"      only in B: {k}")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "sites":
        cmd_sites(sys.argv[2])
    elif cmd == "key":
        cmd_key(sys.argv[2], sys.argv[3])
    elif cmd == "leaf":
        cmd_leaf(sys.argv[2], sys.argv[3])
    elif cmd == "allkeys":
        cmd_allkeys(sys.argv[2])
    elif cmd == "apply":
        cmd_apply(sys.argv[2])
    elif cmd == "compare":
        cmd_compare(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
