pin `taskset -c 4`, warmup 3, 15 timed rounds, base `base`, bootstrap 10000 resamples seed 20260921, ASLR randomize_va_space=2

| label | workload | mean ms | median ms | min ms | ratio vs base | 95% CI | half-width |
|---|---|---|---|---|---|---|---|
| comb | objsearch | 1023.0 | 1012.7 | 999.8 | 0.9934 | [0.9791, 1.0088] | 1.49% |
| comb | strproc | 1084.0 | 1082.2 | 1073.7 | 0.9976 | [0.9917, 1.0031] | 0.57% |
| comb | readwrite | 861.1 | 852.7 | 845.9 | 1.0201 | [1.0085, 1.0321] | 1.18% |
| base | objsearch | 1016.2 | 1009.7 | 996.4 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| base | strproc | 1081.4 | 1082.4 | 1063.9 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| base | readwrite | 878.4 | 874.5 | 867.6 | 1.0000 | [1.0000, 1.0000] | 0.00% |
| aa | objsearch | 1023.8 | 1009.6 | 997.9 | 0.9926 | [0.9785, 1.0079] | 1.47% |
| aa | strproc | 1080.5 | 1081.4 | 1069.1 | 1.0008 | [0.9949, 1.0067] | 0.59% |
| aa | readwrite | 878.3 | 842.8 | 832.5 | 1.0001 | [0.9296, 1.0433] | 5.68% |
| best1f | objsearch | 1014.3 | 1002.8 | 992.9 | 1.0019 | [0.9873, 1.0176] | 1.51% |
| best1f | strproc | 1085.2 | 1069.1 | 1055.2 | 0.9964 | [0.9658, 1.0153] | 2.48% |
| best1f | readwrite | 901.3 | 869.1 | 865.1 | 0.9747 | [0.9135, 1.0117] | 4.91% |

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|---|---|---|
| comb | 1.0036 | [0.9968, 1.0107] | 0.70% |
| base | 1.0000 | [1.0000, 1.0000] | 0.00% |
| aa | 0.9979 | [0.9734, 1.0143] | 2.04% |
| best1f | 0.9909 | [0.9584, 1.0119] | 2.67% |

half-width per workload (worst over non-base labels): objsearch 1.51%, strproc 2.48%, readwrite 5.68%
worst half-width 5.68% -> MDE = max(2 x half-width, 3%) = 11.37%
