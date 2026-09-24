# jev-opt search run `zopfli-jev-r1`

target `zopfli`, proposer `jev`, case set `training` (text, binary, json), 15 repetitions, warmup 3, pinned to CPU 2, gap 0 ms, vocabulary `v6-2026-09-23`, state format `state-v6.0-2026-09-23`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 7 | 1 | fn:zopfli::squeeze::lz77_optimal=inline_always, fn:zopfli::squeeze::get_best_lengths=inline_always | ebad178d | none | yes | 0.9832 | [0.9813, 0.9853] | - | - | no | 1.0005 ±0.0027 | no |
| 2 | combination | - | code | 5 | 3 | fn:zopfli::squeeze::lz77_optimal_run=inline_always, zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2=unroll_count_2, zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2=unroll_disable | 05bfdee7 | none | yes | 0.9669 | [0.9651, 0.9691] | - | - | no | 0.9995 ±0.0025 | no |
| 3 | combination | - | code | 3 | 2 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3=unroll_disable | 0b6f7d3f | none | yes | 0.9657 | [0.9644, 0.9671] | - | - | no | 1.0019 ±0.0016 | no |
| 4 | combination | - | code | 1 | 1 | none | 86e44b27 | none | yes | 0.9967 | [0.9882, 1.0115] | - | - | not triggered | 1.0076 ±0.0104 | no |
| 5 | combination | - | code | 1 | 1 | none | 86e44b27 | none | yes | 0.9895 | [0.9853, 0.9925] | - | - | no | 1.0002 ±0.0016 | no |

Best plan: baseline (round 0, ratio 1.0000). `best-plan.json` is a copy of it.

Jev: 14 HTTP requests, 53 Choice questions, 29.3 s of latency in total (max 2826 ms), 184206 input + 4420 output tokens, $0.00000000, 0.95% of the run's wall clock.
Gateway (decision 92 d): 14 requests in 72 HTTP attempts, 14 landed, 0 exhausted; 0 phase(s) lost, 0 round(s) lost and not built; 117.6 s spent waiting between attempts and re-sends.

Holdout (holdout, measured once, after the best plan was frozen): ratio 1.0029, 95% CI [0.9988, 1.0094], in-run A/A 0.9981 ±0.0029, MDE 0.0303.
