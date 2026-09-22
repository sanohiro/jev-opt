//! Driver for the hint benchmark kernels.
//!
//! Usage: `hintbench <k1|k2|k3|k4|k5|k6|k7|k8|all> [repeats]`
//!
//! Same rules as `targets/toy`: inputs come from a fixed seed through a tiny
//! xorshift so every build sees byte-identical data, the program prints one
//! checksum line per workload and nothing else, and there is no timing code in
//! here at all. Timing is done from the outside (`scripts/bench.py`) so that
//! the measured binary contains only the kernels under study.
//!
//! The per-kernel `hb_kN` functions below are the *drivers*: the hot loops that
//! call the marked kernels of `hbkernels`. They live in this crate rather than
//! beside the kernels so that every call to a kernel crosses a crate boundary,
//! which is what keeps rustc's MIR inliner from deleting the kernels before
//! LLVM --- and the plugin --- ever sees them (see the crate docs of
//! `hbkernels`).
//!
//! One workload per kernel, because the readout is per kernel: the oracle's
//! ground truth for kernel N is the speed ratio on workload kN, not the
//! eight-way geometric mean, in which a 10% win on one kernel would be 1.2%
//! and below the minimum detectable effect (decision 16, results.md 58).

use hbkernels::{
    k1_step, k2_mix, k3_fill_run, k4_count_bytes, k5_mul_reduce, k6_hot_loop,
    k7_error_path, k8_scale_add,
};
use std::hint::black_box;

/// xorshift64*. Deterministic, no external crates, good enough for test data.
struct Rng(u64);

impl Rng {
    fn new(seed: u64) -> Self {
        Rng(seed)
    }

    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
}

const SEED: u64 = 0x9E37_79B9_7F4A_7C15;

// Input sizes. K4, K5, K6 and K8 stay inside L1 so those kernels are limited
// by the dependency chain or the issue width rather than by DRAM: a kernel
// waiting on memory cannot show a hint's effect at all.
const K1_LEN: usize = 1 << 16;
const K2_LEN: usize = 1 << 12;
const K3_LEN: usize = 1 << 12;
const K3_RUNS: usize = 1 << 12;
const K4_LEN: usize = 1 << 14;
const K5_LEN: usize = 1 << 12;
const K6_LEN: usize = 1 << 13;
const K7_LEN: usize = 1 << 14;
const K8_LEN: usize = 1 << 12;

/// Per-workload repeat counts, calibrated so that each workload runs for at
/// least 300 ms in the plain release build on the reference machine
/// (Ryzen 9 5950X; results.md "Hint benchmark (design)").
const REP_K1: u64 = 285;
const REP_K2: u64 = 950;
const REP_K3: u64 = 20000;
const REP_K4: u64 = 530000;
const REP_K5: u64 = 3800000;
const REP_K6: u64 = 100000;
const REP_K7: u64 = 41000;
const REP_K8: u64 = 920000;

fn gen_u8(len: usize, salt: u64) -> Vec<u8> {
    let mut rng = Rng::new(SEED ^ salt);
    (0..len).map(|_| (rng.next_u64() >> 24) as u8).collect()
}

fn gen_u32(len: usize, salt: u64) -> Vec<u32> {
    let mut rng = Rng::new(SEED ^ salt);
    (0..len).map(|_| (rng.next_u64() >> 32) as u32).collect()
}

/// K7 wants the two guarded paths taken on roughly one iteration in 256 each,
/// so the low two bytes are forced to zero exactly that often and never
/// otherwise. Rare enough that the body is not the kernel's work, common
/// enough that the profile summary does not call the call site cold.
fn gen_k7(len: usize) -> Vec<u32> {
    let mut rng = Rng::new(SEED ^ 0x7777_7777_7777_7777);
    (0..len)
        .map(|_| {
            let r = rng.next_u64();
            let mut v = (r >> 32) as u32 | 0x0000_0101;
            match r % 256 {
                0 => v &= 0xFFFF_FF00,
                1 => v &= 0xFFFF_00FF,
                _ => {}
            }
            v
        })
        .collect()
}

// --- drivers -------------------------------------------------------------

/// K1: eight call sites of `k1_step` in one loop body, on eight independent
/// states, so that the default build carries eight copies of it inside the
/// loop and `inline(never)` has something to take out.
fn hb_k1(data: &[u8], seed: u32) -> u32 {
    let mut a = seed;
    let mut b = seed ^ 0x5555_5555;
    let mut c = seed ^ 0xAAAA_AAAA;
    let mut d = seed ^ 0x3333_3333;
    let mut e = seed ^ 0x0F0F_0F0F;
    let mut f = seed ^ 0xF0F0_F0F0;
    let mut g = seed ^ 0x1234_5678;
    let mut h = seed ^ 0x8765_4321;
    let mut i = 0usize;
    while i + 8 <= data.len() {
        a = k1_step(a, data[i]);
        b = k1_step(b, data[i + 1]);
        c = k1_step(c, data[i + 2]);
        d = k1_step(d, data[i + 3]);
        e = k1_step(e, data[i + 4]);
        f = k1_step(f, data[i + 5]);
        g = k1_step(g, data[i + 6]);
        h = k1_step(h, data[i + 7]);
        i += 8;
    }
    a ^ b ^ c ^ d ^ e ^ f ^ g ^ h
}

/// K2: two call sites of `k2_mix`, both with constant `mode` and `rot`.
fn hb_k2(data: &[u32], seed: u32) -> u32 {
    let mut a = seed;
    let mut b = seed ^ 0x1234_5678;
    for &x in data {
        a = k2_mix(a ^ x, 5, 13);
        b = k2_mix(b ^ x, 6, 21);
    }
    a ^ b
}

/// K3: walk a table of run descriptors and fill each run (trip 4..=19).
fn hb_k3(dst: &mut [u16], runs: &[u32]) -> u64 {
    let n = dst.len();
    let mut prev = 0usize;
    let mut acc = 0u64;
    for &r in runs {
        let len = 3 + (r & 15) as usize;
        if prev + len >= n {
            prev = 0;
        }
        let end = prev + len;
        acc = acc.wrapping_add(k3_fill_run(dst, prev, end, (r >> 16) as u16) as u64);
        prev = end + 1;
    }
    acc
}

/// K6: two call sites, each with a long inner loop, few calls in total.
fn hb_k6(data: &[u32], seed: u32) -> u32 {
    let half = data.len() / 2;
    let mut h = k6_hot_loop(&data[..half], seed);
    h = k6_hot_loop(&data[half..], h ^ 0x9E37_79B1);
    h
}

/// K7: two guarded call sites of the error path inside one hot loop.
fn hb_k7(data: &[u32], seed: u32) -> u32 {
    let mut acc = seed;
    for &x in data {
        acc = acc.wrapping_add(x).rotate_left(3);
        if x & 0xFF == 0 {
            acc ^= k7_error_path(acc, x);
        }
        if x & 0xFF00 == 0 {
            acc ^= k7_error_path(acc ^ 0x5A5A, x >> 8);
        }
    }
    acc
}

// --- repeat loops --------------------------------------------------------

fn run_k1(data: &[u8], reps: u64) -> u64 {
    let mut acc: u64 = 0;
    for i in 0..reps {
        acc = acc.wrapping_add(hb_k1(black_box(data), i as u32) as u64);
    }
    acc
}

fn run_k2(data: &[u32], reps: u64) -> u64 {
    let mut acc: u64 = 0;
    for i in 0..reps {
        acc = acc.wrapping_add(hb_k2(black_box(data), i as u32) as u64);
    }
    acc
}

fn run_k3(dst: &mut [u16], runs: &[u32], reps: u64) -> u64 {
    let mut acc: u64 = 0;
    for _ in 0..reps {
        acc = acc.wrapping_add(hb_k3(black_box(&mut *dst), black_box(runs)));
    }
    acc
}

fn run_k4(data: &[u8], needle: u8, reps: u64) -> u64 {
    let mut acc: u64 = 0;
    for _ in 0..reps {
        acc = acc
            .wrapping_add(k4_count_bytes(black_box(data), black_box(needle)) as u64);
    }
    acc
}

fn run_k5(data: &[u32], reps: u64) -> u64 {
    let mut acc: u64 = 0;
    for _ in 0..reps {
        acc = acc.wrapping_add(k5_mul_reduce(black_box(data)) as u64);
    }
    acc
}

fn run_k6(data: &[u32], reps: u64) -> u64 {
    let mut acc: u64 = 0;
    for i in 0..reps {
        acc = acc.wrapping_add(hb_k6(black_box(data), i as u32) as u64);
    }
    acc
}

fn run_k7(data: &[u32], reps: u64) -> u64 {
    let mut acc: u64 = 0;
    for i in 0..reps {
        acc = acc.wrapping_add(hb_k7(black_box(data), i as u32) as u64);
    }
    acc
}

fn run_k8(a: &[u32], b: &[u32], out: &mut [u32], reps: u64) -> u64 {
    let mut acc: u64 = 0;
    for _ in 0..reps {
        k8_scale_add(black_box(a), black_box(b), black_box(&mut *out));
        acc = acc.wrapping_add(out[out.len() - 1] as u64);
    }
    acc
}

fn usage() -> ! {
    eprintln!("usage: hintbench <k1|k2|k3|k4|k5|k6|k7|k8|all> [repeats]");
    std::process::exit(2);
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 || args.len() > 3 {
        usage();
    }
    let workload = args[1].as_str();
    // When given, `repeats` overrides the default repeat count of every
    // workload that runs. Left out, each workload uses its own default.
    let override_reps: Option<u64> = match args.get(2) {
        None => None,
        Some(s) => match s.parse() {
            Ok(n) => Some(n),
            Err(_) => usage(),
        },
    };
    let reps = |default: u64| override_reps.unwrap_or(default);

    let all = workload == "all";
    let want = |name: &str| all || workload == name;
    if !(all
        || matches!(workload, "k1" | "k2" | "k3" | "k4" | "k5" | "k6" | "k7" | "k8"))
    {
        usage();
    }

    if want("k1") {
        let n = reps(REP_K1);
        let data = gen_u8(K1_LEN, 0x1111_1111_1111_1111);
        let acc = run_k1(&data, n);
        println!("k1 inline_never  len={K1_LEN} reps={n} checksum=0x{acc:016x}");
    }
    if want("k2") {
        let n = reps(REP_K2);
        let data = gen_u32(K2_LEN, 0x2222_2222_2222_2222);
        let acc = run_k2(&data, n);
        println!("k2 inline        len={K2_LEN} reps={n} checksum=0x{acc:016x}");
    }
    if want("k3") {
        let n = reps(REP_K3);
        let runs = gen_u32(K3_RUNS, 0x3333_3333_3333_3333);
        let mut dst = vec![0u16; K3_LEN];
        let acc = run_k3(&mut dst, &runs, n);
        println!("k3 unroll        len={K3_LEN} reps={n} checksum=0x{acc:016x}");
    }
    if want("k4") {
        let n = reps(REP_K4);
        let data = gen_u8(K4_LEN, 0x4444_4444_4444_4444);
        let acc = run_k4(&data, 0x5a, n);
        println!("k4 vec_width     len={K4_LEN} reps={n} checksum=0x{acc:016x}");
    }
    if want("k5") {
        let n = reps(REP_K5);
        let data = gen_u32(K5_LEN, 0x5555_5555_5555_5555);
        let acc = run_k5(&data, n);
        println!("k5 interleave    len={K5_LEN} reps={n} checksum=0x{acc:016x}");
    }
    if want("k6") {
        let n = reps(REP_K6);
        let data = gen_u32(K6_LEN, 0x6666_6666_6666_6666);
        let acc = run_k6(&data, n);
        println!("k6 align         len={K6_LEN} reps={n} checksum=0x{acc:016x}");
    }
    if want("k7") {
        let n = reps(REP_K7);
        let data = gen_k7(K7_LEN);
        let acc = run_k7(&data, n);
        println!("k7 cold          len={K7_LEN} reps={n} checksum=0x{acc:016x}");
    }
    if want("k8") {
        let n = reps(REP_K8);
        let a = gen_u32(K8_LEN, 0x8888_8888_8888_8888);
        let b = gen_u32(K8_LEN, 0x8888_8888_AAAA_AAAA);
        let mut out = vec![0u32; K8_LEN];
        let acc = run_k8(&a, &b, &mut out, n);
        println!("k8 keep_default  len={K8_LEN} reps={n} checksum=0x{acc:016x}");
    }
}
