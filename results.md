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

---

## Day 0 (toy) --- noise floor and headroom

Date: 2026-09-21, same machine and same pinned toolchain as the section above
(rustc 1.100.0-nightly bba531001 / LLVM 23.1.1). This section covers
SPEC.ja.md 13 day-0 item 5 for the toy: the A/A noise floor, the minimum
detectable effect, the LLVM 23.1.1 knob list, and the group 0-3 headroom
sweep. Group 4 (znver3 `-Ctarget-feature` / `-Ctarget-cpu=x86-64-v3`) was not
run. **The toy carries no performance claim (SPEC.ja.md 6.4); everything here
is a record that the procedure runs and what it produced.**

Reproduce with:

```
scripts/gen_llvm_knobs.sh          # llvm-knobs.json from the pinned toolchain
scripts/toy_aa.sh 30 5             # A/A, 30 rounds, warmup 5
scripts/toy_headroom.sh            # 30 builds, remark diff, then timing
scripts/toy_loop_attribution.sh <binary>
```

`scripts/bench.py` is the timing harness (`run` and `stats`);
`scripts/toy_common.sh` holds the shared PGO-baseline build recipe. Outputs go
to `artifacts/toy-aa/` and `artifacts/toy-headroom/` (git-ignored), build logs
to `remarks/toy/` (git-ignored). Every number below is therefore repeated here
in full.

### 8. Paths: the day-0 artifacts are now target-scoped

`pgo/merged.profdata` and `pgo/profraw/` moved to `pgo/toy/`, and
`remarks/` to `remarks/toy/`, as SPEC.ja.md 3 and 11 spell them
(`pgo/<target>/`, `remarks/<target>/`). `scripts/toy_pgo_baseline.sh` takes
`TARGET` (default `toy`) and `REUSE_PROFDATA` (default 1) for this.

```
$ sha256sum pgo/toy/merged.profdata
4a0540999315e8c3a80b1c9c5c8a2937cddca3afdd1df0af7b939f219bf4e887
```

Unchanged from section 4, so this is the same profdata that every arm and
every sweep configuration below uses. **The training run was not repeated.**

The PGO baseline was rebuilt from scratch by `scripts/toy_aa.sh` and came out
bit-identical in `.text` to the one section 5 recorded, which is the build
determinism that the whole sweep rests on:

```
$ objcopy -O binary --only-section=.text target-toy-aa/.../toy /dev/stdout | sha256sum
6e07f5abd338bea952afad8129af54c10b58f6fd917e4c8414b6edc23f594668
```

### 9. Pinning and topology

```
$ lscpu -e | head -4
CPU NODE SOCKET CORE L1d:L1i:L2:L3 ONLINE
  0    0      0    0 0:0:0:0          yes
  1    0      0    0 0:0:0:0          yes
  2    0      0    1 1:1:1:0          yes
$ cat /sys/devices/system/cpu/cpu0/cache/index3/shared_cpu_list
0-31
$ cat /sys/devices/system/cpu/cpu2/topology/thread_siblings_list
2-3
$ cat /proc/sys/kernel/randomize_va_space
2
```

**The CCD boundary is not observable from inside WSL2.** `lscpu -e` reports a
single L3 instance shared by all 32 CPUs; the 5950X physically has two CCDs
with 32 MiB of L3 each, and the guest does not see the split (nor is the
vCPU -> host-core mapping guaranteed). So SPEC.ja.md 10's "pin to a physical
core inside a single CCD" can only be satisfied in its one-core part:

- measurements run `taskset -c 2`, i.e. core 1, a single physical core;
- its SMT sibling CPU 3 is left unused;
- "single CCD" holds trivially (one core cannot straddle two) but **cannot be
  verified** from the guest.

ASLR is left on (`randomize_va_space=2`), configuration order is round-robin
interleaved, and no build ran while timing ran.

### 10. A/A noise floor and the minimum detectable effect

The PGO baseline binary is built once, copied to two labels A1 and A2, and
both copies are stripped (SPEC.ja.md 3 evaluates stripped binaries). The two
files are byte-identical:

```
$ sha256sum artifacts/toy-aa/A1 artifacts/toy-aa/A2
de7f41495553ea56e45f893f1266019d939e3ae688eaf3630b2530185a5dfcad  A1
de7f41495553ea56e45f893f1266019d939e3ae688eaf3630b2530185a5dfcad  A2
```

```
$ scripts/toy_aa.sh 30 5
# = scripts/bench.py run --cpu 2 --warmup 5 --runs 30 \
#       --label A1=artifacts/toy-aa/A1 --label A2=artifacts/toy-aa/A2 \
#       --workload quotes --workload special --workload sum --workload dot \
#       --out artifacts/toy-aa/aa.json
#   scripts/bench.py stats artifacts/toy-aa/aa.json --base A1 \
#       --seed 20260921 --resamples 10000
```

hyperfine is not installed on this machine, and it cannot interleave several
binaries round-robin in any case, so `scripts/bench.py` is the harness:
`taskset -c 2 <bin> <workload>`, wall time from `time.perf_counter_ns` around
`subprocess.run`, stdout captured (and compared across labels). A *round* runs
every workload for every label before the next round starts and rotates the
label order, so the round is the pairing unit for the bootstrap.

240 timed samples (2 labels x 4 workloads x 30 rounds), warmup 5 rounds:

| workload | A1 mean ms | A1 median ms | A1 min ms | A2 mean ms | A2 median ms | A2 min ms | ratio A1/A2 | 95% CI | half-width |
|---|---|---|---|---|---|---|---|---|---|
| quotes | 116.6 | 116.6 | 115.6 | 116.8 | 116.8 | 115.8 | 0.9979 | [0.9954, 1.0003] | 0.24% |
| special | 622.0 | 621.4 | 617.7 | 621.9 | 621.3 | 617.4 | 1.0003 | [0.9985, 1.0021] | 0.18% |
| sum | 110.0 | 108.8 | 106.8 | 109.9 | 109.6 | 106.7 | 1.0011 | [0.9890, 1.0134] | 1.22% |
| dot | 276.2 | 276.0 | 272.8 | 276.7 | 276.1 | 274.1 | 0.9981 | [0.9955, 1.0010] | 0.27% |
| **aggregate (geomean)** | | | | | | | 0.9993 | [0.9960, 1.0028] | 0.34% |

Speed ratio is `t_A1 / t_A2`; > 1 means A2 is faster. The CI is a paired
bootstrap over round indices, resampled jointly across workloads, 10000
resamples, seed 20260921.

**Noise floor = the CI half-width: 0.24% (quotes), 0.18% (special), 1.22%
(sum), 0.27% (dot); 0.34% on the aggregate. Worst per-workload half-width
1.22%.**

**MDE = max(2 x 1.22%, 3%) = 3.00%.** The 3% floor binds; the machine is
quieter than the floor. `sum` is the noisiest workload by a factor of ~5 and
is also the shortest (110 ms) --- worth knowing before zopfli's cases are
chosen.

Two independent corroborations of this noise floor fell out of the sweep
below: `g1-tailfold-prefer` and `g3-loop-distribute` both produce a `.text`
section bit-identical to the baseline's (so they are A/A pairs in disguise)
and measured 1.0020 [0.9991, 1.0050] and 1.0015 [0.9978, 1.0049] against it.

### 11. `llvm-knobs.json` and the SPEC.ja.md 6.3 matrix on LLVM 23.1.1

```
$ scripts/gen_llvm_knobs.sh
/home/hiro/prj/jev-optimize/llvm-knobs.json: 2689 options, rustc 1.100.0-nightly, LLVM 23.1.1
# = echo 'fn main(){}' | rustc -Cllvm-args=--help-list-hidden - -o /dev/null
```

2693 option lines are printed; 4 are not captured because they use an
optional-argument spelling the parser does not handle
(`amdgpu-use-native[`, `basic-block-sections`, `enable-origin-stacktraces[`,
`nvvm-reflect-add`). None of them is in the matrix.

**The generator must be run inside the repository.** Run from `/tmp` it picks
up the user default toolchain (stable 1.96.0 / LLVM 22.1.2) and prints a
*different* option list --- that mistake was made once while writing this
section and is exactly the trap SPEC.ja.md 4 warns about.

Defaults: LLVM's `--print-all-options` and `--print-options` exist as cl::opts
on 23.1.1 but print nothing through rustc's `-Cllvm-args` path (tried with and
without a non-default option set, with `--emit=obj`). So `llvm-knobs.json`
carries `default_doc`, the default as stated in the help text, and the
operative definition of "default" for this sweep is *the flag is not passed*.

| SPEC.ja.md 6.3 knob | exists on 23.1.1 | documented default | swept values |
|---|---|---|---|
| `-align-all-nofallthru-blocks` | yes, `<uint>` | not stated | 5 |
| `-vectorizer-maximize-bandwidth` | yes, bool | not stated (off) | on |
| `-force-vector-width` | yes, `<ElementCount>` | "Zero is autoselect" | 8, 16, 32 |
| `-force-vector-interleave` | yes, `<uint>` | "Zero is autoselect" | 1, 2, 4 |
| `-prefer-predicate-over-epilogue` | **NO --- does not exist** | --- | dropped |
| `-runtime-memory-check-threshold` | yes, `<uint>` | 8 | 24, 128 |
| `-enable-early-exit-vectorization` | yes, bool | not stated; **measured on** (below) | on (a no-op) |
| `-inline-threshold` | yes, `<int>` | 225 | 325, 500, 1000 |
| `-unroll-threshold` | yes, `<uint>` | not stated | 300, 1000 |
| `-unroll-max-count` | yes, `<uint>` | not stated | 2, 8 |
| `-unroll-runtime` | yes, bool | not stated | on |
| `-enable-loop-distribute` | yes, bool | not stated | on |
| `-slp-threshold` | yes, `<int>` | not stated | -20, 100 |
| `-unswitch-threshold` | yes, `<int>` | not stated | 200 |
| `-enable-loop-flatten` | yes, bool | not stated | on |
| `-enable-gvn-hoist` | yes, bool | off | on |

**One knob of the matrix does not exist on LLVM 23.1.1:
`-prefer-predicate-over-epilogue`.** Its 23.1.1 replacements were swept in its
place, both confirmed present:

```
$ grep -A4 -E '^  --(epilogue-tail-folding-policy|force-tail-folding-style)=' <help output>
  --epilogue-tail-folding-policy=<value>  - Epilogue-tail-folding preferences over creating an epilogue loop.
    =dont-fold-tail                       -   Don't tail-fold loops.
    =prefer-fold-tail                     -   prefer tail-folding, otherwise create an epilogue when appropriate.
  --force-tail-folding-style=<value>      - Force the tail folding style
    =none / =data / =data-without-lane-mask / =data-and-control / =data-with-evl
```

Swept as `-epilogue-tail-folding-policy=prefer-fold-tail`,
`-force-tail-folding-style=data` and `=data-and-control`.

### 12. Headroom sweep: 30 builds, remark diff first

```
$ scripts/toy_headroom.sh
```

29 configurations plus the baseline. Every one is the PGO baseline recipe of
SPEC.ja.md 3 --- same `-Cprofile-use=pgo/toy/merged.profdata`, same
`-Ctarget-cpu=native -Csymbol-mangling-version=v0`, same
`CARGO_PROFILE_RELEASE_{OPT_LEVEL=3,LTO=fat,CODEGEN_UNITS=1,DEBUG=1,PANIC=unwind}`,
same three `-pass-remarks*` flags, explicit
`--target x86_64-unknown-linux-gnu`, its own `CARGO_TARGET_DIR`, clean build
--- plus the knob(s) of that configuration as extra `-Cllvm-args`. Build time
2.8-4.7 s per configuration (the `-inline-threshold` ones are the slow end),
2 m 11 s of wall time for all 30. No configuration failed to build.

Primary read is the remark diff (SPEC.ja.md 6.3): `grep '^remark: '` on the
build log, `sort -u`, `comm` against the baseline's. Two normalizations
matter and are recorded separately:

- the line **order** is not deterministic (two rustc processes interleave on
  one stderr) but the **set** is, so everything is sorted first;
- the cost-model numbers inside remarks (`(cost=-14995, threshold=525)`,
  `with cost N and threshold N`, `tree size N`) are masked before comparing,
  otherwise every `-inline-threshold` configuration "differs" on arithmetic
  that carries no decision. Vectorization width, interleave count and
  `file:line:col` are **not** masked --- those are the decision.

`.text` hashes are recorded too, and they turn out to be the sharper
criterion: a configuration whose `.text` is bit-identical to the baseline's
cannot differ in time, whatever its remarks say.

| config | knobs | checksums | .text vs base | remark lines +/- | toy-loop decision changed | timed? |
|---|---|---|---|---|---|---|
| g0-align5 | `-align-all-nofallthru-blocks=5` | MATCH | differ | +0 / -0 | no | yes |
| g1-maxbw | `-vectorizer-maximize-bandwidth` | MATCH | differ | +5 / -3 | YES | yes |
| g1-vw8 | `-force-vector-width=8` | MISMATCH | differ | +8 / -17 | YES | yes |
| g1-vw16 | `-force-vector-width=16` | MISMATCH | differ | +10 / -18 | YES | yes |
| g1-vw32 | `-force-vector-width=32` | MISMATCH | differ | +13 / -19 | YES | yes |
| g1-maxbw-vw32 | `-vectorizer-maximize-bandwidth -force-vector-width=32` | MISMATCH | differ | +13 / -19 | YES | yes |
| g1-ic1 | `-force-vector-interleave=1` | MATCH | differ | +15 / -15 | YES | yes |
| g1-ic2 | `-force-vector-interleave=2` | MATCH | differ | +15 / -20 | YES | yes |
| g1-ic4 | `-force-vector-interleave=4` | MATCH | differ | +17 / -19 | YES | yes |
| g1-tailfold-prefer | `-epilogue-tail-folding-policy=prefer-fold-tail` | MATCH | same | +8 / -0 | YES | yes |
| g1-tfstyle-data | `-force-tail-folding-style=data` | MATCH | differ | +0 / -0 | no | yes |
| g1-tfstyle-data-and-control | `-force-tail-folding-style=data-and-control` | MATCH | differ | +0 / -1 | no | yes |
| g1-memcheck24 | `-runtime-memory-check-threshold=24` | MATCH | same | +0 / -0 | no | skipped (identical) |
| g1-memcheck128 | `-runtime-memory-check-threshold=128` | MATCH | same | +0 / -0 | no | skipped (identical) |
| g1-earlyexit | `-enable-early-exit-vectorization` | MATCH | same | +0 / -0 | no | skipped (identical) |
| g2-inline325 | `-inline-threshold=325` | MATCH | differ | +524 / -308 | no | yes |
| g2-inline500 | `-inline-threshold=500` | MATCH | differ | +1076 / -607 | no | yes |
| g2-inline1000 | `-inline-threshold=1000` | MATCH | differ | +1370 / -863 | YES | yes |
| g2-unroll-thr300 | `-unroll-threshold=300` | MATCH | differ | +11 / -1 | no | yes |
| g2-unroll-thr1000 | `-unroll-threshold=1000` | MATCH | differ | +11 / -1 | no | yes |
| g2-unroll-max2 | `-unroll-max-count=2` | MATCH | differ | +14 / -15 | YES | yes |
| g2-unroll-max8 | `-unroll-max-count=8` | MATCH | same | +0 / -0 | no | skipped (identical) |
| g2-unroll-runtime | `-unroll-runtime` | MATCH | differ | +4 / -0 | no | yes |
| g3-loop-distribute | `-enable-loop-distribute` | MATCH | same | +255 / -0 | YES | yes |
| g3-slp-neg20 | `-slp-threshold=-20` | MATCH | differ | +435 / -122 | YES | yes |
| g3-slp-100 | `-slp-threshold=100` | MATCH | differ | +122 / -128 | YES | yes |
| g3-unswitch200 | `-unswitch-threshold=200` | MATCH | same | +0 / -0 | no | skipped (identical) |
| g3-loop-flatten | `-enable-loop-flatten` | MATCH | same | +0 / -0 | no | skipped (identical) |
| g3-gvn-hoist | `-enable-gvn-hoist` | MATCH | differ | +1 / -1 | no | yes |

Timing was run for the baseline, for group 0, and for every configuration
whose normalized remarks or whose `.text` changed: 24 labels.
**Six configurations were skipped: `g1-memcheck24`, `g1-memcheck128`,
`g1-earlyexit`, `g2-unroll-max8`, `g3-unswitch200`, `g3-loop-flatten`.** All
six produced zero remark-set difference *and* a `.text` section bit-identical
to the baseline's, i.e. the same machine code, so there was nothing to time.
`-enable-early-exit-vectorization` producing literally no change is itself a
result, and a follow-up probe says why: **it is already on by default on LLVM
23.1.1.**

```
$ source scripts/toy_common.sh
$ build_variant target-toy-eeprobe /tmp/eeprobe.log '-enable-early-exit-vectorization=false'
$ text_hash target-toy-eeprobe/x86_64-unknown-linux-gnu/release/toy
6e07f5abd338bea952afad8129af54c10b58f6fd917e4c8414b6edc23f594668   # == baseline
$ comm -13 <baseline remarks> <=false remarks> | wc -l   ->  9
$ comm -23 <baseline remarks> <=false remarks> | wc -l   -> 18
$ grep -c 'uncountable early exit is not enabled' remarks/toy/baseline-build.log
0
```

Turning the knob **off** changes 27 analysis remark lines (the baseline log
already carries 161 `early exit loop` analysis remarks without the flag);
turning it **on** changes nothing at all. The default is therefore on, and the
PGO baseline already has early-exit vectorization enabled. Neither direction
changes a byte of `.text`: `find_special` is refused earlier, on "Incorrect
number of successors from early exiting block", before the enable flag would
matter.

Two configurations changed remarks but not `.text`
(`g1-tailfold-prefer` +8 remark lines, `g3-loop-distribute` +255) and were
timed anyway; they served as the in-sweep A/A controls quoted in section 10.

### 13. Correctness

`<binary> all` was run for all 30 builds and compared to the baseline's
checksum block.

```
$ diff artifacts/toy-headroom/remarks/baseline.checksums artifacts/toy-headroom/remarks/<config>.checksums
```

**25 of 29 configurations match the baseline exactly. Four do not, and they
are all `-force-vector-width`:**

```
$ diff baseline.checksums g1-vw8.checksums
4c4
< dot     len=1048576 reps=400 checksum=0x40e3988466029b57
---
> dot     len=1048576 reps=400 checksum=0x40e39884660299c9
```

| config | quotes | special | sum | dot |
|---|---|---|---|---|
| g1-vw8 | match | match | match | **0x40e39884660299c9** (base 0x40e3988466029b57) |
| g1-vw16 | match | match | match | **0x40e39884660299c9** |
| g1-vw32 | match | match | match | **0x40e3988466029b03** |
| g1-maxbw-vw32 | match | match | match | **0x40e3988466029b03** |

This is a real semantic change, not a rounding curiosity of the harness. On
the baseline the `dot_f64` loop is refused by the loop vectorizer on legality
grounds and the reduction stays an ordered `vaddsd` chain (section 6). Under
`-force-vector-width` that remark disappears and the reduction is vectorized:

```
$ comm -23 baseline.norm g1-vw32.norm | grep 'lib.rs:50'
remark: toyloops/src/lib.rs:50:9: Vectorized horizontal reduction with cost C and with tree size S
remark: toyloops/src/lib.rs:50:9: Vectorizing ordered reduction is possible but not beneficial with cost C and threshold T
remark: toyloops/src/lib.rs:50:9: loop not vectorized: cannot prove it is safe to reorder floating-point operations
$ scripts/toy_loop_attribution.sh artifacts/toy-headroom/bin/baseline   | sed -n '/### dot_f64/,/^$/p'
### dot_f64: 44 instructions, 21 use vector registers
    mnemonics: vaddsdx9, ..., vmulpdx2, ...
$ scripts/toy_loop_attribution.sh artifacts/toy-headroom/bin/g1-vw32    | sed -n '/### dot_f64/,/^$/p'
### dot_f64: 136 instructions, 103 use vector registers
    mnemonics: vaddsdx35, ..., vmulpdx8, vaddpdx8, ...
```

Eight `vaddpd %ymm` appear where the baseline had none: the floating-point
reduction was reassociated. **Forcing a vectorization width makes LLVM treat
the loop as explicitly requested for vectorization, which lifts the
FP-reordering legality bail that SPEC.ja.md 6.2 observed.** The `dot`
workload's +260% "speedup" for these four configurations (section 14) is
therefore a different computation, not a faster one, and those configurations
are disqualified on correctness before any timing is read.

`-vectorizer-maximize-bandwidth` alone does **not** have this effect: its
checksums match on all four workloads.

**This is not obviously confined to the global knob.** In LLVM the width hint
that `-force-vector-width` sets and the width hint that
`llvm.loop.vectorize.width` metadata sets feed the same
`LoopVectorizeHints`, and it is that hint's presence that makes the
vectorizer treat the loop as explicitly requested and allow the reordering.
If that is also true of the metadata form, then the Stage 2 H01 family
(`vectorize.width`) --- the plugin's headline hint --- can change FP results
on any site with a floating-point reduction. **This has not been measured:
the metadata path needs the plugin, which does not exist yet.** It is
recorded here as the thing to test first, because two statements in
SPEC.ja.md rest on it being false:

- SPEC.ja.md 6.2: "`vectorize.width` は FP の再結合を許可しない" --- already
  false for the global knob, unknown for the metadata.
- SPEC.ja.md 8.4: "合法性は LoopVectorize の legality 解析がそのまま守るので、
  ヒントは意味の主張を捏造しない" --- the same assumption.

Concretely, day 3 item 13 (the hard-coded `vectorize.width=8` apply test)
should be run on `dot_f64` specifically and its checksum compared, and until
that comes back clean nothing in the pipeline would catch a plan that changes
a user's output.

### 14. Timing: 24 configurations, interleaved

```
$ scripts/bench.py run --cpu 2 --warmup 3 --runs 10 \
      --label baseline=artifacts/toy-headroom/strip/baseline ... (24 labels) \
      --workload quotes --workload special --workload sum --workload dot \
      --out artifacts/toy-headroom/headroom.json
$ scripts/bench.py stats artifacts/toy-headroom/headroom.json --base baseline \
      --seed 20260921 --resamples 10000 --mde 0.03
```

960 timed samples (24 labels x 4 workloads x 10 rounds), warmup 3 rounds, one
single invocation so all 24 are genuinely round-robin against the same
baseline rounds. Speed ratio = `t_baseline / t_config`; **> 1 means the
configuration is faster than the PGO baseline.** n=10 makes each CI coarser
than the A/A's n=30; the MDE stays the one frozen by the A/A, 3.00%.

Aggregate (unweighted geometric mean over the four workloads --- the toy has
no pre-frozen case weights):

| config | aggregate ratio (geomean) | 95% CI | half-width | abs change | beyond MDE 3%? |
|---|---|---|---|---|---|
| baseline | 1.0000 | [1.0000, 1.0000] | 0.00% | 0.00% | no |
| g0-align5 | 0.9982 | [0.9942, 1.0020] | 0.39% | 0.18% | no |
| g1-ic1 | 0.7338 | [0.7316, 0.7360] | 0.22% | 26.62% | YES |
| g1-ic2 | 0.9160 | [0.9126, 0.9194] | 0.34% | 8.40% | YES |
| g1-ic4 | 0.9892 | [0.9763, 0.9987] | 1.12% | 1.08% | no |
| g1-maxbw | 0.8179 | [0.8155, 0.8206] | 0.26% | 18.21% | YES |
| g1-maxbw-vw32 | 1.1293 | [1.1231, 1.1360] | 0.65% | 12.93% | YES |
| g1-tailfold-prefer | 1.0020 | [0.9991, 1.0050] | 0.29% | 0.20% | no |
| g1-tfstyle-data | 0.9943 | [0.9897, 0.9994] | 0.49% | 0.57% | no |
| g1-tfstyle-data-and-control | 0.9942 | [0.9902, 0.9982] | 0.40% | 0.58% | no |
| g1-vw16 | 1.1374 | [1.1276, 1.1471] | 0.98% | 13.74% | YES |
| g1-vw32 | 1.1332 | [1.1253, 1.1406] | 0.76% | 13.32% | YES |
| g1-vw8 | 1.3685 | [1.3548, 1.3816] | 1.34% | 36.85% | YES |
| g2-inline1000 | 1.0006 | [0.9968, 1.0040] | 0.36% | 0.06% | no |
| g2-inline325 | 1.0025 | [0.9994, 1.0056] | 0.31% | 0.25% | no |
| g2-inline500 | 1.0013 | [0.9974, 1.0049] | 0.38% | 0.13% | no |
| g2-unroll-max2 | 0.9944 | [0.9887, 0.9997] | 0.55% | 0.56% | no |
| g2-unroll-runtime | 1.0030 | [1.0003, 1.0059] | 0.28% | 0.30% | no |
| g2-unroll-thr1000 | 0.9931 | [0.9776, 1.0029] | 1.27% | 0.69% | no |
| g2-unroll-thr300 | 0.9970 | [0.9935, 1.0008] | 0.36% | 0.30% | no |
| g3-gvn-hoist | 1.0000 | [0.9976, 1.0023] | 0.24% | 0.00% | no |
| g3-loop-distribute | 1.0015 | [0.9978, 1.0049] | 0.35% | 0.15% | no |
| g3-slp-100 | 0.9985 | [0.9935, 1.0026] | 0.45% | 0.15% | no |
| g3-slp-neg20 | 0.9897 | [0.9865, 0.9933] | 0.34% | 1.03% | no |

Per workload, mean wall time and ratio with its 95% CI:

| config | quotes ms | special ms | sum ms | dot ms | quotes ratio [CI] | special ratio [CI] | sum ratio [CI] | dot ratio [CI] |
|---|---|---|---|---|---|---|---|---|
| baseline | 117.6 | 622.1 | 109.7 | 277.1 | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] |
| g0-align5 | 117.2 | 622.8 | 110.9 | 276.9 | 1.0035 [0.9995, 1.0073] | 0.9990 [0.9973, 1.0007] | 0.9895 [0.9695, 1.0075] | 1.0009 [0.9922, 1.0087] |
| g1-ic1 | 161.4 | 622.0 | 275.5 | 277.3 | 0.7283 [0.7236, 0.7321] | 1.0001 [0.9981, 1.0020] | 0.3982 [0.3941, 0.4031] | 0.9993 [0.9922, 1.0065] |
| g1-ic2 | 126.6 | 624.2 | 144.5 | 276.6 | 0.9283 [0.9245, 0.9318] | 0.9967 [0.9943, 0.9993] | 0.7594 [0.7483, 0.7707] | 1.0020 [0.9962, 1.0082] |
| g1-ic4 | 117.5 | 623.4 | 114.7 | 276.3 | 1.0004 [0.9917, 1.0067] | 0.9980 [0.9964, 0.9997] | 0.9562 [0.9110, 0.9885] | 1.0030 [0.9963, 1.0105] |
| g1-maxbw | 259.4 | 626.0 | 110.6 | 276.7 | 0.4532 [0.4519, 0.4545] | 0.9938 [0.9925, 0.9952] | 0.9922 [0.9795, 1.0062] | 1.0014 [0.9950, 1.0083] |
| g1-maxbw-vw32 | 259.8 | 623.6 | 109.9 | 76.8 | 0.4526 [0.4512, 0.4539] | 0.9977 [0.9952, 0.9998] | 0.9983 [0.9870, 1.0122] | 3.6080 [3.5539, 3.6587] |
| g1-tailfold-prefer | 117.3 | 622.1 | 109.2 | 276.9 | 1.0021 [0.9978, 1.0058] | 1.0000 [0.9981, 1.0020] | 1.0051 [0.9969, 1.0146] | 1.0008 [0.9949, 1.0074] |
| g1-tfstyle-data | 117.0 | 622.5 | 112.8 | 276.9 | 1.0048 [1.0014, 1.0080] | 0.9994 [0.9973, 1.0014] | 0.9724 [0.9538, 0.9936] | 1.0009 [0.9953, 1.0067] |
| g1-tfstyle-data-and-control | 117.0 | 623.1 | 112.1 | 278.5 | 1.0049 [1.0010, 1.0088] | 0.9984 [0.9964, 1.0003] | 0.9785 [0.9603, 0.9969] | 0.9951 [0.9851, 1.0047] |
| g1-vw16 | 254.0 | 623.3 | 108.8 | 77.2 | 0.4628 [0.4611, 0.4644] | 0.9980 [0.9956, 1.0003] | 1.0089 [0.9904, 1.0271] | 3.5907 [3.5021, 3.6722] |
| g1-vw32 | 259.8 | 623.1 | 110.4 | 75.5 | 0.4526 [0.4506, 0.4542] | 0.9984 [0.9957, 1.0009] | 0.9941 [0.9694, 1.0158] | 3.6705 [3.6245, 3.7131] |
| g1-vw8 | 120.9 | 622.6 | 109.6 | 76.9 | 0.9722 [0.9693, 0.9750] | 0.9992 [0.9977, 1.0008] | 1.0014 [0.9713, 1.0264] | 3.6057 [3.5444, 3.6713] |
| g2-inline1000 | 117.5 | 626.0 | 109.1 | 276.5 | 1.0008 [0.9908, 1.0085] | 0.9938 [0.9911, 0.9963] | 1.0053 [0.9897, 1.0212] | 1.0024 [0.9953, 1.0095] |
| g2-inline325 | 117.1 | 622.8 | 109.4 | 276.1 | 1.0043 [1.0001, 1.0079] | 0.9990 [0.9969, 1.0012] | 1.0029 [0.9896, 1.0166] | 1.0038 [0.9981, 1.0098] |
| g2-inline500 | 117.2 | 623.5 | 109.3 | 277.0 | 1.0034 [0.9991, 1.0079] | 0.9978 [0.9959, 0.9997] | 1.0036 [0.9882, 1.0195] | 1.0003 [0.9930, 1.0073] |
| g2-unroll-max2 | 116.8 | 623.1 | 112.0 | 278.9 | 1.0064 [1.0018, 1.0105] | 0.9984 [0.9966, 0.9998] | 0.9794 [0.9601, 0.9983] | 0.9938 [0.9873, 1.0014] |
| g2-unroll-runtime | 116.4 | 627.3 | 108.9 | 276.5 | 1.0103 [1.0062, 1.0143] | 0.9918 [0.9899, 0.9935] | 1.0079 [0.9954, 1.0207] | 1.0022 [0.9958, 1.0089] |
| g2-unroll-thr1000 | 116.6 | 626.5 | 112.9 | 277.3 | 1.0082 [1.0030, 1.0127] | 0.9931 [0.9912, 0.9951] | 0.9721 [0.9106, 1.0099] | 0.9994 [0.9922, 1.0069] |
| g2-unroll-thr300 | 117.0 | 625.7 | 111.3 | 276.2 | 1.0047 [1.0004, 1.0088] | 0.9942 [0.9926, 0.9956] | 0.9860 [0.9675, 1.0051] | 1.0034 [0.9954, 1.0113] |
| g3-gvn-hoist | 116.5 | 622.9 | 110.5 | 277.2 | 1.0091 [1.0061, 1.0123] | 0.9988 [0.9969, 1.0009] | 0.9927 [0.9842, 1.0025] | 0.9996 [0.9923, 1.0076] |
| g3-loop-distribute | 117.2 | 622.6 | 109.5 | 276.6 | 1.0034 [0.9998, 1.0069] | 0.9992 [0.9978, 1.0002] | 1.0015 [0.9857, 1.0184] | 1.0021 [0.9951, 1.0095] |
| g3-slp-100 | 116.7 | 626.9 | 110.8 | 276.1 | 1.0072 [1.0045, 1.0104] | 0.9924 [0.9900, 0.9943] | 0.9906 [0.9707, 1.0083] | 1.0038 [0.9971, 1.0107] |
| g3-slp-neg20 | 120.9 | 629.2 | 109.6 | 278.1 | 0.9725 [0.9687, 0.9759] | 0.9888 [0.9858, 0.9913] | 1.0013 [0.9899, 1.0144] | 0.9966 [0.9877, 1.0057] |

Configurations that moved a workload beyond the 3.00% MDE:

| config | workload | change | 95% CI | correctness |
|---|---|---|---|---|
| g1-maxbw | quotes | **-54.68%** | [-54.81%, -54.55%] | checksums match |
| g1-vw16 | quotes | -53.72% | [-53.89%, -53.56%] | dot differs |
| g1-vw32 | quotes | -54.74% | [-54.94%, -54.58%] | dot differs |
| g1-maxbw-vw32 | quotes | -54.74% | [-54.88%, -54.61%] | dot differs |
| g1-ic1 | quotes | **-27.17%** | [-27.64%, -26.79%] | checksums match |
| g1-ic1 | sum | **-60.18%** | [-60.59%, -59.69%] | checksums match |
| g1-ic2 | quotes | **-7.17%** | [-7.55%, -6.82%] | checksums match |
| g1-ic2 | sum | **-24.06%** | [-25.17%, -22.93%] | checksums match |
| g1-ic4 | sum | **-4.38%** | [-8.90%, -1.15%] | checksums match |
| g1-vw8 | dot | +260.57% | [+254.44%, +267.13%] | **different result** |
| g1-vw16 | dot | +259.07% | [+250.21%, +267.22%] | **different result** |
| g1-vw32 | dot | +267.05% | [+262.45%, +271.31%] | **different result** |
| g1-maxbw-vw32 | dot | +260.80% | [+255.39%, +265.87%] | **different result** |

**Every correctness-valid movement beyond the MDE is a regression.** Nothing
in groups 0-3 made the toy faster by more than 1.1% on the aggregate, and the
largest valid per-workload gain of any configuration is +1.03%
(`g2-unroll-runtime` on quotes, CI [+0.62%, +1.43%]) --- a third of the MDE.

The group 0 noise probe behaved: `g0-align5` changed `.text` but no remark and
measured 0.9982 aggregate, CI [0.9942, 1.0020], inside the A/A band.

### 15. `count_quotes`: width 32 materialized, and it is 2.2x slower

This is the loop SPEC.ja.md 6.2 called "the highest-expected-value hint on
this machine". Both `-vectorizer-maximize-bandwidth` and
`-force-vector-width=32` do produce VF 32 for it, so the hint mechanism works
exactly as hoped --- and the result is a large regression.

Remarks, at the `count_quotes` DebugLoc (`library/core/src/slice/iter/macros.rs:279:24`):

```
baseline      : vectorized loop (vectorization width: 4, interleaved count: 4)
g1-maxbw      : vectorized loop (vectorization width: 32, interleaved count: 1)
g1-vw32       : vectorized loop (vectorization width: 32, interleaved count: 1)
```

Machine code (`scripts/toy_loop_attribution.sh <binary>`, which walks every
instruction of `toy::main` and resolves the inline chain --- the remark text
alone cannot say which loop is which, section 6):

| build | insns in count_quotes | with vector regs | the shape |
|---|---|---|---|
| baseline | 80 | 43 | 5 x `vpcmpeqb %xmm` (16 B) + 5 x `vpmovzxbq %xmm,%ymm` + 12 x `vpaddq` |
| g1-maxbw | 112 | 75 | `vpcmpeqb (%r8,%r10,1),%ymm2,%ymm11` (**32 B**) + `vpmovzxbw` -> `vpmovzxwd` -> 8 x `vpmovzxdq` + 22 x `vpaddq` |
| g1-vw32 | 79 | 58 | `vpcmpeqb (%r8,%r10,1),%ymm0,%ymm10` (**32 B**) + the same three-level widening + 17 x `vpaddq` |

```
quotes mean wall time: baseline 117.6 ms, g1-maxbw 259.4 ms, g1-vw32 259.8 ms
ratio vs baseline:     g1-maxbw 0.4532 [0.4519, 0.4545], g1-vw32 0.4526 [0.4506, 0.4542]
```

**Why it is slower, and what that costs SPEC.ja.md 6.2's hypothesis.** The
hypothesis was that the i64 accumulator holds the loop to 16 bytes per
iteration and that a byte-width accumulator would take 32, an 8x-per-register
gap. What LLVM actually does at VF 32 is raise the *element count* and keep
the *accumulator type*: the 32-byte compare result is widened i8 -> i16 -> i32
-> i64 through a three-level `vpmovzx` tree into **eight** `ymm` accumulators,
which are then all `vpaddq`-ed. The widening tree, not the compare, becomes
the loop body. LLVM never narrows the reduction, so the "8x per register" was
never on offer through this knob --- and the cost model that picked VF 4 was
right.

This is a record about the toy, not a claim about zopfli or jaq, but it is a
direct measurement against the specific hypothesis the spec named, on the
pinned toolchain, and it points the other way.

### 16. Stopping rule (SPEC.ja.md 6.3), applied to the toy as a record

SPEC.ja.md 6.4 exempts the toy from the stopping rule. The rule is applied
here anyway, as a record, to check that it can be evaluated mechanically:

> Across groups 1-3, if (a) no configuration's aggregate speed-ratio CI lower
> bound exceeds the minimum effect size, **and** (b) no configuration improves
> a single case beyond the minimum effect size, record "this target is flat
> under the hint method" and swap the target.

Evaluated with MDE = 3.00% over the 23 timed configurations of groups 1-3:

- **(a)** Among configurations whose output is correct: the highest aggregate
  CI lower bound is 1.0003 (`g2-unroll-runtime`, CI [1.0003, 1.0059]), far
  below 1.03. **Not satisfied.** Four configurations do clear it --- `g1-vw8` at
  [1.3548, 1.3816] and the other three `-force-vector-width` builds --- but
  all four compute a different `dot` result (section 13).
- **(b)** Among correct configurations, no per-workload improvement reaches
  3%; the best is +1.03%. **Not satisfied.**

**Outcome for the toy: (a) no and (b) no, so the rule reads "flat under the
hint method, swap the target".** For the toy that outcome is discarded by
SPEC.ja.md 6.4 --- the toy exists to verify the pipeline, and the pipeline
ran. What is worth carrying forward is that the rule was decidable from the
recorded artifacts without any judgement call, and that **it only stayed
decidable because the correctness check was applied first**: read literally,
with no correctness precondition, clause (a) would have been satisfied by
`-force-vector-width` and the toy would have been recorded as having
headroom, on the strength of a binary that computes the wrong answer.

### 17. Implications for the Stage 1 candidate set

What moved anything on the toy, and in which direction:

| knob | effect on the toy | keep as a Stage 1 candidate? |
|---|---|---|
| `-vectorizer-maximize-bandwidth` | VF 4 -> 32 on the i8 reduction, quotes **-54.7%**, aggregate **-18.2%**; checksums match | yes --- it is the strongest lever found, it is just pointing down here. Its description must state the direction is not known a priori |
| `-force-vector-width` 8/16/32 | same VF change plus **reassociates FP reductions**; quotes -53.7 to -54.7%, `dot` output changes | **only behind a correctness gate.** Not safe as a global flag on any target with an FP reduction |
| `-force-vector-interleave` 1/2/4 | IC 1: quotes -27.2%, sum -60.2%; IC 2: -7.2% / -24.1%; IC 4: sum -4.4%. All regressions, all correct | yes, as evidence that interleave is the *second* live dimension here. PGO already picked IC 4 and picked well |
| `-epilogue-tail-folding-policy`, `-force-tail-folding-style` | remarks change (+8) or `.text` changes, time does not (<= 0.6%) | low value on this shape; keep at low priority for zopfli |
| `-inline-threshold` 325/500/1000 | 524-1370 remark lines change, `.text` changes, time does not (<= 0.25%) | keep --- the toy is too small for inlining to matter; this says nothing about zopfli/jaq |
| unroll knobs (`-unroll-threshold`, `-unroll-max-count`, `-unroll-runtime`) | `.text` changes, time within 0.7% | keep at low priority |
| `-slp-threshold` -20/100 | 435/122 remark lines change, aggregate -1.0% / -0.2% | low priority |
| `-enable-loop-distribute` | 255 remarks, `.text` **identical** | drop unless a target has a distributable loop |
| `-enable-gvn-hoist` | 1 remark, 1 line, no time change | drop |
| `-runtime-memory-check-threshold`, `-unswitch-threshold`, `-enable-loop-flatten`, `-unroll-max-count=8` | byte-identical `.text` | drop for this target shape; re-probe per target |
| `-enable-early-exit-vectorization` | **already on by default** on 23.1.1; on and off both give byte-identical `.text` | drop, and correct the premise: SPEC.ja.md 6.2 calls this "the one global lever, untested" for `find_special`. It is not untested --- the PGO baseline already runs with it on, and `find_special` is still refused on legality |

Two procedural findings for Stage 1:

1. **The `.text` hash is a better skip criterion than the remark diff.** Six
   configurations produced byte-identical code, which is proof that timing is
   unnecessary; two produced changed remarks with identical code, which the
   remark diff alone would have sent to the timer. Both checks are cheap.
2. **The correctness check has to run before the timing is read**, not after.
   The largest single "speedup" in this whole sweep (+267% on `dot`) is a
   wrong answer.

### 18. Not done on the toy day (all three closed by the zopfli section below)

- Group 4 (`-Ctarget-feature=+prefer-256-bit` / `+prefer-128-bit`,
  `-Ctarget-cpu=x86-64-v3`). SPEC.ja.md 13 day-0 item 6 ties group 4 to the
  stopping-rule decision, which is a zopfli item. **Run on zopfli, section 25.**
- Everything for zopfli (SPEC.ja.md 13 day-0 items 5 and 6 proper).
  **Sections 19-30.**
- `remark-reason-map.json` is still the nine hand-classified seeds of section
  6; the sweep logs contain many more reason strings that have not been
  classified. **Extended to 26 strings, including the first `cost` entries,
  in section 23; still living in `scripts/remark_attribution.py` rather than
  in a JSON file.**

`scripts/toy_*.sh` are now three-line shims over `scripts/target_*.sh`
(section 19); the commands quoted above still run unchanged.

## Stage 0 (zopfli) --- the first real target

Date: 2026-09-21, same machine and same pinned toolchain as the toy sections
(rustc 1.100.0-nightly bba531001 / LLVM 23.1.1). This covers SPEC.ja.md 13
day-0 items 2-6 for zopfli: PGO baseline, disqualification filter, the loop
landscape, the A/A noise floor, the group 0-4 headroom sweep and the
SPEC.ja.md 6.3 stopping rule. **Unlike the toy, zopfli carries the stopping
rule** (SPEC.ja.md 6.4).

Reproduce with:

```
python3 targets/zopfli/workloads/gen.py           # the six inputs, fixed seeds
TARGET=zopfli REUSE_PROFDATA=0 REPRO=1 scripts/target_pgo_baseline.sh
scripts/profdata_hotness.py pgo/zopfli/merged.profdata
scripts/remark_attribution.py --bin target-zopfli-pgo-use/x86_64-unknown-linux-gnu/release/zopfli \
    --log remarks/zopfli/baseline-build.log \
    --src-prefix targets/zopfli/src/src --sym-filter zopfli --out artifacts/zopfli-attr
TARGET=zopfli scripts/target_aa.sh 15 3
TARGET=zopfli RUNS=8 WARMUP=2 scripts/target_headroom.sh
```

**The day-0 scripts are now target-parameterised.** `scripts/toy_common.sh`,
`toy_aa.sh`, `toy_headroom.sh` and `toy_pgo_baseline.sh` were renamed to
`scripts/target_*.sh` and take `TARGET=toy|zopfli`; the only place a target
name appears is one `case` block in `scripts/target_common.sh` (manifest, bin
name, cargo flags, workload specs, training inputs, correctness procedure).
Three-line `scripts/toy_*.sh` shims remain, so every command quoted in the
"Day 0 (toy)" sections above still runs unchanged. New at this stage:
`scripts/remark_attribution.py` (SPEC.ja.md 7's DebugLoc -> function
attribution, generalised from `toy_loop_attribution.sh`),
`scripts/profdata_hotness.py`, and `targets/zopfli/workloads/gen.py`.

### 19. The target: vendored zopfli, driven entirely from the environment

```
$ git submodule add https://github.com/zopfli-rs/zopfli targets/zopfli/src
$ cd targets/zopfli/src && git checkout 91a34e5d2ce57883a82145158bc74222d7da5229
$ git log -1 --format='%H %ci' && git describe --tags
91a34e5d2ce57883a82145158bc74222d7da5229 2025-10-30 15:31:00 +0100
v0.8.3
```

Pinned to the **v0.8.3** tag, commit `91a34e5d2ce57883a82145158bc74222d7da5229`.
This is the pure-Rust port (crate `zopfli`, `categories = ["compression",
"no-std"]`), not a binding.

The CLI exists and needs no extra `--features`:

```
[[bin]]
name = "zopfli"
required-features = ["gzip", "std", "zlib"]

[features]
default = ["gzip", "std", "zlib"]
```

`default` already is exactly the bin's `required-features`, so a plain
`cargo build --release` produces `zopfli`. The bin takes filenames on argv,
writes `<input>.gz` next to each input, hardcodes `Format::Gzip` and
`Options::default()` (`iteration_count = 15`, `maximum_block_splits = 15`),
and prints nothing (its one `info!` has no logger installed).

**Nothing in the submodule is edited.** Everything is driven exactly as the
product path will drive it: `CARGO_PROFILE_RELEASE_{OPT_LEVEL,LTO,
CODEGEN_UNITS,DEBUG,PANIC}`, `CARGO_ENCODED_RUSTFLAGS`, `RUSTUP_TOOLCHAIN`
via the repository's `rust-toolchain.toml`, explicit
`--target x86_64-unknown-linux-gnu`, a separate `CARGO_TARGET_DIR` per
variant, and `--locked` so the vendored `Cargo.lock` cannot drift. `git
status` in the submodule stays clean across every build in this section.

Reference arm R (SPEC.ja.md 9) --- the effective release profile if
`jev-opt` overrode nothing:

```
$ sed -n '/^\[profile\.release\]/,/^\[/p' targets/zopfli/src/Cargo.toml
[profile.release]
debug = true
```

So arm R is **opt-level 3, `lto` unset (off/"thin-local"), `codegen-units`
16, `debug = true`, no `target-cpu=native`, no PGO**. Only `debug` is set by
the crate; `CARGO_PROFILE_RELEASE_DEBUG=1` overrides it to the same effect.
Arm R itself is measured in Stage 1; this is the profile it will have.

### 20. Disqualification filter (SPEC.ja.md 6.1-2): one hit, and why it is not fatal

```
$ cd targets/zopfli/src && cargo tree -e normal --locked | grep -iE 'memchr|simd|wide|std_detect'
└── simd-adler32 v0.3.7
$ grep -rlE 'core::arch|_mm_|_mm256|target_feature' targets/zopfli/src/src
(no match)
```

The dependency tree is `bumpalo`, `crc32fast` (-> `cfg-if`), `log`,
`simd-adler32`. **zopfli's own sources contain no hand-written SIMD at all**;
the filter fires only on two checksum crates, and `crc32fast` additionally
carries a `pclmulqdq` kernel (its `src/specialized/pclmulqdq.rs` shows up in
the build log's remarks).

Read literally the filter disqualifies zopfli. The profile says that would be
wrong, and the profile is free because SPEC.ja.md 8.2 already makes it the
hotness source:

```
$ scripts/profdata_hotness.py pgo/zopfli/merged.profdata --grep simd_adler32
259 function records, total block count 10766393517
functions matching 'simd_adler32': 117, summed block count 0 (0.000000% of the total)
$ scripts/profdata_hotness.py pgo/zopfli/merged.profdata --grep crc32fast
functions matching 'crc32fast': 7, summed block count 67200 (0.000624% of the total)
  sum=         67200  max=         67194  _RNvMCsaL4U1ISpxSG_9crc32fast...Hasher6update
```

`simd-adler32` is **never executed** (the CLI only ever emits gzip, so the
zlib path is linked and dead), and `crc32fast` accounts for **0.000624%** of
all block executions. Both are one linear pass over 1.4 MiB against ~2.6 s of
LZ77 and squeeze.

**Verdict: zopfli is not disqualified.** Recorded as a filter hit with the
number that overrides it.

### 21. Workloads: three kinds, two disjoint splits, one generator

`targets/zopfli/workloads/gen.py` (Python standard library only, no network,
fixed seeds). Training and holdout differ only in seed, so the holdout is the
same measurement on data the profile has never seen (SPEC.ja.md 10).

```
$ python3 targets/zopfli/workloads/gen.py
d0063a2e4ab40c6791a2a28b75aec370ee9ed2ef65e11700078c1489a335dae8  1433600  train-text.dat    seed=20260921001
f84dea12c0831b3a340a64d022290f73dd75c65ae892655dd366f6707de95e49  1433600  train-binary.dat  seed=20260921002
15170b05967a6ab1621b1bea980a49b66a99ccec2cf3ade06cd0a59a603731b3  1433600  train-json.dat    seed=20260921003
40d63cd415fdc8cccee8c262c2455b809087e012aafca203928d8846e7f2a791  1433600  hold-text.dat     seed=20260921101
542239adfe8ca616be6963d9d87cb62d21584ad632bbff84cbd753f17b5e910c  1433600  hold-binary.dat   seed=20260921102
a52a647ea929d8e6b6eac3f8cf73d3c9a177f79fe4c74ab78f724cc9b850e34e  1433600  hold-json.dat     seed=20260921103
```

| kind | content | size | PGO-baseline wall time | compressed |
|---|---|---|---|---|
| text | word salad from a 512-word vocabulary, Zipf-ish weights, 64 repeated phrases | 1400 KiB | 2.67 s | 262661 B |
| binary | uniform bytes from a 16-symbol alphabet (4 bits/byte, almost no long matches) | 1400 KiB | 1.64 s | 769769 B |
| json | records with repeated keys and short values | 1400 KiB | 2.67 s | 306321 B |

Every case is far over the 1 s floor, so process startup is noise. The
inputs are git-ignored (regenerable, 8.4 MiB total); the sha256 above is what
pins them.

**Correctness is the sha256 of the produced `.gz`.** zopfli prints nothing,
so `bench.py`'s `stdout_mismatches` check is vacuously empty here and must
not be read as a correctness pass; `run_correctness` in
`scripts/target_common.sh` copies each input to a scratch directory, runs the
binary and hashes the `.gz`. The output is deterministic:

```
========== 0b. output determinism (same binary, same inputs, twice) ==========
OUTPUT DETERMINISM: MATCH
```

### 22. PGO baseline (SPEC.ja.md 3, 13 day-0 items 2-3)

```
$ TARGET=zopfli REUSE_PROFDATA=0 REPRO=1 scripts/target_pgo_baseline.sh
```

Instrumented build -> training run on the **three training inputs only** ->
`llvm-profdata merge` with the pinned toolchain's tool:

```
========== b. training run (instrumented) ==========
  trained on train-text.dat -> 262661 bytes
  trained on train-binary.dat -> 769769 bytes
  trained on train-json.dat -> 306321 bytes
training run wall time: 8945 ms
-rw-r--r-- 1 hiro hiro 42920 default_6916624953303219016_0.profraw
========== c. llvm-profdata merge ==========
f066f5072627b070f19acfe1bfa4772b25cf5babc7752799931f579036e0ace8  pgo/zopfli/merged.profdata
Instrumentation level: IR  entry_first = 0  instrument_loop_entries = 0
Total functions: 259
Maximum function count: 151050803
Maximum internal block count: 706227900
Total number of blocks: 2385
Total count: 10766393517
```

**`merged.profdata` sha256 =
`f066f5072627b070f19acfe1bfa4772b25cf5babc7752799931f579036e0ace8`.** This is
the one profdata every arm and every sweep configuration below uses; the
training run is not repeated after this section.

Note the single `.profraw`: `-Cprofile-generate` makes rustc use a `%m`
filename, which is LLVM's merge-pooling mode, so the three training processes
accumulate into one file under a file lock.

**Profdata reproducibility (SPEC.ja.md 3) --- partially fails, and the cause
is recorded.** SPEC.ja.md 3's wording is "re-run the training with the *same
instrumented binary*". Done that way it reproduces exactly:

```
$ mv pgo/zopfli/profraw pgo/zopfli/profraw-run1 && mkdir pgo/zopfli/profraw
$ <re-run the same instrumented binary on the same three inputs>
$ cmp pgo/zopfli/profraw-run1/*.profraw pgo/zopfli/profraw/*.profraw
... differ: byte 114        # 1120 of 42920 raw bytes differ
$ llvm-profdata merge -o pgo/zopfli/merged-run2.profdata pgo/zopfli/profraw/*.profraw
$ sha256sum pgo/zopfli/merged.profdata pgo/zopfli/merged-run2.profdata
f066f5072627b070f19acfe1bfa4772b25cf5babc7752799931f579036e0ace8  merged.profdata
f066f5072627b070f19acfe1bfa4772b25cf5babc7752799931f579036e0ace8  merged-run2.profdata
```

**Byte-identical**, even though the raw file is not --- `llvm-profdata` drops
the raw regions that vary. But rebuilding the instrumented binary into a
different `CARGO_TARGET_DIR` and retraining (`REPRO=1`, the stricter test the
script runs) does **not** reproduce:

```
========== c2. profdata reproducibility (second training run, separate directory) ==========
f066f5072627b070f19acfe1bfa4772b25cf5babc7752799931f579036e0ace8  merged.profdata
6eaa084f1a521381b68f00e1ec52bb160d36dd312370ee967f9ceb760ed36bd6  merged-repro.profdata
PROFDATA REPRODUCIBLE: NO --- the two merges differ
```

Cause, established on the spot: the two files differ in **exactly 20 bytes,
at offsets 65073-65092 of 65104**, and all counters are identical
(`llvm-profdata show --all-functions --counts` of the two files diffs to zero
lines). Those 20 bytes are the binary ID:

```
$ llvm-profdata show --binary-ids pgo/zopfli/merged.profdata       -> cafbb6ee7477f63fc51ae37de59e726af58dcc7d
$ llvm-profdata show --binary-ids pgo/zopfli/merged-repro.profdata -> 5dbbe8143614f34add2c863de0618745fc2d2032
```

i.e. the GNU build-id of the instrumented binary, which changes when the
binary is rebuilt under a different target directory. **The profile content
is reproducible; the profdata file is reproducible only for a fixed
instrumented binary.** For the spec this matters in one place: a
`basis.pgo_profile_sha` equality check is a check on "same profile *and* same
instrumented binary", which is stricter than intended but never wrong.

PGO baseline build, with `-pgo-warn-missing-function` and the three
`-pass-remarks*` flags:

```
========== d. PGO baseline build (-Cprofile-use) + remarks ==========
--- remark lines total ---            31764      (5255 unique after sort -u)
--- hash mismatch ---                 0
--- no profile data available for function --- 0
--- all warning: lines ---            0
--- .text sha256 ---
9aca86fcd89a759f60bb5d83ac768ff83a72b21516bee26ab0cd0982fa76cbdf
```

**Zero profile-use warnings of any kind on a real program**, which is a much
stronger statement than the toy's zero (the toy had one crate). Note the
caveat still holds that `-Cprofile-use` applies to the five crates built from
source and not to the prebuilt std rlibs.

Correctness, plain release vs PGO baseline --- all six inputs:

```
========== e. checksum comparison (plain release vs PGO baseline) ==========
train-text.dat   90d617f8cea1de4ac2b85e584342541fe2b023fe9fa6b5c8d33395cf1ee96e0d
train-binary.dat 74be7ace4f6ba9857ce0335ca8ace40e107f3902b006c98923d16c0745cb9dcc
train-json.dat   f94c7fd2f4331f31d69ae8c97ce0fe23bccb40a7a43d0fdeb330952d38c67773
hold-text.dat    e876f985995f485871cd8835c163c40257ee277ef08d6829f8e44a25ac01d9fb
hold-binary.dat  f2b0f204e2c2468e0faaceec8eea7b6a3c4478f0fa4979c8118f7c355e0660ff
hold-json.dat    535723094e22129aff69fa5017d21d6700002928e83637f1d40174f77a9b99b5
CHECKSUMS: MATCH
```

`.text` and debuginfo, re-confirming section 5's toy finding on a real target:

```
========== f. .text hash, debug=1 vs debug=0 ==========
debug=1 .text sha256: 9aca86fcd89a759f60bb5d83ac768ff83a72b21516bee26ab0cd0982fa76cbdf
debug=0 .text sha256: 1db5248153263dfb14e1e16a7f14e4a024ca0879b27095967755f5fbb62703e5
TEXT HASH: DIFFER
debug=0 checksums: MATCH
```

Builds are cheap: 4.4-6.3 s each, `.text` 333884 bytes, binary 2653128 bytes
before strip and 440128 after.

Build determinism: `scripts/target_aa.sh` rebuilt the PGO baseline from
scratch in a different target directory and got the same `.text` hash
`9aca86fc...`. The whole sweep rests on that.

### 23. The loop landscape (SPEC.ja.md 6.2's real-target check)

```
$ scripts/remark_attribution.py \
    --bin target-zopfli-pgo-use/x86_64-unknown-linux-gnu/release/zopfli \
    --log remarks/zopfli/baseline-build.log \
    --src-prefix targets/zopfli/src/src --sym-filter zopfli \
    --out artifacts/zopfli-attr --top 25
remarks parsed: declined=512, reason=2339, slp=3193, vectorized=23
symbols walked: 81 (99298 bytes of .text), filter='zopfli'
instructions:   22308
unattributed remark locations: 3853 of 6067
ambiguous (DebugLoc resolving to >1 function): 1328
```

Out of 31764 remark lines: **23 loops vectorized, 512 loops refused** (the
bare `loop not vectorized` line is the per-loop verdict; the reason strings
are separate analysis lines and several attach to one loop). 3193 lines are
SLP, out of reach of every loop-metadata family.

**A parsing point worth keeping.** LLVM 23.1.1 emits the cost-model verdicts
as *standalone* analysis remarks, not as `loop not vectorized: <reason>`:

```
remark: src/hash.rs:150:46: the cost-model indicates that vectorization is not beneficial
remark: src/hash.rs:150:46: the cost-model indicates that interleaving is not beneficial
```

A parser that only reads the `loop not vectorized:` form reports **zero
`cost` remarks for zopfli** --- and the `cost` bucket is precisely what
SPEC.ja.md 7 feeds to Jev. The first version of this script did exactly that.

#### VF/IC distribution of the 23 vectorized loops

| VF | IC | count |
|---|---|---|
| 4 | 1 | 3 |
| 4 | 2 | 7 |
| 4 | 4 | 6 |
| 8 | 1 | 1 |
| 8 | 2 | 1 |
| 8 | 4 | 1 |
| 16 | 1 | 2 |
| 16 | 4 | 2 |

#### Reasons, with the SPEC.ja.md 4 classification

| count | class | reason string |
|---|---|---|
| 455 | unsupported | `call instruction cannot be vectorized` |
| 443 | unsupported | `value that could not be identified as reduction is used outside the loop` |
| 184 | legality | `Cannot vectorize early exit loop` |
| 161 | unsupported | `could not determine number of loop iterations` |
| 159 | **unknown** | `instruction cannot be vectorized` |
| 117 | **cost** | `the cost-model indicates that interleaving is not beneficial` |
| 111 | **cost** | `the cost-model indicates that vectorization is not beneficial` |
| 110 | unsupported | `loop induction variable could not be identified` |
| 89 | unsupported | `instruction return type cannot be vectorized` |
| 69 | **unknown** | `Loop contains an unsupported terminator` |
| 62 | **unknown** | `Cannot vectorize uncountable loop` |
| 58 | unsupported | `Control flow cannot be substituted for a select` |
| 49 | legality | `Incorrect number of successors from early exiting block` |
| 46 | **unknown** | `unable to calculate the loop count due to complex control flow` |
| 40 | unsupported | `loop control flow is not understood by vectorizer` |
| 40 | legality | `Loop contains an unsupported switch` |
| 39 | **unknown** | `Cannot vectorize early exit loop with reductions or recurrences` |
| 31 | **unknown** | `Cannot vectorize early exit loop with complex writes to memory` |
| 25 | legality | `cannot identify array bounds` |
| 19 | **unknown** | `Cannot vectorize early exit loop with strided fault-only-first load` |
| 14 | **unknown** | `Early exit loop with store but no supported condition load` |
| 8 | legality | `unsafe dependent memory operations in loop...` |
| 4 | **unknown** | `read with atomic ordering or volatile read` |
| 2 | **unknown** | `Auto-vectorization of early exit loops requiring a scalar epilogue is unsupported` |
| 2 | **unknown** | `runtime pointer checks needed...` |
| 2 | **unknown** | `Early exit loop contains operations that cannot be speculatively executed` |

Totals by class: **unsupported 1356, unknown 449, cost 228, legality 306** (2339 reason lines, 26 distinct strings).

**New strings for `remark-reason-map.json`.** Section 6's nine toy seeds
covered 8 of the 26 strings above; the ninth
(`cannot prove it is safe to reorder floating-point operations`) does not
appear in zopfli's build log at all (see section 25). Added to the table in
`scripts/remark_attribution.py` (classified by hand, same rule --- anything
not listed stays `unknown`):

- legality: `cannot identify array bounds`, `unsafe dependent memory
  operations in loop. Use #pragma clang loop distribute(enable)...`
- unsupported: `loop control flow is not understood by vectorizer`,
  `instruction return type cannot be vectorized`, `Unsupported outer loop`
- **cost (a class the toy never produced)**: `the cost-model indicates that
  vectorization is not beneficial`, `the cost-model indicates that
  interleaving is not beneficial`

**Left deliberately `unknown`: 12 distinct strings, 449 lines --- these need
a decision.** Nine of the twelve are the early-exit family
(`Cannot vectorize early exit loop with reductions or recurrences`,
`... with complex writes to memory`, `... with strided fault-only-first load`,
`Cannot vectorize uncountable loop`, `Loop contains an unsupported
terminator`, `unable to calculate the loop count due to complex control
flow`, `Early exit loop with store but no supported condition load`,
`Early exit loop contains operations that cannot be speculatively executed`,
`Auto-vectorization of early exit loops requiring a scalar epilogue is
unsupported`). They all *look* like legality, but LLVM 23.1.1's early-exit
vectorization is a feature with its own enable flag, so calling them
`legality` would be an assertion this section has not tested. The other
three are `instruction cannot be vectorized` (159 lines, too vague to
classify), `read with atomic ordering or volatile read` and `runtime pointer
checks needed...`. All twelve stay `unknown`, which means SPEC.ja.md 8.3
will not exclude those sites from Jev.

#### Which functions, and what the loops are made of

Hotness from the profile (SPEC.ja.md 8.2's source, without the plugin's
instruction weighting):

```
$ scripts/profdata_hotness.py pgo/zopfli/merged.profdata --top 8
259 function records, total block count 10766393517
  max=     706227900  sum=    1125245001  (10.45%)  <zopfli::cache::ZopfliLongestMatchCache as Cache>::try_get
  max=     611160922  sum=    4543415570  (42.20%)  zopfli::lz77::find_longest_match_loop
  max=     571056690  sum=    2651837803  (24.63%)  zopfli::squeeze::lz77_optimal::<ZopfliLongestMatchCache>
  max=     166329758  sum=     397253167  ( 3.69%)  zopfli::squeeze::get_cost_stat
  max=     151050803  sum=    1035496521  ( 9.62%)  <zopfli::hash::ZopfliHash>::update
  max=     129891675  sum=     260153638  ( 2.42%)  <zopfli::cache::ZopfliLongestMatchCache>::max_sublen
  max=      71999001  sum=      78843535  ( 0.73%)  zopfli::lz77::find_longest_match::<ZopfliLongestMatchCache>
  max=      47806904  sum=     133806706  ( 1.24%)  <zopfli::lz77::Lz77Store>::follow_path::<...>
```

Four functions are 87% of all block executions. Now the 23 vectorized loops,
each with the functions its DebugLoc resolves to:

| DebugLoc | VF/IC | lines | attribution |
|---|---|---|---|
| `src/lz77.rs:563:21` | 16/4 | 1 | **UNIQUE**: `zopfli::lz77::find_longest_match_loop` |
| `src/lz77.rs:303:26` | 4/4 | 1 | **UNIQUE**: `<zopfli::lz77::Lz77Store>::get_histogram_at` |
| `src/squeeze.rs:265:5` | 8/4 | 1 | 2 candidates, both `zopfli::squeeze::get_best_lengths::<..>` instantiations |
| `core/src/slice/iter/macros.rs:28:9` | 4/4 | 2 | **UNIQUE**: `<SymbolStats>::calculate_entropy` |
| `core/src/slice/iter/macros.rs:279:24` | 4/2, 4/4 | 5 | **UNIQUE**: `<SymbolStats>::calculate_entropy` |
| `core/src/slice/iter/macros.rs:180:28` | 4/1, 4/2 | 2 | ambiguous, 11 candidates |
| `core/src/iter/range.rs:1103:12` | 4/1, 4/2, 4/4, 8/2, 16/4 | 8 | ambiguous, **29 candidates** |
| `<unknown>:0:0` | 8/1, 16/1 | 3 | unattributable (no DebugLoc at all) |

**SPEC.ja.md 7's ambiguity problem is real and large on a real target**: 1328
of 6067 decision lines resolve to more than one function, and the single
DebugLoc `core/src/iter/range.rs:1103:12` (the `for i in a..b` desugaring) is
shared by 29 distinct functions in this binary. Every function in the
per-function report therefore shows the same "8 vectorized loops" from that
shared set; only the `UNIQUE` rows above are attributions worth acting on.
Stage 2's plugin dump does not have this problem (it reads the IR).

An additional wrinkle this target adds: std bundles `gimli`, `addr2line` and
`object` for backtraces, and their files are spelled `src/read/line.rs`,
`src/function.rs`, `src/unit.rs`, `src/leb128.rs` --- the same `src/...` shape
as zopfli's own `src/lz77.rs`. Matching remark paths on a basename would
merge them. `remark_attribution.py` matches a remark path as a **suffix** of
the DWARF path instead.

#### Are zopfli's hot loops integer or f64?

**Integer and byte, in every hot function. The f64 is in the cost model, not
in a reduction the hints can reach.** Concretely:

- `src/lz77.rs:563:21` (inside `find_longest_match_loop`, 42.20%) is
  `for sublength in subl.iter_mut().take(..).skip(..) { *sublength = dist as u16; }`
  --- a **u16 store loop, already vectorized at VF 16 IC 4**.
- `src/lz77.rs:303:26` (`get_histogram_at`) is a `usize`-indexed **u32 copy**,
  VF 4 IC 4.
- `src/squeeze.rs:265:5` is `*cost = f32::INFINITY` --- an **f32 fill**, VF 8
  IC 4. A store, not a reduction.
- `<SymbolStats>::calculate_entropy` is the only real floating-point work the
  vectorizer touched: 299 of its 476 instructions use vector registers, mixed
  `int:123 + f64:59`. It is a **map** (`log2` per symbol), not a reduction,
  which is why it vectorizes at all --- and it is 0.15% of the profile.
- `zopfli::squeeze::get_cost_stat` (3.69%) is f64 arithmetic but is a
  per-symbol cost lookup called from a scalar loop, not a reducible loop.

The two **cost-declined loops that sit in hot functions** are both integer:

```
$ # src/cache.rs:108, inside <ZopfliLongestMatchCache as Cache>::try_get (10.45%)
$ #   16x "the cost-model indicates that vectorization is not beneficial"
$ #   16x "the cost-model indicates that interleaving is not beneficial"
$ #   16x "unable to calculate the loop count due to complex control flow"
            let mut i = prevlength;
            while i <= length {
                sublen[i] = dist;          // u16 store, trip count unknown
                i += 1;
            }
$ # src/hash.rs:150, inside <ZopfliHash>::update (9.62%)
$ #   12x "the cost-model indicates that vectorization is not beneficial"
$ #   12x "the cost-model indicates that interleaving is not beneficial"
        while another_index < array.len() && array_pos == array[another_index]
              && amount < u16::MAX
        { amount += 1; another_index += 1; }   // byte compare, early exit
```

These two are the best Stage 2 candidates the landscape offers: hot, integer,
declined on **cost** rather than legality, hence inside the reach of the five
hint families.

**SPEC.ja.md 6.2's zopfli predictions, scored:**

- "LZ77 match-length comparison is a byte loop with width/interleave room" ---
  **partly wrong in a useful way.** The byte comparison itself
  (`get_match` / `hash.rs:150`) is an early-exit loop that is refused; the
  vectorized loop in the hot LZ77 function is the `sublen` fill, and LLVM
  **already picks VF 16 IC 4** for it without any hint.
- "integer reduction" --- **no integer reduction loop is among the vectorized
  23**; what vectorizes is stores, copies and one map.
- "the f64 reduction is out of reach, so do not aim at it" (the retraction
  made after the toy's `dot_f64`) --- **correct, and stronger than stated**:
  zopfli has no vectorizable f64 reduction in the hot path at all, so the
  question never arises.

### 24. A/A noise floor and the minimum detectable effect

```
$ TARGET=zopfli scripts/target_aa.sh 15 3
# = build the PGO baseline, copy it to A1 and A2, strip both, then
#   scripts/bench.py run --cpu 2 --warmup 3 --runs 15 \
#       --label A1=artifacts/zopfli-aa/A1 --label A2=artifacts/zopfli-aa/A2 \
#       --workload text=.../hold-text.dat --workload binary=... --workload json=... \
#       --out artifacts/zopfli-aa/aa.json
#   scripts/bench.py stats artifacts/zopfli-aa/aa.json --base A1 \
#       --seed 20260921 --resamples 10000
$ sha256sum artifacts/zopfli-aa/A1 artifacts/zopfli-aa/A2
79c3322677aa336f8fab45c449559cac9568277636afdfc998e9d07bae887a98  A1
79c3322677aa336f8fab45c449559cac9568277636afdfc998e9d07bae887a98  A2
```

90 timed samples (2 labels x 3 workloads x 15 rounds), warmup 3, `taskset -c 2`:

| workload | A1 mean ms | A2 mean ms | ratio A1/A2 | 95% CI | half-width |
|---|---|---|---|---|---|
| text | 2666.3 | 2662.0 | 1.0016 | [1.0001, 1.0035] | **0.17%** |
| binary | 1625.8 | 1629.3 | 0.9978 | [0.9948, 1.0006] | **0.29%** |
| json | 2669.2 | 2660.7 | 1.0032 | [1.0009, 1.0064] | **0.28%** |
| **aggregate (geomean)** | | | 1.0009 | [0.9995, 1.0023] | **0.14%** |

**Noise floor = worst per-workload half-width 0.29%; aggregate 0.14%.**
**MDE = max(2 x 0.29%, 3%) = 3.00%.** The 3% floor binds by a factor of five.

zopfli is a much quieter target than the toy: the toy's worst half-width was
1.22% (on its 110 ms `sum` case); zopfli's worst is 0.29% on cases of 1.6-2.7
s. Every case clears the "at least 1 s" rule by a wide margin and it shows.

### 25. Headroom sweep: 32 builds, correctness first, `.text` as the skip criterion

```
$ TARGET=zopfli RUNS=8 WARMUP=2 scripts/target_headroom.sh
```

Baseline plus 31 configurations, every one the SPEC.ja.md 3 recipe --- same
`-Cprofile-use=pgo/zopfli/merged.profdata`, same
`-Ctarget-cpu=native -Csymbol-mangling-version=v0`, same
`CARGO_PROFILE_RELEASE_{OPT_LEVEL=3,LTO=fat,CODEGEN_UNITS=1,DEBUG=1,PANIC=unwind}`,
same three `-pass-remarks*` flags, explicit `--target`, own
`CARGO_TARGET_DIR`, `--locked`, clean build --- plus that configuration's
knobs. Build time 4372-6335 ms, mean 4538 ms, 145 s for all 32. **No
configuration failed to build.**

Two deviations from the toy's list, both recorded in section 17:
`-enable-early-exit-vectorization` is **not swept** (measured default-on on
23.1.1, so passing it is a no-op), and **group 4 is included**
(SPEC.ja.md 13 day-0 item 6 ties group 4 to the zopfli stopping-rule
decision). `build_variant` now passes a knob starting with `-C` through to
rustc untouched, which is what group 4's `-Ctarget-feature` / `-Ctarget-cpu`
need; rustc takes the last `-Ctarget-cpu`, so `g4-v3` overrides `=native`.

The decision column is now target independent: `vec_decisions` keeps the
normalized remark lines that *are* a vectorizer decision (`vectorized loop
(...)`, `loop not vectorized...`, the reduction verdicts), 856 lines for the
baseline. The toy's hand-written table of four DebugLocs does not scale to a
target with hundreds of loops.

| config | knobs | output hashes | .text vs base | raw +/- | norm +/- | vec decision changed | timed? |
|---|---|---|---|---|---|---|---|
| g0-align5 | `-align-all-nofallthru-blocks=5` | MATCH | differ | +0 / -0 | +0 / -0 | no | yes (noise probe) |
| g1-maxbw | `-vectorizer-maximize-bandwidth` | MATCH | differ | +4 / -2 | +4 / -2 | YES | yes |
| g1-vw8 | `-force-vector-width=8` | MATCH | differ | +20 / -34 | +20 / -34 | YES | yes |
| g1-vw16 | `-force-vector-width=16` | MATCH | differ | +20 / -37 | +20 / -37 | YES | yes |
| g1-vw32 | `-force-vector-width=32` | MATCH | differ | +26 / -40 | +24 / -40 | YES | yes |
| g1-maxbw-vw32 | both of the above | MATCH | differ | +26 / -40 | +24 / -40 | YES | yes |
| g1-ic1 | `-force-vector-interleave=1` | MATCH | differ | +34 / -31 | +34 / -31 | YES | yes |
| g1-ic2 | `-force-vector-interleave=2` | MATCH | differ | +31 / -42 | +30 / -42 | YES | yes |
| g1-ic4 | `-force-vector-interleave=4` | MATCH | differ | +33 / -41 | +32 / -41 | YES | yes |
| g1-tailfold-prefer | `-epilogue-tail-folding-policy=prefer-fold-tail` | MATCH | **same** | +10 / -0 | +10 / -0 | no | **skipped** |
| g1-tfstyle-data | `-force-tail-folding-style=data` | MATCH | differ | +0 / -0 | +0 / -0 | no | yes |
| g1-tfstyle-data-and-control | `-force-tail-folding-style=data-and-control` | MATCH | differ | +0 / -1 | +0 / -1 | YES | yes |
| g1-memcheck24 | `-runtime-memory-check-threshold=24` | MATCH | **same** | +0 / -0 | +0 / -0 | no | **skipped** |
| g1-memcheck128 | `-runtime-memory-check-threshold=128` | MATCH | **same** | +0 / -0 | +0 / -0 | no | **skipped** |
| g2-inline325 | `-inline-threshold=325` | MATCH | differ | +1346 / -1126 | +541 / -320 | YES | yes |
| g2-inline500 | `-inline-threshold=500` | MATCH | differ | +1838 / -1408 | +1097 / -663 | YES | yes |
| g2-inline1000 | `-inline-threshold=1000` | MATCH | differ | +2058 / -1535 | +1431 / -916 | YES | yes |
| g2-unroll-thr300 | `-unroll-threshold=300` | MATCH | differ | +13 / -1 | +12 / -1 | YES | yes |
| g2-unroll-thr1000 | `-unroll-threshold=1000` | MATCH | differ | +46 / -31 | +22 / -13 | YES | yes |
| g2-unroll-max2 | `-unroll-max-count=2` | MATCH | differ | +22 / -25 | +22 / -25 | YES | yes |
| g2-unroll-max8 | `-unroll-max-count=8` | MATCH | differ | +2 / -4 | +2 / -4 | YES | yes |
| g2-unroll-runtime | `-unroll-runtime` | MATCH | differ | +4 / -0 | +4 / -0 | no | yes |
| g3-loop-distribute | `-enable-loop-distribute` | MATCH | **same** | +353 / -0 | +353 / -0 | no | **skipped** |
| g3-slp-neg20 | `-slp-threshold=-20` | MATCH | differ | +908 / -195 | +573 / -180 | YES | yes |
| g3-slp-100 | `-slp-threshold=100` | MATCH | differ | +405 / -241 | +180 / -201 | YES | yes |
| g3-unswitch200 | `-unswitch-threshold=200` | MATCH | differ | +29 / -13 | +16 / -4 | YES | yes |
| g3-loop-flatten | `-enable-loop-flatten` | MATCH | **same** | +0 / -0 | +0 / -0 | no | **skipped** |
| g3-gvn-hoist | `-enable-gvn-hoist` | MATCH | differ | +14 / -15 | +2 / -3 | no | yes |
| g4-prefer256 | `-Ctarget-feature=+prefer-256-bit` | MATCH | **same** | +0 / -0 | +0 / -0 | no | **skipped** |
| g4-prefer128 | `-Ctarget-feature=+prefer-128-bit` | MATCH | differ | +21 / -27 | +20 / -21 | YES | yes |
| g4-v3 | `-Ctarget-cpu=x86-64-v3` | MATCH | differ | +234 / -132 | +202 / -106 | YES | yes |

**Correctness: all 31 configurations produce byte-identical output on all six
inputs.** Zero correctness violations, so nothing is excluded from the
headroom judgement.

```
$ for f in artifacts/zopfli-headroom/remarks/*.checksums; do
      diff -q artifacts/zopfli-headroom/remarks/baseline.checksums $f >/dev/null || echo "MISMATCH $f"; done
(no output)
```

**`-force-vector-width` does not change zopfli's output**, which is the
opposite of the toy (section 13, where vw8/16/32 reassociated `dot_f64`'s
reduction and changed the answer). The mechanism is directly visible in the
remark counts: the string the toy's `dot_f64` produced on its baseline,
`cannot prove it is safe to reorder floating-point operations`, appears
**0 times in zopfli's 31764 remark lines**. There was no FP-ordering refusal
for the width hint to lift. The structural reason is in section 23:
zopfli has no vectorizable floating-point *reduction* in the hot path. Its
floating point is a map (`calculate_entropy`) and a store (`f32::INFINITY`
fill), and reassociation has nothing to reorder. **This is one target's
evidence that the toy's finding is not universal --- it is not evidence that
the risk is gone.** A target with an f64 accumulator would still be exposed,
and the metadata form of the hint is still untested (section 13).

Six configurations were skipped for timing, all with a `.text` section
bit-identical to the baseline's: `g1-tailfold-prefer`, `g1-memcheck24`,
`g1-memcheck128`, `g3-loop-distribute`, `g3-loop-flatten`, `g4-prefer256`.
Two of them (`g1-tailfold-prefer` +10 remark lines, `g3-loop-distribute`
+353) would have gone to the timer on a remark diff alone --- **exactly the
same two knobs as on the toy**, which is a second target confirming section
17's procedural finding that the `.text` hash is the sharper criterion.
`g4-prefer256` producing identical code says znver3 already prefers 256-bit,
as SPEC.ja.md 3 expected.

### 26. Timing: 26 configurations, interleaved, holdout inputs

```
$ scripts/bench.py run --cpu 2 --warmup 2 --runs 8 \
      --label baseline=... (26 labels) \
      --workload text=.../hold-text.dat --workload binary=... --workload json=... \
      --out artifacts/zopfli-headroom/headroom.json
$ scripts/bench.py stats artifacts/zopfli-headroom/headroom.json --base baseline \
      --seed 20260921 --resamples 10000 --mde 0.03
```

780 timed samples (26 labels x 3 workloads x 8 rounds), warmup 2, one single
invocation so all 26 are genuinely round-robin against the same baseline
rounds. Speed ratio = `t_baseline / t_config`; **> 1 means faster than the
PGO baseline.**

| config | aggregate ratio | 95% CI | half-width | abs change | beyond MDE 3%? |
|---|---|---|---|---|---|
| baseline | 1.0000 | [1.0000, 1.0000] | 0.00% | 0.00% | no |
| g0-align5 | 0.9987 | [0.9960, 1.0015] | 0.28% | 0.13% | no |
| g1-maxbw | 1.0010 | [0.9983, 1.0037] | 0.27% | 0.10% | no |
| g1-vw8 | 1.0035 | [1.0016, 1.0056] | 0.20% | 0.35% | no |
| g1-vw16 | 0.9983 | [0.9952, 1.0012] | 0.30% | 0.17% | no |
| g1-vw32 | 0.9988 | [0.9966, 1.0011] | 0.22% | 0.12% | no |
| g1-maxbw-vw32 | 0.9989 | [0.9970, 1.0009] | 0.20% | 0.11% | no |
| g1-ic1 | 0.9997 | [0.9975, 1.0021] | 0.23% | 0.03% | no |
| g1-ic2 | 1.0029 | [1.0014, 1.0047] | 0.16% | 0.29% | no |
| g1-ic4 | 0.9998 | [0.9977, 1.0021] | 0.22% | 0.02% | no |
| g1-tfstyle-data | 1.0009 | [0.9988, 1.0034] | 0.23% | 0.09% | no |
| g1-tfstyle-data-and-control | 0.9997 | [0.9963, 1.0031] | 0.34% | 0.03% | no |
| g2-inline325 | 1.0017 | [0.9976, 1.0052] | 0.38% | 0.17% | no |
| g2-inline500 | 0.9823 | [0.9560, 0.9989] | 2.14% | 1.77% | no |
| g2-inline1000 | 0.9930 | [0.9853, 0.9994] | 0.70% | 0.70% | no |
| g2-unroll-thr300 | 1.0008 | [0.9988, 1.0029] | 0.21% | 0.08% | no |
| g2-unroll-thr1000 | 1.0076 | [1.0015, 1.0131] | 0.58% | 0.76% | no |
| g2-unroll-max2 | 1.0017 | [0.9761, 1.0174] | 2.06% | 0.17% | no |
| g2-unroll-max8 | 0.9812 | [0.9462, 1.0016] | 2.77% | 1.88% | no |
| g2-unroll-runtime | 0.9966 | [0.9846, 1.0039] | 0.97% | 0.34% | no |
| g3-slp-neg20 | 0.9866 | [0.9788, 0.9926] | 0.69% | 1.34% | no |
| g3-slp-100 | 0.9991 | [0.9924, 1.0035] | 0.56% | 0.09% | no |
| g3-unswitch200 | 1.0069 | [1.0021, 1.0111] | 0.45% | 0.69% | no |
| g3-gvn-hoist | 1.0027 | [1.0003, 1.0056] | 0.27% | 0.27% | no |
| g4-prefer128 | 0.9988 | [0.9969, 1.0010] | 0.20% | 0.12% | no |
| g4-v3 | 0.9978 | [0.9957, 1.0001] | 0.22% | 0.22% | no |

Per workload, mean wall time and the speed ratio with its 95% CI (26 labels x 3 workloads x 8 rounds):

| config | text ms | binary ms | json ms | text ratio [95% CI] | binary ratio [95% CI] | json ratio [95% CI] |
|---|---|---|---|---|---|---|
| baseline | 2680.7 | 1634.6 | 2676.7 | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] | 1.0000 [1.0000, 1.0000] |
| g0-align5 | 2680.8 | 1643.4 | 2672.6 | 0.9999 [0.9977, 1.0022] | 0.9946 [0.9902, 0.9994] | 1.0015 [0.9971, 1.0063] |
| g1-ic1 | 2673.0 | 1639.3 | 2679.0 | 1.0029 [1.0008, 1.0051] | 0.9971 [0.9929, 1.0015] | 0.9992 [0.9951, 1.0025] |
| g1-ic2 | 2657.5 | 1635.7 | 2675.3 | 1.0087 [1.0064, 1.0119] | 0.9993 [0.9957, 1.0029] | 1.0006 [0.9970, 1.0049] |
| g1-ic4 | 2678.1 | 1637.9 | 2675.5 | 1.0010 [0.9977, 1.0049] | 0.9980 [0.9957, 1.0006] | 1.0005 [0.9963, 1.0041] |
| g1-maxbw | 2676.6 | 1633.3 | 2675.2 | 1.0015 [0.9981, 1.0042] | 1.0008 [0.9988, 1.0032] | 1.0006 [0.9955, 1.0060] |
| g1-maxbw-vw32 | 2678.2 | 1642.1 | 2676.0 | 1.0009 [1.0000, 1.0018] | 0.9955 [0.9927, 0.9983] | 1.0003 [0.9963, 1.0049] |
| g1-tfstyle-data | 2677.5 | 1633.3 | 2674.3 | 1.0012 [0.9984, 1.0049] | 1.0008 [0.9984, 1.0030] | 1.0009 [0.9976, 1.0045] |
| g1-tfstyle-data-and-control | 2677.7 | 1641.4 | 2671.2 | 1.0011 [0.9986, 1.0036] | 0.9959 [0.9885, 1.0021] | 1.0021 [0.9968, 1.0073] |
| g1-vw16 | 2682.2 | 1642.8 | 2675.8 | 0.9994 [0.9968, 1.0023] | 0.9950 [0.9900, 0.9984] | 1.0004 [0.9936, 1.0069] |
| g1-vw32 | 2676.4 | 1642.7 | 2677.2 | 1.0016 [0.9994, 1.0035] | 0.9951 [0.9921, 0.9982] | 0.9998 [0.9955, 1.0038] |
| g1-vw8 | 2662.4 | 1635.4 | 2665.4 | 1.0069 [1.0043, 1.0097] | 0.9995 [0.9950, 1.0031] | 1.0043 [1.0011, 1.0073] |
| g2-inline1000 | 2686.9 | 1645.4 | 2709.4 | 0.9977 [0.9944, 1.0011] | 0.9934 [0.9883, 0.9990] | 0.9879 [0.9673, 1.0015] |
| g2-inline325 | 2668.5 | 1638.3 | 2669.1 | 1.0046 [1.0015, 1.0080] | 0.9977 [0.9852, 1.0067] | 1.0029 [0.9992, 1.0062] |
| g2-inline500 | 2683.3 | 1720.7 | 2680.0 | 0.9990 [0.9952, 1.0023] | 0.9499 [0.8739, 0.9954] | 0.9988 [0.9901, 1.0057] |
| g2-unroll-max2 | 2628.0 | 1617.7 | 2745.0 | 1.0201 [1.0168, 1.0238] | 1.0105 [1.0047, 1.0153] | 0.9751 [0.9028, 1.0188] |
| g2-unroll-max8 | 2677.4 | 1636.4 | 2833.5 | 1.0012 [0.9983, 1.0042] | 0.9989 [0.9945, 1.0035] | 0.9447 [0.8472, 1.0050] |
| g2-unroll-runtime | 2668.9 | 1635.8 | 2714.1 | 1.0044 [1.0022, 1.0065] | 0.9993 [0.9958, 1.0028] | 0.9863 [0.9520, 1.0068] |
| g2-unroll-thr1000 | 2638.7 | 1623.9 | 2675.7 | 1.0159 [1.0136, 1.0191] | 1.0066 [1.0016, 1.0116] | 1.0004 [0.9845, 1.0132] |
| g2-unroll-thr300 | 2673.1 | 1637.1 | 2674.1 | 1.0029 [0.9990, 1.0061] | 0.9984 [0.9959, 1.0007] | 1.0010 [0.9959, 1.0066] |
| g3-gvn-hoist | 2664.6 | 1634.5 | 2671.4 | 1.0060 [1.0031, 1.0098] | 1.0001 [0.9976, 1.0024] | 1.0020 [0.9968, 1.0071] |
| g3-slp-100 | 2669.0 | 1634.3 | 2696.3 | 1.0044 [1.0024, 1.0070] | 1.0002 [0.9986, 1.0017] | 0.9927 [0.9729, 1.0055] |
| g3-slp-neg20 | 2679.2 | 1674.4 | 2722.8 | 1.0005 [0.9977, 1.0049] | 0.9762 [0.9726, 0.9796] | 0.9831 [0.9606, 0.9980] |
| g3-unswitch200 | 2649.8 | 1628.1 | 2663.4 | 1.0116 [1.0093, 1.0146] | 1.0040 [1.0000, 1.0087] | 1.0050 [0.9948, 1.0120] |
| g4-prefer128 | 2674.2 | 1642.7 | 2679.4 | 1.0024 [0.9998, 1.0055] | 0.9951 [0.9925, 0.9978] | 0.9990 [0.9950, 1.0029] |
| g4-v3 | 2681.4 | 1646.7 | 2673.6 | 0.9997 [0.9976, 1.0022] | 0.9926 [0.9897, 0.9955] | 1.0012 [0.9980, 1.0048] |

**No configuration moves the aggregate by as much as 2%, and none reaches the
3% MDE.** Two per-workload figures cross the MDE and both are regressions:

```
  - g2-inline500/binary  -5.01% CI [-12.61%, -0.46%]
  - g2-unroll-max8/json  -5.53% CI [-15.28%, +0.50%]
```

**Both are single-sample outliers, not effects.** The raw samples say so
directly:

```
g2-inline500   binary  2246.8  1643.3  1639.3  1647.8  1641.9  1659.1  1655.0  1632.7
g2-unroll-max8 json    2653.2  2651.5  3957.0  2666.8  2671.8  2696.6  2684.5  2686.6
g2-unroll-max2 json    2643.2  2636.0  3496.9  2631.9  2640.4  2654.5  2630.5  2626.5
baseline       binary  1641.7  1628.1  1632.5  1623.6  1632.8  1638.3  1642.7  1637.1
```

One round in each case is 35-50% slow while every other round sits inside
1%. This is WSL2 doing something else for a moment; the A/A run (same
harness, same pinning, 15 rounds) had no such sample. n=8 is too few to
absorb one. A median-based cross-check over the same data
(`artifacts/zopfli-headroom/median-crosscheck.txt`) puts **every**
configuration within [0.9913, 1.0154] on the geomean and **max |per-case
change| = 2.12%**. In full (ratio = median(baseline) /
median(config); `artifacts/` is git-ignored, so the table is repeated here):

| config | text ratio | binary ratio | json ratio | geomean |
|---|---|---|---|---|
| g2-unroll-max2 | 1.0180 | 1.0129 | 1.0152 | 1.0154 |
| g2-unroll-thr1000 | 1.0148 | 1.0052 | 1.0075 | 1.0092 |
| g3-unswitch200 | 1.0103 | 1.0036 | 1.0116 | 1.0085 |
| g1-ic2 | 1.0072 | 1.0017 | 1.0020 | 1.0036 |
| g2-inline325 | 1.0032 | 1.0035 | 1.0034 | 1.0034 |
| g3-gvn-hoist | 1.0053 | 1.0014 | 1.0033 | 1.0033 |
| g1-vw8 | 1.0052 | 1.0014 | 1.0026 | 1.0031 |
| g3-slp-100 | 1.0033 | 1.0022 | 1.0029 | 1.0028 |
| g2-unroll-runtime | 1.0023 | 1.0001 | 1.0037 | 1.0020 |
| g1-tfstyle-data | 1.0000 | 1.0025 | 1.0014 | 1.0013 |
| g1-maxbw | 1.0001 | 1.0015 | 1.0016 | 1.0011 |
| g1-tfstyle-data-and-control | 0.9988 | 0.9989 | 1.0040 | 1.0005 |
| g2-unroll-max8 | 1.0005 | 1.0008 | 1.0000 | 1.0004 |
| g2-unroll-thr300 | 1.0004 | 0.9991 | 1.0015 | 1.0003 |
| g1-ic4 | 1.0002 | 0.9988 | 1.0016 | 1.0002 |
| baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| g1-ic1 | 1.0002 | 1.0013 | 0.9984 | 1.0000 |
| g1-vw32 | 1.0023 | 0.9960 | 1.0015 | 0.9999 |
| g1-maxbw-vw32 | 1.0007 | 0.9965 | 1.0024 | 0.9998 |
| g4-prefer128 | 1.0012 | 0.9962 | 1.0010 | 0.9995 |
| g2-inline500 | 0.9960 | 0.9935 | 1.0037 | 0.9977 |
| g0-align5 | 0.9979 | 0.9937 | 1.0014 | 0.9977 |
| g1-vw16 | 0.9974 | 0.9963 | 0.9990 | 0.9976 |
| g4-v3 | 0.9976 | 0.9930 | 1.0017 | 0.9975 |
| g2-inline1000 | 0.9949 | 0.9939 | 0.9977 | 0.9955 |
| g3-slp-neg20 | 0.9988 | 0.9788 | 0.9964 | 0.9913 |
best  g2-unroll-max2 geomean 1.0154
worst g3-slp-neg20 geomean 0.9913
max |per-case change| = 2.12%


To settle the three configurations whose medians looked best, plus the worst
one, a confirmatory run at n=25 warmup 3 (`artifacts/zopfli-headroom/
confirm.json`, 420 samples, same harness and pinning):

| config | aggregate ratio | 95% CI | text | binary | json |
|---|---|---|---|---|---|
| g2-unroll-max2 | **1.0155** | [1.0143, 1.0167] | +1.65% | +1.73% | +1.27% |
| g2-unroll-thr1000 | 1.0093 | [1.0083, 1.0105] | +1.05% | +1.04% | +0.71% |
| g3-unswitch200 | 1.0074 | [1.0060, 1.0087] | +0.87% | +0.60% | +0.74% |
| g3-slp-neg20 | 0.9899 | [0.9885, 0.9914] | -0.32% | -2.14% | -0.55% |

All four are **real** (the CI excludes 1 in every case, and every per-workload
CI excludes 1 too) and all four are **well under the 3% MDE**. The largest
genuine effect any global knob has on zopfli is `-unroll-max-count=2` at
**+1.55% [+1.43%, +1.67%]** --- about half the MDE.

### 27. What the knobs actually did to the loops

The flatness is not "the knobs did nothing". They changed zopfli's own
vectorization decisions, and the time did not follow.

`-force-vector-interleave=1` (`g1-ic1`, aggregate 0.9997, i.e. **0.03%**)
changes the interleave count of all three of zopfli's own vectorized loops:

```
$ cd artifacts/zopfli-headroom/remarks
$ comm -23 baseline.decisions g1-ic1.decisions | grep -E 'src/(lz77|squeeze)'
remark: src/lz77.rs:303:26: vectorized loop (vectorization width: 4, interleaved count: 4)
remark: src/lz77.rs:563:21: vectorized loop (vectorization width: 16, interleaved count: 4)
remark: src/squeeze.rs:265:5: vectorized loop (vectorization width: 8, interleaved count: 4)
$ comm -13 baseline.decisions g1-ic1.decisions | grep -E 'src/(lz77|squeeze)'
remark: src/lz77.rs:303:26: vectorized loop (vectorization width: 4, interleaved count: 1)
remark: src/lz77.rs:563:21: vectorized loop (vectorization width: 16, interleaved count: 1)
remark: src/squeeze.rs:265:5: vectorized loop (vectorization width: 8, interleaved count: 1)
```

IC 4 -> IC 1 on the `sublen` fill inside the 42%-of-profile
`find_longest_match_loop`, on `get_histogram_at`'s u32 copy and on the `costs`
fill --- **and the aggregate moves 0.03%.** For comparison, the same knob cost
the toy 26.6%.

`-force-vector-width=32` (`g1-vw32`, -0.12%) pushes the shared `iter::range`
and `slice::iter` loops to VF 32 and adds two `Vectorized horizontal
reduction` lines; `-vectorizer-maximize-bandwidth` (`g1-maxbw`, +0.10%) takes
`slice/iter/macros.rs:279:24` --- the same DebugLoc that cost the toy 54.7% ---
from VF 4 IC 4 to VF 32 IC 1. On zopfli that loop is inside
`calculate_entropy`, 0.15% of the profile, and nothing measurable happens.

`-unroll-max-count=2`, the one knob with a real effect, barely shows up in
the remarks at all:

```
$ comm -23 baseline.decisions g2-unroll-max2.decisions
remark: library/core/src/iter/range.rs:1103:12: unrolled vectorized loop by a factor of 4
remark: library/core/src/num/uint_macros.rs:1043:17: unrolled vectorized loop by a factor of 9
$ comm -13 baseline.decisions g2-unroll-max2.decisions
remark: library/core/src/iter/range.rs:1103:12: unrolled vectorized loop by a factor of 2
remark: library/core/src/num/uint_macros.rs:1043:17: unrolled vectorized loop by a factor of 2
```

Two lines. Its full normalized diff is +22/-25 and its `.text` changes, so
most of what it did was to **scalar** unrolling, which LLVM does not emit a
remark for. **The remark diff systematically under-reports the unroll
dimension**; the `.text` hash is what catches it. That the best knob on this
target is one that *reduces* unrolling (front-end pressure on a small hot
loop, presumably) is worth carrying to Stage 1.

### 28. Stopping rule (SPEC.ja.md 6.3), applied for real

> Across groups 1-3, if (a) no configuration's aggregate speed-ratio CI lower
> bound exceeds the minimum effect size, **and** (b) no configuration
> improves a single case beyond the minimum effect size, record "this target
> is flat under the hint method" and swap the target.

Correctness precondition (added to the rule by section 16's toy experience):
**satisfied trivially --- all 31 configurations produce identical output**, so
no configuration is excluded and the rule reads on the full set. Evaluated
with MDE = 3.00% over the 25 timed configurations of groups 1-4:

- **(a)** The highest aggregate CI lower bound among all configurations is
  **1.0143** (`g2-unroll-max2`, n=25 confirmation, CI [1.0143, 1.0167]),
  against the required 1.03. In the n=8 sweep itself the highest is 1.0021
  (`g3-unswitch200`). **Not satisfied.**
- **(b)** No configuration improves any single case beyond 3%. The largest
  genuine per-case improvement is **+1.73%** (`g2-unroll-max2` on `binary`,
  CI [+1.58%, +1.90%]). The only two per-case figures beyond the MDE are
  regressions and are single-sample outliers. **Not satisfied.**

**Outcome for zopfli: (a) no and (b) no --- "this target is flat under the
hint method; swap the target."**

Because (a) is not satisfied, SPEC.ja.md 1.3-1 --- "there exists at least one
global dimension that moves the aggregate speed ratio by twice the minimum
effect size" --- is **not met on zopfli**. Group 4 was run here too
(SPEC.ja.md 13 day-0 item 6), and it does not change the outcome:
`-Ctarget-feature=+prefer-256-bit` produces byte-identical code, `+prefer-128-bit`
is -0.12% and `-Ctarget-cpu=x86-64-v3` is -0.22%.

**What this outcome is, and what it is not.** It is a statement about
*global* knobs: one setting applied to the whole build. SPEC.ja.md 6.3 says
so explicitly --- "a global sweep is neither an upper nor a lower bound",
which is why the rule is asymmetric. The per-site case is not dead on the
evidence here, and section 23 named two concrete reasons: `src/cache.rs:108`
and `src/hash.rs:150` are hot (10.45% and 9.62% of block counts), integer,
and declined on **cost**, which is the one reason class a loop hint can
overturn. What the global sweep shows is that no *uniform* setting reaches
them without paying for it elsewhere.

**The rule's own answer is "swap the target", and that is what is recorded.**
SPEC.ja.md 6.4 asks for one decision per target at the end of its Stage 0.
That decision is not Stage 0's to make against a pre-registered rule, so what
follows is a *recommendation* with the evidence for it, for the spec owner to
accept or decline:

> **Recommended: do not swap zopfli out; record "flat under global hints" and
> carry it into Stage 1 as the transfer target and into Stage 2 as the
> site-plan target, without promoting it to a headline performance claim.**
> The evidence for the exception is post-hoc and is listed so it can be
> weighed as such: (i) the rule is explicitly a statement about *uniform*
> settings and SPEC.ja.md 6.3 says a global sweep bounds nothing; (ii)
> section 23 found two hot, integer, **cost**-declined loops
> (`src/cache.rs:108` at 10.45% and `src/hash.rs:150` at 9.62%), which is the
> one reason class a loop hint can overturn; (iii) SPEC.ja.md 1.3-5 needs two
> transfer targets and zopfli is one of the two. The Stage 2 heterogeneity
> gate (SPEC.ja.md 8.3-3) would then be the real test; if that also fails,
> zopfli is reported as a negative transfer result, which is still one of the
> five pieces of evidence SPEC.ja.md 1.3 asks for.
>
> **If the rule is applied as written, zopfli is swapped out now** and the
> Stage 1 / Stage 2 transfer slot goes to oxipng or symphonia (SPEC.ja.md
> 6.4). Nothing measured here argues that the rule *mis*fired; it argues that
> its scope is global knobs.

### 29. Implications for the Stage 1 candidate set

What moved anything on zopfli, and in which direction (compare with section
17's toy column --- the two targets disagree on almost every row):

| knob | zopfli | toy | keep as a Stage 1 candidate? |
|---|---|---|---|
| `-unroll-max-count=2` | **+1.55%** aggregate, positive on all three cases, output identical | -0.56% | **yes --- the strongest knob on this target.** Also the one the remark diff nearly misses |
| `-unroll-threshold=1000` | +0.93% | -0.69% | yes |
| `-unswitch-threshold=200` | +0.74% | byte-identical `.text` | yes --- the toy dropped it as inert and it is not inert here |
| `-slp-threshold=-20` | **-1.01%**, -2.14% on `binary` | -1.03% | yes, as a known-negative direction |
| `-vectorizer-maximize-bandwidth` | +0.10% (nothing) | **-18.2%** | keep, but its description must say the direction is target dependent and can be catastrophic |
| `-force-vector-width` 8/16/32 | +0.35% / -0.17% / -0.12%, **output identical** | output **changed** | keep **only behind the correctness gate**. zopfli shows the gate can pass; the toy shows why it exists |
| `-force-vector-interleave` 1/2/4 | 0.03% / +0.29% / 0.02%, though it changes all three of zopfli's own loops | -26.6% / -8.4% / -1.1% | keep. Same knob, same decision change, 900x difference in effect |
| `-inline-threshold` 325/500/1000 | +0.17% / -1.77% / -0.70%; thousands of remark lines move | <= 0.25% | keep; it is the largest remark mover on both targets and moves time on neither |
| `-enable-gvn-hoist` | +0.27% (CI excludes 1) | 0.00% | marginal; keep at low priority |
| `-epilogue-tail-folding-policy`, `-force-tail-folding-style` | `.text` identical or <= 0.09% | <= 0.6% | drop for byte/integer targets |
| `-runtime-memory-check-threshold`, `-enable-loop-distribute`, `-enable-loop-flatten` | byte-identical `.text` | byte-identical `.text` | **drop.** Two targets, no code change |
| `-Ctarget-feature=+prefer-256-bit` | byte-identical `.text` | not run | drop --- znver3 already prefers 256-bit |
| `-Ctarget-feature=+prefer-128-bit`, `-Ctarget-cpu=x86-64-v3` | -0.12% / -0.22% | not run | drop |
| `-enable-early-exit-vectorization` | not swept (default-on, section 12) | default-on | drop |

Five procedural conclusions for Stage 1 and Stage 2:

1. **The candidate set must not be one list.** No knob is good on both
   targets, and the two knobs that matter most (`-force-vector-interleave`,
   `-vectorizer-maximize-bandwidth`) differ by two orders of magnitude
   between them. That is an argument *for* the premise of the project --- a
   per-program decision has something to decide --- and an argument against
   a hand-written default.
2. **`cost` is the class to feed Jev, and it exists on zopfli** (228 lines),
   but only via standalone analysis remarks that the obvious parser misses.
   SPEC.ja.md 7's plan to hand Jev "the source of functions whose loops got a
   `cost` remark" resolves here to `<ZopfliLongestMatchCache as Cache>::try_get`
   and `<ZopfliHash>::update` --- the 2nd and 4th hottest functions. That is a
   workable Stage 1 input.
3. **The `.text` hash decides what to time; the remark diff decides what to
   look at.** Six configurations skipped, two of them (the same two as on the
   toy) with changed remarks and identical code, and one (`-unroll-max-count=2`)
   with a real effect and almost no remark change. Both checks are needed and
   neither is sufficient.
4. **n=8 is not enough on this machine.** One outlier round in 8 produced two
   false "beyond MDE" flags. The sweep should use n >= 15, or the statistic
   should be trimmed; `bench.py stats` currently uses means. Cheap fix, and
   the A/A run already showed n=15 is quiet.
5. **The SPEC.ja.md 7 DebugLoc -> function attribution degrades badly at
   scale.** 29 functions share one `core::iter::range` DebugLoc in this
   binary. The `UNIQUE` subset is usable and the rest is not, which raises the
   value of the Stage 2 plugin dump (it reads the IR and does not have the
   problem) and lowers the value of Stage 1's remark-based function selection.

### 30. Deviations, and what is not done

- **The sweep was run on the holdout inputs**, not the training inputs.
  SPEC.ja.md 7 says the sweep runs on the training workloads and the holdout
  is measured once, after freezing. Done this way on instruction, and
  recorded here because the consequence is real: **the Stage 1 candidate set
  will have been chosen while looking at holdout numbers.** Before Stage 1
  either §7 should be amended, or `gen.py`'s three `hold-*` seeds should be
  changed to produce a fresh holdout (a three-line edit, and the inputs are
  regenerable by construction).
- The n=25 confirmation run is a second pass over the same holdout inputs
  with the same binaries. It changes no conclusion (every configuration was
  under the MDE in both passes) but it is a second look and is listed here
  as one.
- `remark-reason-map.json` still does not exist as a file; the classification
  lives in `REASON_CLASS` in `scripts/remark_attribution.py`, now 26 strings
  covering 1890 of the 2339 reason lines seen on zopfli. 443 lines
  (nine early-exit strings) are deliberately `unknown`.
- The Stage 2 heterogeneity gate, the plugin, and the `vectorize.width`
  metadata FP-reassociation test (section 13's open question) are all still
  open. zopfli cannot answer the last one: it has no vectorizable FP
  reduction.
- Post-hoc attribution with `perf` / `callgrind` (SPEC.ja.md 10) was not
  needed --- no configuration produced a difference worth attributing.
