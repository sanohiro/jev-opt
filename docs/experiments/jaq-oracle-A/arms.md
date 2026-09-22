| arm | mark | candidate | apply | correct | ratio | 95% CI | CI excludes 1 | changed syms | profile share | build vs baseline |
|---:|---|---|---|---|--:|---|---|--:|--:|---|
| 1 | read::parse | inline | consumed x18 | yes | 1.0032 | [0.9961, 1.0108] | no | identical | 0.00% | no-op build |
| 2 | read::parse | inline_never | consumed x18 | yes | 0.9995 | [0.9912, 1.0079] | no | 15 | 28.63% | code changed |
| 3 | read::parse | cold | consumed x18 | yes | 1.0038 | [0.9955, 1.0120] | no | 5 | 0.17% | code changed |
| 4 | read::parse | align_16 | consumed x18 | yes | 0.9902 | [0.9645, 1.0080] | no | identical | 0.00% | no-op build |
| 5 | read::parse | align_32 | consumed x18 | yes | 1.0113 | [1.0038, 1.0192] | yes (+) | identical | 0.00% | layout only |
| 6 | read::parse | align_64 | consumed x18 | yes | 1.0154 | [1.0066, 1.0235] | yes (+) | identical | 0.00% | layout only |
| 7 | Lex::seq | inline | consumed x8 | yes | 1.0002 | [0.9935, 1.0067] | no | identical | 0.00% | no-op build |
| 8 | Lex::seq | inline_never | consumed x8 | yes | 0.9482 | [0.9447, 0.9520] | yes (-) | 14 | 28.77% | code changed |
| 9 | Lex::seq | cold | consumed x8 | yes | 0.9878 | [0.9815, 0.9938] | yes (-) | identical | 0.00% | no-op build |
| 10 | Lex::seq | align_16 | consumed x8 | yes | 0.9997 | [0.9921, 1.0072] | no | identical | 0.00% | no-op build |
| 11 | Lex::seq | align_32 | consumed x8 | yes | 0.9980 | [0.9926, 1.0042] | no | identical | 0.00% | no-op build |
| 12 | Lex::seq | align_64 | consumed x8 | yes | 0.9741 | [0.9655, 0.9836] | yes (-) | identical | 0.00% | no-op build |
| 13 | str_fold | inline | consumed x5 | yes | 0.9960 | [0.9887, 1.0039] | no | identical | 0.00% | no-op build |
| 14 | str_fold | inline_never | consumed x5 | yes | 1.0134 | [1.0080, 1.0188] | yes (+) | 119 | 14.86% | code changed |
| 15 | str_fold | cold | consumed x5 | yes | 1.0155 | [1.0058, 1.0259] | yes (+) | identical | 0.00% | no-op build |
| 16 | str_fold | align_16 | consumed x5 | yes | 0.9942 | [0.9899, 0.9984] | yes (-) | identical | 0.00% | no-op build |
| 17 | str_fold | align_32 | consumed x5 | yes | 1.0035 | [0.9944, 1.0150] | no | identical | 0.00% | no-op build |
| 18 | str_fold | align_64 | consumed x5 | yes | 0.9852 | [0.9773, 0.9935] | yes (-) | identical | 0.00% | no-op build |
| 19 | write_until | inline | consumed x6 | yes | 1.0067 | [0.9983, 1.0173] | no | 4 | 12.00% | code changed |
| 20 | write_until | inline_never | consumed x6 | yes | 0.9575 | [0.9427, 0.9688] | yes (-) | 4 | 37.71% | code changed |
| 21 | write_until | cold | consumed x6 | yes | 1.0198 | [1.0135, 1.0256] | yes (+) | identical | 0.00% | no-op build |
| 22 | write_until | align_16 | consumed x6 | yes | 1.0038 | [0.9957, 1.0120] | no | identical | 0.00% | no-op build |
| 23 | write_until | align_32 | consumed x6 | yes | 0.9948 | [0.9890, 1.0009] | no | identical | 0.00% | layout only |
| 24 | write_until | align_64 | consumed x6 | yes | 1.0054 | [1.0006, 1.0103] | yes (+) | identical | 0.00% | layout only |
| 25 | TermId::run | inline | consumed x62 | yes | 1.0024 | [0.9947, 1.0103] | no | identical | 0.00% | no-op build |
| 26 | TermId::run | inline_never | consumed x62 | yes | 1.0001 | [0.9956, 1.0047] | no | 160 | 5.02% | code changed |
| 27 | TermId::run | cold | consumed x62 | yes | 1.0323 | [1.0249, 1.0401] | yes (+) | 10 | 0.06% | code changed |
| 28 | TermId::run | align_16 | consumed x62 | yes | 0.9933 | [0.9703, 1.0181] | no | identical | 0.00% | no-op build |
| 29 | TermId::run | align_32 | consumed x62 | yes | 1.0005 | [0.9923, 1.0084] | no | identical | 0.00% | layout only |
| 30 | TermId::run | align_64 | consumed x62 | yes | 1.0019 | [0.9956, 1.0078] | no | identical | 0.00% | layout only |
| 31 | write::write | inline | consumed x1 | yes | 0.9996 | [0.9935, 1.0066] | no | identical | 0.00% | no-op build |
| 32 | write::write | inline_never | consumed x1 | yes | 0.9885 | [0.9804, 0.9973] | yes (-) | identical | 0.00% | no-op build |
| 33 | write::write | cold | consumed x1 | yes | 0.9698 | [0.9624, 0.9771] | yes (-) | 12 | 8.55% | code changed |
| 34 | write::write | align_16 | consumed x1 | yes | 1.0130 | [1.0059, 1.0197] | yes (+) | identical | 0.00% | no-op build |
| 35 | write::write | align_32 | consumed x1 | yes | 1.0051 | [0.9971, 1.0153] | no | identical | 0.00% | layout only |
| 36 | write::write | align_64 | consumed x1 | yes | 1.0109 | [1.0036, 1.0184] | yes (+) | identical | 0.00% | layout only |
| 37 | funs::base{closure#3} | inline | consumed x1 | yes | 0.9861 | [0.9795, 0.9923] | yes (-) | identical | 0.00% | no-op build |
| 38 | funs::base{closure#3} | inline_never | consumed x1 | yes | 1.0039 | [0.9954, 1.0123] | no | identical | 0.00% | no-op build |
| 39 | funs::base{closure#3} | cold | consumed x1 | yes | 0.9984 | [0.9928, 1.0045] | no | identical | 0.00% | no-op build |
| 40 | funs::base{closure#3} | align_16 | consumed x1 | yes | 1.0073 | [0.9999, 1.0149] | no | identical | 0.00% | no-op build |
| 41 | funs::base{closure#3} | align_32 | consumed x1 | yes | 1.0130 | [1.0056, 1.0210] | yes (+) | identical | 0.00% | no-op build |
| 42 | funs::base{closure#3} | align_64 | consumed x1 | yes | 1.0095 | [1.0033, 1.0156] | yes (+) | identical | 0.00% | no-op build |
| 43 | Path::run{closure#0} | inline | consumed x2 | yes | 0.9967 | [0.9876, 1.0060] | no | identical | 0.00% | no-op build |
| 44 | Path::run{closure#0} | inline_never | consumed x2 | yes | 1.0080 | [0.9962, 1.0197] | no | identical | 0.00% | no-op build |
| 45 | Path::run{closure#0} | cold | consumed x2 | yes | 1.0041 | [0.9928, 1.0154] | no | identical | 0.00% | no-op build |
| 46 | Path::run{closure#0} | align_16 | consumed x2 | yes | 0.9834 | [0.9770, 0.9896] | yes (-) | identical | 0.00% | no-op build |
| 47 | Path::run{closure#0} | align_32 | consumed x2 | yes | 0.9988 | [0.9879, 1.0095] | no | identical | 0.00% | layout only |
| 48 | Path::run{closure#0} | align_64 | consumed x2 | yes | 1.0139 | [1.0070, 1.0211] | yes (+) | 1 | 0.05% | code changed |
| 49 | Adapter::write_str | inline | consumed x1 | yes | 0.9958 | [0.9900, 1.0014] | no | 1 | 0.00% | code changed |
| 50 | Adapter::write_str | inline_never | consumed x1 | yes | 1.0036 | [0.9992, 1.0081] | no | 3 | 7.44% | code changed |
| 51 | Adapter::write_str | cold | consumed x1 | yes | 1.0099 | [1.0052, 1.0144] | yes (+) | identical | 0.00% | no-op build |
| 52 | Adapter::write_str | align_16 | consumed x1 | yes | 1.0016 | [0.9909, 1.0108] | no | identical | 0.00% | no-op build |
| 53 | Adapter::write_str | align_32 | consumed x1 | yes | 0.9873 | [0.9828, 0.9913] | yes (-) | identical | 0.00% | layout only |
| 54 | Adapter::write_str | align_64 | consumed x1 | yes | 1.0080 | [1.0018, 1.0142] | yes (+) | identical | 0.00% | layout only |
| 55 | reserve_rehash | inline | consumed x1 | yes | 1.0074 | [1.0004, 1.0152] | yes (+) | 4 | 7.87% | code changed |
| 56 | reserve_rehash | inline_never | consumed x1 | yes | 0.9984 | [0.9923, 1.0046] | no | identical | 0.00% | no-op build |
| 57 | reserve_rehash | cold | consumed x1 | yes | 1.0209 | [1.0137, 1.0281] | yes (+) | identical | 0.00% | no-op build |
| 58 | reserve_rehash | align_16 | consumed x1 | yes | 0.9899 | [0.9819, 0.9975] | yes (-) | identical | 0.00% | no-op build |
| 59 | reserve_rehash | align_32 | consumed x1 | yes | 1.0012 | [0.9951, 1.0085] | no | identical | 0.00% | layout only |
| 60 | reserve_rehash | align_64 | consumed x1 | yes | 0.9972 | [0.9914, 1.0037] | no | identical | 0.00% | layout only |
| 61 | Rc<IndexMap>::drop_slow | inline | consumed x1 | yes | 0.9920 | [0.9816, 1.0029] | no | 43 | 14.37% | code changed |
| 62 | Rc<IndexMap>::drop_slow | inline_never | consumed x1 | yes | 0.9943 | [0.9886, 1.0000] | no | identical | 0.00% | no-op build |
| 63 | Rc<IndexMap>::drop_slow | cold | consumed x1 | yes | 1.0138 | [1.0086, 1.0189] | yes (+) | 7 | 3.75% | code changed |
| 64 | Rc<IndexMap>::drop_slow | align_16 | consumed x1 | yes | 0.9943 | [0.9866, 1.0011] | no | identical | 0.00% | no-op build |
| 65 | Rc<IndexMap>::drop_slow | align_32 | consumed x1 | yes | 1.0105 | [0.9581, 1.0723] | no | identical | 0.00% | no-op build |
| 66 | Rc<IndexMap>::drop_slow | align_64 | consumed x1 | yes | 1.0040 | [0.9962, 1.0111] | no | identical | 0.00% | no-op build |
| 67 | base_run{closure#7} | inline | consumed x1 | yes | 0.9834 | [0.9773, 0.9899] | yes (-) | identical | 0.00% | no-op build |
| 68 | base_run{closure#7} | inline_never | consumed x1 | yes | 0.9853 | [0.9813, 0.9894] | yes (-) | identical | 0.00% | no-op build |
| 69 | base_run{closure#7} | cold | consumed x1 | yes | 0.9860 | [0.9794, 0.9924] | yes (-) | identical | 0.00% | no-op build |
| 70 | base_run{closure#7} | align_16 | consumed x1 | yes | 0.9950 | [0.9877, 1.0028] | no | identical | 0.00% | no-op build |
| 71 | base_run{closure#7} | align_32 | consumed x1 | yes | 1.0229 | [1.0173, 1.0286] | yes (+) | identical | 0.00% | layout only |
| 72 | base_run{closure#7} | align_64 | consumed x1 | yes | 1.0114 | [1.0050, 1.0184] | yes (+) | identical | 0.00% | layout only |
| 73 | path::run | inline | consumed x12 | yes | 1.0070 | [0.9996, 1.0146] | no | identical | 0.00% | no-op build |
| 74 | path::run | inline_never | consumed x12 | yes | 0.9826 | [0.9774, 0.9872] | yes (-) | 126 | 4.43% | code changed |
| 75 | path::run | cold | consumed x12 | yes | 1.0026 | [0.9950, 1.0105] | no | 1 | 0.61% | code changed |
| 76 | path::run | align_16 | consumed x12 | yes | 0.9954 | [0.9900, 1.0005] | no | identical | 0.00% | no-op build |
| 77 | path::run | align_32 | consumed x12 | yes | 0.9884 | [0.9791, 0.9983] | yes (-) | identical | 0.00% | layout only |
| 78 | path::run | align_64 | consumed x12 | yes | 0.9954 | [0.9882, 1.0027] | no | identical | 0.00% | layout only |
| 79 | Val::hash | inline | consumed x12 | yes | 0.9959 | [0.9901, 1.0018] | no | identical | 0.00% | no-op build |
| 80 | Val::hash | inline_never | consumed x12 | yes | 1.0072 | [0.9997, 1.0148] | no | 128 | 8.11% | code changed |
| 81 | Val::hash | cold | consumed x12 | yes | 1.0013 | [0.9965, 1.0059] | no | 3 | 2.35% | code changed |
| 82 | Val::hash | align_16 | consumed x12 | yes | 0.9903 | [0.9840, 0.9972] | yes (-) | identical | 0.00% | no-op build |
| 83 | Val::hash | align_32 | consumed x12 | yes | 1.0032 | [0.9766, 1.0289] | no | identical | 0.00% | layout only |
| 84 | Val::hash | align_64 | consumed x12 | yes | 1.0064 | [1.0012, 1.0118] | yes (+) | identical | 0.00% | layout only |
| 85 | String::fmt | inline | consumed x7 | yes | 0.9898 | [0.9849, 0.9950] | yes (-) | 4 | 0.43% | code changed |
| 86 | String::fmt | inline_never | consumed x7 | yes | 1.0070 | [1.0009, 1.0134] | yes (+) | 4 | 0.43% | code changed |
| 87 | String::fmt | cold | consumed x7 | yes | 1.0013 | [0.9957, 1.0071] | no | identical | 0.00% | no-op build |
| 88 | String::fmt | align_16 | consumed x7 | yes | 1.0140 | [1.0067, 1.0241] | yes (+) | identical | 0.00% | no-op build |
| 89 | String::fmt | align_32 | consumed x7 | yes | 0.9921 | [0.9853, 0.9990] | yes (-) | 1 | 0.00% | code changed |
| 90 | String::fmt | align_64 | consumed x7 | yes | 1.0013 | [0.9946, 1.0078] | no | 1 | 0.00% | code changed |
| 91 | (combination) | - | consumed x106 | yes | 1.0215 | [1.0128, 1.0300] | yes (+) | 18 | 3.86% | code changed |

## Per mark: the best of its six candidates

| mark | best candidate | ratio | 95% CI | CI excludes 1 | worst candidate | ratio |
|---|---|--:|---|---|---|--:|
| read::parse | align_64 | 1.0154 | [1.0066, 1.0235] | yes (+) | align_16 | 0.9902 |
| Lex::seq | inline | 1.0002 | [0.9935, 1.0067] | no | inline_never | 0.9482 |
| str_fold | cold | 1.0155 | [1.0058, 1.0259] | yes (+) | align_64 | 0.9852 |
| write_until | cold | 1.0198 | [1.0135, 1.0256] | yes (+) | inline_never | 0.9575 |
| TermId::run | cold | 1.0323 | [1.0249, 1.0401] | yes (+) | align_16 | 0.9933 |
| write::write | align_16 | 1.0130 | [1.0059, 1.0197] | yes (+) | cold | 0.9698 |
| funs::base{closure#3} | align_32 | 1.0130 | [1.0056, 1.0210] | yes (+) | inline | 0.9861 |
| Path::run{closure#0} | align_64 | 1.0139 | [1.0070, 1.0211] | yes (+) | align_16 | 0.9834 |
| Adapter::write_str | cold | 1.0099 | [1.0052, 1.0144] | yes (+) | align_32 | 0.9873 |
| reserve_rehash | cold | 1.0209 | [1.0137, 1.0281] | yes (+) | align_16 | 0.9899 |
| Rc<IndexMap>::drop_slow | cold | 1.0138 | [1.0086, 1.0189] | yes (+) | inline | 0.9920 |
| base_run{closure#7} | align_32 | 1.0229 | [1.0173, 1.0286] | yes (+) | inline | 0.9834 |
| path::run | inline | 1.0070 | [0.9996, 1.0146] | no | inline_never | 0.9826 |
| Val::hash | inline_never | 1.0072 | [0.9997, 1.0148] | no | align_16 | 0.9903 |
| String::fmt | align_16 | 1.0140 | [1.0067, 1.0241] | yes (+) | inline | 0.9898 |

90 one-factor arms measured. Above +3%: 1. Below -3%: 3. Normalised-code-identical to the baseline: 67.

Above the MDE: TermId::run cold 1.0323

Below the MDE: Lex::seq inline_never 0.9482, write_until inline_never 0.9575, write::write cold 0.9698

**The in-sweep null panel.** 48 of the 90 arms produced a build whose normalised instruction text AND whose symbol table (addresses and sizes) are identical to the baseline's: the attribute was applied and changed nothing. Those 48 builds are the in-sweep null panel of SPEC.ja.md 7. Their ratios run 0.9741 to 1.0209 (4.67 points), and 20 of them have a 95% CI that excludes 1.

| null arm | ratio | 95% CI | CI excludes 1 |
|---|--:|---|---|
| reserve_rehash cold | 1.0209 | [1.0137, 1.0281] | yes (+) |
| write_until cold | 1.0198 | [1.0135, 1.0256] | yes (+) |
| str_fold cold | 1.0155 | [1.0058, 1.0259] | yes (+) |
| String::fmt align_16 | 1.0140 | [1.0067, 1.0241] | yes (+) |
| funs::base{closure#3} align_32 | 1.0130 | [1.0056, 1.0210] | yes (+) |
| write::write align_16 | 1.0130 | [1.0059, 1.0197] | yes (+) |
| Rc<IndexMap>::drop_slow align_32 | 1.0105 | [0.9581, 1.0723] | no |
| Adapter::write_str cold | 1.0099 | [1.0052, 1.0144] | yes (+) |
| funs::base{closure#3} align_64 | 1.0095 | [1.0033, 1.0156] | yes (+) |
| Path::run{closure#0} inline_never | 1.0080 | [0.9962, 1.0197] | no |
| funs::base{closure#3} align_16 | 1.0073 | [0.9999, 1.0149] | no |
| path::run inline | 1.0070 | [0.9996, 1.0146] | no |
| Path::run{closure#0} cold | 1.0041 | [0.9928, 1.0154] | no |
| Rc<IndexMap>::drop_slow align_64 | 1.0040 | [0.9962, 1.0111] | no |
| funs::base{closure#3} inline_never | 1.0039 | [0.9954, 1.0123] | no |
| write_until align_16 | 1.0038 | [0.9957, 1.0120] | no |
| str_fold align_32 | 1.0035 | [0.9944, 1.0150] | no |
| read::parse inline | 1.0032 | [0.9961, 1.0108] | no |
| TermId::run inline | 1.0024 | [0.9947, 1.0103] | no |
| Adapter::write_str align_16 | 1.0016 | [0.9909, 1.0108] | no |
| String::fmt cold | 1.0013 | [0.9957, 1.0071] | no |
| Lex::seq inline | 1.0002 | [0.9935, 1.0067] | no |
| Lex::seq align_16 | 0.9997 | [0.9921, 1.0072] | no |
| write::write inline | 0.9996 | [0.9935, 1.0066] | no |
| reserve_rehash inline_never | 0.9984 | [0.9923, 1.0046] | no |
| funs::base{closure#3} cold | 0.9984 | [0.9928, 1.0045] | no |
| Lex::seq align_32 | 0.9980 | [0.9926, 1.0042] | no |
| Path::run{closure#0} inline | 0.9967 | [0.9876, 1.0060] | no |
| str_fold inline | 0.9960 | [0.9887, 1.0039] | no |
| Val::hash inline | 0.9959 | [0.9901, 1.0018] | no |
| path::run align_16 | 0.9954 | [0.9900, 1.0005] | no |
| base_run{closure#7} align_16 | 0.9950 | [0.9877, 1.0028] | no |
| Rc<IndexMap>::drop_slow inline_never | 0.9943 | [0.9886, 1.0000] | no |
| Rc<IndexMap>::drop_slow align_16 | 0.9943 | [0.9866, 1.0011] | no |
| str_fold align_16 | 0.9942 | [0.9899, 0.9984] | yes (-) |
| TermId::run align_16 | 0.9933 | [0.9703, 1.0181] | no |
| Val::hash align_16 | 0.9903 | [0.9840, 0.9972] | yes (-) |
| read::parse align_16 | 0.9902 | [0.9645, 1.0080] | no |
| reserve_rehash align_16 | 0.9899 | [0.9819, 0.9975] | yes (-) |
| write::write inline_never | 0.9885 | [0.9804, 0.9973] | yes (-) |
| Lex::seq cold | 0.9878 | [0.9815, 0.9938] | yes (-) |
| funs::base{closure#3} inline | 0.9861 | [0.9795, 0.9923] | yes (-) |
| base_run{closure#7} cold | 0.9860 | [0.9794, 0.9924] | yes (-) |
| base_run{closure#7} inline_never | 0.9853 | [0.9813, 0.9894] | yes (-) |
| str_fold align_64 | 0.9852 | [0.9773, 0.9935] | yes (-) |
| Path::run{closure#0} align_16 | 0.9834 | [0.9770, 0.9896] | yes (-) |
| base_run{closure#7} inline | 0.9834 | [0.9773, 0.9899] | yes (-) |
| Lex::seq align_64 | 0.9741 | [0.9655, 0.9836] | yes (-) |

19 further arms changed no instruction, only where the code sits (an alignment that moved the symbols): ratios 0.9873 to 1.0229.
