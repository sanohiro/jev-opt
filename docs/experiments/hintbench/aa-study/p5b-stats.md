pin `taskset -c 8`, warmup 3, 15 timed rounds, base `c112xxxxxxxxxxxxxxxxxxxxxxxxxxx`, bootstrap 10000 resamples seed 20260921, ASLR randomize_va_space=2

| label | workload | mean ms | median ms | min ms | ratio vs base | 95% CI | half-width |
|---|---|---|---|---|---|---|---|
| c112xxxxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 329.9 | 330.5 | 325.9 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 335.6 | 333.5 | 330.3 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c96xxxxxxxxxxxx | k5 | 359.4 | 359.4 | 355.6 | 0.9181 | [0.9133, 0.9226] | 0.46% |
| c96xxxxxxxxxxxx | k8 | 345.2 | 341.8 | 337.8 | 0.9722 | [0.9584, 0.9855] | 1.35% |
| c80xx | k5 | 330.1 | 330.4 | 325.8 | 0.9995 | [0.9934, 1.0057] | 0.61% |
| c80xx | k8 | 348.2 | 346.4 | 335.3 | 0.9637 | [0.9477, 0.9805] | 1.64% |

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|---|---|---|
| c112xxxxxxxxxxxxxxxxxxxxxxxxxxx | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c96xxxxxxxxxxxx | 0.9447 | [0.9388, 0.9503] | 0.57% |
| c80xx | 0.9815 | [0.9723, 0.9908] | 0.93% |

half-width per workload (worst over non-base labels): k5 0.61%, k8 1.64%
worst half-width 1.64% -> MDE = max(2 x half-width, 3%) = 3.28%
