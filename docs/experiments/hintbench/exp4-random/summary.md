# jev-opt search run `random-r5`

target `hintbench`, proposer `random`, case set `holdout-as-search` (k1, k2, k3, k4, k5, k6, k7, k8), 15 repetitions, warmup 3, pinned to CPU 8, gap 0 ms, vocabulary `v4-2026-09-22`, state format `state-v4.1-2026-09-22`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first).

| round | site | candidate | code vs base | fn hints | loop hints | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 6 | 3 | none | yes | 0.9415 | [0.9387, 0.9442] | - | - | no | 1.0015 ±0.0026 | no |
| 2 | combination | - | code | 8 | 4 | none | yes | 0.9947 | [0.9918, 0.9975] | - | - | no | 0.9999 ±0.0030 | no |
| 3 | combination | - | code | 6 | 4 | none | yes | 0.9990 | [0.9954, 1.0024] | - | - | not triggered | 0.9995 ±0.0020 | no |
| 4 | combination | - | code | 8 | 4 | none | yes | 0.7087 | [0.7067, 0.7106] | - | - | no | 1.0010 ±0.0024 | no |
| 5 | combination | - | code | 6 | 3 | none | yes | 0.9952 | [0.9926, 0.9975] | - | - | no | 0.9996 ±0.0026 | no |

Best plan: baseline (round 0, ratio 1.0000). `best-plan.json` is a copy of it.

Holdout (holdout, measured once, after the best plan was frozen): ratio 0.9990, 95% CI [0.9970, 1.0013], in-run A/A 1.0012 ±0.0023, MDE 0.0381.
