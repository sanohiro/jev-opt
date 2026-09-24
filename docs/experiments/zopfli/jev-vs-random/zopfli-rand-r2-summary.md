# jev-opt search run `zopfli-rand-r2`

target `zopfli`, proposer `random`, case set `training` (text, binary, json), 15 repetitions, warmup 3, pinned to CPU 2, gap 0 ms, vocabulary `v6-2026-09-23`, state format `state-v6.0-2026-09-23`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 4 | 2 | none | 90de0685 | none | yes | 0.9787 | [0.9771, 0.9804] | - | - | no | 0.9995 ±0.0015 | no |
| 2 | combination | - | code | 3 | 3 | none | bbb4f284 | none | yes | 0.9779 | [0.9755, 0.9802] | - | - | no | 1.0011 ±0.0026 | no |
| 3 | combination | - | code | 4 | 3 | none | 91d2c3bc | none | yes | 0.8803 | [0.8785, 0.8820] | - | - | no | 1.0004 ±0.0025 | no |
| 4 | combination | - | code | 8 | 2 | none | 34fc546c | none | yes | 0.9801 | [0.9794, 0.9808] | - | - | no | 1.0008 ±0.0011 | no |
| 5 | combination | - | code | 6 | 3 | none | 32429c56 | none | yes | 0.9805 | [0.9779, 0.9835] | - | - | no | 1.0018 ±0.0025 | no |

Best plan: baseline (round 0, ratio 1.0000). `best-plan.json` is a copy of it.

Holdout (holdout, measured once, after the best plan was frozen): ratio 1.0019, 95% CI [0.9999, 1.0038], in-run A/A 1.0004 ±0.0018, MDE 0.0300.
