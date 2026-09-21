# Marks for jaq --- the profile they were chosen from

Date: 2026-09-22. Machine, toolchain and binary as in results.md
"Stage 0 (jaq)": rustc 1.100.0-nightly bba531001 / LLVM 23.1.1, the PGO
baseline build of jaq v3.1.1 (`.text`
`642dd55ea3c831132b4adf006464d9f1ef924ccb9918557e5f3c751355f72b4c`,
`pgo/jaq/merged.profdata`
`4e879ce11687fa3c56c720c8b33dd7d0546e0d5c7d9b7c612fef903de9f3a4e5`, both
re-verified before recording).

This file records **where the cycles are**. It contains no hint, attribute
or compiler setting, and no suggestion of one: under decision 58 the human
side says where, and jev-opt decides what to do there. The marks themselves
are in `targets/jaq/jev-marks.txt`.

## How it was measured

`perf` --- SPEC.ja.md 10's first choice, and absent from this machine until
now (results.md "Day 0 (toy)" section 3 recorded its absence, and
`scripts/ipsample.c` exists because of it). It was made to work without
root: `scripts/perf_local.sh` downloads Debian's `linux-perf` and the three
shared libraries Pengwin 13 lacks, unpacks them into a private prefix and
writes a wrapper that sets `LD_LIBRARY_PATH` and `PERF_EXEC_PATH`. The WSL2
kernel 6.18.33.2 has `CONFIG_PERF_EVENTS=y` and its virtualised PMU answers
`perf_event_open` for hardware `cycles`, so `scripts/ipsample.c` was **not**
needed.

```
scripts/perf_local.sh setup                      # no root; ~5 MB of .deb
export TARGET=jaq
scripts/perf_marks_profile.sh /tmp/perf-flat 6 5000
scripts/perf_hotness.py --binary target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/jaq \
    --inline --crates --top 35 --tsv artifacts/jaq-marks/perf-self.tsv \
    --inline-tsv artifacts/jaq-marks/perf-inline.tsv /tmp/perf-flat/*.data
scripts/inline_structure.py --binary target-jaq-pgo-use/.../jaq \
    --names-from artifacts/jaq-marks/perf-self.tsv --top 24 \
    --tsv artifacts/jaq-marks/inline-structure.tsv
scripts/perf_hotness.py --binary target-jaq-pgo-use/.../jaq --top 0 \
    --marks targets/jaq/jev-marks.txt /tmp/perf-flat/*.data
```

Six workloads (the three holdout and the three training cases of results.md
section 52, argv for argv, repeat counts included), each recorded as six
consecutive runs under one `perf record -e cycles:u -F 5000`, pinned to CPU
4 with stdout to `/dev/null`.

| workload | samples | in-binary share of user cycles |
|---|--:|--:|
| hold-objsearch | 31841 | 94.63% |
| hold-strproc | 33685 | 97.06% |
| hold-readwrite | 27254 | 68.20% |
| train-objsearch | 31800 | 94.60% |
| train-strproc | 33374 | 97.17% |
| train-readwrite | 27079 | 68.37% |

185033 samples, 27079 to 33685 per workload --- above the 20000 asked for.
Shares below are **sample periods summed** (what `perf report`'s Overhead
column shows) as a percentage of the periods that landed inside the jaq
binary.

Four properties of the measurement that the numbers depend on:

1. **User cycles only.** `perf_event_paranoid` is 2, so `cycles:u` is the
   only thing samplable and kernel time is invisible. 11.16% of all samples
   land outside the binary --- 8.03% at kernel addresses (WSL2's PMU
   reports the kernel IP even for a `:u` event) and 3.04% in libc. The
   readwrite case is the one that notices: 32% of its user-cycle samples
   are outside the binary, because it writes 50 MB to `/dev/null`. Every
   share here is a share of the 88.84% that is inside.
2. **The hardware PMU is trustworthy here.** The hold-strproc case was
   recorded a second time with the software `cpu-clock` event. Hardware
   `cycles` against `cpu-clock`, top 8: 25.97/26.16, 13.30/13.05,
   6.40/6.48, 6.34/6.32, 4.08/3.81, 3.80/3.77, 3.17/3.22, 3.14/3.09 --- no
   symbol differs by more than 0.3 points, and the concentration agrees to
   0.6 points (top 5 56.09 vs 55.82, top 30 91.13 vs 90.57). A virtualised
   PMU that fabricated its samples would not reproduce a software timer.
3. **Attribution is done here, not by perf.** The binary has 761 demangled
   names with more than one definition (`jaq_json::read::parse` has four),
   and a mark names a source function, so the copies must be summed. Each
   sample's ip is turned into a link-time vaddr through its own process's
   `PERF_RECORD_MMAP2` record and the binary's LOAD headers, then resolved
   against `nm` and against `llvm-symbolizer --inlining`. Both are Debian's LLVM 19.1.7; demangling
   the binary's 5723 text symbols with the pinned toolchain's LLVM 23.1.1
   `llvm-nm -C` yields an identical set of 4763 Rust names, so the marks
   are spelled the way the plugin's own `llvm::demangle()` will spell
   them.
4. **Callchains were attempted and are not usable.** The binary keeps no
   frame pointers (`--call-graph fp` returns stack garbage), and
   `--call-graph dwarf` at 4096 and at 32768 bytes of stack both resolve
   only ~20-25% of samples to more than one frame, with **zero** usable
   chains rooted in a mimalloc leaf. So there is no inclusive
   ("`--children`") column below, and no attribution of the allocator's
   22.94% to the jaq functions that drive it. Recorded as a negative
   result; the flat and inline-aware tables are what the marks rest on.

## Self time by post-LTO symbol

`share` = summed over all six workloads; `eq-w` = the mean of the six
per-workload shares (so a case that burns more CPU cannot carry the table);
`obj`/`str`/`rw` = the per-case share, holdout and training averaged (the
two splits agree to within 0.5 points everywhere, which is the strongest
statement this profile makes about its own stability). `insns`, `vec` and
`be` (backedges) are `scripts/interp_share.py`'s machine-code counts for
that symbol.

| # | share | eq-w | obj | str | rw | insns | vec | be | crate | function |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|---|
| 1 | 29.29% | 29.15% | 33.9 | 26.0 | 27.5 | 4426 | 150 | 259 | jaq_json | `jaq_json::read::parse::<hifijson::SliceLexer>` |
| 2 | 8.32% | 6.91% | 6.8 | 13.2 | 0.8 | 6562 | 549 | 236 | jaq_core | `<jaq_core::compile::TermId>::run::<jaq_all::data::DataKind>` |
| 3 | 6.81% | 6.14% | 9.3 | 6.6 | 2.5 | 46 | 0 | 3 | C:mimalloc | `mi_free` |
| 4 | 4.48% | 7.55% | 0.1 | 0.0 | 22.6 | 2390 | 22 | 179 | jaq_json | `jaq_json::write::write` |
| 5 | 3.10% | 2.92% | 3.6 | 3.2 | 1.9 | 34 | 0 | 2 | C:mimalloc | `_mi_page_malloc_zero` |
| 6 | 3.09% | 2.89% | 3.7 | 3.1 | 1.8 | 29 | 0 | 0 | C:mimalloc | `mi_theap_malloc_aligned` |
| 7 | 2.71% | 2.12% | 0.0 | 6.4 | 0.0 | 451 | 30 | 40 | jaq_json | `<jaq_json::funs::base<jaq_all::data::DataKind>::{closure#3} as core::ops::function::FnO…` |
| 8 | 2.53% | 2.14% | 4.2 | 2.3 | 0.0 | 1012 | 48 | 53 | jaq_core | `<<jaq_core::path::Path<jaq_json::Val>>::run::{closure#0} as core::ops::function::FnOnce…` |
| 9 | 2.50% | 2.34% | 3.3 | 2.3 | 1.4 | 6 | 0 | 0 | C:mimalloc | `mi_malloc_aligned` |
| 10 | 2.45% | 4.11% | 0.2 | 0.0 | 12.2 | 41 | 0 | 2 | core | `<core::io::write::default_write_fmt::Adapter<alloc::io::buffered::bufwriter::BufWriter<…` |
| 11 | 2.43% | 2.66% | 4.6 | 0.1 | 3.3 | 346 | 21 | 16 | hashbrown | `<hashbrown::raw::RawTable<usize>>::reserve_rehash::<indexmap::map::core::get_hash<jaq_j…` |
| 12 | 2.37% | 2.23% | 5.0 | 0.7 | 1.1 | 271 | 0 | 29 | alloc | `<alloc::rc::Rc<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::Ra…` |
| 13 | 1.99% | 1.59% | 1.0 | 3.8 | 0.0 | 434 | 34 | 18 | core | `<core::iter::adapters::flatten::FlatMap<core::iter::adapters::filter::Filter<alloc::box…` |
| 14 | 1.95% | 1.66% | 3.5 | 1.5 | 0.0 | 21 | 0 | 1 | C:mimalloc | `mi_page_free_list_extend` |
| 15 | 1.73% | 1.36% | 0.0 | 4.1 | 0.0 | 432 | 98 | 14 | jaq_std | `<jaq_std::base_run<jaq_all::data::DataKind>::{closure#7} as core::ops::function::FnOnce…` |
| 16 | 1.31% | 1.07% | 1.2 | 2.0 | 0.0 | 466 | 58 | 13 | jaq_core | `jaq_core::path::run::<jaq_json::Val, jaq_json::Val, alloc::vec::into_iter::IntoIter<(ja…` |
| 17 | 1.30% | 1.02% | 0.0 | 3.1 | 0.0 | 582 | 54 | 25 | core | `<core::iter::sources::from_fn::FromFn<jaq_core::fold::fold<jaq_core::filter::Ctx<jaq_al…` |
| 18 | 1.19% | 0.99% | 1.4 | 1.5 | 0.0 | 1052 | 118 | 19 | jaq_core | `<jaq_core::path::Path<core::result::Result<jaq_json::Val, jaq_core::exn::Exn<jaq_json::…` |
| 19 | 1.17% | 1.23% | 1.7 | 0.6 | 1.4 | 1492 | 0 | 90 | jaq_json | `<jaq_json::Val as core::hash::Hash>::hash::<foldhash::fast::FoldHasher>` |
| 20 | 1.10% | 1.86% | 0.0 | 0.0 | 5.6 | 471 | 152 | 25 | ? | `<&alloc::string::String as core::fmt::Display>::fmt` |
| 21 | 0.93% | 0.75% | 0.5 | 1.7 | 0.0 | 900 | 126 | 13 | jaq_core | `jaq_core::filter::bind_vars::<jaq_all::data::DataKind, jaq_json::Val>` |
| 22 | 0.81% | 0.68% | 0.4 | 1.5 | 0.2 | 166 | 0 | 15 | C:mimalloc | `_mi_theap_realloc_zero` |
| 23 | 0.75% | 1.26% | 0.0 | 0.0 | 3.7 | 480 | 152 | 25 | ? | `<&str as core::fmt::Display>::fmt` |
| 24 | 0.66% | 0.54% | 0.5 | 1.1 | 0.0 | 310 | 14 | 9 | core | `<core::iter::adapters::flatten::FlatMap<alloc::boxed::Box<dyn core::iter::traits::itera…` |
| 25 | 0.63% | 0.51% | 0.4 | 1.1 | 0.0 | 7 | 2 | 0 | core | `<core::iter::sources::once::Once<core::result::Result<jaq_json::Val, jaq_core::exn::Exn…` |
| 26 | 0.62% | 1.00% | 0.1 | 0.0 | 2.9 | 222 | 0 | 17 | ? | `<&isize as core::fmt::Display>::fmt` |
| 27 | 0.60% | 0.97% | 0.2 | 0.0 | 2.7 | 985 | 23 | 74 | jaq | `jaq::real_main::{closure#6}` |
| 28 | 0.57% | 0.90% | 0.2 | 0.0 | 2.5 | 454 | 7 | 31 | alloc | `<alloc::io::buffered::bufwriter::BufWriter<std::io::stdio::StdoutLock> as core::io::wri…` |
| 29 | 0.57% | 0.49% | 0.8 | 0.6 | 0.1 | 134 | 0 | 18 | jaq_json | `<jaq_json::Val as core::cmp::PartialEq>::eq` |
| 30 | 0.53% | 0.88% | 0.1 | 0.0 | 2.6 | 79 | 7 | 5 | ? | `<&jaq_json::num::Num as core::fmt::Display>::fmt` |

Concentration: **top 5 = 52.01%, top 10 = 65.30%, top 20 = 81.84%, top 30 =
88.50%.** Of the whole in-binary profile, **22.94% is mimalloc's C**, spread
over 88 symbols, and 77.06% is Rust.

By crate (leading path component of the demangled name, C counted as one):
jaq_json 38.50%, mimalloc (C) 22.94%, jaq_core 15.26%, core 10.47%, alloc
4.49%, `?` 3.00% (names beginning `<&...`, almost all of them
`core::fmt::Display::fmt` instantiations on the write path), hashbrown
2.43%, jaq_std 1.73%, jaq 0.60% (the bin crate), bytes 0.55%. jaq's own
workspace crates hold 56.1%, which is not comparable with the 35.3% of
results.md section 54: that number was a share of *instrumented* code,
whose denominator excluded mimalloc entirely.

## Inline-aware reach

Under fat LTO a hot symbol is an inline host: `jaq_json::read::parse` is
4426 instructions and 259 backedges of which only 805 instructions belong to
`read::parse` itself. A mark names a source function, so the question is not
"which symbol is hot" but "whose code is hot". `reach` is the share of
cycles running machine code with that function anywhere in its inlined frame
stack; `leaf` is the share where it is the innermost frame. `own/ownbe` and
`reach-insns/be` come from `scripts/inline_structure.py`: instructions and
machine-code backedges belonging to the function's own body, and to its body
plus everything inlined into it.

| # | reach | leaf | obj | str | rw | own/ownbe | reach-insns/be | function |
|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 1 | 29.29% | 2.92% | 33.9 | 26.0 | 27.5 | 805/26 | 4426/259 | `jaq_json::read::parse::<hifijson::SliceLexer>` |
| 2 | 10.85% | 0.07% | 16.2 | 5.0 | 13.3 | 69/0 | 1064/49 | `<hifijson::SliceLexer as hifijson::token::Lex>::seq::<hifijson::Error, jaq_json::read::…` |
| 3 | 10.64% | 1.90% | 15.9 | 4.9 | 13.1 | 240/4 | 763/21 | `jaq_json::read::parse::<hifijson::SliceLexer>::{closure#1}` |
| 4 | 9.07% | 0.05% | 4.1 | 16.8 | 1.9 | 44/2 | 715/46 | `<hifijson::SliceLexer as hifijson::str::LexWrite>::str_fold::<hifijson::str::Error, all…` |
| 5 | 9.07% | 0.00% | 4.1 | 16.8 | 1.9 | 0/0 | 715/46 | `jaq_json::read::parse_string::<hifijson::SliceLexer>` |
| 6 | 8.32% | 2.02% | 6.8 | 13.2 | 0.8 | 1322/24 | 6562/236 | `<jaq_core::compile::TermId>::run::<jaq_all::data::DataKind>` |
| 7 | 7.53% | 0.49% | 3.4 | 14.0 | 1.4 | 15/0 | 69/3 | `<hifijson::SliceLexer as hifijson::write::Write>::write_until::<hifijson::str::LexWrite…` |
| 8 | 7.45% | 0.00% | 11.1 | 3.3 | 9.6 | 19/0 | 253/10 | `<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>::i…` |
| 9 | 7.45% | 1.38% | 11.1 | 3.3 | 9.6 | 9/0 | 234/10 | `<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>::i…` |
| 10 | 6.81% | 0.19% | 9.3 | 6.6 | 2.5 | -/- | -/- | `mi_free` |
| 11 | 6.75% | 0.00% | 2.8 | 12.9 | 1.0 | 0/0 | 43/2 | `<core::iter::adapters::copied::Copied<core::slice::iter::Iter<u8>> as core::iter::trait…` |
| 12 | 6.75% | 0.14% | 2.8 | 12.9 | 1.0 | 5/0 | 43/2 | `<core::slice::iter::Iter<u8> as core::iter::traits::iterator::Iterator>::try_fold::<(),…` |
| 13 | 6.75% | 0.00% | 2.8 | 12.9 | 1.0 | 0/0 | 43/2 | `<core::iter::adapters::copied::Copied<core::slice::iter::Iter<u8>> as core::iter::trait…` |
| 14 | 5.66% | 0.00% | 8.6 | 2.3 | 7.3 | 18/0 | 205/9 | `<indexmap::map::core::IndexMapCore<jaq_json::Val, jaq_json::Val>>::insert_full` |
| 15 | 4.70% | 2.64% | 6.5 | 4.6 | 1.4 | -/- | -/- | `mi_free_ex` |
| 16 | 4.68% | 1.13% | 1.8 | 9.1 | 0.6 | 6/0 | 20/0 | `core::iter::adapters::copied::copy_try_fold::<u8, (), core::ops::control_flow::ControlF…` |
| 17 | 4.48% | 1.23% | 0.1 | 0.0 | 22.6 | 749/16 | 2390/179 | `jaq_json::write::write` |
| 18 | 3.56% | 1.70% | 1.3 | 7.0 | 0.5 | 6/0 | 14/0 | `core::iter::traits::iterator::Iterator::position::check::<u8, hifijson::str::LexWrite::…` |
| 19 | 3.22% | 3.22% | 3.7 | 3.3 | 2.0 | -/- | -/- | `mi_page_malloc_zero` |
| 20 | 3.10% | 0.44% | 3.6 | 3.2 | 1.9 | -/- | -/- | `_mi_page_malloc_zero` |
| 21 | 3.09% | 0.00% | 3.7 | 3.1 | 1.8 | -/- | -/- | `mi_theap_malloc_aligned_at` |
| 22 | 3.09% | 0.00% | 3.7 | 3.1 | 1.8 | -/- | -/- | `mi_theap_malloc_aligned` |
| 23 | 3.09% | 3.03% | 3.7 | 3.1 | 1.8 | -/- | -/- | `mi_theap_malloc_zero_aligned_at` |
| 24 | 3.08% | 0.70% | 0.2 | 0.0 | 15.3 | 74/0 | 183/1 | `<alloc::io::buffered::bufwriter::BufWriter<std::io::stdio::StdoutLock> as core::io::wri…` |
| 25 | 2.99% | 0.03% | 4.5 | 1.2 | 4.0 | 103/0 | 793/33 | `jaq_json::read::parse_num::<hifijson::SliceLexer>` |

The string path reads as a chain, and the loop is two frames below the
function that looks hot: `str_fold` (9.07%) -> `write_until` (7.53%) ->
`Copied<Iter<u8>>::position` (6.75%) -> `Iter<u8>::try_fold` (6.75%) ->
`copy_try_fold` (4.68%) -> `position::check::{closure#0}` (3.56%, leaf
1.70%). `write_until`'s own body is 15 instructions with no backedge of its
own; the 3 backedges appear once the `position` chain is counted in. That is
why the marks name `str_fold` and `write_until` and not the `core::iter`
adapters: the adapters are the loop, the two hifijson functions are the
places a human would point at.

## Per workload

The three cases exercise three different halves of the program, and the
holdout/training pairs agree everywhere.

### objsearch --- `.[] | select(.k == "v") | .id` over 4 x 20 MiB of records

| # | share | hold | train | be | function |
|--:|--:|--:|--:|--:|---|
| 1 | 33.91% | 33.41 | 34.42 | 259 | `jaq_json::read::parse::<hifijson::SliceLexer>` |
| 2 | 9.30% | 9.48 | 9.12 | 3 | `mi_free` |
| 3 | 6.83% | 6.95 | 6.70 | 236 | `<jaq_core::compile::TermId>::run::<jaq_all::data::DataKind>` |
| 4 | 4.98% | 4.99 | 4.97 | 29 | `<alloc::rc::Rc<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::Ra…` |
| 5 | 4.58% | 4.73 | 4.43 | 16 | `<hashbrown::raw::RawTable<usize>>::reserve_rehash::<indexmap::map::core::get_hash<jaq_j…` |
| 6 | 4.16% | 4.20 | 4.12 | 53 | `<<jaq_core::path::Path<jaq_json::Val>>::run::{closure#0} as core::ops::function::FnOnce…` |
| 7 | 3.73% | 3.68 | 3.78 | 0 | `mi_theap_malloc_aligned` |
| 8 | 3.64% | 3.77 | 3.50 | 2 | `_mi_page_malloc_zero` |
| 9 | 3.52% | 3.38 | 3.66 | 1 | `mi_page_free_list_extend` |
| 10 | 3.29% | 3.33 | 3.26 | 0 | `mi_malloc_aligned` |

### strproc --- `[.[] | .name | ascii_downcase | length] | add` over 8 x 24 MiB

| # | share | hold | train | be | function |
|--:|--:|--:|--:|--:|---|
| 1 | 26.02% | 25.97 | 26.08 | 259 | `jaq_json::read::parse::<hifijson::SliceLexer>` |
| 2 | 13.16% | 13.30 | 13.01 | 236 | `<jaq_core::compile::TermId>::run::<jaq_all::data::DataKind>` |
| 3 | 6.57% | 6.40 | 6.75 | 3 | `mi_free` |
| 4 | 6.37% | 6.34 | 6.39 | 40 | `<jaq_json::funs::base<jaq_all::data::DataKind>::{closure#3} as core::ops::function::FnO…` |
| 5 | 4.08% | 4.08 | 4.07 | 14 | `<jaq_std::base_run<jaq_all::data::DataKind>::{closure#7} as core::ops::function::FnOnce…` |
| 6 | 3.79% | 3.80 | 3.77 | 18 | `<core::iter::adapters::flatten::FlatMap<core::iter::adapters::filter::Filter<alloc::box…` |
| 7 | 3.17% | 3.17 | 3.16 | 2 | `_mi_page_malloc_zero` |
| 8 | 3.09% | 3.14 | 3.05 | 0 | `mi_theap_malloc_aligned` |
| 9 | 3.05% | 3.13 | 2.97 | 25 | `<core::iter::sources::from_fn::FromFn<jaq_core::fold::fold<jaq_core::filter::Ctx<jaq_al…` |
| 10 | 2.30% | 2.37 | 2.22 | 0 | `mi_malloc_aligned` |

### readwrite --- `-c '.'` over 2 x 24 MiB of ndjson

| # | share | hold | train | be | function |
|--:|--:|--:|--:|--:|---|
| 1 | 27.51% | 27.30 | 27.72 | 259 | `jaq_json::read::parse::<hifijson::SliceLexer>` |
| 2 | 22.56% | 22.51 | 22.62 | 179 | `jaq_json::write::write` |
| 3 | 12.15% | 12.14 | 12.17 | 2 | `<core::io::write::default_write_fmt::Adapter<alloc::io::buffered::bufwriter::BufWriter<…` |
| 4 | 5.59% | 5.92 | 5.25 | 25 | `<&alloc::string::String as core::fmt::Display>::fmt` |
| 5 | 3.73% | 3.74 | 3.71 | 25 | `<&str as core::fmt::Display>::fmt` |
| 6 | 3.26% | 3.28 | 3.24 | 16 | `<hashbrown::raw::RawTable<usize>>::reserve_rehash::<indexmap::map::core::get_hash<jaq_j…` |
| 7 | 2.87% | 2.78 | 2.96 | 17 | `<&isize as core::fmt::Display>::fmt` |
| 8 | 2.74% | 2.71 | 2.76 | 74 | `jaq::real_main::{closure#6}` |
| 9 | 2.56% | 2.64 | 2.48 | 5 | `<&jaq_json::num::Num as core::fmt::Display>::fmt` |
| 10 | 2.55% | 2.52 | 2.58 | 3 | `mi_free` |

Only `jaq_json::read::parse` is in the top 3 of all six recordings. The write
path (`write::write`, `Adapter::write_str`, the `Display::fmt` family) is
readwrite-only; the builtin closures are strproc-only; the IndexMap work is
objsearch-heavy. A mark set chosen on the aggregate alone would be a mark set
for parsing, which is why the coverage below is also given per workload.

## What the PGO profile said, and what perf says

Both measure the same binary. results.md section 54's table is the sum of
PGO block counts per profdata record; the column beside it is this profile.

| profdata share | perf self | perf reach | function |
|--:|--:|--:|---|
| 22.52% | - | 7.53% | `<hifijson::SliceLexer as hifijson::write::Write>::write_until::<hifijson::str::LexWrite…` |
| 7.26% | 29.29% | 29.29% | `jaq_json::read::parse::<hifijson::SliceLexer>` |
| 5.73% | 1.73% | 1.73% | `<jaq_std::base_run<jaq_all::data::DataKind>::{closure#7} as core::ops::function::FnOnce…` |
| 4.66% | - | 0.46% | `jaq_json::read::ws_tk::<hifijson::SliceLexer>` |
| 4.62% | - | 2.29% | `<hifijson::SliceLexer as hifijson::num::LexWrite>::num_string_with` |
| 4.33% | 4.48% | 4.48% | `jaq_json::write::write` |
| 3.32% | - | 9.07% | `jaq_json::read::parse_string::<hifijson::SliceLexer>` |
| 2.22% | 0.04% | 2.68% | `core::ptr::drop_glue::<jaq_json::Val>` |
| 2.06% | 0.00% | 0.52% | `__rustc::__rust_alloc` |
| 2.00% | - | 0.39% | `__rustc::__rust_dealloc` |
| 1.93% | 8.32% | 8.32% | `<jaq_core::compile::TermId>::run::<jaq_all::data::DataKind>` |
| 1.92% | - | 7.45% | `<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>::i…` |
| 1.85% | - | 0.51% | `<jaq_json::num::Num>::from_str_radix` |
| 1.70% | 0.00% | 0.25% | `<alloc::raw_vec::RawVecInner>::finish_grow` |
| 1.56% | 2.45% | 2.49% | `<core::io::write::default_write_fmt::Adapter<alloc::io::buffered::bufwriter::BufWriter<…` |
| 1.56% | 0.25% | 2.35% | `<alloc::io::buffered::bufwriter::BufWriter<std::io::stdio::StdoutLock> as core::io::wri…` |
| 1.54% | - | 0.40% | `<alloc::raw_vec::RawVecInner>::grow_amortized` |
| 1.36% | 0.32% | 0.44% | `core::ptr::drop_glue::<alloc::boxed::Box<dyn core::iter::traits::iterator::Iterator<Ite…` |
| 1.21% | - | 2.30% | `<bstr::utf8::Chars as core::iter::traits::iterator::Iterator>::count` |
| 1.10% | - | 0.46% | `<alloc::vec::Vec<u8>>::reserve` |

Four differences, all structural rather than noise:

1. **`write_until` 22.52% -> 7.53%, and 0.00% as a symbol.** It is the
   single hottest profdata record and it does not appear in the perf flat
   table at all: fat LTO inlined it into `read::parse`. A profdata record is
   a pre-inlining IR function; a perf sample lands in the symbol that
   absorbed it.
2. **`read::parse` 7.26% -> 29.29%** and **`TermId::run` 1.93% -> 8.32%**,
   for the same reason from the other side: they are the hosts.
3. **mimalloc: 4.06% -> 22.94%.** The profile sees `__rust_alloc` and
   `__rust_dealloc` as one-instruction thunks because `-Cprofile-generate`
   cannot instrument C (results.md section 51 predicted exactly this and
   called the interpreter-layer share an under-count). Allocation is the
   second largest consumer of cycles in this program and no profdata-based
   list can show it.
4. **Block counts over-weight short hot loops.** `ws_tk` (4.66% -> 0.46%),
   `num_string_with` (4.62% -> 2.29%) and `from_str_radix` (1.85% -> 0.51%)
   are small bodies executed very often; `TermId::run` and `write::write`
   are large bodies with expensive instructions. A block count is a count,
   not a cost.

The practical consequence for this experiment: **the Stage 0 hot list was
not a good list of places to mark.** Its top entry is inlined away, its
second-largest real consumer is invisible, and the two functions that hold
37.6% of the cycles between them sit at ranks 2 and 11.

## The marks

15 lines in `targets/jaq/jev-marks.txt`, matched as documented there
(equality, or the line followed by `::<` or `::{closure`). `reach` is the
share of in-binary user cycles running code that belongs to a function the
line matches.

| reach | be | mark |
|--:|--:|---|
| 29.29% | 259 | `jaq_json::read::parse` |
| 13.05% | 49 | `<hifijson::SliceLexer as hifijson::token::Lex>::seq` |
| 9.07% | 46 | `<hifijson::SliceLexer as hifijson::str::LexWrite>::str_fold` |
| 8.85% | 236 | `<jaq_core::compile::TermId>::run` |
| 8.75% | 3 | `<hifijson::SliceLexer as hifijson::write::Write>::write_until` |
| 4.48% | 179 | `jaq_json::write::write` |
| 2.71% | 40 | `<jaq_json::funs::base<..>::{closure#3} as FnOnce<..>>::call_once` |
| 2.53% | 53 | `<<jaq_core::path::Path<jaq_json::Val>>::run::{closure#0} as FnOnce<..>>::call_once` |
| 2.49% | 2 | `<..Adapter<BufWriter<StdoutLock>> as core::fmt::Write>::write_str` |
| 2.43% | 16 | `<hashbrown::raw::RawTable<usize>>::reserve_rehash::<..get_hash<Val, Val>..>` |
| 2.37% | 29 | `<alloc::rc::Rc<IndexMap<Val, Val, RandomState>>>::drop_slow` |
| 1.73% | 14 | `<jaq_std::base_run<..>::{closure#7} as FnOnce<..>>::call_once` |
| 1.73% | 13 | `jaq_core::path::run` |
| 1.17% | 90 | `<jaq_json::Val as core::hash::Hash>::hash` |
| 1.10% | 25 | `<&alloc::string::String as core::fmt::Display>::fmt` |

The reaches overlap --- the four read-path marks union to exactly
`read::parse`'s own 29.29%, the other three being entirely inside it --- so
the union over all fifteen is what matters:

| | covered |
|---|--:|
| all six workloads | **60.91%** of in-binary user cycles |
| hold-objsearch | 58.17% |
| train-objsearch | 58.68% |
| hold-strproc | 56.91% |
| train-strproc | 56.72% |
| hold-readwrite | 74.62% |
| train-readwrite | 74.39% |
| of the **markable** (Rust) cycles | **79.04%** |

The 39.09% not covered is **22.94% mimalloc** plus a 16.15% tail whose
largest single entries are 1.56% (`FlatMap<Filter<Box<dyn Iterator>>>`),
1.30% (`FromFn<jaq_core::fold::fold<..>>`) and 1.19%
(`Path<Result<Val, Exn<Val>>>::combinations`).

### Why these fifteen

Every mark satisfies both tests the task sets: it carries share, and it
either still contains a machine-code loop after LTO (`be > 0` in the table
above --- all fifteen do) or is a hot body that is called rather than
inlined. They divide into four groups, and the division is deliberate:
the aggregate is 60% parsing, but a set chosen only on the aggregate would
cover the readwrite and objsearch cases badly.

* **Read path (4 marks, 29.29% union --- the three after the first are
  entirely inside it).** `read::parse` is the host --- top-3
  in all six recordings, 26-34% everywhere, 4426 instructions and 259
  backedges. The other three name the loops inside it that the inline table
  shows carrying the time: the token dispatcher (`Lex::seq`, 13.05%), the
  string body (`str_fold`, 9.07%) and the byte scanner (`write_until`,
  8.75%). They add nothing to the union --- they are inside the host --- but
  they are separate compile-time functions and separate loops, and naming
  them is the difference between pointing at one 4426-instruction body and
  pointing at the four places inside it that run. (`write_until`'s 8.75%
  exceeds the 7.53% of the `string_end` instantiation because the line also
  matches the `num_bytes_with` one.)
* **Filter/interpreter (5 marks).** `TermId::run` is the largest hot symbol
  in the binary (6562 instructions, 236 backedges) and holds 13.2% of
  strproc and 6.8% of objsearch. The four closures and `path::run` beneath
  it are the bodies the two filter-heavy cases actually spend time in.
* **Write path (3 marks).** Invisible in the aggregate top 5 and 22.6% +
  12.2% + 5.6% of the readwrite case. `Adapter::write_str` is only 41
  instructions but every byte jaq prints goes through it, and it is called,
  not inlined.
* **Object machinery (3 marks).** `reserve_rehash`, `Rc<IndexMap>::drop_slow`
  and `Val::hash` are 4.6%, 5.0% and 1.7% of objsearch. Two of the three are
  in third-party crates by name only: they are generics instantiated on
  `jaq_json::Val`, compiled inside jaq's own LTO unit, and `Val::hash` is the
  most loop-dense function in `jaq_json` (1492 instructions, 90 backedges).

### What was deliberately left out

* **mimalloc, 22.94%** --- 88 C symbols with no LLVM IR in the build. It is
  the second-largest consumer of cycles in the program and nothing a plugin
  can reach. `<mimalloc::MiMalloc as GlobalAlloc>::alloc` (the Rust shim) is
  reachable but is 757 instructions of inlined wrapper with no loop.
* **`core::ptr::drop_glue::<jaq_json::Val>`, 2.68% reach** --- the largest
  single unmarked Rust item. It is compiler-generated: there is no source
  function, only a monomorphised instantiation. It is named here rather than
  in the marks file so the omission is on the record.
* **The `core::iter` adapters under the lexer** (`position` 6.75%,
  `try_fold` 6.75%, `copy_try_fold` 4.68%, `position::check::{closure#0}`
  3.56%) --- they hold the backedge, but they are library plumbing that a
  human would not point at, and marking `write_until` and `str_fold` reaches
  the same machine code.
* **`__rust_alloc` / `__rust_dealloc`** (2.06% and 2.00% of the PGO block
  counts, 0.52% and 0.39% of cycles) --- one-instruction jump thunks.
* **The tail below 1%.** 88 symbols would be needed to add the next 10
  points, and the budget is 15 marks.
