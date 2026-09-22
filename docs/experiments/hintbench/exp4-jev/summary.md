# jev-opt search run `jev-v4-r5`

target `hintbench`, proposer `jev`, case set `holdout-as-search` (k1, k2, k3, k4, k5, k6, k7, k8), 15 repetitions, warmup 3, pinned to CPU 8, gap 0 ms, vocabulary `v4-2026-09-22`, state format `state-v4.1-2026-09-22`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first).

| round | site | candidate | code vs base | fn hints | loop hints | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 2 | 3 | none | yes | 0.9931 | [0.9905, 0.9957] | - | - | no | 1.0001 ±0.0016 | no |
| 2 | combination | - | code | 2 | 1 | none | yes | 1.0628 | [1.0590, 1.0660] | - | - | no | 0.9982 ±0.0039 | yes |
| 3 | combination | - | code | 2 | 1 | none | yes | 1.0636 | [1.0614, 1.0659] | - | - | no | 0.9983 ±0.0024 | no |
| 4 | combination | - | code | 2 | 1 | none | yes | 1.0669 | [1.0627, 1.0718] | - | - | no | 1.0019 ±0.0044 | no |
| 5 | combination | - | code | 2 | 1 | none | yes | 1.0679 | [1.0644, 1.0715] | - | - | no | 1.0020 ±0.0030 | yes |

Best plan: round-05 (round 5, ratio 1.0679). `best-plan.json` is a copy of it.

Jev: 12 HTTP requests, 76 Choice questions, 19.9 s of latency in total (max 3541 ms), 207911 input + 5969 output tokens, $0.00000000, 1.14% of the run's wall clock.

Holdout (holdout, measured once, after the best plan was frozen): ratio 1.0673, 95% CI [1.0645, 1.0704], in-run A/A 1.0034 ±0.0024, MDE 0.0334.
