# jev-opt search run `random-r5`

target `jaq`, proposer `random`, case set `training` (objsearch, strproc, readwrite), 15 repetitions, warmup 3, pinned to CPU 4, gap 250 ms, vocabulary `v1-2026-09-22`, state format `state-v1-2026-09-22`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first).

| round | fn hints | loop hints | ambiguous keys | apply problems | correct | ratio | 95% CI | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 119 | 16 | 3 | none | yes | 0.9510 | [0.9453, 0.9571] | 0.9874 ±0.0050 | no |
| 2 | 138 | 15 | 3 | none | yes | 1.0017 | [0.9948, 1.0080] | 0.9991 ±0.0090 | no |
| 3 | 136 | 14 | 3 | none | yes | 1.0193 | [1.0053, 1.0353] | 1.0173 ±0.0144 | yes |
| 4 | 137 | 14 | 3 | none | yes | 0.9959 | [0.9893, 1.0022] | 0.9755 ±0.0719 | no |
| 5 | 119 | 14 | 3 | none | yes | 0.9134 | [0.9068, 0.9201] | 0.9896 ±0.0074 | no |

Best plan: round-03 (round 3, ratio 1.0193). `best-plan.json` is a copy of it.

Holdout (holdout, measured once, after the best plan was frozen): ratio 0.9809, 95% CI [0.9764, 0.9857], in-run A/A 0.9879 ±0.0059, MDE 0.0300.
