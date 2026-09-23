pin `taskset -c 2`, warmup 3, 15 timed rounds, base `base`, bootstrap 10000 resamples seed 20260924, ASLR randomize_va_space=2, argv0 pinned class 96

| label | workload | mean ms | median ms | min ms | ratio vs base | 95% CI | half-width |
|---|---|---|---|---|---|---|---|
| aa | text | 2662.1 | 2659.4 | 2639.2 | 0.9993 | [0.9963, 1.0022] | 0.29% |
| aa | binary | 1619.8 | 1619.6 | 1613.0 | 1.0011 | [0.9982, 1.0040] | 0.29% |
| aa | json | 2663.3 | 2659.5 | 2653.2 | 0.9989 | [0.9957, 1.0019] | 0.31% |
| bestloop | text | 2612.0 | 2610.2 | 2603.5 | 1.0184 | [1.0163, 1.0205] | 0.21% |
| bestloop | binary | 1617.5 | 1617.8 | 1606.5 | 1.0025 | [0.9997, 1.0055] | 0.29% |
| bestloop | json | 2610.4 | 2608.5 | 2582.9 | 1.0191 | [1.0150, 1.0229] | 0.40% |
| base | text | 2660.1 | 2660.4 | 2645.4 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| base | binary | 1621.6 | 1621.9 | 1611.3 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| base | json | 2660.3 | 2660.0 | 2642.5 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| comb | text | 2601.8 | 2600.7 | 2589.0 | 1.0224 | [1.0201, 1.0247] | 0.23% |
| comb | binary | 1616.3 | 1616.0 | 1609.2 | 1.0033 | [1.0003, 1.0065] | 0.31% |
| comb | json | 2588.8 | 2588.6 | 2574.3 | 1.0276 | [1.0255, 1.0301] | 0.23% |

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|---|---|---|
| aa | 0.9998 | [0.9979, 1.0018] | 0.20% |
| bestloop | 1.0133 | [1.0116, 1.0151] | 0.17% |
| base | 1.0000 | [1.0000, 1.0000] | 0.00% |
| comb | 1.0177 | [1.0163, 1.0193] | 0.15% |

half-width per workload (worst over non-base labels): text 0.29%, binary 0.31%, json 0.40%
worst half-width 0.40% -> MDE = max(2 x half-width, 3%) = 3.00%
