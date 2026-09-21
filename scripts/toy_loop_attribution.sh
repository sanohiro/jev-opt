#!/usr/bin/env bash
#
# Attribute machine code in the toy binary back to the four toyloops functions.
#
# Why this exists: with fat LTO the only remark mechanism that survives on the
# pinned nightly is LLVM's plain-text stderr remarks, and those carry a
# DebugLoc but no function name. After inlining, the DebugLoc of a
# `bytes.iter()...` loop points into core's slice iterator, where std's own
# loops also live, so the remark text alone cannot say which loop is which.
#
# This script walks every instruction of `toy::main`, resolves its full inline
# chain with addr2line, and buckets the instructions by which toyloops function
# the chain names. That is a direct, per-loop answer to "vectorized or not, and
# how wide", independent of the remarks. results.md quotes both.
#
# Usage: scripts/toy_loop_attribution.sh [path-to-toy-binary]
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
BIN="${1:-$REPO/target-toy-pgo-use/$TRIPLE/release/toy}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

[ -f "$BIN" ] || { echo "no such binary: $BIN" >&2; exit 1; }

# `main` is where everything ends up after fat LTO inlining.
read -r MAIN_ADDR MAIN_SIZE < <(nm -S "$BIN" | awk '/_3toy4main$/ {print $1, $2}')
[ -n "${MAIN_ADDR:-}" ] || { echo "toy::main not found in $BIN" >&2; exit 1; }
START=$((16#$MAIN_ADDR))
STOP=$((START + 16#$MAIN_SIZE))
echo "binary:   $BIN"
printf 'main:     0x%x .. 0x%x (%d bytes)\n' "$START" "$STOP" $((STOP - START))

objcopy --version >/dev/null
objdump -d --start-address="$START" --stop-address="$STOP" --no-show-raw-insn "$BIN" \
  | grep -E '^[[:space:]]+[0-9a-f]+:' | sed 's/^[[:space:]]*//' > "$WORK/main.dis"
cut -d: -f1 "$WORK/main.dis" > "$WORK/main.addrs"
# -p keeps one frame per line; inlined frames are the " (inlined by)" lines,
# which is what makes the per-address grouping unambiguous.
addr2line -i -f -p -e "$BIN" @"$WORK/main.addrs" > "$WORK/main.a2lp"

python3 - "$WORK" <<'PY'
import collections, re, sys

work = sys.argv[1]
dis = [l.rstrip("\n") for l in open(work + "/main.dis")]
groups, cur = [], None
for line in open(work + "/main.a2lp"):
    line = line.rstrip("\n")
    if line.startswith(" (inlined by)"):
        cur.append(line.strip())
    else:
        cur = [line]
        groups.append(cur)
if len(groups) != len(dis):
    sys.exit(f"frame/instruction mismatch: {len(groups)} vs {len(dis)}")

targets = ["count_quotes", "find_special", "sum_indexed", "dot_f64"]
buckets = collections.defaultdict(list)
for insn, chain in zip(dis, groups):
    joined = " | ".join(chain)
    for t in targets:
        if t in joined:
            buckets[t].append((insn, chain[0]))
            break

vec = re.compile(r"\b[xyz]mm\d+\b")
for t in targets:
    rows = buckets[t]
    mnemonics = collections.Counter()
    nvec = 0
    for insn, _ in rows:
        parts = insn.split("\t")
        mnemonics[parts[1].split()[0] if len(parts) > 1 else "?"] += 1
        if vec.search(insn):
            nvec += 1
    print(f"### {t}: {len(rows)} instructions, {nvec} use vector registers")
    print("    mnemonics: " + ", ".join(f"{k}x{v}" for k, v in mnemonics.most_common(12)))
    leaves = collections.Counter(leaf.split(" at ")[-1] for _, leaf in rows)
    print("    leaf locations: " + ", ".join(f"{k} x{v}" for k, v in leaves.most_common(4)))
    distinct = sorted({insn.split("\t")[1].strip() for insn, _ in rows if vec.search(insn)})
    for d in distinct:
        print("      vec: " + d)
    print()
PY
