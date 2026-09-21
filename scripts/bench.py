#!/usr/bin/env python3
"""Interleaved wall-clock benchmark harness and paired-bootstrap statistics.

Python 3 standard library only. hyperfine is not installed on this machine and
hyperfine cannot interleave several binaries round-robin anyway, which
SPEC.ja.md 10 requires ("round-robin the configuration order; running them
back to back makes the later ones slower as the chip heats up").

Two subcommands:

  run    spawn every (round, workload, label) combination, pinned with taskset,
         and write one JSON file with every sample.
  stats  per-workload mean/median/min, paired-bootstrap CI of the speed ratio
         against a base label, and markdown tables for results.md.

Conventions fixed here and quoted in results.md:

  * A *round* is the pairing unit. Round r runs every workload for every label
    before round r+1 starts, so a slow patch of the machine hits all labels.
    The label order rotates by round, so no label is permanently first.
    `--shuffle SEED` replaces the rotation with a seeded random permutation
    per (round, workload). Rotation keeps two adjacent labels adjacent in
    every round, so an in-run A/A between neighbours prices only the drift
    over one slot and understates the label-to-label noise for a pair at
    opposite ends of the round (results.md "Experiment 1 (jaq)" section 69).
    Shuffling gives every pair the same distribution of separations, so the
    A/A prices the whole round. The default is unchanged.
  * speed ratio = t_base / t_config. Greater than 1 means the config is
    FASTER than the base.
  * The bootstrap resamples round indices with replacement, jointly across
    workloads and labels (the pair is the round), 10000 resamples, fixed seed.
  * The aggregate is the unweighted geometric mean of the per-workload ratios.
    The toy has no pre-frozen case weights (SPEC.ja.md 11 freezes them per
    target before a holdout); equal weights are stated, not derived.
"""

import argparse
import json
import math
import os
import platform
import random
import shlex
import statistics
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def cmd_run(args):
    labels = []
    for spec in args.label:
        name, _, path = spec.partition("=")
        if not path:
            sys.exit(f"--label wants NAME=PATH, got {spec!r}")
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            sys.exit(f"no such binary: {path}")
        labels.append((name, path))

    workloads = []
    for spec in args.workload:
        name, sep, argstr = spec.partition("=")
        workloads.append((name, shlex.split(argstr) if sep else [name]))

    pin = ["taskset", "-c", args.cpu]

    # SPEC.ja.md 10: "discard stdout the same way in both variants, and keep
    # the correctness check separate from the timing". `pipe` (the default,
    # unchanged for toy and zopfli) reads the child's stdout into memory and
    # compares it across labels, which is free when the output is a checksum
    # line and ruinous when it is a re-serialised 25 MB JSON document: the
    # child then blocks on this process's pipe reads inside the timed window.
    # `devnull` is for those targets; correctness there is run_correctness's
    # sha256 of stdout, taken outside the timing run.
    sink = subprocess.PIPE if args.stdout == "pipe" else subprocess.DEVNULL

    header = {
        "schema_version": 1,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cpu_pin": args.cpu,
        "warmup": args.warmup,
        "runs": args.runs,
        "labels": {n: p for n, p in labels},
        "workloads": {n: a for n, a in workloads},
        "uname": platform.uname()._asdict(),
        "aslr": read_file("/proc/sys/kernel/randomize_va_space"),
        "lscpu_e": capture(["lscpu", "-e"]),
        "taskset": " ".join(pin),
        "gap_ms": args.gap_ms,
        "label_order": ("rotate" if args.shuffle is None
                        else f"shuffle:{args.shuffle}"),
        "note": "ns is time.perf_counter_ns around subprocess.run, so it "
                "includes fork/exec and process teardown.",
    }

    samples = []
    digests = {}
    digest_mismatches = []
    total = (args.warmup + args.runs) * len(workloads) * len(labels)
    done = 0
    for r in range(args.warmup + args.runs):
        warm = r < args.warmup
        for wname, wargs in workloads:
            order = list(range(len(labels)))
            if args.shuffle is None:
                order = order[r % len(order):] + order[:r % len(order)]
            else:
                # Seeded on (seed, round, workload) so the whole run is
                # reproducible from the seed alone and no two workloads in a
                # round share a permutation.
                random.Random(f"{args.shuffle}:{r}:{wname}").shuffle(order)
            for i in order:
                lname, path = labels[i]
                argv = pin + [path] + wargs
                t0 = time.perf_counter_ns()
                proc = subprocess.run(argv, stdout=sink,
                                      stderr=subprocess.DEVNULL)
                t1 = time.perf_counter_ns()
                if proc.returncode != 0:
                    sys.exit(f"{lname}/{wname} exited {proc.returncode}")
                if proc.stdout is not None:
                    # The toy prints a checksum line; keep it as a free
                    # correctness check across configs (SPEC.ja.md 10).
                    out = proc.stdout.decode(errors="replace").strip()
                    key = wname
                    if key not in digests:
                        digests[key] = out
                    elif digests[key] != out and [lname, wname] not in digest_mismatches:
                        digest_mismatches.append([lname, wname])
                if not warm:
                    samples.append({"label": lname, "workload": wname,
                                    "round": r - args.warmup,
                                    "ns": t1 - t0})
                done += 1
                if args.progress and done % 20 == 0:
                    print(f"  {done}/{total}", file=sys.stderr, flush=True)
                if args.gap_ms:
                    time.sleep(args.gap_ms / 1000.0)

    header["stdout_mode"] = args.stdout
    header["stdout_per_workload"] = digests
    header["stdout_mismatches"] = digest_mismatches
    header["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    doc = {"header": header, "samples": samples}
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=1)
    print(f"{args.out}: {len(samples)} timed samples, "
          f"{len(labels)} labels x {len(workloads)} workloads x {args.runs} rounds")
    if digest_mismatches:
        print(f"WARNING: stdout differs between labels: {digest_mismatches}")


def capture(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True).stdout
    except OSError:
        return None


def read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

def cmd_stats(args):
    doc = json.load(open(args.infile))
    samples = doc["samples"]
    labels, workloads, rounds = [], [], set()
    for s in samples:
        if s["label"] not in labels:
            labels.append(s["label"])
        if s["workload"] not in workloads:
            workloads.append(s["workload"])
        rounds.add(s["round"])
    rounds = sorted(rounds)

    # t[label][workload][round] in seconds
    t = {l: {w: {} for w in workloads} for l in labels}
    for s in samples:
        t[s["label"]][s["workload"]][s["round"]] = s["ns"] / 1e9

    base = args.base
    if base not in labels:
        sys.exit(f"base label {base!r} not among {labels}")

    rng = random.Random(args.seed)
    # One shared set of resampled round-index vectors, so every config is
    # compared to the base over the same resamples.
    boot_idx = [[rng.randrange(len(rounds)) for _ in rounds]
                for _ in range(args.resamples)]

    out = {"base": base, "seed": args.seed, "resamples": args.resamples,
           "rounds": len(rounds), "workloads": workloads, "labels": labels,
           "per_workload": {}, "aggregate": {}}

    for label in labels:
        per_wl = {}
        for w in workloads:
            b = [t[base][w][r] for r in rounds]
            c = [t[label][w][r] for r in rounds]
            ratio = mean(b) / mean(c)
            lo, hi = bootstrap_ratio_ci(b, c, boot_idx)
            per_wl[w] = {
                "mean_s": mean(c), "median_s": statistics.median(c),
                "min_s": min(c), "n": len(c),
                "ratio_vs_base": ratio, "ci95": [lo, hi],
                "halfwidth": (hi - lo) / 2.0,
            }
        # aggregate: geometric mean of the per-workload ratios
        agg = math.exp(mean([math.log(per_wl[w]["ratio_vs_base"]) for w in workloads]))
        alo, ahi = bootstrap_agg_ci(t, base, label, workloads, rounds, boot_idx)
        out["per_workload"][label] = per_wl
        out["aggregate"][label] = {"ratio": agg, "ci95": [alo, ahi],
                                   "halfwidth": (ahi - alo) / 2.0}

    halfwidths = {w: max(out["per_workload"][l][w]["halfwidth"]
                         for l in labels if l != base) if len(labels) > 1 else
                  out["per_workload"][base][w]["halfwidth"]
                  for w in workloads}
    worst = max(halfwidths.values())
    out["noise_floor_halfwidth_per_workload"] = halfwidths
    out["noise_floor_halfwidth_worst"] = worst
    out["mde"] = max(2 * worst, 0.03)

    if args.mde is not None:
        out["frozen_mde"] = args.mde
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
    print(markdown(out, doc))
    return out


def mean(xs):
    return sum(xs) / len(xs)


def bootstrap_ratio_ci(b, c, boot_idx):
    ratios = []
    for idx in boot_idx:
        sb = 0.0
        sc = 0.0
        for i in idx:
            sb += b[i]
            sc += c[i]
        ratios.append(sb / sc)
    ratios.sort()
    n = len(ratios)
    return ratios[int(0.025 * n)], ratios[min(n - 1, int(0.975 * n))]


def bootstrap_agg_ci(t, base, label, workloads, rounds, boot_idx):
    cols = [([t[base][w][r] for r in rounds], [t[label][w][r] for r in rounds])
            for w in workloads]
    vals = []
    k = len(workloads)
    for idx in boot_idx:
        acc = 0.0
        for b, c in cols:
            sb = 0.0
            sc = 0.0
            for i in idx:
                sb += b[i]
                sc += c[i]
            acc += math.log(sb / sc)
        vals.append(math.exp(acc / k))
    vals.sort()
    n = len(vals)
    return vals[int(0.025 * n)], vals[min(n - 1, int(0.975 * n))]


def markdown(out, doc):
    base = out["base"]
    lines = []
    h = doc["header"]
    lines.append(f"pin `{h['taskset']}`, warmup {h['warmup']}, "
                 f"{out['rounds']} timed rounds, base `{base}`, "
                 f"bootstrap {out['resamples']} resamples seed {out['seed']}, "
                 f"ASLR randomize_va_space={h.get('aslr')}")
    lines.append("")
    lines.append("| label | workload | mean ms | median ms | min ms | "
                 "ratio vs base | 95% CI | half-width |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for label in out["labels"]:
        for w in out["workloads"]:
            d = out["per_workload"][label][w]
            lines.append(
                f"| {label} | {w} | {d['mean_s']*1e3:.1f} | "
                f"{d['median_s']*1e3:.1f} | {d['min_s']*1e3:.1f} | "
                f"{d['ratio_vs_base']:.4f} | "
                f"[{d['ci95'][0]:.4f}, {d['ci95'][1]:.4f}] | "
                f"{d['halfwidth']*100:.2f}% |")
    lines.append("")
    mde = out.get("frozen_mde")
    extra = " abs change | beyond MDE? | CI excludes 1 |" if mde else ""
    lines.append("| label | aggregate ratio (geomean) | 95% CI | half-width |" + extra)
    lines.append("|---|---|---|---|" + ("---|---|---|" if mde else ""))
    for label in out["labels"]:
        a = out["aggregate"][label]
        row = (f"| {label} | {a['ratio']:.4f} | "
               f"[{a['ci95'][0]:.4f}, {a['ci95'][1]:.4f}] | "
               f"{a['halfwidth']*100:.2f}% |")
        if mde:
            delta = abs(a["ratio"] - 1.0)
            excl = "yes" if (a["ci95"][0] > 1.0 or a["ci95"][1] < 1.0) else "no"
            row += (f" {delta*100:.2f}% | "
                    f"{'YES' if delta > mde else 'no'} | {excl} |")
        lines.append(row)
    if mde:
        lines.append("")
        lines.append(f"frozen MDE (from the A/A run) = {mde*100:.2f}%. "
                     "Per-workload configs beyond it:")
        hits = []
        for label in out["labels"]:
            for w in out["workloads"]:
                d = out["per_workload"][label][w]
                if abs(d["ratio_vs_base"] - 1.0) > mde:
                    hits.append(f"{label}/{w} {(d['ratio_vs_base']-1)*100:+.2f}% "
                                f"CI [{(d['ci95'][0]-1)*100:+.2f}%, "
                                f"{(d['ci95'][1]-1)*100:+.2f}%]")
        lines.extend("  - " + h for h in hits) if hits else lines.append("  (none)")
    lines.append("")
    label_kind = ("CI half-width per workload (worst over the compared configs; "
                  "this is a spread, NOT a noise floor -- only an A/A run "
                  "measures the noise floor)"
                  if out.get("frozen_mde") else
                  "half-width per workload (worst over non-base labels)")
    lines.append(label_kind + ": " +
                 ", ".join(f"{w} {v*100:.2f}%" for w, v in
                           out["noise_floor_halfwidth_per_workload"].items()))
    if not out.get("frozen_mde"):
        lines.append(
            f"worst half-width {out['noise_floor_halfwidth_worst']*100:.2f}%"
            f" -> MDE = max(2 x half-width, 3%) = {out['mde']*100:.2f}%")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="collect interleaved samples")
    r.add_argument("--label", action="append", required=True,
                   metavar="NAME=PATH", help="a binary to measure; repeatable")
    r.add_argument("--workload", action="append", required=True,
                   metavar="NAME[=ARGS]",
                   help="argv tail for one case; ARGS defaults to NAME")
    r.add_argument("--cpu", default="2", help="taskset -c value (default 2)")
    r.add_argument("--warmup", type=int, default=5)
    r.add_argument("--runs", type=int, default=30)
    r.add_argument("--out", required=True)
    r.add_argument("--progress", action="store_true")
    r.add_argument("--shuffle", type=int, default=None, metavar="SEED",
                   help="shuffle the label order per (round, workload) with "
                        "this seed instead of rotating it by round")
    r.add_argument("--gap-ms", type=int, default=0,
                   help="idle this many milliseconds after each timed run "
                        "(outside the timed window). Default 0, which is what "
                        "the toy and zopfli runs used. A target that leaves a "
                        "large resident set behind makes the NEXT process pay "
                        "for reclaiming it, which the round-robin turns into "
                        "noise; a short gap lets the machine settle first "
                        "(results.md \"Stage 0 (jaq)\" section 55)")
    r.add_argument("--stdout", choices=("pipe", "devnull"), default="pipe",
                   help="what to do with each run's stdout: 'pipe' (default) "
                        "captures it and cross-checks it between labels; "
                        "'devnull' discards it, for targets whose output is "
                        "large enough to distort the measurement")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("stats", help="paired bootstrap over a run's JSON")
    s.add_argument("infile")
    s.add_argument("--base", required=True)
    s.add_argument("--seed", type=int, default=20260921)
    s.add_argument("--resamples", type=int, default=10000)
    s.add_argument("--json", help="also write the numbers as JSON")
    s.add_argument("--mde", type=float, default=None,
                   help="minimum detectable effect frozen by the A/A run, as a "
                        "fraction (0.03 = 3%%); enables the flagging columns")
    s.set_defaults(func=cmd_stats)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
