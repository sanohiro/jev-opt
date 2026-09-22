# Jev prompt/state study --- does the way we ask change what Jev answers?

Status: **complete.** 153 requests, 800 answered questions, 18 framings x 9
sites x 3 repeats, no request lost. **Round 2 is at the bottom of this file**
(`# Round 2`): seven more framings that ask whether the structural facts can
be made to count, and the first framing in the study to beat "answer
`KEEP_DEFAULT` everywhere". The section above the horizontal rule is
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


---

# Round 2 --- can the structural facts be made to count?

Status: **complete.** 43 requests attempted and 42 answered (one lost to a
burst of HTTP 503), 243 answered questions, 7 framings x 9 sites x 3 repeats,
Jev API only, same nine sites and the same reference
picks as above (they were not touched). Round 2's log is
`round2/log.jsonl` and `round2/requests.jsonl`, kept separate from round 1's
so that round 1's tables still reproduce from round 1's log alone.

## The question this round asks

The user's question was: *"Jev can't decide whether to optimize; can we force
'optimize' and still get the right hint?"* Round 1's answer was no --- forcing
gives a constant (`inline` at every function, `unroll_disable` at four of five
loops).

Round 1 also found the thing this round is built on: **Jev reads verdicts and
does not infer from structural facts.** A remark saying `loop not vectorized:
Loop contains an unsupported switch` was obeyed in 54 cells out of 54; a
section header saying `10496 LLVM instructions` was read past on the way to
choosing `inline`. Round 2 turns that observation into two interventions and
tests them separately and together.

* **Idea A --- make the structural facts into verdicts.** A tool computes a
  block of verdict-shaped lines per site and puts it *next to the question*,
  where round 1 showed the wording has its effect. Every line comes from one
  rule applied to all nine sites.
* **Idea B --- put the applicability conditions into the option
  descriptions.** Each candidate says, generically, when it tends to help and
  when it hurts. No line names a site of this program.
* **Idea C --- forcing (`W4`), pairwise questions (`W5`) and the
  decision-71 readout (`W6`) on top of A+B.**

| variant | what it is |
|---|---|
| **W1** | V2's wording + the mechanical verdict block + the platform block. Idea A alone. |
| **W2** | V2's wording + the enriched option descriptions. Idea B alone. |
| **W3** | W1 + W2. |
| **W4** | W3 with `KEEP_DEFAULT` removed (forced). It takes V1's preamble, because V2's says "one of the options at every site is 'no change'", which is false once the option is gone. |
| **W5** | W3 asked as independent 2-way Choices; the winner is derived by round-robin. |
| **W6** | request-identical to W3, read out by `1 - P(KEEP_DEFAULT)` (decision 71). Because the request is identical, W3 and W6 together are also six repeats of one framing --- the repeatability check round 1 never had. |
| **W7** | the confirmation run: W3's config for the function phase, W1's for the loop phase. See the note below --- it was added after W1 and W3 were read. |

**W7 is a confirmation, not a discovery, and the file says so.** W1 and W3
disagree about which phase wants the enriched descriptions, and functions and
loops ride in separate requests anyway, so their combination is a framing in
its own right. But it was chosen *after* five loop-phase results had been
looked at, which is exactly the post-hoc selection round 1's V5 rule was
written to avoid. The repair is the cheap one: the combination was entered in
`BASE_VARIANTS` as `W7`, committed, and only then sent its own six requests,
so the row below is a prediction that was tested rather than a subset that
was picked. Six of the nine reference picks are still `KEEP_DEFAULT`, so a
single 8/9 row is not proof of much on its own; what it rules out is that the
combination was an artefact of reading two tables side by side.

`V7` from round 1 (V2 + the platform block, and nothing else) is the control
that separates W1's verdict block from W1's platform block: V7 reproduced
V2's modal choice at all nine sites, so everything W1 moves is the verdicts.

## The rules the verdict block applies, in full

No site is special-cased; these are the module constants of
`scripts/jev_state_variants.py` and they run over all nine sites.

| reading | rule |
|---|---|
| size class | `<50` tiny, `<300` small, `<1000` medium, `<2000` large, `>=2000` very large |
| copy class | 1 single, 2--8 few, `>=9` many |
| trip class | `<2` degenerate, `<16` short, `<100` medium, `>=100` long |
| hotness class | `<1%` not hot, 1--5% hot, `>=5%` very hot |
| inline budget | LLVM's own `-inline-threshold=225` / `-inlinehint-threshold=325`; the line prints body instructions over whichever applies to the attributes the function carries, and says in the same breath that it is an order-of-magnitude comparison and not an InlineCost computation |
| lanes | `256 / element bit width`; the element type is read off the recorded inline chain and reported as *unknown* where the chain does not carry one (L2, L5) |
| legality | `loop not vectorized: <reason>` whose reason is an early exit / unsupported switch / bad successor count / unidentifiable induction variable / undeterminable trip count / non-reduction used outside the loop. `runtime pointer checks needed` is **not** counted as a legality failure. No remarks recorded (L5) prints `UNKNOWN`, not "legal" |
| no-op check | a candidate that reproduces what the site already carries: `inline` where the attributes already include `inlinehint`, `vectorize_width_N` where a remark already reports `vectorized loop (vectorization width: N)` |

The honesty constraint that shaped the inline-budget line: the state's own
remarks carry real `cost=45 vs threshold=45` and `threshold=250` pairs (for
these functions' *callees*), so a flat "over threshold 225" line would have
contradicted text Jev can see. The line names both LLVM defaults and says
which comparison it is making.

## The numbers

## Per-variant summary

(`V0b`, `V2`, `V11` and `V15` are round 1's rows, recomputed from round 1's log, as comparators. `V11` is there for finding 2b.)

| variant | answers | KEEP_DEFAULT rate | mean confidence | stable sites (3/3 identical) | exact | same family | different |
|---|--:|--:|--:|--:|--:|--:|--:|
| V0b | 27 | 100% | 0.93 | 9/9 | 18 | 0 | 9 |
| V2 | 27 | 78% | 0.59 | 9/9 | 18 | 6 | 3 |
| V11 | 27 | 100% | 0.63 | 9/9 | 18 | 0 | 9 |
| V15 | 27 | 0% | 0.44 | 8/9 | 0 | 8 | 19 |
| W1 | 27 | 67% | 0.63 | 9/9 | 18 | 3 | 6 |
| W2 | 27 | 67% | 0.63 | 9/9 | 18 | 0 | 9 |
| W3 | 27 | 52% | 0.66 | 8/9 | 20 | 0 | 7 |
| W4 | 27 | 0% | 0.63 | 9/9 | 6 | 0 | 21 |
| W5 | 27 | 56% | 0.71 | 9/9 | 18 | 0 | 9 |
| W6 | 27 | 48% | 0.65 | 8/9 | 19 | 0 | 8 |
| W7 | 27 | 56% | 0.66 | 9/9 | 24 | 0 | 3 |

## Choice per site, per variant (modal answer of the repeats; `!` when the three repeats did not agree)

| variant | F1 | F2 | F3 | F4 | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|---|---|---|---|
| **reference** | KEEP_DEFAULT | inline_never | inline_never | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | vectorize_width_16 | KEEP_DEFAULT | KEEP_DEFAULT |
| V0b | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V2 | KEEP_DEFAULT | inline | inline | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V11 | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT |
| V15 | inline | inline | inline | inline | unroll_disable | unroll_disable | vectorize_width_4 ! | unroll_disable | unroll_disable |
| W1 | inline | inline | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | vectorize_width_16 | KEEP_DEFAULT | KEEP_DEFAULT |
| W2 | inline_never | inline_never | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | unroll_count_4 | KEEP_DEFAULT | KEEP_DEFAULT |
| W3 | inline_never | inline_never | inline_never | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | unroll_count_4 | KEEP_DEFAULT ! | KEEP_DEFAULT |
| W4 | inline_never | inline_never | inline_never | inline | unroll_count_2 | unroll_disable | unroll_count_4 | unroll_count_2 | unroll_disable |
| W5 | inline_never | inline_never | inline_never | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | unroll_count_2 | KEEP_DEFAULT |
| W6 | inline_never | inline_never | inline_never | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | unroll_count_4 | unroll_count_2 ! | KEEP_DEFAULT |
| W7 | inline_never | inline_never | inline_never | KEEP_DEFAULT | KEEP_DEFAULT | KEEP_DEFAULT | vectorize_width_16 | KEEP_DEFAULT | KEEP_DEFAULT |

## Does the choice track the site information?

| variant | L3 trip 222, vectorizable | L5 trip 1 | L1/L2/L4 reported illegal to vectorize | F2 10496 insts |
|---|---|---|---|---|
| V0b | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | KEEP_DEFAULT |
| V2 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | inline |
| V11 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | KEEP_DEFAULT |
| V15 | vectorize_width_4 | unroll_disable | 0/9 vector-family answers | inline |
| W1 | vectorize_width_16 | KEEP_DEFAULT | 0/9 vector-family answers | inline |
| W2 | unroll_count_4 | KEEP_DEFAULT | 0/9 vector-family answers | inline_never |
| W3 | unroll_count_4 | KEEP_DEFAULT | 0/9 vector-family answers | inline_never |
| W4 | unroll_count_4 | unroll_disable | 0/9 vector-family answers | inline_never |
| W5 | KEEP_DEFAULT | KEEP_DEFAULT | 0/9 vector-family answers | inline_never |
| W6 | unroll_count_4 | KEEP_DEFAULT | 0/9 vector-family answers | inline_never |
| W7 | vectorize_width_16 | KEEP_DEFAULT | 0/9 vector-family answers | inline_never |

## Where the probability mass sat, not just the argmax

A Choice answer carries a probability for every candidate. The argmax can stay on KEEP_DEFAULT while the mass behind it moves, and that is the sensitive measure of whether a section of the state was read at all. Each cell is the mean probability the repeats put on **anything other than KEEP_DEFAULT**, and, for the loop sites, the mean mass on the vectorize family in parentheses. `W5` has no single
distribution per site, so its row is the mean of the two-candidate
distributions over the pairs that contain `KEEP_DEFAULT`; it is comparable
with the other rows as an ordering and not as a number.

| variant | F1 | F2 | F3 | F4 | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|---|---|---|---|
| V0b | 0.03 | 0.08 | 0.16 | 0.13 | 0.00 (0.00) | 0.00 (0.00) | 0.05 (0.01) | 0.01 (0.00) | 0.02 (0.00) |
| V2 | 0.45 | 0.58 | 0.58 | 0.47 | 0.18 (0.03) | 0.18 (0.02) | 0.45 (0.15) | 0.30 (0.11) | 0.29 (0.05) |
| V11 | 0.53 | 0.54 | 0.52 | 0.29 | 0.07 (0.00) | 0.05 (0.00) | 0.51 (0.09) | 0.18 (0.05) | 0.12 (0.03) |
| V15 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 (0.17) | 1.00 (0.21) | 1.00 (0.31) | 1.00 (0.38) | 1.00 (0.29) |
| W1 | 0.75 | 0.74 | 0.49 | 0.28 | 0.20 (0.00) | 0.17 (0.00) | 0.77 (0.51) | 0.36 (0.01) | 0.18 (0.02) |
| W2 | 0.60 | 0.71 | 0.40 | 0.32 | 0.10 (0.01) | 0.10 (0.01) | 0.71 (0.05) | 0.29 (0.05) | 0.22 (0.02) |
| W3 | 0.81 | 0.85 | 0.57 | 0.21 | 0.14 (0.00) | 0.07 (0.00) | 0.86 (0.21) | 0.56 (0.01) | 0.21 (0.02) |
| W4 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 (0.04) | 1.00 (0.02) | 1.00 (0.22) | 1.00 (0.04) | 1.00 (0.24) |
| W5 | 0.41 | 0.42 | 0.32 | 0.09 | 0.04 (0.01) | 0.01 (0.00) | 0.35 (0.14) | 0.28 (0.01) | 0.04 (0.01) |
| W6 | 0.81 | 0.83 | 0.62 | 0.21 | 0.20 (0.00) | 0.06 (0.00) | 0.86 (0.24) | 0.55 (0.01) | 0.20 (0.02) |
| W7 | 0.82 | 0.83 | 0.60 | 0.21 | 0.20 (0.00) | 0.20 (0.00) | 0.77 (0.51) | 0.39 (0.01) | 0.19 (0.02) |

## The four sites the round-2 question is about

| variant | F2 -> inline_never? | F3 -> inline_never? | L3 -> vectorize_width_16/8? | F4 avoids inline? | the six KEEP sites still KEEP |
|---|---|---|---|---|---|
| V0b | no (KEEP_DEFAULT) | no (KEEP_DEFAULT) | no (KEEP_DEFAULT) | **yes** (KEEP_DEFAULT) | 6/6 |
| V2 | no (inline) | no (inline) | no (KEEP_DEFAULT) | **yes** (KEEP_DEFAULT) | 6/6 |
| V11 | no (KEEP_DEFAULT) | no (KEEP_DEFAULT) | no (KEEP_DEFAULT) | **yes** (KEEP_DEFAULT) | 6/6 |
| V15 | no (inline) | no (inline) | no (vectorize_width_4) | no (inline) | 0/6 |
| W1 | no (inline) | no (KEEP_DEFAULT) | **yes** (vectorize_width_16) | **yes** (KEEP_DEFAULT) | 5/6 |
| W2 | **yes** (inline_never) | no (KEEP_DEFAULT) | no (unroll_count_4) | **yes** (KEEP_DEFAULT) | 5/6 |
| W3 | **yes** (inline_never) | **yes** (inline_never) | no (unroll_count_4) | **yes** (KEEP_DEFAULT) | 5/6 |
| W4 | **yes** (inline_never) | **yes** (inline_never) | no (unroll_count_4) | no (inline) | 0/6 |
| W5 | **yes** (inline_never) | **yes** (inline_never) | no (KEEP_DEFAULT) | **yes** (KEEP_DEFAULT) | 4/6 |
| W6 | **yes** (inline_never) | **yes** (inline_never) | no (unroll_count_4) | **yes** (KEEP_DEFAULT) | 4/6 |
| W7 | **yes** (inline_never) | **yes** (inline_never) | **yes** (vectorize_width_16) | **yes** (KEEP_DEFAULT) | 5/6 |

## The decision-71 readout: which site would be tried first, and with which hint

Sites ranked by `1 - P(KEEP_DEFAULT)` averaged over the repeats; the hint is that site's own highest-probability non-`KEEP` candidate, also averaged over the repeats.

| variant | first site | its best non-KEEP hint | 1-P(KEEP) | second site | reference pick at the first site |
|---|---|---|--:|---|---|
| V0b | F3 | `inline` | 0.16 | F4 | `inline_never` |
| V2 | F3 | `inline` | 0.58 | F2 | `inline_never` |
| V11 | F2 | `inline` | 0.54 | F1 | `inline_never` |
| V15 | n/a --- no KEEP_DEFAULT candidate in this variant | | | | |
| W1 | L3 | `vectorize_width_16` | 0.77 | F1 | `vectorize_width_16` |
| W2 | L3 | `unroll_count_4` | 0.71 | F2 | `vectorize_width_16` |
| W3 | L3 | `unroll_count_4` | 0.86 | F2 | `vectorize_width_16` |
| W4 | n/a --- no KEEP_DEFAULT candidate in this variant | | | | |
| W5 | F2 | `inline_never` | 0.42 | F1 | `inline_never` |
| W6 | L3 | `unroll_count_4` | 0.86 | F2 | `vectorize_width_16` |
| W7 | F2 | `inline_never` | 0.83 | F1 | `inline_never` |

## W5: every pairwise answer

| site | pair | winner (3 repeats) |
|---|---|---|
| F1 | `inline` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| F1 | `inline` vs `inline_never` | `inline_never`, `inline_never`, `inline_never` |
| F1 | `inline_never` vs `KEEP_DEFAULT` | `inline_never`, `inline_never`, `inline_never` |
| F2 | `inline` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| F2 | `inline` vs `inline_never` | `inline_never`, `inline_never`, `inline_never` |
| F2 | `inline_never` vs `KEEP_DEFAULT` | `inline_never`, `inline_never`, `inline_never` |
| F3 | `inline` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| F3 | `inline` vs `inline_never` | `inline_never`, `inline_never`, `inline_never` |
| F3 | `inline_never` vs `KEEP_DEFAULT` | `inline_never`, `inline_never`, `inline_never` |
| F4 | `inline` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| F4 | `inline` vs `inline_never` | `inline`, `inline`, `inline` |
| F4 | `inline_never` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| L1 | `unroll_count_4` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| L1 | `vectorize_width_8` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| L1 | `vectorize_width_8` vs `unroll_count_4` | `unroll_count_4`, `unroll_count_4`, `unroll_count_4` |
| L2 | `unroll_count_4` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| L2 | `vectorize_width_4` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| L2 | `vectorize_width_4` vs `unroll_count_4` | `unroll_count_4`, `unroll_count_4`, `unroll_count_4` |
| L3 | `unroll_count_8` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| L3 | `vectorize_width_16` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| L3 | `vectorize_width_16` vs `unroll_count_8` | `vectorize_width_16`, `vectorize_width_16`, `vectorize_width_16` |
| L4 | `unroll_count_2` vs `KEEP_DEFAULT` | `unroll_count_2`, `unroll_count_2`, `unroll_count_2` |
| L4 | `vectorize_width_16` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| L4 | `vectorize_width_16` vs `unroll_count_2` | `unroll_count_2`, `unroll_count_2`, `unroll_count_2` |
| L5 | `unroll_count_2` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| L5 | `vectorize_width_4` vs `KEEP_DEFAULT` | `KEEP_DEFAULT`, `KEEP_DEFAULT`, `KEEP_DEFAULT` |
| L5 | `vectorize_width_4` vs `unroll_count_2` | `unroll_count_2`, `unroll_count_2`, `unroll_count_2` |

## API reliability (round 2 only)

- requests attempted 43, answered 42, never answered 1
- HTTP attempts 104 for 43 requests (2.42 per request); 61 were retries after a retryable status
- questions answered 243
- latency ms: total 39822, mean 948, median 930, max 1540
- tokens in/out 631380 / 22692
- cost billed $0.00000000, list price $0.02651796
- requests that never answered, by status: 503 x1

## One request and response per variant

Each block is repeat 1 of that variant at the site where the variant's story is --- `L3` for the loop-side variants, `F2` for `W2` and `W5`. The full request bodies are in `round2/requests.jsonl`, keyed by the `request_sha` of each log line.

### W1

request `W1-L1-L2-L3-L4-L5`: state 22671 chars, 5 question(s); question `q2` (L3):

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?

Mechanical readings for this site. Each line is produced by a tool from the numbers and the compiler remarks already in the state, by the same rule at every site in this request; none of them is an opinion about which hint to choose.
  - average trip count: 221.7; trip class long (rule: <2 degenerate, <16 short, <100 medium, >=100 long)
  - body size: 13 LLVM instructions; size class tiny (rule: <50 tiny, <300 small, <1000 medium, <2000 large, >=2000 very large)
  - calls inside the body: no; loop nesting depth 1; loops this site key names: 1
  - element type at the loop's iterator: u8 (read off the inline chain); one 256-bit vector register holds 32 of them, so the widest `vectorize.width` in this list that fits one register is 16 (the list stops at 16)
  - vectorisation legality, from the baseline remarks at this line: LEGAL --- the remarks include `vectorized loop (vectorization width: 4)`, i.e. LLVM already vectorises this line without any hint
  - no-op check: the width already in effect is 4, so the candidate `vectorize_width_4` reproduces the state this site is already in
  - cost model, from the baseline remarks at this line: vectorization not beneficial
  - caveat that applies to every loop here: remarks are attributed by source location only, so several loops can share one line
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "vectorize_width_16",
 "confidence": 0.47,
 "probabilities": {
  "KEEP_DEFAULT": 0.21,
  "interleave_count_1": 0.02,
  "interleave_count_2": 0.01,
  "interleave_count_4": 0.01,
  "unroll_count_2": 0.05,
  "unroll_count_4": 0.04,
  "unroll_count_8": 0.13,
  "unroll_disable": 0.01,
  "vectorize_width_16": 0.5,
  "vectorize_width_2": 0,
  "vectorize_width_4": 0.01,
  "vectorize_width_8": 0.01
 },
 "type": "choice"
}
```

### W2

request `W2-F1-F2-F3-F4`: state 25623 chars, 4 question(s); question `q1` (F2):

```
Section `q1` of the state describes one marked function of this program. Which single hint from the list is most likely to make this function faster on this workload?
criteria: KEEP_DEFAULT, align_16, align_32, align_64, cold, inline, inline_never
```

response:

```json
{
 "choice": "inline_never",
 "confidence": 0.63,
 "probabilities": {
  "KEEP_DEFAULT": 0.27,
  "align_16": 0,
  "align_32": 0,
  "align_64": 0,
  "cold": 0,
  "inline": 0.04,
  "inline_never": 0.68
 },
 "type": "choice"
}
```

### W3

request `W3-L1-L2-L3-L4-L5`: state 22671 chars, 5 question(s); question `q2` (L3):

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?

Mechanical readings for this site. Each line is produced by a tool from the numbers and the compiler remarks already in the state, by the same rule at every site in this request; none of them is an opinion about which hint to choose.
  - average trip count: 221.7; trip class long (rule: <2 degenerate, <16 short, <100 medium, >=100 long)
  - body size: 13 LLVM instructions; size class tiny (rule: <50 tiny, <300 small, <1000 medium, <2000 large, >=2000 very large)
  - calls inside the body: no; loop nesting depth 1; loops this site key names: 1
  - element type at the loop's iterator: u8 (read off the inline chain); one 256-bit vector register holds 32 of them, so the widest `vectorize.width` in this list that fits one register is 16 (the list stops at 16)
  - vectorisation legality, from the baseline remarks at this line: LEGAL --- the remarks include `vectorized loop (vectorization width: 4)`, i.e. LLVM already vectorises this line without any hint
  - no-op check: the width already in effect is 4, so the candidate `vectorize_width_4` reproduces the state this site is already in
  - cost model, from the baseline remarks at this line: vectorization not beneficial
  - caveat that applies to every loop here: remarks are attributed by source location only, so several loops can share one line
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "unroll_count_4",
 "confidence": 0.33,
 "probabilities": {
  "KEEP_DEFAULT": 0.12,
  "interleave_count_1": 0.01,
  "interleave_count_2": 0,
  "interleave_count_4": 0.02,
  "unroll_count_2": 0.12,
  "unroll_count_4": 0.39,
  "unroll_count_8": 0.1,
  "unroll_disable": 0.01,
  "vectorize_width_16": 0.21,
  "vectorize_width_2": 0,
  "vectorize_width_4": 0,
  "vectorize_width_8": 0.02
 },
 "type": "choice"
}
```

### W4

request `W4-L1-L2-L3-L4-L5`: state 22614 chars, 5 question(s); question `q2` (L3):

```
Section `q2` of the state describes one loop inside a marked function of this program. We are going to try exactly one hint on it in the next build. Which of these is the most promising for making this loop faster on this workload?

Mechanical readings for this site. Each line is produced by a tool from the numbers and the compiler remarks already in the state, by the same rule at every site in this request; none of them is an opinion about which hint to choose.
  - average trip count: 221.7; trip class long (rule: <2 degenerate, <16 short, <100 medium, >=100 long)
  - body size: 13 LLVM instructions; size class tiny (rule: <50 tiny, <300 small, <1000 medium, <2000 large, >=2000 very large)
  - calls inside the body: no; loop nesting depth 1; loops this site key names: 1
  - element type at the loop's iterator: u8 (read off the inline chain); one 256-bit vector register holds 32 of them, so the widest `vectorize.width` in this list that fits one register is 16 (the list stops at 16)
  - vectorisation legality, from the baseline remarks at this line: LEGAL --- the remarks include `vectorized loop (vectorization width: 4)`, i.e. LLVM already vectorises this line without any hint
  - no-op check: the width already in effect is 4, so the candidate `vectorize_width_4` reproduces the state this site is already in
  - cost model, from the baseline remarks at this line: vectorization not beneficial
  - caveat that applies to every loop here: remarks are attributed by source location only, so several loops can share one line
criteria: interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "unroll_count_4",
 "confidence": 0.44,
 "probabilities": {
  "interleave_count_1": 0.02,
  "interleave_count_2": 0.01,
  "interleave_count_4": 0.01,
  "unroll_count_2": 0.11,
  "unroll_count_4": 0.49,
  "unroll_count_8": 0.15,
  "unroll_disable": 0.01,
  "vectorize_width_16": 0.16,
  "vectorize_width_2": 0,
  "vectorize_width_4": 0.02,
  "vectorize_width_8": 0.02
 },
 "type": "choice"
}
```

### W5

request `W5-F1-F2-F3-F4`: state 27439 chars, 12 question(s); question `q1_inline__KEEP_DEFAULT` (F2):

```
Section `q1` of the state describes one marked function of this program. Exactly two options are on the table in this question, and only these two. Which of the two is more likely to make this function faster on this workload?

Mechanical readings for this site. Each line is produced by a tool from the numbers and the compiler remarks already in the state, by the same rule at every site in this request; none of them is an opinion about which hint to choose.
  - body size: 10496 LLVM instructions after LTO
  - size class: very large (rule: <50 tiny, <300 small, <1000 medium, <2000 large, >=2000 very large)
  - distinct copies in the binary: 62 monomorphization(s); copy class many (rule: 1 single, 2-8 few, >=9 many)
  - inline budget: LLVM's defaults are -inline-threshold=225 and -inlinehint-threshold=325 cost units; body instructions / -inlinehint-threshold=325 = 32x over (an order-of-magnitude comparison, not an InlineCost computation --- the cost=/threshold= pairs in the remarks above are the real ones, and they are about this function's callees)
  - attributes already on it: cold | inlinehint | inlinehint,cold
  - no-op check: some copies already carry `inlinehint`, so the candidate `inline` reproduces, on those copies, the state this site is already in
  - no-op check: `cold` already appears among the attribute sets this site carries
  - share of the program's user cycles: 8.32%; hotness class very hot (rule: <1% not hot, 1-5% hot, >=5% very hot)
  - loop sites inside it: 15
criteria: KEEP_DEFAULT, inline
```

response:

```json
{
 "choice": "KEEP_DEFAULT",
 "confidence": 0.85,
 "probabilities": {
  "KEEP_DEFAULT": 0.92,
  "inline": 0.08
 },
 "type": "choice"
}
```

### W6

request `W6-L1-L2-L3-L4-L5`: state 22671 chars, 5 question(s); question `q2` (L3):

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?

Mechanical readings for this site. Each line is produced by a tool from the numbers and the compiler remarks already in the state, by the same rule at every site in this request; none of them is an opinion about which hint to choose.
  - average trip count: 221.7; trip class long (rule: <2 degenerate, <16 short, <100 medium, >=100 long)
  - body size: 13 LLVM instructions; size class tiny (rule: <50 tiny, <300 small, <1000 medium, <2000 large, >=2000 very large)
  - calls inside the body: no; loop nesting depth 1; loops this site key names: 1
  - element type at the loop's iterator: u8 (read off the inline chain); one 256-bit vector register holds 32 of them, so the widest `vectorize.width` in this list that fits one register is 16 (the list stops at 16)
  - vectorisation legality, from the baseline remarks at this line: LEGAL --- the remarks include `vectorized loop (vectorization width: 4)`, i.e. LLVM already vectorises this line without any hint
  - no-op check: the width already in effect is 4, so the candidate `vectorize_width_4` reproduces the state this site is already in
  - cost model, from the baseline remarks at this line: vectorization not beneficial
  - caveat that applies to every loop here: remarks are attributed by source location only, so several loops can share one line
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "unroll_count_4",
 "confidence": 0.34,
 "probabilities": {
  "KEEP_DEFAULT": 0.12,
  "interleave_count_1": 0.01,
  "interleave_count_2": 0,
  "interleave_count_4": 0.02,
  "unroll_count_2": 0.11,
  "unroll_count_4": 0.4,
  "unroll_count_8": 0.08,
  "unroll_disable": 0.01,
  "vectorize_width_16": 0.23,
  "vectorize_width_2": 0,
  "vectorize_width_4": 0,
  "vectorize_width_8": 0.02
 },
 "type": "choice"
}
```

### W7

request `W7-L1-L2-L3-L4-L5`: state 22671 chars, 5 question(s); question `q2` (L3). Its loop phase is W1's, so the verdict block is there and the option descriptions are the frozen ones; its function phase is W3's.

```
Section `q2` of the state describes one loop inside a marked function of this program. Which single hint from the list is most likely to make this loop faster on this workload?

Mechanical readings for this site. Each line is produced by a tool from the number [...]
criteria: KEEP_DEFAULT, interleave_count_1, interleave_count_2, interleave_count_4, unroll_count_2, unroll_count_4, unroll_count_8, unroll_disable, vectorize_width_16, vectorize_width_2, vectorize_width_4, vectorize_width_8
```

response:

```json
{
 "choice": "vectorize_width_16",
 "confidence": 0.44,
 "probabilities": {
  "KEEP_DEFAULT": 0.25,
  "interleave_count_1": 0.01,
  "interleave_count_2": 0,
  "interleave_count_4": 0.01,
  "unroll_count_2": 0.06,
  "unroll_count_4": 0.03,
  "unroll_count_8": 0.12,
  "unroll_disable": 0.01,
  "vectorize_width_16": 0.49,
  "vectorize_width_2": 0,
  "vectorize_width_4": 0.01,
  "vectorize_width_8": 0.01
 },
 "type": "choice"
}
```


### W3, the function side --- where `inline(never)` comes from

request `W3-F1-F2-F3-F4`: state 27439 chars, 4 question(s); question `q1` (F2):

```
Section `q1` of the state describes one marked function of this program. Which single hint from the list is most likely to make this function faster on this workload?

Mechanical readings for this site. Each line is produced by a tool from the numbers and the compiler remarks already in the state, by the same rule at every site in this request; none of them is an opinion about which hint to choose.
  - body size: 10496 LLVM instructions after LTO
  - size class: very large (rule: <50 tiny, <300 small, <1000 medium, <2000 large, >=2000 very large)
  - distinct copies in the binary: 62 monomorphization(s); copy class many (rule: 1 single, 2-8 few, >=9 many)
  - inline budget: LLVM's defaults are -inline-threshold=225 and -inlinehint-threshold=325 cost units; body instructions / -inlinehint-threshold=325 = 32x over (an order-of-magnitude comparison, not an InlineCost computation --- the cost=/threshold= pairs in the remarks above are the real ones, and they are about this function's callees)
  - attributes already on it: cold | inlinehint | inlinehint,cold
  - no-op check: some copies already carry `inlinehint`, so the candidate `inline` reproduces, on those copies, the state this site is already in
  - no-op check: `cold` already appears among the attribute sets this site carries
  - share of the program's user cycles: 8.32%; hotness class very hot (rule: <1% not hot, 1-5% hot, >=5% very hot)
  - loop sites inside it: 15

criteria (the enriched descriptions of `inline` and `inline_never`; the other five are in `jev_state_variants.py`):
  inline: Add the `inlinehint` attribute (the SPEC vocabulary's `inline`). It raises the inliner's threshold for this function, so callers that were just over the limit paste its body in. It tends to help a small hot leaf (roughly under 300 instructions) called from few hot sites, where the caller then specialises on what it passes. It tends to hurt a large body (a thousand instructions and up) and a function with many monomorphized copies, because every pasted copy costs instruction cache. It is a no-op where the function already carries the attribute.
  inline_never: Add the `noinline` attribute (the SPEC vocabulary's `inline(never)`). The function stays one out-of-line copy: call overhead is paid at every call site and the callers stay small. It tends to help a very large body (thousands of instructions) or a function with many monomorphized copies, by stopping code growth and instruction-cache pressure --- especially where an `inlinehint` is already asking the inliner to paste that body in. It tends to hurt a small hot leaf, where the call overhead is the bulk of the cost. It is a no-op where the body is already too large for any caller's threshold.
```

response:

```json
{
 "choice": "inline_never",
 "confidence": 0.78,
 "probabilities": {
  "KEEP_DEFAULT": 0.14,
  "align_16": 0,
  "align_32": 0,
  "align_64": 0,
  "cold": 0,
  "inline": 0.04,
  "inline_never": 0.81
 },
 "type": "choice"
}
```

## What moved, and which idea moved it

**1. For the first time in the study, a framing beats "answer
`KEEP_DEFAULT` everywhere".** Round 1's exact agreement peaked at 18/27,
which is exactly the score of knowing nothing and answering `KEEP_DEFAULT`
nine times. W3 scores **20/27** and W6, the identical request asked again,
scores 19/27. On the modal answer W3 is **7/9**, and the two cells it misses
are `F1` (it says `inline_never`, the reference says leave it alone) and
`L3`.

**2. Idea B --- the option descriptions --- is what produced
`inline(never)`.** W2 is V2 plus nothing but rewritten `criteria` text, and
it turns `TermId::run` from `inline` into `inline_never`; W3 adds the verdict
block and `write::write` follows. Round 1 called Jev choosing `inline` at the
two largest bodies in the set "the sharpest failure in the study". It is
gone: every variant carrying the enriched descriptions (W2, W3, W4, W5, W6)
answers `inline_never` at both `F2` and `F3`, in every repeat, at confidence
up to 0.78 --- the reference pick at both sites, which round 1 hit twice in
486 cells.

**2b. The same words in a different place give the opposite answer, and this
revises a round-1 rule.** Round 1's V11 put a hint guide in the state and got
100% `KEEP_DEFAULT`; its paragraph on `inline` is very nearly word for word
`ENRICHED_FN["inline"]`. W2 puts that content inside the `criteria`
descriptions instead and gets `inline_never` at `F2`. Same knowledge, same
vocabulary, two placements, opposite results --- and it is the sharpest thing
this study has to say about *where* Jev reads: a prose block beside the state
makes it cautious, the description attached to the option it is choosing
between makes it discriminate. Round 1's standing rule was "do not put the
hint guide into the shipped state (V11, V13, V14)". That rule survives for
V13 and V14, which are measured results and Claude's reasoning; for V11's
generic mechanism text it is **revised**: the content is fine, the placement
was wrong. The `criteria` are where the vocabulary is defined anyway, which is
also why this does not smuggle Claude back into the loop --- the text is the
same at every site and names none of them.

**3. Idea A --- the verdict block --- is what produced
`vectorize.width=16`.** W1 answers `vectorize_width_16` at `L3` in **all
three repeats** (P = 0.50, confidence 0.47). No framing in round 1 ever
returned it, in any repeat, including the two that were given the ymm width
and the trip count as a table (V7, V15). The difference is not the
information --- V8 already carried `trip 221.7` and V7 already carried "one
ymm holds 32 x u8" --- but that W1 states the join as a finished reading
next to the question: *element type u8 -> one register holds 32 -> the widest
width in this list that fits is 16*. Jev does not do that arithmetic; it does
act on it once it is done.

**4. The two ideas interfere at `L3`.** W1 (verdicts only) gets `L3` right;
W3 and W6 (verdicts + enriched descriptions) move it to `unroll_count_4`, and
W2 (descriptions only) does the same. The enriched `unroll.count=4` text
--- "a short body (tens of instructions) with a trip count in the hundreds"
--- describes `L3` exactly, and it wins against a width hint whose own text
warns about overshooting the register. The intervention that fixed the
function side broke the one loop the study cares about.

**5. The two halves are separate HTTP requests, so the two ideas can be
kept apart.** Functions and loops ride in one request
each. Taking **W3's function request and W1's loop request** --- both sent,
neither invented --- gives:

| | F1 | F2 | F3 | F4 | L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|---|---|---|---|
| reference | KEEP | `inline_never` | `inline_never` | KEEP | KEEP | KEEP | `vectorize_width_16` | KEEP | KEEP |
| W3 fn + W1 loop | `inline_never` | `inline_never` | `inline_never` | KEEP | KEEP | KEEP | `vectorize_width_16` | KEEP | KEEP |

**8/9 exact, identical in all three repeats.** `W7` then asked that exact
combination as a variant of its own, entered in the code and committed before
its six requests were sent, and reproduced it: **8/9 in every one of three
repeats, 24/27**, the highest in the study by four cells. The only
disagreement left in the whole set is `F1`, where Jev says `inline(never)` and the reference says
leave it alone --- and the reference's own reasoning for `F1` ("it would
fight the specialisation that makes this the inline host for `seq`,
`str_fold` and `write_until`") is the one argument in the nine that rests on
something no verdict line carries.

**6. Forcing now lands on the right hints where a hint has a mechanism, and
invents one everywhere else.** W4 is no longer a constant: round 1's forced
variants answered `inline` at all four functions, and W4 answers
`inline_never` at three of them and `inline` at exactly the one small hot
leaf (`F4`, 251 instructions). That is the *shape* discrimination round 1
could not get at any price. But forcing still scores 6/27, because six of the
nine reference picks are "leave it alone" and W4 cannot say it. **The answer
to the user's question is: forcing now gets the right hint, but only at the
sites that deserve one, and forcing is still the wrong way to ask** --- W3
gets those same two sites right *and* keeps the six KEEP sites.

**7. Pairwise (W5) is the cleanest diagnostic and the worst proposer.** Every
hint the round-robin put head to head against `KEEP_DEFAULT` lost, at all
nine sites but one (`L4`, where `unroll.count=2` beat KEEP in all three
repeats and the derived winner is therefore wrong). But the hint-against-hint
pairs are decided sharply and correctly: `inline_never` beats `inline` at
`F1`/`F2`/`F3` and loses to it at `F4`, and `vectorize_width_16` beats
`unroll_count_8` at `L3` while losing to KEEP. So Jev **can** rank the hints
by shape; what it will not do is prefer any of them to doing nothing. W5's
mean confidence, 0.71, is the highest of the round, which is the signature of
an easy question rather than a well-answered one.

**8. Legality discrimination went from good to essentially perfect.** The
mean vectorize-family probability mass at the three loops LLVM reports as
impossible to vectorize: V2 0.056, W2 0.021, **W1 0.003, W3 0.003, W6
0.004**. Restating the remark as a verdict line (`NOT VECTORIZABLE --- ... A
vectorize.width hint is not a permission slip`) drains the mass that round 1
still found there, and no W variant chose a vector-family hint at those three
loops in any repeat (0/9 per variant, as in round 1).

**9. The readout of decision 71 now proposes hints the reference agrees
with.** Ranked by `1 - P(KEEP_DEFAULT)`, round 1's V2 would have tried
`write::write` first with `inline` --- the opposite of the reference pick at
that site. Under W1 the top of the list is `L3` at 0.77 with
`vectorize_width_16`, which is the reference pick. Under W3 and W6 the top is
a **tie and should be reported as one**: L3 0.86 against F2 0.85 in W3, L3
0.86 against F2 0.83 in W6. Under the recommended `W7` the order is F2 0.83,
F1 0.82, L3 0.77, so the first hint it would try is `inline_never` at
`TermId::run` --- also a reference pick, and the second is the one cell
where Jev and the reference still disagree. Either way the rule now produces
a first move that is defensible, which round 1's did not.

**10. Repeatability.** W3 and W6 are the same request sent three times each,
six repeats in total. Their modal answers agree at 8 of 9 sites; the one
disagreement is `L4`, which was unstable within both triples. Everything else
in this round is stable 3/3.

## Recommendation

**Ship the verdict block and the enriched descriptions, and keep them apart
at the loop sites.**

1. **Adopt the verdict block (idea A) for both phases.** It is a tool, not a
   judgement: the rules are eight lines of thresholds applied uniformly, and
   they are auditable in a way a prose guide is not. It is what produces
   `vectorize.width=16` at the one site with a mechanism, it sharpens legality
   to 0.003, and it moves the decision-71 ranking onto sites whose reference
   pick is a hint rather than "leave it alone".
2. **Adopt the enriched descriptions (idea B) for the function phase.** They
   are what ends round 1's sharpest failure --- `inline` on the two largest
   bodies in the program --- and they cost nothing but `criteria` text.
3. **Do not adopt them for the loop phase yet.** W1 against W3 is the
   measurement: the loop descriptions cost the `L3` pick. The state to ship
   is **`W7`** --- W3's function phase, W1's loop phase --- which scored 8/9
   exact in all three repeats as a pre-committed variant. If the loop
   descriptions are wanted later, the `unroll.count=4` text is the line to
   rewrite, not the idea.
   This revises round 1's "do not put the hint guide into the shipped state"
   for the generic mechanism text only, and finding 2b is the reason: the
   objection was never to the content but to a prose block that made Jev
   uniformly cautious. Measured results (V13) and Claude's reasoning (V14)
   stay out, as before.
4. **Keep `KEEP_DEFAULT`, and keep reading the probabilities.** W4 is the
   third forced variant in this study to score worst of its round. The
   decision-71 readout does the job forcing was meant to do without deleting
   the option: under `W7` it would try `inline(never)` at `TermId::run`
   first (0.83) and `vectorize.width=16` at the byte loop third (0.77), both
   of which are reference picks.
5. **Do not use pairwise.** W5 needs three requests' worth of questions for a
   result that is `KEEP_DEFAULT` wherever `KEEP_DEFAULT` is on the ballot.

### What this does not settle

The reference picks are still Claude's judgement, not measurements. Round 2
moved Jev's answers onto them at `F2`, `F3` and `L3`; whether those three are
*right* is the oracle sweep's question, not this study's. Note the direction
of the risk: round 1 ended with Jev saying "leave everything alone" and the
open possibility that Jev was closer than Claude. Round 2 has taught Jev to
say what Claude says, which is worth exactly as much as Claude's picks turn
out to be worth --- and `F1`, where Jev now proposes `inline(never)` on the
function holding 29% of the cycles, is the cell to watch.

### Limits

* Idea A and idea B were each tested once, as a block. Which verdict line
  carries W1's `L3` result, and which description carries W2's
  `inline_never`, is not separated here.
* W2 carries no platform block (W1 and W3 do), so W1-against-W2 is not a
  clean A-against-B comparison. V7 from round 1 is the control that says the
  platform block changes no modal answer, which is why the comparison is
  still made.
* The `L3` reference pick still rests on a remark attributed by source line
  only, and `macros.rs:279` carries several. The verdict block repeats that
  caveat at every loop rather than hiding it.
* **The thresholds and the phrasings were written by someone who had already
  seen these nine sites.** `<300` for a small function, `>=2000` for a very
  large one, `>=100` for a long trip, 5% for very hot, and phrases such as "a
  trip count in the hundreds" are round numbers, applied by one rule to all
  nine sites and never per site --- but the person choosing the round numbers
  knew what the nine sites look like. Finding 4 is the evidence that this
  matters: the `unroll.count=4` text "describes `L3` exactly", and that is
  not a coincidence to be proud of. This is the same criticism round 1
  levelled at V11 and V14, and relocating the text into `criteria` does not
  escape it. The only real validation is sites that were not in view when the
  rules were written, and this study does not have any.
* `scripts/jev_prompt_study.py` writes `"study": "prompt-study-v1-2026-09-22"`
  into every log row, including round 2's, while the round-2 state header
  says `prompt-study-r2-2026-09-22`. The variant name and the separate
  `round2/` directory are what distinguish the rounds; the log field is
  stale and was not worth a re-run.
* 43 requests, one program, one day. Everything above is a count.
