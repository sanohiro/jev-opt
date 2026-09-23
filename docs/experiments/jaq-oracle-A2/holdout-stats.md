pin `taskset -c 4`, warmup 3, 15 timed rounds, base `base`, bootstrap 10000 resamples seed 20260921, ASLR randomize_va_space=2

| label | workload | mean ms | median ms | min ms | ratio vs base | 95% CI | half-width |
|---|---|---|---|---|---|---|---|
| comb | objsearch | 999.2 | 982.5 | 973.9 | 1.0265 | [1.0115, 1.0422] | 1.54% |
| comb | strproc | 1068.5 | 1061.4 | 1047.7 | 1.0025 | [0.9935, 1.0107] | 0.86% |
| comb | readwrite | 876.1 | 850.2 | 833.9 | 0.9767 | [0.9280, 1.0068] | 3.94% |
| base | objsearch | 1025.7 | 1015.3 | 1007.9 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| base | strproc | 1071.2 | 1062.2 | 1054.0 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| base | readwrite | 855.7 | 855.1 | 843.7 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| aa | objsearch | 1025.4 | 1014.0 | 1006.6 | 1.0002 | [0.9846, 1.0173] | 1.63% |
| aa | strproc | 1080.8 | 1079.1 | 1063.2 | 0.9911 | [0.9854, 0.9968] | 0.57% |
| aa | readwrite | 855.0 | 855.0 | 845.9 | 1.0008 | [0.9964, 1.0051] | 0.43% |
| best1f | objsearch | 982.0 | 974.9 | 968.1 | 1.0445 | [1.0312, 1.0579] | 1.34% |
| best1f | strproc | 1074.8 | 1057.4 | 1046.4 | 0.9966 | [0.9633, 1.0194] | 2.80% |
| best1f | readwrite | 847.3 | 845.3 | 839.0 | 1.0099 | [1.0050, 1.0144] | 0.47% |

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|---|---|---|
| comb | 1.0017 | [0.9789, 1.0177] | 1.94% |
| base | 1.0000 | [1.0000, 1.0000] | 0.00% |
| aa | 0.9973 | [0.9920, 1.0033] | 0.56% |
| best1f | 1.0168 | [1.0038, 1.0275] | 1.18% |

half-width per workload (worst over non-base labels): objsearch 1.63%, strproc 2.80%, readwrite 3.94%
worst half-width 3.94% -> MDE = max(2 x half-width, 3%) = 7.88%
