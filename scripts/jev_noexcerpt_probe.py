#!/usr/bin/env python3
"""State without source excerpts: request size, landing rate, L13 check.

results.md 180 (pre-registration and results), decision 110. API only:
nothing is built and nothing is timed. The driver's own objects render every
request (`scripts/jev_search.py`, `--source-excerpt full|none`), from the
frozen baseline dumps prompt study 2 used.

Subcommands:

  render   write the six probe bodies per condition (hintbench v5, zopfli
           v6; phase A, phase B, the phase-B exploration request, as
           `--print-state` renders them) and the L13 identity check: the
           driver's `none` state for study 2's v6 round-1 requests against
           the L13 request bodies study 2 actually sent
  probe    send each probe body 10 times, full/none interleaved, 3 s apart,
           ONE HTTP attempt per send (no retry), log JSONL + .log
  choice   send the `none` phase-A/B requests (study 2's v6 rendering) as
           real Choice questions, 3 repeats per target, with the driver's
           retry policy, logged in study 2's layout (phase tags `L13.A`,
           `L13.B`) so that `jev_prompt_study2.py report --run-prefix nx`
           scores them exactly as study 2 did
  table    the probe table (bytes, landed/sends, mean sends-to-land)
"""

import argparse
import contextlib
import gzip
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jev_search as S          # noqa: E402
import jev_vocab as V           # noqa: E402
import jev_prompt_study2 as P2  # noqa: E402

REPO = S.REPO
LOG_DIR = os.path.join(REPO, "docs", "experiments", "jev-prompt-study-2",
                       "noexcerpt")
WORK = os.path.join(REPO, "artifacts", "jev-noexcerpt-probe")
BODIES = os.path.join(WORK, "bodies")
PROBE_TARGETS = {"hintbench": "v5", "zopfli": "v6"}
CONDS = ("full", "none")
KINDS = ("A", "B", "explore")
N_SENDS = 10
GAP_S = 3.0


def setup(target, vocab, excerpt):
    spec = P2.TARGETS[target]
    os.environ["TARGET"] = target
    scratch = os.path.join(WORK, "_driver-%s-%s-%s" % (target, vocab, excerpt))
    args = P2._Args(target=target, marks=os.path.join(REPO, spec["marks"]),
                    sites=os.path.join(REPO, spec["sites"]),
                    site_set=spec["site_set"],
                    baseline_dir=os.path.join(REPO, spec["baseline_dir"]),
                    out=scratch, run_id="nx-setup-%s" % target, vocab=vocab,
                    explore=2, source_excerpt=excerpt)
    cfg = S.load_config(args.config)
    search = S.Search(args, cfg)
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        rc = search.run()
    if rc != 0:
        sys.exit("driver setup failed:\n" + buf.getvalue())
    return search, cfg


def body_of(state, questions, cfg):
    return {"model": cfg["jev"]["model"], "state": state,
            "questions": questions}


def print_state_bodies(search, cfg):
    """A, B and the phase-B exploration request, exactly as --print-state
    renders them (round 1, preview ctx, KEEP_DEFAULT assumed for explore)."""
    out = {}
    for phase, items in (("A", search.fn_list + search.build_list),
                         ("B", search.base_loops)):
        ctx = search.ctx({"arm": None, "loop_items": search.base_loops,
                          "fn_choice_text": "(none: this is a preview)"})
        q, sm = S.questions_for(items, ctx, search.knobs)
        st = S.state_header(ctx, len(items)) + "".join(
            S.state_section(it, ctx) for it in items)
        out[phase] = (body_of(st, q, cfg), sm)
        if phase == "B":
            elig = {}
            pairs = S.exploration_sites(items, {}, ctx, search.knobs, 2, 0,
                                        record=elig)
            eq, esm = S.exploration_questions(pairs, ctx, elig.get("meta"))
            est = S.state_header(ctx, len(pairs)) + "".join(
                S.state_section(it, ctx) for it, _c in pairs)
            out["explore"] = (body_of(est, eq, cfg), esm)
    return out


def l13_logged(target):
    """Study 2's L13 request bodies, repeat 1, by phase."""
    path = os.path.join(P2.DOC_DIR, "ps2-%s.jsonl.gz" % target)
    got = {}
    for line in gzip.open(path, "rt"):
        r = json.loads(line)
        if r["round"] == 1 and r["phase"] in ("L13.A", "L13.B") \
                and not r.get("exhausted"):
            got.setdefault(r["phase"][-1], r["request"])
    return got


def cmd_render(_a):
    assert P2.SOURCE_OMITTED == S.SOURCE_OMITTED, "L13 placeholder drifted"
    os.makedirs(BODIES, exist_ok=True)
    sizes = {}
    for target, vocab in PROBE_TARGETS.items():
        for cond in CONDS:
            search, cfg = setup(target, vocab, cond)
            fmt = S.STATE_FORMAT_VERSION
            for kind, (body, sm) in print_state_bodies(search, cfg).items():
                name = "%s-%s-%s" % (target, kind, cond)
                payload = json.dumps(body).encode()
                with open(os.path.join(BODIES, name + ".json"), "w") as f:
                    json.dump({"body": body, "site_map": sm,
                               "vocab_version": V.VOCAB_VERSION,
                               "state_format": fmt, "source_excerpt": cond},
                              f)
                sizes[name] = {"request_bytes": len(payload),
                               "state_chars": len(body["state"]),
                               "questions": len(body["questions"]),
                               "state_format": fmt}
    for name in sorted(sizes):
        s = sizes[name]
        print("%-24s %8d bytes  state %7d chars  %2d q  %s"
              % (name, s["request_bytes"], s["state_chars"], s["questions"],
                 s["state_format"]))
    with open(os.path.join(WORK, "sizes.json"), "w") as f:
        json.dump(sizes, f, indent=1)
    # L13 identity: study 2's rendering (v6, its phase ctx), driver `none`.
    ident = {}
    for target in PROBE_TARGETS:
        search, cfg = setup(target, "v6", "none")
        logged = l13_logged(target)
        for phase in "AB":
            req = P2.build_requests(search, "B0", phase)
            assert len(req) == 1
            mine = req[0]["state"].splitlines()
            theirs = logged[phase]["state"].splitlines()
            diff = [(i, a, b) for i, (a, b) in enumerate(zip(mine, theirs))
                    if a != b]
            same_q = req[0]["questions"] == logged[phase]["questions"]
            ident["%s.%s" % (target, phase)] = {
                "lines_mine": len(mine), "lines_l13": len(theirs),
                "differing_lines": [{"line": i + 1, "driver": a, "l13": b}
                                    for i, a, b in diff],
                "questions_identical": same_q}
            print("[L13 identity] %s %s: %d vs %d lines, %d differing, "
                  "questions identical %s"
                  % (target, phase, len(mine), len(theirs), len(diff), same_q))
            for i, a, b in diff:
                print("    line %d\n      driver: %s\n      L13:    %s"
                      % (i + 1, a, b))
    with open(os.path.join(WORK, "l13-identity.json"), "w") as f:
        json.dump(ident, f, indent=1)


def load_body(name):
    return json.load(open(os.path.join(BODIES, name + ".json")))


def cmd_probe(a):
    cfg = S.load_config(os.path.join(REPO, "jev-opt.toml"))
    jc = dict(cfg["jev"])
    jc["retries"] = 1            # one HTTP attempt per send: honest status
    os.makedirs(LOG_DIR, exist_ok=True)
    client = S.JevClient(jc, LOG_DIR, a.run_id, source_comments="strip")
    S.RETRY_JITTER = 0.0
    with open(client.log_path, "a") as f:
        f.write("# results.md 180 probe: %d sends per body, %.0f s gap, one "
                "HTTP attempt per send, full/none interleaved (full first "
                "on odd sends)\n" % (N_SENDS, GAP_S))
    t0 = time.time()
    for rep in range(1, N_SENDS + 1):
        for target, vocab in PROBE_TARGETS.items():
            for kind in KINDS:
                order = CONDS if rep % 2 else tuple(reversed(CONDS))
                for cond in order:
                    b = load_body("%s-%s-%s" % (target, kind, cond))
                    V.set_version(vocab)
                    S.STATE_FORMAT_VERSION = b["state_format"]
                    client.source_excerpt = cond
                    ans, ln = client.ask(b["body"]["state"],
                                         b["body"]["questions"], rep,
                                         "%s.%s.%s" % (target, kind, cond),
                                         b["site_map"])
                    print("[probe s%02d] %-9s %-7s %-4s -> %s (line %d)"
                          % (rep, target, kind, cond,
                             "landed" if ans is not None else "not landed",
                             ln), flush=True)
                    time.sleep(GAP_S)
    client.write_totals(time.time() - t0)


def cmd_choice(a):
    for target in a.targets:
        search, cfg = setup(target, "v6", "none")
        assert S.STATE_FORMAT_VERSION == "state-v6.0-noexcerpt-2026-09-25"
        os.makedirs(LOG_DIR, exist_ok=True)
        S.RETRY_JITTER = 0.0
        client = S.JevClient(dict(cfg["jev"]), LOG_DIR, "nx-%s" % target,
                             source_comments="strip", source_excerpt="none")
        t0 = time.time()
        for rep in range(1, a.repeats + 1):
            for phase in "AB":
                for req in P2.build_requests(search, "B0", phase):
                    ans, ln = P2.send(client, req, rep, "L13")
                    print("[choice %s r%d] %s -> %s (line %d)"
                          % (target, rep, phase,
                             "ok" if ans is not None else "LOST", ln),
                          flush=True)
        client.write_totals(time.time() - t0)


def cmd_table(a):
    path = os.path.join(LOG_DIR, a.run_id + ".jsonl")
    opener = open if os.path.isfile(path) else gzip.open
    path = path if os.path.isfile(path) else path + ".gz"
    recs = [json.loads(l) for l in opener(path, "rt")]
    print("| target | body | source excerpt | request bytes | landed / sends "
          "| mean sends to land | statuses |")
    print("|---|---|---|--:|--:|--:|---|")
    for target in PROBE_TARGETS:
        for kind in KINDS:
            for cond in CONDS:
                rs = [r for r in recs
                      if r["phase"] == "%s.%s.%s" % (target, kind, cond)]
                if not rs:
                    continue
                n_land = sum(1 for r in rs if not r["exhausted"])
                st = {}
                for r in rs:
                    st[str(r["http_status"])] = st.get(
                        str(r["http_status"]), 0) + 1
                print("| %s | %s | %s | %d | %d / %d | %s | %s |"
                      % (target, kind, cond, rs[0]["request_bytes"], n_land,
                         len(rs), ("%.2f" % (len(rs) / n_land)) if n_land
                         else "inf",
                         ", ".join("%s x%d" % kv for kv in sorted(st.items()))))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("render")
    pr = sub.add_parser("probe")
    pr.add_argument("--run-id", default="probe")
    ch = sub.add_parser("choice")
    ch.add_argument("--targets", nargs="+", default=list(PROBE_TARGETS))
    ch.add_argument("--repeats", type=int, default=3)
    tb = sub.add_parser("table")
    tb.add_argument("--run-id", default="probe")
    a = p.parse_args()
    {"render": cmd_render, "probe": cmd_probe, "choice": cmd_choice,
     "table": cmd_table}[a.cmd](a)


if __name__ == "__main__":
    main()
