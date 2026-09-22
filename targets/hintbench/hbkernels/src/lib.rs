//! Eight kernels, one per hint in the frozen vocabulary of SPEC.ja.md 1(2).
//!
//! Each kernel is built so that exactly one hint has a *mechanism* to make it
//! faster and every other hint is neutral or harmful. `EXPECTED.md` names the
//! mechanism and the expected winner for each one, written down before any
//! timing; the oracle's one-factor sweep is what decides whether the mechanism
//! is real.
//!
//! Deliberate constraints, the same ones `targets/toy/toyloops` obeys: no
//! `#[inline]`, no `#[inline(never)]`, no `#[cold]`, no `#[repr(align)]`, no
//! `#[no_mangle]`, no architecture intrinsics, no byte-search crate. The whole
//! point is to observe what LLVM does by default and then to change it from
//! the outside through the plugin, so the source must not opt out of the
//! decision it exists to exercise. Every shape below is plain arithmetic and
//! plain `for` / `while` loops.
//!
//! **This crate holds only the kernels; their drivers are in the `hintbench`
//! bin.** That split is load bearing. rustc's own MIR inliner runs long before
//! the plugin sees anything, and a callee it inlines has no LLVM function for
//! a function attribute to be attached to. Within one crate it will inline a
//! body of MIR cost 50; across a crate boundary the callee must first be
//! exported as cross-crate-inlinable, which needs MIR cost under 100. Putting
//! every call site in the other crate therefore doubles the size a kernel
//! needs in order to survive as a symbol.
//!
//! Three facts about the *PGO* baseline drive the rest of the shapes, and none
//! of them is true of plain `-O3`:
//!
//!   * a call site the profile summary calls hot gets inline threshold 3000,
//!     so a callee under roughly 600 instructions is inlined there whatever
//!     else is true, and `inlinehint` (which only scales the threshold by
//!     325/250) cannot change that. The one kernel whose hint is `inline`
//!     therefore has to be called from a call site that is *not* hot.
//!   * a function with exactly one call site and internal linkage --- which is
//!     what every function here becomes after fat-LTO internalisation --- gets
//!     the "last call to static" bonus and is inlined regardless of size. So
//!     every kernel whose hint is a function attribute is called from two or
//!     more call sites.
//!   * a function whose entry count is hot is given the `inlinehint` threshold
//!     for free, which is the second reason the `inline` kernel has to be cool.

// ---------------------------------------------------------------------------
// shared round macros
// ---------------------------------------------------------------------------
//
// A "round" is one multiply, one rotate and one xor: about four LLVM
// instructions and a three-cycle dependency. Round counts are the only tuning
// knob used to place a kernel on the right side of an inline threshold, and
// each kernel says below which side it is aiming for.

macro_rules! hb_round {
    ($v:ident, $k:literal) => {
        $v = $v.wrapping_mul(($k as u32) | 1).rotate_left(5) ^ ($k as u32);
    };
}

macro_rules! hb_rounds {
    ($v:ident, $($k:literal),* $(,)?) => { $( hb_round!($v, $k); )* };
}

// ---------------------------------------------------------------------------
// K1 --- inline(never): a step function inlined eight times into a hot loop
// ---------------------------------------------------------------------------
//
// 22 rounds of straight-line ALU work, called from eight sites in one loop
// body. The size is set by the inline threshold, and the threshold that
// applies is 787, not the 3000 of a hot call site: this kernel's loop runs a
// few million times against k5's 1.6e10, so the profile summary does not call
// its call sites hot. The first draft --- 64 rounds, cost 1900 --- was left
// out of line by the baseline, which made `inline(never)` a no-op (measured,
// results.md "Hint benchmark (design)"). At 22 rounds the cost is about 650,
// the baseline inlines all eight copies, and the loop body becomes something
// like a thousand instructions of straight-line code. `inline(never)`
// collapses that to one out-of-line body called eight times: the loop fits the
// op cache again, and pays eight calls and eight returns per iteration.

macro_rules! k1_round {
    ($s:ident, $t:ident, $k:literal) => {
        $t = $t.rotate_left(7) ^ $s.wrapping_mul(($k as u32) | 1);
        $s = $s
            .wrapping_add($t)
            .rotate_left(11)
            ^ 0x9E37_79B1u32.wrapping_mul($k as u32);
    };
}

macro_rules! k1_rounds {
    ($s:ident, $t:ident, $($k:literal),* $(,)?) => { $( k1_round!($s, $t, $k); )* };
}

/// One step of a 22-round mixer. Marked; the hint under test is `inline(never)`.
pub fn k1_step(state: u32, b: u8) -> u32 {
    let mut s = state;
    let mut t = state ^ (b as u32).wrapping_mul(0x0101_0101);
    k1_rounds!(
        s, t, 0x11, 0x23, 0x37, 0x4d, 0x59, 0x67, 0x71, 0x83, 0x95, 0xa7,
        0xb3, 0xc5, 0xd9, 0xe3, 0xf1, 0x0b, 0x15, 0x29, 0x3b, 0x41, 0x57,
        0x63,
    );
    s ^ t
}

// ---------------------------------------------------------------------------
// K2 --- inline: a leaf just over the default inline threshold
// ---------------------------------------------------------------------------
//
// `inlinehint` replaces the base threshold 250 with 325 and the single-basic-
// block and vector bonuses scale from there, so it moves a call site's
// threshold by about 30% and nothing more. The only leaf it can flip is one
// whose cost lands inside that 30% window, at a call site the profile does not
// call hot. Both are engineered: the round count below is chosen from the
// measured `(cost=..., threshold=...)` remark of the baseline build, and the
// driver `hb_k2` does few iterations of heavy work so its block count stays
// three orders of magnitude under the vectorised kernels'.
//
// What inlining buys beyond the call itself: `mode` is a constant at both call
// sites, so the register multiply in every round becomes a multiply by 5 and
// the backend turns it into an `lea`. That is a two-cycle saving per round on
// the critical path, seventy-odd times per call, and it cannot happen while
// the callee is a separate function.

macro_rules! k2_round {
    ($v:ident, $m:ident, $k:literal) => {
        $v = $v.wrapping_mul($m).rotate_left(5) ^ ($k as u32);
    };
}

macro_rules! k2_rounds {
    ($v:ident, $m:ident, $($k:literal),* $(,)?) => { $( k2_round!($v, $m, $k); )* };
}

/// Leaf mixer for K2. Marked; the hint under test is `inline`.
///
/// `m` is derived from `mode`, which is a constant at both call sites. Out of
/// line, every round pays a register `imul` (three cycles on znver3); inlined,
/// `m` folds to 5 and the multiply becomes an `lea` (one cycle). That is where
/// the win is: the inline cost model counts the multiply the same either way,
/// so making the argument constant does not push the callee back under the
/// threshold, and the strength reduction only happens after inlining.
pub fn k2_mix(x: u32, mode: u32, rot: u32) -> u32 {
    let m = (mode & 7) | 1;
    let mut v = x ^ rot;
    k2_rounds!(
        v, m, 0xba, 0x33, 0x82, 0xab, 0xca, 0xa3, 0x92, 0x1b, 0xda, 0x13,
        0xa2, 0x8b, 0xea, 0x83, 0xb2, 0xfb, 0xfa, 0xf3, 0xc2, 0x6b, 0x0a,
        0x63, 0xd2, 0xdb, 0x1a, 0xd3, 0xe2, 0x4b, 0x2a, 0x43, 0xf2, 0xbb,
        0x3a, 0xb3, 0x02, 0x2b, 0x4a, 0x23, 0x12, 0x9b, 0x5a, 0x93, 0x22,
        0x0b, 0x6a, 0x03, 0x32, 0x7b, 0x7a, 0x73, 0x42, 0xeb, 0x8a, 0xe3,
        0x52, 0x5b, 0x9a, 0x53, 0x62, 0xcb,
    );
    v ^ (v >> 7)
}

// ---------------------------------------------------------------------------
// K3 --- unroll.disable: the zopfli cache.rs:108 shape
// ---------------------------------------------------------------------------
//
// A `while i <= end` fill over a slice with a runtime trip count of 4 to 19.
// The rotate carried from one iteration to the next is what keeps the
// vectoriser out ("value that could not be identified as reduction"): a plain
// fill of a constant is vectorised at width 16 here, which on a trip count of
// a dozen means the vector body never runs and the loop pays the guard for
// nothing. With the vectoriser out of the way the unroller is the only thing
// left that a hint can reach, and its default runtime unroll pays a prologue
// and an epilogue for a loop that runs a dozen times (decision 22: on zopfli's
// version of this loop, turning the unroll off was worth +1.6%).

/// Fill `dst[prev..=end]` with a rotating value. Marked; the hint under test
/// is `unroll.disable` on its single loop.
pub fn k3_fill_run(dst: &mut [u16], prev: usize, end: usize, dist: u16) -> u16 {
    let mut i = prev;
    let mut v = dist;
    while i <= end {
        dst[i] = v;
        v = v.rotate_left(3) ^ 0x9E37;
        i += 1;
    }
    v
}

// ---------------------------------------------------------------------------
// K4 --- vectorize.width: a byte count with a 32-bit accumulator
// ---------------------------------------------------------------------------
//
// Decision 12 is the trap this avoids. `toyloops::count_quotes` accumulates
// into i64, so forcing a wide factor builds a three-level extension tree into
// eight `vpaddq` chains and is 2.2x slower; the cost model was right. Here the
// accumulator is u32, so one 256-bit register holds eight lanes and each extra
// lane group costs one `vpmovzxbd` rather than a tree level. The array is
// 16 KiB so it stays in L1 and the loop is limited by issue width rather than
// by memory. Which factor LLVM picks by default is read off the baseline
// remark, not assumed.

/// Count occurrences of `needle`. Marked; the hint under test is a
/// `vectorize.width` on its single loop.
pub fn k4_count_bytes(bytes: &[u8], needle: u8) -> u32 {
    let mut n: u32 = 0;
    for &b in bytes {
        n += (b == needle) as u32;
    }
    n
}

// ---------------------------------------------------------------------------
// K5 --- interleave.count: a latency-bound integer reduction
// ---------------------------------------------------------------------------
//
// An integer *add* reduction is throughput-bound --- `vpaddd` has one cycle of
// latency --- so no amount of interleaving can move it. A *multiply* reduction
// is a chain of `vpmulld`, three cycles on znver3, so the number of independent
// accumulator chains is the whole story: at IC 1 the loop retires 8 elements
// every three cycles, at IC 4 it retires 32.
//
// The measured default is already VF 8 x IC 4 (see EXPECTED.md), which is the
// right answer, because LoopVectorize returns the *maximum* interleave count
// for any vectorised loop that carries a reduction and never applies the
// small-loop-cost cap to it. So this kernel does not have an `interleave.count`
// winner: it is the site at which the sweep is expected to measure a large
// *loss* for `interleave.count=1` and `=2`, which is what shows that the
// measurement can see a real effect at all.

/// Multiplicative reduction. Marked; the hint under test is an
/// `interleave.count` on its single loop.
pub fn k5_mul_reduce(a: &[u32]) -> u32 {
    let mut acc: u32 = 1;
    for &x in a {
        acc = acc.wrapping_mul(x | 1);
    }
    acc
}

// ---------------------------------------------------------------------------
// K6 --- align=64: a tiny serial loop whose entry alignment is the variable
// ---------------------------------------------------------------------------
//
// The loop body is a rotate, an xor and a load: a few bytes of machine code,
// repeated 2^14 times per call. Its offset inside the function is fixed, so
// moving the function entry onto a cache line moves the loop inside the 64-byte
// fetch windows. On jaq, an alignment flag moved the aggregate by 1.3% and a
// single case by 3.4% --- more than any vectoriser knob (decision 31) --- so
// this is the one kernel whose mechanism has already been seen on a real
// target.
//
// Two things keep the function out of line, which `align` needs: a 48-round
// preamble that runs once per call and pushes the inline cost well past any
// threshold a cool call site gets, and two call sites, which deny it the "last
// call to static" bonus. The inner loop does 2^14 iterations per call, so the
// preamble is under a thousandth of the kernel's work.

/// Serial hash over `data`. Marked; the hint under test is `align=64`.
pub fn k6_hot_loop(data: &[u32], k: u32) -> u32 {
    let mut h = k;
    hb_rounds!(
        h, 0x2f, 0x4b, 0x61, 0x7d, 0x93, 0xa9, 0xbf, 0xd5, 0xeb, 0x0f, 0x21,
        0x43, 0x65, 0x87, 0xa1, 0xc3, 0xe7, 0x09, 0x2b, 0x4d, 0x6f, 0x81, 0xa5,
        0xc9, 0xed, 0x03, 0x25, 0x47, 0x69, 0x8b, 0xad, 0xcf, 0xf1, 0x13, 0x37,
        0x59, 0x7b, 0x9f, 0xc1, 0xe3, 0x05, 0x27, 0x49, 0x6b, 0x8d, 0xaf, 0xd1,
        0xf3,
    );
    for &x in data {
        h = h.rotate_left(5) ^ x;
    }
    h
}

// ---------------------------------------------------------------------------
// K7 --- cold: a rarely taken error path inlined into the hot loop
// ---------------------------------------------------------------------------
//
// Taken on about one iteration in 256. That is far too often for the profile
// summary to call the call site cold, so the default build inlines the whole
// error body into the middle of the hot loop, between the two halves of the
// loop's own work. `cold` does two things to that: it lowers the callee's own
// threshold to 45, which takes the body back out of line, and it tells the
// layout pass to put the body away from the loop.

/// The rarely taken path. Marked; the hint under test is `cold`.
pub fn k7_error_path(code: u32, tag: u32) -> u32 {
    let mut v = code ^ tag.wrapping_mul(0x9E37_79B1);
    hb_rounds!(v, 0x3d, 0x59, 0x6f, 0x8b, 0xa7, 0xc1, 0xdd, 0xf9, 0x17, 0x33);
    v ^ (code.rotate_left(11) & 0x00FF_00FF)
}

// ---------------------------------------------------------------------------
// K8 --- KEEP_DEFAULT control: a loop LLVM already compiles well
// ---------------------------------------------------------------------------
//
// Unit-stride loads, a unit-stride store, no dependency across iterations, a
// trip count in the tens of thousands and data that fits in L1. LLVM vectorises
// it at the factor its cost model likes and the loop is limited by the store
// port, so there is no chain for `interleave.count` to split and no bandwidth
// for a wider `vectorize.width` to buy. Every hint in the vocabulary should be
// neutral or harmful. This is the control that says whether the sweep can tell
// "nothing to do" from "something to do".

/// Element-wise scale and add. Marked; the expected answer is `KEEP_DEFAULT`.
pub fn k8_scale_add(a: &[u32], b: &[u32], out: &mut [u32]) {
    let n = if a.len() < b.len() { a.len() } else { b.len() };
    let n = if n < out.len() { n } else { out.len() };
    for i in 0..n {
        out[i] = a[i].wrapping_mul(3).wrapping_add(b[i]);
    }
}
