# jev-opt LLVM pass plugins

Two LLVM pass plugins, loaded into `rustc` with `-Zllvm-plugins=<abs path>`:

| plugin | source | what it is for |
|---|---|---|
| `libjevprobe.so` | `plugin/probe/probe.cpp` | measurement only. Registers a no-op logging pass on every PassBuilder extension point so the EP table can be produced from observation rather than from reading LLVM's source. |
| `libjevplugin.so` | `plugin/jev/jev.cpp` | the real one. Describes the loops inside marked functions (`dump`) and applies the hints Jev chose (`apply`). |

Neither links any LLVM library. They are `dlopen`'d by `rustc`, which is
already linked against `libLLVM.so.23.1-rust-1.100.0-nightly`, so every
`llvm::` symbol resolves out of that library at load time. Linking an LLVM
library in would register its `cl::opt` objects a second time and abort
inside `dlopen`.

## Build

```
scripts/fetch_llvm_headers.sh     # once: LLVM 23.1.1 headers, no LLVM built
scripts/build_plugin.sh           # -> plugin/build/libjev{probe,plugin}.so
scripts/build_plugin.sh probe     # just one of them
```

`fetch_llvm_headers.sh` downloads the `llvmorg-23.1.1` release tarball into
git-ignored `third_party/`, extracts `llvm/`, `cmake/`, `third-party/` and
`libc/`, configures with

```
-DLLVM_TARGETS_TO_BUILD=X86 -DLLVM_ENABLE_ASSERTIONS=OFF
-DLLVM_ABI_BREAKING_CHECKS=FORCE_OFF
```

and runs the tablegen targets that produce headers (`intrinsics_gen`,
`analysis_gen`, `vt_gen`, `target_parser_gen`, `omp_gen`, `acc_gen`,
`llvm_vcsrevision_h`). No LLVM library target is ever built.

Two traps, both found by failing:

* The CMake option is **`LLVM_ABI_BREAKING_CHECKS`**, not
  `LLVM_ENABLE_ABI_BREAKING_CHECKS` (which is the generated macro). Passing
  the latter puts the string `FORCE_OFF` in the cache, `#cmakedefine01` reads
  it as true, and the headers end up referencing
  `llvm::EnableABIBreakingChecks` — a symbol the host `libLLVM` does not
  define, because it was built with assertions off.
* `ninja intrinsics_gen` alone is not enough:
  `PassBuilder.h → CGSCCPassManager.h → LazyCallGraph.h → TargetLibraryInfo.h`
  needs `TargetLibraryInfo.inc`.

`build_plugin.sh` gates on this: every undefined `llvm::` symbol in the built
`.so` must be exported by the `libLLVM` that `rustc` loads. That check is what
catches an ABI-macro mismatch before `rustc` does.

Compile flags: `-fPIC -shared -fno-rtti -fno-exceptions -DNDEBUG -std=c++17`,
plus `-fvisibility=hidden` with an explicit `default` on
`llvmGetPassPluginInfo`, so the plugin can never interpose a `libLLVM` symbol.

## Extension points

Fixed by measurement (`scripts/plugin_ep_table.sh`, results.md "Day 3
(plugin)"), not assumed:

| what | extension point | when it fires |
|---|---|---|
| function attributes | `PipelineStartEP` | once per CGU, **pre-link only**. `buildLTODefaultPipeline` does not invoke it, so there is no merged-module second call. This is the only point before any inlining. |
| loop metadata | `VectorizerStartEP` | under fat LTO, only in the **merged** module; under `lto=off`, in the single per-CGU pipeline. Either way it is the last point at which a hint still reaches LoopVectorize. |

Stage detection: under fat LTO `rustc` reuses the primary CGU's module
identifier *and* its process for the merged module, so the stage cannot be
read off the module name. `FullLinkTimeOptimizationEarlyEP` is the marker —
everything after it, in that process for that module, is the merged stage.
Reports are therefore one file per `(module, stage, pid)` and the CLI merges
them (`scripts/plugin_report.py` is the part of that job the day-3 tests
need).

## Environment variables

| variable | modes | meaning |
|---|---|---|
| `JEV_MODE` | all | `off` (default) / `dump` / `apply` / `apply-dump` |
| `JEV_MARKS` | dump, apply-dump | path to `jev-marks.txt` |
| `JEV_PLAN` | apply, apply-dump | path to the plan JSON |
| `JEV_PLAN_SHA` | apply, apply-dump | sha256 of that file; a mismatch is fatal |
| `JEV_REPORT_DIR` | dump, apply, apply-dump | directory the reports are written to |

`off` registers **no callback at all**, so the pipeline `rustc` builds is the
one it builds with no plugin loaded. That is the off-equivalence gate of
SPEC.ja.md 8.2, and it is measured in results.md "Day 3 (plugin)" 5a.

`apply-dump` applies only the `fn_attrs` half of the plan, at
`PipelineStartEP`, and then dumps the loops out of the IR those attributes
produced. It exists because loop decisions have to be taken on the IR the
attribute decisions created: applying `inline(never)` to a function changes
that function's own loop keys (results.md 5f).

The plugin's own sha256 is checked against two known answers at startup
whenever the mode is not `off`. `JEV_PLAN_SHA` is the only thing between a
stale plan and a silently mis-hinted build.

## Marks file

One Rust path per line; blank lines ignored. `#` starts a comment **only
as the first non-space character of a line** --- it is not a mid-line
comment marker, because a demangled closure is spelled `{closure#3}` and
four of jaq's fifteen marks contain one.

```
# artifacts/plugin-day3/marks/toy-all.txt
toyloops::count_quotes
toyloops::find_special
```

Matching is against the **full demangled** v0 linkage name, generic
arguments included. A mark matches when the demangled path

* equals the mark, or
* continues with the mark + `::` — a monomorphization
  (`jaq_json::read::parse::<hifijson::SliceLexer>`), a closure
  (`toyloops::count_quotes::{closure#0}`) or any other inner item, or
* ends with `::` + the mark (the mark was written without its crate).

A generic mark therefore reaches every monomorphization of it, and
`jaq_json::read::parse` does not match `jaq_json::read::parse_string`. This
is the rule results.md "Marks (jaq)" section 85 states for
`targets/jaq/jev-marks.txt`.

An earlier version normalised both sides by deleting every balanced `<...>`
group first. That is wrong for a mark written in trait-impl form: it turns
`<jaq_json::Val as core::hash::Hash>::hash` into `hash`, which then matches
every `::hash` in the program. On jaq's 15 marks it collapsed eleven of them
to a bare method name, three of those to the same string, and one to a path
ending in `::` that could never match (results.md "Sites (jaq)"). That
normalisation survives only as the readable suffix of a site key, where a
collision is harmless.

Marks that matched nothing are listed in `unmatched_marks`, but only in
reports whose `loop_ep_ran` is true — under fat LTO the pre-link modules never
reach the loop extension point, so "unmatched there" means nothing. The field
is still per report: a mark that matched only in a pre-link function table
reads unmatched in the merged-LTO report, so the CLI has to take the
intersection across every report of a build before calling a mark unmatched.

A loop is related to a mark in one of two ways, and the dump says which:

* `loop_in_mark` — the loop's own source location, following the
  `DILocation → inlinedAt` chain, sits inside the marked function. This is
  "the loop in the function you marked".
* `mark_in_loop` — only the *body* reaches the mark: the marked function was
  inlined into a loop that belongs to a caller. On the toy this is the
  driver's `for _ in 0..repeats` loop.

## Plan schema (as implemented)

```json
{
  "schema_version": 1,
  "plan_id": "5c-loopmd",
  "fn_attrs": [
    {"fn": "toyloops::count_quotes", "inline": "never", "align": 64},
    {"fn": "toyloops::find_special", "cold": true}
  ],
  "loop_md": [
    {"key": "8d0b9cbf99f073bc--macros.rs-279", "stage": "lto",
     "vectorize_width": 8},
    {"key": "e46f821f746d117a-spec_next-range.rs-1103", "stage": "lto",
     "unroll_count": 4}
  ]
}
```

`fn_attrs` entry:

| field | type | meaning |
|---|---|---|
| `fn` | string | linkage name, or a Rust path matched like a mark |
| `inline` | `"hint"` / `"never"` / null | `inlinehint` / `noinline` |
| `cold` | bool | `cold` |
| `hot` | bool | `hot` (mutually exclusive with `cold`) |
| `align` | int / null | function alignment, power of two |

`inline` and `cold`/`hot` remove the opposing attribute first: the verifier
rejects a function that is both `noinline` and `inlinehint`.

A `fn` is matched by exactly the rule marks use (above), on the full
demangled name, so a **generic** function name reaches every
monomorphization and a function name reaches its closures. The attribute is
applied to all of them and the report also carries an `ambiguous` row saying
how many. `ambiguous` never means "nothing was applied", for either half. Decision 61 (c) settles the generic half of this.

Until results.md "Sites (jaq)" the `fn_attrs` matcher had a rule of its own
— equality or `::`-suffix over generics-stripped names, with no prefix case
— so a generic name reached no monomorphization and no closure. Unifying
the two moved one recorded toy key; that section says which.

`loop_md` entry:

| field | type | meaning |
|---|---|---|
| `key` | string | site key from a dump |
| `stage` | `"prelink"` / `"lto"` / absent | only apply in that stage |
| `unroll_count` | int | `llvm.loop.unroll.count` |
| `unroll_disable` | bool | `llvm.loop.unroll.disable` (one-operand node) |
| `vectorize_width` | int | `llvm.loop.vectorize.width` + `vectorize.enable` |
| `interleave_count` | int | `llvm.loop.interleave.count` |

`unroll_count` and `unroll_disable` are mutually exclusive. A malformed plan
is fatal, not a warning.

Anything applied also gets `!{!"jev.site", !"<key>"}` and `!{!"jev.applied"}`,
which is what makes a second visit idempotent.

## Site key

SPEC.ja.md 8.3: the first 16 hex digits of the sha256 of

1. `owner_fn` — `DISubprogram::getLinkageName()` of the function that finally
   contains the loop,
2. `inline_chain` — the `DILocation → inlinedAt` chain of the loop's own
   location, outer to inner,
3. `leaf` — the innermost frame's `(file, line, col)`,
4. `loop_fingerprint` — the sorted set of `(innermost linkage name, line)`
   over every instruction in the body,
5. `depth` — loop-tree depth,

followed by a readable suffix (`<leaf fn>-<file>-<line>`). Sorted, so
instruction scheduling between dump and apply cannot move the key.

A key that resolves to no loop is reported `vanished`. One that resolves to
several is reported `ambiguous` **and the hint is attached to every loop it
resolved to** --- `finalizeKeyOutcomes` folds the hit counts into the report
after the fact, it does not undo the attachments, so an `ambiguous` key
carries one `attached` row per copy as well. Neither outcome moves a hint to
a different loop, and the counts are the health metric for the design.

That matters on jaq, where 13 of the 127 `loop_in_mark` keys resolve to
between 2 and 9 loops each (results.md "Sites (jaq)"). A plan entry is
therefore an instruction about a *key*, not about a loop, and on those 13 it
hints every copy at once.

## Report schema

One file per `(module, stage, pid)`:

* `sites-<module>-<stage>-<pid>.json` for `dump` and `apply-dump`
* `apply-report-<module>-<stage>-<pid>.json` for `apply`

```json
{
  "schema_version": 1,
  "mode": "dump",
  "plan_id": "",
  "module_id": "toy.762c70952d143d6-cgu.0",
  "stage": "lto",
  "pid": 429989,
  "profile_summary": true,
  "loop_ep_ran": true,
  "unmatched_marks": [],
  "functions": [
    {"linkage": "_RNvCs..._8toyloops12count_quotes",
     "demangled": "toyloops::count_quotes",
     "mark": "toyloops::count_quotes",
     "inst_count": 16, "entry_count": 1400,
     "attributes": "noinline,align=64", "self_loops": 1}
  ],
  "sites": [
    {"key": "...", "mark": "...", "marks_in_chain": ["..."],
     "match": "loop_in_mark",
     "owner_fn": "...", "owner_fn_demangled": "toy::main",
     "inline_chain": ["..."],
     "leaf": {"file": "...", "line": 279, "col": 24},
     "depth": 2, "already_vectorized": false, "jev_applied": false,
     "trip_count": 1047827.695, "header_count": 1468006600,
     "body_inst_count": 10, "hotness": 14680066000,
     "has_calls": false, "has_fp_reduction": false}
  ]
}
```

`apply` reports carry `results` instead:

```json
{"key": "...", "outcome": "attached", "owner_fn": "...",
 "leaf": {...}, "attached": "vectorize.width=8"}
{"fn": "toyloops::count_quotes", "outcome": "consumed",
 "linkage": "...", "demangled": "...", "attached": "noinline,align=64"}
```

Outcomes: `attached` / `consumed` (the hint went in), `already_vectorized`,
`skipped_idempotent`, `skipped_empty`, `vanished`, `ambiguous`, `unmatched`.

`unmatched` is per module and must be merged before it means anything: a
`fn_attrs` entry naming a function of one crate is legitimately unmatched in
every other module. `scripts/plugin_report.py apply <dir>` does that merge.

`trip_count` is the profile estimate of decision 36: exits = header count −
back-edge count, average trip = header count / exits. It is `null` without a
profile. `hotness` is `header count × body instruction count`.

`profile_summary` is latched, not sampled: `PGOInstrumentationUse` attaches
the summary partway through the pre-link pipeline, so it is **false** at
`PipelineStartEP` even with `-Cprofile-use`. SPEC.ja.md 8.2 says to abort when
the summary is missing; that rule cannot be applied at the function-attribute
extension point.

## Fixed rustc flag

`-Cllvm-args=-hints-allow-reordering=false` is pinned for every arm.
`LoopVectorizeHints` cannot tell a `vectorize.width` hint from the
command-line option, so without it a width hint on an FP reduction also
authorises reordering the additions and the program's answer changes. Measured
in results.md "Day 3 (plugin)" 5c.
