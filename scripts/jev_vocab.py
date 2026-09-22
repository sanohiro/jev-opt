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

There are now three frozen vocabularies, selected by `set_version()` and by
the driver's `--vocab` flag:

  v1   what Experiment 3 was run with. Frozen; nothing below it may change.
  v2   decision 73, the prompt study's `W7`: the same candidate ids, the
       same plan fragments and the same SPEC spellings, with (a) the
       applicability conditions written into the *function* descriptions,
       (b) the plain v1 descriptions kept for the *loop* hints --- W1
       against W3 measured that the loop applicability text costs the one
       pick with a mechanism --- (c) `KEEP_DEFAULT` described neutrally
       and (d) the V2 question wording ("which single hint is most likely
       to make this faster") instead of "pick KEEP_DEFAULT unless".
  v3   decision 77. The function candidates change for the first time:
       `inline` (`inlinehint`) and `cold` are dropped and `inline_always`
       (`alwaysinline`) takes their place. Under this recipe --- O3,
       `-Cprofile-use`, fat LTO --- the inliner reads `inlinehint` and then
       overwrites the threshold it produced with the call site's
       profile-derived one, and the single arm that reads the callee's
       `cold` is unreachable whenever the call site is classified at all;
       the reasoning, with the LLVM 23.1.1 line numbers, is in
       `docs/experiments/hintbench/inline-attrs-under-pgo.md`.
       `alwaysinline` and `noinline` are decided before the cost analyser is
       constructed and are therefore immune to the profile. `hot` is NOT
       added in their place: it never appears in `InlineCost.cpp` at all and
       has no Rust counterpart. The loop half is v2's, unchanged, so a v2/v3
       difference on a loop site cannot come from the vocabulary.

Every string of v2 is copied verbatim from
`docs/experiments/jev-prompt-study/` (`scripts/jev_state_variants.py`
`ENRICHED_FN`, `NEUTRAL_KEEP_FN`, `NEUTRAL_KEEP_LOOP`, `Q_V2_FN`,
`Q_V2_LOOP`), so the shipped state asks what the study measured.

Nothing below v1 or v2 may change: both are kept so that Experiment 3 and
the prompt study can be replayed byte for byte, which is also why the plugin
still accepts `inline: "hint"` and `cold: true`.

The module-level default stays **v1** so that every other importer ---
`scripts/jev_state_variants.py` above all, which reproduces round 1 of the
study --- keeps the vocabulary it was measured with. The search driver
selects its own vocabulary explicitly (v3 since decision 77).

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
# v2 (decision 73): the prompt study's W7 vocabulary
# ---------------------------------------------------------------------------
#
# Idea B of the study, and only half of it. The applicability conditions go
# into the *function* descriptions, where they ended the behaviour of round 1
# that decision 70 called its sharpest failure (`inline` on the two largest
# bodies in the program, in every repeat). They are deliberately NOT written
# into the loop descriptions: W1 (verdict block, plain loop descriptions)
# chose `vectorize.width=16` at the one loop with a mechanism in all three
# repeats, and W3 (verdict block plus loop applicability text) moved it to
# `unroll.count=4`. The loop half of v2 is therefore the v1 text with a
# neutral `KEEP_DEFAULT`.
#
# None of these sentences names a function, a loop, a file or a site of any
# program, and none of them says what to pick: they are about the hint. The
# candidate ids, the plan fragments and the SPEC spellings are v1's, so a
# plan written under v2 is the same plan v1 would have written for the same
# choice.

FN_CANDIDATES_V2 = {
    KEEP_DEFAULT: (
        "Change nothing about this function's attributes. This is the 'no "
        "change' option: the build keeps whatever LLVM's own cost model "
        "decides, exactly as in the baseline.",
        {},
    ),
    "inline": (
        "Add the `inlinehint` attribute (the SPEC vocabulary's `inline`). "
        "It raises the inliner's threshold for this function, so callers "
        "that were just over the limit paste its body in. It tends to help "
        "a small hot leaf (roughly under 300 instructions) called from few "
        "hot sites, where the caller then specialises on what it passes. "
        "It tends to hurt a large body (a thousand instructions and up) "
        "and a function with many monomorphized copies, because every "
        "pasted copy costs instruction cache. It is a no-op where the "
        "function already carries the attribute.",
        dict(FN_CANDIDATES['inline'][1]),
    ),
    "inline_never": (
        "Add the `noinline` attribute (the SPEC vocabulary's "
        "`inline(never)`). The function stays one out-of-line copy: call "
        "overhead is paid at every call site and the callers stay small. "
        "It tends to help a very large body (thousands of instructions) or "
        "a function with many monomorphized copies, by stopping code "
        "growth and instruction-cache pressure --- especially where an "
        "`inlinehint` is already asking the inliner to paste that body in. "
        "It tends to hurt a small hot leaf, where the call overhead is the "
        "bulk of the cost. It is a no-op where the body is already too "
        "large for any caller's threshold.",
        dict(FN_CANDIDATES['inline_never'][1]),
    ),
    "cold": (
        "Add the `cold` attribute. Callers place calls to it out of line, "
        "it is optimised for size rather than speed, and it is never "
        "inlined. It tends to help a function that is genuinely off the "
        "hot path, by moving its code away from the hot path's cache "
        "lines. It is a pessimisation by definition on a function that "
        "carries a significant share of the cycles, whatever its size.",
        dict(FN_CANDIDATES['cold'][1]),
    ),
    "align_16": (
        "Set the function's alignment to 16 bytes (`align=16`). 16 bytes "
        "is already the default on x86-64, so this mostly pins the current "
        "alignment and changes nothing. It helps and hurts nowhere in "
        "particular.",
        dict(FN_CANDIDATES['align_16'][1]),
    ),
    "align_32": (
        "Set the function's alignment to 32 bytes (`align=32`). The entry "
        "point starts on a 32-byte boundary, which changes how the first "
        "instructions and the first loop fall into the 32-byte "
        "instruction-fetch windows and the uop cache. It tends to help "
        "where a hot loop sits at or very near the function's entry; it "
        "does nothing for a hot loop deep inside a large body, and it is a "
        "lottery rather than a mechanism wherever the layout is not known.",
        dict(FN_CANDIDATES['align_32'][1]),
    ),
    "align_64": (
        "Set the function's alignment to 64 bytes (`align=64`). Same "
        "mechanism as `align=32`, one step coarser: the function starts on "
        "a cache line, and up to 63 bytes of padding are wasted per "
        "function. Same applicability as `align=32`, with more padding to "
        "pay for it.",
        dict(FN_CANDIDATES['align_64'][1]),
    ),
}

LOOP_KEEP_DEFAULT_V2 = (
    "Attach no metadata to this loop. This is the 'no change' option: "
    "LLVM's vectoriser and unroller decide with their own cost model, "
    "exactly as in the baseline."
)

FN_INSTRUCTIONS_V2 = (
    "Section `{qname}` of the state describes one marked function of this "
    "program. Which single hint from the list is most likely to make this "
    "function faster on this workload?"
)

LOOP_INSTRUCTIONS_V2 = (
    "Section `{qname}` of the state describes one loop inside a marked "
    "function of this program. Which single hint from the list is most "
    "likely to make this loop faster on this workload?"
)

# The loop half of v2: v1's descriptions, with KEEP_DEFAULT described
# neutrally. Built from v1 rather than copied, so the two cannot drift.
LOOP_CANDIDATES_V2 = {
    cid: ((LOOP_KEEP_DEFAULT_V2 if cid == KEEP_DEFAULT else desc),
          dict(frag))
    for cid, (desc, frag) in LOOP_CANDIDATES.items()
}



# ---------------------------------------------------------------------------
# v3 (decision 77): the function candidates that are live under PGO
# ---------------------------------------------------------------------------
#
# v2's function list contained two candidates that cannot change a decision
# in this recipe. `docs/experiments/hintbench/inline-attrs-under-pgo.md`
# reads the LLVM 23.1.1 source line by line; the short form is:
#
#   * `inlinehint` is read at `InlineCost.cpp:2137` and then thrown away at
#     `:2154`, which assigns (not `max`es) the threshold of a hot or locally
#     hot call site. Under `-Copt-level=3` a call site inside a driver loop
#     is locally hot by frequency alone.
#   * the callee's `cold` attribute is read in the last `else if` of that
#     same chain (`:2163-2179`), which a classified call site never reaches.
#   * `alwaysinline` (`:3209`) and `noinline` (`:3242`) are answered by
#     `getAttributeBasedInliningDecision` before the cost analyser exists.
#   * `align=N` is not an inliner input at all.
#
# So the function half becomes KEEP_DEFAULT + `inline_always` +
# `inline_never` + the three alignments: five candidates plus the default,
# every one of them with a mechanism that survives the profile. `hot` is not
# added (it is absent from `InlineCost.cpp` and from Rust's surface syntax).
#
# Wording follows v2's rule: the two inlining candidates carry the W7
# applicability conditions (helps / hurts / no-op, in the same vocabulary as
# the verdict block), the alignments keep v1's plain descriptions --- the
# study's enriched align text is nothing but a restatement of the same
# mechanism, and v1's is shorter --- and KEEP_DEFAULT stays neutral. No
# sentence names a function, a loop, a file or a site.

FN_CANDIDATES_V3 = {
    KEEP_DEFAULT: (FN_CANDIDATES_V2[KEEP_DEFAULT][0], {}),
    "inline_always": (
        "Add the `alwaysinline` attribute (the SPEC vocabulary's "
        "`inline(always)`). The body is pasted into every call site, "
        "whatever the inliner's cost model would have decided: the choice "
        "is made before any cost is computed, so a call site's measured "
        "hotness cannot overrule it. It tends to help a small hot leaf "
        "(roughly under 300 instructions) that the inliner is declining to "
        "paste in, because the caller then specialises on what it passes "
        "and the call overhead goes away. It tends to hurt a large body (a "
        "thousand instructions and up) and a function with many "
        "monomorphized copies, since every call site pays the full code "
        "growth with no cost model left to stop it. Where inlining is "
        "impossible --- a recursive self-call, a target-feature mismatch --- "
        "nothing happens and the build says so with a `NotInlined` remark. "
        "It is a no-op where every call site was being inlined anyway.",
        {"inline": "always"},
    ),
    "inline_never": (
        "Add the `noinline` attribute (the SPEC vocabulary's "
        "`inline(never)`). The function stays one out-of-line copy: call "
        "overhead is paid at every call site and the callers stay small. "
        "Like `alwaysinline` it is decided before the cost model runs, so "
        "the profile cannot overrule it either. It tends to help a very "
        "large body (thousands of instructions) or a function with many "
        "monomorphized copies, by stopping code growth and "
        "instruction-cache pressure --- especially where an `inlinehint` is "
        "already asking the inliner to paste that body in. It tends to hurt "
        "a small hot leaf, where the call overhead is the bulk of the cost. "
        "It is a no-op where the body is already too large for any caller's "
        "threshold.",
        {"inline": "never"},
    ),
    "align_16": (FN_CANDIDATES["align_16"][0],
                 dict(FN_CANDIDATES["align_16"][1])),
    "align_32": (FN_CANDIDATES["align_32"][0],
                 dict(FN_CANDIDATES["align_32"][1])),
    "align_64": (FN_CANDIDATES["align_64"][0],
                 dict(FN_CANDIDATES["align_64"][1])),
}

# The loop half of v3 is v2's, and the questions are v2's. Built from v2
# rather than copied, so the two cannot drift.
LOOP_CANDIDATES_V3 = {cid: (desc, dict(frag))
                      for cid, (desc, frag) in LOOP_CANDIDATES_V2.items()}

FN_INSTRUCTIONS_V3 = FN_INSTRUCTIONS_V2
LOOP_INSTRUCTIONS_V3 = LOOP_INSTRUCTIONS_V2


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


VOCAB_VERSIONS = {"v1": "v1-2026-09-22", "v2": "v2-2026-09-22",
                  "v3": "v3-2026-09-22"}

_TABLES = {
    "v1": {"fn": FN_CANDIDATES, "loop": LOOP_CANDIDATES},
    "v2": {"fn": FN_CANDIDATES_V2, "loop": LOOP_CANDIDATES_V2},
    "v3": {"fn": FN_CANDIDATES_V3, "loop": LOOP_CANDIDATES_V3},
}

_INSTRUCTIONS = {
    "v1": {"fn": FN_INSTRUCTIONS, "loop": LOOP_INSTRUCTIONS,
           "build": BUILD_INSTRUCTIONS},
    # The `__build__` question is asked with v1's wording in both versions:
    # the study never varied it, and inventing wording for it here would be
    # a change nothing measured.
    "v2": {"fn": FN_INSTRUCTIONS_V2, "loop": LOOP_INSTRUCTIONS_V2,
           "build": BUILD_INSTRUCTIONS},
    "v3": {"fn": FN_INSTRUCTIONS_V3, "loop": LOOP_INSTRUCTIONS_V3,
           "build": BUILD_INSTRUCTIONS},
}

_ACTIVE = "v1"


def set_version(version):
    """Select the vocabulary for this process, and update `VOCAB_VERSION`.

    `VOCAB_VERSION` is what the driver writes into the manifest, into every
    plan and into every request log line, so selecting a vocabulary and
    recording which one was selected are the same act.
    """
    global _ACTIVE, VOCAB_VERSION
    if version not in VOCAB_VERSIONS:
        raise ValueError("unknown vocabulary %r (have %s)"
                         % (version, ", ".join(sorted(VOCAB_VERSIONS))))
    _ACTIVE = version
    VOCAB_VERSION = VOCAB_VERSIONS[version]
    return VOCAB_VERSION


def active_version():
    return _ACTIVE


def candidates_for(kind, build_knobs=(), version=None):
    """Ordered {candidate id: description} for a site kind.

    `version` defaults to whatever `set_version()` selected (v1 unless the
    caller said otherwise). The `__build__` list is the same in both
    vocabularies: it is built from `[search] build_knobs`, not frozen here.
    """
    table = _TABLES[version or _ACTIVE]
    if kind in table:
        return {k: v[0] for k, v in table[kind].items()}
    if kind == "build":
        return {k: v[0] for k, v in build_candidates(build_knobs).items()}
    raise ValueError("unknown site kind %r" % (kind,))


def instructions_for(kind, qname, version=None):
    text = _INSTRUCTIONS[version or _ACTIVE].get(kind)
    if text is None:
        raise ValueError("unknown site kind %r" % (kind,))
    return text.format(qname=qname)


def fragment_for(kind, candidate, build_knobs=(), version=None):
    """The plan fragment (fn/loop) or rustc flag (build) a candidate means.

    The fragments are the same in every vocabulary --- v2 is a description
    variant of v1, not a different set of hints --- but the lookup still
    goes through the selected table so that a candidate id which exists in
    only one of them cannot silently resolve against the other.
    """
    table = _TABLES[version or _ACTIVE]
    if kind in table:
        return dict(table[kind][candidate][1])
    if kind == "build":
        return build_candidates(build_knobs)[candidate][1]
    raise ValueError("unknown site kind %r" % (kind,))


def spec_spelling(kind, candidate):
    """The SPEC.ja.md 1(2) spelling, for tables humans read."""
    if candidate == KEEP_DEFAULT:
        return KEEP_DEFAULT
    if kind == "fn":
        # Every id of every vocabulary: v1/v2's `inline` and `cold` are still
        # spelled out here so an old run's tables can be reprinted.
        return {
            "inline": "inline",
            "inline_always": "inline(always)",
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
    import sys
    want = sys.argv[1] if len(sys.argv) > 1 else _ACTIVE
    print("vocabulary %s" % set_version(want))
    for kind in ("fn", "loop"):
        print("\n%s question: %s" % (kind, instructions_for(kind, "qN")))
        print("%s candidates:" % kind)
        for cid, desc in candidates_for(kind).items():
            print("  %-20s %-18s %s" % (cid, spec_spelling(kind, cid),
                                        desc.split(".")[0] + "."))
