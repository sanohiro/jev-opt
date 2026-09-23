pin `taskset -c 8`, warmup 3, 15 timed rounds, base `L091xxxxxxxxxxxxxxxxxxxxxxx`, bootstrap 10000 resamples seed 20260922, ASLR randomize_va_space=2

| label | workload | mean ms | median ms | min ms | ratio vs base | 95% CI | half-width |
|---|---|---|---|---|---|---|---|
| L088xxxxxxxxxxxxxxxxxxxx | k5 | 361.0 | 359.6 | 355.7 | 0.9136 | [0.9043, 0.9213] | 0.85% |
| L088xxxxxxxxxxxxxxxxxxxx | k8 | 344.5 | 342.5 | 338.8 | 0.9822 | [0.9729, 0.9924] | 0.97% |
| Q089xxxxxxxxxxxxxxxxxxxxx | k5 | 331.6 | 331.4 | 326.6 | 0.9946 | [0.9894, 1.0001] | 0.53% |
| Q089xxxxxxxxxxxxxxxxxxxxx | k8 | 337.7 | 333.8 | 330.3 | 1.0018 | [0.9811, 1.0186] | 1.87% |
| L087xxxxxxxxxxxxxxxxxxx | k5 | 361.1 | 359.7 | 356.2 | 0.9134 | [0.9049, 0.9205] | 0.78% |
| L087xxxxxxxxxxxxxxxxxxx | k8 | 345.5 | 341.8 | 334.1 | 0.9793 | [0.9630, 0.9947] | 1.58% |
| L089xxxxxxxxxxxxxxxxxxxxx | k5 | 331.6 | 332.6 | 326.9 | 0.9946 | [0.9893, 1.0002] | 0.55% |
| L089xxxxxxxxxxxxxxxxxxxxx | k8 | 337.7 | 334.6 | 330.6 | 1.0017 | [0.9885, 1.0143] | 1.29% |
| H088xxxxxxxxxxxxxxxxxxxx | k5 | 361.9 | 360.3 | 356.1 | 0.9112 | [0.9021, 0.9191] | 0.85% |
| H088xxxxxxxxxxxxxxxxxxxx | k8 | 349.1 | 344.1 | 338.1 | 0.9691 | [0.9537, 0.9842] | 1.53% |
| L090xxxxxxxxxxxxxxxxxxxxxx | k5 | 330.9 | 329.7 | 326.5 | 0.9967 | [0.9910, 1.0025] | 0.58% |
| L090xxxxxxxxxxxxxxxxxxxxxx | k8 | 339.6 | 334.5 | 330.2 | 0.9961 | [0.9803, 1.0129] | 1.63% |
| L094xxxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 331.9 | 330.5 | 325.8 | 0.9935 | [0.9820, 1.0022] | 1.01% |
| L094xxxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 338.4 | 334.2 | 330.6 | 0.9997 | [0.9824, 1.0163] | 1.70% |
| L091xxxxxxxxxxxxxxxxxxxxxxx | k5 | 329.8 | 329.0 | 325.6 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| L091xxxxxxxxxxxxxxxxxxxxxxx | k8 | 338.3 | 334.6 | 330.4 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| L085xxxxxxxxxxxxxxxxx | k5 | 360.3 | 360.9 | 354.9 | 0.9152 | [0.9105, 0.9203] | 0.49% |
| L085xxxxxxxxxxxxxxxxx | k8 | 348.7 | 342.4 | 338.1 | 0.9702 | [0.9531, 0.9869] | 1.69% |
| H089xxxxxxxxxxxxxxxxxxxxx | k5 | 329.8 | 329.4 | 326.0 | 1.0000 | [0.9936, 1.0064] | 0.64% |
| H089xxxxxxxxxxxxxxxxxxxxx | k8 | 339.3 | 336.4 | 331.0 | 0.9970 | [0.9820, 1.0120] | 1.50% |
| L093xxxxxxxxxxxxxxxxxxxxxxxxx | k5 | 332.1 | 331.8 | 326.5 | 0.9930 | [0.9874, 0.9990] | 0.58% |
| L093xxxxxxxxxxxxxxxxxxxxxxxxx | k8 | 338.6 | 334.3 | 330.4 | 0.9993 | [0.9892, 1.0096] | 1.02% |
| L086xxxxxxxxxxxxxxxxxx | k5 | 361.0 | 360.7 | 356.1 | 0.9135 | [0.9057, 0.9206] | 0.75% |
| L086xxxxxxxxxxxxxxxxxx | k8 | 344.2 | 342.1 | 339.3 | 0.9831 | [0.9707, 0.9957] | 1.25% |
| L092xxxxxxxxxxxxxxxxxxxxxxxx | k5 | 331.4 | 330.1 | 326.5 | 0.9951 | [0.9874, 1.0012] | 0.69% |
| L092xxxxxxxxxxxxxxxxxxxxxxxx | k8 | 340.6 | 334.8 | 330.4 | 0.9934 | [0.9705, 1.0140] | 2.17% |

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|---|---|---|
| L088xxxxxxxxxxxxxxxxxxxx | 0.9473 | [0.9397, 0.9551] | 0.77% |
| Q089xxxxxxxxxxxxxxxxxxxxx | 0.9982 | [0.9870, 1.0075] | 1.03% |
| L087xxxxxxxxxxxxxxxxxxx | 0.9458 | [0.9370, 0.9547] | 0.88% |
| L089xxxxxxxxxxxxxxxxxxxxx | 0.9982 | [0.9907, 1.0055] | 0.74% |
| H088xxxxxxxxxxxxxxxxxxxx | 0.9397 | [0.9296, 0.9489] | 0.97% |
| L090xxxxxxxxxxxxxxxxxxxxxx | 0.9964 | [0.9873, 1.0058] | 0.93% |
| L094xxxxxxxxxxxxxxxxxxxxxxxxxx | 0.9966 | [0.9838, 1.0076] | 1.19% |
| L091xxxxxxxxxxxxxxxxxxxxxxx | 1.0000 | [1.0000, 1.0000] | 0.00% |
| L085xxxxxxxxxxxxxxxxx | 0.9423 | [0.9326, 0.9522] | 0.98% |
| H089xxxxxxxxxxxxxxxxxxxxx | 0.9985 | [0.9911, 1.0064] | 0.76% |
| L093xxxxxxxxxxxxxxxxxxxxxxxxx | 0.9961 | [0.9909, 1.0012] | 0.52% |
| L086xxxxxxxxxxxxxxxxxx | 0.9476 | [0.9391, 0.9553] | 0.81% |
| L092xxxxxxxxxxxxxxxxxxxxxxxx | 0.9942 | [0.9792, 1.0068] | 1.38% |

half-width per workload (worst over non-base labels): k5 1.01%, k8 2.17%
worst half-width 2.17% -> MDE = max(2 x half-width, 3%) = 4.34%
