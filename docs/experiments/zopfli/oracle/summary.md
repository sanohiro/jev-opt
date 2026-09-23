# jev-opt search run `oracle`

target `zopfli`, proposer `oracle`, case set `training` (text, binary, json), 15 repetitions, warmup 3, pinned to CPU 2, gap 0 ms, vocabulary `v6-2026-09-23`, state format `state-v6.0-2026-09-23`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its plan differs from the incumbent's, its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first). A round whose plan is the incumbent's plan is the incumbent's binary: it is recorded as one more independent batch on it and cannot re-promote it (decision 89 a).

Batches measured on the best plan's own binary: 2 (1.0181, 1.0206), spread 0.25 points. Nothing inside that spread separates two plans.

| round | site | candidate | code vs base | fn hints | loop hints | explored | plan | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | fn:zopfli::lz77::find_longest_match_loop | inline_always | code | 1 | 0 | none | 5b56f361 | none | yes | 0.9932 | [0.9901, 0.9963] | - | - | no | 1.0014 ±0.0036 | no |
| 2 | fn:zopfli::lz77::find_longest_match_loop | inline_never | identical | 1 | 0 | none | e154afc0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 3 | fn:zopfli::squeeze::lz77_optimal | inline_always | code | 1 | 0 | none | 28c373c6 | none | yes | 0.9874 | [0.9846, 0.9902] | - | - | no | 1.0008 ±0.0022 | no |
| 4 | fn:zopfli::squeeze::lz77_optimal | inline_never | identical | 1 | 0 | none | c3407682 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 5 | fn:zopfli::squeeze::get_best_lengths | inline_always | identical | 2 | 0 | none | 947145db | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 6 | fn:zopfli::squeeze::get_best_lengths | inline_never | code | 2 | 0 | none | b07c703e | none | yes | 0.9799 | [0.9764, 0.9832] | - | - | no | 1.0000 ±0.0042 | no |
| 7 | fn:zopfli::squeeze::lz77_optimal_run | inline_always | identical | 2 | 0 | none | 55bf3080 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 8 | fn:zopfli::squeeze::lz77_optimal_run | inline_never | code | 2 | 0 | none | 926b18a6 | none | yes | 0.9779 | [0.9718, 0.9842] | - | - | no | 0.9995 ±0.0060 | no |
| 9 | fn:<zopfli::hash::ZopfliHash>::update | inline_always | code | 1 | 0 | none | 72a9c503 | none | yes | 0.9999 | [0.9958, 1.0041] | - | - | not triggered | 1.0021 ±0.0035 | no |
| 10 | fn:<zopfli::hash::ZopfliHash>::update | inline_never | code | 1 | 0 | none | 4817ecc9 | none | yes | 0.9914 | [0.9894, 0.9936] | - | - | no | 0.9985 ±0.0030 | no |
| 11 | fn:zopfli::lz77::find_longest_match | inline_always | code | 2 | 0 | none | cbcfb42d | none | yes | 0.9799 | [0.9754, 0.9851] | - | - | no | 1.0025 ±0.0048 | no |
| 12 | fn:zopfli::lz77::find_longest_match | inline_never | code | 2 | 0 | none | 5e3e263a | none | yes | 0.9777 | [0.9753, 0.9803] | - | - | no | 1.0011 ±0.0032 | no |
| 13 | zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1 | unroll_count_2 | code | 0 | 1 | none | 2681853c | none | yes | 0.9856 | [0.9836, 0.9876] | - | - | no | 0.9976 ±0.0037 | no |
| 14 | zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1 | unroll_count_4 | code | 0 | 1 | none | 9ea319b7 | none | yes | 0.9943 | [0.9886, 0.9998] | - | - | no | 1.0029 ±0.0059 | no |
| 15 | zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1 | unroll_count_8 | code | 0 | 1 | none | 99d53f48 | none | yes | 0.9906 | [0.9865, 0.9942] | - | - | no | 0.9990 ±0.0041 | no |
| 16 | zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1 | vectorize_width_2 | identical | 0 | 1 | none | 0c2d9fab | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 17 | zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1 | vectorize_width_4 | identical | 0 | 1 | none | 6e220753 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 18 | zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1 | vectorize_width_8 | identical | 0 | 1 | none | 44205d25 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 19 | zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1 | vectorize_width_16 | identical | 0 | 1 | none | 396535e5 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 20 | zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1 | interleave_count_1 | identical | 0 | 1 | none | 8b90ec0a | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 21 | zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1 | interleave_count_2 | identical | 0 | 1 | none | 2137abc0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 22 | zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1 | interleave_count_4 | identical | 0 | 1 | none | a386007a | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 23 | zopfli::lz77::find_longest_match_loop@lz77.rs:530:11#d1 | unroll_disable | identical | 0 | 1 | none | c62b5193 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 24 | zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2 | unroll_count_2 | code | 0 | 1 | none | fb23bbc9 | none | yes | 0.9843 | [0.9827, 0.9860] | - | - | no | 1.0009 ±0.0016 | no |
| 25 | zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2 | unroll_count_4 | code | 0 | 1 | none | 14e468e3 | none | yes | 0.9639 | [0.9595, 0.9677] | - | - | no | 0.9984 ±0.0029 | no |
| 26 | zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2 | unroll_count_8 | code | 0 | 1 | none | d7f23bd2 | none | yes | 0.9169 | [0.9149, 0.9189] | - | - | no | 1.0005 ±0.0029 | no |
| 27 | zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2 | vectorize_width_2 | identical | 0 | 1 | none | 897f9369 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 28 | zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2 | vectorize_width_4 | identical | 0 | 1 | none | ff30154c | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 29 | zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2 | vectorize_width_8 | identical | 0 | 1 | none | 81c3b1d7 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 30 | zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2 | vectorize_width_16 | identical | 0 | 1 | none | 96d0709e | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 31 | zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2 | interleave_count_1 | identical | 0 | 1 | none | 3cafecdd | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 32 | zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2 | interleave_count_2 | identical | 0 | 1 | none | 5072f73e | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 33 | zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2 | interleave_count_4 | identical | 0 | 1 | none | 04b46935 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 34 | zopfli::squeeze::lz77_optimal@squeeze.rs:275:11#d2 | unroll_disable | identical | 0 | 1 | none | e1113ce7 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 35 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3 | unroll_count_2 | code | 0 | 1 | none | a5d5bdee | none | yes | 1.0095 | [1.0056, 1.0133] | - | - | no | 0.9991 ±0.0027 | yes |
| 36 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3 | unroll_count_4 | code | 0 | 1 | none | 63a7c895 | none | yes | 1.0072 | [1.0034, 1.0110] | - | - | no | 1.0013 ±0.0035 | no |
| 37 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3 | unroll_count_8 | code | 0 | 1 | none | b1dd4899 | none | yes | 1.0126 | [1.0096, 1.0154] | - | - | no | 1.0006 ±0.0038 | yes |
| 38 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3 | vectorize_width_2 | identical | 0 | 1 | none | d081556c | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 39 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3 | vectorize_width_4 | identical | 0 | 1 | none | 7fa3de8d | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 40 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3 | vectorize_width_8 | identical | 0 | 1 | none | d565e801 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 41 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3 | vectorize_width_16 | identical | 0 | 1 | none | 96142730 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 42 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3 | interleave_count_1 | identical | 0 | 1 | none | a7ecec2e | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 43 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3 | interleave_count_2 | identical | 0 | 1 | none | 9895cbe8 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 44 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3 | interleave_count_4 | identical | 0 | 1 | none | f41af0d3 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 45 | zopfli::squeeze::lz77_optimal@squeeze.rs:325:9#d3 | unroll_disable | identical | 0 | 1 | none | abab561f | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 46 | zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2 | unroll_count_2 | code | 0 | 1 | none | c06d4684 | none | yes | 1.0041 | [1.0016, 1.0068] | - | - | no | 0.9984 ±0.0040 | no |
| 47 | zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2 | unroll_count_4 | code | 0 | 1 | none | a6e91025 | none | yes | 1.0044 | [1.0020, 1.0068] | - | - | no | 1.0014 ±0.0031 | no |
| 48 | zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2 | unroll_count_8 | code | 0 | 1 | none | 1e98fe8f | none | yes | 1.0050 | [1.0011, 1.0089] | - | - | no | 0.9979 ±0.0029 | no |
| 49 | zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2 | vectorize_width_2 | code | 0 | 1 | none | 45c3e978 | none | yes | 0.9997 | [0.9968, 1.0025] | - | - | not triggered | 0.9985 ±0.0019 | no |
| 50 | zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2 | vectorize_width_4 | code | 0 | 1 | none | e1f4c9c0 | none | yes | 0.9935 | [0.9850, 1.0000] | - | - | no | 1.0026 ±0.0083 | no |
| 51 | zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2 | vectorize_width_8 | code | 0 | 1 | none | ce22ffb7 | none | yes | 0.9981 | [0.9947, 1.0014] | - | - | not triggered | 0.9970 ±0.0045 | no |
| 52 | zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2 | vectorize_width_16 | identical | 0 | 1 | none | 4d28a959 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 53 | zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2 | interleave_count_1 | code | 0 | 1 | none | 5f38fb07 | none | yes | 1.0010 | [0.9963, 1.0059] | - | - | not triggered | 0.9978 ±0.0066 | no |
| 54 | zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2 | interleave_count_2 | code | 0 | 1 | none | 3b38d42f | none | yes | 0.9997 | [0.9946, 1.0045] | - | - | not triggered | 1.0006 ±0.0051 | no |
| 55 | zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2 | interleave_count_4 | identical | 0 | 1 | none | 9fec63e8 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 56 | zopfli::lz77::find_longest_match_loop@lz77.rs:563:21#d2 | unroll_disable | code | 0 | 1 | none | ff90c082 | none | yes | 0.9980 | [0.9933, 1.0029] | - | - | not triggered | 0.9998 ±0.0051 | no |
| 57 | <zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1 | unroll_count_2 | code | 0 | 1 | none | b925f625 | none | yes | 0.9978 | [0.9926, 1.0031] | - | - | not triggered | 1.0001 ±0.0068 | no |
| 58 | <zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1 | unroll_count_4 | code | 0 | 1 | none | 288c6f0c | none | yes | 0.9948 | [0.9898, 0.9997] | - | - | no | 0.9997 ±0.0032 | no |
| 59 | <zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1 | unroll_count_8 | code | 0 | 1 | none | 4861b9e3 | none | yes | 0.9977 | [0.9939, 1.0014] | - | - | not triggered | 0.9996 ±0.0035 | no |
| 60 | <zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1 | vectorize_width_2 | identical | 0 | 1 | none | 846c1f53 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 61 | <zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1 | vectorize_width_4 | identical | 0 | 1 | none | c5441200 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 62 | <zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1 | vectorize_width_8 | identical | 0 | 1 | none | c323c6b0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 63 | <zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1 | vectorize_width_16 | identical | 0 | 1 | none | a2e90ff9 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 64 | <zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1 | interleave_count_1 | identical | 0 | 1 | none | 5d47f4d4 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 65 | <zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1 | interleave_count_2 | identical | 0 | 1 | none | 8cf11b35 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 66 | <zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1 | interleave_count_4 | identical | 0 | 1 | none | 52bc6d62 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 67 | <zopfli::hash::ZopfliHash>::update@index.rs:184:12#d1 | unroll_disable | identical | 0 | 1 | none | 0c730a13 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 68 | combination | - | code | 0 | 2 | none | c905f2b9 | none | yes | 1.0181 | [1.0159, 1.0203] | - | - | no | 1.0011 ±0.0019 | yes |

Best plan: round-68 (round 68, ratio 1.0181). `best-plan.json` is a copy of it.

The holdout has NOT been measured by this run (SPEC.ja.md 7: the holdout is measured once, after the best plan is frozen; pass --measure-holdout).
