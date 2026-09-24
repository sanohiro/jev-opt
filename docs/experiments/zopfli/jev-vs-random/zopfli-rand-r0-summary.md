# jev-opt search run `zopfli-rand-r0`

target `zopfli`, proposer `random`, case set `training` (text, binary, json), 15 repetitions, warmup 3, pinned to CPU 2, gap 0 ms, vocabulary `v6-2026-09-23`, state format `state-v6.0-2026-09-23`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 6 | 3 | none | 4ab875c1 | none | yes | 0.9429 | [0.9410, 0.9453] | - | - | no | 1.0000 ±0.0020 | no |
| 2 | combination | - | code | 7 | 2 | none | 0a79b472 | none | yes | 0.9908 | [0.9893, 0.9924] | - | - | no | 1.0002 ±0.0021 | no |
| 3 | combination | - | code | 5 | 0 | none | e90c4a40 | none | yes | 0.9727 | [0.9698, 0.9754] | - | - | no | 0.9996 ±0.0019 | no |
| 4 | combination | - | code | 8 | 2 | none | cfea9118 | none | yes | 0.9702 | [0.9684, 0.9720] | - | - | no | 1.0004 ±0.0022 | no |
| 5 | combination | - | code | 7 | 2 | none | 7f3d3efc | none | yes | 0.9882 | [0.9786, 1.0027] | - | - | not triggered | 0.9879 ±0.0162 | no |

Best plan: baseline (round 0, ratio 1.0000). `best-plan.json` is a copy of it.

Holdout (holdout, measured once, after the best plan was frozen): ratio 1.0360, 95% CI [0.9853, 1.0850], in-run A/A 1.0218 ±0.0373, MDE 0.1826.
