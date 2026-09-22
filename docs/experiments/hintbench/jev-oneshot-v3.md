# Jev on hintbench, one shot, vocabulary and state v3

Run 2026-09-22, **API only**: no build, no timing, no plugin invocation. An
oracle sweep owns the CPU; this pass spends nothing but six HTTP requests.

The question is decision 69's: how close does Jev's answer come to Claude's
judgement, before any feedback. `targets/hintbench/EXPECTED.md` (sections 1--3
frozen before any timing, section 4 the revision after decision 77) is the
reference answer; this file is the third column. Nothing here is a speed
claim: whether either column is *right* is the oracle's question, and the
oracle has not run on this target yet.

* log: `docs/experiments/hintbench/jev-oneshot-v3.jsonl` (full request and
  response bodies, one line per HTTP call including the failures) and
  `jev-oneshot-v3.log` (one readable line per call plus totals; `*.log` is
  git-ignored repo-wide, so only the JSONL is committed --- the same
  arrangement as `docs/experiments/jev-prompt-study/`).
* what was sent: vocabulary `v3-2026-09-22`, state format
  `state-v3-2026-09-22`, `--readout forced_top1`, `min_confidence 0.0`.

## 1. What was asked, and how it was rendered

One request per phase, three repeats:

| phase | questions | sites | state chars | questions chars | requests |
|---|---|---|---|---|---|
| A | 8 | the 8 marked functions | 52155 | 32415 | 1 (`max_state_chars` 120000) |
| B | 4 | the frozen `loop_in_mark` set | 25969 | 18012 | 1 |

The state and the questions are rendered by the driver itself. The harness
loads `scripts/jev_search.py` as a module, runs it with `--print-state` (which
performs the whole round-1 setup and then returns), intercepts
`questions_for()` to capture the real `items` and `ctx` of each phase, and
sends them through `JevProposer.choose()`. So the batching, the candidate
validation, the confidence gate and the decision-71 readout are the driver's
own code paths, and what was sent equals round 1 of
`scripts/jev_search.py --proposer jev --vocab v3` on this target byte for
byte, with **one** exception, recorded here:

```
--print-state renders both phases with
  function attributes this round already applied: (none: this is a preview)
round 1 renders phase A with fn_choice_text = "" (the line is not shown at a
function site at all) and phase B with
  function attributes this round already applied: none
```

The harness sets the round-1 strings. The rendered phase-A state is then
byte-identical to `--print-state`'s, and the phase-B state differs from it in
exactly those 4 lines (one per loop site) out of 468.

The baseline is the design step's dump, reused through `--baseline-dir`
(`artifacts/hintbench-sites/baseline`, `bin` sha256 in its `baseline.json`);
the site list and the frozen 4-key loop set are
`artifacts/hintbench-sites/sites.json`, written by
`scripts/hintbench_oracle.sh dump`. Nothing was rebuilt.

### Caveat: phase B was asked as if phase A had chosen KEEP_DEFAULT everywhere

In a real round the phase-B loop sites come from the `JEV_MODE=apply-dump`
build that phase A's choices produced, and the phase-B state names those
choices. This pass builds nothing, so phase B uses the **baseline dump's**
loop sites (the same four keys the oracle sweeps) and is told
`function attributes this round already applied: none`. That is exactly the
round-1 phase B of a run whose phase A answered KEEP_DEFAULT at all eight
functions --- which is *not* what phase A answered here (it chose
`inline_always` at k2 and `align_64` at k6, and at k7 in two repeats of
three). Under those choices the real round 1 would re-dump the loops after
the attributes were applied, and a key can move when an attribute changes
(decision 61). The four keys are almost certainly the same ones, but this was
not verified, because verifying it is a build.

## 2. Per-site results

Three repeats. "stable" means the argmax was the same in all three.

### Phase A --- the 8 marked functions

| site | Claude (EXPECTED) | Jev argmax x3 | P(argmax) | confidence | stable | verdict |
|---|---|---|---|---|---|---|
| `k1_step` | `inline(never)` | KEEP, KEEP, KEEP | 0.66 / 0.63 / 0.59 | 0.60 / 0.57 / 0.50 | yes | **miss** |
| `k2_mix` | `inline(always)` (§4) | `inline_always` x3 | 0.81 / 0.80 / 0.82 | 0.76 / 0.76 / 0.77 | yes | **exact** |
| `k3_fill_run` | KEEP_DEFAULT | KEEP, KEEP, KEEP | 0.48 / 0.48 / 0.53 | 0.37 / 0.38 / 0.44 | yes | **exact** |
| `k4_count_bytes` | KEEP_DEFAULT | KEEP, KEEP, KEEP | 0.80 / 0.75 / 0.71 | 0.76 / 0.71 / 0.65 | yes | **exact** |
| `k5_mul_reduce` | KEEP_DEFAULT | KEEP, KEEP, KEEP | 0.78 / 0.84 / 0.82 | 0.75 / 0.81 / 0.78 | yes | **exact** |
| `k6_hot_loop` | `align=64` | `align_64` x3 | 0.84 / 0.85 / 0.85 | 0.81 / 0.83 / 0.83 | yes | **exact** |
| `k7_error_path` | `inline(never)` | KEEP, `inline_always`, `inline_always` | 0.42 / 0.47 / 0.42 | 0.30 / 0.37 / 0.29 | **no** | **miss** |
| `k8_scale_add` | KEEP_DEFAULT | KEEP, KEEP, KEEP | 0.88 / 0.91 / 0.91 | 0.85 / 0.89 / 0.88 | yes | **exact** |

Candidates at every function site (v3): `KEEP_DEFAULT`, `inline_always`,
`inline_never`, `align_16`, `align_32`, `align_64`.

Claude's per-site reference is derived from EXPECTED's per-*kernel* winner:
the kernels whose winner is a loop hint (k3, k4, k5) or nothing (k8) have
KEEP_DEFAULT as their *function-site* reference, because the vocabulary has no
function candidate that could deliver their mechanism.

### Phase B --- the 4 frozen loop sites

| site | Claude (EXPECTED) | Jev argmax x3 | P(argmax) | confidence | stable | verdict |
|---|---|---|---|---|---|---|
| `k3_fill_run@lib.rs:174` | `unroll.disable` | `unroll_disable` x3 | 0.92 / 0.92 / 0.92 | 0.90 x3 | yes | **exact** |
| `k4_count_bytes@macros.rs:180` | KEEP_DEFAULT | KEEP x3 | 0.76 / 0.63 / 0.73 | 0.74 / 0.61 / 0.70 | yes | **exact** |
| `k5_mul_reduce@macros.rs:180` | KEEP_DEFAULT | KEEP x3 | 0.52 / 0.58 / 0.51 | 0.47 / 0.53 / 0.46 | yes | **exact** |
| `k8_scale_add@range.rs:1103` | KEEP_DEFAULT | KEEP x3 | 0.89 / 0.90 / 0.92 | 0.87 / 0.88 / 0.90 | yes | **exact** |

## 3. One-shot agreement

Scoring rule. It was written **after** the argmaxes were read, so it is not
pre-registered. It is taken from EXPECTED's own sentences rather than invented
for this run, and both readings of the one case it affects (k7) are shown
below:

* **exact** --- the same candidate id.
* **same family** --- the same hint family *in the same direction*:
  `align_16 / align_32 / align_64`; `unroll_count_* / unroll_disable`
  (EXPECTED §1 K3 says `unroll.count=2` "should also win, by less");
  `vectorize_width_*`; `interleave_count_*`. `inline_always` against
  `inline_never` is the **opposite** direction and scores as a miss.
* **miss** --- anything else, including KEEP_DEFAULT against a hint and a hint
  against KEEP_DEFAULT.

| | exact | same family | miss |
|---|---|---|---|
| functions (8) | **6** (k2, k3, k4, k5, k6, k8) | 0 | 2 (k1, k7) |
| loops (4) | **4** | 0 | 0 |
| all 12 sites | **10** | 0 | 2 |

Stability: 11 of 12 sites gave the same argmax in all three repeats; only
`k7_error_path` moved (KEEP once, `inline_always` twice), and it is also the
lowest-confidence function site in the set (0.29--0.37).

One case turns on the direction clause: **k7**. Claude says `inline(never)`
(take the 40-instruction body out of the hot loop); Jev reaches for
`inline_always` (paste it in harder). Under a family-only rule that would
score "same family" and the function total would read 6 exact + 1 family + 1
miss. The strict reading is used above because the two hints do opposite
things to the same call site and EXPECTED's mechanism for k7 is specifically
about removing the body from the loop. Both readings are reported so the
choice is visible.

This is the **one-shot** number: round 1, no feedback, no measurement in the
state. It is not comparable to the prompt study's 8/9 (decision 73), which was
measured on jaq sites against a reference judgement that the jaq oracle later
contradicted twice (decision 79).

## 4. The decision-71 readout

Ranking by `1 - P(KEEP_DEFAULT)`, with each site's own best non-KEEP
candidate. Both phases were **non-empty** in all three repeats
(`all_keep_default: false`), so `forced_top1` never fired --- but the ranking
is recorded either way, and it answers "which site would be tried first if
every answer had been KEEP".

Phase A, repeat 1 (ranks 1--5 are identical in all three repeats):

| rank | site | `1-P(KEEP)` | best non-KEEP | P |
|---|---|---|---|---|
| 1 | `k6_hot_loop` | 0.94 | `align_64` | 0.84 |
| 2 | `k2_mix` | 0.81 | `inline_always` | 0.81 |
| 3 | `k7_error_path` | 0.58 | `inline_always` | 0.39 |
| 4 | `k3_fill_run` | 0.52 | `inline_always` | 0.39 |
| 5 | `k1_step` | 0.34 | `inline_never` | 0.16 |
| 6 | `k5_mul_reduce` | 0.22 | `inline_always` | 0.18 |
| 7 | `k4_count_bytes` | 0.20 | `inline_always` | 0.14 |
| 8 | `k8_scale_add` | 0.12 | `inline_always` | 0.11 |

Phase B, repeat 1:

| rank | site | `1-P(KEEP)` | best non-KEEP | P |
|---|---|---|---|---|
| 1 | `k3_fill_run @ lib.rs:174` | 0.94 | `unroll_disable` | 0.92 |
| 2 | `k5_mul_reduce @ macros.rs:180` | 0.48 | `unroll_count_8` | 0.17 |
| 3 | `k4_count_bytes @ macros.rs:180` | 0.24 | `unroll_disable` | 0.07 |
| 4 | `k8_scale_add @ range.rs:1103` | 0.11 | `unroll_disable` | 0.05 |

Readings:

* **The site the readout would try first is Claude's predicted winner, in both
  phases and in all three repeats**: `align_64` at k6 (rank 1 at 0.94--0.95)
  and `unroll_disable` at the k3 fill loop (rank 1 at 0.94--0.95). On this
  target the decision-71 lever points at the right place. That is the first
  positive evidence for it; on jaq it has never been tested against a target
  with a known answer.
* The ranking is **not** a second opinion at the bottom: `inline_always` is
  the best non-KEEP candidate at six of eight function sites, including the
  control k8. The ordering carries information; the hint the ordering names at
  a cold site does not.
* The two rankings are stable: ranks 1--5 of phase A and all four of phase B
  are the same in all three repeats. Only ranks 6--7 of phase A swap (k4
  against k5), and at rank 5 the best non-KEEP at k1 flips between
  `inline_never` (repeats 1, 3) and `inline_always` (repeat 2) on a 0.13/0.18
  margin.

## 5. Sanity checks

**Does Jev avoid vectorize hints on K3, which is not vectorizable?** Yes:
`sum P(vectorize_width_*)` at the k3 fill loop is **0.000** in all three
repeats. But the check is **non-discriminating on this target**, and that is
a finding about the state, not about Jev. The verdict line
`vectorisation legality, from the baseline remarks at this line` reads
**NOT VECTORIZABLE** at *all four* loop sites --- including k4, k5 and k8,
which the baseline vectorises at width 8 x interleave 4 (EXPECTED §2b). The
line is built from remarks attributed by source location, and three of the
four sites sit on `macros.rs:180` / `range.rs:1103`, lines shared by every
`for &x in slice` loop in the program, so the negative remarks of other loops
are what it picks up. The vectorize mass is nonetheless not uniform:

| loop site | `vectorize_*` mass x3 | `interleave_*` mass x3 | `unroll_*` mass x3 |
|---|---|---|---|
| k3 fill (genuinely not vectorizable) | 0.00, 0.00, 0.00 | 0.00, 0.00, 0.00 | 0.94, 0.95, 0.94 |
| k4 byte count (VF8 x IC4) | 0.08, 0.15, 0.10 | 0.00, 0.01, 0.00 | 0.16, 0.21, 0.17 |
| k5 mul reduction (VF8 x IC4) | 0.01, 0.01, 0.03 | 0.15, 0.16, 0.15 | 0.32, 0.25, 0.31 |
| k8 control (VF8 x IC4) | 0.00, 0.00, 0.00 | 0.00, 0.00, 0.00 | 0.11, 0.10, 0.08 |

A fourth reading of the same defect: the k4 site's state section says
`already vectorized when the hint is attached: no`, two lines under a remark
block whose first line is
`vectorized loop (vectorization width: 8, interleaved count: 4)`.

So Jev still puts its largest vectorize mass exactly where the width verdict
line computes a lane count (`u8` -> 32 per register -> widest in the list is
16) --- the k4 byte loop, which is the site where decision 70 recorded Claude
choosing `vectorize.width=16` and where EXPECTED §1 K4 now says that choice is
wrong. `vectorize_width_16` is the single largest non-KEEP candidate at k4 in
all three repeats (0.07 / 0.11 / 0.08), and in repeat 2 it is the readout's
best non-KEEP there. Jev does not commit to it; Claude did.

**Does Jev avoid `inline_always` on the large K1 body?** As an argmax, yes:
KEEP_DEFAULT wins all three repeats, and `inline_never` leads `inline_always`
in two of three (0.16 vs 0.13, 0.21 vs 0.15) and trails it in one (0.13 vs
0.18). But **the state does not describe K1 as large.** What Jev is shown is
`body size: 137 LLVM instructions after LTO`, `size class: small`,
`distinct copies: 1`, `attributes already on it: (none)` and the
`inline budget` line concluding *"0.6x, i.e. the body fits inside that
budget"*. EXPECTED's "large" is the *post-inlining loop body* --- eight copies
of `k1_step` in one loop, roughly a thousand instructions --- and nothing in
the state says that the baseline already inlines it at eight call sites. So
Jev's near-tie here is not the model resisting a trap; it is the model
guessing under a description that points the other way. The check as written
cannot be run against this state.

**Is K2's `cost=870, threshold=787` visible in the verdict lines?** **No.**
The string `870` does not occur anywhere in either phase's state. The remark
block shown under the k2 site is `lib.rs`-attributed noise from `std`'s
backtrace machinery (`panic_in_cleanup`, `addr2line`) and the two
`panic_bounds_check` remarks of k3, not the inline decision about `k2_mix`.
The real remark is in the baseline build log --

```
'...k2_mix' not inlined into '..._9hintbench4main' because too costly to
inline (cost=870, threshold=787)
```

-- attributed to the *call site's* line in `main`, not to `k2_mix`'s own
definition, so `RemarkBook`'s per-site lookup never finds it. The verdict
block says the opposite of the fact: *"body instructions / -inline-threshold=225
= 0.8x, i.e. the body fits inside that budget"*. Jev chose `inline_always` at
k2 anyway, at P = 0.80--0.82 and the second-highest confidence of any non-KEEP function
pick (k6 is first). It
got EXPECTED §4's revised answer without being shown the 83 cost units that
are the whole mechanism.

**Flat, non-discriminating inputs.** `sites.json` hardcodes
`share: 12.5, reach: 12.5` at all eight marks, so every function site reads
`hotness class very hot` and the hotness rule separates nothing here. Each
kernel really is 1/8 of the workload by construction, so the number is not
wrong, but no site can be distinguished by it.

**The source excerpts name the hint under test.** This is the largest
uncontrolled confound in the agreement number above and it was not noticed
before the requests were sent. The state's `source:` block is a +/-40-line
window of `hbkernels/src/lib.rs`, and the kernels' own doc comments say, in
the window:

```
/// One step of a 22-round mixer. Marked; the hint under test is `inline(never)`.
/// Leaf mixer for K2. Marked; the hint under test is `inline`.
/// Fill `dst[prev..=end]` ... the hint under test is `unroll.disable` on its single loop.
/// Count occurrences of `needle`. Marked; the hint under test is a `vectorize.width` ...
/// Multiplicative reduction. Marked; the hint under test is an `interleave.count` ...
/// Serial hash over `data`. Marked; the hint under test is `align=64`.
/// The rarely taken path. Marked; the hint under test is `cold`.
```

Decision 59 keeps the hypothesis out of `jev-marks.txt` and EXPECTED.md is
never shown, but the kernel sources were written as documentation of the
benchmark and they leak it. Of Jev's four non-KEEP argmaxes, **three name the
hint the comment names** (k2 `inline` -> `inline_always`, k6 `align=64`, k3
loop `unroll.disable`). The leak is not sufficient on its own: Jev **ignored**
the comment at k1 (`inline(never)`, where following it would have *agreed*
with EXPECTED), at the k4 loop (`vectorize.width`) and at the k5 loop
(`interleave.count`), and the two kernels it ignored on the loop side are
exactly the two EXPECTED §0 revised to KEEP_DEFAULT. Still: the agreement
number cannot be read as "Jev reasoned its way to Claude's answer" at k2, k6
and the k3 loop while this text is in the state. Re-running with the doc
comments stripped from the source window is one cheap API pass and would
settle it; it has not been run.

## 6. Request and response excerpts

One question and its answer per phase, verbatim from the JSONL. The state
preamble (52 KB in phase A) is not reproduced; it is line 1 of the log.

### Phase A, `q1` = `fn:hbkernels::k2_mix`

Request (`request.questions.q1.instructions`, the criteria list is the six v3
function candidates with their applicability conditions):

```
Section `q1` of the state describes one marked function of this program.
Which single hint from the list is most likely to make this function faster
on this workload?

Mechanical readings for this site. Each line is produced by a tool from the
numbers and the compiler remarks already in the state, by the same rule at
every site in this request; none of them is an opinion about which hint to
choose.
  - body size: 186 LLVM instructions after LTO
  - size class: small (rule: <50 tiny, <300 small, <1000 medium, <2000 large,
    >=2000 very large)
  - distinct copies in the binary: 1 monomorphization(s); copy class single
    (rule: 1 single, 2-8 few, >=9 many)
  - inline budget: LLVM's defaults are -inline-threshold=225 and
    -inlinehint-threshold=325 cost units; body instructions /
    -inline-threshold=225 = 0.8x, i.e. the body fits inside that budget
    (an order-of-magnitude comparison, not an InlineCost computation --- the
    cost=/threshold= pairs in the remarks above are the real ones, and they
    are about this function's callees)
  - attributes already on it: (none)
  - inliner mechanics of this recipe: with a profile present, `inlinehint`
    and `cold` on a function do not change the inliner's threshold for it,
    because the call site's own hotness class assigns that threshold
    afterwards; `alwaysinline` and `noinline` are decided before the cost
    model runs and are always honoured
  - share of the program's user cycles: 12.50%; hotness class very hot
    (rule: <1% not hot, 1-5% hot, >=5% very hot)
```

Response (`response.answers.q1`, repeat 1):

```json
{"type": "choice", "choice": "inline_always", "confidence": 0.76,
 "probabilities": {"KEEP_DEFAULT": 0.19, "inline_always": 0.81,
                   "inline_never": 0, "align_16": 0, "align_32": 0,
                   "align_64": 0}}
```

### Phase B, `q3` = `hbkernels::k3_fill_run@lib.rs:174:9#d3`

Request:

```
Section `q3` of the state describes one loop inside a marked function of this
program. Which single hint from the list is most likely to make this loop
faster on this workload?

Mechanical readings for this site. [...]
  - average trip count: 11.5; trip class short (rule: <2 degenerate, <16
    short, <100 medium, >=100 long)
  - body size: 11 LLVM instructions; size class tiny (rule: <50 tiny, ...)
  - calls inside the body: no; loop nesting depth 3; loops this site key
    names: not recorded for this key (a key can name several loops, and a
    hint on it would reach all of them)
  - element type at the loop's iterator: not derivable from the recorded
    inline chain, so the lane count for this loop is unknown
  - vectorisation legality, from the baseline remarks at this line: NOT
    VECTORIZABLE --- value that could not be identified as reduction is used
    outside the loop. A `vectorize.width` hint is not a permission slip:
    LLVM drops it when vectorisation is illegal.
  - caveat that applies to every loop here: remarks are attributed by source
    location only, so several loops can share one line
```

Response (repeat 1):

```json
{"type": "choice", "choice": "unroll_disable", "confidence": 0.9,
 "probabilities": {"unroll_disable": 0.92, "KEEP_DEFAULT": 0.06,
                   "unroll_count_2": 0.01, "unroll_count_4": 0.01,
                   "unroll_count_8": 0, "vectorize_width_2": 0,
                   "vectorize_width_4": 0, "vectorize_width_8": 0,
                   "vectorize_width_16": 0, "interleave_count_1": 0,
                   "interleave_count_2": 0, "interleave_count_4": 0}}
```

## 7. API

| | |
|---|---|
| HTTP calls logged | 11 lines (6 answered 200, 5 exhausted on 503) |
| internal retries recorded (`failed_attempts`) | 19 |
| answered requests | 6 (3 x phase A, 3 x phase B) |
| questions answered | 36 (3 x 8 + 3 x 4) |
| latency of the answered calls | 792--1788 ms (mean 1209 ms) |
| tokens in / out (answered) | 128517 / 3572 |
| gateway cost | 0.00000000 USD (`marketCost` 0.005398 USD) |
| wall clock | 222 s for the first pass + one retry pass |

**Repeat 2 of phase A had to be asked twice.** Its first pass hit a 503 burst
that survived the whole backoff --- 5 outer attempts x 3 internal retries, 15
consecutive 503s over 3 minutes --- so the driver's own rule replaced every
answer with KEEP_DEFAULT and recorded `source: "no answer"` at all eight
sites. That is not an answer and it is not scored above. The phase was re-sent
unchanged a minute later and answered on the third internal attempt; it is
logged as phase `A.retry`, round 2. Both the five failures and the retry are
in the JSONL, and the five failed lines carry `"response": null`. Phase B and
repeats 1 and 3 of phase A each came back on the first or second internal
attempt. No request was ever modified to make it succeed.

Log line ordering: rounds 1--3 in the JSONL are repeats 1--3; the `A.retry`
line at the end is repeat 2's phase A and supersedes the five `r2 A` failures
above it.

## 8. What this does and does not establish

* Jev, one shot, with no feedback and no measurement, reproduces Claude's
  frozen per-site prediction at **10 of 12 sites** (6/8 functions, 4/4 loops),
  stably at 11 of 12.
* Both misses are function-attribute sites where EXPECTED's mechanism is about
  taking a body *out* of a hot loop (k1, k7), and at both of them the
  information that the baseline already inlines the callee is absent from the
  state (checked: the phase-A state contains no inline remark naming
  `k1_step` or `k7_error_path`, though the baseline build log has two for
  each). At k7 Jev picks the opposite hint; at k1 it declines to pick.
* The decision-71 readout's top-ranked site is Claude's predicted winner in
  both phases, in every repeat. That is the first test of decision 71 against
  a target with a designed answer, and it passes.
* None of this says either column is correct. Four of the twelve reference
  answers are KEEP_DEFAULT because EXPECTED *could not build* the mechanism
  (§0), and the jaq oracle has already falsified two of Claude's reference
  picks on another target (decision 79). The hintbench oracle is what decides.
* Three inputs the state gets wrong or leaves out are recorded in section 5 and
  should be fixed before this number is quoted as a prompt-quality result: the
  legality line's false NOT VECTORIZABLE at three of four loop sites, the
  missing `cost=870, threshold=787` at k2 (with the `inline budget` line
  asserting the reverse), and the kernel doc comments naming the hint under
  test inside the source window.
