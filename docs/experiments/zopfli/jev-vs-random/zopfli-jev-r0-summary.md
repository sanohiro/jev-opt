# jev-opt search run `zopfli-jev-r0`

target `zopfli`, proposer `jev`, case set `training` (text, binary, json), 15 repetitions, warmup 3, pinned to CPU 2, gap 0 ms, vocabulary `v6-2026-09-23`, state format `state-v6.0-2026-09-23`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 7 | 1 | fn:zopfli::squeeze::lz77_optimal=inline_always, fn:zopfli::squeeze::get_best_lengths=inline_always | 5ed127e9 | none | yes | 0.9826 | [0.9803, 0.9851] | - | - | no | 1.0009 ±0.0024 | no |
| 2 | combination | - | code | 4 | 3 | fn:zopfli::squeeze::lz77_optimal_run=inline_always, zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1=unroll_count_4, zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2=unroll_disable | 2004a60a | none | yes | 0.9656 | [0.9624, 0.9683] | - | - | no | 1.0002 ±0.0016 | no |
| 3 | combination | - | code | 3 | 2 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3=unroll_disable | 156c0102 | none | yes | 0.9681 | [0.9662, 0.9698] | - | - | no | 0.9979 ±0.0020 | no |
| 4 | combination | - | code | 2 | 3 | none | 2bed2881 | none | yes | 0.9684 | [0.9671, 0.9697] | - | - | no | 0.9996 ±0.0017 | no |
| 5 | combination | - | code | 2 | 4 | none | a2bc360f | none | yes | 0.9861 | [0.9842, 0.9880] | - | - | no | 1.0001 ±0.0018 | no |

Best plan: baseline (round 0, ratio 1.0000). `best-plan.json` is a copy of it.

Jev: 14 HTTP requests, 55 Choice questions, 24.2 s of latency in total (max 2250 ms), 189860 input + 4735 output tokens, $0.00000000, 0.70% of the run's wall clock.
Gateway (decision 92 d): 14 requests in 108 HTTP attempts, 14 landed, 0 exhausted; 0 phase(s) lost, 0 round(s) lost and not built; 188.5 s spent waiting between attempts and re-sends.

Holdout (holdout, measured once, after the best plan was frozen): ratio 1.0008, 95% CI [0.9993, 1.0022], in-run A/A 1.0004 ±0.0015, MDE 0.0300.
