pin `taskset -c 8`, warmup 3, 15 timed rounds, base `c112xxxxxxxxxxxxxxxxxxxxxxxxx`, bootstrap 10000 resamples seed 20360922, ASLR randomize_va_space=2

| label | workload | mean ms | median ms | min ms | ratio vs base | 95% CI | half-width |
|---|---|---|---|---|---|---|---|
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k1 | 344.7 | 343.7 | 340.5 | 0.9992 | [0.9939, 1.0039] | 0.50% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k2 | 343.8 | 343.0 | 341.2 | 1.0023 | [0.9995, 1.0053] | 0.29% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k3 | 364.9 | 365.5 | 360.8 | 1.0028 | [0.9985, 1.0069] | 0.42% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k4 | 345.8 | 345.4 | 343.5 | 1.0031 | [0.9999, 1.0064] | 0.33% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 358.4 | 358.3 | 355.5 | 0.9190 | [0.9159, 0.9219] | 0.30% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k6 | 358.3 | 357.7 | 355.9 | 1.0001 | [0.9973, 1.0031] | 0.29% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k7 | 354.7 | 353.0 | 350.0 | 0.9992 | [0.9923, 1.0061] | 0.69% |
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 350.1 | 343.1 | 339.5 | 0.9619 | [0.9469, 0.9760] | 1.46% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k1 | 344.6 | 344.3 | 340.4 | 0.9994 | [0.9923, 1.0065] | 0.71% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k2 | 343.6 | 343.7 | 340.7 | 1.0028 | [0.9998, 1.0057] | 0.30% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k3 | 363.3 | 363.5 | 359.0 | 1.0072 | [1.0007, 1.0128] | 0.60% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k4 | 346.5 | 346.6 | 343.1 | 1.0011 | [0.9968, 1.0054] | 0.43% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 328.8 | 328.1 | 326.5 | 1.0017 | [0.9983, 1.0053] | 0.35% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k6 | 358.7 | 358.2 | 355.4 | 0.9991 | [0.9960, 1.0024] | 0.32% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k7 | 353.9 | 352.1 | 349.6 | 1.0012 | [0.9935, 1.0083] | 0.74% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 340.8 | 337.6 | 333.5 | 0.9881 | [0.9743, 1.0036] | 1.46% |
| c80 | k1 | 343.6 | 342.9 | 340.1 | 1.0023 | [0.9980, 1.0070] | 0.45% |
| c80 | k2 | 343.5 | 343.9 | 339.9 | 1.0031 | [0.9993, 1.0071] | 0.39% |
| c80 | k3 | 363.5 | 362.8 | 359.5 | 1.0068 | [1.0017, 1.0119] | 0.51% |
| c80 | k4 | 346.4 | 345.3 | 343.6 | 1.0016 | [0.9990, 1.0045] | 0.27% |
| c80 | k5 | 328.4 | 327.1 | 326.0 | 1.0029 | [0.9990, 1.0071] | 0.40% |
| c80 | k6 | 358.0 | 357.6 | 355.6 | 1.0011 | [0.9979, 1.0043] | 0.32% |
| c80 | k7 | 354.4 | 354.4 | 350.0 | 0.9998 | [0.9933, 1.0067] | 0.67% |
| c80 | k8 | 344.9 | 339.2 | 334.7 | 0.9763 | [0.9588, 0.9925] | 1.68% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k1 | 344.4 | 343.9 | 340.7 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k2 | 344.6 | 345.0 | 341.4 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k3 | 366.0 | 367.5 | 360.5 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k4 | 346.9 | 347.3 | 343.7 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 329.3 | 329.3 | 327.1 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k6 | 358.4 | 358.6 | 356.4 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k7 | 354.4 | 354.4 | 350.2 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 336.7 | 333.4 | 330.3 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k1 | 344.2 | 344.4 | 340.1 | 1.0004 | [0.9958, 1.0055] | 0.49% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k2 | 343.4 | 343.3 | 340.5 | 1.0033 | [0.9994, 1.0071] | 0.39% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k3 | 364.4 | 363.8 | 359.4 | 1.0043 | [0.9978, 1.0105] | 0.64% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k4 | 347.1 | 346.5 | 343.0 | 0.9996 | [0.9947, 1.0041] | 0.47% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 359.2 | 359.2 | 354.7 | 0.9168 | [0.9133, 0.9204] | 0.36% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k6 | 357.7 | 357.1 | 356.3 | 1.0021 | [0.9997, 1.0047] | 0.25% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k7 | 354.5 | 353.6 | 349.6 | 0.9998 | [0.9940, 1.0055] | 0.57% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 352.3 | 350.6 | 338.4 | 0.9558 | [0.9373, 0.9764] | 1.96% |
| c96xxxxxxxxxx | k1 | 344.1 | 343.9 | 339.1 | 1.0008 | [0.9970, 1.0044] | 0.37% |
| c96xxxxxxxxxx | k2 | 343.9 | 343.5 | 340.8 | 1.0019 | [0.9968, 1.0069] | 0.50% |
| c96xxxxxxxxxx | k3 | 363.9 | 364.0 | 360.9 | 1.0056 | [1.0006, 1.0110] | 0.52% |
| c96xxxxxxxxxx | k4 | 346.6 | 345.9 | 343.4 | 1.0008 | [0.9962, 1.0055] | 0.46% |
| c96xxxxxxxxxx | k5 | 358.6 | 358.8 | 355.1 | 0.9182 | [0.9150, 0.9218] | 0.34% |
| c96xxxxxxxxxx | k6 | 358.1 | 357.7 | 355.5 | 1.0009 | [0.9970, 1.0047] | 0.38% |
| c96xxxxxxxxxx | k7 | 355.7 | 355.7 | 350.6 | 0.9962 | [0.9890, 1.0028] | 0.69% |
| c96xxxxxxxxxx | k8 | 347.1 | 342.8 | 336.7 | 0.9703 | [0.9501, 0.9924] | 2.11% |

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|---|---|---|
| c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | 0.9855 | [0.9829, 0.9880] | 0.26% |
| c144xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | 1.0001 | [0.9982, 1.0020] | 0.19% |
| c80 | 0.9992 | [0.9967, 1.0015] | 0.24% |
| c112xxxxxxxxxxxxxxxxxxxxxxxxx | 1.0000 | [1.0000, 1.0000] | 0.00% |
| c160xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | 0.9848 | [0.9825, 0.9872] | 0.24% |
| c96xxxxxxxxxx | 0.9864 | [0.9840, 0.9888] | 0.24% |

half-width per workload (worst over non-base labels): k1 0.71%, k2 0.50%, k3 0.64%, k4 0.47%, k5 0.40%, k6 0.38%, k7 0.74%, k8 2.11%
worst half-width 2.11% -> MDE = max(2 x half-width, 3%) = 4.23%
