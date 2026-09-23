pin `taskset -c 10`, warmup 3, 15 timed rounds, base `c112xxxxxxxxxxxxxxxxxxxxxxxxxxx`, bootstrap 10000 resamples seed 20260921, ASLR randomize_va_space=2

| label | workload | mean ms | median ms | min ms | ratio vs base | 95% CI | half-width |
|---|---|---|---|---|---|---|---|
| c112xxxxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 330.4 | 330.9 | 326.0 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 333.8 | 333.1 | 329.8 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c96xxxxxxxxxxxx | k5 | 358.4 | 358.3 | 355.2 | 0.9221 | [0.9175, 0.9263] | 0.44% |
| c96xxxxxxxxxxxx | k8 | 344.5 | 341.7 | 337.5 | 0.9688 | [0.9559, 0.9811] | 1.26% |
| c80xx | k5 | 329.1 | 328.3 | 325.7 | 1.0039 | [1.0000, 1.0080] | 0.40% |
| c80xx | k8 | 340.8 | 337.0 | 332.9 | 0.9794 | [0.9601, 0.9955] | 1.77% |

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|---|---|---|
| c112xxxxxxxxxxxxxxxxxxxxxxxxxxx | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c96xxxxxxxxxxxx | 0.9451 | [0.9395, 0.9503] | 0.54% |
| c80xx | 0.9916 | [0.9823, 0.9990] | 0.84% |

half-width per workload (worst over non-base labels): k5 0.44%, k8 1.77%
worst half-width 1.77% -> MDE = max(2 x half-width, 3%) = 3.54%
