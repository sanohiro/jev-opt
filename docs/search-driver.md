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
--site-set PATH     the frozen loop-site key list inside sites.json, e.g.
                    oracle.selected_keys_top3. All three proposers must be
                    given the same one (SPEC.ja.md 2)
--fn-attr-scope     own (default) or all; see "Sites" below
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
  or `::helper` is an item defined inside it.
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

Rule 3 is deliberately conservative: it never promotes a plan whose interval
merely overlaps the incumbent. A round that fails 1 or 2 is recorded with the
failure and is not measured further.

`--ignore-apply-failures` relaxes rule 2 for debugging; the outcome is
recorded either way.

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

## The state format (frozen)

Decision 19: what the state says changes the answer, so the format is frozen
like a measurement condition. It is `STATE_FORMAT_VERSION` in
`jev_search.py`, `VOCAB_VERSION` in `jev_vocab.py`, and both are written into
every request log line, every plan and the run manifest. `--print-state`
prints the whole thing without making a request.

The API takes one `state` string and N questions, so the per-site material
lives in the state, one section per question, named after the question:

```
# jev-opt hint search --- state format state-v1-..., vocabulary v1-...
## What is being decided          what varies, what is measured, that
                                  KEEP_DEFAULT reproduces the baseline
## The build every arm shares     target, toolchain, machine, recipe, cases,
                                  repetitions, definition of the speed ratio
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
source:        <file:line, +-40 lines, the site's line marked `>`>
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

* **jev** --- one request per phase. Everything is logged twice: the raw
  request and response as JSONL (`jev-log/<run-id>.jsonl`, one line per
  request, no `Authorization`), and one human-readable line per request plus
  a totals block (`<run-id>.log`: requests, questions, latency, tokens, cost,
  and the share of the run's wall clock spent waiting for Jev).
* **random** --- uniform over the same candidate list, same sites, same
  number of rounds, seeded from `[evaluation] seed` and the round number.
* **oracle** --- the arms of SPEC.ja.md 2: every candidate alone at every
  site with everything else `KEEP_DEFAULT`, then one arm combining the
  per-site winners. The combination is applied through the normal two-phase
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
  rounds.jsonl         one line per round: plans, apply outcomes, correctness,
                       ratio, CI, in-run A/A, accepted
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
* Remark attribution is by source location only --- the remark lines carry no
  function name (SPEC.ja.md 3) --- so a section can show a neighbouring
  function's remarks when both live within 40 lines of each other.
* Only the toy has been run end to end (results.md "Search driver (smoke)"),
  with `n=3` and one round. Nothing about speed follows from that, and at
  that `n` the acceptance rule accepted a code-identical build, which is the
  in-sweep null panel doing its job.
* The standard library's sources are not on this machine (`rust-src` is not
  installed), so a mark whose DWARF definition is in `library/core` gets no
  source excerpt. Five of jaq's fifteen are in that position.
