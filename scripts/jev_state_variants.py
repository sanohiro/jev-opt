#!/usr/bin/env python3
"""State/question framings for the Jev prompt study (decisions 66-68).

**Not wired into `scripts/jev_search.py`.** The driver's state format is
frozen (`state-v1-2026-09-22`, decision 65 (e)) and `scripts/jev_vocab.py` is
frozen with it; this file is where the *variants* live so that the frozen
pair stays untouched while the study runs. If the study picks a framing, that
framing is copied into the driver as state v2 and this file stays as the
record of what was compared.

The study asks one question: Experiment 3 got `KEEP_DEFAULT` to all 107
questions at mean confidence 0.95 (decision 66) --- is that Jev's opinion, or
is it what the way we ask produces (decision 67)? Decision 68 added the
second half: the state carried one line about the machine and almost no
per-site profile, and rode 15 questions in one 71 KB request.

Variants
--------

    V0    the frozen state and question, verbatim, in the frozen request
          shape (15 function questions / 16 loop questions per request).
          The control: it must reproduce the KEEP_DEFAULT behaviour.
    V0b   the frozen state and question, verbatim per site, but only the
          study's sites in the request. Separates *wording* from *batching*:
          without it, V0 (15-16 questions) against V1..V8 (9 questions)
          confounds the two.
    V1    V0b with KEEP_DEFAULT removed from `criteria`, and the question
          "we will try one hint here; which is the most promising?".
    V2    V0b with KEEP_DEFAULT kept but described neutrally ("no change"),
          and the question reworded from "should anything change?" to
          "which single hint is most likely to make this faster on this
          workload?".
    V3    V2 minus the anchoring sections: what LLVM said in the baseline,
          the attributes already on the function, and the previous rounds.
    V4    V2 plus explicit search framing: round 1 of a search, a wrong hint
          costs one build and is measured rather than shipped.
    V5    Score (0-3 expected gain, ordered array) for every candidate at
          every site, plus one Noul per site ("is this site worth a hint at
          all"). The choice is derived from the scores.
    V6    V2 with the source excerpt cut from +-40 lines to +-10, to test
          whether length dilutes the decision.
    V7    V2 plus a structured platform block (decision 68): micro-
          architecture, ISA, vector width and register count, cache sizes,
          how the measurement is pinned.
    V8    V2 plus a per-site profile table (decision 68): self and reach
          share, share per workload, and the loop/function shape numbers.
    V9    V2+V7+V8 with one question per HTTP request.
    V10   V4's search framing + V7 + V8 + one question per request.
    V11   V2+V7+V8 plus a hint guide: what each hint in the frozen
          vocabulary does, where it helps, where it backfires. General only
          --- it never mentions a site of this program.
    V12   the decision split in two. Stage 1 chooses a *family* (leave it
          alone / function attribute / unroll / vectorize / interleave),
          stage 2 chooses the value inside the family the stage-1 answer
          named, in a separate request.
    V13   V2+V7+V8 plus six measured examples from the toy and zopfli days
          (results.md Day 0 sections 13-15, section 31): what happened when
          a hint of this shape was put on a loop of that shape.
    V14   V2+V7+V8 plus Claude's *reasoning* for the reference picks,
          generalised so that it states no conclusion about any site of this
          program. The ceiling measurement: if the information is all there,
          does Jev reach the same answer? Not shippable --- it needs Claude
          every time.

Everything the variants reuse verbatim (the site sections, the frozen
question wording, the candidate descriptions) is read from the Experiment 3
request log rather than rebuilt, so V0 is the real thing and not a
reconstruction of it. The one exception is L5, which was never asked about
and whose section is assembled here from `targets/jaq/sites.json`; it is
labelled as such in the state.

Usage:

    scripts/jev_state_variants.py --list
    scripts/jev_state_variants.py --variant V8 --print
    scripts/jev_state_variants.py --variant V12 --stage 1 --print
"""

import argparse
import json
import os
import re
import sys

STUDY_VERSION = "prompt-study-v1-2026-09-22"

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_JSONL = os.path.join(
    REPO, "artifacts", "jaq-search", "jev-r5", "jev-log", "jev-r5.jsonl")
DEFAULT_SITES_JSON = os.path.join(REPO, "targets", "jaq", "sites.json")

sys.path.insert(0, os.path.join(REPO, "scripts"))
import jev_vocab  # noqa: E402  (frozen vocabulary; read only, never edited)


# ---------------------------------------------------------------------------
# the study's sites
# ---------------------------------------------------------------------------
#
# `src` says where the section text comes from:
#   ("A", "q4")  the round-1 phase-A request of the Experiment 3 log
#   ("B", "q8")  the round-3 phase-B request of the same log
#   ("built",)   assembled here (L5 only: it is outside the frozen site set)

SITES = [
    dict(id="F1", kind="fn", src=("A", "q0"),
         label="jaq_json::read::parse",
         ref="KEEP_DEFAULT"),
    dict(id="F2", kind="fn", src=("A", "q4"),
         label="<jaq_core::compile::TermId>::run",
         ref="inline_never"),
    dict(id="F3", kind="fn", src=("A", "q5"),
         label="jaq_json::write::write",
         ref="inline_never"),
    dict(id="F4", kind="fn", src=("A", "q11"),
         label="<jaq_std::base_run<..>::{closure#7} as FnOnce<..>>::call_once",
         ref="KEEP_DEFAULT"),
    dict(id="L1", kind="loop", src=("B", "q0"),
         key="a48529f86e22591a-next-macros.rs-180",
         label="<&String as Display>::fmt @ slice/iter/macros.rs:180 (d2)",
         ref="KEEP_DEFAULT"),
    dict(id="L2", kind="loop", src=("B", "q8"),
         key="c2530364c88e4ee5-write-mod.rs-1653",
         label="jaq_json::write::write @ core/fmt/mod.rs:1653 (d1)",
         ref="KEEP_DEFAULT"),
    dict(id="L3", kind="loop", src=("B", "q7"),
         key="fd4b78443b0dcc85--macros.rs-279",
         label="base_run{closure#7} @ slice/iter/macros.rs:279 (d1)",
         ref="vectorize_width_16"),
    dict(id="L4", kind="loop", src=("B", "q4"),
         key="7a171b553e34d5fc-string_end-str.rs-194",
         label="read::parse @ hifijson str.rs:194 (d1)",
         ref="KEEP_DEFAULT"),
    dict(id="L5", kind="loop", src=("built",),
         key="e94fd84394a175bd-next-iter.rs-605",
         label="jaq_json::write::write @ slice/iter.rs:605 (d1), trip 1",
         ref="KEEP_DEFAULT"),
]

SITE_BY_ID = {s["id"]: s for s in SITES}

# Per-site profile material for V8. `self_share` and `reach` are perf shares
# from targets/jaq/jev-marks.rationale.md; obj/str/rw are that file's
# per-workload columns; the loop numbers are targets/jaq/sites.json.
PROFILE = {
    "F1": dict(self_share="29.29%", reach="29.29%", obj="33.9%", str="26.0%",
               rw="27.5%", shape="7660 LLVM insts (4426 machine insts, 259 "
               "machine backedges; 805 insts are read::parse's own body, the "
               "rest is inlined into it), 18 monomorphizations, 49 loop sites "
               "inside it",
               attrs="cold or inlinehint (the distinct sets over the copies)",
               remark_class="inlining refusals only (panic paths cost=never, "
               "strip_prefix cost=45 vs threshold=45); no vectorisation "
               "remark on the function's own line"),
    "F2": dict(self_share="8.32%", reach="8.85%", obj="6.8%", str="13.2%",
               rw="0.8%", shape="10496 LLVM insts (6562 machine insts, 236 "
               "machine backedges; 1322 insts are its own body), 62 "
               "monomorphizations, 15 loop sites inside it",
               attrs="cold, or inlinehint, or inlinehint+cold (the distinct sets over the copies)",
               remark_class="inlining refusals; one `Cannot SLP vectorize "
               "list` at filter.rs:466"),
    "F3": dict(self_share="4.48%", reach="4.48%", obj="0.1%", str="0.0%",
               rw="22.6%", shape="5467 LLVM insts (2390 machine insts, 179 "
               "machine backedges; 749 insts are its own body), 1 "
               "monomorphization plus 7 closures defined inside it, 22 loop "
               "sites inside it",
               attrs="inlinehint",
               remark_class="load not eliminated / loop-invariant load could "
               "not be moved at write.rs:303; inlining decisions elsewhere"),
    "F4": dict(self_share="1.73%", reach="1.73%", obj="0.0%", str="4.1%",
               rw="0.0%", shape="251 LLVM insts (432 machine insts, 98 of "
               "them vector, 14 machine backedges), 1 monomorphization, 1 "
               "loop site inside it",
               attrs="inlinehint",
               remark_class="already vectorized (width 4, interleave 2 and 4) "
               "plus `completely unrolled` at macros.rs:279; cost model says "
               "vectorisation and interleaving are not beneficial"),
    "L1": dict(mark="<&alloc::string::String as core::fmt::Display>::fmt",
               mark_share="1.10%", obj="0.0%", str="0.0%", rw="5.6%",
               trip="32.0", header="722,491,314", insts="36", calls="no",
               depth="2", copies="1 (the key names exactly one loop)",
               hot="2.60e10 --- the largest hotness of any loop_in_mark key "
               "in this program",
               chain="Formatter::pad -> Chars::count -> do_count_chars -> "
               "<slice::Iter<[u8;4]>>::next",
               remark_class="ILLEGAL to vectorize (early exit with complex "
               "writes to memory; incorrect number of successors from early "
               "exiting block; value that could not be identified as a "
               "reduction is used outside the loop) + unroller advises "
               "against (contains a call/invoke) + cost model says not "
               "beneficial"),
    "L2": dict(mark="jaq_json::write::write", mark_share="4.48%",
               obj="0.1%", str="0.0%", rw="22.6%",
               trip="25.8", header="144,524,134", insts="141", calls="yes",
               depth="1",
               copies="4 (one hint on this key lands on all four loops; "
               "their hotness sums to 3.24e10)",
               hot="2.04e10", chain="jaq_json::write::write -> "
               "BufWriter<StdoutLock>::write_fmt -> default_write_fmt -> "
               "core::fmt::write",
               remark_class="ILLEGAL to vectorize (early exit; loop induction "
               "variable could not be identified; could not determine number "
               "of loop iterations) + unroller advises against (contains a "
               "call/invoke)"),
    "L3": dict(mark="<jaq_std::base_run<..>::{closure#7} as FnOnce<..>>::"
               "call_once", mark_share="1.73%",
               obj="0.0%", str="4.1%", rw="0.0%",
               trip="221.7", header="177,080,637", insts="13", calls="no",
               depth="1", copies="1", hot="2.30e9",
               chain="base_run{closure#7} -> map_utf8_str -> "
               "ByteSlice::to_ascii_lowercase -> <slice::Iter<u8>>::next",
               remark_class="LEGAL and already vectorized: `vectorized loop "
               "(vectorization width: 4, interleaved count: 2)` and `(width "
               "4, interleaved count: 4)` at this line, plus `completely "
               "unrolled`; cost model reports vectorisation and interleaving "
               "as not beneficial, and one `runtime pointer checks needed`. "
               "Remarks are attributed by source line only, and several loops "
               "share macros.rs:279"),
    "L4": dict(mark="jaq_json::read::parse", mark_share="29.29%",
               obj="33.9%", str="26.0%", rw="27.5%",
               trip="13.9", header="207,748,447", insts="13", calls="no",
               depth="1", copies="1", hot="2.89e9",
               chain="read::parse -> parse_string -> str_fold -> write_until "
               "-> Copied<Iter<u8>>::position -> position::check",
               remark_class="ILLEGAL to vectorize (loop contains an "
               "unsupported switch; incorrect number of successors from early "
               "exiting block; value that could not be identified as a "
               "reduction is used outside the loop)"),
    "L5": dict(mark="jaq_json::write::write", mark_share="4.48%",
               obj="0.1%", str="0.0%", rw="22.6%",
               trip="1.0", header="5,591,880", insts="200", calls="yes",
               depth="1", copies="1", hot="1.12e9",
               chain="jaq_json::write::write -> <slice::Iter<..>>::next",
               remark_class="not recorded for this site (it is outside the "
               "frozen site set, so no remark attribution was run for it)"),
}


# ---------------------------------------------------------------------------
# V7: the platform block
# ---------------------------------------------------------------------------
#
# lscpu and /sys/devices/system/cpu/cpu0/cache on this machine. The L3 figure
# is what WSL2 exposes (one 32 MiB instance shared by all 32 logical CPUs);
# decision 17 recorded that the two CCDs of a 5950X are not visible from
# inside WSL2, so the number is reported as seen and not "corrected".

PLATFORM_BLOCK = """\
## The machine this will run on

  cpu model         AMD Ryzen 9 5950X, 16 cores / 32 threads, family 25 model 33
  microarchitecture Zen 3 (LLVM target-cpu `znver3`)
  isa               AVX, AVX2, FMA, BMI1, BMI2, AES, SHA, VAES, VPCLMULQDQ,
                    POPCNT, MOVBE, RDSEED, ADX, CLWB, CLFLUSHOPT, ERMS, FSRM
  no isa            **no AVX-512 of any kind**, no AMX, no SVE
  vector width      256 bit, 16 architectural ymm registers
                    one ymm holds 32 x u8, 16 x u16, 8 x u32/f32, 4 x u64/f64
                    two 256-bit FP/vector pipes, 2 loads + 1 store per cycle
  l1 data           32 KiB, 8-way, per core
  l1 instruction    32 KiB, 8-way, per core
  l2 unified        512 KiB, 8-way, per core
  l3 unified        32 MiB, 16-way, reported by this kernel as one instance
                    shared by all 32 logical cpus (this is a WSL2 guest; the
                    two CCDs of the physical part are not visible from inside
                    it, so treat the L3 figure as a guest-visible number)
  how it is timed   the process is pinned to one logical cpu (`taskset -c 4`)
                    with a 250 ms settle gap between runs; its SMT sibling is
                    left idle; 15 interleaved repetitions, shuffled label
                    order, paired bootstrap 95% CI
  compiler          rustc 1.100.0-nightly (bba531001), LLVM 23.1.1
  baseline flags    -Copt-level=3, fat LTO, 1 codegen unit, -Cdebuginfo=1,
                    -Ctarget-cpu=native, PGO (-Cprofile-use, one shared
                    profile), -Cllvm-args=-hints-allow-reordering=false
                    (that last flag means a width hint does **not** authorise
                    reassociating a floating-point reduction; a
                    non-reassociable reduction is simply not widened)
"""


# ---------------------------------------------------------------------------
# V11: the hint guide
# ---------------------------------------------------------------------------
#
# General mechanism only. It names no function, loop or file of this program:
# choosing per-site candidates is the thing this study is not allowed to do.

HINT_GUIDE = """\
## What each hint in the list does, in general

This section is about the hints themselves. It says nothing about the sites
in this request.

`inline` (`inlinehint`)
  Raises the inliner's threshold for one function, so callers that were just
  over the limit now paste its body in. It pays on a small, hot function
  called from few places, where the caller then specialises on constants it
  passes. It backfires on a large body, on a function called from many
  places (every copy costs instruction cache), and it is a no-op when the
  function already carries the attribute or is already inlined everywhere.

`inline(never)` (`noinline`)
  Forces one out-of-line copy. It pays when a large body was being pasted
  into many callers and the instruction cache, not the call overhead, is the
  cost --- typically a big dispatch or a recursive body with many
  monomorphizations. It costs a call and the lost specialisation at every
  call site, so it hurts on a small hot leaf.

`cold`
  Tells LLVM the function is rarely executed: calls to it move out of line,
  it is optimised for size, and it is never inlined. It is correct only for
  error and fallback paths. On anything that carries a real share of the
  cycles it is a straight pessimisation.

`align=16 / 32 / 64`
  Moves the function's entry to that boundary, which changes how its first
  instructions and its first loop fall into the 32-byte fetch windows and the
  uop cache. 16 is already the x86-64 default, so it mostly pins what is
  there. Larger values can help a function whose hot loop sits near its
  entry, they waste padding, and their effect is close to unpredictable ---
  when alignment has been measured to matter it was usually as a whole-build
  setting rather than one function's entry.

`unroll.count = 2 / 4 / 8`
  Overrides the unroller, including its own advice not to unroll. It pays on
  a short body with a high trip count, where loop control and the dependence
  chain between iterations are a real fraction of the work. It costs code
  size and a longer remainder loop, so it hurts when the trip count is low,
  when the body is already large, or when the body contains a call --- the
  call dominates whatever the loop control cost. Note that unrolling runs
  after vectorisation, so on a loop LLVM vectorises this unrolls the vector
  loop.

`unroll.disable`
  Forbids unrolling. It pays when the caller's instruction footprint is the
  problem, or when the loop is short and its trip count unpredictable.

`vectorize.width = 2 / 4 / 8 / 16`
  Forces the number of lanes per vector iteration and enables vectorisation.
  The right width is a property of the element type and the machine's vector
  register: lanes x element size should reach the register width, and going
  past it makes LLVM emit several registers per iteration. It pays when the
  loop is long, straight-line, has no calls, and LLVM chose a width below
  what the element type allows. It is **not a permission slip**: when the
  compiler reports the loop as illegal to vectorize --- an early exit, an
  unsupported switch, a value that is not a recognised reduction escaping the
  loop, an undeterminable trip count --- the hint is dropped and the build
  is unchanged. It hurts when the trip count is too low to amortise the
  remainder loop, and a width far above the register width has been measured
  to produce code several times slower than the default.

`interleave.count = 1 / 2 / 4`
  How many independent vector bodies run per iteration. More chains hide the
  latency of a dependent reduction at the cost of registers and a longer
  remainder; `1` shortens the loop when the default interleaving was too
  aggressive for the trip count.
"""


# ---------------------------------------------------------------------------
# V13: measured examples
# ---------------------------------------------------------------------------

EXAMPLES_BLOCK = """\
## Six hints of this vocabulary, measured on other programs

These are real measurements from two earlier targets of this project, not
this program. They are here as calibration for how large the effects of this
vocabulary are and which shapes respond.

1. A byte-counting loop (`bytes.iter().filter(|&&b| b == b'"').count()`),
   25% of its program, which LLVM had vectorised at width 4 with interleave
   4. Forcing `vectorize.width = 32` made it **2.2x slower**: the forced
   width was materialised as many narrow operations plus a long remainder.
   Forcing width 16 on the same loop was also slower than the default. A
   width far above what the element type needs in one register is not a
   bigger version of the right answer.
2. A floating-point dot product. A width hint on it changed the program's
   **output**, because widening a reduction reorders the additions. The build
   in this study pins `-hints-allow-reordering=false` for that reason, and a
   non-reassociable reduction is therefore not widened at all --- the hint is
   accepted and does nothing.
3. An early-exit search loop (scan until a byte matches). Every width and
   interleave hint left the machine code bit-identical: the compiler had
   already reported the loop as not vectorizable, and metadata does not make
   an illegal transformation legal.
4. On a compression library, a whole-build sweep of 30 configurations found
   nothing above the 3% floor from loop hints alone; the largest single
   effect in the sweep, about +1.6%, came from **capping** unrolling rather
   than increasing it.
5. On a JSON processor, a sweep of 33 whole-build configurations produced
   +2.1% from an SLP-vectorizer threshold, and the next largest effect was
   from function **alignment** --- as a build-wide setting, applied to every
   function, not as one function's entry.
6. Across four programs already built with `-Copt-level=3`, fat LTO,
   `target-cpu=native` and PGO, the total room found for loop hints was
   between 0% and 2%. The prior that a given hint at a given site changes the
   whole program by more than 3% is low, and the useful question is which
   site has a mechanism at all.
"""


# ---------------------------------------------------------------------------
# V14: Claude's reasoning, generalised (no conclusion about any site)
# ---------------------------------------------------------------------------

REASONING_BLOCK = """\
## How a careful reader would work through a site like these

This section is a method, not an answer. It states no conclusion about any
site in this request.

Start from what the compiler already reported about the region, because it
decides which candidates can do anything at all. If the report says the loop
could not be vectorized --- an early exit, an unsupported switch, a value
that is not a recognised reduction escaping the loop, an induction variable
or trip count that could not be identified --- then every `vectorize.width`
and `interleave.count` candidate is inert, and the only live candidates are
the unroll ones, because unroll metadata does override the unroller's own
advice. If the report instead shows the loop *was* vectorized and at which
width, then the question becomes whether that width uses the machine's vector
register for the element type in play, and a loop whose reported width leaves
most of the register idle is the rare case where forcing a wider one has a
mechanism.

Then read the trip count against the body. Unrolling and widening both buy
fewer iterations of loop control and pay for it with a remainder loop and
code size. A high trip count over a tiny body is where that trade is
favourable; a trip count of one or two makes every such candidate pure cost,
whatever the loop's share of the profile. A body containing a call is a third
case: the call dominates, so the loop-control saving is invisible, and this
is also why the unroller declines on its own.

For a function attribute, read the size and the number of monomorphizations
against the attributes the function already carries. An `inline` candidate is
a no-op on a function that already has the hint, and it is the wrong
direction on a body large enough that no threshold would admit it anyway.
`inline(never)` has a mechanism only where a large body is being replicated
into callers and instruction cache is the constraint. `cold` is a statement
that the function is off the hot path, so on anything holding a real share of
the cycles it is a pessimisation regardless of anything else. Alignment
candidates have no site-specific mechanism to reason from.

Finally weigh the site's share. A hint has to move the whole program, so the
most a site can contribute is bounded by its share of the cycles, and a
perfect improvement inside a 1% site cannot reach a 3% whole-program
threshold. The honest answer at a site where no candidate has a mechanism is
to leave it alone, and a reader who never answers that way is not reading.
"""


# ---------------------------------------------------------------------------
# question wording per variant
# ---------------------------------------------------------------------------

NEUTRAL_KEEP_FN = (
    "Change nothing about this function's attributes. This is the "
    "'no change' option: the build keeps whatever LLVM's own cost model "
    "decides, exactly as in the baseline."
)
NEUTRAL_KEEP_LOOP = (
    "Attach no metadata to this loop. This is the 'no change' option: "
    "LLVM's vectoriser and unroller decide with their own cost model, "
    "exactly as in the baseline."
)

Q_V1_FN = (
    "Section `{qname}` of the state describes one marked function of this "
    "program. We are going to try exactly one hint on it in the next build. "
    "Which of these is the most promising for making this function faster on "
    "this workload?"
)
Q_V1_LOOP = (
    "Section `{qname}` of the state describes one loop inside a marked "
    "function of this program. We are going to try exactly one hint on it in "
    "the next build. Which of these is the most promising for making this "
    "loop faster on this workload?"
)
Q_V2_FN = (
    "Section `{qname}` of the state describes one marked function of this "
    "program. Which single hint from the list is most likely to make this "
    "function faster on this workload?"
)
Q_V2_LOOP = (
    "Section `{qname}` of the state describes one loop inside a marked "
    "function of this program. Which single hint from the list is most likely "
    "to make this loop faster on this workload?"
)

SEARCH_FRAMING = """\
## What this request is

This is round 1 of a search. Each answer becomes one entry of a build plan,
the plan is built once, and the result is measured against the baseline and
recorded. A hint that turns out not to help costs one build and is discarded;
nothing here is shipped to anyone, and no answer has to be defended later.
The search only learns from arms that differ from the baseline: a round in
which every site is left unchanged rebuilds the baseline and measures
nothing. Where a hint has any mechanism at all, trying it is worth more than
keeping the default; where no candidate has a mechanism, saying so is still
the right answer.
"""

V1_PREAMBLE_REPLACEMENT = """\
## What is being decided

A Rust program is compiled with one frozen recipe. The only thing that varies
between builds is a set of optimisation hints attached to named functions and
to the loops inside them; no source file is ever edited. You are shown one
site per question and you choose one hint for it from a fixed list. All the
questions in this request are answered independently and they all take effect
in the same build, which is then measured as a whole.

At each site in this request the build **will** apply one of the listed
hints. The question is which one. The measurement is end-to-end wall time
over the case set below; the noise floor of this machine is about 1%
aggregated. Hints that change the program's output are rejected regardless of
speed.

"""

V2_PREAMBLE_REPLACEMENT = """\
## What is being decided

A Rust program is compiled with one frozen recipe. The only thing that varies
between builds is a set of optimisation hints attached to named functions and
to the loops inside them; no source file is ever edited. You are shown one
site per question and you choose one hint for it from a fixed list. All the
questions in this request are answered independently and they all take effect
in the same build, which is then measured as a whole.

One of the options at every site is "no change", which reproduces the
baseline at that site. It is one option among the others, neither preferred
nor discouraged. The measurement is end-to-end wall time over the case set
below; the noise floor of this machine is about 1% aggregated. Hints that
change the program's output are rejected regardless of speed.

"""

# V12 stage 1
FAMILIES_FN = {
    "leave_alone": "No function attribute would help this function; leave it "
                   "as the baseline has it.",
    "inlining": "An inlining attribute (`inlinehint` or `noinline`): change "
                "whether and how often this function's body is pasted into "
                "its callers.",
    "cold": "The `cold` attribute: declare this function to be off the hot "
            "path, so callers move calls to it out of line and it is "
            "optimised for size.",
    "alignment": "A function alignment attribute (16, 32 or 64 bytes): move "
                 "the function's entry point to a coarser boundary.",
}
FAMILIES_LOOP = {
    "leave_alone": "No loop hint would help this loop; leave it as the "
                   "baseline has it.",
    "unroll": "An unrolling hint (`unroll.count = 2/4/8` or "
              "`unroll.disable`): change how many copies of the body run per "
              "iteration, overriding the unroller's own decision.",
    "vectorize": "A vectorisation width hint (`vectorize.width = 2/4/8/16`): "
                 "force the number of lanes per vector iteration, and enable "
                 "vectorisation.",
    "interleave": "An interleaving hint (`interleave.count = 1/2/4`): change "
                  "how many independent vector chains run per iteration.",
}
FAMILY_MEMBERS = {
    "inlining": ["inline", "inline_never"],
    "cold": ["cold"],
    "alignment": ["align_16", "align_32", "align_64"],
    "unroll": ["unroll_count_2", "unroll_count_4", "unroll_count_8",
               "unroll_disable"],
    "vectorize": ["vectorize_width_2", "vectorize_width_4",
                  "vectorize_width_8", "vectorize_width_16"],
    "interleave": ["interleave_count_1", "interleave_count_2",
                   "interleave_count_4"],
}

Q_V12_STAGE1_FN = (
    "Section `{qname}` of the state describes one marked function of this "
    "program. Before choosing a value, choose a kind: which of these families "
    "of change, if any, has a mechanism that could make this function faster "
    "on this workload?"
)
Q_V12_STAGE1_LOOP = (
    "Section `{qname}` of the state describes one loop inside a marked "
    "function of this program. Before choosing a value, choose a kind: which "
    "of these families of hint, if any, has a mechanism that could make this "
    "loop faster on this workload?"
)
Q_V12_STAGE2 = (
    "Section `{qname}` of the state describes one site of this program. The "
    "family of hint to use there has already been decided: {family}. Which "
    "value inside that family should the build use?"
)

SCORE_CRITERIA = [
    "No measurable change: under 3% on this site's own time, or an effect "
    "too small to survive the whole-program measurement.",
    "Small gain: 3-10% faster on this site.",
    "Clear gain: 10-50% faster on this site.",
    "Large gain: more than 50% faster on this site.",
]
Q_V5_SCORE = (
    "Section `{qname}` of the state describes one site of this program. How "
    "much faster would that site get if the build applied `{cand}` to it "
    "({desc})?"
)
Q_V5_NOUL = (
    "Section `{qname}` of the state describes one site of this program. Is "
    "this site worth spending a hint on at all, given its share of the "
    "program's cycles, its shape, and the candidates available for it?"
)


# ---------------------------------------------------------------------------
# reading the Experiment 3 log
# ---------------------------------------------------------------------------

def _split_state(state):
    head, _, rest = state.partition("### q0")
    rest = "### q0" + rest
    parts = re.split(r"(?m)^(### q\d+)\n", rest)
    out = {}
    it = iter(parts[1:])
    for name, body in zip(it, it):
        out[name.strip()[4:]] = body
    return head, out


def load_material(jsonl_path=DEFAULT_JSONL):
    """The verbatim Experiment 3 request material the variants reuse.

    Phase A comes from round 1 (the only round whose 'previous rounds'
    section says 'nothing has been measured yet'); phase B comes from
    round 3, because rounds 1 and 2 of phase B were lost to HTTP 503 and
    never reached Jev. That asymmetry is real and is recorded in the study's
    README: V0's loop half therefore carries two rounds of history.
    """
    rows = [json.loads(l) for l in open(jsonl_path)]
    a = next(r for r in rows if r["phase"] == "A" and r["http_status"] == 200)
    b = next(r for r in rows if r["phase"] == "B" and r["http_status"] == 200)
    ha, qa = _split_state(a["request"]["state"])
    hb, qb = _split_state(b["request"]["state"])
    return {
        "A": dict(head=ha, sections=qa, request=a["request"],
                  site_map=a["site_map"]),
        "B": dict(head=hb, sections=qb, request=b["request"],
                  site_map=b["site_map"]),
    }


def _built_L5_section():
    """L5's section in the frozen template, assembled from sites.json.

    It was never asked about, so there is no verbatim text for it. Only the
    two fields the driver would have filled from a source search and from
    remark attribution are missing, and the section says so rather than
    inventing them.
    """
    p = PROFILE["L5"]
    return """
site kind      one loop inside a marked function
marked function jaq_json::write::write
owner after inlining  jaq_json::write::write
location       iter.rs:605 (loop nesting depth 1)
profile share of the marked function  4.48%
average trip count (from the PGO profile)  1
loop body      200 LLVM instructions, calls inside: yes, floating-point reduction: no
already vectorized when the hint is attached: no
function attributes this round already applied: none

source of the marked function this loop belongs to:
  (not available: the source file is not in the vendored tree)

what LLVM said about this region in the baseline build:
  (not recorded: this site is outside the frozen site set of decision 63, so
   no remark attribution was run for it)

  what earlier rounds chose here:
    (this site was not asked about in an earlier round)
"""


# ---------------------------------------------------------------------------
# section surgery
# ---------------------------------------------------------------------------

ANCHOR_RE_REMARKS = re.compile(
    r"\nwhat LLVM said about this region in the baseline build:\n"
    r"(?:.*\n)*?(?=\n  what earlier rounds chose here:|\Z)")
ANCHOR_RE_HISTORY = re.compile(
    r"\n  what earlier rounds chose here:\n(?:.*\n)*?(?=\Z)")
ANCHOR_RE_ATTRS_FN = re.compile(r"(?m)^attributes now .*\n")
ANCHOR_RE_ATTRS_LOOP = re.compile(
    r"(?m)^function attributes this round already applied: .*\n")


def strip_anchors(section):
    """V3: drop the baseline remarks, the current attributes and the history."""
    s = ANCHOR_RE_REMARKS.sub("\n", section)
    s = ANCHOR_RE_HISTORY.sub("\n", s)
    s = ANCHOR_RE_ATTRS_FN.sub("", s)
    s = ANCHOR_RE_ATTRS_LOOP.sub("", s)
    return re.sub(r"\n{3,}", "\n\n", s)


_SRC_LINE = re.compile(r"^\s*(\d+)\s?[ >]", )


def shorten_excerpts(section, halfwidth=10):
    """V6: cut every numbered source excerpt to +-`halfwidth` lines.

    An excerpt is a run of lines that start with a line number; the site's own
    line is the one whose number is followed by `>`. Everything else in the
    section is left alone.
    """
    lines = section.split("\n")
    out = []
    i = 0
    while i < len(lines):
        if re.match(r"^\s*\d+\s*[> ]", lines[i]) and \
                re.match(r"^\s*\d+", lines[i]):
            j = i
            while j < len(lines) and re.match(r"^\s*\d+[ >]", lines[j]):
                j += 1
            block = lines[i:j]
            mark = None
            for k, ln in enumerate(block):
                if re.match(r"^\s*\d+>", ln):
                    mark = k
                    break
            if mark is None:
                mark = len(block) // 2
            lo = max(0, mark - halfwidth)
            hi = min(len(block), mark + halfwidth + 1)
            if lo > 0:
                out.append("  ... (%d earlier lines omitted)" % lo)
            out.extend(block[lo:hi])
            if hi < len(block):
                out.append("  ... (%d later lines omitted)"
                           % (len(block) - hi))
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def profile_table(site):
    """V8: the per-site structured profile block."""
    p = PROFILE[site["id"]]
    if site["kind"] == "fn":
        return """
profile and shape of this function, as a table

  | field | value |
  |---|---|
  | perf self share (all six workloads) | %(self)s |
  | perf reach share (this function anywhere in the inline frame stack) | %(reach)s |
  | share of the objsearch case | %(obj)s |
  | share of the strproc case | %(str)s |
  | share of the readwrite case | %(rw)s |
  | size and shape after LTO | %(shape)s |
  | attributes it carries now | %(attrs)s |
  | what the baseline remarks on this function's lines are about | %(rc)s |
""" % dict(self=p["self_share"], reach=p["reach"], obj=p["obj"],
           str=p["str"], rw=p["rw"], shape=p["shape"], attrs=p["attrs"],
           rc=p["remark_class"])
    return """
profile and shape of this loop, as a table

  | field | value |
  |---|---|
  | marked function it belongs to | %(mark)s |
  | that function's perf share (all six workloads) | %(ms)s |
  | its share of the objsearch case | %(obj)s |
  | its share of the strproc case | %(str)s |
  | its share of the readwrite case | %(rw)s |
  | average trip count (PGO) | %(trip)s |
  | loop header execution count (PGO) | %(hdr)s |
  | body size | %(insts)s LLVM instructions |
  | calls inside the body | %(calls)s |
  | loop nesting depth | %(depth)s |
  | loops this site key names | %(copies)s |
  | hotness (header count x body instructions) | %(hot)s |
  | inline chain from the marked function down to the loop | %(chain)s |
  | what the baseline remarks on this loop's line say | %(rc)s |
""" % dict(mark=p["mark"], ms=p["mark_share"], obj=p["obj"], str=p["str"],
           rw=p["rw"], trip=p["trip"], hdr=p["header"], insts=p["insts"],
           calls=p["calls"], depth=p["depth"], copies=p["copies"],
           hot=p["hot"], chain=p["chain"], rc=p["remark_class"])


# ---------------------------------------------------------------------------
# building a request
# ---------------------------------------------------------------------------

BASE_VARIANTS = {
    # variant -> (preamble replacement, keep_default kept?, neutral keep?,
    #             question wording, strip anchors?, excerpt halfwidth,
    #             platform block?, profile table?, extra blocks, one per req)
    "V0":  dict(pre=None, keep=True,  neutral=False, q="frozen", anchors=True,
                excerpt=None, platform=False, profile=False, extra=[],
                per_site=False, frozen_batch=True),
    "V0b": dict(pre=None, keep=True,  neutral=False, q="frozen", anchors=True,
                excerpt=None, platform=False, profile=False, extra=[],
                per_site=False),
    "V1":  dict(pre=V1_PREAMBLE_REPLACEMENT, keep=False, neutral=False,
                q="v1", anchors=True, excerpt=None, platform=False,
                profile=False, extra=[], per_site=False),
    "V2":  dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="v2", anchors=True, excerpt=None, platform=False,
                profile=False, extra=[], per_site=False),
    "V3":  dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="v2", anchors=False, excerpt=None, platform=False,
                profile=False, extra=[], per_site=False),
    "V4":  dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="v2", anchors=True, excerpt=None, platform=False,
                profile=False, extra=["search"], per_site=False),
    "V5":  dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="score", anchors=True, excerpt=None, platform=False,
                profile=False, extra=[], per_site=False),
    "V6":  dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="v2", anchors=True, excerpt=10, platform=False,
                profile=False, extra=[], per_site=False),
    "V7":  dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="v2", anchors=True, excerpt=None, platform=True,
                profile=False, extra=[], per_site=False),
    "V8":  dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="v2", anchors=True, excerpt=None, platform=False,
                profile=True, extra=[], per_site=False),
    "V9":  dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="v2", anchors=True, excerpt=None, platform=True,
                profile=True, extra=[], per_site=True),
    "V10": dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="v2", anchors=True, excerpt=None, platform=True,
                profile=True, extra=["search"], per_site=True),
    "V11": dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="v2", anchors=True, excerpt=None, platform=True,
                profile=True, extra=["guide"], per_site=False),
    "V12": dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="family", anchors=True, excerpt=None, platform=True,
                profile=True, extra=[], per_site=False),
    "V13": dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="v2", anchors=True, excerpt=None, platform=True,
                profile=True, extra=["examples"], per_site=False),
    "V14": dict(pre=V2_PREAMBLE_REPLACEMENT, keep=True, neutral=True,
                q="v2", anchors=True, excerpt=None, platform=True,
                profile=True, extra=["reasoning"], per_site=False),
    # Added after the first pass. V1 was the only framing that produced a
    # vectorisation hint, and it produced width 4 on a byte loop; these two
    # ask the same forced choice with the machine and the profile spelled
    # out, and then with the hint guide as well, to see whether the width
    # moves to what the register can hold.
    "V15": dict(pre=V1_PREAMBLE_REPLACEMENT, keep=False, neutral=False,
                q="v1", anchors=True, excerpt=None, platform=True,
                profile=True, extra=[], per_site=False),
    "V16": dict(pre=V1_PREAMBLE_REPLACEMENT, keep=False, neutral=False,
                q="v1", anchors=True, excerpt=None, platform=True,
                profile=True, extra=["guide"], per_site=False),
}

VARIANTS = list(BASE_VARIANTS)

EXTRA_BLOCKS = {
    "search": SEARCH_FRAMING,
    "guide": HINT_GUIDE,
    "examples": EXAMPLES_BLOCK,
    "reasoning": REASONING_BLOCK,
}

PREAMBLE_RE = re.compile(
    r"## What is being decided\n(?:.*\n)*?(?=## The build every arm shares)")
PREV_ROUNDS_RE = re.compile(
    r"## Results of the previous rounds\n(?:.*\n)*?"
    r"(?=## The sites in this request)")


def section_for(site, material):
    if site["src"][0] == "built":
        return _built_L5_section()
    phase, q = site["src"]
    return material[phase]["sections"][q]


def criteria_for(site, cfg):
    cands = dict(jev_vocab.candidates_for(site["kind"]))
    if not cfg["keep"]:
        cands.pop(jev_vocab.KEEP_DEFAULT)
    elif cfg["neutral"]:
        cands[jev_vocab.KEEP_DEFAULT] = (
            NEUTRAL_KEEP_FN if site["kind"] == "fn" else NEUTRAL_KEEP_LOOP)
    return cands


def instructions_for(site, cfg, qname, **kw):
    style = cfg["q"]
    if style == "frozen":
        return jev_vocab.instructions_for(site["kind"], qname)
    if style == "v1":
        t = Q_V1_FN if site["kind"] == "fn" else Q_V1_LOOP
        return t.format(qname=qname)
    if style in ("v2", "score"):
        t = Q_V2_FN if site["kind"] == "fn" else Q_V2_LOOP
        return t.format(qname=qname)
    if style == "family":
        if kw.get("stage") == 2:
            return Q_V12_STAGE2.format(qname=qname, family=kw["family"])
        t = Q_V12_STAGE1_FN if site["kind"] == "fn" else Q_V12_STAGE1_LOOP
        return t.format(qname=qname)
    raise ValueError(style)


def build_state(variant, sites, material, stage=None, families=None):
    """The `state` string for one request of `variant` covering `sites`."""
    cfg = BASE_VARIANTS[variant]
    phase = "A" if sites[0]["kind"] == "fn" else "B"
    head = material[phase]["head"]

    header = ("# jev-opt prompt study --- %s, variant %s, vocabulary %s\n"
              % (STUDY_VERSION, variant, jev_vocab.VOCAB_VERSION))
    if variant == "V0":
        header = head.split("\n")[0] + "\n"
        body = head[len(head.split("\n")[0]) + 1:]
    else:
        body = head[len(head.split("\n")[0]) + 1:]

    if cfg["pre"]:
        body = PREAMBLE_RE.sub(cfg["pre"], body)
    if not cfg["anchors"]:
        body = PREV_ROUNDS_RE.sub("", body)
    for name in cfg["extra"]:
        body = body.replace("## The build every arm shares",
                            EXTRA_BLOCKS[name] + "\n## The build every arm "
                            "shares", 1)
    if cfg["platform"]:
        body = body.replace("## Where the hints are applied",
                            PLATFORM_BLOCK + "\n## Where the hints are "
                            "applied", 1)

    body = re.sub(r"## The sites in this request \(\d+ of them\)",
                  "## The sites in this request (%d of them)" % len(sites),
                  body)

    out = [header, body.rstrip(), ""]
    for i, site in enumerate(sites):
        qname = "q%d" % i
        sec = section_for(site, material)
        if not cfg["anchors"]:
            sec = strip_anchors(sec)
        if cfg["excerpt"]:
            sec = shorten_excerpts(sec, cfg["excerpt"])
        out.append("### %s" % qname)
        out.append(sec.rstrip())
        if cfg["profile"]:
            out.append(profile_table(site).rstrip())
        out.append("")
    return "\n".join(out)


def build_questions(variant, sites, stage=None, families=None):
    cfg = BASE_VARIANTS[variant]
    qs = {}
    meta = {}
    for i, site in enumerate(sites):
        qname = "q%d" % i
        meta[qname] = site["id"]
        if cfg["q"] == "score":
            cands = criteria_for(site, cfg)
            for j, (cid, desc) in enumerate(cands.items()):
                if cid == jev_vocab.KEEP_DEFAULT:
                    continue
                sub = "%s_s%d" % (qname, j)
                qs[sub] = dict(
                    type="score",
                    instructions=Q_V5_SCORE.format(
                        qname=qname, cand=jev_vocab.spec_spelling(
                            site["kind"], cid),
                        desc=desc.split(".")[0].strip()),
                    criteria=list(SCORE_CRITERIA))
                meta[sub] = "%s/%s" % (site["id"], cid)
            noul = "%s_worth" % qname
            qs[noul] = dict(type="noul",
                            instructions=Q_V5_NOUL.format(qname=qname))
            meta[noul] = "%s/worth" % site["id"]
        elif cfg["q"] == "family" and stage == 1:
            fam = FAMILIES_FN if site["kind"] == "fn" else FAMILIES_LOOP
            qs[qname] = dict(type="choice",
                             instructions=instructions_for(site, cfg, qname),
                             criteria=dict(fam))
        elif cfg["q"] == "family" and stage == 2:
            family = families[site["id"]]
            allc = dict(jev_vocab.candidates_for(site["kind"]))
            crit = {c: allc[c] for c in FAMILY_MEMBERS[family]}
            qs[qname] = dict(
                type="choice",
                instructions=instructions_for(site, cfg, qname, stage=2,
                                              family=family),
                criteria=crit)
        else:
            qs[qname] = dict(type="choice",
                             instructions=instructions_for(site, cfg, qname),
                             criteria=criteria_for(site, cfg))
    return qs, meta


def requests_for(variant, material, stage=None, families=None):
    """[(tag, {model,state,questions}, {qname: site_id})] for one repeat."""
    cfg = BASE_VARIANTS[variant]
    out = []

    if cfg.get("frozen_batch"):
        # V0: the request Experiment 3 actually sent, verbatim, both phases.
        for phase in ("A", "B"):
            req = dict(material[phase]["request"])
            qmap = {q: v.get("site_id", v.get("label"))
                    for q, v in material[phase]["site_map"].items()}
            out.append(("%s-phase%s" % (variant, phase), req, qmap))
        return out

    groups = []
    if cfg["per_site"]:
        groups = [[s] for s in SITES]
    else:
        groups = [[s for s in SITES if s["kind"] == "fn"],
                  [s for s in SITES if s["kind"] == "loop"]]

    for g in groups:
        if not g:
            continue
        if stage == 2:
            # A family with one member needs no second question: the stage-1
            # answer already named the candidate.
            g = [s for s in g
                 if families.get(s["id"]) not in (None, "leave_alone")
                 and len(FAMILY_MEMBERS.get(families[s["id"]], [])) > 1]
            if not g:
                continue
        state = build_state(variant, g, material, stage=stage,
                            families=families)
        qs, meta = build_questions(variant, g, stage=stage, families=families)
        tag = "%s-%s" % (variant, "-".join(s["id"] for s in g))
        if stage:
            tag += "-stage%d" % stage
        out.append((tag, dict(model="typesafe-ai/jev", state=state,
                              questions=qs), meta))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default=DEFAULT_JSONL)
    ap.add_argument("--variant")
    ap.add_argument("--stage", type=int)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--sizes", action="store_true")
    a = ap.parse_args()

    if a.list:
        for v in VARIANTS:
            print(v)
        return
    material = load_material(a.jsonl)
    if a.sizes:
        for v in VARIANTS:
            if v == "V12":
                rs = requests_for(v, material, stage=1)
            else:
                rs = requests_for(v, material)
            print("%-5s %2d request(s), %5d question(s), state %6d chars max"
                  % (v, len(rs), sum(len(r[1]["questions"]) for r in rs),
                     max(len(r[1]["state"]) for r in rs)))
        return
    if a.variant:
        fam = None
        if a.variant == "V12" and a.stage == 2:
            fam = {s["id"]: "vectorize" if s["kind"] == "loop" else "inlining"
                   for s in SITES}
        for tag, req, meta in requests_for(a.variant, material,
                                           stage=a.stage, families=fam):
            print("=" * 70)
            print(tag, json.dumps(meta))
            if a.do_print:
                print(req["state"])
                print(json.dumps(req["questions"], indent=1)[:4000])


if __name__ == "__main__":
    main()
