# jev-opt search run `exp6-both`

target `hintbench`, proposer `jev`, case set `holdout-as-search` (k1, k2, k3, k4, k5, k6, k7, k8), 15 repetitions, warmup 3, pinned to CPU 8, gap 0 ms, vocabulary `v5-2026-09-23`, state format `state-v5.1-2026-09-23`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

Batches measured on the best plan's own binary: 2 (1.0754, 1.0722), spread 0.32 points. Nothing inside that spread separates two plans.

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 4 | 3 | fn:hbkernels::k5_mul_reduce=inline_always, fn:hbkernels::k4_count_bytes=inline_always, hbkernels::k5_mul_reduce@macros.rs:180:28#d2=unroll_count_8, hbkernels::k8_scale_add@range.rs:1103:12#d2=interleave_count_1 | 1fc44ee1 | none | yes | 0.9533 | [0.9321, 0.9689] | - | - | no | 1.0009 ±0.0033 | no |
| 2 | combination | - | code | 5 | 3 | fn:hbkernels::k8_scale_add=inline_always, fn:hbkernels::k3_fill_run=inline_always, fn:hbkernels::k5_mul_reduce=inline_never, hbkernels::k3_fill_run@lib.rs:174:9#d3=unroll_count_4, hbkernels::k8_scale_add@range.rs:1103:12#d2=interleave_count_2 | 67be15da | none | yes | 1.0020 | [0.9971, 1.0065] | - | - | not triggered | 1.0005 ±0.0023 | no |
| 3 | combination | - | code | 5 | 2 | fn:hbkernels::k1_step=inline_always, fn:hbkernels::k7_error_path=inline_always, fn:hbkernels::k4_count_bytes=inline_never, hbkernels::k5_mul_reduce@macros.rs:180:28#d2=interleave_count_1 | b04d3c61 | none | yes | 0.9237 | [0.9216, 0.9261] | - | - | no | 0.9978 ±0.0027 | no |
| 4 | combination | - | code | 3 | 2 | fn:hbkernels::k8_scale_add=inline_never, hbkernels::k4_count_bytes@macros.rs:180:28#d2=interleave_count_1 | 67015c81 | none | yes | 1.0754 | [1.0705, 1.0803] | - | - | no | 1.0013 ±0.0043 | yes |
| 5 | combination | - | code | 3 | 1 | fn:hbkernels::k3_fill_run=inline_never | e6aed8ff | none | yes | 1.0491 | [1.0444, 1.0537] | - | - | no | 0.9989 ±0.0032 | no |

Best plan: round-04 (round 4, ratio 1.0754). `best-plan.json` is a copy of it.

Jev: 19 HTTP requests, 72 Choice questions, 14.6 s of latency in total (max 1080 ms), 261638 input + 5133 output tokens, $0.00000000, 0.88% of the run's wall clock.
Gateway (decision 92 d): 19 requests in 38 HTTP attempts, 19 landed, 0 exhausted; 0 phase(s) lost, 0 round(s) lost and not built; 38.8 s spent waiting between attempts and re-sends.

Holdout (holdout, measured once, after the best plan was frozen): ratio 1.0725, 95% CI [1.0694, 1.0754], in-run A/A 0.9999 ±0.0029, MDE 0.0389.
