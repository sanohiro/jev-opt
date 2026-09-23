# Marks for zopfli --- the rule, then the profile they were chosen from

This file records **where the cycles are** and the rule that turned that
into `targets/zopfli/jev-marks.txt`. It contains no hint, attribute or
compiler setting, and no suggestion of one: under decision 58 the human side
(here Claude as the human's proxy) says where, and jev-opt decides what to
do there. Section 1 was written and saved before any of the perf tables in
section 2 were produced or read.

## 1. Selection rule (fixed before the tables were read)

Inputs. The six `perf record -e cycles:u` files in `artifacts/zopfli-marks/`
(6 consecutive runs per case), taken with `scripts/perf_marks_profile.sh`
on the plugin-off base build
`target-zopfli-sites-base/x86_64-unknown-linux-gnu/release/zopfli`
(normalised-code identical to the Stage 0 baseline per `norm_code_diff.py`).
`train-{text,binary,json}.data` are the **search set**: the recorder labels
`TRAIN_WORKLOADS` as `train`, and for zopfli those are
`targets/zopfli/workloads/search-*.dat` (decision 98), **not** the PGO
training inputs `train-*.dat`. `hold-{text,binary,json}.data` are the
holdout cases `hold-*.dat`.

Metric. `reach` from `scripts/perf_hotness.py --inline`: the share of
in-binary user cycles (summed sample periods; samples outside the binary ---
kernel, libc --- are excluded from the denominator) whose inlined frame
stack contains the function, i.e. its own body plus everything inlined into
it, wherever fat LTO placed that code. `self` is the share of its own
post-LTO symbol(s), all copies summed.

Rule.
1. Rank every function by `reach` on the three search-set profiles
   aggregated (periods summed).
2. Walk down the ranking and add each function to the marks. After each
   addition, recompute the **union** coverage with
   `perf_hotness.py --top 0 --marks <candidate marks file>` on the same three
   profiles. Stop after the addition that first brings the union to
   **>= 90%** of in-binary cycles. Reach is not additive: a function whose
   code sits inside an already-marked function adds little or nothing to the
   union, and it is still included when its turn in the ranking comes (the
   jaq precedent, whose three lexer marks sit inside `read::parse`). No
   "skip if it adds less than X points" clause.
3. No crate filter: a function from `core`, `alloc` or a dependency counts
   like one from `zopfli`. Only process-entry glue whose inlined stack is the
   whole program rather than a piece of it (`main`, `std::rt::lang_start*`
   and their `FnOnce` shims) is skipped, since marking it would mark
   everything at once; any such skip is listed in section 3.
4. Existence gate. A mark must resolve to at least one LLVM IR function in
   the plugin's own view: `scripts/target_sites.sh dump` / `allkeys`. A mark
   the plugin reports as `unmatched` is removed (recorded in section 3,
   `--allow-unresolved` is not used), and the walk does **not** continue to
   refill the coverage. `nm -C` on the binary (does a post-LTO symbol of that
   name survive?) is recorded as information only, because marks match
   before inlining and a fully-inlined function can still resolve.
5. Names are copied from the tool's output (the demangled v0 spelling),
   never retyped.

Numbers carried into the marks file. Each mark's comment block carries
`share` = its self share and `reach` = its reach, both on the search set
aggregated, with the holdout values and the per-case range in parentheses
(the format `jev_search.py`'s `shares_from_marks_file` reads: the first
`share N%` and `reach N%` in the comment block directly above the name).

Agreement check with the holdout. The same tables are computed on the three
holdout profiles. For every function in the search-set top 10 by reach, the
holdout reach is reported next to it; a function that is in the top 10 of
one set and not the other, or whose reach differs by more than 2 points
between the sets, is named in section 3. The check reports; it does not
change the marks (the marks are chosen on the search set only).

## 2. The profile

Date: 2026-09-23. rustc 1.100.0-nightly bba531001 / LLVM 23.1.1; binary
`target-zopfli-sites-base/x86_64-unknown-linux-gnu/release/zopfli`
(profdata `pgo/zopfli/merged.profdata` `f066f507…`, `.text`
`9aca86fc…`, which the plugin dump build reproduces bit for bit).

```
export TARGET=zopfli
B=target-zopfli-sites-base/x86_64-unknown-linux-gnu/release/zopfli
D=artifacts/zopfli-marks
for s in train hold; do
  scripts/perf_hotness.py --binary $B --inline --crates --top 20 \
      --tsv $D/perf-self-$s.tsv --inline-tsv $D/perf-inline-$s.tsv \
      $D/$s-*.data > $D/perf-hotness-$s.txt
done
scripts/perf_hotness.py --binary $B --top 0 --marks <candidates> $D/train-*.data   # rule step 2
scripts/perf_hotness.py --binary $B --top 0 --marks targets/zopfli/jev-marks.txt $D/hold-*.data
```

| set | case | samples | in-binary share of user cycles |
|---|---|--:|--:|
| search | binary | 35042 | 92.55% |
| search | json | 57595 | 97.80% |
| search | text | 59340 | 98.45% |
| holdout | binary | 51427 | 91.84% |
| holdout | json | 85471 | 98.39% |
| holdout | text | 85779 | 98.51% |

Outside the binary: 2.90% (search) and 2.73% (holdout), kernel addresses
and libc. 99.87% of in-binary cycles are in the `zopfli` crate. Self-time
concentration (search): top 5 symbols 96.17%, top 10 99.06%.

Top 14 by reach on the search set (`S` = search, `H` = holdout; self is the
function's own post-LTO symbols; `nm` = a post-LTO text symbol of that name
exists in the binary):

| # | self S | reach S | per case S (bin/json/text) | self H | reach H | rank H | nm | function |
|--:|--:|--:|---|--:|--:|--:|:-:|---|
| 1 | 43.31 | 43.31 | 30.2/47.8/44.5 | 41.76 | 41.76 | 4 | y | `zopfli::lz77::find_longest_match_loop` |
| 2 | 40.53 | 40.53 | 38.9/37.8/43.8 | 42.87 | 42.87 | 1 | y | `zopfli::squeeze::lz77_optimal::<…>` |
| 3 | 0.00 | 39.82 | 36.8/37.4/43.4 | 0.00 | 42.10 | 3 | n | `zopfli::squeeze::get_best_lengths::<…>` |
| 4 | 0.00 | 39.82 | 36.8/37.4/43.4 | 0.00 | 42.10 | 2 | n | `zopfli::squeeze::lz77_optimal_run::<…>` |
| 5 | 0.00 | 15.02 | 28.2/12.5/11.9 | 0.00 | 16.20 | 5 | y | `<zopfli::hash::ZopfliHash>::update` |
| 6 | 0.00 | 11.62 | 21.8/9.8/9.1 | 0.00 | 12.63 | 6 | n | `<zopfli::hash::HashThing>::update` |
| 7 | 0.00 | 11.15 | 9.2/10.0/13.0 | 0.00 | 11.58 | 7 | y | `zopfli::lz77::find_longest_match::<…>` |
| 8 | 0.00 | 11.01 | 8.9/10.0/12.9 | 0.00 | 11.45 | 8 | y | `<zopfli::cache::ZopfliLongestMatchCache as zopfli::cache::Cache>::try_get` |
| 9 | 9.61 | 9.61 | 17.5/7.6/8.2 | 10.31 | 10.31 | 9 | y | `<zopfli::lz77::Lz77Store>::follow_path::<…>` |
| 10 | 0.00 | 6.82 | 14.5/5.7/4.7 | 0.00 | 7.48 | 10 | - | `<core::option::Option<u16> as core::cmp::PartialEq>::eq` |
| 11 | 0.00 | 6.53 | 3.0/6.5/8.1 | 0.00 | 6.65 | 11 | - | `<zopfli::cache::ZopfliLongestMatchCache>::fetch_sublen` |
| 12 | 0.00 | 4.41 | 2.4/4.4/5.3 | 0.00 | 4.60 | 12 | - | `zopfli::squeeze::get_cost_stat` |
| 13 | 0.00 | 4.41 | 2.4/4.4/5.3 | 0.00 | 4.60 | 13 | - | `zopfli::squeeze::lz77_optimal::<…>::{closure#0}` |
| 14 | 0.00 | 4.03 | 3.2/4.9/4.5 | 0.00 | 4.40 | 14 | - | `<zopfli::cache::ZopfliLongestMatchCache>::max_sublen` |

The walk (rule step 2), union coverage of in-binary cycles on the search
set after each addition:

| + function | union |
|---|--:|
| `zopfli::lz77::find_longest_match_loop` | 43.31% |
| `zopfli::squeeze::lz77_optimal` | 83.84% |
| `zopfli::squeeze::get_best_lengths` | 83.84% |
| `zopfli::squeeze::lz77_optimal_run` | 83.84% |
| `<zopfli::hash::ZopfliHash>::update` | 89.87% |
| `<zopfli::hash::HashThing>::update` | 89.87% |
| `zopfli::lz77::find_longest_match` | **93.37%** (stop) |

For information only (after the stop): adding `try_get` leaves the union at
93.37%, adding `follow_path` as well gives 94.01%. They are not marks.

## 3. Outcome

**Marks: 6** (`targets/zopfli/jev-marks.txt`), union coverage 93.37% of
in-binary user cycles on the search set (per case 86.17% / 93.17% / 96.58%)
and 94.88% on the holdout (88.87% / 95.76% / 96.41%).

Skipped as entry glue (rule step 3): none; no such function reached the
ranking above the stop.

Removed by the existence gate (rule step 4): **`<zopfli::hash::HashThing>::update`**.
The first `scripts/target_sites.sh dump` with the seven selected names
resolved it in both pre-link modules (a function row in each) but the
post-LTO report, the only one whose loop stage ran, lists it in
`unmatched_marks` (no function of that name is left at that stage), so
`target_sites_report.py` (intersection over the reports whose loop stage
ran, the same rule as `jev_search.py`'s `unmatched_marks()`) reports it
**unmatched**. The driver's own hard resolution check (a function row in any
report, or a loop attributed to the mark) would have accepted it through its
pre-link function rows; the removal rests on rule step 4 as written. It was removed, the
walk was not continued, and `dump` / `allkeys` / `sites` were re-run with
the six remaining marks. Its removal changes the union by 0.00 points.
`get_best_lengths` and `lz77_optimal_run` have no post-LTO function either
but are not `unmatched`: loops are attributed to them through the inline
chain.

`allkeys` (every dumped key applied once): 42 keys, 37 `attached`, 5
`ambiguous+attached`, no `unmatched` or `vanished`; outputs match. The
ambiguous keys (a key naming more than one loop): `…-fetch_sublen-cache.rs-108`
with 8 copies, and four `…-update-hash.rs-150` keys with 2 copies each
(16 loops behind 5 keys). Recorded as counts (decision 64).

Holdout agreement check: the search-set top 10 and the holdout top 10 are
the same ten functions. Reach differs by more than 2 points for
`lz77_optimal` (40.53 vs 42.87), `get_best_lengths` and `lz77_optimal_run`
(39.82 vs 42.10 each); every other top-10 function is within 1.6 points.
No function is hot in one set only. `<zopfli::hash::ZopfliHash>::update`
and `HashThing::update` are about twice as hot on the binary case as on the
other two, in both sets.
