#!/usr/bin/env python3
"""Which cost-declined loops sit in the target's hot code?

SPEC.ja.md 7 hands Jev the functions whose loops got a `cost` remark, and
SPEC.ja.md 8.3 makes `cost` the reason class a loop hint can overturn. This
script asks the question the other way round from
`scripts/remark_attribution.py`, which on a large target drowns in ambiguous
DebugLocs (results.md "Stage 0 (jaq)" section 56):

  1. collect every `file:line` in the build log that carries a cost-model
     remark;
  2. take the hot symbols from `scripts/interp_share.py --tsv`;
  3. disassemble each and map its instructions to innermost source lines
     with `addr2line -i`;
  4. report each (cost location, hot symbol) pair weighted by the symbol's
     profile share times the fraction of its instructions at that line,
     with every loop-decision remark seen at that location.

The weight is deliberately crude --- it answers "is there a cost-declined
loop anywhere near the hot path", not "how much is it worth". The remarks
printed beside it are what says whether the cost verdict can even be
attributed to this inline instance.

Usage:
  scripts/cost_hot_loops.py [TOPN]      # paths below are the jaq defaults
"""

import collections, csv, os, re, subprocess, sys, tempfile

BIN = "target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/jaq"
LOG = "remarks/jaq/baseline-build.log"
TSV = "artifacts/jaq-day0/interp-share-all.tsv"
TOPN = int(sys.argv[1]) if len(sys.argv) > 1 else 25

# cost remark locations
cost = collections.Counter()
other = collections.defaultdict(collections.Counter)
RE = re.compile(r"^remark: (\S+?):(\d+):(\d+): (.*)$")
for line in open(LOG, errors="replace"):
    m = RE.match(line.rstrip("\n"))
    if not m: continue
    loc = f"{m.group(1)}:{m.group(2)}"
    t = m.group(4)
    if "cost-model indicates" in t:
        cost[loc] += 1
    if t.startswith("loop not vectorized") or "cost-model indicates" in t or t.startswith("vectorized loop") or t.startswith("unrolled") or t.startswith("completely unrolled"):
        other[loc][t.split(" (")[0][:80]] += 1

# hot symbols
rows = []
with open(TSV) as f:
    for r in csv.DictReader(f, delimiter="\t"):
        rows.append(r)
rows = rows[:TOPN]

nm = subprocess.run(["nm","-S","--defined-only",BIN],capture_output=True,text=True).stdout
dem = subprocess.run(["llvm-cxxfilt"],input=nm,capture_output=True,text=True).stdout
addr_of = {}
for raw,d in zip(nm.splitlines(), dem.splitlines()):
    p=raw.split()
    if len(p)<4 or p[2].lower()!='t': continue
    try: a,s=int(p[0],16),int(p[1],16)
    except ValueError: continue
    if s: addr_of.setdefault(" ".join(d.split()[3:]), []).append((a,s))

hits = collections.defaultdict(float)
hits_insns = collections.defaultdict(int)
for r in rows:
    fn = r["function"]; share = float(r["share"])
    for a,s in addr_of.get(fn, []):
        out=subprocess.run(["objdump","-d","--no-show-raw-insn",f"--start-address={a}",f"--stop-address={a+s}",BIN],capture_output=True,text=True).stdout
        insns=[]
        for line in out.splitlines():
            m=re.match(r"^\s+([0-9a-f]+):\t(.*)$",line)
            if m: insns.append(int(m.group(1),16))
        if not insns: continue
        with tempfile.NamedTemporaryFile("w",delete=False,suffix=".txt") as f:
            for ad in insns: f.write("0x%x\n"%ad)
            lf=f.name
        a2l=subprocess.run(["addr2line","-i","-f","-p","-C","-e",BIN,"@"+lf],capture_output=True,text=True).stdout
        os.unlink(lf)
        chains=[];cur=None
        for line in a2l.splitlines():
            if line.startswith(" (inlined by)"): cur.append(line)
            else: cur=[line.strip()];chains.append(cur)
        per=collections.Counter()
        for ch in chains:
            m=re.match(r"^(?P<fn>.*?) at (?P<file>.*?):(?P<line>\d+|\?)",ch[0])
            if not m: continue
            per[f"{m.group('file')}:{m.group('line')}"]+=1
        for loc,n in per.items():
            # remark paths are suffixes of DWARF paths
            for cloc in cost:
                cf,_,cl = cloc.rpartition(":")
                if loc.endswith("/"+cf+":"+cl) or loc == cloc:
                    hits[(cloc, fn)] += share * n / len(insns)
                    hits_insns[(cloc, fn)] += n
print(f"cost-remark locations in the log: {len(cost)}")
print(f"\nhot symbols (top {TOPN} by profile share) whose code contains a cost-declined line:")
for (loc, fn), w in sorted(hits.items(), key=lambda kv:-kv[1])[:25]:
    print(f"  ~{w:5.2f}% of total  {hits_insns[(loc,fn)]:4d} insns  {loc}")
    print(f"        in {fn[:110]}")
    for t,c in other[loc].most_common(6):
        print(f"           {c:4d}x {t}")
