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
--vocab v1|..|v4    the frozen vocabulary AND state template. v3 is the
                    default (decision 77), rendering the v3.1 state since
                    decision 83; v4 (decision 84) is v3 with the six
                    function descriptions rebalanced; v2 is decision 73's
                    W7; v1 is what Experiment 3 was run with. See "The
                    state format" below
--readout           forced_top1 (default) or argmax: how a phase's answers
                    become plan entries (decision 71). See "The proposers"
--explore K         how many extra Choices a round adds for sites nothing
                    has ever been tried at (decision 89 b, default 2).
                    --explore 0 is the behaviour of Experiment 4. jev only.
                    See "The proposers"
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
--print-state       print the state of both phases and stop; no HTTP. With
                    --resume it prints the state of the NEXT round, history
                    and all, and the exploration request it would send
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

A round becomes the best so far **only if all five hold**:

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
5. **its plan is a different plan from the incumbent's** (decision 89 a).

Rule 5 is what Experiment 4 was missing. Rounds 2 to 5 of
`docs/experiments/hintbench/exp4.md` produced the **identical binary**,
measured in four independent batches at 1.0628, 1.0636, 1.0669 and 1.0679,
and round 5 was "accepted as the new best" over round 2 because 1.0644 >
1.0628 --- rules 3 and 4 never ask whether the plan moved. It cost nothing
there, the plan being the same plan; on a run where two *different* plans sit
inside the batch-to-batch spread it promotes the luckier batch.

The comparison is on `plan_sig`, a sha256 of the hints alone: `plan_id`,
`jev_site_id`, `jev_choice`, `jev_readout`, `answer_ref` and `exploration`
record how a plan was arrived at and change no instruction, so the four
rounds above have four `plan_sha256` values and one `plan_sig`. A round whose
`plan_sig` is the incumbent's is recorded with `same_plan_as_best: true`,
its round batch and its confirmation batch are appended to the incumbent's
`batches`, and `summary.md` prints how far those batches spread. It is never
compared and never promoted, so the incumbent keeps the round number, the
plan file and the ratio it was accepted at. That spread is a free null panel:
it is the same pair of binaries measured again.

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

There are four of them, and `--vocab` selects both halves at once, because
the wording and the template are one measurement condition and the prompt
study measured them together. v3 is the default; it is v2 with a different
set of function candidates, and v4 is v3 with the function descriptions
rebalanced. Both have their own section below, as does the decision-83
repair of the v3 state (`state-v3.1-2026-09-22`), which v3 and v4 share and
v1 and v2 do not.

The four format strings, as `STATE_FORMATS` in `jev_search.py` spells them:
`state-v1-2026-09-22`, `state-v2-2026-09-22`, **`state-v3.2-2026-09-22`**
and **`state-v4.1-2026-09-22`**. The last two are the decision-19 bump for
the round-history change of Experiment 4, described in "v3.2 / v4.1" below;
v3's own repair (v3.1) and v4's first form are the sections before it.

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
| hotness class | `<1%` not hot, 1--5% hot, `>=5%` very hot (the mark's own profile share, `reach` when it has no symbol of its own). **v3.1 and v4:** where every mark carries one and the same share the number is a design statement, not a measurement, so the line reports `not measured` and there is no class |
| inline budget | **v1 and v2 only.** LLVM's own `-inline-threshold=225` / `-inlinehint-threshold=325`; the line prints body instructions over whichever applies to the attributes the function already carries, and says in the same breath that it is an order-of-magnitude comparison and not an `InlineCost` computation. v3.1 replaced it with `inliner outcomes` below |
| inliner outcomes | **v3.1 and v4.** The inline remarks of the baseline build, matched by **callee symbol** rather than by source location, aggregated over every linkage name of the mark (identical lines deduplicated, since a log holds the pre-link compilation and the LTO one): how many call sites were inlined, at which `cost=`/`threshold=` pairs, how many were declined and why. An inline remark is located at the *caller's* line, so no window around the callee's definition can find it --- which is why the site's remark block never showed it and the budget ratio above could contradict it |
| lanes | `<register width> / <element bit width>`; the element type is the innermost `Iter<...>` of the recorded inline chain, demangled with `llvm-cxxfilt`, and the line says *not derivable* where the chain carries none (a loop over format pieces, say) rather than guessing one. An element as wide as the register says so instead of naming a width |
| legality | `loop not vectorized: <reason>` whose reason is an early exit / unsupported switch / bad successor count / unidentifiable induction variable / undeterminable trip count / non-reduction used outside the loop. `runtime pointer checks needed` is **not** counted as a legality failure. No remarks recorded at the location prints `UNKNOWN`, not "legal". **v1 and v2** read the remarks from a +-10-line window; **v3.1 and v4** read them from the loop's own leaf `file:line:col` and print `UNKNOWN (shared source line; remarks not attributable to this loop)` where more than one vectoriser verdict was emitted there |
| loops at this location | **v3.1 and v4.** One verdict per loop: the bare `loop not vectorized` missed-remark, or `vectorized loop (...)`. Counted *before* dedup, at the exact leaf location, it is how many loops of the program were compiled onto that source line --- 17 at `macros.rs:180:28`, 18 at `range.rs:1103:12`, 1 at a kernel's own line |
| dump facts | **v3.1 and v4.** Trip count, calls in the body and `llvm.loop.isvectorized`, stated as the primary source because the dump records a loop and a remark records a line. The `isvectorized` reading carries its own caveat: the plugin tests it at `VectorizerStartEP`, before LoopVectorize runs, so `no` is the normal answer and is not a statement that the loop stays scalar |
| loops per key | the dump record does not carry it, so it is the `key_copies` of `sites.json` where the key is one that file recorded, and "not recorded for this key" otherwise --- never a silent 1, since 13 of jaq's 127 keys name 2--9 loops |
| no-op check | a candidate that reproduces what the site already carries: `inline` where the attributes already include `inlinehint` (and whether that is every copy or some), `cold` where `cold` is already there, `vectorize_width_N` where a remark already reports `vectorized loop (vectorization width: N)` |

The thresholds and the phrasings are the study's, copied from
`scripts/jev_state_variants.py` where they were pre-registered. The remark
window is the same one the section prints, so no line of the block can cite
something the reader cannot see: +-10 lines for a loop under v1 and v2, the
loop's own leaf location under v3.1 and v4, and under those two the
function section additionally quotes the inline remarks the `inliner
outcomes` line aggregates.

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
string was **not** bumped for it: `state-v3-2026-09-22` renders one extra
header line, and that line is the disambiguator between a `keep` run and a
`strip` run. It is added to **every** template, v1 and v2 included: a
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

One later change reaches every template: since commit `b955338` the
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

`v3-2026-09-22` is frozen at commit `7fe1a92`, on the same terms as v2
above. Its **state** is not: decision 83 replaced three defective readings
and bumped the state format to `state-v3.1-2026-09-22`, described next. The
vocabulary is unchanged to the byte, so a v3 run before and after that
commit asks the same question of a differently-evidenced state, and the two
are told apart by the state format string in every JSONL line, plan and
manifest.

### v3.1: the evidence repaired (decision 83)

`state-v3.1-2026-09-22`, the evidence content that `--vocab v3` and
`--vocab v4` both render and neither of the older two does. The string
itself has since been superseded by `state-v3.2` / `state-v4.1` for the
round-history change below; everything in this section is in both. Three readings of the v3 state said things the
build log does not support; `docs/experiments/hintbench/jev-oneshot-v3.md`
sections 5 and 14 found all three and
`docs/experiments/hintbench/jev-oneshot-v4.md` measures what fixing them
does. Nothing about the candidates, the descriptions or the questions
moves.

| | v3 | v3.1 |
|---|---|---|
| loop legality | the +-10-line remark window. Three of hintbench's four loop sites, and 12 of jaq's 16, sit on a `std` line every inlined `for` loop shares, so the window pooled other loops' verdicts and asserted NOT VECTORIZABLE at loops the baseline vectorises | the loop's own leaf `file:line:col`, plus a count of the vectoriser verdicts emitted there. More than one -> `UNKNOWN (shared source line; remarks not attributable to this loop)` |
| the loop's remark block | the same +-10-line window, unlabelled | the exact leaf location, with a header naming how many loops were compiled onto it when that number is above 1 |
| dump facts for a loop | `already vectorized when the hint is attached: no`, which reads as "LLVM leaves this loop scalar" and is not what the field means | one line stating the dump as the primary source, and saying that `llvm.loop.isvectorized` is tested before LoopVectorize runs so `no` is the normal answer |
| the inliner's decision about a function | an `inline budget` ratio of body instructions over `-inline-threshold=225`, which at hintbench's k2 said "the body fits inside that budget" while LLVM had measured cost 870 against threshold 787 and declined | the ratio is **gone**; `InlineBook` parses the log's inline remarks by callee symbol, aggregates them per mark, and both the verdict line and the state section quote them |
| a placeholder profile share | `hotness class very hot` at all eight hintbench marks, from a `share: 12.5` that is the design's "one eighth each" | `not measured`, no class, wherever every mark carries the same value. Detected, not special-cased: jaq's 1.10--29.29% keep their classes |

What the legality fix costs is recorded with it: LLVM really does vectorise
k4, k5 and k8 at VF 8 x IC 4, that fact is in the log, and it is not
reachable by source location. `UNKNOWN` is the honest reading and Jev
answers `vectorize_width_*` at all three sites once it is given
(`jev-oneshot-v4.md` section 5). Recovering the fact needs
`scripts/remark_attribution.py` wired into the state, or a plugin that
records a loop's post-vectoriser state; neither exists yet.

### v4: the function descriptions, rebalanced (decision 84)

`v4-2026-09-22`, whose state string was `state-v4-2026-09-22` until the
round-history change below took it to `state-v4.1-2026-09-22`. Same
candidates as v3, same ids,
same plan fragments, same loop half, same questions, same v3.1 state. Only
the six **function** descriptions change, so a v3/v4 difference can come
from nothing else.

Why: with the hintbench doc-comment leak removed, `inline_always` was the
best non-`KEEP_DEFAULT` candidate at all eight function sites in all three
repeats and the argmax at four, the control kernel included, while every
confidence fell to 0.34--0.48 (decision 82). v3 argues for `inline_always`
at 148 words and for `inline_never` at 117, and mentions the three
alignments in 26--37 words of v1 prose with no applicability at all; a
candidate argued for at five times the length of its rivals is a reason to
pick it that has nothing to do with the site.

v4's rule, applied to all six including `KEEP_DEFAULT`: one paragraph,
383--411 characters, 67--72 words, four sentences --- what the attribute
does, then one sentence beginning "It helps where" and one beginning "It
hurts where". No superlatives, no numeric instruction threshold in one
description and not in another, no claim that a candidate is immune to
anything, and no function, loop, file or site named. The six together are
2374 characters against v3's 2329: the words are redistributed, not added.
The candidate **order** is v3's, so position is held constant rather than
varied.

What it did: on hintbench, with the v3.1 state, v4 moved **no argmax at any
of the twelve sites** and halved the probability mass at the two sites where
`inline_always` is still chosen (k2 0.94 -> 0.70, k6 0.98 -> 0.70), while
raising `P(KEEP_DEFAULT)` everywhere else. `inline_always` is the best
non-KEEP candidate at 4 of 8 sites instead of 8 of 8. Most of that repair
was the v3.1 state, not the descriptions: the state fix alone already took
it to 5 of 8. `docs/experiments/hintbench/jev-oneshot-v4.md` has both
ablations.

`v4-2026-09-22` is frozen on the same terms as v2 and v3.

### v3.2 / v4.1: the round history reports every case (Experiment 4)

`state-v3.2-2026-09-22` and `state-v4.1-2026-09-22`, rendered by
`--vocab v3` and `--vocab v4`. The candidates, the descriptions, the
questions, the verdict block and the source excerpts are v3.1's and v4's to
the byte; only what the state *reports back* about earlier rounds changes.

Why: `## Results of the previous rounds` carried the **aggregate** ratio
only, and a site's own history line the whole-build ratio only. On a target
with one case per site the aggregate is the geometric mean over all of
them, so the 42% that `vectorize.width=16` costs at hintbench's k4 reached
the proposer as 6% of a number that names no site. And `record_batch` kept
only the arm's own kernel, which a one-factor oracle arm has and a search
round --- many sites at once, `arm` is `None` --- does not, so under
`--proposer jev` and `--proposer random` **no per-case reading was recorded
at all**.

| | v3.1 / v4 | v3.2 / v4.1 |
|---|---|---|
| round record | the aggregate ratio, its CI, the in-run A/A, and the arm's own kernel where there is an arm | the same, plus `per_workload`: every case's ratio, CI, half-width and A/A, in the round's batch and in its confirmation batch |
| the history table | round, correct, aggregate ratio, CI, accepted | the same plus an **`outcome`** column, which says why a round was not timed (`identical_to_baseline`, output mismatch, apply-incomplete, build failure) instead of printing a bare `-` |
| a second table | -- | one row per round, one column per case, with `*` on a ratio whose own 95% CI excludes 1. Rendered only where the round records carry `per_workload` |
| a site's history line | `round N: <hint> -> whole-build ratio R` | the same, plus the ratio and CI **on that site's own case** where `own_workload_of` resolves one, and whether the round was accepted |

The extra material is data-driven, not vocabulary-driven: `own_workload_of`
returns a case only on a target whose workloads are named after its sites
(`targets/hintbench`), so on jaq, zopfli and oxipng the per-case table and
the per-case history line do not appear and the only differences from v3.1
and v4 are the header line and the `outcome` column, which is added
unconditionally. **Round 1 of any run has no history at all**, so its state
is its predecessor's apart from the header line --- which is what makes
round 1 of a run comparable with a `jev_oneshot.py` pass, and
`docs/experiments/hintbench/exp4.md` 1.4 records the diff.

What it does not do is separate two sites that share a case. hintbench's k4
has a function site and a loop site and one workload, so after a round both
lines quote the same 0.5813 and neither says which of the two answers
earned it.

### v3.3 / v4.2: cross-kernel cost, shared cases, and what LLVM did (decision 89)

`state-v3.3-2026-09-22` and `state-v4.2-2026-09-22`, rendered by `--vocab v3`
and `--vocab v4`. The candidate lists, the descriptions, the question
wordings, the verdict *rules* and the source excerpts are v3.2's and v4.1's
to the byte. Three things are added, all of them evidence, all gated on
`evidence_fixes` so that v1 and v2 stay byte-replayable:

**(a) What the same hint measured on the other cases (decision 89 c).** The
per-kernel readout of v3.2 answers "did the hint help where it was applied"
and is silent about what it cost elsewhere. `inline(always)` at hintbench's
`k6_hot_loop` reads 1.0011 on k6 --- free, by its own case --- and 0.972 on
k3, and that is most of what Experiment 4's accepted plan did not win. A
site's history block now carries one extra line per distinct hint tried
there:

```
    what inline(always) at this site measured on the OTHER cases, over the
    1 round(s) it was in the plan (a hint can be free on the case its own
    site is timed by and still cost time in a kernel this site has nothing
    to do with; `*` marks a case whose own 95% CI excluded 1 in every one of
    those rounds): k3 0.9721*, k8 1.0004, k4 1.0003, ...
```

The ratio is the geometric mean over the rounds that hint was in the plan,
and the cases are ordered by distance from 1. It is rendered only where the
round records carry `per_workload`, i.e. on a target with a per-case readout.

**(b) Sites that share a timing case (decision 89 d).** hintbench times
`k4_count_bytes` and the loop inside it on one workload, so after a round in
which the loop cost 42% the *function* site's history line also said 42%. The
readout cannot separate them, and each such site now says so:

```
  this site's own timing case, k4, is also timed by
  `hbkernels::k4_count_bytes@macros.rs:180:28#d2`: the case's ratio is the
  ratio of a build in which every one of them was answered, so a change in
  it cannot be attributed to one of them alone.
```

Printed whether or not there is a history: it is a property of the case set.

**(c) What LLVM did with the loop (decision 87 c, plugin).** Decision 83
could only say `vectorisation legality: UNKNOWN (shared source line)` for
three of hintbench's four loops, because a remark carries a source location
and no function name --- and that is why Experiment 4's loop answers were
chosen from lane arithmetic alone. The plugin now records, per site key, what
the loop looked like **after** LoopVectorize (`plugin/README.md`,
`post_vectorize`), and the loop verdict block leads with it:

```
  - what LLVM did with this loop in the baseline build, recorded by the
    plugin itself after LoopVectorize had run --- this is a fact about this
    one loop, not a remark attributed to a source line, and it is the primary
    evidence here: LLVM vectorized it, with vectors of 4 lanes, interleaved 4
    times (the vectorized loop's induction variable advances 16 elements per
    iteration).
  - vectorisation legality: LEGAL, and already taken --- the baseline
    vectorizes this loop with no hint at all.
  - no-op check: 4 is the width LLVM already uses here, so the candidate
    `vectorize_width_4` asks for the state this site is in and the build it
    produces can only be the baseline's.
```

The four cases it distinguishes are *vectorized* (width, interleave count and
the no-op checks that follow from them), *not vectorized* (the loop is there
and carries no `llvm.loop.isvectorized`; a width hint is not a permission
slip, and why LLVM declined is still only in the remarks), *gone* (no loop
answers to that key after the vectorizer, so a hint on it has nothing to act
on) and *ambiguous* (two loops of one function cannot be told apart after the
rewrite --- the same honest UNKNOWN as a shared remark line, on a much
smaller set). The shared-line caveat survives, demoted to what it really
covers: the *reason*.

A report written by an older plugin carries no `post_vectorize`, and the
block then falls back to the v3.2 remark reading unchanged --- which is what
`artifacts/hintbench-sites/baseline` still does.

### One shot, API only: `scripts/jev_oneshot.py`

Round 1 of a run, both phases, N repeats, **no build and no timing**. It
loads `jev_search.py` as a module, runs the `--print-state` path to perform
the whole round-1 setup, and then drives `JevProposer.choose()` on the
driver's own item lists, so the state, the questions, the batching, the
candidate validation, the confidence gate and the decision-71 readout are
the driver's code. A phase whose every answer came back `no answer` is
re-sent unchanged and both lines stay in the JSONL.

Its one departure from a real round is forced by building nothing: phase B
is asked against the **baseline** dump's loop sites and told `function
attributes this round already applied: none`, which is round 1 of a run
whose phase A answered `KEEP_DEFAULT` everywhere. Use it to compare
prompts, never to produce a plan.

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

  **A phase that never got through is re-sent unchanged.** When all three
  internal retries of a request fail --- a 503 burst on the gateway, which
  decision 87 recorded taking out both phases of a one-shot repeat --- every
  answer of that phase is replaced by `KEEP_DEFAULT` with `source: "no
  answer"` and no probabilities, so the plan is empty *and* the decision-71
  readout has nothing to rank. `JevProposer.choose` therefore detects a
  phase whose every answer is `no answer` and sends the **same request
  again**, ten seconds later, logged as phase `A.retry` / `B.retry`; the
  exhausted line stays in the JSONL with its `http_status`. No request is
  ever modified to make it succeed. This is what `scripts/jev_oneshot.py`
  has always done at the harness level, and that harness's own `ask_phase`
  now retries on top of this one --- a second re-send after this one has
  also failed, recorded as `A.retry.retry`.

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
  **Exploration: `--explore K` (decision 89 b, default 2).** Experiment 4
  showed the feedback working as a *filter* and not as a search: it dropped
  both harmful picks in one round and discovered nothing. The reason is
  structural --- the state can only speak about hints that have been tried,
  so no round ever said what `unroll.count=4` at the k3 loop (+4.4%) or
  `vectorize.width=16` at k8 (+8.8%) would be worth, and neither was tried
  once in 58 answers. The one exploration mechanism the driver had,
  `forced_top1`, fires only when a phase is *entirely* `KEEP_DEFAULT`, which
  never happened because `k2_mix` alone kept phase A non-empty in all five
  rounds.

  After a phase's own answers are in, the driver therefore sends **one more
  request** for that phase, logged as `A.explore` / `B.explore`. A site is
  eligible when

  * no earlier round, accepted or not, put a non-`KEEP_DEFAULT` hint on it,
    **and**
  * this round's own answer there is `KEEP_DEFAULT`.

  The second clause is what makes the extra Choice additive: a site that is
  already getting a hint this round will have been tried by the end of it, so
  there is nothing to explore, and **no argmax is ever overridden**.
  Eligible sites are ordered by hotness --- the dump's own `hotness` for a
  loop, the profile share for a function, and where every mark declares the
  same share by construction (hintbench: one eighth each, which decision 83
  already refuses to classify) the summed hotness of the loops the dump found
  inside the mark --- and the first `K` are asked.

  The question's criteria are **every candidate that site has not already
  been given**, filtered mechanically, with their frozen descriptions and
  without `KEEP_DEFAULT`; nothing is left out on anyone's judgement. The
  wording is "One of the candidates below will be tried at this site in this
  round's build; which of them is most promising?" --- the site is going to
  be tried either way, and the Choice is only about which hint.

  The answer joins this round's plan beside the argmax entries. The entry
  carries `exploration: true`, the site's `why` record carries
  `source: "exploration"` and the `KEEP_DEFAULT` it replaced, and
  `phase_a.exploration` / `phase_b.exploration` in `rounds.jsonl` record the
  `K`, the sites asked and what each one was given. An answer that does not
  come back, or is not one of the candidates, leaves the site at
  `KEEP_DEFAULT`: exploration must not be able to put a hint in a plan that
  the model did not choose.

  **An exploration request that never got through is re-sent unchanged**, ten
  seconds later, logged as `A.explore.retry` / `B.explore.retry` --- the same
  rule `choose` applies to a phase whose every answer is `no answer`
  (`docs/experiments/hintbench/exp4.md` 1.4 b), and added before round 1 of
  Experiment 5 for the same reason. A request the gateway dropped leaves
  every eligible site at `KEEP_DEFAULT`, and because those sites are then
  still untried it costs the round its whole exploration slot. Six of
  Experiment 4's twelve requests carried at least one 503 and two exhausted
  all three internal retries. No request is ever modified to make it
  succeed, and the exhausted line stays in the JSONL with its
  `http_status`.

  `--explore 0` restores Experiment 4's behaviour exactly. Exploration is a
  `jev` mechanism: `random` already draws non-`KEEP_DEFAULT` candidates by
  construction, and the oracle's arms are enumerated. It is a command-line
  flag and not a `jev-opt.toml` key, like `--readout` and unlike `rounds`:
  it is a property of an experiment's arm, not of the machine.

  **Round 1 of a run with `--explore 2` is no longer a one-shot control.**
  Round 1 has no history, so every site is untried and exploration fires on
  two of them per phase --- which is the point, and which is also why
  `docs/experiments/hintbench/exp4.md` 1.4's "round 1 reproduces
  `jev-oneshot-v4.md`" only holds under `--explore 0`. `scripts/jev_oneshot.py`
  pins `--explore 0` for exactly that reason.
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
* **Exploration tries a hint; it does not find the right one.** `--explore K`
  guarantees that the K hottest untried sites of a phase stop being untried,
  which is the gap Experiment 4 measured. It does not make the answer better:
  the candidate is still chosen by the same model from the same descriptions,
  and a site with eleven candidates needs eleven rounds to be swept by a
  mechanism that offers it one a round. What it buys is that the feedback
  loop is given something to filter.
* **Exploration is ordered by a hotness that hintbench does not have.** Every
  mark of `targets/hintbench` declares the same profile share by
  construction, so the order falls back to the summed hotness of the loops
  inside the mark --- a real profile number, but a loop number standing in
  for a function one. On a target with a measured per-mark share (jaq) the
  share is used and this does not arise.
* **A round that is not compared is still built and still measured.** Rule 5
  drops the comparison, not the build: a round whose plan is the incumbent's
  spends two builds and one or two batches to add a point to the incumbent's
  null panel. That is worth having --- it is the only free measurement of how
  far this machine moves between batches --- but it is not free.
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
  that caveat at every loop rather than hiding it. Where the build's reports
  carry `post_vectorize` (a plugin from decision 87 c on), the *outcome* --
  vectorized or not, at what width and interleave count -- comes from the
  plugin instead and is per loop; only the compiler's **reason** for
  declining is still a remark, and still attributed by source location.
* **`post_vectorize` matches a loop back across the vectorizer by signature,
  not by site key.** A site key hashes the loop body and LoopVectorize
  rewrites the body, so the match is on (owner function, innermost debug
  location with its inline chain, nesting depth). Two loops of one function
  that begin at the same `file:line:col` at the same depth share a signature
  and both are reported `ambiguous_signature` with no facts. Where the apply
  half attached `jev.site` metadata the match is exact instead.
* **The interleave count is derived, not read.** LoopVectorize drops the
  `llvm.loop.vectorize.*` metadata from the loop it produces, so the plugin
  recovers the factor from the vectorized loop's induction-variable step
  divided by its vector width. On the toy that reproduces the remarks exactly
  (`count_quotes` and `sum_indexed`: width 4, interleave 4). A loop whose
  induction variable is not an integer phi incremented by a constant reports
  `iv_step: null` and no interleave count.
* **Every result obtained before v3 was obtained with two inert function
  candidates in the list.** Experiment 3's five rounds and both rounds of
  the prompt study offered `inline` and `cold`, neither of which can change
  an inlining decision under this recipe (decision 77, and the v3 section
  above). The measurements stand; the agreement figures are the ones that
  have to be read with it, since `inline` was round 1's most frequent pick.
