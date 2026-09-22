# `scripts/jev_search.py` --- the hint search driver

The loop of SPEC.ja.md 1(3), as a Python script (decision 62): resolve the
marks, enumerate the sites, ask a proposer for one hint per site, write a
plan, build, check the output, measure, feed the result back, repeat, keep
the best plan. `--proposer jev|random|oracle` switches the arm.

Nothing here owns anything that already exists somewhere else:

| what | who owns it |
|---|---|
| build recipe, workloads, pinned core, settle gap, per-case output hashes | `scripts/target_common.sh` |
| interleaved timing, paired bootstrap, noise floor, MDE | `scripts/bench.py` |
| reading the plugin's per-module reports | `scripts/plugin_report.py` |
| normalised per-symbol code comparison | `scripts/norm_code_diff.py` |
| the hint vocabulary and the wording Jev sees for it | `scripts/jev_vocab.py` |
| rounds, caps, Jev endpoint, repetitions | `jev-opt.toml` |

Python 3 standard library only; `requests` is not installed, so the HTTP
client is `urllib`. The API key comes from `AI_GATEWAY_API_KEY` in the
environment or from `.env`, and is never written to either log.

## Usage

```
scripts/jev_search.py --target jaq \
    --marks targets/jaq/jev-marks.txt \
    --sites targets/jaq/sites.json \
    --proposer jev --rounds 5 \
    --out artifacts/jaq-search/2026-09-22-jev-1/
```

Useful flags:

```
--vocab v1|v2|v3    the frozen vocabulary AND state template. v3 is the
                    default (decision 77); v2 is decision 73's W7; v1 is
                    what Experiment 3 was run with. See "The state format"
                    below
--readout           forced_top1 (default) or argmax: how a phase's answers
                    become plan entries (decision 71). See "The proposers"
--source-comments   strip (default) or keep: whether the source excerpts in
                    the state are stripped of comments and doc attributes
                    (decision 81). See "Source excerpts" below
--site-set PATH     the frozen loop-site key list inside sites.json, e.g.
                    oracle.selected_keys_top3. All three proposers must be
                    given the same one (SPEC.ja.md 2)
--fn-attr-scope     own (default) or all; see "Sites" below
--oracle-phase      A, B or all (default): restrict the oracle's arm list
                    to the function-attribute sweep, the loop sweep or
                    both. A round still builds both phases
--dry-run           list the sites (or the oracle's arms) and stop
--print-state       print the round-1 state of both phases and stop; no HTTP
--n N --warmup W    bench.py --runs / --warmup for the rounds
--bench-set         training (default, SPEC.ja.md 7) or holdout
--baseline-dir DIR  reuse a baseline another run already built
--resume            continue an interrupted run from its rounds.jsonl
--measure-holdout   after the rounds, measure the best plan once on holdout
--smoke             mark every artifact of the run as a smoke test
--keep-binaries all keep every round's binary, not only the accepted ones
```

`--rounds` is ignored for the oracle, whose arm count is determined by the
site and candidate lists.

## A round is two builds

A loop's site key is a hash of the inlining result, so changing a function
attribute changes (or deletes) the loop keys inside that function
(SPEC.ja.md 8.4, decision 61). Choosing both in one shot is therefore not
possible, and a round does this instead:

```
phase A   one Choice per marked function (+ the __build__ pseudo-site)
          -> plan-a.json: fn_attrs only
          -> build with JEV_MODE=apply-dump
             (attributes applied at PipelineStartEP, then the loops of the
              resulting IR are dumped)
phase B   one Choice per refreshed loop_in_mark site
          -> plan-b.json: the same fn_attrs + loop_md
          -> build with JEV_MODE=apply
          -> correctness: run_correctness's output, line for line, vs the
             baseline's
          -> timing: bench.py, cand vs base vs an in-run A/A copy of base
```

`plan-b.json` carries `basis`, the sha256 of the attribute set the dump its
loop keys came from was taken under, and the driver checks it before
building. SPEC.ja.md 8.4 asks the *plugin* to enforce this; the plugin as
built ignores unknown plan fields and never reads `basis`, so the check is
the driver's --- and within one round it is a tautology, since the same
attribute set wrote both plans. It bites on `--resume` and on a hand-edited
plan. `jev_site_id`, `jev_choice` and `answer_ref` ride along in each
plan entry for the same reason --- they are for the record, not for the
plugin, and the toy smoke run confirmed the plugin tolerates them.

Only sites the proposer did not leave at `KEEP_DEFAULT` become plan entries.
An all-`KEEP_DEFAULT` round therefore writes an empty plan, which is the
build whose off-equivalence results.md "Day 3 (plugin)" 5a measured: it is
the in-sweep null arm of SPEC.ja.md 7, not a failure.

## Sites

* **function sites** come from the dump's function table, which the plugin
  emits only for marked functions. A generic mark appears once per
  monomorphization; one Choice covers the mark and the plan gets one entry
  per resolved **linkage name** (decision 61c). Naming linkage names rather
  than the Rust path is exact: `JevApplyFnAttrs` matches `F.getName()` first,
  so nothing else can match by accident.
  **Inner items are excluded from the fan-out.** The plugin's mark rule
  reaches `::{closure#N}` and other inner items on purpose, so that a loop
  inside a closure is attributed to the marked function. A function
  attribute must not follow it there: `inline(never)` on a mark is a
  statement about that function, and putting `noinline` on every closure it
  defines would also stop LLVM inlining those closures into the mark's own
  loops --- a different intervention from the one the human asked for. The
  excluded names are recorded per round in `fn_fanout`, and
  `--fn-attr-scope all` restores the plugin's own reach. The spec does not
  settle this; this is the driver's choice.
  Telling the two apart is not "does the name contain `::{`": since the
  plugin reports the full demangled name, a monomorphization's generic
  arguments routinely contain a closure path. What separates them is the
  suffix *after the mark* --- `::<...>` is a monomorphization, `::{closure#0}`
  or `::helper` is an item defined inside it. It is not the single character
  after the mark either, which is what the rule read until decision 80 (c):
  for a **generic** mark that character is the `<` of the generic arguments,
  so `read::parse::<SliceLexer>::{closure#0}` passed as a monomorphization
  and one Choice about `read::parse` put its attribute on every closure the
  function defines. The rule skips the balanced `::<...>` group first and
  asks what follows *it*. Measured on the recorded dumps: a full phase-A
  plan on jaq falls from **138 entries to 49** (`read::parse` 18 -> 6,
  `TermId::run` 62 -> 2, `path::run` 12 -> 3, `Val::hash` 12 -> 4) and
  hintbench, whose eight marks are non-generic, stays at 8. Everything
  measured on jaq before that (Experiment 3, oracle A) used the old reach,
  and results.md "Oracle A (jaq)" 112 says so.
* **loop sites** are the `loop_in_mark` records only. `mark_in_loop` --- the
  caller's loop around an inlined copy of a marked function --- is excluded
  (decision 61a).
* a mark that resolves to **neither** a function nor a loop stops the run
  (SPEC.ja.md 1(1)). A mark that resolves to a loop but not to a function is
  legal and gets only a loop question: the toy's `sum_indexed` is one, MIR
  inlined it away before the plugin ever sees the module.
* `[search] max_sites` counts both phases and is a hard error. `--site-set`
  is how a run stays under it on jaq: `targets/jaq/sites.json` carries the
  pre-registered mechanical rule (drop the keys the training profile never
  entered, drop trip count < 2, keep the top 3 by hotness per mark) and the
  16 keys it selects, which with the 15 marks makes 31 questions a round.
  All three proposers take the same list, which is what makes them
  comparable.
* **a site key is not always one loop.** On jaq 13 of 127 keys resolve to
  2--9 loops; the plugin attaches the hint to every copy and reports the key
  `ambiguous` as well. A plan entry is an instruction about a key, so such an
  arm moves several loops at once and cannot separate them. That is counted
  per round (`n_ambiguous`), shown in `summary.md`, and is **not** a failure.
  `vanished`, `unmatched` and `skipped_empty` are failures.

`site_id` --- `<mark>@<file>:<line>:<col>#d<depth>` --- is a coarser identity
than the site key, and is what round-to-round history and the oracle's
"best per site" are keyed on, because the key itself moves whenever the
attributes move. The key is still the only thing a plan ever names.

## The acceptance rule (pre-registered)

A round becomes the best so far **only if all three hold**:

1. its output matches the baseline on every case, byte for byte:
   `run_correctness` from `target_common.sh` writes one line per case
   (`name sha256` on jaq, zopfli and oxipng; the toy's own checksum block on
   the toy) and the whole output is compared line for line, so the gate does
   not depend on any target's line shape;
2. every plan entry took effect --- no `unmatched`, `vanished` or
   `skipped_empty` in the merged apply report (merged over modules, as
   `plugin_report.py apply` does: an entry naming a function of one crate is
   legitimately unmatched in every other module). `ambiguous` is counted,
   not failed;
3. the **lower end of its 95% CI is above the best point estimate so far**.
   The baseline is the first best, at ratio 1.0000.
4. **the interval that did that survives a second, independent batch**
   (decision 80 a): the same two binaries, the same conditions, a fresh
   shuffle seed, and both batches' intervals excluding 1 with the same sign.

Rule 3 is deliberately conservative: it never promotes a plan whose interval
merely overlaps the incumbent. Rule 4 exists because at the frozen `n` rule 3
is not conservative *enough*: over jaq's 90-arm oracle the in-run A/A
interval --- an interval around a second copy of the baseline --- failed to
cover 1.0 **49 times in 90**, and 20 of the 48 arms whose binary was provably
the baseline's also excluded it (results.md "Oracle A (jaq)" 113, 116). Three
arms were accepted under rule 3 alone and the holdout reversed all three. A
round that fails 1 or 2 is recorded with the failure and is not measured
further.

`--ignore-apply-failures` relaxes rule 2 for debugging and
`--no-confirm-batch` drops rule 4; the outcome is recorded either way.

### No-op arms are not measured (decision 80 b)

After the phase-B build and the correctness check, every arm's binary is
classified against the baseline's by **normalised instruction sequence**
(`norm_code_diff.py`: any hex literal of four or more digits becomes `A`, per
symbol) **and symbol table** (`nm -S`, addresses and sizes), and the class is
recorded as `code_class` in the round record:

| `code_class` | meaning | timed? |
|---|---|---|
| `identical` | same instructions, same symbol table | **no** --- `status: identical_to_baseline`, `ratio: 1.0` by construction, `ci95: null` |
| `layout` | same instructions, symbols moved | yes --- this is what `align=N` does when it works |
| `code` | at least one symbol's instructions changed | yes |

The plugin cannot supply this: it has no `skipped_idempotent` verdict for a
function attribute, so an attribute it set is reported `consumed` whether or
not LLVM then did anything with it. The no-op count comes from the binaries.
`--no-noop-skip` times such an arm anyway; the classification is recorded
either way.

## Measurement

Per round, in `round-NN/`:

* the candidate binary is copied out unstripped (for `norm_code_diff.py`) and
  three stripped copies are made for timing: `base`, `cand` and `aa`, the
  last a second copy of the baseline binary, which is the in-run A/A of
  SPEC.ja.md 2.
* `bench.py run --shuffle <seed+round> --gap-ms <target's> --cpu <target's>
  --runs <n> --warmup <w> --stdout <target's>`; the CPU, the gap and the
  stdout policy come from `target_common.sh`, so jaq gets CPU 4, 250 ms and
  `devnull` without this script naming them.
* `bench.py stats --base base` gives the aggregate speed ratio, its 95% CI
  from the paired bootstrap, and the MDE.
* search rounds use the **training** case set. The holdout is measured once,
  after the best plan is frozen, and only when `--measure-holdout` is given
  (SPEC.ja.md 7). A target with no training case set (the toy) falls back to
  its single set and every artifact says `case_set: holdout-as-search`.
* when **no round was accepted**, the holdout still runs, with the baseline
  itself as `cand` and `"null_arm": true` in `holdout.json`. It is not a
  candidate: it is SPEC.ja.md 7's in-sweep null panel on the holdout set, and
  it is the only way to get that set's A/A half-width and MDE out of a run
  that accepted nothing (results.md "Experiment 3 (jaq)" 102). The
  acceptance rule is untouched.
* each round record carries `wall_s`, written at the call site in `run()`
  because `one_round` has six early returns. Nothing reads it back.

## The state format (frozen)

Decision 19: what the state says changes the answer, so the format is frozen
like a measurement condition. It is `STATE_FORMAT_VERSION` in
`jev_search.py`, `VOCAB_VERSION` in `jev_vocab.py`, and both are written into
every request log line, every plan and the run manifest, as is
`source_comments` (below). `--print-state`
prints the whole thing --- the state of both phases **and** every question,
with its instructions and its `criteria` --- without making a request.

There are three of them, and `--vocab` selects both halves at once, because
the wording and the template are one measurement condition and the prompt
study measured them together. v3 is the default; it is v2 with a different
set of function candidates and is described in its own section below.

| | v1 (`state-v1-2026-09-22`, `v1-2026-09-22`) | v2 (`state-v2-2026-09-22`, `v2-2026-09-22`) |
|---|---|---|
| question | "Which attribute should the build put on it? Pick KEEP_DEFAULT unless there is a reason..." | "Which single hint from the list is most likely to make this function faster on this workload?" |
| `KEEP_DEFAULT` | "Leave this function's attributes exactly as they are" | "This is the 'no change' option ... exactly as in the baseline" |
| function `criteria` | mechanism only | mechanism **plus applicability**: where the hint tends to help, where it tends to hurt, where it is a no-op |
| loop `criteria` | mechanism only | the same v1 text, with the neutral `KEEP_DEFAULT` |
| per question | nothing | the **verdict block** (below) |
| per state | -- | the **platform block** (below) and the V2 wording of "What is being decided" |

v2 is the prompt study's `W7` (decision 73,
`docs/experiments/jev-prompt-study/` "Round 2"): 8 of 9 of Claude's
reference picks, identical in all three repeats, 24/27 --- the only framing
in 25 that beat "answer `KEEP_DEFAULT` at every site". The two halves are
deliberately **not** symmetric: the applicability text goes on the function
phase only, because W1 against W3 measured that the same text on the loop
phase costs the one loop pick that has a mechanism
(`vectorize.width=16` becomes `unroll.count=4`). Functions and loops are
separate HTTP requests, so the asymmetry costs nothing.

Everything else about a section --- the marks table, the round history, the
source excerpts, the baseline remarks --- is v1's material unchanged. V3
measured what removing it costs: the vectorize-family probability mass at
the loops LLVM reports as impossible to vectorize rises from 0.02--0.11 to
0.23--0.44 when the remarks go away. The remarks are the one input the study
could show Jev reads, and they stay.

### The verdict block

Each question's `instructions` carry, after the question itself, a block of
mechanical readings of that site. They are produced by one rule applied to
every site of the request; no site is special-cased, none of them names a
site, and none of them says which hint to pick. They state as a finished
reading what the state already carries as numbers --- which is what moved
the answer: the study's V7 and V8 gave Jev the register width and the trip
count as a table and changed no answer at all, while W1 stated the join
(`u8` -> one register holds 32 -> the widest width in this list that fits is
16) and got `vectorize.width=16` in every repeat.

Placement is not incidental. The same mechanism text in a state section
(round 1's V11 hint guide) produced 100% `KEEP_DEFAULT`; attached to the
question and to the options being chosen between, it discriminates. That is
finding 2b of round 2.

| reading | rule |
|---|---|
| size class | `<50` tiny, `<300` small, `<1000` medium, `<2000` large, `>=2000` very large |
| copy class | 1 single, 2--8 few, `>=9` many (monomorphizations resolved by the dump) |
| trip class | `<2` degenerate, `<16` short, `<100` medium, `>=100` long |
| hotness class | `<1%` not hot, 1--5% hot, `>=5%` very hot (the mark's own profile share, `reach` when it has no symbol of its own) |
| inline budget | LLVM's own `-inline-threshold=225` / `-inlinehint-threshold=325`; the line prints body instructions over whichever applies to the attributes the function already carries, and says in the same breath that it is an order-of-magnitude comparison and not an `InlineCost` computation --- the state's own remarks carry real `cost=/threshold=` pairs, and they are about this function's *callees* |
| lanes | `<register width> / <element bit width>`; the element type is the innermost `Iter<...>` of the recorded inline chain, demangled with `llvm-cxxfilt`, and the line says *not derivable* where the chain carries none (a loop over format pieces, say) rather than guessing one. An element as wide as the register says so instead of naming a width |
| legality | `loop not vectorized: <reason>` whose reason is an early exit / unsupported switch / bad successor count / unidentifiable induction variable / undeterminable trip count / non-reduction used outside the loop. `runtime pointer checks needed` is **not** counted as a legality failure. No remarks recorded at the location prints `UNKNOWN`, not "legal" |
| loops per key | the dump record does not carry it, so it is the `key_copies` of `sites.json` where the key is one that file recorded, and "not recorded for this key" otherwise --- never a silent 1, since 13 of jaq's 127 keys name 2--9 loops |
| no-op check | a candidate that reproduces what the site already carries: `inline` where the attributes already include `inlinehint` (and whether that is every copy or some), `cold` where `cold` is already there, `vectorize_width_N` where a remark already reports `vectorized loop (vectorization width: N)` |

The thresholds and the phrasings are the study's, copied from
`scripts/jev_state_variants.py` where they were pre-registered. The remark
window is the same one the section prints (+-10 lines for a loop), so no
line of the block can cite something the reader cannot see.

### The platform block

`lscpu`, `/sys/devices/system/cpu/cpu0/cache` and the `-target-cpu` that
`-march=native` resolves to, read **once per run** and cached in the run
directory as `platform.json` (both the raw readings and the rendered text).
The vector width comes from the ISA flags (AVX-512 -> 512, AVX/AVX2 -> 256,
otherwise 128) and is what the lanes arithmetic above divides. Nothing is
corrected: this is a WSL2 guest, decision 17 recorded that the two CCDs of
the physical part are not visible from inside it, and the block says the
cache figures are the guest-visible ones. On its own the block changed no
answer in the study (V7 reproduces V2 at all nine sites); it is there
because the lanes line refers to the register width and should not be the
only place that number appears.

### Source excerpts: `--source-comments`

Every function section quotes a +/-40-line window of the site's own source,
and every loop section quotes its marked function's. `--source-comments`
decides whether the comments inside that window are quoted with it.

* `strip` (the **default** since decision 81): every comment --- `//`,
  `///`, `//!`, `/* */`, which nests --- and every `#[doc = ...]` attribute
  is removed from the file before the window is cut. A line that held
  nothing else is rendered as `// [comment removed]`, a trailing comment is
  cut and its code kept, and a blank line stays blank, so the window has one
  printed line per source line and the numbers and the `>` marker point
  where they did. The same strip runs over the remark quote lines, which in
  practice carry no source text. It is a lexer, not a regex: `//` inside
  `b'"'`, `'\''` or `r#"http://x"#` is not a comment.
* `keep`: quote the file verbatim. This is what every run before
  2026-09-22 did, and it is how to reproduce one.

**No source file is edited for this.** Editing one would move the line
numbers the site keys and the profile are built from (decision 61), which is
why the filter lives in the driver.

Why it is the default: the hintbench kernels document their own benchmark,
and their comments name the hint each kernel exists to exercise ("the hint
under test is `inline(never)`") and spell out its mechanism. Under `keep`
that text is inside the windows the state quotes, and
`docs/experiments/hintbench/jev-oneshot-v3.md` measures what it was worth:
one-shot agreement with `targets/hintbench/EXPECTED.md` falls from **10 of
12 sites to 7 of 12** when the comments are stripped and nothing else
changes, the two non-KEEP hints the comments named disappear, and the
decision-71 readout stops ranking Claude's predicted winner first. Any
target whose sources discuss its own optimisation --- which is most of them,
at the lines the hot loops live on --- can leak the same way.

The mode is recorded in the state header (`source  source_comments: ...`),
on every JSONL request line and in `run-manifest.json`. The state format
string is **not** bumped for it: `state-v3-2026-09-22` renders one extra
header line, and that line is the disambiguator between a `keep` run and a
`strip` run. It is added to **all three** templates, v1 and v2 included: a
state without that line was rendered before the option existed and is a
`keep` state, so the line, not the date, is what tells the two conditions
apart.

### v2 is frozen

`v2-2026-09-22` / `state-v2-2026-09-22` were frozen at commit `ac94c8a`.
Changing any of it --- a threshold, a description, the question wording, a
verdict line --- makes the runs before and after incomparable, exactly as
decision 19 says, and requires re-running whatever is being compared.
`--vocab v1` is kept so that Experiment 3's condition can be reproduced;
the v1 state that this driver renders is unchanged by the v2 work.

One later change reaches all three templates: since commit `b955338` the
build block carries a `source  source_comments: ...` line and the excerpts
are stripped of comments by default (see "Source excerpts" above). So
reproducing a pre-2026-09-22 state needs `--source-comments keep`, which
restores the excerpts; the header line stays either way. Decision 19 applies
to it as to everything else here --- a `strip` run and a `keep` run are two
conditions, not one --- and
`docs/experiments/hintbench/jev-oneshot-v3.md` measures how far apart they
are on one target.

One correction rides in v2 and in v2 only: the per-function line "N loop(s)
inside it" was always printing 0, because it summed a dump field the plugin
does not emit (it writes `n_loops`). v2 prints the mark's `loop_in_mark`
site count from the dump instead --- the same number the marks table and the
verdict block use, so one request cannot contradict itself. The v1 line is
left exactly as Experiment 3 sent it.

### v3 (the default): the function candidates that survive the profile

`v3-2026-09-22` / `state-v3-2026-09-22`, decision 77. v3 is v2 with three
changes, all in the **function** phase. The loop phase --- candidates,
descriptions, verdict lines --- is v2's, byte for byte, so a v2/v3
difference at a loop site cannot come from the vocabulary.

| | v2 | v3 |
|---|---|---|
| function candidates | `KEEP_DEFAULT`, `inline`, `inline_never`, `cold`, `align_16/32/64` | `KEEP_DEFAULT`, **`inline_always`**, `inline_never`, `align_16/32/64` |
| plan fragment of the new one | -- | `{"inline": "always"}` → `alwaysinline` |
| function `criteria` | applicability text on all six | applicability text on the two inlining candidates; v1's plain text on the three alignments |
| verdict block | the `inline` / `cold` no-op checks | one generic line on the inliner's mechanics (below) |
| arms per function site (oracle) | 6 | **5** |

Why: `docs/experiments/hintbench/inline-attrs-under-pgo.md` reads LLVM
23.1.1 and finds that under this recipe --- `-Copt-level=3`,
`-Cprofile-use`, fat LTO --- `inlinehint` is read
(`InlineCost.cpp:2137`) and then discarded by the assignment at `:2154`
that gives a hot or locally hot call site its own threshold, and that the
only arm reading the callee's `cold` (`:2163-2179`) is unreachable once the
call site has been classified at all. `alwaysinline` (`:3209`) and
`noinline` (`:3242`) are decided by `getAttributeBasedInliningDecision`
before the cost analyser is constructed, so the profile cannot touch them.
`hot` is **not** added in their place: it does not appear in
`InlineCost.cpp` at all and no Rust attribute produces it.

The verdict block's function half therefore loses the two no-op checks that
referred to the departed candidates and gains one line, the same at every
site, naming no site:

```
  - inliner mechanics of this recipe: with a profile present, `inlinehint`
    and `cold` on a function do not change the inliner's threshold for it,
    because the call site's own hotness class assigns that threshold
    afterwards; `alwaysinline` and `noinline` are decided before the cost
    model runs and are always honoured
```

It is there because the attribute list of a site can still *say*
`inlinehint` or `cold` --- `PGOInstrumentationUse` stamps both, after the
plugin has run --- and without that line those words read as evidence about
the inliner's threshold, which under a profile they are not.

**What this means for the earlier results.** Experiment 3 (decision 66) and
the prompt study (decisions 70, 73) were run with v1 and v2, whose function
list contained two candidates that cannot change a decision in this recipe.
`inline` was the hint Jev reached for most often in round 1, so the
agreement and disagreement figures of those runs are partly figures about
*inert* candidates and have to be read that way. Nothing in them is
retracted: the reference picks of `inline(never)` stand, the plans were
applied and measured as recorded, and the `--vocab v1` / `--vocab v2` paths
still render those conditions exactly. Decision 77 is that the comparison is
taken again under v3.

The plugin accepts `inline: "hint"` and `cold: true` for exactly that
replay; only the vocabulary stops offering them.

`v3-2026-09-22` / `state-v3-2026-09-22` are frozen at commit `7fe1a92`, on
the same terms as v2 above.

**`--resume` does not carry the vocabulary.** A resumed run reads
`rounds.jsonl` for the rounds already recorded and skips that many arms **by
position**, not by `(site, candidate)`; the vocabulary comes from `--vocab`
(now v3) every time. So a run started under v1 or v2 must be resumed with
that same `--vocab` spelled out, or the arms will silently realign onto a
list of a different length and composition. Each round records its own
`vocab_version`, which is where to check what a run was started with.

The API takes one `state` string and N questions, so the per-site material
lives in the state, one section per question, named after the question:

```
# jev-opt hint search --- state format state-v1-..., vocabulary v1-...
## What is being decided          what varies, what is measured, that
                                  KEEP_DEFAULT reproduces the baseline
## The build every arm shares     target, toolchain, machine, recipe, cases,
                                  repetitions, definition of the speed ratio,
                                  `source_comments`
## Where the hints are applied    PipelineStartEP / VectorizerStartEP
## The marked functions           one line each: share, loop-site count
## Results of the previous rounds round | correct | ratio | CI | accepted
## The sites in this request
### q0
site kind      one marked function (function attribute)
function       <mark>
profile share  <share> of the program's user cycles
size after LTO <n> LLVM instructions, <n> loop(s) inside it
attributes now <current LLVM attributes>
source:        <file:line, +-40 lines, the site's line marked `>`, comments
               stripped unless --source-comments keep>
what LLVM said about this region in the baseline build: <remarks>
  what earlier rounds chose here: <round, hint, whole-build ratio>
### q1
site kind      one loop inside a marked function
marked function / owner after inlining / location / profile share /
average trip count / body instructions, calls, FP reduction /
already vectorized / function attributes this round already applied
source of the marked function this loop belongs to: <+-40 lines>
source at the loop's innermost location: <+-20 lines, when it differs>
what LLVM said about this region in the baseline build: <remarks>
  what earlier rounds chose here: ...
```

Two notes on the source excerpts. The dump carries a source location for
loops but not for functions, so a mark's own source is found in three steps:
`nm` plus `addr2line` on the baseline binary, which is exact and is why
SPEC.ja.md 3 pins `-Cdebuginfo=1` and `strip=none`; then a definition search
(`fn <last identifier>`, scored by how many of the mark's identifiers the
file path repeats) over the vendored tree and the registry crates
Cargo.lock pins; then the leaf location of one of the mark's loops. When all
three fail the state says "source:" and nothing, rather than guessing --- a
path that resolves to a file shorter than the recorded line is treated as
not resolved. And a loop's `leaf` location is usually inside core's iterator
machinery (`range.rs`, `macros.rs`), not in the marked function, which is
why both excerpts are shown and the state says which is which.

`criteria` is an object (decision 19; an array is `invalid_request`), the
candidate ids are the keys, and the descriptions are the frozen ones in
`jev_vocab.py`. A round is one HTTP request per phase; the state is split
into several only when it would exceed `[search] max_state_chars`, and the
split is recorded as phase `A.1`, `B.1`, ... in the logs.

An answer is replaced by `KEEP_DEFAULT`, with the reason recorded, when the
request failed, when the answer is not one of the candidates, or when its
confidence is below `[jev] min_confidence` (0 by default: SPEC.ja.md 6 asks
for a threshold but fixes no value).

## The proposers

* **jev** --- one request per phase, still one, under v2 and v3 as under
  v1.
  Everything is logged twice: the raw request and response as JSONL
  (`jev-log/<run-id>.jsonl`, one line per request, no `Authorization` ---
  the `request` object holds the **full rendered state** and every question,
  so what was asked is recoverable from the log alone), and one
  human-readable line per request plus a totals block (`<run-id>.log`:
  requests, questions, latency, tokens, cost, and the share of the run's
  wall clock spent waiting for Jev).

  **The readout (decision 71).** The argmax alone throws the probabilities
  away, and Experiment 3 spent five rounds answering `KEEP_DEFAULT`
  everywhere: an empty plan, a rebuilt baseline, nothing measured, nothing
  learned. After each phase the driver therefore ranks the sites by
  `1 - P(KEEP_DEFAULT)` and records the whole ranking (`phase_a.readout`,
  `phase_b.readout` in `rounds.jsonl`: the rule, the ranking with each
  site's best non-`KEEP_DEFAULT` candidate and its probability, and whether
  a pick was forced).

  * `--readout forced_top1` (the default): the argmax everywhere, except
    that a phase whose every answer is `KEEP_DEFAULT` still applies **one**
    hint --- the top-ranked site's own highest-probability non-`KEEP`
    candidate. Each plan entry records which it was, as `jev_readout:
    argmax | forced_top1`, and the site's `why` entry keeps the argmax it
    replaced together with the probabilities it was chosen from.
  * `--readout argmax`: the old behaviour. Such a phase stays empty; the
    ranking is recorded all the same.

  Two details of the rule, both deliberate. The `__build__` pseudo-site is
  not ranked and is never forced: one build-wide compiler flag is not "one
  entry at one site". And a site whose answer was thrown away by
  `[jev] min_confidence` is not eligible either --- the gate said the answer
  is not worth acting on. This is not a better search, it is a search that
  moves; whether the hint it tries is worth anything is the oracle's
  question. Under `W7` the study's ranking would have tried
  `inline(never)` at `TermId::run` first and `vectorize.width=16` at the
  byte loop third, both of which are reference picks.
* **random** --- uniform over the same candidate list, same sites, same
  number of rounds, seeded from `[evaluation] seed` and the round number.
* **oracle** --- the arms of SPEC.ja.md 2: every candidate alone at every
  site with everything else `KEEP_DEFAULT`, then one arm combining the
  per-site winners. A winner joins the combination only if its own arm was
  **confirmed** --- its interval excluded 1 with the same sign in two
  independent batches (rule 4 above) --- and the two weaker rules this
  replaces are recorded beside the chosen set in the arm record, as
  `one_batch_rule_would_pick` (the CI lower bound of one batch, which is
  what jaq's oracle A used) and `point_rule_would_pick`. On jaq the
  one-batch rule combined twelve marks whose claims multiplied to +22.4%
  and delivered +2.15%, with an in-run A/A of +2.26% in the same batch.

  The winner is ranked on the **per-site readout** where the target has
  one: a target with one workload per site (`targets/hintbench`, one kernel
  per hint) is read on that site's own workload, because results.md "Hint
  benchmark (design)" 103 froze it and because a 10% win on one of eight
  kernels is 1.2% of the geometric mean. `own_workload_of` recognises a
  `kN_` site name against a workload called `kN` and returns nothing
  anywhere else, so on jaq, zopfli and oxipng the aggregate is still what
  ranks a site. Both numbers are in every round record.

  `--oracle-phase A|B` runs one half of the
  sweep, so that jaq's 75 function-attribute arms and its 176 loop arms can
  be separate jobs; the rounds are unchanged by it. The combination is applied through the normal two-phase
  round, so its loop choices are remapped from `site_id` onto whatever keys
  the combined attributes produce. Build count is
  `sum(sites x candidates) + 1 + 1`, which is why `max_sites` is a hard
  error; `--dry-run` prints the arm list without building anything.

`sites.json` (`--sites`) is optional and only ever adds information: profile
shares and source locations per mark, notes and per-site candidate
allowlists, and `search.max_sites`. Unknown keys are ignored, and a plugin
report directory is also accepted in its place.

## Files a run writes

```
<out>/
  baseline/            bin, correctness.txt, reports/ (the JEV_MODE=dump
                       build: the baseline binary and sites.json in one
                       build, SPEC.ja.md 8.2), build.log, baseline.json
  round-NN/
    plan-a.json plan-b.json     the two plans, with basis and answer_ref
    build-a.log build-b.log     the full build logs (remarks included)
    rep-a/ rep-b/               the plugin's per-module reports
    bin                         unstripped, kept only if the round is accepted
    timing/{base,cand,aa}       stripped copies, what bench.py timed
    samples.json stats.json stats.md
    correctness.txt
  platform.json        the machine as lscpu and the cache sysfs report it,
                       read once and reused for every request of the run
                       (state v2 and v3 only)
    confirm/                    the second, independent batch of rule 4:
                                its own timing/, samples.json, stats.json
  rounds.jsonl         one line per round: plans, apply outcomes, correctness,
                       `code_class` and the changed symbols, ratio, CI,
                       in-run A/A, the own-workload readout (`kernel`), the
                       confirmation batch (`confirm`) and its verdict
                       (`confirmed`, `confirmed_aggregate`), accepted, and
                       the readout ranking of each phase
  best-plan.json       a copy of the accepted round's plan-b.json
  summary.md           the table above, in markdown
  run-manifest.json    toolchain, lscpu -e, pinned core, sha256 of the
                       config, marks, plugin, profdata and baseline binary,
                       the case set, the Jev totals
  jev-log/<run-id>.{jsonl,log}
  holdout/             only with --measure-holdout
```

`artifacts/` is git-ignored: a run's output is evidence for `results.md`, not
a tracked artifact.

## Known limits

* `basis` is checked by the driver, not by the plugin, and within one round
  the check is a tautology (above).
* A function attribute goes on the mark's own functions only, never on the
  closures defined inside it (above). Loop attribution is unaffected: a loop
  inside such a closure is still a site of the mark.
* The function-source search is a heuristic, and a mark whose definition is
  outside the vendored tree gets no source excerpt at all.
* **A source window can still leak.** `--source-comments strip` removes
  comments; it does not remove an identifier, a string literal or a
  `#[inline]` attribute that says the same thing, and it cannot know that a
  neighbouring function within 40 lines is the one the benchmark documents.
  The strip is a floor, not a guarantee.
* Remark attribution is by source location only --- the remark lines carry no
  function name (SPEC.ja.md 3) --- so a section can show a neighbouring
  function's remarks when both live within 40 lines of each other.
* jaq has now been run end to end twice, five rounds each (results.md
  "Experiment 3 (jaq)"). At the frozen `n=15` the acceptance rule still let
  one random round through whose own in-run A/A moved almost as far as the
  candidate, and a code-identical build's 95% CI excluded 1.0 in one Jev
  round: the interval is only as good as the noise it is computed from, and
  the null panel is what catches it. The earlier toy smoke run
  (results.md "Search driver (smoke)") used `n=3` and one round; nothing
  about speed follows from that.
* The standard library's sources are not on this machine (`rust-src` is not
  installed), so a mark whose DWARF definition is in `library/core` gets no
  source excerpt. Five of jaq's fifteen are in that position.
* **The v2 thresholds and phrasings were written by someone who had already
  seen jaq's nine study sites.** `<300` for a small function, `>=2000` for a
  very large one, `>=100` for a long trip and 5% for very hot are round
  numbers applied by one rule to every site, but the person choosing the
  round numbers knew what those sites look like. The study says so itself,
  and `targets/hintbench` (decision 72) is the measurement meant to close
  it: sites whose ground truth is measured rather than judged.
* The element type of a loop is read off the recorded inline chain. Where
  the chain carries no iterator --- a loop over format pieces, a validation
  loop over raw bytes --- the block says the lane count is unknown, so the
  lanes argument simply does not reach those loops. On jaq's frozen set that
  is 12 of 16.
* The verdict block's legality reading is only as good as remark
  attribution, which is by source location (SPEC.ja.md 3). The block repeats
  that caveat at every loop rather than hiding it.
* **Every result obtained before v3 was obtained with two inert function
  candidates in the list.** Experiment 3's five rounds and both rounds of
  the prompt study offered `inline` and `cold`, neither of which can change
  an inlining decision under this recipe (decision 77, and the v3 section
  above). The measurements stand; the agreement figures are the ones that
  have to be read with it, since `inline` was round 1's most frequent pick.
