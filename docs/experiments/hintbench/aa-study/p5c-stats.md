pin `taskset -c 8`, warmup 3, 15 timed rounds, base `c112xxxxxxxxxxxxxxxxxxxxxxxxxxx`, bootstrap 10000 resamples seed 20260921, ASLR randomize_va_space=2

| label | workload | mean ms | median ms | min ms | ratio vs base | 95% CI | half-width |
|---|---|---|---|---|---|---|---|
| c112xxxxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 332.8 | 332.9 | 327.6 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 338.8 | 337.0 | 332.2 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c96xxxxxxxxxxxx | k5 | 362.1 | 360.9 | 358.1 | 0.9191 | [0.9143, 0.9232] | 0.44% |
| c96xxxxxxxxxxxx | k8 | 353.4 | 354.5 | 342.3 | 0.9587 | [0.9470, 0.9710] | 1.20% |
| c80xx | k5 | 345.5 | 335.1 | 327.9 | 0.9632 | [0.9006, 1.0014] | 5.04% |
| c80xx | k8 | 346.5 | 342.1 | 338.2 | 0.9776 | [0.9604, 0.9952] | 1.74% |

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|---|---|---|
| c112xxxxxxxxxxxxxxxxxxxxxxxxxxx | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c96xxxxxxxxxxxx | 0.9387 | [0.9322, 0.9452] | 0.65% |
| c80xx | 0.9704 | [0.9357, 0.9940] | 2.92% |

half-width per workload (worst over non-base labels): k5 5.04%, k8 1.74%
worst half-width 5.04% -> MDE = max(2 x half-width, 3%) = 10.08%
