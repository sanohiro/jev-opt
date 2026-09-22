# Experiment 4 (hintbench): Jev with feedback against random

Five rounds of `scripts/jev_search.py --proposer jev`, against five rounds of
`--proposer random`, over `targets/hintbench`, whose ground truth
`docs/experiments/hintbench/oracle.md` measured arm by arm. This is the
experiment the project is named after --- "Jev がいろいろやる": the proposer
is shown what its own earlier rounds measured and is asked again.

The three things it is here to answer:

1. does a proposer that is told the result of its last plan choose
   differently from one that is not, and differently from chance;
2. how much of the oracle's own combination (+8.8% training) does either
   reach;
3. does the pre-registered gate stop a harmful plan --- Jev's one-shot
   answer at k4 was `vectorize.width=16`, which the oracle measured at
   **−42%** on that kernel (decision 87).

## 1. Protocol

### 1.1 What is frozen, and is the oracle's

Everything in `oracle.md` 1.1, unchanged and reused, so that a round of this
experiment and an arm of the sweep are the same measurement:

| | |
|---|---|
| target | `hintbench`, PGO baseline |
| baseline | `artifacts/hintbench-sites/baseline` (`--baseline-dir`), the same `JEV_MODE=dump` build every oracle arm resolved its keys against |
| marks | `targets/hintbench/jev-marks.txt`, 8 |
| site set | `oracle.selected_keys_loop_hint_kernels`, the frozen 8 functions + 4 loops, pre-registered in `scripts/hintbench_oracle.sh` |
| case set | the eight kernel workloads `k1`..`k8`; no `TRAIN_WORKLOADS`, so every artifact says `holdout-as-search` |
| repetitions | 15, warmup 3, shuffled label order, seed 20260921 + round |
| pinning | `taskset -c 8` = physical core 4 |
| settle gap | **0 ms**, hintbench's frozen value |
| bootstrap | 10000 resamples, paired on the round |
| vocabulary | **v4** (`--vocab v4`), `--source-comments strip`, `--readout forced_top1`, `min_confidence 0.0` |
| acceptance | the four pre-registered conditions: correct output, every plan entry took effect, CI lower bound above the incumbent's point estimate, and **confirmed in a second independent batch** |
| no-op skip | on: a build identical to the baseline is recorded at ratio 1.0 and not timed |
| rounds | 5 per proposer |
| random seed | `[evaluation] seed` 20260921, drawn as `Random("20260921\|<round>\|<phase>")` --- deterministic and reproducible |

Neither proposer sees the oracle. Random does not see the history either:
it is the control for "does the feedback do anything", not a second
learner.

### 1.2 Three batches, as the oracle had

1. the round's own batch (seed 20260921 + round);
2. the **confirmation** batch of decision 80 (a), fired whenever the round's
   interval excludes 1, over the same two binaries with a fresh seed
   (20260921 + 100000 + round). Acceptance requires it;
3. the **third batch**, `--measure-holdout`. hintbench declares no training
   split, so this is the same eight workloads measured once more,
   independently, after the best plan is frozen --- exactly what
   `oracle.md` 8 did for the combination arm. It is a third batch, not a
   generalisation test.

### 1.3 How the plans are scored (`scripts/hintbench_exp4_score.py`)

Per site, against the oracle's own `rounds.jsonl` --- never a transcription
of it:

* **truth at a site** = the arm there with the highest ratio on that site's
  own kernel workload among the arms **confirmed in two batches with a
  positive sign** *and* clearing their own batch's MDE; `KEEP_DEFAULT`
  where nothing qualifies. This is decision 87's rule, so the numbers here
  are comparable with the 7/8 and 0/4 recorded there. It reproduces
  decision 87's twelve truths exactly.
* **exact / same-family / miss** as `oracle.md` 2. `unroll.disable` is in
  the unroll family; `inline(always)` against `inline(never)` is the
  opposite direction and is a miss.
* **harmful** is separate and deliberately looser, per the brief: a pick
  whose own oracle arm was **confirmed below 1**, MDE or no MDE. A pick can
  be a miss and harmful, or a miss and merely inert.
* **share of the oracle combination** = `(plan − 1) / (combination − 1)`
  on like batches: a training round against the combination's 1.0881, a
  third batch against the combination's own third batch, 1.0847. The
  combination was selected by the *looser* rule (confirmed positive, no MDE
  gate), so it also carries the sub-MDE gains at the k4 function site and
  the k5 loop that the scoring rule above calls `KEEP_DEFAULT`: a plan can
  score 12/12 exact and still fall short of 100%.

The twelve truths, as the script derives them:

| site | kind | kernel | truth (MDE-gated) | ratio | truth (no MDE gate) | ratio | harmful candidates |
|---|---|---|---|--:|---|--:|---|
| `fn:hbkernels::k1_step` | fn | k1 | `KEEP_DEFAULT` | - | `KEEP_DEFAULT` | - | `inline_never` 0.9545 |
| `fn:hbkernels::k2_mix` | fn | k2 | `inline_always` | 1.6775 | `inline_always` | 1.6775 | (none) |
| `fn:hbkernels::k3_fill_run` | fn | k3 | `KEEP_DEFAULT` | - | `KEEP_DEFAULT` | - | `inline_never` 0.8294 |
| `hbkernels::k3_fill_run@lib.rs:174:9#d3` | loop | k3 | `unroll_count_4` | 1.0436 | `unroll_count_4` | 1.0436 | `unroll_disable` 0.7056 |
| `fn:hbkernels::k4_count_bytes` | fn | k4 | `KEEP_DEFAULT` | - | `inline_never` | 1.0152 | (none) |
| `hbkernels::k4_count_bytes@macros.rs:180:28#d2` | loop | k4 | `KEEP_DEFAULT` | - | `unroll_count_4` | 1.0053 | `interleave_count_1` 0.7301, `interleave_count_2` 0.9396, `unroll_count_2` 0.9848, `unroll_disable` 0.7309, `vectorize_width_16` 0.5793, `vectorize_width_2` 0.2024, `vectorize_width_4` 0.6744 |
| `fn:hbkernels::k5_mul_reduce` | fn | k5 | `KEEP_DEFAULT` | - | `KEEP_DEFAULT` | - | `inline_never` 0.9916 |
| `hbkernels::k5_mul_reduce@macros.rs:180:28#d2` | loop | k5 | `KEEP_DEFAULT` | - | `vectorize_width_16` | 1.0265 | `interleave_count_1` 0.2957, `interleave_count_2` 0.5953, `unroll_count_2` 0.9872, `unroll_disable` 0.2941, `vectorize_width_2` 0.2791, `vectorize_width_4` 0.5568, `vectorize_width_8` 0.9950 |
| `fn:hbkernels::k6_hot_loop` | fn | k6 | `KEEP_DEFAULT` | - | `KEEP_DEFAULT` | - | (none) |
| `fn:hbkernels::k7_error_path` | fn | k7 | `KEEP_DEFAULT` | - | `KEEP_DEFAULT` | - | (none) |
| `fn:hbkernels::k8_scale_add` | fn | k8 | `KEEP_DEFAULT` | - | `KEEP_DEFAULT` | - | (none) |
| `hbkernels::k8_scale_add@range.rs:1103:12#d2` | loop | k8 | `vectorize_width_16` | 1.0881 | `vectorize_width_16` | 1.0881 | `interleave_count_1` 0.8033, `interleave_count_2` 0.9456, `unroll_disable` 0.8226, `vectorize_width_2` 0.4467, `vectorize_width_4` 0.9171 |

### 1.4 Two driver changes, made before round 1

Both are recorded here because they are conditions of the measurement, and
both are in the commit that opens this document.

**(a) The feedback the experiment is about did not exist.** The round
history in the state carried the **aggregate** ratio only, and a site's own
history line carried the whole-build ratio only. On this target the
aggregate is the geometric mean of eight kernels, so the −42% that
`vectorize.width=16` costs at k4 arrives in the state as −6% of a number
that names no site --- the proposer could not have attributed it even in
principle. `record_batch` now keeps **every** case's ratio and 95% CI (it
kept only the arm's own kernel, and a search round has no single arm, so
for `--proposer jev|random` it kept none), `render_history` prints a
per-case table beside the aggregate one, and `site_history_lines` quotes
the site's own case, its CI, and whether the round was accepted. A round's
outcome is also spelled out now ("this build was instruction-for-
instruction the baseline, so it was not timed") instead of a bare `-`.

The state format is bumped for it, per decision 19: `state-v3.2-2026-09-22`
and `state-v4.1-2026-09-22`. Nothing else in the state moves --- candidates,
descriptions, questions, verdict blocks and source excerpts are v3.1's and
v4's to the byte --- and on a target with no per-case readout (jaq, zopfli,
oxipng: `own_workload_of` returns `None` there) the only difference is the
header line and the new outcome column.

**Round 1 is therefore the one-shot control.** Round 1 has no history, so
its state is the state `jev-oneshot-v4.md` sent. Diffed against the state
recorded in `docs/experiments/hintbench/jev-oneshot-v4.jsonl`:

```
phase A   1 changed line, the header:
  - state format state-v4-2026-09-22    +  state format state-v4.1-2026-09-22
          questions: identical
phase B   that line, and the four sites' "function attributes this round
          already applied", which says `none` in the one-shot because it
          builds nothing (jev-oneshot-v4.md records that as its one
          departure from a real round) and names k2 and k6 here, because
          phase A really applied them
          questions: identical
```

Round 1's answers are the one-shot's answers at all twelve sites.

**(b) A 503 burst cost a whole round.** Decision 87 recorded a gateway 503
burst that exhausted all three internal retries on both phases of one
repeat; `scripts/jev_oneshot.py` already re-sent such a request **unchanged**
and kept both lines in the JSONL, and `jev_search.py` did not --- a phase
whose every answer is `no answer` becomes all-`KEEP_DEFAULT` with no
probabilities, so `forced_top1` cannot fire either and the round rebuilds
the baseline. One round in five is 20% of the run. `JevProposer.choose` now
does what the one-shot harness does. **It fired on rounds 1 and 2 of this
very run**, both times on phase A, each after three consecutive 503s, and
both the exhausted line and the `A.retry` are in the JSONL.

No request is ever modified to make it succeed.

## 2. Run 1: Jev, five rounds, feedback on

`artifacts/hintbench-search/jev-v4-r5/`, 20:55--21:24 JST, **29.0 min**.
Every round: output correct, every plan entry applied, no `ambiguous`, no
`vanished`, no `unmatched`, code class `code` with 3 symbols changed.

### 2.1 The rounds

| round | phase A (functions) | phase B (loops) | readout | ratio | 95% CI | confirm | A/A | accepted |
|---|---|---|---|--:|---|---|--:|---|
| 1 | k2 `inline(always)`, k6 `inline(always)` | k4 `vectorize.width=16`, k5 `vectorize.width=8`, k8 `vectorize.width=8` | argmax | **0.9931** | [0.9905, 0.9957] | 0.9903, same sign | 1.0001 ±0.0016 | **no** |
| 2 | k2 `inline(always)`, k6 `inline(always)` | k8 `vectorize.width=8` | argmax | **1.0628** | [1.0590, 1.0660] | 1.0656, same sign | 0.9982 ±0.0039 | **yes** |
| 3 | the same | the same | argmax | 1.0636 | [1.0614, 1.0659] | 1.0665 | 0.9983 ±0.0024 | no |
| 4 | the same | the same | argmax | 1.0669 | [1.0627, 1.0718] | 1.0672 | 1.0019 ±0.0044 | no |
| 5 | the same | the same | argmax | **1.0679** | [1.0644, 1.0715] | 1.0663 | 1.0020 ±0.0030 | **yes** |

`forced_top1` never fired: no phase was all-`KEEP_DEFAULT` in any round, so
every entry is an argmax. Per case:

| round | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1.0026 | **1.6804** | 0.9549 | **0.5813** | 1.0008 | 1.0036 | 1.0020 | 1.0054 |
| 2 | 1.0010 | **1.6733** | 0.9880 | 1.0002 | 1.0078 | 0.9971 | 0.9952 | 0.9834 |
| 3 | 0.9960 | **1.6792** | 0.9876 | 1.0004 | 0.9967 | 0.9990 | 0.9969 | 0.9986 |
| 4 | 1.0003 | **1.6710** | 0.9851 | 0.9996 | 1.0006 | 1.0001 | 0.9985 | 1.0204 |
| 5 | 1.0017 | **1.6862** | 0.9864 | 1.0013 | 0.9996 | 1.0013 | 0.9995 | 1.0132 |

### 2.2 Scored against the oracle

| round | exact | same-family | miss | **harmful** | share of the combination (training) |
|---|--:|--:|--:|--:|--:|
| 1 | 7 | 1 | 4 | **2** | **−7.8%** (the plan is slower than the baseline) |
| 2 | **9** | 1 | 2 | **0** | 71.3% |
| 3 | 9 | 1 | 2 | 0 | 72.2% |
| 4 | 9 | 1 | 2 | 0 | 75.9% |
| 5 | **9** | 1 | 2 | **0** | **77.1%** |

Round 1 is the one-shot of decision 87 reproduced exactly (7 of 12: functions
7/8, loops 0/4) --- and it is the round that carries both harmful picks and
is **slower than the baseline**. What the remaining four rounds get wrong,
they get wrong the same way every time:

| site | Jev's final pick | truth | verdict | what it cost or left |
|---|---|---|---|---|
| `fn:k6_hot_loop` | `inline(always)` | `KEEP_DEFAULT` | miss | the arm is 1.0011 at k6, unconfirmed --- inert at its own kernel, but it costs **2.8% at k3** (oracle arm 26) |
| `k3_fill_run@lib.rs:174` | `KEEP_DEFAULT` | `unroll.count=4` | miss | **+4.4%** at k3, never tried |
| `k8_scale_add@range.rs:1103` | `vectorize.width=8` | `vectorize.width=16` | same-family | the baseline's own width, a null; **+8.8%** at k8, never tried |

The other nine are exact, including the one that matters: `inline(always)`
at `k2_mix`, the +67.8% of decision 85, in every round.

### 2.3 The third batch

| | ratio | 95% CI | A/A | MDE |
|---|--:|---|--:|--:|
| best plan (round 5) on the third batch | **1.0673** | [1.0645, 1.0704] | 1.0034 ±0.0024 | 3.34% |

**(1.0673 − 1) / (1.0847 − 1) = 79.4% of the oracle combination's own third
batch**, against 77.1% of it on training. Three independent batches of the
same plan (1.0679 training, 1.0663 confirmation, 1.0673 third) agree to
within 0.2 points.

Where the missing 21% is: the combination also carries `unroll.count=4` at
the k3 loop, `vectorize.width=16` at k8 and k5, and `inline(never)` at the
k4 function. Jev's plan is the +67.8% at k2 and nothing else that moved.

## 3. Run 2: random, five rounds, same everything

`artifacts/hintbench-search/random-r5/`, 21:43--22:10 JST, **27.0 min**,
seeded from `[evaluation] seed` 20260921 and reproducible. Every round:
output correct, every plan entry applied, no `ambiguous`.

| round | fn hints | loop hints | ratio | 95% CI | confirm | A/A | accepted |
|---|--:|--:|--:|---|---|--:|---|
| 1 | 6 | 3 | **0.9415** | [0.9387, 0.9442] | 0.9332, same sign | 1.0015 | no |
| 2 | 8 | 4 | 0.9947 | [0.9918, 0.9975] | 0.9968 | 0.9999 | no |
| 3 | 6 | 4 | 0.9990 | [0.9954, 1.0024] | not triggered | 0.9995 | no |
| 4 | 8 | 4 | **0.7087** | [0.7067, 0.7106] | 0.6999, same sign | 1.0010 | no |
| 5 | 6 | 3 | 0.9952 | [0.9926, 0.9975] | 0.9954 | 0.9996 | no |

Per case:

| round | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1.0020 | 1.0014 | 1.0091 | 1.0116 | **0.6039** | 1.0010 | 0.9993 | 0.9978 |
| 2 | 0.9975 | 0.9985 | 0.9738 | 0.9843 | 1.0008 | 0.9993 | 1.0043 | 0.9993 |
| 3 | 1.0003 | 1.0101 | 0.9722 | 1.0048 | 1.0146 | 1.0018 | 0.9980 | 0.9905 |
| 4 | 0.9992 | 1.0012 | 0.9996 | **0.2031** | **0.3087** | 1.0002 | 1.0024 | 1.0128 |
| 5 | 1.0004 | 1.0028 | 0.9524 | 1.0166 | 0.9970 | 1.0016 | 1.0012 | 0.9910 |

**No round was accepted.** The best plan is the baseline, `best-plan.json`
is not written, and the third batch is the run's null arm: **0.9990
[0.9970, 1.0013]**, A/A 1.0012 ±0.0023, MDE 3.81% --- the baseline against
itself. Random reached **0% of the oracle combination** on both batches.

Scored against the same truth:

| round | sites asked | exact | same-family | miss | **harmful** |
|---|--:|--:|--:|--:|--:|
| 1 | 11 | 2 | 1 | 8 | **1** (`interleave.count=2` at the k5 loop, 0.5953) |
| 2 | 12 | 0 | 0 | 12 | **2** (`unroll.count=2` at k4 0.9848; `vectorize.width=8` at k5 0.9950) |
| 3 | 12 | 2 | 0 | 10 | 0 |
| 4 | 12 | 0 | 0 | 12 | **2** (`vectorize.width=2` at k4 0.2024; `unroll.disable` at k5 0.2941) |
| 5 | 11 | 2 | 0 | 9 | 0 |
| **total** | **58** | **6** | 1 | 51 | **5** |

All six of random's exact answers are `KEEP_DEFAULT` at a site whose truth
is `KEEP_DEFAULT` --- it left a site alone and was right by construction.
It never found `inline(always)` at `k2_mix`, `unroll.count=4` at the k3
loop or `vectorize.width=16` at k8: **not one of the three hints that can
make this benchmark faster, in 58 draws.**

Rounds 1 and 5 asked eleven sites, not twelve. Random put `inline(never)`
on `k4_count_bytes` in both, which changes the inlining the k4 loop lives
in, so the loop's site key does not come back from the phase-A dump. The
driver records `n_loop_sites: 3` and asks three loop questions; nothing
fails, and a site that was never asked is not scored as a wrong answer.

## 4. Jev against random

| | Jev (feedback) | random |
|---|---|---|
| rounds accepted | **2** (2 and 5) | **0** |
| best plan | k2 `inline(always)`, k6 `inline(always)`, k8 loop `vectorize.width=8` | the baseline |
| training ratio | **1.0679** [1.0644, 1.0715] | 1.0000 by construction |
| third batch | **1.0673** [1.0645, 1.0704] | 0.9990 [0.9970, 1.0013] (null arm) |
| share of the oracle combination, training | **77.1%** | **0%** |
| share of the oracle combination, third batch | **79.4%** | **0%** |
| per-site score, final plan | **9 exact, 1 same-family, 2 miss, 0 harmful** | n/a (no plan) |
| harmful picks made | 2, both in round 1, both dropped after one round of feedback | 5, spread over three rounds, none dropped |
| worst round | 0.9931 | **0.7087** |

## 5. Did the feedback change Jev's choices?

Yes at two of the three sites the brief names, and the third shows the
limit. `P` is the probability the answer carried, per round.

| site | candidate | r1 | r2 | r3 | r4 | r5 |
|---|---|--:|--:|--:|--:|--:|
| k4 loop | `vectorize_width_16` | **0.88** | 0.28 | 0.07 | 0.13 | **0.12** |
| k5 loop | `vectorize_width_8` | **0.58** | 0.37 | 0.03 | 0.10 | **0.08** |
| k8 loop | `vectorize_width_8` | 0.60 | 0.56 | 0.85 | 0.81 | **0.79** |
| k8 loop | `vectorize_width_16` | 0.01 | 0.02 | 0.00 | 0.00 | **0.00** |
| k3 loop | `unroll_count_4` | 0.15 | 0.15 | 0.09 | 0.10 | **0.13** |
| k3 loop | `unroll_count_2` | 0.24 | 0.21 | 0.11 | 0.20 | 0.18 |
| `k2_mix` fn | `inline_always` | 0.75 | 0.88 | 0.95 | 0.96 | **0.91** |
| `k6_hot_loop` fn | `inline_always` | 0.76 | 0.79 | 0.56 | 0.59 | **0.62** |

**k4, away from width 16 after the −42%: yes, in one round.** This is what
round 2's state said at that site, and it is the whole of what changed
there:

```
  what earlier rounds chose here:
    round 1: vectorize.width=16 -> whole-build ratio 0.9931; on case k4, the
    one case this site's own code is timed by, 0.5813 with 95% CI [0.5797,
    0.5830] (not accepted)
```

`P(vectorize_width_16)` fell 0.88 → 0.28, the argmax moved to
`KEEP_DEFAULT`, and by round 3 --- with a second line saying `KEEP_DEFAULT`
had returned k4 to 1.0002 and been accepted --- it was 0.07 and never came
back. The same happened at k5, the other harmful pick: 0.58 → 0.08.

**k3 to `unroll.count=4`: no.** 0.15 → 0.13, flat. **k8 to width 16: no**,
and it moved the wrong way: 0.01 → 0.00, while `vectorize.width=8` --- the
width the baseline already uses --- *rose* from 0.60 to 0.79.

The asymmetry is the finding. The feedback can only speak about hints that
have been tried: after a round, the k4 section says what width 16 cost, but
no section ever says what `unroll.count=4` would have been worth, because
no round ever tried it. And Jev reads "k8 1.005, not accepted" as
confirmation that width 8 is harmless rather than as evidence that
something else should be tried. **Feedback removed both harmful picks and
both inert ones; it discovered nothing.** The driver has exactly one
exploration mechanism, `forced_top1`, and it fires only when a phase is
*entirely* `KEEP_DEFAULT` --- which never happened, because `k2_mix` alone
kept phase A non-empty in all five rounds.

At `k6_hot_loop` the feedback pushed in the right direction and did not
finish: four rounds of "k6 ≈ 1.000" took `inline_always` from 0.76 to
0.56--0.62, never below `KEEP_DEFAULT`. It is the one pick in the final
plan that is measurably bad --- **inert at its own kernel (1.0011) and
−2.8% at k3** (oracle arm 26) --- and the per-kernel readout is exactly why
nothing catches it: k6's own case says the hint is free.

## 6. What went wrong, and what the gates did

* **The gate stopped the harmful plan.** Round 1, carrying width 16 at k4,
  measured 0.9931 with its interval below 1 in two batches. It was not
  accepted, so it never became the incumbent and the run never built on it.
  Correctness held in all ten rounds of both runs; no plan changed the
  program's output, and no gate had to catch one that did.
* **The acceptance rule promoted the same binary twice.** Rounds 2, 3, 4
  and 5 of the Jev run are the **identical binary** (`bb18ceb4...`),
  measured in four independent batches at 1.0628, 1.0636, 1.0669 and
  1.0679 --- a 0.51-point spread. Round 5 was "accepted as the new best"
  over round 2 because 1.0644 > 1.0628. Rule 3 compares an interval against
  the incumbent's *point estimate*, and rule 4 only asks that the interval
  exclude 1, which it does for a plan that is genuinely +6.6%; neither asks
  whether the new plan is different from the incumbent. Harmless here,
  since the plan is the same one --- but on a run where two different plans
  sit inside the batch-to-batch spread, this promotes the luckier batch. It
  is the jaq failure of decision 80 (a) in a form the confirmation batch
  does not cover. Not fixed here: fixing it mid-experiment would change the
  rule the two runs were measured under.
* **Those four batches are a free null panel.** Same pair, four independent
  batches, spread 0.51 pt; the in-run A/A over the ten rounds of both runs
  ranged 0.9982--1.0020 with half-widths 0.0016--0.0044. Quieter than jaq
  (4.67 pt, results.md 113), consistent with `oracle.md` 3.
* **A per-case readout cannot separate two sites on one case.** k4 has a
  function site and a loop site and one workload. After round 1 the
  *function* site's history line also read "`KEEP_DEFAULT` → on case k4 …
  0.5813", which is true and attributes the loop's loss to the function's
  answer. Jev did not take the bait --- `KEEP_DEFAULT` at `k4_count_bytes`
  stayed at P 0.90--0.97 throughout --- but the state cannot currently say
  which of two sites on one case moved it, and on a target with more sites
  per case it would say much less.
* **`vectorize.width=8` at k5 and k8 is not a null.** Decision 84 called
  those two arms candidates for the null panel, and the oracle confirmed
  k5's at **0.9950 with a negative sign**: small, under the MDE, but
  confirmed in two batches. By the brief's definition that makes Jev's k5
  answer in round 1 a *harmful* pick, not an inert one.
* **Random's worst round cost 29%** (0.7087) and its worst case 80%
  (k4 0.2031). Both survived the correctness gate --- they are correct
  programs --- and both were stopped by the speed gate, which is what it is
  for.

## 7. Cost

| | |
|---|--:|
| wall clock, Jev run (5 rounds + third batch) | 29.0 min |
| wall clock, random run (5 rounds + third batch) | 27.0 min |
| both runs, 20:55--22:11 JST | **56.0 min** |
| builds | 20 (2 per round x 10 rounds); the baseline was reused |
| timing batches | **21** = 10 rounds + 9 confirmations + 2 third batches |
| Jev HTTP requests | 12 (10 answered 200, **2 exhausted on 503 and re-sent unchanged**) |
| Choice questions | 76 |
| latency, total / mean / max | 19.9 s / 1655 ms / 3541 ms |
| tokens in / out | 207911 / 5969 |
| gateway cost | **$0.00000000** |
| Jev's share of the run's wall clock | 1.14% |
| internal 503 retries inside answered requests (`failed_attempts`) | 6, in four of the ten answered calls |

All five Jev rounds fired a confirmation batch; four of the five random
rounds did, its round 3 interval being the one that covered 1. No round of
either run was skipped as `identical_to_baseline`: every one of the twenty
builds changed code.

**The 503 rate was high.** Six of the twelve requests carried at least one
503, and two exhausted all three internal retries --- both phase A, rounds
1 and 2. Without the phase-level re-send of 1.4 (b) those two rounds would
have gone out with every answer `KEEP_DEFAULT` and no probabilities, which
`forced_top1` cannot rescue, and **round 1 would not have been the one-shot
control this experiment is read against**.
