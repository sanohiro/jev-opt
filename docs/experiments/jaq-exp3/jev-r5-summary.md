# jev-opt search run `jev-r5`

target `jaq`, proposer `jev`, case set `training` (objsearch, strproc, readwrite), 15 repetitions, warmup 3, pinned to CPU 4, gap 250 ms, vocabulary `v1-2026-09-22`, state format `state-v1-2026-09-22`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first).

| round | fn hints | loop hints | ambiguous keys | apply problems | correct | ratio | 95% CI | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | 0 | 0 | none | yes | 0.9934 | [0.9862, 1.0006] | 0.9999 ±0.0073 | no |
| 2 | 0 | 0 | 0 | none | yes | 0.9976 | [0.9915, 1.0039] | 0.9918 ±0.0078 | no |
| 3 | 0 | 0 | 0 | none | yes | 1.0019 | [0.9968, 1.0071] | 1.0129 ±0.0068 | no |
| 4 | 0 | 0 | 0 | none | yes | 0.9902 | [0.9846, 0.9958] | 1.0166 ±0.0073 | no |
| 5 | 0 | 0 | 0 | none | yes | 1.0009 | [0.9947, 1.0073] | 0.9920 ±0.0076 | no |

Best plan: baseline (round 0, ratio 1.0000). `best-plan.json` is a copy of it.

Jev: 10 HTTP requests, 155 Choice questions, 13.8 s of latency in total (max 1858 ms), 257674 input + 10665 output tokens, $0.00000000, 0.77% of the run's wall clock.

Holdout (holdout, measured once, after the best plan was frozen): ratio 0.9787, 95% CI [0.9727, 0.9856], in-run A/A 0.9906 ±0.0094, MDE 0.0395.
