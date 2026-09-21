#!/usr/bin/env python3
"""The scale knob: run each parametric pool candidate as large as it will go.

decisions.ja.md entry 46: the jaq repository contains no large input, and the
thing that could rescue it is not selection but running an existing candidate
*bigger*. The 27 `examples/benches/*.jq` items take `n` on stdin and
`examples/benches.json` fixes one `n` per benchmark; across the file those `n`
range over

    7, 17, 23, 128, 8192, 16384, 65536, 131072, 524288, 1048576

which is what "bench.sh's range" means here. This walks each benchmark *up*
that ladder from its own `n`, on the plain binary, and keeps the largest rung
whose wall time stays inside bench.sh's own `timeout 10`. Walking up rather
than starting at 1048576 matters: `ack`, `tree-contains` and `tree-flatten`
are exponential in `n`, and a probe that started at the top would spend a
minute timing out and might exhaust memory first.

Each chosen variant is then profiled under the instrumented binary exactly the
way scripts/jaq_candidate_profile.py profiles a pool item, so the rows of the
two files are directly comparable and can be mixed in one arm.

Usage:
  scripts/jaq_scale_probe.py \
      --plain target-jaq-plain/x86_64-unknown-linux-gnu/release/jaq \
      --binary target-jaq-pgo-gen/x86_64-unknown-linux-gnu/release/jaq \
      --ref pgo/jaq/merged.profdata \
      --profraw-dir <dir> --out artifacts/jaq-exp2/candidates-scaled.jsonl
"""

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jaq_candidate_profile as CP            # noqa: E402
import jaq_pool_extract as pool_mod           # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The distinct `n` in examples/benches.json, ascending: bench.sh's range.
LADDER = [7, 17, 23, 128, 8192, 16384, 65536, 131072, 524288, 1048576]


def parametric(items):
    """Pool items that take `n` on stdin, i.e. examples/benches/*.jq.

    bench.sh's three hand-written benchmarks (`empty`, `bf-fib`, `defs`) are
    `bench` items too but are not parametric in this sense: their size lives
    in a loop count, a .bf file and a generated filter file.
    """
    out = []
    for it in items:
        if it["source"] != "bench" or not it["origin"].startswith("examples/"):
            continue
        n = it["stdin"].strip()
        if n.isdigit():
            out.append((it, int(n)))
    return out


def wall(plain, it, stdin, timeout):
    """Seconds, or None if the run timed out or failed.

    Failure has to disqualify a rung, not just slowness: `ack.jq` is
    `ack(3; .)`, so at n = 1048576 the interpreter blows the stack and aborts
    in 19 ms. A probe that only looked at wall time would happily pick a rung
    that produces no profile at all.
    """
    t0 = time.perf_counter()
    try:
        p = subprocess.run([plain] + it["argv"], input=stdin.encode(),
                           cwd=os.path.join(REPO, it["cwd"]),
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None
    return time.perf_counter() - t0


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plain", required=True)
    p.add_argument("--binary", required=True)
    p.add_argument("--ref", required=True)
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--profraw-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--budget", type=float, default=10.0,
                   help="bench.sh's own per-invocation timeout, in seconds")
    p.add_argument("--llvm-profdata", default=None)
    args = p.parse_args()

    tool = args.llvm_profdata or CP.llvm_profdata_path()
    plain = os.path.abspath(args.plain)
    gen = os.path.abspath(args.binary)
    os.makedirs(args.profraw_dir, exist_ok=True)

    ref = CP.show_counts(tool, args.ref)
    names = sorted(ref)
    dem = CP.demangle_all(names)
    layer = {n: CP.layer_of(dem[n]) for n in names}
    hot = sorted(ref, key=lambda n: -(max(ref[n]) if ref[n] else 0))[:args.top]

    items = [i for i in pool_mod.load_pool()["items"]
             if not i.get("poisons_profile")]
    todo = parametric(items)
    print(f"{len(todo)} parametric candidates\n")
    print(f"{'id':12s} {'bench':16s} {'repo n':>9s} {'chosen n':>9s} "
          f"{'plain s':>8s}  ladder probe")

    rows = []
    env = dict(os.environ)
    for it, n0 in todo:
        ok, trace = [(n0, it["dry_ms"] / 1000.0)], []
        for n in LADDER:
            if n <= n0:
                continue
            s = wall(plain, it, f"{n}\n", args.budget)
            trace.append(f"{n}:" + ("failed" if s is None else f"{s:.2f}s"))
            if s is None:
                break
            ok.append((n, s))
            if s > args.budget / 2:
                # The next rung is at least 2x; do not spend the timeout.
                break
        # Profile the largest rung that also survives the instrumented
        # binary, which is several times slower and uses more stack.
        raw = best_n = best_s = r = funcs = None
        while ok:
            best_n, best_s = ok.pop()
            raw = os.path.join(args.profraw_dir,
                               it["id"] + f".n{best_n}.profraw")
            if os.path.exists(raw):
                os.remove(raw)
            env["LLVM_PROFILE_FILE"] = raw
            r = pool_mod.run_item(gen, dict(it, stdin=f"{best_n}\n"),
                                  timeout=120.0, env=env)
            if r["status"] == "ok" and r["rc"] == 0 and \
                    os.path.exists(raw) and os.path.getsize(raw) > 0:
                break
            trace.append(f"inst {best_n}:failed")
        funcs = CP.show_counts(tool, raw)
        by_layer = dict.fromkeys(CP.LAYERS, 0)
        total, mx, mx_fn = 0, 0, None
        for fn, counts in funcs.items():
            if not counts:
                continue
            s = sum(counts)
            if s:
                total += s
                by_layer[layer.get(fn) or CP.layer_of(dem.get(fn, fn))] += s
            if max(counts) > mx:
                mx, mx_fn = max(counts), fn
        hot_sum = sum(sum(funcs.get(h, ())) for h in hot)
        data = sum(by_layer[k] for k in CP.DATA_LAYERS)
        start = sum(by_layer[k] for k in CP.START_LAYERS)
        rows.append({
            "kind": "candidate_scaled", "id": it["id"], "source": it["source"],
            "origin": it["origin"], "filter": it.get("filter", ""),
            "argv": it["argv"], "repo_n": n0, "scaled_n": best_n,
            "stdin": f"{best_n}\n",
            "plain_s": round(best_s, 3) if best_s else None,
            "ladder": trace,
            "input_bytes": len(f"{best_n}\n"), "dry_ms": it["dry_ms"],
            "inst_ms": round(r["ms"], 3), "inst_status": r["status"],
            "inst_rc": r["rc"], "total_count": total, "max_block": mx,
            "max_block_fn": dem.get(mx_fn, mx_fn) if mx_fn else None,
            "hot20_count": hot_sum,
            "hot20_share": hot_sum / total if total else 0.0,
            "hot20_zero": sum(1 for h in hot if not sum(funcs.get(h, ()))),
            "layer_counts": by_layer,
            "layer_share": {k: (by_layer[k] / total if total else 0.0)
                            for k in CP.LAYERS},
            "datapath_count": data, "startup_count": start,
            "datapath_startup": (data / start) if start else float("inf"),
            "profraw": os.path.relpath(raw, REPO) if raw.startswith(REPO)
                       else raw,
        })
        print(f"{it['id']:12s} {it['origin'].split('/')[-1][:16]:16s} "
              f"{n0:>9d} {best_n:>9d} "
              f"{(best_s if best_s else -1):8.2f}  {' '.join(trace)}",
              flush=True)

    with open(args.out, "w") as fh:
        fh.write(json.dumps({
            "kind": "meta", "schema_version": 1, "ladder": LADDER,
            "budget_s": args.budget, "n_scaled": len(rows),
            "scaled_up": sum(1 for r in rows if r["scaled_n"] > r["repo_n"]),
            "instrumented_wall_s": sum(r["inst_ms"] for r in rows) / 1000.0,
        }) + "\n")
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    up = sum(1 for r in rows if r["scaled_n"] > r["repo_n"])
    print(f"\n{args.out}: {len(rows)} rows, {up} scaled above the repo's n, "
          f"{sum(r['inst_ms'] for r in rows) / 1000:.1f} s instrumented")


if __name__ == "__main__":
    main()
