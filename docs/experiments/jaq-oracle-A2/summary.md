# jev-opt search run `oracle-A2`

target `jaq`, proposer `oracle`, case set `training` (objsearch, strproc, readwrite), 15 repetitions, warmup 3, pinned to CPU 4, gap 250 ms, vocabulary `v4-2026-09-22`, state format `state-v4.1-2026-09-22`, readout `forced_top1`.

Acceptance rule, fixed before the first round: a round becomes the best so far only if its output matches the baseline on every case, every plan entry was applied, and the lower end of its 95% CI is above the best point estimate so far (the baseline, 1.0000, is the first).

| round | site | candidate | code vs base | fn hints | loop hints | apply problems | correct | ratio | 95% CI | own kernel | own-kernel CI | confirmed | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | fn:jaq_json::read::parse | inline_always | code | 6 | 0 | none | yes | 0.9741 | [0.9513, 0.9956] | - | - | no | 1.0175 ±0.0155 | no |
| 2 | fn:jaq_json::read::parse | inline_never | identical | 6 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 3 | fn:jaq_json::read::parse | align_16 | identical | 6 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 4 | fn:jaq_json::read::parse | align_32 | layout | 6 | 0 | none | yes | 1.0122 | [1.0028, 1.0221] | - | - | no | 1.0013 ±0.0121 | no |
| 5 | fn:jaq_json::read::parse | align_64 | layout | 6 | 0 | none | yes | 0.9856 | [0.9785, 0.9918] | - | - | no | 0.9811 ±0.0065 | no |
| 6 | fn:<hifijson::SliceLexer as hifijson::token::Lex>::seq | inline_always | identical | 8 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 7 | fn:<hifijson::SliceLexer as hifijson::token::Lex>::seq | inline_never | code | 8 | 0 | none | yes | 0.9061 | [0.8988, 0.9133] | - | - | no | 0.9882 ±0.0081 | no |
| 8 | fn:<hifijson::SliceLexer as hifijson::token::Lex>::seq | align_16 | identical | 8 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 9 | fn:<hifijson::SliceLexer as hifijson::token::Lex>::seq | align_32 | identical | 8 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 10 | fn:<hifijson::SliceLexer as hifijson::token::Lex>::seq | align_64 | identical | 8 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 11 | fn:<hifijson::SliceLexer as hifijson::str::LexWrite>::str_fold | inline_always | identical | 5 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 12 | fn:<hifijson::SliceLexer as hifijson::str::LexWrite>::str_fold | inline_never | code | 5 | 0 | none | yes | 0.9861 | [0.9792, 0.9927] | - | - | no | 0.9893 ±0.0054 | no |
| 13 | fn:<hifijson::SliceLexer as hifijson::str::LexWrite>::str_fold | align_16 | identical | 5 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 14 | fn:<hifijson::SliceLexer as hifijson::str::LexWrite>::str_fold | align_32 | identical | 5 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 15 | fn:<hifijson::SliceLexer as hifijson::str::LexWrite>::str_fold | align_64 | identical | 5 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 16 | fn:<hifijson::SliceLexer as hifijson::write::Write>::write_until | inline_always | code | 6 | 0 | none | yes | 1.0153 | [1.0042, 1.0265] | - | - | no | 0.9930 ±0.0135 | yes |
| 17 | fn:<hifijson::SliceLexer as hifijson::write::Write>::write_until | inline_never | code | 6 | 0 | none | yes | 0.9625 | [0.9564, 0.9697] | - | - | no | 0.9854 ±0.0080 | no |
| 18 | fn:<hifijson::SliceLexer as hifijson::write::Write>::write_until | align_16 | identical | 6 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 19 | fn:<hifijson::SliceLexer as hifijson::write::Write>::write_until | align_32 | layout | 6 | 0 | none | yes | 0.9919 | [0.9866, 0.9971] | - | - | no | 1.0070 ±0.0056 | no |
| 20 | fn:<hifijson::SliceLexer as hifijson::write::Write>::write_until | align_64 | layout | 6 | 0 | none | yes | 1.0102 | [1.0041, 1.0169] | - | - | no | 0.9869 ±0.0086 | no |
| 21 | fn:<jaq_core::compile::TermId>::run | inline_always | identical | 2 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 22 | fn:<jaq_core::compile::TermId>::run | inline_never | identical | 2 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 23 | fn:<jaq_core::compile::TermId>::run | align_16 | identical | 2 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 24 | fn:<jaq_core::compile::TermId>::run | align_32 | code | 2 | 0 | none | yes | 1.0084 | [1.0000, 1.0164] | - | - | not triggered | 0.9774 ±0.0109 | no |
| 25 | fn:<jaq_core::compile::TermId>::run | align_64 | code | 2 | 0 | none | yes | 0.9936 | [0.9845, 1.0025] | - | - | not triggered | 0.9931 ±0.0061 | no |
| 26 | fn:jaq_json::write::write | inline_always | code | 1 | 0 | none | yes | 0.9445 | [0.9397, 0.9494] | - | - | no | 1.0180 ±0.0073 | no |
| 27 | fn:jaq_json::write::write | inline_never | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 28 | fn:jaq_json::write::write | align_16 | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 29 | fn:jaq_json::write::write | align_32 | layout | 1 | 0 | none | yes | 1.0050 | [0.9991, 1.0111] | - | - | not triggered | 1.0010 ±0.0063 | no |
| 30 | fn:jaq_json::write::write | align_64 | layout | 1 | 0 | none | yes | 0.9941 | [0.9856, 1.0024] | - | - | not triggered | 0.9961 ±0.0106 | no |
| 31 | fn:<jaq_json::funs::base<jaq_all::data::DataKind>::{closure#3} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once | inline_always | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 32 | fn:<jaq_json::funs::base<jaq_all::data::DataKind>::{closure#3} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once | inline_never | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 33 | fn:<jaq_json::funs::base<jaq_all::data::DataKind>::{closure#3} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once | align_16 | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 34 | fn:<jaq_json::funs::base<jaq_all::data::DataKind>::{closure#3} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once | align_32 | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 35 | fn:<jaq_json::funs::base<jaq_all::data::DataKind>::{closure#3} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once | align_64 | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 36 | fn:<<jaq_core::path::Path<jaq_json::Val>>::run::{closure#0} as core::ops::function::FnOnce<(jaq_core::path::Part<jaq_json::Val>, jaq_json::Val)>>::call_once | inline_always | identical | 2 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 37 | fn:<<jaq_core::path::Path<jaq_json::Val>>::run::{closure#0} as core::ops::function::FnOnce<(jaq_core::path::Part<jaq_json::Val>, jaq_json::Val)>>::call_once | inline_never | identical | 2 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 38 | fn:<<jaq_core::path::Path<jaq_json::Val>>::run::{closure#0} as core::ops::function::FnOnce<(jaq_core::path::Part<jaq_json::Val>, jaq_json::Val)>>::call_once | align_16 | identical | 2 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 39 | fn:<<jaq_core::path::Path<jaq_json::Val>>::run::{closure#0} as core::ops::function::FnOnce<(jaq_core::path::Part<jaq_json::Val>, jaq_json::Val)>>::call_once | align_32 | layout | 2 | 0 | none | yes | 0.9884 | [0.9822, 0.9947] | - | - | no | 0.9945 ±0.0073 | no |
| 40 | fn:<<jaq_core::path::Path<jaq_json::Val>>::run::{closure#0} as core::ops::function::FnOnce<(jaq_core::path::Part<jaq_json::Val>, jaq_json::Val)>>::call_once | align_64 | code | 2 | 0 | none | yes | 1.0089 | [0.9919, 1.0217] | - | - | not triggered | 0.9988 ±0.0080 | no |
| 41 | fn:<core::io::write::default_write_fmt::Adapter<alloc::io::buffered::bufwriter::BufWriter<std::io::stdio::StdoutLock>> as core::fmt::Write>::write_str | inline_always | code | 1 | 0 | none | yes | 0.9914 | [0.9853, 0.9980] | - | - | no | 1.0019 ±0.0079 | no |
| 42 | fn:<core::io::write::default_write_fmt::Adapter<alloc::io::buffered::bufwriter::BufWriter<std::io::stdio::StdoutLock>> as core::fmt::Write>::write_str | inline_never | code | 1 | 0 | none | yes | 1.0032 | [0.9967, 1.0095] | - | - | not triggered | 0.9885 ±0.0084 | no |
| 43 | fn:<core::io::write::default_write_fmt::Adapter<alloc::io::buffered::bufwriter::BufWriter<std::io::stdio::StdoutLock>> as core::fmt::Write>::write_str | align_16 | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 44 | fn:<core::io::write::default_write_fmt::Adapter<alloc::io::buffered::bufwriter::BufWriter<std::io::stdio::StdoutLock>> as core::fmt::Write>::write_str | align_32 | layout | 1 | 0 | none | yes | 1.0059 | [0.9976, 1.0148] | - | - | not triggered | 1.0117 ±0.0111 | no |
| 45 | fn:<core::io::write::default_write_fmt::Adapter<alloc::io::buffered::bufwriter::BufWriter<std::io::stdio::StdoutLock>> as core::fmt::Write>::write_str | align_64 | layout | 1 | 0 | none | yes | 0.9987 | [0.9916, 1.0063] | - | - | not triggered | 0.9938 ±0.0063 | no |
| 46 | fn:<hashbrown::raw::RawTable<usize>>::reserve_rehash::<indexmap::map::core::get_hash<jaq_json::Val, jaq_json::Val>::{closure#0}> | inline_always | code | 1 | 0 | none | yes | 1.0104 | [1.0047, 1.0162] | - | - | no | 0.9987 ±0.0047 | no |
| 47 | fn:<hashbrown::raw::RawTable<usize>>::reserve_rehash::<indexmap::map::core::get_hash<jaq_json::Val, jaq_json::Val>::{closure#0}> | inline_never | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 48 | fn:<hashbrown::raw::RawTable<usize>>::reserve_rehash::<indexmap::map::core::get_hash<jaq_json::Val, jaq_json::Val>::{closure#0}> | align_16 | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 49 | fn:<hashbrown::raw::RawTable<usize>>::reserve_rehash::<indexmap::map::core::get_hash<jaq_json::Val, jaq_json::Val>::{closure#0}> | align_32 | layout | 1 | 0 | none | yes | 0.9970 | [0.9732, 1.0136] | - | - | not triggered | 0.9957 ±0.0109 | no |
| 50 | fn:<hashbrown::raw::RawTable<usize>>::reserve_rehash::<indexmap::map::core::get_hash<jaq_json::Val, jaq_json::Val>::{closure#0}> | align_64 | layout | 1 | 0 | none | yes | 0.9921 | [0.9854, 0.9991] | - | - | no | 1.0123 ±0.0079 | no |
| 51 | fn:<alloc::rc::Rc<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>>::drop_slow | inline_always | code | 1 | 0 | none | yes | 0.9525 | [0.9475, 0.9572] | - | - | no | 0.9781 ±0.0074 | no |
| 52 | fn:<alloc::rc::Rc<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>>::drop_slow | inline_never | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 53 | fn:<alloc::rc::Rc<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>>::drop_slow | align_16 | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 54 | fn:<alloc::rc::Rc<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>>::drop_slow | align_32 | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 55 | fn:<alloc::rc::Rc<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>>::drop_slow | align_64 | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 56 | fn:<jaq_std::base_run<jaq_all::data::DataKind>::{closure#7} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once | inline_always | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 57 | fn:<jaq_std::base_run<jaq_all::data::DataKind>::{closure#7} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once | inline_never | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 58 | fn:<jaq_std::base_run<jaq_all::data::DataKind>::{closure#7} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once | align_16 | identical | 1 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 59 | fn:<jaq_std::base_run<jaq_all::data::DataKind>::{closure#7} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once | align_32 | layout | 1 | 0 | none | yes | 0.9744 | [0.9668, 0.9830] | - | - | no | 0.9846 ±0.0085 | no |
| 60 | fn:<jaq_std::base_run<jaq_all::data::DataKind>::{closure#7} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once | align_64 | layout | 1 | 0 | none | yes | 0.9911 | [0.9863, 0.9962] | - | - | no | 1.0033 ±0.0074 | no |
| 61 | fn:jaq_core::path::run | inline_always | code | 3 | 0 | none | yes | 1.0116 | [1.0029, 1.0197] | - | - | no | 1.0071 ±0.0060 | no |
| 62 | fn:jaq_core::path::run | inline_never | identical | 3 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 63 | fn:jaq_core::path::run | align_16 | identical | 3 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 64 | fn:jaq_core::path::run | align_32 | layout | 3 | 0 | none | yes | 1.0041 | [0.9973, 1.0105] | - | - | not triggered | 1.0069 ±0.0070 | no |
| 65 | fn:jaq_core::path::run | align_64 | layout | 3 | 0 | none | yes | 0.9860 | [0.9804, 0.9915] | - | - | no | 0.9780 ±0.0059 | no |
| 66 | fn:<jaq_json::Val as core::hash::Hash>::hash | inline_always | code | 4 | 0 | none | yes | 1.0426 | [1.0343, 1.0505] | - | - | no | 1.0032 ±0.0066 | yes |
| 67 | fn:<jaq_json::Val as core::hash::Hash>::hash | inline_never | identical | 4 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 68 | fn:<jaq_json::Val as core::hash::Hash>::hash | align_16 | identical | 4 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 69 | fn:<jaq_json::Val as core::hash::Hash>::hash | align_32 | layout | 4 | 0 | none | yes | 1.0054 | [0.9995, 1.0116] | - | - | not triggered | 1.0029 ±0.0084 | no |
| 70 | fn:<jaq_json::Val as core::hash::Hash>::hash | align_64 | layout | 4 | 0 | none | yes | 1.0118 | [1.0028, 1.0216] | - | - | no | 1.0076 ±0.0075 | no |
| 71 | fn:<&alloc::string::String as core::fmt::Display>::fmt | inline_always | code | 7 | 0 | none | yes | 0.9957 | [0.9883, 1.0031] | - | - | not triggered | 0.9991 ±0.0075 | no |
| 72 | fn:<&alloc::string::String as core::fmt::Display>::fmt | inline_never | code | 7 | 0 | none | yes | 0.9865 | [0.9802, 0.9933] | - | - | no | 1.0112 ±0.0044 | no |
| 73 | fn:<&alloc::string::String as core::fmt::Display>::fmt | align_16 | identical | 7 | 0 | none | yes | 1.0000 | - | - | - | n/a | - | no |
| 74 | fn:<&alloc::string::String as core::fmt::Display>::fmt | align_32 | code | 7 | 0 | none | yes | 0.9988 | [0.9802, 1.0160] | - | - | not triggered | 0.9994 ±0.0393 | no |
| 75 | fn:<&alloc::string::String as core::fmt::Display>::fmt | align_64 | code | 7 | 0 | none | yes | 0.9475 | [0.9188, 0.9812] | - | - | no | 1.0317 ±0.0395 | no |
| 76 | combination | - | code | 11 | 0 | none | yes | 1.0291 | [0.9676, 1.0952] | - | - | not triggered | 1.0071 ±0.0560 | no |

Best plan: round-66 (round 66, ratio 1.0426). `best-plan.json` is a copy of it.

The holdout has NOT been measured by this run (SPEC.ja.md 7: the holdout is measured once, after the best plan is frozen; pass --measure-holdout).
