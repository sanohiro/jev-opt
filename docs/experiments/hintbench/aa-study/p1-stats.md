pin `taskset -c 8`, warmup 3, 15 timed rounds, base `c112xxxxxxxxxxxxxxxxxxxxxxxxx`, bootstrap 10000 resamples seed 20260927, ASLR randomize_va_space=2

| label | workload | mean ms | median ms | min ms | ratio vs base | 95% CI | half-width |
|---|---|---|---|---|---|---|---|
| c80 | k1 | 344.3 | 343.8 | 339.9 | 0.9974 | [0.9921, 1.0033] | 0.56% |
| c80 | k2 | 344.3 | 344.6 | 341.7 | 0.9978 | [0.9943, 1.0011] | 0.34% |
| c80 | k3 | 364.8 | 364.5 | 360.3 | 0.9993 | [0.9946, 1.0042] | 0.48% |
| c80 | k4 | 346.7 | 346.0 | 343.3 | 1.0000 | [0.9973, 1.0023] | 0.25% |
| c80 | k5 | 330.5 | 330.5 | 325.9 | 0.9977 | [0.9924, 1.0033] | 0.54% |
| c80 | k6 | 358.7 | 358.9 | 356.2 | 0.9993 | [0.9967, 1.0019] | 0.26% |
| c80 | k7 | 355.9 | 356.8 | 350.6 | 0.9959 | [0.9884, 1.0034] | 0.75% |
| c80 | k8 | 339.8 | 336.8 | 333.4 | 0.9926 | [0.9744, 1.0100] | 1.78% |
| c96xxxxxxxxxx | k1 | 343.8 | 341.8 | 339.8 | 0.9990 | [0.9929, 1.0050] | 0.60% |
| c96xxxxxxxxxx | k2 | 343.9 | 344.0 | 341.0 | 0.9990 | [0.9953, 1.0026] | 0.36% |
| c96xxxxxxxxxx | k3 | 364.6 | 363.6 | 361.0 | 0.9998 | [0.9939, 1.0056] | 0.59% |
| c96xxxxxxxxxx | k4 | 346.1 | 345.7 | 343.0 | 1.0016 | [0.9982, 1.0047] | 0.33% |
| c96xxxxxxxxxx | k5 | 359.6 | 358.9 | 354.7 | 0.9170 | [0.9119, 0.9219] | 0.50% |
| c96xxxxxxxxxx | k6 | 358.1 | 357.9 | 355.4 | 1.0010 | [0.9989, 1.0030] | 0.21% |
| c96xxxxxxxxxx | k7 | 354.1 | 353.3 | 349.4 | 1.0011 | [0.9957, 1.0075] | 0.59% |
| c96xxxxxxxxxx | k8 | 346.1 | 341.2 | 337.7 | 0.9744 | [0.9599, 0.9904] | 1.53% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k1 | 343.4 | 342.4 | 340.2 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k2 | 343.6 | 343.7 | 340.6 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k3 | 364.5 | 364.2 | 360.4 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k4 | 346.7 | 347.0 | 343.5 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 329.8 | 329.9 | 326.2 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k6 | 358.4 | 357.8 | 356.6 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k7 | 354.5 | 353.6 | 350.0 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 337.3 | 334.7 | 329.8 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k1 | 344.1 | 342.5 | 341.2 | 0.9981 | [0.9925, 1.0040] | 0.58% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k2 | 344.7 | 343.8 | 342.7 | 0.9967 | [0.9925, 1.0006] | 0.41% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k3 | 364.8 | 363.8 | 360.8 | 0.9993 | [0.9942, 1.0042] | 0.50% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k4 | 347.3 | 346.6 | 344.9 | 0.9982 | [0.9949, 1.0012] | 0.31% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 359.6 | 359.0 | 355.5 | 0.9170 | [0.9121, 0.9214] | 0.47% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k6 | 358.5 | 358.3 | 356.3 | 0.9998 | [0.9973, 1.0023] | 0.25% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k7 | 354.8 | 353.9 | 349.8 | 0.9990 | [0.9896, 1.0082] | 0.93% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 352.8 | 355.7 | 340.8 | 0.9559 | [0.9393, 0.9717] | 1.62% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k1 | 343.9 | 342.9 | 339.5 | 0.9986 | [0.9939, 1.0035] | 0.48% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k2 | 344.4 | 344.2 | 340.9 | 0.9976 | [0.9940, 1.0014] | 0.37% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k3 | 364.4 | 364.5 | 360.6 | 1.0003 | [0.9964, 1.0040] | 0.38% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k4 | 347.1 | 346.4 | 344.0 | 0.9987 | [0.9950, 1.0021] | 0.35% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 330.8 | 331.5 | 326.3 | 0.9969 | [0.9927, 1.0007] | 0.40% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k6 | 358.7 | 358.4 | 356.1 | 0.9993 | [0.9970, 1.0017] | 0.24% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k7 | 354.4 | 352.4 | 349.9 | 1.0001 | [0.9939, 1.0058] | 0.60% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 344.0 | 341.1 | 333.4 | 0.9804 | [0.9652, 0.9969] | 1.59% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k1 | 345.0 | 344.7 | 339.5 | 0.9955 | [0.9888, 1.0020] | 0.66% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k2 | 344.6 | 344.1 | 340.5 | 0.9969 | [0.9936, 1.0005] | 0.34% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k3 | 365.5 | 366.3 | 360.4 | 0.9974 | [0.9927, 1.0027] | 0.50% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k4 | 346.3 | 346.5 | 343.9 | 1.0012 | [0.9980, 1.0041] | 0.30% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 359.2 | 358.5 | 356.3 | 0.9180 | [0.9130, 0.9233] | 0.52% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k6 | 358.6 | 358.1 | 356.2 | 0.9996 | [0.9973, 1.0020] | 0.23% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k7 | 358.0 | 358.2 | 352.8 | 0.9902 | [0.9840, 0.9966] | 0.63% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 347.7 | 342.2 | 339.2 | 0.9701 | [0.9509, 0.9887] | 1.89% |

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|---|---|---|
| c80 | 0.9975 | [0.9943, 1.0005] | 0.31% |
| c96xxxxxxxxxx | 0.9862 | [0.9841, 0.9884] | 0.22% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | 0.9825 | [0.9801, 0.9849] | 0.24% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | 0.9965 | [0.9939, 0.9989] | 0.25% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | 0.9832 | [0.9809, 0.9853] | 0.22% |

half-width per workload (worst over non-base labels): k1 0.66%, k2 0.41%, k3 0.59%, k4 0.35%, k5 0.54%, k6 0.26%, k7 0.93%, k8 1.89%
worst half-width 1.89% -> MDE = max(2 x half-width, 3%) = 3.77%
