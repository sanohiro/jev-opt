# FP reassociation option: mechanism check and target scouting

Read-only scouting for decision 38(2) --- "Jev judges, per hot loop, whether FP
reassociation is acceptable; the plugin allows it only there". No builds, no benchmarks
(another agent is measuring). LLVM facts are from the pinned tag `llvmorg-23.1.1` fetched
raw from GitHub; repository facts from shallow clones and `cargo tree`, never a build.

---

## 1. Mechanism: how a loop hint lifts the FP-ordering bail

### 1.1 The gate

`LoopVectorize.cpp:8028` calls `LVL.canVectorizeFPMath(AllowOrderedReductions)`; on
failure it emits `OptimizationRemarkAnalysisFPCommute("CantReorderFPOps")` with the string
`"loop not vectorized: cannot prove it is safe to reorder floating-point operations"` ---
verbatim the remark Day 0 §13 saw disappear on `dot_f64`. `AllowOrderedReductions` is
`-force-ordered-reductions` if set, else `TTI->enableOrderedReductions()` --- which X86
does not override, so it is the base `false` (`TargetTransformInfoImpl.h:436`) ---
so that escape hatch is off here and everything hangs on the first line of
`LoopVectorizationLegality.cpp:1273-1297`:
`if (!Requirements->getExactFPInst() || Hints->allowReordering()) return true;`.
Two ways through: **no ExactFP instruction was recorded**, or **the hints allow
reordering**.

### 1.2 `allowReordering()` --- does metadata take the same path?

`LoopVectorizationLegality.cpp:250-256`:

```cpp
bool LoopVectorizeHints::allowReordering() const {
  ElementCount EC = getWidth();
  return HintsAllowReordering &&
         (getForce() == LoopVectorizeHints::FK_Enabled || EC.getKnownMinValue() > 1);
}
```

* `HintsAllowReordering` = `cl::opt<bool> "hints-allow-reordering"`, **`cl::init(true)`**,
  `cl::Hidden` (`LoopVectorizationLegality.cpp:51-54`); `false` kills *all* hint-driven FP
  reordering globally.
* `getWidth()` / `getForce()` (`LoopVectorizationLegality.h:141-146`, `159-164`) read the
  `Hint` members `Width.Value` / `Force.Value`, which the ctor
  (`LoopVectorizationLegality.cpp:103-116`) initialises as
  `Width("vectorize.width", VectorizerParams::VectorizationFactor.getKnownMinValue(), HK_WIDTH)`
  and `Force("vectorize.enable", FK_Undefined, HK_FORCE)` before calling
  **`getHintsFromMetadata()`**, which walks the `llvm.loop.*` operands into `setHint()`.
* `VectorizerParams::VectorizationFactor` *is* `-force-vector-width`
  (`LoopAccessAnalysis.cpp:74-78`, `cl::opt<ElementCount, true>` with `cl::location`).

**Verdict: YES --- metadata and the cl::opt are literally the same field.** The cl::opt
supplies the hint's *initial value*; loop metadata overwrites it afterwards;
`allowReordering()` cannot tell them apart. Three equivalent triggers:

1. `-force-vector-width=N`, N > 1 --- measured (Day 0 §13);
2. `llvm.loop.vectorize.width = N`, N > 1 --- **source-confirmed, still unmeasured**;
3. `llvm.loop.vectorize.enable = true` --- FK_Enabled, **no width needed at all**.

SPEC §8.4 rule 1 must therefore cover `vectorize.enable`, not only `vectorize.width`, and
day-3 item 13 becomes a confirmation rather than a discovery. Two further consumers of the
same bit: `LoopVectorize.cpp:6538` passes `Hints.allowReordering()` into
`VPlanTransforms::createHeaderPhiRecipes`, where
`VPlanConstruction.cpp:961` computes `bool UseOrderedReductions = !AllowReordering &&
RdxDesc.isOrdered();` --- the hint also picks the reduction *recipe* --- and
`isPotentiallyUnsafe()` (`LoopVectorizationLegality.h:188-191`) is suppressed when
`getForce() == FK_Enabled`, so an enable hint also bypasses the target's unsafe-FP veto
(`LoopVectorize.cpp:8014-8019`).

### 1.3 The targeted alternative: set `reassoc` on the chain

`IVDescriptors.cpp`, `RecurrenceDescriptor::isRecurrenceInstr`, lines 1012 (FMul),
1016-1018 (FSub), 1019-1022 (FAdd), 1037-1039 (FMulAdd), all of the form
`InstDesc(Kind == RecurKind::FAdd || ..., I, I->hasAllowReassoc() ? nullptr : I)`.
The `ExactFPMathInst` that `canVectorizeFPMath` tests is recorded **only when the chain
instruction lacks `reassoc`** (propagated at `IVDescriptors.cpp:618-620`, handed to
`Requirements->addExactFPMathInst` at `LoopVectorizationLegality.cpp:848`). So setting
`reassoc` on one loop's `fadd`/`fmul`/`fmuladd` chain nulls `getExactFPInst()` and
`canVectorizeFPMath` returns true on its first line --- **with no width or enable hint, and
the cost model still choosing VF/IC**.

Two details: `contract` is not checked here (only `hasAllowReassoc`), so
`allow_reassoc_and_contract` is a genuinely separate, additive decision (FMA fusion); and
`isConditionalRdxPattern` (predicated `sum += x` under a select) requires `I1->isFast()`,
the full flag set, so conditional reductions need more than `reassoc` or stay strict.

### 1.4 Comparison

| | width/enable hint | per-instruction `reassoc` FMF |
|---|---|---|
| Granularity | per loop | per instruction in one loop |
| Side effects | forces VF (Day 0 §15: forced width cost 2.2x on a byte loop), overrides the cost model, changes recipe kind, bypasses `isPotentiallyUnsafe` | none on VF; cost model untouched |
| FP blast radius | every FP reduction in the loop | exactly the flagged instructions --- but flags persist into SLP/InstCombine/DAGCombine, so the scalar epilogue may also be reassociated |
| Off switch | `-hints-allow-reordering=false` (global) | do not set the flag |
| Separable from the speed hint? | no | yes |

**Recommendation.** Implement the option *only* through FMF, and pin
`-Cllvm-args=-hints-allow-reordering=false` on every arm (decision 13(d)). That makes the
default path's width/enable hints provably FP-safe and leaves reassociation a single,
explicitly requested, per-site act. Detection is cheap and the API is exported by the
shipped library: `nm -D $SYSROOT/lib/libLLVM.so.23.1-* | grep isReductionPHI` resolves
`llvm::RecurrenceDescriptor::isReductionPHI(...)`, so `has_fp_reduction`, the recurrence
kind and `hasExactFPMath()` all come from one call per header PHI in the dump pass.

---

## 2. Target scouting

Method: shallow clone; `cargo tree --target x86_64-unknown-linux-gnu -e normal,build`
(decision 28: `-e build` alone does not descend; `--target` avoids other platforms'
`*-sys` false positives); grep for
`core::arch|std::arch|packed_simd|std::simd|wide|target_feature`; grep for long
accumulators (`fold(0.0`, `sum +=`, `.sum::<f32|f64>()`, `+= a * b`) and for the
counter-pattern of hand-unrolled partial sums (`acc0..accN`, `chunks_exact(8)`); read the
candidate loops. **Hotness is unverified** --- no profiles were taken.

What this option alone unlocks: a **long, single-accumulator, ordered f32/f64 reduction**.
It does *not* help IIR recurrences, 3--4 element dots (SLP territory), elementwise
`out[i] += a[i]*b[i]` (already legal), or loops already split into 4--8 partial sums.

| # | target | version | C deps (`-e normal,build`) | hand SIMD | CLI | artifact | benches |
|---|---|---|---|---|---|---|---|
| 1 | **llama2-rs** (danielgrittner) | 0.1.0, `a6c406d` (untagged) | **none** | none | own bin | logits / tokens | none |
| 2 | **ebur128** (sdroege) | 0.1.10 | none (`cc` only under `c-tests`) | `_mm_setcsr` FTZ only | `examples/replaygain.rs` | LUFS/peak numbers | `benches/` (criterion) |
| 3 | **Symphonia** | v0.6.1 | none for `symphonia-check`; **`libpulse-sys`** for `symphonia-play` | **none anywhere** | `symphonia-check`, `symphonia-play --decode-only` | PCM | none |
| 4 | **image** resize/blur + thin CLI | 0.25.9 | none at default features (`dav1d-sys`+`cc` only with `--all-features`) | none | none --- needs a wrapper | pixels | `benches/` |
| 5 | **lewton** (Vorbis) | 0.10.2 | none | none | `--example perf` only | PCM | none |

**1. llama2-rs** --- `fn matmul` is
`target.par_iter_mut()... x.iter().zip(w[row..]).fold(0.0, |r,(x,w)| r + x*w)` (`src`,
lines 394-402) plus `inner_product` for attention: textbook ordered f32 reductions of
length 288--4096, >90% of the time in a llama2.c-shaped program. Deps
`byteorder memmap2 num_cpus rand rayon`, all pure Rust; deterministic at temperature 0.
Honest caveats: ~700 lines, "small but real"; `rayon` ⇒ `RAYON_NUM_THREADS=1` for timing;
weights are a ~60 MB download (stories15M/110M); output is *discrete* (argmax), so the
artifact must be a logit dump, not the token string.

**2. ebur128** --- `filter.rs:307 calc_gating_block` is `sum += x*x` in f64 over a 400 ms
block (~19.2k samples/channel at 48 kHz); `history.rs`/`utils.rs` add more f64 sums.
Output is a handful of numbers, which makes the tolerance gate trivial to define and read.
Caveats, both useful: much of the time is the cascaded biquad (an IIR recurrence the option
cannot touch), so coverage is partial; and `filter.rs:335-336` says *"Don't use
`channel_sum += sum()` here because that gives slightly different results than the C
version because of rounding errors"* --- an author-written `keep_strict` signal and the
single best test of whether Jev reads intent (§4). No shipped bin;
`examples/replaygain.rs` (hound, pure Rust) is the CLI.

**3. Symphonia** --- honest evaluation, since it was already on our list. Cleanliness is
excellent: zero `core::arch`/`std::simd`/`wide` in the whole workspace and no `cc`/`*-sys`
under `symphonia-check`. `symphonia-play` pulls `libpulse-sys` + `libpulse-simple-sys` on
Linux; note that this is *not* automatically a decision-28 disqualification (that rule
needs detection **plus** wall-clock attribution, and `--decode-only` would measure pulse at
0%) --- the real reason it is unsuitable is that it emits no PCM artifact for the gate.
`symphonia-check` shells out to `ffmpeg`/`flac`/`mpg123`, so a workload needs that external
decoder or a thin decode-to-PCM CLI of our own. Structurally the news is worse than hoped:
MP3 synthesis (`symphonia-bundle-mp3/src/synthesis.rs:311-321`) is
`o_vec[i] += v0[i]*D[k+i]; o_vec[i] += v1[i]*D[k+i+32]` --- **elementwise**, no reduction,
already reorder-free --- and the IMDCT/hybrid loops are fixed 6/12/18/36-iteration
butterflies. **Scope of that reading**: MP3 was read by hand; the AAC (`aac/dsp.rs`,
`aac/window.rs`) and Vorbis conclusions rest on grep counts only (22 accumulation hits
workspace-wide, mostly short). Keep it as the "real program" target; expect the option to
reach little of it.

**4. image** --- `imageops/sample.rs` `horizontal_sample`/`vertical_sample` accumulate
weighted sums of 4 taps (Triangle) to ~24 (Lanczos3 at 4x downscale): real reductions,
medium length. No binary, so it needs our own wrapper crate (same shape as `targets/toy`)
--- a toy-like harness over real library code. `imagecli` v0.2.1 is a real CLI over
`image`+`imageproc` but is 2021-era, drags `cc` via `backtrace 0.3.61` (build-only, off
the hot path) and is a build-compatibility risk on the pinned nightly.
**5. lewton** --- pure Rust Vorbis, no C, no intrinsics, but only example binaries and the
same "butterflies and elementwise" shape as Symphonia.

**Examined and rejected.** *rubato* 5.0.0: clean tree but ships
`sinc_interpolator_{avx,sse,neon}.rs` and 27 hand-unrolled partial-sum sites --- the author
already reassociated by hand. *rustfft/realfft*: `core::arch` AVX kernels. *llama2.rs*
(srush): `core::arch` plus a CUDA `build.rs`. *rs_pbrt* v0.9.12: clean tree
(`linux-raw-sys` is the §42 false positive) but its 79 accumulation sites are 3-wide vector
algebra and the time goes to BVH traversal; rayon-parallel. *gifski* 1.35.0: clean tree
(`js-sys` is not C) and a real CLI, but heavily threaded with integer-ish quantization.
*kmeans-colors* 0.7.1: clean tree, real CLI, `--seed`, but the inner loop is a 3-wide
distance plus argmin and `recalculate_centroids` is a *conditional* accumulation needing
`isFast()` (§1.3) --- stretch candidate. *tract/candle/rten*: hand SIMD or assembly.
None of these have benches we would use; only ebur128, image and rubato ship any.

**Meta-finding.** The pool of real, pure-Rust, hand-SIMD-free programs whose hot loops are
long FP reductions is thin, and thin for a reason: anyone who cared about FP throughput has
already written intrinsics or unrolled the accumulator. That is decision 29/37's pattern
("the headroom was already taken") reappearing in a new dimension.

---

## 3. Correctness gate when reassociation is allowed

**Asymmetry first.** The default path keeps the bitwise gate of decision 13(b), unchanged.
The tolerance gate exists *only* under an explicit `--allow-fp-reassoc`, and its results
must never be folded into a default-path claim. Decision 35 still holds: the gate only
covers executed code, so the site rule (`has_fp_reduction` ⇒ ask Jev; no answer ⇒ strict)
stays the primary defence and the gate is secondary.

Per build, in order: (1) **determinism self-check** --- run the baseline twice per
workload and require bitwise-identical artifacts; if it fails, the target is ineligible for
*any* gate, or thread noise gets misread as reassociation error. (2) Each workload declares
`artifact = { kind, path|stdout }`; anything undeclared falls back to bitwise.
(3) Compare baseline vs candidate on the **holdout** inputs, never the PGO training inputs.

| artifact kind | metric | default tolerance |
|---|---|---|
| `f64_array` | max rel err, max ULP | 1e-12 / 64 ULP |
| `f32_array` | max rel err, max ULP | 1e-6 / 256 ULP |
| `pcm_f32` | SNR vs baseline, max sample delta | SNR ≥ 120 dB |
| `pcm_s16` | exact with a quota | ≤ 0.01 % of samples off by ±1 LSB |
| `image_u8` | PSNR, max channel delta | PSNR ≥ 70 dB, max delta ≤ 1 |
| `numbers` (parsed from stdout) | abs + rel | 1e-9 rel |
| `bytes`, `tokens`, any discrete output | bitwise | no tolerance available |

Tolerances live in `jev-opt.toml` (`[fp.tolerance]`) per artifact kind, overridable per
workload; the table is the fallback. **Discrete amplification is the trap**: argmax, a
threshold, `sort_by(partial_cmp)` or u8 quantization turn 1 ULP into a visibly different
output. Where a float feeds a discrete decision, compare the *pre-quantized* value (dump
logits, not tokens); if it cannot be dumped, the site is `keep_strict` by rule.

Record per build: which sites got flags and which instructions in each; remark evidence
that `CantReorderFPOps` disappeared at that DebugLoc (otherwise the flag was applied and
bought nothing); per artifact the metric, observed value, threshold and *fraction of budget
used*, so a near-miss is visible; and which flagged sites the profile says actually ran.
Caveat for the write-up: tree summation is usually *more* accurate than the sequential
baseline, so the gate measures divergence, not error --- the baseline is not truth.

---

## 4. What Jev would judge

One `Choice` per hot site the dump reports as `has_fp_reduction`.

**State**: loop body ±20 lines; enclosing function signature and doc comment; all comments
inside the loop, verbatim (see ebur128 above); recurrence kind
(`FAdd`/`FMul`/`FMulAdd`/conditional) and accumulator type; profile trip count and hotness;
crate and module path; and **how the result is consumed** (returned, stored, printed to N
digits, compared, hashed, fed to argmax/sort/quantization).

**Criteria**: `keep_strict` | `allow_reassoc` | `allow_reassoc_and_contract`. Default on
refusal, low confidence or missing state: `keep_strict`.

*Strict signals*: compensated summation (Kahan/Neumaier --- `c`, `comp`, `err`,
`(t - sum) - y`); comments about rounding, bit-exactness, C-reference parity or
determinism; the result hashed, checksummed or compared with `==`/`assert_eq!`;
`total_cmp`, `to_bits`, float map or sort keys; monetary/accounting vocabulary;
verification paths (FLAC/ALAC MD5 of decoded PCM); RNG or seed state; anything feeding a
discrete branch whose flip is user-visible.

*Acceptable signals*: signal energy, RMS, loudness, mean/variance for display or gating;
dot products in inference or embedding similarity; radiance/distance/transmittance
accumulation in rendering; convolution taps in resampling, scaling or colour conversion;
values immediately quantized into a lossy pipeline (u8 pixels, s16 PCM); statistics
printed to few significant digits.

`allow_reassoc_and_contract` only when the chain is mul+add, the user opted into FMA, and
the source is not already using `mul_add` explicitly (an explicit `mul_add` is a deliberate
rounding choice). The state must also state the blast radius honestly: the flag stays on
those instructions for later passes, so the scalar remainder may be reassociated too.

---

## 5. Cost estimate

Gate 0 already passed (Day 0 §2: `libLLVM.so.23.1` exports 63 `PassBuilder` symbols,
assertions off, libstdc++ crosses the boundary) and the EP-probe plan exists (SPEC §13
day 3). What the FP option adds:

| item | days |
|---|---|
| Plugin skeleton: EP probe, site key, `dump`/`apply`/`off` (SPEC §13 day 3-5, already scoped) | 2--3 |
| `has_fp_reduction` + chain enumeration in dump via `RecurrenceDescriptor::isReductionPHI` (export confirmed) | 1 |
| Apply `setHasAllowReassoc` (+ optional `setHasAllowContract`); `-hints-allow-reordering=false` on all arms | 0.5--1 |
| ABI / libstdc++ / pass-ordering risk buffer | 1 |
| Target workloads: llama2-rs and ebur128 (weights or WAV, holdout split, artifact dump) | 1--2 |
| Tolerance gate, artifact comparators, determinism self-check | 1--1.5 |
| Jev `Choice` wiring, frozen prompt, JSONL logging | 1 |

**Total ≈ 6--9 working days for two targets**, +1--2 if Symphonia is added as the "real
program" third. Day-3 item 13 (metadata `vectorize.width=8`, and `vectorize.enable=true`
alone, on `dot_f64`) should still be run: it is pre-registered by decisions 8 and 13(c),
it is cheap, and the source now predicts the outcome, so it is a confirmation of the
re-verify-on-23.1.1 rule rather than an open question.
