import json, glob, statistics, collections
root = "/home/hiro/prj/jev-optimize/"
def chunk(n): return max(32, (n + 8 + 15) & ~15)
files = glob.glob(root + "artifacts/hintbench-*/**/samples.json", recursive=True)
tab = collections.defaultdict(list); minority = []; legs = 0
kern = collections.defaultdict(lambda: collections.defaultdict(list))
for f in files:
    d = json.load(open(f)); h = d["header"]
    era = "exp6" if h["started"] >= "2026-09-23T15" else "exp4/5+oracle"
    for lab, path in h["labels"].items():
        if not (lab in ("base", "aa") or lab.startswith("n")): continue
        c = chunk(len(path))
        k5 = [s["ns"]/1e6 for s in d["samples"] if s["label"] == lab and s["workload"] == "k5"]
        med = statistics.median(k5)
        tab[(era, c)].append(med); legs += 1
        thr = 345 if era == "exp6" else 337
        slow = med > thr
        m = [x for x in k5 if (x > thr) != slow]
        if m: minority.append((f.replace(root, ""), lab, len(path), round(med,1), [round(x,1) for x in m]))
        for w in ["k%d" % i for i in range(1, 9)]:
            kern[(era, c)][w].append(statistics.median([s["ns"]/1e6 for s in d["samples"] if s["label"] == lab and s["workload"] == w]))
print("baseline legs:", legs)
for k in sorted(tab):
    v = tab[k]; print(k, "legs", len(v), "k5 median-of-medians %.1f range [%.1f, %.1f]" % (statistics.median(v), min(v), max(v)))
    print("     ", " ".join("%s %.1f" % (w, statistics.median(x)) for w, x in kern[k].items()))
print("legs with runs on the other side of the threshold:", len(minority))
for m in minority: print("  ", m)
