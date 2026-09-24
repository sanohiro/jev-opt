# jev-opt search run `zopfli-jev-r2`

target `zopfli`, proposer `jev`, case set `training` (text, binary, json), 15 repetitions, warmup 3, pinned to CPU 2, gap 0 ms, vocabulary `v6-2026-09-23`, state format `state-v6.0-2026-09-23`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | combination | - | code | 7 | 1 | fn:zopfli::squeeze::lz77_optimal=inline_always, fn:zopfli::squeeze::get_best_lengths=inline_always | 5ed127e9 | none | yes | 0.9825 | [0.9808, 0.9843] | - | - | no | 1.0020 ±0.0013 | no |
| 2 | combination | - | code | 4 | 3 | fn:zopfli::squeeze::lz77_optimal_run=inline_always, zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2=unroll_count_2, zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2=unroll_disable | 2004a60a | none | yes | 0.9689 | [0.9672, 0.9707] | - | - | no | 1.0019 ±0.0035 | no |
| 3 | combination | - | code | 1 | 2 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3=unroll_disable | 6ebf497b | none | yes | 1.0001 | [0.9988, 1.0013] | - | - | not triggered | 1.0005 ±0.0019 | no |
| 4 | combination | - | code | 1 | 1 | none | 47effc94 | none | yes | 0.9974 | [0.9953, 0.9995] | - | - | no | 1.0010 ±0.0020 | no |
| 5 | combination | - | code | 1 | 1 | none | 47effc94 | none | yes | 0.9964 | [0.9931, 0.9990] | - | - | no | 1.0044 ±0.0051 | no |

Best plan: baseline (round 0, ratio 1.0000). `best-plan.json` is a copy of it.

Jev: 14 HTTP requests, 56 Choice questions, 27.9 s of latency in total (max 3047 ms), 192948 input + 4865 output tokens, $0.00000000, 0.84% of the run's wall clock.
Gateway (decision 92 d): 14 requests in 134 HTTP attempts, 14 landed, 0 exhausted; 0 phase(s) lost, 0 round(s) lost and not built; 238.9 s spent waiting between attempts and re-sends.

Holdout (holdout, measured once, after the best plan was frozen): ratio 0.9971, 95% CI [0.9922, 1.0004], in-run A/A 0.9871 ±0.0163, MDE 0.0889.
