#!/usr/bin/env python3
"""Generate jaq's deterministic training and holdout inputs.

Python 3 standard library only, fixed seeds, no network. The same command
always produces byte-identical files, so the inputs are regenerable and are
not committed (see .gitignore); `--check` prints their sha256 so results.md
can pin them.

Three kinds of input, each paired with the article workload whose filter it
feeds (SPEC.ja.md 11 freezes the case set per target before a holdout):

  objects  one large JSON array of records with nested fields. Feeds the
           *object search* filter `.[] | select(.k == "v") | .id`, which is
           the interpreter walking every element, comparing a string field
           and projecting one number out. Parsing dominates, the filter adds
           a `select` per element.
  strings  one large JSON array of `{"id":N,"name":"..."}` records whose
           `name` is a long string full of escapes (`\\"`, `\\\\`, `\\n`,
           `\\t`, `\\uXXXX`) and raw multi-byte UTF-8. Feeds the *array and
           string processing* filter
           `[.[] | .name | ascii_downcase | length] | add`, so every string
           is unescaped, lowercased and measured.
  ndjson   many small independent documents, one per line. Feeds the
           *read/write* filter `.` with `-c`, i.e. parse and re-serialise
           every document, which is the closest thing to a pure I/O-shaped
           jq invocation.

Training and holdout differ only in seed (and therefore in content), never in
kind or size, so the holdout is the same measurement on data the profile has
never seen. SPEC.ja.md 10: "the holdout cases are never used to produce the
profdata".
"""

import argparse
import hashlib
import os
import random
import sys

# Seeds are part of the artifact: changing one changes the inputs.
SEEDS = {
    ("train", "objects"): 20260921201,
    ("train", "strings"): 20260921202,
    ("train", "ndjson"): 20260921203,
    ("hold", "objects"): 20260921301,
    ("hold", "strings"): 20260921302,
    ("hold", "ndjson"): 20260921303,
}

# Target sizes in bytes, and how many times each case names its file on the
# jaq command line (`jaq FILTER f.json f.json ...`, which parses and runs the
# filter over each file in turn).
#
# The split matters and was measured. A single 72 MiB array made every run
# take about 1.2 s, which clears SPEC.ja.md 10's floor, but jaq materialises
# the whole array as `Rc` values --- 1.2 GiB resident --- and the wall time
# then became **bimodal**, alternating between about 930 ms and about 1280 ms
# on the same binary and the same input (results.md "Stage 0 (jaq)" section
# 55). A/A on that shape gave a 13% half-width and a 26% MDE, i.e. no
# measurement at all. Repeating a smaller file instead keeps the same total
# work and the same filter, caps the resident set at a few hundred MiB, and
# brings the run-to-run spread back to about 1.5%.
SIZES = {
    "objects": 20 * 1024 * 1024,
    "strings": 24 * 1024 * 1024,
    "ndjson": 24 * 1024 * 1024,
}

# Repetitions per timed run. Frozen with the case set (SPEC.ja.md 11); the
# repeat count is part of the case, and scripts/target_common.sh spells the
# argv out.
REPEATS = {"objects": 4, "strings": 8, "ndjson": 2}

LOWER = "abcdefghijklmnopqrstuvwxyz"
UPPER = LOWER.upper()

# The `k` field the object-search filter selects on. Four values, so the
# filter keeps about a quarter of the records and the `select` is neither
# always-true nor always-false.
K_VALUES = ["u", "v", "w", "x"]

KINDS = ["alpha", "beta", "gamma", "delta", "epsilon"]
TAGS = ["red", "green", "blue", "fast", "slow", "new", "old"]

# Escape sequences and raw UTF-8 that the string kind mixes into `name`.
# Written literally into the JSON text: the first five are two-character
# escapes the parser must decode, `\uXXXX` is the six-character form, and the
# rest are raw multi-byte code points.
ESCAPES = ['\\"', "\\\\", "\\n", "\\t", "\\r", "\\/", "\\u00e9", "\\u65e5",
           "\\u0416", "\\ud83d\\ude00"]
RAW_UTF8 = ["é", "ü", "ß", "日本語", "Привет", "αβγ", "—", "→", "✓"]


def word(rng, lo=3, hi=12):
    return "".join(rng.choice(LOWER) for _ in range(rng.randint(lo, hi)))


def gen_objects(rng, size):
    """A JSON array of records with nested fields, pretty much a log dump."""
    vocab = [word(rng) for _ in range(256)]
    names = [rng.choice(UPPER) + word(rng) for _ in range(128)]
    out = ["["]
    n = 1
    i = 0
    while n < size:
        rec = (
            '{"id":%d,"k":"%s","name":"%s","kind":"%s",'
            '"nested":{"a":%d,"b":[%d,%d,%d],"c":{"d":"%s","e":%s}},'
            '"tags":["%s","%s"],"score":%d.%02d,"ts":%d,"note":"%s"}'
            % (i,
               rng.choice(K_VALUES),
               rng.choice(names),
               rng.choice(KINDS),
               rng.randrange(100000),
               rng.randrange(1000), rng.randrange(1000), rng.randrange(1000),
               rng.choice(vocab),
               "true" if rng.random() < 0.6 else "false",
               rng.choice(TAGS), rng.choice(TAGS),
               rng.randrange(1000), rng.randrange(100),
               1700000000 + rng.randrange(10_000_000),
               " ".join(rng.choice(vocab) for _ in range(rng.randint(2, 6))))
        )
        sep = ",\n" if i else "\n"
        out.append(sep + rec)
        n += len(rec) + len(sep)
        i += 1
    out.append("\n]\n")
    return "".join(out).encode("utf-8")


def gen_strings(rng, size):
    """A JSON array of {"id":N,"name":"<long escaped/unicode string>"}."""
    vocab = [word(rng, 3, 14) for _ in range(256)]
    out = ["["]
    n = 1
    i = 0
    while n < size:
        parts = []
        for _ in range(rng.randint(12, 40)):
            r = rng.random()
            if r < 0.10:
                parts.append(rng.choice(ESCAPES))
            elif r < 0.20:
                parts.append(rng.choice(RAW_UTF8))
            elif r < 0.35:
                # Mixed case, so ascii_downcase has work to do.
                w = rng.choice(vocab)
                parts.append(w.capitalize() if rng.random() < 0.5 else w.upper())
            else:
                parts.append(rng.choice(vocab))
        name = " ".join(parts)
        rec = '{"id":%d,"name":"%s"}' % (i, name)
        sep = ",\n" if i else "\n"
        out.append(sep + rec)
        n += len(rec.encode("utf-8")) + len(sep)
        i += 1
    out.append("\n]\n")
    return "".join(out).encode("utf-8")


def gen_ndjson(rng, size):
    """Many small independent documents, one per line."""
    vocab = [word(rng) for _ in range(128)]
    out = []
    n = 0
    i = 0
    while n < size:
        rec = (
            '{"id":%d,"k":"%s","name":"%s","v":%d,"ok":%s,"xs":[%d,%d],"s":"%s"}\n'
            % (i,
               rng.choice(K_VALUES),
               rng.choice(vocab),
               rng.randrange(100000),
               "true" if rng.random() < 0.5 else "false",
               rng.randrange(1000), rng.randrange(1000),
               rng.choice(vocab))
        )
        out.append(rec)
        n += len(rec)
        i += 1
    return "".join(out).encode("utf-8")


GENERATORS = {"objects": gen_objects, "strings": gen_strings,
              "ndjson": gen_ndjson}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out-dir", default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument("--check", action="store_true",
                   help="only print the sha256 of the files that exist")
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    for (split, kind), seed in sorted(SEEDS.items(),
                                      key=lambda kv: (kv[0][0], kv[0][1])):
        path = os.path.join(args.out_dir, f"{split}-{kind}.json")
        if not args.check:
            data = GENERATORS[kind](random.Random(seed), SIZES[kind])
            with open(path, "wb") as f:
                f.write(data)
        if not os.path.isfile(path):
            print(f"missing: {path}", file=sys.stderr)
            continue
        with open(path, "rb") as f:
            blob = f.read()
        print(f"{hashlib.sha256(blob).hexdigest()}  {len(blob):>9}  "
              f"{os.path.basename(path)}  seed={seed}")


if __name__ == "__main__":
    main()
