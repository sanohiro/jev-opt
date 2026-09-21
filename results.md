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
**+1.55% [+1.43%, +1.67%]** --- about half the MDE. Section 31 sweeps the
unroll dimension properly and finds the saturation point one step further
out, at `-unroll-max-count=1`, **+1.59% [+1.30%, +1.82%]**; it also measures
`-unroll-max-count=2` a second time, at +1.43% [+1.24%, +1.62%], which is
how far two independent n=15/n=25 runs of the same binary drift apart here.

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
>
> **Section 31 weakens point (ii) of this recommendation and should be read
> with it.** Estimating the Stage 2 ceiling on those two loops from nine
> extra builds puts it at about +1.6%, half the MDE: the width family does
> not reach either loop at all (byte-identical machine code under every
> forced width, even with the unroller disabled), `src/hash.rs:150` has an
> average trip count below 1 so its `cost` verdict is correct, and the whole
> unroll dimension on `src/cache.rs:108` is worth +1.59%. The honest
> expectation for zopfli's Stage 2 is a negative result.

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
   workable Stage 1 input, with one caveat section 31.2 adds: a `cost`
   classification is **not** by itself evidence of an opportunity.
   `<ZopfliHash>::update`'s loop is `cost`-declined and its average trip
   count is below 1, so the cost model is simply right. A site's trip count
   (which the plugin dump writes, SPEC.ja.md 8.5) has to gate the `cost`
   class before it reaches Jev.
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

### 31. Estimating the Stage 2 ceiling on zopfli without the plugin

Section 28 recorded "flat under global hints" and named two loops as the
reason not to close the book: `src/cache.rs:108` (inside
`<ZopfliLongestMatchCache as Cache>::try_get`, 10.45% of block counts) and
`src/hash.rs:150` (inside `<ZopfliHash>::update`, 9.62%), both hot, both
integer, both declined with a **cost** remark. This section puts a number on
what a per-site hint could do to them, using the sweep's existing logs plus
nine extra builds. No plugin, so this is an estimate and is labelled as one
everywhere below.

Reproduce with:

```
scripts/loop_body_insns.py --loc src/cache.rs:108 --loc src/hash.rs:150 \
    artifacts/zopfli-unroll/bin/{baseline,g5-max1,g2-unroll-max2,g5-max4,g2-unroll-max8,g5-count8}
scripts/func_code_diff.py --match 5Cache7try_get --match 10ZopfliHash6update \
    artifacts/zopfli-headroom/bin/{baseline,g1-maxbw,g1-vw8,g1-vw16,g1-vw32,g1-maxbw-vw32}
TARGET=zopfli SUITE=unroll ONLY='^(g5-|g2-unroll-max2$|g2-unroll-max8$)' \
    RUNS=15 WARMUP=3 scripts/target_headroom.sh
scripts/profdata_hotness.py pgo/zopfli/merged.profdata --top 20 \
    --binary artifacts/zopfli-headroom/bin/baseline
```

Two new scripts: `scripts/loop_body_insns.py` runs SPEC.ja.md 7's attribution
backwards (how many instructions in this binary come from `file:line`, and
what are they) and `scripts/func_code_diff.py` compares one function's
normalised instruction sequence across builds. `scripts/target_headroom.sh`
gained `SUITE=` (output directory, so a probe does not overwrite the main
sweep) and `ONLY=` (a regex over configuration names), plus a group 5 for the
unroll dimension.

#### 31.1 The width family does not reach either loop --- at all

| config | cache.rs:108 remark set | hash.rs:150 remark set | `try_get` code | `ZopfliHash::update` code |
|---|---|---|---|---|
| baseline | 16 `unable to calculate the loop count due to complex control flow` + 16 cost-vec + 16 cost-interleave + 15 `unrolled by 8 with run-time trip count` + 1 `unrolled by 20` | 12 cost-vec + 12 cost-interleave | 712 insns, 0 vector | 88 insns, 0 vector |
| `-vectorizer-maximize-bandwidth` | **identical** | **identical** | **identical** | **identical** |
| `-force-vector-width=8` | **identical** | **identical** | **identical** | **identical** |
| `-force-vector-width=16` | **identical** | **identical** | **identical** | **identical** |
| `-force-vector-width=32` | **identical** | **identical** | **identical** | **identical** |
| `-vectorizer-maximize-bandwidth -force-vector-width=32` | **identical** | **identical** | **identical** | **identical** |
| `-force-vector-interleave=1` | **identical** | **identical** | **identical** | **identical** |

"Identical" is literal in both columns: the multiset of remark lines at that
DebugLoc is the same, and the normalised instruction sequence of the
containing function hashes to the same value (`scripts/func_code_diff.py`
replaces addresses and branch targets with `A`, so relocation does not count
as a change). `try_get` is 712 instructions and `<ZopfliHash>::update` is 88
in every one of these builds, and **neither contains a single
vector-register instruction in any of them**.

The obvious objection is that the unroller got there first and left the
vectorizer nothing. It did not. Three extra builds turn the unroller off and
force the width anyway:

```
$ scripts/loop_body_insns.py --loc src/cache.rs:108 --loc src/hash.rs:150 \
      artifacts/zopfli-unroll/bin/g5-max1 \
      artifacts/zopfli-probe/p1-max1-vw8 \
      artifacts/zopfli-probe/p2-max1-vw16 \
      artifacts/zopfli-probe/p3-max1-maxbw
g5-max1        (-unroll-max-count=1)                      cache.rs:108  50 insns, 0 vector   hash.rs:150  204 insns, 0 vector
p1-max1-vw8    (-unroll-max-count=1 -force-vector-width=8)  ... identical to g5-max1 ...
p2-max1-vw16   (-unroll-max-count=1 -force-vector-width=16) ... identical to g5-max1 ...
p3-max1-maxbw  (-unroll-max-count=1 -vectorizer-maximize-bandwidth) ... identical to g5-max1 ...
```

All three also keep `loop not vectorized: unable to calculate the loop count
due to complex control flow` at `cache.rs:108:17`, and all three produce
output identical to the baseline on all six inputs.

**So the H01 family (`vectorize.width`) is structurally blocked on both
loops, not merely out-competed.** Whatever a Stage 2 plan would write into
`llvm.loop.vectorize.width` for these two sites, the global form of the same
request changes nothing, and the loop-metadata form goes through the same
`LoopVectorizeHints` (SPEC.ja.md 8.4).

#### 31.2 Why: the two loops fail for two different reasons, and the profile says the cost model is right about one of them

**`src/hash.rs:150` is a genuine `cost` decline, and the cost model is
correct.** It carries only the two cost strings --- no legality and no
unsupported string appears at that DebugLoc anywhere in the 31764-line log.
The profile explains the verdict:

```
$ grep -A3 '10ZopfliHash6update:' artifacts/zopfli-day0/profdata-functions.txt
    Counters: 12
    Block counts: [151050803, 5956749, 145094557, 5622022, 5644788,
                   142776781, 142761838, 145093615, 142776781, 142761838, 0, 5956749]
```

Entry count 151,050,803; the `while another_index < array.len() && array_pos
== array[another_index] && ...` body runs 142,776,781 times in total. **The
loop body executes about 0.95 times per call** --- it almost always exits on
the first test. No vectorization factor can pay for a prologue on a loop with
an average trip count below one, so `the cost-model indicates that
vectorization is not beneficial` is not an opportunity, it is the right
answer. This is an important qualification of SPEC.ja.md 8.3: a site
classified `cost` is not automatically a site worth asking Jev about.

**`src/cache.rs:108` is the opposite: a long loop the vectorizer cannot
analyse.**

```
$ grep -A3 '5Cache7try_get:' artifacts/zopfli-day0/profdata-functions.txt
    Counters: 17
    Block counts: [962322, 706227900, 110342610, ...]
```

962,322 calls, hottest block 706,227,900, i.e. **about 734 iterations per
call** of a `sublen[i] = dist; i += 1;` u16 fill --- exactly the shape a width
hint is for. It is nonetheless refused, and the reason at that DebugLoc is
not cost but `unable to calculate the loop count due to complex control
flow` (classified `unknown` in section 23, and on this evidence it behaves
like a legality/analysis refusal). The two cost strings at the same DebugLoc
belong to the interleave decision and to other inline instances; forcing the
width does not remove them.

The one dimension that does reach this loop is unrolling: LLVM already
applies `unrolled loop by a factor of 8 with run-time trip count` to it in
the baseline.

#### 31.3 The unroll dimension, swept properly (group 5, 9 configurations)

```
$ TARGET=zopfli SUITE=unroll ONLY='^(g5-|g2-unroll-max2$|g2-unroll-max8$)' \
      RUNS=15 WARMUP=3 scripts/target_headroom.sh
```

**All nine configurations produce output identical to the baseline on all six
inputs**, so all nine are in the judgement. Timed against the baseline at
n=15 warmup 3 (540 samples, one interleaved invocation, MDE still 3.00%):

| config | knobs | insns at `src/cache.rs:108` | aggregate ratio | 95% CI | text | binary | json |
|---|---|---|---|---|---|---|---|
| baseline | (unroll ×8 runtime) | 615 | 1.0000 | --- | --- | --- | --- |
| g5-max1 | `-unroll-max-count=1` | **50** | **1.0159** | [1.0130, 1.0182] | +2.23% | +0.83% | +1.73% |
| g2-unroll-max2 | `-unroll-max-count=2` | 238 | 1.0143 | [1.0124, 1.0162] | +1.56% | +1.47% | +1.27% |
| g5-max2-runtime-off | `-unroll-max-count=2 -unroll-runtime=false` | --- | 1.0127 | [1.0098, 1.0148] | +1.72% | +0.84% | +1.25% |
| g5-max2-thr1000 | `-unroll-max-count=2 -unroll-threshold=1000` | --- | 1.0110 | [1.0083, 1.0134] | +1.32% | +0.86% | +1.12% |
| g5-max4 | `-unroll-max-count=4` | 354 | 1.0073 | [1.0039, 1.0100] | +0.95% | +0.77% | +0.46% |
| g2-unroll-max8 | `-unroll-max-count=8` | 600 | 1.0026 | [1.0012, 1.0044] | +0.30% | +0.35% | +0.14% |
| g5-count8 | `-unroll-count=8` | 608 | 0.9756 | [0.9647, 0.9821] | -2.63% | -3.09% | -1.60% |
| g5-count4 | `-unroll-count=4` | --- | 0.9730 | [0.9655, 0.9775] | -2.41% | -3.50% | -2.20% |
| g5-count2 | `-unroll-count=2` | --- | 0.9728 | [0.9710, 0.9747] | -1.64% | -3.94% | -2.56% |

Every CI excludes 1, so every one of these is a real effect. The dimension is
**monotone in the unroll cap and saturates**: the less LLVM unrolls, the
faster zopfli runs, and the curve flattens at `-unroll-max-count=1`.

The objdump evidence for the mechanism, not the remarks (section 27: the
remark diff does not report scalar unrolling):

```
$ scripts/loop_body_insns.py --loc src/cache.rs:108 ...
baseline        615 instructions at cache.rs:108   (try_get 311 + lz77_optimal 304)
g2-unroll-max8  600
g5-max4         354
g2-unroll-max2  238
g5-max1          50
```

and per containing function:

```
$ # instructions in <ZopfliLongestMatchCache as Cache>::try_get, by source line
baseline        712 total, 311 at cache.rs:108, 98 at cache.rs:107
g2-unroll-max2  443 total, 118 at cache.rs:108,  42 at cache.rs:107
g5-max1         345 total,  27 at cache.rs:108,  38 at cache.rs:107
```

`-unroll-count=N` (force a count on **every** loop) goes the other way and is
the worst family in the whole study: it inflates `src/hash.rs:150` from 207
instructions to **1022** and destroys the one genuinely useful vectorized
loop in the hottest function, `src/lz77.rs:563` dropping from 23
instructions with 2 vector registers to 4 with none.

#### 31.4 The Stage 2 ceiling

Two facts bound it.

**First, the best unroll setting is already a de-facto site intervention.**
Profile-weighted, `-unroll-max-count=1` changes very little:

```
$ # normalised code hash per symbol, baseline vs g5-max1, weighted by profdata share
   symbols compared 451, machine code changed in 22
   profile share held by the changed symbols: 37.25%
      24.63%  zopfli::squeeze::lz77_optimal::<ZopfliLongestMatchCache>
      10.45%  <ZopfliLongestMatchCache as Cache>::try_get
       1.24%  <Lz77Store>::follow_path::<ZopfliLongestMatchCache>
       0.36%  zopfli::katajainen::length_limited_code_lengths
       0.25%  zopfli::deflate::optimize_huffman_for_rle
       0.15%  <SymbolStats>::get_statistics
```

`zopfli::lz77::find_longest_match_loop` (42.20%) and `<ZopfliHash>::update`
(9.62%) are **byte-identical** under it. The two symbols that do change and
that matter are precisely the two hosts of the `cache.rs:108` loop, holding
35.08% of block counts between them; the remaining 20 changed symbols hold
about 2.2%. So the global knob is already hitting essentially one site, and
a per-site hint could reclaim at most that ~2.2% of collateral.

**Second, the measured value of the whole dimension on that site is
+1.59%.** Driving `cache.rs:108` from 615 instructions to 50 --- the entire
span the unroller can produce, from ×8 runtime unrolling to none --- buys
**+1.59% [+1.30%, +1.82%]** on the aggregate.

Amdahl, done both ways:

- *Share-based ceiling, useless as expected.* The two functions hold 20.07%
  of block executions, so removing their loops entirely would give
  1/(1−0.2007) = **+25.1%**. SPEC.ja.md 8.3-2 already warns that
  `1/(1−S)` from counts × instructions is a rough order-of-magnitude figure;
  here it is 16x above anything observed and carries no information.
- *Empirically anchored ceiling.* `cache.rs:108`: **+1.59%**, measured, with
  the global knob already at its most extreme setting for that loop, plus at
  most ~2.2% of profile share worth of collateral a site hint could avoid.
  `hash.rs:150`: **0%** --- average trip count below 1, no family reaches it,
  and the only knob that changes its code (`-unroll-count`) is a −2.4% to
  −2.7% regression. H01 (`vectorize.width`) on both: **0%**, measured
  byte-for-byte.

**Verdict, recorded: the Stage 2 ceiling from these two loops is about
+1.6%, roughly half the MDE of 3.00%. Per-site hints on zopfli's two
cost-declined hot loops cannot reach the minimum effect size.** The
heterogeneity gate of SPEC.ja.md 8.3-3 would therefore be expected to fail
on zopfli, and the recommendation in section 28 (keep zopfli as the transfer
target, do not promote it) should be read with that in mind: the honest
expectation is a negative Stage 2 result on this target, reported as such.

This is an estimate from global knobs, not a measurement of loop metadata.
It could be wrong in one direction only: if `llvm.loop.vectorize.width` on a
single site behaves differently from `-force-vector-width` on every site.
Section 31.1 makes that unlikely for these two loops --- the width request
does not change their code even when nothing else competes for them --- but
the plugin is what settles it.

#### 31.5 How much of zopfli is out of reach in principle

```
$ scripts/profdata_hotness.py pgo/zopfli/merged.profdata --top 20 \
      --binary artifacts/zopfli-headroom/bin/baseline
these 20 functions hold 99.16% of the total block count
of which 24.78 percentage points sit in functions whose own machine code
contains no vector-register instruction
```

| function | share | own machine code | reachable by a loop hint? |
|---|---|---|---|
| `lz77::find_longest_match_loop` | 42.20% | 270 insns, **9 vector** | the 9 are the `src/lz77.rs:563` u16 fill (23 insns), already VF 16 IC 4. The rest is the data-dependent match scan: no |
| `squeeze::lz77_optimal::<..>` | 24.63% | 3533 insns, 823 vector | fat-LTO inline host; contains the inlined copies of `cache.rs:108` (304 insns) and `hash.rs:150` (88 insns). Function-level classification is meaningless here |
| `<ZopfliLongestMatchCache as Cache>::try_get` | 10.45% | 712 insns, **0 vector** | unroll only, worth +1.59% (31.4) |
| `<ZopfliHash>::update` | 9.62% | 88 insns, **0 vector** | no (trip count < 1) |
| `squeeze::get_cost_stat` | 3.69% | 42 insns, 7 vector, 1 backward branch | its loop averages 166329758/64512000 = **2.6 iterations** and the FP is a scalar `vaddsd` chain: no |
| `<ZopfliLongestMatchCache>::max_sublen` | 2.42% | inlined away, no symbol | --- |
| 11 further functions (`follow_path` 1.24%, `Cache::store` 1.36%, `boundary_pm` 0.65%, `find_longest_match` 0.73%, `append_store_item` 0.26%, `lit_len_dist` 0.16%, `hash::new` 0.08%, `add_huffman_bits` 0.14%, `add_bits` 0.09%, ...) | | **0 vector** each | --- |

Adding it up: **24.78% of block executions are in functions with no
vectorized code at all**, and adding `find_longest_match_loop`, which is
96.7% scalar by instruction count, brings it to **66.98% of the profile in
code that is essentially entirely scalar.** The top five functions hold
90.59%; of those, only `get_cost_stat` (3.69%) is effectively loopless, and
the rest are loops the vectorizer refused on analysis or legality grounds.

This is the zopfli answer to the question SPEC.ja.md 6.1-4 asks of jaq: the
share that no hint can reach. jaq's gate is 70% of `total_score` from an
interpreter layer; zopfli's equivalent figure is ~67%, and it comes not from
indirect calls and refcounting but from **data-dependent early-exit byte
scans** --- LZ77 match comparison, hash chain walking. Different cause, same
consequence for a loop-metadata method.

#### 31.6 One script bug found while doing this

`TARGET=zopfli source scripts/target_common.sh` does **not** work: bash
restores a temporary assignment when the builtin returns, so `TARGET` is
empty again by the time a later `run_correctness` call runs its `case`, and
the function silently did nothing. `export TARGET=zopfli` first. A `*)` arm
that returns an error was added to `run_correctness` so it can never fail
quietly again. The `scripts/toy_*.sh` and `TARGET=x scripts/target_*.sh`
forms were never affected (those set the variable in a child process).

## Stage 0 (jaq) --- the article's intended target

Date: 2026-09-21/22, same machine and same pinned toolchain as the toy and
zopfli sections (rustc 1.100.0-nightly bba531001 / LLVM 23.1.1). This covers
SPEC.ja.md 13 day-0 items 2-6 for jaq plus **SPEC.ja.md 6.1-4's 70%
interpreter-layer gate**, which SPEC.ja.md 13 item 16 puts at the entrance to
jaq and which was never applied to the toy or to zopfli.

Sections are numbered from 50 to leave room for the oxipng work running
beside this one.

Reproduce with:

```
python3 targets/jaq/workloads/gen.py                # six inputs, fixed seeds
export TARGET=jaq                                   # NOT `TARGET=jaq source` (section 31.6)
REUSE_PROFDATA=0 REPRO=0 DEBUG0=0 scripts/target_pgo_baseline.sh
scripts/interp_share.py pgo/jaq/merged.profdata \
    --binary target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/jaq \
    --top 20 --crates --tsv artifacts/jaq-day0/interp-share-all.tsv
scripts/remark_attribution.py \
    --bin target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/jaq \
    --log remarks/jaq/baseline-build.log \
    --src-prefix targets/jaq/src --out artifacts/jaq-attr --top 30
scripts/target_aa.sh 15 3
BENCH_SET=training ONLY='^(g[0-3]-|g5-(max1|max4|count2|count4)$)' \
    RUNS=15 WARMUP=3 scripts/target_headroom.sh
```

**New in this stage.** `scripts/interp_share.py` (the 6.1-4 gate's arithmetic
without the plugin: profile weight, a trip proxy, instruction and
vector-register counts and a machine-code backedge count per symbol) and
`scripts/norm_code_diff.py` (whole-binary normalised code comparison, needed
because jaq's `.text` hash is not reproducible --- section 53).
`scripts/target_common.sh` gained a `jaq` arm plus three target-independent
knobs used by it: `BENCH_SET=holdout|training` (SPEC.ja.md 7 puts the sweep on
the training inputs), `BENCH_STDOUT=pipe|devnull` and `BENCH_GAP_MS`.
`scripts/bench.py` gained the matching `--stdout` and `--gap-ms`. All four
default to the toy/zopfli behaviour, so every command quoted in the earlier
sections still runs unchanged.

### 50. The target: vendored jaq v3.1.1, driven entirely from the environment

```
$ git submodule add https://github.com/01mf02/jaq targets/jaq/src
$ cd targets/jaq/src && git checkout c866e70303b5dbc37d83a0b0cbacf10e90af9c8c
$ git log -1 --format='%H %ci' && git describe --tags
c866e70303b5dbc37d83a0b0cbacf10e90af9c8c 2026-08-05 09:34:37 +0200
v3.1.1
```

Pinned to the **v3.1.1** tag (the latest release), commit
`c866e70303b5dbc37d83a0b0cbacf10e90af9c8c`. It is a cargo **workspace**:
`jaq-core` (the interpreter), `jaq-json` (the `Val` type and the JSON
reader/writer), `jaq-std`, `jaq-fmts`, `jaq-all` and the `jaq` bin. The bin
package is built on its own (`--manifest-path targets/jaq/src/jaq/Cargo.toml`)
with its default features, which include **`mimalloc`**; that choice is what
a user gets from `cargo install jaq` and it has consequences recorded in
sections 53 and 54.

**Nothing in the submodule is edited.** Everything is driven from the
environment exactly as the product path will drive it:
`CARGO_PROFILE_RELEASE_{OPT_LEVEL=3,LTO=fat,CODEGEN_UNITS=1,DEBUG=1,PANIC=unwind}`,
`CARGO_ENCODED_RUSTFLAGS`, `RUSTUP_TOOLCHAIN=nightly-2026-09-21`, explicit
`--target x86_64-unknown-linux-gnu`, a separate `CARGO_TARGET_DIR` per
variant, and `--locked`. `git status` in the submodule stays clean across
every build below.

**One extra profile override this target needs.** jaq's workspace
`[profile.release]` is

```
$ sed -n '/^\[profile\.release\]/,$p' targets/jaq/src/Cargo.toml
[profile.release]
strip = true
codegen-units = 1
```

`strip = true` would remove the symbol table and DWARF from every build,
which silently breaks every analysis script in this repository at once (`nm`
returns nothing, so `profdata_hotness.py --binary` reports every function
"inlined away"; `addr2line` answers `??`, so `remark_attribution.py` and
`loop_body_insns.py` attribute nothing). The `jaq` arm of
`scripts/target_common.sh` therefore exports
**`CARGO_PROFILE_RELEASE_STRIP=none`** alongside the other profile
overrides, and the binaries are stripped by the harness before timing, as on
the other targets. This is recorded as a frozen build dimension
(SPEC.ja.md 3).

Reference arm R (SPEC.ja.md 9) --- the effective release profile if
`jev-opt` overrode nothing --- is therefore **opt-level 3, `lto` unset
(off/"thin-local"), `codegen-units` 1, `strip = true`, `debug` unset (=0), no
`target-cpu=native`, no PGO**. Unlike zopfli, this crate does set
`codegen-units`, so arm R already has one of the three global settings.

### 51. Disqualification filter (SPEC.ja.md 6.1-2): memchr, and a C allocator the filter cannot see

```
$ cd targets/jaq/src/jaq && cargo tree -e normal --locked | grep -iE 'memchr|simd|wide|std_detect'
│   │   │   └── memchr v2.8.3
│   │   │   ├── memchr v2.8.3
│   ├── memchr v2.8.3
$ grep -rlE 'core::arch|_mm_|_mm256|target_feature' targets/jaq/src/src targets/jaq/src/*/src
(no match)
```

`memchr` enters three times --- through `aho-corasick` and `bstr` (both used
by `jaq-std`'s regex and string builtins, and by `jaq-fmts`) and directly
through `rustyline`. **None of jaq's own workspace crates contains a line of
hand-written SIMD**, and neither does `hifijson`, the JSON lexer that turns
out to hold the hottest loop in the program (section 54).

Judged by profile share rather than by name (results.md section 20's rule):

```
$ scripts/profdata_hotness.py pgo/jaq/merged.profdata --grep memchr
8102 function records, total block count 3438334653
functions matching 'memchr': 50, summed block count 0 (0.000000% of the total)
$ scripts/profdata_hotness.py pgo/jaq/merged.profdata --grep aho_corasick
functions matching 'aho_corasick': 403, summed block count 0 (0.000000% of the total)
$ scripts/profdata_hotness.py pgo/jaq/merged.profdata --grep hifijson
functions matching 'hifijson': 66, summed block count 1473121794 (42.844049% of the total)
```

**Verdict: jaq is not disqualified.** Neither `memchr` nor `aho-corasick`
executes a single instrumented block on these workloads --- the JSON path
does not go through them at all. What it does go through is `hifijson`, at
**42.8%** of all block executions, and `hifijson` has no SIMD: its lexer is
plain `slice::iter().position(..)` (section 54). Recorded as a filter hit with the number
that overrides it.

**A third check this target forces, and the filter as written misses it.**

```
$ cd targets/jaq/src/jaq && cargo tree -e normal,build --locked | grep -iE 'cc v|-sys v'
│       └── cc v1.4.0
│   └── dirs-sys v0.5.0
│   └── libmimalloc-sys v0.1.49
$ ls target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/build/libmimalloc-sys/*/out/libmimalloc.a
```

jaq's default features pull in **mimalloc**, which is C compiled by `cc` into
`libmimalloc.a` and linked in. That code is invisible to `-Cllvm-args`, to
`-Ctarget-cpu`, to `-Cprofile-generate` and to the remark stream, all at
once. The consequence for everything below is concrete: `__rust_alloc` and
`__rust_dealloc` appear in the profile as **one-instruction jump thunks**
(2.06% and 2.00% of block counts, section 54), so the profile records how
*often* jaq allocates and nothing at all about how *long* that takes. Every
"interpreter-layer share" in section 54 therefore **under**-counts the
allocation part of that layer. The same blindness was found
independently by the oxipng work running beside this one (sections 42-43),
whose author added the third check to `scripts/target_pgo_baseline.sh`:
`cargo tree -e build | grep -iE 'cc v|-sys v|cmake v|bindgen v'`. The
SPEC.ja.md 6.1-2 filter as written has two greps and neither can see a C
dependency: the crate name need not contain "simd" and the C sources live in
the cargo registry, not under the target's `src/`.

`serde_json` is **not** in the dependency tree (it is a dev-dependency of
`jaq-core`/`jaq-json` only), so the question SPEC.ja.md asks about it does
not arise.

### 52. Workloads: three input kinds, three article filters, two disjoint splits

`targets/jaq/workloads/gen.py` (Python standard library only, no network,
fixed seeds). Each input kind is paired with the article workload whose
filter fits it; training and holdout differ only in seed.

| case | filter | input kind | file | repeats per run |
|---|---|---|---|---|
| `objsearch` | `.[] \| select(.k == "v") \| .id` | one large array of records with nested fields | 20 MiB | 4 |
| `strproc` | `[.[] \| .name \| ascii_downcase \| length] \| add` | array of records whose `name` is a long string with `\"`, `\\`, `\n`, `\t`, `\uXXXX` and raw UTF-8 | 24 MiB | 8 |
| `readwrite` | `-c '.'` | many small newline-delimited documents | 24 MiB | 2 |

```
$ python3 targets/jaq/workloads/gen.py
411233554e3f25e2a1b25e422af6e0b49905d353a4d36271b9f723e99cfbb9b2   25165849  hold-ndjson.json   seed=20260921303
a15c30c1ea13944338fd9c43e53226ce150f5831a99dc53ca72a781c9db9b65b   20971644  hold-objects.json  seed=20260921301
40888824d1c18de96db05877b5f92a4ede10d04b5ae8ccb233ab9bce4011feca   25165859  hold-strings.json  seed=20260921302
ea80825e8e024d99f9a0baf06c43437dbe30476006450391af550d77f0956ca0   25165903  train-ndjson.json  seed=20260921203
dc8364b13bda8fa004a1d91634f623f3f03aceef3a83f50fdc392fdb7bb0eb45   20971722  train-objects.json seed=20260921201
5568fdbcc786e17e555961d33becbf2d6afac6e3c8746017b57e89aa35ec1c63   25166034  train-strings.json seed=20260921202
```

**Why each case names its file several times** rather than using one big
file: see section 55. The short version is that a single 72 MiB array makes
jaq hold 1.2 GiB resident and turns the wall time bimodal; the repeat form
does the same total work with a few hundred MiB resident and a measurable
wall time.

**Correctness is the sha256 of stdout**, taken outside the timing run by
`run_correctness` in `scripts/target_common.sh`; the timed runs send stdout
to `/dev/null` (`bench.py --stdout devnull`), which is what SPEC.ja.md 10
means by "discard stdout the same way in both variants and keep the
correctness check separate from the timing". Piping tens of megabytes of
re-serialised JSON into the harness would otherwise be inside the timed
window. The output is deterministic:

```
========== 0b. output determinism (same binary, same inputs, twice) ==========
OUTPUT DETERMINISM: MATCH
```

One property worth noting: `-c '.'` on the ndjson input reproduces the input
**byte for byte**, so that case's correctness hash is the input's own hash.

### 53. PGO baseline (SPEC.ja.md 3, 13 day-0 items 2-3), and a `.text` hash that does not reproduce

```
$ export TARGET=jaq
$ REUSE_PROFDATA=0 REPRO=0 DEBUG0=0 scripts/target_pgo_baseline.sh
```

Instrumented build -> training run on the **three training cases only** ->
`llvm-profdata merge` with the pinned toolchain's tool:

```
========== b. training run (instrumented) ==========
  trained on train-objects.json
  trained on train-strings.json
  trained on train-ndjson.json
training run wall time: 5574 ms
-rw-r--r-- 1 hiro hiro 1642352 default_15401585175505616370_0.profraw
========== c. llvm-profdata merge ==========
4e879ce11687fa3c56c720c8b33dd7d0546e0d5c7d9b7c612fef903de9f3a4e5  pgo/jaq/merged.profdata
Instrumentation level: IR  entry_first = 0  instrument_loop_entries = 0
Total functions: 8102
Maximum function count: 176281976
Maximum internal block count: 251372258
Total number of blocks: 108875
Total count: 3438334653
```

**`merged.profdata` sha256 =
`4e879ce11687fa3c56c720c8b33dd7d0546e0d5c7d9b7c612fef903de9f3a4e5`.** Every
arm and every sweep configuration below uses this one file; the training run
is not repeated after this section. jaq is 31x zopfli's program by function
count (8102 records against 259) and 46x by instrumented blocks.

PGO baseline build, with `-pgo-warn-missing-function` and the three
`-pass-remarks*` flags:

```
========== d. PGO baseline build (-Cprofile-use) + remarks ==========
--- remark lines total ---            228248
--- hash mismatch ---                 0
--- no profile data available for function --- 0
--- all warning: lines ---            0
--- .text sha256 ---
642dd55ea3c831132b4adf006464d9f1ef924ccb9918557e5f3c751355f72b4c
```

**Zero profile-use warnings of any kind on a 67-crate dependency graph**, which is
the strongest version of this check the project has run (toy: one crate;
zopfli: five). 228248 remark lines, 7.2x zopfli's 31764.

Correctness, plain release vs PGO baseline --- all six inputs:

```
========== e. checksum comparison (plain release vs PGO baseline) ==========
train-objects.json 536b38cedb6b6483c654f2a367f82b4b92f4c0f267c6263e421dd1e5007e7127
train-strings.json f9f67ae87fe136bd2b7cbad5d59c2586467c574b0779f6957e0be900bf1a52b9
train-ndjson.json  231f15264418df7a96f6c3d64de3e0f85d93e8f7620bdd5f7f750c0e0bf79ed7
hold-objects.json  a338602a7f3148cbe74d0f9016b386edaf97a832a284a109addb8399090b2b0d
hold-strings.json  baeb97a8af67ca1d65de1c355e256c8a44abd38ff41ac2c2c1f9c8df83fab443
hold-ndjson.json   72ff02e47dafe5becb2f652c3fefc383e57765bd442ec12a1713f3f5bcecad37
CHECKSUMS: MATCH
```

Builds cost 38-42 s each (zopfli: 4.4-6.3 s), `.text` is 2628530 bytes
(zopfli: 333884) and the unstripped binary is 33 MB.

#### The `.text` hash is not reproducible on jaq, and SPEC.ja.md 6.3's skip criterion dies with it

zopfli's whole sweep rested on "the build is deterministic, so a
configuration whose `.text` is bit-identical to the baseline's needs no
timing" (section 22). On jaq that premise is false. Four builds of the
**same** configuration, same flags, same profdata:

```
$ source scripts/target_common.sh     # after `export TARGET=jaq`
$ build_variant target-jaq-det1 /tmp/d1.log; text_hash .../det1/.../jaq
61ab0b9c1375b1db2ab722af12c13315909b3718199f75afbbbe672ea17ae91b
$ build_variant target-jaq-det2 /tmp/d2.log; text_hash .../det2/.../jaq
97f3cd036feac13638e6a5beadf4bdeec639a7d20c4e4324c1577642195a80bb
$ # and twice into the SAME target directory, to rule the path out:
ccdbc9261194dd488e95b1a4d7c30e022ffb34f7b7d4d1a1eebf28645eefc0b8
28911f609b17dd455c7e85b6e2c447038dcfb3650bfd906b5f8d6a2deb7ea5f8
```

The cause was established rather than guessed. Two such builds have
**identical section sizes, identical symbol order and identical symbol
sizes**, and differ in 11351 bytes:

```
  .note.gnu.build-id   20
  .rela.dyn           481
  .rodata           10530
  .text               260      (spread over 148 symbols, a few bytes each)
  .debug_info/.debug_loc 60
```

The `.rodata` difference is a single contiguous 5.6 KB run, and the two
sides differ by the presence of a **wall-clock time string**:

```
  A: ... invalid DTD at . cause .0.00:36:40.show_errors.show_stats. ...
  B: ... invalid DTD at . cause .0.show_errors.show_stats. ...
$ strings -a det1 | grep -E '^[0-9]{2}:[0-9]{2}:[0-9]{2}$'  ->  00:36:40
$ strings -a det2 | grep -E '^[0-9]{2}:[0-9]{2}:[0-9]{2}$'  ->  00:37:21
```

00:36:40 and 00:37:21 are the two builds' clock times, and the neighbouring
strings (`show_errors`, `show_stats`) are **mimalloc option names**: this is
mimalloc's C `__TIME__`, recompiled by `cc` on every clean build. The string
shifts the constants after it inside a fixed-size region, and the 148
instructions that reference those constants change their immediates. That is
the whole of the `.text` difference --- **no optimisation decision moved**.

Consequences, all of which the sweep below lives with:

1. **Every configuration is timed.** `scripts/target_headroom.sh` adds a
   configuration to the timing set when its `.text` differs from the
   baseline's, which on jaq is always. Nothing is skipped and nothing can be.
   The 6-of-32 saving zopfli got from this criterion (section 25) is zero
   here.
2. **The normalised remark diff is the only cheap decision signal left**, and
   section 27 already showed it under-reports scalar unrolling. Both of the
   two checks SPEC.ja.md 6.3 relies on are therefore weaker on jaq than on
   zopfli, in opposite ways.
3. `scripts/norm_code_diff.py` was written to restore a code-level criterion:
   it disassembles every symbol, replaces any hex literal of four or more
   digits with `A` (func_code_diff.py's rule) and hashes what is left, per
   symbol and for the whole binary. That comparison **is** stable across
   rebuilds of the same configuration and is what section 58 uses to say
   whether a knob changed code.
4. SPEC.ja.md 3's "the build is deterministic, so the same recipe gives the
   same `.text`" needs the qualifier "for a pure-Rust target". Any target
   with a `cc`-compiled dependency may fail it, and mimalloc is a common
   default feature.

`REPRO=1` was **not** run: section 22 already established that the profdata
file's only irreproducible part is the binary id, and the cause does not
change per target. `DEBUG0=1` was not run either: SPEC.ja.md 3 records that
debuginfo changes `.text` on this toolchain and that the check is therefore
not performed.

### 54. The interpreter-layer share (SPEC.ja.md 6.1-4's 70% gate)

This is the gate SPEC.ja.md 13 item 16 puts at jaq's entrance, and the only
one of its kind in the spec. It asks for the share of `total_score` held by
functions with no loop, or dominated by indirect calls, reference counting,
`IndexMap`/`BTreeMap` lookup and allocation, and says to consider replacing
the target above 70%.

**The measurement is a substitute and is labelled as one.** The spec sources
`total_score` from the Stage 2 plugin dump (profile count x loop-body
instruction count); the plugin does not exist. `scripts/interp_share.py`
uses the same profile with the weight results.md section 31.5 used for the
equivalent zopfli question --- the sum of a function's PGO block counts ---
and adds, per symbol, the machine-code facts that make the (a)/(b) split
checkable: instruction count, how many instructions use a vector register,
and **how many backedges the symbol's own machine code contains**. A symbol
with zero backedges has no loop, so no loop hint can reach it; that part of
the classification needs no judgement.

```
$ scripts/interp_share.py pgo/jaq/merged.profdata \
      --binary target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/jaq \
      --top 20 --crates --tsv artifacts/jaq-day0/interp-share-all.tsv
7951 function records, total weight 3438334653
```

| # | share | insns | vec | backedges | function | class |
|---|---|---|---|---|---|---|
| 1 | **22.52%** | 42 | 0 | 2 | `<hifijson::SliceLexer as hifijson::write::Write>::write_until::<...str_fold::string_end>` | **(a)** byte scan |
| 2 | 7.26% | 4426 | 150 | 259 | `jaq_json::read::parse::<hifijson::SliceLexer>` | mixed host |
| 3 | 5.73% | 432 | 98 | 14 | `<jaq_std::base_run<..>::{closure#7} as FnOnce<..>>::call_once` | **(b)** dispatch |
| 4 | 4.66% | 86 | 0 | 7 | `jaq_json::read::ws_tk::<hifijson::SliceLexer>` | **(a)** byte scan |
| 5 | 4.62% | 245 | 0 | 15 | `<hifijson::SliceLexer as hifijson::num::LexWrite>::num_string_with` | **(a)** byte scan |
| 6 | 4.33% | 2390 | 22 | 179 | `jaq_json::write::write` | mixed host |
| 7 | 3.32% | 1573 | 33 | 117 | `jaq_json::read::parse_string::<hifijson::SliceLexer>` | **(a)** byte scan |
| 8 | 2.22% | 240 | 0 | 13 | `core::ptr::drop_glue::<jaq_json::Val>` | **(b)** refcount/drop |
| 9 | 2.06% | **1** | 0 | **0** | `__rustc::__rust_alloc` | **(b)** allocation (thunk into C) |
| 10 | 2.00% | **1** | 0 | **0** | `__rustc::__rust_dealloc` | **(b)** allocation (thunk into C) |
| 11 | 1.93% | 6562 | 549 | 236 | `<jaq_core::compile::TermId>::run::<jaq_all::data::DataKind>` | **(b)** interpreter dispatch |
| 12 | 1.92% | 1007 | 143 | 33 | `<indexmap::IndexMap<Val, Val, foldhash>>::insert_full` | **(b)** map insert |
| 13 | 1.85% | 290 | 6 | 26 | `<jaq_json::num::Num>::from_str_radix` | **(a)** digit loop |
| 14 | 1.70% | 320 | 0 | 14 | `<alloc::raw_vec::RawVecInner>::finish_grow` | **(b)** allocation |
| 15 | 1.56% | 41 | 0 | 2 | `<...Adapter<BufWriter<StdoutLock>> as fmt::Write>::write_str` | **(b)** io glue |
| 16 | 1.56% | 229 | 0 | 16 | `<BufWriter<StdoutLock> as io::Write>::write_fmt` | **(b)** io glue |
| 17 | 1.54% | 888 | 0 | 56 | `<alloc::raw_vec::RawVecInner>::grow_amortized` | **(b)** allocation |
| 18 | 1.36% | 29 | 0 | **0** | `drop_glue::<Box<dyn Iterator<Item = Result<Val, Exn<Val>>>>>` | **(b)** dyn drop |
| 19 | 1.21% | 77 | 0 | 5 | `<bstr::utf8::Chars as Iterator>::count` | (a) short loop |
| 20 | 1.10% | 198 | 0 | 10 | `<alloc::vec::Vec<u8>>::reserve` | **(b)** allocation |

These 20 hold **74.44%** of the weight. Adding the classes up:

- **(b) glue, hand-classified, inside the top 20: 24.68%**
  (5.73 + 2.22 + 2.06 + 2.00 + 1.93 + 1.92 + 1.70 + 1.56 + 1.56 + 1.54 + 1.36 + 1.10)
- (a) loop-bearing, inside the top 20: **38.18%**
- two fat-LTO inline hosts that are genuinely both (`read::parse` and
  `write::write`, 11.59%) --- section 31.5 hit the same problem with
  `lz77_optimal` and the answer is the same: function-level classification
  is meaningless for an inline host.
- the tail below the top 20 is 25.56%, of which the machine-code check puts
  **6.29%** in symbols with no backedge at all.

```
weight in symbols with NO machine-code backedge: 11.71%
weight in symbols with no vector-register instruction: 60.09%
weight in profdata records with no symbol in this binary: 2.81%
```

**Gate result: the interpreter layer is 31.0% at the floor and at most
61.8% at the ceiling** (floor = the hand-classified 24.68% plus the tail's
6.29% of loopless symbols; ceiling = that plus both mixed hosts plus the
entire unclassified tail). **Both numbers are below 70%, so jaq passes
SPEC.ja.md 6.1-4 and is not swapped out on this criterion.**

One number for the report, since a range from 31% to 62% invites the
question. The 25.56% tail splits, by the machine-code check alone, into
6.29% with no backedge, 16.46% with at least one (of which 7.81% has
between one and ten, i.e. small functions) and 2.81% with no symbol. If the
16.46% is divided in the same (a):(b):mixed proportion the hand-classified
top 20 shows (38.18 : 24.68 : 11.59), the interpreter layer lands at
**about 39%**. That is a point estimate from an extrapolation, not a
measurement, and the honest statement is the range; 39% is what to quote
when one number is needed, and it is comfortably under 70% either way.

Two qualifications on that pass, and they matter more than the number:

1. **It is an under-count by construction.** mimalloc is C (section 51), so
   the 4.06% that `__rust_alloc` and `__rust_dealloc` contribute is the cost
   of two `jmp` instructions, not the cost of allocating. The real
   allocation share is larger by an unknown amount, and allocation is
   squarely in class (b).
2. **Passing the gate does not mean the hints can reach the rest.** The
   38.18% classified (a) is not 38% of opportunity: every one of those
   loops is an early-exit, data-dependent byte scanner in the JSON lexer,
   and section 56 shows the vectorizer refuses all of them on *legality*,
   not on cost. jaq clears the gate the spec wrote and then fails for the
   reason the spec wrote about the **toy's** `find_special` (SPEC.ja.md
   6.2). The gate as written looks for the wrong obstruction on this target.

#### Where the cycles are: crates, and the bin

```
$ scripts/interp_share.py pgo/jaq/merged.profdata --crates   (leading crate of the demangled name)
   27.61%  hifijson          2.63%  bytes
   24.25%  jaq_json          1.70%  bstr
   14.56%  core              1.15%  hashbrown
    8.85%  alloc             1.15%  (unattributed)
    5.73%  jaq_std           0.14%  jaq          <-- the bin itself
    5.09%  jaq_core          0.11%  jaq_fmts
    4.15%  __rustc           0.08%  foldhash
    2.80%  indexmap
```

Grouped: **jaq's own workspace crates 35.3%** (jaq_json 24.25, jaq_std 5.73,
jaq_core 5.09, jaq_fmts 0.11, jaq 0.14), **third-party 36.0%** (hifijson
27.61, indexmap 2.80, bytes 2.63, bstr 1.70, hashbrown 1.15, foldhash 0.08),
**std 27.6%** (core 14.56, alloc 8.85, `__rustc` 4.15). **The bin crate is
0.14%**; everything that matters is in dependencies, and the single largest
dependency is `hifijson`, a crate nobody would think to look at from the
name "jaq". Measured the other way --- any record whose mangled name
mentions `hifijson`, which adds the `jaq_json` functions generic over
`hifijson::SliceLexer` --- the JSON lexer accounts for **42.8%**.

`jaq_core`, the interpreter proper, is **5.09%**. That is the single most
surprising number in this section: the hypothesis behind the 70% gate was
that jaq would be dominated by its interpreter, and it is dominated by its
*parser* instead. The three cases here parse far more JSON than they
evaluate filter terms, which is what jq is normally used for; a workload
built around a heavy filter over a small document would move this share a
lot, and that is a limitation of this case set, not a property of jaq.

#### Per case, because the mix decides the answer

```
$ scripts/interp_share.py pgo/jaq/per-case/<case>.profdata --binary <bin> --top 10 --crates
```

| | `objsearch` | `strproc` | `readwrite` |
|---|---|---|---|
| hottest function | `write_until` 13.78% | `write_until` **37.68%** | `jaq_json::write::write` 16.45% |
| 2nd | `read::parse` 11.62% | `base_run` closure 13.37% | `read::parse` 9.81% |
| 3rd | `num_string_with` 7.38% | `bstr::Chars::count` 2.82% | `write_until` 8.06% |
| no-backedge weight | 15.79% | 10.86% | 8.21% |
| no-vector weight | 62.01% | 62.19% | 54.41% |
| leading crate | jaq_json 29.1% | hifijson 40.0% | jaq_json 42.8% |

The gate's answer depends on the mix exactly as expected: `strproc` is
dominated by one byte-scan loop and `objsearch` has the largest loopless
share. No case comes near 70%.

### 55. Measuring jaq at all: the resident set, the settle gap, and the A/A floor

zopfli's A/A had a worst per-case half-width of **0.29%** (section 24). The
first jaq A/A, run with the obvious workload shape --- one 72 MiB array per
case, one invocation per sample --- gave this:

| workload | half-width |
|---|---|
| objsearch | **13.02%** |
| strproc | 6.09% |
| readwrite | 3.92% |
| aggregate | 4.77% |

**MDE = max(2 x 13.02%, 3%) = 26.05%.** That is not a measurement. Three
things were found and fixed, in this order.

**(i) The resident set makes the wall time bimodal.** jaq materialises a
whole JSON array as `Rc`-counted `Val`s: a 72 MiB array is 1.2 GiB resident.
The raw samples alternate between two modes ~35% apart on the *same binary
and the same input*:

```
objsearch A1    932   1281   1073   1268    933   1273    932   1254 ...
objsearch A2   1321    927   1289    953   1272   1046   1235    947 ...
```

and back-to-back runs of one binary do the same (`1312 1249 965 965 934 982
1331 931`). Transparent huge pages are `[madvise]` on this machine, and the
mode a process lands in appears to depend on what the *previous* process
left behind. Sizing the array down and naming the file several times on the
command line --- same filter, same total bytes, a few hundred MiB resident
--- removes it:

```
10 MiB x8:  1202  1055  1046  1023  1027  1005  1023  1046
20 MiB x4:  1156  1014  1060  1022  1033  1067  1067  1039
40 MiB x2:  1136  1022  1015  1017  1031  1071  1030  1026
```

That is what `targets/jaq/workloads/gen.py`'s `REPEATS` is, and it is frozen
with the case set.

**(ii) The next process pays for the last one's pages.** Even at 20 MiB x 4
the A/A showed a clean position effect: whichever label ran *first* in a
round was ~8% faster. `bench.py` rotates the label order by round, so with
15 rounds and 2 labels one label gets 8 first-positions and the other 7 ---
which is exactly the **1.8% aggregate bias between two byte-identical
binaries** that run showed. A settle gap outside the timed window removes
most of it (`bench.py --gap-ms`, `BENCH_GAP_MS=250` in the `jaq` arm):
within-binary spread fell from ~8% to ~1%.

**(iii) What is left is real, and it is what the A/A is for.** Four
byte-identical copies of the stripped baseline at four paths, measured in
randomised order with a 0.30 s gap
(`artifacts/jaq-day0/four-copy-experiment.txt`):

```
A1:   983   991   993   984   994   988   989   999   mean  990
A2:  1015  1016  1012  1017  1009  1002  1024  1008   mean 1013
A3:   995   994   995  1011  1030   990  1013   990   mean 1002
A4:  1051  1012  1016  1061  1053  1069  1006  1009   mean 1035
```

4.5% between identical binaries, each internally stable to ~1.6%. Re-copying
the files and repeating three times does not reproduce a fixed per-path
offset --- the offsets move --- so this is a slowly drifting machine state
(page placement / THP / page cache) that is constant over tens of seconds
and different between binaries measured tens of seconds apart. **It is
exactly the thing the A/A protocol exists to price, and on jaq it prices at
2-3%, an order of magnitude above zopfli.**

The A/A that the sweep's MDE comes from, with the final case set and
`BENCH_GAP_MS=250`:

```
$ export TARGET=jaq && scripts/target_aa.sh 15 3
$ sha256sum artifacts/jaq-aa/A1 artifacts/jaq-aa/A2
31499f93537d43604e6a13443663b383d81795ab7eabfd12544dd984d581f732  A1
31499f93537d43604e6a13443663b383d81795ab7eabfd12544dd984d581f732  A2
```

90 timed samples (2 labels x 3 workloads x 15 rounds), warmup 3,
`taskset -c 4` (core 2; its SMT sibling CPU 5 is left idle, and CPU 2 is
left to the oxipng work running beside this):

| workload | A1 mean ms | A2 mean ms | ratio A1/A2 | 95% CI | half-width |
|---|---|---|---|---|---|
| objsearch | 1043.0 | 1038.0 | 1.0049 | [0.9846, 1.0264] | **2.09%** |
| strproc | 1073.8 | 1065.4 | 1.0078 | [0.9986, 1.0153] | **0.83%** |
| readwrite | 862.8 | 891.8 | 0.9675 | [0.9539, 0.9819] | **1.40%** |
| **aggregate (geomean)** | | | 0.9932 | [0.9842, 1.0019] | **0.88%** |

**Noise floor = worst per-workload half-width 2.09%; aggregate 0.88%.**
**MDE = max(2 x 2.09%, 3%) = 4.17%**, and the no-floor value **2 x
half-width = 4.17%** --- unlike the toy and zopfli, **the 3% floor does not
bind on jaq; the measured noise does.** That is the first target in this
project where that happens.

Note the `readwrite` row: 0.9675 is a **3.3% difference between two copies
of the same bytes**, with a CI that excludes 1. Any single per-case reading
below about 3.5% on this target should be read as noise even when its CI
looks tight, and the aggregate is the more trustworthy statistic here.

Another run of the machine's environment is recorded in the log:
`lscpu -e` shows 32 logical CPUs sharing one L3 (WSL2 hides the 5950X's two
CCDs, as section 9 recorded), ASLR is on, and the whole sweep and A/A ran
while a second agent was building and timing oxipng on CPU 2. That
contention is inside the A/A number, which is the honest place for it.

### 56. The loop landscape (SPEC.ja.md 6.2's real-target check, second target)

```
$ scripts/remark_attribution.py \
    --bin target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/jaq \
    --log remarks/jaq/baseline-build.log --src-prefix targets/jaq/src \
    --out artifacts/jaq-attr --top 30
remarks parsed: declined=3975, reason=18636, slp=23814, vectorized=46
symbols walked: 5726 (2578971 bytes of .text)
instructions:   619279
unattributed remark locations: 7228 of 46363
ambiguous (DebugLoc resolving to >1 function): 34256
remarks whose file path matched >1 DWARF file: 2075
```

Out of 228248 remark lines: **46 loops vectorized, 3975 loops refused**,
18636 reason lines and 23814 SLP lines. Both remark forms are present, and
the standalone cost-model form that section 23 warned about
(`the cost-model indicates that ... is not beneficial`, with no
`loop not vectorized:` prefix) accounts for **all 586** of jaq's `cost`
lines --- a parser reading only the prefixed form would again report zero.

#### VF/IC distribution of the 46 vectorized loops

| VF | IC | count |
|---|---|---|
| 4 | 1 | 12 |
| 4 | 2 | 7 |
| 4 | 4 | 8 |
| 8 | 1 | 11 |
| 16 | 1 | 2 |
| 32 | 1 | 5 |
| 32 | 2 | 1 |

#### Reasons, with the SPEC.ja.md 4 classification

| count | class | reason string |
|---|---|---|
| 5180 | unsupported | `call instruction cannot be vectorized` |
| 2869 | unsupported | `value that could not be identified as reduction is used outside the loop` |
| 1784 | legality | `Cannot vectorize early exit loop` |
| 1636 | **unknown** | `instruction cannot be vectorized` |
| 1265 | unsupported | `could not determine number of loop iterations` |
| 875 | unsupported | `loop induction variable could not be identified` |
| 844 | **unknown** | `Loop contains an unsupported terminator` |
| 755 | unsupported | `Control flow cannot be substituted for a select` |
| 399 | **unknown** | `Cannot vectorize early exit loop with complex writes to memory` |
| 392 | legality | `Incorrect number of successors from early exiting block` |
| 389 | unsupported | `loop control flow is not understood by vectorizer` |
| 383 | unsupported | `instruction return type cannot be vectorized` |
| 329 | **unknown** | `Cannot vectorize uncountable loop` |
| 308 | **cost** | `the cost-model indicates that interleaving is not beneficial` |
| 295 | legality | `Loop contains an unsupported switch` |
| 278 | **cost** | `the cost-model indicates that vectorization is not beneficial` |
| 157 | **unknown** | `Cannot vectorize early exit loop with reductions or recurrences` |
| 154 | **unknown** | `unable to calculate the loop count due to complex control flow` |
| 135 | legality | `cannot identify array bounds` |
| 64 | **unknown** | `Cannot vectorize early exit loop with strided fault-only-first load` |
| 40 | **unknown** | `Early exit loop with store but no supported condition load` |
| 32 | **unknown** | `Early exit loop contains operations that cannot be speculatively executed` |
| 22 | legality | `unsafe dependent memory operations in loop...` |
| 13 | **unknown** | `runtime pointer checks needed...` |
| 11 | **unknown** | `Auto-vectorization of early exit loops requiring a scalar epilogue is unsupported` |
| 10 | legality | `cannot prove it is safe to reorder floating-point operations` |
| 8 | **unknown** | `read with atomic ordering or volatile read` |
| 4 | **unknown** | `Load for uncountable exit not guaranteed to execute` |
| 3 | **unknown** | `Store instruction cannot be vectorized` |
| 1 | **unknown** | `integer loop induction variable could not be identified` |
| 1 | **unknown** | `runtime SCEV checks needed...` |

Totals by class: **unsupported 11716, unknown 3696, legality 2638, cost 586**
(18636 reason lines, 31 distinct strings). **`cost` is 3.1% of the reason
lines** --- on zopfli it was 9.7%.

**Four reason strings are new** relative to the 26 zopfli produced, all left
`unknown` under section 23's rule: `Load for uncountable exit not guaranteed
to execute`, `Store instruction cannot be vectorized`, `integer loop
induction variable could not be identified`, `runtime SCEV checks needed...`.
`REASON_CLASS` in `scripts/remark_attribution.py` now covers 14941 of 18636
lines seen here.

**`cannot prove it is safe to reorder floating-point operations` appears on
jaq, 10 times** --- zopfli had none, which is what let zopfli's
`-force-vector-width` configurations pass the correctness gate (section 25).
On jaq every one of the ten is in `libm`:

```
$ grep 'cannot prove it is safe to reorder floating-point' ... | cut -d: -f2-3 | sort | uniq -c
      5 src/math/rem_pio2_large.rs:281
      1 src/math/rem_pio2_large.rs:440
      1 src/math/rem_pio2_large.rs:435
      1 src/math/rem_pio2_large.rs:417
      1 src/math/rem_pio2_large.rs:371
      1 src/math/jn.rs:138
```

i.e. trigonometric argument reduction and Bessel functions, reachable from
jaq's `sin`/`cos`/`significand` builtins and **not executed by any of the
three cases**. So the width family can in principle change jaq's answers,
and **the correctness gate would not catch it here**, because the gate only
covers code the cases execute. That is a limitation of the gate worth
writing down (section 61).

#### SPEC.ja.md 7's DebugLoc attribution does not survive this scale

34256 of 46363 decision locations resolve to more than one function (zopfli:
1328 of 6067). The per-function report is unusable: every function that
inlines a `core::iter` loop shows the same shared verdicts, and the top of
the report is `regex_automata`, `jiff` and `saphyr_parser` --- crates with
no executed block at all --- simply because they contain the most loops.
The run also wrote a **5.4 GB** `remark-attribution.json` (46363 locations x
their candidate sets), which is a scaling bug in its own right; it was
deleted, and section 61 records the fix that is needed.

**The usable method on a target this size is the reverse one**: start from
the profile's hot symbols, map their instructions to source lines with
`addr2line -i`, and look up the remarks at those lines. That is how the
three loops below were identified.

#### jaq's three hottest loops, and what LLVM said about each

**1. `hifijson::write::write_until::<string_end>` --- 22.52% of all block
executions, 37.68% on `strproc`.** 42 instructions, **0 vector registers**,
2 backedges. The source is four lines:

```rust
// hifijson-0.5.0/src/write.rs:33-38
fn write_until(&mut self, bytes: &mut Self::Bytes, stop: impl FnMut(u8) -> bool) {
    let pos = self.slice.iter().copied().position(stop);
    ...
}
// hifijson-0.5.0/src/str.rs:193-195, the `stop` that is inlined into it
fn string_end(c: u8) -> bool {
    matches!(c, b'\\' | b'"' | 0..=0x1F)
}
```

This is **the toy's `find_special` verbatim** --- SPEC.ja.md 6.2's
"`position(|c| c == b'"' || c == b'\\' || c < 0x20)` type byte-search loop"
--- and it is the hottest loop in the article's intended target. The
verdict is the same as the toy's, on the real target:

```
$ grep 'remark: src/str.rs:194:' remarks/jaq/baseline-build.log | sort | uniq -c
     14 loop not vectorized: value that could not be identified as reduction is used outside the loop
      7 loop not vectorized: Loop contains an unsupported switch
      7 loop not vectorized: Incorrect number of successors from early exiting block
      7 loop not vectorized
```

**Legality, not cost.** The toy predicted exactly these two strings
(SPEC.ja.md 6.2, results.md section 6) and no hint family lifts them.

Its trip count, derived from the profile's block counts rather than from
`counts[0]` (see below):

```
write_until block counts: [2073520, 18028220, 251372258, 233344038, 233344038, 18028220, 0, 0, 18028220]
                                               ^header      ^backedge                    ^exit
```

251372258 / 18028220 = **13.9 bytes scanned per call** overall, and per case
46143208/7947912 = **5.8** (`objsearch`), 182824008/4469488 = **40.9**
(`strproc`), 22405042/5610820 = **4.0** (`readwrite`). So even if the
legality obstruction were lifted, a width of 32 would be pointless on two of
the three cases; only `strproc`'s 41-byte average strings would pay.

**2. `hifijson::num::num_string_with` --- 4.62%.** 245 instructions, **0
vector registers**, 15 backedges. Its hot line is the number-lexer state
machine `Num::num_part` (`hifijson-0.5.0/src/num.rs:94`), a `match (self.read, c)`
over byte ranges:

```
$ grep 'remark: src/num.rs:94:' ... | sort | uniq -c
     10 loop not vectorized: value that could not be identified as reduction is used outside the loop
      2 loop not vectorized: Loop contains an unsupported switch
      2 loop not vectorized: Cannot vectorize early exit loop with reductions or recurrences
      2 loop not vectorized
```

Again legality/unsupported. Trip count from its block counts:
31719484 / 5692288 = **5.6 digits per number**, which matches the inputs
(4-6 digit integers). A 5-iteration loop is not width-hint material even if
it were legal.

**3. `jaq_json::read::ws_tk` --- 4.66%.** 86 instructions, **0 vector
registers**, 7 backedges: `lexer.eat_whitespace()` followed by
`peek_next()`, i.e. another early-exit byte scan.

Below those, `jaq_json::read::parse` (7.26%) and `jaq_json::write::write`
(4.33%) are fat-LTO inline hosts holding the recursive-descent parser and
the serialiser; `<jaq_core::compile::TermId>::run` (1.93%) is the
interpreter's dispatch loop over an indirect-call graph. None of those is a
vectorizable loop.

#### Cost-declined hot loops: there are effectively none

SPEC.ja.md 7 feeds the `cost` class to Jev, and section 31.2 already warned
that a `cost` classification is not evidence of an opportunity. On jaq the
problem is one step earlier: **the 586 cost lines sit at 37 distinct
DebugLocs, and the ones that overlap hot code are shared `core` locations**
(`library/core/src/slice/iter/macros.rs:180`,
`library/core/src/iter/traits/iterator.rs:2503`) that dozens of functions
inline. Weighting each (location, hot symbol) pair by the symbol's profile
share and the fraction of its instructions at that line
(`scripts/cost_hot_loops.py`, output in
`artifacts/jaq-day0/cost-declined-hot.txt`), the largest is **~2.1%** and it
is `iterator.rs:2503` inside `write_until` --- the same
DebugLoc that also carries 363 `Cannot vectorize early exit loop` lines from
other inline instances. The remark text cannot say which instance the cost
verdict belongs to, and the machine code says the answer anyway: the loop is
42 scalar instructions with a legality refusal at its own DebugLoc.

**So the Stage 2 candidate list that section 29.2 built for zopfli ---
"hand Jev the functions whose loops got a `cost` remark" --- returns nothing
usable on jaq.**

#### A trip-count caveat that also applies backwards to zopfli

Section 31.2 computed `<ZopfliHash>::update`'s average trip count as
`loop body count / counts[0]`, treating **`Block counts[0]` as the function
entry count**. On jaq that is demonstrably wrong: `write_until`'s
`counts[0]` is 2073520 while its loop is *entered* 18028220 times, and
`counts[0]` is **0** in the `objsearch` and `readwrite` profiles even though
the function runs millions of times there. The profile header says why:

```
Instrumentation level: IR  entry_first = 0
```

With `entry_first = 0` LLVM's MST-based IR instrumentation does not
guarantee that counter 0 is the entry block, and `llvm-profdata`'s
"function count" inherits the same assumption. **The reliable method is the
one used above: find the loop header count and the backedge count among the
blocks, and take exits = header - backedge.** Section 31.2's zopfli figure
is probably still right (151050803 is plausible as the call count of
`update` for 4.2 MB of input at 15 squeeze iterations, and 2.3 M is not),
but it was obtained by a method that does not hold in general and should be
redone with the header/backedge form before it is quoted again.

#### Pre-registered reading of the sweep, written before the timing table existed

Because the A/A produced a 3.3% per-case "effect" between byte-identical
binaries, a per-case crossing of the MDE in a 32-configuration sweep is
likely to happen by noise alone. Fixed here, before the numbers were read
(the rule itself is SPEC.ja.md 6.3's and is not being changed; this is how
its inputs are read):

1. **Correctness first**, as always: a configuration whose output checksums
   differ on any of the six inputs is recorded as a violation and excluded
   from the judgement.
2. **Flag two thresholds, not one**: the frozen MDE (4.17%) and the
   per-case `2 x half-width` from the A/A above --- objsearch **4.17%**,
   strproc **1.67%**, readwrite **2.80%**, aggregate **1.76%**. Every
   crossing of either is reported.
3. **A crossing is evidence only if the code moved.** For any configuration
   that crosses, `scripts/norm_code_diff.py` must show changed machine code
   in symbols holding profile share, and the raw 15 samples must not show
   the single-outlier-round pattern that produced two false flags on zopfli
   (section 26). A crossing that fails either check is reported as a
   crossing and attributed to noise, not to the knob.
4. `g0-align5` is the in-sweep noise probe: if it sits outside the A/A
   band, the whole table inherits that caveat.

`scripts/norm_code_diff.py` was validated first, on two independent builds
of the *same* configuration --- the pair whose raw `.text` hashes differ for
the mimalloc reason of section 53:

```
$ scripts/norm_code_diff.py target-jaq-pgo-use/.../jaq artifacts/jaq-headroom/bin/baseline \
      --profdata pgo/jaq/merged.profdata
target-jaq-pgo-use/.../jaq: 4763 symbols, normalised whole-code hash 7ad6d9821bbed2fb
artifacts/jaq-headroom/bin/baseline: hash 7ad6d9821bbed2fb  IDENTICAL
  symbols: 4763 (base 4763), changed 0, only-in-base 0, only-here 0
```

so the normalised hash **is** stable across rebuilds where the raw `.text`
hash is not, which is what makes it usable as the code-change criterion.

### 57. Headroom sweep: 33 builds, correctness first, and no configuration skipped

```
$ export TARGET=jaq
$ BENCH_SET=training ONLY='^(g[0-3]-|g5-(max1|max4|count2|count4)$)' \
      RUNS=15 WARMUP=3 scripts/target_headroom.sh
```

Baseline plus 32 configurations: groups 0-3 of the SPEC.ja.md 6.3 matrix
plus the four extra points of group 5 that section 31.3 added for the unroll
dimension (`-unroll-max-count=1/4` and `-unroll-count=2/4`;
`-unroll-max-count=2/8` are already group 2). Every one is the SPEC.ja.md 3
recipe --- same `-Cprofile-use=pgo/jaq/merged.profdata`, same
`-Ctarget-cpu=native -Csymbol-mangling-version=v0`, same
`CARGO_PROFILE_RELEASE_{OPT_LEVEL=3,LTO=fat,CODEGEN_UNITS=1,DEBUG=1,PANIC=unwind,STRIP=none}`,
same three `-pass-remarks*` flags, explicit `--target`, own
`CARGO_TARGET_DIR`, `--locked`, clean build --- plus that configuration's
knobs. Build time 39.6-48.7 s each (1352 s for all 33; the build phase and the
timing phase together took about 65 minutes). **No
configuration failed to build.**

Two deviations from zopfli's list, both deliberate: group 4 is **not** swept
(section 28 settled it on zopfli --- `+prefer-256-bit` is byte-identical
code on znver3, `+prefer-128-bit` and `x86-64-v3` are small regressions ---
and the four unroll points of group 5 are the better use of the build
budget), and **the sweep runs on the training inputs** (`BENCH_SET=training`),
which is what SPEC.ja.md 7 asks for and what section 30 recorded as the one
thing zopfli got wrong.

| config | knobs | output hashes | .text vs base | raw +/- | norm +/- | vec decision changed | timed? |
|---|---|---|---|---|---|---|---|
| g0-align5 | `-align-all-nofallthru-blocks=5` | MATCH | differ | +0 / -0 | +0 / -0 | no | yes (noise probe) |
| g1-maxbw | `-vectorizer-maximize-bandwidth` | MATCH | differ | +2 / -1 | +2 / -1 | YES | yes |
| g1-vw8 | `-force-vector-width=8` | MATCH | differ | +22 / -31 | +21 / -31 | YES | yes |
| g1-vw16 | `-force-vector-width=16` | MATCH | differ | +30 / -37 | +29 / -37 | YES | yes |
| g1-vw32 | `-force-vector-width=32` | MATCH | differ | +31 / -34 | +27 / -34 | YES | yes |
| g1-maxbw-vw32 | both | MATCH | differ | +31 / -34 | +27 / -34 | YES | yes |
| g1-ic1 | `-force-vector-interleave=1` | MATCH | differ | +44 / -43 | +44 / -43 | YES | yes |
| g1-ic2 | `-force-vector-interleave=2` | MATCH | differ | +51 / -54 | +51 / -54 | YES | yes |
| g1-ic4 | `-force-vector-interleave=4` | MATCH | differ | +64 / -58 | +60 / -58 | YES | yes |
| g1-tailfold-prefer | `-epilogue-tail-folding-policy=prefer-fold-tail` | MATCH | differ | +10 / -0 | +10 / -0 | no | yes |
| g1-tfstyle-data | `-force-tail-folding-style=data` | MATCH | differ | +0 / -0 | +0 / -0 | no | yes |
| g1-tfstyle-data-and-control | `-force-tail-folding-style=data-and-control` | MATCH | differ | +0 / -1 | +0 / -1 | YES | yes |
| g1-memcheck24 | `-runtime-memory-check-threshold=24` | MATCH | differ | +0 / -0 | +0 / -0 | no | yes |
| g1-memcheck128 | `-runtime-memory-check-threshold=128` | MATCH | differ | +0 / -0 | +0 / -0 | no | yes |
| g2-inline325 | `-inline-threshold=325` | MATCH | differ | +3212 / -2280 | +1576 / -670 | YES | yes |
| g2-inline500 | `-inline-threshold=500` | MATCH | differ | +3674 / -2848 | +1722 / -917 | YES | yes |
| g2-inline1000 | `-inline-threshold=1000` | MATCH | differ | +4793 / -3562 | +2652 / -1455 | YES | yes |
| g2-unroll-thr300 | `-unroll-threshold=300` | MATCH | differ | +55 / -2 | +55 / -2 | YES | yes |
| g2-unroll-thr1000 | `-unroll-threshold=1000` | MATCH | differ | +71 / -29 | +56 / -18 | YES | yes |
| g2-unroll-max2 | `-unroll-max-count=2` | MATCH | differ | +9 / -9 | +9 / -9 | no | yes |
| g2-unroll-max8 | `-unroll-max-count=8` | MATCH | differ | +0 / -0 | +0 / -0 | no | yes |
| g2-unroll-runtime | `-unroll-runtime` | MATCH | differ | +6 / -1 | +6 / -1 | no | yes |
| g3-loop-distribute | `-enable-loop-distribute` | MATCH | differ | +1154 / -0 | +1154 / -0 | YES | yes |
| g3-slp-neg20 | `-slp-threshold=-20` | MATCH | differ | +4125 / -1027 | +2876 / -983 | YES | yes |
| g3-slp-100 | `-slp-threshold=100` | MATCH | differ | +1462 / -1246 | +975 / -1108 | YES | yes |
| g3-unswitch200 | `-unswitch-threshold=200` | MATCH | differ | +169 / -109 | +99 / -41 | YES | yes |
| g3-loop-flatten | `-enable-loop-flatten` | MATCH | differ | +0 / -0 | +0 / -0 | no | yes |
| g3-gvn-hoist | `-enable-gvn-hoist` | MATCH | differ | +362 / -432 | +34 / -107 | YES | yes |
| g5-count2 | `-unroll-count=2` | MATCH | differ | +957 / -628 | +733 / -404 | YES | yes |
| g5-count4 | `-unroll-count=4` | MATCH | differ | +676 / -397 | +471 / -192 | YES | yes |
| g5-max1 | `-unroll-max-count=1` | MATCH | differ | +5 / -31 | +3 / -26 | no | yes |
| g5-max4 | `-unroll-max-count=4` | MATCH | differ | +5 / -5 | +5 / -5 | no | yes |

**Correctness: all 32 configurations produce byte-identical output on all
six inputs.** Zero violations, so nothing is excluded from the judgement.

```
$ for f in artifacts/jaq-headroom/remarks/*.checksums; do
      diff -q artifacts/jaq-headroom/remarks/baseline.checksums $f >/dev/null || echo "MISMATCH $f"; done
(no output)
```

**The `-force-vector-width` family passes the gate on jaq, and the reason is
weaker than zopfli's.** zopfli passed because the FP-reordering refusal does
not exist anywhere in its build (section 25). jaq's build has ten of them
(section 56) --- so the hint *could* change an answer --- but all ten are in
`libm`'s trigonometric argument reduction, which none of the three cases
executes. **The correctness gate only covers code the cases run**, so on jaq
it is passing by workload coverage rather than by structure. A case set that
called `sin`/`cos` would be the test, and this one is not it. Recorded as a
gap in the gate, not as a clean pass.

**The `.text` column is uninformative and every configuration was timed.**
Every entry reads "differ", including the four whose normalised remark set
is empty of changes (`g1-tfstyle-data`, `g1-memcheck24`, `g1-memcheck128`,
`g3-loop-flatten`) and `g2-unroll-max8`, because of the mimalloc `__TIME__`
of section 53. On zopfli this criterion skipped 6 of 32 configurations; here
it skips none and cannot. The normalised code hash is what answers the same
question, after the fact, in section 58.

### 58. Timing: 33 configurations, interleaved, training inputs

```
$ scripts/bench.py run --cpu 4 --warmup 3 --runs 15 --stdout devnull --gap-ms 250 \
      --label baseline=... (33 labels) \
      --workload objsearch=... --workload strproc=... --workload readwrite=... \
      --out artifacts/jaq-headroom/headroom.json --progress
$ scripts/bench.py stats artifacts/jaq-headroom/headroom.json --base baseline \
      --seed 20260921 --resamples 10000 --mde 0.04173240105455345
```

1485 timed samples (33 labels x 3 workloads x 15 rounds), warmup 3, one
single round-robin invocation, `taskset -c 4`, 250 ms settle gap, **training
inputs**. Speed ratio = `t_baseline / t_config`; **> 1 means faster than the
PGO baseline.** Frozen MDE 4.17% (section 55).

| config | aggregate ratio | 95% CI | half-width | abs change | beyond MDE 4.17%? | CI excludes 1 |
|---|---|---|---|---|---|---|
| baseline | 1.0000 | --- | 0.00% | 0.00% | no | --- |
| g3-slp-100 | **1.0208** | [1.0125, 1.0284] | 0.80% | 2.08% | no | yes |
| g0-align5 | 1.0132 | [1.0075, 1.0194] | 0.59% | 1.32% | no | yes |
| g3-gvn-hoist | 1.0090 | [1.0007, 1.0159] | 0.76% | 0.90% | no | yes |
| g3-loop-distribute | 1.0061 | [0.9999, 1.0127] | 0.64% | 0.61% | no | no |
| g3-loop-flatten | 1.0053 | [0.9994, 1.0118] | 0.62% | 0.53% | no | no |
| g2-inline1000 | 1.0048 | [0.9973, 1.0125] | 0.76% | 0.48% | no | no |
| g2-inline325 | 1.0043 | [0.9961, 1.0116] | 0.78% | 0.43% | no | no |
| g1-memcheck128 | 1.0042 | [0.9973, 1.0122] | 0.74% | 0.42% | no | no |
| g1-maxbw-vw32 | 1.0039 | [0.9988, 1.0089] | 0.51% | 0.39% | no | no |
| g2-unroll-max2 | 1.0038 | [0.9950, 1.0126] | 0.88% | 0.38% | no | no |
| g3-unswitch200 | 1.0031 | [0.9994, 1.0072] | 0.39% | 0.31% | no | no |
| g1-ic1 | 1.0028 | [0.9958, 1.0094] | 0.68% | 0.28% | no | no |
| g1-ic2 | 1.0028 | [0.9979, 1.0083] | 0.52% | 0.28% | no | no |
| g5-max1 | 1.0027 | [0.9932, 1.0114] | 0.91% | 0.27% | no | no |
| g1-vw32 | 1.0024 | [0.9962, 1.0093] | 0.66% | 0.24% | no | no |
| g1-vw8 | 1.0018 | [0.9946, 1.0084] | 0.69% | 0.18% | no | no |
| g5-count2 | 1.0017 | [0.9965, 1.0074] | 0.55% | 0.17% | no | no |
| g1-ic4 | 1.0012 | [0.9940, 1.0087] | 0.73% | 0.12% | no | no |
| g2-inline500 | 0.9996 | [0.9924, 1.0071] | 0.74% | 0.04% | no | no |
| g1-tfstyle-data | 0.9978 | [0.9874, 1.0074] | 1.00% | 0.22% | no | no |
| g1-vw16 | 0.9977 | [0.9937, 1.0027] | 0.45% | 0.23% | no | no |
| g2-unroll-max8 | 0.9977 | [0.9893, 1.0062] | 0.84% | 0.23% | no | no |
| g1-tfstyle-data-and-control | 0.9968 | [0.9882, 1.0052] | 0.85% | 0.32% | no | no |
| g1-memcheck24 | 0.9961 | [0.9898, 1.0024] | 0.63% | 0.39% | no | no |
| g1-tailfold-prefer | 0.9955 | [0.9907, 1.0003] | 0.48% | 0.45% | no | no |
| g5-max4 | 0.9928 | [0.9863, 0.9986] | 0.61% | 0.72% | no | yes |
| g1-maxbw | 0.9923 | [0.9853, 0.9996] | 0.72% | 0.77% | no | yes |
| g2-unroll-runtime | 0.9885 | [0.9836, 0.9939] | 0.52% | 1.15% | no | yes |
| g2-unroll-thr300 | 0.9877 | [0.9817, 0.9926] | 0.55% | 1.23% | no | yes |
| g2-unroll-thr1000 | 0.9869 | [0.9770, 0.9956] | 0.93% | 1.31% | no | yes |
| g3-slp-neg20 | 0.9632 | [0.9537, 0.9712] | 0.87% | 3.68% | no | yes |
| g5-count4 | **0.9497** | [0.9420, 0.9566] | 0.73% | **5.03%** | **YES** | yes |

**Exactly one configuration moves the aggregate past the MDE, and it is a
regression**: `-unroll-count=4` at **-5.03% [-5.80%, -4.34%]**. The largest
improvement in the whole matrix is `-slp-threshold=100` at **+2.08%
[+1.25%, +2.84%]**, half the MDE.

Per-workload crossings of the 4.17% MDE, all four of them regressions:

```
  - g3-slp-neg20/objsearch -5.07% CI [-6.61%, -4.00%]
  - g3-slp-neg20/strproc   -4.53% CI [-5.43%, -3.39%]
  - g5-count4/objsearch    -6.19% CI [-6.80%, -5.52%]
  - g5-count4/strproc      -5.05% CI [-6.27%, -4.13%]
```

Crossings of the softer per-case `2 x half-width` thresholds
(objsearch 4.17%, strproc 1.67%, readwrite 2.80%) that are **improvements**:
`g3-slp-100/readwrite` +3.38%, `g2-unroll-max2/readwrite` +3.21%,
`g3-loop-distribute/readwrite` +3.12%, `g5-max4/readwrite` +3.07%,
`g3-loop-flatten/readwrite` +2.97%, `g3-unswitch200/readwrite` +2.86%,
`g1-memcheck128/readwrite` +2.80%, plus several strproc readings near 2%.
Step 3 of the pre-registered rule (section 55) says to check whether the
code moved. It did not, for most of them.

#### The five-label in-sweep A/A that the sweep produced by accident

`scripts/norm_code_diff.py` against the baseline for all 32 configurations
(`artifacts/jaq-headroom/norm-code-diff.txt`) finds **five whose normalised
machine code is identical to the baseline's, symbol for symbol**:
`g1-memcheck24`, `g1-memcheck128`, `g1-tailfold-prefer`, `g2-unroll-max8`
and `g3-loop-flatten`. Their raw `.text` hashes all differ (mimalloc,
section 53); their code does not. **Anything they show that is not 1.0000 is
noise**, and five labels is a better null than the A/A's two:

| config | objsearch | strproc | readwrite | aggregate |
|---|---|---|---|---|
| g1-memcheck24 | 0.9893 | 0.9967 | 1.0023 | 0.9961 |
| g1-memcheck128 | 0.9912 | 0.9938 | 1.0280 | 1.0042 |
| g1-tailfold-prefer | 0.9927 | 0.9909 | 1.0031 | 0.9955 |
| g2-unroll-max8 | 0.9834 | 0.9948 | 1.0150 | 0.9977 |
| g3-loop-flatten | 0.9936 | 0.9931 | 1.0297 | 1.0053 |
| **null median** | **0.9912** | **0.9938** | **1.0150** | **0.9977** |
| null spread | 1.02 pp | 0.58 pp | **2.73 pp** | 0.98 pp |

Three things follow, and they are the most useful numbers in this section.

1. **The aggregate is trustworthy to about 1%** on this target: five
   binaries that are provably the same code land inside
   [0.9955, 1.0053].
2. **A single case is not trustworthy below about 3%.** `g3-loop-flatten`
   --- identical code --- reads **+2.97% on `readwrite` with a CI of
   [+1.95%, +4.06%] that excludes 1**. Every one of the seven "improvements"
   listed above is inside or barely outside that null band. The A/A's
   readwrite row (0.9675 between two copies of one binary) said the same
   thing with two labels; this says it with five.
3. **The bias has a direction, because every ratio shares one baseline
   binary.** All five nulls read `readwrite` high (median +1.50%) and
   `objsearch` low (median -0.88%), which means the baseline binary itself
   happens to be slow on `readwrite` and fast on `objsearch`. That offset is
   in *every* column of the table above.

Re-expressing every configuration against the null median
(`artifacts/jaq-headroom/null-corrected.txt`) corrects for that, crudely:

| config | objsearch* | strproc* | readwrite* | geomean* |
|---|---|---|---|---|
| g3-slp-100 | 1.0276 | 1.0165 | 1.0185 | **1.0208** |
| g0-align5 | 1.0342 | 1.0169 | 0.9892 | 1.0132 |
| g3-gvn-hoist | 1.0113 | 1.0111 | 1.0049 | 1.0091 |
| g3-loop-distribute | 1.0041 | 0.9987 | 1.0159 | 1.0062 |
| ... | | | | |
| g2-unroll-thr1000 | 0.9897 | 0.9960 | 0.9754 | 0.9870 |
| g3-slp-neg20 | 0.9578 | 0.9607 | 0.9713 | 0.9632 |
| g5-count4 | 0.9465 | 0.9554 | 0.9472 | **0.9497** |

The correction removes the `readwrite` improvements entirely --- the seven
configurations listed above collapse to +0.5% to +1.9% --- and leaves the
ordering of the aggregate untouched. **No configuration's corrected geomean
reaches 4.17% in the improving direction; two exceed it in the regressing
direction.**

#### What actually changed, for the configurations that moved

```
$ scripts/norm_code_diff.py artifacts/jaq-headroom/bin/baseline \
      artifacts/jaq-headroom/bin/* --profdata pgo/jaq/merged.profdata --top 5
```

| config | changed symbols | profile share changed | what it did to the hot functions |
|---|---|---|---|
| `g5-count4` (-5.03%) | 386 | **26.16%** | `read::parse` 4426 -> **8229** insns, `TermId::run` 6562 -> 6863, `write::write` 2390 -> 2439. Forcing a count on every loop doubles the parser. |
| `g3-slp-neg20` (-3.68%) | 1785 | **45.52%** | `read::parse` 4426 -> 4579, `num_string_with` 245 -> 279, `write::write` 2390 -> 2486, `parse_string` 1573 -> 1671. SLP inflates everything and pays nowhere. |
| `g3-slp-100` (+2.08%) | 357 | 18.12% | `read::parse` 4426 -> **4421**, `insert_full` 1007 -> **999**, `parse_string` 1573 -> 1588. The *opposite* direction: less SLP, slightly smaller hot code. |
| `g0-align5` (+1.32%) | **3602** | **91.21%** | pure padding: `write_until` 42 -> 47 instructions, `ws_tk` 86 -> 96, `read::parse` 4426 -> 4947. Every function gains NOPs and nothing else. |
| `g3-gvn-hoist` (+0.90%) | --- | 19.52% | --- |
| `g5-max1`, `g5-max4`, `g2-unroll-max2` | --- | **0.05%** | the unroll cap reaches essentially nothing on jaq |
| `g2-unroll-runtime`, `g3-loop-distribute` | --- | **0.00%** | code changed, but in no symbol the profile visits |

Two of these deserve a sentence.

**`g0-align5` is the noise probe and it is not inert on jaq.** SPEC.ja.md
6.3 calls group 0 "noise-floor measurement only, no decision content", and
that is true of its *decisions* --- the remark set is bit-identical, +0/-0
--- but `-align-all-nofallthru-blocks=5` inserts alignment padding into
3602 of 4763 symbols covering 91% of the profile, and it buys **+1.32%
aggregate, +3.42% on `objsearch` after the null correction**, the single
largest per-case improvement in the matrix. On a target whose hot loop is 42
instructions, code alignment is a bigger lever than any vectorizer knob.
That is a real result about jaq, and it is also a warning about using group
0 as a noise probe: on this target it measures alignment, not noise. The
five identical-code configurations above are the honest probe.

**The unroll dimension, which was zopfli's only real lever (+1.59%), is dead
here.** `-unroll-max-count=1/2/4/8` change **0.05% of the profile's worth of
symbols** and move the aggregate by 0.23% to 0.72%; `-unroll-count=2/4`
change 26-33% and cost 0.17% and 5.03%. zopfli's monotone "less unrolling is
faster" curve does not appear: jaq's hot loops are already minimal
(`write_until` is 42 instructions) and there is nothing for the unroller to
undo.

### 59. Stopping rule (SPEC.ja.md 6.3), applied to jaq

> Across groups 1-3, if (a) no configuration's aggregate speed-ratio CI
> lower bound exceeds the minimum effect size, **and** (b) no configuration
> improves a single case beyond the minimum effect size, record "this target
> is flat under the hint method" and swap the target.

**Correctness precondition: satisfied trivially.** All 32 configurations
produce byte-identical output on all six inputs (section 57), so no
configuration is excluded and the rule reads on the full set. Evaluated with
MDE = **4.17%** over the 32 timed configurations of groups 0-3 and 5:

- **(a)** The highest aggregate CI lower bound is **1.0125**
  (`g3-slp-100`, CI [1.0125, 1.0284]), against the required **1.0417**.
  **Not satisfied.**
- **(b)** No configuration improves any single case beyond 4.17%. The
  largest per-case improvement with a CI excluding 1 is **+3.38%**
  (`g3-slp-100` on `readwrite`, CI [+1.80%, +4.83%]) --- and section 58's
  five-label null shows an identical-code configuration reading **+2.97%**
  on that same case, so most of it is the baseline binary's own offset;
  corrected, it is +1.85%. The largest corrected per-case improvement in
  the matrix is `g0-align5` on `objsearch` at **+3.42%**, from alignment
  padding. **Not satisfied.**

**Outcome for jaq: (a) no and (b) no --- "this target is flat under the hint
method; swap the target."**

Because (a) is not satisfied, SPEC.ja.md 1.3-1 --- "there exists at least
one global dimension that moves the aggregate speed ratio by twice the
minimum effect size" --- is **not met on jaq either**. It is now unmet on
all three targets measured (toy, zopfli, jaq).

**Group 4 was not swept**, deliberately and for the reason section 57
gives: section 28 measured it on zopfli as byte-identical code
(`+prefer-256-bit`) or a small regression, nothing about jaq suggests a
different answer on an ISA dimension, and the four extra unroll points of
group 5 were the better use of the build budget. The rule is evaluated over
groups 0-3 and 5.

**What this outcome is, and what it is not.** As on zopfli it is a statement
about *global* knobs. Unlike zopfli, though, the per-site case is not merely
unproven here --- section 56 argues it is closed:

- zopfli's exception was two hot, integer, **cost**-declined loops. jaq has
  no equivalent. Its three hottest loops (`write_until` 22.52%,
  `num_string_with` 4.62%, `ws_tk` 4.66%) are refused on **legality /
  unsupported** grounds, and the 586 `cost` lines sit at shared `core`
  DebugLocs that carry legality refusals from other inline instances at the
  same time (section 56).
- The width family cannot reach those loops even in principle: the
  refusals are `Loop contains an unsupported switch` and `Incorrect number
  of successors from early exiting block`, which `llvm.loop.vectorize.width`
  does not lift (SPEC.ja.md 6.2, established on the toy and now confirmed
  on the real target).
- Two of the three cases have an average scan length of 4-6 bytes
  (section 56), so even a hypothetical legal vectorization of `write_until`
  would only pay on `strproc`.

**Recommendation** (Stage 0 does not make the swap decision; this is the
evidence for the spec owner):

> **Record jaq as "flat under global hints, and closed under per-site hints
> for a structural reason", and do not spend Stage 2 on it.** jaq was the
> article's intended target and the honest report is that the five hint
> families cannot reach it: 42.8% of its profile is a JSON lexer built out
> of `slice::iter().position(..)` early-exit byte scans, which is precisely
> the shape SPEC.ja.md 6.2 identified on the toy as out of reach on
> legality grounds. The 70% interpreter gate passed (section 54) and looked
> for the wrong obstruction.
>
> jaq is still worth keeping in the report as the **strongest negative
> result** the project has: it is the target the article was about, the
> analysis is complete, the reason is structural rather than statistical,
> and it names an obstruction (early-exit byte search) that the spec
> already predicted but had only measured on a toy.
>
> If a third transfer target is wanted after zopfli, SPEC.ja.md 6.4's own
> list points at oxipng (PNG filters are counted byte loops without early
> exits) rather than at anything jaq-shaped.

### 60. Implications for Stage 1 and Stage 2

**PGO on/off under the frozen recipe**, measured because step 1 of this
stage asks for the plain build's times (this is *not* reference arm R, which
would also drop `lto=fat`, `codegen-units=1` and `target-cpu=native`):

```
$ scripts/bench.py run --cpu 4 --warmup 3 --runs 15 --gap-ms 250 --stdout devnull \
      --label plain=artifacts/jaq-plain/plain --label pgo=artifacts/jaq-plain/pgo ...
```

| case | plain ms | PGO ms | PGO / plain |
|---|---|---|---|
| objsearch | 1202.9 | 1022.8 | **1.176** |
| strproc | 1113.5 | 1067.9 | 1.043 |
| readwrite | 1246.8 | 896.4 | **1.391** |
| **aggregate** | | | **1.195** [1.185, 1.205] |

**PGO alone is worth +19.5% on jaq** (+39.1% on the read/write case), which
is 4.7x the MDE and about ten times the largest global knob in the entire
sweep. Whatever `jev-opt build` ends up claiming on this target, that number
is the one a user would feel, and none of it comes from a hint.

**What moved anything on jaq, and how it compares with the other two
targets** (all three columns are aggregate speed ratios):

| knob | jaq | zopfli | toy | keep as a Stage 1 candidate? |
|---|---|---|---|---|
| `-slp-threshold=100` | **+2.08%** (best on this target) | +0.09% | --- | **yes** --- first target where raising the SLP threshold helps, and the third different "best knob" in three targets |
| `-align-all-nofallthru-blocks=5` | **+1.32%** (+3.42% on one case) | -0.13% | noise probe | **yes, as a layout dimension.** It was the noise probe and it is not inert here |
| `-enable-gvn-hoist` | +0.90% | +0.27% | 0.00% | yes, low priority; positive on both real targets |
| `-unroll-max-count` 1/2/4/8 | +0.27% / +0.38% / **-0.72%** / -0.23% | **+1.59% / +1.55%** / +0.73% / +0.26% | -0.56% | keep, but the direction is target dependent: zopfli's best knob is inert on jaq (0.05% of the profile's symbols change) |
| `-unroll-count` 2/4 | +0.17% / **-5.03%** | -2.63% .. -3.94% | --- | **drop.** Worst family on both real targets |
| `-slp-threshold=-20` | **-3.68%** | -1.01% | -1.03% | keep as a known-negative direction |
| `-unroll-threshold` 300/1000 | -1.23% / -1.31% | +0.08% / **+0.93%** | -0.69% | keep; sign flips between targets |
| `-force-vector-width` 8/16/32 | +0.18% / -0.23% / +0.24%, output identical | +0.35% / -0.17% / -0.12%, output identical | output **changed** | keep behind the correctness gate. jaq has ten FP-reorder sites but none on the hot path, so its pass is weaker than zopfli's |
| `-force-vector-interleave` 1/2/4 | +0.28% / +0.28% / +0.12% | 0.03% / +0.29% / 0.02% | -26.6% / -8.4% / -1.1% | keep; inert on both real targets |
| `-vectorizer-maximize-bandwidth` | -0.77% | +0.10% | **-18.2%** | keep, direction target dependent |
| `-inline-threshold` 325/500/1000 | +0.43% / -0.04% / +0.48%; 3212 remark lines move | +0.17% / -1.77% / -0.70% | <= 0.25% | keep; the largest remark mover on all three targets and moves time on none |
| `-enable-loop-distribute` | +0.61%, 1154 remark lines, **0.00% of profile share changed** | byte-identical `.text` | byte-identical | **drop** |
| `-runtime-memory-check-threshold`, `-enable-loop-flatten`, `-epilogue-tail-folding-policy` | **normalised code identical** | byte-identical `.text` | byte-identical | **drop.** Three targets, no code change |

Six conclusions to carry forward:

1. **Three targets, three different best knobs, and no overlap**:
   `-force-vector-interleave` on the toy (catastrophically negative),
   `-unroll-max-count` on zopfli (+1.59%), `-slp-threshold=100` on jaq
   (+2.08%). Every one of them is inert or harmful on the other two. This
   is the strongest form of section 29.1's argument: a hand-written default
   candidate list cannot exist, and a per-program decision has something
   real to decide --- even though what it decides is worth less than the
   noise floor on every target so far.
2. **The `.text`-hash skip criterion is not portable.** It needs a
   reproducible build, and a `cc`-built default feature breaks that.
   `scripts/norm_code_diff.py` should become the criterion, with the raw
   hash as a fast pre-check.
3. **The in-sweep null is free and should be mandatory.** Five
   configurations of this sweep produced code identical to the baseline's,
   and they measured the noise floor five-label instead of two, exposed a
   direction-of-bias in the baseline binary, and killed seven spurious
   per-case "improvements". Every sweep produces such configurations; the
   harness should identify them (it now can) and report them as a null
   panel next to the results.
4. **Group 0 is not a noise probe on a target with small hot loops.**
   `-align-all-nofallthru-blocks=5` changed 91% of jaq's profile by
   instruction padding and was one of the two biggest improvements.
5. **`cost` as the class to feed Jev does not survive contact with a large
   program.** On zopfli it resolved to two named hot functions (section
   29.2). On jaq the 586 `cost` lines live at `core::iter` DebugLocs shared
   by dozens of inline instances, and the hot loops' own DebugLocs carry
   legality refusals. SPEC.ja.md 7's Stage 1 input is empty here, and the
   Stage 2 plugin (which reads IR, not DebugLocs) is the only way to ask
   the question at all.
6. **The obstruction on the article's target is the one the toy found, not
   the one the spec gated on.** SPEC.ja.md 6.1-4 gates jaq on the
   interpreter layer; the interpreter layer is 31-62% and `jaq_core` is
   5.09%. The thing in the way is a four-line `position()` over bytes with
   an early exit, at 22.52% of the profile, refused for legality. If the
   project wants a target the five families can reach, the selection
   criterion should be "counted loops over contiguous data" and not
   "no interpreter".

### 61. Deviations, script problems found, and what is not done

**Deviations from the recipe, all deliberate and all listed:**

- `CARGO_PROFILE_RELEASE_STRIP=none` is added for this target, because jaq's
  workspace sets `strip = true` and every analysis script in this repository
  needs the symbol table and DWARF (section 50). Frozen and recorded, like
  panic and debuginfo.
- `BENCH_CPU=4` instead of 2 (core 2 instead of core 1, SMT sibling idle),
  so that a second agent measuring oxipng on CPU 2 cannot contend for the
  same physical core. Comparisons are only ever made within this target.
- `BENCH_GAP_MS=250` and `--stdout devnull`, both new and both explained in
  section 55. The defaults are unchanged, so the toy and zopfli commands in
  the earlier sections still reproduce.
- **Group 4 was not swept.** Section 28 settled it on zopfli and the budget
  went to group 5's four extra unroll points instead.
- `REPRO=1` and `DEBUG0=1` were not run (section 53 says why).
- Each case names its input file 2-8 times instead of using one large file
  (section 55). This is a property of the frozen case set, not of the
  harness.

**Problems found in this repository's own scripts, and what was done:**

1. `TARGET=jaq source scripts/target_common.sh` still does not work
   (section 31.6's bash behaviour); `export TARGET=jaq` first. The `*)` arm
   added then did its job here.
2. `scripts/remark_attribution.py` wrote a **5.4 GB**
   `remark-attribution.json` on this target --- one record per (remark
   location x candidate function), and jaq has 46363 locations with large
   candidate sets. A `--no-dump` flag was added; the printed reports do not
   use the file.
3. The same script's DebugLoc -> function attribution is **not usable at
   this scale**: 34256 of 46363 locations are ambiguous and the per-function
   report is topped by crates (`regex_automata`, `jiff`, `saphyr_parser`)
   that execute zero blocks. Section 29.5 flagged this on zopfli; jaq
   settles it. The working method is the reverse one --- start from the
   profile's hot symbols, map their instructions to source lines, look up
   the remarks there --- and `scripts/cost_hot_loops.py` now implements it
   for the `cost` class.
4. `scripts/profdata_hotness.py --binary` ran one `objdump` per symbol,
   which is 5726 processes on this binary. It still completes, but
   `scripts/interp_share.py` does the same work in a single `objdump` pass
   (2.5 s) and adds the backedge count, so it is what section 54 uses.

**Two things the spec should say and does not** (reported, not edited):

- **SPEC.ja.md 3's "the build is deterministic"** holds for a pure-Rust
  target and fails for a target with a `cc`-built dependency. jaq's
  `.text` hash changes between two builds of the same configuration because
  mimalloc's C prints `__DATE__ __TIME__`
  (`libmimalloc-sys-0.1.49/c_src/mimalloc/v*/src/options.c:236`). SPEC.ja.md
  6.3's `.text` skip criterion therefore needs a normalised fallback, which
  `scripts/norm_code_diff.py` now provides and which was validated on two
  builds of one configuration before being used.
- **SPEC.ja.md 8.5 / section 31.2's trip-count method is unsound.** It reads
  `Block counts[0]` as the function entry count. This profile says
  `entry_first = 0`, and on jaq `counts[0]` is demonstrably not the entry
  block (section 56). The header/backedge derivation should replace it, and
  zopfli's `<ZopfliHash>::update` figure should be re-derived that way
  before it is quoted again.

**Not done here:**

- The Stage 2 plugin, and therefore the *real* `total_score` the
  SPEC.ja.md 6.1-4 gate is defined against. Section 54's numbers are a
  profile-weight substitute and are labelled as one everywhere.
- Reference arm R (SPEC.ja.md 9) as a measured arm; section 50 records what
  its profile would be, and section 59 measures PGO on/off under the frozen
  recipe instead, which is a different and smaller comparison.
- Post-hoc attribution with `perf` / `callgrind` (SPEC.ja.md 10): not
  needed, because no configuration produced a difference worth attributing.
- A case set that exercises jaq's *filter evaluation* rather than its
  parser. All three cases here are parse-dominated (`jaq_core` is 5.09% of
  the profile), which is realistic for `jaq '.' big.json` and unrepresentative
  of a heavy filter over a small document. If Stage 1 or Stage 2 wants to
  claim anything about the interpreter, it needs a fourth case, and section
  54's gate answer would have to be recomputed on it.
- The `vectorize.width` metadata FP-reassociation question (section 13)
  remains open, and jaq can answer it where zopfli could not: it has ten
  `cannot prove it is safe to reorder floating-point operations` sites in
  `libm`. They are not on the hot path, but they are a test case.


## Stage 0 (oxipng) --- the target whose hot loop is not Rust

Date: 2026-09-21, same machine and same pinned toolchain as every section
above (rustc 1.100.0-nightly bba531001 / LLVM 23.1.1). oxipng is SPEC.ja.md
6.4's "replacement / transfer candidate" row, run as a numeric candidate for
SPEC.ja.md 1.3-1: does *any* target have headroom for loop hints over
`O3 + target-cpu=native + fat LTO + PGO`?

**Sections are numbered 40-49.** The jaq Stage 0 was written concurrently by
another agent and took 50 onwards, so the two blocks do not collide even
though the jaq block appears earlier in this file. The two runs shared the
machine, which section 44 records as a measurement caveat.

Reproduce with:

```
python3 targets/oxipng/workloads/gen.py            # the six inputs, fixed seeds
export TARGET=oxipng                               # `TARGET=x source` does not work (section 31.6)
REUSE_PROFDATA=0 REPRO=1 scripts/target_pgo_baseline.sh
cc -O2 -fPIC -shared -o /tmp/ipsample.so scripts/ipsample.c
scripts/ipsample.py --binary target-oxipng-pgo-use/x86_64-unknown-linux-gnu/release/oxipng /tmp/s-*.txt
scripts/profdata_hotness.py pgo/oxipng/merged.profdata --top 20 \
    --binary target-oxipng-pgo-use/x86_64-unknown-linux-gnu/release/oxipng
scripts/remark_attribution.py --bin target-oxipng-pgo-use/x86_64-unknown-linux-gnu/release/oxipng \
    --log remarks/oxipng/baseline-build.log \
    --src-prefix targets/oxipng/src/src --sym-filter oxipng --out artifacts/oxipng-attr
scripts/target_aa.sh 15 3
BENCH_SET=training RUNS=15 WARMUP=3 scripts/target_headroom.sh
```

New this section: `scripts/ipsample.c` + `scripts/ipsample.py` (an LD_PRELOAD
`ITIMER_PROF` instruction-pointer sampler, because SPEC.ja.md 10's `perf` and
`callgrind` are both absent and `gdb -p` cannot attach at
`ptrace_scope=1`), `targets/oxipng/workloads/gen.py`, an `oxipng` branch in
`scripts/target_common.sh` and `scripts/target_pgo_baseline.sh`, and a third
disqualification-filter check (`cargo tree -e normal,build`).

### 40. The target: vendored oxipng, and a feature set that cannot be satisfied

```
$ git submodule add https://github.com/oxipng/oxipng targets/oxipng/src
$ cd targets/oxipng/src && git checkout v9.1.5
$ git log -1 --format='%H %ci' && git describe --tags
c7d462f909e9c6ebc8d32820d83a6119b681cad6 2025-04-26 01:19:57 +0200
v9.1.5
```

Pinned to the **v9.1.5** tag, commit
`c7d462f909e9c6ebc8d32820d83a6119b681cad6`, the latest release. Nothing in the
submodule is edited; everything is driven by `CARGO_PROFILE_RELEASE_*`,
`CARGO_ENCODED_RUSTFLAGS`, the repository's `rust-toolchain.toml`, an explicit
`--target`, a per-variant `CARGO_TARGET_DIR` and `--locked`.

**The brief for this run said "default features minus anything that pulls C
SIMD". That is not satisfiable on oxipng 9.1.5.** From its `Cargo.toml`:

```
[dependencies]
libdeflater = "1.23.1"          # NOT optional
zopfli = { version = "0.8.2", optional = true, ... }

[features]
default = ["binary", "parallel", "zopfli", "filetime"]
system-libdeflate = ["libdeflater/dynamic"]
freestanding = ["libdeflater/freestanding"]
```

- `libdeflater` is an unconditional dependency. `libdeflate-sys` builds the
  vendored libdeflate **C** sources with the `cc` crate. `system-libdeflate`
  only switches static linking for dynamic and `freestanding` only removes
  libc; neither removes the C.
- The `zopfli` feature is the **pure-Rust** zopfli crate (the previous
  target), not a C library, and it is selected only by `--zopfli` at runtime,
  so it is dead code at `-o 2`.

So the only pure-Rust deflate oxipng can use is the crate this study already
measured flat, at `--zopfli` speeds. **SPEC.ja.md 6.4's oxipng row, "turn off
the libdeflate feature and pin rayon to a single thread", is factually wrong
for 9.1.5: there is no libdeflate feature to turn off.**

Features actually used, and why:

```
--locked --no-default-features --features binary,filetime
```

| feature | state | reason |
|---|---|---|
| `binary` | on | `[[bin]] required-features`; without it there is no CLI |
| `filetime` | on | kept from the default set; inert without `--preserve` |
| `parallel` | **off** | oxipng ships its own single-threaded shim in `src/rayon.rs` for exactly this build, so the binary is single-threaded *by construction*. Note the consequence: **`--threads` only exists when `parallel` is on**, so there is no flag to pass |
| `zopfli` | **off** | dead code at `-o 2`; including it would add its loops to the remark landscape for nothing |

Reference arm R (SPEC.ja.md 9) --- the effective release profile if `jev-opt`
overrode nothing:

```
$ sed -n '/^\[profile\.release\]/,/^\[/p' targets/oxipng/src/Cargo.toml
[profile.release]
lto = "fat"
strip = "symbols"
panic = "abort"
```

So arm R is **opt-level 3, lto fat, codegen-units 16, panic abort, stripped,
no `target-cpu=native`, no PGO** --- a much stronger arm R than zopfli's.
`strip = "symbols"` has to be overridden (`CARGO_PROFILE_RELEASE_STRIP=none`,
set in the `oxipng` branch of `scripts/target_common.sh`), because a stripped
binary has no symbol table and no DWARF and every analysis script here would
silently find nothing.

### 41. Workloads: three kinds, two disjoint splits, one generator

`targets/oxipng/workloads/gen.py` (standard library only, no network, fixed
seeds). Training and holdout differ only in the seed.

```
$ python3 targets/oxipng/workloads/gen.py
8f35c0e2d9b871734948f264e78d3c9152ba13d0fa062d1c9ae7ba5840d6069d   10248623  train-photo.png    2048x2048 seed=20260921201
12f61332a615b8e794b5d10cf0fe6cf4be31c5b67168884ffeab57084d237e05   10721871  train-alpha.png    3072x3072 seed=20260921202
bd9de2d9bccb6a2a2fbad69bca9cc42c40697bb4106f0e56793d00bbef0a2eea    6195385  train-palette.png  3072x3072 seed=20260921203
5f6e730a8b89b4745aacfad2ba9a1cb0f8818b02c6b0b727340c644d35db96d8   10248287  hold-photo.png     2048x2048 seed=20260921301
829b0371b4bbeee1062f475ac4ecd1b47adb9b5bc278484b6cb27d0f4fa9da94   10721716  hold-alpha.png     3072x3072 seed=20260921302
a655d7f52ec32b67aeaee2714fd71052504df30103ca171907bb26d2932c2a7e    6194710  hold-palette.png   3072x3072 seed=20260921303
```

| kind | content | colour type | PGO-baseline wall time (`-o 2`) |
|---|---|---|---|
| photo | RGB8 gradient plus 3-bit noise, nearly incompressible | 2 | 1.43 s |
| alpha | RGBA8, a 64x64 repeated tile plus an alpha ramp | 6 | 1.48 s |
| palette | indexed 8-bit, 256-entry PLTE, structured indices | 3 | 1.97 s |

Every case clears SPEC.ja.md 10's one-second floor. The sizes were chosen for
that: **1024x1024 RGB at `-o 2` takes 247 ms**, far too short, and raising the
preset instead (`-o 4` on 1024x1024 is 753 ms) would have shifted even more of
the time into the C compressor, which section 42 shows is the whole problem.

Two generator traps worth recording, both hit here:

- **The noise must not touch the per-row filter byte.** The first version
  XOR-ed noise over the whole zlib stream including each row's filter-type
  byte, which produced filter types 5-7. Those do not exist, and oxipng
  rejected the file in 45 ms with exit code 1 --- a "workload" that measures
  nothing. `add_filter_bytes()` now inserts the filter bytes after the noise.
- **oxipng writes no output file when it finds no improvement.** The inputs
  are deflated at zlib level 6 so that oxipng always improves them, and
  `run_correctness` records `NO-OUTPUT` (rather than silently hashing
  nothing) if the file is missing.

**Correctness is the sha256 of the produced PNG.** oxipng prints only
progress on stderr, so `bench.py`'s `stdout_mismatches` is vacuously empty
here and must not be read as a correctness pass, exactly as for zopfli.
Output is deterministic:

```
========== 0b. output determinism (same binary, same inputs, twice) ==========
OUTPUT DETERMINISM: MATCH
```

### 42. The disqualification filter passes oxipng, and it is wrong to

SPEC.ja.md 6.1-2's two checks, run by `scripts/target_pgo_baseline.sh`:

```
========== disqualification filter (hand-written SIMD) ==========
$ cargo tree -e normal | grep -iE 'memchr|simd|wide|std_detect'
(no match)
$ grep -rlE 'core::arch|_mm_|_mm256|target_feature' targets/oxipng/src/src targets/oxipng/src/*/src
(no match)
```

**Both pass. Both are wrong**, and the profile-share override that rescued
zopfli in section 20 cannot correct them here, because it is blind in the same
place. What the binary actually contains:

```
$ nm --defined-only target-oxipng-pgo-use/.../oxipng | grep -iE ' [tT] .*(avx|sse|pclmul|vnni|bmi)'
adler32_x86_avx2                    crc32_x86_pclmulqdq
adler32_x86_avx2_vnni               crc32_x86_pclmulqdq_avx
adler32_x86_avx512_vl256_vnni       crc32_x86_vpclmulqdq_avx2
adler32_x86_avx512_vl512_vnni       crc32_x86_vpclmulqdq_avx512_vl256
adler32_x86_sse2                    crc32_x86_vpclmulqdq_avx512_vl512
deflate_decompress_bmi2             ... plus memchr::arch::x86_64 (from std)
$ nm -S --defined-only <bin>  # split by the v0 mangling prefix
rust text symbols:      1265,  733394 bytes
non-rust text symbols:    61,   99236 bytes
```

Three separate blind spots, each worth a spec change:

1. **The `cargo tree` grep looks for the wrong names.** The C arrives as
   `libdeflater -> libdeflate-sys -> cc`, and none of `memchr|simd|wide|
   std_detect` matches any of those three.
2. **The source grep looks in the wrong directory.** libdeflate's C lives in
   `~/.cargo/registry/src/.../libdeflate-sys-1.23.1/libdeflate/lib/x86/`, not
   under the target's `src/`.
3. **A dependency can also arrive through the prebuilt `std` rlibs**, which
   `cargo tree` on the target does not list at all. That is where the
   `memchr::arch::x86_64::...::find_sse2` symbol above comes from (std's
   backtrace machinery). Harmless here --- it is never hot --- but it is a
   fourth way for hand-written SIMD to enter a binary unnoticed.

A third check was added to the script for this:

```
$ cargo tree -e normal,build | grep -iE 'cc v|-sys v|cmake v|bindgen v'
cc v1.2.19
libdeflate-sys v1.23.1
linux-raw-sys v0.9.4          # a false positive: pure Rust
```

**`-e build` alone does not work** --- it lists only the root package's own
build-dependencies and does not descend, so it printed `(no match)` for a C
dependency two levels down. `-e normal,build` is what finds it. The first
version of this check in `target_pgo_baseline.sh` had exactly that bug.

### 43. The profile-share override cannot see the problem, and says the opposite

Section 20 rescued zopfli from a filter hit by checking the profile share of
the flagged crates. Doing the same here gives a **confidently wrong answer**,
and that is the most transferable finding in this section.

```
$ scripts/profdata_hotness.py pgo/oxipng/merged.profdata --top 20 --binary <baseline>
1592 function records, total block count 2312803624
  max=     346030080  sum=    1064108056  (46.01%)  <oxipng::png::PngImage>::filter_image      [1612 insns, 161 vector]
  max=     188676096  sum=    1205214655  (52.11%)  <oxipng::filters::RowFilter>::filter_line  [1134 insns,  54 vector]
  max=       9437184  sum=       9439494  ( 0.41%)  oxipng::reduction::palette::reduced_palette
  max=       9437183  sum=       9445877  ( 0.41%)  oxipng::reduction::palette::sorted_palette
  max=       4718593  sum=      23592970  ( 1.02%)  oxipng::reduction::alpha::reduced_alpha_channel
  ...
these 20 functions hold 100.00% of the total block count
```

Read at face value: two pure-Rust byte-filter functions hold **98.1%** of the
profile, oxipng is an ideal loop-hint target, proceed. That reading is an
artefact. **`-Cprofile-generate` instruments Rust only.** The `cc`-built
objects carry no counters, so a profdata share is a share *of the Rust code*,
normalised to 100%, no matter how little of the program's time the Rust code
holds. The denominator is wrong and nothing in the output says so.

What the machine actually spends its time on, measured by sampling the
instruction pointer (`scripts/ipsample.c`, `ITIMER_PROF`, 500 us, three runs
per case, 1040-1448 samples each, symbols classified by the `_R` v0-mangling
prefix):

| workload | Rust | C (libdeflate) | outside the exe (libc) | mean wall |
|---|---|---|---|---|
| photo | **11.39%** | 84.59% | 4.01% | 1.43 s |
| alpha | **28.02%** | 63.92% | 8.06% | 1.48 s |
| palette | **9.63%** | 87.45% | 2.92% | 1.97 s |
| wall-time-weighted over the three | **15.7%** | 80.1% | 4.2% | |

```
=== photo ===                                 === alpha ===
 38.56%  [c   ] deflate_compress_lazy          24.78%  [c   ] deflate_compress_near_optimal
 19.79%  [c   ] deflate_compress_near_optimal  23.03%  [c   ] deflate_compress_lazy
 16.43%  [c   ] deflate_find_min_cost_path     18.48%  [rust] <RowFilter>::filter_line
  8.22%  [rust] <RowFilter>::filter_line        9.19%  [rust] <PngImage>::filter_image
  5.60%  [c   ] deflate_flush_block             6.57%  [c   ] deflate_find_min_cost_path
  3.17%  [rust] <PngImage>::filter_image        2.71%  [c   ] deflate_decompress_bmi2

=== palette ===
 44.61%  [c   ] deflate_compress_lazy      5.83%  [rust] <RowFilter>::filter_line
 21.10%  [c   ] deflate_compress_near_optimal
 16.73%  [c   ] deflate_find_min_cost_path 3.42%  [rust] <PngImage>::filter_image
```

Every sample above is from the **PGO baseline binary under test**, three runs
per case. (A first pass on a plain release build of the same source gave
10.19 / 27.41 / 9.05% --- the same picture.)

An independent cross-check that needs no profiler at all: rebuild with the
**Rust** code at a lower opt-level while forcing the C to stay at `-O3`
(`CARGO_PROFILE_RELEASE_OPT_LEVEL=1 CFLAGS=-O3`), and verify with
`scripts/func_code_diff.py` that the C is byte-identical:

```
## deflate_compress_lazy2
  rust-O3 build   2296 insns,  416 vector, code adc5a45794ce66f3
  rust-O1 build   2296 insns,  416 vector, code adc5a45794ce66f3   <- identical
## crc32_x86_vpclmulqdq_avx2
  rust-O3 / rust-O1    377 insns, 171 vector, code 3510cb230b5b05dd (both)

wall time, 2048x2048 RGB, -o 2, three runs each:
  rust-O3   1016 / 1003 /  986 ms
  rust-O1   1054 / 1049 / 1039 ms      +4.5%
  rust-O0   9219 / 8924 / 9550 ms      9.4x
```

**Dropping every Rust optimisation from O3 to O1 costs 4.5% of the wall
time.** (`cc` takes its `-O` level from cargo's `OPT_LEVEL`, so `CFLAGS=-O3`
is required to hold the C fixed; the hashes above are the evidence that it
worked.)

**The two measurements are consistent, which is weaker than agreement, and
the difference is worth being precise about.** They do not measure the same
quantity:

- The sampler measures a share of **CPU time** (`ITIMER_PROF` counts
  user+sys, not wall). On a single-threaded process that spends 1-2% in the
  kernel this is within noise of a wall share, but it is not one by
  definition.
- The O1 differential measures **wall time** and bounds nothing on its own:
  if Rust is share `S` and O1 code is `k` times slower than O3 code, the
  observed 4.5% is `S(k-1)`. `k = 1.3` implies `S = 15%`, `k = 2` implies
  `S = 4.5%`, `k = 3` implies `S = 2.3%`. `k` was not measured, so the
  differential cannot pin `S` down by itself.

What it does is rule out the only way the sampler could be badly wrong ---
if the sampler had missed a large block of Rust time, O1 would have cost far
more than 4.5%. Every plausible `k` puts `S` inside the sampler's 9-28%
band. Taken together: **the part of oxipng that any rustc or LLVM flag can
touch is a single-digit to low-twenties percentage of its runtime.**

**This is a stronger form of "out of reach" than anything earlier in this
study.** jaq's interpreter layer (SPEC.ja.md 6.1-4) and zopfli's
data-dependent byte scans (section 31.5) are at least *visible* to the
compiler; a loop hint simply has nothing to offer them. libdeflate is invisible
to `-Cllvm-args`, to `-Ctarget-cpu`, to `-Cprofile-generate` and to the LLVM
pass plugin that Stage 2 will add, all at once, and it is already
hand-vectorised with AVX-512 kernels.

### 44. PGO baseline (SPEC.ja.md 3, 13 day-0 items 2-3)

```
$ export TARGET=oxipng
$ REUSE_PROFDATA=0 REPRO=1 scripts/target_pgo_baseline.sh
========== b. training run (instrumented) ==========
  trained on train-photo.png -> 5656844 bytes
  trained on train-alpha.png -> 902346 bytes
  trained on train-palette.png -> 3581565 bytes
training run wall time: 5101 ms
========== c. llvm-profdata merge ==========
b4abad926d1becd7f77f9cfc3c369f8faa8a28f24d265ecb47ef41e3dff9e3bc  pgo/oxipng/merged.profdata
Instrumentation level: IR  entry_first = 0  instrument_loop_entries = 0
Total functions: 1592          Total number of blocks: 20903
Maximum function count: 334261 Total count: 2312803624
Maximum internal block count: 346030080
========== d. PGO baseline build (-Cprofile-use) + remarks ==========
--- remark lines total ---            68359      (12802 unique after sort -u)
--- hash mismatch ---                 0
--- no profile data available for function --- 0
--- all warning: lines ---            0
--- .text sha256 ---
5b2bd442736f24c377d0f230ba107ecced4c35dd9e2b7fb51881fc0f708f8ed7
========== e. checksum comparison (plain release vs PGO baseline) ==========
CHECKSUMS: MATCH
========== f. .text hash, debug=1 vs debug=0 ==========
TEXT HASH: DIFFER        debug=0 checksums: MATCH
```

**`merged.profdata` sha256 =
`b4abad926d1becd7f77f9cfc3c369f8faa8a28f24d265ecb47ef41e3dff9e3bc`**, used by
every arm and every sweep configuration below. **Zero profile-use warnings of
any kind** on a program with 1592 instrumented functions across 22 crates ---
a third target, and the strongest instance yet, of SPEC.ja.md 3's "the same
profdata fits both arms". Section 5's debuginfo finding reproduces: `.text`
differs between debug=1 and debug=0 while the output does not. Builds are
cheap: 14-18 s each, `.text` 842678 bytes.

**Profdata reproducibility fails, and for a new reason.** zopfli's failure
(section 22) was cosmetic --- the counters were identical and only the
embedded build-id differed. oxipng's counters themselves differ:

```
========== c2. profdata reproducibility (second training run, separate directory) ==========
b4abad926d1becd7f77f9cfc3c369f8faa8a28f24d265ecb47ef41e3dff9e3bc  merged.profdata
223b65cee1a50190c9339067c66435c5b5e8746d33f6e69018bf6b029f7b3163  merged-repro.profdata
PROFDATA REPRODUCIBLE: NO --- the two merges differ
```

23 of 523288 bytes differ; `llvm-profdata show --all-functions --counts`
diffs to **12 lines in three functions**, all of them `indexmap` internals:

```
<IndexMapCore<rgb::Rgba<u8>, ()>>::insert_full   Block counts: [154, 12032, ...]
                                                              [160, 12032, ...]
<IndexMap<oxipng::filters::RowFilter, ()>>::insert_full  [1, 0, 0, 20, ...]
                                                         [0, 0, 0, 20, ...]
Total count: 2312803624  vs  2312803629
```

Cause: `indexmap`'s default hasher is `RandomState`, seeded per process, so
the probe sequence --- and therefore the block counts of `insert_full` ---
differs from run to run. Re-running the **same** instrumented binary twice
reproduces the failure (2 bytes differ), which rules out the rebuild as the
cause and pins it on the process-level seed. The program's **output is
unaffected** (`OUTPUT DETERMINISM: MATCH`, `CHECKSUMS: MATCH`): the map is
insertion-ordered, only the probing is not.

**Consequence for the spec.** SPEC.ja.md 3 says "profdata reproduces; if it
does not, record the cause and move on", and SPEC.ja.md 8.4 makes
`basis.pgo_profile_sha` equality the evidence that both arms used the same
profile. For a target with a randomly-seeded hasher, that sha is reproducible
only within one training run; it still proves "both arms used *this* profile",
which is what the check is for, but it can never prove "this profile is the
one the recipe produces". Two targets in a row now fail the check for two
unrelated reasons, so the check should be restated as a same-run identity,
not a recipe identity.

**Measurement caveat for everything from here on.** A second agent was
running the jaq Stage 0 on this machine at the same time, pinned to core 2
(CPU 4); oxipng is pinned to core 3 (CPU 6, SMT sibling CPU 7 idle). The two
never share a physical core, but they do share the chip, the memory
controller and the L3, and the other run's `cargo build -j` bursts are not
synchronised with anything here. The A/A below measures the noise floor under
exactly those conditions, and every configuration is round-robin interleaved
against the baseline within one `bench.py` invocation, which is what that
design is for --- but the earlier sections' numbers were taken on an idle
machine and these were not.

### 45. The loop landscape: the one Rust loop worth hinting is already at byte width

```
$ scripts/remark_attribution.py --bin target-oxipng-pgo-use/.../oxipng \
    --log remarks/oxipng/baseline-build.log \
    --src-prefix targets/oxipng/src/src --sym-filter oxipng \
    --out artifacts/oxipng-attr --top 25
remarks parsed: declined=1289, reason=5099, slp=7036, vectorized=22
symbols walked: 315 (213449 bytes of .text)
instructions:   47544
unattributed remark locations: 6444 of 13446
ambiguous (DebugLoc resolving to >1 function): 5400
remarks whose file path matched >1 DWARF file: 320
```

Out of 68359 remark lines: **22 loops vectorized, 1289 refused**, 7036 SLP
lines out of reach of every loop-metadata family. The reason classes,
re-using section 23's table (26 of the 27 strings were already known; the new
one, `Store instruction cannot be vectorized`, stays `unknown`):

| class | lines |
|---|---|
| unsupported | 2995 |
| unknown | 1202 |
| legality | 622 |
| **cost** | **280** (143 interleave, 137 vectorization) |

(2995 + 1202 + 622 + 280 = 5099 reason lines, 27 distinct strings. 26 were
already in `scripts/remark_attribution.py`'s table from section 23; the one
new string, `Store instruction cannot be vectorized`, stays `unknown`.)

#### The 22 vectorized loops, and the attribution problem at its worst

```
$ grep -E 'vectorized loop \(' remarks/oxipng/baseline-build.log | sort | uniq -c | sort -rn
      7 library/core/src/slice/iter/macros.rs:279:24: vectorized loop (width: 4, interleave: 4)
      3 library/core/src/slice/iter/macros.rs:279:24: vectorized loop (width: 4, interleave: 2)
      2 library/core/src/iter/range.rs:1103:12:        vectorized loop (width: 32, interleave: 4)
      2 <unknown>:0:0:                                  vectorized loop (width: 16, interleave: 1)
      1 library/core/src/slice/mod.rs:2165:12:          vectorized loop (width: 8, interleave: 1)
      1 library/core/src/slice/iter/macros.rs:279:24:   vectorized loop (width: 32, interleave: 4)
      1 library/core/src/slice/iter/macros.rs:279:24:   vectorized loop (width: 32, interleave: 1)
      1 library/core/src/slice/iter/macros.rs:180:28:   vectorized loop (width: 4, interleave: 2)
      1 library/core/src/slice/iter/macros.rs:180:28:   vectorized loop (width: 4, interleave: 1)
      1 library/core/src/iter/range.rs:1145:12:         vectorized loop (width: 4, interleave: 4)
      1 library/alloc/src/vec/into_iter.rs:381:19:      vectorized loop (width: 8, interleave: 2)
      1 <unknown>:0:0:                                  vectorized loop (width: 8, interleave: 1)
```

**Not one of the 22 has a DebugLoc in oxipng's own sources.** Every vectorized
loop in this binary is an inlined `core` iterator, and 5400 of 13446 decision
lines resolve to more than one function --- worse than zopfli's 1328 of 6067,
on a binary with four times as many crates. `remark_attribution.py`'s
per-function report is therefore unusable on oxipng: the top ten functions all
report the same shared set of `slice::iter` loops. Section 29-5's conclusion
("the SPEC.ja.md 7 DebugLoc -> function attribution degrades badly at scale")
holds a fortiori. A second path-collision hazard shows up here too --- 320
remark paths matched more than one DWARF file, because `src/lib.rs`,
`src/parser/...`, `src/raw/mod.rs` and `src/control/bitmask.rs` belong to
clap, hashbrown and bitvec, not to oxipng.

So the landscape has to be read from the machine code instead.

#### What the two hot Rust functions actually contain

```
$ objdump -d <filter_line> | grep '%[xyz]mm' | histogram of mnemonics
     36 vmovdqu
     18 vpsubb        (32 ymm operands, 40 xmm operands)
```

The static histogram has more `xmm` than `ymm` operands, which would be the
wrong thing to conclude from. The loop body settles it:

```
   337a0: vmovdqu (%rdx,%rax,1),%ymm0        337b7: vpsubb (%r8,%rax,1),%ymm0,%ymm0
   337a5: vmovdqu 0x20(%rdx,%rax,1),%ymm1    337bd: vpsubb 0x20(%r8,%rax,1),%ymm1,%ymm1
   337ab: vmovdqu 0x40(%rdx,%rax,1),%ymm2    337c4: vpsubb 0x40(%r8,%rax,1),%ymm2,%ymm2
   337b1: vmovdqu 0x60(%rdx,%rax,1),%ymm3    337cb: vpsubb 0x60(%r8,%rax,1),%ymm3,%ymm3
                        ... four 32-byte stores, then the backward branch
   338c0: vmovdqu 0x60(%rdx,%rsi,1),%xmm0    <- the 16-byte REMAINDER loop
   338c6: vpsubb 0x60(%r8,%rsi,1),%xmm0,%xmm0
   338d3: add $0x10,%rsi ; cmp %rsi,%r9 ; jne 338c0
```

`<oxipng::filters::RowFilter>::filter_line` is the PNG row filter, and its Sub
and Up cases are `data.iter().skip(bpp).zip(data.iter()).map(|(cur, last)|
cur.wrapping_sub(*last))` fed to `Vec::extend`. **The main loop is four
`vpsubb` on `ymm` per iteration: VF 32, interleave 4, 128 bytes of filtering
per backward branch.** All the `xmm` instructions are the 16-byte epilogue and
its unrolled peel; they run a handful of times per row against ~30 iterations
of the `ymm` loop. 32 bytes is the widest byte operation this CPU has (no
AVX-512, SPEC.ja.md 3), so the width family has literally nothing left to
ask for. This is the exact loop SPEC.ja.md 6.4 named when it
listed oxipng ("PNG filters are pure byte loops with obvious vectorize
room"), and the prediction is **wrong in the most complete way possible**: the
room is not there because the baseline already took all of it.

It is worth contrasting with the toy (section 15). The toy's `count_quotes`
was stuck at VF 4 because its accumulator was `i64`, and forcing VF 32 made it
2.2x *slower* by adding a three-stage widening tree. Here the operation is
byte-in / byte-out with no accumulator, so there is no type to widen and VF 32
is simply what the cost model picks. **"Byte loop" is not the property that
predicts width headroom; "byte loop whose result type is wider than a byte" is
the one that predicted the toy's trap, and neither predicts an opportunity.**

`<oxipng::png::PngImage>::filter_image` (161 vector instructions of 1612) is
the filter-selection heuristic --- `vpsadbw`, `vpshufb`, `vpcmpeqb`,
`vpmovmskb`, `vpaddd` --- i.e. the entropy and bigram estimators, also already
vectorised, largely by SLP (7036 SLP remark lines) rather than by the loop
vectorizer.

#### Trip counts (SPEC.ja.md 8.5, with section 31.2's caveat)

Section 31.2 found a `cost`-declined zopfli loop whose average trip count was
below 1, i.e. a loop where the cost model was simply right. oxipng has the
opposite shape, and it does not help:

```
$ grep -A3 '9RowFilter11filter_line:' artifacts/oxipng-day0/profdata-functions.txt
    Block counts: [..., 188676096, 128974848, ..., 46080, ..., 128928768, 46080, ...]
$ grep -A3 '8PngImage12filter_image:' artifacts/oxipng-day0/profdata-functions.txt
    Block counts: [0, 57615360, ..., 8192, 0, 298885120, 10485760, ..., 346030080, ...]
```

Without the Stage 2 plugin there is no way to say which counter is a given
loop's header (section 31.2 had the same limitation), so these are ratios, not
trip counts. But the orders of magnitude are unambiguous. In `filter_image`
the counter **8192** is exactly the number of scan lines in the three training
images (2048 + 3072 + 3072), and the hot block next to it runs **346030080**
times, a ratio of 42240. That is far more than a scan line has bytes (at most
12288), so the block is not "the row loop": at `-o 2` each row is filtered and
scored for four candidate filters, and the entropy and bigram estimators then
walk a 256-entry histogram, so 42240 is a product of several nestings. The
point here is only the order of magnitude, which is thousands, not the
factorisation. In `filter_line` the
smallest non-zero counter is **46080** against a hot block of **188676096**,
about 4094 to one. Either way these are long, countable, byte-typed loops with
nothing like zopfli's `src/hash.rs:150` problem (average trip count below 1,
section 31.2) --- **and the vectorizer has already taken them.** A large trip
count is a necessary condition for width headroom, not a sufficient one:
zopfli failed the necessary condition on one of its two candidate loops, and
oxipng passes it on both while still having nothing to gain.

### 46. A/A noise floor and the minimum detectable effect

```
$ export TARGET=oxipng && scripts/target_aa.sh 15 3
$ sha256sum artifacts/oxipng-aa/A1 artifacts/oxipng-aa/A2
06714b8d17e996c2b6178ceda923eb599f85acdc7f7cf9e833612ee14364a369  A1
06714b8d17e996c2b6178ceda923eb599f85acdc7f7cf9e833612ee14364a369  A2
```

Build determinism holds: `target_aa.sh` rebuilt the PGO baseline from scratch
in a different target directory and got the same `.text` hash
`5b2bd442...` as section 44. 90 timed samples (2 labels x 3 workloads x 15
rounds), warmup 3, `taskset -c 6` (SMT sibling CPU 7 idle), holdout inputs:

| workload | A1 mean ms | A2 mean ms | ratio A1/A2 | 95% CI | half-width |
|---|---|---|---|---|---|
| photo | 1430.4 | 1452.6 | 0.9847 | [0.9655, 0.9995] | **1.70%** |
| alpha | 1477.8 | 1480.1 | 0.9985 | [0.9900, 1.0061] | **0.80%** |
| palette | 1971.1 | 1971.9 | 0.9996 | [0.9960, 1.0035] | **0.38%** |
| **aggregate (geomean)** | | | 0.9942 | [0.9862, 1.0004] | **0.71%** |

**Noise floor = worst per-workload half-width 1.70%; aggregate 0.71%.**
**MDE = max(2 x 1.70%, 3%) = 3.40%.**

Two things to read out of this that the earlier targets did not show.

- **The 3% floor does not bind here.** On the toy it bound at 1.22% and on
  zopfli at 0.29%; oxipng's 1.70% pushes the MDE above the floor for the first
  time in this study. The cause is visible in `photo`: mean 1452.6 against
  median 1420.8 for A2, i.e. a right tail, on cases of 1.4-2.0 s that should
  be as quiet as zopfli's 1.6-2.7 s ones.
- **The A/A aggregate CI very nearly excludes 1** ([0.9862, 1.0004] for two
  byte-identical copies of one binary). Six times noisier than zopfli's
  [0.9995, 1.0023]. The difference is the machine, not the target: a second
  Stage 0 (jaq) was running on core 2 throughout, with `cargo build -j`
  bursts. That is what an A/A is for --- the noise it measures is the noise
  the sweep will see --- but it is the reason the MDE below is 3.40% and not
  something near 1%.

### 47. Headroom sweep: 38 builds, zero correctness violations, nothing faster

```
$ export TARGET=oxipng
$ BENCH_SET=training RUNS=15 WARMUP=3 scripts/target_headroom.sh
```

Baseline plus 37 configurations, each the SPEC.ja.md 3 recipe --- same
`-Cprofile-use=pgo/oxipng/merged.profdata`, same
`-Ctarget-cpu=native -Csymbol-mangling-version=v0`, same
`CARGO_PROFILE_RELEASE_{OPT_LEVEL=3,LTO=fat,CODEGEN_UNITS=1,DEBUG=1,PANIC=unwind,STRIP=none}`,
same three `-pass-remarks*` flags, explicit `--target`, own
`CARGO_TARGET_DIR`, `--locked`, clean build --- plus that configuration's
knobs. Groups 0-5, i.e. zopfli's group 0-4 list plus the group 5 unroll
dimension section 31.3 added. Build time 14.3-15.2 s each, 38 builds in about
9 minutes. **No configuration failed to build.**

**Unlike every earlier sweep in this file, this one ran on the TRAINING
inputs** (`BENCH_SET=training`), which is what SPEC.ja.md 7 asks for and what
section 30 recorded as a deviation for zopfli. The holdout is untouched by the
sweep; the A/A in section 46 is the only thing that has seen it.

**Correctness: all 37 configurations produce byte-identical output on all six
inputs.** Zero violations, so the full set enters the judgement.

```
$ awk -F'\t' 'NR>1 && $3!="MATCH"' artifacts/oxipng-headroom/summary.tsv
(no output)
```

Only **two** configurations were skipped for timing on a bit-identical
`.text`: `g1-tailfold-prefer` and `g1-memcheck24`. Both were skipped on zopfli
too. Note the divergences from zopfli's skip list, all of which mean *more*
code motion on oxipng: `g3-loop-distribute` (+544 remark lines) and
`g3-loop-flatten` and `g4-prefer256` all change `.text` here, and
`g1-memcheck128` changes `.text` while `g1-memcheck24` does not.
`g4-prefer256` changing the code at all is new --- on zopfli it was
byte-identical, confirming znver3's 256-bit preference; oxipng's f32/u16
mixed code gives it something to do.

#### 47.1 The n=15 run is outlier-contaminated, and the contamination is in the base

1665 timed samples (37 labels x 3 workloads x 15 rounds), one interleaved
invocation. The raw aggregate table flags **16 of 36 configurations as
"+3.5 to +4.7% on `photo`", beyond the 3.40% MDE.** That cannot be real ---
the 16 include knobs that contradict each other --- and the raw samples say
what happened:

```
baseline  photo    1424.3 1442.7 1427.9 1439.1 1687.8 1459.7 1464.3 1427.3
                   1474.0 1488.8 1438.7 1497.1 1430.1 2010.0 1518.0
baseline  palette  ... 2603.2 ...   (median 2023.2)
```

**Two of the baseline's fifteen `photo` rounds are 16% and 38% slow, and one
`palette` round is 29% slow.** A single label's outliers bias all 36 ratios
against it in the same direction. Machine-wide the run is not drifting (the
per-round mean over all 37 labels goes 1418 -> 1470 ms and stays there); the
outliers are scattered, and the base label simply drew three of them.
Across the whole run **52 of 1665 samples sit more than 15% above their own
(label, workload) median** --- 3.1%, against zero such samples in zopfli's
A/A. This is the concurrent jaq run on core 2, and it is the second time this
file has had to say that `bench.py stats`'s mean-based statistic is not robust
enough for this machine (section 29-4).

The median cross-check that section 26 introduced for exactly this
(`artifacts/oxipng-headroom/median-crosscheck.txt`, ratio =
median(baseline) / median(config)) puts **every** configuration in
**[0.9834, 1.0151]** on the geomean, with max |per-case change| 3.52% (a
regression, `g5-count4` on `alpha`). Top and bottom:

| config | photo | alpha | palette | geomean |
|---|---|---|---|---|
| g2-inline325 | 1.0158 | 1.0225 | 1.0070 | **1.0151** |
| g2-inline500 | 1.0164 | 1.0178 | 1.0090 | 1.0144 |
| g3-gvn-hoist | 1.0197 | 1.0070 | 1.0041 | 1.0103 |
| g3-slp-100 | 1.0186 | 1.0081 | 1.0040 | 1.0102 |
| g1-maxbw | 1.0164 | 1.0124 | 1.0012 | 1.0100 |
| ... | | | | |
| g5-max1 | 1.0122 | 0.9866 | 0.9993 | 0.9993 |
| g5-count2 | 1.0036 | 0.9934 | 0.9945 | 0.9972 |
| g3-slp-neg20 | 0.9908 | 0.9969 | 0.9951 | 0.9943 |
| g5-count4 | 0.9957 | 0.9648 | 0.9901 | **0.9834** |

Even this still carries the artefact: the baseline's `photo` median (1459.7
ms) is above almost every configuration's (about 1440 ms), so the whole
`photo` column reads about +1.3% for reasons that have nothing to do with the
knobs.

#### 47.2 Confirmation at n=25: nothing improves oxipng, and two knobs hurt

Six labels --- the baseline, the three best on the median check and the two
worst --- re-measured in one interleaved invocation, n=25 warmup 3, 450
samples, same binaries, same pinning, same training inputs:

| config | aggregate ratio | 95% CI | half-width | photo | alpha | palette |
|---|---|---|---|---|---|---|
| g2-inline325 | 1.0048 | [0.9999, 1.0096] | 0.49% | +0.99% | +0.74% | -0.28% |
| g3-gvn-hoist | 0.9972 | [0.9919, 1.0019] | 0.50% | +0.02% | -0.67% | -0.19% |
| g1-maxbw | 0.9951 | [0.9894, 1.0006] | 0.56% | -0.33% | -0.51% | -0.64% |
| **g5-max1** | **0.9885** | **[0.9821, 0.9943]** | 0.61% | +0.01% | -3.07% | -0.37% |
| **g5-count4** | **0.9763** | **[0.9724, 0.9805]** | 0.41% | -0.71% | -4.93% | -1.41% |

The machine was quiet for this pass (half-widths 0.4-1.3%, comparable to
zopfli's A/A), and the picture is unambiguous:

- **`g2-inline325`, the best configuration in the whole study on this target,
  is +0.48% with a CI of [0.9999, 1.0096] --- it does not even exclude 1.**
  The +1.51% from the median cross-check was the baseline artefact.
- `g1-maxbw` and `g3-gvn-hoist` are indistinguishable from the baseline.
- The only two **real** effects are **regressions**: `-unroll-count=4` at
  -2.37% [-1.95%, -2.76%] and `-unroll-max-count=1` at -1.15%.
- The one per-workload figure beyond the 3.40% MDE in this run is
  `g5-count4` on `alpha` at **-4.93%** [-5.55%, -4.40%]. A regression.

**`-unroll-max-count=1` is worth a line on its own: it was the single best
knob on zopfli (+1.59%, section 31.3) and it is a 1.15% regression here.**
That is a fourth entry for section 29-1's "the candidate set must not be one
list".

#### 47.3 A process note: do not edit a bash script while it is running

`scripts/target_headroom.sh` aborted after writing `headroom.json` with

```
scripts/target_headroom.sh: line 240: unexpected EOF while looking for matching `"'
```

Bash reads a script incrementally, by byte offset, so the concurrent jaq
agent's edit to the same shared file changed what this already-running
instance read next. No data was lost --- the 1665 samples were already on
disk --- and the statistics above were produced by running the same
`scripts/bench.py stats` invocation the script would have run. Worth a rule
if this repository is ever driven by more than one agent again: **a shared
script must be edited by copy-and-rename, not in place, while a run is
outstanding.**

### 48. Stopping rule, and what oxipng says about the project

> Across groups 1-3, if (a) no configuration's aggregate speed-ratio CI lower
> bound exceeds the minimum effect size, **and** (b) no configuration improves
> a single case beyond the minimum effect size, record "this target is flat
> under the hint method" and swap the target.

Correctness precondition: **satisfied trivially --- all 37 configurations
produce identical output on all six inputs**, so nothing is excluded and the
rule reads on the full set. MDE = 3.40% (section 46).

- **(a)** The highest aggregate CI lower bound over all 36 timed
  configurations is **1.0075** (`g1-tfstyle-data-and-control`, n=15), against
  the required 1.0340; at n=25 the best configuration's lower bound is
  **0.9999**. **Not satisfied.**
- **(b)** No configuration improves any single case beyond 3.40%. The 16
  per-case flags in the n=15 run are the base-label outlier artefact of
  section 47.1, refuted by both the median cross-check and the n=25
  confirmation, where the largest genuine per-case improvement is **+0.99%**
  (`g2-inline325` on `photo`). The only per-case figure beyond the MDE that
  survives confirmation is a **regression** (`g5-count4` on `alpha`,
  -4.93%). **Not satisfied.**

**Outcome for oxipng: (a) no and (b) no --- "this target is flat under the
hint method; swap the target."** SPEC.ja.md 1.3-1 is **not met on oxipng**.

#### 48.1 Does oxipng have hint headroom? No, and for a reason the other targets did not have

Three targets have now come back flat, for three different reasons, and
oxipng's is the most conclusive:

| target | why flat | could a better plan change it? |
|---|---|---|
| toy | the one loop the width family reached had an `i64` accumulator, so VF 32 was 2.2x *slower* (section 15) | no --- the hint worked and the answer was wrong |
| zopfli | 67% of the profile is data-dependent early-exit byte scans the vectorizer refuses on analysis grounds; the one reachable loop is worth +1.6% (section 31.4) | marginally; the ceiling is half the MDE |
| **oxipng** | **80% of the wall time is in statically linked C** that no rustc flag, no `-Cllvm-args`, no PGO profile and no LLVM pass plugin can reach, and the 16% that is Rust is **already vectorised at the widest byte width the CPU has** | **no** |

The arithmetic is short. With the Rust share at 15.7% overall (section 43),
a global knob would have to make **every line of oxipng's Rust code 21%
faster** to move the aggregate by the 3.40% MDE (`1/(1 - 0.157x) = 1.034`).
On the one workload where the Rust share is largest (`alpha`, 28.0%) it would
still need 12%. And the code
it would have to speed up is `vpsubb` on `ymm` registers in a loop of ~4000
byte iterations --- the output of a cost model that already had all the
information a width hint could give it.

#### 48.2 Is there site-level room worth a Stage 2? No

SPEC.ja.md 6.3 is explicit that a global sweep bounds nothing, and section 28
used that to keep zopfli alive for Stage 2 on the strength of two hot,
integer, `cost`-declined loops. The same question, asked of oxipng, answers
itself in the other direction:

1. **The candidate list is two functions**, `<RowFilter>::filter_line` and
   `<PngImage>::filter_image`, and they are 11.4% / 28.0% / 9.6% of the wall
   time on the three cases.
2. **Both are already vectorised**, `filter_line` with `vpsubb` on 32-byte
   registers and `filter_image` with the `vpsadbw` / `vpshufb` / `vpmovmskb`
   entropy estimators. The width family's request is the state they are
   already in.
3. **The `cost` class, which is the one class a hint can overturn, has 280
   lines here, and not one of them is at an oxipng DebugLoc** that resolves to
   either function unambiguously --- the attribution is 5400-way ambiguous
   (section 45). Even choosing a site to ask Jev about is not currently
   possible on this target without the plugin.
4. **Every member of the width family was measured, globally, and none of
   them moved anything**: `g1-vw8/16/32`, `g1-maxbw`, `g1-maxbw-vw32`,
   `g1-ic1/2/4` all sit inside +-0.5% at n=15-25 with identical output.

An empirically anchored ceiling in section 31.4's style: the entire Rust
share is 15.7% of the wall time, and **those two functions are essentially
all of it** --- 15.5 of the 15.7 points, wall-time weighted. The best global
knob touching them is +0.48%, and its CI includes 1. **The Stage 2 ceiling on oxipng is indistinguishable
from zero, which is materially worse than zopfli's estimated +1.6%.**

#### 48.3 Recommendation

**Recommended: apply the rule as written and drop oxipng.** Unlike section
28's zopfli recommendation, there is no post-hoc argument for an exception:
the reason oxipng is flat is not "the uniform setting could not reach the
site", it is "the site is in another compiler's output, and the sites that
are in this compiler's output are already optimal". oxipng is worth keeping in
`results.md` as **evidence**, not as a target:

- it is the clean demonstration that SPEC.ja.md 6.1-2's disqualification
  filter has a false-negative mode, and that SPEC.ja.md 8.2's profile-based
  hotness has a matching blind spot (sections 42-43);
- it is a third independent "flat" result for SPEC.ja.md 1.3-1, on a target
  SPEC.ja.md 6.4 named as *the* obvious byte-loop candidate, which makes the
  negative result harder to attribute to bad target selection;
- it is the strongest evidence so far for section 29-1's "the candidate set
  must not be one list": `-unroll-max-count=1` is zopfli's best knob and
  oxipng's second-worst.

#### 48.4 Recommended changes to SPEC.ja.md and docs/decisions.ja.md (not applied here)

Neither file was edited. These are the changes this section's evidence
supports:

1. **SPEC.ja.md 6.4, the oxipng row.** "Turn off the libdeflate feature and
   pin rayon to one thread" is wrong for 9.1.5: `libdeflater` is not optional,
   and `--threads` exists only when the `parallel` feature is on. Replace the
   row with the measured result, or delete oxipng from the candidate list.
2. **SPEC.ja.md 6.1-2, the disqualification filter.** Add a third *static*
   check, `cargo tree -e normal,build | grep -iE 'cc v|-sys v|cmake v|bindgen v'`
   (note `-e build` alone does not descend), and a fourth,
   `nm --defined-only <bin> | grep -v ' _R'` on the built binary. Both are
   **hints, not verdicts**: the `nm` form also matches libc and crt stubs
   (`_start`, `deregister_tm_clones`) and any `#[no_mangle]` Rust, and
   `linux-raw-sys` is a false positive on the `cargo tree` form. What settles
   it is the **dynamic** check --- a sampled IP share by symbol class (item 3)
   --- and the static checks' job is to say when that is worth running. State
   that a C dependency is a **harder** disqualification than hand-written
   SIMD in Rust, because it is invisible to `-Cllvm-args`, `-Ctarget-cpu`,
   `-Cprofile-generate` and the Stage 2 plugin at once.
3. **SPEC.ja.md 6.1-4 and 8.2-8.3, profile share.** Say in the text that a
   profdata share is a share **of the instrumented code only**, and that on a
   target with a `cc` dependency it is normalised to the wrong denominator and
   will read ~100% Rust. Require a wall-clock attribution (`perf`,
   `callgrind`, or `scripts/ipsample.c`) before a profile share is used to
   clear a filter hit, as section 20 did for zopfli.
4. **SPEC.ja.md 3, profdata reproducibility.** Two targets now fail it for
   unrelated reasons (zopfli: embedded build id; oxipng: a randomly seeded
   `indexmap` hasher changes real counters). Restate the requirement as
   same-run identity --- `basis.pgo_profile_sha` proves both arms used *this*
   profile, never that the recipe reproduces it.
5. **SPEC.ja.md 10, the statistic.** `bench.py stats` uses means; 3.1% of the
   samples in section 47 were more than 15% above their own median, and three
   of them landed on the base label and produced sixteen false "beyond MDE"
   flags. Freeze a trimmed or median-based statistic, or require the
   median cross-check as a mandatory second read rather than an ad-hoc one.
6. **SPEC.ja.md 6.2's byte-loop hypothesis.** Restate it. "Byte loop" does not
   predict width headroom: oxipng's byte loop is already at VF 32 because its
   result type is a byte, and the toy's was stuck at VF 4 because its result
   type was `i64` --- and forcing the width there made it 2.2x slower. The
   property that predicts anything is the **accumulator/result type**, and in
   both directions it predicts *no* opportunity.
7. **SPEC.ja.md 10, measurement hygiene.** Add: only one target may be
   measured on this machine at a time, and a shared script may not be edited
   in place while a run is outstanding (section 47.3). The cost of the
   concurrency here, in numbers the spec owner can weigh: oxipng's A/A
   half-width was **1.70% against zopfli's 0.29%**, which pushed the MDE above
   the 3% floor for the first time in this study; 3.1% of the sweep's samples
   were more than 15% above their own median, three of them landed on the base
   label, and they produced **16 false "beyond MDE" flags**; the n=25
   confirmation on a quieter machine had half-widths **three to five times
   smaller** (0.4-1.3% against 1.6-3.7%).

### 49. Deviations, and what is not done

- The sweep ran on the **training** inputs (SPEC.ja.md 7), unlike the toy and
  zopfli sweeps; the holdout is untouched except by the A/A.
- `scripts/bench.py stats` for the main sweep was run by hand after the
  driving script was corrupted mid-run by a concurrent edit (section 47.3).
  The invocation is the one the script contains, with the frozen MDE.
- A second Stage 0 (jaq) ran on this machine throughout (section 44).
- **`scripts/ipsample.c` is a sampler, not `perf`.** It samples
  `ITIMER_PROF` at 500 us, pooled over three runs per case (1071-1578 samples
  each), so the binomial standard error on a share near 10% is about 0.9
  percentage points and near 28% about 1.3. Quoting the shares to two decimals
  above is the raw arithmetic, not a claim of that precision, and nothing here
  turns on the second digit. Note also that these are shares of **CPU** time,
  not wall time (section 43).
- The Stage 2 plugin, the heterogeneity gate and the `vectorize.width`
  metadata FP-reassociation question are still open. oxipng cannot answer the
  last one either: like zopfli it has no vectorizable FP reduction, and
  `cannot prove it is safe to reorder floating-point operations` does not
  appear in its 68359 remark lines.
- Post-hoc attribution beyond section 43 was not needed: no configuration
  produced a difference worth attributing.


## Experiment 1 (jaq) --- does the PGO training set matter?

Date: 2026-09-22, same machine and the same pinned toolchain as every
section above (rustc 1.100.0-nightly bba531001 / LLVM 23.1.1), same jaq
submodule commit `c866e70303b5dbc37d83a0b0cbacf10e90af9c8c` (v3.1.1).
Sections are numbered from 62.

This is the first experiment of the direction decided in
docs/decisions.ja.md entry 38. The product claim under test is:

> `jev-opt build` replaces `cargo build --release`. It runs PGO, and **Jev
> picks which inputs already in the repository** (tests, examples, doc
> examples, benches, fixtures) to train on, so the user writes no training
> workload.

Before building any selector, this measures the **upper bound** on what a
selector could be worth: how far apart are the holdout speeds of PGO
binaries that differ *only* in which repository inputs the instrumented
binary saw? If a naive choice is as good as a realistic one, there is
nothing to choose and the thesis is flat.

Predictions were written down before the timing run (section 67 records
which held).

Reproduce with:

```
export TARGET=jaq
scripts/jaq_pool_extract.py extract \
    --binary target-jaq-plain/x86_64-unknown-linux-gnu/release/jaq \
    --timeout 10 --progress
scripts/jaq_pool_extract.py scan \
    --binary target-jaq-pgo-gen/x86_64-unknown-linux-gnu/release/jaq \
    --scratch /tmp/jaq-scan
for arm in T_all T_allraw T_readme T_big T_bench T_real T_allreal T0; do
    scripts/pgo_train_arm.sh $arm
done
# then section 65's single interleaved bench.py run
```

**New in this experiment.** `scripts/jaq_pool_extract.py` (enumerate the
repository's candidate inputs, dry-run them, find the ones that corrupt the
instrumented binary's counters, and run a named subset as a training run),
`scripts/pgo_train_arm.sh` (one arm: training run -> merge -> PGO-use build
-> correctness) and `scripts/profdata_cover.py` (how much of a reference
profile's hot set another profile actually covers). Nothing in
`scripts/target_common.sh`, `scripts/bench.py` or the jaq submodule was
changed; `pgo/jaq/merged.profdata` and `pgo/jaq/profraw/` were made
read-only for the duration and verified byte-identical afterwards.

### 62. The candidate pool: what is actually inside the jaq repository

`scripts/jaq_pool_extract.py extract` walks six sources. Each of them is a
place the repository itself already drives jaq from, and for each the
extractor mimics the repository's own runner rather than inventing a shape:

| source | where | what the repository does with it | extractor |
|---|---|---|---|
| `doctest` | ``` `FILTER --> EXPECTED` ``` code spans in `docs/*.dj` | `docs/tests.jq` extracts them, `jaq --run-tests` runs them with input `null` | code-span regex after fenced blocks are removed |
| `doccli` | `$ producer \| jaq ARGS` lines in `docs/*.dj` | `docs/cli-tests.jq` extracts them, `docs/shelltest.rs` runs them in `sh` | shlex-tokenise, keep pipelines that reduce to (producer -> jaq), run the producer once to get the stdin bytes |
| `test` | `give`/`gives`/`yields!`/`fail` in `jaq-{core,std,json,fmts}/tests/*.rs` | `cargo test`, against the *library* | balanced-paren Rust parse of `json!(input)` and the filter string literal; run as `jaq FILTER` with the input on stdin |
| `clitest` | `test!(name, &[args], input, output)` in `jaq/tests/golden.rs` | `cargo test`, already spawning the real binary | same parse; `cwd` is `jaq/` because two tests use `-L tests` and `--rawfile tests/256.bin` |
| `bench` | `examples/benches/*.jq` x the `n` in `examples/benches.json` | `bench.sh` runs `echo $n \| jaq "$(cat f.jq) \| length"` | exactly that, plus `bench.sh`'s three hand-written cases (`empty`, `bf-fib`, `defs`) |
| `example` | `examples/*.jq` | `examples/ball.sh`, `bench.sh` | four runnable programs |

```
$ scripts/jaq_pool_extract.py extract --binary target-jaq-plain/.../jaq --timeout 10
parsed 1185 candidates
  skipped doccli:multi-stage: 9
  skipped doccli:not-jaq-last: 5
  skipped doccli:shell-control: 24
  skipped doccli:would-block-on-stdin: 5
  skipped test:filter-not-literal: 34
  skipped test:input-not-literal: 30
dry run: 1185 usable, 0 dropped
```

**1185 candidates, every one of which terminates** under the repository's
own `bench.sh` timeout of 10 s on the plain binary. 107 candidates were
visible but not extractable: 43 shell examples whose pipeline does not
reduce to (producer -> jaq) --- `yes | jaq -n`, `jaq -i . tmp.json && cat
tmp.json`, `jaq ... | jaq ...` --- and 64 Rust test calls whose input or
filter is a Rust expression rather than a literal (`gives(ab(1), ...)`,
format strings). Those are extraction limits, not properties of jaq; a real
selector would want the shell ones, and this experiment does not need them.

Pool composition and, the point of this section, the **size distribution**:

```
pool by source:
  bench     n=   30  input bytes min/median/max 0/8/1000006   dry ms min/median/max 3/189/541
  clitest   n=   21  input bytes min/median/max 1/14/257      dry ms min/median/max 1/2/3
  doccli    n=   46  input bytes min/median/max 0/11/1053     dry ms min/median/max 1/3/3
  doctest   n=  513  input bytes min/median/max 5/5/5         dry ms min/median/max 1/3/10
  example   n=    4  input bytes min/median/max 0/1455/2173   dry ms min/median/max 3/6/44
  test      n=  571  input bytes min/median/max 2/5/95        dry ms min/median/max 1/3/27

input-byte distribution over all 1185 items:
  p0 0  p10 5  p25 5  p50 5  p75 5  p90 8  p99 93  p100 1000006
  total input bytes 1015609
  total dry-run wall time 9.4 s, median item 2.7 ms
```

**The repository contains no large input.** The median candidate reads 5
bytes (the string `null\n`, which is what every doc test and most unit tests
feed in). The 99th percentile is 93 bytes. The single item above a kilobyte
of *data* is `examples/fib.bf` at 2352 bytes. The one megabyte-scale item,
`bench.sh:defs`, is 100000 generated lines of `def a: 0;` --- a **program**,
not data, and it exercises the parser.

**And input size is anti-correlated with work.** The twelve heaviest items in
the pool (277-541 ms each on the plain binary) are `examples/benches/*.jq`
at `n = 1048576`, whose entire input is the decimal string `1048576\n`:
**8 bytes**. They generate their millions of values in the interpreter. The
whole pool is 9.4 s of work, of which the 34 `bench`/`example` items are
6.3 s (67%) while holding 8 bytes of stdin each.

For comparison, the Stage 0 training set (section 52) is three invocations
reading **71 MiB** of generated JSON. Nothing remotely like it exists in the
repository.

Written to `targets/jaq/pool/pool.json` (one entry per candidate: `id`,
`source`, `origin`, `filter`, `argv`, `stdin`, `cwd`, `input_paths`,
`input_bytes`, `filter_bytes`, and the dry run's status/rc/ms).

### 63. Three pool items corrupt the instrumented binary's counters

This was found by disbelieving a number, and it is a genuine hazard for the
product rather than a harness bug.

The first `T_all` and `T_readme` profiles reported an impossible block count:

```
$ llvm-profdata show pgo/jaq/arms/T_allraw/merged.profdata
Total functions: 8102
Maximum function count: 88750782
Maximum internal block count: 39582476944192      <- 4e13
Total count: 39587563369240
```

4e13 block executions in a 13 s training run is about four orders of
magnitude beyond what the machine can execute. The value sits in **one**
counter (index 150 of 161) of one cold function,
`num_bigint::biguint::convert::to_radix_le`, whose other counters read 0-342.
It is not a merge-pooling artifact --- running the same 559 items with one
profraw per process (`%p`-style unique names) and merging gives the same
value as running them with `%m`:

```
  %m  Maximum internal block count: 35184425839296
  %p  Maximum internal block count: 35184425839296
```

and it is not a count, because it changes between runs in its low bits while
keeping its high bits: `0x200003342ac0`, `0x2000033430c0`,
`0x200003345340` for the first item and `0x20000230610`, `0x20000230c70`
for the other two. **Those are pointers** --- the 2 TiB and 32 TiB regions
mimalloc maps its arenas into. Something on the big-integer formatting path
writes a heap pointer into the instrumented binary's `__llvm_prf_cnts`.

Bisecting the pool (`scripts/jaq_pool_extract.py scan`, which is that
bisection made reproducible) finds exactly three items, and all three call
`tostring` on a big integer:

```
chunk   180-  240 max block count 35184425839296
   POISONS THE PROFILE: doctest-0224 docs/formats.dj:243
       | {a: nth(1024; 1 | recurse(.*2))} | totoml | try fromtoml catch -1
chunk   840-  900 max block count 2199025550864
   POISONS THE PROFILE: test-0325 jaq-std/tests/defs.rs:147
       | def fib: recurse([.[1], add])[0]; nth(100; [0, 1] | fib) | tostring
chunk   960- 1020 max block count 2199025552496
   POISONS THE PROFILE: test-0431 jaq-std/tests/funs.rs:199
       | 2e22 | round | tostring

3 of 1185 pool items poison the profile
```

**Why it matters, and it matters a great deal.** LLVM's ProfileSummary
percentiles --- which set the hot/cold cutoffs the inliner and block
placement use --- are computed over block counts. With one block at 3.5e13:

```
$ llvm-profdata show --detailed-summary pgo/jaq/arms/T_allraw/merged.profdata
1 blocks (0.00%) with count >= 35184425840832 account for  1% of the total counts.
...
1 blocks (0.00%) with count >= 35184425840832 account for 99.999% of the total counts.
103 blocks (0.09%) with count >= 186569 account for 99.9999% of the total counts.
```

Every percentile from 1% to 99.999% lands on that one block, so the whole
program is cold relative to the cutoff. This is not hypothetical: the binary
built from that profile (`T_allraw`, kept and timed in section 65) is
**9.9% slower than no PGO at all**.

Three notes on what this is and is not:

1. It is invisible in the shipped binary. Only the `-Cprofile-generate`
   build writes there, and the released build of all three filters is
   correct (every arm's output checksums match, section 64).
2. It is deterministic in *which* item triggers it and non-deterministic in
   the value, i.e. a wild write, not a counting error. Whether the defect
   is in `num-bigint`'s `to_radix_le` (which does use `Vec::set_len` on
   uninitialised capacity) or in LLVM's instrumentation of it was not chased
   further; it is out of this experiment's scope, and the mechanism is
   established well enough to act on.
3. **A `jev-opt build` that just ran the repository's tests would hit this.**
   Two of the three are ordinary unit tests in `cargo test`. So "run
   everything" needs a profile sanity check --- no block count may exceed
   the wall time times a plausible IPC --- before the profile is used. That
   check is cheap: it is one `llvm-profdata show`.

The three items stay in `pool.json` (a selector must be able to see them),
flagged `poisons_profile`, and are excluded from every arm except
`T_allraw`, which exists precisely to price the mistake.

### 64. The arms

All arms share the **frozen Stage 0 instrumented binary**
`target-jaq-pgo-gen/x86_64-unknown-linux-gnu/release/jaq` --- the one that
produced `pgo/jaq/merged.profdata` with zero `-Cprofile-use` warnings
(section 53). Nothing is rebuilt for instrumentation, so the arms cannot
differ by anything but their inputs. Each arm writes to its own
`LLVM_PROFILE_FILE=pgo/jaq/arms/<arm>/raw/%m.profraw`; the baked-in path is
the frozen `pgo/jaq/profraw/`, which was made read-only and verified
byte-identical at the end.

**T_real is the frozen profdata itself, copied, not regenerated.** Section 53
records that the training run is done once per target and only the binary id
inside a profdata is irreproducible. As a mechanism check the Stage 0
training set was re-run once through the instrumented binary under
`LLVM_PROFILE_FILE` and the merge compared:

```
re-run  Total functions: 8102  Maximum function count: 176281976  Total count: 3438331105
frozen  Total functions: 8102  Maximum function count: 176281976  Total count: 3438334653
```

identical function count, block count and maximum; total counts differ by
3548 in 3.44e9, i.e. **1.0e-4 %** (process-startup paths that depend on the
environment). The re-run was then discarded.

Every PGO-use build is `build_variant` from `scripts/target_common.sh`,
i.e. byte-for-byte the Stage 0 baseline recipe with only `-Cprofile-use`
pointing elsewhere. `T0` is the same recipe with the profile flags removed
and nothing else changed.

| arm | what it trains on | invocations | training wall | profdata sha256 | profdata total count |
|---|---|---:|---:|---|---:|
| `T0` | nothing (no PGO) | 0 | --- | --- | --- |
| `T_all` | every pool item once, minus the 3 of section 63 | 1182 | 13.1 s | `b454f7b160bc92ad…` | 5085349161 |
| `T_allraw` | every pool item once, **including** the 3 | 1185 | 13.1 s | `40b595898af41112…` | 39587563369240 |
| `T_readme` | `docs/*.dj` doc tests + CLI examples | 558 | 2.2 s | `d1903b42cc424573…` | 115908737 |
| `T_big` | top 10% of the pool by input bytes | 118 | 1.0 s | `a4308db7ff966e00…` | 356062697 |
| `T_bench` | `examples/benches` + `bench.sh` + `examples/*` | 34 | 8.6 s | `639600bc5d77899b…` | 4822071352 |
| `T_real` | the Stage 0 training set (71 MiB of generated JSON) | 3 | 5.6 s | `4e879ce11687fa3c…` | 3438334653 |
| `T_allreal` | `llvm-profdata merge` of T_all's profraw with T_real's profdata | 1185 | 18.7 s | `1ad1dcd1d1d94da4…` | 8523683814 |

`T_allreal`'s weighting is by **absolute block count**, not by invocation:
the merge adds counters, so T_real's 3.44e9 and T_all's 5.09e9 arrive in
that ratio.

Two naming notes. `T_readme` is not README.md: README.md contains exactly
two runnable jaq lines and both are deliberately non-terminating
(`jaq -nr 'repeat("[")' | jaq`, `jaq -n 'def f: 1+f; f'`). The arm is the
manual under `docs/`, which is where jaq's documentation examples actually
live. And the repository runs its 513 doc tests as **one** `jaq --run-tests`
process; this arm runs them as 558 processes, one per item, which is what
"run each candidate once" means and which is itself part of why the arm's
profile looks the way it does (section 66).

**No arm produced a single profile-use warning.**

```
arm        remarks   hash mismatch   no profile data available   warning:
T0          304591        0                    0                    0
T_all       257483        0                    0                    0
T_allraw    218560        0                    0                    0
T_readme    253597        0                    0                    0
T_big       246466        0                    0                    0
T_bench     244205        0                    0                    0
T_real      228248        0                    0                    0
T_allreal   259694        0                    0                    0
```

`-pgo-warn-missing-function` is therefore **useless as a selection signal on
this target**: IR instrumentation emits a record for all 8102 functions
whether or not they run, so a profile trained on 558 five-byte doc tests is
as "complete" as one trained on 71 MiB of JSON. The discriminating number is
in section 66.

**Correctness precondition.** All nine timing labels were stripped
(`strip -s`) and run through `run_correctness` before any timing; all nine
produce byte-identical output on all six inputs (three training, three
holdout). `T_real` and `T_realB` are byte-identical files
(`cceee7768c3ed6eb…`), which is the in-run A/A pair.

### 65. Holdout timing: nine labels, one interleaved run

The Stage 0 measurement recipe unchanged (section 55): the three **holdout**
cases, `taskset -c 4`, `--gap-ms 250`, `--stdout devnull`, warmup 3, 15
timed rounds, paired bootstrap over rounds, 10000 resamples, seed 20260921.
405 timed samples in one run, so every label saw the same machine.

```
$ scripts/bench.py run --cpu 4 --warmup 3 --runs 15 --stdout devnull --gap-ms 250 \
    --label T0=...  --label T_all=... --label T_allraw=... --label T_readme=... \
    --label T_big=... --label T_bench=... --label T_real=... --label T_realB=... \
    --label T_allreal=... \
    --workload "objsearch='.[] | select(.k == \"v\") | .id' hold-objects.json x4" \
    --workload "strproc='[.[] | .name | ascii_downcase | length] | add' hold-strings.json x8" \
    --workload "readwrite=-c '.' hold-ndjson.json x2" \
    --out artifacts/jaq-exp1/holdout.json
artifacts/jaq-exp1/holdout.json: 405 timed samples, 9 labels x 3 workloads x 15 rounds
```

**In-run A/A** (`T_realB` against `T_real`, the same bytes at two paths):

| workload | ratio | 95% CI | half-width |
|---|---|---|---|
| objsearch | 1.0022 | [0.9907, 1.0138] | **1.15%** |
| strproc | 0.9988 | [0.9928, 1.0045] | 0.59% |
| readwrite | 1.0062 | [0.9991, 1.0142] | 0.75% |
| **aggregate (geomean)** | 1.0024 | [0.9975, 1.0072] | **0.49%** |

Worst per-workload A/A half-width **1.15%**, so
**MDE = max(2 x 1.15%, 3%) = 3.00%** --- the 3% floor binds again. Note this
is *better* than Stage 0's A/A (worst 2.09%, MDE 4.17%) despite nine labels
and a 34 s round: the machine was quiet this time, with no second target
being built beside it (section 55 recorded that contention).

**Against T0** (`scripts/bench.py stats artifacts/jaq-exp1/holdout.json
--base T0`; ratio > 1 means faster than no PGO):

| label | objsearch | strproc | readwrite | aggregate | 95% CI | half-width |
|---|---|---|---|---|---|---|
| `T_real` | 1.1665 | 1.0652 | 1.4475 | **1.2161** | [1.2105, 1.2215] | 0.55% |
| `T_realB` | 1.1690 | 1.0639 | 1.4565 | 1.2190 | [1.2134, 1.2243] | 0.55% |
| `T_allreal` | 1.1564 | 1.0584 | 1.4250 | **1.2037** | [1.1981, 1.2095] | 0.57% |
| `T_readme` | 1.0310 | 0.9648 | 1.1770 | **1.0540** | [1.0494, 1.0582] | 0.44% |
| `T_big` | 1.0529 | 0.9940 | 1.0784 | **1.0411** | [1.0361, 1.0465] | 0.52% |
| `T_all` | 1.0640 | 0.9794 | 1.0576 | **1.0329** | [1.0273, 1.0382] | 0.55% |
| `T_bench` | 0.9306 | 0.8783 | 0.9581 | **0.9217** | [0.9181, 0.9253] | 0.36% |
| `T_allraw` | 0.8937 | 0.8444 | 0.9696 | **0.9011** | [0.8974, 0.9047] | 0.36% |

**Against T_real** (`--base T_real`; ratio < 1 means slower than the
realistic training set):

| label | objsearch | strproc | readwrite | aggregate | 95% CI | half-width | gap vs T_real |
|---|---|---|---|---|---|---|---|
| `T_realB` | 1.0022 | 0.9988 | 1.0062 | 1.0024 | [0.9975, 1.0072] | 0.49% | +0.2% (A/A) |
| `T_allreal` | 0.9914 | 0.9936 | 0.9845 | **0.9898** | [0.9852, 0.9942] | 0.45% | **-1.0%** |
| `T_readme` | 0.8839 | 0.9058 | 0.8131 | **0.8667** | [0.8623, 0.8708] | 0.42% | **-13.3%** |
| `T_big` | 0.9026 | 0.9332 | 0.7450 | **0.8561** | [0.8504, 0.8620] | 0.58% | **-14.4%** |
| `T_all` | 0.9122 | 0.9195 | 0.7307 | **0.8494** | [0.8456, 0.8533] | 0.39% | **-15.1%** |
| `T0` | 0.8573 | 0.9388 | 0.6909 | **0.8223** | [0.8187, 0.8261] | 0.37% | -17.8% |
| `T_bench` | 0.7978 | 0.8246 | 0.6619 | **0.7579** | [0.7554, 0.7601] | 0.23% | **-24.2%** |
| `T_allraw` | 0.7662 | 0.7928 | 0.6698 | **0.7410** | [0.7371, 0.7449] | 0.39% | -25.9% |

### 66. Judgment

**1. Is there selection headroom >= MDE? Yes, by a factor of six.**

The pre-registered key number is `T_real - T_all`. T_all reaches
**0.8494** of T_real's speed: choosing the training set well is worth
**+17.7%** (1/0.8494) over "run every input in the repository", against an
MDE of **3.00%**. `T_real - T_readme` is +15.4%. Both are five to six times
the MDE, with bootstrap CIs nowhere near it.

Put in the terms of decisions.ja.md entry 32, which is why this direction
was chosen: PGO on jaq is worth +21.6% over no PGO when it is trained well
(T_real), and **+3.3% when it is trained on the repository's own inputs**
(T_all). **85% of the available PGO win depends on the training-set choice.**
That is the headroom a selector could capture, and it is an order of
magnitude above anything the loop-hint direction ever produced (0-2%,
decisions.ja.md entry 37).

**2. "Pick the largest inputs" is not a trivially good rule --- it is barely
better than nothing.** `T_big` (top 10% by input bytes) gets **1.0411** over
T0, i.e. it recovers 4.1 of the 21.6 available points, **19%** of T_real.
The reason is in section 62: on this repository input size and work are
anti-correlated. The top-10%-by-bytes rule selects 118 items holding 0.74 s
of the pool's 9.4 s of work and **misses 28 of the 30 `bench` items**,
because those read 8 bytes of stdin and generate their data internally.
Jev's selection problem is therefore not solved by a size heuristic.

**3. Training on the repository's own benchmark suite is worse than not
doing PGO at all.** `T_bench` --- the 30 benchmarks `bench.sh` exists to run,
the closest thing to a curated performance workload the repository has ---
lands at **0.9217** of T0 and **0.7579** of T_real. It is 7.8% *slower* than
the non-PGO binary, well beyond MDE, on all three holdout cases. A selector
that reasoned "the repository has benches, benches are the performance
workload, train on those" would ship a regression. Section 67 shows the
mechanism.

**4. Dilution is real but small: `T_all+real` ~ `T_real`.** `T_allreal`
reaches **0.9898** of T_real, a 1.0% loss. The CI [0.9852, 0.9942] excludes
1, so the dilution is measurable, but it is **below the 3% MDE**, so by the
pre-registered rule the two are not distinguishable. Adding 1182 junk
invocations to a good training set costs about 1%; it does not destroy it.
This matters for the product: the selector's job is mostly to **find** the
representative input, not to **exclude** the unrepresentative ones --- a
useful asymmetry, because recall is easier than precision.

**5. Not doing PGO beats doing it badly.** Ordering the arms by holdout
speed: T_real (1.2161) > T_allreal (1.2037) >> T_readme (1.0540) > T_big
(1.0411) > T_all (1.0329) > **T0 (1.0000)** > T_bench (0.9217) > T_allraw
(0.9011). Two of the six repository-derived training sets produce a binary
slower than `cargo build --release` with no PGO. `jev-opt build` therefore
cannot be "always PGO, any inputs": it needs either a good selector or a
holdout check that can fall back to T0.

### 67. Attribution: the profile never sees the JSON lexer

Section 54 established that jaq's time on these workloads is dominated by
`hifijson`, the JSON lexer, at **42.8%** of block executions, and that the
single hottest loop in the program (22.5% overall) is `write_until`'s
early-exit byte search. Here is that share in every arm's profile
(`scripts/profdata_hotness.py <profdata> --grep hifijson`):

| arm | hifijson block counts | share of that profile |
|---|---:|---:|
| `T_real` | 1473121794 | **42.844%** |
| `T_allreal` | 1476330254 | 17.320% |
| `T_bench` | 3140027 | **0.065%** |
| `T_all` | 3208460 | **0.063%** |
| `T_readme` | 27661 | 0.024% |
| `T_big` | 25012 | 0.007% |
| `T_allraw` | 3208568 | 0.000008% |

**Yes: T_all's profile simply has no counts on the lexer.** Not zero counts
--- the functions do run, so `-pgo-warn-missing-function` stays silent --- but
**680x under-weighted** relative to the real workload. The pool's items read
a median of 5 bytes, so the lexer does a few hundred thousand byte tests in
total where the holdout does 1.5 billion.

The same thing measured against the reference hot set
(`scripts/profdata_cover.py pgo/jaq/merged.profdata T_all=... ... --top 20`,
which takes T_real's top 20 functions by max block count --- they hold
**71.16%** of T_real's counts --- and asks what each arm gives them):

| arm | zero-count, of 20 | share of the arm's own total | relative to T_real |
|---|---:|---:|---:|
| `T_real` | 0 | 71.16% | 1.000x |
| `T_allreal` | 0 | 34.77% | 0.489x |
| `T_bench` | **8** | 10.55% | 0.148x |
| `T_all` | 0 | 10.16% | 0.143x |
| `T_big` | 0 | 9.90% | 0.139x |
| `T_readme` | 0 | 1.84% | 0.026x |
| `T_allraw` | 0 | 0.00% | 0.000x |

The zero-count column is the blunt instrument the day-0 checklist asks for,
and it is **0 for five of the seven arms** --- even a five-byte `null` input
goes through the lexer and the writer. Only `T_bench` has literal holes (8
of 20: the benchmarks take a decimal integer on stdin and print one integer,
so they never parse a string, never allocate a `Val` from JSON text and never
run the buffered writer). The *share* column is what separates the arms, and
it tracks holdout speed monotonically except for the `T_bench`/`T_all`/`T_big`
cluster, where the arms differ in *where* their weight goes rather than how
much reaches the hot set.

**What the profiles did to the code**
(`scripts/norm_code_diff.py target-jaq-exp1-T_real/.../jaq
target-jaq-exp1-{T_all,T_bench,T_readme}/.../jaq --profdata
pgo/jaq/merged.profdata --top 14`; percentages are T_real's profile share,
instruction counts are T_real -> arm):

| function | share | T_all | T_bench | T_readme |
|---|---:|---|---|---|
| `hifijson::SliceLexer::write_until` (the hot byte search) | 22.52% | 42 -> **84** | 42 -> 42 | 42 -> **84** |
| `jaq_json::read::parse` | 7.26% | 4426 -> **2952** | 4426 -> **2720** | 4426 -> **3001** |
| `jaq_std::base_run` closure | 5.73% | 432 -> **137** | 432 -> **113** | 432 -> **137** |
| `hifijson::num_string_with` | 4.62% | 245 -> **151** | 245 -> **149** | 245 -> **150** |
| `jaq_json::write::write` | 4.33% | 2390 -> **1607** | 2390 -> **1488** | 2390 -> **1669** |
| `jaq_core::compile::TermId::run` (the interpreter loop) | 1.93% | 6562 -> **11802** | 6562 -> **11738** | 6562 -> 5664 |
| `BufWriter<StdoutLock>::write` | 1.56% | 229 -> **45** | 229 -> **45** | 229 -> 240 |

The changed symbols hold 86-88% of the real profile in every arm, so this is
not a marginal difference in code. The mechanism is legible:

* The **JSON reader and writer collapse.** `jaq_json::read::parse` loses a
  third to two fifths of its instructions in every repository-trained arm,
  `jaq_json::write::write` a third, `num_string_with` two fifths,
  `BufWriter::write` **80%** (229 -> 45 instructions, i.e. the fast path is
  no longer inlined into it). These are the functions the holdout spends its
  time in, and the repository profile says they are cold, so LLVM stops
  inlining into them and lets them shrink.
* The **interpreter dispatch loop inflates**: `TermId::run` grows from 6562
  to **11802** instructions under T_all and 11738 under T_bench --- an 80%
  increase. That is the one part of jaq the repository's items really do
  exercise, so the profile makes it look hot and LLVM inlines aggressively
  into it. It buys nothing on the holdout and costs instruction cache.
* `write_until`, the 22.5% loop, **doubles from 42 to 84 instructions** under
  T_all and T_readme. Stage 0 (section 56) established this loop cannot be
  vectorised (`Incorrect number of successors from early exiting block`), so
  the extra 42 instructions are not width --- they are a second, unrolled or
  peeled copy chosen for a loop LLVM now believes is cold and short-running.
  It stays at 42 under T_bench, which never enters it at all.
* The `readwrite` case is the extreme in every table (T_all 0.7307 of T_real,
  T_big 0.7450) because it is the one that is almost entirely lexer plus
  writer, which is exactly the pair the repository profile mis-weights.

**Predictions, scored.** Four were written down before the timing run.
(a) *T_all ~ T_bench, because the benchmarks swamp the tiny items*:
**wrong in the numbers, right in the mechanism.** The two are far apart in
speed (1.0329 vs 0.9217) although their hifijson shares are nearly identical
(0.063% vs 0.065%) --- the benchmarks do dominate T_all's counts, but T_all's
1152 tiny items still add enough parser and startup weight to change the
outcome by 12%. (b) *T_readme trains the loader and compiler*: **right** ---
its top functions are `jaq_core::load::lex` and `Compiler::compile`, and its
hot-set share is the lowest of any sane arm at 1.84%. (c) *T_all may land
below T0 on readwrite*: **right in spirit, wrong in sign for T_all**
(1.0576, still above T0) but exactly right for T_bench (0.9581) and T_allraw
(0.9696). (d) *T_big-by-bytes fails because bytes and work are decoupled*:
**right**, and it is the cleanest result in the experiment.

### 68. What Jev would need to see

This is the input to the `criteria` design for the Choice, written from what
actually separated the arms here rather than from first principles.

**Size is the wrong feature.** `input_bytes` ranks the pool almost exactly
backwards: the twelve heaviest candidates carry 8 bytes each and the
largest-by-bytes candidate is a generated *program*. Any criterion of the
form "prefer large fixtures" would have produced T_big (+4.1%) instead of
T_real (+21.6%).

**Measured work is a necessary but not sufficient feature.** Dry-running each
candidate is nearly free --- the entire 1185-item pool runs in **9.4 s** --- so
Jev can have a wall-time and even a cheap profile per candidate before it
chooses. But T_bench is the arm with the most work per item and it is the
*worst* arm. Work tells you which candidates can move a profile; it does not
tell you whether they move it in the right direction.

**The discriminating feature is profile shape, and it is observable
per-candidate at the same cost.** The number that ordered the arms was each
profile's share on the reference hot set (section 67), and the reason the
repository fails is structural: every candidate is a *unit* test, so it
exercises the interpreter and the compiler, and none of them feeds the
program enough **data** to make the data path hot. Concretely, what Jev would
need to look at:

* **The ratio of data-path counts to startup/compile counts per candidate.**
  Every jaq invocation pays a fixed cost (parse the filter, build ~200
  stdlib definitions, compile). An item that is nothing but that fixed cost
  contributes noise. The pool's median item is close to it: T_readme's own
  top five functions are `jaq_core::load::lex::{token,space,ident}` and
  `Compiler::term`, holding **55.06%** of that arm's block counts between
  them (`scripts/profdata_hotness.py pgo/jaq/arms/T_readme/merged.profdata
  --top 5`).
* **Which library layers a candidate touches at all.** `hifijson` /
  `jaq_json::read` / `jaq_json::write` versus `jaq_core::load` /
  `jaq_core::compile`. T_bench's 8 zero-count functions of 20 are the
  cleanest possible signal, and they are visible from one candidate's
  profraw.
* **Coverage as a set property, not a per-item property.** No single
  repository candidate covers the hot set; the question is whether the
  *chosen set* does, which makes this a set-cover problem over per-candidate
  profiles, not a ranking problem.
* **A scale knob.** The one thing that would have rescued this repository is
  not selection at all: it is running an existing candidate *bigger*. The
  `examples/benches/*.jq` items take `n` on stdin, and `bench.sh` itself
  sweeps `n` from 7 to 1048576. A selector that may also choose an input's
  **size parameter** has a far larger reachable set than one that may only
  pick items. This is the most important open design question this
  experiment raises.

**And a guard, not a criterion.** Section 63: the profile must be sanity
checked (no block count above wall-time x plausible IPC) before it is used,
because three ordinary repository items silently turn PGO into a 9.9%
regression. That check costs one `llvm-profdata show`.

**The honest limit of this result.** This is one target. jaq is a case where
the repository's inputs are structurally unlike the production workload
(unit tests of an interpreter versus megabytes of JSON), and that is exactly
why the headroom is 17.7%. A target whose tests *are* its workload --- a
compiler with a test suite of real programs, a codec with fixture files ---
would show far less, and might well be flat. The next experiment should pick
such a target deliberately, because the product claim needs the headroom to
exist on repositories where the naive answer is already decent, not only
where it is terrible.

### 69. Deviations, and what is not done

- **The pool is an approximation and the numbers say by how much.** 1185 of
  1292 discovered candidates were extractable (section 62); the 107 misses
  are 43 shell examples that need a real shell and 64 Rust test calls whose
  arguments are Rust expressions. All 107 are tiny items of the same shape
  as the ones that were extracted, so including them would move T_all's
  profile by well under the factor of 680 that separates it from T_real.
- **Unit tests are run through the CLI, not the library.** `jaq-core`'s
  tests call `jaq_core::Compiler` directly; the arm runs `jaq FILTER` with
  the input on stdin. That adds process startup and the CLI's argument
  handling to each item, which is what a `jev-opt build` driving the binary
  would also do. It is not what `cargo test` does.
- **The doc tests are run as 558 processes**, where the repository runs them
  as one `jaq --run-tests`. The one-process form would spend proportionally
  more of its profile inside the interpreter and less in startup; it was not
  measured. Given that T_readme is 13.3% behind T_real and its hot-set share
  is 1.84%, no plausible reshaping of that arm reaches T_real.
- **`T_allreal` merges T_all's profraw with T_real's profdata by count.** An
  invocation-weighted or normalised union was not measured.
- The three poisoning items were found by bisection with a threshold of
  1e11. A lower threshold might flag more items with smaller corruptions;
  the largest non-flagged chunk maximum was 8.2e7, three orders of magnitude
  below the threshold, so there is no borderline case in this pool.
- **The in-run A/A prices one-slot drift, not the whole round.** `bench.py`
  rotates the label order by round, and `T_real`/`T_realB` are adjacent in
  the label list, so the pair is always measured about 4 s apart inside a
  34 s round. Section 55 established that the page-placement drift on this
  target is constant over tens of seconds and *differs* between binaries
  measured tens of seconds apart, so the true label-to-label noise for a
  pair at opposite ends of a round (`T0` at index 0 against `T_real` at
  index 6) is larger than the 1.15% this A/A reports, by an unmeasured
  amount. Every headline here is at least four times the MDE, and the one
  effect that is not --- the 1.0% `T_allreal` dilution --- is already
  declared sub-MDE, so no claim depends on this. A shuffled rather than
  rotated label order would price it properly and is what the next
  experiment should use.
- **One run of one machine.** The A/A prices the noise at 1.15% worst-case
  per workload and the effects are 13-26%, so this is not a close call, but
  the arms were built once each and timed once each. Section 53's warning
  stands: the `.text` hash is not reproducible on jaq, so "the same arm
  rebuilt" was not checked to be the same binary.
- `scripts/interp_share.py`, `remark_attribution.py` and the Stage 2 ceiling
  machinery were not re-run: the attribution in section 67 did not need
  them, and the loop-hint direction they serve is closed
  (decisions.ja.md entry 37).
- The frozen Stage 0 artifacts were verified unchanged at the end:
  `pgo/jaq/merged.profdata` = `4e879ce11687fa3c…`,
  `pgo/jaq/profraw/default_15401585175505616370_0.profraw` =
  `92f435725faa963f…`, both as recorded in section 53.

## Experiment 2 (jaq) --- the within-repo ceiling, and deterministic selectors

Date: 2026-09-22, same machine, same pinned toolchain (rustc
1.100.0-nightly bba531001 / LLVM 23.1.1), same jaq submodule commit
`c866e70303b5dbc37d83a0b0cbacf10e90af9c8c` (v3.1.1), same frozen
instrumented binary and same PGO-use recipe as Experiment 1. Sections are
numbered from 70.

Experiment 1's +17.7% was measured against `T_real`, which is 71 MiB of JSON
**this repository does not contain**. It is an upper bound on selection, not
a product claim. This experiment asks the two questions that stand between
that bound and a shippable `jev-opt build`:

1. **What is the within-repo ceiling?** The best holdout speed reachable
   using only candidates that exist in the jaq repository, plus the scale
   knob for the parametric ones.
2. **How good is a deterministic selector on this pool**, i.e. how much room
   is left for Jev's judgment?

and one product question that turned out to matter more than either:

3. How much does **one small user-provided sample** recover?

Predictions for all of it were written down after the selectors had run and
before any binary was built (`artifacts/jaq-exp2/predictions.txt`, scored in
section 76). Three of nine were wrong, and the two biggest are the result.

Reproduce with:

```
export TARGET=jaq EXP=exp2
scripts/jaq_candidate_profile.py \
    --binary target-jaq-pgo-gen/x86_64-unknown-linux-gnu/release/jaq \
    --ref pgo/jaq/merged.profdata --profraw-dir $SCRATCH/cand \
    --out artifacts/jaq-exp2/candidates.jsonl --progress
scripts/jaq_scale_probe.py \
    --plain target-jaq-plain/x86_64-unknown-linux-gnu/release/jaq \
    --binary target-jaq-pgo-gen/x86_64-unknown-linux-gnu/release/jaq \
    --ref pgo/jaq/merged.profdata --profraw-dir $SCRATCH/cand-scaled \
    --out artifacts/jaq-exp2/candidates-scaled.jsonl
python3 targets/jaq/workloads/gen.py --sample
scripts/jaq_select_arms.py groups
scripts/jaq_select_arms.py select --out-dir artifacts/jaq-exp2/arms \
    --profraw-dir $SCRATCH/cand --scaled-profraw-dir $SCRATCH/cand-scaled
CAND_CACHE=$SCRATCH/cand SCALED_CACHE=$SCRATCH/cand-scaled
for arm in B_cover B_shape B_datapath E_expert E_expert_noscale S_sample1; do
    ARM_SPEC=artifacts/jaq-exp2/arms/$arm.json scripts/pgo_train_arm.sh $arm
done
scripts/profdata_sanity.py --wall-from-manifest pgo/jaq/arms/*/merged.profdata
# then section 73's single interleaved bench.py run
```

**New in this experiment.** `scripts/jaq_candidate_profile.py` (one
instrumented profile per pool candidate, reduced to selector features),
`scripts/jaq_scale_probe.py` (the scale knob: every parametric bench run as
large as bench.sh's range allows), `scripts/jaq_select_arms.py` (the
grouping and the four deterministic/expert selectors),
`scripts/jaq_arm_profile.py` (an arm spec -> a merged profdata, reusing the
per-candidate profraws) and `scripts/profdata_sanity.py` (section 63's
poison check, made a reusable gate). `scripts/bench.py` gained `--shuffle`
(section 69 asked for it; the default is unchanged),
`scripts/pgo_train_arm.sh` gained the `ARM_SPEC` path and an `EXP` prefix,
`targets/jaq/workloads/gen.py` gained `--sample`. Nothing else changed;
`pgo/jaq/merged.profdata` = `4e879ce11687fa3c…` and
`pgo/jaq/profraw/default_…` = `92f435725faa963f…` were verified unchanged at
the end, as in section 69.

### 70. One instrumented profile per candidate, for 72 seconds

Section 68 claimed profile shape is observable per candidate "at the same
cost" as a dry run. It is, and this prices it exactly. Every one of the 1182
non-poisoned pool items (section 63's three are excluded everywhere) is run
once under the frozen instrumented binary with its own `LLVM_PROFILE_FILE`,
and `llvm-profdata show --all-functions --counts` is run straight on the
profraw --- no merge step, 17 ms each:

```
artifacts/jaq-exp2/candidates.jsonl: 1182 candidates, 72.1 s wall
  (14.1 s of it inside jaq), 0 did not terminate normally
```

**72 seconds for the whole pool**, of which 14 s is jaq and 58 s is
`llvm-profdata` plus Python. For a build tool that already spends minutes in
LTO, per-candidate profiling is free. Every arm below is then an
`llvm-profdata merge` of a subset of those 1182 profraws, so no candidate is
ever run twice and two arms cannot differ by anything except which profraws
went into the merge.

Functions are bucketed into layers by an ordered substring match on the
demangled name (first match wins; the rule is in
`scripts/jaq_candidate_profile.py` and `other` is reported so leaks are
visible). The split puts `jaq_json::read::parse::<hifijson::SliceLexer>` in
`json_read` and `<hifijson::SliceLexer as ...>::write_until` in `hifijson`,
where section 67's `--grep hifijson` lumped them together; `hifijson +
json_read` reproduces that 42.8%.

**The distribution over the pool:**

```
                     p10        p50        p90        p99        max
total_count      2.17e+05   2.18e+05   2.22e+05   1.89e+08   4.33e+08
hot20_share        1.72%      1.75%      2.12%     40.4%      42.4%
datapath/startup   0.0105     0.0118     0.0212     191.9      672.3   (+36 inf)
instrumented ms      4.4        4.7        5.2        362        797
```

Three things in that table decide the rest of the experiment.

**The median candidate is 79% startup.** Half the pool sits within 2% of
218 000 block counts, and 78.7% of the median candidate's counts are
`jaq_core::load` + `jaq_core::compile` --- lexing the filter text and loading
~200 stdlib definitions. That fixed cost is **0.01%** of the reference
profile's `core_load`. The pool is, to three significant figures, 1100 copies
of jaq starting up.

**Nothing in the repository feeds the lexer.** 1115 of 1182 candidates have
a nonzero `hifijson` count --- a five-byte `null` still goes through the
lexer, which is why section 64's `-pgo-warn-missing-function` stayed silent
--- so "touches the lexer at all" is true of 94% of the pool and carries no
information. Weighted, it collapses: **14 candidates spend more than 1% of
their own counts in hifijson, and exactly one spends more than 5%.**

That one is `bench-0022`, `examples/benches/to-fromjson.jq`:

```
[range(.) | tojson] | join(",") | "[" + . + "]" | fromjson | length
```

It serialises n numbers, concatenates them into one JSON document and parses
it back. At the repository's n = 65536 it holds 1.89 M hifijson counts; the
runner-up in the entire pool holds **2210**. It is the only place in jaq's
repository where the program is handed a large JSON text --- which turns
out not to be the property that matters (section 75).

**And no candidate covers the hot set: all 1182 leave at least one of the
reference's top-20 functions at zero.** Section 45 predicted this; it is why
selection is a set-cover problem and not a ranking.

**The scale knob** (`scripts/jaq_scale_probe.py`). The 27
`examples/benches/*.jq` items take n on stdin, and the distinct n in
`examples/benches.json` --- 7, 17, 23, 128, 8192, 16384, 65536, 131072,
524288, 1048576 --- are "bench.sh's range". Each bench is walked *up* that
ladder from its own n on the plain binary, keeping the largest rung that
still exits 0 inside bench.sh's own `timeout 10`, and the chosen rung is then
required to survive the instrumented binary too:

```
8 of 27 scaled above the repository's n; 26.5 s instrumented in total
  upto 8192->1048576   reduce-update 16384->1048576   kv 131072->1048576
  kv-update 131072->1048576   kv-entries 131072->1048576 (3.52 s)
  pyramid 524288->1048576   to-fromjson 65536->1048576  str-slice 8192->65536
  ack stays at 7, tree-{contains,flatten,update,paths} stay at 17-23,
  range-prop stays at 128
```

Walking up rather than starting at the top is load-bearing, and so is
checking the exit status: `ack.jq` is `ack(3; .)`, and at n = 1048576 it
overflows the stack and aborts **in 19 ms**. A probe that accepted a rung on
wall time alone would have picked a run that produces no profile at all.

Scaling `to-fromjson` 16x multiplies its counts by 16 and barely moves its
shape, because its startup was already amortised:

| n | total counts | hifijson | json_read | json_write | json_val | core_load | hot-20 share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 65536 | 32 961 578 | 5.74% | 3.78% | 1.59% | 39.90% | 0.36% | 24.18% |
| 262144 | 132 438 017 | 6.37% | 3.76% | 1.58% | 40.02% | 0.09% | 25.01% |
| 1048576 | 531 647 578 | 6.69% | 3.75% | 1.58% | 40.01% | 0.02% | 25.41% |

### 71. Grouping: 30 groups, and the one that matters has one member

The grouping is mechanical and is shared by the deterministic selectors and,
later, by Jev: **(source, the set of layers holding more than 5% of that
candidate's own block counts)**. `scripts/jaq_select_arms.py groups`:

```
1182 candidates, layer threshold 5% of the candidate's own counts
30 groups

    n source          counts   hot20    dp/su  layers > threshold
  528 test         115555295   1.77%     0.01  core_load core_compile core_run
  493 doctest      108002675   1.78%     0.01  core_load core_compile core_run
   26 doccli         5698306   1.95%     0.02  core_load core_compile core_run
   26 test              6900   5.65%      inf  alloc other
   20 doccli          100399  38.32%   165.49  json_val alloc other
   13 clitest        2853970   1.83%     0.02  core_load core_compile core_run
   11 bench       2033861604  11.92%     2.85  json_val core_compile core_run
   11 bench       2060385143  11.61%     3.30  json_val core_compile core_run alloc
   10 doctest           2659   5.64%      inf  alloc other
    9 test           2042132   1.66%     0.01  core_load core_compile core_run other
    6 doctest        1408246   1.64%     0.01  core_load core_compile core_run other
    6 clitest          27841  40.40%   171.91  json_val alloc other
    2 doctest         517560   3.14%     0.01  core_load core_compile core_run alloc other
    2 test          24198020  12.88%     2.68  json_val core_compile core_run
    2 bench         54440212   3.87%    34.64  json_val core_run
    2 bench         32635219   0.02%     0.00  core_load core_compile core_run
    2 example        2560521  10.78%     1.54  json_val core_load core_compile core_run alloc
    1 doctest         129447   2.48%     0.01  core_load
    1 test           1659685  10.47%     0.75  json_val core_load core_compile core_run alloc
    1 test            129221   2.49%     0.01  core_load
    1 test            575988   8.65%     0.69  json_val core_load core_compile core_run
    1 test            257328   3.15%     0.01  core_load core_compile core_run alloc other
    1 clitest           5562  38.48%   271.70  json_read json_write json_val alloc other
    1 clitest           5915  34.18%   258.20  json_read json_val core_run alloc other
    1 bench        117666630   0.00%   672.28  json_val
    1 bench         88169406  15.47%    33.85  json_val core_run alloc
    1 bench         32961578  24.18%     5.88  hifijson json_val core_compile core_run alloc other
    1 bench         373403875   0.16%    82.20  json_val other
    1 example       25850113  10.41%     2.38  json_val core_compile core_run alloc
    1 example         139501   2.42%     0.01  core_load
```

1047 of 1182 candidates fall into the three `core_load core_compile
core_run` groups --- "a jaq that started up and did a little interpreting".
**Exactly one group has `hifijson` in its signature, and it has one member**:
`bench-0022`, `to-fromjson`. The grouping, which knows nothing about the
holdout, isolates the candidate that moves the most JSON bytes, all by
itself.

That looks like the positive result of the grouping, and sections 74 and 75
are what happens when a selector trusts it. The candidate that actually
decides the experiment, `doccli-0044`, sits anonymously in the 26-member
`doccli / core_load core_compile core_run` group, indistinguishable at this
resolution from 25 neighbours --- because what makes it special is not which
*layers* its counts fall in but *which symbols inside a layer*, and the
signature aggregates exactly that away.

### 72. The arms

Six new PGO binaries, plus four labels reused unchanged from Experiment 1.
Every new arm's profile is a merge of cached per-candidate profraws, so the
instrumented binary, the merge tool and the PGO-use flags are Experiment 1's
exactly. Reference = the reference profile's top 20 functions by max block
count (71.16% of it), the same set `scripts/profdata_cover.py` uses.

| arm | selector | items | training wall | profdata sha256 | total count | hot-20 share | zero of 20 |
|---|---|---:|---:|---|---:|---:|---:|
| `T0` | no PGO | 0 | --- | --- | --- | --- | --- |
| `T_all` | every pool item (Exp. 1) | 1182 | 13.1 s | `b454f7b160bc92ad…` | 5 085 349 161 | 10.16% | 0 |
| `T_real` | the 71 MiB Stage 0 set (Exp. 1) | 3 | 5.6 s | `4e879ce11687fa3c…` | 3 438 334 653 | 71.16% | 0 |
| `B_cover` | greedy weighted set cover | 2 | 0.01 s | `bad1d2e65bda3278…` | 444 329 | 3.45% | 0 |
| `B_cover_scaled` | the same, scaled universe | 2 | 0.01 s | `bad1d2e65bda3278…` | 444 329 | 3.45% | 0 |
| `B_shape` | greedy shape match, may scale | 1 | 0.97 s | `3d31b449cb41aafc…` | 531 647 573 | 25.41% | **8** |
| `B_datapath` | top 50 by data-path / startup | 50 | 6.44 s | `e33e63bd2a99f9f4…` | 3 682 616 849 | 10.39% | **6** |
| `E_expert` | 10 hand-picked, 1 scaled | 10 | 1.01 s | `e7789ac2ce6e1a7a…` | 531 693 923 | 25.41% | **8** |
| `E_expert_noscale` | the same 10 at the repo's n | 10 | 0.10 s | `d934e1d2713b9926…` | 33 007 928 | 24.20% | **8** |
| `S_sample1` | one 2 MiB user sample x 3 filters | 3 | 0.21 s | `c6754b6fab51acdf…` | 86 685 373 | **73.46%** | 0 |

No arm produced a single profile-use warning (`hash mismatch` 0,
`no profile data available for function` 0, `warning:` 0 for all six), and
all six produce byte-identical output to `T_real` on all six correctness
cases (three training, three holdout) after `strip -s`.

**`B_cover`: the literal greedy weighted set cover saturates after two
candidates.** Universe = the 20 reference-hot functions weighted by their
reference share; a candidate covers a function if its own count there is
nonzero; stop below 1% marginal gain or at 50 picks.

```
 1. doccli-0044    +65.436pp -> 65.436pp of 71.162pp, 19/20 functions
 2. doctest-0450   + 5.726pp -> 71.162pp of 71.162pp, 20/20 functions
stop: best marginal gain 0.0000pp < 0.7116pp
     doccli-0044    tot=    226604 hot20= 5.08%  docs/stdlib.dj:2284
     doctest-0450   tot=    217725 hot20= 1.75%  docs/stdlib.dj:1419
```

`doccli-0044` is `jaq --slurp input_filename examples/benches.json`, a
documentation example that names a JSON file on the command line; it covers
19 of the 20 hot functions on its own, and a five-byte doc test covers the
twentieth. Section 75 is why that one line of documentation is the most
valuable object in the repository. The third pick would add **exactly
zero**. So on this pool, *boolean* coverage of the hot set is not a selection
signal at all: the answer is "any two candidates", the training set is
444 329 block counts, and `B_cover_scaled` --- the same procedure over a
universe where every parametric bench is at its scaled n --- produces a
**bit-identical profdata** (`bad1d2e65bda3278…` both), because the greedy
never reaches a parametric candidate. `B_cover_scaled` is therefore not
timed separately; it is the same binary.

**`B_shape`: the steelman.** Since boolean coverage degenerates, the
experiment also carries the strongest mechanical selector we could write:
greedy maximisation of the **histogram intersection** between the merged
profile's distribution over (top-20 functions + one "rest" bin) and the
reference's. Its universe contains both the repository's n and the scaled n
for every parametric bench, so it can use the scale knob. It asks "is this
function executed in the right *proportion*", which is the number section 67
said ordered Experiment 1's arms.

```
 1. bench-0022     n= 1048576 +44.601pp -> intersection  44.60% of the reference shape
stop: best gain 0.0693pp < 0.1000pp  (intersection 44.60%)
```

It picks `to-fromjson` at the top of bench.sh's range and stops: nothing else
in the pool adds a tenth of a point.

**`B_datapath`: top 50 by (hifijson + jaq_json) / (jaq_core::load +
::compile)**, among the 1135 candidates whose dry run exited 0. The
exit-status filter is hygiene, not tuning: 36 of the literal top 50 are pool
items that fail immediately (`jaq -1` with an empty filter), whose whole
profile is 264 counts and whose startup denominator is 0, so the literal rule
selects 9559 counts of crashed processes. With the filter the ratio ranks the
heavy benches above every doc test and the arm is 3.68e9 counts. The stated
budget --- "K such that training <= 30 s" --- does not bind, because the
*entire* pool is 14.1 s instrumented; K = 50 was used instead, to mirror
`B_cover`'s cap.

**`E_expert`: the hand-picked set.** Written into
`scripts/jaq_select_arms.py` before anything was built, and reproduced here
verbatim because the point of the arm is the reasoning:

> What the holdout does: read a 20-25 MiB JSON document, walk every value,
> and (in one of the three cases) write it all back out. In the reference
> profile that is hifijson 27.6% + `jaq_json::read` 15.3% + `jaq_json::write`
> 8.3% + Val 20.9% + allocator 11.4%, against `jaq_core::load` 0.01%.
>
> 1. Exactly one candidate makes jaq parse a large JSON *text*:
>    `examples/benches/to-fromjson.jq`. It is the only pool item whose
>    hifijson count is above 2.2 k (1.9 M at the repository's n = 65536; the
>    runner-up is 2.2 k), and at n = 1048576 it is 531 M counts shaped
>    hifijson 6.7% / read 3.8% / write 1.6% / Val 40.0% / load 0.02%. That is
>    the closest thing to the production shape the repository can produce,
>    and the scale knob is what makes it large enough to dominate a merge. It
>    is pick 1, at the largest n in bench.sh's range.
> 2. Everything else in the pool is startup: the median candidate spends 78%
>    of its counts in `jaq_core::load` + `::compile`, which is 3.3% of
>    production. Adding such items cannot improve the shape, and adding
>    *heavy* ones actively destroys it, because the merge is weighted by
>    absolute counts: the pool without to-fromjson is 5.05e9 counts of
>    interpreter work and would drown pick 1 ten to one. So the expert's
>    second decision is a negative one --- do not add the other 26 benches,
>    and do not scale them.
> 3. to-fromjson prints only `length`, so the buffered writer to stdout
>    (`BufWriter::write`, 1.6% of the reference, the function section 67 saw
>    lose 80% of its instructions) never runs hot. The pool items that do
>    print JSON through it are the doccli/clitest ones that pipe a real JSON
>    producer into jaq. They are ~5 k counts each, i.e. 0.001% of the arm, so
>    they cannot shift a share; they are included as the cheapest available
>    insurance that no hot-set function is left at zero, and the expert's own
>    prediction is that they change nothing.

The ten picks are `bench-0022` at n = 1048576, plus `clitest-0016..0019` and
`doccli-0012,0013,0014,0028,0031`. `E_expert_noscale` is the same ten at the
repository's n, and is the only pair in the experiment that isolates the
scale knob.

**`S_sample1`: one file a user drops in.** `targets/jaq/workloads/gen.py
--sample` writes one 2 MiB `objects`-kind document (seed 20260922401, shared
with neither the training nor the holdout inputs; sha256
`0822c6c194c41452…`, 2 097 194 bytes), and the arm is three invocations ---
that one file through the three Stage 0 filters. `objects` is the only kind
all three filters accept. This models `jev-opt/samples/` (decisions.ja.md
entry 46): the user writes no training workload, they drop in one
representative input. It is 1/150 of `T_real`'s bytes.

### 73. Holdout timing: ten labels, one interleaved run, shuffled order

The Stage 0 recipe (section 55) with one change section 69 asked for: the
label order is a **seeded shuffle per (round, workload)** instead of a
rotation, so the in-run A/A pair is no longer always adjacent and therefore
prices whole-round drift rather than one-slot drift.

```
$ scripts/bench.py run --cpu 4 --warmup 3 --runs 15 --stdout devnull \
    --gap-ms 250 --shuffle 20260922 \
    --label T0=... --label T_all=... --label T_real=... --label T_realB=... \
    --label B_cover=... --label B_shape=... --label B_datapath=... \
    --label E_expert=... --label E_expert_noscale=... --label S_sample1=... \
    --workload "objsearch='.[] | select(.k == \"v\") | .id' hold-objects.json x4" \
    --workload "strproc='[.[] | .name | ascii_downcase | length] | add' hold-strings.json x8" \
    --workload "readwrite=-c '.' hold-ndjson.json x2" \
    --out artifacts/jaq-exp2/holdout.json
artifacts/jaq-exp2/holdout.json: 450 timed samples, 10 labels x 3 workloads x 15 rounds
12m44s
```

**In-run A/A** (`T_realB` against `T_real`, the same bytes at two paths,
`cceee7768c3ed6eb…`):

| workload | ratio | 95% CI | half-width |
|---|---|---|---|
| objsearch | 0.9979 | [0.9843, 1.0127] | **1.42%** |
| strproc | 1.0152 | [1.0100, 1.0200] | 0.50% |
| readwrite | 0.9820 | [0.9737, 0.9914] | 0.88% |
| **aggregate (geomean)** | 0.9983 | [0.9923, 1.0041] | 0.59% |

Worst per-workload half-width over **all** non-base labels is 2.03%
(`B_cover` on objsearch), so **MDE = max(2 x 2.03%, 3%) = 4.07%**, up from
Experiment 1's 3.00%. That is the shuffle doing its job, not the machine
getting worse: the A/A pair now lands anywhere in the round.

**Against T0** (ratio > 1 means faster than no PGO):

| label | objsearch | strproc | readwrite | aggregate | 95% CI | half-width |
|---|---|---|---|---|---|---|
| `T_real` | 1.1883 | 1.0617 | 1.4508 | **1.2232** | [1.2168, 1.2293] | 0.62% |
| `T_realB` | 1.1859 | 1.0778 | 1.4247 | 1.2211 | [1.2144, 1.2280] | 0.68% |
| `S_sample1` | 1.1913 | 1.0762 | 1.4095 | **1.2180** | [1.2103, 1.2256] | 0.77% |
| `B_cover` | 1.1310 | 0.9622 | 1.1620 | **1.0814** | [1.0745, 1.0888] | 0.72% |
| `T_all` | 1.0816 | 1.0393 | 1.0789 | **1.0664** | [1.0602, 1.0729] | 0.64% |
| `T0` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | --- | --- |
| `B_datapath` | 0.9356 | 0.9030 | 0.9765 | **0.9379** | [0.9324, 0.9429] | 0.52% |
| `E_expert_noscale` | 0.9104 | 0.8723 | 1.0021 | **0.9267** | [0.9208, 0.9330] | 0.61% |
| `B_shape` | 0.9051 | 0.8817 | 0.9845 | **0.9227** | [0.9163, 0.9298] | 0.68% |
| `E_expert` | 0.9160 | 0.8731 | 0.9753 | **0.9205** | [0.9159, 0.9252] | 0.47% |

**Against T_real** (ratio < 1 means slower than the realistic training set):

| label | aggregate | 95% CI | gap vs T_real |
|---|---|---|---|
| `T_realB` | 0.9983 | [0.9923, 1.0041] | -0.2% (A/A) |
| `S_sample1` | **0.9957** | [0.9921, 0.9994] | **-0.4%** |
| `B_cover` | 0.8841 | [0.8794, 0.8888] | -13.1% |
| `T_all` | 0.8718 | [0.8667, 0.8774] | -14.7% |
| `T0` | 0.8175 | [0.8135, 0.8218] | -22.3% |
| `B_datapath` | 0.7667 | [0.7622, 0.7713] | -30.4% |
| `E_expert_noscale` | 0.7576 | [0.7529, 0.7627] | -32.0% |
| `B_shape` | 0.7543 | [0.7492, 0.7599] | -32.6% |
| `E_expert` | 0.7525 | [0.7486, 0.7566] | -32.9% |

### 74. Judgment

**1. The within-repo ceiling is +8.1%, and it is not distinguishable from
doing no selection at all.** The best repository-only arm is `B_cover` at
**1.0814** over T0 --- the arm whose entire training set is *two documentation
examples worth 444 329 block counts between them*. `T_all`, the naive "run
everything", is 1.0664. The gap is **1.4%**, far below the 4.07% MDE. Every
other selector in this experiment, including the expert one, is **below T0**.
So:

> On jaq, selecting a PGO training set out of the repository is worth
> nothing measurable over running the whole repository, and the whole-repo
> answer is itself worth only about +7% of the +22% PGO can give.

Experiment 1 measured the *headroom* correctly (`T_real / T_all`, +14.7% in
this run, +17.7% in Experiment 1's). Experiment 2 shows that headroom is
**not reachable from inside this repository**. The 17.7% is a statement about
the value of the right input, not about the value of selection.

**2. Judgment did not beat mechanism, and the one selector that won did so for
a reason none of the others could see.** `B_shape` (the mechanical shape
matcher) picked `bench-0022` at n = 1048576 and stopped. `E_expert` (a human
reading `candidates.jsonl` and the filters behind it) picked `bench-0022` at n
= 1048576 plus nine items worth 0.008% of the arm. They land at 0.9227 and
0.9205, a difference of 0.2%, well inside the A/A. **Mechanism and judgment
reached the same answer, and the answer was wrong**: both are about 8% *slower
than no PGO* and 14% slower than `T_all`.

The comparison that was supposed to price Jev's value instead priced the
*objective* both were given. Section 75 shows that the one selector which
beat `T_all` --- the "degenerate" boolean set cover --- beat it because its
objective is stated over the exact profdata symbols, and it therefore found
the single candidate in the whole repository that runs the code the holdout
runs. Judgment lost to mechanism here not by a margin but by a category: the
expert reasoned about data volume and profile shape and threw that candidate
away.

**3. One 2 MiB sample recovers the entire gap.** `S_sample1` reaches
**1.2180** over T0 and **0.9957** of `T_real`, against an A/A of 0.9983 and
an MDE of 4.07%: it is **indistinguishable from training on 71 MiB**, from
three invocations totalling 6 MiB and 0.21 s. Its hot-set share is 73.46%,
slightly *above* the reference's own 71.16%. This is the product result of
the experiment: the thing that closes the +14.7% gap is not a cleverer
selector, it is one representative file.

**4. The scale knob is worth nothing here.** `E_expert` (to-fromjson at
n = 1048576) against `E_expert_noscale` (the same ten picks at the
repository's n) is 0.9205 vs 0.9267, i.e. scaling made it **0.7% slower**,
sub-MDE and of the wrong sign. The reason is now clear: scaling multiplies
every counter by 16 and LLVM's ProfileSummary cutoffs are percentiles, so a
uniform rescaling is invisible to it (section 70's table shows the shape
moves by under one point). The knob can only matter as a *relative* weight
inside a merge that also contains junk --- a case no arm here contains,
because every selector that picked to-fromjson picked essentially nothing
else. And `B_cover_scaled` shows the other half: a selector whose objective
never reaches a parametric candidate cannot use the knob at all.

**5. Not doing PGO still beats doing it badly, and "badly" now includes the
best-reasoned choice available.** Ordering: S_sample1 (1.2180) ~ T_real
(1.2232) >> B_cover (1.0814) ~ T_all (1.0664) > **T0 (1.0000)** >
B_datapath (0.9379) > E_expert_noscale (0.9267) ~ B_shape (0.9227) ~
E_expert (0.9205). Four of the six new arms ship a binary slower than
`cargo build --release`. Section 66's conclusion --- `jev-opt build` needs a
holdout self-check that can fall back to T0 --- is now not a precaution but
the main line of defence.

### 75. Attribution: one candidate of 1182 runs the production symbols

Section 67 dismissed the zero-count column as "the blunt instrument the
day-0 checklist asks for", because it was 0 for five of Experiment 1's seven
arms, and promoted *share* as the discriminating number. With five more arms
that verdict inverts, and cleanly.

`scripts/profdata_cover.py pgo/jaq/merged.profdata <every arm> --top 20`,
joined with section 73's aggregate:

| arm | zero of 20 | hot-20 share | vs T0 |
|---|---:|---:|---:|
| `T_real` | 0 | 71.16% | 1.2232 |
| `S_sample1` | 0 | 73.46% | 1.2180 |
| `B_cover` | 0 | 3.45% | 1.0814 |
| `T_all` | 0 | 10.16% | 1.0664 |
| `B_datapath` | **6** | 10.39% | 0.9379 |
| `E_expert_noscale` | **8** | 24.20% | 0.9267 |
| `B_shape` | **8** | 25.41% | 0.9227 |
| `E_expert` | **8** | 25.41% | 0.9205 |

**Among arms that pass the section 77 poison check, every arm with a
zero-count hot function is slower than no PGO and every arm without one is
faster.** The separation is total, and it holds on Experiment 1's arms too:
`T_bench` was the only Experiment 1 arm with zeros (8 of 20) and the only
*unpoisoned* one below T0 (0.9217); `T_readme` and `T_big` had 0 zeros and
1.84% / 9.90% shares and were both above T0. Twelve arms across two
experiments, no exception --- but the qualifier is load-bearing, because
`T_allraw` has **0 zeros and is 0.9011**: a poisoned profile is a second,
independent failure mode, and the rule only holds downstream of the gate
that catches it.

Share, by contrast, is not even monotone: `B_cover` at 3.45% beats `T_all`
at 10.16%, and both beat `E_expert` at 25.41%.

**Which functions, and why `to-fromjson` fails.** The eight the expert's pick
never executes:

| # | reference share | function |
|---:|---:|---|
| 1 | 22.52% | `<hifijson::SliceLexer as hifijson::write::Write>::write_until` (the byte search) |
| 17 | 7.26% | `jaq_json::read::parse::<hifijson::SliceLexer>` |
| 2 | 5.73% | `jaq_std::base_run::{closure#7}` |
| 5 | 4.66% | `jaq_json::read::ws_tk::<hifijson::SliceLexer>` |
| 16 | 3.32% | `jaq_json::read::parse_string::<hifijson::SliceLexer>` |
| 12 | 1.70% | `<alloc::raw_vec::RawVecInner>::finish_grow` |
| 13 | 1.54% | `<alloc::raw_vec::RawVecInner>::grow_amortized` |
| 11 | 1.10% | `<alloc::vec::Vec<u8>>::reserve` |

**47.8% of production's block counts land on functions this arm never
executes**, while the arm still reports a 25.41% hot-set share off the other
twelve. Chasing that down is the most useful thing in this experiment, and
the answer is not "the wrong data" --- it is **the wrong symbol for the same
source code**, twice over.

**(a) stdin and a file argument are different monomorphisations.** The
holdout runs `jaq FILTER hold-objects.json …`, and jaq maps a file argument
into a byte slice and parses it with `hifijson::SliceLexer`. Fed on stdin
instead, jaq streams and uses `hifijson::IterLexer<…, StdinLock>`. These are
separate instantiations with separate counters. `clitest-0018` and
`doccli-0013` --- two of the nine items the expert added precisely as
"insurance that no hot-set function is left at zero" --- do parse real JSON,
and their counts land on
`jaq_json::read::parse::<hifijson::IterLexer<…, StdinLock>>`, which is not in
the reference's hot set and never will be. They leave **nine** of the hot 20
at zero on their own.

**(b) the same instantiation is duplicated per codegen unit, and the call
site picks the copy.** `jaq_json::read::parse::<hifijson::SliceLexer>` exists
as **five** separate entries in the profdata, one per CGU that instantiated
it (`hifijson`, `jaq`, `jaq_all`, `jaq_fmts`, `jaq_json`). The reference
executes the `jaq_fmts` copy (249 592 342 counts). `bench-0022`'s `fromjson`
executes the `jaq_all` copy (13 631 519 counts) and leaves the `jaq_fmts` one
at zero. Same source function, same generic arguments, different counters. So
even "this candidate runs the production parser" is not enough; the call path
decides which copy it runs, and `-Cprofile-use` attaches counts per copy.

Put together, over the whole pool:

```
candidates executing production's read::parse copy:  1 / 1182
candidates executing production's write_until copy:  1 / 1182
    doccli-0044   jaq --slurp input_filename examples/benches.json
```

**One candidate out of 1182 touches the code path the holdout spends 42% of
its time in**, and it is a documentation example that happens to name a file
on the command line --- the repository's own `examples/benches.json` --- and
to pass `--slurp`, which buffers the input into a slice. Its counts there are
tiny (1108 on `parse`, 1350 on `write_until`), which is why no share-based
feature can see it.

That is also the whole explanation of section 74:

* `B_cover` picked `doccli-0044` **first**, with a marginal gain of 65.4 of
  the 71.2 available points, because boolean coverage is computed over the
  exact profdata symbols. The "degenerate" greedy found the only candidate in
  the repository on the production path, for exactly the right reason, and
  stopped because there was nothing left to find.
* `T_all` contains it too (it contains everything), which is why `T_all` also
  has no zeros --- but 1108 counts against 5.09e9 of interpreter work.
* `B_datapath` ranks it 0.054 on data-path/startup and does not select it:
  6 zeros. `B_shape` and `E_expert` reject it as negligible: 8 zeros.
* The expert's reasoning was about data volume and profile shape, and the
  candidate that mattered is invisible in both. The expert **excluded the
  only useful item in the pool** and kept nine that exercise the wrong
  lexer.

Every crate- or layer-level metric in this experiment --- `hifijson` share,
data-path/startup, the 44.60% histogram intersection, the layer signature the
grouping uses --- was blind to all of this, because all of them aggregate
away the symbol. The per-symbol zero check was not.

**What the profiles did to the code** (`scripts/norm_code_diff.py
target-jaq-exp1-T_real/…/jaq <arm>/…/jaq --profdata pgo/jaq/merged.profdata`;
instruction counts are T_real -> arm, percentages are the reference share):

| function | share | S_sample1 | B_cover | T_all | B_datapath | E_expert |
|---|---:|---|---|---|---|---|
| `hifijson::…::write_until` | 22.52% | 42 -> 84 | 42 -> 84 | 42 -> 84 | 42 -> 42 | 42 -> 42 |
| `jaq_json::read::parse` | 7.26% | 4426 -> 4031 | 4426 -> 3716 | 4426 -> 2952 | 4426 -> 2725 | 4426 -> 2976 |
| `jaq_json::write::write` | 4.33% | 2390 -> 2318 | 2390 -> 1257 | 2390 -> 1607 | 2390 -> 1269 | 2390 -> 1720 |
| `TermId::run` (interpreter) | 1.93% | 6562 -> 7505 | 6562 -> 4478 | 6562 -> 11802 | 6562 -> **19554** | 6562 -> 5167 |
| `BufWriter<StdoutLock>::write` | 1.56% | 229 -> 240 | 229 -> 45 | 229 -> 45 | 229 -> 45 | 229 -> 45 |
| changed symbols hold | | 70.9% | 86.3% | 88% | 89.0% | 88.2% |

Two corrections to section 67 fall out of this table.

* **The `write_until` doubling is not the damage.** Section 67 read
  42 -> 84 instructions as "a second copy chosen for a loop LLVM now believes
  is cold". `S_sample1` is statistically identical to `T_real` and **also**
  has 84, while `E_expert` and `B_datapath` keep 42 (they never execute it,
  so LLVM has no profile for it and leaves the static shape, which is
  `T_real`'s). The instruction count of that loop is not what separates the
  arms.
* **`BufWriter::write` collapsing from 229 to 45 is common to every
  repository-derived arm**, including the two that beat T0. It costs
  something --- `B_cover` and `T_all` give up most of their readwrite
  advantage --- but it is not what makes an arm slower than no PGO.

And no column of that table orders the arms either. `TermId::run` is
grossly inflated under `B_datapath` (19554, 3.0x) and `T_all` (11802) but
*shrinks* under `E_expert` (5167) --- `to-fromjson` is one tight interpreter
loop that LLVM specialises hard for the wrong filter --- and `T_all` is
above T0 while `E_expert` is below it. `jaq_json::write::write` is smaller
in `B_cover` (1257) than in `E_expert` (1720), and `B_cover` is 17% faster.

**The machine code says what happened; it does not say which arm wins.** The
one quantity in this experiment that does is the zero-count column at the
top of this section, and section 75's explanation of it: an arm is fast if
and only if something in its training set executed the exact symbols the
holdout executes. Of the repository's 1182 candidates, one did.

### 76. Predictions, scored

Nine were written down (`artifacts/jaq-exp2/predictions.txt`) after the
selectors ran and before any binary was built.

| # | prediction | outcome |
|---|---|---|
| a | `B_cover` is degenerate, 1.00-1.06 vs T0 | **wrong where it counts**: the saturation was predicted exactly (2 picks, third gain 0.0000pp), but "degenerate" was the wrong reading --- it is the *best* repository arm at 1.0814, and section 75 shows it saturated because it had already found the only candidate on the production path |
| b | `B_cover_scaled` is bit-identical to `B_cover` | **right** (`bad1d2e65bda3278…` both) |
| c | `B_shape` and `E_expert` are the same answer, within A/A | **right** (0.9227 vs 0.9205, 0.2%) |
| d | the ceiling is 1.10-1.16 vs T0, beating `T_all` by more than the MDE | **wrong, and the main result**: `E_expert`/`B_shape` are 0.92, i.e. *below T0*. The hot-set-share interpolation that produced this number is exactly the metric section 75 shows is broken |
| e | the scale knob is worth less than the MDE | **right** (0.7%, and of the wrong sign) |
| f | `B_datapath` reproduces `T_bench`, 0.92-1.00 | **right** (0.9379; `T_bench` was 0.9217) |
| g | `S_sample1` is within the MDE of `T_real` | **right** (0.9957, against an A/A of 0.9983) |
| h | shuffling raises the A/A half-width to 1.2-2.5% and the MDE to 3.0-5.0% | **right** (2.03%, MDE 4.07%) |
| i | the poison check passes on every Experiment 2 arm and flags `T_allraw` | **right** (section 77) |
| j | (the expert's own pick 3) the nine small doccli/clitest items are "insurance that no hot-set function is left at zero" and "change nothing" | **wrong on the first, right on the second**: they change nothing (`E_expert` vs `B_shape` is 0.2%), but they are not insurance --- they feed JSON on **stdin**, so their parser counts land on the `IterLexer<StdinLock>` instantiation and each leaves nine of the hot 20 at zero by itself (section 75) |

The two that were badly wrong, (a) and (d), were wrong for the same reason:
both reasoned about hot-set *share*, the feature Experiment 1 promoted and
this experiment retires. (d) interpolated a speed from a share; (a) called an
arm degenerate because its share was 3.45%. The arm with the lowest share of
all was the best of them.

### 77. The poison check as a reusable step

`scripts/profdata_sanity.py` makes section 63's finding a gate. A block
cannot have executed more often than the training run had time for, so with
`--max-ipc` retired instructions per second as the ceiling, any block above
`wall_seconds * max_ipc` is not a count. The default 5e9/s is about one
instruction per cycle on a 5 GHz core, generous by several times for a
single-threaded program. Exit status is 1 if any profile fails, so it can
gate a build; `scripts/jaq_arm_profile.py` records each arm's training wall
in `<profdata>.manifest.json` so `--wall-from-manifest` needs no argument.

```
$ scripts/profdata_sanity.py --wall-from-manifest pgo/jaq/arms/*/merged.profdata
profile                             wall s       limit        max block            total  verdict
B_cover/merged.profdata               0.01    4.89e+07            20645           444329  ok
B_cover_scaled/merged.profdata        0.01    4.89e+07            20645           444329  ok
B_shape/merged.profdata               0.97    4.85e+09          8388642        531647573  ok
B_datapath/merged.profdata            6.44    3.22e+10         62669245       3682616849  ok
E_expert/merged.profdata              1.01    5.03e+09          8388657        531693923  ok
E_expert_noscale/merged.profdata      0.10    4.88e+08           524337         33007928  ok
S_sample1/merged.profdata             0.21    1.03e+09          3456858         86685373  ok

7 profiles, 0 poisoned
```

and the positive control, Experiment 1's unguarded arm:

```
$ scripts/profdata_sanity.py --wall 13.1 pgo/jaq/arms/T_all/merged.profdata \
      pgo/jaq/arms/T_allraw-merged.profdata
T_all/merged.profdata                13.10    6.55e+10         82883240       5085349161  ok
T_allraw-merged.profdata             13.10    6.55e+10   39582476944192   39587563369240  POISONED
                                   culprit: counter 150 of 161 in num_bigint::biguint::convert::to_radix_le
                                            39582476944192 = 0x2400037a4340 (604x the limit)
```

It names the function and the counter index, and the value prints as a
pointer into mimalloc's arena region, which is what makes the diagnosis
immediate. The margin is comfortable at both ends: the tightest honest
profile here is `B_cover`, whose 0.01 s of training gives a limit of 4.89e7
against a real maximum of 20 645 (2400x of headroom), and the poisoned one is
604x *over*. No threshold tuning was needed.

### 78. Implications for the Jev Choice design

Written from what actually separated these arms.

**1. Two gates in sequence, and together they have no exception.** First the
poison check of section 77; then, *among profiles that pass it*, per-symbol
zero counts on a reference hot set. Twelve arms across two experiments:
poisoned -> slower than no PGO (`T_allraw`, 0.9011, despite zero zeros); of
the rest, zeros present -> slower than no PGO, zeros absent -> faster. Both
are computable before the PGO-use build from one `llvm-profdata show` each,
neither needs a timing run, and the second would have rejected both the
mechanical and the expert answer here. `jev-opt build` should treat both as
hard preconditions and fall back to T0 when either fails. The open problem
is that the second needs a *reference* hot set, which in production means
either the user's sample (`S_sample1` supplies one) or a first-run profile
of the user's own workload.

**2. The unit of a PGO profile is the symbol, and "the same function" is
not one symbol.** Section 75: production's JSON parse is
`jaq_json::read::parse::<hifijson::SliceLexer>` *in the `jaq_fmts` codegen
unit*. Feed the same bytes on stdin instead of as a file argument and the
counts go to an `IterLexer<StdinLock>` instantiation. Reach the same
instantiation from `fromjson` instead of from the CLI and the counts go to
the `jaq_all` copy of it. Both leave production's symbol at zero. Every
aggregate feature this experiment built --- hifijson share,
data-path/startup, the histogram intersection, the layer signature the
grouping uses --- was fooled by this, and the per-symbol comparison was not.
Whatever Jev is shown must be per-symbol at the hot end, with the CGU
qualifier intact.

**2b. How a candidate is invoked is a selection decision, not a harness
detail.** All 1182 pool candidates were extracted to run with their input on
**stdin**, because that is what the repository's own test runners do
(section 62). That single convention put 1181 of them on the wrong lexer.
The one candidate that lands on the production path, `doccli-0044`, does so
because it names a file on the command line. So `jev-opt build` should treat
*argv shape* --- file argument vs stdin, `--slurp`, `--raw-input`, `-n` ---
as part of the candidate, and where a candidate's input could be presented
either way, it should consider presenting it the way the user's production
invocation does. On this target that one decision is worth more than every
other feature in the experiment combined, and it was not measured as an arm
because it was not anticipated; it is the first thing Experiment 3 should
test.

**3. Counts on the right symbols, then as little else as possible.**
`B_cover`'s 444 329 counts produce the best repository-only binary for two
reasons that both matter: it is the only arm whose selector found the one
candidate on the production path (section 75), *and* what it adds on top is
two orders of magnitude too small to push LLVM off its static heuristics
anywhere else. `T_all` has the same good candidate and 5.09e9 counts of
interpreter work on top, and gives up 1.4%; `B_datapath` has 3.68e9 counts
of interpreter work and no good candidate, and gives up 13%. A selector that
cannot find a representative input should deliberately select *less*, not
more --- which is the opposite of section 66's "recall beats precision", and
holds for the opposite reason: there the good candidate was 40% of the
merge, here it is 0.02%.

**4. What separated `E_expert`'s picks from a mechanical cover, and why it
went the wrong way.** This experiment was set up to ask whether judgment
beats mechanism. It answered the question, but not in the direction it was
posed.

The expert used three things no mechanical rule here had: the *meaning* of a
filter (`fromjson` parses a document, so `to-fromjson` is categorically
unlike the other 26 benches), the *negative* decision that the pool's mass is
startup and must be excluded, and the scale knob on exactly one candidate.
All three are sound as reasoning, all three are visible in the profile shape
--- which is why `B_shape`, given a shape objective, reproduced them
mechanically and landed within 0.2% --- and all three are **about aggregate
quantities**. The information that actually decided the outcome was not an
aggregate: it was *which profdata symbols a candidate's counters land on*,
and by that measure the pool contains exactly one useful item, worth 1108
counts, which both the expert and the shape matcher discarded as noise.

So the design conclusion is not "Jev's judgment is worth more than a cover".
On this pool it was worth 0.2%, and the reasoning that felt most insightful
(a scaled `to-fromjson` is the closest thing to production) produced the
second-worst arm. The conclusion is: **give any chooser, human or model, a
per-symbol acceptance test it is scored against, and the choice between
candidates matters far less than that test.** Jev's plausible remaining edge
is upstream of selection --- reading the user's description of production,
noticing that no repository candidate matches it, and saying so --- and
downstream, in choosing *how* to invoke a candidate (item 2b), which is a
judgment about the user's deployment that no repository artifact records.

**5. The scale knob should stay, but demoted.** Scaling is percentile-
invariant, so it cannot fix a shape; it only changes an item's weight
*relative to other items in the same merge*. It is worth keeping for the case
where a selector keeps junk it cannot identify, and it costs one probe per
parametric candidate (27 items, 100 s here, including the `ack` stack
overflow that a wall-time-only probe would have accepted). It is not the
answer to a repository with no representative input.

**6. `jev-opt/samples/` is not a fallback, it is the feature.** One 2 MiB
file and three invocations, 0.21 s of training, reach 0.9957 of a 71 MiB
training set and +21.8% over no PGO, where the entire repository reaches
+8.1% at best. On this target the product is better described as "drop in one
representative input and `jev-opt build` does the rest" than as "Jev picks
your training set out of your repo". The selection machinery still earns its
place --- it is what decides that the repository *cannot* do the job, and it
is what keeps a bad training set from shipping --- but it is the guard rail,
not the engine.

### 79. Deviations, and what is not done

- **The pool's stdin convention is a confound, and it is the largest one.**
  The extractor runs every candidate with its input on stdin, mirroring the
  repository's own runners (section 62), while the holdout passes file
  arguments. Section 75 shows those are different lexer instantiations, so
  1181 of 1182 candidates were on a code path the holdout never enters. Some
  of that is real --- a doc test's input genuinely is a five-byte literal,
  not a file --- but the *choice* of stdin over a temporary file is the
  harness's, not the repository's, and re-extracting the pool with file
  arguments where the input is a JSON document is an obvious arm that this
  experiment does not contain. Every "the repository cannot do it" statement
  here is conditional on that convention; the +8.1% ceiling in particular
  could move.
- **`B_datapath`'s stated budget does not bind, so K was fixed at 50.** "K
  such that training <= 30 s" selects the entire pool, because all 1182
  candidates are 14.1 s instrumented. K = 50 mirrors `B_cover`'s cap. The
  arm also applies an exit-status-0 filter (section 72); the literal
  unfiltered top 50 is 36 crashed invocations and 9559 block counts and was
  not built.
- **`B_cover_scaled` was not timed.** Its profdata is bit-identical to
  `B_cover`'s, so the binary would be too; only the profdata was produced,
  and its sha256 compared.
- **The reference hot set is `T_real`'s.** Every `B_*` selector is therefore
  oracle-assisted: it is told which functions matter, which a real
  `jev-opt build` does not know. That makes the mechanical arms *stronger*
  than they could be in production, which only sharpens the negative result.
- **`S_sample1` is generated by the same script and the same generator as
  `T_real`'s inputs**, differing only in seed and size. It is therefore the
  most favourable possible sample, and 0.9957 is an upper bound on what one
  file recovers. A user's real file would differ in shape as well as in
  content; that was not measured.
- **The same two binaries moved between runs.** `T_all` and `T_real` are the
  identical stripped files Experiment 1 timed. `T_real` reads 1.2161 there
  and 1.2232 here (+0.6%), but `T_all` reads 1.0329 there and 1.0664 here
  (**+3.2%**). Both experiments' headline gaps are far larger than that, but
  it is direct evidence for section 69's warning that the rotation-based A/A
  understated label-to-label noise, and a reason to compare only within a
  single interleaved run.
- **Layer attribution is an ordered substring match on demangled names.** It
  is coarse by construction (section 70), and section 75 is the case where
  that coarseness is not a presentation detail but the reason a selector
  failed. The `other` bucket is reported everywhere so the leak is visible.
- **The per-candidate profraws (1.9 GB) are not kept in the repository.**
  They live in a scratch directory; `artifacts/jaq-exp2/candidates.jsonl` is
  the reduction, and `scripts/jaq_candidate_profile.py` regenerates them in
  72 s.
- **One run of one machine, one target.** The arms were built once and timed
  once. Section 53's warning stands: jaq's `.text` hash is not reproducible,
  so "the same arm rebuilt" was not checked to be the same binary.
- The three poisoning items are excluded from the candidate profiling run,
  so no Experiment 2 arm can contain them; `T_allraw` is kept only as the
  positive control for section 77.


## Marks (jaq) --- where the human's proxy points jev-opt

Date: 2026-09-22, same machine and pinned toolchain as every section above
(rustc 1.100.0-nightly bba531001 / LLVM 23.1.1), same jaq submodule commit
`c866e70303b5dbc37d83a0b0cbacf10e90af9c8c` (v3.1.1). **Sections are
numbered from 80.**

Decision 58 fixes the experiment at four items, and this is the first:
*speed this function up* --- a human, or Claude acting as the human's proxy,
names the functions and jev-opt decides what to do with them. This section
is the profiling that produced `targets/jaq/jev-marks.txt`. **It contains no
hint, attribute or compiler setting**, and neither does the marks file or
`targets/jaq/jev-marks.rationale.md`: naming a hint here would be the proxy
doing the optimising.

New in this section: `scripts/perf_local.sh` (a rootless `perf`),
`scripts/perf_marks_profile.sh` (record every frozen workload of a target),
`scripts/perf_hotness.py` (per-symbol and inline-aware shares, and the
coverage of a marks file) and `scripts/inline_structure.py` (what is inside
a post-LTO inline host, with a backedge count per source function).

Reproduce with:

```
scripts/perf_local.sh setup                       # no root required
export TARGET=jaq                                 # NOT `TARGET=jaq scripts/...`
scripts/perf_marks_profile.sh /tmp/perf-flat 6 5000
scripts/perf_hotness.py --binary target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/jaq \
    --inline --crates --top 35 --tsv artifacts/jaq-marks/perf-self.tsv \
    --inline-tsv artifacts/jaq-marks/perf-inline.tsv /tmp/perf-flat/*.data
scripts/inline_structure.py --binary target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/jaq \
    --names-from artifacts/jaq-marks/perf-self.tsv --top 24 \
    --tsv artifacts/jaq-marks/inline-structure.tsv
scripts/perf_hotness.py --binary target-jaq-pgo-use/x86_64-unknown-linux-gnu/release/jaq \
    --top 0 --marks targets/jaq/jev-marks.txt /tmp/perf-flat/*.data
```

### 80. `perf` works on this machine after all, without root

results.md "Day 0 (toy)" section 3 recorded that `perf` is absent, and
`scripts/ipsample.c` --- the `LD_PRELOAD` `ITIMER_PROF` sampler oxipng's
section 43 used --- exists because of that. The user prefers `perf`, so it
was tried again, and two things had changed or had never been checked:

```
$ zcat /proc/config.gz | grep -E 'CONFIG_PERF_EVENTS='
CONFIG_PERF_EVENTS=y
$ uname -r ; cat /proc/sys/kernel/perf_event_paranoid
6.18.33.2-microsoft-standard-WSL2
2
```

The WSL2 kernel has the subsystem compiled in, and a `perf_event_open`
probe (software `cpu-clock`, sampling `cpu-clock`, hardware `cycles`,
hardware `instructions`) succeeds on all four at `paranoid=2`. What was
missing was only the *tool*, and installing it needs root --- which this
account does not have (`sudo` asks for a password). The way round is that
`apt-get download` does not need root:

```
$ apt-get download linux-perf libopencsd1 libbabeltrace1 libtraceevent1
$ for d in *.deb; do dpkg-deb -x "$d" $PREFIX/root; done
$ LD_LIBRARY_PATH=$PREFIX/root/usr/lib/x86_64-linux-gnu \
      PERF_EXEC_PATH=$PREFIX/root/usr/lib/perf-core $PREFIX/root/usr/bin/perf --version
perf version 7.1.8
```

`linux-perf` needs exactly three shared libraries Pengwin 13 does not ship
(`libopencsd_c_api.so.1`, `libbabeltrace-ctf.so.1`, `libtraceevent.so.1`).
The tool is 7.1.8 from trixie-backports and the kernel is 6.18; recording
and reporting `cycles:u` work regardless. `scripts/perf_local.sh` is that
sequence plus a wrapper script, idempotent, and it prints the wrapper's
path. **`scripts/ipsample.c` was therefore not used** --- it stays as the
fallback for a machine where this does not work.

Three properties of `perf` on this kernel that the numbers below depend on.

**The hardware PMU is real.** `perf record -e cycles:u` on the hold-strproc
case and `-e cpu-clock:u` on the same case, 6 runs each, agree to within
0.3 percentage points on all eight of the top-8 symbols (25.97/26.16,
13.30/13.05, 6.40/6.48, 6.34/6.32, 4.08/3.81, 3.80/3.77, 3.17/3.22,
3.14/3.09) and to 0.6 points on concentration (top 5 56.09 vs 55.82; top 30
91.13 vs 90.57). A virtualised PMU that fabricated its samples would not
reproduce a software timer this closely.

**Only user time is visible, and the kernel IP leaks anyway.** At
`paranoid=2` the event must be `:u`. 11.16% of samples land outside the jaq
binary: 8.03% at `0xffffffff…` kernel addresses (WSL2 reports the kernel IP
for a `:u` sample taken during a syscall) and 3.04% in libc. Per case the
in-binary fraction is 94.6% (objsearch), 97.1% (strproc) and **68.2%
(readwrite)** --- that case writes 50 MB to `/dev/null`. Every share below
is a share of the in-binary part.

**Callchains do not work on this binary, in either mode.** The frozen recipe
does not force frame pointers, so `--call-graph fp` returns stack garbage
(`0x95e9800095d28` as a caller of `mi_free`). `--call-graph dwarf` resolves
more than one frame for only 20.2% of samples at 4096 bytes of captured
stack and 25.1% at 32768, and **not one** of the resolvable chains has a
mimalloc symbol as its leaf. So there is no inclusive column in this section
and no attribution of the allocator's 22.94% to the jaq functions that drive
it. Recorded as a negative result.

### 81. The recording, and how a sample becomes a function

Six workloads --- the three holdout and the three training cases of section
52, argv for argv including the x4/x8/x2 repeat counts --- each recorded as
six consecutive runs inside one `perf record -e cycles:u -F 5000`, pinned to
CPU 4 (`BENCH_CPU` for jaq), stdout to `/dev/null`, `--no-buildid-cache`.
The binary is the section 53 PGO baseline, re-verified before recording:
`merged.profdata` sha256 `4e879ce1…`, `.text` sha256 `642dd55e…`.

| workload | samples | in-binary share of user cycles |
|---|--:|--:|
| hold-objsearch | 31841 | 94.63% |
| hold-strproc | 33685 | 97.06% |
| hold-readwrite | 27254 | 68.20% |
| train-objsearch | 31800 | 94.60% |
| train-strproc | 33374 | 97.17% |
| train-readwrite | 27079 | 68.37% |

185033 samples, 27079--33685 per workload. Shares are summed sample periods
(what `perf report`'s Overhead column shows), not sample counts.

Attribution is done by `scripts/perf_hotness.py`, not by `perf report`, for
one reason: **the binary contains 761 demangled names with more than one
definition** and `jaq_json::read::parse` has four, so `perf`'s per-symbol
rows split a source function across its LTO copies. The script turns each
sample's ip into a link-time vaddr through that process's own
`PERF_RECORD_MMAP2` record and the binary's LOAD headers (the executable
segment has `p_vaddr - p_offset = 0x1000`, so the two are not
interchangeable), then resolves it against `nm` and against
`llvm-symbolizer --inlining` (Debian LLVM 19.1.7; demangling the binary's
5723 text symbols with the pinned toolchain's 23.1.1 `llvm-nm -C` gives an
identical set of 4763 Rust names, so the marks are spelled the way the
plugin's `llvm::demangle()` will spell them). The holdout and training halves of each case
agree to within 0.5 points on every row, which is the strongest statement
this profile makes about its own repeatability.

### 82. Self time by post-LTO symbol, top 20 of the 236 with a sample

`eq-w` is the mean of the six per-workload shares; `obj`/`str`/`rw` are the
per-case shares with holdout and training averaged. `insns`, `vec` and `be`
are `scripts/interp_share.py`'s machine-code counts for the symbol.

| # | share | eq-w | obj | str | rw | insns | vec | be | crate | function |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|---|
| 1 | 29.29% | 29.15% | 33.9 | 26.0 | 27.5 | 4426 | 150 | 259 | jaq_json | `jaq_json::read::parse::<hifijson::SliceLexer>` |
| 2 | 8.32% | 6.91% | 6.8 | 13.2 | 0.8 | 6562 | 549 | 236 | jaq_core | `<jaq_core::compile::TermId>::run::<jaq_all::data::DataKind>` |
| 3 | 6.81% | 6.14% | 9.3 | 6.6 | 2.5 | 46 | 0 | 3 | C:mimalloc | `mi_free` |
| 4 | 4.48% | 7.55% | 0.1 | 0.0 | 22.6 | 2390 | 22 | 179 | jaq_json | `jaq_json::write::write` |
| 5 | 3.10% | 2.92% | 3.6 | 3.2 | 1.9 | 34 | 0 | 2 | C:mimalloc | `_mi_page_malloc_zero` |
| 6 | 3.09% | 2.89% | 3.7 | 3.1 | 1.8 | 29 | 0 | 0 | C:mimalloc | `mi_theap_malloc_aligned` |
| 7 | 2.71% | 2.12% | 0.0 | 6.4 | 0.0 | 451 | 30 | 40 | jaq_json | `<jaq_json::funs::base<jaq_all::data::DataKind>::{closure#3} as core::ops::function::FnO…` |
| 8 | 2.53% | 2.14% | 4.2 | 2.3 | 0.0 | 1012 | 48 | 53 | jaq_core | `<<jaq_core::path::Path<jaq_json::Val>>::run::{closure#0} as core::ops::function::FnOnce…` |
| 9 | 2.50% | 2.34% | 3.3 | 2.3 | 1.4 | 6 | 0 | 0 | C:mimalloc | `mi_malloc_aligned` |
| 10 | 2.45% | 4.11% | 0.2 | 0.0 | 12.2 | 41 | 0 | 2 | core | `<core::io::write::default_write_fmt::Adapter<alloc::io::buffered::bufwriter::BufWriter<…` |
| 11 | 2.43% | 2.66% | 4.6 | 0.1 | 3.3 | 346 | 21 | 16 | hashbrown | `<hashbrown::raw::RawTable<usize>>::reserve_rehash::<indexmap::map::core::get_hash<jaq_j…` |
| 12 | 2.37% | 2.23% | 5.0 | 0.7 | 1.1 | 271 | 0 | 29 | alloc | `<alloc::rc::Rc<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::Ra…` |
| 13 | 1.99% | 1.59% | 1.0 | 3.8 | 0.0 | 434 | 34 | 18 | core | `<core::iter::adapters::flatten::FlatMap<core::iter::adapters::filter::Filter<alloc::box…` |
| 14 | 1.95% | 1.66% | 3.5 | 1.5 | 0.0 | 21 | 0 | 1 | C:mimalloc | `mi_page_free_list_extend` |
| 15 | 1.73% | 1.36% | 0.0 | 4.1 | 0.0 | 432 | 98 | 14 | jaq_std | `<jaq_std::base_run<jaq_all::data::DataKind>::{closure#7} as core::ops::function::FnOnce…` |
| 16 | 1.31% | 1.07% | 1.2 | 2.0 | 0.0 | 466 | 58 | 13 | jaq_core | `jaq_core::path::run::<jaq_json::Val, jaq_json::Val, alloc::vec::into_iter::IntoIter<(ja…` |
| 17 | 1.30% | 1.02% | 0.0 | 3.1 | 0.0 | 582 | 54 | 25 | core | `<core::iter::sources::from_fn::FromFn<jaq_core::fold::fold<jaq_core::filter::Ctx<jaq_al…` |
| 18 | 1.19% | 0.99% | 1.4 | 1.5 | 0.0 | 1052 | 118 | 19 | jaq_core | `<jaq_core::path::Path<core::result::Result<jaq_json::Val, jaq_core::exn::Exn<jaq_json::…` |
| 19 | 1.17% | 1.23% | 1.7 | 0.6 | 1.4 | 1492 | 0 | 90 | jaq_json | `<jaq_json::Val as core::hash::Hash>::hash::<foldhash::fast::FoldHasher>` |
| 20 | 1.10% | 1.86% | 0.0 | 0.0 | 5.6 | 471 | 152 | 25 | ? | `<&alloc::string::String as core::fmt::Display>::fmt` |

**Concentration: top 5 = 52.01%, top 10 = 65.30%, top 20 = 81.84%, top 30 =
88.50%.** By crate: jaq_json 38.50%, **mimalloc (C) 22.94%** over 88
symbols, jaq_core 15.26%, core 10.47%, alloc 4.49%, `<&…` Display
instantiations 3.00%, hashbrown 2.43%, jaq_std 1.73%, the `jaq` bin 0.60%,
bytes 0.55%. jaq's own workspace crates hold 56.1% of the cycles --- not
comparable with section 54's 35.3%, which was a share of *instrumented*
code and so excluded mimalloc from its denominator by construction.

Only `jaq_json::read::parse` is in the top 3 of all six recordings
(26.0--34.4%). `jaq_json::write::write` is 22.6% of readwrite and 0.1%
elsewhere; `<jaq_json::funs::base…{closure#3}…>::call_once` is 6.4% of
strproc and 0.0% elsewhere; `Rc<IndexMap>::drop_slow` is 5.0% of objsearch.
The full per-case tables are in `targets/jaq/jev-marks.rationale.md`.

### 83. Inline-aware reach: a hot symbol is not a hot function

`read::parse` is 4426 instructions and 259 backedges, of which **805
instructions belong to `read::parse` itself**; the rest is the hifijson
lexer, inlined. A mark names a source function, so the table that matters is
this one: `reach` is the share of cycles whose machine code has that
function anywhere in its inlined frame stack, `leaf` the share where it is
innermost, and `own/ownbe`, `reach-insns/be` are
`scripts/inline_structure.py`'s instruction and machine-code-backedge counts
for the function's own body and for its body plus everything inlined into
it.

| # | reach | leaf | obj | str | rw | own/ownbe | reach-insns/be | function |
|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 1 | 29.29% | 2.92% | 33.9 | 26.0 | 27.5 | 805/26 | 4426/259 | `jaq_json::read::parse::<hifijson::SliceLexer>` |
| 2 | 10.85% | 0.07% | 16.2 | 5.0 | 13.3 | 69/0 | 1064/49 | `<hifijson::SliceLexer as hifijson::token::Lex>::seq::<hifijson::Error, jaq_json::read::…` |
| 3 | 10.64% | 1.90% | 15.9 | 4.9 | 13.1 | 240/4 | 763/21 | `jaq_json::read::parse::<hifijson::SliceLexer>::{closure#1}` |
| 4 | 9.07% | 0.05% | 4.1 | 16.8 | 1.9 | 44/2 | 715/46 | `<hifijson::SliceLexer as hifijson::str::LexWrite>::str_fold::<hifijson::str::Error, all…` |
| 5 | 9.07% | 0.00% | 4.1 | 16.8 | 1.9 | 0/0 | 715/46 | `jaq_json::read::parse_string::<hifijson::SliceLexer>` |
| 6 | 8.32% | 2.02% | 6.8 | 13.2 | 0.8 | 1322/24 | 6562/236 | `<jaq_core::compile::TermId>::run::<jaq_all::data::DataKind>` |
| 7 | 7.53% | 0.49% | 3.4 | 14.0 | 1.4 | 15/0 | 69/3 | `<hifijson::SliceLexer as hifijson::write::Write>::write_until::<hifijson::str::LexWrite…` |
| 8 | 7.45% | 0.00% | 11.1 | 3.3 | 9.6 | 19/0 | 253/10 | `<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>::i…` |
| 9 | 7.45% | 1.38% | 11.1 | 3.3 | 9.6 | 9/0 | 234/10 | `<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>::i…` |
| 10 | 6.81% | 0.19% | 9.3 | 6.6 | 2.5 | -/- | -/- | `mi_free` |
| 11 | 6.75% | 0.00% | 2.8 | 12.9 | 1.0 | 0/0 | 43/2 | `<core::iter::adapters::copied::Copied<core::slice::iter::Iter<u8>> as core::iter::trait…` |
| 12 | 6.75% | 0.14% | 2.8 | 12.9 | 1.0 | 5/0 | 43/2 | `<core::slice::iter::Iter<u8> as core::iter::traits::iterator::Iterator>::try_fold::<(),…` |
| 13 | 6.75% | 0.00% | 2.8 | 12.9 | 1.0 | 0/0 | 43/2 | `<core::iter::adapters::copied::Copied<core::slice::iter::Iter<u8>> as core::iter::trait…` |
| 14 | 5.66% | 0.00% | 8.6 | 2.3 | 7.3 | 18/0 | 205/9 | `<indexmap::map::core::IndexMapCore<jaq_json::Val, jaq_json::Val>>::insert_full` |
| 15 | 4.70% | 2.64% | 6.5 | 4.6 | 1.4 | -/- | -/- | `mi_free_ex` |
| 16 | 4.68% | 1.13% | 1.8 | 9.1 | 0.6 | 6/0 | 20/0 | `core::iter::adapters::copied::copy_try_fold::<u8, (), core::ops::control_flow::ControlF…` |
| 17 | 4.48% | 1.23% | 0.1 | 0.0 | 22.6 | 749/16 | 2390/179 | `jaq_json::write::write` |
| 18 | 3.56% | 1.70% | 1.3 | 7.0 | 0.5 | 6/0 | 14/0 | `core::iter::traits::iterator::Iterator::position::check::<u8, hifijson::str::LexWrite::…` |

The string scan reads as a chain and **the backedge is two frames below the
function that looks hot**: `str_fold` (9.07%) -> `write_until` (7.53%) ->
`Copied<Iter<u8>>::position` (6.75%) -> `Iter<u8>::try_fold` (6.75%) ->
`copy_try_fold` (4.68%) -> `position::check::{closure#0}` (3.56%, leaf
1.70%). `write_until`'s own body is 15 instructions with no backedge of its
own; three appear once the `position` chain is counted in. This is the same
`slice::iter().position(..)` byte scanner section 54 found, seen from the
other end.

### 84. What the PGO profile said, and what `perf` says, about the same binary

Section 54's column is the sum of PGO block counts per profdata record.

| profdata share | perf self | perf reach | function |
|--:|--:|--:|---|
| 22.52% | - | 7.53% | `<hifijson::SliceLexer as hifijson::write::Write>::write_until::<hifijson::str::LexWrite…` |
| 7.26% | 29.29% | 29.29% | `jaq_json::read::parse::<hifijson::SliceLexer>` |
| 5.73% | 1.73% | 1.73% | `<jaq_std::base_run<jaq_all::data::DataKind>::{closure#7} as core::ops::function::FnOnce…` |
| 4.66% | - | 0.46% | `jaq_json::read::ws_tk::<hifijson::SliceLexer>` |
| 4.62% | - | 2.29% | `<hifijson::SliceLexer as hifijson::num::LexWrite>::num_string_with` |
| 4.33% | 4.48% | 4.48% | `jaq_json::write::write` |
| 3.32% | - | 9.07% | `jaq_json::read::parse_string::<hifijson::SliceLexer>` |
| 2.22% | 0.04% | 2.68% | `core::ptr::drop_glue::<jaq_json::Val>` |
| 2.06% | 0.00% | 0.52% | `__rustc::__rust_alloc` |
| 2.00% | - | 0.39% | `__rustc::__rust_dealloc` |
| 1.93% | 8.32% | 8.32% | `<jaq_core::compile::TermId>::run::<jaq_all::data::DataKind>` |
| 1.92% | - | 7.45% | `<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>::i…` |
| 1.85% | - | 0.51% | `<jaq_json::num::Num>::from_str_radix` |
| 1.70% | 0.00% | 0.25% | `<alloc::raw_vec::RawVecInner>::finish_grow` |
| 1.56% | 2.45% | 2.49% | `<core::io::write::default_write_fmt::Adapter<alloc::io::buffered::bufwriter::BufWriter<…` |
| 1.56% | 0.25% | 2.35% | `<alloc::io::buffered::bufwriter::BufWriter<std::io::stdio::StdoutLock> as core::io::wri…` |
| 1.54% | - | 0.40% | `<alloc::raw_vec::RawVecInner>::grow_amortized` |
| 1.36% | 0.32% | 0.44% | `core::ptr::drop_glue::<alloc::boxed::Box<dyn core::iter::traits::iterator::Iterator<Ite…` |
| 1.21% | - | 2.30% | `<bstr::utf8::Chars as core::iter::traits::iterator::Iterator>::count` |
| 1.10% | - | 0.46% | `<alloc::vec::Vec<u8>>::reserve` |

Four differences, all structural:

1. **`write_until`: 22.52% -> 7.53% reach, and it is not in the perf flat
   table at all.** The hottest profdata record in the program was inlined
   into `read::parse`. A profdata record is a pre-inlining IR function; a
   perf sample lands in the symbol that absorbed it.
2. **`read::parse` 7.26% -> 29.29%, `TermId::run` 1.93% -> 8.32%**: the same
   effect from the host's side. The two functions that hold 37.6% of the
   cycles between them sit at ranks 2 and 11 of the profdata list.
3. **mimalloc 4.06% -> 22.94%.** Section 51 said `__rust_alloc` and
   `__rust_dealloc` are one-instruction thunks and that every
   interpreter-layer share in section 54 is therefore an under-count "by an
   unknown amount". The amount is now known: allocation is the second
   largest consumer of cycles in jaq, and no profdata-based list can see it.
4. **Block counts over-weight small, very frequent bodies.** `ws_tk` 4.66%
   -> 0.46%, `num_string_with` 4.62% -> 2.29%, `from_str_radix` 1.85% ->
   0.51%, `base_run…{closure#7}` 5.73% -> 1.73%. A block count is a count,
   not a cost.

The consequence for this experiment is blunt: **the section 54 hot list was
not a usable list of places to mark.** Six of its top ten are either inlined
away, mis-weighted, or invisible.

### 85. The marks file

`targets/jaq/jev-marks.txt`, 15 lines plus a comment header. A line matches
an LLVM function whose demangled v0 name equals it, or continues with `::<`
(a generic instantiation) or `::{closure`; so `jaq_core::path::run` matches
both instantiations and does not match `jaq_core::path::run_all`, and
`jaq_json::read::parse` does not match `jaq_json::read::parse_string`. A `#`
is a comment only as the first non-space character of a line, because
`{closure#3}` contains one.

```
jaq_json::read::parse
<hifijson::SliceLexer as hifijson::token::Lex>::seq
<hifijson::SliceLexer as hifijson::str::LexWrite>::str_fold
<hifijson::SliceLexer as hifijson::write::Write>::write_until
<jaq_core::compile::TermId>::run
<jaq_json::funs::base<jaq_all::data::DataKind>::{closure#3} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once
<<jaq_core::path::Path<jaq_json::Val>>::run::{closure#0} as core::ops::function::FnOnce<(jaq_core::path::Part<jaq_json::Val>, jaq_json::Val)>>::call_once
<jaq_std::base_run<jaq_all::data::DataKind>::{closure#7} as core::ops::function::FnOnce<((jaq_core::filter::Ctx<jaq_all::data::DataKind>, jaq_json::Val),)>>::call_once
jaq_core::path::run
jaq_json::write::write
<core::io::write::default_write_fmt::Adapter<alloc::io::buffered::bufwriter::BufWriter<std::io::stdio::StdoutLock>> as core::fmt::Write>::write_str
<&alloc::string::String as core::fmt::Display>::fmt
<hashbrown::raw::RawTable<usize>>::reserve_rehash::<indexmap::map::core::get_hash<jaq_json::Val, jaq_json::Val>::{closure#0}>
<alloc::rc::Rc<indexmap::map::IndexMap<jaq_json::Val, jaq_json::Val, foldhash::fast::RandomState>>>::drop_slow
<jaq_json::Val as core::hash::Hash>::hash
```

Every mark's comment in the file gives its share, its per-workload shares,
its instruction and backedge counts and what it does --- and nothing else.

| reach | be | mark (abbreviated) |
|--:|--:|---|
| 29.29% | 259 | `jaq_json::read::parse` |
| 13.05% | 49 | `<SliceLexer as hifijson::token::Lex>::seq` |
| 9.07% | 46 | `<SliceLexer as hifijson::str::LexWrite>::str_fold` |
| 8.85% | 236 | `<jaq_core::compile::TermId>::run` |
| 8.75% | 3 | `<SliceLexer as hifijson::write::Write>::write_until` |
| 4.48% | 179 | `jaq_json::write::write` |
| 2.71% | 40 | `<jaq_json::funs::base…{closure#3} as FnOnce<…>>::call_once` |
| 2.53% | 53 | `<<path::Path<Val>>::run::{closure#0} as FnOnce<…>>::call_once` |
| 2.49% | 2 | `<…Adapter<BufWriter<StdoutLock>> as core::fmt::Write>::write_str` |
| 2.43% | 16 | `<RawTable<usize>>::reserve_rehash::<…get_hash<Val, Val>…>` |
| 2.37% | 29 | `<Rc<IndexMap<Val, Val, RandomState>>>::drop_slow` |
| 1.73% | 14 | `<jaq_std::base_run…{closure#7} as FnOnce<…>>::call_once` |
| 1.73% | 13 | `jaq_core::path::run` |
| 1.17% | 90 | `<jaq_json::Val as core::hash::Hash>::hash` |
| 1.10% | 25 | `<&alloc::string::String as core::fmt::Display>::fmt` |

All fifteen still contain a machine-code loop after LTO (`be > 0`), which
was the second of the two tests; the first was share. The reaches overlap
--- the four read-path marks union to exactly `read::parse`'s own 29.29%,
because the other three are entirely inside it --- so the union over all
fifteen is the number that counts:

| | covered |
|---|--:|
| **all six workloads** | **60.91%** of in-binary user cycles |
| hold-objsearch / train-objsearch | 58.17% / 58.68% |
| hold-strproc / train-strproc | 56.91% / 56.72% |
| hold-readwrite / train-readwrite | 74.62% / 74.39% |
| **of the markable (Rust) cycles** | **79.04%** |

The 39.09% not covered is 22.94% mimalloc --- C, no IR, unreachable by any
plugin --- plus a 16.15% tail whose three largest entries are 1.56%, 1.30%
and 1.19%. Reaching 70% of *total* cycles would need something the plugin
cannot do; 79% of what it can touch is the honest ceiling of a 15-mark set
here.

Deliberately excluded, on the record: `core::ptr::drop_glue::<jaq_json::Val>`
(2.68% reach --- the largest unmarked Rust item, but compiler-generated, with
no source function behind it); the `core::iter` adapters under the lexer
(`position` 6.75%, `try_fold` 6.75%, `copy_try_fold` 4.68%) --- they hold the
backedge, but marking `write_until` and `str_fold` reaches the same machine
code and is what a human would point at; `__rust_alloc`/`__rust_dealloc`
(0.52% and 0.39% of cycles against 2.06% and 2.00% of block counts).

### 86. Deviations, and what is not done

- **No timing was run.** This section is profiling only; the marks have not
  been built with, and nothing here is a speed claim.
- **The machine was shared.** The LLVM plugin work (C++ compiles, toy
  builds) ran on other cores throughout. Shares are ratios within one
  pinned process, which is far less sensitive to a neighbour than a wall
  time is, and the holdout/training agreement to 0.5 points is evidence
  that the neighbour did not distort them --- but section 48's rule (one
  measurement at a time) was not honoured and is noted.
- **Kernel time is outside the picture.** 11.16% of samples, and 32% of the
  readwrite case's, are kernel or libc. A marks file cannot address them.
- **No callchains**, for the reason in section 80. The allocator's 22.94%
  is unattributed to callers.
- **`perf.data` is not kept** (7.5 MB flat, 124 MB with dwarf stacks). The
  reductions are `artifacts/jaq-marks/perf-self.tsv` (236 symbols that got
  a sample), `perf-inline.tsv` (1897 source functions) and
  `inline-structure.tsv` (1829 rows), and `/artifacts/` is gitignored like
  every other artifact directory in this repository, so they are not in the
  commit either; the commands above regenerate all three in about 40
  seconds of recording plus 10 of analysis.
- **One binary.** All of this describes the PGO baseline. A different
  configuration inlines differently, and the inline-aware table would move
  with it; the self-time table would move less.
