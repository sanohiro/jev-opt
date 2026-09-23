# jev-opt search run `exp6-pv`

target `hintbench`, proposer `jev`, case set `holdout-as-search` (k1, k2, k3, k4, k5, k6, k7, k8), 15 repetitions, warmup 3, pinned to CPU 8, gap 0 ms, vocabulary `v5-2026-09-23`, state format `state-v5.1-2026-09-23`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

Batches measured on the best plan's own binary: 2 (1.0518, 1.0598), spread 0.80 points. Nothing inside that spread separates two plans.

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 4 | 3 | fn:hbkernels::k5_mul_reduce=inline_always, fn:hbkernels::k4_count_bytes=inline_always, hbkernels::k5_mul_reduce@macros.rs:180:28#d2=unroll_count_8, hbkernels::k8_scale_add@range.rs:1103:12#d2=interleave_count_1 | 1fc44ee1 | none | yes | 0.9681 | [0.9611, 0.9754] | - | - | no | 1.0011 ±0.0030 | no |
| 2 | combination | - | code | 4 | 2 | fn:hbkernels::k8_scale_add=inline_always, fn:hbkernels::k3_fill_run=inline_always, hbkernels::k3_fill_run@lib.rs:174:9#d3=unroll_count_4 | c03c73f8 | none | yes | 1.0518 | [1.0427, 1.0607] | - | - | no | 0.9998 ±0.0022 | yes |
| 3 | combination | - | code | 4 | 2 | fn:hbkernels::k1_step=inline_always, fn:hbkernels::k7_error_path=inline_always | 3419c13f | none | yes | 1.0500 | [1.0431, 1.0567] | - | - | no | 0.9963 ±0.0039 | no |
| 4 | combination | - | code | 2 | 2 | none | b116db22 | none | yes | 1.0485 | [1.0392, 1.0579] | - | - | no | 0.9991 ±0.0026 | no |
| 5 | combination | - | code | 2 | 2 | none | b116db22 | none | yes | 1.0496 | [1.0422, 1.0570] | - | - | no | 1.0001 ±0.0018 | no |

Best plan: round-02 (round 2, ratio 1.0518). `best-plan.json` is a copy of it.

Jev: 15 HTTP requests, 69 Choice questions, 12.7 s of latency in total (max 1086 ms), 244254 input + 5218 output tokens, $0.00000000, 0.70% of the run's wall clock.
Gateway (decision 92 d): 15 requests in 44 HTTP attempts, 15 landed, 0 exhausted; 0 phase(s) lost, 0 round(s) lost and not built; 60.3 s spent waiting between attempts and re-sends.

Holdout (holdout, measured once, after the best plan was frozen): ratio 1.0525, 95% CI [1.0428, 1.0616], in-run A/A 0.9986 ±0.0030, MDE 0.1081.
