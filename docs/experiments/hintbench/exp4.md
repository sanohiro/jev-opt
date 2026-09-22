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

<!-- TRUTH TABLE -->

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

<!-- ROUND 1 DIFF -->

**(b) A 503 burst cost a whole round.** Decision 87 recorded a gateway 503
burst that exhausted all three internal retries on both phases of one
repeat; `scripts/jev_oneshot.py` already re-sent such a request **unchanged**
and kept both lines in the JSONL, and `jev_search.py` did not --- a phase
whose every answer is `no answer` becomes all-`KEEP_DEFAULT` with no
probabilities, so `forced_top1` cannot fire either and the round rebuilds
the baseline. One round in five is 20% of the run. `JevProposer.choose` now
does what the one-shot harness does. **It fired on round 1 of this very
run** (phase A, three consecutive 503s), and both lines are in the log.

No request is ever modified to make it succeed.

<!-- RESULTS -->
