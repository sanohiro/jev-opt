| arm | mark | candidate | plan entries | apply | correct | build vs baseline | ratio | 95% CI | excl 1 | confirm | confirmed | changed syms | profile share |
|---:|---|---|--:|---|---|---|--:|---|---|--:|---|--:|--:|
| 1 | read::parse | inline_always | 6 | consumed x6 | yes | code | 0.9741 | [0.9513, 0.9956] | yes (-) | 0.9739 | yes (-1) | 29 | 21.54% |
| 2 | read::parse | inline_never | 6 | consumed x6 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 3 | read::parse | align_16 | 6 | consumed x6 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 4 | read::parse | align_32 | 6 | consumed x6 | yes | layout | 1.0122 | [1.0028, 1.0221] | yes (+) | 1.0031 | no | 0 | 0.00% |
| 5 | read::parse | align_64 | 6 | consumed x6 | yes | layout | 0.9856 | [0.9785, 0.9918] | yes (-) | 0.9849 | yes (-1) | 0 | 0.00% |
| 6 | Lex::seq | inline_always | 8 | consumed x8 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 7 | Lex::seq | inline_never | 8 | consumed x8 | yes | code | 0.9061 | [0.8988, 0.9133] | yes (-) | 0.9426 | yes (-1) | 16 | 28.77% |
| 8 | Lex::seq | align_16 | 8 | consumed x8 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 9 | Lex::seq | align_32 | 8 | consumed x8 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 10 | Lex::seq | align_64 | 8 | consumed x8 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 11 | str_fold | inline_always | 5 | consumed x5 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 12 | str_fold | inline_never | 5 | consumed x5 | yes | code | 0.9861 | [0.9792, 0.9927] | yes (-) | 0.9928 | yes (-1) | 244 | 14.86% |
| 13 | str_fold | align_16 | 5 | consumed x5 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 14 | str_fold | align_32 | 5 | consumed x5 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 15 | str_fold | align_64 | 5 | consumed x5 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 16 | write_until | inline_always | 6 | consumed x6 | yes | code | 1.0153 | [1.0042, 1.0265] | yes (+) | 1.0215 | yes (+1) | 5 | 12.00% |
| 17 | write_until | inline_never | 6 | consumed x6 | yes | code | 0.9625 | [0.9564, 0.9697] | yes (-) | 0.9678 | yes (-1) | 5 | 37.71% |
| 18 | write_until | align_16 | 6 | consumed x6 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 19 | write_until | align_32 | 6 | consumed x6 | yes | layout | 0.9919 | [0.9866, 0.9971] | yes (-) | 1.0115 | no | 0 | 0.00% |
| 20 | write_until | align_64 | 6 | consumed x6 | yes | layout | 1.0102 | [1.0041, 1.0169] | yes (+) | 1.0131 | yes (+1) | 0 | 0.00% |
| 21 | TermId::run | inline_always | 2 | consumed x2 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 22 | TermId::run | inline_never | 2 | consumed x2 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 23 | TermId::run | align_16 | 2 | consumed x2 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 24 | TermId::run | align_32 | 2 | consumed x2 | yes | code | 1.0084 | [1.0000, 1.0164] | no | - | no | 1 | 1.93% |
| 25 | TermId::run | align_64 | 2 | consumed x2 | yes | code | 0.9936 | [0.9845, 1.0025] | no | - | no | 1 | 1.93% |
| 26 | write::write | inline_always | 1 | consumed x1 | yes | code | 0.9445 | [0.9397, 0.9494] | yes (-) | 0.9337 | yes (-1) | 10 | 1.81% |
| 27 | write::write | inline_never | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 28 | write::write | align_16 | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 29 | write::write | align_32 | 1 | consumed x1 | yes | layout | 1.0050 | [0.9991, 1.0111] | no | - | no | 0 | 0.00% |
| 30 | write::write | align_64 | 1 | consumed x1 | yes | layout | 0.9941 | [0.9856, 1.0024] | no | - | no | 0 | 0.00% |
| 31 | funs::base{closure#3} | inline_always | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 32 | funs::base{closure#3} | inline_never | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 33 | funs::base{closure#3} | align_16 | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 34 | funs::base{closure#3} | align_32 | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 35 | funs::base{closure#3} | align_64 | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 36 | Path::run{closure#0} | inline_always | 2 | consumed x2 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 37 | Path::run{closure#0} | inline_never | 2 | consumed x2 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 38 | Path::run{closure#0} | align_16 | 2 | consumed x2 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 39 | Path::run{closure#0} | align_32 | 2 | consumed x2 | yes | layout | 0.9884 | [0.9822, 0.9947] | yes (-) | 1.0030 | no | 0 | 0.00% |
| 40 | Path::run{closure#0} | align_64 | 2 | consumed x2 | yes | code | 1.0089 | [0.9919, 1.0217] | no | - | no | 1 | 0.05% |
| 41 | Adapter::write_str | inline_always | 1 | consumed x1 | yes | code | 0.9914 | [0.9853, 0.9980] | yes (-) | 0.9942 | no | 1 | 0.00% |
| 42 | Adapter::write_str | inline_never | 1 | consumed x1 | yes | code | 1.0032 | [0.9967, 1.0095] | no | - | no | 3 | 7.44% |
| 43 | Adapter::write_str | align_16 | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 44 | Adapter::write_str | align_32 | 1 | consumed x1 | yes | layout | 1.0059 | [0.9976, 1.0148] | no | - | no | 0 | 0.00% |
| 45 | Adapter::write_str | align_64 | 1 | consumed x1 | yes | layout | 0.9987 | [0.9916, 1.0063] | no | - | no | 0 | 0.00% |
| 46 | reserve_rehash | inline_always | 1 | consumed x1 | yes | code | 1.0104 | [1.0047, 1.0162] | yes (+) | 1.0096 | yes (+1) | 17 | 11.73% |
| 47 | reserve_rehash | inline_never | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 48 | reserve_rehash | align_16 | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 49 | reserve_rehash | align_32 | 1 | consumed x1 | yes | layout | 0.9970 | [0.9732, 1.0136] | no | - | no | 0 | 0.00% |
| 50 | reserve_rehash | align_64 | 1 | consumed x1 | yes | layout | 0.9921 | [0.9854, 0.9991] | yes (-) | 1.0001 | no | 0 | 0.00% |
| 51 | Rc<IndexMap>::drop_slow | inline_always | 1 | consumed x1 | yes | code | 0.9525 | [0.9475, 0.9572] | yes (-) | 0.9848 | yes (-1) | 45 | 14.46% |
| 52 | Rc<IndexMap>::drop_slow | inline_never | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 53 | Rc<IndexMap>::drop_slow | align_16 | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 54 | Rc<IndexMap>::drop_slow | align_32 | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 55 | Rc<IndexMap>::drop_slow | align_64 | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 56 | base_run{closure#7} | inline_always | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 57 | base_run{closure#7} | inline_never | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 58 | base_run{closure#7} | align_16 | 1 | consumed x1 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 59 | base_run{closure#7} | align_32 | 1 | consumed x1 | yes | layout | 0.9744 | [0.9668, 0.9830] | yes (-) | 0.9998 | no | 0 | 0.00% |
| 60 | base_run{closure#7} | align_64 | 1 | consumed x1 | yes | layout | 0.9911 | [0.9863, 0.9962] | yes (-) | 0.9937 | no | 0 | 0.00% |
| 61 | path::run | inline_always | 3 | consumed x3 | yes | code | 1.0116 | [1.0029, 1.0197] | yes (+) | 1.0060 | no | 20 | 2.86% |
| 62 | path::run | inline_never | 3 | consumed x3 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 63 | path::run | align_16 | 3 | consumed x3 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 64 | path::run | align_32 | 3 | consumed x3 | yes | layout | 1.0041 | [0.9973, 1.0105] | no | - | no | 0 | 0.00% |
| 65 | path::run | align_64 | 3 | consumed x3 | yes | layout | 0.9860 | [0.9804, 0.9915] | yes (-) | 0.9978 | no | 0 | 0.00% |
| 66 | Val::hash | inline_always | 4 | consumed x4 | yes | code | 1.0426 | [1.0343, 1.0505] | yes (+) | 1.0484 | yes (+1) | 250 | 12.47% |
| 67 | Val::hash | inline_never | 4 | consumed x4 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 68 | Val::hash | align_16 | 4 | consumed x4 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 69 | Val::hash | align_32 | 4 | consumed x4 | yes | layout | 1.0054 | [0.9995, 1.0116] | no | - | no | 0 | 0.00% |
| 70 | Val::hash | align_64 | 4 | consumed x4 | yes | layout | 1.0118 | [1.0028, 1.0216] | yes (+) | 1.0069 | yes (+1) | 0 | 0.00% |
| 71 | String::fmt | inline_always | 7 | consumed x7 | yes | code | 0.9957 | [0.9883, 1.0031] | no | - | no | 4 | 0.43% |
| 72 | String::fmt | inline_never | 7 | consumed x7 | yes | code | 0.9865 | [0.9802, 0.9933] | yes (-) | 0.9918 | yes (-1) | 4 | 0.43% |
| 73 | String::fmt | align_16 | 7 | consumed x7 | yes | identical | 1.0000 | not timed | - | - | - | 0 | 0.00% |
| 74 | String::fmt | align_32 | 7 | consumed x7 | yes | code | 0.9988 | [0.9802, 1.0160] | no | - | no | 1 | 0.00% |
| 75 | String::fmt | align_64 | 7 | consumed x7 | yes | code | 0.9475 | [0.9188, 0.9812] | yes (-) | 1.0623 | no | 1 | 0.00% |
| 76 | (combination) | - | 11 | consumed x11 | yes | code | 1.0291 | [0.9676, 1.0952] | no | - | no | 263 | 17.22% |

## What the builds were

| what the build differs in | arms | ratio range |
|---|--:|---|
| nothing: same instructions, same symbol table (not timed) | 39 | 1.0000 -- 1.0000 |
| only where the code sits | 17 | 0.9744 -- 1.0122 |
| instructions changed | 19 | 0.9061 -- 1.0426 |

75 one-factor arms: 39 identical to the baseline and not timed, 36 measured.

## By candidate

| candidate | arms | identical | layout | code | measured mean | min | max | confirmed |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| align_16 | 15 | 15 | 0 | 0 | -- | -- | -- | 0 |
| align_32 | 15 | 4 | 9 | 2 | 0.9992 | 0.9744 | 1.0122 | 0 |
| align_64 | 15 | 4 | 8 | 3 | 0.9927 | 0.9475 | 1.0118 | 3 |
| inline_always | 15 | 6 | 0 | 9 | 0.9931 | 0.9445 | 1.0426 | 6 |
| inline_never | 15 | 10 | 0 | 5 | 0.9689 | 0.9061 | 1.0032 | 4 |

## Per mark: the best of its five candidates

| mark | plan entries | best candidate | ratio | 95% CI | excl 1 | confirmed | worst candidate | ratio |
|---|--:|---|--:|---|---|---|---|--:|
| read::parse | 6 | align_32 | 1.0122 | [1.0028, 1.0221] | yes (+) | no | inline_always | 0.9741 |
| Lex::seq | 8 | inline_always | 1.0000 | not timed | - | no | inline_never | 0.9061 |
| str_fold | 5 | inline_always | 1.0000 | not timed | - | no | inline_never | 0.9861 |
| write_until | 6 | inline_always | 1.0153 | [1.0042, 1.0265] | yes (+) | yes | inline_never | 0.9625 |
| TermId::run | 2 | align_32 | 1.0084 | [1.0000, 1.0164] | no | no | align_64 | 0.9936 |
| write::write | 1 | align_32 | 1.0050 | [0.9991, 1.0111] | no | no | inline_always | 0.9445 |
| funs::base{closure#3} | 1 | inline_always | 1.0000 | not timed | - | no | align_64 | 1.0000 |
| Path::run{closure#0} | 2 | align_64 | 1.0089 | [0.9919, 1.0217] | no | no | align_32 | 0.9884 |
| Adapter::write_str | 1 | align_32 | 1.0059 | [0.9976, 1.0148] | no | no | inline_always | 0.9914 |
| reserve_rehash | 1 | inline_always | 1.0104 | [1.0047, 1.0162] | yes (+) | yes | align_64 | 0.9921 |
| Rc<IndexMap>::drop_slow | 1 | inline_never | 1.0000 | not timed | - | no | inline_always | 0.9525 |
| base_run{closure#7} | 1 | inline_always | 1.0000 | not timed | - | no | align_32 | 0.9744 |
| path::run | 3 | inline_always | 1.0116 | [1.0029, 1.0197] | yes (+) | no | align_64 | 0.9860 |
| Val::hash | 4 | inline_always | 1.0426 | [1.0343, 1.0505] | yes (+) | yes | align_16 | 1.0000 |
| String::fmt | 7 | align_16 | 1.0000 | not timed | - | no | align_64 | 0.9475 |

## The MDE gate and the confirmation

MDE 3%. Arms above it: 1. Below it: 5. Arms whose interval excluded 1 in **both** batches with the same sign: 13.

| arm | mark | candidate | ratio | 95% CI | confirm | confirm 95% CI | confirmed | in-run A/A |
|---:|---|---|--:|---|--:|---|---|--:|
| 66 | Val::hash | inline_always | 1.0426 | [1.0343, 1.0505] | 1.0484 | [1.0420, 1.0546] | yes | 1.0032 |
| 17 | write_until | inline_never | 0.9625 | [0.9564, 0.9697] | 0.9678 | [0.9625, 0.9733] | yes | 0.9854 |
| 51 | Rc<IndexMap>::drop_slow | inline_always | 0.9525 | [0.9475, 0.9572] | 0.9848 | [0.9773, 0.9922] | yes | 0.9781 |
| 75 | String::fmt | align_64 | 0.9475 | [0.9188, 0.9812] | 1.0623 | [1.0114, 1.1188] | no | 1.0317 |
| 26 | write::write | inline_always | 0.9445 | [0.9397, 0.9494] | 0.9337 | [0.9267, 0.9409] | yes | 1.0180 |
| 7 | Lex::seq | inline_never | 0.9061 | [0.8988, 0.9133] | 0.9426 | [0.9369, 0.9487] | yes | 0.9882 |

Confirmed arms (both batches exclude 1, same sign):

| arm | mark | candidate | batch 1 | 95% CI | batch 2 | 95% CI | clears MDE |
|---:|---|---|--:|---|--:|---|---|
| 66 | Val::hash | inline_always | 1.0426 | [1.0343, 1.0505] | 1.0484 | [1.0420, 1.0546] | yes |
| 16 | write_until | inline_always | 1.0153 | [1.0042, 1.0265] | 1.0215 | [1.0122, 1.0312] | no |
| 70 | Val::hash | align_64 | 1.0118 | [1.0028, 1.0216] | 1.0069 | [1.0017, 1.0123] | no |
| 46 | reserve_rehash | inline_always | 1.0104 | [1.0047, 1.0162] | 1.0096 | [1.0036, 1.0162] | no |
| 20 | write_until | align_64 | 1.0102 | [1.0041, 1.0169] | 1.0131 | [1.0035, 1.0224] | no |
| 72 | String::fmt | inline_never | 0.9865 | [0.9802, 0.9933] | 0.9918 | [0.9869, 0.9970] | no |
| 12 | str_fold | inline_never | 0.9861 | [0.9792, 0.9927] | 0.9928 | [0.9876, 0.9982] | no |
| 5 | read::parse | align_64 | 0.9856 | [0.9785, 0.9918] | 0.9849 | [0.9774, 0.9929] | no |
| 1 | read::parse | inline_always | 0.9741 | [0.9513, 0.9956] | 0.9739 | [0.9675, 0.9802] | no |
| 17 | write_until | inline_never | 0.9625 | [0.9564, 0.9697] | 0.9678 | [0.9625, 0.9733] | yes |
| 51 | Rc<IndexMap>::drop_slow | inline_always | 0.9525 | [0.9475, 0.9572] | 0.9848 | [0.9773, 0.9922] | yes |
| 26 | write::write | inline_always | 0.9445 | [0.9397, 0.9494] | 0.9337 | [0.9267, 0.9409] | yes |
| 7 | Lex::seq | inline_never | 0.9061 | [0.8988, 0.9133] | 0.9426 | [0.9369, 0.9487] | yes |

## The null panel this run has: the in-run A/A

Every timed batch carries a third label that is a second copy of the baseline binary. Over the 60 batches of this run (37 first batches, 23 confirmations) that label ran **0.9774 to 1.0317 (5.43 points), sd 1.10%, and 28 of 60 of its intervals exclude 1.0**.

## The combination arm

Selected by: confirmed in two batches, ratio > 1. 3 sites.

* `reserve_rehash` inline_always
* `write_until` inline_always
* `Val::hash` inline_always

The one-batch rule would have chosen 5 sites: reserve_rehash inline_always, write_until inline_always, Val::hash inline_always, path::run inline_always, read::parse align_32

The point-estimate rule would have chosen 9 sites: Path::run{closure#0} align_64, Adapter::write_str align_32, reserve_rehash inline_always, write_until inline_always, TermId::run align_32, Val::hash inline_always, path::run inline_always, read::parse align_32, write::write align_32

Training: 1.0291 [0.9676, 1.0952], no confirmation batch. Correctness OK, build code.
