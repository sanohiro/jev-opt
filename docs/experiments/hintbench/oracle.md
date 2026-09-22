# The hint benchmark oracle

The one-factor sweep of SPEC.ja.md 2 over `targets/hintbench`: every candidate
of vocabulary v3, alone, at every one of the twelve sites, with every other
site at `KEEP_DEFAULT`, plus one combination arm. 84 one-factor arms.

It exists to turn `targets/hintbench/EXPECTED.md` --- Claude's per-kernel
prediction, frozen before any timing run --- into a score, and to say which
hints in the frozen vocabulary can move this recipe at all.

Sections 1 and 2 were written and committed **before the first arm was
built**. Everything from section 3 on is the measurement.

## 1. Protocol

### 1.1 What is frozen

From `scripts/target_common.sh` and `jev-opt.toml`, unchanged:

| | |
|---|---|
| target | `hintbench`, PGO baseline, `.text` sha256 `df5968bc018b17ad9a3d1f236e1ac8f6c9995d76bc296f0c8c67fda9c9f1fe7a` |
| baseline binary | `artifacts/hintbench-sites/baseline/bin`, the `JEV_MODE=dump` build, `.text` identical to the plain PGO baseline (results.md 108) |
| case set | the eight kernel workloads `k1`..`k8`; hintbench declares no `TRAIN_WORKLOADS`, so every artifact says `holdout-as-search` |
| repetitions | 15, warmup 3 |
| label order | shuffled per (round, workload), seed 20260922 + round |
| pinning | `taskset -c 8` = physical core 4 (cores 1--3 belong to toy/zopfli, jaq and oxipng) |
| settle gap | **0 ms** --- hintbench's frozen value; only jaq sets 250 ms |
| stdout | `pipe` (the binary prints a checksum block) |
| bootstrap | 10000 resamples, paired on the round |
| vocabulary | v3 (decision 77): functions `inline(always)`, `inline(never)`, `align=16/32/64`; loops unchanged |
| site set | `oracle.selected_keys_loop_hint_kernels`, pre-registered in `scripts/hintbench_oracle.sh`: 8 marked functions + 4 loops |

### 1.2 The readout is per kernel, not the aggregate

results.md "Hint benchmark (design)" 103 froze it: *"the ground truth for
kernel N is the ratio on workload kN, not the eight-way geometric mean (a 10%
win on one kernel is 1.2% in the mean, under the minimum detectable effect of
decision 16)"*. So for an arm at a `kN_*` site the primary number is the ratio
on workload `kN` and its 95% CI; the aggregate is recorded beside it and is
what the driver's acceptance rule and the `best` bookkeeping still use.

### 1.3 Three driver fixes, pre-registered (decision 80)

All three were made, tested and committed before arm 1, and none of them
touches the vocabulary, the state format, the site set or the measurement
conditions.

**(a) Closure fan-out (decision 80 c).** `is_inner_item` decided whether a
function belongs to a mark or is an item defined inside it by looking at the
single character after the mark. For a *generic* mark that character is the
`<` of the generic arguments, so `read::parse::<SliceLexer>::{closure#0}` was
filed as a monomorphization and got the attribute. The rule now skips the
balanced `::<...>` group and asks what follows it: another `::` segment is an
inner item, nothing is the function itself. Effect, measured on the two
targets' existing dumps without building anything:

| target | plan entries for a full phase-A plan, before | after | removed |
|---|--:|--:|--:|
| hintbench | 8 | 8 | **0** |
| jaq | 138 | 49 | **89** (4 generic marks: `read::parse` 18→6, `TermId::run` 62→2, `path::run` 12→3, `Val::hash` 12→4) |

hintbench is unaffected --- its eight marks are non-generic and each resolves
to exactly one function --- so this sweep measures the same thing it would
have measured without the fix. The number that matters is jaq's.

**(b) No-op skip (decision 80 b).** After the phase-B build and the
correctness check, every arm's binary is classified against the baseline by
normalised instruction sequence (`norm_code_diff.py`) **and** symbol table
(`nm -S`, addresses and sizes):

* `identical` --- same instructions, same symbol table. Outcome
  `identical_to_baseline`, ratio 1.0 **by construction**, `ci95: null`, and
  **no timing batch**. On jaq 48 such arms were timed anyway and 20 of them
  produced an interval that excluded 1.0.
* `layout` --- same instructions, symbols moved. Measured: this is what
  `align=N` does when it works.
* `code` --- at least one symbol's instructions changed. Measured.

**(c) Confirmation batch (decision 80 a).** An arm whose 95% CI excludes 1 in
its first batch --- on the aggregate, or on its own kernel's workload --- is
re-measured in a **second, independent batch**: the same two binaries, the
same n, warmup and conditions, a fresh shuffle seed (`20260922 + 100000 +
round`). The arm is **confirmed** only if both batches exclude 1 with the same
sign. The confirmation lives inside the same round record.

Two rules downstream now require it:

* the driver's acceptance rule gains a fourth condition --- rule 3 (the CI
  lower bound beats the incumbent) must be confirmed in the second batch;
* **the combination arm takes a site's best *confirmed* arm, ranked by the
  per-kernel readout**, instead of its best one-batch arm ranked by the
  aggregate. The one-batch set and the point-estimate set are recorded beside
  the chosen one. Without this the combination arm on this target would be
  chosen by aggregate noise: a real +5% on k1 is +0.6% of the aggregate.

## 2. How EXPECTED.md is scored (pre-registered)

For each kernel, one row. The prediction is EXPECTED.md section 0 as revised
by its section 4 (K2 → `inline(always)`; sections 1--3 are frozen).

**Measured best** for kernel N = the arm at one of kernel N's own sites (its
function mark, and its loop if it has one in the frozen set) with the highest
ratio on workload `kN` **among the arms that were confirmed with a positive
sign**. If no arm at that kernel was confirmed positive, the measured best is
`KEEP_DEFAULT`: the sweep found nothing there.

**Score**, one of three:

* **hit** --- the measured best is the hint EXPECTED.md named (including
  `KEEP_DEFAULT` when that is what it named);
* **same-family** --- same hint kind, different value: `unroll.count=2` for
  `unroll.disable`, `align=32` for `align=64`, `vectorize.width=4` for
  `=16`, `interleave.count=2` for `=4`;
* **miss** --- anything else, including a named hint where the measured best
  is `KEEP_DEFAULT`, and `KEEP_DEFAULT` where some hint was confirmed.

**Added 17:08 JST, after round 21 and before round 22** (so before the
calibration arm, before K6, K7 and K8 and before every loop arm): the two
rules above disagree, and the disagreement is visible at K4, whose
`inline(never)` arm came back confirmed at 1.0152 --- the highest confirmed
ratio at that kernel, and therefore its "measured best", while 1.52% is under
the 3% MDE floor and therefore a *dead* hint by the rule below. A row cannot
honestly be both the answer and undetectable. The pre-registered rule is not
changed; instead **the scorecard is reported twice**: once exactly as
pre-registered, which is the score, and once with the additional gate that
the confirmed effect cleared its own batch's MDE, which says which scores
rest on an effect this protocol calls too small to act on. Both readings are
fixed here before the arms that decide them.

**The calibration arm.** K5's `interleave.count=1` is predicted to cost 50--75%
of the k5 workload (EXPECTED.md 1, K5; results.md 107). If that arm does not
show a large, confirmed degradation on k5, **the sweep cannot see anything**
and no other row of the scorecard may be read. This is stated before the run
so that it cannot be re-interpreted after it.

**Live and dead hints.** A candidate is *live* on this benchmark if it cleared
the MDE (`max(2 x worst per-workload half-width, 3%)`, per batch) on at least
one kernel with confirmation, in either direction. Everything else is dead
*under this recipe on this target* --- which for a candidate that never once
changed an instruction is a statement about the compiler, and for one that
changed code without moving the clock is a statement about the workload.

## 3. The null panel, before the sweep

Two independent batches, each four stripped copies of the one baseline binary,
same conditions as every arm (`scripts/bench_panel.sh`, 15 runs, warmup 3,
CPU 8, gap 0). Seeds 20260922 and 20260923.

| label | batch 1 ratio | batch 1 95% CI | batch 2 ratio | batch 2 95% CI |
|---|--:|---|--:|---|
| n0 (base) | 1.0000 | --- | 1.0000 | --- |
| n1 | 0.9997 | [0.9976, 1.0018] | 1.0017 | [0.9996, 1.0039] |
| n2 | 0.9998 | [0.9977, 1.0017] | 1.0017 | [0.9996, 1.0041] |
| n3 | 1.0005 | [0.9984, 1.0027] | 1.0018 | [0.9991, 1.0044] |

* **Within-batch spread between byte-identical binaries: 0.08 points**
  (batch 1) and **0.01 points** (batch 2). No interval in either batch
  excludes 1.
* **Between batches the same comparison moved 0.17 points** --- all three
  non-base labels shifted together, which is a batch-level shift of the base
  label rather than label-to-label scatter.
* In-batch aggregate half-width 0.21%, so on this target the within-batch
  interval is about the right size for the between-batch scatter it sits in.
  **This is the opposite of jaq**, where the in-batch half-width was 0.73%
  and the between-batch A/A ranged over 5.35 points (results.md 113). The
  confirmation batch is therefore expected to be a cheap formality here and a
  necessity there.
* Per-workload half-widths, worst over the non-base labels:

| batch | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 | MDE |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 0.38% | 0.53% | 0.64% | 0.33% | 0.38% | 0.32% | 0.48% | **1.54%** | 3.08% |
| 2 | 0.45% | 0.50% | 0.42% | 0.34% | 0.48% | 0.55% | 0.49% | **1.88%** | 3.75% |

  k8, the control kernel, is three times noisier than any other workload in
  both batches. Nothing else exceeds 0.7%.

Raw: `artifacts/hintbench-oracle-nullpanel-{1,2}/` (git-ignored).
