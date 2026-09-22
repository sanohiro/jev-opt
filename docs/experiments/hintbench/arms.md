
## overview

| | |
|---|--:|
| one-factor arms | 84 |
| correctness held | 84 of 84 |
| builds identical to the baseline (not timed) | **39** |
| builds that only moved code (layout) | 4 |
| builds that changed instructions | 41 |
| arms whose first batch excluded 1 (confirmation run) | 38 |
| confirmed on the kernel readout | **33** |
| confirmed on the aggregate | 27 |
| in-run A/A intervals excluding 1, first batch (aggregate) | 5 of 45 |
| in-run A/A intervals excluding 1, first batch (own kernel) | 12 of 45 |
| in-run A/A intervals excluding 1, confirmation batch | 5 of 38 |
| wall clock of the rounds | 3.8 h |

## arms

### K1

| arm | site | candidate | build vs baseline | changed syms | k1 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 1 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 2 | fn | `inline_never` | code | 2 | 0.9545 | [0.9519, 0.9571] | **yes (-)** | 0.9951 | [0.9929, 0.9974] |
| 3 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 4 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 5 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

### K2

| arm | site | candidate | build vs baseline | changed syms | k2 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 6 | fn | `inline_always` | code | 2 | 1.6775 | [1.6682, 1.6864] | **yes (+)** | 1.0629 | [1.0564, 1.0689] |
| 7 | fn | `inline_never` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 8 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 9 | fn | `align_32` | layout | 0 | 1.0071 | [0.9985, 1.0211] | not triggered | 1.0019 | [0.9987, 1.0052] |
| 10 | fn | `align_64` | layout | 0 | 0.9974 | [0.9940, 1.0016] | not triggered | 1.0007 | [0.9979, 1.0035] |

### K3

| arm | site | candidate | build vs baseline | changed syms | k3 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 11 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 12 | fn | `inline_never` | code | 2 | 0.8294 | [0.8276, 0.8313] | **yes (-)** | 0.9781 | [0.9760, 0.9802] |
| 13 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 14 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 15 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 74 | loop | `unroll_count_2` | code | 1 | 1.0423 | [1.0397, 1.0448] | **yes (+)** | 1.0060 | [1.0028, 1.0089] |
| 75 | loop | `unroll_count_4` | code | 1 | 1.0436 | [1.0412, 1.0461] | **yes (+)** | 1.0060 | [1.0030, 1.0092] |
| 76 | loop | `unroll_count_8` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 77 | loop | `unroll_disable` | code | 1 | 0.7056 | [0.7021, 0.7088] | **yes (-)** | 0.9567 | [0.9540, 0.9600] |
| 78 | loop | `vectorize_width_2` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 79 | loop | `vectorize_width_4` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 80 | loop | `vectorize_width_8` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 81 | loop | `vectorize_width_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 82 | loop | `interleave_count_1` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 83 | loop | `interleave_count_2` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 84 | loop | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

### K4

| arm | site | candidate | build vs baseline | changed syms | k4 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 16 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 17 | fn | `inline_never` | code | 2 | 1.0152 | [1.0110, 1.0193] | **yes (+)** | 0.9957 | [0.9938, 0.9980] |
| 18 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 19 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 20 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 52 | loop | `unroll_count_2` | code | 1 | 0.9848 | [0.9823, 0.9874] | **yes (-)** | 0.9993 | [0.9963, 1.0022] |
| 53 | loop | `unroll_count_4` | code | 1 | 1.0053 | [1.0025, 1.0082] | **yes (+)** | 1.0015 | [0.9988, 1.0040] |
| 54 | loop | `unroll_count_8` | code | 1 | 1.0048 | [0.9825, 1.0417] | not triggered | 0.9999 | [0.9925, 1.0087] |
| 55 | loop | `unroll_disable` | code | 1 | 0.7309 | [0.7297, 0.7327] | **yes (-)** | 0.9596 | [0.9575, 0.9618] |
| 56 | loop | `vectorize_width_2` | code | 1 | 0.2024 | [0.2020, 0.2027] | **yes (-)** | 0.8194 | [0.8174, 0.8215] |
| 57 | loop | `vectorize_width_4` | code | 1 | 0.6744 | [0.6732, 0.6754] | **yes (-)** | 0.9517 | [0.9499, 0.9535] |
| 58 | loop | `vectorize_width_8` | code | 1 | 0.9996 | [0.9967, 1.0024] | not triggered | 0.9983 | [0.9947, 1.0018] |
| 59 | loop | `vectorize_width_16` | code | 1 | 0.5793 | [0.5777, 0.5813] | **yes (-)** | 0.9361 | [0.9344, 0.9379] |
| 60 | loop | `interleave_count_1` | code | 1 | 0.7301 | [0.7266, 0.7349] | **yes (-)** | 0.9605 | [0.9583, 0.9630] |
| 61 | loop | `interleave_count_2` | code | 1 | 0.9396 | [0.9377, 0.9417] | **yes (-)** | 0.9883 | [0.9823, 0.9926] |
| 62 | loop | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

### K5

| arm | site | candidate | build vs baseline | changed syms | k5 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 21 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 22 | fn | `inline_never` | code | 2 | 0.9916 | [0.9873, 0.9958] | **yes (-)** | 0.9951 | [0.9919, 0.9984] |
| 23 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 24 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 25 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 41 | loop | `unroll_count_2` | code | 1 | 0.9872 | [0.9705, 0.9983] | **yes (-)** | 0.9986 | [0.9966, 1.0006] |
| 42 | loop | `unroll_count_4` | code | 1 | 1.0207 | [1.0150, 1.0278] | **yes (+)** | 1.0043 | [1.0023, 1.0063] |
| 43 | loop | `unroll_count_8` | code | 1 | 1.0194 | [1.0154, 1.0250] | **yes (+)** | 1.0017 | [0.9994, 1.0040] |
| 44 | loop | `unroll_disable` | code | 1 | 0.2941 | [0.2935, 0.2947] | **yes (-)** | 0.8571 | [0.8523, 0.8616] |
| 45 | loop | `vectorize_width_2` | code | 1 | 0.2791 | [0.2787, 0.2794] | **yes (-)** | 0.8525 | [0.8505, 0.8545] |
| 46 | loop | `vectorize_width_4` | code | 1 | 0.5568 | [0.5559, 0.5577] | **yes (-)** | 0.9301 | [0.9273, 0.9329] |
| 47 | loop | `vectorize_width_8` | code | 1 | 0.9950 | [0.9929, 0.9970] | **yes (-)** | 0.9985 | [0.9967, 1.0003] |
| 48 | loop | `vectorize_width_16` | code | 1 | 1.0265 | [1.0235, 1.0294] | **yes (+)** | 1.0048 | [1.0031, 1.0065] |
| 49 | loop | `interleave_count_1` | code | 1 | 0.2957 | [0.2943, 0.2978] | **yes (-)** | 0.8591 | [0.8566, 0.8619] |
| 50 | loop | `interleave_count_2` | code | 1 | 0.5953 | [0.5941, 0.5965] | **yes (-)** | 0.9392 | [0.9372, 0.9413] |
| 51 | loop | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

### K6

| arm | site | candidate | build vs baseline | changed syms | k6 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 26 | fn | `inline_always` | code | 2 | 1.0011 | [0.9981, 1.0039] | no | 0.9949 | [0.9916, 0.9979] |
| 27 | fn | `inline_never` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 28 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 29 | fn | `align_32` | layout | 0 | 0.9985 | [0.9954, 1.0013] | not triggered | 0.9977 | [0.9949, 1.0004] |
| 30 | fn | `align_64` | layout | 0 | 1.0008 | [0.9981, 1.0039] | not triggered | 1.0011 | [0.9980, 1.0041] |

### K7

| arm | site | candidate | build vs baseline | changed syms | k7 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 31 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 32 | fn | `inline_never` | code | 2 | 0.9999 | [0.9981, 1.0017] | no | 1.0019 | [1.0000, 1.0037] |
| 33 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 34 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 35 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

### K8

| arm | site | candidate | build vs baseline | changed syms | k8 ratio | 95% CI | confirmed | aggregate | aggregate CI |
|---:|---|---|---|--:|--:|---|---|--:|---|
| 36 | fn | `inline_always` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 37 | fn | `inline_never` | code | 2 | 0.9914 | [0.9745, 1.0072] | no | 0.9943 | [0.9923, 0.9962] |
| 38 | fn | `align_16` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 39 | fn | `align_32` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 40 | fn | `align_64` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |
| 63 | loop | `unroll_count_2` | code | 1 | 1.0164 | [1.0029, 1.0304] | **yes (+)** | 1.0008 | [0.9987, 1.0030] |
| 64 | loop | `unroll_count_4` | code | 1 | 0.9778 | [0.9514, 1.0007] | no | 0.9965 | [0.9935, 0.9990] |
| 65 | loop | `unroll_count_8` | code | 1 | 1.0201 | [1.0025, 1.0403] | no | 1.0031 | [1.0008, 1.0056] |
| 66 | loop | `unroll_disable` | code | 1 | 0.8226 | [0.7819, 0.8626] | **yes (-)** | 0.9753 | [0.9691, 0.9812] |
| 67 | loop | `vectorize_width_2` | code | 1 | 0.4467 | [0.4255, 0.4680] | **yes (-)** | 0.9034 | [0.8978, 0.9087] |
| 68 | loop | `vectorize_width_4` | code | 1 | 0.9171 | [0.8895, 0.9437] | **yes (-)** | 0.9891 | [0.9853, 0.9929] |
| 69 | loop | `vectorize_width_8` | code | 1 | 1.0005 | [0.9803, 1.0193] | not triggered | 0.9991 | [0.9968, 1.0015] |
| 70 | loop | `vectorize_width_16` | code | 1 | 1.0881 | [1.0709, 1.1069] | **yes (+)** | 1.0100 | [1.0072, 1.0133] |
| 71 | loop | `interleave_count_1` | code | 1 | 0.8033 | [0.7600, 0.8464] | **yes (-)** | 0.9726 | [0.9655, 0.9795] |
| 72 | loop | `interleave_count_2` | code | 1 | 0.9456 | [0.9081, 0.9840] | **yes (-)** | 0.9933 | [0.9885, 0.9980] |
| 73 | loop | `interleave_count_4` | **identical** | 0 | 1.0000* | by construction | n/a | 1.0000 | - |

## scorecard

| kernel | Claude's expected winner | expected effect | confidence | measured best (confirmed) | measured ratio | score | worst arm |
|---|---|---|---|---|--:|---|---|
| K1 | `inline_never` | +2% to +10% | low | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9545 |
| K2 | `inline_always` | +2% to +10% | medium | `inline_always` | 1.6775 | **hit** | `align_64` 0.9974 |
| K3 | `unroll_disable` | +2% to +10% | medium | `unroll_count_4` | 1.0436 | same-family | `unroll_disable` 0.7056 |
| K4 | `KEEP_DEFAULT` | width 16: 0% to -25% | medium | `inline_never` | 1.0152 | miss | `vectorize_width_2` 0.2024 |
| K5 | `KEEP_DEFAULT` | IC 1: -50% to -75% | high | `vectorize_width_16` | 1.0265 | miss | `vectorize_width_2` 0.2791 |
| K6 | `align_64` | +-0% to +-3%, sign unknown | low | `KEEP_DEFAULT` | -- | miss | `align_32` 0.9985 |
| K7 | `inline_never` | 0% to +5% | medium | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9999 |
| K8 | `KEEP_DEFAULT` | every hint <= 0% | high | `vectorize_width_16` | 1.0881 | miss | `vectorize_width_2` 0.4467 |

**1 hit, 1 same-family, 6 miss of 8.**

With the post-hoc MDE gate (oracle.md 2, dated note): the same rule, plus the confirmed effect having cleared its batch's MDE.

| kernel | Claude's expected winner | expected effect | confidence | measured best (confirmed) | measured ratio | score | worst arm |
|---|---|---|---|---|--:|---|---|
| K1 | `inline_never` | +2% to +10% | low | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9545 |
| K2 | `inline_always` | +2% to +10% | medium | `inline_always` | 1.6775 | **hit** | `align_64` 0.9974 |
| K3 | `unroll_disable` | +2% to +10% | medium | `unroll_count_4` | 1.0436 | same-family | `unroll_disable` 0.7056 |
| K4 | `KEEP_DEFAULT` | width 16: 0% to -25% | medium | `KEEP_DEFAULT` | -- | **hit** | `vectorize_width_2` 0.2024 |
| K5 | `KEEP_DEFAULT` | IC 1: -50% to -75% | high | `KEEP_DEFAULT` | -- | **hit** | `vectorize_width_2` 0.2791 |
| K6 | `align_64` | +-0% to +-3%, sign unknown | low | `KEEP_DEFAULT` | -- | miss | `align_32` 0.9985 |
| K7 | `inline_never` | 0% to +5% | medium | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9999 |
| K8 | `KEEP_DEFAULT` | every hint <= 0% | high | `vectorize_width_16` | 1.0881 | miss | `vectorize_width_2` 0.4467 |

**3 hit, 1 same-family, 4 miss of 8.**

## vocabulary

| candidate | arms | identical builds | best kernel ratio | worst kernel ratio | confirmed effects | cleared the MDE |
|---|--:|--:|--:|--:|---|---|
| `align_16` | 8 | 8 | - | - | none | **never** |
| `align_32` | 8 | 6 | 1.0071 (k2) | 0.9985 (k6) | none | **never** |
| `align_64` | 8 | 6 | 1.0008 (k6) | 0.9974 (k2) | none | **never** |
| `inline_always` | 8 | 6 | 1.6775 (k2) | 1.0011 (k6) | k2 1.6775 | k2 1.6775 (MDE 7.0%) |
| `inline_never` | 8 | 2 | 1.0152 (k4) | 0.8294 (k3) | k1 0.9545, k3 0.8294, k4 1.0152, k5 0.9916 | k1 0.9545 (MDE 3.0%), k3 0.8294 (MDE 3.4%) |
| `interleave_count_1` | 4 | 1 | 0.8033 (k8) | 0.2957 (k5) | k5 0.2957, k4 0.7301, k8 0.8033 | k5 0.2957 (MDE 4.4%), k4 0.7301 (MDE 3.9%), k8 0.8033 (MDE 8.6%) |
| `interleave_count_2` | 4 | 1 | 0.9456 (k8) | 0.5953 (k5) | k5 0.5953, k4 0.9396, k8 0.9456 | k5 0.5953 (MDE 4.0%) |
| `interleave_count_4` | 4 | 4 | - | - | none | **never** |
| `unroll_count_2` | 4 | 0 | 1.0423 (k3) | 0.9848 (k4) | k5 0.9872, k4 0.9848, k8 1.0164, k3 1.0423 | **never** |
| `unroll_count_4` | 4 | 0 | 1.0436 (k3) | 0.9778 (k8) | k5 1.0207, k4 1.0053, k3 1.0436 | k3 1.0436 (MDE 3.5%) |
| `unroll_count_8` | 4 | 1 | 1.0201 (k8) | 1.0048 (k4) | k5 1.0194 | **never** |
| `unroll_disable` | 4 | 0 | 0.8226 (k8) | 0.2941 (k5) | k5 0.2941, k4 0.7309, k8 0.8226, k3 0.7056 | k5 0.2941 (MDE 6.5%), k4 0.7309 (MDE 3.0%), k8 0.8226 (MDE 8.1%), k3 0.7056 (MDE 3.3%) |
| `vectorize_width_16` | 4 | 1 | 1.0881 (k8) | 0.5793 (k4) | k5 1.0265, k4 0.5793, k8 1.0881 | k4 0.5793 (MDE 4.2%), k8 1.0881 (MDE 3.8%) |
| `vectorize_width_2` | 4 | 1 | 0.4467 (k8) | 0.2024 (k4) | k5 0.2791, k4 0.2024, k8 0.4467 | k5 0.2791 (MDE 3.4%), k4 0.2024 (MDE 3.7%), k8 0.4467 (MDE 4.3%) |
| `vectorize_width_4` | 4 | 1 | 0.9171 (k8) | 0.5568 (k5) | k5 0.5568, k4 0.6744, k8 0.9171 | k5 0.5568 (MDE 4.3%), k4 0.6744 (MDE 4.5%), k8 0.9171 (MDE 5.4%) |
| `vectorize_width_8` | 4 | 1 | 1.0005 (k8) | 0.9950 (k5) | k5 0.9950 | **never** |

## combination

Selection rule: **confirmed in two batches, ratio > 1**.

| rule | sites it would combine |
|---|---|
| confirmed in two batches (used) | `hbkernels::k2_mix` inline_always, `hbkernels::k4_count_bytes` inline_never, `hbkernels::k3_fill_run@lib.rs:174:9#d3` unroll_count_4, `hbkernels::k4_count_bytes@macros.rs:180:28#d2` unroll_count_4, `hbkernels::k5_mul_reduce@macros.rs:180:28#d2` vectorize_width_16, `hbkernels::k8_scale_add@range.rs:1103:12#d2` vectorize_width_16 |
| one batch, CI lower > 1 | `hbkernels::k2_mix` inline_always, `hbkernels::k4_count_bytes` inline_never, `hbkernels::k3_fill_run@lib.rs:174:9#d3` unroll_count_4, `hbkernels::k4_count_bytes@macros.rs:180:28#d2` unroll_count_4, `hbkernels::k5_mul_reduce@macros.rs:180:28#d2` vectorize_width_16, `hbkernels::k8_scale_add@range.rs:1103:12#d2` vectorize_width_16 |
| point estimate > 1 | `hbkernels::k2_mix` inline_always, `hbkernels::k4_count_bytes` inline_never, `hbkernels::k6_hot_loop` inline_always, `hbkernels::k3_fill_run@lib.rs:174:9#d3` unroll_count_4, `hbkernels::k4_count_bytes@macros.rs:180:28#d2` unroll_count_4, `hbkernels::k5_mul_reduce@macros.rs:180:28#d2` vectorize_width_16, `hbkernels::k8_scale_add@range.rs:1103:12#d2` vectorize_width_16 |

Measured: ratio 1.0881 [1.0861, 1.0901], code class `code`, correctness OK, confirmed **yes (+)**.
