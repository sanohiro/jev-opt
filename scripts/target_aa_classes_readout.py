#!/usr/bin/env python3
"""Readout of scripts/target_aa_classes.sh (results.md 163, pre-registered).

Input: OUT/samples.json (bench.py run, --argv0-raw) and OUT/stats.json
(bench.py stats --base c96). Every leg is a hard link to one stripped inode,
exec'd from a path of a different byte length; the only difference between
legs is argv[0]'s length (and so its glibc chunk class / mimalloc bin).

Ratios follow bench.py: ratio = t_c96 / t_leg, > 1 means the leg is FASTER
than the c96 leg (the pinned class of decision 97).

Rules (verbatim from the pre-registration):
  per case w, leg L != base:
    med_ratio  = median(base runs) / median(L runs)
    boot ratio + 95% CI = stats.json per_workload[L][w] (mean-based, paired)
    spread     = max(IQR/median of L's runs, IQR/median of base's runs) / 2
    case shift is SIGNIFICANT iff the CI excludes 1 AND |med_ratio - 1| > spread
    case shift is LARGE iff SIGNIFICANT AND |med_ratio - 1| >= M
      (M = 3% on jaq, its MDE and the top of its 2-4% A/A; 1% on zopfli)
  Rule 1  leg aggregate (geomean, stats.json) outside [0.995, 1.005] -> flag.
  Rule 2  (broad effect) a leg with every case SIGNIFICANT, one sign, and Rule 1.
  Rule 3  (case-local effect, the hintbench k5 shape) a case in which at least
          two legs are LARGE with the same sign.
  Target verdict:
    CLASS EFFECT         Rule 2 or Rule 3 holds somewhere;
    FLAG, NOT CLAIMED    otherwise, if Rule 1 flags a leg or any case/leg is
                         LARGE (one leg alone is not claimed: a second panel,
                         the owner's call, would be needed);
    NULL                 otherwise.
  Pattern (reported, not a gate): per case, the sign of each SIGNIFICANT leg,
  and whether it matches hintbench's period-32 map read against c96 (c80 and
  c112 shifted the same way, c128 not shifted).
"""

import argparse
import json
import os
import statistics
import sys

TOL = 0.005


def iqr_rel(xs):
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return (q[2] - q[0]) / statistics.median(xs)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="panel directory (samples.json, stats.json)")
    ap.add_argument("--samples")
    ap.add_argument("--stats")
    ap.add_argument("--base", default="c96")
    ap.add_argument("--target", default="?")
    ap.add_argument("--min-shift", type=float, default=None,
                    help="M; default 0.03 for jaq, 0.01 otherwise")
    a = ap.parse_args()
    M = a.min_shift if a.min_shift is not None else (0.03 if a.target == "jaq" else 0.01)
    samples_p = a.samples or os.path.join(a.out, "samples.json")
    stats_p = a.stats or os.path.join(a.out, "stats.json")
    doc = json.load(open(samples_p))
    st = json.load(open(stats_p))
    if st["base"] != a.base:
        sys.exit(f"stats.json base is {st['base']!r}, readout wants {a.base!r}")
    h = doc["header"]
    labels, wls = st["labels"], st["workloads"]
    runs = {}
    for s in doc["samples"]:
        runs.setdefault((s["label"], s["workload"]), []).append(s["ns"] / 1e6)

    a0 = h.get("argv0") or {}
    print(f"== argv0 class readout: target {a.target}, {samples_p} ==")
    print(f"mode {h.get('argv0_mode')}, cpu {h.get('cpu_pin')}, gap {h.get('gap_ms')} ms, "
          f"stdout {h.get('stdout_mode')}, {h.get('label_order')}, warmup {h.get('warmup')}, "
          f"runs {h.get('runs')}, {h.get('started')} .. {h.get('finished')}")
    for l in labels:
        d = a0.get(l, {})
        print(f"  {l:<6} len {d.get('len', '?'):>3} class {d.get('class', '?'):>3}  {d.get('path', '')}")
    if h.get("stdout_mismatches"):
        print(f"WARNING stdout mismatches: {h['stdout_mismatches']}")
    print()

    print("| case | leg | median ms | IQR/med | med ratio vs base | boot ratio | 95% CI | spread | sig |")
    print("|---|---|--:|--:|--:|--:|---|--:|:-:|")
    legres = {}
    for w in wls:
        b = runs[(a.base, w)]
        bm = statistics.median(b)
        print(f"| {w} | {a.base} (base) | {bm:.1f} | {iqr_rel(b)*100:.2f}% | 1 | 1 | | | |")
        for l in labels:
            if l == a.base:
                continue
            c = runs[(l, w)]
            cm = statistics.median(c)
            mr = bm / cm
            pw = st["per_workload"][l][w]
            lo, hi = pw["ci95"]
            spread = max(iqr_rel(c), iqr_rel(b)) / 2
            excl = lo > 1.0 or hi < 1.0
            sig = excl and abs(mr - 1) > spread
            sign = (mr > 1) - (mr < 1)
            legres.setdefault(l, []).append((w, mr, sig, sign, spread))
            print(f"| {w} | {l} | {cm:.1f} | {iqr_rel(c)*100:.2f}% | {mr:.4f} | "
                  f"{pw['ratio_vs_base']:.4f} | [{lo:.4f}, {hi:.4f}] | "
                  f"{spread*100:.2f}% | {'yes' if sig else 'no'} |")
    print()

    print("| leg | aggregate (geomean) | 95% CI | Rule 1 (outside +-0.5%) | all cases sig, one sign | Rule 2 |")
    print("|---|--:|---|:-:|:-:|:-:|")
    r2legs, r1legs = {}, []
    for l in labels:
        if l == a.base:
            continue
        ag = st["aggregate"][l]
        r1 = abs(ag["ratio"] - 1) > TOL
        rs = legres[l]
        allsig = all(x[2] for x in rs) and len({x[3] for x in rs}) == 1
        if r1:
            r1legs.append(l)
        if r1 and allsig:
            r2legs[l] = rs[0][3]
        print(f"| {l} | {ag['ratio']:.4f} | [{ag['ci95'][0]:.4f}, {ag['ci95'][1]:.4f}] | "
              f"{'FLAG' if r1 else 'ok'} | {'yes' if allsig else 'no'} | {'YES' if (r1 and allsig) else 'no'} |")
    print()

    # Rule 3 and the per-case pattern.
    r3cases, large = {}, []
    print(f"per case, SIGNIFICANT legs (+ = faster than {a.base}; * = LARGE, |shift| >= {M*100:.1f}%):")
    for w in wls:
        sig = {l: (x[3], abs(x[1] - 1) >= M) for l, rs in legres.items()
               for x in rs if x[0] == w and x[2]}
        for l, (sg, lg) in sig.items():
            if lg:
                large.append(f"{l}/{w}")
        for sgn in (1, -1):
            ls = [l for l, (sg, lg) in sig.items() if lg and sg == sgn]
            if len(ls) >= 2:
                r3cases.setdefault(w, []).append((sgn, ls))
        hb = (sig.get("c80", (0,))[0] != 0 and sig.get("c80", (0,))[0] == sig.get("c112", (None,))[0]
              and "c128" not in sig)
        print(f"  {w}: " + (", ".join(f"{l}{'+' if sg > 0 else '-'}{'*' if lg else ''}"
                                     for l, (sg, lg) in sig.items()) or "(none)")
              + f"   hintbench map: {'MATCH' if hb else 'no'}"
              + (f"   Rule 3: YES" if w in r3cases else ""))
    print()

    need = max(x[4] for rs in legres.values() for x in rs)
    print(f"largest per-case spread threshold in this panel: {need*100:.2f}%; "
          f"M = {M*100:.1f}% (a shift below max(spread, M) cannot be claimed here)")
    if r2legs or r3cases:
        verdict = "CLASS EFFECT"
        why = ([f"Rule 2 {l} {'faster' if s > 0 else 'slower'}" for l, s in r2legs.items()]
               + [f"Rule 3 {w}: {'faster' if sg > 0 else 'slower'} {'/'.join(ls)}"
                  for w, v in r3cases.items() for sg, ls in v])
    elif r1legs or large:
        verdict = "FLAG, NOT CLAIMED"
        why = ([f"Rule 1 {l}" for l in r1legs] + [f"LARGE {x}" for x in large])
    else:
        verdict = "NULL"
        why = []
    print(f"VERDICT: {verdict}" + (f" ({'; '.join(why)})" if why else ""))

if __name__ == "__main__":
    main()
