#!/usr/bin/env python3
"""Readout for the hintbench k5 A/A-only panel study (results.md 160).

Usage: readout.py STUDY_DIR   (every STUDY_DIR/<panel>/samples.json is read)

Per panel and leg: argv[0] length, glibc chunk class max(32, (len+23) & ~15)
and its residue mod 32, inode; for every k5*/k8* workload the per-run times
(ms, in round order), min/median/max, the ratio vs the panel's base label
(stats.json), and for k5* the mode per run and per leg:
  per run: F fast (< 345 ms), S slow (> 345 ms)  [reported; spikes only]
  per leg (pre-registered, relative): within one panel, sort all k5* leg
  medians and take the largest gap between neighbours; if it is >= 12 ms the
  legs below it are F and above it S; if it is narrower the panel has "no
  clean split" and its legs are assigned by the absolute 345 ms line instead
  (flagged "abs"), so a panel whose legs all sit in one mode scores as misses
  wherever the prediction wanted two modes.
Pre-registered prediction H6 (results.md 160): for a plain k5 workload the
leg is S iff chunk % 32 == 0.
"""
import json, os, statistics, sys, glob

THR, MIN_GAP = 345.0, 12.0

def chunk(n): return max(32, (n + 23) & ~15)

def split_point(meds):
    """Midpoint of the largest gap between sorted leg medians, or None."""
    m = sorted(meds)
    if len(m) < 2: return None
    gap, i = max((m[j + 1] - m[j], j) for j in range(len(m) - 1))
    return (m[i] + m[i + 1]) / 2 if gap >= MIN_GAP else None

def main(root):
    total = {"ok": 0, "miss": 0, "unassigned": 0}
    for f in sorted(glob.glob(os.path.join(root, "*", "samples.json"))):
        pid = os.path.basename(os.path.dirname(f))
        d = json.load(open(f)); h = d["header"]
        st = {}
        sf = os.path.join(os.path.dirname(f), "stats.json")
        if os.path.exists(sf):
            st = json.load(open(sf))
        print(f"== {pid}: cpu {h['cpu_pin']}, {h['label_order']}, runs {h['runs']}, "
              f"warmup {h['warmup']}, {h['started']} .. {h.get('finished')}")
        info = {}
        for lab, path in h["labels"].items():
            n = len(path); c = chunk(n)
            try: ino = os.stat(path).st_ino
            except OSError: ino = "-"
            info[lab] = (n, c, ino)
            print(f"   {lab:32s} len {n:3d} chunk {c:3d} (mod32 {c % 32:2d}) inode {ino}")
        wls = [w for w in h["workloads"] if w.startswith(("k5", "k8"))]
        k5meds = [statistics.median([s["ns"] / 1e6 for s in d["samples"]
                                     if s["label"] == lab and s["workload"] == w])
                  for w in wls if w.startswith("k5") for lab in h["labels"]]
        cut = split_point(k5meds)
        print(f"   k5 leg split: " + (f"{cut:.1f} ms (relative)" if cut else
              f"NO CLEAN SPLIT (largest gap < {MIN_GAP} ms): absolute {THR} ms used"))
        c0 = cut if cut else THR
        leg_mode = lambda med: "F" if med < c0 else "S"
        k8_by_res = {}
        p3 = {}
        for w in wls:
            print(f"   -- {w} (argv tail {' '.join(h['workloads'][w])[:40]})")
            for lab in h["labels"]:
                xs = [s["ns"] / 1e6 for s in sorted(d["samples"], key=lambda s: s["round"])
                      if s["label"] == lab and s["workload"] == w]
                if not xs: continue
                med = statistics.median(xs)
                r = st.get("per_workload", {}).get(lab, {}).get(w, {}).get("ratio_vs_base")
                rtxt = f"{r:.4f}" if r else "  -   "
                n, c, _ = info[lab]
                line = (f"   {lab[:24]:24s} len {n:3d} c{c:3d} min {min(xs):6.1f} med {med:6.1f} "
                        f"max {max(xs):6.1f} ratio {rtxt}")
                if w.startswith("k5"):
                    m = leg_mode(med)
                    runs = "".join("F" if x < THR else "S" for x in xs)
                    line += f" mode {m} runs {runs}"
                    # every leg in this study is a baseline copy; on archived
                    # runs this line also scores `cand`, which is not a test
                    if w == "k5" or w == "k5a0":
                        pred = "S" if c % 32 == 0 else "F"
                        verdict = "unassigned" if m == "?" else ("ok" if m == pred else "miss")
                        total[verdict] += 1
                        line += f" pred {pred} {verdict.upper()}"
                    p3.setdefault(lab, {})[w] = m
                else:
                    k8_by_res.setdefault((w, c % 32), []).append(med)
                print(line)
                print("      " + " ".join(f"{x:.0f}" for x in xs))
        for (w, res), v in sorted(k8_by_res.items()):
            print(f"   {w} chunk%32={res:2d}: {len(v)} legs, median of leg medians "
                  f"{statistics.median(v):.1f} ms")
        if any(k.startswith("k5a") and k != "k5a0" for m in p3.values() for k in m):
            for lab, m in p3.items():
                a = [m.get(k, "?") for k in ("k5a0", "k5a7", "k5a25", "k5a41", "k5a57")]
                alt = (a[1] == a[3] and a[2] == a[4] and a[1] != a[2] and "?" not in a[1:])
                print(f"   P3 {lab[:24]}: a0/a7/a25/a41/a57 = {'/'.join(a)}; "
                      f"alternation a7=a41, a25=a57, a7!=a25: {'YES' if alt else 'NO'}")
        print()
    print(f"H6 plain-k5 legs: ok {total['ok']}, miss {total['miss']}, "
          f"unassigned {total['unassigned']}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         "/home/hiro/prj/jev-optimize/artifacts/hintbench-aa-study")
