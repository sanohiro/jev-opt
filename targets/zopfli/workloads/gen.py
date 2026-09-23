#!/usr/bin/env python3
"""Generate zopfli's deterministic training and holdout inputs.

Python 3 standard library only, fixed seeds, no network. The same command
always produces byte-identical files, so the inputs are regenerable and are
not committed (see .gitignore); `--check` prints their sha256 so results.md
can pin them.

Three kinds of input, chosen to give the compressor three different
characters (SPEC.ja.md 11 freezes the case set per target before a holdout):

  text    word-salad from a fixed vocabulary with heavy phrase repetition and
          a Zipf-ish word distribution --- long LZ77 matches, deep hash chains.
  binary  pseudo-random bytes drawn from a 16-symbol alphabet --- almost no
          long matches, so the LZ77 search runs its full window and the
          Huffman side does the work.
  json    structured records with repeated keys and short values --- many
          medium-length matches at regular strides.

Training and holdout differ only in seed (and therefore in content), never in
kind or size, so the holdout is the same measurement on data the profile has
never seen. SPEC.ja.md 10: "the holdout cases are never used to produce the
profdata".

A third split, `search`, is the input set for the Jev search loop itself
(decision 98), distinct from both: it is not fed to PGO (the `train-*`
inputs still produce `merged.profdata`, unchanged) and it is not the
one-time holdout transfer check. `search-*` is smaller (896 KiB) than
`train-*`/`hold-*` (1400 KiB): at that size each search input is under
1e6 bytes, so it compresses as a single zopfli master block, while the
1,433,600-byte holdout inputs span two master blocks. A hint that wins on
the single-block search inputs and still wins on the two-block holdout
inputs is evidence the win transfers across that boundary, not an artifact
of it.
"""

import argparse
import hashlib
import os
import random
import sys

# Seeds are part of the artifact: changing one changes the inputs.
SEEDS = {
    ("train", "text"): 20260921001,
    ("train", "binary"): 20260921002,
    ("train", "json"): 20260921003,
    ("hold", "text"): 20260921101,
    ("hold", "binary"): 20260921102,
    ("hold", "json"): 20260921103,
    ("search", "text"): 20260923201,
    ("search", "binary"): 20260923202,
    ("search", "json"): 20260923203,
}

# Target sizes, tuned so that one zopfli run takes >= 1 s on the PGO baseline
# (SPEC.ja.md 10 wants the case long enough that process startup is noise).
# `search` is smaller by design (see module docstring): one master block
# instead of two, so it is a cheaper, faster loop for the search itself.
SIZES = {"text": 1400 * 1024, "binary": 1400 * 1024, "json": 1400 * 1024}
SEARCH_SIZE = 896 * 1024


def _size_for(split, kind):
    return SEARCH_SIZE if split == "search" else SIZES[kind]

LOWER = "abcdefghijklmnopqrstuvwxyz"


def gen_text(rng, size):
    vocab = ["".join(rng.choice(LOWER) for _ in range(rng.randint(2, 11)))
             for _ in range(512)]
    # A Zipf-ish weighting: index i is drawn about 1/(i+1) as often as index 0.
    weights = [1.0 / (i + 1) for i in range(len(vocab))]
    # Fixed phrases give the matcher something long to find.
    phrases = [" ".join(rng.choices(vocab, weights, k=rng.randint(4, 12)))
               for _ in range(64)]
    out = []
    n = 0
    while n < size:
        if rng.random() < 0.25:
            chunk = rng.choice(phrases)
        else:
            chunk = " ".join(rng.choices(vocab, weights, k=rng.randint(3, 15)))
        if rng.random() < 0.08:
            chunk += "\n"
        out.append(chunk)
        n += len(chunk) + 1
    return (" ".join(out)).encode("ascii")[:size]


def gen_binary(rng, size):
    # 16 distinct byte values, uniform: entropy 4 bits/byte, and long matches
    # are vanishingly rare, so this is the opposite end from `text`.
    alphabet = bytes(sorted(rng.sample(range(256), 16)))
    return bytes(rng.choice(alphabet) for _ in range(size))


def gen_json(rng, size):
    keys = ["id", "name", "kind", "value", "ts", "tags", "ok", "note"]
    kinds = ["alpha", "beta", "gamma", "delta", "epsilon"]
    tags = ["red", "green", "blue", "fast", "slow", "new", "old"]
    out = ['{"records":[']
    n = len(out[0])
    i = 0
    while n < size:
        rec = (
            '{"%s":%d,"%s":"%s%04d","%s":"%s","%s":%d.%02d,"%s":%d,'
            '"%s":["%s","%s"],"%s":%s,"%s":"%s"}'
            % (keys[0], i,
               keys[1], rng.choice(kinds), rng.randrange(10000),
               keys[2], rng.choice(kinds),
               keys[3], rng.randrange(1000), rng.randrange(100),
               keys[4], 1700000000 + rng.randrange(10_000_000),
               keys[5], rng.choice(tags), rng.choice(tags),
               keys[6], "true" if rng.random() < 0.7 else "false",
               keys[7], "".join(rng.choice(LOWER) for _ in range(rng.randint(4, 20))))
        )
        sep = "," if i else ""
        out.append(sep + rec)
        n += len(rec) + len(sep)
        i += 1
    out.append("]}")
    return "".join(out).encode("ascii")[:size]


GENERATORS = {"text": gen_text, "binary": gen_binary, "json": gen_json}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out-dir", default=os.path.dirname(os.path.abspath(__file__)))
    p.add_argument("--check", action="store_true",
                   help="only print the sha256 of the files that exist")
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    for (split, kind), seed in sorted(SEEDS.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        path = os.path.join(args.out_dir, f"{split}-{kind}.dat")
        if not args.check:
            data = GENERATORS[kind](random.Random(seed), _size_for(split, kind))
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
