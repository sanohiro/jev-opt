pin `taskset -c 8`, warmup 3, 15 timed rounds, base `S112xxxxxxxxxxxxxxxxxxxxxxxxxxxx`, bootstrap 10000 resamples seed 20360924, ASLR randomize_va_space=2

| label | workload | mean ms | median ms | min ms | ratio vs base | 95% CI | half-width |
|---|---|---|---|---|---|---|---|
| S112xxxxxxxxxxxxxxxxxxxxxxxxxxxx | k5a0 | 330.4 | 330.7 | 327.1 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| S112xxxxxxxxxxxxxxxxxxxxxxxxxxxx | k5a7 | 360.9 | 361.3 | 357.0 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| S112xxxxxxxxxxxxxxxxxxxxxxxxxxxx | k5a25 | 361.9 | 362.1 | 357.1 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| S112xxxxxxxxxxxxxxxxxxxxxxxxxxxx | k5a41 | 362.6 | 362.5 | 357.1 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| S112xxxxxxxxxxxxxxxxxxxxxxxxxxxx | k5a57 | 331.4 | 331.9 | 325.9 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| S112xxxxxxxxxxxxxxxxxxxxxxxxxxxx | k8a0 | 339.3 | 335.4 | 331.4 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| S112xxxxxxxxxxxxxxxxxxxxxxxxxxxx | k8a6 | 345.4 | 342.1 | 336.0 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| S112xxxxxxxxxxxxxxxxxxxxxxxxxxxx | k8a25 | 347.0 | 343.3 | 340.6 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| S096xxxxxxxxxxxx | k5a0 | 361.6 | 360.7 | 356.1 | 0.9138 | [0.9051, 0.9205] | 0.77% |
| S096xxxxxxxxxxxx | k5a7 | 331.5 | 331.8 | 327.2 | 1.0889 | [1.0854, 1.0925] | 0.35% |
| S096xxxxxxxxxxxx | k5a25 | 335.2 | 333.2 | 326.5 | 1.0797 | [1.0616, 1.0916] | 1.50% |
| S096xxxxxxxxxxxx | k5a41 | 330.9 | 330.4 | 326.7 | 1.0958 | [1.0890, 1.1043] | 0.77% |
| S096xxxxxxxxxxxx | k5a57 | 360.1 | 359.9 | 355.7 | 0.9204 | [0.9151, 0.9259] | 0.54% |
| S096xxxxxxxxxxxx | k8a0 | 348.6 | 352.9 | 337.7 | 0.9734 | [0.9580, 0.9911] | 1.65% |
| S096xxxxxxxxxxxx | k8a6 | 338.0 | 338.7 | 266.3 | 1.0220 | [0.9939, 1.0599] | 3.30% |
| S096xxxxxxxxxxxx | k8a25 | 335.5 | 333.9 | 330.2 | 1.0341 | [1.0218, 1.0480] | 1.31% |

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|---|---|---|
| S112xxxxxxxxxxxxxxxxxxxxxxxxxxxx | 1.0000 | [1.0000, 1.0000] | 0.00% |
| S096xxxxxxxxxxxx | 1.0137 | [1.0088, 1.0187] | 0.49% |

half-width per workload (worst over non-base labels): k5a0 0.77%, k5a7 0.35%, k5a25 1.50%, k5a41 0.77%, k5a57 0.54%, k8a0 1.65%, k8a6 3.30%, k8a25 1.31%
worst half-width 3.30% -> MDE = max(2 x half-width, 3%) = 6.59%
