//! Driver for the toy loops.
//!
//! Usage: `toy <quotes|special|sum|dot|all> [repeats]`
//!
//! Inputs are generated from a fixed seed with a tiny xorshift, so every build
//! of this binary sees byte-identical data. The program prints a checksum per
//! workload and nothing else; correctness across builds (no-PGO release vs PGO
//! baseline vs, later, jev-hinted builds) is "the checksums match".
//!
//! There is no timing code here on purpose. Timing is done from the outside so
//! that the measured binary contains only the loops under study.

use std::hint::black_box;
use toyloops::{count_quotes, dot_f64, find_special, sum_indexed};

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

const BYTES_LEN: usize = 1 << 20;
const U32_LEN: usize = 1 << 20;
const F64_LEN: usize = 1 << 20;

/// Per-workload repeat counts, tuned so each workload runs for at least
/// 200 ms in a release build on the reference machine (Ryzen 9 5950X).
const REP_QUOTES: u64 = 1400;
const REP_SPECIAL: u64 = 1400;
const REP_SUM: u64 = 2400;
const REP_DOT: u64 = 400;

/// Printable bytes with quotes sprinkled in, for the counting loop.
fn gen_quote_bytes(len: usize) -> Vec<u8> {
    let mut rng = Rng::new(SEED);
    let mut out = Vec::with_capacity(len);
    for _ in 0..len {
        let r = rng.next_u64();
        // Roughly one quote every 64 bytes.
        if r % 64 == 0 {
            out.push(b'"');
        } else {
            out.push(0x20 + (r >> 8) as u8 % 0x5f);
        }
    }
    out
}

/// Bytes with no special character except a single one in the last position,
/// so the early-exit scanner always walks the whole buffer.
fn gen_scan_bytes(len: usize) -> Vec<u8> {
    let mut rng = Rng::new(SEED ^ 0x5851_F42D_4C95_7F2D);
    let mut out = Vec::with_capacity(len);
    for _ in 0..len {
        let mut c = 0x20 + (rng.next_u64() >> 8) as u8 % 0x5f;
        if c == b'"' || c == b'\\' {
            c = b'.';
        }
        out.push(c);
    }
    if len > 0 {
        out[len - 1] = b'"';
    }
    out
}

fn gen_u32(len: usize) -> Vec<u32> {
    let mut rng = Rng::new(SEED ^ 0x1234_5678_9ABC_DEF0);
    (0..len).map(|_| (rng.next_u64() >> 32) as u32).collect()
}

fn gen_f64(len: usize, salt: u64) -> Vec<f64> {
    let mut rng = Rng::new(SEED ^ salt);
    // Values in [-1, 1), exactly representable steps, so the sum stays tame.
    (0..len)
        .map(|_| ((rng.next_u64() >> 11) as f64 / (1u64 << 53) as f64) * 2.0 - 1.0)
        .collect()
}

fn run_quotes(data: &[u8], reps: u64) -> u64 {
    let mut acc: u64 = 0;
    for _ in 0..reps {
        acc = acc.wrapping_add(count_quotes(black_box(data)) as u64);
    }
    acc
}

fn run_special(data: &[u8], reps: u64) -> u64 {
    let mut acc: u64 = 0;
    for _ in 0..reps {
        let found = find_special(black_box(data));
        acc = acc.wrapping_add(found.map_or(u64::MAX, |i| i as u64));
    }
    acc
}

fn run_sum(data: &[u32], reps: u64) -> u64 {
    let mut acc: u64 = 0;
    for _ in 0..reps {
        acc = acc.wrapping_add(sum_indexed(black_box(data)));
    }
    acc
}

fn run_dot(a: &[f64], b: &[f64], reps: u64) -> f64 {
    let mut acc: f64 = 0.0;
    for _ in 0..reps {
        acc += dot_f64(black_box(a), black_box(b));
    }
    acc
}

fn usage() -> ! {
    eprintln!("usage: toy <quotes|special|sum|dot|all> [repeats]");
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

    let want_quotes = matches!(workload, "quotes" | "all");
    let want_special = matches!(workload, "special" | "all");
    let want_sum = matches!(workload, "sum" | "all");
    let want_dot = matches!(workload, "dot" | "all");
    if !(want_quotes || want_special || want_sum || want_dot) {
        usage();
    }

    if want_quotes {
        let n = reps(REP_QUOTES);
        let data = gen_quote_bytes(BYTES_LEN);
        let acc = run_quotes(&data, n);
        println!("quotes  len={BYTES_LEN} reps={n} checksum=0x{acc:016x}");
    }
    if want_special {
        let n = reps(REP_SPECIAL);
        let data = gen_scan_bytes(BYTES_LEN);
        let acc = run_special(&data, n);
        println!("special len={BYTES_LEN} reps={n} checksum=0x{acc:016x}");
    }
    if want_sum {
        let n = reps(REP_SUM);
        let data = gen_u32(U32_LEN);
        let acc = run_sum(&data, n);
        println!("sum     len={U32_LEN} reps={n} checksum=0x{acc:016x}");
    }
    if want_dot {
        let n = reps(REP_DOT);
        let a = gen_f64(F64_LEN, 0xA5A5_A5A5_A5A5_A5A5);
        let b = gen_f64(F64_LEN, 0x5A5A_5A5A_5A5A_5A5A);
        let acc = run_dot(&a, &b, n);
        // Print the bit pattern: any reassociation of the reduction shows up.
        println!("dot     len={F64_LEN} reps={n} checksum=0x{:016x}", acc.to_bits());
    }
}
