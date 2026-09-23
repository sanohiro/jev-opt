# hintbench k5 mode: A/A-only panel study

Pre-registration `results.md` §160, results §161, decision 97.
Artifacts: `artifacts/hintbench-aa-study/{p1,p2,p3,p4,p5a,p5b,p5c}/`
(`samples.json`, `stats.json`, `stats.md`, `paths.tsv`, `panel.txt` for p1/p4),
summary `artifacts/hintbench-aa-study/readout.txt`, run log
`artifacts/hintbench-aa-study-run.log`. Scripts `scripts/hintbench_aa_study/`
(`run.sh`, `readout.py`, `chunk.py`).

## 1. What was asked

Decision 95: the baseline hintbench binary's k5 has two modes, ~358–362 ms
(slow) and ~326–333 ms (fast), with k8 ~2% along. In Experiment 6 every
driver round batch and first holdout was slow, every confirm batch and
panel base leg fast, and 4 of 7 panels failed the A/A rule with the same
shape (aa k5 slow, k8 slow). The same binary read 1.02 (slow) and 1.28
(fast) at k5 for rev's round-3 plan. Question: what decides a label's k5
mode — seed / label order (H3), what ran before (H4), file or page-cache
placement (H2), per-run bimodality (H1), the CPU (H5)?

## 2. The archive finding (before any new run)

All 170 hintbench `samples.json` files were read (344 baseline-copy legs:
`base`, `aa`, null-panel `n*`). Grouped by the glibc chunk class of an
allocation of `len(argv[0])` bytes, `c = max(32, (len + 23) & ~15)`, they
split with **zero exceptions**: c96 (len 73–88) slow, c80 / c112 (len 72,
89–94) fast. No leg is internally bimodal (H1 refuted), and legs of one
batch disagree exactly when base and aa straddle 88|89 (H3, H4 refuted).
The driver names its timing copies under the run directory; confirm and
panel directories have longer names than round directories, which is why
the split followed the batch *kind*.

Hypothesis H6: the mode is keyed to argv[0] length. Prediction: plain-k5
leg slow iff `c % 32 == 0`.

## 3. Protocol

Frozen baseline `artifacts/hintbench-sites/baseline/bin` (stripped sha256
a84b7c0dfe37e4f6…), nothing built, no HTTP. CPU 8, gap 0, stdout pipe,
warmup 3, 15 runs; every path length asserted before the run.

| panel | what | tests |
|---|---|---|
| p1 | `bench_panel.sh`, 8 kernels, copies at c 112 (base), 80, 96, 128, 144, 160; seed 20260927 | H6 map, period 32 vs 64 |
| p2 | `bench.py` k5+k8, len 91 (base) and 85–94, twin at 89, two hard links to one inode at 88 and 89; seed 20260922 | step at 88\|89, H2 |
| p3 | two fixed paths (c112, c96); `k5` with an extra zero-padded repeat argument of 7/25/41/57 chars (same work), `k8` with 6/25 | heap-offset mechanism |
| p4 | p1 again, seed 20360922 | H3 |
| p5a | c 112/80/96 on CPU 10 | H5 |
| p5b | same on CPU 8, 4096-byte extra env variable, cwd `/` (stack moves, heap does not) | stack vs heap |
| p5c | same on CPU 8, busy loop on SMT sibling CPU 9 | robustness |

## 4. Results

Full per-leg tables are in `results.md` §161. The k5 map (medians, ms):

| class | len | p1 | p4 | p5a | p5b | p5c | mode |
|--:|--:|--:|--:|--:|--:|--:|:-:|
| 80 | 70 | 330.5 | 327.1 | 328.3 | 330.4 | 335.1 | F |
| 96 | 80 | 358.9 | 358.8 | 358.3 | 359.4 | 360.9 | S |
| 112 | 96 | 329.9 | 329.3 | 330.9 | 330.5 | 332.9 | F |
| 128 | 112 | 358.5 | 358.3 | | | | S |
| 144 | 128 | 331.5 | 328.1 | | | | F |
| 160 | 144 | 359.0 | 359.2 | | | | S |

p2 (k5): len 85–88 → 360.9 / 360.7 / 359.7 / 359.6 (S); len 89–94 →
332.6 / 329.7 / 329.0 (base, 91) / 330.1 / 331.8 / 330.5 (F); twin Q089
331.4; hard links to inode 1426930: H088 360.3, H089 329.4.

p3 (k5, a0/a7/a25/a41/a57): S112 330.7 / 361.3 / 362.1 / 362.5 / 331.9 =
F/S/S/S/F; S096 360.7 / 331.8 / 333.2 / 330.4 / 359.9 = S/F/F/F/S. k8
(a0/a6/a25): S112 335.4 / 342.1 / 343.3, S096 352.9 / 338.7 / 333.9.

k8, median of leg medians, class mod 32 = 0 vs 16: p1 342.2 / 336.8, p2
342.4 / 334.5, p4 343.1 / 337.6, p5a 341.7 / 335.0, p5b 341.8 / 339.9, p5c
354.5 / 339.5.

## 5. Verdicts (pre-registered rules, in order)

| rule | verdict | key numbers |
|---|---|---|
| H6 length key | **confirmed** | 31/31 pre-registered legs (p1, p2, p4, p5a, p5b), 0 misses; 36/36 with p3 a0 and p5c; period 32 (c128 = c96) |
| Mechanism (heap offset) | **not confirmed: length key confirmed, mechanism unknown** | p3 does not alternate at either path (F/S/S/S/F, S/F/F/F/S) |
| H2 file / page cache | **refuted** | one inode: 360.3 at len 88, 329.4 at len 89; twins 332.6 / 331.4 |
| H1 per-run bimodality | not reopened | at most 2/15 runs past 345 ms in any leg (p5c c80, under SMT load) |
| H3 seed / order | not reopened | p1 = p4 on all 6 legs |
| H5 CPU | not reopened | p5a map unchanged on CPU 10 |
| p5b stack moved | unchanged | c96 359.4 S, c80/c112 F |
| p5c SMT busy | unchanged | map held; k5 +0.4–1.4%, k8 c96 +3.7% |
| k8 | ~2% co-movement in direction | mod-0 higher in all 6 panels (+0.6 to +4.4%), legs overlap |

## 6. Mechanism story

Marked by status.

- **実測 (measured)**: the mode is a function of `len(argv[0])` with a
  32-byte period in the chunk class, steps between 88 and 89, and does not
  depend on the inode, the seed/order, CPU 8 vs 10, the stack position
  (p5b), or SMT load. Adding one argv argument of the same numeric value
  flips the mode at both paths for 7-, 25- and 41-char arguments and not
  for 57, and the two paths (16 bytes apart in class) stay in opposite modes
  at all five argument lengths (p3). k8 moves with k5, including under p3's
  padding. Other kernels do not move beyond ~1%, inconsistently.
- **仮説 (hypothesis, source-read, not measured)**: hintbench's `main`
  starts with `let args: Vec<String> = std::env::args().collect();`
  (`targets/hintbench/hintbench/src/main.rs:258`), which allocates the argv
  strings on the brk heap before the kernel data (k5's input is
  `gen_u32(K5_LEN = 4096)`, 16 KiB, below the mmap threshold, so also on
  the brk heap). brk randomisation is page-granular, so the data's offset
  *within a page* is fixed by the sizes of what was allocated before it —
  here, by argv[0]'s length — and k5's inner loop is sensitive to that
  alignment (a 32-byte period suggests a cache-line-half or a
  store-forwarding / 4K-aliasing interaction, untested). The simple
  prediction of this story (p3: `a7 = a41, a25 = a57, a7 ≠ a25`) failed,
  so the exact allocation arithmetic is not understood; no new pattern was
  fitted after the fact.

## 7. Consequences

1. **Equal-length exec paths.** Every label of a timing batch must be
   executed from a path of the same length. `bench.py` will hard-link each
   label to `artifacts/timing-run/<8hex>/<name>` at exactly 80 bytes
   (class 96 — the oracle's and every round batch's class), assert equal
   length and class before timing, and record them (decision 97).
2. **Cross-class comparisons are invalid** for k5 (and ~2% for k8): the
   footnote table in §161 lists every existing one. Exp6 training (round)
   and first-holdout ratios are same-class with the oracle (c96); confirm
   batches and panels are c112 or mixed. Nothing is recomputed; whether to
   re-measure is the owner's call.
3. **Ground truth is per class.** The oracle's k5 numbers (unroll 8 =
   1.0194, combination 1.0881) are class 96, rev's 1.28 is class 112. Only
   the baseline binary's map is measured; a candidate binary may map
   differently.

## 8. Exposure of the real targets (proposed, not done)

jaq and zopfli are Rust and also copy argv to the heap before reading their
input: jaq `targets/jaq/src/jaq/src/cli.rs:167` (`std::env::args_os()`),
zopfli `targets/zopfli/src/src/main.rs:23` (`env::args().skip(1)`; that
std copies argv[0] to the heap even when it is skipped is our reading of
std on Linux, not checked against this toolchain's source — `rust-src` is
not installed). Whether
their timing depends on argv[0] length is not measured. Proposed: one
cheap A/A check per target, the same binary at two classes (e.g. c96 and
c112), about 10 minutes each. Until then, any existing jaq/zopfli comparison whose labels had
different path lengths carries an unknown bias of this kind.
