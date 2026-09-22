# Jev on hintbench: the state's evidence repaired, and vocabulary v4

Run 2026-09-22, **API only**: no build, no timing, no plugin invocation. The
hintbench oracle sweep owned the CPU throughout; this file cost twelve
answered HTTP requests and 53 + 27 seconds of wall clock.

It continues `docs/experiments/hintbench/jev-oneshot-v3.md`, whose two passes
ended at decision 82: with the kernels' doc comments stripped out of the
state, Jev's one-shot agreement with `targets/hintbench/EXPECTED.md` fell from
10 of 12 to 7 of 12, `inline_always` became the best non-`KEEP_DEFAULT`
candidate at **all eight** function sites in all three repeats, and every
function confidence collapsed into 0.34--0.48. Decision 82 named two suspects
and asked for them to be separated:

* **(a) the state's evidence.** Three defects were recorded in sections 5 and
  14 of that file: the legality verdict line said NOT VECTORIZABLE at three of
  four loop sites that the baseline vectorises, k2's decisive
  `cost=870 > threshold=787` was nowhere in the state while an invented
  `inline budget` line said the opposite, and a placeholder profile share was
  classified `very hot` at all eight marks.
* **(b) the descriptions.** v3 argues for `inline_always` and `inline_never`
  at about 130 words each, with applicability conditions, and mentions the
  three alignments in about 35 words of v1 prose with none.

This pass fixes (a), calls the result **v3 + fixed state** (state format
`state-v3.1-2026-09-22`, vocabulary `v3-2026-09-22` unchanged to the byte),
then fixes (b) as **v4** (`v4-2026-09-22`, state `state-v4-2026-09-22`) and
runs both. The two runs differ in exactly the six function descriptions, at the eight
function sites --- 48 rendered lines on each side, 360 characters in all,
and nothing else but the two version strings --- so the comparison isolates
(b), and the comparison of either against pass 2 isolates (a).

Nothing here is a speed claim. Whether EXPECTED or Jev is *right* is the
oracle's question.

* logs: `jev-oneshot-v3-pass3.jsonl` and `jev-oneshot-v4.jsonl` in this
  directory (full request and response bodies, one line per HTTP call
  including the two that were exhausted); the matching `*.log` files are
  git-ignored repo-wide, as before.
* harness: `scripts/jev_oneshot.py`, committed with this file. Passes 1 and 2
  were driven by a throwaway script; this one is in the repository so the
  run can be repeated. It drives the driver's own objects --- the site lists,
  the state, the questions, the batching, the candidate validation, the
  confidence gate and the decision-71 readout are all `scripts/jev_search.py`
  code, reached through `JevProposer.choose()`.
* **the caveat of section 1 of the v3 file still applies**: this pass builds
  nothing, so phase B is asked against the *baseline* dump's loop sites and
  is told `function attributes this round already applied: none`. That is
  round 1 of a run whose phase A answered KEEP_DEFAULT everywhere, which is
  not what phase A answered here.

---

## 1. Part (a): what the state now says

Three changes in `scripts/jev_search.py`, all of them in the evidence and
none in the wording, the candidates or the questions. They render for v3 and
v4 only: `--vocab v1` and `--vocab v2` were checked to produce a
byte-identical `--print-state` before and after.

### 1a. A loop's legality comes from that loop's own location

Before, the verdict line was built from `RemarkBook.near(leaf, span=10)`: a
±10-line window. A `for &x in slice` loop's leaf is
`library/core/src/slice/iter/macros.rs:180:28` and a `for i in a..b` loop's is
`library/core/src/iter/range.rs:1103:12`, so the window collected the remarks
of every such loop in the program.

Now the line is built from `RemarkBook.at(file, line, col)` --- exactly this
loop's leaf, column included --- and from a second, mechanical question:
**how many loops does the log report at that location?** LoopVectorize emits
one verdict per loop it looks at, either `vectorized loop (vectorization
width: N, ...)` or the bare `loop not vectorized` missed-remark that
accompanies the `loop not vectorized: <reason>` analysis. Counting those
lines *before* dedup counts the loops. One means the remarks there are this
loop's; more than one means they are several loops' and cannot be split.

| loop site | leaf | verdicts at that leaf | legality line now |
|---|---|---|---|
| k5 reduction | `macros.rs:180:28` | **17** | `UNKNOWN (shared source line; remarks not attributable to this loop)` |
| k4 byte count | `macros.rs:180:28` | **17** | `UNKNOWN (shared source line; ...)` |
| k8 control | `range.rs:1103:12` | **18** | `UNKNOWN (shared source line; ...)` |
| k3 fill | `lib.rs:174:9` | **1** | `NOT VECTORIZABLE --- value that could not be identified as reduction is used outside the loop` |

The fourth row is the point of the exercise: the rule does not refuse to
answer, it refuses to answer where the log cannot. k3's leaf is the kernel's
own line, one loop is compiled there, and the verdict that comes out matches
EXPECTED §2b (`lib.rs:173`/`174`, "loop not vectorized", runtime unroll by 8)
independently.

The remark block quoted in the state section is narrowed the same way, and
where the location is shared it now carries a header saying so:

```
what LLVM said at macros.rs:180:28 in the baseline build --- CAUTION: 17
different loops of this program were compiled at that one location, so the
lines below are their remarks pooled together and none of them can be
assigned to this loop:
```

**The plugin's dump is stated as the primary source**, because it records a
loop rather than a source line, and one new verdict line carries what it
knows --- and only what it knows:

```
  - from the plugin's dump, which is the primary source here because it
    records this loop and not a source line: trip count 16384.1, calls in the
    body no, `llvm.loop.isvectorized` metadata at the point the hint is
    attached: no --- the hint goes in before LoopVectorize runs, so `no` is
    the normal reading and says nothing about whether LLVM vectorises this
    loop afterwards
```

That clause matters. Section 5 of the v3 file read
`already vectorized when the hint is attached: no` at the k4 site as a fourth
symptom of the attribution defect. It is not one: `plugin/jev/jev.cpp:1127`
tests `llvm.loop.isvectorized` at `VectorizerStartEP`, i.e. **before**
LoopVectorize runs in this pipeline, so `false` is the answer at all 14
hintbench loop sites including the three the baseline vectorises. The old
line invited the wrong reading; the new one says what the field means.

*What this fix loses.* It is true that LLVM vectorises k4, k5 and k8 at
VF 8 × IC 4. That fact is in the build log and it is **not recoverable by
source location** --- which is exactly what `UNKNOWN` says. Section 4 below
shows what Jev does with the honest gap, and it is not comfortable.

### 1b. A function's verdict quotes the inliner instead of estimating it

An inline remark is located at the **call site**, a line in the caller, so a
lookup around the callee's own definition never finds it. On hintbench that
meant the k2 section quoted `std`'s backtrace machinery and the string `870`
did not occur anywhere in either phase's state, while the verdict block
asserted *"body instructions / -inline-threshold=225 = 0.8x, i.e. the body
fits inside that budget"*.

The new `InlineBook` parses the log's inline remarks by **callee symbol** ---
`'C' inlined into 'K' with (cost=N, threshold=M)`, `... not inlined into ...
because too costly to inline (cost=N, threshold=M)`, `... because it should
never be inlined (cost=never): <reason>`, and the AlwaysInliner's
`always inline attribute at callsite` --- joins them to the mark's linkage
names from the dump, and aggregates. Identical lines are deduplicated,
because a build log holds the pre-link compilation and the LTO one and can
print the same decision twice (no line of hintbench's eight marks is
affected either way). The `inline budget` line is **gone**;
the size class line stays. What the eight hintbench marks now read:

| mark | verdict line (the part after "in the baseline,") | EXPECTED §2a |
|---|---|---|
| `k1_step` | 8 call sites inlined (cost=640 vs threshold=787 at 7 of them, cost=-14360 vs threshold=787); 0 declined | 640/787, inlined at all 8 |
| `k2_mix` | **0 call sites inlined; 2 call sites declined as too costly (cost=870 > threshold=787 at 2 of them)** | **870/787, not inlined, 2 call sites** |
| `k3_fill_run` | 1 call site inlined (cost=-14955 vs threshold=525); 0 declined | -14955/525 |
| `k4_count_bytes` | 1 call site inlined (cost=-15005 vs threshold=525); 0 declined | -15005/525 |
| `k5_mul_reduce` | 1 call site inlined (cost=-15000 vs threshold=525); 0 declined | -15000/525 |
| `k6_hot_loop` | 0 call sites inlined; 2 call sites declined as too costly (cost=715 > threshold=525 at 2 of them) | 715/525, not inlined, 2 call sites |
| `k7_error_path` | 2 call sites inlined (cost=-14865 vs threshold=787, cost=135 vs threshold=787); 0 declined | 135 / -14865, 787, inlined at both |
| `k8_scale_add` | 1 call site inlined (cost=-15000 vs threshold=525); 0 declined | -15000/525 |

Every row reproduces EXPECTED §2a, which was assembled by hand. The matched
remarks are also quoted, under their own heading, in the site's state section.

### 1c. A placeholder share is reported as a placeholder

`artifacts/hintbench-sites/sites.json` carries `share: 12.5, reach: 12.5` at
all eight marks: the design's "one eighth each", not a measurement. The old
rule turned it into `hotness class very hot` at every site.

The driver now detects the case rather than special-casing the target --- more
than one mark, every recorded share the same value --- and prints

```
  - share of the program's user cycles: not measured on this target --- the
    site list carries one and the same value (12.50%) for every mark, so
    there is no hotness class here
```

with the matching change in the state section. jaq's shares run 1.10% to
29.29%, so jaq keeps its hotness classes.

### 1d. Checks

* `--print-state --vocab v3` on hintbench: **the k2 verdict line carries
  870 and 787**, the k4/k5/k8 loop legality lines read UNKNOWN with the
  shared-line reason, and the k3 loop's reads NOT VECTORIZABLE derived from
  its own single remark.
* `--print-state --vocab v1` and `--vocab v2` on hintbench: byte-identical to
  the same command run at commit `2d89cff`. The freezing rule of
  `scripts/jev_vocab.py` holds.
* **jaq is unaffected and still renders.** `--print-state --vocab v3` on jaq
  (baseline reused from `artifacts/jaq-search/jev-r5/baseline`, nothing
  rebuilt) exits 0 and produces 5.3 MB of state. Its 15 function sites all get
  an inline-outcomes line, and the parser handles what jaq has and hintbench
  does not: `always inline attribute at the call site`, `recursive`,
  `recursive and allocates too much stack space`, `noinline function
  attribute`, and marks with many monomorphizations (one reads *"3 call sites
  inlined (always inline attribute at the call site at 2 of them, cost=130 vs
  threshold=3000); 2 call sites declined as too costly (cost=155 > threshold=45
  at 2 of them)"*). Of jaq's 16 loop sites, 12 now read UNKNOWN for a shared
  line, 2 for having no remarks at all, and 2 report no legality failure.

---

## 2. Part (b): vocabulary v4

Same candidates as v3, same ids, same plan fragments, same loop half, same
questions. Only the six function descriptions change. The rule:

* one paragraph each, four sentences: what the attribute does, then one
  sentence beginning **"It helps where"** and one beginning **"It hurts
  where"**, in that order, in every candidate including `KEEP_DEFAULT`;
* no superlatives, no numeric instruction threshold in one description and
  not in another, no sentence about a candidate being immune to anything;
* no function, loop, file, program or site is named, as in v2 and v3.

| candidate | v3 | v4 |
|---|---|---|
| `KEEP_DEFAULT` | 164 chars, 26 words | 396 chars, 69 words |
| `inline_always` | **876 chars, 148 words** | 411 chars, 72 words |
| `inline_never` | 699 chars, 117 words | 383 chars, 70 words |
| `align_16` | 161 chars, 26 words | 397 chars, 71 words |
| `align_32` | 238 chars, 37 words | 395 chars, 67 words |
| `align_64` | 191 chars, 33 words | 392 chars, 70 words |
| longest / shortest | **5.4x** | **1.07x** |
| all six together | 2329 chars | 2374 chars |

The total barely moves: v4 redistributes the words rather than adding them.

The three that changed most, verbatim:

```
inline_always:
  Put the `alwaysinline` attribute on this function (the SPEC vocabulary's
  `inline(always)`). Its body is then pasted into every call site and the
  cost model is not consulted. It helps where the inliner is declining a
  body whose caller would specialise on what it passes, and the call
  overhead is worth removing. It hurts where the body is long or the call
  sites are many, since each of them pays the code growth.

align_64:
  Set this function's entry alignment to 64 bytes (the SPEC vocabulary's
  `align=64`). The entry then begins on a cache line, the mechanism of
  `align=32` one step coarser, and up to 63 bytes of padding are spent. It
  helps where a hot loop sits near the entry and afterwards spans fewer
  cache lines rather than fewer fetch windows. It hurts where the padding
  is spent and the spans do not change.

KEEP_DEFAULT:
  Put no attribute on this function. Its inlining and its entry alignment
  stay whatever LLVM's cost model and the platform default produce, exactly
  as in the baseline build. It helps where the cost model already reaches
  the decision the readings above support, so that an attribute could only
  restate it. It hurts where a decision the cost model will not revisit on
  its own is worth making by hand.
```

`align_16` is a near no-op on x86-64 and says so, at the same length and in
the same shape as the others: the fix is to stop describing candidates at
unequal length, not to talk each of them up to the strongest one.

Two things v4 deliberately does **not** change, so that they are held constant
across the ablation rather than varied with it: the candidate **order** in the
`criteria` object (position is a confound nobody asked for), and the verdict
line *"inliner mechanics of this recipe: ... `alwaysinline` and `noinline` are
decided before the cost model runs and are always honoured"*, which is state,
not vocabulary, and is in both arms.

---

## 3. Per-site results

Three repeats each, `--source-comments strip`, `--readout forced_top1`,
`min_confidence 0.0`. "stable" means the argmax was the same in all three
repeats. `P` is the probability of the argmax; the scoring rule is section 3
of the v3 file, unchanged (exact / same family in the same direction / miss;
`inline_always` against `inline(never)` is the opposite direction and is a
miss).

### 3a. Phase A --- the 8 marked functions

| site | EXPECTED | v3 + fixed state, x3 | P | conf | v4, x3 | P | conf | verdict (both) |
|---|---|---|---|---|---|---|---|---|
| `k1_step` | `inline(never)` | KEEP x3 | .79/.77/.79 | .75/.73/.75 | KEEP x3 | .89/.90/.90 | .86/.87/.87 | miss |
| `k2_mix` | `inline(always)` | `inline_always` x3 | .96/.94/.94 | .94/.92/.93 | `inline_always` x3 | .68/.72/.72 | .62/.66/.67 | **exact** |
| `k3_fill_run` | KEEP_DEFAULT | KEEP x3 | .85/.86/.85 | .81/.82/.82 | KEEP x3 | .86/.89/.89 | .84/.87/.85 | **exact** |
| `k4_count_bytes` | KEEP_DEFAULT | KEEP x3 | .91/.90/.90 | .88/.87/.86 | KEEP x3 | .95 x3 | .94/.92/.94 | **exact** |
| `k5_mul_reduce` | KEEP_DEFAULT | KEEP x3 | .93/.91/.93 | .91/.90/.91 | KEEP x3 | .96 x3 | .95/.94/.95 | **exact** |
| `k6_hot_loop` | `align=64` | `inline_always` x3 | .98 x3 | .97/.96/.96 | `inline_always` x3 | .71/.72/.69 | .66/.67/.64 | miss |
| `k7_error_path` | `inline(never)` | KEEP x3 | .91 x3 | .89/.88/.88 | KEEP x3 | .95/.95/.93 | .93/.94/.92 | miss |
| `k8_scale_add` | KEEP_DEFAULT | KEEP x3 | .87/.86/.87 | .84/.83/.83 | KEEP x3 | .87/.89/.90 | .86/.86/.88 | **exact** |

### 3b. Phase B --- the 4 frozen loop sites

| site | EXPECTED | v3 + fixed state, x3 | P | conf | v4, x3 | P | conf | verdict (both) |
|---|---|---|---|---|---|---|---|---|
| `k3_fill_run@lib.rs:174` | `unroll.disable` | KEEP x3 | .55/.54/.51 | .50/.50/.47 | KEEP x3 | .55/.59/.51 | .51/.56/.46 | miss |
| `k4_count_bytes@macros.rs:180` | KEEP_DEFAULT | `vectorize_width_16` x3 | .85/.85/.86 | .83/.84/.84 | `vectorize_width_16` x3 | .85/.85/.86 | .84/.83/.84 | miss |
| `k5_mul_reduce@macros.rs:180` | KEEP_DEFAULT | `vectorize_width_8` x3 | .61/.55/.63 | .56/.51/.60 | `vectorize_width_8` x3 | .56/.55/.56 | .52/.51/.52 | miss |
| `k8_scale_add@range.rs:1103` | KEEP_DEFAULT | `vectorize_width_8` x3 | .59 x3 | .54/.56/.56 | `vectorize_width_8` x3 | .57/.59/.59 | .53/.57/.56 | miss |

**The two arms give the same argmax at all twelve sites, in all three
repeats.** Every site is stable in both. v4 moved the probabilities and moved
no decision.

### 3c. Agreement with EXPECTED (informational: the oracle decides truth)

| | exact | same family | miss |
|---|---|---|---|
| functions (8) | **5** (k2, k3, k4, k5, k8) | 0 | 3 (k1, k6, k7) |
| loops (4) | **0** | 0 | 4 |
| all 12 | **5** | 0 | 7 |

identical for v3 + fixed state and for v4. Against the earlier passes:

| pass | state | functions | loops | total | stable | fn confidence |
|---|---|---|---|---|---|---|
| 1 | v3, comments kept | 6/8 | 4/4 | **10/12** | 11/12 | 0.29--0.89 |
| 2 | v3, comments stripped | 4/8 | 3/4 | **7/12** | 10/12 | 0.34--0.48 |
| 3 | v3, comments stripped + evidence fixed | 5/8 | 0/4 | **5/12** | 12/12 | 0.73--0.97 |
| 4 | v4, comments stripped + evidence fixed | 5/8 | 0/4 | **5/12** | 12/12 | 0.62--0.95 |

Agreement went *down* and confidence and stability went *up*. Section 4 is
why, and why the number is not the thing to read here.

---

## 4. Is the `inline_always` pull gone?

Decision 82's symptom had three parts. All three move, and the state fix does
most of the moving.

| | pass 2 (v3, broken state) | pass 3 (v3, fixed state) | pass 4 (v4) |
|---|---|---|---|
| sites whose **best non-KEEP** is `inline_always` (majority of 3) | **8 of 8** | 5 of 8 | **4 of 8** |
| sites whose **argmax** is `inline_always` | 4 of 8 | 2 of 8 (k2, k6) | 2 of 8 (k2, k6) |
| `inline_always` argmax at the control kernel k8 | yes | **no** | **no** |
| function confidence range | 0.34--0.48 | 0.73--0.97 | 0.62--0.95 |
| spread of `1-P(KEEP)` across the 8 sites | 0.13 | 0.91 | 0.74 |

So: **yes, the uniform pull is gone.** It was already gone after the evidence
fix alone, and what v4 adds is a halving of the mass wherever `inline_always`
is still chosen, plus a rise in KEEP everywhere else:

| site | `P(inline_always)`, v3 + fixed | v4 |
|---|---|---|
| `k2_mix` (argmax) | 0.96 / 0.94 / 0.94 | 0.68 / 0.72 / 0.72 |
| `k6_hot_loop` (argmax) | 0.98 x3 | 0.71 / 0.72 / 0.69 |
| `k1_step` | 0.09 / 0.07 / 0.07 | 0.06 / 0.05 / 0.05 |
| `k7_error_path` | 0.05 x3 | 0.03 / 0.03 / 0.04 |
| `k8_scale_add` (the control) | 0.04 / 0.05 / 0.04 | 0.02 x3 |

The two remaining `inline_always` picks are the two marks the baseline
**declines to inline**, and the verdict line now says so in cost units:
k2 at `cost=870 > threshold=787` and k6 at `cost=715 > threshold=525`. That
is a per-site fact, not a blanket, and the ranking follows it: k6 and k2 are
ranks 1 and 2 of phase A in all six repeats of both arms, and ranks 3--8 are
between 0.04 and 0.23.

What replaces the blanket at the bottom is `align_32`, which is the best
non-KEEP candidate at 4 of 8 sites under v4 --- at `P` between 0.02 and 0.07.
A tie broken at the noise floor is not the same phenomenon as an argmax at
0.5, but it is worth recording: **something** is always at the top of a
non-KEEP ranking, and reading it as a recommendation is a mistake the
decision-71 readout can still make.

### The k6 disagreement is new, and it is not a description artefact

Pass 1 chose `align_64` at k6 because a doc comment named it; pass 2 chose
`inline_always` at `P` 0.45--0.48 with everything else. Pass 3 and pass 4
choose `inline_always` at k6 with `P` 0.98 and 0.70 --- and now there is a
reason in the state: k6 is a 158-instruction function the inliner declines at
both of its call sites, by 190 cost units (`cost=715 > threshold=525`). EXPECTED's mechanism for k6 is an
instruction-fetch alignment effect it measured in the disassembly, and
EXPECTED never considered `inline(always)` there. Both columns are
predictions; the oracle sweeps `align_16/32/64`, `inline_always` and
`inline_never` at k6 and will answer it.

---

## 5. The loop phase got worse, and that is the honest reading

Phase B went from 3/4 (pass 2) to 0/4. Nothing about the vocabulary changed on
the loop side --- v3 and v4 share v2's loop descriptions verbatim --- so this
is the evidence fix, and specifically §1a.

| loop site | legality line, pass 2 | legality line, pass 3/4 | argmax, pass 2 | argmax, pass 3/4 |
|---|---|---|---|---|
| k4 bytes (VF8 x IC4) | NOT VECTORIZABLE (false) | UNKNOWN (shared line) | KEEP | `vectorize_width_16` |
| k5 reduce (VF8 x IC4) | NOT VECTORIZABLE (false) | UNKNOWN (shared line) | KEEP | `vectorize_width_8` |
| k8 control (VF8 x IC4) | NOT VECTORIZABLE (false) | UNKNOWN (shared line) | KEEP | `vectorize_width_8` |
| k3 fill (genuinely not) | NOT VECTORIZABLE (true) | NOT VECTORIZABLE (true) | KEEP | KEEP |

Vectorize family mass at the three shared-line sites goes from 0.02--0.06 to
0.56--0.87. Decision 70 recorded that the legality remark was "the one input
Jev reads unambiguously"; pass 2's three KEEP answers there were that input
being read correctly from a **false** premise. Remove the false premise and
the three KEEP answers go with it. Pass 2's 3/4 was luck of the same kind
pass 1's 10/12 was.

Two readings, both worth keeping:

* At k4 the verdict block still computes *"u8 ... one 256-bit vector register
  holds 32 of them, so the widest `vectorize.width` in this list that fits one
  register is 16"*, and Jev now takes it: `vectorize_width_16` at `P` 0.85 and
  confidence 0.84, the most confident non-KEEP loop answer of any pass. This
  is decision 73 (b) working exactly as designed --- "Jev does not do this
  arithmetic, but it follows it when it is done" --- at the one site where
  EXPECTED §1 K4 says the arithmetic's answer is *wrong*, because the baseline
  is already at VF 8 with IC 4 and a wider factor can only trade lanes against
  interleaving. The lane-count line is mechanically correct and materially
  misleading, and it is now the loudest thing in the k4 section.
* At k5 and k8 Jev asks for `vectorize_width_8`, which **is the width the
  baseline already uses**. Those two arms are candidates for the in-sweep
  null panel, and the oracle will say whether they are code-identical to the
  baseline.

The fix is not to put the false NOT VECTORIZABLE back. The missing fact ---
that LLVM vectorises these three loops at VF 8 x IC 4 --- is real, is in the
build log, and is simply not reachable by source location.
`scripts/remark_attribution.py` exists for exactly this and is not wired into
the state; alternatively the plugin could record the post-LoopVectorize state
of each dumped loop, which it currently cannot because it runs before the
vectoriser. Until one of those lands, `UNKNOWN` is the correct thing for the
state to say and the loop phase will answer worse than a lucky lie made it
answer.

---

## 6. The decision-71 readout

Both phases were non-empty in all six repeats of both arms
(`all_keep_default: false`), so `forced_top1` never fired. The ranking is
recorded anyway.

Phase A, `1 - P(KEEP_DEFAULT)`, best non-KEEP in brackets (repeat 1 of each;
ranks 1 and 2 are the same in all three repeats of both arms):

| rank | v3 + fixed state | v4 |
|---|---|---|
| 1 | `k6_hot_loop` 0.98 (`inline_always`) | `k6_hot_loop` 0.78 (`inline_always`) |
| 2 | `k2_mix` 0.96 (`inline_always`) | `k2_mix` 0.71 (`inline_always`) |
| 3 | `k1_step` 0.21 (`align_32`) | `k3_fill_run` 0.14 (`align_32`) |
| 4 | `k3_fill_run` 0.15 (`inline_always`) | `k8_scale_add` 0.13 (`align_32`) |
| 5 | `k8_scale_add` 0.13 (`align_32`) | `k1_step` 0.11 (`inline_always`) |
| 6 | `k4_count_bytes` 0.09 (`align_32`) | `k7_error_path` 0.05 (`inline_always`) |
| 7 | `k7_error_path` 0.09 (`inline_always`) | `k4_count_bytes` 0.05 (`inline_never`) |
| 8 | `k5_mul_reduce` 0.07 (`inline_always`) | `k5_mul_reduce` 0.04 (`align_32`) |

Phase B puts k4 first (0.87--0.88, `vectorize_width_16`) and k3 last
(0.41--0.49, `unroll_count_2`) in all six repeats of both arms; k5 and k8
swap ranks 2 and 3 between repeats, at 0.67--0.74 with `vectorize_width_8`
either way.

Pass 2's finding stands and is not repaired: the readout's top-ranked site is
**not** Claude's predicted winner any more. In phase A it is k6, where the two
columns disagree about the mechanism; in phase B it is k4, whose EXPECTED
answer is KEEP_DEFAULT and which pass 1 ranked third. What *is* better than
pass 2 is that the ranking now has a shape: a 0.91 spread from rank 1 to rank
8 instead of 0.13, and ranks 1 and 2 identical in every repeat of both arms.

---

## 7. API

| | v3 + fixed state | v4 |
|---|---|---|
| HTTP lines logged | 6 | 8 (6 answered 200, 2 exhausted on 503) |
| internal retries recorded (`failed_attempts`) | 5 | 8 |
| answered requests / questions | 6 / 36 | 6 / 36 |
| latency of the answered calls | 890--2019 ms (mean 1195) | 838--1253 ms (mean 1066) |
| tokens in / out | 117729 / 3603 | 117573 / 3603 |
| gateway cost | 0.00000000 USD (`marketCost` 0.004945) | 0.00000000 USD (`marketCost` 0.004938) |
| wall clock | 27 s | 53 s |
| phase A state / questions chars | 40604 / 30873 | 40602 / 31233 |
| phase B state / questions chars | 21122 / 18576 | 21120 / 18576 |

("questions chars" is the sum over questions of the instruction text plus
every criterion description; the same convention gives 30986 / 16592 for
passes 1 and 2.)

**Repeat 1 of v4 had both phases exhausted on a 503 burst** --- three
consecutive 503s each, through the internal backoff --- so the driver's rule
replaced every answer with KEEP_DEFAULT and recorded `source: "no answer"`.
The harness detected an all-`no answer` phase and re-sent each request
**unchanged** ten seconds later; both were answered on the first attempt and
are logged as `A.retry` and `B.retry`. The two exhausted lines are in the
JSONL with `"http_status": 503`. No request was ever modified to make it
succeed, and only the answered ones are scored.

The state grows 7% over pass 2 (37832 -> 40604 chars in phase A) for the new
evidence, and 12% in phase B. Input tokens are within 0.2% of each other
between the two arms, which is what "the two runs differ in 96 characters"
predicts.

---

## 8. What this establishes, and what it does not

* **Decision 82 (a) and (b) are separated.** The `inline_always` blanket ---
  best non-KEEP at 8 of 8 function sites, argmax at 4, confidence 0.34--0.48
  --- was mostly the **state**, not the descriptions. Repairing the evidence
  alone takes it to 5 of 8 / 2 / 0.73--0.97. v4's rebalancing takes it to
  4 of 8 / 2 / 0.62--0.95 and halves the probability mass at the two sites
  where the pick survives, without moving a single argmax.
* **v4 is worth keeping anyway**, on the evidence of what it did *not* do:
  three sentences of extra argument for `inline_always` in v3 were carrying
  0.25 of probability mass at k2 and k6 that no site-specific fact supports.
  A description set in which the six candidates are the same size is one less
  thing the answer can be about.
* **Agreement with EXPECTED fell to 5 of 12, and that is not a regression in
  Jev.** Three of the seven misses (the k4, k5 and k8 loops) are Jev
  answering a question the state can no longer answer falsely; one (k3 loop)
  is Jev declining where EXPECTED has a mechanism; and one (k6) is Jev
  following a fact EXPECTED never weighed. The 10/12 of pass 1 was the
  comments, the 7/12 of pass 2 was three KEEP answers resting on a false
  premise, and 5/12 is what is left when the state only says what it knows.
  All four numbers are agreement with a *prediction*.
* **The oracle is what decides.** Four of the twelve EXPECTED answers are
  KEEP_DEFAULT because the kernel could not be built as intended (§0 of
  `EXPECTED.md`), the jaq oracle has already falsified two of Claude's
  reference picks on another target (decision 79), and the hintbench sweep
  running while this file was written covers every one of the twelve sites.
* **One thing to fix next, and it is not a prompt.** Three of four loop sites
  cannot be told what LLVM did to them, because the only attribution the
  driver has is a source location that three of them share with fifteen other
  loops. That is `scripts/remark_attribution.py`'s problem or the plugin's,
  not the vocabulary's.
