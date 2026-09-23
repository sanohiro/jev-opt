# jev-opt search run `exp6-rev`

target `hintbench`, proposer `jev`, case set `holdout-as-search` (k1, k2, k3, k4, k5, k6, k7, k8), 15 repetitions, warmup 3, pinned to CPU 8, gap 0 ms, vocabulary `v5-2026-09-23`, state format `state-v5.0-2026-09-23`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

Batches measured on the best plan's own binary: 2 (1.0780, 1.1082), spread 3.02 points. Nothing inside that spread separates two plans.

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 4 | 3 | fn:hbkernels::k5_mul_reduce=inline_always, fn:hbkernels::k4_count_bytes=inline_always, hbkernels::k5_mul_reduce@macros.rs:180:28#d2=unroll_count_8, hbkernels::k8_scale_add@range.rs:1103:12#d2=unroll_count_2 | c0630234 | none | yes | 1.0029 | [1.0004, 1.0056] | - | - | no | 1.0019 ±0.0029 | yes |
| 2 | combination | - | code | 5 | 3 | fn:hbkernels::k8_scale_add=inline_always, fn:hbkernels::k3_fill_run=inline_always, fn:hbkernels::k5_mul_reduce=inline_never, hbkernels::k3_fill_run@lib.rs:174:9#d3=unroll_count_4 | f22be0e0 | none | yes | 1.0045 | [1.0013, 1.0075] | - | - | no | 1.0021 ±0.0021 | no |
| 3 | combination | - | code | 5 | 3 | fn:hbkernels::k1_step=inline_always, fn:hbkernels::k7_error_path=inline_always, fn:hbkernels::k4_count_bytes=inline_never, hbkernels::k3_fill_run@lib.rs:174:9#d3=unroll_count_2 | 4ff56d21 | none | yes | 1.0780 | [1.0750, 1.0810] | - | - | no | 1.0001 ±0.0024 | yes |
| 4 | combination | - | code | 4 | 3 | fn:hbkernels::k8_scale_add=inline_never | 2ac7c6d9 | none | yes | 1.0074 | [1.0051, 1.0098] | - | - | no | 1.0012 ±0.0030 | no |
| 5 | combination | - | code | 3 | 3 | fn:hbkernels::k3_fill_run=inline_never | 206791b6 | none | yes | 0.9911 | [0.9877, 0.9944] | - | - | no | 1.0018 ±0.0030 | no |

Best plan: round-03 (round 3, ratio 1.0780). `best-plan.json` is a copy of it.

Jev: 18 HTTP requests, 70 Choice questions, 14.2 s of latency in total (max 1031 ms), 250149 input + 4904 output tokens, $0.00000000, 0.78% of the run's wall clock.
Gateway (decision 92 d): 18 requests in 49 HTTP attempts, 18 landed, 0 exhausted; 0 phase(s) lost, 0 round(s) lost and not built; 62.7 s spent waiting between attempts and re-sends.

Holdout (holdout, measured once, after the best plan was frozen): ratio 1.0812, 95% CI [1.0774, 1.0849], in-run A/A 0.9987 ±0.0044, MDE 0.0401.
