#!/usr/bin/env python3
"""One shot of Jev on a target: round 1 only, API only, no build, no timing.

This is the harness `docs/experiments/hintbench/jev-oneshot-v3.md` describes
and does not ship. It is committed here so that the v3 and v4 passes of
decision 84 can be repeated: the earlier passes were driven by a throwaway
script and the only record of what they sent is their JSONL.

What it does, and what it deliberately does not do:

* it loads `scripts/jev_search.py` as a module and drives the driver's own
  objects. The site lists, the state, the questions, the batching, the
  candidate validation, the confidence gate and the decision-71 readout are
  `jev_search.py`'s code, called through `JevProposer.choose()`. Nothing
  about the request is written here;
* it runs the driver's `--print-state` path first, which performs the whole
  round-1 setup (baseline dump, sites, source book, remark book, inline
  book) and then returns without making a request. Its output is discarded;
  the populated `Search` object is what this script wants;
* it **builds nothing**. Phase B is therefore asked against the *baseline*
  dump's loop sites rather than against the `apply-dump` build phase A's
  choices would have produced, and is told
  `function attributes this round already applied: none`. That is round 1
  of a run whose phase A answered KEEP_DEFAULT everywhere, which is not in
  general what phase A answers. The caveat is the one section 1 of the v3
  write-up records, and it is the price of spending no CPU;
* a phase whose every answer came back `no answer` (the driver's rule when
  the HTTP call never succeeded) is **re-sent unchanged**, and both the
  failed line and the retry stay in the JSONL. No request is ever modified
  to make it succeed.

Usage:

  scripts/jev_oneshot.py --target hintbench \
      --marks targets/hintbench/jev-marks.txt \
      --sites artifacts/hintbench-sites/sites.json \
      --site-set oracle.selected_keys_loop_hint_kernels \
      --baseline-dir artifacts/hintbench-sites/baseline \
      --vocab v4 --repeats 3 \
      --log-dir docs/experiments/hintbench --run-id jev-oneshot-v4
"""

import argparse
import contextlib
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jev_search as S          # noqa: E402
import jev_vocab as V           # noqa: E402


class _Args:
    """The subset of `jev_search.main`'s namespace `Search` reads."""

    def __init__(self, **kw):
        self.target = None
        self.marks = None
        self.sites = None
        self.site_set = None
        self.baseline_dir = None
        self.vocab = "v3"
        self.readout = "forced_top1"
        # The one-shot is round 1 of a run and nothing else: no build, no
        # history, and therefore no exploration request either (decision
        # 89 b). Its whole purpose is that a pass taken today is comparable
        # with one recorded before the mechanism existed.
        self.explore = 0
        self.source_comments = "strip"
        self.proposer = "jev"
        self.out = None
        self.run_id = None
        self.rounds = None
        self.n = None
        self.warmup = None
        self.bench_set = "training"
        self.dry_run = False
        self.print_state = True
        self.smoke = False
        self.measure_holdout = False
        self.keep_binaries = "best"
        self.oracle_phase = "all"
        self.fn_attr_scope = "own"
        self.no_site_cap = False
        self.allow_unresolved = False
        self.no_noop_skip = False
        self.no_confirm_batch = False
        self.ignore_apply_failures = False
        self.resume = False
        self.config = os.path.join(S.REPO, "jev-opt.toml")
        self.__dict__.update(kw)


def setup(args):
    """A `Search` that has done round 1's setup and made no request."""
    cfg = S.load_config(args.config)
    search = S.Search(args, cfg)
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        rc = search.run()                    # --print-state: returns 0
    if rc != 0:
        sys.exit("driver setup failed:\n" + buf.getvalue())
    return search, cfg


def ask_phase(proposer, items, ctx, round_no, phase):
    """One phase, re-sent unchanged if every answer was `no answer`."""
    picks, why = proposer.choose(items, ctx, round_no, phase)
    lost = [i for i in items
            if (why.get(i.id) or {}).get("source") == "no answer"]
    if items and len(lost) == len(items):
        print("  [%s] every answer was `no answer` (the request never got "
              "through); re-sending it unchanged" % phase)
        time.sleep(10)
        picks, why = proposer.choose(items, ctx, round_no,
                                     "%s.retry" % phase)
    return picks, why


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", required=True)
    p.add_argument("--marks", required=True)
    p.add_argument("--sites", default=None)
    p.add_argument("--site-set", default=None)
    p.add_argument("--baseline-dir", default=None)
    p.add_argument("--vocab", default="v3",
                   choices=("v1", "v2", "v3", "v4"))
    p.add_argument("--readout", default="forced_top1",
                   choices=("forced_top1", "argmax"))
    p.add_argument("--source-comments", default="strip",
                   choices=("strip", "keep"))
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--log-dir", required=True,
                   help="where the JSONL and the readable log are written")
    p.add_argument("--run-id", required=True)
    p.add_argument("--scratch", default=None,
                   help="a directory the driver may write its own artifacts "
                        "to (nothing of value lands there)")
    p.add_argument("--summary", default=None,
                   help="write the per-site answers as JSON here")
    a = p.parse_args()

    scratch = a.scratch or os.path.join(
        S.REPO, "artifacts", "_oneshot-%s" % a.run_id)
    args = _Args(target=a.target, marks=a.marks, sites=a.sites,
                 site_set=a.site_set, baseline_dir=a.baseline_dir,
                 vocab=a.vocab, readout=a.readout,
                 source_comments=a.source_comments, out=scratch,
                 run_id=a.run_id)
    search, cfg = setup(args)
    print("[setup] %s, vocabulary %s, state format %s, source comments %s"
          % (a.target, V.VOCAB_VERSION, S.STATE_FORMAT_VERSION,
             a.source_comments))
    print("[setup] %d function sites, %d loop sites"
          % (len(search.fn_list), len(search.base_loops)))

    client = S.JevClient(cfg["jev"], os.path.abspath(a.log_dir), a.run_id,
                         source_comments=a.source_comments)
    proposer = S.JevProposer(client, cfg["jev"], search.knobs,
                             int(cfg["search"]["max_state_chars"]),
                             readout=a.readout, explore=0)

    items_a = search.fn_list + search.build_list
    items_b = search.base_loops
    t0 = time.time()
    out = {"run_id": a.run_id, "target": a.target,
           "vocab_version": V.VOCAB_VERSION,
           "state_format": S.STATE_FORMAT_VERSION,
           "source_comments": a.source_comments, "readout": a.readout,
           "repeats": a.repeats, "repeats_data": []}
    for r in range(1, a.repeats + 1):
        print("\n=== repeat %d ===" % r)
        rec = {"repeat": r}
        # The round-1 strings of a real run, not `--print-state`'s preview:
        # phase A does not show the line at all, phase B shows `none`
        # because this pass builds nothing (see the module docstring).
        ctx_a = search.ctx({"arm": None})
        picks_a, why_a = ask_phase(proposer, items_a, ctx_a, r, "A")
        rec["A"] = {"picks": picks_a, "why": why_a,
                    "readout": ctx_a.get("readout")}
        ctx_b = search.ctx({"arm": None, "fn_choice_text": "none"})
        picks_b, why_b = ask_phase(proposer, items_b, ctx_b, r, "B")
        rec["B"] = {"picks": picks_b, "why": why_b,
                    "readout": ctx_b.get("readout")}
        out["repeats_data"].append(rec)
        for phase, items, picks, why in (("A", items_a, picks_a, why_a),
                                         ("B", items_b, picks_b, why_b)):
            for it in items:
                w = why.get(it.id) or {}
                pr = w.get("probabilities") or {}
                print("  %s %-52s %-16s P=%.2f conf=%s"
                      % (phase, it.id, picks.get(it.id),
                         float(pr.get(picks.get(it.id)) or 0.0),
                         w.get("confidence")))
    wall = time.time() - t0
    client.write_totals(wall)
    out["totals"] = dict(client.totals)
    out["wall_s"] = round(wall, 1)
    if a.summary:
        os.makedirs(os.path.dirname(os.path.abspath(a.summary)), exist_ok=True)
        with open(a.summary, "w") as f:
            json.dump(out, f, indent=1, default=str)
        print("\n[summary] %s" % a.summary)
    print("[api] %d requests, %d questions, %d/%d tokens, %.1f s"
          % (client.totals["requests"], client.totals["questions"],
             client.totals["input_tokens"], client.totals["output_tokens"],
             wall))
    return 0


if __name__ == "__main__":
    sys.exit(main())
