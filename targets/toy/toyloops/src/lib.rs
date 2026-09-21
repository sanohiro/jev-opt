//! Four loop shapes that jev-opt cares about, written as plainly as possible.
//!
//! Deliberate constraints (see SPEC.ja.md 6.2 and 6.4): no inlining attributes,
//! no symbol-name attributes, no byte-search crate, and no architecture
//! intrinsics. The toy exists to exercise the inlining and site-matching
//! problem, so it must not opt out of it. Whether these functions survive as
//! separate symbols or get inlined into the binary is exactly what we want to
//! observe. Keeping the disqualification-filter tokens of SPEC.ja.md 6.1-2 out
//! of this file also keeps that filter free of false positives.

/// Byte reduction: count double quotes.
///
/// The accumulator that `count()` produces is `usize`, so LLVM may widen the
/// i8 compare result all the way to i64 and pick a small vector factor.
/// This is the VF 4 -> 32 hypothesis of SPEC.ja.md 6.2.
pub fn count_quotes(bytes: &[u8]) -> usize {
    bytes.iter().filter(|&&b| b == b'"').count()
}

/// Early-exit byte scanner: first byte that a JSON string would have to escape.
///
/// `position` breaks out of the loop, which historically makes the loop
/// vectorizer bail on legality grounds rather than on cost. This is the
/// "hints cannot reach it" case of SPEC.ja.md 6.2.
pub fn find_special(bytes: &[u8]) -> Option<usize> {
    bytes.iter().position(|&c| c == b'"' || c == b'\\' || c < 0x20)
}

/// Plain indexed reduction over u32 widened to u64.
///
/// The simplest possible shape: an index loop with a bounds-checked access
/// that LLVM should be able to prove away.
pub fn sum_indexed(v: &[u32]) -> u64 {
    let mut total: u64 = 0;
    for i in 0..v.len() {
        total += v[i] as u64;
    }
    total
}

/// f64 dot product: the zopfli-like shape (Huffman cost calculation).
///
/// Floating point addition is not associative, so without fast-math LLVM is
/// not allowed to reorder this reduction. Whether it vectorizes anyway (and
/// how) is one of the things day 0 records rather than assumes.
pub fn dot_f64(a: &[f64], b: &[f64]) -> f64 {
    let n = if a.len() < b.len() { a.len() } else { b.len() };
    let mut total: f64 = 0.0;
    for i in 0..n {
        total += a[i] * b[i];
    }
    total
}
