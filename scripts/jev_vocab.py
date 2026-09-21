#!/usr/bin/env python3
"""The frozen hint vocabulary and the frozen wording Jev sees for it.

SPEC.ja.md 1(2) fixes the list of hints; decision 58 fixes that the list is
the same for every mark and that `KEEP_DEFAULT` is always in it; decision 19
records that *how the state is written changes the answer*, so the candidate
descriptions are part of the measurement conditions and are frozen here, in
one place, rather than built ad hoc by the driver.

Freezing rule (SPEC.ja.md 1(2), 6): nothing in this file may change between
round 1 and the last round of a run, and any change to it invalidates the
comparison with earlier runs. `VOCAB_VERSION` is written into the run
manifest and into every Jev request log line so a changed vocabulary is
visible after the fact instead of being silently mixed in.

Three kinds of site:

  fn      one marked function          -> plan `fn_attrs` entry
  loop    one `loop_in_mark` loop      -> plan `loop_md` entry
  build   the pseudo-site `__build__`  -> one extra rustc flag for the build

Candidate ids are plain identifiers (plus the literal `KEEP_DEFAULT`) because
they become JSON object keys in the Choice `criteria` object and appear again
in `answers.<q>.probabilities`. The SPEC spelling of each candidate
(`inline(never)`, `align=64`, `unroll.count=4`, ...) is in the description,
which is what Jev reads.
"""

VOCAB_VERSION = "v1-2026-09-22"

KEEP_DEFAULT = "KEEP_DEFAULT"

# The pseudo-site that carries the one build-wide compiler knob of
# SPEC.ja.md 1(2) row 4 / 6 ("the compiler-setting hint is one per build, not
# one per mark").
BUILD_SITE_ID = "__build__"


# ---------------------------------------------------------------------------
# function attributes
# ---------------------------------------------------------------------------
#
# Each value is (description, plan fragment). The fragment is merged into the
# plan's `fn_attrs` entry for that function (plugin/README.md "Plan schema").
# KEEP_DEFAULT has an empty fragment and the driver emits no entry at all for
# it, so an all-KEEP_DEFAULT plan is byte-identical to the empty plan whose
# off-equivalence results.md "Day 3 (plugin)" 5a measured.

FN_CANDIDATES = {
    KEEP_DEFAULT: (
        "Leave this function's attributes exactly as they are. LLVM's own "
        "inlining cost model and the default 16-byte function alignment "
        "decide, as they do in the baseline build.",
        {},
    ),
    "inline": (
        "Add the `inlinehint` attribute (the SPEC vocabulary's `inline`). It "
        "raises the inliner's threshold for this function, so it is inlined "
        "into callers it would otherwise be too large for. Its own loops then "
        "become loops of the callers, and specialisation on the call site "
        "becomes possible; code size and I-cache pressure grow.",
        {"inline": "hint"},
    ),
    "inline_never": (
        "Add the `noinline` attribute (the SPEC vocabulary's `inline(never)`). "
        "The function stays a single out-of-line copy. Call overhead is paid "
        "at every call site, and in exchange the callers stay small and the "
        "function's own body is optimised once for all of them.",
        {"inline": "never"},
    ),
    "cold": (
        "Add the `cold` attribute. It tells LLVM this function is rarely "
        "executed: callers place calls to it out of line, it is optimised for "
        "size rather than speed, and it is never inlined. Correct only if the "
        "function really is off the hot path; on a hot function it is a "
        "pessimisation.",
        {"cold": True},
    ),
    "align_16": (
        "Set the function's alignment to 16 bytes (the SPEC vocabulary's "
        "`align=16`). This is the usual default on x86-64, so it mostly means "
        "'pin the current alignment'.",
        {"align": 16},
    ),
    "align_32": (
        "Set the function's alignment to 32 bytes (`align=32`). The entry "
        "point starts on a 32-byte boundary, which changes how the function's "
        "first instructions and its first loop fall into the 32-byte "
        "instruction-fetch windows and the uop cache.",
        {"align": 32},
    ),
    "align_64": (
        "Set the function's alignment to 64 bytes (`align=64`). The function "
        "starts on a cache line. Same mechanism as align=32, one step "
        "coarser, and it wastes up to 63 bytes of padding per function.",
        {"align": 64},
    ),
}


# ---------------------------------------------------------------------------
# loop hints
# ---------------------------------------------------------------------------
#
# Attached as `llvm.loop.*` metadata at VectorizerStartEP, i.e. after inlining
# and loop canonicalisation and immediately before LoopVectorize
# (plugin/README.md "Extension points"). Every arm of this experiment is built
# with `-Cllvm-args=-hints-allow-reordering=false`, so a width hint on a
# floating-point reduction does not authorise reassociating it
# (SPEC.ja.md 2, decision 60); the descriptions say so because decision 19
# showed that what the state does and does not say moves the answer.

LOOP_CANDIDATES = {
    KEEP_DEFAULT: (
        "Attach no metadata to this loop. LLVM's vectoriser and unroller "
        "decide with their own cost model, as in the baseline build.",
        {},
    ),
    "unroll_count_2": (
        "Attach `llvm.loop.unroll.count = 2`: unroll the loop body twice. "
        "Halves the loop-control overhead and gives the scheduler two "
        "iterations to interleave. Note that this runs after vectorisation, "
        "so on a loop LLVM vectorises it unrolls the *vector* loop.",
        {"unroll_count": 2},
    ),
    "unroll_count_4": (
        "Attach `llvm.loop.unroll.count = 4`: unroll the loop body four "
        "times. More scheduling freedom and fewer branches than count=2, at "
        "four times the body's code size and a longer remainder loop.",
        {"unroll_count": 4},
    ),
    "unroll_count_8": (
        "Attach `llvm.loop.unroll.count = 8`: unroll the loop body eight "
        "times. Only worth it for a very short body with a high trip count; "
        "otherwise the code growth costs more in instruction cache than the "
        "saved branches are worth.",
        {"unroll_count": 8},
    ),
    "unroll_disable": (
        "Attach `llvm.loop.unroll.disable`: forbid unrolling this loop "
        "entirely. Keeps the body small, which helps when the loop is short "
        "and unpredictable or when the caller's instruction footprint is the "
        "problem.",
        {"unroll_disable": True},
    ),
    "vectorize_width_2": (
        "Attach `llvm.loop.vectorize.width = 2` (and `vectorize.enable`): "
        "force two lanes per vector iteration. A narrow forced width is a way "
        "to keep vectorisation but cut the cost of the scalar remainder when "
        "the trip count is low. Reassociation of floating-point reductions "
        "stays forbidden (the build pins -hints-allow-reordering=false), so a "
        "non-reassociable reduction will simply not be widened.",
        {"vectorize_width": 2},
    ),
    "vectorize_width_4": (
        "Attach `llvm.loop.vectorize.width = 4` (and `vectorize.enable`): "
        "four lanes per vector iteration. On this machine (znver3, AVX2, no "
        "AVX-512) that is one 256-bit register for 64-bit elements.",
        {"vectorize_width": 4},
    ),
    "vectorize_width_8": (
        "Attach `llvm.loop.vectorize.width = 8` (and `vectorize.enable`): "
        "eight lanes per vector iteration. For 32-bit elements that is one "
        "256-bit register; for 64-bit elements it is two, which LLVM will "
        "split.",
        {"vectorize_width": 8},
    ),
    "vectorize_width_16": (
        "Attach `llvm.loop.vectorize.width = 16` (and `vectorize.enable`): "
        "sixteen lanes per vector iteration. Only 8-bit and 16-bit element "
        "types fit that in one AVX2 register; for anything wider LLVM emits "
        "several registers per iteration, which can pay off on a very long "
        "loop and hurts on a short one.",
        {"vectorize_width": 16},
    ),
    "interleave_count_1": (
        "Attach `llvm.loop.interleave.count = 1`: vectorise without "
        "interleaving, i.e. one vector body per iteration and a single "
        "accumulator chain. Shortens the loop and the remainder when LLVM's "
        "default interleaving was too aggressive.",
        {"interleave_count": 1},
    ),
    "interleave_count_2": (
        "Attach `llvm.loop.interleave.count = 2`: two independent vector "
        "chains per iteration, which hides the latency of a dependent "
        "reduction at the cost of more registers.",
        {"interleave_count": 2},
    ),
    "interleave_count_4": (
        "Attach `llvm.loop.interleave.count = 4`: four independent vector "
        "chains per iteration. The most latency hiding of the three and the "
        "most register pressure; on a short trip count the remainder loop "
        "eats the gain.",
        {"interleave_count": 4},
    ),
}


# ---------------------------------------------------------------------------
# build-wide knobs
# ---------------------------------------------------------------------------

BUILD_KEEP_DESCRIPTION = (
    "Change no compiler setting: build with the frozen baseline flags only "
    "(-Copt-level=3, fat LTO, one codegen unit, -Ctarget-cpu=native, PGO, "
    "and -Cllvm-args=-hints-allow-reordering=false)."
)

BUILD_KNOB_DESCRIPTION = (
    "Add the LLVM option `{knob}` to the whole build, on top of the frozen "
    "baseline flags. It applies to every function in the program, not only to "
    "the marked ones."
)


def build_candidates(knobs):
    """{candidate id: (description, rustc flag or None)} for `__build__`.

    `knobs` is the `[search] build_knobs` list of jev-opt.toml: raw strings
    that are passed to `build_variant` exactly as written (a value starting
    with `-C` or `-Z` is a rustc flag, anything else is wrapped in
    `-Cllvm-args=`; see scripts/target_common.sh). The default is the empty
    list, which means the `__build__` question is not asked at all.
    """
    out = {KEEP_DEFAULT: (BUILD_KEEP_DESCRIPTION, None)}
    for i, knob in enumerate(knobs):
        out["knob_%d" % i] = (BUILD_KNOB_DESCRIPTION.format(knob=knob), knob)
    return out


# ---------------------------------------------------------------------------
# frozen question wording
# ---------------------------------------------------------------------------

FN_INSTRUCTIONS = (
    "Section `{qname}` of the state describes one marked function of this "
    "program. Which function attribute should the build put on it? Pick "
    "KEEP_DEFAULT unless there is a reason in that section to expect the "
    "attribute to make the whole program measurably faster."
)

LOOP_INSTRUCTIONS = (
    "Section `{qname}` of the state describes one loop inside a marked "
    "function, together with the function attributes this build has already "
    "applied. Which loop hint should the build attach to it? Pick "
    "KEEP_DEFAULT unless there is a reason in that section to expect the hint "
    "to make the whole program measurably faster."
)

BUILD_INSTRUCTIONS = (
    "Section `{qname}` of the state lists compiler settings that apply to the "
    "whole build rather than to one site. Which one should this round use?"
)


def candidates_for(kind, build_knobs=()):
    """Ordered {candidate id: description} for a site kind."""
    if kind == "fn":
        return {k: v[0] for k, v in FN_CANDIDATES.items()}
    if kind == "loop":
        return {k: v[0] for k, v in LOOP_CANDIDATES.items()}
    if kind == "build":
        return {k: v[0] for k, v in build_candidates(build_knobs).items()}
    raise ValueError("unknown site kind %r" % (kind,))


def instructions_for(kind, qname):
    if kind == "fn":
        return FN_INSTRUCTIONS.format(qname=qname)
    if kind == "loop":
        return LOOP_INSTRUCTIONS.format(qname=qname)
    if kind == "build":
        return BUILD_INSTRUCTIONS.format(qname=qname)
    raise ValueError("unknown site kind %r" % (kind,))


def fragment_for(kind, candidate, build_knobs=()):
    """The plan fragment (fn/loop) or rustc flag (build) a candidate means."""
    if kind == "fn":
        return dict(FN_CANDIDATES[candidate][1])
    if kind == "loop":
        return dict(LOOP_CANDIDATES[candidate][1])
    if kind == "build":
        return build_candidates(build_knobs)[candidate][1]
    raise ValueError("unknown site kind %r" % (kind,))


def spec_spelling(kind, candidate):
    """The SPEC.ja.md 1(2) spelling, for tables humans read."""
    if candidate == KEEP_DEFAULT:
        return KEEP_DEFAULT
    if kind == "fn":
        return {
            "inline": "inline",
            "inline_never": "inline(never)",
            "cold": "cold",
            "align_16": "align=16",
            "align_32": "align=32",
            "align_64": "align=64",
        }[candidate]
    if kind == "loop":
        if candidate == "unroll_disable":
            return "unroll.disable"
        name, _, n = candidate.rpartition("_")
        return {"unroll_count": "unroll.count",
                "vectorize_width": "vectorize.width",
                "interleave_count": "interleave.count"}[name] + "=" + n
    return candidate


if __name__ == "__main__":
    print("vocabulary %s" % VOCAB_VERSION)
    for kind in ("fn", "loop"):
        print("\n%s candidates:" % kind)
        for cid, desc in candidates_for(kind).items():
            print("  %-20s %-18s %s" % (cid, spec_spelling(kind, cid),
                                        desc.split(".")[0] + "."))
