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
| label order | shuffled per (round, workload), seed 20260921 + round (`[evaluation] seed`) |
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
same n, warmup and conditions, a fresh shuffle seed (`20260921 + 100000 +
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

*What "large" means, written 17:12 JST after round 21 and before round 49,
the arm itself* --- "large" was left undefined above, which would have let it
be chosen after the number was known. Three bands, on the k5 ratio of the
`interleave.count=1` arm, confirmed in two batches:

| k5 ratio | reading |
|---|---|
| **< 0.75** | as predicted (a 25%+ loss, inside or near EXPECTED's -50% to -75% band). The sweep sees; the scorecard stands. |
| **0.75 -- 0.97** | the sweep sees an effect of the predicted sign but the K5 mechanism model (IC 4 -> IC 1 quarters the reduction throughput) is wrong about its size. The scorecard stands; EXPECTED's K5 reasoning does not. |
| **> 0.97** | either the hint did not reach the loop or the instrument cannot resolve a change this large. **The scorecard is void** and nothing else in this document may be read as a measurement of a prediction. |

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

## 4. The sweep

`scripts/hintbench_oracle.sh run --keep-binaries all`, 16:39--20:28 JST on
2026-09-22, 85 rounds, no API calls. Provenance from `run-manifest.json`:
baseline binary `07498197…`, plugin `be74c857…`, `merged.profdata`
`d1b226d5…`, `jev-marks.txt` `87922190…`, `jev-opt.toml` `a8029ac1…`,
vocabulary and state format `v3-2026-09-22`, case set `holdout-as-search`.


| | |
|---|--:|
| one-factor arms | 84 |
| correctness held | 84 of 84 |
| builds identical to the baseline (not timed) | **39** |
| builds that only moved code (layout) | 4 |
| builds that changed instructions | 41 |
| arms whose first batch excluded 1 (confirmation run) | 38 |
| confirmed on the kernel readout | **33** |
| confirmed on the aggregate | 27 |
| in-run A/A intervals excluding 1, first batch (aggregate) | 5 of 45 |
| in-run A/A intervals excluding 1, first batch (own kernel) | 12 of 45 |
| in-run A/A intervals excluding 1, confirmation batch | 5 of 38 |
| wall clock of the rounds | 3.8 h |

**Correctness held in 84 of 84 arms and in the combination**, every plan
entry `consumed` or `attached`, nothing `vanished`, `unmatched` or
`ambiguous`.

**The no-op skip paid for itself.** 39 of the 84 arms built a binary
identical to the baseline's --- 27 of the 40 function arms and 12 of the 44
loop arms. A skipped arm costs 9.6 s (two builds, correctness, the code
comparison) against 290 s for a measured one, so the skip removed about
**3.1 hours** from a sweep that took 3.8. It also removed 39 measurements
that could only have produced noise: on jaq the same 48 arms were timed and
20 of them came back with an interval excluding 1.

**The confirmation batch was cheap here and would have been cheap to skip.**
38 arms triggered it, 33 were confirmed on the kernel readout and 27 on the
aggregate. Not one arm that this sweep would have accepted on one batch was
refused by the second: the combination arm's membership is **identical**
under the confirmed-in-two-batches rule and under the one-batch rule it
replaces (section 7). That is a statement about hintbench, not about the
rule --- the null panel already said this target's intervals are the right
size, and it is jaq where the one-batch rule combined twelve arms whose
claims multiplied to +22.4% and delivered +2.15%.

**The in-run A/A, the calibration number.** Over the timed arms the A/A
label --- a second stripped copy of the baseline, in the same batch --- had
an interval excluding 1.0 in **5 of 45** aggregate readings (11%), **12 of
45** own-kernel readings (27%) and **5 of 38** confirmation batches (13%).
jaq's figure was 41 of 90 (46%). The aggregate interval on this target is
close to honest; the single-workload interval is still about five times too
confident, which is why the per-kernel readout needs the confirmation batch
more than the aggregate does.

**Cross-kernel interference is real and is not noise.** The eight kernels
share one binary, so any arm relocates everyone's code. Round 2 (`k1_step
inline(never)`) moved k4 by +1.44% with an interval excluding 1, from a
change that touched two symbols neither of which k4 executes. That is the
argument for the per-kernel readout, and it is also why "confirmed on the
aggregate" can fire on interference: the aggregate mixes the site's own
kernel with seven others that only felt the layout move.

## 5. Per kernel

Every candidate at every one of that kernel's sites. `1.0000*` is the no-op
skip: ratio 1.0 by construction, never measured.

### K1

| arm | site | candidate | build vs baseline | changed syms | k1 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 1 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 2 | fn | `inline_never` | code | 2 | 0.9545 | [0.9519, 0.9571] | **yes (-)** | 0.9951 | [0.9929, 0.9974] |
| 3 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 4 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 5 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

### K2

| arm | site | candidate | build vs baseline | changed syms | k2 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 6 | fn | `inline_always` | code | 2 | 1.6775 | [1.6682, 1.6864] | **yes (+)** | 1.0629 | [1.0564, 1.0689] |
| 7 | fn | `inline_never` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 8 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 9 | fn | `align_32` | layout | 0 | 1.0071 | [0.9985, 1.0211] | not triggered | 1.0019 | [0.9987, 1.0052] |
| 10 | fn | `align_64` | layout | 0 | 0.9974 | [0.9940, 1.0016] | not triggered | 1.0007 | [0.9979, 1.0035] |

### K3

| arm | site | candidate | build vs baseline | changed syms | k3 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 11 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 12 | fn | `inline_never` | code | 2 | 0.8294 | [0.8276, 0.8313] | **yes (-)** | 0.9781 | [0.9760, 0.9802] |
| 13 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 14 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 15 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 74 | loop | `unroll_count_2` | code | 1 | 1.0423 | [1.0397, 1.0448] | **yes (+)** | 1.0060 | [1.0028, 1.0089] |
| 75 | loop | `unroll_count_4` | code | 1 | 1.0436 | [1.0412, 1.0461] | **yes (+)** | 1.0060 | [1.0030, 1.0092] |
| 76 | loop | `unroll_count_8` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 77 | loop | `unroll_disable` | code | 1 | 0.7056 | [0.7021, 0.7088] | **yes (-)** | 0.9567 | [0.9540, 0.9600] |
| 78 | loop | `vectorize_width_2` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 79 | loop | `vectorize_width_4` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 80 | loop | `vectorize_width_8` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 81 | loop | `vectorize_width_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 82 | loop | `interleave_count_1` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 83 | loop | `interleave_count_2` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 84 | loop | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

### K4

| arm | site | candidate | build vs baseline | changed syms | k4 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 16 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 17 | fn | `inline_never` | code | 2 | 1.0152 | [1.0110, 1.0193] | **yes (+)** | 0.9957 | [0.9938, 0.9980] |
| 18 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 19 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 20 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 52 | loop | `unroll_count_2` | code | 1 | 0.9848 | [0.9823, 0.9874] | **yes (-)** | 0.9993 | [0.9963, 1.0022] |
| 53 | loop | `unroll_count_4` | code | 1 | 1.0053 | [1.0025, 1.0082] | **yes (+)** | 1.0015 | [0.9988, 1.0040] |
| 54 | loop | `unroll_count_8` | code | 1 | 1.0048 | [0.9825, 1.0417] | not triggered | 0.9999 | [0.9925, 1.0087] |
| 55 | loop | `unroll_disable` | code | 1 | 0.7309 | [0.7297, 0.7327] | **yes (-)** | 0.9596 | [0.9575, 0.9618] |
| 56 | loop | `vectorize_width_2` | code | 1 | 0.2024 | [0.2020, 0.2027] | **yes (-)** | 0.8194 | [0.8174, 0.8215] |
| 57 | loop | `vectorize_width_4` | code | 1 | 0.6744 | [0.6732, 0.6754] | **yes (-)** | 0.9517 | [0.9499, 0.9535] |
| 58 | loop | `vectorize_width_8` | code | 1 | 0.9996 | [0.9967, 1.0024] | not triggered | 0.9983 | [0.9947, 1.0018] |
| 59 | loop | `vectorize_width_16` | code | 1 | 0.5793 | [0.5777, 0.5813] | **yes (-)** | 0.9361 | [0.9344, 0.9379] |
| 60 | loop | `interleave_count_1` | code | 1 | 0.7301 | [0.7266, 0.7349] | **yes (-)** | 0.9605 | [0.9583, 0.9630] |
| 61 | loop | `interleave_count_2` | code | 1 | 0.9396 | [0.9377, 0.9417] | **yes (-)** | 0.9883 | [0.9823, 0.9926] |
| 62 | loop | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

### K5

| arm | site | candidate | build vs baseline | changed syms | k5 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 21 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 22 | fn | `inline_never` | code | 2 | 0.9916 | [0.9873, 0.9958] | **yes (-)** | 0.9951 | [0.9919, 0.9984] |
| 23 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 24 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 25 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 41 | loop | `unroll_count_2` | code | 1 | 0.9872 | [0.9705, 0.9983] | **yes (-)** | 0.9986 | [0.9966, 1.0006] |
| 42 | loop | `unroll_count_4` | code | 1 | 1.0207 | [1.0150, 1.0278] | **yes (+)** | 1.0043 | [1.0023, 1.0063] |
| 43 | loop | `unroll_count_8` | code | 1 | 1.0194 | [1.0154, 1.0250] | **yes (+)** | 1.0017 | [0.9994, 1.0040] |
| 44 | loop | `unroll_disable` | code | 1 | 0.2941 | [0.2935, 0.2947] | **yes (-)** | 0.8571 | [0.8523, 0.8616] |
| 45 | loop | `vectorize_width_2` | code | 1 | 0.2791 | [0.2787, 0.2794] | **yes (-)** | 0.8525 | [0.8505, 0.8545] |
| 46 | loop | `vectorize_width_4` | code | 1 | 0.5568 | [0.5559, 0.5577] | **yes (-)** | 0.9301 | [0.9273, 0.9329] |
| 47 | loop | `vectorize_width_8` | code | 1 | 0.9950 | [0.9929, 0.9970] | **yes (-)** | 0.9985 | [0.9967, 1.0003] |
| 48 | loop | `vectorize_width_16` | code | 1 | 1.0265 | [1.0235, 1.0294] | **yes (+)** | 1.0048 | [1.0031, 1.0065] |
| 49 | loop | `interleave_count_1` | code | 1 | 0.2957 | [0.2943, 0.2978] | **yes (-)** | 0.8591 | [0.8566, 0.8619] |
| 50 | loop | `interleave_count_2` | code | 1 | 0.5953 | [0.5941, 0.5965] | **yes (-)** | 0.9392 | [0.9372, 0.9413] |
| 51 | loop | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

### K6

| arm | site | candidate | build vs baseline | changed syms | k6 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 26 | fn | `inline_always` | code | 2 | 1.0011 | [0.9981, 1.0039] | no | 0.9949 | [0.9916, 0.9979] |
| 27 | fn | `inline_never` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 28 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 29 | fn | `align_32` | layout | 0 | 0.9985 | [0.9954, 1.0013] | not triggered | 0.9977 | [0.9949, 1.0004] |
| 30 | fn | `align_64` | layout | 0 | 1.0008 | [0.9981, 1.0039] | not triggered | 1.0011 | [0.9980, 1.0041] |

### K7

| arm | site | candidate | build vs baseline | changed syms | k7 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 31 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 32 | fn | `inline_never` | code | 2 | 0.9999 | [0.9981, 1.0017] | no | 1.0019 | [1.0000, 1.0037] |
| 33 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 34 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 35 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

### K8

| arm | site | candidate | build vs baseline | changed syms | k8 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 36 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 37 | fn | `inline_never` | code | 2 | 0.9914 | [0.9745, 1.0072] | no | 0.9943 | [0.9923, 0.9962] |
| 38 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 39 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 40 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 63 | loop | `unroll_count_2` | code | 1 | 1.0164 | [1.0029, 1.0304] | **yes (+)** | 1.0008 | [0.9987, 1.0030] |
| 64 | loop | `unroll_count_4` | code | 1 | 0.9778 | [0.9514, 1.0007] | no | 0.9965 | [0.9935, 0.9990] |
| 65 | loop | `unroll_count_8` | code | 1 | 1.0201 | [1.0025, 1.0403] | no | 1.0031 | [1.0008, 1.0056] |
| 66 | loop | `unroll_disable` | code | 1 | 0.8226 | [0.7819, 0.8626] | **yes (-)** | 0.9753 | [0.9691, 0.9812] |
| 67 | loop | `vectorize_width_2` | code | 1 | 0.4467 | [0.4255, 0.4680] | **yes (-)** | 0.9034 | [0.8978, 0.9087] |
| 68 | loop | `vectorize_width_4` | code | 1 | 0.9171 | [0.8895, 0.9437] | **yes (-)** | 0.9891 | [0.9853, 0.9929] |
| 69 | loop | `vectorize_width_8` | code | 1 | 1.0005 | [0.9803, 1.0193] | not triggered | 0.9991 | [0.9968, 1.0015] |
| 70 | loop | `vectorize_width_16` | code | 1 | 1.0881 | [1.0709, 1.1069] | **yes (+)** | 1.0100 | [1.0072, 1.0133] |
| 71 | loop | `interleave_count_1` | code | 1 | 0.8033 | [0.7600, 0.8464] | **yes (-)** | 0.9726 | [0.9655, 0.9795] |
| 72 | loop | `interleave_count_2` | code | 1 | 0.9456 | [0.9081, 0.9840] | **yes (-)** | 0.9933 | [0.9885, 0.9980] |
| 73 | loop | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

## 6. The calibration arm, and the scorecard

**K5 `interleave.count=1` measures 0.2957 [0.2943, 0.2978] on k5, confirmed
at 0.2944 in the second batch.** That is a 70.4% loss, inside EXPECTED.md's
predicted −50% to −75% band and far below the 0.75 threshold that section 2
fixed at round 21. **Band one: the sweep sees, and the scorecard may be
read.** `interleave.count=2` came in at 0.5953 --- almost exactly half the
loss, as EXPECTED.md said it would --- and `interleave.count=4` produced a
binary identical to the baseline, because IC 4 is what the baseline already
picks. The kernel EXPECTED.md called "the calibration site of the whole
benchmark" did the job it was kept for.


| kernel | Claude's expected winner | expected effect | confidence | measured best (confirmed) | measured ratio | score | worst arm |
|---|---|---|---|---|--:|---|---|
| K1 | `inline_never` | +2% to +10% | low | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9545 |
| K2 | `inline_always` | +2% to +10% | medium | `inline_always` | 1.6775 | **hit** | `align_64` 0.9974 |
| K3 | `unroll_disable` | +2% to +10% | medium | `unroll_count_4` | 1.0436 | same-family | `unroll_disable` 0.7056 |
| K4 | `KEEP_DEFAULT` | width 16: 0% to -25% | medium | `inline_never` | 1.0152 | miss | `vectorize_width_2` 0.2024 |
| K5 | `KEEP_DEFAULT` | IC 1: -50% to -75% | high | `vectorize_width_16` | 1.0265 | miss | `vectorize_width_2` 0.2791 |
| K6 | `align_64` | +-0% to +-3%, sign unknown | low | `KEEP_DEFAULT` | -- | miss | `align_32` 0.9985 |
| K7 | `inline_never` | 0% to +5% | medium | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9999 |
| K8 | `KEEP_DEFAULT` | every hint <= 0% | high | `vectorize_width_16` | 1.0881 | miss | `vectorize_width_2` 0.4467 |

**1 hit, 1 same-family, 6 miss of 8.**

With the post-hoc MDE gate (oracle.md 2, dated note): the same rule, plus the confirmed effect having cleared its batch's MDE.

| kernel | Claude's expected winner | expected effect | confidence | measured best (confirmed) | measured ratio | score | worst arm |
|---|---|---|---|---|--:|---|---|
| K1 | `inline_never` | +2% to +10% | low | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9545 |
| K2 | `inline_always` | +2% to +10% | medium | `inline_always` | 1.6775 | **hit** | `align_64` 0.9974 |
| K3 | `unroll_disable` | +2% to +10% | medium | `unroll_count_4` | 1.0436 | same-family | `unroll_disable` 0.7056 |
| K4 | `KEEP_DEFAULT` | width 16: 0% to -25% | medium | `KEEP_DEFAULT` | -- | **hit** | `vectorize_width_2` 0.2024 |
| K5 | `KEEP_DEFAULT` | IC 1: -50% to -75% | high | `KEEP_DEFAULT` | -- | **hit** | `vectorize_width_2` 0.2791 |
| K6 | `align_64` | +-0% to +-3%, sign unknown | low | `KEEP_DEFAULT` | -- | miss | `align_32` 0.9985 |
| K7 | `inline_never` | 0% to +5% | medium | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9999 |
| K8 | `KEEP_DEFAULT` | every hint <= 0% | high | `vectorize_width_16` | 1.0881 | miss | `vectorize_width_2` 0.4467 |

**3 hit, 1 same-family, 4 miss of 8.**

### What the two readings disagree about

Three rows, all of them effects between 1.5% and 2.7% that were confirmed in
two batches and are under their batch's 3--3.1% MDE: K4 `inline(never)`
1.0152, K5 `vectorize.width=16` 1.0265, and (not a disagreement, because it
clears the MDE at 8.8%) K8 `vectorize.width=16`. The frozen rule calls the
first two the kernel's measured best and scores `KEEP_DEFAULT` a miss; the
MDE-gated rule calls them undetectable and scores `KEEP_DEFAULT` a hit. Both
numbers are real and reproducible; the question the two rules disagree on is
whether this protocol is allowed to act on a 2% effect, and SPEC.ja.md's 3%
floor says no.

### Winner claims and effect-size claims are two different scores

The scorecard above grades the **winner** claim. EXPECTED.md also states an
effect size for each kernel, and that column grades differently:

| kernel | predicted size | measured | size claim |
|---|---|---|---|
| K1 | +2% to +10% | **−4.55%** | wrong sign |
| K2 | +2% to +10% | **+67.8%** | right sign, 7x the top of the band |
| K3 | +2% to +10% (`unroll.disable`) | **−29.4%** for that hint, +4.4% for `unroll.count=4` | wrong sign for the named hint, in band for its own sibling |
| K4 | width 16: 0% to −25% | **−42.1%** | right sign, outside the band |
| K5 | IC 1: −50% to −75% | **−70.4%** | **in band** |
| K6 | ±0% to ±3%, sign unknown | **+0.08%**, unconfirmed | **in band** |
| K7 | 0% to +5% | **−0.01%**, unconfirmed | **in band**, at its floor |
| K8 | every hint ≤ 0% | **+8.8%** for `vectorize.width=16` | wrong |

So four of eight size claims land inside their stated band while only one of
eight winner claims is a hit. Where Claude is well calibrated is on *how
much a knob can matter*; where it is not is on *which knob*, and on the sign
of the two inlining redirections.

## 7. The combination arm

Selection rule: **confirmed in two batches, ratio > 1**.

| rule | sites it would combine |
|---|---|
| confirmed in two batches (used) | `hbkernels::k2_mix` inline_always, `hbkernels::k4_count_bytes` inline_never, `hbkernels::k3_fill_run@lib.rs:174:9#d3` unroll_count_4, `hbkernels::k4_count_bytes@macros.rs:180:28#d2` unroll_count_4, `hbkernels::k5_mul_reduce@macros.rs:180:28#d2` vectorize_width_16, `hbkernels::k8_scale_add@range.rs:1103:12#d2` vectorize_width_16 |
| one batch, CI lower > 1 | `hbkernels::k2_mix` inline_always, `hbkernels::k4_count_bytes` inline_never, `hbkernels::k3_fill_run@lib.rs:174:9#d3` unroll_count_4, `hbkernels::k4_count_bytes@macros.rs:180:28#d2` unroll_count_4, `hbkernels::k5_mul_reduce@macros.rs:180:28#d2` vectorize_width_16, `hbkernels::k8_scale_add@range.rs:1103:12#d2` vectorize_width_16 |
| point estimate > 1 | `hbkernels::k2_mix` inline_always, `hbkernels::k4_count_bytes` inline_never, `hbkernels::k6_hot_loop` inline_always, `hbkernels::k3_fill_run@lib.rs:174:9#d3` unroll_count_4, `hbkernels::k4_count_bytes@macros.rs:180:28#d2` unroll_count_4, `hbkernels::k5_mul_reduce@macros.rs:180:28#d2` vectorize_width_16, `hbkernels::k8_scale_add@range.rs:1103:12#d2` vectorize_width_16 |

Measured: ratio 1.0881 [1.0861, 1.0901], code class `code`, correctness OK, confirmed **yes (+)**.

The six sites it combined are every site whose best arm was confirmed
positive. **Training: 1.0881 [1.0861, 1.0901], confirmed at 1.0856 in a
second batch**, correctness held, three symbols changed.

Per kernel, the combination against the one-factor arms it is made of:

| kernel | one-factor best | in the combination |
|---|--:|--:|
| k1 | (nothing chosen) | 1.0029 |
| k2 | 1.6775 `inline(always)` | **1.6687** |
| k3 | 1.0436 `unroll.count=4` | **1.0487** |
| k4 | 1.0152 `inline(never)` + 1.0053 `unroll.count=4` | **1.0153** |
| k5 | 1.0265 `vectorize.width=16` | **1.0272** |
| k6 | (nothing chosen) | 1.0024 |
| k7 | (nothing chosen) | 1.0010 |
| k8 | 1.0881 `vectorize.width=16` | **1.0699** |

**The per-kernel effects survive being combined**, within a point or two of
what they were alone. That is the sharpest contrast with jaq, where twelve
chosen arms whose claims multiplied to +22.4% delivered +2.15% and the same
batch's A/A moved +2.26% (results.md "Oracle A (jaq)" 114). The difference
is not the combination rule --- it picked the same six sites under both
rules --- it is that on hintbench the one-factor arms were measuring code
and on jaq they were measuring the machine.

## 8. The holdout batch

hintbench declares no `TRAIN_WORKLOADS`, so its "holdout" is **the same
eight workloads**: this is a third independent batch, not a generalisation
test, and nothing here says an effect transfers to inputs it was not tuned
on. One batch, four labels, seed 20260924 (`scripts/bench_panel.sh`).

| label | aggregate | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | --- | --- |
| **comb** (the combination arm) | **1.0847** | [1.0822, 1.0872] | 0.25% |
| **best1f** (`k2_mix inline(always)`) | **1.0636** | [1.0609, 1.0661] | 0.26% |
| aa (a second copy of the baseline) | 1.0097 | [1.0069, 1.0122] | 0.26% |

Per workload:

| label | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| comb | 0.9994 | **1.6721** | **1.0444** | 1.0138 | 1.0243 | 0.9996 | 0.9992 | **1.0584** |
| best1f | 0.9964 | **1.6745** | 0.9905 | 0.9971 | 0.9982 | 0.9989 | 0.9989 | 0.9976 |
| aa | 1.0007 | 1.0020 | 0.9996 | 0.9995 | **1.0938** | 0.9978 | 0.9971 | 0.9905 |

The batch's MDE is `max(2 x 1.95%, 3%) = 3.90%` and both candidates clear
it. Two caveats, both visible above:

* **the A/A label carries a 9.4% outlier on k5**, which is where its whole
  +0.97% aggregate comes from. It is this target's version of the readwrite
  outlier jaq's holdout batch had (results.md 114), the batch was not
  repeated, and it is the single worst identical-binary reading in the four
  batches of this document. Net of it, the combination is about +7.4%.
* **k8 is the noisiest workload in every batch** (per-workload half-width
  1.5--2.0% against 0.3--0.6% for the rest), and k8 is where the
  combination's second-largest gain sits. The k8 effect is nonetheless
  +8.8% one-factor, +7.0% combined, +5.8% here --- three independent
  batches, all well outside that noise.

## 9. What the sweep taught about the vocabulary

| candidate | arms | identical builds | best kernel ratio | worst kernel ratio | confirmed effects | cleared the MDE |
|---|--:|--:|--:|--:|---|---|
| `align_16` | 8 | 8 | - | - | none | **never** |
| `align_32` | 8 | 6 | 1.0071 (k2) | 0.9985 (k6) | none | **never** |
| `align_64` | 8 | 6 | 1.0008 (k6) | 0.9974 (k2) | none | **never** |
| `inline_always` | 8 | 6 | 1.6775 (k2) | 1.0011 (k6) | k2 1.6775 | k2 1.6775 (MDE 7.0%) |
| `inline_never` | 8 | 2 | 1.0152 (k4) | 0.8294 (k3) | k1 0.9545, k3 0.8294, k4 1.0152, k5 0.9916 | k1 0.9545 (MDE 3.0%), k3 0.8294 (MDE 3.4%) |
| `interleave_count_1` | 4 | 1 | 0.8033 (k8) | 0.2957 (k5) | k5 0.2957, k4 0.7301, k8 0.8033 | k5 0.2957 (MDE 4.4%), k4 0.7301 (MDE 3.9%), k8 0.8033 (MDE 8.6%) |
| `interleave_count_2` | 4 | 1 | 0.9456 (k8) | 0.5953 (k5) | k5 0.5953, k4 0.9396, k8 0.9456 | k5 0.5953 (MDE 4.0%) |
| `interleave_count_4` | 4 | 4 | - | - | none | **never** |
| `unroll_count_2` | 4 | 0 | 1.0423 (k3) | 0.9848 (k4) | k5 0.9872, k4 0.9848, k8 1.0164, k3 1.0423 | **never** |
| `unroll_count_4` | 4 | 0 | 1.0436 (k3) | 0.9778 (k8) | k5 1.0207, k4 1.0053, k3 1.0436 | k3 1.0436 (MDE 3.5%) |
| `unroll_count_8` | 4 | 1 | 1.0201 (k8) | 1.0048 (k4) | k5 1.0194 | **never** |
| `unroll_disable` | 4 | 0 | 0.8226 (k8) | 0.2941 (k5) | k5 0.2941, k4 0.7309, k8 0.8226, k3 0.7056 | k5 0.2941 (MDE 6.5%), k4 0.7309 (MDE 3.0%), k8 0.8226 (MDE 8.1%), k3 0.7056 (MDE 3.3%) |
| `vectorize_width_16` | 4 | 1 | 1.0881 (k8) | 0.5793 (k4) | k5 1.0265, k4 0.5793, k8 1.0881 | k4 0.5793 (MDE 4.2%), k8 1.0881 (MDE 3.8%) |
| `vectorize_width_2` | 4 | 1 | 0.4467 (k8) | 0.2024 (k4) | k5 0.2791, k4 0.2024, k8 0.4467 | k5 0.2791 (MDE 3.4%), k4 0.2024 (MDE 3.7%), k8 0.4467 (MDE 4.3%) |
| `vectorize_width_4` | 4 | 1 | 0.9171 (k8) | 0.5568 (k5) | k5 0.5568, k4 0.6744, k8 0.9171 | k5 0.5568 (MDE 4.3%), k4 0.6744 (MDE 4.5%), k8 0.9171 (MDE 5.4%) |
| `vectorize_width_8` | 4 | 1 | 1.0005 (k8) | 0.9950 (k5) | k5 0.9950 | **never** |

### Live and dead under this recipe

**Live** --- cleared the MDE with confirmation on at least one kernel:
`inline(always)` (K2, +67.8%), `inline(never)` (K1 −4.6%, K3 −17.1%),
`unroll.count=4` (K3, +4.4%), `unroll.disable` (four kernels, −17.7% to
−70.6%), `vectorize.width=2` and `=4` (three kernels each),
`vectorize.width=16` (K4 −42%, K8 +8.8%), `interleave.count=1` (three
kernels) and `interleave.count=2` (K5). **Nine of the sixteen candidates
can move this benchmark by more than its noise floor** --- and only three
of the nine ever do it in the right direction: `inline(always)`,
`unroll.count=4` and `vectorize.width=16`. The other six are levers for
making the program slower.

**Dead** --- never cleared the MDE anywhere:

| candidate | why |
|---|---|
| `align=16` | 8 of 8 arms built a binary identical to the baseline. x86-64 already aligns functions to 16, which the vocabulary's own description says. |
| `align=32`, `align=64` | 6 of 8 identical (the kernel has no out-of-line copy to align); the two `layout` arms on k2 and k6 moved the symbol exactly as asked and moved the clock by at most 0.7%, unconfirmed. |
| `interleave.count=4` | 4 of 4 identical: it is what LoopVectorize already picks for every vectorised loop here. |
| `unroll.count=2`, `unroll.count=8` | `=8` reproduces the default on k3 (identical) and nothing either does anywhere clears 3%. |
| `vectorize.width=8` | VF 8 is already the baseline's choice at every vectorised site. |

Seven of the sixteen candidates in vocabulary v3 are, on this target, ways
of telling LLVM what it has already decided.

### Three findings the scorecard does not carry

**(a) `inline(always)` is the one function attribute that can win, and it
won bigger than anything else in this project.** EXPECTED.md's mechanism for
K2 is confirmed instruction for instruction: round 6's binary has **60 fewer
`imul`** --- exactly the 60-round dependency chain --- because `mode` is a
literal at both call sites, so `m = (mode & 7) | 1` folds to a constant and
the 3-cycle register multiply becomes a `lea` pair. That accounts for about
1.25x of the 1.68x (5 cycles per round to 4 on the chain); the rest is the
call being removed and the two inlined copies being scheduled in place, and
was not measured separately. `k2_mix` disappears from the symbol table, and
the dump and the normalised-code comparison both handled the callee
vanishing --- the robustness case decision 77 flagged.

**(b) `unroll.disable` and `interleave.count=1` are the same instruction to
a vectorised loop.** On k5 they produce the same instruction count (6
`vpmulld` against the baseline's 16) and the same ratio: 0.2941 and 0.2957.
On k4 and k8 likewise (0.7309 / 0.7301 and 0.8226 / 0.8033). LoopVectorize
reads `llvm.loop.unroll.disable` and refuses to interleave, so on an
already-vectorised site **one of these two arms is a duplicate
measurement** --- 8 wasted arms of this sweep's 44, and the same waste
waits in jaq's 176-arm loop half. On k3, whose loop the vectoriser refuses,
they are properly different: `unroll.disable` reaches the unroller (−29.4%)
and `interleave.count=1` is inert (identical build), exactly as EXPECTED.md
said it should be.

*The dump cannot tell you which sites those are.* `sites.json` records
`already_vectorized: false` for all four hintbench loop sites, including
k4, k5 and k8, whose remarks say "vectorized loop (vectorization width: 8,
interleaved count: 4)". The field is read at `VectorizerStartEP`, before
the vectoriser runs, so it can only mean "this loop already carries
`llvm.loop.isvectorized` metadata", never "this loop will be vectorised"
--- the same reading decision 83 (b) arrived at independently, from the
state side, while this sweep was running. It cannot be used to predict the
duplicate arms on jaq.

**(c) A wider vector width can add chains rather than trade them, and
EXPECTED.md ruled that out for the wrong reason.** Sections 1 K4 and 1 K5
both argue that "a forced width of 16 cannot add bandwidth, it can only
trade lanes against interleaving". On k5 --- a latency-bound multiplicative
reduction --- that is false: round 48's binary has **15 `ymm vpmulld`
against the baseline's 8**, because VF 16 on u32 is two `ymm` per vector
and with IC 4 that is roughly eight independent chains instead of four.
Result: +2.65%, confirmed, and the largest confirmed gain on k5. On k4 ---
byte counting, bandwidth-bound --- the same argument is correct, and width
16 costs 42%. So the prediction survived at both kernels (under the MDE
gate) while the reasoning behind it was right at one and wrong at the
other, in opposite directions.

**And the control kernel was not a control.** K8's prediction was "every
hint <= 0%. If any hint wins here by more than the noise floor, the noise
floor is wrong." `vectorize.width=16` wins there by **+8.8%**, confirmed in
two batches, +7.0% inside the combination and +5.8% in the holdout batch.
The noise floor is not wrong --- four independent batches and a
two-batch confirmation say so. What is wrong is the premise that a
store-limited unit-stride loop at VF 8 x IC 4 has nothing left to give.

## 10. Wall clock, cost, deviations

```
null panels, two batches of four labels               7 min
84 one-factor arms + 1 combination arm             3 h 49 min  (16:39-20:28 JST)
   of which 39 skipped as identical (9.6 s each)      6 min
   46 measured arms, 290 s each on average
   38 of them carrying a second, confirmation batch
holdout batch, four labels                            4 min
```

**About 4.1 hours in total, 0 API calls, $0.** The brief expected 2--3
hours; the design estimate in results.md 108 ("roughly 2 minutes per arm")
counted two timing labels and no per-arm confirmation, and the real batch
is three labels over eight 350 ms workloads, 432 executions, 2.5 minutes.
The no-op skip took about 3.1 hours off that.

Deviations, all recorded before the run:

* **The settle gap is 0 ms, not the 250 ms in the brief.** 250 ms is jaq's
  frozen value; hintbench inherits the default and has since the target was
  written. Changing it would have changed the target's recipe mid-project.
  The null panels were measured under the same 0 ms and are the evidence
  that it is good enough here.
* **`taskset -c 8`, not `-c 4`.** CPU 8 *is* physical core 4 on this
  machine (`target_common.sh`: "Core 4 (CPU 8, SMT sibling CPU 9 left
  idle)"), and cores 1--3 belong to the other targets.
* **The holdout is the same eight workloads** (section 8).
* The combination arm was selected by the confirmed-in-two-batches rule; on
  this target that rule and the one-batch rule it replaces chose the same
  six sites, so nothing here tests the difference between them.
* Arms 6 and 85 were accepted under the acceptance rule (all four
  conditions, confirmation included). The frozen `best` is arm 85.
