# jev-opt results

Records only. Every number below is followed by the command that produced it.
Gate outcomes are recorded as observations, not as conclusions about the
project's viability.

---

## Day 0 (toy)

Date: 2026-09-21. Machine: AMD Ryzen 9 5950X (znver3, no AVX-512), WSL2,
32 logical CPUs. Scope of this day: toolchain pin, gate 0, the toy crate, a
hand-run PGO baseline for the toy, and the remark-mechanism check. No CLI, no
LLVM plugin, no bench harness, no A/A, no headroom sweep, no zopfli.

Reproduce with:

```
scripts/toy_pgo_baseline.sh        # steps 0,a-f and the disqualification filter
scripts/toy_loop_attribution.sh    # per-loop machine-code attribution
```

Both write to `artifacts/toy-day0/` (git-ignored).

### 1. Toolchain

`rust-toolchain.toml` at the repository root pins:

```toml
[toolchain]
channel = "nightly-2026-09-21"
components = ["llvm-tools-preview"]
profile = "minimal"
```

Installed with:

```
$ rustup toolchain install nightly-2026-09-21 --profile minimal -c llvm-tools-preview
  nightly-2026-09-21-x86_64-unknown-linux-gnu installed - rustc 1.100.0-nightly (bba531001 2026-09-20)
```

```
$ rustc -vV            # run inside the repository, so the pin applies
rustc 1.100.0-nightly (bba531001 2026-09-20)
binary: rustc
commit-hash: bba531001d4de6d7f49693e0836a2668ca063282
commit-date: 2026-09-20
host: x86_64-unknown-linux-gnu
release: 1.100.0-nightly
LLVM version: 23.1.1
```

```
$ $(rustc --print sysroot)/lib/rustlib/x86_64-unknown-linux-gnu/bin/llvm-profdata --version
LLVM (http://llvm.org/):
  LLVM version 23.1.1-rust-1.100.0-nightly
  Optimized build.
```

**LLVM is 23.1.1, not 22.x.** SPEC.ja.md 3 recorded stable 1.96.0 / LLVM 22.1.2
and assumed a nightly of the same LLVM major could be pinned; no such nightly is
available today. Consequences recorded rather than resolved:

- The SPEC.ja.md 6.2 hypotheses were formed against LLVM 22.1.2. Section 6 below
  is the re-verification on 23.1.1.
- `llvm-knobs.json` and `remark-reason-map.json` must be regenerated for 23.1.1;
  any knob list taken from 22.x is stale. Section 6 already shows one cl::opt
  that SPEC.ja.md names and 23.1.1 does not have.
- Stable 1.96.0 (LLVM 22.1.2) stays installed, so an A/B across LLVM majors is
  possible later if the difference turns out to matter.
- The two compilers cannot share a `merged.profdata`: the profraw format is tied
  to the LLVM major. Everything in this project uses the pinned nightly's
  `llvm-profdata` only.

`-Zllvm-plugins` acceptance on the pin:

```
$ rustc +nightly-2026-09-21 -Zllvm-plugins=/nonexistent.so --emit=obj -o t.o t.rs
error: failed to run LLVM passes: Could not load library '/nonexistent.so': /nonexistent.so: cannot open shared object file: No such file or directory
error: aborting due to 1 previous error
(exit 1)
```

That is a dlopen failure, not an unknown-flag failure, so the flag is accepted.
Two controls:

```
$ rustc +1.96.0 -Zllvm-plugins=/nonexistent.so --emit=obj -o t.o t.rs
error: the option `Z` is only accepted on the nightly compiler

$ rustc +nightly-2026-09-21 -Zllvm-plugins-bogus=/x --emit=obj -o t2.o t.rs
error: unknown unstable option: `llvm-plugins-bogus`
```

Caveat found while testing: with `--emit=metadata` the same command exits 0 and
loads nothing. The plugin is only dlopen'd when codegen runs, so `jev-opt doctor`
must probe with a codegen-producing `--emit`.

### 2. Gate 0

Run against the **pinned nightly's** sysroot, not stable's.

```
$ S=$(rustc +nightly-2026-09-21 --print sysroot)
$ nm -D $S/lib/librustc_driver-*.so | grep -c '_ZN4llvm11PassBuilder'
15

$ nm -D $S/lib/librustc_driver-*.so | grep -E 'EnableABIBreakingChecks|DisableABIBreakingChecks'
(no output, grep exit 1)

$ nm -D $S/lib/librustc_driver-*.so | grep -c '_ZNSt'
0
```

The file is
`$S/lib/librustc_driver-9d0931a694d885c3.so`.

**This nightly does not statically link LLVM into `librustc_driver`.** That
changes what gate 0 is measuring, so the same three checks were repeated against
the real LLVM host:

```
$ ldd $S/lib/librustc_driver-*.so | grep LLVM
	libLLVM.so.23.1-rust-1.100.0-nightly => .../lib/libLLVM.so.23.1-rust-1.100.0-nightly

$ L=$S/lib/libLLVM.so.23.1-rust-1.100.0-nightly
$ nm -D $L | grep -c '_ZN4llvm11PassBuilder'
63

$ nm -D $L | grep -E 'EnableABIBreakingChecks|DisableABIBreakingChecks'
0000000008a61440 B _ZN4llvm24DisableABIBreakingChecksE@@LLVM_23.1

$ nm -D $L | grep -c '_ZNSt'
1841
```

Records:

| check | librustc_driver | libLLVM.so.23.1 |
|---|---|---|
| `_ZN4llvm11PassBuilder` count | 15 | 63 |
| ABI-breaking-checks symbol | neither defined | `DisableABIBreakingChecks` defined |
| `_ZNSt` count | 0 | 1841 |

Notes for day 3, recorded now, not acted on:

- `DisableABIBreakingChecks` (not `Enable…`) is the defined symbol, i.e. this
  LLVM was built with assertions off. The plugin's ABI macro has to be set to
  match, and it has to resolve against `libLLVM.so`, not `librustc_driver`.
- `_ZNSt` = 1841 means libstdc++ symbols cross the plugin boundary, so the
  plugin must be built against a compatible libstdc++.
- The `[llvm] link-shared = true` rustc source build that SPEC.ja.md 13 lists as
  the gate-0-failure fallback is already the shipped configuration here.

### 3. Toy crate

`targets/toy/` is a two-crate cargo workspace so that every build goes through
the rlib + fat-LTO path the real targets use.

```
targets/toy/Cargo.toml               workspace + [profile.release]
targets/toy/toyloops/Cargo.toml      crate-type = ["rlib"]
targets/toy/toyloops/src/lib.rs      the four loops
targets/toy/toy/Cargo.toml           depends on toyloops
targets/toy/toy/src/main.rs          workload driver
```

`[profile.release]`: `opt-level = 3`, `lto = "fat"`, `codegen-units = 1`,
`debug = 1`, `panic = "unwind"`. These live in the toy's own `Cargo.toml`
because the toy is ours to edit; external targets keep using the
`CARGO_PROFILE_RELEASE_*` mechanism of SPEC.ja.md 3 so their manifests stay
untouched.

The four loops in `toyloops`:

| function | shape | why |
|---|---|---|
| `count_quotes(&[u8]) -> usize` | `iter().filter(..).count()` | byte reduction with a usize/i64 accumulator; the VF 4 -> 32 hypothesis |
| `find_special(&[u8]) -> Option<usize>` | `iter().position(..)` | early-exit scanner; the legality-reason case |
| `sum_indexed(&[u32]) -> u64` | plain `for i in 0..v.len()` | simplest indexed reduction |
| `dot_f64(&[f64], &[f64]) -> f64` | f64 reduction | the zopfli-like shape |

No `#[inline(never)]`, no `#[inline(always)]`, no `#[no_mangle]`, no byte-search
crate, no architecture intrinsics. The toy must not opt out of the inlining
problem it exists to exercise. (All four are in fact inlined into `toy::main`
under fat LTO; see section 6.)

`toy` generates its input from a fixed seed with an inline xorshift64\*, so every
build sees byte-identical data, and prints one checksum line per workload. It
contains no timing code. `toy <quotes|special|sum|dot|all> [repeats]`; without
`repeats` each workload uses a per-workload default tuned to run >= 200 ms.

Per-workload wall time of the plain release build (`date +%s%N` around the run,
so it includes input generation):

```
quotes  396 ms
special 641 ms
sum     295 ms
dot     288 ms
all    1617 ms
```

Checksums (identical for every build made today):

```
$ target-toy-plain/x86_64-unknown-linux-gnu/release/toy all
quotes  len=1048576 reps=1400 checksum=0x000000000262e5d8
special len=1048576 reps=1400 checksum=0x00000000577ffa88
sum     len=1048576 reps=2400 checksum=0x4af984fa85b70860
dot     len=1048576 reps=400 checksum=0x40e3988466029b57
```

Disqualification filter (SPEC.ja.md 6.1-2):

```
$ cd targets/toy && cargo tree -e normal | grep -iE 'memchr|simd|wide|std_detect'
(no match)
$ grep -rlE 'core::arch|_mm_|_mm256|target_feature' targets/toy/*/src
(no match)
```

### 4. PGO baseline (hand-run)

All builds use `--target x86_64-unknown-linux-gnu` explicitly and their own
`CARGO_TARGET_DIR`, and each variant is built from scratch.

Instrumented build:

```
CARGO_TARGET_DIR=target-toy-pgo-gen
CARGO_ENCODED_RUSTFLAGS="-Ctarget-cpu=native \x1f -Csymbol-mangling-version=v0 \x1f -Cprofile-generate=/home/hiro/prj/jev-optimize/pgo/profraw"
cargo build --manifest-path targets/toy/Cargo.toml --release --target x86_64-unknown-linux-gnu
```

Training run (workload `all`, the only training run):

```
$ target-toy-pgo-gen/x86_64-unknown-linux-gnu/release/toy all
training run wall time: 1175 ms
$ ls pgo/profraw
default_2442100662238977579_0.profraw   (2808 bytes)
```

Merge, with the pinned toolchain's `llvm-profdata`:

```
$ /home/hiro/.rustup/toolchains/nightly-2026-09-21-x86_64-unknown-linux-gnu/lib/rustlib/x86_64-unknown-linux-gnu/bin/llvm-profdata merge \
    -o /home/hiro/prj/jev-optimize/pgo/merged.profdata /home/hiro/prj/jev-optimize/pgo/profraw/*.profraw

$ sha256sum pgo/merged.profdata
4a0540999315e8c3a80b1c9c5c8a2937cddca3afdd1df0af7b939f219bf4e887  /home/hiro/prj/jev-optimize/pgo/merged.profdata
```

```
$ llvm-profdata show --all-functions pgo/merged.profdata | tail
Instrumentation level: IR  entry_first = 0  instrument_loop_entries = 0
Functions shown: 13
Total functions: 13
Maximum function count: 1468005000
Maximum internal block count: 2516582400
Total number of blocks: 146
Total count: 7345324484
```

`merged.profdata` is byte-reproducible: a second training run of the same
instrumented binary into a fresh profraw directory merged to the same sha256.

```
$ LLVM_PROFILE_FILE=<tmp>/second_%m_%p.profraw target-toy-pgo-gen/.../toy all
$ llvm-profdata merge -o <tmp>/second.profdata <tmp>/second_*.profraw
$ sha256sum pgo/merged.profdata <tmp>/second.profdata
4a0540999315e8c3a80b1c9c5c8a2937cddca3afdd1df0af7b939f219bf4e887  pgo/merged.profdata
4a0540999315e8c3a80b1c9c5c8a2937cddca3afdd1df0af7b939f219bf4e887  <tmp>/second.profdata
```

PGO baseline build adds, on top of the fixed flags,
`-Cprofile-use=/home/hiro/prj/jev-optimize/pgo/merged.profdata`,
`-Cllvm-args=-pgo-warn-missing-function` and the remark flags of section 6.

`-Cprofile-use` warning counts, from `artifacts/toy-day0/pgo-baseline-build.log`:

```
$ grep -c 'hash mismatch' pgo-baseline-build.log
0
$ grep -c 'no profile data available for function' pgo-baseline-build.log
0
$ grep -c '^warning: ' pgo-baseline-build.log
0
```

Zero, with `-pgo-warn-missing-function` explicitly on. Note what that does and
does not show: only `toyloops` and `toy` are compiled with `-Cprofile-use`
(std arrives precompiled), both were fully exercised by the training run, and
the profdata holds 13 functions. The count is a real zero for the code under
study, not evidence about a large program.

Correctness: the PGO baseline prints the plain release build's checksums.

```
$ diff checksums-plain.txt checksums-pgo.txt
CHECKSUMS: MATCH
```

### 5. `.text` hash, debuginfo 1 vs 0

```
$ objcopy -O binary --only-section=.text target-toy-pgo-use/.../toy /dev/stdout | sha256sum
6e07f5abd338bea952afad8129af54c10b58f6fd917e4c8414b6edc23f594668   (CARGO_PROFILE_RELEASE_DEBUG=1)
$ objcopy -O binary --only-section=.text target-toy-pgo-use-debug0/.../toy /dev/stdout | sha256sum
da42b1ee5f43f459c00095b19af71ea88414e9d3b180fd5015a6bd37b9ab32ce   (CARGO_PROFILE_RELEASE_DEBUG=0)
TEXT HASH: DIFFER
```

They differ, and not only in relocated displacements: the sections are different
sizes and the functions are ordered differently.

```
$ readelf -S <bin> | grep -A1 '\.text'
debug=1: .text ... 00000000000396aa
debug=0: .text ... 00000000000398fa
```

Recorded, not chased. Keeping `debug = 1` as SPEC.ja.md 3 says. Two
consequences:

- SPEC.ja.md 3's plan to "confirm debuginfo does not change `.text` by comparing
  the hash at debuginfo=0/1" does not hold on this toolchain. The equality it
  expected is false here, so it cannot serve as that confirmation.
- The day-3 off-equivalence gate (SPEC.ja.md 8.1, plugin unloaded vs loaded with
  `JEV_MODE=off`) is unaffected, because both sides of that comparison hold
  debuginfo fixed. `.text` hashes must only ever be compared between builds that
  agree on debuginfo.

Checksums are identical between the debug=1 and debug=0 binaries.

### 6. Remark mechanism

Three mechanisms were tried on the pinned nightly with the toy's fat-LTO build.

| mechanism | result |
|---|---|
| `-Cremark=all -Zremark-dir=<dir>` | per-CGU YAML is written, but contains **no** vectorizer remarks under fat LTO |
| `-Cllvm-args=-pass-remarks-output=… -pass-remarks-filter=…` | **the cl::opts do not exist** on LLVM 23.1.1 |
| `-Cllvm-args=-pass-remarks=.* -pass-remarks-missed=.* -pass-remarks-analysis=.*` | **works**: plain-text remarks on stderr, captured from the build log. Chosen. |

Details.

`-Cremark=all -Zremark-dir` writes `<cgu>.opt.opt.yaml`, `<cgu>.lto.opt.yaml`,
`<cgu>.codegen.opt.yaml`. It is not silently broken — it just loses the stage we
need:

```
$ # lto = off
$ grep -rh '^Pass:' <dir>/*.yaml | grep -c loop-vectorize      -> 67 matching lines
$ # lto = fat (the project basis)
$ grep -rh 'loop-vectorize' <dir>/*.yaml                       -> 0
$ ls -la <dir>/toy.*-cgu.0.lto.opt.yaml                        -> 0 bytes
```

So the YAML path carries vectorizer remarks with LTO off, and under fat LTO the
`.lto.opt.yaml` for the merged module comes out empty and every middle-end
remark of that stage is lost. Per-CGU files would have avoided the clobber
problem, which is why this was tried first; it is unusable for the fat-LTO
basis.

SPEC.ja.md 3's recommended mechanism is gone on LLVM 23:

```
$ CARGO_ENCODED_RUSTFLAGS='…-Cllvm-args=-pass-remarks-output=…' cargo build …
rustc -Cllvm-args="..." with: Unknown command line argument '-pass-remarks-output=…'.
rustc -Cllvm-args="..." with: Did you mean '--lto-pass-remarks-output=…'?
rustc -Cllvm-args="..." with: Unknown command line argument '-pass-remarks-filter=.*'.
```

`--lto-pass-remarks-output` is accepted but writes nothing (rustc does not go
through the legacy LTO code generator). `rustc -Cllvm-args=--help-list-hidden`
on 23.1.1 lists only `--pass-remarks`, `--pass-remarks-missed`,
`--pass-remarks-analysis` and the `--lto-pass-remarks-*` family.

Chosen mechanism, in the PGO baseline build:

```
-Cllvm-args=-pass-remarks=.*
-Cllvm-args=-pass-remarks-missed=.*
-Cllvm-args=-pass-remarks-analysis=.*
```

24484 remark lines in `artifacts/toy-day0/pgo-baseline-build.log`. The process-global
clobber problem of SPEC.ja.md 3 does not arise, since nothing is written to a
file; both rustc processes append to the same captured stream.

**The trade-off this mechanism carries.** The text remarks give a DebugLoc but
no function name and no structured fields, and the YAML (which does have a
`Function` field) is exactly the thing that is empty under fat LTO. After
inlining, the DebugLoc of `bytes.iter()…` points into
`library/core/src/slice/iter/macros.rs`, where std's own loops also live, so the
remark text alone cannot say which loop is which. This directly affects
SPEC.ja.md 7, which plans to map `DebugLoc -> function name` from the remark
YAML. Day 0 works around it by attributing machine code instead
(`scripts/toy_loop_attribution.sh`: walk every instruction of `toy::main`,
resolve the full inline chain with `addr2line -i -f -p`, bucket by the toyloops
function the chain names). Stage 2's plugin dump will not need this, since it
reads the IR directly.

#### Per-loop findings on the PGO baseline (real-toolchain check of SPEC.ja.md 6.2)

All four functions are inlined into `toy::main`:

```
remark: toy/src/main.rs:97:32: '…toyloops12count_quotes' inlined into '…3toy4main' with (cost=-14995, threshold=525)
remark: toy/src/main.rs:105:21: '…toyloops12find_special' inlined into '…3toy4main' with (cost=-14965, threshold=525)
```

| loop | vectorized | VF / IC | evidence |
|---|---|---|---|
| `count_quotes` | yes | VF 4, IC 4 | remark + machine code |
| `find_special` | no | - | legality |
| `sum_indexed` | yes | VF 4, IC 4 | remark + machine code |
| `dot_f64` | no (loop vectorizer); SLP vectorized the multiply | - | legality (FP ordering) |

**`count_quotes`: vectorized, VF 4, IC 4. The SPEC.ja.md 6.2 hypothesis holds on
LLVM 23.1.1.**

```
remark: library/core/src/slice/iter/macros.rs:279:24: vectorized loop (vectorization width: 4, interleaved count: 4)
```

Machine code confirms which loop that remark belongs to and what VF 4 costs
here: four `vmovd` loads at offsets 0/4/8/0xc, five `vpcmpeqb`, five
`vpmovzxbq %xmm,%ymm`, and four independent `ymm` accumulators combined with
`vpaddq`. The accumulator is i64, so each 256-bit register holds four lanes and
the loop consumes 16 bytes per iteration instead of the 32 a byte-width
accumulator would allow. That 8x-per-register gap is the headroom the
`vectorize.width=32` / `-vectorizer-maximize-bandwidth` hint is aimed at, and it
is still there on 23.1.1.

**`find_special`: not vectorized, legality. The SPEC.ja.md 6.2 hypothesis
holds.**

```
remark: toyloops/src/lib.rs:26:32: loop not vectorized: Incorrect number of successors from early exiting block
remark: toyloops/src/lib.rs:26:32: loop not vectorized: Loop contains an unsupported switch
remark: toyloops/src/lib.rs:26:32: loop not vectorized
```

Machine code: 15 instructions, zero vector registers — a scalar
`movzbl`/`cmp`/`je` byte loop. Both reason strings classify as `legality`
in the future `remark-reason-map.json`, i.e. out of reach of loop metadata.
Note the reason strings differ from the wording SPEC.ja.md 6.2 quotes
("unsupported switch" survives; "early exiting block" now reads "Incorrect
number of successors from early exiting block"), which is why the reason map has
to be rebuilt per LLVM major.

**`sum_indexed`: vectorized, VF 4, IC 4.**

```
remark: library/core/src/iter/range.rs:1103:12: vectorized loop (vectorization width: 4, interleaved count: 4)
```

Machine code: four `vpxor`-zeroed `ymm` accumulators, `vpmovzxdq` at offsets
0/0x10/0x20/0x30, `vpaddq`. 16 u32 per iteration. Same u32 -> u64 widening
story as `count_quotes`, one step milder.

**`dot_f64`: loop vectorizer refused on FP-ordering legality; SLP vectorized the
multiply and kept the reduction ordered.**

```
remark: toyloops/src/lib.rs:50:9: loop not vectorized: cannot prove it is safe to reorder floating-point operations
remark: toyloops/src/lib.rs:50:9: Vectorizing ordered reduction is possible but not beneficial with cost 52954200 and threshold 0
remark: toyloops/src/lib.rs:50:9: Vectorized horizontal reduction with cost -529542000 and with tree size 3
```

Machine code: two `vmulpd …,%ymm` (8 doubles per iteration) feeding a strictly
ordered `vaddsd` chain, with `vextractf128` / `vshufpd` doing the horizontal
extraction. So the multiplies are vectorized and the reduction is not. This is a
reason no hint in the five families can lift: `vectorize.width` does not grant
reassociation. It is a useful warning for the zopfli f64-reduction case of
SPEC.ja.md 6.2, which was expected to be in range of width/interleave/unroll
hints and may not be.

Seeds for `remark-reason-map.json` (LLVM 23.1.1 only):

| remark string | class |
|---|---|
| `Incorrect number of successors from early exiting block` | legality |
| `Loop contains an unsupported switch` | legality |
| `cannot prove it is safe to reorder floating-point operations` | legality |
| `Cannot vectorize early exit loop` | legality |
| `could not determine number of loop iterations` | unsupported |
| `call instruction cannot be vectorized` | unsupported |
| `value that could not be identified as reduction is used outside the loop` | unsupported |
| `Control flow cannot be substituted for a select` | unsupported |
| `loop induction variable could not be identified` | unsupported |

Not a finished map: these are the strings that actually appeared in this build
log, classified by hand. Anything not listed must stay `unknown`.

### 7. Open notes

- **`RUSTUP_TOOLCHAIN`.** `rust-toolchain.toml` only governs directories under
  this repository, and the toy lives inside it, so the toy is covered. The CLI
  will drive zopfli and jaq in *other* directories, where those projects' own
  `rust-toolchain.toml` (or the user default) would win. `jev-opt` must set
  `RUSTUP_TOOLCHAIN=nightly-2026-09-21` explicitly in the environment of every
  cargo and rustc it spawns, and record the resolved `rustc -vV` in
  `run-manifest.json` rather than trusting the pin.
- **LLVM is 23.1.1, not 22.x** (section 1). Everything SPEC.ja.md says about
  LLVM internals is a 22.1.2 observation and has to be re-checked; section 6 is
  the first instance where it did not survive.
- **The remark YAML is empty for the fat-LTO stage** (section 6). Worth a
  narrowed reproduction and an upstream report later; for now the text remarks
  are the mechanism. This also means remark hotness
  (`-lto-pass-remarks-with-hotness`) is not available to us.
- **Remarks carry no function name** under the chosen mechanism (section 6),
  which SPEC.ja.md 7's Stage 1 input selection assumes. Either Stage 1 accepts
  file:line granularity, or it uses the machine-code attribution of
  `scripts/toy_loop_attribution.sh`, or Stage 1 waits for the plugin dump.
- **`.text` is not debuginfo-invariant** on this toolchain (section 5).
- **Gate 0 has to be read against `libLLVM.so`, not `librustc_driver`**
  (section 2). Both records are kept above.
- Nothing was measured for speed today. The toy is pipeline verification only
  and carries no performance claim (SPEC.ja.md 6.4).
