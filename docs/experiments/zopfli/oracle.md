# The zopfli oracle

The one-factor sweep of SPEC.ja.md 2 over `targets/zopfli`: every candidate of
vocabulary v6, alone, at every one of the 6 marked functions and the 5 loop
sites of `oracle.selected_keys_top6`, with every other site at
`KEEP_DEFAULT`, plus one combination arm. 67 one-factor arms + 1.

It exists to give the §167 Jev-vs-random comparison its ground truth on a
real program: which hints in the frozen vocabulary move zopfli at all, in
which direction, and how far above the PGO + fat-LTO baseline the best of
them can get.

Numbers and the full per-arm table are `results.md` §168; the protocol and
the rules were pre-registered in `results.md` §165-§166 before the first arm
ran. This document is the readable version. Copies of the run's own
artifacts are in `oracle/` next to it (see the end).

## 1. Protocol (pre-registered, `results.md` §166)

| | |
|---|---|
| target | `zopfli`, PGO baseline, `.text` sha256 `9aca86fc...` (identical to Stage 0, §165) |
| baseline binary | `artifacts/zopfli-sites/baseline/bin`, sha256 `8b0ba235...`, stripped `79c33226...` |
| flags | `-Copt-level=3 -Ctarget-cpu=native -Clto=fat -Ccodegen-units=1` + PGO (profdata `f066f507...`), `-Cllvm-args=-hints-allow-reordering=false` on every arm |
| case set | training = `search-{text,binary,json}.dat` (896 KiB each, decision 98); holdout `hold-*.dat` measured once at the end |
| repetitions | 15, warmup 3; three labels per batch (`base`, `cand`, in-run `aa`) |
| pinning | CPU 2, gap 0 ms, stdout pipe |
| argv0 | every label's path 80 bytes, class 96 (decision 97) |
| vocabulary | v6 (decision 98): functions `inline_always`, `inline_never`; loops `unroll_count_{2,4,8}`, `unroll_disable`, `vectorize_width_{2,4,8,16}`, `interleave_count_{1,2,4}` |
| marks | 6 (`targets/zopfli/jev-marks.txt`, 93.4% of in-binary cycles on the search set) |
| loop sites | 5: `lz77.rs:530`, `squeeze.rs:275`, `squeeze.rs:325`, `lz77.rs:563` (the only vectorized one, VF 16 / IC 4), `index.rs:184` |

**Rules.** Correctness: all nine `.gz` sha256 identical to the baseline's,
or the arm is rejected. No-op skip: an arm whose build is `identical`
(normalised instructions and symbol table) is not timed, ratio 1.0 by
construction. Confirmation: an arm whose first batch CI excludes 1 is
re-measured in an independent batch (fresh seed); it is *sign-confirmed* if
both exclude 1 with the same sign (decision 80 (a)). **Good** =
sign-confirmed positive and the gain exceeds the batch MDE in both batches;
**harmful** = the same on the loss side; MDE = `max(2 x worst per-workload
half-width, 3%)` per batch. Combination = each site's best sign-confirmed arm
with ratio > 1.

**Prediction, stated before the run (§166).** The four unvectorized loops are
likely flat under loop-metadata hints; `inline(always)` / `inline(never)` on
the six marks is where a result, if any, is more likely to appear.

**A known limitation, stated before the run (§166 §3).** Stage 0's only
global win, `-unroll-max-count=1` (+1.6%), acted through `cache.rs:108`,
which is capped out of this site set (and `try_get` is outside the marks).
This oracle cannot measure that site.

A field-name warning for anyone reading `rounds.jsonl`: `confirmed` there is
the *own-kernel* confirmation and is `false` on all 68 rows (zopfli has no
per-site kernels). The two-batch sign rule is `confirmed_aggregate`.

## 2. The null panel

The A/A panels of §165 (three stripped copies of the baseline, 18 rounds,
class 96): training aggregate aa 1.0017 [0.9983, 1.0049], aa2 1.0005
[0.9960, 1.0043], worst per-workload half-width 0.92%; holdout aa 1.0004,
aa2 0.9995, worst half-width 0.39%. Both give MDE = 3% (the floor).

Inside the sweep, the in-run A/A label excluded 1 in **0 of 30** round
batches and **1 of 22** confirmation batches (round 15's, 1.0037 [1.0006,
1.0066]). Worst round-batch A/A half-width 0.83% (round 50). zopfli's
intervals are honest at the aggregate --- hintbench's shape, not jaq's.

## 3. The sweep

`scripts/jev_search.py ... --proposer oracle --oracle-phase all --vocab v6`,
2026-09-23 22:21 to 2026-09-24 06:07 JST, with an interruption (section 7).
No API calls.

| | |
|---|--:|
| one-factor arms | 67 |
| correctness held | 67 of 67, and the combination |
| builds identical to the baseline (not timed) | **38** |
| builds that changed instructions | 29 |
| arms whose first batch excluded 1 (confirmation run) | 21 |
| sign-confirmed in two batches | 17 (4 +, 13 -) |
| **good** (confirmed +, above MDE) | **0** |
| **harmful** (confirmed -, beyond MDE) | **2** |
| wall clock of the rounds (sum of `wall_s`) | 4.40 h |

**The no-op skip removed more than half the sweep.** 38 of the 67 arms built
the baseline: 4 of the 12 function arms, 34 of the 55 loop arms. Every width,
every interleave count and `unroll_disable` on all four unvectorized loops
(32 arms) changed nothing. The vectorizer does not take those loops at any
forced width, and LLVM is not unrolling them, so there is nothing for
`unroll.disable` to stop. At the vectorized `lz77.rs:563`, width 16 and
interleave 4 are the baseline's own choice and are identical too. The four
identical function arms are the attribute each function already has in
effect: `find_longest_match_loop` and `lz77_optimal` are not inlined
(`inline_never` is a no-op); `get_best_lengths` and `lz77_optimal_run` are
fully inlined, with no post-LTO symbol (`inline_always` is a no-op). A
skipped arm cost 29 s against 295-562 s for a timed one.

**The only candidates that reach code at an unvectorized loop are
`unroll.count=2/4/8`**, i.e. more unrolling. They produced both the sweep's
gains and its only harmful arms.

## 4. Scorecard

| dimension | arms | identical | changed code | sign-confirmed + | sign-confirmed - | good | harmful |
|---|--:|--:|--:|--:|--:|--:|--:|
| `inline_always` | 6 | 2 | 4 | 0 | 3 | 0 | 0 |
| `inline_never` | 6 | 2 | 4 | 0 | 4 | 0 | 0 |
| `unroll_count_{2,4,8}` | 15 | 0 | 15 | 4 | 6 | 0 | 2 |
| `unroll_disable` | 5 | 4 | 1 | 0 | 0 | 0 | 0 |
| `vectorize_width_*` | 20 | 17 | 3 | 0 | 0 | 0 | 0 |
| `interleave_count_*` | 15 | 13 | 2 | 0 | 0 | 0 | 0 |
| **total** | **67** | **38** | **29** | **4** | **13** | **0** | **2** |

Best per site among the sign-confirmed positive arms:
`squeeze.rs:325` -> `unroll_count_8` (+1.26% / +1.29%);
`lz77.rs:563` -> `unroll_count_8` (+0.50% / +0.40%). No function mark and no
other loop has a sign-confirmed positive arm.

## 5. Per site

`1.0000*` is the no-op skip: ratio 1.0 by construction, never measured.
Per case = the round batch. `confirm` = the confirmation batch and whether
the two batches agree in sign.

### `zopfli::lz77::find_longest_match_loop`

| arm | candidate | build vs baseline | changed syms | ratio | 95% CI | confirm | text | binary | json | verdict |
|--:|---|---|--:|--:|---|---|--:|--:|--:|---|
| 1 | `inline_always` | code | 5 | 0.9932 | [0.9901, 0.9963] | 0.9909 [0.9878, 0.9939] **yes (-)** | 0.9896 | 0.9986 | 0.9915 | flat (-, < MDE) |
| 2 | `inline_never` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |

### `zopfli::squeeze::lz77_optimal`

| arm | candidate | build vs baseline | changed syms | ratio | 95% CI | confirm | text | binary | json | verdict |
|--:|---|---|--:|--:|---|---|--:|--:|--:|---|
| 3 | `inline_always` | code | 6 | 0.9874 | [0.9846, 0.9902] | 0.9876 [0.9851, 0.9902] **yes (-)** | 0.9828 | 0.9867 | 0.9927 | flat (-, < MDE) |
| 4 | `inline_never` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |

### `zopfli::squeeze::get_best_lengths`

| arm | candidate | build vs baseline | changed syms | ratio | 95% CI | confirm | text | binary | json | verdict |
|--:|---|---|--:|--:|---|---|--:|--:|--:|---|
| 5 | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 6 | `inline_never` | code | 9 | 0.9799 | [0.9764, 0.9832] | 0.9783 [0.9755, 0.9812] **yes (-)** | 0.9866 | 0.9681 | 0.9851 | flat (-, < MDE) |

### `zopfli::squeeze::lz77_optimal_run`

| arm | candidate | build vs baseline | changed syms | ratio | 95% CI | confirm | text | binary | json | verdict |
|--:|---|---|--:|--:|---|---|--:|--:|--:|---|
| 7 | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 8 | `inline_never` | code | 8 | 0.9779 | [0.9718, 0.9842] | 0.9817 [0.9773, 0.9863] **yes (-)** | 0.9801 | 0.9824 | 0.9711 | flat (-, < MDE) |

### `<zopfli::hash::ZopfliHash>::update`

| arm | candidate | build vs baseline | changed syms | ratio | 95% CI | confirm | text | binary | json | verdict |
|--:|---|---|--:|--:|---|---|--:|--:|--:|---|
| 9 | `inline_always` | code | 4 | 0.9999 | [0.9958, 1.0041] | not triggered | 1.0012 | 0.9996 | 0.9987 | flat |
| 10 | `inline_never` | code | 3 | 0.9914 | [0.9894, 0.9936] | 0.9967 [0.9944, 0.9992] **yes (-)** | 0.9980 | 0.9840 | 0.9923 | flat (-, < MDE) |

### `zopfli::lz77::find_longest_match`

| arm | candidate | build vs baseline | changed syms | ratio | 95% CI | confirm | text | binary | json | verdict |
|--:|---|---|--:|--:|---|---|--:|--:|--:|---|
| 11 | `inline_always` | code | 8 | 0.9799 | [0.9754, 0.9851] | 0.9796 [0.9770, 0.9822] **yes (-)** | 0.9862 | 0.9680 | 0.9855 | flat (-, < MDE) |
| 12 | `inline_never` | code | 9 | 0.9777 | [0.9753, 0.9803] | 0.9732 [0.9706, 0.9760] **yes (-)** | 0.9842 | 0.9674 | 0.9816 | flat (-, < MDE) |

### `zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1`

| arm | candidate | build vs baseline | changed syms | ratio | 95% CI | confirm | text | binary | json | verdict |
|--:|---|---|--:|--:|---|---|--:|--:|--:|---|
| 13 | `unroll_count_2` | code | 1 | 0.9856 | [0.9836, 0.9876] | 0.9879 [0.9854, 0.9904] **yes (-)** | 0.9821 | 0.9932 | 0.9816 | flat (-, < MDE) |
| 14 | `unroll_count_4` | code | 1 | 0.9943 | [0.9886, 0.9998] | 0.9914 [0.9881, 0.9946] **yes (-)** | 0.9908 | 0.9990 | 0.9930 | flat (-, < MDE) |
| 15 | `unroll_count_8` | code | 1 | 0.9906 | [0.9865, 0.9942] | 0.9939 [0.9902, 0.9981] **yes (-)** | 0.9913 | 0.9899 | 0.9906 | flat (-, < MDE) |
| 16 | `vectorize_width_2` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 17 | `vectorize_width_4` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 18 | `vectorize_width_8` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 19 | `vectorize_width_16` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 20 | `interleave_count_1` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 21 | `interleave_count_2` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 22 | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 23 | `unroll_disable` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |

### `zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2`

| arm | candidate | build vs baseline | changed syms | ratio | 95% CI | confirm | text | binary | json | verdict |
|--:|---|---|--:|--:|---|---|--:|--:|--:|---|
| 24 | `unroll_count_2` | code | 1 | 0.9843 | [0.9827, 0.9860] | 0.9868 [0.9842, 0.9896] **yes (-)** | 0.9811 | 0.9878 | 0.9839 | flat (-, < MDE) |
| 25 | `unroll_count_4` | code | 1 | 0.9639 | [0.9595, 0.9677] | 0.9668 [0.9647, 0.9689] **yes (-)** | 0.9550 | 0.9776 | 0.9591 | **harmful** |
| 26 | `unroll_count_8` | code | 1 | 0.9169 | [0.9149, 0.9189] | 0.9156 [0.9127, 0.9185] **yes (-)** | 0.9000 | 0.9592 | 0.8931 | **harmful** |
| 27 | `vectorize_width_2` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 28 | `vectorize_width_4` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 29 | `vectorize_width_8` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 30 | `vectorize_width_16` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 31 | `interleave_count_1` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 32 | `interleave_count_2` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 33 | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 34 | `unroll_disable` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |

### `zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3`

| arm | candidate | build vs baseline | changed syms | ratio | 95% CI | confirm | text | binary | json | verdict |
|--:|---|---|--:|--:|---|---|--:|--:|--:|---|
| 35 | `unroll_count_2` | code | 1 | 1.0095 | [1.0056, 1.0133] | 1.0100 [1.0048, 1.0148] **yes (+)** | 1.0123 | 1.0056 | 1.0107 | flat (+, < MDE) |
| 36 | `unroll_count_4` | code | 1 | 1.0072 | [1.0034, 1.0110] | 1.0049 [1.0013, 1.0086] **yes (+)** | 1.0133 | 0.9962 | 1.0121 | flat (+, < MDE) |
| 37 | `unroll_count_8` | code | 1 | 1.0126 | [1.0096, 1.0154] | 1.0129 [1.0099, 1.0158] **yes (+)** | 1.0176 | 1.0034 | 1.0168 | flat (+, < MDE) |
| 38 | `vectorize_width_2` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 39 | `vectorize_width_4` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 40 | `vectorize_width_8` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 41 | `vectorize_width_16` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 42 | `interleave_count_1` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 43 | `interleave_count_2` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 44 | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 45 | `unroll_disable` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |

### `zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2`

| arm | candidate | build vs baseline | changed syms | ratio | 95% CI | confirm | text | binary | json | verdict |
|--:|---|---|--:|--:|---|---|--:|--:|--:|---|
| 46 | `unroll_count_2` | code | 1 | 1.0041 | [1.0016, 1.0068] | 1.0023 [0.9991, 1.0052] no | 1.0071 | 1.0023 | 1.0029 | flat |
| 47 | `unroll_count_4` | code | 1 | 1.0044 | [1.0020, 1.0068] | 1.0020 [0.9992, 1.0050] no | 1.0039 | 0.9997 | 1.0096 | flat |
| 48 | `unroll_count_8` | code | 1 | 1.0050 | [1.0011, 1.0089] | 1.0040 [1.0005, 1.0082] **yes (+)** | 1.0068 | 0.9983 | 1.0098 | flat (+, < MDE) |
| 49 | `vectorize_width_2` | code | 1 | 0.9997 | [0.9968, 1.0025] | not triggered | 0.9987 | 0.9993 | 1.0013 | flat |
| 50 | `vectorize_width_4` | code | 1 | 0.9935 | [0.9850, 1.0000] | 1.0013 [0.9969, 1.0059] no | 1.0011 | 0.9942 | 0.9855 | flat |
| 51 | `vectorize_width_8` | code | 1 | 0.9981 | [0.9947, 1.0014] | not triggered | 0.9975 | 0.9950 | 1.0018 | flat |
| 52 | `vectorize_width_16` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 53 | `interleave_count_1` | code | 1 | 1.0010 | [0.9963, 1.0059] | not triggered | 1.0020 | 1.0016 | 0.9995 | flat |
| 54 | `interleave_count_2` | code | 1 | 0.9997 | [0.9946, 1.0045] | not triggered | 1.0066 | 0.9952 | 0.9973 | flat |
| 55 | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 56 | `unroll_disable` | code | 1 | 0.9980 | [0.9933, 1.0029] | not triggered | 0.9969 | 0.9984 | 0.9986 | flat |

### `<zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1`

| arm | candidate | build vs baseline | changed syms | ratio | 95% CI | confirm | text | binary | json | verdict |
|--:|---|---|--:|--:|---|---|--:|--:|--:|---|
| 57 | `unroll_count_2` | code | 1 | 0.9978 | [0.9926, 1.0031] | not triggered | 1.0005 | 0.9954 | 0.9976 | flat |
| 58 | `unroll_count_4` | code | 1 | 0.9948 | [0.9898, 0.9997] | 0.9966 [0.9916, 1.0013] no | 0.9997 | 0.9948 | 0.9898 | flat |
| 59 | `unroll_count_8` | code | 1 | 0.9977 | [0.9939, 1.0014] | not triggered | 0.9977 | 0.9982 | 0.9973 | flat |
| 60 | `vectorize_width_2` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 61 | `vectorize_width_4` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 62 | `vectorize_width_8` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 63 | `vectorize_width_16` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 64 | `interleave_count_1` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 65 | `interleave_count_2` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 66 | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |
| 67 | `unroll_disable` | **identical** | 0 | 1.0000* | by construction | n/a | - | - | - | no-op |

## 6. The combination arm, on training and on the holdout

The rule picks each site's best sign-confirmed arm with ratio > 1: two loops,
`squeeze.rs:325 unroll_count_8` and `lz77.rs:563 unroll_count_8`, both
sub-MDE (the one-batch and point-estimate rules pick the same two). Plan:
`oracle/combination-plan.json`. Two symbols changed, output identical.

| batch | aggregate | 95% CI | text | binary | json | A/A | MDE |
|---|--:|---|--:|--:|--:|---|--:|
| training, round | **1.0181** | [1.0159, 1.0203] | 1.0193 | 1.0094 | 1.0257 | 1.0011 +-0.0019 | 3% |
| training, confirmation | **1.0206** | [1.0155, 1.0287] | 1.0199 | 1.0068 | 1.0354 | 1.0003 +-0.0033 | 3.73% |

The parts multiply to +1.77%; the combination is +1.81% / +2.06%. Unlike
jaq (independent +6.96%, measured +0.17%), the parts add up: two different
loops in two different functions, both real.

**Holdout panel**, one batch after the arms were frozen
(`scripts/bench_panel.sh`, holdout cases, 15 rounds, warmup 3, CPU 2, seed
20260924, class 96 on all four labels; `oracle/holdout-stats.md`):

| label | aggregate | 95% CI | text | binary | json |
|---|--:|---|--:|--:|--:|
| aa | 0.9998 | [0.9979, 1.0018] | 0.9993 | 1.0011 | 0.9989 |
| **comb** (round 68) | **1.0177** | [1.0163, 1.0193] | 1.0224 | 1.0033 | 1.0276 |
| **bestloop** (round 37, `squeeze.rs:325 unroll_count_8`) | **1.0133** | [1.0116, 1.0151] | 1.0184 | 1.0025 | 1.0191 |

MDE for this batch: worst half-width 0.40% -> 3%. There is no best-function
label: no function arm was sign-confirmed positive (`holdout-picks.json`:
`"fn": null`), so the fourth label §166 planned had nothing to carry.

The holdout reproduces training almost to the decimal (comb +1.77% vs
+1.81% / +2.06%; bestloop +1.33% vs +1.26% / +1.29%), text and json carry
it, binary barely moves. **Real, transferring, and below the MDE in every
batch: not "good".**

## 7. Interruption

Rounds 1-67 ran 22:21:48-02:35:44 JST. The log stops at 02:36 during round
68's first timing batch (built, correctness OK, `code`, 2 symbols changed).
Windows/WSL rebooted at 05:53 JST. A stale `artifacts/timing-run/8954fa25`
argv0-alias directory was removed, and at 05:57 the same command was re-run
with `--resume`: `67 rounds already recorded (0 of them lost)`. Only round 68
was rebuilt and re-timed; nothing else was re-measured.

Comparability: same plan signature (`c905f2b9...`), same code class and
changed-symbol count as the pre-reboot log line, the in-batch base copy
hashes to the same stripped baseline `79c33226...` as all 52 base copies of
the run, class 96, quiet in-run A/A. The pre-reboot binary's sha was never
logged and was overwritten, so "the same binary" rests on build determinism
rather than a direct comparison; the pre-reboot timing never completed, so
there is nothing to compare it against. The ratio is within one post-reboot
batch.

## 8. What the zopfli oracle says, plainly

* **Nothing in vocabulary v6, at these 6 marks and 5 loops, makes zopfli
  faster by 3% or more.** Good arms: 0 of 67. The ceiling --- the
  combination --- is +1.8% on training and on the holdout.
* **There is a real, small, transferring lever**: unrolling
  `squeeze.rs:325` (the per-length cost loop in `get_best_lengths`, trip
  ~9) by 8 gives +1.3%, the same size in four batches over two input sets.
  This protocol does not call it an effect, and this document does not
  either.
* **The pre-registered prediction did not hold.** The loop dimension,
  predicted flat, holds every arm that cleared the MDE and every
  sign-confirmed gain; the inline dimension, predicted as the likely source
  of a result, produced none. What did hold: width, interleave and
  `unroll.disable` are no-ops on all four unvectorized loops (32 of 32).
  `unroll.count` was not flat: it holds both the only
  gains and the only harmful arms (`squeeze.rs:275`, the outer
  `while i < inend` loop, -3.6% at 4x and -8.3% at 8x). Forced inlining,
  where a result was expected, moved code in 8 of 12 arms and helped in
  none: 7 sign-confirmed losses of 0.3-2.7%, in both directions. The
  baseline's inlining of these six functions is, as far as this vocabulary
  can see, already right.
* **Stage 0's +1.6% has no counterpart here.** It came from *less*
  unrolling of `cache.rs:108`; `unroll_disable` was a no-op or flat at every
  site this sweep reached, and the best arm is *more* unrolling at a
  different loop. `cache.rs:108` is outside the site set by the cap rule, so
  the reason v6 exists (decision 98) is untested, not refuted.
* **For §167**: check (a) is void (no good site); the harmful set for (b) is
  `squeeze.rs:275 unroll_count_4/8`; flat sites for (c) are every site but
  `squeeze.rs:275`. With a ceiling under the MDE, §167's effect rule cannot
  be met by the difference this oracle allows; the expected headline is
  "not resolved at n=3", "flat; correct no-ops".

## 9. Files

`oracle/` (copies; the originals are under the git-ignored
`artifacts/zopfli-search/`):

| file | what |
|---|---|
| `summary.md` | the driver's round table |
| `manifest.json` | `run-manifest.json`: provenance, best plan, batches |
| `holdout-picks.json` | what the holdout panel carried and why (`fn: null`) |
| `holdout-stats.md` | the holdout panel's `stats.md` |
| `combination-plan.json` | round 68's `plan-b.json` |
| `oracle-run.part1.log` | rounds 1-67, ends at 02:36 inside round 68 |
| `oracle-run.log` | part 1 + the resumed round 68 |
