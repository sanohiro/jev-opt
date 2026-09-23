# Experiment 6 (hintbench): revisit budget, the post_vectorize untried line, and a gateway that lands

Four five-round runs of `scripts/jev_search.py --proposer jev --explore 2`
over `targets/hintbench`, one per cell of a 2 x 2 design (revisit budget
off/on x untried line off/on), against the same oracle
(`docs/experiments/hintbench/oracle.md`) and the same baseline binary as
Experiments 4 and 5. Numbers and commands are in `results.md` §150–§159;
this document interprets them. Decisions 93–95 record what follows.

**Headline, honestly.** Three of the four arms reached a best-plan training
ratio of **+7.4% to +7.8%** (84–89% of the oracle combination's training
ratio, 1.0881); the fourth (pv) reached **+5.2%** (59%) because one
exploration pick at the k8 loop was harmful. **0 of 40 phase requests were
lost** to the gateway (Exp5: 5 of 10). Neither mechanism this experiment
added found the k8 `vectorize.width=16` (+8.8%). No per-feature effect is
resolved: the arms are single runs, and Jev's answers vary on
byte-identical input (§4). rev's confirm and panel readings are inflated
by a k5 measurement mode (§2.1) and are not used as its headline.

## 1. What was run, and what differs from Exp5

Pre-registration: `results.md` §150 (arms, command template), §151 (rules
1–9). Commits, all before the first arm:

| commit | what |
|---|---|
| af01508 | vocabulary v5: v4 minus the three `align` candidates and `unroll.disable` (decision 85; all dead or duplicate in the oracle sweep) |
| b489e5d | deterministic 503 policy (fixed 2 s ±20% pause seeded by the body's sha256, 200 attempts / 600 s wall per request, 2 byte-identical resends) and the round gate (a lost phase loses the round, never a half plan) — decision 92 d |
| 366a35f | `--explore-revisit R` (one more exploration visit per already-tried site, frozen text `r1`) and `--pv-untried on` (a mechanical sentence after each `post_vectorize` width/IC fact naming the untried vocabulary values) — decision 92 b, c |
| 2bf0504 | pre-registration (§150, §151) |
| 904401c | `docs/search-driver.md` for the three driver commits |

| arm | run id | `--explore-revisit` | `--pv-untried` | state format |
|---|---|--:|---|---|
| control | exp6-ctl | 0 | off | `state-v5.0-2026-09-23` |
| revisit | exp6-rev | 1 | off | `state-v5.0-2026-09-23` |
| pv | exp6-pv | 0 | on | `state-v5.1-2026-09-23` |
| both | exp6-both | 1 | on | `state-v5.1-2026-09-23` |

Frozen and identical to Exp5: marks, the 12-site set (8 functions + 4
loops), k1..k8, n=15, warmup 3, `taskset -c 8`, seeds (round
20260921+r, confirm +100000, holdout 20260921, panel 20260927),
`--readout forced_top1`, `--source-comments strip`, `--explore 2`, and the
baseline binary (whole-binary sha256 `07498197…`, `run-manifest.json`
`baseline_bin_sha256` in all four arms). Because vocabulary, state format
and gateway policy all changed, **exp6-ctl vs Exp5 is not an attributable
comparison** (§150); the attributable comparisons are within Exp6 and
against the oracle.

## 2. The four arms side by side

| | ctl | rev | pv | both |
|---|--:|--:|--:|--:|
| best round | 2 | 3 | 2 | 4 |
| training (best round) | **1.0742** | **1.0780** | **1.0518** | **1.0754** |
| share of the combination (1.0881) | 84.27% | 88.48% | 58.82% | 85.61% |
| driver confirm | 1.0776 | 1.1082 ⚠ | 1.0598 | 1.0722 |
| holdout (`--measure-holdout`) | 1.0735 | 1.0812 | 1.0525 | 1.0725 |
| panel batch 2 (A/A) | 1.0751 (0.9875 **fail**) | 1.1083 ⚠ (0.9864 **fail**) | 1.0551 (0.9846 **fail**) | 1.0769 (1.0010 pass) |
| panel batch 2b (A/A) | 1.0743 (1.0002 pass) | 1.1107 ⚠ (1.0012 pass) | 1.0661 (0.9864 **fail**) | not owed |
| lost phases (of 10) | 0 | 0 | 0 | 0 |
| rule 3 (a)/(b)/(c) | n/a | fail/fail/fail | n/a | **pass**/fail/fail |
| rule 4: P(`vectorize_width_16`) at k8, round-1 `B.explore` | 0.01 | 0.01 | 0.02 | 0.02 |
| wall clock (`wall_s`) | 1730.9 s | 1822.8 s | 1806.0 s | 1659.9 s |

⚠ = the k5 mode effect, §2.1. Sources: `artifacts/hintbench-search/<arm>/rounds.jsonl`,
`run-manifest.json`, `holdout/stats.json`, `holdout-batch2{,b}/stats.json`;
`scripts/hintbench_exp4_score.py run …` for the share.

**Gateway per phase** (`run-manifest.json` `gateway.attempts_by_phase`):

| arm | A req / attempts / mean bytes | B req / attempts / mean bytes | explore req / attempts / mean bytes | seconds waiting |
|---|---|---|---|--:|
| ctl | 5 / 50 / 70 655 | 5 / 22 / 48 206 | 4 / 4 / 21 567 | 124.7 |
| rev | 5 / 31 / 71 181 | 5 / 8 / 39 587 | 8 / 10 / 20 202 | 62.7 |
| pv | 5 / 22 / 70 658 | 5 / 14 / 49 963 | 5 / 8 / 20 633 | 60.3 |
| both | 5 / 14 / 71 082 | 5 / 11 / 41 241 | 9 / 13 / 21 339 | 38.8 |

Every request landed (`landed` = `requests` in every cell).

### 2.1 exp6-rev's five readings of one binary, per case

exp6-rev's round-3 binary was measured five times against the same
baseline and read two ways: ~8% (training 1.0780, holdout 1.0812) and ~11%
(confirm 1.1082, panel 1.1083, panel 1.1107). Per case (`per_workload.cand[k].ratio_vs_base`):

| batch (file) | k1 | k2 | k3 | k4 | **k5** | k6 | k7 | k8 | aggregate | A/A |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| training (`round-03/stats.json`) | 0.9991 | 1.6997 | 1.0368 | 1.0095 | **1.0226** | 1.0047 | 1.0026 | 0.9958 | 1.0780 | 1.0001 |
| holdout (`holdout/stats.json`) | 1.0031 | 1.6974 | 1.0420 | 1.0155 | **1.0213** | 1.0020 | 1.0066 | 1.0060 | 1.0812 | 0.9987 |
| confirm (`round-03/confirm/stats.json`) | 1.0053 | 1.6893 | 1.0391 | 1.0134 | **1.2835** | 1.0019 | 1.0080 | 0.9813 | 1.1082 | 1.0001 |
| panel b2 (`holdout-batch2/stats.json`) | 1.0009 | 1.6959 | 1.0342 | 1.0159 | **1.2857** | 1.0000 | 0.9986 | 0.9941 | 1.1083 | 0.9864 |
| panel b2b (`holdout-batch2b/stats.json`) | 1.0015 | 1.6981 | 1.0396 | 1.0079 | **1.2879** | 0.9997 | 1.0092 | 1.0007 | 1.1107 | 1.0012 |

**Only k5 flips** (1.02 vs 1.28); every other kernel agrees within about
one point across all five, k8 included (0.981–1.006, k8 is merely the
widest). The same file, the same plan (k5 loop `unroll.count=8`), two
readings. The raw means say why (`per_workload.<label>.k5.mean_s`):

| batch | base k5 | cand k5 | aa k5 |
|---|--:|--:|--:|
| training | 361.8 ms | 353.8 ms | 360.7 ms |
| holdout | 359.0 | 351.5 | 357.0 |
| confirm | 329.4 | 256.6 | 329.1 |
| panel b2 | 330.6 | 257.1 | **359.8** |
| panel b2b | 330.7 | 256.8 | 330.0 |

k5 is **bimodal per label per batch**: the baseline binary runs k5 at
~358–362 ms or ~326–333 ms, and this candidate at ~352 ms or ~257 ms. In
the fast mode `unroll.count=8` at k5 is worth +28%; in the slow mode +2%.

The mode is not random across batch types. Over all four arms, **every**
driver round batch (seeds 20260922–26, 20 batches) and every
`--measure-holdout` batch (seed 20260921, 4) read the baseline's k5 in the
slow mode (357–363 ms); **every** driver confirm batch (seeds 2036092x, 18)
and every panel's base leg (seed 20260927, 7) in the fast mode (326–333 ms).
Experiments 4 and 5 show the same split (`jev-v4-r5`, `jev-v42-r5`: rounds
350–354 ms, confirms 320–337 ms). k8 moves with it by ~2% (slow ~343–351 ms,
fast ~334–343 ms). The code paths of a round batch and its confirm batch
differ only in the shuffle seed (`measure()` in `scripts/jev_search.py`;
the seed permutes label order per (round, workload), `scripts/bench.py`
110–116) and in what ran just before; the cause is **not investigated**,
and neither alone explains it: rev's holdout batch started at 16:31:02,
the second its round-5 confirm batch ended, and base k5 went from 326.9 ms
to 359.0 ms (so not "what ran before"); yet in the oracle sweep all 85
batches, confirm seeds included, read base k5 slow (349.8–366.5 ms,
`artifacts/hintbench-oracle/**/stats.json`), so not simply the seed. The
panel's A/A copy flips independently of base (slow in 4 of 7 panels, §5;
the oracle's holdout panel had base slow and aa fast, 351.3 vs 321.2 ms,
`artifacts/hintbench-oracle-holdout/stats.json`).

Consequences:

* **The discrepancy is in the measurement, not in the plan.** The plan and
  the binary are the same in all five readings. Of the seven Exp6 plans
  that carried k5 loop `unroll.count=8` (rev rounds 1, 3, 4, 5; ctl, pv,
  both round 1), six read k5 1.019–1.024 in their round batch (both's
  round 1 read 0.9593; that plan also had k5 fn `inline(always)`); all six
  that got a confirm batch read 1.275–1.295 there (`rounds.jsonl`
  `per_workload.k5.ratio`, `confirm.per_workload.k5.ratio`). Plans with `KEEP_DEFAULT` at the k5
  loop read ~1.00 in both modes.
* **The A/A leg cannot catch this.** A/A compares two copies of the
  baseline; it fails when those two land in different modes. Here base and
  cand were in the matching mode in every batch, so A/A passed (confirm
  1.0001, panel b2b 1.0012) while the cand's k5 moved by 26 points between
  batches.
* **The oracle's k5-loop truth is a slow-mode number.** The oracle measured
  k5 `unroll.count=8` at 1.0194 (`oracle.md`, candidate table;
  `artifacts/hintbench-oracle/round-43`) with base k5 in the slow mode, as
  in all 85 oracle batches, and the k5 loop's truth is `KEEP_DEFAULT`. The
  combination's 1.0881 is also a slow-mode number. Whether either holds
  in the other mode is unmeasured. This is why rev's panels (1.1083,
  1.1107) can exceed 1.0881 without meaning anything about Jev against the
  oracle.
* **rev's headline is its training ratio, 1.0780**, as pre-registered
  (§151 rule 1), and the 8%/11% discrepancy is **unresolved**.

**The other three arms, per case, same five batches** (cand
`ratio_vs_base`; files as above under each arm's best round):

ctl (round 2; k5 loop `KEEP_DEFAULT`):

| batch | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 | agg |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| training | 0.9996 | 1.6920 | 1.0338 | 1.0095 | 1.0046 | 1.0014 | 0.9968 | 1.0020 | 1.0742 |
| confirm | 1.0049 | 1.6877 | 1.0352 | 1.0118 | 1.0036 | 1.0007 | 1.0045 | 1.0148 | 1.0776 |
| holdout | 1.0027 | 1.6966 | 1.0436 | 1.0091 | 0.9924 | 0.9995 | 0.9999 | 0.9923 | 1.0735 |
| b2 | 1.0040 | 1.6973 | 1.0353 | 1.0061 | 0.9976 | 1.0000 | 0.9978 | 1.0105 | 1.0751 |
| b2b | 1.0005 | 1.6981 | 1.0372 | 1.0136 | 1.0027 | 0.9996 | 0.9964 | 0.9943 | 1.0743 |

pv (round 2; k8 loop `interleave.count=1`):

| batch | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 | agg |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| training | 1.0049 | 1.6983 | 1.0507 | 1.0046 | 1.0019 | 1.0029 | 1.0020 | 0.8259 | 1.0518 |
| confirm | 1.0049 | 1.6899 | 1.0486 | 0.9937 | 0.9986 | 1.0033 | 1.0045 | 0.8936 | 1.0598 |
| holdout | 1.0025 | 1.6892 | 1.0547 | 1.0035 | 1.0001 | 1.0007 | 0.9979 | 0.8416 | 1.0525 |
| b2 | 1.0029 | 1.6947 | 1.0415 | 1.0036 | 1.0008 | 1.0009 | 1.0073 | 0.8568 | 1.0551 |
| b2b | 1.0030 | 1.6941 | 1.0524 | 1.0021 | 0.9997 | 0.9979 | 1.0042 | 0.9298 | 1.0661 |

both (round 4; no batch 2b — not owed):

| batch | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 | agg |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| training | 1.0005 | 1.7023 | 1.0475 | 0.9902 | 0.9959 | 1.0004 | 1.0030 | 1.0134 | 1.0754 |
| confirm | 0.9984 | 1.6953 | 1.0437 | 0.9915 | 0.9986 | 1.0004 | 0.9974 | 1.0008 | 1.0722 |
| holdout | 0.9996 | 1.6878 | 1.0507 | 0.9943 | 1.0032 | 0.9966 | 0.9975 | 0.9959 | 1.0725 |
| b2 | 1.0061 | 1.6974 | 1.0488 | 0.9974 | 1.0030 | 1.0000 | 1.0019 | 1.0072 | 1.0769 |

ctl and both are stable (aggregate spread 0.41 pt and 0.47 pt). pv's
spread (1.43 pt) is entirely k8: its harmful `interleave.count=1` reads
0.826–0.930, the noisiest cell of the experiment.

## 3. Mechanism results

### 3.1 The revisit budget (rule 3)

| arm | (a) k8 loop asked ≥ 2 times by round 4 | (b) width 16 chosen at k8 | (c) kept in final plan |
|---|---|---|---|
| rev | **fail** — asked once (round 1, `new`) | fail | fail (final: `unroll.count=2`) |
| both | **pass** — round 1 `new`, round 2 `revisit` | fail | fail (final: no k8-loop entry) |

**Why rev never revisited k8.** A site is eligible for a revisit only if
"this round's own argmax answer there is `KEEP_DEFAULT`"
(`docs/search-driver.md`, revisit budget), the same clause that guarantees
"no argmax is ever overridden". In rev, after round 1's exploration put
`unroll_count_2` on the k8 loop, the main phase-B argmax there stayed
`unroll_count_2` in every later round it was asked (2, 3, 5), so the site
was never eligible (§153).

**Why both did.** In both, round 2's main phase-B argmax at the k8 loop
went back to `KEEP_DEFAULT` (P 0.61, `exp6-both.jsonl` line 7), which made
it eligible; the revisit offered 9 candidates and Jev picked
`interleave_count_2` (P 0.30). P(`vectorize_width_16`) rose from 0.02 on
the first visit to **0.08** on the revisit — still not chosen. With
`max_visits` 2 spent, k8 was never offered again (§157).

**The conflict, recorded, not designed away.** The eligibility clause
"argmax is `KEEP_DEFAULT`" and the invariant "never override an argmax"
are the same rule, and at a site where Jev keeps committing to a wrong
non-`KEEP` hint (rev's k8: `unroll_count_2`, 1.0164 on its own workload in
the oracle against 1.0881 for width 16) that rule makes the budget
unreachable exactly where it was meant to act. Whether to relax it is a
design question for later (§7).

**What revisits cost.** Every revisit asked, rev and both
(`pick_detail` `kind: "revisit"`):

| arm | round | site | pick (P) | round ratio | accepted / in final plan |
|---|--:|---|---|--:|---|
| rev | 2 | k5 fn | `inline_never` (1.00, only one left) | 1.0045 | no |
| rev | 3 | k4 fn | `inline_never` (1.00) | 1.0780 | **yes / yes** |
| rev | 3 | k3 loop | `unroll_count_2` (0.60; had `unroll_count_4`) | 1.0780 | **yes / yes** |
| rev | 4 | k8 fn | `inline_never` (1.00) | 1.0074 | no |
| rev | 5 | k3 fn | `inline_never` (1.00) | 0.9911 | no |
| both | 2 | k5 fn | `inline_never` (1.00) | 1.0020 | no |
| both | 2 | k8 loop | `interleave_count_2` (0.30) | 1.0020 | no |
| both | 3 | k4 fn | `inline_never` (1.00) | 0.9237 | no |
| both | 3 | k5 loop | `interleave_count_1` (0.30) | **0.9237** | no |
| both | 4 | k8 fn | `inline_never` (1.00) | 1.0754 | **yes / yes** |
| both | 4 | k4 loop | `interleave_count_1` (0.32) | 1.0754 | **yes / yes** |
| both | 5 | k3 fn | `inline_never` (1.00) | 1.0491 | no |

Function revisits are trivial (a 2-way vocabulary leaves one candidate).
Of the four loop revisits, none reached a hint the oracle calls positive;
rev's k3 revisit *replaced* the oracle's `unroll_count_4` with the
same-family `unroll_count_2`; both's round-3 k5-loop revisit picked
`interleave.count=1` at a `KEEP_DEFAULT`-truth site — the oracle's
calibration arm, −70% on k5 (round-3 k5 0.2916) — and cost that round
the whole headline (0.9237); both's round-4 k4-loop revisit
`interleave.count=1` is harmful in isolation (oracle 0.7301) and read
0.9902–0.9974 inside the accepted plan. The speed gate stopped the bad
rounds; no harmful plan was accepted.

### 3.2 The untried line (rule 4)

The sentence was sent: 34 copies in each on-arm, in
`request.questions[*].instructions` (§156, which corrects §155's grep of
`state`). P(`vectorize_width_16`) at the k8 loop, round-1 `B.explore`:
ctl 0.01, rev 0.01, pv 0.02, both 0.02 (Exp5 0.01). **Width 16 was never
chosen at k8 in either on-arm.** As a discovery aid for the hint it was
built to surface, the line is **null**.

What the line may have done instead is §4's second observation: on
`B.explore` at k8, both off-arms picked `unroll_count_2` and both on-arms
picked `interleave_count_1` (harmful, 0.8033 in the oracle). That is n=2 per
cell and is recorded as an observation, not an effect.

## 4. The methodological finding: n=1 arms cannot resolve a 0.5 pt effect

**What the request hashes show** (`request_sha256` in each arm's
`jev-log/<arm>.jsonl`, round 1; after normalizing the state-format header
string, which is the only difference between off- and on-arms in phases A
and A.explore):

| round-1 request | identical in | argmax agreement | max \|ΔP\| on identical input |
|---|---|---|--:|
| A | all four arms (raw sha: ctl≡rev, pv≡both) | all 8 choices identical | 0.08 (ctl/rev), 0.03 (pv/both) |
| A.explore | all four arms | identical | 0.03, 0.04 |
| B | ctl≡rev; pv≡both | **ctl/rev flipped at the k4 loop**: `vectorize_width_16` 0.49 / `KEEP_DEFAULT` 0.39 vs `KEEP_DEFAULT` 0.49 / width 16 0.40 | 0.10, 0.05 |
| B.explore | ctl≡rev; pv≡both | identical within each pair | 0.03, 0.03 |

So:

1. **Jev is not deterministic on byte-identical input.** Probabilities move
   by up to 0.10 and a near-tie argmax flipped once (k4 loop, ctl vs rev).
   `forced_top1` happened to absorb that flip (both built the same round-1
   plan, `plan_sig c0630234…`), but a flip at a site where the readout does
   not rescue it changes the plan.
2. **The k8 pick that cost pv 2.2 points was not on identical input.** The
   `B.explore` requests differ by the untried line; the pick agreed within
   each identical pair (`unroll_count_2` 0.23/0.23 off; `interleave_count_1`
   0.22/0.24 on), with `interleave_count_1`'s P moving 0.12/0.14 → 0.22/0.24,
   more than the within-pair jitter. §155's and §156's reading ("sampling
   variation, not the line") is therefore not supported; neither is the
   opposite at n=2.
3. **One pick at one uninformed site is worth about 2 points of headline.**
   pv − ctl on training is −2.24 pt, and it is the k8 cell (0.8259 ≈ −2.4 pt
   of an 8-case geomean). That is the size of a single sampled difference,
   not a measured variance.
4. **The measurement side is not 0.17 pt either, for every plan.** The same
   binary measured in two arms' round-1 batches read 0.9978 vs 1.0029 (ctl
   vs rev, `bin_sha256 f45bf61f…`, 0.51 pt) and 0.9681 vs 0.9533 (pv vs
   both, `9ca85087…`, 1.48 pt, k5 1.0239 vs 0.9593 and k8 0.7779 vs
   0.7392). Same-binary repeats of accepted plans are tighter: ctl rounds
   2–5 (`66b3c843…`) 1.0742–1.0766, pv rounds 2–5 (`e5ef6bd2…`)
   1.0485–1.0518.

**Therefore every rule-2 difference is reported as not resolved at n=1**
(results.md §159): rev − ctl +0.37 pt, pv − ctl −2.24 pt, both − ctl
+0.12 pt, interaction +1.99 pt on training (confirm and holdout in §159).
§151 rule 2's 0.5 pt bar bounded measurement noise only, and not proposer
sampling; a difference above it at n=1 is not an effect. **What stands**
are the binary mechanism checks (rule 3 (a)(b)(c), rule 4: width 16 never
chosen at k8), which do not depend on the size of a difference.

**Determinism control in the API: none found.** The SystemOne request
body documents `state`, `model` and `questions`, and per question `type`,
`instructions` and `criteria`; no seed, temperature or sampling field
(https://docs.typesafe.ai/api.md). The Python SDK's `system_one()` takes
`state`, `questions`, `model`, `retry`, `timeout`, `extra_headers`,
`extra_body`, `response_model` — no determinism parameter
(https://docs.typesafe.ai/sdk/python/api/clients/sync.md). The full index
(https://docs.typesafe.ai/llms.txt) and the jev-1.13 jaggedness page
(https://docs.typesafe.ai/model-jaggedness/jev-1.13.md) do not mention
seed, temperature or repeatability. TypeSafe's own consistency cookbook
(https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook.md) says
picked labels "can flip inside a single condition" across repeats and
recommends acting on a probability threshold (0.60) rather than the raw
winner. (Checked 2026-09-23; docs only, no API calls.) Replicates, not a
knob, are the way to bound it.

## 5. Measurement

Seven `bench_panel.sh` panels were taken (seed 20260927; A/A = a second
copy of the baseline; rule 1 is ±0.5%):

| panel | file | A/A | aa k5 / k8 | cand | rule 1 |
|---|---|--:|---|--:|---|
| ctl b2 | `exp6-ctl/holdout-batch2/stats.json` | 0.9875 | 0.9146 / 0.9829 | 1.0751 | **fail** |
| ctl b2b | `exp6-ctl/holdout-batch2b/stats.json` | 1.0002 | 0.9974 / 1.0010 | 1.0743 | pass |
| rev b2 | `exp6-rev/holdout-batch2/stats.json` | 0.9864 | 0.9187 / 0.9747 | 1.1083 | **fail** |
| rev b2b | `exp6-rev/holdout-batch2b/stats.json` | 1.0012 | 1.0020 / 1.0008 | 1.1107 | pass |
| pv b2 | `exp6-pv/holdout-batch2/stats.json` | 0.9846 | 0.9236 / 0.9652 | 1.0551 | **fail** |
| pv b2b | `exp6-pv/holdout-batch2b/stats.json` | 0.9864 | 0.9150 / 0.9802 | 1.0661 | **fail** |
| both b2 | `exp6-both/holdout-batch2/stats.json` | 1.0010 | 1.0018 / 1.0107 | 1.0769 | pass |

**4 of 7 A/A legs failed, by −1.25% to −1.54%, every one with the same
pattern**: the aa copy's k5 in the slow mode (356.6–360.7 ms against base's
329–331 ms) and k8 ~2% slow, the other six cases within 0.5%. This is the
bimodal k5 of §2.1 landing on the aa label, not a one-day disturbance: the
split exists since the oracle (the aa label of one of its panels read 1.0938 at k5,
`oracle.md`) and in Exp4/Exp5's artifacts. (Exp5 §147's rejected batch
failed differently — interference outliers of 1.5–2.2x at k7 and k1.)

**pv has no confirmed panel under rule 1** (failed twice; §158). Its
headline stands on training/confirm/holdout; its panel numbers are not
used as confirmed.

**Proposal (not run):** before jaq, an A/A-only panel study on hintbench:
four to six copies of the baseline binary, several seeds (including the
driver's round, confirm and panel seeds), each panel reporting per-label
**k5 and k8 mean_s**, not only ratios; the question is what decides a
label's k5 mode (seed/label order, copy/page placement, or what ran before).
Until it is answered, first panels are not trusted and rule 1's
retake-once rule stays.

## 6. Gateway

**0 of 40 phase requests lost** across the four arms (A+B x 5 rounds x 4),
and 0 of 26 exploration requests, against Exp5's 5 of 10 phase requests
(§149). Attempts per landed request, by phase: A 10.0 / 6.2 / 4.4 / 2.8
(ctl, rev, pv, both), B 4.4 / 1.6 / 2.8 / 2.2, explore 1.0 / 1.25 / 1.6 /
1.44 (§2 table). Phase A (~71 KB) needed the most attempts in every arm and
explore (~21 KB) the fewest; the load fell over the afternoon (ctl 15:29 →
both 18:00).

The probe behind the policy (`docs/search-driver.md`, "Gateway and
retries", 2026-09-23, Exp5 bodies): phase A 85 KB landed 0 of 6, B 51 KB 4
of 18, explore 24 KB 5 of 6. Against that, jaq's phase A (~103–106 KB,
`artifacts/jaq-search/jev-r5/jev-log/jev-r5.jsonl`) landed **5 of 5** on
2026-09-22 (with retries on 3), while its phase B (~118–121 KB) landed 2 of
5 (`jev-r5.log`). Size dependence is the provider's condition of the day,
not a fixed threshold; the fix that works is attempts under a wall budget,
with byte-identical resends (b489e5d), and it absorbed everything today.

## 7. Follow-ups (not blockers)

* **`inline(never)` removes that kernel's loop from phase B's site set for
  the round.** In both, each round's phase-A `inline(never)` (k5 r2, k4 r3,
  k8 r4, k3 r5) was followed by `[A] refreshed loop sites: 3` and that
  kernel's loop was absent from phase B (§157); round 4 therefore never
  asked about the k8 loop, and the score counts 11 of 12 sites there.
  Presumably the out-of-line copy's loop no longer matches the site key in
  the refreshed dump; not investigated, not fixed.
* **The revisit eligibility conflict** (§3.1): at a site where Jev's
  argmax is a wrong non-`KEEP` hint, the budget cannot act.
* **Replicates.** Per-feature effects need n ≥ 3 runs per arm (decision
  94).
* **The k5 mode study** (§5), and whether the oracle's k5 and k8 truths
  hold in the fast mode.

## 8. Cost and deviations

| | ctl | rev | pv | both |
|---|--:|--:|--:|--:|
| wall clock (`wall_s`) | 28.8 min | 30.4 min | 30.1 min | 27.7 min |
| HTTP requests (landed) | 14 | 18 | 15 | 19 |
| Choice questions | 68 | 70 | 69 | 72 |
| latency total / mean / max | 11.9 s / 852 ms / 1358 ms | 14.2 s / 791 ms / 1031 ms | 12.7 s / 847 ms / 1086 ms | 14.6 s / 769 ms / 1081 ms |
| tokens in / out | 236 566 / 5 070 | 250 149 / 4 904 | 244 254 / 5 218 | 261 638 / 5 133 |
| cost | $0.00 | $0.00 | $0.00 | $0.00 |
| Jev share of wall clock | 0.69% | 0.78% | 0.70% | 0.88% |

(From the `# totals` block of each `jev-log/<arm>.log`; seconds waiting on
503s are in §2 and are not in the latency column.) Panels ~2.5 min each.

Deviations:

* **A 29-minute idle gap** between exp6-rev's end (holdout done 16:33:31)
  and its batch 2 (started 17:02:56), caused by the orchestrator's chain
  script, not by the protocol. Nothing ran on the machine in between.
* **§155 misread the untried line as never sent** (it grepped `state`, the
  sentence is in `questions[*].instructions`); §156 corrected it.
* **§155/§156's attribution of pv's k8 pick to sampling** is not supported
  by the request hashes (§4); corrected in §159.
* **§153's "confirm and holdout deltas exceed the 0.5 pt bar"** for rev −
  ctl: the confirm delta (+3.06 pt) is the k5 mode (§2.1), the holdout
  delta (+0.77 pt) is within what one sampled pick can do; neither is an
  effect (§159).
* Batch-2 retakes were run by a chain script after all four arms
  (§154, §158); exp6-both's was not owed.
* Random control not re-run (§151 rule 8); Exp4's 0% stands.
