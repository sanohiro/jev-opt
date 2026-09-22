# Why `inlinehint` and `cold` are inert in the PGO baseline

Read-only source study, 2026-09-22. No build, no measurement.

Closes the open question in `results.md` §106 ("**Why is not established**") and
replaces the hypothesis recorded in decision 74 ("PGO's profile-derived hotness
takes precedence over the callee's `inlinehint` / `cold` attributes") with a
sharper statement that also predicts the two control results §106 used to rule
that hypothesis out.

All LLVM citations are `third_party/llvm-project-23.1.1.src/`, tag
`llvmorg-23.1.1`, fetched by `scripts/fetch_llvm_headers.sh`. Paths below are
relative to that directory. rustc citations are the pinned toolchain,
`nightly-2026-09-21` = `rustc 1.100.0-nightly (bba53100 …)`.

---

## 0. One-line answer

The inliner **does** read `inlinehint`. It reads it first, and then a later
branch in the same function **assigns over it** — not `max`, a plain
assignment — whenever the callsite is hot or locally hot. `cold` is worse off:
the branch that reads the callee's `cold` attribute is the `else` arm of the
same if/else chain, so a hot, locally hot or cold *callsite* makes that arm
unreachable. `noinline` and `alwaysinline` are decided before the cost analyser
is ever constructed, which is why they always win. `align` is not an inliner
input at all.

So the correct framing is not "PGO ignores the attributes". It is: **under PGO
at `-Copt-level=3`, nearly every callsite is classifiable from the profile, and
a classified callsite overwrites or bypasses the attribute-derived threshold.
`inlinehint` and `cold` survive in exactly one cell of the matrix — a callsite
the profile calls neither hot, nor locally hot, nor cold.**

---

## 1. The threshold path, line by line

`InlineCostCallAnalyzer::updateThreshold` is called once per candidate, from
`onAnalysisStart` (`llvm/lib/Analysis/InlineCost.cpp:1169`). Its body begins at
`llvm/lib/Analysis/InlineCost.cpp:2075`.

### 1a. `inlinehint` is read — unconditionally

```cpp
// llvm/lib/Analysis/InlineCost.cpp:2130-2137
  // Adjust the threshold based on inlinehint attribute and profile based
  // hotness information if the caller does not have MinSize attribute.
  if (!Caller->hasMinSize()) {
    std::optional<int> HintThreshold = Caller->hasOptSize()
                                           ? Params.OptSizeHintThreshold
                                           : Params.HintThreshold;
    if (Callee.hasFnAttribute(Attribute::InlineHint))
      Threshold = MaxIfValid(Threshold, HintThreshold);
```

The only guard is `!Caller->hasMinSize()`. There is no `PSI` test, no
`hasProfileSummary()` test. **The claim "when PGO profile data exists the callee's
`inlinehint` is ignored" is, read literally, refuted at line 2136.** It is read,
and `Threshold` really does become 325 (`HintThreshold`,
`llvm/lib/Analysis/InlineCost.cpp:81-83`) or 5000 under
`-inlinehint-threshold=5000`.

### 1b. …and then overwritten

```cpp
// llvm/lib/Analysis/InlineCost.cpp:2139-2180
    // FIXME: After switching to the new passmanager, simplify the logic below
    // by checking only the callsite hotness/coldness as we will reliably
    // have local profile information.
    //
    // Callsite hotness and coldness can be determined if sample profile is
    // used (which adds hotness metadata to calls) or if caller's
    // BlockFrequencyInfo is available.
    BlockFrequencyInfo *CallerBFI = GetBFI ? &(GetBFI(*Caller)) : nullptr;
    auto HotCallSiteThreshold = getHotCallSiteThreshold(Call, CallerBFI);
    if (!Caller->hasOptSize() && HotCallSiteThreshold) {
      LLVM_DEBUG(dbgs() << "Hot callsite.\n");
      // FIXME: This should update the threshold only if it exceeds the
      // current threshold, but AutoFDO + ThinLTO currently relies on this
      // behavior to prevent inlining of hot callsites during ThinLTO
      // compile phase.
      Threshold = *HotCallSiteThreshold;                      // 2154
    } else if (isColdCallSite(Call, CallerBFI)) {
      LLVM_DEBUG(dbgs() << "Cold callsite.\n");
      DisallowAllBonuses();                                   // 2161
      Threshold = MinIfValid(Threshold, Params.ColdCallSiteThreshold); // 2162
    } else if (PSI) {                                         // 2163
      // Use callee's global profile information only if we have no way of
      // determining this via callsite information.
      if (PSI->isFunctionEntryHot(&Callee)) {                 // 2166
        Threshold = MaxIfValid(Threshold, HintThreshold);     // 2171
      } else if (PSI->isFunctionEntryCold(&Callee)) {         // 2172
        DisallowAllBonuses();                                 // 2178
        Threshold = MinIfValid(Threshold, Params.ColdThreshold); // 2179
      }
    }
  }
```

Two things decide everything:

* **Line 2154 is `=`, not `max`.** The FIXME at 2150-2153 says so explicitly and
  says why it has never been fixed. Whatever `inlinehint` put in `Threshold` at
  2137 is discarded.
* **Lines 2155 / 2163 are `else if`.** The `PSI` arm — the *only* place the
  callee's `cold` attribute can reach the threshold — is entered only when the
  callsite is neither hot/locally hot (2148) nor cold (2155).

The comment at 2164-2165 states the design intent in LLVM's own words: callee
attributes are the fallback used "only if we have no way of determining this via
callsite information". With a profile there is always a way.

### 1c. What `getHotCallSiteThreshold` returns

```cpp
// llvm/lib/Analysis/InlineCost.cpp:2046-2072  (abridged)
InlineCostCallAnalyzer::getHotCallSiteThreshold(CallBase &Call,
                                                BlockFrequencyInfo *CallerBFI) {
  if (PSI && PSI->hasProfileSummary() && PSI->isHotCallSite(Call, CallerBFI))
    return Params.HotCallSiteThreshold;                 // 3000
  if (!CallerBFI || !Params.LocallyHotCallSiteThreshold)
    return std::nullopt;
  …
  std::optional<BlockFrequency> Limit = CallerEntryFreq.mul(HotCallSiteRelFreq);
  if (Limit && CallSiteFreq >= *Limit)
    return Params.LocallyHotCallSiteThreshold;          // 525
  return std::nullopt;
}
```

Constants: `HotCallSiteThreshold` = 3000 (`:122-123`),
`LocallyHotCallSiteThreshold` = 525 (`:125-127`), `HotCallSiteRelFreq` = 60
(`:135-138`), `ColdCallSiteThreshold` = 45 (`:86-89`), `ColdThreshold` = 45
(`:117-119`), `HintThreshold` = 325 (`:81-83`). The O3 default threshold is
`InlineConstants::OptAggressiveThreshold` = 250
(`llvm/include/llvm/Analysis/InlineCost.h:46`, selected in
`getInlineParamsFromOptLevel`, `llvm/lib/Analysis/InlineCost.cpp:3427-3438`).

`Params.LocallyHotCallSiteThreshold` is populated **only at `OptLevel > 2`**
(`llvm/lib/Analysis/InlineCost.cpp:3435-3437`). `targets/hintbench/Cargo.toml:16`
is `opt-level = 3`, so it is populated here.

`GetBFI` is handed to `getInlineCost` unconditionally by the default advisor
(`llvm/lib/Analysis/InlineAdvisor.cpp:156-158, 173-175`), so `CallerBFI` is never
null in this configuration.

### 1d. This account reproduces every number in `results.md` §105/§106

`results.md` reports `threshold=787` for K1/K2/K7 and `threshold=525` for K6.

* 525 is `LocallyHotCallSiteThreshold` verbatim. Nothing else in the file is
  525. It is reached through the second branch of §1c: a kernel called from a
  driver loop trivially exceeds 60× the caller's entry frequency.
* 787 = 525 + `SingleBBBonus`, where `SingleBBBonusPercent = 50`
  (`llvm/lib/Analysis/InlineCost.cpp:2106`) → 525 × 50 / 100 = 262. The bonus is
  applied speculatively in `onAnalysisStart` and withdrawn in `onBlockAnalyzed`
  (`:856-877`) the moment a block with more than one successor is seen. K6 is the
  loop kernel; K1/K2/K7 are straight-line. The `VectorBonus` (150%,
  `llvm/include/llvm/Analysis/TargetTransformInfoImpl.h:111`) is likewise applied
  speculatively and fully withdrawn at `:1100-1106` for a callee that is ≤10%
  vector instructions.
* Had the hot-callsite branch **not** fired, K2 would have shown
  `threshold = max(250, 325) + 162 = 487`, and with `-inlinehint-threshold=5000`
  it would have shown 7500. Neither was observed; 787 was, both times.

This is what §106's first "ruled out" control actually proved: not that the
attribute is unread, but that line 2154 discards it. And §106's second "ruled
out" control — "`cold` should have produced `threshold=45` and cancelled the
−14865 last-call bonus" — is answered by the `else if` at 2163: with the
hot-callsite branch taken, `DisallowAllBonuses()` at 2178 and
`Params.ColdThreshold` at 2179 are simply not executed. The remark being "byte
for byte the baseline's" is the predicted outcome, not an anomaly.

### 1e. `cold` on the callee *is* honoured — in the one arm that is unreachable here

```cpp
// llvm/lib/Analysis/ProfileSummaryInfo.cpp:106-117
bool ProfileSummaryInfo::isFunctionEntryCold(const Function *F) const {
  if (!F)
    return false;
  if (F->hasFnAttribute(Attribute::Cold))
    return true;
  if (!hasProfileSummary())
    return false;
  …
}
```

The attribute short-circuits ahead of the profile. So on a *lukewarm* callsite,
`cold` still works and still yields `Threshold = min(T, 45)` plus
`DisallowAllBonuses()`. It is not dead code; it is code this baseline never
reaches.

Note the asymmetry: `isFunctionEntryHot`
(`llvm/include/llvm/Analysis/ProfileSummaryInfo.h:115-123`) has **no**
`Attribute::Hot` check. It reads the entry count only.

### 1f. The second reason `cold` cannot bite under PGO: BPI

Even the indirect route is closed. `BranchProbabilityInfo` gives a block
containing a call to a `cold` function the `COLD` execution weight:

```cpp
// llvm/lib/Analysis/BranchProbabilityInfo.cpp:935-939
  // Check if the block contains 'cold' call.
  for (const auto &I : *BB)
    if (const CallInst *CI = dyn_cast<CallInst>(&I))
      if (CI->hasFnAttr(Attribute::Cold))
        return static_cast<uint32_t>(BlockExecWeight::COLD);
```

but the per-block dispatch checks profile metadata first and returns:

```cpp
// llvm/lib/Analysis/BranchProbabilityInfo.cpp:1256-1259
    if (calcMetadataWeights(BB))
      continue;
    if (calcEstimatedHeuristics(BB))   // <- where the cold-call weight lives
      continue;
```

Under `-Cprofile-use` every conditional branch in a function the profile saw
executed carries `!prof`, so `calcMetadataWeights` wins there and the cold-call
heuristic never runs. (A function whose counters are all zero gets
`setEntryCount(0)` and no branch weights,
`PGOInstrumentation.cpp:2315-2319` — but then its callsites read profile count 0
and land in class C below, where the `cold` attribute is equally unreachable.)
`cold` therefore cannot even move the caller's block frequencies, which is what
`isColdCallSite` reads.

### 1g. On genuinely hot callsites the threshold is not consulted at all

Under an **instrumentation** profile (which `-Cprofile-use` is), LLVM switches
the hottest callsites to cost/benefit:

```cpp
// llvm/lib/Analysis/InlineCost.cpp:900-927 (abridged)
  bool isCostBenefitAnalysisEnabled() {
    if (!PSI || !PSI->hasProfileSummary()) return false;
    if (!GetBFI) return false;
    if (InlineEnableCostBenefitAnalysis.getNumOccurrences()) { … }
    else { if (!PSI->hasInstrumentationProfile()) return false; }
    if (!Caller->getEntryCount()) return false;
    …
    // For now, limit to hot call site.
    if (!PSI->isHotCallSite(CandidateCall, CallerBFI)) return false;
```

and when it is enabled the threshold comparison is short-circuited entirely:

```cpp
// llvm/lib/Analysis/InlineCost.cpp:1121-1135
    if (auto Result = costBenefitAnalysis()) {
      DecidedByCostBenefit = true;
      …
    }
    if (IgnoreThreshold) return InlineResult::success();
    DecidedByCostThreshold = true;
    return Cost < std::max(1, Threshold) ? … ;
```

Such a decision is reported as `always inline (benefit over cost)` /
`never inline (cost over benefit)` with no threshold at all
(`llvm/lib/Analysis/InlineCost.cpp:3293-3299`). **On jaq's hottest callsites,
no threshold-shifting hint can matter by construction.** Only the
attribute-based decisions of §2 can.

---

## 2. `alwaysinline` and `noinline` bypass all of the above

`getInlineCost` asks `getAttributeBasedInliningDecision` before it constructs
the analyser; a non-`nullopt` answer returns `getAlways`/`getNever` immediately
(`llvm/lib/Analysis/InlineCost.cpp:3265-3272`).

```cpp
// llvm/lib/Analysis/InlineCost.cpp:3200-3247 (abridged, order preserved)
  if (!IgnoreTTIInlineCompatible &&
      !CalleeTTI.areInlineCompatible(Caller, Callee))          // 3202-3205
    return InlineResult::failure("conflicting target features");

  if (Call.hasFnAttr(Attribute::AlwaysInline)) {               // 3209
    if (Call.getAttributes().hasFnAttr(Attribute::NoInline))   // 3210
      return InlineResult::failure("noinline call site attribute");
    auto IsViable = isInlineViable(*Callee);                   // 3213
    …
  }
  if (!functionsHaveCompatibleAttributes(Caller, Callee, GetTLI)) …  // 3220
  if (Caller->hasFnAttribute(Attribute::Flatten)) …            // 3225
  if (Caller->hasOptNone()) …                                  // 3233
  if (Callee->isInterposable(false)) …                         // 3237
  if (Callee->hasFnAttribute(Attribute::NoInline))             // 3242
    return InlineResult::failure("noinline function attribute");
  if (Call.isNoInline()) …                                     // 3246
```

No `PSI`, no `BFI`, no threshold. **Both are profile-immune.** This is exactly
what `results.md` §106 measured for `noinline` on `k1_step`.

### Does `noinline` *always* win?

In our world, yes. In LLVM in general, two orderings beat a callee's `noinline`,
because both are tested before line 3242: an `alwaysinline` attribute **on the
callsite** (3209 fires first, and the guard at 3210 only looks at the callsite's
own `noinline`), and a **caller** carrying `flatten` (3225). Neither is
producible from Rust source, and the plugin only ever writes function
attributes, so `inline(never)` is absolute for us — confirmed by measurement in
`results.md` §106.

### Caveats for `alwaysinline`

| caveat | citation |
|---|---|
| Target-feature mismatch beats it (checked at 3202, *before* 3209) | `InlineCost.cpp:3202-3205` |
| A `noinline` **callsite** attribute beats it | `InlineCost.cpp:3210-3211` |
| `noinline` + `alwaysinline` on one function is a **verifier error** | `llvm/lib/IR/Verifier.cpp:2137-2141`, `:2359-2361` |
| Not viable ⇒ not inlined: recursive self-call, `va_start`, `indirectbr`, taken blockaddress, exposing returns-twice, `llvm.localescape`, `llvm.icall.branch.funnel` | `InlineCost.cpp:3311-3360` |
| Failure is *reported*: `AlwaysInliner` emits `OptimizationRemarkMissed("NotInlined")` with the reason | `llvm/lib/Transforms/IPO/AlwaysInliner.cpp:60-69`, `:76-83` |
| Inlined at **every** callsite regardless of cost or code growth | `AlwaysInliner.cpp:107-113` |
| A trivially-dead `alwaysinline` callee is **erased from the module** after inlining — the symbol disappears | `AlwaysInliner.cpp:120-129` |

The last row is operationally important for us: an `inline(always)` arm can make
the marked function vanish from the symbol table, which the plugin's
`vanished`/`consumed` bookkeeping and the oracle's normalised-code hash must be
prepared for.

The verifier row is also a plugin bug waiting to happen. `plugin/jev/jev.cpp`
has no `"always"` branch today (`:1314-1332` handles only `"never"` and
`"hint"`), and its comment at `:1316-1317` is slightly wrong: only
`noinline`+`alwaysinline` is rejected, `noinline`+`inlinehint` is legal. An
`"always"` branch must `removeFnAttr(Attribute::NoInline)` before
`addFnAttr(Attribute::AlwaysInline)` — **and must skip a callee with
`optnone`**, because `llvm/lib/IR/Verifier.cpp:2363-2365` requires `optnone` to
be accompanied by `noinline`; stripping the `noinline` off such a function
breaks the module verifier. (rustc emits `optnone` for `#[optimize(none)]`, and
pairs it with `InlineAttr::Never`.)

---

## 3. `hot`

`Attribute::Hot` does not occur anywhere in `llvm/lib/Analysis/InlineCost.cpp`
(zero grep hits), and `isFunctionEntryHot` does not read it
(`ProfileSummaryInfo.h:115-123`). **`hot` is inert for inlining, with or without
a profile.** It is not "overridden under PGO"; it was never an inliner input.

It is not a no-op overall:

* `.text.hot` section placement, and `hot` **overrides** the profile there:
  `llvm/lib/CodeGen/CodeGenPrepare.cpp:594-606`.
* It suppresses PGO's own cold marking and emits a **warning diagnostic** when
  the profile disagrees — an observable build-log signal:
  `llvm/lib/Transforms/Instrumentation/PGOInstrumentation.cpp:2394-2406`
  (`"Function X is annotated as a hot function but the profile is cold"`).
* It blocks `FunctionAttrs`' cold inference:
  `llvm/lib/Transforms/IPO/FunctionAttrs.cpp:2136-2143`.

---

## 4. Pipeline ordering: PGO stamps the same attributes, after us

The plugin registers at `PipelineEarlySimplificationEP`
(`plugin/jev/jev.cpp:1514`). In `buildModuleSimplificationPipeline` that EP is
invoked at `llvm/lib/Passes/PassBuilderPipelines.cpp:1218`;
`addPGOInstrPasses` (which adds `PGOInstrumentationUse`, `:907`) is added at
`:1276-1282`. **The plugin runs first; `PGOInstrumentationUse` runs after it.**

`PGOInstrumentationUse` then stamps hotness attributes of its own:

```cpp
// llvm/lib/Transforms/Instrumentation/PGOInstrumentation.cpp:2388-2408 (abridged)
  for (auto &F : HotFunctions)  F->addFnAttr(Attribute::InlineHint);   // 2391
  for (auto &F : ColdFunctions) {
    if (F->hasFnAttribute(Attribute::Hot)) { …warn…; continue; }       // 2396-2406
    F->addFnAttr(Attribute::Cold);                                     // 2407
  }
```

It never removes a plugin-applied `inlinehint`, and removes `cold` only on the
`PseudoHot` path (`:2319-2326`). Consequences:

* A plugin `inline` on a profile-hot function is **redundant** — PGO would have
  added `inlinehint` anyway. This is `results.md` §105's observation that
  `k3_fill_run` already carried PGO's own `inlinehint`, and decision 70's
  "251-instruction hot leaf already `inlinehint`".
* A plugin `cold` on a profile-hot function produces a function carrying
  **both** `cold` and `inlinehint` (legal IR; only `noinline`+`alwaysinline` is
  rejected). In the `else if (PSI)` arm `isFunctionEntryHot` is tested first
  (2166), so even on a lukewarm callsite the `cold` would lose to the entry
  count.

This also lays §106's remaining alternative to rest: no pass strips the
attributes. They are present at the inliner, and the inliner's own control flow
skips them.

---

## 5. Is this PGO-specific?

Partly. Precisely:

| mechanism | needs a profile? |
|---|---|
| `Threshold = 3000` on a PSI-hot callsite (2154 via 2050-2051) | yes — `PSI->hasProfileSummary()` |
| cost/benefit replaces the threshold entirely (900-927, 1121) | yes — `hasInstrumentationProfile()` + PSI-hot |
| `Threshold = min(T, 45)` on a PSI-cold callsite (2162 via 2026-2028) | yes for the PSI route; a BFI-only route exists at 2038-2043 |
| **`Threshold = 525` on a locally hot callsite (2154 via 2062-2069)** | **no — `CallerBFI` + `OptLevel > 2` only** |
| `calcMetadataWeights` shadowing the cold-call heuristic (1256-1258) | yes — `!prof` metadata |

The 525 row is the one that actually killed K2 and K7, and it does not require a
profile. It requires `-Copt-level=3` (for `LocallyHotCallSiteThreshold` to be
populated at all) and a callsite whose estimated frequency is ≥60× the caller's
entry. Without a profile LLVM's static loop heuristic scales a single loop body
by roughly one order of magnitude, which for a shallow loop nest falls short of
60× — so `inlinehint` is often live at plain O3 and usually dead under PGO.
(That last figure is an estimate from LLVM's static backedge probabilities, not a
citation; it is not load-bearing for anything above.) At `-Copt-level=2` the locally-hot route is disabled
entirely and only the PSI routes remain.

Write it down as: **under this recipe (`-Copt-level=3` + `-Cprofile-use` + fat
LTO), `inline` and `cold` are effectively inert; the surviving window is
lukewarm callsites, which in a PGO-trained program are by definition the ones
that do not matter.**

---

## 6. rustc's mapping, for vocabulary honesty

`compiler/rustc_codegen_llvm/src/attributes.rs` at the pinned commit
`bba531001d4de6d7f49693e0836a2668ca063282` (rustc 1.100.0-nightly):

```rust
// fn inline_attr, ~lines 48-76
match inline {
    InlineAttr::Hint => Some(AttributeKind::InlineHint.create_attr(cx.llcx)),
    InlineAttr::Always | InlineAttr::Force { .. } => {
        Some(AttributeKind::AlwaysInline.create_attr(cx.llcx))
    }
    InlineAttr::Never => {
        if tcx.sess.target.arch != Arch::AmdGpu {
            Some(AttributeKind::NoInline.create_attr(cx.llcx))
        } else {
            None
        }
    }
    InlineAttr::None => None,
}

// in llfn_attrs_from_instance, ~lines 416-418
if codegen_fn_attrs.flags.contains(CodegenFnAttrFlags::COLD) {
    to_add.push(AttributeKind::Cold.create_attr(cx.llcx));
}
```

| Rust | LLVM fn attribute |
|---|---|
| `#[inline]` | `inlinehint` |
| `#[inline(always)]` (and internal `#[rustc_force_inline]`) | `alwaysinline` |
| `#[inline(never)]` | `noinline` (except AMDGPU) |
| `#[cold]` | `cold` |
| `#[optimize(size)]` | `minsize` + `optsize` |
| — no surface syntax — | `hot` |

So our names `inline` / `inline(always)` / `inline(never)` / `cold` are honest
one-for-one names for `inlinehint` / `alwaysinline` / `noinline` / `cold`.
**`hot` has no Rust counterpart**: a Rust programmer cannot write it, and the
plugin is the only way it enters the IR. Two further honesty notes:

* `#[inline]` in Rust is *more* than `inlinehint`: it also drives cross-crate
  instantiation and the MIR inliner, neither of which the plugin's IR-level
  attribute touches. Compare decision 75 — the MIR inliner had to be disabled
  with `-Zcross-crate-inline-threshold=never` before the kernels even reached
  LLVM. The plugin's `inline` is strictly the weaker, LLVM-only half.
* For `#[cold]` no additional rustc-side effect was found at this commit:
  `rustc_mir_transform/src/inline.rs`'s `check_codegen_attributes` (~941-948)
  rejects `InlineAttr::Never` and checks target features / instruction sets, but
  does not special-case `CodegenFnAttrFlags::COLD`. (Only that function was
  read; this is a weaker statement than "nothing else in rustc looks at it".)
  The same file notes (~707) that `#[inline(always)]` still passes through the
  MIR inliner's cost threshold — another respect in which the Rust attribute and
  the LLVM attribute are not the same object.

---

## 7. Conclusion — the vocabulary table

Callsite classes under the baseline recipe (`-Copt-level=3`, `-Cprofile-use`,
fat LTO):

* **A — PSI-hot**: `PSI->isHotCallSite` (`ProfileSummaryInfo.cpp:219-223`).
  Decision made by cost/benefit; threshold meaningless.
* **B — locally hot**: callsite frequency ≥ 60× caller entry. `Threshold := 525`.
  *(K1, K2, K6, K7 are all here.)*
* **C — cold**: `PSI->isColdCallSite`. `Threshold := min(T, 45)`, all bonuses off.
* **D — lukewarm**: none of the above. The only arm that reads callee attributes.

| hint | A (PSI-hot) | B (locally hot, 525) | C (cold, 45) | D (lukewarm) | deciding line |
|---|---|---|---|---|---|
| `inline` → `inlinehint` | **inert** | **inert** | **inert** | live (250→325) | `InlineCost.cpp:2137` read, `:2154` overwritten |
| `inline(always)` → `alwaysinline` | **live** | **live** | **live** | **live** | `InlineCost.cpp:3209`, before any cost analysis |
| `inline(never)` → `noinline` | **live** | **live** | **live** | **live** | `InlineCost.cpp:3242`, before any cost analysis |
| `cold` → `cold` | **inert** | **inert** | **inert** | live (T→45, bonuses off) *unless the callee's entry count is hot — 2166 is tested before 2172* | `InlineCost.cpp:2163` `else if` unreachable; `:2179` |
| `hot` → `hot` | inert | inert | inert | inert | absent from `InlineCost.cpp` entirely |
| `align=N` | **live** | **live** | **live** | **live** | not an inliner input; emitted by AsmPrinter |

Secondary (non-inlining) effects that remain live in every column: `cold` and
`hot` both steer `.text.unlikely` / `.text.hot` placement
(`CodeGenPrepare.cpp:594-606`), and `hot` additionally suppresses PGO's cold
marking with a build-log warning (`PGOInstrumentation.cpp:2396-2406`).

### Recommended change to the frozen vocabulary (SPEC.ja.md §1(2), `jev_vocab.py` v2)

1. **Replace `inline` with `inline(always)`.** `inlinehint` cannot move a
   decision in this recipe and is redundant with what `PGOInstrumentationUse`
   stamps anyway (§4). `alwaysinline` is the only *positive* inlining lever that
   survives the profile. This needs a plugin change: a `"always"` branch in
   `plugin/jev/jev.cpp` around `:1314`, removing `NoInline` first (verifier), and
   the dump/consumed bookkeeping must tolerate the callee being erased
   (`AlwaysInliner.cpp:120-129`).
   Risks to record with it: unconditional code growth at every callsite; failure
   is silent unless remarks are read (`AlwaysInliner.cpp:60-69`); target-feature
   mismatch and viability failures (recursion, `va_start`, `indirectbr`) beat it.
2. **Drop `cold`, or relabel it.** It cannot reach the threshold here. If kept,
   it should be described as a *layout* hint (`.text.unlikely`), not an inlining
   hint — that is the only thing it still does under PGO.
3. **Drop `hot`.** Inert for inlining in every configuration, has no Rust
   counterpart, and its one live effect (section prefix + a PGO warning) is not
   what the name suggests to the model.
4. **Keep `inline(never)` and `align=N` unchanged.** Both confirmed live in the
   source and in `results.md` §106's measurement.

### Consequences for the decision-70 reading

`inline` was the hint Jev reached for most often in the prompt study. Under this
recipe that choice was a no-op in every case where the site was worth optimising
at all. The prompt study's agreement figures therefore over-report agreement on
*inert* candidates; §1g is the sharper form — on the hottest callsites of a
PGO-trained program **no** threshold-shifting vocabulary item can matter, and
only `inline(always)` / `inline(never)` / `align` can.

### Cheap follow-ups this memo does not do

* The in-sweep null panel for K2 `inline` and K7 `cold` (decision 76) should now
  be a *prediction*, not a check: both arms must be code-identical to the
  baseline.
* One `JEV_MODE=apply` build on jaq (decision 74's item 1) to confirm the same
  on a real target. The prediction is: `inline` and `cold` change nothing;
  remarks on jaq's hottest sites will read `benefit over cost` rather than
  `cost=…, threshold=…`, which is itself a check of §1g.
* `"function-inline-threshold"` / `"function-inline-cost"` are **callsite**
  string attributes applied at `InlineCost.cpp:1107-1119`, i.e. *after* line
  2154 and before the cost/benefit short-circuit. They are the only way to move
  a threshold in classes B, C and D from outside. The plugin marks functions,
  not callsites, so this is a possible future site kind, not a vocabulary change.
