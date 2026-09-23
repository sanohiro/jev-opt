# Experiment 5 (hintbench): Jev with exploration

Five rounds of `scripts/jev_search.py --proposer jev --explore 2` over
`targets/hintbench`, against the same oracle
(`docs/experiments/hintbench/oracle.md`) and under the same frozen
conditions as `exp4.md`. Experiment 4 left one finding and one gap:
feedback works as a **filter** --- it dropped both harmful picks in a
single round --- and it **discovered nothing**, because the state can only
speak about hints that have been tried, and the two hints that could have
paid (`unroll.count=4` at the k3 loop, **+4.4%**, and
`vectorize.width=16` at the k8 loop, **+8.8%**) were never tried once in
58 answers.

Decision 90 implemented the four repairs decision 89 asked for. This
experiment measures them:

1. does `--explore 2` reach the two hints Experiment 4 never tried, and
   does Jev pick them when it is asked which untried candidate is most
   promising;
2. do the plugin's post-vectorization facts change the loop answers ---
   Experiment 4's loop picks came from lane arithmetic alone, because the
   state could only say `UNKNOWN` for three of the four loops;
3. does the run beat Experiment 4's **77.1% of the oracle combination**.

## 1. Protocol

### 1.1 What is frozen, and is the oracle's

Everything in `exp4.md` 1.1, unchanged, with two differences, both
recorded here because they are conditions of the measurement:

| | |
|---|---|
| target | `hintbench`, PGO baseline |
| baseline | `artifacts/hintbench-sites/baseline`, **rebuilt with the new plugin** (1.2) |
| marks | `targets/hintbench/jev-marks.txt`, 8 |
| site set | `oracle.selected_keys_loop_hint_kernels`, the same frozen 8 functions + 4 loops |
| case set | `k1`..`k8`, `holdout-as-search` |
| repetitions | 15, warmup 3, shuffled, seed 20260921 + round |
| pinning | `taskset -c 8`, settle gap 0 ms, bootstrap 10000 |
| vocabulary | **v4**, `--source-comments strip`, `--readout forced_top1`, `min_confidence 0.0` |
| state format | **`state-v4.2-2026-09-22`** (decision 89 c/d + the plugin's `post_vectorize`), where Experiment 4 sent `state-v4.1` |
| exploration | **`--explore 2`**, where Experiment 4 was `--explore 0` by construction (the flag did not exist) |
| acceptance | the **five** pre-registered conditions: correct output, every entry applied, CI lower bound above the incumbent's point estimate, confirmed in a second batch, and **the plan differs from the incumbent's** (decision 89 a, rule 5) |
| no-op skip | on |
| rounds | 5, then a third batch (`--measure-holdout`) on the best plan |

The command:

```
scripts/jev_search.py --target hintbench \
    --marks targets/hintbench/jev-marks.txt \
    --sites artifacts/hintbench-sites/sites.json \
    --site-set oracle.selected_keys_loop_hint_kernels \
    --proposer jev --rounds 5 --vocab v4 --readout forced_top1 \
    --source-comments strip --explore 2 -n 15 --warmup 3 \
    --baseline-dir artifacts/hintbench-sites/baseline \
    --measure-holdout --out artifacts/hintbench-search/jev-v42-r5
```

**Random is not re-run.** Exploration is a `jev` mechanism: random already
draws non-`KEEP_DEFAULT` candidates by construction, so "random with the
same exploration budget" is the same arm it already was. Experiment 4's
random run (`exp4-random/`, 0% of the oracle combination on both batches,
5 harmful picks, no round accepted) stands as the control.

### 1.2 The baseline was rebuilt, and it is the same binary

Decision 90 (a): the dump `exp4` ran against was written by the old
plugin and carries no `post_vectorize`, so the v4.2 loop verdict would
have fallen back to v3.2's remark reading. `scripts/hintbench_oracle.sh
dump` rebuilt it with the new plugin (`libjevplugin.so` sha256
`ca4a6625…`, where Experiment 4's manifest records `be74c857…`), same
frozen flags, same `pgo/hintbench/merged.profdata`
(`d1b226d5…`, unchanged).

The plugin must not change codegen, and it does not:

| | |
|---|---|
| `.text` sha256 | `df5968bc018b17ad9a3d1f236e1ac8f6c9995d76bc296f0c8c67fda9c9f1fe7a` --- the frozen value of `oracle.md` 1.1 |
| whole-binary sha256 | `0749819773842642cecaa04e79d6cfaae899288b967a697bbf692d40e8384cb6` --- **byte-identical** to `exp4-jev/manifest.json`'s `baseline_bin_sha256` |
| `norm_code_diff.py` vs the PGO baseline | `IDENTICAL`, 373 symbols, 0 changed, 0 only-in-base, 0 only-here |
| `run_correctness` | identical, line for line, to the pre-rebuild `correctness-dump.txt` |
| `sites.json` | `marks`, `sites` and `oracle` blocks compare equal to the pre-rebuild file; the frozen loop set is the same four keys |

The whole binary matching, not only `.text`, is the stronger statement:
the search is measuring against the same bytes Experiment 4 and the whole
oracle sweep measured against. The pre-rebuild directory is kept at
`artifacts/hintbench-sites.pre-v42/`.

### 1.3 `post_vectorize` against the oracle's remarks

The plugin's `VectorizerEndEP` pass records, per site key, what the loop
looked like after `LoopVectorize`. Read from the **lto**-stage report of
the rebuilt dump (`artifacts/hintbench-sites/rep-dump/
sites-hintbench.480de01ae119761f-cgu.0-lto-1010026.json`), for the four
frozen loop sites:

| site | kernel | `watched` | `exists` | `ambiguous` | `isvectorized` | VF | `iv_step` | IC | the oracle's remark |
|---|---|---|---|---|---|--:|--:|--:|---|
| `hbkernels::k5_mul_reduce@macros.rs:180:28#d2` | k5 | yes | yes | no | **true** | **8** | 32 | **4** | "vectorized loop (vectorization width: 8, interleaved count: 4)" |
| `hbkernels::k4_count_bytes@macros.rs:180:28#d2` | k4 | yes | yes | no | **true** | **8** | 32 | **4** | same |
| `hbkernels::k8_scale_add@range.rs:1103:12#d2` | k8 | yes | yes | no | **true** | **8** | 32 | **4** | same |
| `hbkernels::k3_fill_run@lib.rs:174:9#d3` | k3 | yes | yes | no | **false** | - | 8 | - | "loop not vectorized: value that could not be identified as reduction is used outside the loop" |

**Four of four agree with the remarks**, and none of the four came back
`ambiguous`, which was the risk: `k3_fill_run` holds two loops and the
match at `VectorizerEnd` is coarser than a site key. `oracle.md` 9 (b)
notes that the dump's own `already_vectorized` field says `false` for all
four --- it is read at `VectorizerStartEP`, before the vectoriser runs,
and can only mean "this loop already carries `llvm.loop.isvectorized`".
`post_vectorize` is the field that answers the question that one cannot.

One thing the table does not say and the report does: k3's unvectorized
loop has `iv_step: 8`. The loop the vectoriser refuses is unrolled eight
times by the unroller, which is the mechanism behind `unroll.disable`
costing 29.4% there (`oracle.md` 9 b) --- and the reason a further
`unroll.count` hint is a re-tuning and not an introduction.

### 1.4 What the state now says, and what it no longer says

`--print-state --vocab v4` on the rebuilt baseline, 2363 lines, header
`state format state-v4.2-2026-09-22`. The loop verdicts state the width
and the interleave count instead of `UNKNOWN`. The k8 loop, section `q2`
of phase B --- the site Experiment 4 answered `vectorize.width=8` at in
all five rounds, which is the width the baseline already uses:

```
  - what LLVM did with this loop in the baseline build, recorded by the
    plugin itself after LoopVectorize had run --- this is a fact about this
    one loop, not a remark attributed to a source line, and it is the
    primary evidence here: LLVM vectorized it, with vectors of 8 lanes,
    interleaved 4 times (the vectorized loop's induction variable advances
    32 elements per iteration).
  - vectorisation legality: LEGAL, and already taken --- the baseline
    vectorizes this loop with no hint at all.
  - no-op check: 8 is the width LLVM already uses here, so the candidate
    `vectorize_width_8` asks for the state this site is in and the build it
    produces can only be the baseline's.
  - no-op check: 4 is the interleave count LLVM already uses here, so
    `interleave_count_4` asks for the state this site is in.
  - the remarks cannot add to that: range.rs:1103 carries 18 separate
    vectoriser verdicts in the baseline build, because every loop inlined
    from that line lands on it, so none of them can be read as a statement
    about this loop.
```

The k3 loop, section `q3`, is the other case:

```
  - what LLVM did with this loop in the baseline build ... LLVM did NOT
    vectorize it: after LoopVectorize the loop is still there and carries
    no `llvm.loop.isvectorized` metadata.
  - a `vectorize.width` hint is not a permission slip: where LLVM declined
    to vectorize a loop, asking for a width does not make it legal or
    profitable.
```

Checks on the printed state:

* **no `UNKNOWN` verdict survives.** The string occurs six times and every
  one is the standing caveat line ("the readings above use this loop's own
  leaf location only, and say UNKNOWN where that location is shared"),
  never a verdict.
* **no comments in the source windows**: no `//`, `///`, `/*` or `#[doc`
  anywhere in the 2363 lines, which is the decision-82 confound removed.
* **the exploration request renders.** With a fake all-`KEEP_DEFAULT`
  history --- the preview's assumption --- both phases produce a two-question
  request:

| phase | `e0` | `e1` |
|---|---|---|
| A | `fn:hbkernels::k5_mul_reduce` | `fn:hbkernels::k4_count_bytes` |
| B | `hbkernels::k5_mul_reduce@macros.rs:180:28#d2` | `hbkernels::k4_count_bytes@macros.rs:180:28#d2` |

  with the wording

```
Section `e0` of the state describes this site. No hint has ever been tried
there: in every round of this run so far it was answered KEEP_DEFAULT, so
nothing that has been measured says what any of the hints below would be
worth, and the results table cannot say. One of the candidates below will be
tried at this site in this round's build; which of them is most promising?
The list is every candidate this site has not already been given, filtered
mechanically --- KEEP_DEFAULT is not among them and nothing was left out on
anyone's judgement.
```

**The ordering is the experiment's main structural constraint, and it is
worth stating before the result.** Eligible sites are ranked by hotness,
and hintbench's four loops rank k5 (8.70e10) > k4 (5.46e10) > k8 (3.16e10)
> k3 (7.21e9). With `K=2` the first two are k5 and k4 --- the two sites
where almost every non-`KEEP` candidate is between −20% and −80%. The two
hints this experiment is looking for sit at the *bottom* of that order.
Worse, eligibility is permanent: `exploration_sites` skips a site the
moment **any** candidate has been tried there in **any** round, accepted or
not, so a site that Experiment 4's argmax touched in round 1 (k4, k5 and
k8 loops all did) can never be explored. Whether k8 and k3 are reachable
at all therefore depends on the *argmax* answering `KEEP_DEFAULT` there in
round 1 --- which is exactly what the new `post_vectorize` no-op line at k8
might cause, and which is why 1.3 and this section are one experiment and
not two.

### 1.5 One driver change, made before round 1

`exp4.md` 1.4 (b) gave `JevProposer.choose` an unchanged re-send for a
phase whose every answer is `no answer` --- a 503 burst that exhausts all
three internal retries. `explore_round` did not have one: `JevClient.ask`
returns `(None, line_no)` on exhaustion, every eligible site then stays
`KEEP_DEFAULT`, and because those sites are **still untried** the round
loses its whole exploration slot. Six of Experiment 4's twelve requests
carried at least one 503 and two exhausted their retries; this run sends
up to four requests a round, so the expected loss was not negligible and
it would have fallen on precisely the mechanism under test.

`explore_round` now does what `choose` does: ten seconds, the **same**
request, logged as `A.explore.retry` / `B.explore.retry`, with the
exhausted line kept in the JSONL and its `http_status`. No request is ever
modified to make it succeed. Nothing else in the driver moved.

### 1.6 A stopping rule, written down during round 2

Rounds 1 and 2 both lost **phase A** entirely: `A` and `A.retry`, six
consecutive 503s each round, on a request of 75--78 KB. The smaller
requests of the same rounds went through (`A.explore` 22 KB, `B.explore`
25 KB, round 1's `B` 46 KB after one 503). Round 2's `B` and `B.retry`
then went too. Experiment 4 sent bodies of exactly the same size at the
same endpoint and lost only rounds 1 and 2's first `A` attempt, both
recovered by the re-send.

A phase A that never lands cannot answer the brief's question. `k2_mix`
`inline(always)` is +67.8% and is the whole of Experiment 4's 77%; with
the argmax gone it can only enter a plan through exploration, and the
function exploration order puts `k2_mix` in the last tier (hotness 0 by
construction, tie broken by list order). Any "share of the oracle
combination" computed from such a run measures the gateway.

So, written down **during round 2, before round 3's phase A was sent**, so
that the decision is not taken on a result:

> If round 3's phase A exhausts both `A` and `A.retry`, this run is
> abandoned as a gateway outage. Its directory is kept as
> `artifacts/hintbench-search/jev-v42-r5-outage1/` with every log, nothing
> is scored as a search result, and the experiment is re-run from round 1
> --- same command, same seed, same everything --- once a probe that
> re-sends round 1's phase-A body **verbatim** comes back 200. Nothing in
> `jev-opt.toml` (`retries`, `max_state_chars`) and nothing in the driver
> is changed to work around it: splitting phase A into smaller requests
> would change the question bundling, which decisions 68 and 70 measured
> as moving Jev's confidence.

Whatever happens to the run, the answers rounds 1 and 2 did get are real
answers to real questions, and section 2 records them on their own.

## 2. What rounds 1 and 2 established, whatever the run does next

These are readings of answers Jev gave to questions the driver asked, and
they do not depend on the run reaching round 5.

### 2.1 `post_vectorize` moved the loop phase, on the state alone

Round 1 has no history: its phase B is the same question Experiment 4's
round 1 asked, with one thing changed --- the verdict block now states
what LLVM did. The answers are not the same answers.

| loop site | Experiment 4, round 1 | Experiment 5, round 1 | P(KEEP) | the runner-up |
|---|---|---|--:|---|
| k4 | `vectorize_width_16` (P **0.88**) | **`KEEP_DEFAULT`** | 0.51 | `vectorize_width_16` 0.36 |
| k5 | `vectorize_width_8` (P 0.58) | **`KEEP_DEFAULT`** | 0.81 | `unroll_count_8` 0.07 |
| k8 | `vectorize_width_8` (P 0.60) | **`KEEP_DEFAULT`** | 0.77 | `unroll_count_2` 0.09 |
| k3 | `KEEP_DEFAULT` | `KEEP_DEFAULT` | 0.62 | `unroll_count_4` 0.15 |

**All four loops answered `KEEP_DEFAULT`, where Experiment 4 hinted
three.** `vectorize.width=8` --- the width the baseline already uses, and
the pick Experiment 4 repeated at k8 in all five rounds --- collapsed from
P 0.60 to **P 0.01** at k8 and from 0.58 to **0.00** at k5 once the state
said "8 is the width LLVM already uses here, so the candidate
`vectorize_width_8` asks for the state this site is in". Decision 87 (c)
predicted exactly this: the loop answers were coming from lane arithmetic
because the state could not say what LLVM had done. Given the fact, Jev
stops asking for the state it is already in.

k4 is the one that only half-moved: `vectorize.width=16` there is the
oracle's **−42%**, and the fact that the loop is already VF 8 × IC 4 took
it from 0.88 to 0.36 without taking it below `KEEP_DEFAULT`.

### 2.2 And that is what fired `forced_top1` into the −42%

A phase that is *entirely* `KEEP_DEFAULT` is the trigger condition for the
decision-71 readout, which then applies the top-ranked site's own
highest-probability non-`KEEP` candidate. In Experiment 4 it never fired,
because `k2_mix` alone kept phase A non-empty. Here the improved state
made phase B all-`KEEP` --- and `forced_top1` forced
`vectorize_width_16` at k4, P 0.36, the arm the oracle measured at
**0.5793**.

Round 1 measured **0.9369** [0.9340, 0.9400], k4 at **0.5823** --- the
oracle's 0.5793 reproduced to three digits --- and was not accepted. The
gate did its job. But the mechanism is worth stating plainly:

> The better state made the loop phase honest; the honest phase tripped
> `forced_top1`; `forced_top1` spent the round on the single worst hint in
> the phase. Two mechanisms that are each right on their own compose into
> a harmful plan.

It cost more than the round. `forced_top1` writes a real plan entry, so
k4's loop counts as **tried**, and `exploration_sites` skips a site the
moment any candidate has been tried there. Exploration therefore never saw
the k4 loop, and never will in this run.

### 2.3 Exploration reached the k8 loop, and Jev declined width 16 at P 0.01

This is the brief's first question and round 1 answered it. With k4 taken
by `forced_top1` and k3 last by hotness, phase B's two exploration slots
went to **k5 and k8** --- and k8 is the site of the oracle's **+8.8%**.

The question removed `KEEP_DEFAULT` and offered all eleven untried
candidates with their frozen descriptions. Jev's answer:

```
hbkernels::k8_scale_add@range.rs:1103:12#d2   ->  unroll_count_2  (conf 0.25)
  unroll_count_2 0.32   unroll_count_8 0.20   interleave_count_1 0.15
  vectorize_width_8 0.08   ...   vectorize_width_16 0.01
```

**`vectorize_width_16` came last but one, at P 0.01**, in a question whose
whole premise was "something here will be tried; which?". The exploration
mechanism did what decision 89 (b) asked of it --- it put the +8.8% hint
in front of the model, described, with no `KEEP_DEFAULT` to hide behind ---
and the model ranked it eleventh of eleven. Measured, k8 came back 0.9992
against the oracle's 1.0164 for `unroll.count=2`.

The corollary is structural: k8 is now **permanently** ineligible. One
exploration slot, one answer, and the site is tried for the rest of the
run.

At k5 the same request chose `unroll_count_8` (P 0.30 over
`unroll_count_2` 0.27), which measured **1.0176** against the oracle's
1.0194 --- a real if sub-MDE gain, and the only thing round 1 got right.

### 2.4 Exploration found `unroll.count=4` at the k3 loop

This is the brief's second question and round 2 answered it. By round 2
the k4, k5 and k8 loops were all tried, so k3 --- last by hotness, 7.2e9
against k5's 8.7e10 --- was the only eligible loop and got the single
remaining slot:

```
hbkernels::k3_fill_run@lib.rs:174:9#d3   ->  unroll_count_4  (conf 0.25)
  unroll_count_4 0.31   unroll_disable 0.28   vectorize_width_16 0.10
  unroll_count_2 0.09   vectorize_width_2 0.07   vectorize_width_4 0.06
  unroll_count_8 0.04   interleave_count_1 0.02   interleave_count_2 0.02
  vectorize_width_8 0.01   interleave_count_4 0.00
```

**`unroll_count_4` is the truth at that site, +4.4%**, and Jev put it
first --- narrowly, over `unroll_disable`, which is the **−29.4%** at the
same loop and which decision 86 records as Claude's own wrong answer
there. Experiment 4 never tried either in 58 answers; this question was
asked once and got the right one.

It is worth being exact about how thin the margin is. 0.31 against 0.28 is
not knowledge of the mechanism --- the two sit at opposite ends of the
same axis, and the state's `unroll_count_4` description ("more scheduling
freedom and fewer branches ... at four times the body's code size") and
its `unroll_disable` description ("keeps the body small, which helps when
the loop is short") are both plausible readings of a trip count of 11.5.
What the state does add here is the post-vectorization fact that the loop
is **not** vectorized, which is why nothing in the answer reaches for a
width: the four `vectorize_*` candidates together carry 0.24.

### 2.5 Function-phase exploration is the one-eighth-share problem again

Phase A's own request never got through in either round, so every function
hint in this run came from exploration. It asked, in hotness order,
`k5_mul_reduce` and `k4_count_bytes` (round 1) and `k8_scale_add` and
`k3_fill_run` (round 2), and answered **`inline_always` at all four**, at
confidences 0.13--0.33 and probabilities 0.30--0.46 against `align_32` at
0.28--0.31.

All four are `KEEP_DEFAULT` at truth, and three of the four arms are
builds **identical to the baseline** --- the no-op skip records them at
1.0 without timing. So they cost nothing and gained nothing, which is the
honest summary of a question that forces a hint at a site where the right
answer is "none of them". Decision 84's finding stands: with no share to
separate the marks and the function descriptions rebalanced, the
`inline_always` prior is what is left.

## 3. The third batch, which had to be taken twice

**This section is out of narrative order** --- the remaining rounds are
section 4 --- because 3.1 was written, and committed to, *before* the second
batch ran and before anything in sections 4 and 5 was known. It is left
where it was written.

### 3.1 Pre-registration, written before the second batch was taken

The run's own `--measure-holdout` batch ran at 07:16--07:18 JST and its
numbers are in 3.2 below, in full. **It is not usable as a measurement, and
the reason is in its controls, not in its candidate:**

* the `aa` label --- a second copy of the baseline binary, the one thing in
  the batch that is known to be a null --- came back **1.0068 with a
  half-width of 1.83%**, where Experiment 4's third batch had 1.0034 ±0.24%
  and every round batch of this run had ±0.20--0.33%;
* three individual runs are interference outliers of 1.5--2.2x: `base`/k7
  **740.5 ms** against that label's own median of 345.5, `cand`/k1
  **600.1 ms** against 333.0, `aa`/k1 **499.4 ms** against 332.6;
* the worst of them lands on the **baseline** label, so it inflates the
  ratio of everything measured against it --- `aa` reads 1.0752 at k7 and
  `cand` 1.0661 at k7, both of them nonsense --- and the batch's own MDE is
  **23.3%** against Experiment 4's 3.34%.

This machine runs one timing job at a time and nothing else was scheduled;
what took it for those two minutes is not known and is not reconstructible
after the fact.

A second batch is therefore taken, **once**, on the same two binaries, under
the same frozen conditions, with a fresh seed recorded here in advance:
**20260927**.

> **The rule, fixed before the second batch ran and before anything about it
> was known:** the second batch's number is the one this experiment's share
> of the oracle combination is computed from, whatever it says. The first
> batch is not deleted --- it stays in this document and in `results.md` with
> its outliers --- and the second is not re-run if it disappoints. Neither
> batch is chosen after the fact. This is a **deviation** from "the third
> batch is measured once" (`exp4.md` 1.2), it is taken on the controls
> alone, and it is recorded as a deviation in section 6.

### 3.2 Batch 1, kept and unusable

`artifacts/hintbench-search/jev-v42-r5/holdout/stats.md`, 07:16--07:18 JST,
seed 20260921, the same three labels every third batch of this project uses:

| label | aggregate ratio | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | --- | --- |
| cand (round 3's plan) | 1.0756 | [1.0557, 1.0984] | 2.14% |
| **aa (a second copy of the baseline)** | **1.0068** | [0.9913, 1.0278] | **1.83%** |

worst per-workload half-width 11.65% (k7), **MDE 23.30%**

Per case the damage is where the outliers are: k7 reads `aa` 1.0752 and
`cand` 1.0661 --- an identical binary "1.075x faster" than itself --- because
the `base` label's k7 carries a 740.5 ms run against its own 345.5 ms
median. k1 does the same thing more mildly. Every other case is normal, and
the two that carry the result are undamaged (k2 1.6764, k3 1.0488).

Had this batch been used, it would have given **89.3%** of the oracle
combination's third batch. The batch that replaces it gives less. The
rejection was taken on the controls before that was known, and it cost the
experiment its best-looking number.

### 3.3 Batch 2, the one the share is computed from

```
export TARGET=hintbench
scripts/bench_panel.sh \
    artifacts/hintbench-search/jev-v42-r5/holdout-batch2 15 3 20260927 \
    base=artifacts/hintbench-sites/baseline/bin \
    cand=artifacts/hintbench-search/jev-v42-r5/round-03/bin \
    aa=artifacts/hintbench-sites/baseline/bin
```

Same two binaries as batch 1, and provably so: `bench_panel.sh` strips its
own copies, and the stripped sha256s it printed --- `a84b7c0d…` for
`base`/`aa` and `ac3790d4…` for `cand` --- are the ones in
`holdout/timing/`. Same pin (`taskset -c 8`), same gap (0 ms), same n (15),
same warmup (3), same bootstrap (10000). Only the shuffle seed differs, as
an independent batch requires.

| label | aggregate ratio | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | --- | --- |
| **cand (round 3's plan)** | **1.0724** | [1.0704, 1.0742] | **0.19%** |
| aa (a second copy of the baseline) | **0.9979** | [0.9960, 0.9999] | 0.20% |

worst per-workload half-width 1.56% (k8), **MDE 3.12%** --- batch 1's was
23.30%. The A/A is back where hintbench's A/A lives, and no run in the batch
is an outlier.

| case | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| cand | 0.9989 | **1.6736** | **1.0389** | 1.0111 | 1.0029 | 0.9971 | 1.0018 | 0.9944 |
| aa | 1.0007 | 0.9986 | 0.9997 | 1.0011 | 1.0003 | 0.9957 | 1.0017 | 0.9854 |

**1.0724 [1.0704, 1.0742], and (1.0724 − 1) / (1.0847 − 1) = 85.5% of the
oracle combination's own third batch**, against Experiment 4's 79.4%.

## 4. Rounds 3, 4 and 5

Section 2 stopped at round 2 because the run might have been abandoned. It
was not: round 3's phase A landed on `A.retry` after two 503s, so the
stopping rule of 1.6 was tested and did not fire. What follows is the rest.

### 4.1 Round 3: the round that won, and how it was assembled

Phase A's own request landed for the first time in the run. Its argmax:

| function site | answer | P(KEEP) | P(pick) |
|---|---|--:|--:|
| `k6_hot_loop` | `inline_always` | 0.34 | 0.60 |
| `k2_mix` | `inline_always` | 0.40 | 0.57 |
| `k3_fill_run` | `inline_always` | 0.42 | 0.55 |
| `k8_scale_add` | `KEEP_DEFAULT` | 0.87 | 0.07 |
| `k1_step` | `KEEP_DEFAULT` | 0.92 | 0.05 |
| `k7_error_path` | `KEEP_DEFAULT` | 0.96 | 0.03 |
| `k4_count_bytes` | `KEEP_DEFAULT` | 0.97 | 0.01 |
| `k5_mul_reduce` | `KEEP_DEFAULT` | 0.97 | 0.01 |

`k2_mix` at last enters a plan through the phase that was supposed to
propose it --- rounds 1 and 2 never got the question through --- and the
+67.8% arrives with it. The two KEEPs that matter are `k4` and `k5` at
P 0.97: round 1's exploration put `inline_always` on both, and the history
now carries round 1's outcome against them --- the round was rejected at
0.9369 and its k4 case read 0.5823. That the 0.5823 was the **loop** site's
doing and not the function's is precisely the attribution problem of decision
89 (2) (`results.md` 134): one workload serves both of k4's sites, so the
function site's history line carries a number the function site did not
cause. Jev answered `KEEP_DEFAULT` at both, which is the truth at both --- it
was right, and part of its evidence was not.

Phase A's exploration then took the last two never-tried function sites,
`k1_step` and `k7_error_path` (hotness ties broken by list order), and
answered `inline_always` at both. Both are `KEEP_DEFAULT` at truth and both
arms are **builds identical to the baseline** --- inert, as 2.5 predicted.

Phase B needed no exploration: all four loops were tried by round 2, so
`exploration_sites` returned nothing, and the argmax alone carried the
round. It is worth seeing what one measured round did to the k3 answer:

| k3 loop | round 1 | round 2 | round 3 | round 4 |
|---|--:|--:|--:|--:|
| P(`KEEP_DEFAULT`) | 0.62 | (explored) | **0.03** | 0.04 |
| P(`unroll_count_4`) | 0.15 | 0.31 | **0.95** | 0.95 |

Round 2 tried `unroll_count_4` because exploration made it try something;
the round measured **+4.55% at k3**; from round 3 on it is a near-certainty
in the argmax. That is the whole mechanism this experiment was built to
test, in one column: exploration proposes once, measurement decides, and
feedback keeps it.

**Round 3: 1.0741 [1.0720, 1.0760]**, confirmation batch 1.0740
[1.0723, 1.0759], in-run A/A 0.9995 ±0.0020, output correct, every entry
applied. Per case:

| k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|--:|--:|--:|--:|--:|--:|--:|--:|
| 1.0012 | **1.6691** | **1.0402** | 1.0087 | 0.9997 | 1.0009 | 1.0001 | 1.0100 |

Accepted. It is the run's best and the plan `best-plan.json` holds:
`inline_always` at k1, k2, k3, k6, k7 and `unroll_count_4` at the k3 loop.

### 4.2 Rounds 4 and 5 were not rejected by the plan-change rule

The new acceptance condition of decision 89 (a) --- compare only when the
plan differs from the incumbent's --- **never fired in this run**. All five
plans are distinct (`plan_sig` 786fb052, dfa05c9b, 2c909638, 7d4d8d52,
79928ae1; `same_plan_as_best` is `false` in all five records), so the
Experiment 4 failure it was written for could not arise. Rounds 4 and 5
were measured, compared, and lost on the number.

They lost because each of them is **half a plan**, and the missing half is
whatever the gateway dropped that round:

| | round 4 | round 5 |
|---|---|---|
| what never landed | phase **A** (`A` + `A.retry`, both 503) | phase **B** (`B` + `B.retry`, both 503) |
| function hints | **none** | k2, k6 `inline_always` |
| loop hints | k3 loop `unroll_count_4` | **none** |
| ratio | **1.0089** [1.0064, 1.0112] | **1.0660** [1.0637, 1.0682] |
| confirmation | 1.0060 | 1.0669 |
| k2 case | 1.0044 | **1.6764** |
| k3 case | **1.0409** | 0.9856 |
| accepted | no --- below the incumbent's 1.0741 | no --- below the incumbent's 1.0741 |

Round 4 is round 3 with the +67.8% removed; round 5 is round 3 with the
+4.4% removed. Neither is a worse *decision* than round 3 --- they are the
same decisions with a request missing. Two details are worth keeping:

* **`forced_top1` could not fire in round 4's phase A.** The readout record
  says `all_keep_default: true, forced: null, ranking: []`. A phase whose
  every answer is "no answer" has no probabilities, so there is no
  1−P(KEEP) ranking to take a top-1 from. This is the correct behaviour and
  it is *not* what happened in round 1, where the phase really was answered
  and really was all-`KEEP`. The two cases look identical in `choices` and
  are opposite in meaning; only the `why` block separates them.
* **Round 5's phase A dropped three of round 3's five function hints.**
  Given round 3's measurement, `k1_step` fell from P(pick) 0.47 to
  `KEEP_DEFAULT`, `k3_fill_run` from 0.33 to `KEEP_DEFAULT`, and
  `k7_error_path` from 0.08 to `KEEP_DEFAULT`, leaving exactly `k2_mix`
  (P 0.82) and `k6_hot_loop` (P 0.65). The filter of Experiment 4 is still
  working: three inert hints removed in one round, and the one that pays
  kept and reinforced. Round 5's plan is, to the entry, **Experiment 4's
  accepted plan minus the k8 width-8** --- and this run had already beaten
  it in round 3.

### 4.3 The gateway, plainly

| | requests | landed | never landed |
|---|--:|--:|--:|
| phase requests (`A`, `B`, and their re-sends) | 16 | 5 phases | **5 of 10 phases** |
| exploration requests (`A.explore`, `B.explore`) | 5 | **5 of 5** | 0 |
| total | **21** | | |

**Half of this run's phase requests never got through**: A in rounds 1, 2
and 4, B in rounds 2 and 5. Every one of the five exploration requests
landed, two of them after an internal 503 and its backoff, so the
`.explore.retry` added in 1.5 **never fired**. It was added for a real risk
and the risk did not materialise; that is the honest report of it, and the
code stays because the risk was real.

This is not a property of Jev and it is not a property of the request: the
bodies are the sizes Experiment 4 sent successfully at the same endpoint on
the previous evening, and no request was ever modified to make it succeed.
It is a property of the gateway on the morning of 2026-09-23, and it is the
largest single source of noise in this experiment --- not in the timings, in
the *search*. A run that lost none of its phases would have had five rounds
of both phases instead of two and a half.

## 5. Scored against the oracle

`scripts/hintbench_exp4_score.py run artifacts/hintbench-search/jev-v42-r5`,
against the oracle's own `rounds.jsonl` and the twelve truths of `exp4.md`
1.3 --- the same rule and the same script Experiment 4 was scored with:

| round | exact | same-family | miss | **harmful** | ratio | share of the combination (training) |
|---|--:|--:|--:|--:|--:|--:|
| 1 | 5 | 0 | 7 | **1** | 0.9369 | **−71.7%** |
| 2 | 8 | 0 | 4 | 0 | 1.0079 | 8.9% |
| **3** | **7** | **0** | **5** | **0** | **1.0741** | **84.2%** |
| 4 | **10** | 0 | 2 | 0 | 1.0089 | 10.1% |
| 5 | 9 | 0 | 3 | 0 | 1.0660 | 74.9% |

The accepted plan, site by site:

| site | kind | pick | truth | verdict | what it is worth |
|---|---|---|---|---|---|
| `fn:k1_step` | fn | `inline_always` | `KEEP_DEFAULT` | miss | build identical to the baseline |
| `fn:k2_mix` | fn | `inline_always` | `inline_always` | **exact** | **1.6775** |
| `fn:k3_fill_run` | fn | `inline_always` | `KEEP_DEFAULT` | miss | inert at k3, costs elsewhere |
| `fn:k4_count_bytes` | fn | `KEEP_DEFAULT` | `KEEP_DEFAULT` | exact | --- |
| `fn:k5_mul_reduce` | fn | `KEEP_DEFAULT` | `KEEP_DEFAULT` | exact | --- |
| `fn:k6_hot_loop` | fn | `inline_always` | `KEEP_DEFAULT` | miss | 1.0011 at k6, 0.9718 at k3 |
| `fn:k7_error_path` | fn | `inline_always` | `KEEP_DEFAULT` | miss | build identical to the baseline |
| `fn:k8_scale_add` | fn | `KEEP_DEFAULT` | `KEEP_DEFAULT` | exact | --- |
| `k3_fill_run@lib.rs:174` | loop | **`unroll_count_4`** | `unroll_count_4` | **exact** | **1.0436** |
| `k4_count_bytes@macros.rs:180` | loop | `KEEP_DEFAULT` | `KEEP_DEFAULT` | exact | --- |
| `k5_mul_reduce@macros.rs:180` | loop | `KEEP_DEFAULT` | `KEEP_DEFAULT` | exact | --- |
| `k8_scale_add@range.rs:1103` | loop | `KEEP_DEFAULT` | `vectorize_width_16` | **miss** | **1.0881, the whole gap** |

**7 exact, 0 same-family, 5 miss, 0 harmful, 84.2% of the combination on
training and 85.5% on the third batch.**

### 5.1 The exact-match score and the speed are almost unrelated

Round 4 scores **10 of 12**, the best of the run, and is **+0.9%**. Round 3
scores **7 of 12** and is **+7.4%**. Eight of the twelve truths are
`KEEP_DEFAULT`, and answering `KEEP_DEFAULT` correctly is worth nothing;
one truth (k2's `inline_always`) is worth 67.8% and another (the k8 loop) is
worth 8.8%. A score out of twelve weights the eight free answers exactly as
heavily as the two that pay.

Against Experiment 4, which is the comparison the brief asks for:

| | Experiment 4 | Experiment 5 |
|---|--:|--:|
| best plan, training | 1.0679 | **1.0741** |
| best plan, third batch | 1.0673 | **1.0724** |
| share of the combination, training | 77.1% | **84.2%** |
| share of the combination, third batch | 79.4% | **85.5%** |
| exact / same-family / miss / harmful | 9 / 1 / 2 / 0 | **7 / 0 / 5 / 0** |
| rounds accepted | 2 | 2 |
| harmful picks that reached a build | 2 (round 1) | 1 (round 1) |
| harmful picks that survived a round | 0 | 0 |

**The exact count fell and the speed rose**, and both have the same cause.
Experiment 5 found `unroll.count=4` at the k3 loop, which is worth +4.4% and
which Experiment 4 never tried; it also carried four inert `inline_always`
(k1, k3, k6, k7) that Experiment 4 did not, because exploration forces a
non-`KEEP` answer at a site whose right answer is "none of them". Three of
the four cost nothing measurable. The accepted plan's k3 is 1.0402 where
`unroll_count_4` alone is 1.0436, and the oracle's one-factor arms point the
right way --- `inline_always` is 0.9718 at k3 from k6 and 0.9873 at k3 from
k2 (`results.md` 134) --- but they do not compose: 1.0436 x 0.9718 x 0.9873
is 1.0014, not 1.0402. The direction of the shortfall is attributable; its
size is not.

### 5.2 The two hints this experiment was built to find

| | reached by exploration? | offered to Jev? | picked? | in the final plan? |
|---|---|---|---|---|
| k3 loop `unroll.count=4` (+4.4%) | **yes**, round 2 | yes, 11 candidates, no `KEEP` | **yes**, P 0.31 (over `unroll_disable` 0.28) | **yes** |
| k8 loop `vectorize.width=16` (+8.8%) | **yes**, round 1 | yes, 11 candidates, no `KEEP` | **no** --- ranked 11th of 11 at **P 0.01**; picked `unroll_count_2` | no |

**One of two.** The mechanism did its half of the job at both sites: it
identified the untried site, it removed `KEEP_DEFAULT`, and it put every
untried candidate in front of the model with its frozen description. At k3
the model took the +4.4%. At k8 it ranked the +8.8% last but one, and
because one exploration answer makes a site permanently tried, k8 was never
asked again.

The k8 loop's verdict block is the one `post_vectorize` improved most, and
it is worth reading next to that P 0.01 (the full block is 1.4):

```
  - what LLVM did with this loop in the baseline build, recorded by the
    plugin itself after LoopVectorize had run ... LLVM vectorized it, with
    vectors of 8 lanes, interleaved 4 times (the vectorized loop's induction
    variable advances 32 elements per iteration).
  - vectorisation legality: LEGAL, and already taken --- the baseline
    vectorizes this loop with no hint at all.
  - no-op check: 8 is the width LLVM already uses here, so the candidate
    `vectorize_width_8` asks for the state this site is in and the build it
    produces can only be the baseline's.
```

That block did exactly what decision 87 (c) asked of it: `vectorize_width_8`
collapsed from P 0.60 (Experiment 4) to **P 0.01**, and the site stopped
asking for the state it was already in. What it did not do is suggest that
the next width up might be better. The state says "LLVM chose 8"; the model
reads that as "8 is right" rather than "8 is a choice LLVM made and 16 is
the untried alternative". The fact that removed a wrong answer did not
produce the right one.

## 6. Cost, and deviations

| | |
|---|--:|
| wall clock, 5 rounds + batch 1 | **31.1 min** (06:47--07:18 JST) |
| batch 2 | ~3 min |
| HTTP requests | 21 (10 landed, 11 exhausted with 503) |
| Choice questions | 109 |
| latency, total / mean / max | 16.3 s / 776 ms / 975 ms |
| tokens in / out | 141 901 / 3 833 |
| cost | **$0.00** (Vercel AI Gateway, Hobby free tier) |
| Jev's share of the run's wall clock | **0.87%** |

Deviations and things not established:

* **The third batch was taken twice** (3.1). The deviation, its rule and its
  cost (3.8 points of headline share) are recorded there. Batch 1 is kept.
* **Half the phase requests never landed** (4.3). Rounds 4 and 5 are
  therefore not five clean rounds of a five-round search, and the run's
  "five rounds" should be read as two and a half rounds of both phases plus
  two half-rounds. A re-run with a healthy gateway would not be expected to
  reproduce rounds 4 and 5.
* **Random is not re-run** (1.1), and Experiment 4's random control stands.
* `exploration_sites` skips a site permanently once **any** candidate has
  been tried there, in any round, accepted or not. Round 1's `forced_top1`
  spent the k4 loop's only eligibility on the oracle's −42% (2.2), and
  round 1's exploration spent k8's on `unroll_count_2` (2.3). Whether a
  budget that allowed a site to be explored twice would have found the k8
  width 16 is **not measured here**.
* The k3 `unroll.count=4` result rests on one exploration answer whose
  margin was 0.31 against 0.28 (2.4). Nothing here establishes that the
  answer is robust; it establishes that it was offered, taken, measured and
  kept.
* Eight of the twelve truths are `KEEP_DEFAULT`, so the 12-site score is a
  weak instrument on this target (5.1). The ratio and its share of the
  combination are the measurements; the score is context.
