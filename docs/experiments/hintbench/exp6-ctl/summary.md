# jev-opt search run `exp6-ctl`

target `hintbench`, proposer `jev`, case set `holdout-as-search` (k1, k2, k3, k4, k5, k6, k7, k8), 15 repetitions, warmup 3, pinned to CPU 8, gap 0 ms, vocabulary `v5-2026-09-23`, state format `state-v5.0-2026-09-23`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

Batches measured on the best plan's own binary: 2 (1.0742, 1.0776), spread 0.34 points. Nothing inside that spread separates two plans.

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 4 | 3 | fn:hbkernels::k5_mul_reduce=inline_always, fn:hbkernels::k4_count_bytes=inline_always, hbkernels::k5_mul_reduce@macros.rs:180:28#d2=unroll_count_8, hbkernels::k8_scale_add@range.rs:1103:12#d2=unroll_count_2 | c0630234 | none | yes | 0.9978 | [0.9950, 1.0006] | - | - | not triggered | 0.9979 ±0.0036 | no |
| 2 | combination | - | code | 4 | 1 | fn:hbkernels::k8_scale_add=inline_always, fn:hbkernels::k3_fill_run=inline_always | 72df1081 | none | yes | 1.0742 | [1.0680, 1.0808] | - | - | no | 0.9991 ±0.0067 | yes |
| 3 | combination | - | code | 4 | 1 | fn:hbkernels::k1_step=inline_always, fn:hbkernels::k7_error_path=inline_always | 956dbda2 | none | yes | 1.0744 | [1.0720, 1.0767] | - | - | no | 0.9999 ±0.0029 | no |
| 4 | combination | - | code | 2 | 1 | none | 4423cac1 | none | yes | 1.0766 | [1.0718, 1.0816] | - | - | no | 1.0009 ±0.0040 | no |
| 5 | combination | - | code | 2 | 1 | none | 4423cac1 | none | yes | 1.0752 | [1.0727, 1.0784] | - | - | no | 1.0016 ±0.0017 | no |

Best plan: round-02 (round 2, ratio 1.0742). `best-plan.json` is a copy of it.

Jev: 14 HTTP requests, 68 Choice questions, 11.9 s of latency in total (max 1358 ms), 236566 input + 5070 output tokens, $0.00000000, 0.69% of the run's wall clock.
Gateway (decision 92 d): 14 requests in 76 HTTP attempts, 14 landed, 0 exhausted; 0 phase(s) lost, 0 round(s) lost and not built; 124.7 s spent waiting between attempts and re-sends.

Holdout (holdout, measured once, after the best plan was frozen): ratio 1.0735, 95% CI [1.0709, 1.0759], in-run A/A 0.9998 ±0.0032, MDE 0.0300.
