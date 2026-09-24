# Jev vs random on zopfli (n=3 each)

Six five-round runs of `scripts/jev_search.py` over `targets/zopfli`: three
with `--proposer jev` and three with `--proposer random`, at seed offsets
0/1000/2000. They ran on the six marks and five sites of §166
(`oracle.selected_keys_top6`) with vocabulary v6, against the oracle of
`docs/experiments/zopfli/oracle.md`. The pre-registration is `results.md`
§167, and the numbers and commands are in §169. This document interprets
them. Decision 101 records what follows.

**Headline, honestly.** **Not resolved at n=3, and flat.** No run in either
arm accepted a plan, so every run's representative is the baseline's
1.0000. Both arms have median 1.0000 and range [1.0000, 1.0000], a
difference of 0 pt against a 3% MDE. This is what the oracle predicted:
its ceiling on this site set is +1.8%, under the MDE (§168). It is **not**
a "correct no-ops" result for Jev. Jev proposed non-`KEEP` hints in every
round. 14 of its 15 plans measured slower than the baseline (0.9656–0.9974),
and 6 of them lost more than 3% in both batches. The 15th read 1.0001 with
its CI across 1. The
baseline survived because the speed gate rejected every plan. What Jev
proposed were the oracle's known sub-MDE losses, chiefly
`lz77::find_longest_match inline_always`, and never an oracle-harmful arm.
Its own answers drifted to all-`KEEP_DEFAULT` in 1 of 3 runs. Random drew
the harmful `squeeze.rs:275 unroll_count_8` twice (0.9429 and 0.8803), and
the gate rejected both. Round-1 requests were byte-identical across the three Jev
runs, with max |ΔP| 0.07 and 0 argmax flips, yet a tie on a secondary
probability changed one run's built plan.

## 1. What was run

The command is §167's template, launched by a chain script and checked
against the live process table. It is quoted in full in §169.
`run-manifest.json` has no argv field, so each manifest's parameter fields
were checked instead: `proposer`, `seed_offset` and `seed` (20260921 +
offset), `exploration {k: 2, revisit: 0, pv_untried: off}`,
`readout forced_top1`, `source_comments strip`, vocabulary
`v6-2026-09-23`, state `state-v6.0-2026-09-23`, n 15, warmup 3, CPU 2,
case set `training`, argv0 len 80 / class 96. The provenance hashes
(config, marks, plugin, profdata, baseline binary) equal the oracle's. The
runs alternated jev/random, one at a time:

| run | proposer | seed offset | start–exit (JST 2026-09-24) | `wall_s` |
|---|---|--:|---|--:|
| `zopfli-jev-r0` | jev | 0 | 06:37–07:35 | 3453 s |
| `zopfli-rand-r0` | random | 0 | 07:35–08:23 | 2896 s |
| `zopfli-jev-r1` | jev | 1000 | 08:23–09:15 | 3099 s |
| `zopfli-rand-r1` | random | 1000 | 09:15–10:06 | 3109 s |
| `zopfli-jev-r2` | jev | 2000 | 10:06–11:02 | 3319 s |
| `zopfli-rand-r2` | random | 2000 | 11:02–11:54 | 3130 s |

A round is phase A (one Choice per marked function) followed by phase B
(one Choice per loop site, refreshed after phase A's attributes). Under
`--readout forced_top1`, a phase whose answers are all `KEEP_DEFAULT` still
builds its single best non-`KEEP` candidate. Under `--explore 2`, up to two
not-yet-tried sites per phase are asked again without `KEEP` on offer. So
**no round can build the baseline**, and "keep the baseline" can only be
the outcome of the acceptance gate (`docs/search-driver.md`).

## 2. The two arms side by side

| | jev-r0 | jev-r1 | jev-r2 | rand-r0 | rand-r1 | rand-r2 |
|---|--:|--:|--:|--:|--:|--:|
| accepted rounds | 0 | 0 | 0 | 0 | 0 | 0 |
| **representative** (best accepted, training) | **1.0000** | **1.0000** | **1.0000** | **1.0000** | **1.0000** | **1.0000** |
| round ratios | 0.9826 0.9656 0.9681 0.9684 0.9861 | 0.9832 0.9669 0.9657 0.9967 0.9895 | 0.9825 0.9689 1.0001 0.9974 0.9964 | 0.9429 0.9908 0.9727 0.9702 0.9882 | 0.9712 0.9978 0.9768 0.9646 0.9739 | 0.9787 0.9779 0.8803 0.9801 0.9805 |
| plans beyond −3% in both batches | 3 | 2 | 1 | 1 | 1 | 1 |
| plans with an oracle-harmful arm | 0 | 0 | 0 | 1 (r1) | 0 | 1 (r3) |
| holdout (null arm: baseline vs itself) | 1.0008 | 1.0029 | 0.9971 ⚠ | 1.0360 ⚠ | 1.0219 ⚠ | 1.0019 |
| correct rounds | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |

⚠ = a disturbed batch (MDE 8.9% / 18.3% / 12.6%); see §5.

| arm | median | range | 
|---|--:|---|
| Jev | 1.0000 | [1.0000, 1.0000] |
| random | 1.0000 | [1.0000, 1.0000] |

Pre-registered direction Jev ≥ random: the medians are equal (difference 0 pt, MDE 3%) and the ranges coincide. **Not resolved at
n=3.**

## 3. Mechanism results (k/n)

* **(a) void.** The oracle has no "good" site. As a descriptive line only:
  no Jev plan contains `squeeze.rs:325 unroll_count_8` (the oracle's best
  single arm, sub-MDE +1.3%) or `lz77.rs:563 unroll_count_8`. Jev reached
  `squeeze.rs:325` only by exploration (round 3 of each run) and picked
  `unroll_disable`, at P 0.54 / 0.54 / 0.48. That arm is identical to the
  baseline in the oracle. P(`unroll_count_8`) was 0.02 and
  P(`unroll_count_2`) 0.11–0.18.
* **(b) 3/3, vacuously** (every final plan is the baseline). Over the
  built plans, **0 of 15 Jev plans** contain `squeeze.rs:275
  unroll_count_4/8`. Jev's only entry there was `unroll_disable`, which the
  oracle found identical to the baseline, so this is not evidence of
  avoidance. When that loop was explored, the harmful `unroll_count_4` was
  Jev's second choice (P 0.17–0.19).
* **(c) `KEEP_DEFAULT` at oracle-flat sites: 32/45, 33/43, 42/46 (80%
  overall); 4/7 in round 1 of every run.** Of the 27 non-`KEEP` answers, 21
  are `inline_always` on `find_longest_match` (9), `ZopfliHash::update`
  (6), `find_longest_match_loop` (5) and `lz77_optimal_run` (1). The oracle
  has these at −2.0%, 0.9999, −0.7% and identical, respectively. The
  rate rises with history in every run. In jev-r2 rounds 3–5 every answer
  in both phases was `KEEP_DEFAULT`, and those plans exist only through
  `forced_top1` (plus one exploration pick in round 3). **Jev's own answers reached "keep the baseline" in 1 of 3
  runs, and in 0 of 3 in round 1.**

Why Jev's plans lost more often than random's. All six Jev plans beyond −3%
carry `find_longest_match inline_always` (−2.0% alone in the oracle) plus
unrolls at `lz77.rs:530` and/or `lz77.rs:563`. Multiplying the oracle's
single-arm round ratios predicts −2.2% to −3.4% for these plans, and they
measured −3.1% to −3.4% in their round batches. The oracle timed each
unroll only under the baseline's inlining, not under the changed
inlining these plans used. Random spread its picks, so it built
fewer such plans (3 of 15) but two much worse ones (0.9429 and 0.8803),
both carrying the harmful arm.

## 4. Nondeterminism

Round-1 requests (empty history) were **byte-identical in all three pairs**
of Jev runs for phases A, A.explore and B (`request_sha256`). Later rounds
differ, because the history differs.

| round-1 phase | questions | max \|ΔP\| per pair (r0–r1 / r0–r2 / r1–r2) | argmax flips |
|---|--:|---|--:|
| A | 6 | 0.07 / 0.07 / 0.07 | 0 / 0 / 0 |
| A.explore | 2 | 0.06 / 0.03 / 0.03 | 0 / 0 / 0 |
| B | 1 | 0.02 / 0.01 / 0.02 | 0 / 0 / 0 |

This is tighter than hintbench's 0.10 and one flip (`../hintbench/exp6.md`
§4). The two phase-A near-ties (`ZopfliHash::update`, `find_longest_match`,
margins 0.01–0.16) held. **The built plan still differed.** Phase B was
all-`KEEP`, so `forced_top1` took the best non-`KEEP` candidate at
`index.rs:184`. That was `unroll_count_4` (0.07 / 0.08 vs 0.05) in r0 and
r2, but a 0.07 / 0.07 tie in r1 went to `unroll_count_2`. So r0 and r2 built
plan `5ed127e9…`, and r1 built `ebad178d…`. Zero argmax flips do not mean
identical plans when a readout reads secondary probabilities.

Measurement-only component: the same binary in different batches read
0.9826 / 0.9825 (`3a7068aa…`), 0.9656 / 0.9684 / 0.9689 (`6469d3a8…`,
0.33 pt), 1.0001 / 0.9974 / 0.9964 (`25e9dca2…`, 0.37 pt) and 0.9727 /
0.9739 (`f7d611dd…`, one random plan from each of two runs).

## 5. Measurement

Every batch was taken at argv0 class 96. zopfli has no argv0 mode (decision
99). In-run A/A: the aggregate CI excluded 1 in 4 of 28 Jev batches and
2 of 29 random batches, all within ±0.8%. Disturbed batches were:
jev-r1 round 4 (MDE 6.58%, A/A 1.0076 ±0.0104), rand-r0 round 5 (MDE 6.67%),
rand-r1 round-5 confirmation (MDE 12.76%), and three holdouts,
jev-r2 (8.89%), rand-r0 (18.26%) and rand-r1 (12.56%). In rand-r1's
holdout the CI of the baseline against itself excludes 1 ([1.0006,
1.0554]). All holdouts are null arms, since the best plan is the baseline,
so they carry no transfer information. The disturbed batches affect no
verdict: none was accepted and none is a representative. What disturbed
them is not recorded.

## 6. Gateway

Every run's 14 requests landed, with 0 exhausted, 0 lost phases and 0 lost
rounds, so all runs are valid under §167's ">2 of 10 lost" rule.

| run | A req / attempts | B req / attempts | explore req / attempts | seconds waiting |
|---|---|---|---|--:|
| jev-r0 | 5 / 61 | 5 / 42 | 4 / 5 | 188.5 |
| jev-r1 | 5 / 23 | 5 / 37 | 4 / 12 | 117.6 |
| jev-r2 | 5 / 65 | 5 / 65 | 4 / 4 | 238.9 |

The mean body is about 57.6 KB for phase A, 39–44 KB for phase B and 18.6
KB for explore. The largest attempt count for a single request was 41
(jev-r2 round 5 B), well within 200 attempts / 600 s.

## 7. Cost and deviations

| | jev-r0 | jev-r1 | jev-r2 |
|---|--:|--:|--:|
| HTTP requests (landed) | 14 | 14 | 14 |
| Choice questions | 55 | 53 | 56 |
| latency total / max | 24.2 s / 2250 ms | 29.3 s / 2826 ms | 27.9 s / 3047 ms |
| tokens in / out | 189 860 / 4 735 | 184 206 / 4 420 | 192 948 / 4 865 |
| cost | $0.00 | $0.00 | $0.00 |
| Jev share of wall clock | 0.70% | 0.95% | 0.84% |

The totals are 42 requests (§167 cap ≤ 75), 164 questions, 567 014 / 14 020
tokens and $0. Wall clock was 48–58 min per run, above §167's "30–50 min"
floor estimate.

Deviations:

* **No `best-plan.json` in any run.** `summary.md` claims one ("a copy of
  it") even when the best is the baseline (`plan: null`). This is a driver
  inconsistency; it was recorded and not patched. The copies in
  `jev-vs-random/` therefore contain no `best-plan.json` files.
* The holdouts are null arms, and three of them are disturbed (§5).
* No run needed a `-b` rerun, a resume or a manual intervention.

## 8. What this does and does not establish

Established, on zopfli under O3 + native + fat LTO + CGU 1 + PGO, with
vocabulary v6, 6 marks and 5 sites:
* Neither proposer produced an accepted plan in 3 runs each. The
  acceptance gate kept the baseline every time, including against
  random's −5.7% and −12.0% plans.
* Jev never built an oracle-harmful arm (0/15). The hints it did choose
  are sub-MDE losses in the oracle, and the same function-attribute pick
  (`find_longest_match inline_always`) recurs in round 1 of every run.
* Jev's round-1 answers are stable on identical input (0 flips, |ΔP| ≤
  0.07), and the forced readout can still turn a 0.02 wobble into a
  different plan.

Not established:
* Any Jev-vs-random difference in outcome (0 pt, not resolved).
* Whether Jev finds a good hint on a real program where one exists. This
  site set has none (oracle ceiling +1.8%).
* `cache.rs:108` (Stage 0's lever), which lies outside the site set by the
  cap rule (§166). Adding it is the owner's call.

Files in `jev-vs-random/`: each run's `summary.md` (as
`<run>-summary.md`) and `run-manifest.json` (as `<run>-manifest.json`), and
the three Jev `.log` files.
