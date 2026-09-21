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

### 18. Not done today

- Group 4 (`-Ctarget-feature=+prefer-256-bit` / `+prefer-128-bit`,
  `-Ctarget-cpu=x86-64-v3`). SPEC.ja.md 13 day-0 item 6 ties group 4 to the
  stopping-rule decision, which is a zopfli item.
- Everything for zopfli (SPEC.ja.md 13 day-0 items 5 and 6 proper).
- `remark-reason-map.json` is still the nine hand-classified seeds of section
  6; the sweep logs contain many more reason strings that have not been
  classified.
