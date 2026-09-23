# jev-opt search run `jev-v42-r5`

target `hintbench`, proposer `jev`, case set `holdout-as-search` (k1, k2, k3, k4, k5, k6, k7, k8), 15 repetitions, warmup 3, pinned to CPU 8, gap 0 ms, vocabulary `v4-2026-09-22`, state format `state-v4.2-2026-09-22`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

Batches measured on the best plan's own binary: 2 (1.0741, 1.0740), spread 0.01 points. Nothing inside that spread separates two plans.

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 2 | 3 | fn:hbkernels::k5_mul_reduce=inline_always, fn:hbkernels::k4_count_bytes=inline_always, hbkernels::k5_mul_reduce@macros.rs:180:28#d2=unroll_count_8, hbkernels::k8_scale_add@range.rs:1103:12#d2=unroll_count_2 | 786fb052 | none | yes | 0.9369 | [0.9340, 0.9400] | - | - | no | 1.0017 ±0.0030 | no |
| 2 | combination | - | code | 2 | 1 | fn:hbkernels::k8_scale_add=inline_always, fn:hbkernels::k3_fill_run=inline_always, hbkernels::k3_fill_run@lib.rs:174:9#d3=unroll_count_4 | dfa05c9b | none | yes | 1.0079 | [1.0051, 1.0107] | - | - | no | 1.0025 ±0.0030 | yes |
| 3 | combination | - | code | 5 | 1 | fn:hbkernels::k1_step=inline_always, fn:hbkernels::k7_error_path=inline_always | 2c909638 | none | yes | 1.0741 | [1.0720, 1.0760] | - | - | no | 0.9995 ±0.0020 | yes |
| 4 | combination | - | code | 0 | 1 | none | 7d4d8d52 | none | yes | 1.0089 | [1.0064, 1.0112] | - | - | no | 1.0004 ±0.0033 | no |
| 5 | combination | - | code | 2 | 0 | none | 79928ae1 | none | yes | 1.0660 | [1.0637, 1.0682] | - | - | no | 1.0006 ±0.0028 | no |

Best plan: round-03 (round 3, ratio 1.0741). `best-plan.json` is a copy of it.

Jev: 21 HTTP requests, 109 Choice questions, 16.3 s of latency in total (max 975 ms), 141901 input + 3833 output tokens, $0.00000000, 0.87% of the run's wall clock.

Holdout (holdout, measured once, after the best plan was frozen): ratio 1.0756, 95% CI [1.0557, 1.0984], in-run A/A 1.0068 ±0.0183, MDE 0.2330.
