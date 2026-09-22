# Hint benchmark --- expected winner per kernel

Written 2026-09-22, **before any timing run**. This file is Claude's reference
answer for `targets/hintbench`: for each kernel, the mechanism it was built
around, the hint from the frozen vocabulary (SPEC.ja.md 1(2)) that is expected
to win there, the expected sign and rough size of the effect, and the evidence
gathered *without* measuring time --- remarks, symbol tables, disassembly,
LLVM bitcode and the plugin's dump.

It exists because decision 69 made the experiment's metric "how close Jev's
answer comes to Claude's judgement", and decision 71 left open whether
Claude's judgement is any good. An oracle sweep over these kernels answers
that: the oracle is ground truth, this file is the prediction, and Jev's
answers are the third column. Freezing the prediction before the measurement
is the only thing that makes the comparison mean anything, so **nothing above
section 3 may be edited after the first timing run**; corrections go in a
dated section at the end.

Jev never sees this file, and `jev-marks.txt` carries no hypothesis either
(decision 59).

## 0. Summary

| kernel | mark | hint the kernel was built for | expected winner | expected effect on that workload | confidence |
|---|---|---|---|---|---|
| K1 | `hbkernels::k1_step` | `inline(never)` | `inline(never)` | +2% to +10% | low |
| K2 | `hbkernels::k2_mix` | `inline` | **`KEEP_DEFAULT`** | every candidate 0% | high |
| K3 | `hbkernels::k3_fill_run` | `unroll.disable` | `unroll.disable` | +2% to +10% | medium |
| K4 | `hbkernels::k4_count_bytes` | `vectorize.width=16` | **`KEEP_DEFAULT`** | width 16: 0% to −25% | medium |
| K5 | `hbkernels::k5_mul_reduce` | `interleave.count=4` | **`KEEP_DEFAULT`** | IC 1: −50% to −75% | high |
| K6 | `hbkernels::k6_hot_loop` | `align=64` | `align=64` | ±0% to ±3%, sign unknown | low |
| K7 | `hbkernels::k7_error_path` | `cold` | **`inline(never)`**, not `cold` | 0% to +5%; `cold` exactly 0% | medium |
| K8 | `hbkernels::k8_scale_add` | --- (control) | `KEEP_DEFAULT` | every hint ≤ 0% | high |

Four of the eight could not be built as intended and their revised prediction
is in bold. Two different reasons:

* **K4 and K5**: LLVM already makes the choice the kernel was supposed to make
  it get wrong. The baseline is VF 8 x IC 4 at both, which is the right answer
  at both.
* **K2 and K7**: the hint itself is inert here. `inline` and `cold` are
  applied, reach the merged LTO module (checked in the bitcode, beside a
  `noinline` and an `align 64` that *are* honoured) and change nothing the
  inliner does. Section 2c is the measurement. Why the inliner ignores them is
  **not established** --- the two obvious explanations are ruled out there ---
  and whether it also happens on jaq is one `apply` build away and has not been
  run. It is still the most consequential thing this target found, because
  `inline` is the hint Jev reached for most often in the prompt study
  (decision 70).

That leaves three kernels with a live mechanism --- K1, K3 and K6 --- plus K7
redirected to `inline(never)`, and four sites whose expected answer is "leave
it alone". That is a weaker benchmark than intended and a more honest one: the
ratio of live to dead hints here is itself a result.

## 1. Per kernel

### K1 --- `inline(never)`

*Mechanism.* `k1_step` is 22 rounds of straight-line ALU work. The driver
`hb_k1` calls it from eight sites in one loop body, on eight independent
states. The baseline inlines all eight (measured: seven at `cost=640,
threshold=787` and the eighth at `cost=-14360` once it is the sole call), so
the loop body is roughly a thousand instructions of one-basic-block code ---
about the size of Zen 3's op cache. `inline(never)` leaves one out-of-line body
called eight times: the loop shrinks to a few dozen instructions at the price
of eight calls and eight returns per iteration (about 40 cycles against roughly
250 cycles of work).

The size is set by the threshold, and the threshold is 787, **not** the 3000 of
a hot call site: this kernel's loop runs a few million times against k5's
1.6e10, so the profile summary does not call its call sites hot. The first
draft of the kernel had 64 rounds and cost 1900; the baseline left it out of
line and `inline(never)` was a no-op. That is recorded because it is the trap:
a big function under PGO is only inlined where the *profile* is hot, and a
benchmark of `inline(never)` has to put its kernel there.

*Expected winner.* `inline(never)`, +2% to +10% on the k1 workload.
*Confidence: low* --- eight calls per iteration is a real cost and the gain
depends on whether the eight copies actually miss. `inline` and `cold` should
be exactly 0% (section 2c); the loop hints have nothing to attach to inside
`k1_step`, which has no loop.

### K2 --- `inline` (the hint is inert)

*Mechanism, as designed.* Reading LLVM, `inlinehint` looked like `Threshold =
max(Threshold, 325)`: it can only move a call site whose threshold is *below*
325, and only for a callee whose cost is in between. (That reading turns out
not to survive the control below.) The kernel was built to sit exactly there: `k2_mix` measures **cost 870 against threshold
787**, its call sites are four orders of magnitude below the program's hot
counts, and inlining would buy a great deal --- `k2_mix` multiplies by
`m = (mode & 7) | 1` and `mode` is a literal at both call sites, so out of line
every round pays a three-cycle register `imul` and inlined it becomes a
one-cycle `lea`, sixty times on one dependency chain.

*Why it failed.* Applying `inline` to `k2_mix` leaves the remark unchanged at
`cost=870, threshold=787` and the function stays out of line. This is not the
plugin failing to apply the attribute: `inlinehint` is on `k2_mix` in the
fat-LTO module the optimisation pipeline starts from (section 2c), right beside
the `noinline` that does work on `k1_step`. It is tempting to explain it by
`inline` being `max(Threshold, 325)` --- every threshold in this build is 525
or 787, so the max would never select 325 --- but a control build with
`-Cllvm-args=-inlinehint-threshold=5000` also leaves the threshold at 787, and
that rules the explanation out. The inliner behaves as though the attribute is
not there; why is open (section 2c).

*Expected winner.* `KEEP_DEFAULT`, and specifically: `inline` should produce a
**binary identical to the baseline**, so the k2 arms belong in the run's
in-sweep null panel (decision 31). The oracle's per-arm normalised-code
comparison is what will confirm that; the smoke build cannot, because it
applied all eight hints at once. *Confidence: high.*

### K3 --- `unroll.disable`

*Mechanism.* The zopfli `cache.rs:108` shape (decision 22): `while i <= end {
dst[i] = v; i += 1 }` with a runtime trip count of 4 to 19 (dump: **trip
11.48**). The value carried between iterations (`v = v.rotate_left(3) ^
0x9E37`) keeps the vectoriser out --- the remark at `lib.rs:173` is "loop not
vectorized", and an earlier draft that filled a constant was vectorised at
width 16, which on a trip count of a dozen means the vector body never runs and
the guard is paid for nothing. With the vectoriser out of the way the unroller
is the only thing a hint can reach.

The disassembly shows the default is a **runtime unroll by 8** with an
`and $0x7` / `xor $0x4` prologue and a separate remainder loop, and --- because
the trip count is unknown --- the unrolled body still carries a `cmp`/`je` pair
after *every* one of the eight stores. So the unrolling removes no branches at
all; it only adds a prologue, a remainder loop and eight times the code. On
zopfli, the whole range of this one dimension was worth +1.6% of the program.

*Expected winner.* `unroll.disable`, +2% to +10% on the k3 workload.
*Confidence: medium.* `unroll.count=2` should also win, by less;
`unroll.count=8` should reproduce the default; `vectorize.width=*` should do
nothing, because the loop is refused for a recurrence the vectoriser cannot
identify, and a width hint does not repeal legality (decision 14).

### K4 --- `vectorize.width` (could not be constructed)

*Mechanism, as designed.* `n: u32 += (b == needle) as u32` over a byte slice:
the shape of jaq's `to_ascii_lowercase` loop, the site where decision 70
recorded Claude choosing `vectorize.width=16` and Jev never choosing it. The
accumulator is u32 rather than the i64 of `toyloops::count_quotes`, which is
what made decision 12's forced width 2.2x slower: with u32 lanes a wider factor
costs one `vpmovzxbd` per lane group instead of a three-level extension tree.

*Why it failed.* The baseline already does the wide thing. The remark is
"vectorized loop (vectorization width: 8, interleaved count: 4)" and the
disassembly of the inlined loop is `vpcmpeqb %xmm` / `vpmovzxbd %xmm,%ymm` /
`vpaddd %ymm` over **four** accumulators: 32 bytes per iteration. A forced width
of 16 cannot add bandwidth, it can only trade lanes against interleaving.
LLVM's x86 cost model has been right about vector width on every target in this
project (decisions 12, 29, 31) and it is right again here.

*Expected winner.* `KEEP_DEFAULT`. `vectorize.width=16` is expected to be 0%
to −25%, `vectorize.width=2` clearly worse, `interleave.count=1` clearly worse.
*Confidence: medium* on the sign, low on the size.

### K5 --- `interleave.count` (could not be constructed)

*Mechanism, as designed.* `acc = acc.wrapping_mul(x | 1)` over 4096 u32 in L1:
a multiplicative reduction, so the loop is a chain of `vpmulld` at three cycles
of latency and the number of independent accumulator chains is the whole story.
At IC 1 the loop retires 8 elements every 3 cycles, at IC 4 it retires 32.

*Why it failed.* The baseline already picks IC 4 (remark: "vectorized loop
(vectorization width: 8, interleaved count: 4)"; disassembly: four independent
`ymm` accumulators). That is not an accident of this loop. LoopVectorize
returns the *maximum* interleave count for any vectorised loop that carries a
reduction and does not apply the small-loop-cost cap to it, so on this hardware
a vectorised integer reduction is always interleaved to the register budget. A
draft with six chained multiplies per element --- enough loop cost to trip the
small-loop cap --- still came out IC 4. There is no shape in which
`interleave.count` is a winner and the loop is still a reduction.

*Expected winner.* `KEEP_DEFAULT`. The kernel is kept because its *losses* are
predictable and large: `interleave.count=1` should cost **50% to 75%** of the
k5 workload and `=2` about half of that. That makes k5 the calibration site of
the whole benchmark --- if the sweep cannot see this, it cannot see anything.
*Confidence: high.*

### K6 --- `align=64`

*Mechanism.* A three-instruction loop body (`rorx`, `xor`, the induction step)
over 4096 u32 per call, inside a function the inliner leaves alone (measured:
`cost=715, threshold=525`, and two call sites so the "last call to static"
bonus does not apply). A 48-round preamble that runs once per call is what
holds the cost above the threshold; the inner loop does not pay for it.

Measured layout:

| build | entry | entry mod 64 | loop header | header mod 64 | body |
|---|---|---|---|---|---|
| baseline | `0x11e10` | **16** | entry + `0x300` | **16** | 80 bytes, runtime-unrolled by 8 |
| `align=64` applied | `0xeb00` | **0** | entry + `0x300` | **0** | unchanged |

So the hint does exactly what it is supposed to: the loop moves from byte 16 of
a 64-byte fetch window to byte 0. At 80 bytes the body spans two lines either
way, 48+32 before and 64+16 after. On jaq an alignment flag was the largest
effect in the whole 32-configuration sweep (+1.3% aggregate, +3.4% on one case,
decision 31), which is why this kernel exists, but the sign of a *particular*
realignment is not predictable from first principles.

*Expected winner.* `align=64`, ±0% to ±3%, **sign unknown**. *Confidence:
low*, and here "low" is a property of the mechanism, not of the construction.
`align=16` should be a no-op (16 is already the alignment).

### K7 --- `cold` (the hint is inert; redirected to `inline(never)`)

*Mechanism.* `k7_error_path` is taken on about one iteration in 256, twice per
loop body: far too often for the profile summary to call the call site cold
(its count is around 1e6, not 0), so the baseline inlines it --- measured,
`cost=135, threshold=787` at the first site and `cost=-14865` at the second.
Two copies of a 40-odd instruction body therefore sit *inside* the hot loop,
between the two halves of its own work. Getting them out is the mechanism.

*Why `cold` fails.* Applying `cold` changes nothing: the remark is still
`cost=135, threshold=787` and the function is still inlined at both sites, even
though the `cold` attribute is on it in the fat-LTO module the optimisation
pipeline starts from (section 2c). "The profile summary decides call-site
coldness for itself, and this call site is not cold in the profile" would
explain the *call-site* half, but not this: the callee's own `cold` attribute
also drives `Params.ColdThreshold` = 45, which would have shown as
`threshold=45` and would have cancelled the −14865 last-call bonus. Neither
happened. As with K2, the inliner behaves as though the attribute is not there
and the reason is open.

*Expected winner.* **`inline(never)`**, 0% to +5% on the k7 workload: it is the
one candidate in the vocabulary that actually takes the body out of the loop
(K1 shows it works). `cold` is expected to be exactly 0% and to produce a
baseline-identical binary. *Confidence: medium* on the sign --- LLVM's block
placement already sinks unlikely blocks to the end of the function from the
same profile, so what is left is the loop body's own footprint.

### K8 --- control

*Mechanism.* None, on purpose. `out[i] = a[i] * 3 + b[i]` over 4096 u32 in L1:
unit stride in and out, no loop-carried dependency, a trip count in the
thousands. Measured baseline: VF 8, IC 4 (`range.rs:1103` remark "vectorized
loop (vectorization width: 8, interleaved count: 4)", four `vpaddd` accumulator
groups in the disassembly). The loop is limited by the store port, so there is
no chain for `interleave.count` to split and no spare bandwidth for a wider
`vectorize.width`.

*Expected winner.* `KEEP_DEFAULT`; all 17 non-default candidates ≤ 0%.
*Confidence: high.* If any hint wins here by more than the noise floor, the
noise floor is wrong.

## 2. Evidence gathered without timing

All of it from four builds: the PGO baseline (`scripts/target_pgo_baseline.sh`),
the `JEV_MODE=dump` build, the `JEV_MODE=apply` smoke build and one diagnostic
build with `-Csave-temps`. Commands and raw output: results.md "Hint benchmark
(design)".

### 2a. Inlining, from the PGO baseline's remarks

| mark | cost | threshold | baseline outcome |
|---|---|---|---|
| `k1_step` | 640 | 787 | inlined at all 8 call sites |
| `k2_mix` | 870 | 787 | **not** inlined, 2 call sites |
| `k3_fill_run` | −14955 | 525 | inlined (sole call site) |
| `k4_count_bytes` | −15005 | 525 | inlined |
| `k5_mul_reduce` | −15000 | 525 | inlined |
| `k6_hot_loop` | 715 | 525 | **not** inlined, 2 call sites |
| `k7_error_path` | 135 / −14865 | 787 | inlined at both call sites |
| `k8_scale_add` | −15000 | 525 | inlined |

The dump's function table also shows that PGO put **`inlinehint` on
`k3_fill_run` by itself**, because its entry count is hot. That is the
phenomenon decision 70 saw on jaq's 251-instruction leaf: on a hot function the
`inline` hint is already there before anyone asks for it.

### 2b. Vectoriser and unroller, from remarks and disassembly

| site | remark | disassembly |
|---|---|---|
| k3 fill loop (`lib.rs:173`) | loop not vectorized | runtime unroll by 8, `and $0x7` prologue + remainder loop, a `cmp`/`je` after every store |
| k4 byte count | vectorized loop (width 8, interleaved count 4) | `vpcmpeqb %xmm` + `vpmovzxbd %xmm,%ymm` + `vpaddd %ymm` x4 accumulators |
| k5 mul reduction | vectorized loop (width 8, interleaved count 4) | `vpmulld %ymm` x4 independent chains |
| k6 serial loop | not vectorized (recurrence) | unrolled by 8, 80-byte body |
| k8 scale-add | vectorized loop (width 8, interleaved count 4) | `vpaddd` shift-add over 4 accumulator groups |

Remark attribution is by leaf source location, and for a `for &x in slice` loop
that leaf is `library/core/src/slice/iter/macros.rs:180`, not the kernel ---
which is why the table above pairs every remark with disassembly rather than
trusting the line number.

### 2c. What the plugin can and cannot reach --- the main result

One `JEV_MODE=apply` build carrying one hint per kernel. Every entry is
reported `consumed` (functions) or `attached` (loops), no `vanished` and no
`ambiguous`, and the eight output checksums are unchanged. But *consumed* is
not *effective*:

| hint | applied to | in the LTO bitcode? | effect on codegen |
|---|---|---|---|
| `inline(never)` | `k1_step` | `noinline` | **yes** --- 8 call sites become "should never be inlined", the symbol survives |
| `align=64` | `k6_hot_loop` | `align 64` on the `define` | **yes** --- entry 0x11e10 (mod 64 = 16) becomes 0xeb00 (mod 64 = 0) |
| `inline` | `k2_mix` | `inlinehint` present | **no** --- remark unchanged at `cost=870, threshold=787` |
| `cold` | `k7_error_path` | `cold` present | **no** --- remark unchanged at `cost=135, threshold=787`, still inlined |
| `unroll.disable` | k3 loop | `llvm.loop.unroll.disable` | attached |
| `vectorize.width=16` | k4 loop | metadata | attached |
| `interleave.count=4` | k5 loop | metadata | attached |
| `unroll.count=2` | k8 loop | metadata | attached |

The bitcode column is `llvm-dis` on `*.rcgu.lto.after-restriction.bc`, the
fat-LTO module after internalisation and before the LTO optimisation pipeline.
All four attributes are in that one module, side by side:

```
define internal ... @..k6_hot_loop #99 align 64 ...
attributes #101 = { cold mustprogress nofree norecurse ... }     <- k7_error_path
attributes #102 = { inlinehint mustprogress nofree ... }         <- k2_mix
attributes #103 = { mustprogress nofree noinline norecurse ... } <- k1_step
```

So two of the four are honoured and two are not, out of the same module in the
same build. **Why is not established.** The two obvious explanations are both
ruled out:

* "`inline` is `max(Threshold, 325)` and every threshold here is 525 or 787" is
  a complete story until you run `-Cllvm-args=-inlinehint-threshold=5000`,
  which also leaves `k2_mix` at `threshold=787`. If the attribute were read at
  all, that control had to move it.
* "the profile summary decides coldness for itself" would explain K7's call
  site, but the callee's `cold` attribute also drives `Params.ColdThreshold`
  = 45, which would have shown as `threshold=45` and cancelled the −14865
  last-call bonus. The remark is byte for byte the baseline's.

What is established: **the attributes are in the module the LTO pipeline starts
from and the inliner behaves as though they are absent.** Either a pass inside
that pipeline removes them before the CGSCC inliner, or the inliner does not
consult them in this configuration. Settling it needs a dump of the module
immediately before the inliner, which `-Csave-temps` does not produce.

Scope: this is measured on hintbench, on this recipe. Whether it also happens
on jaq is **one `JEV_MODE=apply` build away and has not been run** --- apply
`inline` to one jaq mark and `cold` to another and read the inline remarks.
Until then, "two of the four function-attribute hints in SPEC.ja.md 1(2) are
inert" is a statement about this target. The oracle will corroborate it here:
the `inline` and `cold` arms should come out code-identical to the baseline and
land in the in-sweep null panel.

### 2d. Sites and arm count

The dump resolves all 8 marks to functions and finds 6 `loop_in_mark` keys. The
frozen loop-site set keeps 4 (`scripts/hintbench_oracle.sh` states the rule),
so the sweep runs over **12 sites = 8 functions + 4 loops** and
**92 one-factor arms + 1 combination arm**.

`k3_fill_run` produces two keys, and only the hotter one is the fill loop:

| key | mark | trip | hotness | leaf | in the set |
|---|---|---|---|---|---|
| `ac9e5da8...-k3_fill_run-lib.rs-174` | k3 | 11.48 | 7.21e9 | `lib.rs:174` | yes |
| `56d14f7e...-k3_fill_run-lib.rs-173` | k3 | 4096.14 | 2.05e9 | `lib.rs:173` | no |
| `5acd6025...-next-macros.rs-180` | k4 | 16384.12 | 5.46e10 | `macros.rs:180` | yes |
| `fc420a4f...-next-macros.rs-180` | k5 | 4096.01 | 8.70e10 | `macros.rs:180` | yes |
| `9e9ba3f3...-spec_next-range.rs-1103` | k8 | 4096.01 | 3.16e10 | `range.rs:1103` | yes |
| `270c014b...-next-macros.rs-180` | k6 | 4096.00 | 6.55e9 | `macros.rs:180` | no (k6's hint is a function attribute) |

The second k3 key is the *driver's* loop over the run table --- its trip count
is the driver's 4096 --- picked up as `loop_in_mark` because the debug location
of its latch comes from the inlined callee. It is the same `loop_in_mark`
fuzziness decision 61 found on the toy, reproduced here on a two-loop nest of
known shape.

## 3. Corrections after the first timing run

*(none yet)*
