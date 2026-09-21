#!/usr/bin/env python3
"""An arm spec -> one merged.profdata, reusing the per-candidate profraws.

Experiment 1 ran every arm's whole input set through the instrumented binary
again. Experiment 2 does not need to: scripts/jaq_candidate_profile.py
already ran every pool candidate once, with its own `LLVM_PROFILE_FILE`, and
`llvm-profdata merge` of a subset of those profraws is by construction the
same profile as running that subset (results.md section 63 verified `%m`
pooling and one-file-per-process merge agree to the bit). So an arm is a
merge, and the only runs left are the ones no cached profraw covers: a
parametric candidate at a scaled `n`, and a user-supplied sample.

Spec format (scripts/jaq_select_arms.py writes these):

  {"arm": "E_expert", "items": [
     {"id": "bench-0022", "stdin": "1048576\\n"},   # scaled -> must be run
     {"id": "clitest-0018"},                        # cached profraw
     {"id": "sample-objsearch", "argv": ["...", "f.json"], "cwd": "."}
  ]}

An item with `argv` is a literal invocation and is always run; an item with
only an `id` is taken from targets/jaq/pool/pool.json and served from the
cache; an item with an `id` and a `stdin` that differs from the pool's is run
fresh into its own profraw.

Usage:
  scripts/jaq_arm_profile.py --spec artifacts/jaq-exp2/arms/E_expert.json \\
      --binary target-jaq-pgo-gen/.../jaq \\
      --cache <candidate profraw dir> --scaled-cache <scaled profraw dir> \\
      --out pgo/jaq/arms/E_expert/merged.profdata
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
CAND_JSONL = os.path.join(REPO, "artifacts/jaq-exp2/candidates.jsonl")
SCALED_JSONL = os.path.join(REPO, "artifacts/jaq-exp2/candidates-scaled.jsonl")


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--spec", required=True)
    p.add_argument("--binary", required=True)
    p.add_argument("--cache", required=True)
    p.add_argument("--scaled-cache", default=None)
    p.add_argument("--run-dir", default=None,
                   help="where freshly run profraws go (default: beside the "
                        "output profdata)")
    p.add_argument("--out", required=True)
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--llvm-profdata", default=None)
    args = p.parse_args()

    tool = args.llvm_profdata or CP.llvm_profdata_path()
    spec = json.load(open(args.spec))
    pool = {i["id"]: i for i in pool_mod.load_pool()["items"]}
    gen = os.path.abspath(args.binary)
    run_dir = args.run_dir or os.path.join(
        os.path.dirname(os.path.abspath(args.out)), "raw")
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    # Per-candidate wall times, so the manifest can record the training wall
    # an equivalent fresh run would have taken. scripts/profdata_sanity.py
    # divides the largest block count by it.
    inst_ms = {}
    for f, key in ((CAND_JSONL, lambda r: (r["id"], None)),
                   (SCALED_JSONL, lambda r: (r["id"], str(r["scaled_n"])))):
        if os.path.exists(f):
            for line in open(f):
                r = json.loads(line)
                if r.get("kind", "").startswith("candidate"):
                    inst_ms[key(r)] = r["inst_ms"]

    raws, ran, cached, wall = [], 0, 0, 0.0
    env = dict(os.environ)
    for spec_item in spec["items"]:
        cid = spec_item["id"]
        base = pool.get(cid)
        if "argv" in spec_item:
            item = {"argv": spec_item["argv"],
                    "stdin": spec_item.get("stdin", ""),
                    "cwd": spec_item.get("cwd", ".")}
            raw = os.path.join(run_dir, cid + ".profraw")
        elif base is None:
            sys.exit(f"{cid}: not in the pool and has no argv")
        elif "stdin" in spec_item and spec_item["stdin"] != base["stdin"]:
            item = dict(base, stdin=spec_item["stdin"])
            n = spec_item["stdin"].strip()
            hit = os.path.join(args.scaled_cache or "", f"{cid}.n{n}.profraw")
            if args.scaled_cache and os.path.exists(hit):
                raws.append(hit)
                cached += 1
                wall += inst_ms.get((cid, n), 0.0) / 1000.0
                continue
            raw = os.path.join(run_dir, f"{cid}.n{n}.profraw")
        else:
            hit = os.path.join(args.cache, cid + ".profraw")
            if not os.path.exists(hit):
                sys.exit(f"{cid}: no cached profraw at {hit}")
            raws.append(hit)
            cached += 1
            wall += inst_ms.get((cid, None), 0.0) / 1000.0
            continue
        if os.path.exists(raw):
            os.remove(raw)
        env["LLVM_PROFILE_FILE"] = raw
        t0 = time.perf_counter()
        r = pool_mod.run_item(gen, item, timeout=args.timeout, env=env)
        wall += time.perf_counter() - t0
        if r["status"] != "ok" or r["rc"] != 0:
            sys.exit(f"{cid}: training run failed: {r}")
        raws.append(raw)
        ran += 1

    print(f"arm {spec['arm']}: {len(raws)} invocations "
          f"({cached} served from the per-candidate cache, {ran} run now, "
          f"{wall:.2f} s of training wall in total)")
    subprocess.run([tool, "merge", "-o", args.out] + raws, check=True)
    print(f"$ llvm-profdata merge -o {args.out} <{len(raws)} profraw>")
    with open(args.out + ".manifest.json", "w") as fh:
        json.dump({"arm": spec["arm"], "n_invocations": len(raws),
                   "cached": cached, "ran": ran, "run_wall_s": wall,
                   "items": spec["items"]}, fh, indent=1)


if __name__ == "__main__":
    main()
