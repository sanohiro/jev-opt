# Jev prompt/state study --- does the way we ask change what Jev answers?

Status: **complete.** 153 requests, 800 answered questions, 18 framings x 9
sites x 3 repeats, no request lost. The section above the horizontal rule is
the pre-registered half --- the nine sites and the hint Claude would choose at
each, committed before a single request was sent; the section below is what
came back.

Decision 66 recorded that Jev answered `KEEP_DEFAULT` to all 107 questions of
Experiment 3 at a mean confidence of 0.95, and decision 67 asked whether that
is Jev's opinion or an artefact of the way the question is put. Decision 68
added that the state carried one line of platform information and almost no
per-site profile, and that 15 questions rode in one 71 KB request.

No build and no benchmark runs here: this is the Jev API only.

## The nine sites

Seven of them are the sites the task named (`F1`, `F2`, `F3`, `F4`, `L1`,
`L2`, `L4`). `L3` is `base_run{closure#7}`'s only loop site, added beside
`F4` because it is the one clean vector candidate in the whole frozen set and
the study needs a site where a hint plausibly pays. `L5` is a deliberate
addition and the only one **outside** the frozen site set of decision 63: the
pre-registered rule "drop trip count < 2" removed every short-trip loop from
that set, and the study needs one to ask whether Jev's vectorisation
preference notices a trip count of 1. All eight of the others appear verbatim
in the Experiment 3 request log, so V0 re-sends the real thing.

| id | kind | site | the numbers the state carries |
|---|---|---|---|
| F1 | fn | `jaq_json::read::parse` | 29.29% of user cycles, 7660 LLVM insts, 18 monomorphizations, attributes now `cold \| inlinehint` |
| F2 | fn | `<jaq_core::compile::TermId>::run` | 8.32% (8.85% with inlined code), 10496 LLVM insts (6562 machine insts, 236 backedges), 62 monomorphizations, attributes now `cold \| inlinehint \| inlinehint,cold` |
| F3 | fn | `jaq_json::write::write` | 4.48% overall, 22.6% of the readwrite case, 5467 LLVM insts, attributes now `inlinehint`, recursive serializer |
| F4 | fn | `<jaq_std::base_run<..>::{closure#7} as FnOnce<..>>::call_once` | 1.73%, 251 LLVM insts, attributes now `inlinehint` |
| L1 | loop | mark 12 `<&String as Display>::fmt` @ `slice/iter/macros.rs:180` depth 2 | **the hottest `loop_in_mark` key in the program** (hot 2.6e10), trip 32, 36 insts, no calls, chain `Formatter::pad -> Chars::count -> do_count_chars -> slice::Iter::next` |
| L2 | loop | `jaq_json::write::write` @ `core/fmt/mod.rs:1653` depth 1 | trip 25.8, 141 insts, **calls inside**, key shared by 4 loops (`ambiguous`), hot 2.0e10 |
| L3 | loop | `base_run{closure#7}` @ `slice/iter/macros.rs:279` depth 1 | **trip 221.7**, 13 insts, no calls, the `to_ascii_lowercase` byte loop; baseline remarks already say `vectorized loop (width 4, interleaved 2)` |
| L4 | loop | `read::parse` @ hifijson `str.rs:194` depth 1 | trip 13.9, 13 insts, no calls, the `write_until` / `position` byte scan; `write_until` and `str_fold` are on its inline chain |
| L5 | loop | `jaq_json::write::write` @ `slice/iter.rs:605` depth 1 | **trip 1.0**, 200 insts, calls inside, hot 1.1e9 --- *study-only, outside the frozen set* |

Two namings in the task deserve a correction, because the study uses the
sites the numbers point at rather than the ones the shorthand names:

* "the hottest `loop_in_mark` site (the `core::fmt` padding loop under mark
  12)" --- the hottest key under mark 12, and in the whole program, is
  `a48529f86e22591a-next-macros.rs-180` (hot 2.6e10), which is the character
  **count** loop under `Formatter::pad`, not `Formatter::padding`. The
  literal padding loop (`dbbda91ece248757-padding-mod.rs-1966`, hot 5.2e8) is
  fifty times colder. `L1` is the hot one.
* "the hifijson `write_until` position loop" --- all six loop sites owned by
  the `write_until` mark have **no profile counts at all** (`trip_count`
  null) and were dropped by the pre-registered rule. The same source loop
  *does* carry a profile where LTO put it, inlined into `read::parse`:
  `7a171b553e34d5fc-string_end-str.rs-194`, with `write_until` and
  `str_fold` on its inline chain. That is `L4`.

## Claude's reference picks, written before any query

These are not ground truth. They are what one reasonably careful reader of
the same state would choose, and the study measures how close Jev's answers
come to them under each framing. Where the honest answer is "nothing in this
vocabulary reaches this site", the pick is `KEEP_DEFAULT` and the reason says
why --- six of the nine are of that kind, and that is itself a result.

### F1 `jaq_json::read::parse` --- **KEEP_DEFAULT**

7660 LLVM instructions across 18 monomorphizations, and the copies already
carry `inlinehint` (and `cold`, from PGO). `inline` on a body that size
cannot clear any threshold and is close to a no-op on top of the hint it
already has; `inline_never` would fight the specialisation that makes this
the inline *host* for `seq`, `str_fold` and `write_until`; `cold` on the
function holding 29% of the cycles is a pessimisation by definition.
`align_16` is the x86-64 default. That leaves `align_32`/`align_64`, and the
one time alignment moved jaq (decision 31) it was a **build-wide**
`-align-all-functions`, not one function's entry --- and this function's hot
loops are deep inside it, not at its entry. Nothing here is worth a build.

### F2 `<jaq_core::compile::TermId>::run` --- **inline_never**

The one site where a function attribute has a mechanism. 62 monomorphizations
of a 10496-instruction interpreter dispatch, carrying `inlinehint` on some
copies, is the textbook instruction-cache blow-up: the hint asks LLVM to
paste that body into callers it would otherwise leave alone. `noinline`
keeps one out-of-line copy per monomorphization and keeps the callers small.
Second choice `cold` (wrong: 8.3% is not cold), and `KEEP_DEFAULT` is a
defensible third --- the body may already be too large to be inlined
anywhere, in which case `noinline` is a no-op rather than a loss.

### F3 `jaq_json::write::write` --- **inline_never**

A recursive serializer (`write` -> `write_val!` -> `write`) of 5467
instructions carrying `inlinehint`, and 22.6% of the readwrite case. The hint
buys one level of recursion pasted into every caller for 5467 instructions of
I-cache each time. Low confidence: LLVM usually declines to inline
self-recursive functions anyway, so this may measure nothing.

### F4 `<jaq_std::base_run<..>::{closure#7}>` --- **KEEP_DEFAULT**

251 instructions, hot, and the state says `attributes now inlinehint`.
`inline` --- the only candidate with a plausible mechanism on a small hot
function --- is *already applied*, so choosing it changes nothing.
`inline_never` on a 251-instruction hot leaf is the wrong direction, `cold`
is wrong, alignment is a lottery. This site is a test of whether the reader
noticed the "attributes now" line.

### L1 `Chars::count` under `Formatter::pad` --- **KEEP_DEFAULT**

The hottest loop key in the program, and out of reach. The baseline remarks
say `Cannot vectorize early exit loop with complex writes to memory`,
`Incorrect number of successors from early exiting block` and `value that
could not be identified as reduction is used outside the loop`: a
`vectorize.width` hint is not a permission slip, it is dropped when
vectorisation is illegal. Both unroll remarks say `advising against
unrolling ... contains a call/invoke`. `unroll_count_2` is the only thing
that could still land (metadata does override that advice) on a
36-instruction body with trip 32, and it is a coin flip --- second choice,
not the pick.

### L2 `core::fmt::write`'s piece loop inside `write::write` --- **KEEP_DEFAULT**

141 instructions whose content is indirect `Display::fmt` calls, trip 25.8,
`calls inside: yes`, not vectorizable (early exit, trip count not
determinable). Unrolling saves loop control that is already invisible next to
an indirect call, and the key is shared by **4 loops**, so the hint lands on
all of them at once. Nothing to buy.

### L3 `to_ascii_lowercase`'s byte loop under `base_run{closure#7}` --- **vectorize_width_16**

The one site where a hint should pay. Trip 221.7, 13 instructions, no calls,
no floating point, no early exit --- the only clean, long, straight-line
vector candidate in the set. The baseline remarks show LLVM chose
`vectorization width: 4`, and on `u8` data a 256-bit ymm register holds 32
lanes, so VF=4 leaves seven eighths of the machine idle and a trip of 222
easily amortises a wider remainder. The vocabulary stops at 16, which is
exactly where I would stop anyway: decision 12 measured a forced width of 32
on a byte loop running **2.2x slower** than the default. Second choice
`vectorize_width_8`, then `interleave_count_2`.
Caveat on the record: remarks are attributed by source line only
(SPEC.ja.md 3), and `macros.rs:279` carries several remarks, so which
`vectorized loop` line belongs to this loop is not certain.

### L4 hifijson `write_until` / `position` byte scan --- **KEEP_DEFAULT**

`Loop contains an unsupported switch`, `Incorrect number of successors from
early exiting block`: an early-exit search loop, which decision 14 already
recorded as out of the hints' reach. Trip 13.9 over a 13-instruction body
would not repay a remainder even if a width hint could be applied.

### L5 the trip-1 loop in `write::write` --- **KEEP_DEFAULT**

Average trip count 1.0 over a 200-instruction body with calls: the body runs
once per entry. Every vectorisation candidate adds a runtime check and a
remainder to a loop that never iterates, and unrolling a body that large
costs I-cache for nothing. The point of including this site is narrow: any
answer here that is a `vectorize_*` hint is evidence that the trip count is
not being read.

### Summary line

| site | reference pick | family |
|---|---|---|
| F1 `read::parse` | `KEEP_DEFAULT` | none |
| F2 `TermId::run` | `inline_never` | inline |
| F3 `write::write` | `inline_never` | inline |
| F4 `base_run{closure#7}` | `KEEP_DEFAULT` | none |
| L1 `Chars::count` | `KEEP_DEFAULT` | none |
| L2 `fmt::write` piece loop | `KEEP_DEFAULT` | none |
| L3 `to_ascii_lowercase` bytes | `vectorize_width_16` | vectorize |
| L4 `write_until` scan | `KEEP_DEFAULT` | none |
| L5 trip-1 loop | `KEEP_DEFAULT` | none |

Six `KEEP_DEFAULT`, two `inline_never`, one `vectorize_width_16`. Agreement is
scored three ways: **exact** (same candidate id), **same family**
(`KEEP_DEFAULT` / inline / align / unroll / vectorize / interleave), and
**different**. A framing that answers `KEEP_DEFAULT` everywhere scores 6/9
exact without knowing anything; a framing that finds `vectorize_width_16` at
L3 and leaves L1/L2/L4/L5 alone is the one that is actually reading.

---

<!-- RESULTS -->

## What was run

`scripts/jev_state_variants.py` builds eighteen framings of the same nine
sites; `scripts/jev_prompt_study.py` sent each of them three times and
`scripts/jev_prompt_study_report.py` produced every table below from
`log.jsonl`. No build and no benchmark: this is the Jev API only, and the
machine's CPU stayed with the oracle sweep.

| variant | what it changes, relative to the frozen state |
|---|---|
| **V0** | nothing. The Experiment 3 request, verbatim, both phases (15 function questions, 16 loop questions). The control. |
| **V0b** | frozen wording, but only this study's sites in the request. Separates *wording* from *batching*. |
| **V1** | `KEEP_DEFAULT` removed from `criteria`; "we will try one hint here; which is the most promising?" |
| **V2** | `KEEP_DEFAULT` kept but described neutrally ("no change", "neither preferred nor discouraged"); question reworded to "which single hint is most likely to make this faster on this workload?" |
| **V3** | V2 minus the anchoring sections: the baseline remarks, the attributes already applied, the previous rounds. |
| **V4** | V2 plus search framing: round 1 of a search, a wrong hint costs one build and is measured, not shipped. |
| **V5** | Score (0--3 expected gain, ordered array) for every candidate plus one Noul per site; the choice is derived. |
| **V6** | V2 with the source excerpts cut from +-40 to +-10 lines. |
| **V7** | V2 plus a structured platform block (Zen 3, AVX2/FMA/BMI2, no AVX-512, 256-bit and 16 ymm, 32 KiB L1d / 512 KiB L2 / 32 MiB L3 as WSL2 reports it, pinned core, LLVM 23.1.1, the baseline flags). |
| **V8** | V2 plus a per-site profile table (self and reach share, share per workload, trip count, header count, body instructions, calls, depth, key copies, inline chain, a classification of the baseline remarks). |
| **V9** | V2+V7+V8, one question per HTTP request. |
| **V10** | V4's search framing + V7 + V8 + one question per request. |
| **V11** | V2+V7+V8 plus a hint guide: what each hint does, where it helps, where it backfires --- general, naming no site of this program. |
| **V12** | the decision split in two: stage 1 chooses a family (leave alone / inlining / cold / alignment, or unroll / vectorize / interleave), stage 2 chooses the value inside it, in a separate request. |
| **V13** | V2+V7+V8 plus six measured examples from the toy and zopfli days (width 32 on a byte loop 2.2x slower; a width hint changing FP output; width hints bit-identical on an early-exit loop; +1.6% from *capping* unrolling; +2.1% from an SLP threshold and alignment next; 0--2% total room across four programs). |
| **V14** | V2+V7+V8 plus Claude's reasoning for the reference picks, generalised so that it states no conclusion about any site here. The ceiling measurement, not shippable: it needs Claude every time. |
| **V15** | added after the first pass: V1's forced choice **plus** V7 and V8. V1 was the only framing that produced a vectorisation hint and it produced width 4 on a byte loop; this asks the same forced question with the register width and the trip count spelled out. |
| **V16** | V15 plus the hint guide. |

`V12`'s two stages are two requests, never a dependency inside one request:
the API evaluates the questions of one request independently (decision 19).

## Per-variant summary

| variant | answers | KEEP_DEFAULT rate | mean confidence | stable sites (3/3 identical) | exact | same family | different |
|---|--:|--:|--:|--:|--:|--:|--:|
| V0 | 24 | 100% | 0.92 | 8/8 | 15 | 0 | 9 |
| V0b | 27 | 100% | 0.93 | 9/9 | 18 | 0 | 9 |
| V1 | 27 | 0% | 0.46 | 8/9 | 0 | 9 | 18 |
| V2 | 27 | 78% | 0.59 | 9/9 | 18 | 6 | 3 |
| V3 | 27 | 89% | 0.45 | 9/9 | 18 | 3 | 6 |
| V4 | 27 | 78% | 0.55 | 7/9 | 17 | 5 | 5 |
| V5 | 27 | 74% | 0.35 | 8/9 | 13 | 0 | 14 |
| V6 | 27 | 78% | 0.58 | 9/9 | 18 | 6 | 3 |
| V7 | 27 | 78% | 0.57 | 9/9 | 18 | 6 | 3 |
| V8 | 27 | 78% | 0.61 | 9/9 | 18 | 6 | 3 |
| V9 | 27 | 67% | 0.64 | 9/9 | 15 | 6 | 6 |
| V10 | 27 | 67% | 0.62 | 9/9 | 15 | 6 | 6 |
| V11 | 27 | 100% | 0.63 | 9/9 | 18 | 0 | 9 |
| V12 | 27 | 59% | 0.77 | 8/9 | 13 | 6 | 8 |
| V13 | 27 | 100% | 0.70 | 9/9 | 18 | 0 | 9 |
| V14 | 27 | 100% | 0.80 | 9/9 | 18 | 0 | 9 |
| V15 | 27 | 0% | 0.44 | 8/9 | 0 | 8 | 19 |
| V16 | 27 | 0% | 0.52 | 8/9 | 2 | 4 | 21 |

## Choice per site, per variant (modal answer of the repeats; `!` when the three repeats did not agree)

| variant | F1 | F2 | F3 | F4 | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|---|---|---|---|
| **reference** | KEEP_DEFAULT | inline_never | inline_never | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | vectorize_width_16 | KEEP_DEFAULT | KEEP_DEFAULT |
| V0 | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | - |
| V0b | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V1 | inline | inline | inline | inline | unroll_disable | unroll_count_4 ! | vectorize_width_4 | unroll_disable | unroll_disable |
| V2 | KEEP_DEFAULT | inline | inline | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V3 | KEEP_DEFAULT | inline | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V4 | KEEP_DEFAULT ! | inline | inline ! | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V5 | inline | KEEP_DEFAULT ! | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | unroll_count_8 | KEEP_DEFAULT |
| V6 | KEEP_DEFAULT | inline | inline | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V7 | KEEP_DEFAULT | inline | inline | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V8 | KEEP_DEFAULT | inline | inline | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V9 | inline | inline | inline | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V10 | inline | inline | inline | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V11 | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V12 | inline | inline | inline | inline ! | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V13 | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V14 | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V15 | inline | inline | inline | inline | unroll_disable | unroll_disable | vectorize_width_4 ! | unroll_disable | unroll_disable |
| V16 | inline | inline_never ! | inline | inline | unroll_disable | unroll_disable | interleave_count_1 | unroll_disable | unroll_disable |

## What came second in V0

- `inline` 12
- `interleave_count_1` 9
- `unroll_count_8` 3

## Does the choice track the site information?

| variant | L3 trip 222, vectorizable | L5 trip 1 | L1/L2/L4 reported illegal to vectorize | F2 10496 insts |
|---|---|---|---|---|
| V0 | KEEP_DEFAULT | - | 0/9 vector-family answers | KEEP_DEFAULT |
| V0b | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | KEEP_DEFAULT |
| V1 | vectorize_width_4 | unroll_disable | 0/9 vector-family answers | inline |
| V2 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | inline |
| V3 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | inline |
| V4 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | inline |
| V5 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | KEEP_DEFAULT |
| V6 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | inline |
| V7 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | inline |
| V8 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | inline |
| V9 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | inline |
| V10 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | inline |
| V11 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | KEEP_DEFAULT |
| V12 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | inline |
| V13 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | KEEP_DEFAULT |
| V14 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | KEEP_DEFAULT |
| V15 | vectorize_width_4 | unroll_disable | 0/9 vector-family answers | inline |
| V16 | interleave_count_1 | unroll_disable | 0/9 vector-family answers | inline_never |

## Where the probability mass sat, not just the argmax

A Choice answer carries a probability for every candidate. The argmax can stay on KEEP_DEFAULT while the mass behind it moves, and that is the sensitive measure of whether a section of the state was read at all. Each cell is the mean probability the repeats put on **anything other than KEEP_DEFAULT**, and, for the loop sites, the mean mass on the vectorize family in parentheses.

| variant | F1 | F2 | F3 | F4 | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|---|---|---|---|
| V0 | 0.06 | 0.08 | 0.16 | 0.20 | 0.00 (0.00) | 0.00 (0.00) | 0.05 (0.01) | 0.00 (0.00) | - |
| V0b | 0.03 | 0.08 | 0.16 | 0.13 | 0.00 (0.00) | 0.00 (0.00) | 0.05 (0.01) | 0.01 (0.00) | 0.02 (0.00) |
| V1 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 (0.18) | 1.00 (0.23) | 1.00 (0.37) | 1.00 (0.41) | 1.00 (0.26) |
| V2 | 0.45 | 0.58 | 0.58 | 0.47 | 0.18 (0.03) | 0.18 (0.02) | 0.45 (0.15) | 0.30 (0.11) | 0.29 (0.05) |
| V3 | 0.52 | 0.60 | 0.50 | 0.37 | 0.57 (0.29) | 0.41 (0.23) | 0.62 (0.19) | 0.57 (0.44) | 0.32 (0.10) |
| V4 | 0.54 | 0.59 | 0.53 | 0.45 | 0.20 (0.04) | 0.20 (0.03) | 0.50 (0.15) | 0.39 (0.17) | 0.30 (0.06) |
| V5 | - | - | - | - | - | - | - | - | - |
| V6 | 0.49 | 0.61 | 0.57 | 0.47 | 0.16 (0.03) | 0.18 (0.03) | 0.43 (0.12) | 0.36 (0.19) | 0.29 (0.05) |
| V7 | 0.48 | 0.56 | 0.54 | 0.50 | 0.17 (0.03) | 0.13 (0.02) | 0.51 (0.20) | 0.30 (0.16) | 0.29 (0.06) |
| V8 | 0.50 | 0.70 | 0.60 | 0.36 | 0.26 (0.04) | 0.23 (0.03) | 0.35 (0.08) | 0.28 (0.08) | 0.30 (0.08) |
| V9 | 0.65 | 0.63 | 0.58 | 0.38 | 0.15 (0.02) | 0.13 (0.02) | 0.25 (0.13) | 0.27 (0.08) | 0.35 (0.17) |
| V10 | 0.68 | 0.65 | 0.61 | 0.39 | 0.16 (0.02) | 0.17 (0.03) | 0.30 (0.14) | 0.31 (0.11) | 0.40 (0.23) |
| V11 | 0.53 | 0.54 | 0.52 | 0.29 | 0.07 (0.00) | 0.05 (0.00) | 0.51 (0.09) | 0.18 (0.05) | 0.12 (0.03) |
| V12 | 1.00 | 1.00 | 1.00 | 1.00 | - | - | - | - | - |
| V13 | 0.44 | 0.52 | 0.48 | 0.22 | 0.08 (0.00) | 0.12 (0.00) | 0.25 (0.06) | 0.08 (0.02) | 0.18 (0.03) |
| V14 | 0.27 | 0.31 | 0.24 | 0.08 | 0.14 (0.00) | 0.03 (0.00) | 0.26 (0.11) | 0.17 (0.00) | 0.04 (0.00) |
| V15 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 (0.17) | 1.00 (0.21) | 1.00 (0.31) | 1.00 (0.38) | 1.00 (0.29) |
| V16 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 (0.11) | 1.00 (0.13) | 1.00 (0.26) | 1.00 (0.26) | 1.00 (0.23) |

## API reliability

- requests attempted 153, answered 153, never answered 0
- HTTP attempts 198 for 153 requests (1.29 per request); 45 were retries after a retryable status
- questions answered 800
- latency ms: total 138020, mean 902, median 824, max 5486
- tokens in/out 1648058 / 64434
- cost billed $0.00000000, list price $0.06921844


## What moved the answer, and what did not

**1. The control reproduces.** V0 answered `KEEP_DEFAULT` to every one of its
24 cells at mean confidence 0.92, three times out of three. Decision 66's
result is not an accident of that particular run.

**2. Batching is not the cause.** V0b is the same wording on a 21 KB state
with 5 questions instead of a 71 KB state with 16, and it is *also* 100%
`KEEP_DEFAULT` at confidence 0.93. Going the other way, one question per
request (V9, V10) did lower the `KEEP_DEFAULT` rate to 67% --- but the
answers it added were `inline` on `read::parse`, which moves *away* from the
reference, and it costs nine requests per round instead of two.

**3. The wording is the whole effect, and it is large.** V0 and V2 carry the
same state, the same nine sites and the same twelve candidates. The only
differences are that `KEEP_DEFAULT` is described as "no change ... neither
preferred nor discouraged" instead of "pick this unless there is a reason",
and that the question asks which hint is most likely to help instead of
whether anything should change. That alone moves the probability mass off
`KEEP_DEFAULT` from 0.00--0.20 to 0.18--0.58, turns two function sites into
`inline`, and drops confidence from 0.92 to 0.59. Nothing was added to the
state.

**4. Platform and profile information changed no answer.** V7 (the structured
machine block) and V8 (the per-site profile table) produce *exactly* V2's
modal choice at all nine sites, and move the mass by at most 0.1 in either
direction. The sharp test is V15: V1, with no `KEEP_DEFAULT` to fall back on,
chose `vectorize_width_4` at L3. V15 asked the identical forced question with
"one ymm holds 32 x u8", "16 architectural ymm registers" and "average trip
count 221.7" in the state --- and the answer was `vectorize_width_4` again.
The width did not move. Decision 68's hypothesis, that the thin platform and
profile sections were what kept Jev at `KEEP_DEFAULT`, is **not supported**.

**5. The anchoring section decision 67 suspected is the one input that is
demonstrably read.** V3 removes the baseline remarks, the current attributes
and the round history. The vectorize-family mass at the three loops LLVM
reports as impossible to vectorize rises from 0.02/0.03/0.11 (V2) to
0.29/0.23/0.44 (V3). Put the remarks back and it falls again. The remarks are
not what produces the `KEEP_DEFAULT` wall --- they are what stops Jev
proposing a hint that would be silently dropped.

**6. Removing `KEEP_DEFAULT` forces an answer, not a search.** V1, V15 and
V16 answer something at every site, at confidence 0.44--0.52, and the answer
is nearly a constant: `inline` at all four function sites and
`unroll_disable` at four of the five loops. Exact agreement with the
reference is 0/27, 0/27 and 2/27. A proposer that says `inline` everywhere is
not cheaper than random, it is random with one arm.

**7. Giving Jev knowledge makes it more conservative, not more
adventurous.** The hint guide (V11), the six measured examples (V13) and
Claude's own reasoning (V14) all push every argmax back to `KEEP_DEFAULT`,
and they raise confidence while doing it (0.63, 0.70, 0.80). They are not
inert: they sharpen the legality discrimination to near-perfect --- the
vectorize mass at the loops LLVM calls impossible falls to 0.00 --- which is
the correct direction. They simply conclude that nothing is worth trying.
V14 is the ceiling measurement, and it says that **given Claude's own method
written out, Jev reaches "leave everything alone", including at L3.**

**8. No framing beat "answer KEEP_DEFAULT everywhere".** Exact agreement
peaks at 18/27, which is precisely the score of answering `KEEP_DEFAULT` at
all nine sites, because six of the nine reference picks are `KEEP_DEFAULT`.
Counting family agreement as partial credit, V2/V6/V7/V8 reach 24/27 and
everything else is below. `vectorize_width_16` at L3 --- the one pick with a
mechanism --- was never returned by any framing, in any repeat. The only
exact non-`KEEP_DEFAULT` match in the whole study is V16's `inline_never` at
`TermId::run`, in one repeat of three.

**9. Legality is respected in the argmax; shape drives the mass.** Across
all eighteen framings, the chosen candidate at the three loops LLVM reports
as impossible to vectorize (L1, L2, L4) was a vectorisation or interleaving
hint **zero times out of 54 cells** --- including in V1, V15 and V16, where
`KEEP_DEFAULT` was not on the menu and something had to be picked. By that
measure the remarks are obeyed exactly. The summed probability mass says
something different about why. In the forced-choice variants it orders the
five loops
L1 0.18 < L2 0.23 < L5 0.26 < L3 0.37 < L4 0.41: the two loops it likes best
are exactly the two that are 13 LLVM instructions with no calls, and one of
them (L4) is the one LLVM reports as containing an unsupported switch. The
trip count separates almost nothing --- trip 1 (L5, 0.26) against trip 221.7
(L3, 0.37) is a factor of 1.4, and neither the ymm width nor the trip count
in V15's platform and profile blocks changed that. With `KEEP_DEFAULT`
present and the remarks in the state (V2) the order improves to L3 0.15 >
L4 0.11 > L5 0.05 > L1 0.03 > L2 0.02, which is the reference ordering.


## One request and response per variant

Each block is the question Jev was asked about **L3** --- the one site where a hint has a mechanism --- in repeat 1 of that variant, and the answer that came back. The full request bodies are in `requests.jsonl`, keyed by the `request_sha` of each log line. V5 is shown with one of its Score questions and its Noul; V12 with its stage-1 family question.

### V0

request `V0-phaseB`: state 64966 chars, 16 question(s); question `q7`:

```
Section `q7` of the state describes one loop inside a marked function, together with the function attributes this build has already applied. Which loop hint should the build attach to it? Pick KEEP_DEFAULT unless there is a reason in that section to expect the hint to make the whole program measurably faster.
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.93,
 "probabilities": {
  "KEEP_DEFAULT": 0.95,
  "interleave_count_1": 0,
  "interleave_count_2": 0,
  "interleave_count_4": 0,
  "unroll_count_2": 0.01,
  "unroll_count_4": 0,
  "unroll_count_8": 0.03,
  "unroll_disable": 0,
  "vectorize_width_16": 0,
  "vectorize_width_2": 0,
  "vectorize_width_4": 0.01,
  "vectorize_width_8": 0
 },
 "type": "choice"
}
```

### V0b

request `V0b-L1-L2-L3-L4-L5`: state 20897 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function, together with the function attributes this build has already applied. Which loop hint should the build attach to it? Pick KEEP_DEFAULT unless there is a reason in that section to expect the hint to make the whole program measurably faster.
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.94,
 "probabilities": {
  "KEEP_DEFAULT": 0.95,
  "interleave_count_1": 0,
  "interleave_count_2": 0,
  "interleave_count_4": 0,
  "unroll_count_2": 0,
  "unroll_count_4": 0,
  "unroll_count_8": 0.03,
  "unroll_disable": 0,
  "vectorize_width_16": 0,
  "vectorize_width_2": 0,
  "vectorize_width_4": 0.02,
  "vectorize_width_8": 0
 },
 "type": "choice"
}
```

### V1

request `V1-L1-L2-L3-L4-L5`: state 20798 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. We are going to try exactly one hint on it in the next build. Which of these is the most promising for making this loop faster on this workload?
criteria: interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "vectorize_width_4",
 "confidence": 0.24,
 "probabilities": {
  "interleave_count_1": 0.03,
  "interleave_count_2": 0.1,
  "interleave_count_4": 0.05,
  "unroll_count_2": 0.12,
  "unroll_count_4": 0.07,
  "unroll_count_8": 0.18,
  "unroll_disable": 0.08,
  "vectorize_width_16": 0.01,
  "vectorize_width_2": 0.02,
  "vectorize_width_4": 0.31,
  "vectorize_width_8": 0.03
 },
 "type": "choice"
}
```

### V2

request `V2-L1-L2-L3-L4-L5`: state 20855 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.48,
 "probabilities": {
  "KEEP_DEFAULT": 0.51,
  "interleave_count_1": 0.02,
  "interleave_count_2": 0.03,
  "interleave_count_4": 0.03,
  "unroll_count_2": 0.08,
  "unroll_count_4": 0.06,
  "unroll_count_8": 0.09,
  "unroll_disable": 0.02,
  "vectorize_width_16": 0,
  "vectorize_width_2": 0.01,
  "vectorize_width_4": 0.13,
  "vectorize_width_8": 0.02
 },
 "type": "choice"
}
```

### V3

request `V3-L1-L2-L3-L4-L5`: state 15374 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.31,
 "probabilities": {
  "KEEP_DEFAULT": 0.38,
  "interleave_count_1": 0,
  "interleave_count_2": 0,
  "interleave_count_4": 0,
  "unroll_count_2": 0.06,
  "unroll_count_4": 0.09,
  "unroll_count_8": 0.3,
  "unroll_disable": 0,
  "vectorize_width_16": 0.01,
  "vectorize_width_2": 0.02,
  "vectorize_width_4": 0.07,
  "vectorize_width_8": 0.07
 },
 "type": "choice"
}
```

### V4

request `V4-L1-L2-L3-L4-L5`: state 21502 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.45,
 "probabilities": {
  "KEEP_DEFAULT": 0.49,
  "interleave_count_1": 0.03,
  "interleave_count_2": 0.03,
  "interleave_count_4": 0.02,
  "unroll_count_2": 0.08,
  "unroll_count_4": 0.06,
  "unroll_count_8": 0.11,
  "unroll_disable": 0.02,
  "vectorize_width_16": 0,
  "vectorize_width_2": 0.01,
  "vectorize_width_4": 0.13,
  "vectorize_width_8": 0.02
 },
 "type": "choice"
}
```

### V5

request `V5-L1-L2-L3-L4-L5`: state 20855 chars, 60 question(s); question `q2_s5`:

```
Section `q2` of the state describes one site of this program. How much faster would that site get if the build applied `vectorize.width=2` to it (Attach `llvm)?
type: score
```

response:

```json
{
 "confidence": 0.91,
 "legend": {
  "0": "No measurable change: under 3% on this site's own time, or an effect too small to survive the whole-program measurement.",
  "1": "Small gain: 3-10% faster on this site.",
  "2": "Clear gain: 10-50% faster on this site.",
  "3": "Large gain: more than 50% faster on this site."
 },
 "probabilities": {
  "0": 0.94,
  "1": 0.03,
  "2": 0.02,
  "3": 0.01
 },
 "score": 0.09,
 "type": "score"
}
```

### V6

request `V6-L1-L2-L3-L4-L5`: state 15899 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.48,
 "probabilities": {
  "KEEP_DEFAULT": 0.54,
  "interleave_count_1": 0.02,
  "interleave_count_2": 0.02,
  "interleave_count_4": 0.02,
  "unroll_count_2": 0.07,
  "unroll_count_4": 0.06,
  "unroll_count_8": 0.1,
  "unroll_disable": 0.02,
  "vectorize_width_16": 0,
  "vectorize_width_2": 0.01,
  "vectorize_width_4": 0.12,
  "vectorize_width_8": 0.02
 },
 "type": "choice"
}
```

### V7

request `V7-L1-L2-L3-L4-L5`: state 22671 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.41,
 "probabilities": {
  "KEEP_DEFAULT": 0.47000000000000003,
  "interleave_count_1": 0.03,
  "interleave_count_2": 0.03,
  "interleave_count_4": 0.02,
  "unroll_count_2": 0.08,
  "unroll_count_4": 0.07,
  "unroll_count_8": 0.1,
  "unroll_disable": 0.01,
  "vectorize_width_16": 0.01,
  "vectorize_width_2": 0.01,
  "vectorize_width_4": 0.13,
  "vectorize_width_8": 0.04
 },
 "type": "choice"
}
```

### V8

request `V8-L1-L2-L3-L4-L5`: state 26364 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.56,
 "probabilities": {
  "KEEP_DEFAULT": 0.6,
  "interleave_count_1": 0.05,
  "interleave_count_2": 0.02,
  "interleave_count_4": 0.01,
  "unroll_count_2": 0.09,
  "unroll_count_4": 0.04,
  "unroll_count_8": 0.07,
  "unroll_disable": 0.02,
  "vectorize_width_16": 0.02,
  "vectorize_width_2": 0.01,
  "vectorize_width_4": 0.04,
  "vectorize_width_8": 0.03
 },
 "type": "choice"
}
```

### V9

request `V9-L3`: state 8719 chars, 1 question(s); question `q0`:

```
Section `q0` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.76,
 "probabilities": {
  "KEEP_DEFAULT": 0.77,
  "interleave_count_1": 0.02,
  "interleave_count_2": 0.01,
  "interleave_count_4": 0,
  "unroll_count_2": 0.03,
  "unroll_count_4": 0.02,
  "unroll_count_8": 0.02,
  "unroll_disable": 0.01,
  "vectorize_width_16": 0.04,
  "vectorize_width_2": 0.01,
  "vectorize_width_4": 0.05,
  "vectorize_width_8": 0.02
 },
 "type": "choice"
}
```

### V10

request `V10-L3`: state 9367 chars, 1 question(s); question `q0`:

```
Section `q0` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.67,
 "probabilities": {
  "KEEP_DEFAULT": 0.69,
  "interleave_count_1": 0.03,
  "interleave_count_2": 0.01,
  "interleave_count_4": 0,
  "unroll_count_2": 0.05,
  "unroll_count_4": 0.04,
  "unroll_count_8": 0.03,
  "unroll_disable": 0.01,
  "vectorize_width_16": 0.04,
  "vectorize_width_2": 0.01,
  "vectorize_width_4": 0.07,
  "vectorize_width_8": 0.02
 },
 "type": "choice"
}
```

### V11

request `V11-L1-L2-L3-L4-L5`: state 31893 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.38,
 "probabilities": {
  "KEEP_DEFAULT": 0.44,
  "interleave_count_1": 0.32,
  "interleave_count_2": 0.02,
  "interleave_count_4": 0.01,
  "unroll_count_2": 0.05,
  "unroll_count_4": 0.02,
  "unroll_count_8": 0.04,
  "unroll_disable": 0.02,
  "vectorize_width_16": 0.02,
  "vectorize_width_2": 0.01,
  "vectorize_width_4": 0.02,
  "vectorize_width_8": 0.03
 },
 "type": "choice"
}
```

### V12

request `V12-L1-L2-L3-L4-L5-stage1`: state 28181 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. Before choosing a value, choose a kind: which of these families of hint, if any, has a mechanism that could make this loop faster on this workload?
criteria: interleave, leave_alone, unroll, vectorize
```

response:

```json
{
 "choice": "leave_alone",
 "confidence": 0.54,
 "probabilities": {
  "interleave": 0.04,
  "leave_alone": 0.65,
  "unroll": 0.18,
  "vectorize": 0.13
 },
 "type": "choice"
}
```

### V13

request `V13-L1-L2-L3-L4-L5`: state 30355 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.71,
 "probabilities": {
  "KEEP_DEFAULT": 0.73,
  "interleave_count_1": 0.04,
  "interleave_count_2": 0.02,
  "interleave_count_4": 0.01,
  "unroll_count_2": 0.07,
  "unroll_count_4": 0.02,
  "unroll_count_8": 0.03,
  "unroll_disable": 0.03,
  "vectorize_width_16": 0.01,
  "vectorize_width_2": 0.01,
  "vectorize_width_4": 0.02,
  "vectorize_width_8": 0.01
 },
 "type": "choice"
}
```

### V14

request `V14-L1-L2-L3-L4-L5`: state 30713 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.69,
 "probabilities": {
  "KEEP_DEFAULT": 0.71,
  "interleave_count_1": 0.03,
  "interleave_count_2": 0.01,
  "interleave_count_4": 0.01,
  "unroll_count_2": 0.04,
  "unroll_count_4": 0.02,
  "unroll_count_8": 0.05,
  "unroll_disable": 0.01,
  "vectorize_width_16": 0.04,
  "vectorize_width_2": 0.01,
  "vectorize_width_4": 0.02,
  "vectorize_width_8": 0.049999999999999996
 },
 "type": "choice"
}
```

### V15

request `V15-L1-L2-L3-L4-L5`: state 28124 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. We are going to try exactly one hint on it in the next build. Which of these is the most promising for making this loop faster on this workload?
criteria: interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "vectorize_width_4",
 "confidence": 0.1,
 "probabilities": {
  "interleave_count_1": 0.07,
  "interleave_count_2": 0.05,
  "interleave_count_4": 0.02,
  "unroll_count_2": 0.18,
  "unroll_count_4": 0.08,
  "unroll_count_8": 0.16,
  "unroll_disable": 0.12,
  "vectorize_width_16": 0.07,
  "vectorize_width_2": 0.02,
  "vectorize_width_4": 0.18,
  "vectorize_width_8": 0.05
 },
 "type": "choice"
}
```

### V16

request `V16-L1-L2-L3-L4-L5`: state 31836 chars, 5 question(s); question `q2`:

```
Section `q2` of the state describes one loop inside a marked function of this program. We are going to try exactly one hint on it in the next build. Which of these is the most promising for making this loop faster on this workload?
criteria: interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "interleave_count_1",
 "confidence": 0.44,
 "probabilities": {
  "interleave_count_1": 0.49,
  "interleave_count_2": 0.03,
  "interleave_count_4": 0.01,
  "unroll_count_2": 0.07,
  "unroll_count_4": 0.02,
  "unroll_count_8": 0.06,
  "unroll_disable": 0.07,
  "vectorize_width_16": 0.05,
  "vectorize_width_2": 0.02,
  "vectorize_width_4": 0.09,
  "vectorize_width_8": 0.09
 },
 "type": "choice"
}
```


## The three checks decision 68 asked for, as yes or no

**Does the machine's vector width move the width that is chosen?** **No.**
V1 chose `vectorize_width_4` at L3 with one line about the machine in the
state. V15 asked the identical forced question with "256 bit, 16
architectural ymm registers", "one ymm holds 32 x u8" and the site's trip
count of 221.7 spelled out in a table, and chose `vectorize_width_4` again
in two of three repeats (the third answered `unroll_count_2`; never a wider
width). Adding the platform block did not move the width towards what the
register holds --- if anything it destabilised the answer, and adding the
hint guide on top (V16) moved it to `interleave_count_1`, which is narrower
still.

**Does a trip count below 2 make it avoid vectorisation hints?** **Weakly,
and only in the argmax.** No variant ever chose a vectorisation hint at L5
(trip 1.0); the forced-choice variants all chose `unroll_disable` there,
which is the right direction. But the probability mass barely separates it:
0.26 of vectorize mass at trip 1.0 against 0.37 at trip 221.7 in V1, and
0.29 against 0.31 in V15 --- a factor of 1.1 for a factor of 222 in trip
count. The number is in the state and it is very nearly not used.

**Does a 10496-instruction function make it avoid `inline`?** **No --- the
opposite, and this is the sharpest failure in the study.** `inline` is chosen
at exactly the two largest bodies in the set, `TermId::run` (10496 LLVM
instructions, 62 monomorphizations) and `write::write` (5467, recursive), in
V2, V4, V6, V7, V8, V9, V10 and V12, and V9/V10 add `read::parse` (7660) as
well. The one function where `inline` has a plausible mechanism --- F4, 251
instructions, hot --- is left at `KEEP_DEFAULT` in every variant that has
that option, and the state's own line `attributes now inlinehint`, which
makes `inline` a no-op there, is never visibly used either. Size is in the
state, in the section header and again in V8's table, and the choice runs
against it.

**Do V0's runners-up become first choices when `KEEP_DEFAULT` is removed?**
**On the function side yes, on the loop side no.** V0's second-ranked
candidate was `inline` at 12 of its 24 cells, and V1, V15 and V16 chose
`inline` at all four function sites. The loop runners-up did not survive:
`interleave_count_1` was second at 9 of V0's loop cells here (Experiment 3's
aggregate runner-up over all 16 loop sites was `vectorize_width_8`), and the
forced loop answer was `unroll_disable` at four of five sites.

## Recommendation: what state v2 should be

**Adopt V2's two wording changes, keep everything else as it is, and read the
probabilities instead of only the argmax.**

Of the four things this study varied --- how much information the state
carries, how the question is worded, whether a guide to the vocabulary is
supplied, and whether the decision is split into stages --- **only the
wording raised agreement.** V2's rewording is what turned six cells from
disagreement into family agreement (18 exact + 6 family, against V0b's
18 + 0). More information (V7, V8) changed nothing, and the same information
spread over nine requests (V9, V10) cost three exact cells. The guide, the
worked examples and Claude's reasoning (V11, V13, V14) each cost all six
family cells by returning every site to `KEEP_DEFAULT`. Splitting the
decision in two (V12) cost five exact cells. Information volume, explanation
and decomposition moved agreement down or not at all; only the framing of
the question moved it up.

1. **Describe `KEEP_DEFAULT` neutrally.** Replace "Leave this function's
   attributes exactly as they are ... LLVM's own cost model decides" and the
   instruction "Pick KEEP_DEFAULT unless there is a reason to expect ..."
   with "Change nothing ... this is the 'no change' option, one option among
   the others, neither preferred nor discouraged."
2. **Ask which hint is most likely to help, not whether anything should
   change.** "Which single hint from the list is most likely to make this
   function faster on this workload?"
3. **Add the platform block (V7) and the per-site profile table (V8).** This
   is an adoption with *no measured benefit*: neither changed a single modal
   choice here. They are worth the 3 KB because they are the state's only
   quantitative per-site summary and because decision 68 asked for them on
   the record --- not because the study found them to work. Say so in the
   spec rather than letting a later reader assume they were validated.
4. **Rank the sites by `1 - P(KEEP_DEFAULT)` and try the top non-`KEEP`
   candidate.** This is the one change that turns this study's result into a
   search that moves. Under V2 the argmax is `KEEP_DEFAULT` at seven of nine
   sites, but the mass behind it is not flat: 0.58 at `TermId::run` against
   0.18 at the `core::fmt` piece loop, and the vectorize mass inside the loop
   sites orders them L3 0.15 > L4 0.11 > L5 0.05 > L1 0.03 > L2 0.02, which
   is the reference ordering. A round that takes the highest-mass site and its
   own highest non-`KEEP` candidate produces a non-empty plan every round,
   needs no Claude, costs nothing extra, and is still Jev's judgement rather
   than Claude's. It also makes decision 66's "empty plan, no feedback"
   impossible by construction. Be clear about what it would try first: under
   V2 the highest-mass site is `TermId::run` at 0.58 and its best non-`KEEP`
   candidate is `inline`, which is the opposite of the reference pick there.
   The rule produces a moving search, not a correct one; the oracle is what
   says which of the two was right.

The recommended state v2 is therefore **V2 wording + V7 + V8, batched one
request per phase as today**, with the driver's answer rule changed from
"take the argmax" to "take the argmax, and if it is `KEEP_DEFAULT` at every
site, take the highest-mass site's best non-`KEEP` candidate".

## What must NOT change, so that Claude does not end up choosing the hints

* **Keep `KEEP_DEFAULT` in `criteria`.** V1, V15 and V16 show what removing
  it buys: a constant answer at half the confidence. If a round must produce
  a non-empty plan, get it from the probabilities (recommendation 4), not by
  deleting the option.
* **Keep the baseline remarks in the state.** V3 is the measurement: without
  them Jev proposes vectorisation hints on loops the compiler has already
  reported as impossible to vectorize, at three to ten times the rate. They
  are an input, not an anchor.
* **Do not put the hint guide, the worked examples or Claude's reasoning into
  the shipped state (V11, V13, V14).** Each of them is Claude's judgement
  about what is worth trying, written in prose; V14 in particular is Claude
  reasoning and Jev agreeing, which is exactly the shape decision 58 rules
  out. They also make Jev *more* conservative, so they do not even buy the
  behaviour they were meant to buy.
* **Do not narrow the candidate list per site.** The vocabulary stays the
  frozen one, identical at every mark (decision 58 (2)). V12's two-stage
  split is the closest legitimate version of this idea and it scored worse
  (13/27 exact) than asking once.
* **Do not split into one request per site.** V9 and V10 cost nine requests a
  round for a lower agreement.
* **Keep the frozen `jev_vocab.py` and `state-v1-...` untouched until the run
  that uses v2 starts.** Everything here lives in `jev_state_variants.py`
  precisely so the comparison with Experiment 3 stays valid.

## The honest answer to "how do we make Jev's answer approach Claude's?"

Under eighteen framings, from the frozen one to one carrying Claude's own
method in prose, Jev's answer on these nine sites is stable: leave them
alone. The framing moves the *confidence* (0.35 to 0.93) and the *mass*
(0.00 to 1.00) by a lot and the *conclusion* almost not at all, and the one
site where Claude thinks a hint has a mechanism was never chosen by any
framing. Two things follow.

First, the cheap lever is not the prompt but the read-out: the ordering
information is in the probabilities and the current driver throws it away.
Second, whether Jev's "leave it alone" is *wrong* is still an open question
that this study cannot answer --- it is what the oracle sweep, running now,
measures. If the oracle finds nothing above the noise floor at these sites
either, then Jev and Claude disagree only about `TermId::run` and one byte
loop, and Jev was closer.

## Limits of this study

* **V0 to V2 changes three things at once**: the "What is being decided"
  paragraph, the description of `KEEP_DEFAULT` in `criteria`, and the
  question text. The shift in probability mass from 0.00--0.20 to 0.18--0.58
  is the effect of all three together, and this study cannot say which of
  them carries it.
* **V12's function row in the mass table is an artefact.** Its stage-2
  request offers only the members of the family stage 1 named, so
  `KEEP_DEFAULT` is not among the candidates and `1 - P(KEEP_DEFAULT)` is
  1.00 by construction. The comparable number for V12 is stage 1's
  `1 - P(leave_alone)`; its loop cells are blank because stage 1 answered
  `leave_alone` there and no stage-2 request was sent.
* Nine sites of one program, three repeats, one day. Everything here is a
  count over 800 answered questions, not an estimate of anything.
* The reference picks are Claude's judgement, not measurements. Six of the
  nine are `KEEP_DEFAULT`, which makes "exact agreement" easy to score
  highly by doing nothing; that is why the family column and the probability
  mass table are there.
* V0's function half comes from the round-1 phase-A request and its loop half
  from the round-3 phase-B request, because rounds 1 and 2 of phase B were
  lost to HTTP 503 and never reached Jev. V0's loop sections therefore carry
  two rounds of history where its function sections carry none. V0b, V1 and
  everything after inherit the same asymmetry.
* L5 is outside the frozen site set and its section is assembled here rather
  than taken from a real request; it has no remark attribution and no source
  excerpt, which the state says.
* Remarks are attributed by source location only (SPEC.ja.md 3), so which
  `vectorized loop (width 4)` line at `macros.rs:279` belongs to L3 is not
  certain. The reference pick at L3 rests on that line.
