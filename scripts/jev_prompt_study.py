#!/usr/bin/env python3
"""Run the Jev prompt study: every variant of `jev_state_variants.py`, N times.

No build, no benchmark --- this is the Jev API only (decisions 66-68). The
gateway returns HTTP 503 in bursts, so every request is retried with
exponential backoff and the attempt count is recorded; a request that never
succeeds is written to the log as a failure and the analysis reports the
number of cells it actually obtained.

The run is resumable: a (variant, repeat, tag) that already has a successful
line in the log is skipped, so the script can be re-run until the gateway has
answered everything.

    scripts/jev_prompt_study.py --out docs/experiments/jev-prompt-study \
        --repeats 3

Two files are written next to each other:

    requests.jsonl   one line per distinct request body, keyed by sha256
    log.jsonl        one line per (variant, repeat, tag): the sha256 of the
                     request, the verbatim response, http status, attempt
                     count, latency, tokens and cost

The API key comes from `AI_GATEWAY_API_KEY` in the environment or from
`.env`, and is never written to either file.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import jev_state_variants as V  # noqa: E402

URL = "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
BACKOFF = [2, 4, 8, 16, 30, 30, 45, 60]


def api_key():
    k = os.environ.get("AI_GATEWAY_API_KEY")
    if k:
        return k.strip()
    with open(os.path.join(REPO, ".env")) as f:
        for line in f:
            if line.startswith("AI_GATEWAY_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("no AI_GATEWAY_API_KEY")


def post(body, key, timeout=90):
    """-> (status, parsed_or_error_text, latency_ms, attempts)"""
    data = json.dumps(body).encode()
    attempts = 0
    last = (None, "no attempt", 0.0)
    for i in range(len(BACKOFF) + 1):
        attempts += 1
        req = urllib.request.Request(
            URL, data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            ms = (time.time() - t0) * 1000.0
            return 200, json.loads(raw), ms, attempts
        except urllib.error.HTTPError as e:
            ms = (time.time() - t0) * 1000.0
            txt = e.read()[:400].decode("utf-8", "replace")
            last = (e.code, txt, ms)
            if e.code not in (429, 500, 502, 503, 504):
                return e.code, txt, ms, attempts
        except Exception as e:  # timeouts, resets
            ms = (time.time() - t0) * 1000.0
            last = (None, "%s: %s" % (type(e).__name__, e), ms)
        if i < len(BACKOFF):
            time.sleep(BACKOFF[i])
    return last[0], last[1], last[2], attempts


def sha(body):
    return hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def load_done(path):
    done = set()
    if not os.path.exists(path):
        return done
    for line in open(path):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("http_status") == 200:
            done.add((r["variant"], r["repeat"], r["tag"]))
    return done


def answers_of(resp):
    return (resp or {}).get("answers", {})


def top_choice(ans):
    if ans.get("type") == "choice":
        return ans.get("choice")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "docs", "experiments", "jev-prompt-study"))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--variants", default=None,
                    help="comma-separated subset, default all")
    ap.add_argument("--jsonl", default=V.DEFAULT_JSONL)
    ap.add_argument("--gap", type=float, default=1.0,
                    help="seconds between successful requests")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    log_path = os.path.join(a.out, "log.jsonl")
    req_path = os.path.join(a.out, "requests.jsonl")
    done = load_done(log_path)
    seen_req = set()
    if os.path.exists(req_path):
        for line in open(req_path):
            try:
                seen_req.add(json.loads(line)["sha"])
            except ValueError:
                pass

    key = api_key()
    material = V.load_material(a.jsonl)
    variants = (a.variants.split(",") if a.variants else V.VARIANTS)

    logf = open(log_path, "a")
    reqf = open(req_path, "a")

    def send(variant, repeat, tag, req, meta, stage=None):
        h = sha(req)
        if h not in seen_req:
            reqf.write(json.dumps(
                {"sha": h, "variant": variant, "tag": tag, "stage": stage,
                 "site_map": meta, "request": req}, sort_keys=True) + "\n")
            reqf.flush()
            seen_req.add(h)
        status, resp, ms, attempts = post(req, key)
        ok = status == 200
        usage = (resp.get("usage") if ok else {}) or {}
        gw = ((resp.get("provider_metadata") or {}).get("gateway")
              if ok else {}) or {}
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "study": V.STUDY_VERSION, "variant": variant, "repeat": repeat,
            "tag": tag, "stage": stage, "request_sha": h, "site_map": meta,
            "http_status": status, "attempts": attempts,
            "latency_ms": round(ms, 1),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cost_usd": gw.get("cost"), "market_cost_usd": gw.get("marketCost"),
            "response": resp if ok else None,
            "error": None if ok else str(resp)[:400],
        }
        logf.write(json.dumps(rec, sort_keys=True) + "\n")
        logf.flush()
        print("%-5s r%d %-40s %s attempts=%d %.0fms"
              % (variant, repeat, tag[:40], status, attempts, ms), flush=True)
        if ok:
            time.sleep(a.gap)
        return rec

    for variant in variants:
        for repeat in range(1, a.repeats + 1):
            if variant == "V12":
                # stage 1: families. stage 2 depends on stage 1's answers, so
                # it is a separate request (never a dependency inside one).
                fams = {}
                for tag, req, meta in V.requests_for(variant, material,
                                                     stage=1):
                    k = (variant, repeat, tag)
                    rec = None
                    if k in done:
                        for line in open(log_path):
                            r = json.loads(line)
                            if (r["variant"], r["repeat"], r["tag"]) == k \
                                    and r["http_status"] == 200:
                                rec = r
                    if rec is None:
                        rec = send(variant, repeat, tag, req, meta, stage=1)
                    for q, ans in answers_of(rec.get("response")).items():
                        sid = rec["site_map"].get(q)
                        c = top_choice(ans)
                        if sid and c:
                            fams[sid] = c
                if not fams:
                    continue
                for tag, req, meta in V.requests_for(variant, material,
                                                     stage=2, families=fams):
                    if (variant, repeat, tag) in done:
                        continue
                    send(variant, repeat, tag, req, meta, stage=2)
                continue

            for tag, req, meta in V.requests_for(variant, material):
                if (variant, repeat, tag) in done:
                    print("skip %s r%d %s" % (variant, repeat, tag[:40]))
                    continue
                send(variant, repeat, tag, req, meta)

    logf.close()
    reqf.close()


if __name__ == "__main__":
    main()
