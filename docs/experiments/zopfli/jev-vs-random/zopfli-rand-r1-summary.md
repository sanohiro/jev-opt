# jev-opt search run `zopfli-rand-r1`

target `zopfli`, proposer `random`, case set `training` (text, binary, json), 15 repetitions, warmup 3, pinned to CPU 2, gap 0 ms, vocabulary `v6-2026-09-23`, state format `state-v6.0-2026-09-23`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 7 | 3 | none | 07265085 | none | yes | 0.9712 | [0.9695, 0.9728] | - | - | no | 1.0004 ±0.0016 | no |
| 2 | combination | - | code | 5 | 3 | none | 3d4ecc7f | none | yes | 0.9978 | [0.9961, 0.9994] | - | - | no | 1.0000 ±0.0020 | no |
| 3 | combination | - | code | 5 | 2 | none | d3297f1e | none | yes | 0.9768 | [0.9748, 0.9788] | - | - | no | 1.0002 ±0.0017 | no |
| 4 | combination | - | code | 6 | 2 | none | 6f15ca7a | none | yes | 0.9646 | [0.9619, 0.9680] | - | - | no | 1.0012 ±0.0028 | no |
| 5 | combination | - | code | 7 | 0 | none | 311bdb22 | none | yes | 0.9739 | [0.9710, 0.9763] | - | - | no | 0.9980 ±0.0030 | no |

Best plan: baseline (round 0, ratio 1.0000). `best-plan.json` is a copy of it.

Holdout (holdout, measured once, after the best plan was frozen): ratio 1.0219, 95% CI [1.0006, 1.0554], in-run A/A 1.0101 ±0.0154, MDE 0.1256.
