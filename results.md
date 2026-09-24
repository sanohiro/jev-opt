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

## Day 3 (plugin)

Date: 2026-09-22. Same machine and toolchain as day 0 (nightly-2026-09-21,
rustc 1.100.0-nightly, LLVM 23.1.1, `libLLVM.so.23.1-rust-1.100.0-nightly`
shared). Scope: the LLVM headers, the probe plugin, the extension-point
table, the jev plugin, and its acceptance tests on the toy. No timing, and
none of the real targets.

Reproduce with:

```
scripts/fetch_llvm_headers.sh      # once; downloads 179 MB, builds no LLVM
scripts/build_plugin.sh            # -> plugin/build/libjev{probe,plugin}.so
scripts/plugin_ep_table.sh         # section 2
scripts/plugin_toy_tests.sh all    # sections 3-8
```

Outputs land in `artifacts/plugin-day3/` (git-ignored); the transcript this
section quotes is `artifacts/plugin-day3/tests-all.log`. `plugin/README.md`
documents the env vars, the marks format, the plan schema and the report
schema.

### 1. Headers: two corrections to the recipe

SPEC.ja.md 8.2 says to take the upstream tarball and run
`ninja intrinsics_gen`. Both halves of that are wrong on 23.1.1 and both
failed loudly rather than silently.

**(a) The ABI-breaking-checks option is `LLVM_ABI_BREAKING_CHECKS`.** The
spec (and the day-3 brief) name `LLVM_ENABLE_ABI_BREAKING_CHECKS`, which is
the *generated macro*, not the CMake option. Passing it as `-D` puts the
string `FORCE_OFF` into the cache; `abi-breaking.h.cmake` uses
`#cmakedefine01`, which reads any non-empty non-false string as true:

```
$ grep -iE "ABI_BREAKING|ENABLE_ASSERTIONS" third_party/llvm-build/CMakeCache.txt
LLVM_ABI_BREAKING_CHECKS:STRING=WITH_ASSERTS
LLVM_ENABLE_ABI_BREAKING_CHECKS:UNINITIALIZED=FORCE_OFF
LLVM_ENABLE_ASSERTIONS:BOOL=OFF

$ grep "define LLVM_ENABLE_ABI_BREAKING_CHECKS" \
      third_party/llvm-build/include/llvm/Config/abi-breaking.h
#define LLVM_ENABLE_ABI_BREAKING_CHECKS 1
```

which makes every translation unit reference `llvm::EnableABIBreakingChecks`
— the symbol the host `libLLVM` does **not** define (day 0 section 2 recorded
that it defines `DisableABIBreakingChecks`). The plugin would have failed to
`dlopen` inside rustc. `scripts/build_plugin.sh` has a gate that caught it
first:

```
$ scripts/build_plugin.sh probe
== probe -> .../plugin/build/libjevprobe.so
FAIL: undefined LLVM symbols not provided by .../libLLVM.so.23.1-rust-1.100.0-nightly:
llvm::EnableABIBreakingChecks
```

With `-DLLVM_ABI_BREAKING_CHECKS=FORCE_OFF` the generated header says `0` and
the check passes. The gate is `nm -u` on the plugin minus `nm -D` on the host
`libLLVM`, and it is worth keeping: it turns an unreadable `dlopen` failure
inside rustc into one line at build time.

**(b) `intrinsics_gen` is not the whole header set.**
`PassBuilder.h → CGSCCPassManager.h → LazyCallGraph.h → TargetLibraryInfo.h`
includes `TargetLibraryInfo.inc`, which `intrinsics_gen` does not build. The
targets that do produce every generated header the plugins reach are
`intrinsics_gen analysis_gen vt_gen target_parser_gen omp_gen acc_gen
llvm_vcsrevision_h`. None of them pulls an LLVM library into the graph, so
LLVM itself is still not built; the whole thing is a `llvm-tblgen` build plus
241 tablegen invocations, about three minutes on 32 cores.

Also: `libc/` has to be extracted from the tarball. `llvm/CMakeLists.txt:725`
hard-errors (`LLVM libc is not found`) without it, and `FindLibcCommonUtils`
only ever puts it on an include path.

Other notes:

* `PassPlugin.h` moved: it is `llvm/Plugins/PassPlugin.h` in 23.1, not
  `llvm/Passes/`.
* `OptimizationLevel` is a plain `enum class : int` (O0..O3) in 23.1;
  `getSpeedupLevel()` / `getSizeLevel()` are gone.
* `Function::getEntryCount()` returns `std::optional<uint64_t>`, not the old
  `ProfileCount`.
* `llvm::SHA256` is not exported by the host `libLLVM`, so the plugin carries
  its own sha256 (with a two-vector known-answer test at startup, because
  `JEV_PLAN_SHA` is the only thing between a stale plan and a mis-hinted
  build). `llvm::demangle`, `llvm::Loop::setLoopID`,
  `llvm::addStringMetadataToLoop`, `BlockFrequencyAnalysis`,
  `BranchProbabilityInfo::getEdgeProbability` and
  `llvm::GlobalObject::setAlignment` all are exported.
* The local `cmake` on PATH is a Windows MSVC 3.19 build; the Debian one is
  `/usr/bin/cmake` 4.3.4. The script names it explicitly.

### 2. The extension-point table

`plugin/probe/probe.cpp` registers a no-op logging pass on every PassBuilder
extension point and records the EP, the `ThinOrFullLTOPhase` argument where
there is one, the module, the function count, the number of loops already
carrying `llvm.loop.isvectorized`, and whether the module has a
ProfileSummary. `scripts/plugin_ep_table.sh` runs it over the toy in four
configurations.

Stage is not readable from the module name: under fat LTO rustc reuses the
primary CGU's module identifier **and its process** for the merged module.
What separates them is `FullLinkTimeOptimizationEarly` — everything a process
logs after it, for that module, is the merged stage. The table below uses
that rule; `phase_arg` is what LLVM passed the callback.

**lto = off** (`artifacts/plugin-day3/ep-off.tsv`)

| ep | scope | phase_arg | stage | fires | modules | isvec max |
|---|---|---|---|---|---|---|
| PipelineStart | module | – | prelink | 2 | 2 | 0 |
| PipelineEarlySimplification | module | None | prelink | 2 | 2 | 0 |
| Peephole | function | – | prelink | 2 | 2 | 0 |
| ScalarOptimizerLate | function | – | prelink | 2 | 2 | 0 |
| LateLoopOptimizations | loop | – | prelink | 64 | 2 | 0 |
| LoopOptimizerEnd | loop | – | prelink | 64 | 2 | 0 |
| VectorizerStart | function | – | prelink | 2 | 2 | 0 |
| VectorizerEnd | function | – | prelink | 2 | 2 | 3 |
| OptimizerEarly | module | None | prelink | 2 | 2 | 0 |
| OptimizerLast | module | None | prelink | 2 | 2 | 3 |

**lto = thin**: the same pre-link set, plus a second, per-module post-link
pipeline. `PipelineEarlySimplification`, `OptimizerEarly` and `OptimizerLast`
fire 21 more times with `phase_arg = ThinLTOPostLink`, one per imported
module; `OptimizerLast` there sees up to 20 vectorized loops.
`PipelineStart` fires **only** pre-link (2 times).

**lto = fat** and **lto = fat + PGO** (`ep-fat.tsv`, `ep-fatpgo.tsv`)

| ep | scope | phase_arg | stage | fires | modules | isvec max |
|---|---|---|---|---|---|---|
| PipelineStart | module | – | prelink | 2 | 2 | 0 |
| PipelineEarlySimplification | module | ThinLTOPreLink | prelink | 2 | 2 | 0 |
| Peephole | module-first | – | prelink | 2 | 2 | 0 |
| ScalarOptimizerLate | module-first | – | prelink | 2 | 2 | 0 |
| LateLoopOptimizations | loop | – | prelink | 64 (17 with PGO) | 2 | 0 |
| LoopOptimizerEnd | loop | – | prelink | 64 (17 with PGO) | 2 | 0 |
| OptimizerEarly | module | ThinLTOPreLink | prelink | 2 | 2 | 0 |
| OptimizerLast | module | ThinLTOPreLink | prelink | 2 | 2 | 0 |
| **FullLinkTimeOptimizationEarly** | module | – | **lto** | 1 | 1 | 0 |
| Peephole | function | – | lto | 24 (25) | 1 | 6 |
| **VectorizerStart** | function | – | **lto** | 4 | 1 | 0 |
| VectorizerEnd | function | – | lto | 16 (17) | 1 | 6 |
| **FullLinkTimeOptimizationLast** | module | – | **lto** | 1 | 1 | 19 |

Four things this settles:

1. **The plugin is loaded in the merged fat-LTO stage.** `-Zllvm-plugins`
   registers its callbacks for the LTO pipeline too.
2. **`PipelineStart`, `PipelineEarlySimplification`, `OptimizerEarly` and
   `OptimizerLast` never see the merged module.** Under fat LTO the module
   EPs that do fire there are `FullLinkTimeOptimizationEarly` / `…Last` only.
   Confirmed against the source: `PassBuilderPipelines.cpp`
   `buildLTODefaultPipeline` (line 2032) invokes
   `FullLinkTimeOptimizationEarly` (2038) and `VectorizerStart` (2305) and
   neither `PipelineStart` nor `OptimizerEarly`.
3. **The pre-link pipeline of a fat-LTO build is the ThinLTO *pre-link*
   pipeline** (`phase_arg = ThinLTOPreLink`), which stops before the
   vectorizers: `VectorizerStart` does not fire at all pre-link, and the
   pre-link `isvectorized` count is 0 everywhere.
4. **`lto = off` is not "no LTO phases" to rustc.** For a plain `-O`
   single-file compile the probe records both a `ThinLTOPreLink` and a
   `ThinLTOPostLink` run; for the toy at `lto = off` the module EPs carry
   `phase_arg = None`.

**Extension points chosen:**

* **Loop metadata → `VectorizerStartEP`.** SPEC.ja.md 8.2's first candidate,
  now measured rather than assumed. Under fat LTO it fires only in the merged
  module, which is where the four toy loops live (all four inline into
  `toy::main`), and `isvec` is still 0 there, so nothing has been vectorized
  yet. It is the last point before LoopVectorize.
* **Function attributes → `PipelineStartEP`.** It fires once per CGU,
  pre-link only, before any inlining — which is the only place `noinline` can
  still change the outcome — and because it never fires for the merged module
  there is no second invocation to be idempotent against.

**ProfileSummary is not available at `PipelineStart`, even with PGO.**
`PGOInstrumentationUse` attaches it partway through the pre-link pipeline:

```
ep=PipelineStart               profsummary=0
ep=PipelineEarlySimplification profsummary=0
ep=Peephole                    profsummary=0
ep=ScalarOptimizerLate         profsummary=1
ep=OptimizerEarly              profsummary=1
ep=FullLinkTimeOptimizationEarly profsummary=1
ep=VectorizerStart             profsummary=1
```

SPEC.ja.md 8.2 says the plugin must stop with an error when the module has no
ProfileSummary. That rule cannot be applied at the function-attribute
extension point; see section 9.

### 3. Off-equivalence (5a)

Three arms plus a determinism control, all fat LTO + PGO with the frozen toy
flags:

```
arm              text_sha256                                                      output_sha256
5a-none1         6e07f5abd338bea952afad8129af54c10b58f6fd917e4c8414b6edc23f594668 a58406a75c439ac40d8d0f50964258d235200bf43a70db7e229662926af99423
5a-none2         6e07f5abd338bea952afad8129af54c10b58f6fd917e4c8414b6edc23f594668 a58406a75c439ac40d8d0f50964258d235200bf43a70db7e229662926af99423
5a-off           6e07f5abd338bea952afad8129af54c10b58f6fd917e4c8414b6edc23f594668 a58406a75c439ac40d8d0f50964258d235200bf43a70db7e229662926af99423
5a-applyempty    6e07f5abd338bea952afad8129af54c10b58f6fd917e4c8414b6edc23f594668 a58406a75c439ac40d8d0f50964258d235200bf43a70db7e229662926af99423

normalised code diff (scripts/norm_code_diff.py), baseline = 5a-none1:
  5a-none2       hash 58b3a5764472d6d4  IDENTICAL  symbols: 371 (base 371), changed 0
  5a-off         hash 58b3a5764472d6d4  IDENTICAL  symbols: 371 (base 371), changed 0
  5a-applyempty  hash 58b3a5764472d6d4  IDENTICAL  symbols: 371 (base 371), changed 0
```

`none1` = no `-Zllvm-plugins` at all, `off` = plugin loaded with
`JEV_MODE=off`, `applyempty` = `JEV_MODE=apply` with
`{"fn_attrs": [], "loop_md": []}`. Raw `.text` hash, normalised code hash and
program output all agree. The gate passes.

Checked rather than assumed: adding `-Zllvm-plugins=<path>` to
`CARGO_ENCODED_RUSTFLAGS` does **not** move the v0 crate disambiguator, so
the identical `.text` is not hiding a renaming.

```
$ nm artifacts/plugin-day3/bin-5a-none1 | grep -o 'Cs[A-Za-z0-9]*_3toy' | sort -u
CsDjvIK8uPE8_3toy
$ nm artifacts/plugin-day3/bin-5a-off   | grep -o 'Cs[A-Za-z0-9]*_3toy' | sort -u
CsDjvIK8uPE8_3toy
```

(`debug = 1` is on in all four arms.)

The refusals were tested too, since a plugin that fails open is worse than no
plugin:

```
$ JEV_MODE=apply JEV_PLAN=<plan> JEV_PLAN_SHA=deadbeef rustc -O -Zllvm-plugins=... t.rs
jev-plugin: fatal: JEV_PLAN_SHA mismatch: expected deadbeef, file is 22bced07f91c6ba2...
(exit 1)

$ JEV_MODE=bogus rustc -O -Zllvm-plugins=... t.rs
jev-plugin: fatal: JEV_MODE must be off, dump, apply or apply-dump, got "bogus"

$ JEV_PLAN=<relative path> ...
jev-plugin: fatal: cannot read JEV_PLAN=artifacts/plugin-day3/plan-5c.json
error: could not compile `toyloops` (lib)
```

All three stop the build. The last one is a real trap: the plan path must be
absolute, because rustc runs with the crate directory as its cwd.

`off` registers no callback at all — the plugin returns a
`PassPluginLibraryInfo` with a null `RegisterPassBuilderCallbacks` — so the
pipeline rustc builds is literally the same object. An empty plan writes no
report at all, which is why "apply-empty reports written: 0".

### 4. Dump (5b)

Marks (`artifacts/plugin-day3/marks/toy-all.txt`): the four `toyloops`
functions. Fat LTO + PGO. Three reports, one per (module, stage, pid); the
merged-LTO one carries every loop:

```
-- sites-toy.<hash>-cgu.0-lto-<pid>.json
   stage=lto loop_ep_ran=True profile_summary=True unmatched_marks=[]
   key                                        match         mark              depth trip     insts hotness      leaf
   e46f821f746d117a-spec_next-range.rs-1103   loop_in_mark  sum_indexed       2     1048652  9     22650873822  range.rs:1103
   8d0b9cbf99f073bc--macros.rs-279            loop_in_mark  count_quotes      2     1047828  10    14680066000  macros.rs:279
   68a90983bba55bf7-_closure_0_-lib.rs-26     loop_in_mark  find_special      2     1047791  10    14658593440  lib.rs:26
   42899cdd9cb7b0cc-spec_next-range.rs-1103   loop_in_mark  dot_f64           2     1048514  11    4613463580   range.rs:1103  [fp-reduction]
   c33f9c24f308dd83-spec_next-range.rs-1103   mark_in_loop  sum_indexed       1     2400     25    60000        range.rs:1103
   fc6962caf87d0857-spec_next-range.rs-1103   mark_in_loop  find_special      1     1400     32    44800        range.rs:1103
   434de139f3e2b72f-spec_next-range.rs-1103   mark_in_loop  count_quotes      1     1400     30    42000        range.rs:1103
   da92d60f8eb8470e-spec_next-range.rs-1103   mark_in_loop  dot_f64           1     400      39    15600        range.rs:1103  [fp-reduction]

-- sites-toyloops.<hash>-cgu.0-prelink-<pid>.json
   stage=prelink loop_ep_ran=False profile_summary=True unmatched_marks=[]
   FN  toyloops::count_quotes::{closure#0} inst=4  entry=None  attrs='inlinehint'
   FN  toyloops::find_special::{closure#0} inst=15 entry=None  attrs='inlinehint'
   FN  toyloops::count_quotes             inst=16 entry=1400  attrs=''
   FN  toyloops::find_special             inst=21 entry=1402  attrs=''
```

Four observations.

**The trip counts are right.** The inner loops report ~1048600, and the toy's
arrays are `1 << 20` = 1048576; the outer loops report exactly the driver's
repeat counts (1400 quotes, 1400 special, 2400 sum, 400 dot — `toy/src/main.rs`
`REP_*`). Decision 36's formula (exits = header count − back-edge count,
average trip = header count / exits) reproduces the known answer to four
significant figures without any `Block counts[0]` assumption.

**Eight sites for four marks, and the extra four are the caller's loops.** The
day-3 brief defines the relation as "any instruction's `DILocation` →
`inlinedAt` chain reaches the marked function". Taken literally that also
catches the driver's `for _ in 0..repeats` loop in `toy::run_quotes`, whose
*body* contains the inlined `count_quotes` but whose own frame chain does not
mention it. Both are reported and the `match` column says which:
`loop_in_mark` (the loop inside the function you marked) vs `mark_in_loop`
(the marked function was inlined into a caller's loop). Without that column a
plan would silently hint the repeat loop. This is a recommended spec change
(section 9).

**Only the four `loop_in_mark` rows are the loops a human meant**, and their
hotness ordering (sum 22.7e9, quotes 14.7e9, special 14.7e9, dot 4.6e9) is
the ordering the day-0 per-workload times imply.

**`has_fp_reduction` is true exactly for the two `dot_f64` sites.**

The function table is only populated in the pre-link reports, because by the
merged stage `count_quotes` and `find_special` no longer exist as functions.
`sum_indexed` never appears in any function table: it is already gone at
`PipelineStart` of either CGU. The mechanism was not established --- MIR
inlining is the likely explanation, but it was not checked. `dot_f64` is
instantiated into the `toy` CGU, not `toyloops`. Entry counts (1400, 1402) come from `!prof`
and are only present in the `OptimizerEarly` snapshot, which is why the
function table is written from two points in the pre-link pipeline.

### 5. Loop metadata (5c)

Plan: `vectorize_width: 8` on the `count_quotes` loop,
`unroll_count: 4` on the `sum_indexed` loop, both `stage: "lto"`.

```
   lto  8d0b9cbf99f073bc--macros.rs-279            attached  vectorize.width=8
   lto  e46f821f746d117a-spec_next-range.rs-1103   attached  unroll.count=4
   totals: attached=2
```

Both consumed. New remarks that the baseline does not have:

```
macros.rs:279:24: vectorized loop (vectorization width: 8, interleaved count: 4)   <- new
range.rs:1103:12: unrolled vectorized loop by a factor of 4 with run-time trip count <- new
```

(the baseline's best at `macros.rs:279` is width 4, and it has no "unrolled
vectorized loop" at `range.rs:1103`).

Two things to note.

* **`unroll.count` reached the *vector* loop, not the scalar one.**
  LoopVectorize copies the non-`vectorize.*` operands of the loop id onto the
  vector loop it creates, so `llvm.loop.unroll.count=4` on a loop that then
  vectorizes unrolls the vectorized body. The remark says so in as many
  words. A plan that wants the scalar loop unrolled has to disable
  vectorization on the same site.
* **Width 8 does not produce `zmm`.** `objdump` of `toy::main` shows only
  `%ymm`: znver3 has no AVX-512, so VF 8 over i64 is split into two 256-bit
  operations. The hint was taken; the register width is a target fact.

Program output unchanged (`a58406a7…` in both).

**In the IR.** Rebuilding the same plan with `--emit=llvm-ir` added to the
rustflags gives the post-LTO module (`.../out/toy.ll`) and the pre-link
`toyloops` module. The hint strings themselves are **not** in the post-LTO
IR, and their absence is the proof they were consumed: LoopVectorize's
`setAlreadyVectorized` strips `vectorize.*` and `interleave.*` and puts
`llvm.loop.isvectorized` there instead, and LoopUnroll replaces
`unroll.count` with `unroll.disable`. What identifies the loops is the
plugin's own marker:

```
loop id !1919: key=8d0b9cbf99f073bc--macros.rs-279
   operands: jev.applied, jev.site, llvm.loop.estimated_trip_count,
             llvm.loop.isvectorized, llvm.loop.unroll.runtime.disable
loop id !2453: key=e46f821f746d117a-spec_next-range.rs-1103
   operands: jev.applied, jev.site, llvm.loop.estimated_trip_count,
             llvm.loop.isvectorized, llvm.loop.unroll.disable
```

Each key appears on 2--3 loop ids, because the transforms copy the loop id
onto the vector loop and the remainder loops they create. A build with the
empty plan has no `jev.site` in its IR at all (`grep -c` gives 0), so the
markers are the plugin's and nothing else's. This also means `jev.site` is
*not* a way to find the original loop again after a transform: it is now on
several.

**`-hints-allow-reordering=false` (decision 40), now measured.** Same plan
shape, `vectorize_width: 8` on the `dot_f64` loop:

```
  arm                text_sha256         output_sha256
  5a-none1           6e07f5ab…           a58406a7…
  5c-dot-guarded     6e07f5ab…           a58406a7…     <- flag on: identical to baseline
  5c-dot-unguarded   f35029c2…           0dd3060a…     <- flag off: code AND answer change
  guarded   CantReorderFPOps remarks: 1
  unguarded CantReorderFPOps remarks: 0
  guarded   'vectorized loop' at range.rs:1103: 1
  unguarded 'vectorized loop' at range.rs:1103: 2
```

With the flag the hint is attached, LoopVectorize still refuses on
`CantReorderFPOps`, and both `.text` and the program's answer are
bit-identical to the baseline. Without it the refusal disappears, the loop
vectorizes, and **the program prints a different number**. This is exactly
the mechanism SPEC.ja.md 8.1 described from the source and never measured:
`LoopVectorizeHints::allowReordering()` cannot tell a metadata width hint
from the command-line option, so a plain width hint on an FP reduction
silently authorises reassociation. `-Cllvm-args=-hints-allow-reordering=false`
is pinned for every arm from here on.

### 6. Function attributes (5d)

Plan: `inline: "never"` + `align: 64` on `toyloops::count_quotes`,
`cold: true` on `toyloops::find_special`.

```
   prelink  toyloops::count_quotes  consumed  noinline,align=64
   prelink  toyloops::find_special  consumed  cold
   totals: consumed=2

-- nm, 5d-apply
000000000000fa80 t toyloops::count_quotes
-- nm, baseline: (no such symbol)
-- address 0xfa80, 64-aligned: True

-- the attributes as they stand in the IR, read back with apply-dump
   prelink  toyloops::count_quotes  attrs='noinline,align=64'
   prelink  toyloops::find_special  attrs='cold'
   lto      toyloops::count_quotes  attrs='noinline,align=64'

-- checksums
  baseline  a58406a75c439ac40d8d0f50964258d235200bf43a70db7e229662926af99423
  5d-apply  a58406a75c439ac40d8d0f50964258d235200bf43a70db7e229662926af99423
```

In the IR (`--emit=llvm-ir` again), with an empty-plan build as the control:

```
post-LTO toy.ll:
  define internal fastcc ... @_RNvCs..._8toyloops12count_quotes(...) #96 align 64
  attributes #96 = { noinline ... }

pre-link toyloops.ll:
  count_quotes -> #0 = { noinline ... }
  find_special -> #1 = { cold ... }

baseline (empty plan), pre-link toyloops.ll:
  count_quotes -> #0 = { }   (no noinline, no cold, no align)
  find_special -> #0 = { }
```

`noinline` works: `count_quotes` is inlined away in every other build and
here survives as its own symbol, at a 64-byte boundary, and the attribute is
still on it in the merged LTO module. `cold` is applied to the IR but does
**not** stop `find_special` being inlined — cold lowers the inline bonus, it
is not a barrier — so there is no symbol to look at in the binary; the IR
read-back is the evidence. Program output unchanged.

The per-module report needs merging before it means anything: the same plan
entry is `consumed` in the `toyloops` CGU and `unmatched` in the `toy` CGU,
because the function is only defined in one of them.
`scripts/plugin_report.py apply` does that merge, and the CLI will have to.

### 7. Key resolution and unmatched marks (5e)

A plan naming **all eight** keys the 5b dump produced, applied to a fresh
fat-LTO + PGO build:

```
   totals: attached=8
```

`vanished = 0`, `ambiguous = 0`, `already_vectorized = 0`. Every key the dump
produced resolved to exactly one loop in the apply build. That is the health
metric SPEC.ja.md 8.3 asks for, and on the toy it is clean — as it should be,
since dump and apply use identical flags and identical profdata, so inlining
is identical.

A bogus mark is reported:

```
  lto       loop_ep_ran=True  unmatched_marks=['toyloops::no_such_function']
  prelink   loop_ep_ran=False unmatched_marks=[]
  prelink   loop_ep_ran=False unmatched_marks=[]
```

`unmatched_marks` is only filled in for reports whose `loop_ep_ran` is true.
Under fat LTO the pre-link modules never reach the loop extension point, so
"unmatched there" would be every mark and would mean nothing.

### 8. Key stability when a function attribute changes (5f)

The question the two-phase rule depends on. Answered with a new mode,
`JEV_MODE=apply-dump`, which applies the `fn_attrs` half of a plan at
`PipelineStart` and then dumps the loops out of the IR those attributes
produced — the only way to ask it inside one build, and the shape the CLI
needs anyway.

Plan: `inline: "never"` on `toyloops::count_quotes` and nothing else.

```
-- loop keys per mark: 5b (no attributes) vs 5f (count_quotes noinline)
   toyloops::count_quotes     CHANGED
      only in A: 8d0b9cbf99f073bc--macros.rs-279
      only in B: 55e212187dc9d670--macros.rs-279
   toyloops::dot_f64          SAME
   toyloops::find_special     SAME
   toyloops::sum_indexed      SAME
```

**Only the keys of the function whose attribute changed moved.** The other
three marks keep their keys byte for byte.

Why that one moved: with `noinline`, `count_quotes` is no longer inlined into
`toy::main`, so its loop's owner changes from `toy::main` to
`toyloops::count_quotes`, the inline chain loses two frames, and the depth
goes 2 → 1 (the loop is no longer nested inside the driver's repeat loop).
Three of the five key inputs changed; the key had to move. The hotness is
essentially unchanged (14680063990 vs 14680066000) — it is the same loop.

A second effect: `count_quotes`'s `mark_in_loop` site (the driver's repeat
loop, `434de139…`) **disappears** in the second dump. With the function no
longer inlined there, no instruction in that loop reaches the mark, so it is
correctly no longer attributed to it. Seven sites instead of eight.

The rule this supports: **function attributes are phase one; loop keys must
be re-dumped from a build that already has them.** But the blast radius is
narrow — only the marked function's own sites move, so re-dumping does not
invalidate the rest of an iteration's loop decisions. Whether that holds on
jaq, where marked functions call each other, is not established by this test.

### 9. Spec changes this section recommends

Not applied — SPEC.ja.md and `docs/decisions.ja.md` were not edited.

1. **8.2, header recipe.** `LLVM_ABI_BREAKING_CHECKS`, not
   `LLVM_ENABLE_ABI_BREAKING_CHECKS`; the tablegen target list is seven
   targets, not `intrinsics_gen`; `libc/` must be extracted. Keep the
   undefined-symbol gate as a named step.
2. **8.2, ProfileSummary.** "Abort when the module has no ProfileSummary"
   cannot hold at the function-attribute extension point: with
   `-Cprofile-use` the summary is still absent at `PipelineStart` (section 2).
   Make it a per-extension-point rule, or drop it to a warning recorded in
   the report (`profile_summary` is already a field). Decision 58 also moves
   the profile to `perf`, so PGO may not be present at all.
3. **8.2, extension points.** Fix them as measured: `PipelineStartEP` for
   function attributes, `VectorizerStartEP` for loop metadata, and record
   that under fat LTO the merged module sees only
   `FullLinkTimeOptimization{Early,Last}` plus the function EPs.
4. **8.2, stage detection.** Say explicitly that the module identifier does
   not distinguish pre-link from merged under fat LTO, and that
   `FullLinkTimeOptimizationEarly` is the marker. Report file names need
   `(module, stage, pid)`, which 8.2 already says; the reason is this.
5. **8.3, site key.** Add the `loop_in_mark` / `mark_in_loop` distinction. The
   brief's definition of "a loop belongs to a marked function" pulls in the
   caller's loop whenever the marked function is inlined into one, which on
   the toy doubles the site count. Both should be reported; only
   `loop_in_mark` should be offered to Jev by default.
6. **8.3, two-phase rule.** Record 5f: a function-attribute change moves only
   that function's own loop keys. A plan's `loop_md` entries should carry
   `stage`, and the CLI should re-dump after applying `fn_attrs` (the
   `apply-dump` mode exists for this).
7. **New: `unroll.count` on a vectorizable loop unrolls the vector loop.**
   The hint vocabulary should say so, or `unroll.count` and `vectorize` need
   to be describable as a pair.
8. **3, fixed flags.** `-Cllvm-args=-hints-allow-reordering=false` is now
   measured, not argued: without it a `vectorize.width` hint on an FP
   reduction changes the program's answer (section 5). It belongs in
   `fixed_rustflags` for every arm, including the baseline.
9. **8.3, `ambiguous` for `fn_attrs`.** The loop half and the function half
   need different rules. A `fn_attrs` entry naming a generic function matches
   every monomorphization in the module, and the implementation applies the
   attribute to all of them *and* reports `ambiguous`. For a site key
   `ambiguous` means "do not apply"; for a function name, applying to all
   monomorphizations is probably what a human marking
   `hifijson::str::write_until` meant. Untested --- the toy has no generics,
   and jaq's marks do. The spec should decide which it is rather than leaving
   the implementation to.
10. **8.6, schema.** The implemented plan and report schemas are in
   `plugin/README.md`; they differ from 8.6 (which is the FP-reassociation
   shape of v0.4). `fn_attrs` + `loop_md` replace `entries[]`, and the
   outcome vocabulary gains `attached`, `consumed`, `skipped_empty` and
   `unmatched`.

### 10. What is not established

* Only the toy. Four loops, all in one merged module, no cross-crate marked
  functions calling each other, no generics. The `vanished` / `ambiguous`
  count of 0 in section 7 is a lower bound on the difficulty, not evidence
  the key survives on jaq.
* No timing of any kind. Whether width 8 on `count_quotes` is *faster* is not
  measured here and day 0 section 37's flat result says not to expect much.
* `thin` LTO is handled but barely exercised. The stage tracker takes the
  merged fat-LTO stage from `FullLinkTimeOptimizationEarly` and the ThinLTO
  post-link stage from the `ThinOrFullLTOPhase` argument of
  `PipelineEarlySimplification`; a `lto=thin` dump of the toy labels 12
  imported modules `thinlto` and finds the same 8 sites, but in the post-link
  copy of the `toy` CGU, with 2 more in the post-link `toyloops` module. 16
  report files instead of 3. None of the acceptance tests ran under thin.
* `hot`, `already_vectorized` and `skipped_idempotent` are implemented but
  never exercised: nothing in the toy tests applies a hint twice to the same
  loop or aims one at a loop that is already vectorized at `VectorizerStart`.
* `unmatched_marks` is per report. A mark that matched only in a pre-link
  function table still reads unmatched in the merged-LTO report, so the union
  across reports is the CLI's job and `scripts/plugin_report.py` does not do
  it yet.
* An empty plan writes no report. An auditable "I applied nothing" file would
  be better.

## Search driver (smoke)

`scripts/jev_search.py` --- the loop of SPEC.ja.md 1(3) as a Python driver
(decision 62) --- with `scripts/jev_vocab.py` (the frozen vocabulary and the
frozen candidate wording), `jev-opt.toml` (the values SPEC.ja.md 8 freezes
that the driver owns) and `docs/search-driver.md` (usage, acceptance rule,
state format, file layout).

**These runs are smoke tests**: the toy, one or two rounds, `n = 3`,
`warmup = 1`, plus zero-build probes against the jaq site list. They exist to
show that the loop closes --- plan applies, output matches, statistics come
out --- and **no speed claim may be read out of them**. The toy was flat
under hints on day 0 (section 37) and `n = 3` is below any usable precision
anyway; section 7 below has a demonstration of exactly that.

### 1. What was run

```
scripts/jev_search.py --target toy --marks artifacts/plugin-day3/marks/toy-all.txt \
    --proposer random --rounds 1 --n 3 --warmup 1 --smoke \
    --out artifacts/toy-search/smoke-random
scripts/jev_search.py --target toy --marks artifacts/plugin-day3/marks/toy-all.txt \
    --proposer jev --rounds 1 --n 3 --warmup 1 --smoke \
    --baseline-dir artifacts/toy-search/smoke-random/baseline \
    --out artifacts/toy-search/smoke-jev
scripts/jev_search.py ... --proposer random --rounds 2 --resume ...   # resume
scripts/jev_search.py ... --proposer oracle --dry-run ...             # arm list
scripts/jev_search.py ... --print-state ...                           # state, no HTTP
# and, against the site list of "Sites (jaq)" with no build at all:
scripts/jev_search.py --target jaq --marks targets/jaq/jev-marks.txt \
    --sites targets/jaq/sites.json --site-set oracle.selected_keys_top3 \
    --proposer jev --baseline-dir <the dump build of scripts/jaq_sites.sh> \
    --dry-run | --print-state --out artifacts/jaq-search/_probe
```

A whole toy round is 26 s: two clean fat-LTO builds, one correctness run and
one `bench.py` run of 3 repetitions over 4 cases and 3 labels.

### 2. Site resolution

The baseline is one `JEV_MODE=dump` build, which yields the baseline binary
and the site list together (SPEC.ja.md 8.2). On the four toy marks:

```
3 function sites, 4 loop sites, 0 build site
  fn     fn:toyloops::count_quotes        (its {closure#0} is excluded, see 3)
  fn     fn:toyloops::dot_f64
  fn     fn:toyloops::find_special
  loop   toyloops::sum_indexed@range.rs:1103:12#d2
  loop   toyloops::count_quotes@macros.rs:279:24#d2
  loop   toyloops::find_special@lib.rs:26:32#d2
  loop   toyloops::dot_f64@range.rs:1103:12#d2
```

`toyloops::sum_indexed` has **no function of its own** in the module --- the
day-3 guess that MIR inlined it away, now confirmed from the other side ---
but its loop is still attributed to the mark. So a mark can resolve to a
loop without resolving to a function, and the "a mark that resolves to
nothing is an error" rule of SPEC.ja.md 1(1) has to test both. The first
version of the driver tested only the function table and stopped on a
perfectly good mark.

On jaq, against the frozen site set of "Sites (jaq)": **15 function sites +
16 loop sites = 31 questions per round**, two HTTP requests. `--site-set
oracle.selected_keys_top3` names the pre-registered list in
`targets/jaq/sites.json` (`oracle.selected_keys_topk_per_mark`), and the
same list is used by all three proposers, which is what makes jev, random
and oracle comparable (SPEC.ja.md 2). Without it the driver would see 127
loop sites and stop on `[search] max_sites = 40`.

### 3. A function attribute goes on the mark, not on what it defines

The plugin's mark rule reaches inner items on purpose: a loop inside a
closure is a loop of the marked function. A function *attribute* must not
follow it there --- `inline(never)` on `jaq_json::write::write` is a
statement about that function, and putting `noinline` on the eight closures
it defines as well would stop LLVM inlining them into the mark's own loops,
which is a different intervention from the one the human asked for. So one
Choice fans out to the mark's own functions and **every monomorphization**
(decision 61c) and the inner items are excluded and listed in the round
record's `fn_fanout`. `--fn-attr-scope all` restores the plugin's own reach.
The spec does not settle this; it is the driver's choice and it is written
down in `docs/search-driver.md`.

Telling the two apart is not "does the name contain `::{`". Since the
plugin started reporting the full demangled name (commit 82a22ca), a
monomorphization's generic arguments routinely contain a closure path:

```
<hifijson::SliceLexer as hifijson::token::Lex>::seq
  ::<hifijson::Error, jaq_json::read::ws_tk<hifijson::SliceLexer, ...{closure#1}>>
```

The naive test filed six of jaq's fifteen marks as inner items and dropped
them from the attribute phase entirely. What separates them is the suffix
*after the mark*: `::<...>` is a monomorphization, `::{closure#0}` or
`::helper` is an item defined inside it.

### 4. The plan applies

Round 1 of the random arm on the toy (three `fn_attrs` entries and four
`loop_md` entries), merged over the per-module reports:

```
phase A (JEV_MODE=apply-dump)          phase B (JEV_MODE=apply)
  ..._8toyloops12count_quotes  consumed cold     8d0b9cbf…-macros.rs-279  attached unroll.count=8
  ..._8toyloops12find_special  consumed align=16 68a90983…-lib.rs-26      attached unroll.count=2
  ..._8toyloops7dot_f64        consumed align=64 42899cdd…-range.rs-1103  attached unroll.count=2
                                                 e46f821f…-range.rs-1103  attached interleave.count=2
                                                 + the three fn rows again, consumed
```

`vanished` 0, `ambiguous` 0, `unmatched` 0, `skipped_empty` 0, and
`run_correctness`'s output matches the baseline line for line.

Three things this settles that were open:

* **The plugin tolerates unknown plan fields.** The plan carries `basis`,
  `vocab_version`, and `jev_site_id` / `jev_choice` / `answer_ref` per entry;
  `loadPlanOnce` only `get`s the keys it knows, and the build is unaffected.
  That was read out of the source and is now measured.
* **`apply-dump` with an empty `fn_attrs` still dumps the loops.** The Jev
  arm chose `KEEP_DEFAULT` everywhere, so phase A applied nothing, and phase
  B still got its four refreshed sites. The fallback to the baseline dump
  that the driver carries for this case was not needed.
* **The refreshed keys really are different keys.** `dot_f64`'s loop is
  `e46f821f…` in the baseline dump and `42899cdd…` after the attributes of
  round 1; the site key moves with inlining exactly as decision 61 says,
  which is why the driver keys its history on the coarser `site_id`
  (`<mark>@<file>:<line>:<col>#d<depth>`) and never on the key.

`ambiguous` is **not** a failure. On jaq 13 of 127 keys resolve to 2--9
loops, the plugin attaches the hint to every copy and says so, and a plan
entry is an instruction about a key: such an arm moves several loops at once
and cannot separate them. The driver counts those entries per round
(`n_ambiguous`, a column in `summary.md`) and fails a round only on
`vanished`, `unmatched` or `skipped_empty`.

### 5. One real Jev call per phase

`--proposer jev`, round 1 on the toy, two HTTP requests
(`artifacts/toy-search/smoke-jev/jev-log/`):

```
ts                                r phase  q  status  latency_ms  in    out  cost
2026-09-22T07:02:55.901012+09:00 r1 A     3  200      687.7      5947  234  0.00000000
2026-09-22T07:02:59.759160+09:00 r1 B     4  200      707.7      9397  607  0.00000000
# 2 requests, 7 choice questions, 1.40 s total latency, 15344 + 841 tokens,
# $0.00000000 billed ($0.00065 at list price), 6.15% of the run's wall clock
```

Jev answered `KEEP_DEFAULT` to all seven, with high confidence:

```
phase A  q0 0.95  q1 0.93  q2 0.97      (the three marked functions)
phase B  q0 0.85  q1 0.94  q2 0.97  q3 0.84   (their loops)
probabilities, count_quotes: KEEP_DEFAULT 0.89, inline 0.11, everything else 0
probabilities, its loop:     KEEP_DEFAULT 0.87, vectorize_width_4 0.06,
                             vectorize_width_8 0.04, unroll_count_8 0.02, rest 0
```

Consistent with `docs/jev-samples/01-*`, where the same loop with "LLVM
already vectorized this at VF=4 IC=4" in the state also came back
`keep_default`; the driver's state says the same thing in its
`already vectorized` and remark lines. Nothing here says whether the answer
is *right* --- that needs jaq and real rounds --- but the arm runs, the empty
plan is a legal outcome, and it costs nothing. One request came back 503 and
the retry succeeded; the log line names the failed attempt.

### 6. State, resume, oracle

* `--print-state` prints both phases' state without making a request. The
  toy is 13.3 KB for 3 function questions and 17.8 KB for 4 loop questions;
  jaq's 31 questions are 59 KB (phase A) and 70 KB (phase B), under the
  120 KB at which `[search] max_state_chars` splits a round into several
  requests.
* Source excerpts. The plugin's function table has no source location, so
  the marked function's source is found with `nm` + `addr2line` on the
  baseline binary, which is exact and is why SPEC.ja.md 3 pins
  `-Cdebuginfo=1` and `strip=none`; a definition search over the vendored
  tree and the Cargo.lock-pinned registry crates is the fallback, and the
  leaf location of one of the mark's loops is the last resort. On jaq's 15
  marks that gives source for 10; the remaining 5 are trait-object shims
  whose DWARF definition is in the standard library, and `rust-src` is not
  installed on this machine, so the state says "not available" rather than
  guessing. An earlier version matched such a path to any file with the
  same basename and put an unrelated `jaq-json/tests/common/mod.rs` in the
  state.
* `--resume` on the 1-round run with `--rounds 2` read `rounds.jsonl`,
  reported `1 rounds already recorded`, ran only round 2, and rewrote
  `summary.md`. Re-running it with `--rounds 2` again ran no round at all.
* `--proposer oracle --dry-run` enumerated **62 one-factor arms + 1
  combination** for the toy (3 function sites x 6 candidates + 4 loop sites x
  11 candidates) without building anything. On jaq's frozen set it is
  15x6 + 16x11 + 1 = 267, the number "Sites (jaq)" prices at 20 h.

### 7. Two build-recipe changes, and why they are safe

`scripts/target_common.sh`'s `build_variant` gained two things:

* **`-Z` is passed through** like `-C`. Without it `-Zllvm-plugins=<abs>`
  became `-Cllvm-args=-Zllvm-plugins=<abs>` and the plugin was never loaded.
* **An extra knob equal to a fixed flag, or repeated, is dropped.** An LLVM
  `cl::opt` is `cl::Optional`, so passing the same `-Cllvm-args` option twice
  aborts rustc. This matters for `-Cllvm-args=-hints-allow-reordering=false`,
  which SPEC.ja.md 2 pins for every arm: the jaq branch sets it through
  `FIXED_RUSTFLAGS` and the search driver also passes it, and the build gets
  exactly one copy either way.

Checked by replaying `build_variant` with a stub `cargo`: with no extra
knobs the encoded rustflags are identical to the pre-change ones flag for
flag, so nothing recorded earlier in this file moves.

### 8. What is not established

* **Only the toy has been built.** The jaq side of this section is the site
  list, the state and the arm count, all produced without a build. No jaq
  round, no oracle sweep and no holdout measurement have been run.
* **The acceptance rule promoted a code-identical build.** The Jev arm's
  round 1 applied an empty plan --- the same program as the baseline --- and
  measured 1.0058 with a 95% CI of [1.0007, 1.0137], so the pre-registered
  rule accepted it as the new best. That is the in-sweep null panel of
  SPEC.ja.md 7 firing on the smoke run: at `n = 3` the paired bootstrap's
  interval is not trustworthy, and the rule is only as good as the interval
  it is given. The frozen `[evaluation] repetitions = 15` is the number for
  a real run, and the null arm has to stay in the panel to catch this.
* **The correctness gate was vacuous until it was fixed.** It compared the
  first two whitespace-separated fields of each line of `run_correctness`'s
  output, which is `name sha256` on jaq but `quotes len=… reps=… checksum=…`
  on the toy --- the checksum was never read. It now compares whole lines,
  which works for every target's format, and the recorded smoke runs were
  re-checked: baseline and round output were in fact identical.
* **`basis` is enforced by the driver, not by the plugin.** SPEC.ja.md 8.4
  asks the plugin to stop the build on a mismatch; the plugin ignores the
  field. Within one round the check is a tautology (the same attribute set
  wrote both plans); it bites on `--resume` and on a hand-edited plan.
* **The confidence threshold is off.** SPEC.ja.md 6 wants low-confidence
  answers replaced by `KEEP_DEFAULT` but fixes no threshold, and the one
  sample response answered decisively at confidence 0.47, so
  `[jev] min_confidence = 0` is the frozen default rather than an invented
  number. The seven answers of the smoke run were 0.84 to 0.97.
* **Remark attribution is by source location only** --- the remark lines
  carry no function name (SPEC.ja.md 3) --- so a state section can show a
  neighbouring function's remarks when both live within 40 lines.

## Sites (jaq) --- resolving the marks and enumerating the loops inside them

Date: 2026-09-22, same machine and pinned toolchain as every section above
(rustc 1.100.0-nightly bba531001 / LLVM 23.1.1), same jaq submodule commit
`c866e70303b5dbc37d83a0b0cbacf10e90af9c8c` (v3.1.1). **Sections are
numbered from 87**, continuing the jaq numbering of "Marks (jaq)".

This is step 1 of SPEC.ja.md 1 (3): turn the fifteen marks of section 85
into the list of things Jev will be asked about. **No timing was run.** The
build wall times quoted are build wall times.

New in this section: `scripts/jaq_sites.sh` (the four builds below, plus a
`flags` subcommand that recovers the exact `CARGO_ENCODED_RUSTFLAGS` out of
`build_variant` rather than re-listing it) and
`scripts/jaq_sites_report.py` (mark resolution, the site tables, the oracle
arithmetic -> `targets/jaq/sites.json`, `targets/jaq/sites.md`).

Reproduce with:

```
scripts/build_plugin.sh jev
export TARGET=jaq                                 # NOT `TARGET=jaq scripts/...`
scripts/jaq_sites.sh all                          # base, dump, allkeys, applydump
FLAGS=$(scripts/jaq_sites.sh flags)
scripts/jaq_sites_report.py --reports artifacts/jaq-sites/rep-dump \
    --marks targets/jaq/jev-marks.txt \
    --json targets/jaq/sites.json --md targets/jaq/sites.md \
    "--flags=$FLAGS" --flags-sha "$(printf '%s' "$FLAGS" | sha256sum | cut -d' ' -f1)" \
    --baseline-text-sha <a> --baseline-norm-hash <b> --dump-text-sha <c> \
    --outputs artifacts/jaq-sites/correctness-base.txt
```

### 87. The baseline moves: `-hints-allow-reordering=false` is in the recipe now

Decision 60 (a) and SPEC.ja.md 2 pin
`-Cllvm-args=-hints-allow-reordering=false` for **every** arm including the
baseline, and it was not in the jaq build recipe. It is now
`FIXED_RUSTFLAGS` in the `jaq` arm of `scripts/target_common.sh`, spliced
into `build_variant`'s fixed list (landed in commit 5e40e87 together with
the search driver's `-Z` pass-through and duplicate-knob guard).

Adding a flag changes the baseline, so the baseline was rebuilt and
re-hashed:

```
========== a. baseline, no plugin, with the pinned -hints-allow-reordering=false ==========
  .text sha256   6147eba528220b06c1a22b436b1a7301480decb1d6538f159f09e4ba57cb5a94
train-objects.json 536b38cedb6b6483c654f2a367f82b4b92f4c0f267c6263e421dd1e5007e7127
train-strings.json f9f67ae87fe136bd2b7cbad5d59c2586467c574b0779f6957e0be900bf1a52b9
train-ndjson.json  231f15264418df7a96f6c3d64de3e0f85d93e8f7620bdd5f7f750c0e0bf79ed7
hold-objects.json  a338602a7f3148cbe74d0f9016b386edaf97a832a284a109addb8399090b2b0d
hold-strings.json  baeb97a8af67ca1d65de1c355e256c8a44abd38ff41ac2c2c1f9c8df83fab443
hold-ndjson.json   72ff02e47dafe5becb2f652c3fefc383e57765bd442ec12a1713f3f5bcecad37
```

All six output checksums are byte for byte section 53's. The `.text` hash
is **not** section 53's `642dd55e…`, and that says nothing: section 53
established that jaq's `.text` does not reproduce across two builds of the
same configuration, because mimalloc's C bakes `__TIME__` into `.rodata`.
The criterion that does work says the flag changed nothing at all:

```
target-jaq-pgo-use/.../jaq:      4763 symbols, normalised whole-code hash 7ad6d9821bbed2fb
target-jaq-sites-base/.../jaq:   hash 7ad6d9821bbed2fb  IDENTICAL
  symbols: 4763 (base 4763), changed 0, only-in-base 0, only-here 0
  profile share held by the changed symbols: 0.00%
```

Expected, on reading LLVM: `LoopVectorizeHints::allowReordering()` is
`HintsAllowReordering && (Force || Width > 1)`, so with no width hint
anywhere in the baseline the option cannot reach a decision. **The pinned
flag is a no-op for the baseline and a correctness gate for every hinted
arm** --- which is the reason it has to be on the baseline too, and now is.
The normalised code hash `7ad6d9821bbed2fb` is the baseline identity from
here on; `.text` hashes are recorded but are not comparable.

The `JEV_MODE=dump` build is the same build with the plugin loaded. It has
to be code-identical, and is:

```
========== b. JEV_MODE=dump ==========
  .text sha256   bc8c1abea757de3cbabc86d81051ff6e41b1caddccc648c1f5705eb3d4f9325d
  reports        10
========== b2. dump must not perturb codegen ==========
  hash 7ad6d9821bbed2fb  IDENTICAL   changed 0, only-in-base 0, only-here 0
  OUTPUTS: MATCH
```

So `sites.json` describes the baseline binary, not a binary like it. (The
off-equivalence gate of day 3 5a covered `JEV_MODE=off`; `dump` registers a
real callback and had not been checked on a target this size.) One build is
41--44 s, as in section 53.

### 88. Three bugs in the plugin's mark handling, none of which the toy could show

The toy's marks are `toyloops::count_quotes` --- no generics, no trait
impl, no closure in the name. jaq's fifteen are the opposite, and none of
the three bugs below can be seen on a mark of the toy's shape.

**(2) and (3) were found before any jaq build**, by replicating the
plugin's normaliser in Python over `targets/jaq/jev-marks.txt` and printing
what each mark becomes. **(1) was found by the first dump**, which --- with
the matcher already fixed --- still resolved only **eleven of fifteen**
marks and reported the other four unmatched, truncated at a `#`. They are
numbered in the order they sit in the code.

**(1) `#` was a mid-line comment.** `loadMarks` truncated every line at the
first `#`. Section 85 says a `#` is a comment only as the first non-space
character *because* `{closure#3}` contains one; the plugin did not
implement that. The four marks containing `{closure#N}` became prefixes
that match nothing, which is what the first dump showed. Fixed: a `#`
starts a comment only at the start of a line.

**(2) `stripGenerics` destroyed eleven marks.** Matching normalised both
sides by deleting every balanced `<...>` group. For `foo::bar::<u8>` that
is right; for a trait-impl path it is fatal, because
`<jaq_json::Val as core::hash::Hash>::hash` becomes `hash`. Eleven of the
fifteen marks collapse to a bare method name:

```
 1 'jaq_json::read::parse'        9 'jaq_core::path::run'
 2 'seq'                         10 'jaq_json::write::write'
 3 'str_fold'                    11 'write_str'
 4 'write_until'                 12 'fmt'
 5 'run'                         13 'reserve_rehash::'
 6 'call_once'                   14 'drop_slow'
 7 'call_once'                   15 'hash'
 8 'call_once'
```

With the suffix rule ("the mark was written without its crate") mark 5
would have absorbed every `*::run` in the binary --- including mark 9's
function, since marks are first-match --- mark 12 every `Display::fmt` and
mark 15 every `::hash`. Marks 6, 7 and 8 normalised to the *same* string,
so 7 and 8 could never match anything. Mark 13's turbofish left a path
ending in `::`, which matches nothing at all. **The resolution would not
have been wrong by a little; it would have been meaningless**, and the
failure is silent apart from the two marks that read unmatched.

Fixed by matching the **full** demangled name with the rule section 85
states for this marks file, which is also what `scripts/perf_hotness.py`
used to compute the coverage there: equal, or continuing with the mark plus
`::` (a monomorphization `::<…>`, a closure `::{closure#…}`, any inner
item), or ending with `::` plus the mark. `stripGenerics` survives only as
the readable suffix of a site key, where a collision is harmless.

**(3) `fn_attrs` had a fourth rule of its own.** The plan's function matcher
used equality-or-suffix over stripped names and had **no prefix case**, so
a plan naming a generic function reached no monomorphization by name ---
exactly what decision 61 (c) requires it to reach. It now uses the same
`matchMark` as the marks.

That unification has one recorded consequence on the toy, and it is a
**retraction**: day 3 section 8 reports the `count_quotes` key under
`inline(never)` as `55e212187dc9d670--macros.rs-279`. Re-running
`scripts/plugin_toy_tests.sh` with the fixed matcher gives
`5465bacda4ffabf9--macros.rs-279`, because `inline(never)` on
`toyloops::count_quotes` now also lands on `toyloops::count_quotes::{closure#0}`
(one function before, two now; the report gains an `ambiguous n=2` row
beside the `consumed` one). Everything else in that suite is unchanged:
5b's eight keys, 5c, 5d's checksums and alignment, 5e's `attached=8`, and
5f's verdict that only the changed function's own keys move. **The
conclusion of day 3 section 8 stands; the key string quoted in it does
not.**

`targets/jaq/jev-marks.txt` was **not** edited. Every spelling in it was
right; all three bugs were in the plugin.

A fourth change, additive: each site now carries `marks_in_chain`, every
mark its inline chain reaches, because on jaq the marked functions are
inlined into each other and `mark` alone (the owner's) hides that.

### 89. Mark resolution: fifteen of fifteen

`targets/jaq/sites.md` has the full tables; the summary is
`unmatched_marks = 0` after intersecting across the ten reports, and:

| # | fn rows | distinct linkage names | `loop_in_mark` owned | reached in chain | mark |
|--:|--:|--:|--:|--:|---|
| 1 | 23 | 18 | 49 | 49 | `jaq_json::read::parse` |
| 2 | 8 | 8 | **0** | 34 | `<SliceLexer as token::Lex>::seq` |
| 3 | 5 | 5 | 4 | 9 | `<SliceLexer as str::LexWrite>::str_fold` |
| 4 | 9 | 6 | 6 | 9 | `<SliceLexer as write::Write>::write_until` |
| 5 | 80 | 62 | 15 | 15 | `<jaq_core::compile::TermId>::run` |
| 6 | 2 | 1 | 6 | 6 | `<jaq_json::funs::base…{closure#3} as FnOnce>::call_once` |
| 7 | 4 | 2 | 8 | 8 | `<<path::Path<Val>>::run::{closure#0} as FnOnce>::call_once` |
| 8 | 2 | 1 | 1 | 1 | `<jaq_std::base_run…{closure#7} as FnOnce>::call_once` |
| 9 | 15 | 12 | 8 | 8 | `jaq_core::path::run` |
| 10 | 10 | 8 | 22 | 22 | `jaq_json::write::write` |
| 11 | 2 | 1 | **0** | **0** | `<…Adapter<BufWriter<StdoutLock>> as fmt::Write>::write_str` |
| 12 | 12 | 7 | 9 | 9 | `<&String as Display>::fmt` |
| 13 | 3 | 2 | 7 | 7 | `<RawTable<usize>>::reserve_rehash::<…>` |
| 14 | 2 | 1 | 2 | 2 | `<Rc<IndexMap<Val, Val, RandomState>>>::drop_slow` |
| 15 | 24 | 20 | 12 | 12 | `<jaq_json::Val as core::hash::Hash>::hash` |

"fn rows" counts `(function, module, stage)` rows: 15 marks resolve to 201
rows over 154 distinct linkage names. The gap between the two columns is
per-CGU duplication --- `<&String as Display>::fmt` appears in `bitflags`,
`saphyr_parser` and `toml_span` as well as jaq's own crates --- and the
distinct-linkage column is the monomorphization count decision 61 (c) says
an attribute applies to. Mark 5 is the extreme: **62 monomorphizations**,
one `fn_attrs` entry.

Two marks are worth reading carefully.

* **Mark 2 (`seq`) owns no loop but is reached by 34.** It has no `lto`
  function row at all: after fat LTO it is entirely inlined into
  `jaq_json::read::parse`, so every loop of its body belongs to mark 1.
  Section 83 said the same thing from the profile's side (`seq` 10.85%
  reach, 0.07% leaf). `loopIsMarked` attributes a loop to the *owner*
  first, so those 34 sites are listed under mark 1 and `marks_in_chain`
  is the only place the relation survives. Marks 3 and 4 are the same
  story, partly (4 and 6 of their loops kept their own frame).
* **Mark 11 (`write_str`) has no loop site of any kind.** Its `lto` row is
  42 instructions with an entry count of 0 --- the out-of-line copy is
  cold, and the two backedges section 85 counted are in the code it was
  inlined into. It is a marked function with nothing for the loop half of
  the vocabulary to attach to; the function-attribute half still applies.

Mark selection was made against `perf`, and this is the first time the two
views have been put side by side on the same binary: **a mark can be hot,
resolve perfectly, and still own no loop.**

Pre-existing attributes, read out of the dump, matter for the sweep: LLVM
and rustc already put `inlinehint` on most of the marked functions,
`noinline` on `reserve_rehash` (mark 13) and `Rc<IndexMap>::drop_slow`
(mark 14), and `cold` on several `read::parse` and `write_until`
instantiations. Some `fn_attrs` candidates are therefore no-ops on their
mark. **They were not dropped.** SPEC.ja.md 1 (2) forbids narrowing the
candidate list per site, and a no-op arm is exactly what section 7's
in-sweep null panel is for: it will show up as a normalised code hash equal
to the baseline's.

### 90. The loop sites: 149 in fifteen marks, behind 127 keys

`loop_in_mark` only, as decision 61 (a) requires. The 65 `mark_in_loop`
rows are in `sites.json` and are not sites.

| | |
|---|--:|
| `loop_in_mark` sites | **149** |
| distinct site keys | **127** |
| keys that resolve to exactly one loop | 114 |
| already vectorized at the dump | **0** |
| no profile count on the header | **70** |
| trip count < 2 | **34** of the 79 that have one |
| contains a call | **79** |
| FP reduction | **0** |
| depth 1 / 2 / 3+ | 103 / 31 / 15 |
| excluded `mark_in_loop` | 65 |

Three of those numbers are structural and should not be read as findings
about jaq:

* **`already_vectorized = 0` cannot be anything else.** The dump runs at
  `VectorizerStartEP`, and under fat LTO that is reached once, in the
  merged module, immediately before the only LoopVectorize run of the
  build. Nothing has been vectorized yet when the dump looks. A rule of the
  form "skip width hints on loops that are already vectorized" is therefore
  empty at this point in the pipeline; what the baseline actually
  vectorizes is in the `-pass-remarks` log, not here.
* **`has_fp_reduction = 0`** is a property of jaq: it is a JSON processor,
  and the one place FP arithmetic appears is number parsing, not a
  reduction. The pinned reordering flag is still required, because a width
  hint authorises reordering whether or not this dump found a reduction.
* **70 sites with no profile count** are loops the three training workloads
  never entered. `trip_count`, `header_count` and `hotness` are null/0 for
  exactly those 70 and for no others.

Distribution is very uneven. `read::parse` owns 49 sites (a third of the
total) and `write::write` 22; marks 8, 14 own one and two. Nine of the
fifteen own fewer than ten. Per-mark rows are in `targets/jaq/sites.md`.

The hottest site of all is not in the JSON reader: it is
`a48529f86e22591a-next-macros.rs-180`, depth 2, trip 32, 36 instructions,
under `<&String as Display>::fmt` (mark 12) --- the `core::fmt` padding
loop. The next three are `write::write`'s serialiser loops at
`core/src/fmt/mod.rs:1653`.

### 91. The site key is not unique on jaq: 13 keys hold 35 loops

SPEC.ja.md 8.3's key is the sha256 of (owner, inline chain, leaf location,
body fingerprint, depth). On the toy the eight keys were eight loops. On
jaq **13 of the 127 keys resolve to between 2 and 9 loops**, 35 loops in
all. The worst is `1ba7fbbfb4242b91-write-mod.rs-1653`: nine loops in
`jaq_json::write::write` with the same owner, the same four-frame inline
chain, the same leaf `(fmt/mod.rs, 1653, 12)`, the same 137-instruction
fingerprint and the same depth 1. They are genuinely different loops ---
their header counts run from 14 429 343 to 144 539 536 and their hotness
from 1.98e9 to 1.98e10 --- and the five key inputs cannot tell them apart.
`write::write` is the recursive serialiser, so the same source loop is
inlined many times along call paths that leave the same recorded
`inlinedAt` chain.

That was checked at apply time, not only predicted. A plan naming **all
192** dumped keys (`plugin_report.py allkeys`, `unroll_count=1`, the
day-3 5e test on the real target):

```
   totals: ambiguous+attached=13, attached=179
   outcome rows: attached 214, ambiguous 13, vanished 0
   OUTPUTS: MATCH
```

`vanished = 0`: **every key the dump produced resolved**, which is the
health metric SPEC.ja.md 8.3 asks for, and 13 is exactly the collision
count the dump predicted. 214 = 179 + 35: the plugin **attaches the hint to
every loop a colliding key resolves to** and records the `ambiguous` row
afterwards, in `finalizeKeyOutcomes`. plugin/README.md said the opposite
("for a loop key `ambiguous` means nothing was applied") and has been
corrected.

The consequence for the experiment is not that those sites are lost. It is
that **a plan entry is an instruction about a key, not about a loop**: on
those 13 keys one Choice moves 2 to 9 loops together and the sweep cannot
separate them. The site count that prices the oracle is therefore 127, not
149.

### 92. A function attribute moves only its own mark's keys --- on jaq too

Day 3 section 8 established on the toy that `inline(never)` on one marked
function moves that function's loop keys and nothing else, and said
explicitly that "whether that holds on jaq, where marked functions call
each other, is not established by this test". It holds.

`JEV_MODE=apply-dump`, plan = `inline: "never"` on `jaq_json::write::write`
and nothing else (the mark rule also puts `noinline` on its seven closures,
`write::write::{closure#1,4,5,7,10,11,12}`):

```
   <&alloc::string::String as core::fmt::Display>::fmt        SAME
   <<jaq_core::path::Path<Val>>::run::{closure#0} as …>::call_once  SAME
   <alloc::rc::Rc<indexmap::map::IndexMap<…>>>::drop_slow      SAME
   <hashbrown::raw::RawTable<usize>>::reserve_rehash::<…>      SAME
   <hifijson::SliceLexer as hifijson::str::LexWrite>::str_fold SAME
   <hifijson::SliceLexer as hifijson::write::Write>::write_until SAME
   <jaq_core::compile::TermId>::run                            SAME
   <jaq_json::Val as core::hash::Hash>::hash                   SAME
   <jaq_json::funs::base…{closure#3} as …>::call_once          SAME
   <jaq_std::base_run…{closure#7} as …>::call_once             SAME
   jaq_core::path::run                                         SAME
   jaq_json::read::parse                                       SAME
   jaq_json::write::write                                      CHANGED
      only in A: 9 keys        only in B: 8 keys
```

**Twelve of the thirteen marks that own a site kept every key byte for
byte** (mark 11 owns none and cannot be compared; mark 2 owns none either).
Only `write::write` moved: 10 keys before, 9 after, and the whole site list
went 149 -> 136 with `mark_in_loop` 65 -> 49. The output of all six cases is
unchanged, so the attribute is correctness-neutral here.

This is the empirical support for decision 61 (b)'s two-phase round on the
real target: **the blast radius of a function attribute is the marked
function's own sites**, so phase B's re-dump does not invalidate the rest
of the round. The caveat from the toy still applies in one direction: this
tested one attribute on one mark, and `write::write` is a mark nothing else
in the list is inlined into. A change to `read::parse`, which absorbs marks
2, 3 and 4, would be the harder case and was not run.

### 93. Oracle sizing: the sweep does not fit, and the cap that makes it fit

SPEC.ja.md 2's oracle is (a) a one-factor sweep --- every site, every
candidate, one at a time --- plus (b) one combined arm, so
`Σ(sites × candidates) + 1` builds. With the frozen vocabulary of
SPEC.ja.md 1 (2): 6 function-attribute candidates
(`inline`, `inline(never)`, `cold`, `align=16/32/64`) on each marked
function, 11 loop candidates (`unroll.count=2/4/8`, `unroll.disable`,
`vectorize.width=2/4/8/16`, `interleave.count=1/2/4`) on each loop site.
At the brief's planning figures --- 2.5 min for a clean fat-LTO + PGO jaq
build, 2 min of timing (n = 15, three cases) --- an arm costs 4.5 min.

| rule (cumulative, pre-registered, result-blind) | loop sites | builds | wall clock |
|---|--:|--:|--:|
| one arm per loop site (upper bound; unreachable, a plan addresses keys) | 149 | 1730 | 129.8 h |
| **0.** one arm per distinct site key | 127 | 1488 | **111.6 h** |
| **1.** drop keys the training profile never entered | 62 | 773 | 58.0 h |
| **2.** drop keys whose trip count is < 2 | 32 | 443 | 33.2 h |
| **3.** top 3 by hotness per mark | 16 | 267 | **20.0 h** |

The unreduced sweep is **111.6 h**, 4.6x the ~24 h budget. Note that
SPEC.ja.md 8's own `[search] max_sites = 40` does not save it either:
15·6 + 40·11 + 1 = 531 builds = 39.8 h. The cap has to be smaller than the
spec's.

The three rules are mechanical, decided here before any arm is run, and
none of them looks at a result:

0. **Per key, not per loop** (section 91). Not a reduction so much as
   arithmetic: the sweep cannot address the 35 loops behind 13 keys
   separately, so it must not be priced as if it could.
1. **No profile count on the header** (70 of 149 loops, 65 of 127 keys).
   The training workloads never enter these loops, the search cases are
   those same three workloads, and a hint on a loop that does not execute
   cannot move a wall time. Dropping them costs nothing measurable and
   halves the sweep.
2. **Trip count < 2.** `unroll` and `vectorize` both need iterations to
   work with; the estimate is the profile's (exits = header − back-edge,
   decision 36). 30 of the remaining 62 keys have an average trip below 2.
3. **Top 3 by hotness per mark.** Hotness is `header count × body
   instructions`, from the profile, computed by the plugin before any arm
   exists. Per mark rather than overall so that a mark with one warm loop
   is not crowded out by `read::parse`'s 49.

Rule 3 leaves **16 keys**, and the whole oracle becomes **267 builds,
20.0 h** --- inside the budget. If the per-mark shape is unwanted (three
marks own no site at all, so K is spent unevenly), the alternative
pre-registered form is a single overall cut: top 20 overall = 311 builds =
23.3 h, top 12 overall = 223 builds = 16.7 h. `sites.json` carries both key
lists (`oracle.selected_keys_topk_per_mark`,
`oracle.selected_keys_top20_overall`) so whichever is chosen is frozen
before the first arm.

**No per-site candidate selection was done**, which SPEC.ja.md 1 (2)
forbids as optimising: every surviving site gets all 11 candidates,
including `vectorize.width` on loops with calls and `unroll.count` on the
one site with a 221-trip loop. The only per-candidate observation on the
record is section 89's --- some `fn_attrs` candidates restate an attribute
the compiler already applied --- and it was deliberately not acted on.

The function-attribute half is **90 builds (6.8 h)** whatever the loop cap
does, and decision 61 (b) makes it phase one. The loop counts above are
measured on the *baseline* IR; after the attribute phase the keys are
re-dumped and the count will differ (section 92 suggests it will differ
only inside the marks whose attribute changed).

### 94. Deviations, and what is not done

- **No timing of any kind.** Four jaq builds, no `bench.py`, no A/A. Every
  minute figure in section 93 is the brief's planning figure multiplied by
  a count, not a measurement of this machine.
- **The plugin changed** (section 88), so its sha256 in
  `targets/jaq/sites.json` differs from the one the day-3 sections used,
  and `scripts/plugin_toy_tests.sh` was re-run to confirm the rest of that
  suite is unaffected. One recorded key in day 3 section 8 is retracted.
- **`SPEC.ja.md` and `docs/decisions.ja.md` were not edited.** What they
  should gain from this section: 8.3 must say that a site key is not unique
  on a target with a recursive marked function and that a colliding key
  hints every copy (section 91); 1 (1) should say that the plugin resolves
  the marks and that the rule is section 85's, not a generics-stripped one
  (section 88); 2 should record the oracle cap actually used (section 93);
  and 8's `max_sites = 40` is too large for jaq's build cost.
- **One attribute, one mark** in section 92. The interesting case ---
  changing `read::parse`, which absorbs three other marks --- was not run.
- **`mark_in_loop` rows are carried without their inline chains** in
  `sites.json`, to keep the file under 600 KB. They are excluded from the
  experiment by decision 61 (a); re-run the dump if the chain is wanted.
- **`marks_in_chain` is new and unused.** Nothing yet decides which mark a
  site should be offered under when several reach it; the field only makes
  the choice possible. On jaq it matters for 34 sites (mark 2) and 5+3
  more (marks 3, 4).
- **One profile, one baseline.** All of this describes the PGO baseline
  built from `merged.profdata` `4e879ce1…`. A different profile changes the
  70 zero-count sites and the whole hotness ordering, and a different
  inliner outcome changes the keys.

## Experiment 3 (jaq): Jev vs random, 5 rounds

The first real rounds of the SPEC.ja.md 1 (3) loop on jaq. Two runs,
sequential, on the frozen site set of "Sites (jaq)" section 93: `--proposer
jev --rounds 5`, then `--proposer random --rounds 5`, then one holdout
measurement each. The oracle arm of decision 65 (f) has **not** been run.

### 95. What was run

```
export TARGET=jaq
scripts/jev_search.py --target jaq --marks targets/jaq/jev-marks.txt \
    --sites targets/jaq/sites.json --site-set oracle.selected_keys_top3 \
    --proposer jev --rounds 5 --measure-holdout \
    --out artifacts/jaq-search/jev-r5/
scripts/jev_search.py ... --proposer random --rounds 5 --measure-holdout \
    --baseline-dir artifacts/jaq-search/jev-r5/baseline \
    --out artifacts/jaq-search/random-r5/
```

Frozen values, all from `jev-opt.toml` and `scripts/target_common.sh`, and
identical for both runs: `repetitions = 15`, `warmup = 3`, label order
shuffled from `seed = 20260921` + the round number, `--gap-ms 250`,
`taskset -c 4`, bootstrap 10000 resamples, vocabulary `v1-2026-09-22`, state
format `state-v1-2026-09-22`, `build_knobs = []` (so the `__build__`
pseudo-site of SPEC.ja.md 1 (2) row 4 **was not asked about in either run** ---
no compiler-setting question exists yet). Rounds ran on the **training**
case set (objsearch, strproc, readwrite), the holdout once at the end.

Identities recorded in both `run-manifest.json`: rustc 1.100.0-nightly
(bba531001 2026-09-20), `merged.profdata` `4e879ce1…`, plugin `695412d0…`,
`jev-opt.toml` `a8029ac1…`, `jev-marks.txt` `40ef24cc…`.

**One baseline, shared.** The random run was given
`--baseline-dir artifacts/jaq-search/jev-r5/baseline`, so both arms were
timed against the *same* baseline binary (`e183c81d…`) rather than against
two independent builds of the same recipe --- on jaq those are not
bit-identical ("Stage 0 (jaq)" section 53: mimalloc bakes `__TIME__` in).
The manifests confirm the same `baseline_bin_sha256` in both runs.

Site set, identical in both runs, from
`targets/jaq/sites.json` → `oracle.selected_keys_topk_per_mark`:
**15 function sites + 16 loop sites = 31 Choice questions per round**, two
HTTP requests per round for the Jev arm.

### 96. Jev, 5 rounds: `KEEP_DEFAULT` at every site, every round

| round | phase A (15 fn sites) | phase B (16 loop sites) | plan entries | apply outcomes | correct | ratio | 95% CI | in-run A/A | accepted |
|---|---|---|---|---|---|---|---|---|---|
| 1 | KEEP_DEFAULT ×15 | KEEP_DEFAULT ×16 | 0 | — (empty plan) | yes | 0.9934 | [0.9862, 1.0006] | 0.9999 ±0.0073 | no |
| 2 | KEEP_DEFAULT ×15 | KEEP_DEFAULT ×16 | 0 | — | yes | 0.9976 | [0.9915, 1.0039] | 0.9918 ±0.0078 | no |
| 3 | KEEP_DEFAULT ×15 | KEEP_DEFAULT ×16 | 0 | — | yes | 1.0019 | [0.9968, 1.0071] | 1.0129 ±0.0068 | no |
| 4 | KEEP_DEFAULT ×15 | KEEP_DEFAULT ×16 | 0 | — | yes | 0.9902 | [0.9846, 0.9958] | 1.0166 ±0.0073 | no |
| 5 | KEEP_DEFAULT ×15 | KEEP_DEFAULT ×16 | 0 | — | yes | 1.0009 | [0.9947, 1.0073] | 0.9920 ±0.0076 | no |

Every round refreshed 16 loop sites after phase A (an empty `fn_attrs` set
leaves the keys where the baseline dump put them). `attached` 0,
`consumed` 0, `ambiguous` 0, `vanished` 0, `unmatched` 0,
`skipped_empty` 0 in all ten builds, because every plan was empty. No round
met the acceptance rule, so **the run's best plan is the baseline itself**
and `best-plan.json` is not written.

**The five rounds are therefore five null arms.** Rebuilding round 1's empty
`plan-b.json` and comparing with `scripts/norm_code_diff.py` against the
baseline binary:

```
baseline: 4763 symbols, normalised whole-code hash 7ad6d9821bbed2fb
empty plan: hash 7ad6d9821bbed2fb  IDENTICAL
  symbols 4763, changed 0, only-in-base 0, only-here 0
  profile share held by the changed symbols: 0.00%
```

What that makes measurable, on the training set, at the frozen `n = 15`:
five timings of a **code-identical** binary gave 0.9902, 0.9934, 0.9976,
1.0009, 1.0019 (spread 1.2 pp), while their in-run A/A copies of the same
binary gave 0.9918 … 1.0166 (spread 2.5 pp) with reported half-widths of
0.68–0.78%. Round 4's 95% CI, [0.9846, 0.9958], **excludes 1.0 for a binary
that is code-identical to the baseline.** This is the in-sweep null panel of
SPEC.ja.md 7, and the pre-registered `MDE = max(2 × A/A half-width, 3%)`
is why no such interval is read as a speed claim.

### 97. What Jev was asked and what it answered

`artifacts/jaq-search/jev-r5/jev-log/jev-r5.log`, verbatim:

```
# ts round phase questions http_status latency_ms input_tokens output_tokens cost_usd
2026-09-22T07:13:23.297934+09:00 r1 A        15 200   1698.7   35522   1163 0.00000000
2026-09-22T07:14:14.179582+09:00 r1 B        16 503   1045.2       0      0 0.00000000  ERROR HTTP 503
2026-09-22T07:18:35.329415+09:00 r2 A        15 200   1316.3   35681   1163 0.00000000  (after 2 failed attempt(s): HTTP 503, HTTP 503)
2026-09-22T07:19:25.363432+09:00 r2 B        16 503    945.0       0      0 0.00000000  ERROR HTTP 503
2026-09-22T07:23:37.833023+09:00 r3 A        15 200   1857.5   36000   1163 0.00000000
2026-09-22T07:24:20.967842+09:00 r3 B        16 200   1610.2   38588   2425 0.00000000
2026-09-22T07:28:40.673838+09:00 r4 A        15 200   1562.3   36319   1163 0.00000000  (after 2 failed attempt(s): HTTP 503, HTTP 503)
2026-09-22T07:29:31.033435+09:00 r4 B        16 200   1398.2   38926   2425 0.00000000  (after 2 failed attempt(s): HTTP 503, HTTP 503)
2026-09-22T07:33:50.639732+09:00 r5 A        15 200   1232.4   36638   1163 0.00000000  (after 2 failed attempt(s): HTTP 503, HTTP 503)
2026-09-22T07:34:41.375144+09:00 r5 B        16 503   1129.7       0      0 0.00000000  ERROR HTTP 503

# http requests      10
# choice questions   155
# latency total/avg/max ms  13795.7 / 1379.6 / 1857.5
# tokens in/out      257674 / 10665
# cost usd           0.00000000
# wall clock of the run s   1786.9
# jev share of the run      0.7720%
```

Cost: **$0.00000000 billed** (the gateway's Hobby free tier; the same
257674 + 10665 tokens at list price is under 1 cent). **0.77% of the run's
wall clock** was spent waiting for Jev.

**Three of the ten requests never got an answer.** The gateway returned
HTTP 503 on 17 of the 24 HTTP attempts the ten requests cost; `[jev]
retries = 3` with a 2 s / 4 s backoff recovered four of them, and r1 B,
r2 B and r5 B exhausted all three attempts. SPEC.ja.md 6 says such a
request falls back to `KEEP_DEFAULT` with the reason recorded, and that is
what the driver did: 48 of the 155 questions (3 × 16 loop questions) were
never seen by Jev. **This did not change any plan**: all 75 function answers
and both surviving sets of 16 loop answers were `KEEP_DEFAULT` too, so every
round's plan would have been empty either way. The `.jsonl` line for each
failed request carries `"error": "HTTP 503"` and `failed_attempts`.

Distribution of the **107 answers actually received**:

| | KEEP_DEFAULT | anything else |
|---|--:|--:|
| phase A (function attributes) | 75 | 0 |
| phase B (loop hints) | 32 | 0 |
| total | **107** | **0** |

Confidence: n = 107, min 0.71, p25 0.93, median 0.97, p75 0.99, max 1.00,
mean 0.950. Histogram: 0.7–0.8 → 3, 0.8–0.9 → 8, 0.9–1.0 → 85, 1.00 → 11.
Phase A mean 0.935 (min 0.71), phase B mean 0.987 (min 0.92). No answer fell
below `[jev] min_confidence = 0`, so the confidence rule never fired.

Which candidate came second in the `probabilities`, counted per answer:
`inline` 62, `vectorize_width_8` 24, `cold` 7, `inline_never` 6,
`unroll_count_8` 4, `unroll_disable` 2, `vectorize_width_4` 2.

One answer of each kind, verbatim from the `.jsonl`:

```
round 3, phase B, site  <&alloc::string::String as core::fmt::Display>::fmt @ macros.rs:180
  {"choice": "KEEP_DEFAULT", "confidence": 1,
   "probabilities": {"KEEP_DEFAULT": 1, "unroll_count_2": 0, "unroll_count_4": 0,
                     "unroll_count_8": 0, "unroll_disable": 0,
                     "vectorize_width_2": 0, "vectorize_width_4": 0,
                     "vectorize_width_8": 0, "vectorize_width_16": 0,
                     "interleave_count_1": 0, "interleave_count_2": 0,
                     "interleave_count_4": 0}}

the least confident of the 107, round 1, phase A, site
  <jaq_std::base_run<…>::{closure#7} as core::ops::function::FnOnce<…>>::call_once
  {"choice": "KEEP_DEFAULT", "confidence": 0.71,
   "probabilities": {"KEEP_DEFAULT": 0.77, "inline": 0.23, "inline_never": 0,
                     "cold": 0, "align_16": 0, "align_32": 0, "align_64": 0}}
```

### 98. Random, 5 rounds

Uniform over the same candidate lists at the same 31 sites, seeded from
`[evaluation] seed` and the round number. "fn sites" is the count of Choice
answers, "plan entries" the linkage names they fan out to (decision 61 c:
one Choice covers every monomorphization of the mark).

| round | fn sites hinted | fn plan entries | loop sites hinted | ambiguous keys | apply outcomes | correct | ratio | 95% CI | in-run A/A | accepted |
|---|--:|--:|--:|--:|---|---|---|---|---|---|
| 1 | 12/15 | 119 | 16/16 | 3 | 119 consumed, 13 attached, 3 ambiguous+attached | yes | 0.9510 | [0.9453, 0.9571] | 0.9874 ±0.0050 | no |
| 2 | 15/15 | 138 | 15/16 | 3 | 138 consumed, 12 attached, 3 ambiguous+attached | yes | 1.0017 | [0.9948, 1.0080] | 0.9991 ±0.0090 | no |
| 3 | 13/15 | 136 | 14/16 | 3 | 136 consumed, 11 attached, 3 ambiguous+attached | yes | **1.0193** | [1.0053, 1.0353] | 1.0173 ±0.0144 | **yes** |
| 4 | 14/15 | 137 | 14/16 | 3 | 137 consumed, 11 attached, 3 ambiguous+attached | yes | 0.9959 | [0.9893, 1.0022] | 0.9755 ±0.0719 | no |
| 5 | 13/15 | 119 | 14/14 | 3 | 119 consumed, 11 attached, 3 ambiguous+attached | yes | 0.9134 | [0.9068, 0.9201] | 0.9896 ±0.0074 | no |

Per-round hint mix (Choice answers, not plan entries):

```
r1 A  KEEP_DEFAULT 3, align_16 3, align_32 2, align_64 2, cold 3, inline 1, inline_never 1
r1 B  interleave_count_1 2, interleave_count_2 4, unroll_count_2 3, unroll_count_4 2,
      unroll_count_8 1, unroll_disable 2, vectorize_width_16 2
r2 A  align_16 3, align_32 1, align_64 1, cold 5, inline 3, inline_never 2
r2 B  KEEP_DEFAULT 1, interleave_count_1 2, interleave_count_2 2, interleave_count_4 1,
      unroll_count_2 3, unroll_count_4 2, unroll_disable 1, vectorize_width_2 1,
      vectorize_width_8 2, vectorize_width_16 1
r3 A  KEEP_DEFAULT 2, align_16 3, align_32 2, align_64 3, cold 1, inline 4
r3 B  KEEP_DEFAULT 2, interleave_count_4 4, unroll_count_4 1, unroll_count_8 2,
      unroll_disable 2, vectorize_width_2 4, vectorize_width_16 1
r4 A  KEEP_DEFAULT 1, align_16 3, align_32 3, align_64 2, cold 2, inline 4
r4 B  KEEP_DEFAULT 2, interleave_count_2 2, interleave_count_4 2, unroll_count_2 2,
      unroll_count_4 1, unroll_disable 2, vectorize_width_2 2, vectorize_width_4 1,
      vectorize_width_16 2
r5 A  KEEP_DEFAULT 2, align_16 2, align_32 4, align_64 1, cold 2, inline 1, inline_never 3
r5 B  interleave_count_2 1, interleave_count_4 2, unroll_count_4 1, unroll_count_8 2,
      unroll_disable 1, vectorize_width_2 2, vectorize_width_4 1, vectorize_width_8 1,
      vectorize_width_16 3
```

Three observations that belong to the driver rather than to speed:

* **Every plan entry took effect in every round.** `unmatched` 0,
  `vanished` 0, `skipped_empty` 0 across all five rounds; the acceptance
  rule's clause 2 never fired.
* **Exactly 3 ambiguous keys every round**, the colliding keys of
  section 91 (the hint goes on every copy and the count is recorded, not
  failed --- decision 64).
* **Round 5 refreshed only 14 loop sites, not 16.** Two of the 16 frozen
  keys did not survive that round's function attributes, which is decision
  61 (b) doing exactly what it says it does; those sites were not asked
  about that round. Round 2–4 kept all 16 keys but 1–2 of them drew
  `KEEP_DEFAULT`.
* **Output was bit-identical to the baseline in all five rounds**, with
  `-Cllvm-args=-hints-allow-reordering=false` pinned, including the rounds
  that put `vectorize.width` on FP-carrying loops.

Round 3 met all three clauses of the acceptance rule and became the run's
best plan at 1.0193 --- **while its own in-run A/A, two stripped copies of
the same baseline binary, read 1.0173 ±0.0144.**

### 99. Holdout, once, after the best plans were frozen

Both measured on the holdout case set with the same recipe, `n = 15`,
warmup 3, `taskset -c 4`, gap 250 ms, three labels (`base` = baseline,
`cand` = the run's best plan, `aa` = a second copy of the baseline).

| run | cand | aggregate ratio | 95% CI | in-run A/A | A/A half-width | MDE (pre-registered) | MDE (bench.py, worst workload) |
|---|---|---|---|---|--:|--:|--:|
| jev-r5 | baseline (no round accepted) | **0.9787** | [0.9727, 0.9856] | 0.9906 | 0.94% | 3.00% | 3.95% |
| random-r5 | round-03 | **0.9809** | [0.9764, 0.9857] | 0.9879 | 0.59% | 3.00% | 3.00% |

Both holdouts used the same shuffle seed (`[evaluation] seed = 20260921`,
with no round offset in `measure_holdout`), so the two runs drew the
**same label permutation sequence**: their two A/A values, 0.9906 and
0.9879, are not independent samples of the noise floor.

The pre-registered MDE is `max(2 × A/A half-width, 3%)` on the **aggregate**
A/A interval, which is 3.00% for both runs. `bench.py` computes the same
formula from the **worst per-workload** half-width and prints 3.95% for the
Jev run; both numbers are in `holdout/stats.md` and neither is exceeded by
anything below.

**The Jev run's holdout row is three copies of one binary.** No round was
accepted, so the driver measured the baseline as the run's null arm
(section 102): `base`, `cand` and `aa` are the same 33 MB file. They came
out 1.0000 / 0.9787 / 0.9906 --- **a 2.1 pp spread between byte-identical
binaries on the holdout set**, larger than anything either arm produced.
Per workload, that null spread is objsearch 1.97%, strproc 0.71%,
readwrite 1.61% (half-widths, worst label).

### 100. Attribution: what the accepted binary actually changed

`scripts/norm_code_diff.py baseline/bin random-r5/round-03/bin --profdata
pgo/jaq/merged.profdata`:

```
baseline hash 7ad6d9821bbed2fb -> 29f818e81d950f85  DIFFERS
  symbols 4763 (base 4763), changed 45, only-in-base 0, only-here 0
  profile share held by the changed symbols: 14.79%
    5.73%  432->413 insns  <jaq_std::base_run<…>::{closure#7} …>::call_once   (inline)
    2.99%  240->317 insns  core::ptr::drop_glue::<jaq_json::Val>
    1.93%  6562->6560 insns  <jaq_core::compile::TermId>::run::<…>            (align=64)
    0.57%  76->105 insns  core::ptr::drop_glue::<alloc::boxed::Box<bytes::Bytes>>
    0.43%  471->852 insns  <&alloc::string::String as core::fmt::Display>::fmt (align=16 + unroll.count=4)
    0.40%  286->108 insns  core::ptr::drop_glue::<[indexmap::Bucket<Val, Val>]>
    0.25%  730->573 insns  <jaq_json::Val>::index_opt
    0.22%  271->87  insns  <Rc<IndexMap<Val, Val, …>>>::drop_slow             (inline + unroll.disable/count=8)
    0.10%  1012->318 insns <Path<Val>::run::{closure#0} …>::call_once         (inline)
    (35 more, each below 0.1% of the profile)
```

Of the 45 changed symbols, **11 carry the name of one of the 15 marks**
(matched on the mark's last path segment, so this is an approximation); the
other 34 are callers, monomorphizations and drop glue that moved because
`inline` on four marks changed what the inliner saw. The Jev run has no such diff: its best plan is the baseline, and the
empty-plan build is normalised-code-identical to it (section 96).

Round-03's plan, for the record (`docs/experiments/jaq-exp3/random-r5-best-plan.json`):
phase A `read::parse` align=64, `Lex::seq` cold, `str_fold` align=32,
`write_until` align=16, `TermId::run` align=64, `write::write` inline,
`funs::base{closure#3}` align=16, `Path::run{closure#0}` inline,
`Adapter::write_str` KEEP_DEFAULT, `reserve_rehash` KEEP_DEFAULT,
`Rc<IndexMap>::drop_slow` inline, `base_run{closure#7}` inline,
`path::run` align=64, `Val::hash` align=32, `String::fmt` align=16;
phase B 14 loop hints over 16 keys (2 KEEP_DEFAULT), listed in the plan file.

### 101. What happened, in the pre-registered metrics only

* **Jev's best plan is the baseline.** Jev answered `KEEP_DEFAULT` to
  107 of 107 questions it answered, at mean confidence 0.950; 48 further
  questions got `KEEP_DEFAULT` from the HTTP-503 fallback rule. No round
  was accepted, so there is no Jev plan to measure: **+0.00% by
  construction**, and the run's holdout row is the null arm at 0.9787
  [0.9727, 0.9856].
* **Random's best plan is −1.91% on holdout**: ratio 0.9809, 95% CI
  [0.9764, 0.9857], against a training-set estimate of +1.93%
  [+0.53%, +3.53%]. The sign reversed between the two case sets.
* **MDE = 3.00%** for both runs (`max(2 × 0.94%, 3%)` and
  `max(2 × 0.59%, 3%)`). Neither result exceeds it, in either direction, so
  neither arm may be called faster or slower than the baseline.
* **Neither arm produced a plan whose holdout interval clears the MDE.**
  The only round that met the pre-registered acceptance rule (random round 3)
  had an in-run A/A of 1.0173 ±0.0144 in the same measurement, i.e. the
  identical-binary control moved almost as far as the candidate did.
* **Correctness held everywhere**: 10 of 10 builds (5 Jev + 5 random) matched
  the baseline's `run_correctness` output line for line, and 0 of 10 had an
  `unmatched`, `vanished` or `skipped_empty` plan entry.

### 102. Wall clock, driver fixes, deviations

**Wall clock.** Per round (build A + build B + correctness + bench):

```
jev-r5     r1 304 s   r2 310 s   r3 295 s   r4 310 s   r5 310 s    total 1787 s (29.8 min)
random-r5  r1 294 s   r2 291 s   r3 300 s   r4 340 s   r5 296 s    total 1726 s (28.8 min)
```

Plus one `JEV_MODE=dump` baseline build (~130 s including correctness,
built once and shared) and two holdout measurements (~120 s each). The whole
of Experiment 3 was **about 62 minutes of wall clock**, 07:11–08:13 JST
2026-09-22. Jev's share of its own run was 0.77%; the cost was $0.

**Two changes to `scripts/jev_search.py`, both records-only.** Neither
touches the acceptance rule, the vocabulary, the state format or the site
set, and both were made before the first round.

1. `rec["wall_s"]` is now recorded per round, at the call site in `run()`
   rather than inside `one_round` (which has six early returns). Nothing
   reads it back; it is the table above.
2. `measure_holdout` no longer skips the measurement when no round was
   accepted. It measures the **baseline as the run's null arm** instead,
   with `"null_arm": true` in `holdout.json`, because that is the only way
   to obtain the holdout A/A half-width and the MDE for a run that accepted
   nothing --- which is exactly what the Jev run did. The acceptance rule is
   unchanged; the null arm is SPEC.ja.md 7's in-sweep null panel, not a
   candidate.

**Deviations, and what is not established.**

* **No oracle arm.** Decision 65 (f) puts it third; it is 267 builds and
  about 20 h and has not been run, so "Jev ÷ oracle" in SPEC.ja.md 2 is
  still TBD and nothing here bounds how much was on the table.
* **Jev never proposed anything, so this experiment did not test whether
  Jev's hints make jaq faster.** It tested that the loop runs, that the
  plan applies, and what Jev says when asked --- and Jev said
  `KEEP_DEFAULT` 107 times out of 107. One run, one state format, one
  vocabulary, one target.
* **Three of ten requests failed with HTTP 503** and their 48 questions were
  resolved by the fallback rule, not by Jev. The answered subset was
  unanimous in the same direction, so no plan changed, but the arm is not a
  clean 155-for-155 sample of Jev's judgement.
* **The `__build__` question was never asked** (`build_knobs = []`), so the
  compiler-setting row of SPEC.ja.md 1 (2) is untested in both arms.
* **The Jev run's round binaries were deleted** by `--keep-binaries best`
  (the default) because no round was accepted. The code-identity check of
  section 96 is a *rebuild* of round 1's empty plan with the same recipe,
  not the binary that was timed.
* **`jev_totals["requests"]` counts `ask()` calls, not HTTP attempts**
  (10 vs 24), and `latency_ms` sums only the attempt that returned. The
  per-line `failed_attempts` field in the `.jsonl` carries the rest.
* **Random's round 5 asked about 14 sites, not 16.** The two runs are not
  matched question-for-question in that round, by construction (decision
  61 b).
* **Random round 4's in-run A/A half-width is 0.0719, ten times every other
  round's** (0.0050–0.0090), while the same round's candidate interval is
  the usual width. It is not a band shift: in that round's `samples.json`
  every label/workload pair has one or more repetitions 1.4–2.4× its own
  median, and they fall in a contiguous block of bench rounds (indices 0–5)
  that hit all three labels. Random round 3 has the same shape at indices
  11–14; the Jev rounds have none above 1.15× their median. `trim_rule =
  "none"` is frozen, so nothing was trimmed and the bursts are inside every
  number above. What caused them is not established --- the machine is WSL2
  with no governor control (SPEC.ja.md 3) --- and the shuffle is what spreads
  such a burst over labels unevenly, which is how a round's A/A ends up ten
  times wider than its neighbours'.
* **No claim is made about the direction of either holdout result.** Both
  are inside the 3% MDE, and the Jev run's own null arm moved 2.1 pp on the
  same case set.

## Hint benchmark (design) --- one kernel per hint, ground truth before the sweep

`targets/hintbench` is a target written for one purpose: to make ground truth
cheap. For each hint in the frozen vocabulary of SPEC.ja.md 1(2) there is one
kernel, shaped so that that hint has a mechanism and the others do not, and
`targets/hintbench/EXPECTED.md` records the mechanism and the predicted winner
**before any timing run**. A one-factor oracle sweep over the kernels then says
which predictions were right, which is what decision 69's metric (Jev's answer
against Claude's judgement) and decision 71's open question (whether Claude's
judgement is any good) both need.

Nothing in this section is a timing measurement. Every number comes from
remarks, symbol tables, disassembly, LLVM bitcode or the plugin's dump. Five
builds were made: the PGO baseline, the `JEV_MODE=dump` build, the
`JEV_MODE=apply` smoke build, and two diagnostics.

### 103. The target

```
targets/hintbench/Cargo.toml              workspace + [profile.release]
targets/hintbench/hbkernels/src/lib.rs    the eight kernels (rlib)
targets/hintbench/hintbench/src/main.rs   the drivers and the workload driver
targets/hintbench/jev-marks.txt           eight marks, one per kernel
targets/hintbench/EXPECTED.md             the prediction, frozen before timing
scripts/hintbench_oracle.sh               dump / sites / arms / smoke / run
```

Same two-crate shape as `targets/toy`, same rules: no `#[inline]`, no
`#[inline(never)]`, no `#[cold]`, no `#[repr(align)]`, no intrinsics,
deterministic xorshift inputs from a fixed seed, one checksum line per
workload, no timing code in the binary, an `all` workload, `REP_*` per
workload. `[profile.release]` is `opt-level = 3`, `lto = "fat"`,
`codegen-units = 1`, `debug = 1`, `panic = "unwind"`.

One workload per kernel, because the readout is per kernel: the ground truth
for kernel N is the ratio on workload kN. In an eight-way geometric mean a 10%
win on one kernel is 1.2%, below the 3% floor of decision 16.

Wall time of each workload, PGO baseline binary, `taskset -c 8`, one run
(calibration, not a measurement):

```
k1 347 ms   k2 349 ms   k3 365 ms   k4 345 ms
k5 328 ms   k6 365 ms   k7 351 ms   k8 338 ms      all 2637 ms
```

`scripts/target_common.sh` gained a `hintbench)` branch and
`scripts/target_pgo_baseline.sh` a `hintbench)` arm in `run_training`. Like the
toy, hintbench declares no `TRAIN_WORKLOADS`: the kernels are their own inputs,
so `jev_search.py --bench-set training` falls back and records
`holdout-as-search`.

### 104. Two build-recipe changes the target forced

**`-Zcross-crate-inline-threshold=never` in `FIXED_RUSTFLAGS`.** rustc's own
MIR inliner runs long before the plugin sees anything, and a callee it deletes
has no LLVM function for a function attribute to attach to. Measured: without
the flag, six of the eight kernels are gone before LLVM and only `k1_step` and
`k6_hot_loop` survive as symbols. With it, all eight are in the IR and all
eight marks resolve to a function. The flag changes no LLVM decision --- LLVM
still inlines whatever its cost model likes --- it only stops the frontend from
pre-empting the decision under test. It is on the baseline and on every arm.

**`FIXED_RUSTFLAGS` added to `build_instrumented` in
`scripts/target_pgo_baseline.sh`.** `-Cprofile-use` matches a profile record to
a function by a hash of the frontend's MIR, so a flag that changes what the
frontend emits has to be in the instrumented build too. Leaving it off
discarded the whole of `main`'s profile ("function control flow change detected
(hash mismatch)") and left five of the eight kernels with "no profile data
available for function". With the flag in both builds: zero warnings of either
kind. For the targets whose fixed flags are only `-Cllvm-args` this changes
nothing, and their profdata is reused (`REUSE_PROFDATA=1`) in any case.

### 105. The eight kernels and what the baseline does with them

| kernel | mark | hint under test | baseline, measured |
|---|---|---|---|
| K1 | `k1_step` | `inline(never)` | inlined at all 8 call sites (`cost=640, threshold=787`) |
| K2 | `k2_mix` | `inline` | not inlined (`cost=870, threshold=787`), 2 call sites |
| K3 | `k3_fill_run` | `unroll.disable` | not vectorized; runtime unroll by 8, trip 11.5 |
| K4 | `k4_count_bytes` | `vectorize.width=16` | VF 8, IC 4 |
| K5 | `k5_mul_reduce` | `interleave.count=4` | VF 8, IC 4 |
| K6 | `k6_hot_loop` | `align=64` | not inlined (`cost=715, threshold=525`); entry mod 64 = 16 |
| K7 | `k7_error_path` | `cold` | inlined at both call sites (`cost=135, threshold=787`) |
| K8 | `k8_scale_add` | control | VF 8, IC 4 |

Three constraints shaped every one of them, and all three are properties of the
**PGO** baseline rather than of `-O3`:

* a call site the profile summary calls hot gets inline threshold 3000, so a
  callee under roughly 600 instructions is inlined there whatever else is true.
  K1's first draft (64 rounds, cost 1900) was built assuming this applied; it
  does not, because K1's loop runs a few million times against K5's 1.6e10 and
  is therefore *not* hot. The draft was left out of line by the baseline and
  `inline(never)` was a no-op. At 22 rounds and eight call sites the baseline
  inlines it and the hint has something to remove.
* a function with one call site and internal linkage --- which every function
  here becomes after fat-LTO internalisation --- gets the "last call to static"
  bonus (−15000) and is inlined regardless of size. Every kernel whose hint is
  a function attribute therefore has two or more call sites.
* PGO adds `inlinehint` to a function whose entry count is hot by itself. The
  dump's function table shows it on `k3_fill_run`. This is decision 70's
  "251-instruction hot leaf already `inlinehint`" reproduced on demand.

K3's default unrolling is worth spelling out, because it is the zopfli
`cache.rs:108` case (decision 22) with the disassembly attached: the trip count
is unknown, so the unrolled body keeps a `cmp`/`je` pair after *every* one of
its eight stores and gains an `and $0x7` / `xor $0x4` prologue and a remainder
loop. The unrolling removes no branches at all.

### 106. The main result: `inline` and `cold` are consumed and do nothing

One `JEV_MODE=apply` build carrying one hint per kernel. Every plan entry is
reported `consumed` (four functions) or `attached` (four loops), nothing
`vanished` or `ambiguous`, and the eight checksums are unchanged:

```
   lto       5acd6025657bd898-next-macros.rs-180        attached   vectorize.width=16
   lto       9e9ba3f36ca98757-spec_next-range.rs-1103   attached   unroll.count=2
   lto       ac9e5da87f238a0d-k3_fill_run-lib.rs-174    attached   unroll.disable
   lto       fc420a4f49bcc12e-next-macros.rs-180        attached   interleave.count=4
   prelink   hbkernels::k1_step                         consumed   noinline
   prelink   hbkernels::k2_mix                          consumed   inlinehint
   prelink   hbkernels::k6_hot_loop                     consumed   align=64
   prelink   hbkernels::k7_error_path                   consumed   cold
   totals: attached=4, consumed=4
   CHECKSUMS: MATCH
```

*Consumed is not effective.* Of the four function attributes, two change the
generated code and two do not:

| hint | in the LTO bitcode | effect |
|---|---|---|
| `inline(never)` on `k1_step` | `noinline` | 8 call sites become "should never be inlined"; the symbol survives |
| `align=64` on `k6_hot_loop` | `align 64` on the `define` | entry `0x11e10` (mod 64 = 16) becomes `0xeb00` (mod 64 = 0), and the loop header with it |
| `inline` on `k2_mix` | `inlinehint` present | none: remark unchanged at `cost=870, threshold=787` |
| `cold` on `k7_error_path` | `cold` present | none: remark unchanged at `cost=135, threshold=787`, still inlined at both sites |

The bitcode column is `llvm-dis` on `*.rcgu.lto.after-restriction.bc`, the
fat-LTO module *after* internalisation and *before* the LTO optimisation
pipeline (produced with `-Csave-temps`). All four attributes are in that one
module, side by side:

```
define internal ... @..k6_hot_loop #99 align 64 ...
attributes #99  = { inlinehint nonlazybind uwtable ... }        <- PGO's own, on k6's caller chain
attributes #101 = { cold mustprogress nofree norecurse ... }    <- k7_error_path
attributes #102 = { inlinehint mustprogress nofree ... }        <- k2_mix
attributes #103 = { mustprogress nofree noinline norecurse ... } <- k1_step
```

So `noinline` and `align 64` are honoured and `cold` and `inlinehint` are not,
from the same module, in the same build. **Why is not established**, and the
two obvious explanations are both ruled out by the evidence here:

* "`inline` is `max(Threshold, 325)` and every threshold here is 525 or 787, so
  the max never selects 325" would be a complete explanation --- except that a
  control build with `-Cllvm-args=-inlinehint-threshold=5000` also leaves
  `k2_mix` at `threshold=787`. If the attribute were being read at all, that
  control had to move it. It did not.
* "`cold` is overridden by the profile summary, which decides call-site
  coldness for itself" would explain K7 --- except that the callee's `cold`
  attribute also drives `Params.ColdThreshold` (45), which would have shown up
  as `threshold=45` and would have cancelled the −14865 last-call bonus.
  Neither happened; the remark is byte for byte the baseline's.

What is established is narrower and still useful: **the two attributes are in
the module the LTO pipeline starts from, and the inliner behaves as though they
are absent.** Either a pass inside that pipeline removes them before the CGSCC
inliner runs, or the inliner does not consult them in this configuration. The
next build that would settle it is one that dumps the module immediately before
the inliner; `-Csave-temps` does not emit a post-optimisation LTO artifact, so
that needs a different mechanism than the one used here.

The scope of the finding is likewise narrower than it first looks. It is
measured on hintbench, on this recipe. Whether it holds on jaq is **one
`JEV_MODE=apply` build away and has not been done**: apply `inline` to one jaq
mark and `cold` to another and read the inline remarks. Until that runs, "two
of the four function-attribute hints in SPEC.ja.md 1(2) are inert" is a
statement about this target only --- but it is worth running, because `inline`
is the hint Jev reached for most often in the prompt study (decision 70), and
because the oracle can confirm it here for free: the K2 `inline` and K7 `cold`
arms should come out code-identical to the baseline and land in the in-sweep
null panel of decision 31. That check is the oracle's per-arm normalised-code
comparison, not this smoke build, which applied all eight hints at once.

### 107. Two kernels LLVM already gets right

**K4, `vectorize.width`.** The kernel is jaq's `to_ascii_lowercase` shape ---
the site where decision 70 recorded Claude choosing `vectorize.width=16` and
Jev never choosing it --- with a u32 accumulator so that decision 12's i64 trap
does not apply. The baseline is already VF 8 x IC 4: `vpcmpeqb %xmm` /
`vpmovzxbd %xmm,%ymm` / `vpaddd %ymm` over four accumulators, 32 bytes per
iteration. A forced width of 16 cannot add bandwidth, only trade lanes against
interleaving. Expected winner revised to `KEEP_DEFAULT`.

**K5, `interleave.count`.** A multiplicative reduction, so the `vpmulld`
dependency chain is the limit and the number of chains is the whole story. The
baseline already picks IC 4. That is not an accident: LoopVectorize returns the
*maximum* interleave count for any vectorised loop carrying a reduction and
does not apply the small-loop-cost cap to it, so a vectorised integer reduction
on this hardware is always interleaved to the register budget. A draft with six
chained multiplies per element --- enough loop cost to trip the cap --- still
came out IC 4. Expected winner revised to `KEEP_DEFAULT`, and K5 becomes the
benchmark's calibration site instead: `interleave.count=1` should cost 50--75%
of the workload, and a sweep that cannot see that cannot see anything.

Together with section 106 this leaves three kernels with a live mechanism (K1
`inline(never)`, K3 `unroll.disable`, K6 `align=64`), K7 redirected from `cold`
to `inline(never)`, and four sites whose expected answer is "leave it alone".
That is a weaker benchmark than intended and a more honest one: the ratio of
live to dead hints is itself a result, and it is consistent with decisions 12,
22, 29, 31 and 37, where the vectoriser knobs never moved a real target and the
only things that did were unrolling and alignment.

### 108. Sites and the oracle's arm count

`scripts/hintbench_oracle.sh dump` builds the baseline with `JEV_MODE=dump`.
The plugin only reads, and the check holds: normalised whole-code hash
`75912ec78622dd1a` on both the plain PGO baseline and the dump build,
`IDENTICAL`, 373 symbols, 0 changed.

All 8 marks resolve to a function. The dump finds 6 `loop_in_mark` keys:

| key | mark | trip | hotness | leaf | frozen set |
|---|---|---|---|---|---|
| `ac9e5da8...-k3_fill_run-lib.rs-174` | k3 | 11.48 | 7.21e9 | `lib.rs:174` | yes |
| `56d14f7e...-k3_fill_run-lib.rs-173` | k3 | 4096.14 | 2.05e9 | `lib.rs:173` | no |
| `5acd6025...-next-macros.rs-180` | k4 | 16384.12 | 5.46e10 | `macros.rs:180` | yes |
| `fc420a4f...-next-macros.rs-180` | k5 | 4096.01 | 8.70e10 | `macros.rs:180` | yes |
| `9e9ba3f3...-spec_next-range.rs-1103` | k8 | 4096.01 | 3.16e10 | `range.rs:1103` | yes |
| `270c014b...-next-macros.rs-180` | k6 | 4096.00 | 6.55e9 | `macros.rs:180` | no |

The frozen rule, pre-registered in `scripts/hintbench_oracle.sh`: keep the
marks whose hint under test is a loop hint (k3, k4, k5, k8), and within a mark
keep the single hottest key. The second part matters for k3, which produces two
keys --- the fill loop itself and the *driver's* loop over the run table, whose
trip count is the driver's 4096 and which is attributed `loop_in_mark` because
the debug location of its latch comes from the inlined callee. The same
`loop_in_mark` fuzziness decision 61 found on the toy, reproduced on a two-loop
nest of known shape. Dropping k6's loop is what keeps the total at 12.

```
$ scripts/hintbench_oracle.sh arms
[sites] sites.json caps the loop sweep at 4 of 6 sites
[oracle] phase all: 92 one-factor arms + 1 combination arm (+1 baseline build already done)
```

**12 sites = 8 functions x 6 candidates + 4 loops x 11 candidates = 92
one-factor arms + 1 combination = 93 arms.** Cost per arm on this machine: a
clean build is about 25 s, and an interleaved pair of labels over eight
workloads at `repetitions = 15`, `warmup = 3` is about 2 x 18 x 8 x 0.35 s =
100 s. So roughly 2 minutes per arm and **three to three and a half hours for
the sweep**, plus the A/A. `scripts/hintbench_oracle.sh run` is the command;
it has not been run.

### 109. What is not done, and what to watch

* **No timing of any kind has been run on this target.** The oracle sweep is
  the next step and it is the only thing that can turn EXPECTED.md into a
  score.
* **K2 and K7 are kept although their hint is inert.** They are the
  demonstration sites for section 106, and their arms are the target's own null
  panel. If either of them moves in the sweep, section 106 is wrong.
* **K6's sign is not predicted.** The hint does what it says (entry 16 -> 0 mod
  64) but an 80-byte loop body spans two cache lines either way.
* **The `hintbench` PGO profile is not reproducible across a source change to
  the kernels**, by construction: every `REP_*` change rewrites the counters.
  `merged.profdata` was regenerated three times while the kernels were being
  tuned and must be regenerated after any further edit; the recorded `.text`
  sha256 of the frozen baseline is
  `df5968bc018b17ad9a3d1f236e1ac8f6c9995d76bc296f0c8c67fda9c9f1fe7a`.

## Oracle A (jaq): function attributes

The first half of the oracle of SPEC.ja.md 2 and decision 65 (f): every
function-attribute candidate, alone, at every marked function, with every
other site at `KEEP_DEFAULT`. The loop half (176 arms) has **not** been run.
This section is what the Jev and random arms of "Experiment 3 (jaq)" are to
be divided by, and --- because 48 of its 90 arms turn out to be builds that
changed nothing --- it is also the largest null panel this project has
measured.

### 110. What was run

```
scripts/bench_panel.sh artifacts/jaq-search/oracle-A-nullpanel 15 3 20260921 \
    n0=<baseline> n1=<baseline> n2=<baseline> n3=<baseline>   # TARGET=jaq BENCH_SET=training

scripts/jev_search.py --target jaq --marks targets/jaq/jev-marks.txt \
    --sites targets/jaq/sites.json --site-set oracle.selected_keys_top3 \
    --proposer oracle --oracle-phase A --keep-binaries all \
    --baseline-dir artifacts/jaq-search/jev-r5/baseline \
    --out artifacts/jaq-search/oracle-A/

scripts/bench_panel.sh artifacts/jaq-search/oracle-A-holdout 15 3 20260921 \
    base=<baseline> comb=round-91/bin best1f=round-27/bin aa=<baseline>
```

**15 marks x 6 candidates (`inline`, `inline_never`, `cold`, `align_16`,
`align_32`, `align_64`) = 90 one-factor arms, then one combination arm.**
Each arm is a full two-phase round: the attribute is applied at
PipelineStartEP under `JEV_MODE=apply-dump`, the loops of the resulting IR
are dumped, all 16 loop sites answer `KEEP_DEFAULT`, and the measured binary
comes from the `JEV_MODE=apply` build --- the same round structure, the same
frozen values and the same **baseline binary** (`e183c81d…`) as both
Experiment 3 runs, so the three proposers remain comparable: `repetitions =
15`, `warmup = 3`, shuffle from `seed = 20260921` + the round number,
`--gap-ms 250`, `taskset -c 4`, bootstrap 10000, training cases, vocabulary
`v1-2026-09-22`, `merged.profdata` `4e879ce1…`, plugin `be74c857…`,
`jev-opt.toml` `a8029ac1…`, `jev-marks.txt` `40ef24cc…`.

**Two changes to the driver and one new script, none of them touching the
acceptance rule, the vocabulary, the state format or the site set**, all
made before arm 1:

1. `--oracle-phase A|B|all` restricts the oracle's *arm list* to one phase.
   It changes nothing about an arm --- a phase-A round still builds both
   phases --- and exists because the two halves are 90 and 176 builds and
   this machine runs one of them at a time.
2. The combination arm now takes a mark's best candidate only when **that
   arm's own 95% CI lower bound is above 1**, not merely its point estimate.
   The point-estimate rule the code carried before would have combined all
   15 marks; the recorded arm says which (`point_rule_would_pick`).
3. `scripts/bench_panel.sh` (new) times N already-built binaries in one
   interleaved batch under the target's frozen conditions. It is how the
   4-binary null panel and the single holdout batch below were measured;
   `measure()` inside the driver takes exactly three labels and was left
   alone so that every arm's batch is shaped exactly like Experiment 3's.

**Which code ran.** The driver process loaded its modules at 08:36 and kept
them for all 91 rounds, so this run executed `scripts/jev_search.py` and
`scripts/jev_vocab.py` as of commit `346b605` plus the three changes above.
The vocabulary v2 and v3 work landed on the same day at 10:12 (`ac94c8a`,
which also carried the two driver changes above into git) and 11:01 (`7fe1a92`),
while the sweep was in its 20th and 30th arm; both are opt-in behind
`--vocab` and neither reached this process. The run's manifest records
`v1-2026-09-22` for both the vocabulary and the state format, and the six
candidates swept are v1's. **Nothing in this section is a measurement of
vocabulary v2 or v3.**

### 111. The null panel: four identical binaries, before the sweep

Four stripped copies of the one baseline binary (`83f7eb23…` after
stripping, all four the same file), one batch, training cases, n=15:

| label | aggregate ratio | 95% CI | half-width |
|---|--:|---|--:|
| n0 (base) | 1.0000 | --- | --- |
| n1 | 0.9923 | [0.9834, 1.0015] | 0.91% |
| n2 | 0.9961 | [0.9874, 1.0045] | 0.85% |
| n3 | 0.9998 | [0.9942, 1.0059] | 0.58% |

**Spread max - min = 0.77 points** between byte-identical binaries; no
interval excludes 1; worst per-workload half-width 1.60%, so `bench.py`'s
MDE for that batch is 3.20% and the pre-registered MDE stays 3.00%. On the
holdout set the same construction had spread 2.1 points ("Experiment 3
(jaq)" 99). One batch of four is a weak estimate of the spread; the 90
batches of the sweep below are a much better one, and they are worse.

### 112. The 90 arms

Full table: `docs/experiments/jaq-oracle-A/arms.md` (mark, candidate, apply
outcome counts, correctness, ratio, CI, whether the CI excludes 1, changed
symbols, profile share held by them, and what the build actually differs in).

* **Correctness held in 90 of 90** (and in the combination arm): every
  build's `run_correctness` output matched the baseline's line for line.
* **Every plan entry took effect in 90 of 90**: all `consumed`, no
  `unmatched`, `vanished` or `skipped_empty`, no `ambiguous` (an ambiguous
  key is a loop phenomenon and this half hinted no loops). The outcome is
  `consumed` for every entry of every arm, including the 48 arms whose build
  changed nothing: the plugin has no `skipped_idempotent` verdict for a
  function attribute --- it sets the attribute and says so, and whether LLVM
  then did anything with it is not visible in the apply report. **The no-op
  count of 113 comes from the binaries, not from the report.**
* **Fan-out**: one Choice becomes 1 to 62 plan entries. The 138 entries a
  full phase-A plan carries are spread very unevenly --- `TermId::run` alone
  fans out to 62 --- and **103 of those 138 are closures of a generic mark**
  (`read::parse::<SliceLexer>::{closure#0}` and friends). The driver's rule
  "the attribute goes on the mark, not on the items defined inside it"
  (decision 65 b) looks only at the character after the mark, so it excludes
  `write::write::{closure#0}` but *not* `read::parse::<T>::{closure#0}`:
  for a **generic** mark the closures are treated as monomorphizations and
  get the attribute. This is pre-existing behaviour, identical in the Jev and
  random runs (both fanned out to the same 138 entries), so it was left
  alone; it is a limit on what "`inline(never)` on `TermId::run`" means, not
  a difference between the arms.
* Distribution: `cold` has the best mean of the six candidates (1.0045) and
  `inline_never` the worst (0.9932), but see 113 before reading anything
  into that.

| candidate | n | mean ratio | min | max |
|---|--:|--:|--:|--:|
| inline | 15 | 0.9975 | 0.9834 | 1.0074 |
| inline_never | 15 | 0.9932 | 0.9482 | 1.0134 |
| cold | 15 | 1.0045 | 0.9698 | 1.0323 |
| align_16 | 15 | 0.9977 | 0.9834 | 1.0140 |
| align_32 | 15 | 1.0020 | 0.9873 | 1.0229 |
| align_64 | 15 | 1.0027 | 0.9741 | 1.0154 |

**Only one arm of 90 exceeds +3%** --- `TermId::run cold`, 1.0323
[1.0249, 1.0401] --- and **three fall below -3%**: `Lex::seq inline_never`
0.9482, `write_until inline_never` 0.9575, `write::write cold` 0.9698. Those
three are the only arms whose sign is also supported by the code: all three
are among the 23 arms that changed instructions, and what they changed is
hot --- `Lex::seq inline_never` 14 symbols holding 28.77% of the profile,
`write_until inline_never` 4 symbols holding 37.71%, `write::write cold` 12
symbols holding 8.55%.

Per mark, the best of its six candidates:

| mark | best candidate | ratio | 95% CI | CI excludes 1 | worst candidate | ratio |
|---|---|--:|---|---|---|--:|
| read::parse | align_64 | 1.0154 | [1.0066, 1.0235] | yes (+) | align_16 | 0.9902 |
| Lex::seq | inline | 1.0002 | [0.9935, 1.0067] | no | inline_never | 0.9482 |
| str_fold | cold | 1.0155 | [1.0058, 1.0259] | yes (+) | align_64 | 0.9852 |
| write_until | cold | 1.0198 | [1.0135, 1.0256] | yes (+) | inline_never | 0.9575 |
| TermId::run | cold | 1.0323 | [1.0249, 1.0401] | yes (+) | align_16 | 0.9933 |
| write::write | align_16 | 1.0130 | [1.0059, 1.0197] | yes (+) | cold | 0.9698 |
| funs::base{closure#3} | align_32 | 1.0130 | [1.0056, 1.0210] | yes (+) | inline | 0.9861 |
| Path::run{closure#0} | align_64 | 1.0139 | [1.0070, 1.0211] | yes (+) | align_16 | 0.9834 |
| Adapter::write_str | cold | 1.0099 | [1.0052, 1.0144] | yes (+) | align_32 | 0.9873 |
| reserve_rehash | cold | 1.0209 | [1.0137, 1.0281] | yes (+) | align_16 | 0.9899 |
| Rc<IndexMap>::drop_slow | cold | 1.0138 | [1.0086, 1.0189] | yes (+) | inline | 0.9920 |
| base_run{closure#7} | align_32 | 1.0229 | [1.0173, 1.0286] | yes (+) | inline | 0.9834 |
| path::run | inline | 1.0070 | [0.9996, 1.0146] | no | inline_never | 0.9826 |
| Val::hash | inline_never | 1.0072 | [0.9997, 1.0148] | no | align_16 | 0.9903 |
| String::fmt | align_16 | 1.0140 | [1.0067, 1.0241] | yes (+) | inline | 0.9898 |

`cold` --- the attribute whose own description in the vocabulary says it is
"a pessimisation on a hot function" --- is the best candidate for six of the
fifteen hottest functions in the program. That is the first sign that this
table is mostly not about code.

### 113. 48 of the 90 arms are builds that changed nothing

`scripts/norm_code_diff.py` normalises addresses away, so it answers "did any
instruction change" and is blind to an alignment that only moves code. Adding
a symbol-table comparison (`nm -S`, addresses **and** sizes, against the
baseline's) splits the 90 arms three ways:

| what the build differs in | arms | ratio range |
|---|--:|---|
| nothing: same instructions, same symbol table | **48** | 0.9741 -- 1.0209 |
| only where the code sits (alignment moved symbols) | 19 | 0.9873 -- 1.0229 |
| instructions changed | 23 | 0.9482 -- 1.0323 |

By candidate: **all 15 `align_16` arms are no-ops** (x86-64 already aligns
functions to 16, which is what the vocabulary's description of `align_16`
says), and so are 10 of 15 `inline`, 9 of 15 `cold` and 6 of 15
`inline_never` arms --- LLVM had already decided, and saying it again changed
no code.

This is the prediction of section 106 and
`docs/experiments/hintbench/inline-attrs-under-pgo.md`, measured on a real
program. That work found on a purpose-built benchmark that `inlinehint` and
`cold` are consumed and change nothing under `-O3` + PGO + fat LTO, while
`noinline` and `align 64` are honoured, and predicted that such arms
"should come out code-identical to the baseline and land in the in-sweep
null panel". On jaq, 19 of the 30 `inline`/`cold` arms did exactly that.
The 11 that did change code are not all explained away by the fan-out to
closures and to monomorphizations the profile never entered: **`cold` on
`write::write` is a clean counterexample.** That mark resolves to exactly
one linkage name and no fan-out at all, and the arm changed 12 symbols
holding 8.55% of the profile and lost 3.0% (0.9698 [0.9624, 0.9771]). On a
single hot profiled function with no closures, `cold` is not inert on jaq.

**Those 48 no-op builds are an in-sweep null panel of 48 measurements, and
20 of them have a 95% CI that excludes 1.0.** Their ratios run from 0.9741 to
1.0209, a spread of 4.67 points. The two highest are
`reserve_rehash cold` 1.0209 [1.0137, 1.0281] and `write_until cold` 1.0198
[1.0135, 1.0256]: a 2% "speedup", with an interval that excludes 1, from a
binary whose every instruction and every symbol address is the baseline's.

The in-run A/A says the same thing from the other side. Over the 90 rounds
the A/A label --- a second copy of the baseline, timed in the same batch as
the candidate --- ran from **0.9721 to 1.0256 (5.35 points), sd 1.09%, and
41 of the 90 A/A intervals exclude 1.0**, against 42 of 90 for the
candidates (22 up, 20 down). There is no drift: the mean A/A of arms 1--45
and of arms 46--90 are 1.0010 and 1.0009. The median in-batch A/A half-width
is 0.73%, so **the within-batch interval is roughly three times too narrow
for the between-batch scatter it is embedded in.**

### 114. The combination arm, on training and on holdout

Twelve of the fifteen marks had a best arm whose CI lower bound was above 1,
so the combination arm is those twelve attributes at once (`read::parse`
align_64, `str_fold` cold, `write_until` cold, `TermId::run` cold,
`write::write` align_16, `funs::base{closure#3}` align_32,
`Path::run{closure#0}` align_64, `Adapter::write_str` cold,
`reserve_rehash` cold, `Rc<IndexMap>::drop_slow` cold, `base_run{closure#7}`
align_32, `String::fmt` align_16). The point-estimate rule would have added
`Lex::seq`, `path::run` and `Val::hash`. The plan is
`docs/experiments/jaq-oracle-A/combination-plan.json`; it applied cleanly
(106 entries --- the twelve marks' fan-out --- all `consumed`) and its output
matched the baseline's.

**Training: 1.0215 [1.0128, 1.0300] --- with an in-run A/A of 1.0226
[1.0135, 1.0309] in the same batch.** The identical-binary control moved
further than the candidate.

If the twelve chosen effects were real and independent, their product would
be **+22.4%**. The combination delivered +2.15%, which is what one expects
when the twelve numbers are draws from the noise of 113 rather than effects.

Holdout, one batch, four labels (SPEC.ja.md 7: measured once, after the arms
were frozen), n=15, warmup 3, `taskset -c 4`, gap 250 ms:

| label | aggregate ratio | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | --- | --- |
| comb (the combination arm) | **1.0036** | [0.9968, 1.0107] | 0.70% |
| best1f (`TermId::run cold`, the best of the 90) | **0.9909** | [0.9584, 1.0119] | 2.67% |
| aa (a second copy of the baseline) | 0.9979 | [0.9734, 1.0143] | 2.04% |

The pre-registered MDE for this batch is `max(2 x 2.04%, 3%) = 4.08%`;
`bench.py`'s worst-per-workload version is 11.37%, inflated by one A/A
readwrite outlier (half-width 5.68% on a label that is the baseline). Nothing
here is within reach of either.

### 115. What the oracle says, plainly

* **The best function-attribute oracle on the training set is
  `TermId::run cold` at 1.0323 [1.0249, 1.0401], and the combination arm is
  1.0215 [1.0128, 1.0300].** Under the pre-registered acceptance rule three
  arms were ever accepted (5, 21, 27) and the run's frozen best is arm 27.
* **On the holdout set neither survives: the combination is 1.0036
  [0.9968, 1.0107] and the best arm is 0.9909 [0.9584, 1.0119], a sign
  reversal.** The same reversal the random arm showed in Experiment 3.
* **Nothing clears the MDE.** One arm of 90 exceeds +3% on training, its own
  batch's A/A being +2.6% at the same time; on holdout nothing exceeds 3%,
  let alone the 4.08% this batch's A/A implies. **No function attribute on
  any of jaq's fifteen marked functions makes jaq measurably faster, and the
  oracle's own best is inside its own noise.**
* Therefore **Jev's 107 `KEEP_DEFAULT` answers are not refuted by the
  function-attribute half of the oracle** (decision 66's open question). The
  oracle found nothing here to have missed. What the oracle *did* find is
  three ways to lose 3--5%, all of them `inline_never`/`cold` on the read
  path, which is the sort of damage a proposer that likes to try things would
  have to survive.
* **The `Jev / oracle` ratio of SPEC.ja.md 2 is not computable from a
  denominator that is indistinguishable from zero.** It waits on the loop
  half.

### 116. Wall clock, cost, and what this changes about the protocol

```
null panel (4 labels, training)                         ~4 min
90 one-factor arms + 1 combination arm, 292 s each      7 h 23 min  (08:36-15:54 JST)
holdout batch (4 labels)                                ~5 min
norm_code_diff over 91 binaries + symbol tables         ~30 min
```

Total about **8 hours**, 0 API calls, $0. Per arm: two clean builds (~85 s
each), correctness (~10 s), and a 3-label batch of 135 timed runs (~120 s).
Disk: 12 GB of kept binaries and build logs under `artifacts/` (git-ignored).

Two things this measurement says about the protocol, neither of which was
applied to this run (the conditions were frozen before arm 1):

1. **The in-batch bootstrap CI is miscalibrated, not merely offset.** A 95%
   interval around an identical binary should cover 1.0 about 95 times in
   100; over the 90 rounds the A/A interval covered it **49 times in 90**,
   and 20 of the 48 provably no-op builds also excluded 1.0. Acceptance
   rule 3 --- "the lower end of the 95% CI is above the best point estimate
   so far" --- is therefore satisfiable by noise at this n, which is how arms
   5, 21 and 27 were accepted here and random round 3 was accepted in
   Experiment 3.
   The obvious repair does **not** work: dividing a candidate by its own
   batch's A/A would have made arms 5 and 21 look *better*, not worse
   (1.0113/0.9858 = 1.0258 and 1.0198/0.9944 = 1.0255), because the three
   labels of one batch scatter independently by one to two points rather
   than sharing a batch-level shift. Only arm 27 had an A/A that moved with
   it (1.0323 against 1.0256). There is no rescaling of a single batch that
   fixes this.
2. **Between-batch variance dominates within-batch variance** by about 3x on
   jaq (in-batch A/A half-width 0.73% median; between-batch A/A sd 1.09%,
   range 5.35 points). Raising `repetitions` inside one batch buys almost
   nothing; what would buy something is repeating the *batch* --- the same
   pair of binaries measured in k independent batches --- and treating the
   between-batch scatter as the error bar. That is a change to SPEC.ja.md 2's
   noise definition and is not made here.

### 117. Deviations, and what is not established

* **The loop half of the oracle (176 arms, ~14 h) has not been run.** Until
  it is, "the oracle" in SPEC.ja.md 2 is only its function-attribute half.
* The combination arm follows decision 65's construction but with the
  CI-lower-bound filter of 110 (2); SPEC.ja.md 2 says only "the best of each
  site", and with the point-estimate filter the arm would have carried 15
  attributes rather than 12. That arm was not built.
* **`align_16` is a no-op on all 15 marks**, so a sixth of the sweep measured
  the baseline. It was kept because the candidate list is frozen and because
  those 15 measurements are exactly the null panel 113 leans on.
* The function-attribute fan-out reaches the closures of a generic mark
  (112); `--fn-attr-scope` was left at `own`, as in Experiment 3.
* The holdout batch carries four labels rather than three so that the
  combination arm and the best one-factor arm are measured in **one** batch
  (SPEC.ja.md 7's "measured once"). Its A/A label had a readwrite outlier;
  the batch was not repeated, and no arm was re-measured to get a better
  number.
* Nothing here says anything about the loop hints, about other targets, or
  about attributes on functions that are not one of these fifteen marks.

## Hint benchmark (oracle) --- the sweep that turns EXPECTED.md into a score

The one-factor sweep of SPEC.ja.md 2 over `targets/hintbench`: every
candidate of vocabulary v3, alone, at each of the twelve sites, with every
other site at `KEEP_DEFAULT`, plus one combination arm. **84 one-factor arms
plus the combination, 16:39--20:28 JST on 2026-09-22, no API calls.**

It is the measurement decision 72 ordered the project around: a target where
a correct answer exists, a prediction frozen before the timing
(`targets/hintbench/EXPECTED.md`), and an oracle that says which predictions
were right. Full per-arm tables, the scorecard under both readings and the
raw numbers are in `docs/experiments/hintbench/oracle.md`; this section is
what the sweep established.

### 118. Three driver fixes, pre-registered and committed before arm 1

Decision 80's protocol changes, in `scripts/jev_search.py`, commit `a44d8e6`,
made and tested before the first build. None touches the vocabulary, the
state format, the site set or the measurement conditions.

**(a) The closure fan-out (decision 80 c).** `is_inner_item` decided whether
a function is the mark or an item defined inside it by looking at the single
character after the mark. For a **generic** mark that character is the `<` of
the generic arguments, so `read::parse::<SliceLexer>::{closure#0}` passed as
a monomorphization and one Choice about `read::parse` put its attribute on
every closure the function defines. The rule now skips the balanced `::<...>`
group and asks what follows *it*. Measured on the recorded dumps, no build:

| target | plan entries in a full phase-A plan, before | after | removed |
|---|--:|--:|--:|
| hintbench | 8 | 8 | **0** |
| jaq | 138 | **49** | **89** |

hintbench is unaffected --- its eight marks are non-generic and each resolves
to one function --- so this sweep measured what it would have measured
anyway. jaq's four generic marks are where it bites: `TermId::run` 62 -> 2,
`read::parse` 18 -> 6, `path::run` 12 -> 3, `Val::hash` 12 -> 4. Experiment 3
and oracle A both ran with the old reach, against the one shared baseline
dump these numbers are computed from, so **the "`inline(never)` on
`TermId::run`" of section 112 was in fact `noinline` on 62 functions, 60 of
them closures**, and the loop half of jaq's oracle has not been run yet and
will use the fixed reach.

**(b) No-op arms are not timed (decision 80 b).** After the build and the
correctness check every arm's binary is classified against the baseline by
normalised instruction sequence (`norm_code_diff.py`) *and* symbol table
(`nm -S`): `identical` (not timed, ratio 1.0 by construction, `ci95: null`),
`layout` (same instructions, symbols moved --- what `align=N` does when it
works), or `code`. The plugin cannot supply this; it reports `consumed`
whether or not LLVM acted.

**(c) The confirmation batch (decision 80 a).** An arm whose interval
excludes 1 --- on the aggregate or on its own kernel's workload --- is
re-measured in a second independent batch over the same two binaries with a
fresh shuffle seed, and is believed only if both batches exclude 1 with the
same sign. This became a fourth condition of the acceptance rule, and it
replaced the combination arm's selection rule: a site now joins with its best
**confirmed** arm, ranked on the **per-kernel readout** that section 103
froze rather than on the eight-way geometric mean, since a 10% win on one
kernel is 1.2% of that mean. Both weaker rules are recorded beside the chosen
set.

### 119. The null panel, and why hintbench is not jaq

Two independent batches, four stripped copies of the one baseline binary,
under the arms' own conditions.

| label | batch 1 | 95% CI | batch 2 | 95% CI |
|---|--:|---|--:|---|
| n1 | 0.9997 | [0.9976, 1.0018] | 1.0017 | [0.9996, 1.0039] |
| n2 | 0.9998 | [0.9977, 1.0017] | 1.0017 | [0.9996, 1.0041] |
| n3 | 1.0005 | [0.9984, 1.0027] | 1.0018 | [0.9991, 1.0044] |

**Within-batch spread between byte-identical binaries: 0.08 points and 0.01
points. Between batches the same comparison moved 0.17 points.** No interval
in either batch excludes 1. jaq's dedicated panel spread 0.77 points and its
48 in-sweep no-op builds spread 4.67 (section 113).

The sweep says the same from inside. Over its 45 timed arms the in-run A/A
interval excluded 1.0 in **5 of 45** aggregate readings, **12 of 45**
single-workload readings and **5 of 38** confirmation batches --- against
**41 of 90** on jaq. The aggregate interval on this target is close to
honest; the single-workload interval is still about five times too confident,
which is the reason the per-kernel readout needs the confirmation batch more
than the aggregate does.

A consequence worth stating plainly: **the confirmation batch changed nothing
on hintbench.** Not one arm this sweep would have accepted on one batch was
refused by the second, and the combination arm's membership is identical
under the new rule and the old. Decision 80 (a) is a fix for jaq's noise
floor, and hintbench is the control that shows it costs nothing where the
noise floor is already sound.

### 120. 39 of the 84 arms built the baseline

| what the build differs in | arms | of the 40 function arms | of the 44 loop arms |
|---|--:|--:|--:|
| nothing: same instructions, same symbol table | **39** | 28 | 11 |
| only where the code sits | **4** | 4 | 0 |
| instructions changed | **41** | 8 | 33 |

Correctness held in 84 of 84 and in the combination; every plan entry
`consumed` or `attached`, nothing `vanished`, `unmatched` or `ambiguous`.

By candidate: **all 8 `align=16` arms are no-ops**, and so are 6 of 8
`align=32`, 6 of 8 `align=64`, 6 of 8 `inline(always)`, 4 of 4
`interleave.count=4` and 7 of the 11 hints aimed at k3's loop. A skipped arm
costs 9.6 s against 290 s for a measured one, so **the skip removed about
3.1 hours from a 3.8-hour sweep** and removed 39 measurements that could only
have produced noise.

Two of the no-ops are worth their own line, because `consumed` hid the
difference:

* **`inline(always)` on `k1_step` is redundant, not inert.** The build log
  carries eight `always inline attribute at callsite` remarks that the
  baseline's log does not have, so AlwaysInliner *did* act --- and the
  binary is **bit-for-bit the baseline's** (`sha256 07498197…`), because the
  cost-model inliner had already inlined all eight call sites. A different
  pass reached the same code.
* **`align=32` and `align=64` are no-ops on six of the eight kernels
  because there is nothing left to align.** Those six are fully inlined and
  have no out-of-line symbol. On the two that do, the hint works exactly as
  EXPECTED.md 1 K6 documented: `k6_hot_loop` sits at entry mod 64 = 16 in
  the baseline, mod 32 = 0 under `align=32`, and **mod 64 = 0 under
  `align=64`** --- and the clock does not move (1.0008 [0.9981, 1.0039],
  unconfirmed).

### 121. The calibration arm passed, so the scorecard can be read

`docs/experiments/hintbench/oracle.md` 2 fixed, at arm 21 and 28 arms before
the arm itself, what "large" had to mean: below 0.75 the prediction holds,
0.75--0.97 the sweep sees but the mechanism model is wrong, above 0.97 the
scorecard is void.

**K5 `interleave.count=1` measures 0.2957 [0.2943, 0.2978] on k5 and 0.2944
in the confirmation batch** --- a 70.4% loss, inside EXPECTED.md's predicted
−50% to −75% band. `interleave.count=2` came in at 0.5953, almost exactly
half the loss as predicted, and `interleave.count=4` produced a binary
identical to the baseline because IC 4 is already what LoopVectorize picks.
The kernel that "could not be constructed" did the one job it was kept for.

### 122. The scorecard: 1 hit of 8, or 3 of 8 with an MDE gate


| kernel | Claude's expected winner | expected effect | confidence | measured best (confirmed) | measured ratio | score | worst arm |
|---|---|---|---|---|--:|---|---|
| K1 | `inline_never` | +2% to +10% | low | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9545 |
| K2 | `inline_always` | +2% to +10% | medium | `inline_always` | 1.6775 | **hit** | `align_64` 0.9974 |
| K3 | `unroll_disable` | +2% to +10% | medium | `unroll_count_4` | 1.0436 | same-family | `unroll_disable` 0.7056 |
| K4 | `KEEP_DEFAULT` | width 16: 0% to -25% | medium | `inline_never` | 1.0152 | miss | `vectorize_width_2` 0.2024 |
| K5 | `KEEP_DEFAULT` | IC 1: -50% to -75% | high | `vectorize_width_16` | 1.0265 | miss | `vectorize_width_2` 0.2791 |
| K6 | `align_64` | +-0% to +-3%, sign unknown | low | `KEEP_DEFAULT` | -- | miss | `align_32` 0.9985 |
| K7 | `inline_never` | 0% to +5% | medium | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9999 |
| K8 | `KEEP_DEFAULT` | every hint <= 0% | high | `vectorize_width_16` | 1.0881 | miss | `vectorize_width_2` 0.4467 |

**1 hit, 1 same-family, 6 miss of 8.**

With the post-hoc MDE gate (oracle.md 2, dated note): the same rule, plus the confirmed effect having cleared its batch's MDE.

| kernel | Claude's expected winner | expected effect | confidence | measured best (confirmed) | measured ratio | score | worst arm |
|---|---|---|---|---|--:|---|---|
| K1 | `inline_never` | +2% to +10% | low | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9545 |
| K2 | `inline_always` | +2% to +10% | medium | `inline_always` | 1.6775 | **hit** | `align_64` 0.9974 |
| K3 | `unroll_disable` | +2% to +10% | medium | `unroll_count_4` | 1.0436 | same-family | `unroll_disable` 0.7056 |
| K4 | `KEEP_DEFAULT` | width 16: 0% to -25% | medium | `KEEP_DEFAULT` | -- | **hit** | `vectorize_width_2` 0.2024 |
| K5 | `KEEP_DEFAULT` | IC 1: -50% to -75% | high | `KEEP_DEFAULT` | -- | **hit** | `vectorize_width_2` 0.2791 |
| K6 | `align_64` | +-0% to +-3%, sign unknown | low | `KEEP_DEFAULT` | -- | miss | `align_32` 0.9985 |
| K7 | `inline_never` | 0% to +5% | medium | `KEEP_DEFAULT` | -- | miss | `inline_never` 0.9999 |
| K8 | `KEEP_DEFAULT` | every hint <= 0% | high | `vectorize_width_16` | 1.0881 | miss | `vectorize_width_2` 0.4467 |

**3 hit, 1 same-family, 4 miss of 8.**

The two readings were both pinned before the arms that separate them
(`oracle.md` 2, dated note at arm 21). They disagree on two rows only, K4 and
K5, and in both cases on a confirmed effect of 1.5--2.7% that is under its
batch's 3% MDE: the frozen rule calls such an arm the kernel's measured best,
the MDE gate calls it undetectable. SPEC.ja.md's 3% floor says the second is
the one to act on; the first is the one that was pre-registered. Both are
reported and neither is argued for.

**Grading the effect-size claims instead of the winner claims gives a
different and better picture.** Four of the eight bands EXPECTED.md states
contain the measured number (K5 −70.4% in −50/−75; K6 +0.08% in ±0--3%; K7
−0.01% at the floor of 0--+5%; and K3's `unroll.count=2`, which EXPECTED.md
predicted "should also win, by less", did win at +4.2%). Where Claude is well
calibrated is **how much a knob can matter**; where it is not is **which
knob**, and the sign of the two inlining redirections:

* **K1.** `inline(never)`, predicted +2% to +10%, measured **0.9545 /
  0.9566 in two batches** --- a 4.5% loss. The mechanism ran exactly as
  described (eight out-of-line calls per iteration, two symbols changed);
  EXPECTED.md priced the calls and not the scheduling the inlined copies
  were getting.
* **K3.** `unroll.disable`, predicted +2% to +10%, measured **0.7056** --- a
  29% loss --- while its sibling `unroll.count=4` won +4.4% and
  `unroll.count=2` +4.2%. The kernel's mechanism was right (the unroller is
  the only thing a hint can reach there, and `unroll.count=8` reproduces the
  default exactly: an identical build). The direction was not: less
  unrolling is much worse, a little less is better.
* **K7.** `inline(never)`, predicted 0% to +5%, measured **0.9999
  [0.9981, 1.0017]**, unconfirmed. Exactly nothing, which is the floor of
  the predicted band and the refutation of the winner claim at once.
* **K2 is the one hit, and it is enormous.** `inline(always)`, predicted
  +2% to +10%, measured **1.6775 and 1.6742 in two batches: +67.8% on k2.**

Three predictions of `inline(never)` as a winner, three failures on sign.
That is a pattern about Claude's model of call overhead, not three
coincidences.

### 123. `inline(always)` at K2: the largest confirmed effect in this project

EXPECTED.md 4 replaced K2's inert `inline` with `inline(always)` after the
source study, kept the mechanism section 1 had designed, and dropped its
confidence to medium because "the size of the win is now the open question
rather than its existence". The mechanism is confirmed instruction for
instruction: round 6's binary has **60 fewer `imul`** --- exactly the
60-round dependency chain --- because `mode` is a literal at both call sites,
so `m = (mode & 7) | 1` folds to a constant and the 3-cycle register multiply
becomes a `lea` pair. That accounts for roughly 1.25x of the 1.68x (5 cycles
per round on the chain becoming 4); the rest is the call being removed and
the two inlined copies being scheduled in place, and was not measured
separately.

`k2_mix` disappears from the symbol table --- the callee-vanishes case
decision 77 flagged as a robustness requirement --- and the dump, the
normalised-code comparison and the correctness check all handled it.

**This is the first time in the project that a hint from the frozen
vocabulary has made a program measurably faster by more than a few percent,
and it is the candidate v3 added.** Decision 77 replaced `inline` with
`inline(always)` from a reading of `InlineCost.cpp`, before any timing; the
oracle says the replacement was worth 67.8% at the one site built to need it.

### 124. Which hints are live on this benchmark, and which are furniture

**Nine of the sixteen candidates in vocabulary v3 can move this benchmark by
more than its noise floor**, counting only confirmed effects that cleared
their batch's MDE --- and **only three of the nine ever do it in the right
direction**:

| | candidates | largest confirmed effect |
|---|---|---|
| live, can win | `inline(always)`, `unroll.count=4`, `vectorize.width=16` | +67.8% (k2), +4.4% (k3), +8.8% (k8) |
| live, only ever lose | `inline(never)`, `unroll.disable`, `vectorize.width=2`, `vectorize.width=4`, `interleave.count=1`, `interleave.count=2` | −70.6% (k5, `unroll.disable`) |
| **dead: never cleared the MDE anywhere** | `align=16`, `align=32`, `align=64`, `interleave.count=4`, `unroll.count=2`, `unroll.count=8`, `vectorize.width=8` | --- |

The three alignment candidates are the whole of the function vocabulary
except the two inlining ones, and none of them moved this benchmark at all:
`align=16` built the baseline 8 times out of 8, and the two arms where
`align=64` genuinely relocated the symbol moved the clock by 0.08% and
0.26%, neither confirmed. `interleave.count=4`, `unroll.count=8` and
`vectorize.width=8` are dead for the opposite reason --- they are what
LLVM already chose, and the driver's classifier says so by building the
baseline.

Seven of the sixteen are, on this target, ways of telling LLVM what it has
already decided. That is the same shape as jaq, where `align=16` was a no-op
on all 15 marks and 48 of 90 arms changed nothing (section 113), and it is
the ratio of live to dead hints that decision 74 said would itself be a
result.

### 125. Three findings the scorecard does not carry

**(a) `unroll.disable` and `interleave.count=1` are the same instruction to
a vectorised loop.** On k5 they produce the same instruction count (6
`vpmulld` against the baseline's 16) and the same ratio, 0.2941 and 0.2957;
on k4, 0.7309 and 0.7301; on k8, 0.8226 and 0.8033. LoopVectorize reads
`llvm.loop.unroll.disable` and refuses to interleave, so **on an
already-vectorised site one of those two arms is a duplicate measurement**
--- 8 of this sweep's 44 loop arms, and the same waste waiting in jaq's
176-arm loop half. On k3, whose loop the vectoriser refuses for a
recurrence, they are properly different: `unroll.disable` reaches the
unroller (−29.4%) and `interleave.count=1` is inert (an identical build),
exactly as EXPECTED.md 1 K3 predicted.

*The dump cannot say which sites those are.* `sites.json` records
`already_vectorized: false` for all four hintbench loop sites, including k4,
k5 and k8, whose own remarks read "vectorized loop (vectorization width: 8,
interleaved count: 4)". The field is read at `VectorizerStartEP`, before the
vectoriser runs, so it can only ever mean "this loop already carries
`llvm.loop.isvectorized` metadata" --- the same reading decision 83 (b)
arrived at independently, from the state side, while this sweep was
running. It cannot be used to predict the
duplicate arms on jaq.

**(b) A wider vector width can add chains rather than trade them.**
EXPECTED.md 1 K4 and 1 K5 both argue that a forced width of 16 "cannot add
bandwidth, it can only trade lanes against interleaving". On k5 --- a
latency-bound multiplicative reduction --- that is false: round 48's binary
has **15 `ymm vpmulld` against the baseline's 8**, because VF 16 on u32 is
two `ymm` per vector and with IC 4 that is about eight independent chains
instead of four. Result +2.65%, confirmed, the largest gain on k5. On k4 ---
byte counting, bandwidth-bound --- the same argument is right and width 16
costs 42%. The prediction survived at both kernels under the MDE gate while
the reasoning behind it was correct at one and wrong at the other.

**(c) The control kernel was not a control.** K8's prediction was "every hint
≤ 0%. If any hint wins here by more than the noise floor, the noise floor is
wrong." `vectorize.width=16` wins there by **+8.8%**, confirmed in two
batches, +7.0% inside the combination arm and +5.8% in the holdout batch.
Four independent batches and a two-batch confirmation say the noise floor is
not wrong. What is wrong is the premise that a store-limited unit-stride loop
already at VF 8 x IC 4 has nothing left to give. K8 was built to be the arm
that catches a broken noise floor, and instead it caught a broken assumption.

### 126. The combination arm, on training and on the holdout batch

Six sites joined --- every site whose best arm was confirmed positive:
`k2_mix inline(always)`, `k4_count_bytes inline(never)`, and
`vectorize.width=16` at the k5 and k8 loops, `unroll.count=4` at the k3 and
k4 loops. The one-batch rule that jaq's oracle used would have chosen the
**same six**; the point-estimate rule would have added `k6_hot_loop
inline(always)`.

**Training: 1.0881 [1.0861, 1.0901], confirmed at 1.0856 in a second
batch.** Correctness held, three symbols changed.

| kernel | best one-factor arm | in the combination | in the holdout batch |
|---|--:|--:|--:|
| k2 | 1.6775 | 1.6687 | 1.6721 |
| k8 | 1.0881 | 1.0699 | 1.0584 |
| k3 | 1.0436 | 1.0487 | 1.0444 |
| k5 | 1.0265 | 1.0272 | 1.0243 |
| k4 | 1.0152 | 1.0153 | 1.0138 |
| k1, k6, k7 | (nothing chosen) | 1.0029, 1.0024, 1.0010 | 0.9994, 0.9996, 0.9992 |

**The per-kernel effects survive being combined**, within a point or two of
what they were alone. That is the sharpest contrast with jaq, where twelve
chosen arms whose claims multiplied to +22.4% delivered +2.15% with an A/A of
+2.26% in the same batch (section 114). The difference is not the selection
rule --- it chose the same six sites under both --- it is that here the
one-factor arms were measuring code and there they were measuring the
machine.

The holdout, one batch, four labels, seed 20260924. **hintbench declares no
`TRAIN_WORKLOADS`, so this is the same eight workloads: a third independent
batch, not a generalisation test.**

| label | aggregate | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | --- | --- |
| **comb** | **1.0847** | [1.0822, 1.0872] | 0.25% |
| **best1f** (`k2_mix inline(always)`) | **1.0636** | [1.0609, 1.0661] | 0.26% |
| aa | 1.0097 | [1.0069, 1.0122] | 0.26% |

The batch's MDE is `max(2 x 1.95%, 3%) = 3.90%` and both candidates clear it.
**Unlike jaq, nothing reversed.** Two caveats: the A/A label carries a 9.4%
outlier on k5 that is the whole of its +0.97% aggregate --- this target's
version of jaq's readwrite outlier, and the worst identical-binary reading in
the four batches of this experiment --- and k8, where the combination's
second-largest gain sits, is the noisiest workload in every batch
(per-workload half-width 1.5--2.0% against 0.3--0.6% for the rest).

### 127. Wall clock, and deviations

```
null panels, two batches of four labels               7 min
84 one-factor arms + 1 combination arm             3 h 49 min  (16:39-20:28 JST)
   39 skipped as identical                            6 min total (9.6 s each)
   46 measured, 290 s each; 38 carried a confirmation batch
holdout batch, four labels                            4 min
```

**About 4.1 hours, 0 API calls, $0.** The estimate in section 108 ("roughly 2
minutes per arm, three to three and a half hours") counted two timing labels
and no confirmation; the real batch is three labels over eight 350 ms
workloads --- 432 executions, 2.5 minutes --- and a confirmed arm carries two
of them. The no-op skip took about 3.1 hours off the total.

* **The settle gap is 0 ms**, hintbench's frozen value; the 250 ms of the
  protocol note is jaq's. It was not changed mid-project, and the two null
  panels are the evidence that 0 ms is good enough here.
* **`taskset -c 8` is physical core 4** on this machine, which is what the
  per-target core allocation in `target_common.sh` reserves for hintbench.
* The combination arm was selected by the confirmed-in-two-batches rule; on
  this target it and the one-batch rule chose the same six sites, so
  **nothing here tests the difference between them**.
* Arms 6 and 85 were accepted under the full four-condition acceptance rule.
* **The closure fix changed nothing on hintbench and everything on jaq.**
  Nothing measured here says whether jaq's numbers move once one Choice stops
  fanning out to 60 closures; that is the loop half's job, and the function
  half would have to be re-run to find out.
* Nothing here says anything about other targets, about inputs these kernels
  were not tuned on, or about what Jev would answer. The next step is Jev v3
  against this ground truth (decision 72, step 3).

### 128. What the oracle settles about the Jev one-shot runs that ran beside it

Decisions 83 and 84 were taken while this sweep was running, from API-only
Jev runs on the same target (`docs/experiments/hintbench/jev-oneshot-v*.md`),
and decision 84 registered two disputes for the oracle to decide. It decides
both, and neither the way the dispute was framed:

* **k4, `vectorize.width=16` (Jev, P 0.85) against `KEEP_DEFAULT`
  (Claude).** Measured **0.5793 [0.5777, 0.5813]**, confirmed at 0.5791 ---
  a **42% loss**. Claude is right and Jev is wrong, decisively. The lane
  arithmetic in the verdict block that led Jev to width 16 is exactly the
  reasoning EXPECTED.md used to rule it out, and on this kernel that
  reasoning is correct.
* **k6, `inline(always)` (Jev) against `align=64` (Claude).** Measured
  1.0011 [0.9981, 1.0039] and 1.0008 [0.9981, 1.0039]: **both unconfirmed,
  both indistinguishable from nothing.** Neither answer is right, and the
  correct answer at k6 is `KEEP_DEFAULT`, which neither proposer gave. The
  `align=64` arm really does move the entry from mod 64 = 16 to mod 64 = 0
  and the clock does not notice.
* Decision 84 also records Jev asking for `vectorize.width=8` at k5 and k8
  --- the baseline's own width, a null candidate. At k5 that arm is
  0.9950 and at k8 1.0005, both unconfirmed: correct as a null. But **k8 is
  where `vectorize.width=16` wins +8.8%**, so at the one loop where a width
  hint had something to gain, Jev asked for the width already in force.

More important than either dispute: **the agreement figures of decisions 78,
83 and 84 are agreement with `EXPECTED.md`, and this section measures
`EXPECTED.md` at 1 winner claim right out of 8.** Decision 84 says as much
itself --- "正解は oracle" --- and deferred the two disputes above to this
sweep, so the reference was known to be provisional when those figures were
taken; what follows is the settling it asked for, not a correction of it. "Jev matches 10/12, then
7/12, then 5/12 of Claude's predictions" is a distance from a reference that
is itself mostly wrong, so the fall from 10 to 5 cannot be read as a
regression *or* as an improvement until each of those 12 answers is scored
against this sweep instead. That rescoring is the next step and it needs no
new measurement --- the per-arm ratios are in
`docs/experiments/hintbench/arms.md`.

One provenance note, the same one section 110 had to make about oracle A:
the driver process loaded its modules at 16:39 and kept them for all 85
rounds, so this sweep executed `scripts/jev_search.py` and
`scripts/jev_vocab.py` as of commit `a44d8e6`. The v3.1 state repair
(decision 83) and vocabulary v4 (decision 84) landed at 19:21 and 20:11,
while this sweep was in its 60th and 80th arm; neither reached this process,
and the manifest records `v3-2026-09-22` for both the vocabulary and the
state format. **Nothing in this section is a measurement of v3.1 or v4** ---
but nothing needs to be: v4 changed only the candidate *descriptions*, and
an oracle arm reads no descriptions.

---

## Experiment 4 (hintbench): Jev with feedback vs random

Five rounds of `scripts/jev_search.py --proposer jev`, five of
`--proposer random`, over `targets/hintbench`, scored against the oracle of
section 122. **2026-09-22, 56 minutes of runs (29.0 + 27.0) inside a
20:55--22:11 JST window, 12 API calls, $0.** Full tables, per-round states and the per-site scoring are in
`docs/experiments/hintbench/exp4.md`; the runs' own records are copied into
`docs/experiments/hintbench/exp4-jev/` and `exp4-random/`.

This is the loop of SPEC.ja.md 1(3) closed on a target where a right answer
exists: propose, build, measure, **tell the proposer what happened**, ask
again. Decision 87 left it as the open question --- Jev's one shot was
7 of 12 with a −42% pick at k4, and "フィードバック付きラウンドが必須".

### 129. Two driver changes, made and committed before round 1

Both are in commit `aa3e587`, both are recorded in `exp4.md` 1.4, and
neither touches the vocabulary, the questions, the site set or the
measurement conditions.

**(a) The feedback did not exist.** The round history in the state carried
the **aggregate** ratio only, and a site's history line the whole-build
ratio only. On this target the aggregate is the geometric mean of eight
kernels, so the 42% that `vectorize.width=16` costs at k4 reached the
proposer as 6% of a number naming no site. `record_batch` now keeps every
case's ratio and CI --- it kept only the arm's own kernel, and a search
round has no single arm, so `--proposer jev|random` recorded **none** ---
`render_history` prints a per-case table, and a site's history line quotes
its own case, its interval and whether the round was accepted. State format
bumped to `state-v3.2` / `state-v4.1` (decision 19). Candidates,
descriptions, questions, verdict blocks and source excerpts are unchanged
to the byte; on a target with no per-case readout (jaq, zopfli, oxipng) the
only differences are the header line and one new `outcome` column in the
round-history table, which is added unconditionally.

**Round 1 is therefore the one-shot control, and it held.** Its phase-A
state differs from the state in `jev-oneshot-v4.jsonl` by exactly one line
(the format string), its questions are identical, and **it returned the
same answer at all twelve sites**.

**(b) A 503 burst cost a round.** Decision 87 recorded a burst exhausting
all three internal retries on both phases of a repeat; `jev_oneshot.py`
already re-sent such a request unchanged and `jev_search.py` did not, so a
phase with no probabilities would go out all-`KEEP_DEFAULT` and
`forced_top1` could not rescue it either. `JevProposer.choose` now does
what the one-shot harness does. **It fired on rounds 1 and 2 of the Jev
run** --- six of the twelve requests carried at least one 503 --- so
without it round 1 would not have been the control above.

### 130. Jev, with feedback: 2 rounds accepted, +6.8%, 77% of the oracle combination

| round | hints | ratio | 95% CI | confirm | accepted | exact/family/miss | harmful |
|---|---|--:|---|---|---|---|--:|
| 1 | k2 `inline(always)`, k6 `inline(always)`, k4 loop **`width=16`**, k5 loop `width=8`, k8 loop `width=8` | **0.9931** | [0.9905, 0.9957] | 0.9903 | no | 7 / 1 / 4 | **2** |
| 2 | k2 `inline(always)`, k6 `inline(always)`, k8 loop `width=8` | **1.0628** | [1.0590, 1.0660] | 1.0656 | **yes** | 9 / 1 / 2 | 0 |
| 3 | the same | 1.0636 | [1.0614, 1.0659] | 1.0665 | no | 9 / 1 / 2 | 0 |
| 4 | the same | 1.0669 | [1.0627, 1.0718] | 1.0672 | no | 9 / 1 / 2 | 0 |
| 5 | the same | **1.0679** | [1.0644, 1.0715] | 1.0663 | **yes** | 9 / 1 / 2 | 0 |

Third batch, best plan: **1.0673 [1.0645, 1.0704]**, A/A 1.0034 ±0.0024,
MDE 3.34%. Against the combination arm of section 126 (1.0881 training,
1.0847 on its own third batch), `(plan−1)/(comb−1)` gives **77.1% of the
oracle combination on training and 79.4% on the third batch.**

Read that with section 133: rounds 2--5 are the same binary, and the nine
batches this run spent on it (four rounds, four confirmations, the third
batch) span **1.0628--1.0679, i.e. 71--77% of the combination**. 77.1% is
the frozen `best`, which is the highest of them.

Round 1 reproduces decision 87 exactly --- 7 of 12, functions 7/8, loops
0/4 --- and is the only round that is **slower than the baseline**. The
three answers the four later rounds still get wrong:

| site | Jev's final pick | truth | what it left or cost |
|---|---|---|---|
| `fn:k6_hot_loop` | `inline(always)` | `KEEP_DEFAULT` | 1.0011 at k6, unconfirmed, and **−2.8% at k3** (oracle arm 26) |
| k3 loop | `KEEP_DEFAULT` | `unroll.count=4` | **+4.4%**, never tried |
| k8 loop | `vectorize.width=8` | `vectorize.width=16` | the baseline's own width; **+8.8%**, never tried |

Everything else is exact, including `inline(always)` at `k2_mix` --- the
+67.8% of section 123 --- in all five rounds.

### 131. Random, same everything, seeded: nothing accepted, 0% of the combination

| round | ratio | 95% CI | confirm | accepted | exact/family/miss | harmful |
|---|--:|---|---|---|---|--:|
| 1 | **0.9415** | [0.9387, 0.9442] | 0.9332 | no | 2 / 1 / 8 | 1 |
| 2 | 0.9947 | [0.9918, 0.9975] | 0.9968 | no | 0 / 0 / 12 | 2 |
| 3 | 0.9990 | [0.9954, 1.0024] | not triggered | no | 2 / 0 / 10 | 0 |
| 4 | **0.7087** | [0.7067, 0.7106] | 0.6999 | no | 0 / 0 / 12 | **2** |
| 5 | 0.9952 | [0.9926, 0.9975] | 0.9954 | no | 2 / 0 / 9 | 0 |

**No round beat the baseline**, so there is no best plan and the third
batch is the run's null arm: 0.9990 [0.9970, 1.0013], A/A 1.0012, MDE
3.81%. Random reached **0% of the oracle combination** on both batches.
Over 58 site-answers: 6 exact, 1 same-family, 51 miss, **5 harmful**. All
six exact answers are `KEEP_DEFAULT` where the truth is `KEEP_DEFAULT`.
**In 58 draws it found none of the three hints that can make this
benchmark faster.** Its worst round cost 29% and its worst case 80% (k4
`vectorize.width=2`, 0.2031) --- correct programs, stopped by the speed
gate.

Rounds 1 and 5 asked eleven sites, not twelve: random put `inline(never)`
on `k4_count_bytes`, which changes the inlining the k4 loop lives in, so
its key does not come back from the phase-A dump. Recorded as
`n_loop_sites: 3`, nothing failed, and an unasked site is not scored.

### 132. The feedback removed the harmful picks in one round, and discovered nothing

`P` of the named candidate, per round, from the raw responses in
`exp4-jev/jev-v4-r5.jsonl`:

| site | candidate | r1 | r2 | r3 | r4 | r5 |
|---|---|--:|--:|--:|--:|--:|
| k4 loop | `vectorize_width_16` | **0.88** | 0.28 | 0.07 | 0.13 | **0.12** |
| k5 loop | `vectorize_width_8` | **0.58** | 0.37 | 0.03 | 0.10 | **0.08** |
| k8 loop | `vectorize_width_8` | 0.60 | 0.56 | 0.85 | 0.81 | **0.79** |
| k8 loop | `vectorize_width_16` | 0.01 | 0.02 | 0.00 | 0.00 | **0.00** |
| k3 loop | `unroll_count_4` | 0.15 | 0.15 | 0.09 | 0.10 | **0.13** |
| `k2_mix` fn | `inline_always` | 0.75 | 0.88 | 0.95 | 0.96 | **0.91** |
| `k6_hot_loop` fn | `inline_always` | 0.76 | 0.79 | 0.56 | 0.59 | **0.62** |

Round 2's state said this at the k4 loop, and nothing else there changed:

```
  what earlier rounds chose here:
    round 1: vectorize.width=16 -> whole-build ratio 0.9931; on case k4, the
    one case this site's own code is timed by, 0.5813 with 95% CI [0.5797,
    0.5830] (not accepted)
```

`P(width=16)` fell 0.88 → 0.28 and the argmax moved to `KEEP_DEFAULT`; by
round 3, with a second line recording that `KEEP_DEFAULT` returned k4 to
1.0002 and was accepted, it was 0.07 and never returned. The other harmful
pick went the same way (k5, 0.58 → 0.08), and the one that worked was
reinforced (k2, 0.75 → 0.91--0.96).

**It discovered nothing.** k3 to `unroll.count=4`: 0.15 → 0.13, flat. k8 to
`width=16`: 0.01 → 0.00, and `width=8` --- the width already in force ---
*rose* to 0.79. The feedback can only speak about hints that were tried:
no state ever said what `unroll.count=4` would be worth, because no round
tried it, and "k8 1.005, not accepted" reads as "width 8 is harmless", not
as "try something else". The driver's only exploration mechanism,
`forced_top1`, fires only when a phase is entirely `KEEP_DEFAULT`, and
`k2_mix` alone kept phase A non-empty in all five rounds.

So the shape of the result is: **feedback is a good filter and not a
search.** It removed both harmful picks and both null ones in a single
round and then converged, at 77% of what the exhaustive sweep found, onto
the one hint the one-shot had already got right.

### 133. The acceptance rule promoted the same binary twice

Rounds 2, 3, 4 and 5 of the Jev run are the **identical binary**
(`bb18ceb4...`), measured in four independent batches: 1.0628, 1.0636,
1.0669, 1.0679 --- a 0.51-point spread. Round 5 was accepted "as the new
best" over round 2 because 1.0644 > 1.0628.

Rule 3 compares an interval against the incumbent's *point estimate* and
rule 4 only asks that the interval exclude 1, which it does for a plan that
really is +6.7%; **neither asks whether the new plan differs from the
incumbent.** It cost nothing here --- the plan is the same plan --- but on
a run where two different plans sit inside the batch-to-batch spread this
promotes the luckier batch, which is the jaq failure of decision 80 (a) in
a form the confirmation batch does not cover. It was **not** fixed during
the experiment: changing the rule mid-run would have changed the rule the
two runs were measured under.

Those four batches are also a free null panel on one pair: spread 0.51 pt,
and the in-run A/A across the ten rounds of both runs ran 0.9982--1.0020 at
half-widths 0.0016--0.0044. Quieter than jaq's 4.67 pt (section 113), in
line with `oracle.md` 3.

### 134. Two things the per-case readout cannot do

* **It cannot separate two sites that share a case.** k4 has a function
  site and a loop site and one workload, so after round 1 the *function*
  site's history line also read "`KEEP_DEFAULT` → on case k4 … 0.5813" ---
  true, and it attributes the loop's loss to the function's answer. Jev did
  not take it (`KEEP_DEFAULT` at `k4_count_bytes` held P 0.90--0.97
  throughout), but the state cannot say which of two sites moved a case,
  and on a target with more sites per case it would say much less.
* **It hides a hint's cost elsewhere.** `inline(always)` at `k6_hot_loop`
  is 1.0011 on k6 and **0.9718 on k3** (oracle arm 26); at `k2_mix` it is
  1.6775 on k2 and 0.9873 on k3. The oracle's per-kernel readout of section
  103 scores each arm on its own kernel only, so neither cost was ever
  scored, and both are inside Jev's accepted plan --- which is why its k3
  sits at 0.985--0.988 in every accepted round. The readout is still right
  for *ranking* a one-factor arm; it is not a statement that the arm is
  free.

One more correction it forces: decision 84 called `vectorize.width=8` at k5
and k8 "null candidates". The oracle confirmed k5's at **0.9950 with a
negative sign** in two batches --- under the MDE, but confirmed --- so by
the "confirmed below 1" definition used here it is a *harmful* pick, not an
inert one, and Jev's round-1 answer at k5 is counted as such above.

## Oracle A2 (jaq): function attributes, vocabulary v4

"Oracle A (jaq)" above swept the six v1 function-attribute candidates over
jaq's fifteen marks and found nothing: no arm cleared the MDE, and on the
holdout both the combination arm and the best one-factor arm collapsed into
the A/A. Two things were wrong with that sweep and both are decision 85 (c):

1. **`inline(always)` was not in the vocabulary.** v1 offered `inline`
   (inlinehint) and `cold`, and decision 77 later established from
   `InlineCost.cpp` that the LLVM 23.1.1 inliner ignores both under
   `O3 + PGO + fat LTO`. Two of the six candidates were furniture. On
   hintbench `inline(always)` is the one hint that moved anything at all
   (k2, +67.8%, section 123), so Oracle A swept jaq without the candidate
   that has the only demonstrated mechanism behind it.
2. **One Choice fanned out over sixty closures.** The mark rule reached the
   closures defined inside a generic mark, so a single answer at
   `TermId::run` wrote **62** plan entries. Decision 80 (c) changed the
   default scope to `own` --- the mark's own functions and their
   monomorphizations, not the closures inside them.

This section is the re-run with both repairs. It is **not** a re-measurement
of Oracle A: the candidate list and the fan-out both changed, so the two
sweeps share the baseline binary and nothing else.

### 135. What was run

```
scripts/jev_search.py --target jaq --marks targets/jaq/jev-marks.txt \
    --sites targets/jaq/sites.json --site-set oracle.selected_keys_top3 \
    --proposer oracle --oracle-phase A --vocab v4 --keep-binaries all \
    --baseline-dir artifacts/jaq-search/jev-r5/baseline \
    --out artifacts/jaq-search/oracle-A2/

scripts/norm_code_diff.py artifacts/jaq-search/jev-r5/baseline/bin \
    artifacts/jaq-search/oracle-A2/round-*/bin \
    --profdata pgo/jaq/merged.profdata \
    > artifacts/jaq-search/oracle-A2/norm-code-diff.txt

export TARGET=jaq
scripts/bench_panel.sh artifacts/jaq-search/oracle-A2-holdout 15 3 20260921 \
    base=artifacts/jaq-search/jev-r5/baseline/bin \
    comb=artifacts/jaq-search/oracle-A2/round-76/bin \
    best1f=artifacts/jaq-search/oracle-A2/round-66/bin \
    aa=artifacts/jaq-search/jev-r5/baseline/bin
```

**15 marks x 5 candidates (`inline_always`, `inline_never`, `align_16`,
`align_32`, `align_64`) = 75 one-factor arms, then one combination arm**, 76
rounds, 2026-09-22 22:37 -- 2026-09-23 03:58 JST, **5 h 21 min**, 0 API calls,
$0. Frozen exactly as Oracle A was, and against the same baseline binary
(`e183c81d…`), so the two sweeps are measured on one reference: `repetitions
= 15`, `warmup = 3`, shuffle from `seed = 20260921` + the round number,
`--gap-ms 250`, `taskset -c 4`, bootstrap 10000, **training** cases,
`merged.profdata` `4e879ce1…`, `jev-opt.toml` `a8029ac1…`, `jev-marks.txt`
`40ef24cc…`. What differs from Oracle A, and only this: vocabulary
`v4-2026-09-22` in place of `v1-2026-09-22`, state format
`state-v4.1-2026-09-22`, plugin `ca4a6625…` in place of `be74c857…`, and the
decision-80 driver --- which classifies every build against the baseline,
does **not** time one that is `identical`, and re-measures in a second
independent batch any arm whose interval excluded 1.

The arm table is `docs/experiments/jaq-oracle-A2/arms.md`, generated by
`scripts/jaq_oracle_table2.py` from the run's own records; the run summary and
the manifest are beside it. Every one of the 76 arms produced output identical
to the baseline's on all three cases, and every plan entry was `consumed`.

### 136. The closure fix: 138 plan entries became 49

The same fifteen marks, the same site set, the same `--fn-attr-scope own`
default the driver has carried since decision 80 (c):

Four of the fifteen marks moved and eleven did not (an arm's entry count is
the `fn hints` column of each run's summary; mark *N* is arms 6N-5..6N in
Oracle A and 5N-4..5N here):

| mark | v1 plan entries (Oracle A) | v4 plan entries (here) |
|---|--:|--:|
| `<jaq_core::compile::TermId>::run` | **62** | **2** |
| `jaq_json::read::parse` | 18 | 6 |
| `jaq_core::path::run` | 12 | 3 |
| `<jaq_json::Val as core::hash::Hash>::hash` | 12 | 4 |
| the other eleven marks | 1, 1, 1, 1, 1, 1, 2, 5, 6, 7, 8 | identical |
| **total, one arm** | **138** | **49** |
| combination arm | 106 (12 marks) | 11 (3 marks) |

An arm of Oracle A therefore put an attribute on 138 functions when the
question asked about fifteen, and the worst case was 62-to-1. Whatever
Oracle A measured at `TermId::run`, it was not "this attribute on this
function": it was the attribute on sixty-two closures at once, and its
accepted best arm (round 27, `TermId::run cold`, 1.0323) is exactly that arm.
The mark this section's headline result comes from, `Val::hash`, is one of
the four: twelve functions in Oracle A, **four** here. Nothing about the
present run's numbers depends on that reading, but the comparison in 141
does.

### 137. 39 of the 75 arms built the baseline

The decision-80 classifier compares each arm's binary to the baseline's with
`norm_code_diff.py` before timing it, and skips the batch when they are the
same instructions and the same symbol table:

| what the build differs in | arms | ratio range |
|---|--:|---|
| nothing: same instructions, same symbol table (**not timed**) | **39** | 1.0000 |
| only where the code sits | 17 | 0.9744 -- 1.0122 |
| instructions changed | 19 | 0.9061 -- 1.0426 |

**39 of 75 one-factor arms are the baseline and 36 were measured** --- the
same picture as hintbench's 39 of 84 (section 120) and Oracle A's 48 of 90,
and about 3 hours of timing not spent. By candidate:

| candidate | arms | identical | layout | code | measured mean | min | max | confirmed |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| `align_16` | 15 | **15** | 0 | 0 | -- | -- | -- | 0 |
| `align_32` | 15 | 4 | 9 | 2 | 0.9992 | 0.9744 | 1.0122 | 0 |
| `align_64` | 15 | 4 | 8 | 3 | 0.9927 | 0.9475 | 1.0118 | 3 |
| `inline_always` | 15 | 6 | 0 | 9 | 0.9931 | 0.9445 | 1.0426 | 6 |
| `inline_never` | 15 | 10 | 0 | 5 | 0.9689 | 0.9061 | 1.0032 | 4 |

`align_16` is a no-op on all fifteen marks for the second time (Oracle A,
section 117), and `align_32`/`align_64` change **where** the code sits and
almost never what it is: of the 22 arms in which they change the binary at
all, **17 are pure `layout` with `changed symbols: 0`**, and the remaining
five (`TermId::run` x2, `Path::run{closure#0}` align_64, `String::fmt` x2)
each change exactly **one** symbol. Section 124's finding that `align` is
furniture holds on jaq as it held on hintbench.

### 138. The `inline(always)` arms, which Oracle A could not ask about

This is the candidate the re-run exists for. **Nine of its fifteen arms
changed instructions and six of them were confirmed in two independent
batches** --- more confirmed arms than any other candidate, and the only
candidate whose confirmed arms point in both directions:

| mark | plan entries | batch 1 | 95% CI | batch 2 | 95% CI | clears 3% MDE | changed syms | profile share |
|---|--:|--:|---|--:|---|---|--:|--:|
| `<jaq_json::Val as core::hash::Hash>::hash` | 4 | **1.0426** | [1.0343, 1.0505] | **1.0484** | [1.0420, 1.0546] | **yes (+)** | 250 | 12.47% |
| `write_until` | 6 | 1.0153 | [1.0042, 1.0265] | 1.0215 | [1.0122, 1.0312] | no | 5 | 12.00% |
| `reserve_rehash` | 1 | 1.0104 | [1.0047, 1.0162] | 1.0096 | [1.0036, 1.0162] | no | 17 | 11.73% |
| `jaq_json::read::parse` | 6 | 0.9741 | [0.9513, 0.9956] | 0.9739 | [0.9675, 0.9802] | no | 29 | 21.54% |
| `<alloc::rc::Rc<IndexMap>>::drop_slow` | 1 | 0.9525 | [0.9475, 0.9572] | 0.9848 | [0.9773, 0.9922] | batch 1 only | 45 | 14.46% |
| `jaq_json::write::write` | 1 | 0.9445 | [0.9397, 0.9494] | 0.9337 | [0.9267, 0.9409] | **yes (−)** | 10 | 1.81% |

The other nine: six built the **baseline** (`Lex::seq`, `str_fold`,
`TermId::run`, `funs::base{closure#3}`, `Path::run{closure#0}`,
`base_run{closure#7}` --- LLVM had already inlined them, or they have no call
site left to inline into), and three moved inside their own noise
(`path::run` 1.0116 with a confirmation of 1.0060, `Adapter::write_str`
0.9914, `String::fmt` 0.9957).

So: **`inline(always)` cuts both ways, and it is the only candidate in
either jaq sweep that ever produced a *positive* arm above the MDE.** One
arm gains 4.3--4.8% in two batches; `write::write` loses 5.5--6.6% in two
batches and `Rc<IndexMap>::drop_slow` loses 4.8% in the first and 1.5% in
the confirmation. It is **not** the only live candidate: `inline_never` has
four confirmed arms of its own and two of them clear the MDE in **both**
batches (139). What is true of both is that they are the same knob ---
forced inlining, in one direction or the other --- and that nothing else on
jaq moves the clock at all.

`Val::hash` is the interesting one and the mechanism is visible in the
normalized diff: 250 symbols changed at 12.47% of the profile, and the
per-case split says what for. On training, `objsearch` +4.71% / +4.01% and
`readwrite` +8.30% / +10.47% in the two batches, `strproc` +0.0% / +0.3%.
`strproc` never builds a map; the other two do, and `Val::hash` is what
`IndexMap` calls per key.

### 139. The MDE gate: one positive arm, four negative

Thirteen arms were confirmed (both batches exclude 1.0 with the same sign).
**Five clear the 3% MDE on their first batch, four of them in both batches,
and only one of the five is a gain:**

| arm | mark | candidate | batch 1 | batch 2 | clears MDE | in-run A/A |
|---:|---|---|--:|--:|---|--:|
| 66 | `Val::hash` | `inline_always` | **1.0426** | **1.0484** | both batches | 1.0032 |
| 7 | `Lex::seq` | `inline_never` | **0.9061** | 0.9426 | both batches | 0.9882 |
| 26 | `write::write` | `inline_always` | 0.9445 | 0.9337 | both batches | 1.0180 |
| 17 | `write_until` | `inline_never` | 0.9625 | 0.9678 | both batches | 0.9854 |
| 51 | `Rc<IndexMap>::drop_slow` | `inline_always` | 0.9525 | 0.9848 | **batch 1 only** | 0.9781 |

(`arms.md` computes its "clears MDE" column from the first batch alone; the
column above is the stricter reading and is what the text uses. The per-mark
best-of-five table is in `arms.md` as well and is not repeated here.)

The four ways to lose 4--9% are all on the read/write path and every one of
them is a forced inlining decision in one direction or the other --- the same
shape Oracle A found (section 115: "three ways to lose 3--5%, all of them
`inline_never`/`cold` on the read path"), now with `inline(always)` supplying
two of them and `inline_never` the other two.

**The in-run A/A of this run is the same broken instrument Oracle A had.**
Over the 60 timed batches (37 first, 23 confirmations) the third label --- a
second copy of the baseline binary --- ran **0.9774 to 1.0317, 5.43 points,
sd 1.10%, and 28 of its 60 intervals exclude 1.0**. Section 116 (1) applies
unchanged: a 95% interval that covers 1.0 in 32 of 60 A/A batches cannot
carry a 1.5% effect, which is why nothing between 0.97 and 1.03 is claimed
here, confirmed or not.

### 140. The combination arm, on training and on the holdout batch

Three of the fifteen marks had an arm confirmed in two batches with a ratio
above 1, so the combination arm is those three, all of them `inline(always)`:
`reserve_rehash`, `write_until`, `Val::hash`. 11 plan entries, all
`consumed`, output identical to the baseline's. The plan is
`docs/experiments/jaq-oracle-A2/combination-plan.json`. (The one-batch rule
would have added `path::run inline_always` and `read::parse align_32`; the
point-estimate rule would have carried nine marks. Neither arm was built.)

If the three confirmed effects were real and independent their product would
be 1.0153 x 1.0104 x 1.0426 = **+6.96%**.

**Training: 1.0291 [0.9676, 1.0952] --- and this batch is not usable.** Its
own A/A ran 1.0071 with a half-width of **5.60%**, its per-case ratios are
`objsearch` 1.1312 against `strproc` 0.9535, and its MDE is 23.4%. Arms 74,
75 and 76 (03:37--03:58 JST) carry A/A half-widths of 3.93%, 3.95% and 5.60%
--- and arm 75's confirmation batch another 5.47% --- where the run's median
over 60 batches is **0.73%**; something outside this run had the machine for
the last twenty minutes of it. The number is recorded because the batch was taken, not
because it says anything. It is **not** re-measured: the training batch is
not what this arm is judged on, and re-running a batch to get a quieter one
is the thing this project does not do.

The holdout batch is the discriminator, and it is quiet. One batch, four
labels, measured once after the arms were frozen (SPEC.ja.md 7), n=15,
warmup 3, `taskset -c 4`, gap 250 ms, holdout cases:

| label | aggregate ratio | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | --- | --- |
| **comb** (the three `inline(always)`) | **1.0017** | [0.9789, 1.0177] | 1.94% |
| **best1f** (`Val::hash inline_always`, the best of the 75) | **1.0168** | [1.0038, 1.0275] | 1.18% |
| aa (a second copy of the baseline) | **0.9973** | [0.9920, 1.0033] | 0.56% |

The pre-registered MDE for this batch is `max(2 x 0.56%, 3%) = 3%`;
`bench.py`'s worst-per-workload version is 7.88%. **`best1f` is +1.68% and
under both.** Per case it is not flat, though:

| case | best1f | 95% CI | comb | 95% CI |
|---|--:|---|--:|---|
| `objsearch` | **1.0445** | [1.0312, 1.0579] | 1.0265 | [1.0115, 1.0422] |
| `strproc` | 0.9966 | [0.9633, 1.0194] | 1.0025 | [0.9935, 1.0107] |
| `readwrite` | 1.0099 | [1.0050, 1.0144] | 0.9767 | [0.9280, 1.0068] |

`objsearch` is `select(.k == "v")` over objects --- the case that hashes ---
and there `Val::hash inline(always)` is **+4.45%** on the holdout input
against +4.71%/+4.01% on the training input: the same effect, the same size,
a different file. The aggregate is a geometric mean over three cases and two
of them have no map in them, so it divides the effect by three.

Oracle A's holdout showed a **sign reversal** (best arm 0.9909, combination
1.0036 against training's 1.0323 and 1.0215). This one does not reverse.

### 141. What Oracle A2 says, plainly, and what changed against Oracle A

* **The picture on jaq changed in one place.** Oracle A's plain statement was
  "no function attribute on any of jaq's fifteen marked functions makes jaq
  measurably faster, and the oracle's own best is inside its own noise."
  That is no longer true as written. `inline(always)` at
  `<jaq_json::Val as core::hash::Hash>::hash` is **+4.26% and +4.84% in two
  independent training batches**, both intervals excluding 1, both clearing
  the 3% MDE, with a quiet A/A (1.0032) in the first of them, and it is
  **+4.45% [1.0312, 1.0579] on the holdout `objsearch` case**. It is the
  first confirmed, above-MDE, positive function-attribute effect this project
  has measured on a real program.
* **It did not change anywhere else.** 74 of the 75 arms are the flat sweep
  Oracle A found. Aggregated over the three cases the holdout is +1.68% for
  the best arm and +0.17% for the combination, both under the MDE, so on the
  headline number --- "how much faster is jaq" --- **jaq is still flat**.
* **The combination is still not the product of its parts.** +6.96% if
  independent, +0.17% measured on the holdout. Two of the three arms
  (`write_until` +1.5%, `reserve_rehash` +1.0%) are sub-MDE and did not
  survive being combined, which is what section 114 saw with twelve arms and
  is the expected behaviour of numbers drawn from noise.
* **`align` is furniture on jaq too**, for the second sweep running: 15 of 15
  `align_16` arms are the baseline, and 17 of the 18 arms `align_32` and
  `align_64` move are pure layout with zero changed symbols.
* **Forced inlining is the only live knob on jaq, in either direction, and
  it is dangerous.** `inline(always)`: six of fifteen arms confirmed, three
  up (one above MDE) and three down (`write::write` −5.5%/−6.6% in both
  batches). `inline_never`: four confirmed, two of them above MDE in both
  batches (`Lex::seq` −9.4%/−5.7%, `write_until` −3.8%/−3.2%), none
  positive. A proposer that likes to try either on jaq is as likely to find
  a 5--9% loss as a 4% gain, which is what the speed gate exists for.
* **The `Jev / oracle` ratio of SPEC.ja.md 2 has a denominator now, and it is
  small**: +4.26% on training, one site of fifteen. It still waits on the
  loop half (176 arms, not run).

### 142. Deviations, and what is not established

* **The loop half of the oracle has still not been run**, so "the oracle" on
  jaq remains its function-attribute half.
* **The combination arm's training batch was measured under interference**
  (A/A half-width 5.60%, MDE 23.4%) and was not repeated. Arms 74 and 75 ---
  `String::fmt align_32` 0.9988 [0.9802, 1.0160] with an A/A of 0.9994
  ±3.93%, and `String::fmt align_64` 0.9475 [0.9188, 0.9812] with an A/A of
  1.0317 ±3.95% and a confirmation of 1.0623 --- share the problem and should
  be read as unmeasured rather than as effects. Exactly five of the run's 60
  batches have an A/A half-width above 1.4%, and four of them are arms
  74--76.
* The holdout batch carries four labels so that the combination and the best
  one-factor arm are measured in **one** batch, as Oracle A's did.
* `--fn-attr-scope` was left at `own`, which is the change this re-run is
  partly about; the `all` scope of Oracle A was not re-measured.
* `Val::hash` is one site of fifteen and one case of three. Nothing here says
  that forced inlining of a hash function helps any other program, or that it
  would survive a different `IndexMap` load.
* The two jaq sweeps share only the baseline binary. Arm-for-arm comparison
  between Oracle A and Oracle A2 is not available and is not made: the
  candidate list changed (6 to 5, two of them replaced) and the fan-out
  changed (138 entries to 49).

## Experiment 5 (hintbench): Jev with exploration

Experiment 4 (sections 129--134) established that the feedback works as a
**filter** and discovers nothing: it dropped both harmful picks in one round
and never once tried the two hints that could have paid, `unroll.count=4` at
the k3 loop (+4.4%) and `vectorize.width=16` at the k8 loop (+8.8%). Decision
90 implemented the four repairs decision 89 asked for. This is the run that
measures them. The write-up is `docs/experiments/hintbench/exp5.md`; the
summary, best plan and Jev log are in `docs/experiments/hintbench/exp5-jev/`.

### 143. What was run

```
scripts/jev_search.py --target hintbench \
    --marks targets/hintbench/jev-marks.txt \
    --sites artifacts/hintbench-sites/sites.json \
    --site-set oracle.selected_keys_loop_hint_kernels \
    --proposer jev --rounds 5 --vocab v4 --readout forced_top1 \
    --source-comments strip --explore 2 -n 15 --warmup 3 \
    --baseline-dir artifacts/hintbench-sites/baseline \
    --measure-holdout --out artifacts/hintbench-search/jev-v42-r5

export TARGET=hintbench
scripts/bench_panel.sh \
    artifacts/hintbench-search/jev-v42-r5/holdout-batch2 15 3 20260927 \
    base=artifacts/hintbench-sites/baseline/bin \
    cand=artifacts/hintbench-search/jev-v42-r5/round-03/bin \
    aa=artifacts/hintbench-sites/baseline/bin

scripts/hintbench_exp4_score.py run artifacts/hintbench-search/jev-v42-r5
```

Everything of `exp4.md` 1.1 is frozen and unchanged --- 8 marks, the same
site set `oracle.selected_keys_loop_hint_kernels` (8 functions + 4 loops),
k1..k8, n=15, warmup 3, shuffle seed 20260921 + round, `taskset -c 8`, gap
0 ms, bootstrap 10000, vocabulary v4, `--source-comments strip`,
`--readout forced_top1`, no-op skip on. **Three things differ**, and all
three are the experiment:

1. `--explore 2` (decision 89 b), where Experiment 4 had no such flag;
2. state format `state-v4.2-2026-09-22` --- decision 89 (c)/(d) plus the
   plugin's `post_vectorize` facts --- where Experiment 4 sent `state-v4.1`;
3. acceptance now has a **fifth** condition, "the plan differs from the
   incumbent's" (decision 89 a).

**The baseline was rebuilt with the new plugin and is the same binary.**
Decision 90 (a) required it because the old dump carries no `post_vectorize`.
`.text` sha256 `df5968bc…` is `oracle.md` 1.1's frozen value, the whole
binary is `07498197…` --- byte-identical to Experiment 4's manifest ---
`norm_code_diff.py` against the PGO baseline says `IDENTICAL` over 373
symbols, and `run_correctness` matches line for line. The search therefore
measures against the same bytes as Experiment 4 and the whole oracle sweep.

**The plugin's post-vectorization facts agree with the oracle's remarks at
four of four loop sites**, none `ambiguous`: k5, k4 and k8 come back
`isvectorized: true`, VF 8, IC 4 (`iv_step` 32), matching "vectorized loop
(vectorization width: 8, interleaved count: 4)"; k3 comes back `false`,
matching "loop not vectorized". The v4.2 state prints those instead of the
`UNKNOWN` that v4.1 printed for three of the four.

**One driver change, made before round 1** and recorded in `exp5.md` 1.5:
`explore_round` got the same unchanged re-send `JevProposer.choose` has had
since Experiment 4 (`A.explore.retry` / `B.explore.retry`, ten seconds, the
same request, the exhausted line kept in the JSONL with its `http_status`).
No request is ever modified to make it succeed. **It never fired** (149).

### 144. The rounds

| round | phase A (functions) | phase B (loops) | explored this round | ratio | 95% CI | confirm | A/A | accepted |
|---|---|---|---|--:|---|--:|--:|---|
| 1 | *lost* (503) | k4 `vectorize.width=16` (`forced_top1`), k5 `unroll.count=8`, k8 `unroll.count=2` | A: k5, k4 fn; B: k5, k8 loop | **0.9369** | [0.9340, 0.9400] | 0.9678 | 1.0017 | **no** |
| 2 | *lost* (503) | k3 `unroll.count=4` | A: k8, k3 fn; B: k3 loop | 1.0079 | [1.0051, 1.0107] | 1.0075 | 1.0025 | **yes** |
| **3** | k1, k2, k3, k6, k7 `inline(always)` | k3 `unroll.count=4` | A: k1, k7 fn; B: none eligible | **1.0741** | [1.0720, 1.0760] | 1.0740 | 0.9995 | **yes** |
| 4 | *lost* (503) | k3 `unroll.count=4` | none eligible | 1.0089 | [1.0064, 1.0112] | 1.0060 | 1.0004 | no |
| 5 | k2, k6 `inline(always)` | *lost* (503) | none eligible | 1.0660 | [1.0637, 1.0682] | 1.0669 | 1.0006 | no |

Every round: output correct, every plan entry applied, no `ambiguous`, no
`vanished`, no `unmatched`. Per case:

| round | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | 0.9965 | 1.0050 | 1.0008 | **0.5823** | 1.0176 | 1.0004 | 0.9996 | 0.9992 |
| 2 | 1.0019 | 1.0068 | **1.0455** | 1.0130 | 1.0015 | 1.0002 | 1.0013 | 0.9937 |
| **3** | 1.0012 | **1.6691** | **1.0402** | 1.0087 | 0.9997 | 1.0009 | 1.0001 | 1.0100 |
| 4 | 1.0006 | 1.0044 | **1.0409** | 1.0088 | 0.9984 | 0.9989 | 1.0038 | 1.0156 |
| 5 | 1.0039 | **1.6764** | 0.9856 | 1.0014 | 0.9946 | 1.0020 | 1.0028 | 1.0040 |

**Round 3 is the best plan: 1.0741, confirmed at 1.0740 in a second
independent batch.** Its plan is `inline(always)` at k1, k2, k3, k6 and k7
and `unroll.count=4` at the k3 loop. Round 1's k4 at **0.5823** reproduces
the oracle's 0.5793 for `vectorize.width=16` there to three digits, and the
speed gate rejected the round, as it did in Experiment 4.

Round 1 is also where the two mechanisms under test collided, and it is
`exp5.md` 2.2's finding: the improved state made **every** loop answer
`KEEP_DEFAULT` (k4 `vectorize.width=16` fell from P 0.88 to 0.36, k8 and k5
`vectorize.width=8` from P 0.60 and 0.58 to **P 0.01 and 0.00** once the
state could say "8 is the width LLVM already uses here"), an all-`KEEP`
phase is exactly the trigger for `forced_top1`, and `forced_top1` then
applied the phase's top-ranked non-`KEEP` candidate --- the −42% at k4. Two
mechanisms that are each right on their own composed into a harmful plan,
and it cost more than the round: a `forced_top1` entry marks the site
**tried**, so exploration could never reach the k4 loop afterwards.

### 145. Exploration reached both target hints and took one of them

This is what the experiment was built to answer.

| the hint | reached by exploration | offered | Jev's answer | in the final plan |
|---|---|---|---|---|
| k3 loop `unroll.count=4`, **+4.4%** | **yes**, round 2 (the only eligible loop left) | 11 untried candidates, no `KEEP_DEFAULT` | **`unroll_count_4`, P 0.31** over `unroll_disable` 0.28 | **yes** |
| k8 loop `vectorize.width=16`, **+8.8%** | **yes**, round 1 | 11 untried candidates, no `KEEP_DEFAULT` | `unroll_count_2` P 0.32; **`vectorize_width_16` ranked 11th of 11 at P 0.01** | no |

**One of two.** At k3 the answer was right and the margin was thin (0.31
against 0.28 --- and `unroll_disable` is the −29.4% at the same loop, which
decision 86 records as Claude's own wrong answer there). Experiment 4 never
tried either candidate in 58 answers; this question was asked once and got
the right one. The measurement then did the rest:

| k3 loop, P(candidate) | round 1 | round 2 | round 3 | round 4 |
|---|--:|--:|--:|--:|
| `KEEP_DEFAULT` | 0.62 | (explored) | **0.03** | 0.04 |
| `unroll_count_4` | 0.15 | 0.31 | **0.95** | 0.95 |

Exploration proposes once, the round measures +4.55% at k3, and from round 3
the argmax carries it without needing exploration again. That is the loop
decision 89 (b) was written to close, closed.

At k8 the mechanism worked and the model did not. The site was identified as
untried, `KEEP_DEFAULT` was removed, and all eleven untried candidates were
put in front of the model with their frozen descriptions --- the +8.8% among
them --- in a question whose premise is "one of these will be tried this
round; which?". It came **last but one**. Measured, Jev's `unroll_count_2`
gave 0.9992 at k8 against the oracle's 1.0164 for that same candidate.

The k8 verdict block is the one `post_vectorize` improved most, which makes
the P 0.01 the interesting number in this experiment:

```
  - what LLVM did with this loop in the baseline build, recorded by the
    plugin itself after LoopVectorize had run ... LLVM vectorized it, with
    vectors of 8 lanes, interleaved 4 times (the vectorized loop's induction
    variable advances 32 elements per iteration).
  - vectorisation legality: LEGAL, and already taken --- the baseline
    vectorizes this loop with no hint at all.
  - no-op check: 8 is the width LLVM already uses here, so the candidate
    `vectorize_width_8` asks for the state this site is in and the build it
    produces can only be the baseline's.
```

The fact did what decision 87 (c) predicted: it killed the wrong answer
(`vectorize_width_8`, P 0.60 → 0.01) and stopped the site asking for the
state it was already in. **It did not produce the right one.** "LLVM chose
8" is read as "8 is correct", not as "8 is a choice and 16 is the untried
alternative next to it". And because one exploration answer makes a site
permanently tried, k8 was never asked again in this run.

### 146. Rounds 4 and 5 were not stopped by the plan-change rule

The new fifth acceptance condition (decision 89 a) **never fired**: all five
plans are distinct (`plan_sig` 786fb052, dfa05c9b, 2c909638, 7d4d8d52,
79928ae1, and `same_plan_as_best` is `false` in all five records), so the
Experiment 4 failure it repairs --- the same binary promoted twice, section
133 --- could not arise. Rounds 4 and 5 were measured, compared, and lost on
the number.

They lost because each is **half a plan**, and the missing half is whatever
the gateway dropped:

| | round 4 | round 5 |
|---|---|---|
| never landed | phase **A** (`A` + `A.retry`, both 503) | phase **B** (`B` + `B.retry`, both 503) |
| function hints | **none** | k2, k6 `inline(always)` |
| loop hints | k3 `unroll.count=4` | **none** |
| ratio | 1.0089 | 1.0660 |
| k2 / k3 case | 1.0044 / **1.0409** | **1.6764** / 0.9856 |
| why not accepted | below the incumbent's 1.0741 | below the incumbent's 1.0741 |

Round 4 is round 3 without the +67.8%; round 5 is round 3 without the +4.4%.
Two details:

* **`forced_top1` could not fire in round 4's phase A**, and correctly so:
  the readout record reads `all_keep_default: true, forced: null,
  ranking: []`. A phase whose every answer is "no answer" has no
  probabilities, so there is no 1−P(KEEP) ranking to take a top-1 from. In
  `choices` this is indistinguishable from round 1's genuinely all-`KEEP`
  phase; only the `why` block separates a dropped request from an answer.
* **Round 5's phase A is the filter working again.** Given round 3's
  measurement, `k1_step` fell from P(pick) 0.47 to `KEEP_DEFAULT`,
  `k3_fill_run` from 0.33 to `KEEP_DEFAULT` and `k7_error_path` from 0.08 to
  `KEEP_DEFAULT`, leaving `k2_mix` (P 0.82) and `k6_hot_loop` (P 0.65).
  Three inert hints dropped in one round; the one that pays kept and
  strengthened. The resulting plan is, to the entry, **Experiment 4's
  accepted plan minus the k8 width-8** --- which this run had already beaten
  in round 3.

### 147. The third batch, taken twice

**The run's own `--measure-holdout` batch is unusable, and the reason is in
its controls.** Its `aa` label --- a second copy of the baseline binary, a
known null --- came back **1.0068 with a half-width of 1.83%** where
Experiment 4's third batch had 1.0034 ±0.24% and every round batch of this
run had ±0.20--0.33%. Three runs in it are interference outliers of
1.5--2.2x: `base`/k7 **740.5 ms** against that label's own 345.5 ms median,
`cand`/k1 600.1 ms against 333.0, `aa`/k1 499.4 ms against 332.6. The worst
lands on the **baseline** label, so `aa` reads 1.0752 at k7 and `cand`
1.0661 at k7, and the batch's MDE is **23.30%** against Experiment 4's
3.34%.

A second batch was therefore taken, once, on the same two binaries --- the
stripped sha256s `bench_panel.sh` printed, `a84b7c0d…` and `ac3790d4…`, are
the ones in `holdout/timing/` --- under the same frozen conditions, with a
fresh seed **pre-registered in `exp5.md` 3.1 before it ran**, together with
the rule that **its number is the one used whatever it says** and that batch
1 is kept and published with its outliers. Neither batch was chosen after
the fact.

| | ratio | 95% CI | A/A | worst case half-width | MDE |
|---|--:|---|--:|--:|--:|
| batch 1 (07:16 JST, seed 20260921) --- **rejected on its controls** | 1.0756 | [1.0557, 1.0984] | **1.0068 ±1.83%** | 11.65% (k7) | **23.30%** |
| **batch 2 (seed 20260927) --- the one used** | **1.0724** | [1.0704, 1.0742] | **0.9979 ±0.20%** | 1.56% (k8) | 3.12% |
| *(Experiment 4's third batch, for scale)* | 1.0673 | [1.0645, 1.0704] | 1.0034 ±0.24% | 1.67% | 3.34% |

Batch 2, per case:

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| cand | 0.9989 | **1.6736** | **1.0389** | 1.0111 | 1.0029 | 0.9971 | 1.0018 | 0.9944 |
| aa | 1.0007 | 0.9986 | 0.9997 | 1.0011 | 1.0003 | 0.9957 | 1.0017 | 0.9854 |

**Rejecting batch 1 cost the experiment its best-looking number**: it would
have read 89.3% of the oracle combination's third batch, where batch 2 reads
**85.5%**. The rejection was decided on the A/A and the outliers, before that
comparison existed.

### 148. Scored against the oracle, and against Experiment 4

Same script, same twelve truths, same rule as section 130:

| round | exact | same-family | miss | **harmful** | ratio | share of the combination (training) |
|---|--:|--:|--:|--:|--:|--:|
| 1 | 5 | 0 | 7 | **1** | 0.9369 | **−71.7%** |
| 2 | 8 | 0 | 4 | 0 | 1.0079 | 8.9% |
| **3** | **7** | **0** | **5** | **0** | **1.0741** | **84.2%** |
| 4 | **10** | 0 | 2 | 0 | 1.0089 | 10.1% |
| 5 | 9 | 0 | 3 | 0 | 1.0660 | 74.9% |

The accepted plan's five misses are `inline(always)` at the k1, k3, k6 and
k7 functions --- truth `KEEP_DEFAULT` at all four, and three of the four are
builds **identical to the baseline** --- and `KEEP_DEFAULT` at the k8 loop,
where the truth is the +8.8%. That last one is the entire remaining gap.

| | Experiment 4 | **Experiment 5** |
|---|--:|--:|
| best plan, training | 1.0679 | **1.0741** |
| best plan, third batch | 1.0673 | **1.0724** |
| share of the combination, training | 77.1% | **84.2%** |
| share of the combination, third batch | 79.4% | **85.5%** |
| exact / same-family / miss / harmful | 9 / 1 / 2 / 0 | 7 / 0 / **5** / 0 |
| rounds accepted | 2 | 2 |
| harmful picks that reached a build | 2 (round 1) | 1 (round 1) |
| harmful picks that survived a round | 0 | 0 |

**The exact count fell and the speed rose, and both have one cause.**
Experiment 5 found `unroll.count=4` at the k3 loop, worth +4.4%, which
Experiment 4 never tried; it also carried four inert `inline(always)` that
Experiment 4 did not, because exploration forces a non-`KEEP` answer at a
site whose right answer is "none of them". Three of the four cost nothing
measurable. The accepted plan's k3 reads 1.0402 where `unroll_count_4`
alone is 1.0436, and section 134's one-factor arms point the right way ---
`inline(always)` is 0.9718 at k3 from k6 and 0.9873 at k3 from k2 --- but
they do not compose: 1.0436 x 0.9718 x 0.9873 is 1.0014, not 1.0402. The
direction is attributable, the size is not.

**The 12-site score is a weak instrument on this target and should not be
read as a headline.** Eight of the twelve truths are `KEEP_DEFAULT`, and
getting those right is worth nothing: round 4 scores **10 of 12**, the best
of the run, and is **+0.9%**; round 3 scores 7 and is +7.4%.

### 149. Cost, the gateway, and deviations

| | |
|---|--:|
| wall clock, 5 rounds + batch 1 | **31.1 min** (06:47--07:18 JST) |
| batch 2 | ~3 min |
| HTTP requests | **21** --- 10 landed, 11 exhausted with 503 |
| Choice questions | 109 |
| latency total / mean / max | **16.3 s** / 776 ms / 975 ms |
| tokens in / out | 141 901 / 3 833 |
| cost | **$0.00** (Vercel AI Gateway, Hobby free tier) |
| Jev's share of the run's wall clock | **0.87%** |

**Half of this run's phase requests never got through.** Phase A was lost in
rounds 1, 2 and 4 and phase B in rounds 2 and 5 --- **5 of 10 phases**, each
after both the request and its unchanged re-send returned 503. Of the five
exploration requests, **5 of 5 landed** (two after an internal 503 and its
backoff), so the `A.explore.retry` / `B.explore.retry` added before round 1
**never fired**: it was written for a real risk that did not materialise,
and it stays because the risk was real. The bodies are the sizes Experiment 4
sent successfully at the same endpoint the previous evening, and no request
was modified to make one succeed.

Deviations and what is not established:

* **The third batch was taken twice** (147), against `exp4.md` 1.2's "the
  third batch is measured once". The rejection is on the controls, it was
  pre-registered with its seed and its rule before the second batch ran, and
  batch 1 is published in full.
* **"Five rounds" should be read as two and a half rounds of both phases
  plus two half-rounds.** Rounds 4 and 5 are not independent evidence about
  the proposer; they are round 3 with a request missing. A re-run against a
  healthy gateway would not be expected to reproduce them.
* **Random is not re-run.** Exploration is a `jev` mechanism --- random draws
  non-`KEEP_DEFAULT` candidates by construction --- so Experiment 4's random
  control (section 131: 0% of the combination, nothing accepted, 5 harmful
  picks) stands unchanged.
* `exploration_sites` makes a site ineligible permanently once **any**
  candidate has been tried there, in any round, accepted or not. Round 1's
  `forced_top1` spent the k4 loop's eligibility on the oracle's −42%, and
  round 1's exploration spent k8's on `unroll_count_2`. **Whether a budget
  that allowed a second visit would have found the k8 width 16 is not
  measured here.**
* The k3 `unroll.count=4` result rests on one answer with a 0.31-against-0.28
  margin. Nothing establishes that the answer is robust; what is established
  is that it was offered, taken, measured and kept.
* Nothing here says anything about a target other than hintbench. The jaq
  run with exploration has not been done.

## Experiment 6 (hintbench): revisit budget, the post_vectorize untried line, and a gateway that lands

Exp5 (§143–149) reached +7.4% (84–86% of the oracle's +8.8% combination) but
k8's `vectorize.width=16` was offered once (P 0.01, ranked 11th) and never
again, and 5 of 10 phase requests were lost to 503. Decision 92 (b)(c)(d)
asked for a revisit budget, a mechanical state line, and a retry policy.
Commits af01508 (vocabulary v5), b489e5d (503 policy + round gate), 366a35f
(revisit budget + pv line). Write-up will be `docs/experiments/hintbench/exp6.md`.

### 150. What will be run (pre-registration)

Four arms, run **in this order**, one at a time, control first because it
validates the retry policy before treatment arms spend time:

| arm | run id | `--explore-revisit` | `--pv-untried` |
|---|---|---|---|
| control | exp6-ctl | 0 | off |
| revisit | exp6-rev | 1 | off |
| pv | exp6-pv | 0 | on |
| both | exp6-both | 1 | on |

Command template (fill the two flags per arm):

```
export TARGET=hintbench
scripts/jev_search.py --target hintbench \
    --marks targets/hintbench/jev-marks.txt \
    --sites artifacts/hintbench-sites/sites.json \
    --site-set oracle.selected_keys_loop_hint_kernels \
    --proposer jev --rounds 5 --vocab v5 --readout forced_top1 \
    --source-comments strip --explore 2 --explore-revisit R --pv-untried X \
    -n 15 --warmup 3 \
    --baseline-dir artifacts/hintbench-sites/baseline \
    --measure-holdout --out artifacts/hintbench-search/<run id>
scripts/bench_panel.sh artifacts/hintbench-search/<run id>/holdout-batch2 15 3 20260927 \
    base=artifacts/hintbench-sites/baseline/bin \
    cand=artifacts/hintbench-search/<run id>/<best round>/bin \
    aa=artifacts/hintbench-sites/baseline/bin
scripts/hintbench_exp4_score.py run artifacts/hintbench-search/<run id>
```

**Frozen and identical to Exp5**: marks, the site set (8 functions + 4 loops,
`oracle.selected_keys_loop_hint_kernels`), k1..k8, n=15, warmup 3, shuffle
seed 20260921 + round, `taskset -c 8`, gap 0 ms, bootstrap 10000,
`--readout forced_top1`, `--source-comments strip`, `--explore 2`, no-op
skip on, and the baseline binary --- `.text` sha256 `df5968bc…`, whole
binary `07498197…`, byte-identical to Experiment 4's and Experiment 5's
manifests. The plugin is unchanged since Exp5, so the baseline is reused
from `artifacts/hintbench-sites/baseline`, not rebuilt.

**Differs from Exp5 in EVERY arm**: vocabulary v5 (= v4 minus the three
`align` candidates and `unroll_disable`, all measured dead or duplicate in
the oracle sweep, §118–128 --- so the oracle reference +8.8% combination
stays the comparison point); the state format --- `state-v5.0-2026-09-23`
(v4.2's template, unchanged, af01508) for the `--pv-untried off` arms
(ctl, rev) and `state-v5.1-2026-09-23` (366a35f) for the `on` arms (pv,
both); `off` renders byte-identical state to v5.0, which is what makes
pv − ctl a clean single-factor comparison; the 503 retry policy and round
gate (decision 92 d, commit b489e5d, `[jev]` keys `request_timeout_s`
(20 s), `retries` (200), `retry_wall_budget_s` (600 s), `backoff_cap_s`
(5.0 s), `phase_resend_max` (2)). Therefore **exp6-ctl vs Exp5 is not a
clean comparison** (vocabulary, state format and gateway all changed
between them); the comparisons that are attributable are within Exp6 (arm
vs exp6-ctl) and against the oracle.

### 151. Rules, stated before the numbers

1. Headline per arm: the best accepted plan's training ratio
   (holdout-as-search, as Exp4/5) plus the driver's confirmation batch, plus
   one `bench_panel.sh` batch (seed 20260927). The A/A leg of that batch
   must lie within ±0.5%; otherwise the batch is retaken once and both are
   reported (Exp5 §147 precedent).
2. Per-feature effects (non-negotiable 4): rev − ctl, pv − ctl, both − ctl,
   and the interaction (both − rev − pv + ctl), on the headline ratio. The
   oracle's batch-to-batch null panel is 0.17 pt; a difference under 0.5 pt
   is reported as within noise, not as an effect.
3. Mechanism checks for the revisit arms (recorded from `rounds.jsonl`,
   pass/fail): (a) the k8 loop is asked at least twice by round 4;
   (b) `vectorize.width=16` is chosen at k8 in some round; (c) it is kept
   in the final plan. (a) without (b) means the budget works and Jev does
   not re-rank; (b) without (c) means the speed gate or a later round
   dropped it.
4. Mechanism check for the pv arms: at k8, the P assigned to
   `vectorize_width_16` in the round-1 phase-B answer versus Exp5's 0.01
   and exp6-ctl's value.
5. Gateway rule: an arm in which more than 2 of its 10 phase requests
   (A and B × 5 rounds) end `lost` is invalid and re-run once under the
   same run id suffix `-b`; both are recorded. Lost explore requests are
   recorded and do not invalidate. Attempts, landed, and mean body bytes
   per phase are reported from the manifest's `gateway.attempts_by_phase`.
6. Correctness gate as always: any plan whose output differs from baseline
   is rejected; every arm carries `-Cllvm-args=-hints-allow-reordering=false`.
7. The 12-site score (`hintbench_exp4_score.py`) is context, not headline
   (8 of 12 truths are `KEEP_DEFAULT`; §148).
8. Random control: not re-run; Exp4's 0% stands (random already draws
   non-`KEEP_DEFAULT` candidates; the revisit budget applies to
   `--proposer jev` only).
9. Nothing in this section is edited after the first arm starts;
   corrections go in later sections.

### 152. exp6-ctl

Command run (the §150 template with the control arm's two flags filled in):

```
export TARGET=hintbench
scripts/jev_search.py --target hintbench \
    --marks targets/hintbench/jev-marks.txt \
    --sites artifacts/hintbench-sites/sites.json \
    --site-set oracle.selected_keys_loop_hint_kernels \
    --proposer jev --rounds 5 --vocab v5 --readout forced_top1 \
    --source-comments strip --explore 2 --explore-revisit 0 --pv-untried off \
    -n 15 --warmup 3 \
    --baseline-dir artifacts/hintbench-sites/baseline \
    --measure-holdout --out artifacts/hintbench-search/exp6-ctl
scripts/bench_panel.sh artifacts/hintbench-search/exp6-ctl/holdout-batch2 15 3 20260927 \
    base=artifacts/hintbench-sites/baseline/bin \
    cand=artifacts/hintbench-search/exp6-ctl/round-02/bin \
    aa=artifacts/hintbench-sites/baseline/bin
scripts/hintbench_exp4_score.py run artifacts/hintbench-search/exp6-ctl
```

`run-manifest.json`: `exploration.revisit: 0`, `exploration.pv_untried: "off"`,
`vocab_version: "v5-2026-09-23"`, `state_format: "state-v5.0-2026-09-23"`,
`baseline_bin_sha256` `07498197…`, matching §150's frozen baseline. Wall
clock: Jev requests span 15:29:35–15:50:47 JST
(`jev-log/exp6-ctl.log`); the full run including holdout, `wall_s` in
`run-manifest.json`, **1730.9 s (28.8 min)**.

**The rounds** (`rounds.jsonl`; phase entries from each round's `choices`,
cross-checked against `exp6-ctl-run.log`; explored sites from each phase's
`exploration.eligible_new`):

| round | phase A picks | phase B picks | explored this round | ratio | 95% CI | confirm | A/A (in-run) | accepted |
|---|---|---|---|--:|---|--:|--:|---|
| 1 | k2, k4, k5, k6 `inline(always)` (k4, k5 via explore) | k4 loop `vectorize.width=16`, k5 loop `unroll.count=8` (explore), k8 loop `unroll.count=2` (explore) | A: k4, k5 fn; B: k5, k8 loop | 0.9978 | [0.9950, 1.0006] | not triggered | 0.9979 ±0.0036 | no |
| **2** | k2, k3, k6, k8 `inline(always)` (k8, k3 via explore) | k3 loop `unroll.count=2` (`forced_top1`, all-`KEEP` phase, P(hint)=0.21) | A: k8, k3 fn | **1.0742** | [1.0680, 1.0808] | **1.0776** [1.0731, 1.0823] | 0.9991 ±0.0067 | **yes** |
| 3 | k1, k2, k6, k7 `inline(always)` (k1, k7 via explore) | k3 loop `unroll.count=2` (direct pick, not forced — p_keep 0.04) | A: k1, k7 fn | 1.0744 | [1.0720, 1.0767] | 1.0711 [1.0584, 1.0787] | 0.9999 ±0.0029 | no |
| 4 | k2, k6 `inline(always)` | k3 loop `unroll.count=2` (direct pick, not forced — p_keep 0.05) | none eligible | 1.0766 | [1.0718, 1.0816] | 1.0777 [1.0750, 1.0804] | 1.0009 ±0.0040 | no |
| 5 | k2, k6 `inline(always)` | k3 loop `unroll.count=2` (direct pick, not forced — p_keep 0.05) | none eligible | 1.0752 | [1.0727, 1.0784] | 1.0766 [1.0732, 1.0798] | 1.0016 ±0.0017 | no |

Every round: output correct, every plan entry applied, no `ambiguous`, no
`vanished`, no `unmatched` (`rounds.jsonl`, `apply` fields; also stated in
`exp6-ctl-run.log` as `[B] correctness: OK` for every round). Round 1's k4
loop pick, `vectorize.width=16`, measured **0.5813** on its own workload
(`rounds.jsonl` round 1 `per_workload.k4.ratio`) — the same harmful site and
near-identical magnitude as Exp5's round 1 (§144: 0.5823, oracle 0.5793 for
that candidate) — and the score (below) marks it `harmful`; round 1's own
aggregate ratio stayed at 0.9978 and the round was not accepted.

**Rounds 3–5 were not accepted although their point ratios (1.0744, 1.0766,
1.0752) all read above round 2's (1.0742).** `summary.md`'s stated
acceptance rule is that a round becomes the new best only if its plan
differs from the incumbent's **and the lower end of its 95% CI is above
the best point estimate so far**. Round 2's point estimate is 1.07424; the
three later rounds' CI lower bounds are 1.07203 (round 3), 1.07176 (round
4) and 1.07268 (round 5) — all below 1.07424 (`rounds.jsonl`, `ci95[0]`
per round) — so none cleared the bar, and `rounds.jsonl` records
`accepted: false` with `same_plan_as_best: false` for all three (their
plans are genuinely different: round 3 adds k1/k7 `inline(always)` in
place of k8/k3; rounds 4–5 drop back to k2/k6 alone). `exp6-ctl-run.log`
prints `[accept] round 2 is the new best (1.0742)` once and never again.

**Best plan (round 2), per case** (`rounds.jsonl` round 2 `per_workload`):

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| ratio | 0.9996 | **1.6920** | 1.0338 | 1.0095 | 1.0046 | 1.0014 | 0.9968 | 1.0020 |

Plan (`best-plan.json`): k2, k6 fn `inline(always)` (`jev_readout: argmax`,
`answer_ref exp6-ctl.jsonl#5`); k3, k8 fn `inline(always)` (`jev_readout:
exploration`, `exploration: true`, `#6`); k3 loop `unroll.count=2`
(`jev_readout: forced_top1`, `#7`). Basis sha256 `b7262c6e…`.

**Holdout**: ratio **1.0735**, 95% CI [1.0709, 1.0759], in-run A/A 0.9998
±0.0032, MDE 0.0300 (`run-manifest.json` `holdout` block; `summary.md`
`[holdout] ratio 1.0735 CI [1.0709, 1.0759]`, measured once on round 2
after it was frozen as best).

**Batch 2** (`artifacts/hintbench-search/exp6-ctl-batch2.log`, seed
20260927, produced by `bench_panel.sh` after this write-up started,
finished before it did):

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | [1.0000, 1.0000] | 0.00% |
| **aa** | **0.9875** | [0.9857, 0.9892] | 0.18% |
| cand | 1.0751 | [1.0718, 1.0783] | 0.32% |

Per case, cand vs aa (`exp6-ctl-batch2.log`):

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| cand | 1.0040 | **1.6973** | 1.0353 | 1.0061 | 0.9976 | 1.0000 | 0.9978 | 1.0105 |
| aa | 1.0022 | 0.9993 | 1.0012 | 1.0020 | **0.9146** | 1.0004 | 1.0006 | **0.9829** |

**The ±0.5% rule (§151 rule 1) did not hold.** The A/A leg reads 0.9875, a
−1.25% deviation with a tight 0.18% half-width (its 95% CI, [0.9857,
0.9892], excludes 1.0000) — well outside ±0.5%. The deviation is not one
outlier case: `aa`/k5 (0.9146) and `aa`/k8 (0.9829) are both off, in the
same direction, while the other six `aa` cases sit within 0.3% of 1.0. Per
rule 1 this batch is to be retaken once with both reported; **that retake
was not run for this section** — this write-up's scope excludes running
`bench_panel.sh`, and `exp6-rev` (the next pre-registered arm) had already
started on the machine by the time batch 2 finished, so a same-machine
retake could not be taken without violating the single-benchmark-at-a-time
rule. Batch 2 is reported above with this rejection stated, not silently
accepted as a headline number; a retake is owed before batch 2's `cand`
number (1.0751) is used anywhere as confirmed.

**Gateway** (`run-manifest.json` `gateway.attempts_by_phase`; per-phase
seconds waiting summed from each round's `phase_a.gate` / `phase_b.gate`
in `rounds.jsonl`, which foot to the manifest's total):

| phase | requests | attempts | landed | mean body bytes | seconds waiting |
|---|--:|--:|--:|--:|--:|
| A | 5 | 50 | 5 | 70655.4 | 90.609 |
| B | 5 | 22 | 5 | 48206.2 | 34.042 |
| explore | 4 | 4 | 4 | 21566.5 | 0.000 |
| **total** | **14** | **76** | **14** | — | **124.651** |

`lost_phases: 0`, `lost_rounds: 0` (`run-manifest.json`) — **0 of 10 phase
requests lost**, against Exp5's 5 of 10 (§149). Rule 5's threshold (>2 of
10 lost invalidates the arm) is not approached; no re-run under `-b` is
needed. Every 503 was absorbed by the round's own resend/backoff (up to 20
attempts on round 2's phase A, `exp6-ctl.log` line `r2 A`) inside the
600 s wall budget, not by losing the phase.

**k8 mechanism check (rule 4 baseline)**: at k8, round 1's phase-B
exploration sub-request (`jev-log/exp6-ctl.jsonl` line 4, phase
`B.explore`, site `e1` = `hbkernels::k8_scale_add@range.rs:1103:12#d2`)
assigned **P(vectorize_width_16) = 0.01** (`choice: "unroll_count_2"`,
`probabilities.vectorize_width_16: 0.01`, tied for last among the 10
untried candidates offered — `unroll_count_2` 0.23, `unroll_count_8` 0.21,
`vectorize_width_8` 0.16, `interleave_count_1` 0.12, `interleave_count_2`
0.11, `unroll_count_4` 0.09, `vectorize_width_4` 0.05, then a three-way
tie at 0.01 for `interleave_count_4`, `vectorize_width_16`,
`vectorize_width_2`). This matches Exp5's 0.01 (§145) to two decimals —
expected, since `--pv-untried off` renders state byte-identical to Exp5's
format (§150) — and is the number the pv/both arms are meant to move. (The
same round's main, non-explore phase-B request had already spent k4's
loop on `vectorize.width=16` at P 0.49 against `KEEP_DEFAULT` 0.39 — a
different site, not k8 — before the explore sub-request ran; k8 itself
was never asked again after round 1, since `exploration_sites` makes a
site ineligible once any candidate has been tried there, same as Exp5.)

**Score** (`scripts/hintbench_exp4_score.py run artifacts/hintbench-search/exp6-ctl`,
context per §151 rule 7, not headline):

| round | exact | same-family | miss | harmful | ratio | share of the combination (training) |
|---|--:|--:|--:|--:|--:|--:|
| 1 | 5 | 0 | 7 | **1** | 0.9978 | −2.5% |
| **2** | **7** | **1** | **4** | **0** | **1.0742** | **84.27%** |
| 3 | 7 | 1 | 4 | 0 | 1.0744 | 84.42% |
| 4 | 9 | 1 | 2 | 0 | 1.0766 | 86.96% |
| 5 | 9 | 1 | 2 | 0 | 1.0752 | 85.39% |

Combination's own training ratio, for scale: **1.0881** (`combination_training`
in the score output, = the oracle's +8.8%). Round 2's (accepted) four
misses are `inline(always)` at k3, k6 and k8 fn (truth `KEEP_DEFAULT` at
all three) and `KEEP_DEFAULT` at the k8 loop (truth `vectorize_width_16`,
the +8.8%); its one same-family pick is `unroll.count=2` at the k3 loop
against the truth `unroll.count=4`. As in Exp5, the k8 loop miss is the
entire remaining gap to the combination.

**What this arm establishes.** `exp6-ctl` runs the identical mechanism to
Exp5 (`--explore-revisit 0 --pv-untried off`, i.e. no revisit budget, no
`post_vectorize` untried line) under vocabulary v5 and the new 503
retry/round-gate policy (decision 92 d). The gateway fix is confirmed
working on its own terms: 14 of 14 requests landed, 0 phases lost, where
Exp5 lost 5 of 10. The best accepted plan (round 2, ratio 1.0742, confirm
1.0776, holdout 1.0735) is close to Exp5's accepted plan's numbers
(training 1.0741, confirm 1.0740, third batch 1.0724, §144/§147), but
**that comparison is not attributable** per §150's pre-registered caveat:
vocabulary v5, state format `state-v5.0-2026-09-23`, and the gateway
policy all changed between Exp5 and every arm of Exp6, so exp6-ctl vs
Exp5 conflates those three changes and is not a clean before/after. What
is attributable is *within* Exp6: exp6-ctl is the baseline the revisit and
pv arms (§150) are measured against, and it reproduces the two
load-bearing facts from Exp5 under the new gateway and vocabulary — the
k4-loop harmful pick at round 1 (0.5813 vs Exp5's 0.5823) and the
k8-loop `vectorize_width_16` exploration P of 0.01 (identical to Exp5's
0.01, §145). Rounds 3–5 had nominally higher point
ratios than round 2 but none was accepted, because none cleared the
pre-registered CI-lower-above-incumbent-point bar (all three CI lower
bounds sit below round 2's 1.07424); this is the driver's acceptance rule
working as designed, not a null result about those rounds' plans. Batch 2's
A/A leg failed the pre-registered ±0.5% check and is reported rejected,
with the required retake not yet taken (out of this write-up's scope).

### 153. exp6-rev

Command run (the §150 template with the revisit arm's two flags filled in):

```
export TARGET=hintbench
scripts/jev_search.py --target hintbench \
    --marks targets/hintbench/jev-marks.txt \
    --sites artifacts/hintbench-sites/sites.json \
    --site-set oracle.selected_keys_loop_hint_kernels \
    --proposer jev --rounds 5 --vocab v5 --readout forced_top1 \
    --source-comments strip --explore 2 --explore-revisit 1 --pv-untried off \
    -n 15 --warmup 3 \
    --baseline-dir artifacts/hintbench-sites/baseline \
    --measure-holdout --out artifacts/hintbench-search/exp6-rev
scripts/bench_panel.sh artifacts/hintbench-search/exp6-rev/holdout-batch2 15 3 20260927 \
    base=artifacts/hintbench-sites/baseline/bin \
    cand=artifacts/hintbench-search/exp6-rev/round-03/bin \
    aa=artifacts/hintbench-sites/baseline/bin
scripts/hintbench_exp4_score.py run artifacts/hintbench-search/exp6-rev
```

`run-manifest.json`: `exploration.revisit: 1`, `exploration.max_visits: 2`,
`exploration.revisit_text: "r1"`, `exploration.pv_untried: "off"`,
`vocab_version: "v5-2026-09-23"`, `state_format: "state-v5.0-2026-09-23"`,
`baseline_bin_sha256` `07498197…`, matching §150's frozen baseline (byte
identical to exp6-ctl's, §152). Wall clock: Jev requests span
16:03:29–16:25:48 JST (`jev-log/exp6-rev.log`); the full run including
holdout, `wall_s` in `run-manifest.json`, **1822.8 s (30.4 min)**.

**The rounds** (`rounds.jsonl`; `phase_a`/`phase_b.choices` for the picks
columns; `phase_a`/`phase_b.exploration.pick_detail` for the explored
column, `kind` and `visit_no` fields):

| round | phase A picks | phase B picks | explored this round (new / revisit, visit_no) | ratio | 95% CI | confirm | A/A (in-run) | accepted |
|---|---|---|---|--:|---|--:|--:|---|
| **1** | k2, k4, k5, k6 `inline(always)` (k4, k5 via explore) | k4 loop `vectorize.width=16` (`forced_top1`, 1-P(KEEP)=0.510), k5 loop `unroll.count=8` (explore), k8 loop `unroll.count=2` (explore) | A: k5, k4 fn (new, v1); B: k5, k8 loop (new, v1) | 1.0029 | [1.0004, 1.0056] | 1.0319 [1.0298, 1.0340] | 1.0019 ±0.0029 | **yes** |
| 2 | k2, k3, k6, k8 `inline(always)` (k3, k8 via explore), k5 `inline(never)` (revisit) | k4 loop `vectorize.width=16`, k8 loop `unroll.count=2`, k3 loop `unroll.count=4` (explore) | A: k8, k3 fn (new, v1); k5 fn (revisit, v2); B: k3 loop (new, v1) | 1.0045 | [1.0013, 1.0075] | 1.0072 [1.0037, 1.0106] | 1.0021 ±0.0021 | no |
| **3** | k1, k2, k6, k7 `inline(always)` (k1, k7 via explore), k4 `inline(never)` (revisit) | k5 loop `unroll.count=8`, k8 loop `unroll.count=2`, k3 loop `unroll.count=2` (revisit) | A: k1, k7 fn (new, v1); k4 fn (revisit, v2); B: k3 loop (revisit, v2) | **1.0780** | [1.0750, 1.0810] | **1.1082** [1.1055, 1.1111] | 1.0001 ±0.0024 | **yes** |
| 4 | k1, k2, k6 `inline(always)`, k8 `inline(never)` (revisit) | k5 loop `unroll.count=8`, k4 loop `vectorize.width=16`, k3 loop `unroll.count=2` (all argmax, no explore) | A: k8 fn (revisit, v2); B: none eligible | 1.0074 | [1.0051, 1.0098] | 1.0354 [1.0330, 1.0378] | 1.0012 ±0.0030 | no |
| 5 | k2, k6 `inline(always)`, k3 `inline(never)` (revisit) | k5 loop `unroll.count=8`, k4 loop `vectorize.width=16`, k8 loop `unroll.count=2` (all argmax, no explore) | A: k3 fn (revisit, v2); B: none eligible | 0.9911 | [0.9877, 0.9944] | 1.0181 [1.0145, 1.0218] | 1.0018 ±0.0030 | no |

Every round: output correct, every plan entry applied, no `ambiguous`, no
`vanished`, no `unmatched` (`rounds.jsonl`, `apply` fields; `exp6-rev-run.log`
prints `[B] correctness: OK` for all five rounds). `exp6-rev-run.log` prints
`[accept]` exactly twice: `round 1 is the new best (1.0029)` and `round 3 is
the new best (1.0780)`; rounds 2, 4 and 5 are recorded `accepted: false` in
`rounds.jsonl` (round 2's plan differs from round 1's but its ratio, 1.0045,
does not clear round 1's CI-lower bar in the way round 3's does; round 5's
point ratio, 0.9911, sits below baseline).

**Revisit mechanism checks (§151 rule 3), evidence from `rounds.jsonl`**
(`phase_a`/`phase_b.exploration.asked`/`.pick_detail`, `kind`, `visit_no`,
`eligible_new`, `eligible_revisit`) and `exp6-rev-run.log`'s `[A.explore]`/
`[B.explore]` lines:

**(a) Was the k8 loop (`hbkernels::k8_scale_add@range.rs:1103:12#d2`) asked
at least twice by round 4? FAIL.** It appears in a `B.explore` request
exactly once, round 1 (`kind: "new"`, `visit_no: 1`, `exp6-rev-run.log`
line 12: `[B.explore] hbkernels::k8_scale_add @ range.rs:1103: nothing has
been tried here; trying unroll.count=2`). In every later round its
`phase_b.exploration.eligible_revisit` list is empty (rounds 2 and 3) or
the whole exploration block is empty (rounds 4, 5) — the site never
qualifies. Per `docs/search-driver.md`'s revisit-eligibility rule, a site
is eligible only if "this round's own argmax answer there is
`KEEP_DEFAULT`"; the k8 loop's main `phase_b.choices` answer is
`unroll_count_2` in every round it exists (1, 2, 3, 5) — never
`KEEP_DEFAULT` again after round 1 — so the first eligibility clause is
never met and the revisit budget (`--explore-revisit 1`, `max_visits: 2`)
never gets a slot to spend there. (Rounds 4 and 5's `phase_b.exploration`
is empty because the round's own site list left nothing meeting any
eligibility clause, new or revisit, not specifically the k8 loop.)

**(b) Was `vectorize.width=16` chosen at k8 in any round? FAIL.** The k8
loop's only exploration answer (round 1, `jev-log/exp6-rev.jsonl` line 4,
site `e1`) picked `unroll_count_2` at P 0.23; the full distribution offered
`unroll_count_8` 0.18, `interleave_count_2` 0.14, `interleave_count_1` 0.14,
`vectorize_width_8` 0.14, `unroll_count_4` 0.08, `vectorize_width_4` 0.06,
`vectorize_width_16` **0.01**, `vectorize_width_2` 0.01, `interleave_count_4`
0.01 — matching exp6-ctl's 0.01 at the same site (§152) and Exp5's 0.01
(§145) to two decimals, as expected since this arm's state format is also
`state-v5.0-2026-09-23` (§150). Every subsequent main-phase answer at k8
(rounds 2, 3, 5) stayed `unroll_count_2` (`rounds.jsonl` `phase_b.choices`);
`vectorize_width_16` is never chosen there in this run.

**(c) Is it kept in the final plan? FAIL (moot, since (b) never fired).**
`best-plan.json`'s `loop_md` entry for
`hbkernels::k8_scale_add@range.rs:1103:12#d2` is `unroll_count_2`
(`jev_readout: "argmax"`, `answer_ref: "exp6-rev.jsonl#11"`), not
`vectorize_width_16`.

**Every revisit question asked** (`kind: "revisit"` in `pick_detail`;
site, round, candidates offered, pick, P; and what happened to its round):

| round | phase | site | tried before | candidates offered | pick | P | round accepted? | in final plan? |
|---|---|---|---|---|---|--:|---|---|
| 2 | A | `fn:hbkernels::k5_mul_reduce` | `inline_always` | `inline_never` (1) | `inline_never` | 1.00 | no (ratio 1.0045) | no |
| 3 | A | `fn:hbkernels::k4_count_bytes` | `inline_always` | `inline_never` (1) | `inline_never` | 1.00 | **yes** | **yes** (`k4_count_bytes: inline(never)`) |
| 3 | B | `hbkernels::k3_fill_run@lib.rs:174:9#d3` | `unroll_count_4` | `unroll_count_2`, `unroll_count_8`, `vectorize_width_2/4/8/16`, `interleave_count_1/2/4` (9) | `unroll_count_2` | 0.60 | **yes** | **yes** (`k3 loop: unroll.count=2`) |
| 4 | A | `fn:hbkernels::k8_scale_add` | `inline_always` | `inline_never` (1) | `inline_never` | 1.00 | no (ratio 1.0074) | no |
| 5 | A | `fn:hbkernels::k3_fill_run` | `inline_always` | `inline_never` (1) | `inline_never` | 1.00 | no (ratio 0.9911) | no |

Every function-attribute revisit has exactly one candidate left
(`inline_always`/`inline_never` is a 2-way vocabulary and the first value
was already tried), so its P is trivially 1.00; the k3 loop's phase-B
revisit (round 3) is the only revisit question with a real ranking (9
candidates), and both its pick and round 3's phase-A revisit pick
(`k4_count_bytes: inline_never`) ended up in the accepted, final plan.

**Best plan (round 3), per case** (`rounds.jsonl` round 3 `per_workload`):

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| ratio | 0.9991 | **1.6997** | 1.0368 | 1.0095 | 1.0226 | 1.0047 | 1.0026 | 0.9958 |

Plan (`best-plan.json`, `plan_id: "r3-b"`): k2, k6 fn `inline(always)`
(`jev_readout: argmax`, `answer_ref exp6-rev.jsonl#9`); k1, k7 fn
`inline(always)`, k4 fn `inline(never)` (`jev_readout: exploration`,
`exploration: true`, `#10`); k5 loop `unroll.count=8`, k8 loop
`unroll.count=2` (`jev_readout: argmax`, `#11`); k3 loop `unroll.count=2`
(`jev_readout: exploration`, `#12`). Basis sha256 `5594b6a6…`.

**Holdout**: ratio **1.0812**, 95% CI [1.0774, 1.0849], in-run A/A 0.9987
±0.0044, MDE 0.0401 (`run-manifest.json` `holdout` block; `exp6-rev-run.log`
`[holdout] ratio 1.0812 CI [1.0774, 1.0849]`, measured once on round 3 after
it was frozen as best).

**Batch 2** (`artifacts/hintbench-search/exp6-rev-holdout-batch2.log`, seed
20260927, already produced by `bench_panel.sh` before this write-up
started):

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | [1.0000, 1.0000] | 0.00% |
| **aa** | **0.9864** | [0.9842, 0.9885] | 0.21% |
| cand | 1.1083 | [1.1056, 1.1109] | 0.27% |

Per case, cand vs aa (`exp6-rev-holdout-batch2.log`):

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| cand | 1.0009 | **1.6959** | 1.0342 | 1.0159 | **1.2857** | 1.0000 | 0.9986 | 0.9941 |
| aa | 1.0027 | 1.0019 | 0.9967 | 1.0050 | **0.9187** | 0.9997 | 0.9951 | **0.9747** |

**The ±0.5% rule (§151 rule 1) did not hold, the same way it did not hold
for exp6-ctl's original batch 2 (§152).** The A/A leg reads 0.9864, a
−1.36% deviation, 95% CI [0.9842, 0.9885] excluding 1.0000. As in ctl's
batch, the deviation concentrates on `aa`/k5 (0.9187, −8.13%) and `aa`/k8
(0.9747, −2.53%), both below 1 by roughly the same order of magnitude as
ctl's k5 (0.9146, −8.54%) and k8 (0.9829, −1.71%, §152), while the other six
`aa` cases deviate at most 0.50% (k4). Per rule 1 this batch is owed a
retake with both reported; that retake was not run for this section, for
the same reason as ctl's (out of this write-up's scope, which excludes
running `bench_panel.sh`; §154 covers only the ctl retake the owner
scheduled). Batch 2 is reported above with this rejection stated; its
`cand` number (1.1083) is not to be used anywhere as confirmed until a
retake is taken.

**Gateway** (`run-manifest.json` `gateway.attempts_by_phase`; per-phase
seconds waiting summed from each round's `phase_a.gate` / `phase_b.gate` and
`.exploration.gate` in `rounds.jsonl`, which foot to the manifest's total):

| phase | requests | attempts | landed | mean body bytes | seconds waiting |
|---|--:|--:|--:|--:|--:|
| A | 5 | 31 | 5 | 71180.6 | 52.743 |
| B | 5 | 8 | 5 | 39586.8 | 6.042 |
| explore | 8 | 10 | 8 | 20201.8 | 3.903 |
| **total** | **18** | **49** | **18** | — | **62.688** |

`lost_phases: 0`, `lost_rounds: 0` (`run-manifest.json`) — **0 of 18
requests lost** (10 phase requests A+B, 8 explore requests: A.explore fired
in every round, B.explore fired in rounds 1–3 only, none in 4–5 since no
site was eligible there). Rule 5's threshold (>2 of 10 phase requests lost
invalidates the arm) is not approached; no re-run under `-b` is needed.
`exp6-rev-run.log` shows every 503 absorbed by the round's own resend/
backoff (up to 12 attempts on round 4's phase A) inside the 600 s wall
budget.

**Score** (`scripts/hintbench_exp4_score.py run artifacts/hintbench-search/exp6-rev`,
context per §151 rule 7, not headline):

| round | exact | same-family | miss | harmful | ratio | share of the combination (training) |
|---|--:|--:|--:|--:|--:|--:|
| 1 | 5 | 0 | 7 | 1 | 1.0029 | 3.26% |
| 2 | 5 | 0 | 6 | 2 | 1.0045 | 5.09% |
| **3** | **4** | **1** | **6** | **0** | **1.0780** | **88.48%** |
| 4 | 5 | 1 | 5 | 1 | 1.0074 | 8.39% |
| 5 | 6 | 0 | 5 | 2 | 0.9911 | −10.08% |

Combination's own training ratio, for scale: **1.0881** (`combination_training`
in the score output, = the oracle's +8.8%, identical to exp6-ctl's, §152).
Round 3's (accepted) four function-attribute misses are `inline(always)` at
k1, k6, k7 (truth `KEEP_DEFAULT`) and `inline(never)` at k4 (truth
`KEEP_DEFAULT`); its two loop misses are `unroll.count=8` at k5 (truth
`KEEP_DEFAULT`) and `unroll.count=2` at k8 (truth `vectorize_width_16`,
the +8.8%, `pick_ratio` 1.0164 on k8's own workload against `truth_ratio`
1.0881); its one same-family pick is `unroll.count=2` at the k3 loop
against the truth `unroll.count=4`. As in exp6-ctl, the k8-loop miss is the
largest single remaining gap to the combination.

**What this arm establishes (§151 rule 2, rev − ctl on the headline).**
Against exp6-ctl (§152: training 1.0742, confirm 1.0776, holdout 1.0735):

| metric | exp6-ctl | exp6-rev | rev − ctl (points) | exceeds 0.5 pt noise bar? |
|---|--:|--:|--:|---|
| training (best round) | 1.0742 | 1.0780 | +0.38 | no |
| confirm | 1.0776 | 1.1082 | +3.06 | yes |
| holdout | 1.0735 | 1.0812 | +0.77 | yes |

The training-ratio delta (+0.38 pt) is under the oracle's 0.5 pt null-panel
bar and is reported within noise; the confirm and holdout deltas (+3.06 pt,
+0.77 pt) both exceed it. Rule 3's mechanism checks above establish that,
for this specific run, the revisit budget (`--explore-revisit 1`) did not
in fact reach the k8 loop a second time — (a), (b) and (c) all failed — so
any headline difference between rev and ctl in this run is not attributable
to the k8-loop mechanism the revisit budget was designed to fix.

### 154. exp6-ctl, batch 2 retaken

Per §151 rule 1, exp6-ctl's original batch 2 (§152) failed the ±0.5% A/A
check and is owed one retake, both reported. The retake command (the same
as §152's, into a `b`-suffixed directory):

```
scripts/bench_panel.sh artifacts/hintbench-search/exp6-ctl/holdout-batch2b 15 3 20260927 \
    base=artifacts/hintbench-sites/baseline/bin \
    cand=artifacts/hintbench-search/exp6-ctl/round-02/bin \
    aa=artifacts/hintbench-sites/baseline/bin
```

(`artifacts/hintbench-search/exp6-ctl-holdout-batch2b.log`, produced after
exp6-rev's own run finished, machine otherwise idle.)

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | [1.0000, 1.0000] | 0.00% |
| aa | **1.0002** | [0.9970, 1.0033] | 0.31% |
| cand | 1.0743 | [1.0712, 1.0770] | 0.29% |

Per case, cand vs aa (`exp6-ctl-holdout-batch2b.log`):

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| cand | 1.0005 | **1.6981** | 1.0372 | 1.0136 | 1.0027 | 0.9996 | 0.9964 | 0.9943 |
| aa | 1.0013 | 0.9990 | 0.9996 | 1.0062 | 0.9974 | 0.9994 | 0.9981 | 1.0010 |

**The ±0.5% rule held on this retake.** The A/A leg reads 1.0002, a +0.02%
deviation with a 0.31% half-width whose 95% CI, [0.9970, 1.0033], includes
1.0000. Unlike both original batch-2 runs (§152, §153), no per-case outlier
appears at k5 or k8 here (`aa`/k5 0.9974, `aa`/k8 1.0010, both within
0.30% of 1); every `aa` case in this retake sits within 0.65% of 1.0000
(worst: k4, 1.0062). `cand` reads 1.0743 [1.0712, 1.0770], consistent with
§152's training ratio (1.0742), confirm (1.0776) and original holdout
(1.0735) on the same round-02 binary. §152 stays as written; this section
records only the retake, as required by rule 1.

### 155. exp6-pv

Command run (the §150 template with the pv arm's two flags filled in):

```
export TARGET=hintbench
scripts/jev_search.py --target hintbench \
    --marks targets/hintbench/jev-marks.txt \
    --sites artifacts/hintbench-sites/sites.json \
    --site-set oracle.selected_keys_loop_hint_kernels \
    --proposer jev --rounds 5 --vocab v5 --readout forced_top1 \
    --source-comments strip --explore 2 --explore-revisit 0 --pv-untried on \
    -n 15 --warmup 3 \
    --baseline-dir artifacts/hintbench-sites/baseline \
    --measure-holdout --out artifacts/hintbench-search/exp6-pv
scripts/bench_panel.sh artifacts/hintbench-search/exp6-pv/holdout-batch2 15 3 20260927 \
    base=artifacts/hintbench-sites/baseline/bin \
    cand=artifacts/hintbench-search/exp6-pv/round-02/bin \
    aa=artifacts/hintbench-sites/baseline/bin
scripts/hintbench_exp4_score.py run artifacts/hintbench-search/exp6-pv
```

`run-manifest.json`: `exploration.revisit: 0`, `exploration.pv_untried: "on"`,
`vocab_version: "v5-2026-09-23"`, `state_format: "state-v5.1-2026-09-23"`,
`baseline_bin_sha256` `07498197…`, matching §150's frozen baseline (byte
identical to exp6-ctl's and exp6-rev's, §152/§153). Wall clock: Jev requests
span 17:07:58–17:30:23 JST (`jev-log/exp6-pv.log`); the full run including
holdout, `wall_s` in `run-manifest.json`, **1806.0 s (30.1 min)**.

**The rounds** (`rounds.jsonl`; `phase_a`/`phase_b.choices` for the picks
columns; `phase_a`/`phase_b.exploration.eligible_new`/`.pick_detail` for the
explored column; `exp6-pv-run.log` for the forced/direct wording):

| round | phase A picks | phase B picks | explored this round | ratio | 95% CI | confirm | A/A (in-run) | accepted |
|---|---|---|---|--:|---|--:|--:|---|
| 1 | k2, k4, k5, k6 `inline(always)` (k4, k5 via explore) | k4 loop `vectorize.width=16` (`forced_top1`, all-`KEEP` phase, 1−P(KEEP)=0.540, P(hint)=0.400), k5 loop `unroll.count=8` (explore), k8 loop `interleave.count=1` (explore) | A: k4, k5 fn; B: k5, k8 loop | 0.9681 | [0.9611, 0.9754] | 1.0147 [1.0038, 1.0271] | 1.0011 ±0.0030 | no |
| **2** | k2, k3, k6, k8 `inline(always)` (k8, k3 via explore) | k8 loop `interleave.count=1` (`forced_top1`, all-`KEEP` phase, 1−P(KEEP)=0.420, P(hint)=0.110), k3 loop `unroll.count=4` (explore) | A: k8, k3 fn; B: k3 loop | **1.0518** | [1.0427, 1.0607] | **1.0598** [1.0511, 1.0684] | 0.9998 ±0.0022 | **yes** |
| 3 | k1, k2, k6, k7 `inline(always)` (k1, k7 via explore) | k8 loop `interleave.count=1` (direct pick, not forced — P(KEEP_DEFAULT) 0.17), k3 loop `unroll.count=4` (direct pick, not forced — P(KEEP_DEFAULT) 0.04) | A: k1, k7 fn | 1.0500 | [1.0431, 1.0567] | 1.0630 [1.0544, 1.0712] | 0.9963 ±0.0039 | no |
| 4 | k2, k6 `inline(always)` | k8 loop `interleave.count=1` (direct pick, not forced — P(KEEP_DEFAULT) 0.19), k3 loop `unroll.count=4` (direct pick, not forced — P(KEEP_DEFAULT) 0.06) | none eligible | 1.0485 | [1.0392, 1.0579] | 1.0599 [1.0489, 1.0700] | 0.9991 ±0.0026 | no |
| 5 | k2, k6 `inline(always)` | k8 loop `interleave.count=1` (direct pick, not forced — P(KEEP_DEFAULT) 0.28), k3 loop `unroll.count=4` (direct pick, not forced — P(KEEP_DEFAULT) 0.05) | none eligible | 1.0496 | [1.0422, 1.0570] | 1.0583 [1.0493, 1.0672] | 1.0001 ±0.0018 | no |

Every round: output correct, every plan entry applied, no `ambiguous`, no
`vanished`, no `unmatched` (`rounds.jsonl`, `apply` fields; `exp6-pv-run.log`
prints `[B] correctness: OK` for all five rounds). `exp6-pv-run.log` prints
`[accept]` exactly once: `round 2 is the new best (1.0518)`. Unlike
exp6-ctl (§152) and exp6-rev (§153), rounds 3–5's own point ratios (1.0500,
1.0485, 1.0496) sit **below** round 2's point estimate (1.0518) already, so
the acceptance rule's CI-lower-bound test is not even reached; `rounds.jsonl`
records `accepted: false`, `same_plan_as_best: false` for all three, and
`exp6-pv-run.log` never prints a second `[accept]` line.

**Best plan (round 2), per case** (`rounds.jsonl` round 2 `per_workload`):

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| ratio | 1.0049 | **1.6983** | 1.0507 | 1.0046 | 1.0019 | 1.0029 | 1.0020 | **0.8259** |

Plan (`best-plan.json`): k2, k6 fn `inline(always)` (`jev_readout: argmax`,
`answer_ref exp6-pv.jsonl#5`); k3, k8 fn `inline(always)` (`jev_readout:
exploration`, `exploration: true`, `#6`); k8 loop `interleave.count=1`
(`jev_readout: forced_top1`, `#7`); k3 loop `unroll.count=4` (`jev_readout:
exploration`, `exploration: true`, `#8`). Basis sha256 `c03c73f8…`.

**Holdout**: ratio **1.0525**, 95% CI [1.0428, 1.0616], in-run A/A 0.9986
±0.0030, MDE 0.1081 (`run-manifest.json` `holdout` block; `exp6-pv-run.log`
`[holdout] ratio 1.0525 CI [1.0428, 1.0616]`, measured once on round 2 after
it was frozen as best).

**Batch 2** (`artifacts/hintbench-search/exp6-pv-holdout-batch2.log`, seed
20260927, produced by `bench_panel.sh` after this write-up started, finished
before it did):

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | [1.0000, 1.0000] | 0.00% |
| **aa** | **0.9846** | [0.9818, 0.9876] | 0.29% |
| cand | 1.0551 | [1.0452, 1.0642] | 0.95% |

Per case, cand vs aa (`exp6-pv-holdout-batch2.log`):

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| cand | 1.0029 | **1.6947** | 1.0415 | 1.0036 | 1.0008 | 1.0009 | 1.0073 | **0.8568** |
| aa | 0.9989 | 0.9961 | 0.9965 | 1.0015 | **0.9236** | 1.0019 | 0.9960 | **0.9652** |

**The ±0.5% rule (§151 rule 1) did not hold, the same way it did not hold
for exp6-ctl's and exp6-rev's original batch 2 (§152/§153).** The A/A leg
reads 0.9846, a −1.54% deviation, 95% CI [0.9818, 0.9876] excluding 1.0000.
As in both earlier batches, the deviation concentrates on `aa`/k5 (0.9236,
−7.64%) and `aa`/k8 (0.9652, −3.48%), the same two cases and the same
direction as ctl's (0.9146, 0.9829, §152) and rev's (0.9187, 0.9747, §153),
while the other six `aa` cases deviate at most 0.40% (k7: 0.9960). Per rule 1 this
batch is owed a retake with both reported. That retake was not run for this
section (out of this write-up's scope, which excludes running
`bench_panel.sh`); per the task instructions this is recorded as **retake
pending**, not waited on. `cand`'s number (1.0551) is not to be used
anywhere as confirmed until a retake is taken.

**Gateway** (`run-manifest.json` `gateway.attempts_by_phase`; per-phase
seconds waiting summed from each round's `phase_a.gate` / `phase_b.gate`
/ `.exploration.gate` in `rounds.jsonl`, which foot to the manifest's
total):

| phase | requests | attempts | landed | mean body bytes | seconds waiting |
|---|--:|--:|--:|--:|--:|
| A | 5 | 22 | 5 | 70657.6 | 35.276 |
| B | 5 | 14 | 5 | 49962.8 | 18.365 |
| explore | 5 | 8 | 5 | 20633.2 | 6.694 |
| **total** | **15** | **44** | **15** | — | **60.335** |

`lost_phases: 0`, `lost_rounds: 0` (`run-manifest.json`) — **0 of 10 phase
requests lost** (A+B ×5 rounds), same as exp6-ctl (§152) and exp6-rev
(§153). Rule 5's threshold (>2 of 10 lost invalidates the arm) is not
approached; no re-run under `-b` is needed. `exp6-pv-run.log` shows every
503 absorbed by the round's own resend/backoff inside the 600 s wall
budget (e.g. round 5 phase A: 1 failed attempt, 2.3 s waited, then HTTP
200).

**k8 mechanism check (§151 rule 4).** k8's loop was asked **twice** in
round 1 phase B: the main (non-explore) request (`jev-log/exp6-pv.jsonl`
line 3, phase `B`, site `q2` = `hbkernels::k8_scale_add@range.rs:1103:12#d2`)
and the exploration sub-request (`jev-log/exp6-pv.jsonl` line 4, phase
`B.explore`, site `e1` = the same site).

* **Main phase (q2, line 3)**: `choice: "KEEP_DEFAULT"`, confidence 0.78,
  `probabilities.vectorize_width_16: 0.00` (`KEEP_DEFAULT` 0.80). This
  request's state text is byte-identical to exp6-ctl's own main-phase-B
  round-1 request except the header's state-format string (verified by diff,
  both 13359 bytes on the k8-loop's B.explore twin, and 8-line/header-only
  diffs on rounds.jsonl-level state text for round 1's A, A.explore, B and
  B.explore phases); exp6-ctl's own main-phase q2 answer
  (`jev-log/exp6-ctl.jsonl` line 3) is `KEEP_DEFAULT` at confidence 0.78,
  `vectorize_width_16: 0.00` (`KEEP_DEFAULT` 0.80) — matching pv's to two
  decimals, as expected on byte-identical input.
* **Exploration sub-request (e1, line 4, the request whose answer is what
  the driver actually applies at k8, since k8 became newly eligible for
  exploration this round)**: `choice: "interleave_count_1"`, confidence
  0.13, **`probabilities.vectorize_width_16: 0.02`**. exp6-ctl's matching
  request (`jev-log/exp6-ctl.jsonl` line 4, same site) answered
  `choice: "unroll_count_2"` with `vectorize_width_16: 0.01` (§152); Exp5's
  was also 0.01 (§145). pv's 0.02 is one hundredth above ctl's 0.01.

  Full probability vector, side by side (`probabilities` field of each
  response, `e1`/round 1/`B.explore`):

  | candidate | exp6-pv P | exp6-ctl P |
  |---|--:|--:|
  | interleave_count_1 | **0.22** (chosen) | 0.12 |
  | unroll_count_2 | 0.16 | **0.23** (chosen) |
  | unroll_count_8 | 0.15 | 0.21 |
  | vectorize_width_4 | 0.14 | 0.05 |
  | interleave_count_2 | 0.14 | 0.11 |
  | unroll_count_4 | 0.08 | 0.09 |
  | vectorize_width_8 | 0.07 | 0.16 |
  | vectorize_width_16 | 0.02 | 0.01 |
  | vectorize_width_2 | 0.01 | 0.01 |
  | interleave_count_4 | 0.01 | 0.01 |

* **The exact pv line never appeared.** `--pv-untried on`'s mechanical
  sentence (`docs/search-driver.md` §"v5.1: the post_vectorize untried
  line", the one grep would find via `cost model picked`) is added only
  after a vectorized loop's `post_vectorize` width/interleave-count lines.
  A grep for `cost model picked` across the `state` field of **all 15**
  request bodies in `jev-log/exp6-pv.jsonl` returns **zero** matches; so do
  greps for `what LLVM did with this loop` and `vectorisation legality`
  (the `post_vectorize` block's own lead-in lines). Every one of this
  site set's four loops — including k8 — instead carries the pre-existing
  shared-source-line fallback in every request that asks about it. The k8
  state (`jev-log/exp6-pv.jsonl` line 4, request `state`, site `e1`) reads:

  > what LLVM said at range.rs:1103:12 in the baseline build --- CAUTION:
  > 18 different loops of this program were compiled at that one
  > location, so the lines below are their remarks pooled together and
  > none of them can be assigned to this loop:
  >   range.rs:1103: advising against unrolling the loop because it
  > contains a call
  >   range.rs:1103: loop not vectorized
  >   range.rs:1103: vectorized loop (vectorization width: 8, interleaved
  > count: 4)
  >   [... 6 more pooled remark lines ...]

  i.e. k8 (and the other three loops in this site set) has no
  plugin-recorded `post_vectorize` fact at this key, so the `--pv-untried
  on` sentence has nothing to attach to and never renders for this site
  set, this run. This is confirmed structurally, not just by the grep: a
  byte-for-byte diff of round 1's four phase requests (A, A.explore, B,
  B.explore) between exp6-pv and exp6-ctl shows the *only* difference is
  the header's state-format version string (`state-v5.1-2026-09-23` vs
  `state-v5.0-2026-09-23`) — the two arms' round-1 states are otherwise
  identical. The 0.01→0.02 shift in P(vectorize_width_16) at k8 is
  therefore not attributable to the pv-untried mechanism; it is
  run-to-run sampling variation on input the mechanism did not change.

* **Was `vectorize.width=16` picked at k8 in any round? No.** `k8 loop`'s
  answer in `phase_b.choices` is `interleave_count_1` in every round it is
  asked (1–5, `rounds.jsonl`); it never changes.
* **Is it in the best plan? No.** `best-plan.json`'s `loop_md` entry for
  `hbkernels::k8_scale_add@range.rs:1103:12#d2` is `interleave_count_1`
  (`jev_readout: "forced_top1"`, `answer_ref: "exp6-pv.jsonl#7"`).

**Score** (`scripts/hintbench_exp4_score.py run artifacts/hintbench-search/exp6-pv`,
context per §151 rule 7, not headline):

| round | exact | same-family | miss | harmful | ratio | share of the combination (training) |
|---|--:|--:|--:|--:|--:|--:|
| 1 | 5 | 0 | 7 | 2 | 0.9681 | −36.25% |
| **2** | **8** | **0** | **4** | **1** | **1.0518** | **58.82%** |
| 3 | 8 | 0 | 4 | 1 | 1.0500 | 56.71% |
| 4 | 10 | 0 | 2 | 1 | 1.0485 | 55.06% |
| 5 | 10 | 0 | 2 | 1 | 1.0496 | 56.30% |

Combination's own training ratio, for scale: **1.0881** (`combination_training`
in the score output, identical to exp6-ctl's and exp6-rev's, §152/§153).
Round 2's (accepted) four misses are `inline(always)` at k3, k6, k8 fn
(truth `KEEP_DEFAULT` at all three) and `interleave.count=1` at the k8 loop
(truth `vectorize_width_16`, the +8.8%, `pick_ratio` 0.8033 [0.7600, 0.8464]
on k8's own workload against `truth_ratio` 1.0881 — the one `harmful` entry,
same as exp6-ctl's round 2). Unlike exp6-ctl, this round's k3-loop pick
(`unroll_count_4`) is an **exact** match to the truth, not a same-family
miss — no `same-family` entries appear in any pv round's score.

**What this arm establishes (§151 rule 2, pv − ctl on the headline; and
the rule-4 answer above).** Against exp6-ctl (§152: training 1.0742,
confirm 1.0776, holdout 1.0735):

| metric | exp6-ctl | exp6-pv | pv − ctl (points) | exceeds 0.5 pt noise bar? |
|---|--:|--:|--:|---|
| training (best round) | 1.0742 | 1.0518 | −2.24 | yes |
| confirm | 1.0776 | 1.0598 | −1.78 | yes |
| holdout | 1.0735 | 1.0525 | −2.09 | yes |

All three deltas exceed the oracle's 0.5 pt null-panel bar, and all three
are negative: exp6-pv's headline sits below exp6-ctl's on training,
confirm and holdout alike. The rule-4 mechanism check above establishes
why the two arms differ here: not because `--pv-untried on` changed
anything at k8 (it did not — the pv line never rendered anywhere in this
run, and round 1's states are otherwise byte-identical to exp6-ctl's), but
because independent sampling at the k8-loop `B.explore` request happened
to draw `interleave_count_1` (harmful, `pick_ratio` 0.8033) in exp6-pv
instead of `unroll_count_2` (near-neutral, exp6-ctl's pick, §152) — a
difference in which non-`KEEP_DEFAULT` candidate the model's sampling
landed on at an equally-uninformed site, not a difference the
post_vectorize-untried sentence produced.

### 156. Correction to 155: the untried line WAS sent

§155's "the exact pv line never appeared" claim is wrong, and the bug is in
where it looked, not in the mechanism. `post_vectorize_lines()`
(`scripts/jev_search.py` ~2224, called ~2435) writes the added sentence into
each question's `instructions` (`request.questions[*].instructions`), not
into the shared `request.state`. §155 grepped `state` and `exp6-pv.log`
(the human-readable per-request summary, which never carries question
text) — both correctly return nothing, but neither is where the sentence
lives.

Re-verified directly:

```
$ grep -c "cost model picked" artifacts/hintbench-search/exp6-pv/jev-log/exp6-pv.jsonl
6
$ grep -c "cost model picked" artifacts/hintbench-search/exp6-pv/jev-log/exp6-pv.log
0
$ jq -r '.request.questions[]?.instructions' artifacts/hintbench-search/exp6-pv/jev-log/exp6-pv.jsonl \
    | grep -c "cost model picked"
34
```

The first grep (6) counts *requests* containing the phrase; the `jq`
version counts individual *copies* across all `questions[].instructions`
(one question can carry the sentence twice, once per vectorized-loop
metric). Per round/phase, via
`jq -r '[.round, .phase, (.request.questions[]?.instructions // "" | [scan("cost model picked")] | length)]'`
matched against the round/phase table in §155:

| round | phase | per-question copies | total |
|---|---|---|--:|
| 1 | B | 2, 2, 2, 0 (k5, k4, k8 = 2 each — width 8, interleave 4; k3 = 0, not vectorized) | 6 |
| 1 | B.explore | 2, 2 (k5, k8) | 4 |
| 2 | B | 2, 2, 2, 0 | 6 |
| 2 | B.explore | 0 (k3 only) | 0 |
| 3 | B | 2, 2, 2, 0 | 6 |
| 4 | B | 2, 2, 2, 0 | 6 |
| 5 | B | 2, 2, 2, 0 | 6 |
| **total** | | | **34** |

6 + 4 + 24 (4 × 6) + 0 = 34, matching the flat `jq` count above. k3 carries
"LLVM did NOT vectorize" instead and never gets the sentence; that is
correct behavior, not the bug.

One copy, verbatim (`jev-log/exp6-pv.jsonl`, round 1, phase `B.explore`,
site `e1`, the k8 loop):

> - 8 is the width LLVM's cost model picked for this loop with no hint; it
> is not a measurement of this program, and no other width has been
> measured at this loop in this run. Vocabulary values other than 8 not
> yet tried here: 2, 4, 16. None of them is being proposed over another.

ctl vs. pv, round 1, with the state-format header string normalized: phases
A and A.explore are identical in both `state` and `questions`; phases B and
B.explore are identical in `state`, and their `questions` differ from
ctl's only by the added lines above (no removals). exp6-ctl, exp6-rev and
Exp5 (`jev-v42-r5`) carry the v4.2 plugin fact line ("recorded by the
plugin itself") in every phase-B question instead (4/4, then 3/3 in rev's
rounds 2–5) and score 0 for "cost model picked", as expected — they are a
different plugin/site-set vintage, not a repeat of this bug.

**Corrected reading of §151 rule 4.** The untried-line sentence reached Jev
at k5, k4 and k8 in every phase-B request. `P(vectorize_width_16)` at k8 in
round 1 `B.explore` was 0.02 for exp6-pv vs. 0.01 for exp6-ctl vs. 0.01 for
Exp5 (§145); width 16 was never picked at k8 in any round. exp6-pv's
−2.2 pt vs. ctl on the headline (§155's closing table) is Jev's pick at
k8 (`interleave_count_1`, harmful, `pick_ratio` 0.8033) on a `B.explore`
question that differs from ctl's *only* by the added untried-line
sentence — so this is a **null result for the untried line as a discovery
aid** (it was sent, and did not move the pick toward `vectorize_width_16`
or away from the harmful pick), not a "line never sent" artefact as §155
concluded.

For the record, independent of the correction above: byte-identical inputs
(ctl's and pv's phase A / A.explore) and near-identical phase-B inputs
produced different picks across arms (§155's k8 `B.explore` probability
table) — single-run arms carry Jev's sampling variance on top of whatever
a feature does. That is stated here as an observation; the exp6 write-up
is where it gets interpreted.

§155 is left as written above, per the append-only rule.

For future write-ups checking whether driver-added text reached Jev: grep
`.request.questions[].instructions` in the `.jsonl`, not `.request.state`
and not the `.log`.

### 157. exp6-both

Command run (the §150 template with the both arm's two flags filled in):

```
export TARGET=hintbench
scripts/jev_search.py --target hintbench \
    --marks targets/hintbench/jev-marks.txt \
    --sites artifacts/hintbench-sites/sites.json \
    --site-set oracle.selected_keys_loop_hint_kernels \
    --proposer jev --rounds 5 --vocab v5 --readout forced_top1 \
    --source-comments strip --explore 2 --explore-revisit 1 --pv-untried on \
    -n 15 --warmup 3 \
    --baseline-dir artifacts/hintbench-sites/baseline \
    --measure-holdout --out artifacts/hintbench-search/exp6-both
scripts/bench_panel.sh artifacts/hintbench-search/exp6-both/holdout-batch2 15 3 20260927 \
    base=artifacts/hintbench-sites/baseline/bin \
    cand=artifacts/hintbench-search/exp6-both/round-04/bin \
    aa=artifacts/hintbench-sites/baseline/bin
scripts/hintbench_exp4_score.py run artifacts/hintbench-search/exp6-both
```

`run-manifest.json`: `exploration.revisit: 1`, `exploration.max_visits: 2`,
`exploration.revisit_text: "r1"`, `exploration.pv_untried: "on"`,
`vocab_version: "v5-2026-09-23"`, `state_format: "state-v5.1-2026-09-23"`,
`baseline_bin_sha256` `07498197…`, matching §150's frozen baseline (byte
identical to exp6-ctl's, exp6-rev's and exp6-pv's, §152/§153/§155). Wall
clock: Jev requests span 17:40:33–18:00:33 JST (`jev-log/exp6-both.log`,
first/last `2026-09-`-prefixed lines); the full run including holdout,
`wall_s` in `run-manifest.json`, **1659.9 s (27.7 min)**.

**The rounds** (`rounds.jsonl`; `phase_a`/`phase_b.choices` for the picks
columns; `phase_a`/`phase_b.exploration.pick_detail` for the explored
column, `kind` and `visit_no` fields; `exp6-both-run.log` for the
forced/direct wording):

| round | phase A picks | phase B picks | explored this round (new / revisit, visit_no) | ratio | 95% CI | confirm | A/A (in-run) | accepted |
|---|---|---|---|--:|---|--:|--:|---|
| 1 | k2, k4, k5, k6 `inline(always)` (k4, k5 via explore) | k4 loop `vectorize.width=16` (`forced_top1`, 1−P(KEEP)=0.510, P(hint)=0.350), k5 loop `unroll.count=8` (explore), k8 loop `interleave.count=1` (explore) | A: k5, k4 fn (new, v1); B: k5, k8 loop (new, v1) | 0.9533 | [0.9321, 0.9689] | 1.0075 [1.0012, 1.0139] | 1.0009 ±0.0033 | no |
| 2 | k2, k3, k6, k8 `inline(always)` (k8, k3 via explore), k5 `inline(never)` (revisit) | k4 loop `vectorize.width=16` (`forced_top1`, 1−P(KEEP)=0.430, P(hint)=0.170), k3 loop `unroll.count=4` (explore, new), k8 loop `interleave.count=2` (explore, revisit) | A: k8, k3 fn (new, v1); k5 fn (revisit, v2); B: k3 loop (new, v1); k8 loop (revisit, v2) | 1.0020 | [0.9971, 1.0065] | not triggered | 1.0005 ±0.0023 | no |
| **3** | k1, k2, k6, k7 `inline(always)` (k1, k7 via explore), k4 `inline(never)` (revisit) | k5 loop `interleave.count=1` (revisit), k3 loop `unroll.count=4` (direct pick, P=0.72), k8 loop `KEEP_DEFAULT` | A: k1, k7 fn (new, v1); k4 fn (revisit, v2); B: k5 loop (revisit, v2) | **0.9237** | [0.9216, 0.9261] | 0.9139 [0.9121, 0.9156] | 0.9978 ±0.0027 | no |
| **4** | k2, k6 `inline(always)`, k8 `inline(never)` (revisit) | k4 loop `interleave.count=1` (revisit), k3 loop `unroll.count=4` (direct pick, P=0.71), k5 loop `KEEP_DEFAULT` | A: k8 fn (revisit, v2); B: k4 loop (revisit, v2) | **1.0754** | [1.0705, 1.0803] | **1.0722** [1.0682, 1.0763] | 1.0013 ±0.0043 | **yes** |
| 5 | k2, k6 `inline(always)`, k3 `inline(never)` (revisit) | k4 loop `interleave.count=1` (direct pick, P=0.65), k5 loop `KEEP_DEFAULT`, k8 loop `KEEP_DEFAULT` | A: k3 fn (revisit, v2); B: none eligible | 1.0491 | [1.0444, 1.0537] | 1.0482 [1.0446, 1.0518] | 0.9989 ±0.0032 | no |

Every round: output correct, every plan entry applied, no `ambiguous`, no
`vanished`, no `unmatched` (`rounds.jsonl`, `apply` fields; `exp6-both-run.log`
prints `[B] correctness: OK` for all five rounds). `exp6-both-run.log` prints
`[accept]` exactly once: `round 4 is the new best (1.0754)`. Round 2's
confirmation batch was not triggered (`rounds.jsonl` round 2
`confirm_trigger: []`, `confirm: null`); rounds 1, 3, 4 and 5 all triggered
on `aggregate` (`confirm_trigger: ["aggregate"]`).

**Round 3 measured 0.9237 — the cause, per case** (`rounds.jsonl` round 3
`per_workload`): k5's own-case ratio that round is **0.2680**
([0.2665, 0.2697]), by far the lowest of the eight (next lowest, k1,
reads 1.0017); every other case sits within 5% of 1.0000. Round 3's own
plan touches k5 exactly once: the phase-B revisit at the k5 loop
(`hbkernels::k5_mul_reduce@macros.rs:180:28#d2`) picked
`interleave_count_1` this round (P 0.30, table below) — the k5 function
attribute itself stayed `KEEP_DEFAULT` that round (round 3 `phase_a.choices`),
so the loop hint is the only round-3 change at k5. (Round 1 had picked
`unroll_count_8` at this same loop site; round 2's phase-B site set that
round was k4/k8/k3 only, with no k5-loop entry at all, `exp6-both.jsonl`
line 7 `site_map` — so round 3's revisit is the loop's first re-ask since
round 1, not a change from a round-2 value.) The score run's isolated
(own-kernel) oracle measurement for the round-3 candidate at that site is
`pick_ratio` **0.2957** [0.2914, 0.3001], flagged `harmful: true`
(`scripts/hintbench_exp4_score.py run …`, round 3 `scored` entry for
`hbkernels::k5_mul_reduce@macros.rs:180:28#d2`) — the same order of
magnitude as round 3's combined 0.2680. `interleave_count_1` at the k5 loop
is the pick that caused round 3's low ratio.

**Rule-3 mechanism checks for the k8 loop**
(`hbkernels::k8_scale_add@range.rs:1103:12#d2`), evidence from
`rounds.jsonl` (`phase_b.exploration.eligible_new`/`.eligible_revisit`/
`.pick_detail`, `kind`, `visit_no`) and `exp6-both-run.log`'s
`[B.explore]` lines:

**(a) Was the k8 loop asked at least twice by round 4? PASS.** It is asked
via explore twice, both before round 4: round 1 as `kind: "new"`,
`visit_no: 1` (`exp6-both-run.log` line 8: `[B.explore]
hbkernels::k8_scale_add @ range.rs:1103: nothing has been tried here;
trying interleave.count=1`) and round 2 as `kind: "revisit"`,
`visit_no: 2` (line: `[B.explore] hbkernels::k8_scale_add @ range.rs:1103:
revisit 2, tried here so far interleave.count=1; trying
interleave.count=2`), which appears in round 2's
`phase_b.exploration.eligible_revisit` list
(`{"site_id": "hbkernels::k8_scale_add@range.rs:1103:12#d2", "n_tried": 1,
"tried": ["interleave_count_1"]}`). This differs from exp6-rev, where the
same check FAILED (§153) because the k8 loop's own argmax answer never
returned to `KEEP_DEFAULT` in a later round there; in exp6-both, round 2's
own main phase-B argmax at this site *is* `KEEP_DEFAULT`
(`exp6-both.jsonl` line 7, `q1`, `choice: "KEEP_DEFAULT"`, confidence
0.57, `probabilities.KEEP_DEFAULT: 0.61`), which is what makes it eligible
for that same round's revisit explore sub-request. With `max_visits: 2`
spent by round 2, the k8 loop no longer appears in any round's
`eligible_revisit` list from round 3 onward (round 3's list holds only the
k5 loop, round 4's only the k4 loop, round 5's is empty); it is still
asked as an ordinary (non-explore) main-phase-B question in rounds 3 and 5
(answered `KEEP_DEFAULT` both times) and dropped from the phase-B site set
entirely in round 4 (`rounds.jsonl` round 4 `phase_b.choices` has no
k8-loop key; `site_map` for that request lists only the k5, k4 and k3
loops). The pattern is the same every round a function gets
`inline(never)` in phase A: that kernel's loop site is absent from phase
B's site set that same round (`[A] refreshed loop sites: 3`, down from 4)
— round 2's k5 `inline(never)` drops the k5 loop from round 2's phase B
(line 7 `site_map`: k4, k8, k3 only); round 3's k4 `inline(never)` drops
the k4 loop (line 11: k5, k8, k3); round 4's k8 `inline(never)` drops the
k8 loop (line 15: k5, k4, k3, as cited above); round 5's k3 `inline(never)`
drops the k3 loop (line 19: k5, k4, k8). This is why round 4's phase-B
request never asks about the k8 loop, and it is also why the score (below)
scores only 11 of 12 sites that round.

**(b) Was `vectorize.width=16` chosen at k8 in any round? FAIL.** The
k8-loop answers across the run: round 1 explore `interleave_count_1`
(P 0.24, `vectorize_width_16` P 0.02); round 2 revisit `interleave_count_2`
(P 0.30, `vectorize_width_16` P 0.08 — up from round 1's 0.02, but still
not the argmax); round 3 main `KEEP_DEFAULT` (`vectorize_width_16` P 0);
round 4 not asked; round 5 main `KEEP_DEFAULT` (`vectorize_width_16`
P 0.01). `vectorize_width_16` is never the chosen candidate at this site
in this run.

**(c) Is it kept in the final plan? FAIL (moot, since (b) never fired).**
`best-plan.json`'s `loop_md` has no entry at all for
`hbkernels::k8_scale_add@range.rs:1103:12#d2` (i.e. it stands at
`KEEP_DEFAULT` in the accepted round-4 plan), not `vectorize_width_16`.

**Every revisit question asked** (`kind: "revisit"` in `pick_detail`; site,
round, candidates offered, pick, P; and what happened to its round):

| round | phase | site | tried before | candidates offered | pick | P | round accepted? | in final plan? |
|---|---|---|---|---|---|--:|---|---|
| 2 | A | `fn:hbkernels::k5_mul_reduce` | `inline_always` | `inline_never` (1) | `inline_never` | 1.00 | no (ratio 1.0020) | no |
| 2 | B | `hbkernels::k8_scale_add@range.rs:1103:12#d2` | `interleave_count_1` | `unroll_count_2/4/8`, `vectorize_width_2/4/8/16`, `interleave_count_2/4` (9) | `interleave_count_2` | 0.30 | no (ratio 1.0020) | no |
| 3 | A | `fn:hbkernels::k4_count_bytes` | `inline_always` | `inline_never` (1) | `inline_never` | 1.00 | no (ratio 0.9237) | no |
| 3 | B | `hbkernels::k5_mul_reduce@macros.rs:180:28#d2` | `unroll_count_8` | `unroll_count_2/4`, `vectorize_width_2/4/8/16`, `interleave_count_1/2/4` (9) | `interleave_count_1` | 0.30 | no (ratio 0.9237) | no |
| **4** | A | `fn:hbkernels::k8_scale_add` | `inline_always` | `inline_never` (1) | `inline_never` | 1.00 | **yes** | **yes** (`k8_scale_add: inline(never)`) |
| **4** | B | `hbkernels::k4_count_bytes@macros.rs:180:28#d2` | `vectorize_width_16` | `unroll_count_2/4/8`, `vectorize_width_2/4/8`, `interleave_count_1/2/4` (9) | `interleave_count_1` | 0.32 | **yes** | **yes** (`k4 loop: interleave.count=1`) |
| 5 | A | `fn:hbkernels::k3_fill_run` | `inline_always` | `inline_never` (1) | `inline_never` | 1.00 | no (ratio 1.0491) | no |

Seven revisit questions total: four function-attribute revisits (2-way
vocabulary, P trivially 1.00 once the first value is excluded) and three
loop revisits (real rankings over 9 remaining candidates). Only round 4's
two revisits — `k8_scale_add: inline(never)` and `k4 loop:
interleave.count=1` — landed in the accepted, final plan; round 2's and
round 3's revisits (including the k8-loop one) belong to rounds that were
never accepted and so do not appear in `best-plan.json`.

**Best plan (round 4), per case** (`rounds.jsonl` round 4 `per_workload`):

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| ratio | 0.9984 | **1.6953** | 1.0437 | 0.9915 | 0.9986 | 1.0004 | 0.9974 | 1.0008 |

Plan (`best-plan.json`, `plan_id: "r4-b"`): k6, k2 fn `inline(always)`
(`jev_readout: argmax`, `answer_ref exp6-both.jsonl#13`); k8 fn
`inline(never)` (`jev_readout: exploration`, `exploration: true`, `#14`);
k3 loop `unroll.count=4` (`jev_readout: argmax`, `#15`); k4 loop
`interleave.count=1` (`jev_readout: exploration`, `exploration: true`,
`#16`). No entry for k5 loop or k8 loop (both stand at `KEEP_DEFAULT`).
Basis sha256 `c40acc8b…`.

**Holdout**: ratio **1.0725**, 95% CI [1.0694, 1.0754], in-run A/A 0.9999
±0.0029, MDE 0.0389 (`run-manifest.json` `holdout` block; `exp6-both-run.log`
`[holdout] ratio 1.0725 CI [1.0694, 1.0754]`, measured once on round 4
after it was frozen as best).

**Batch 2** (`artifacts/hintbench-search/exp6-both-holdout-batch2.log`,
`artifacts/hintbench-search/exp6-both/holdout-batch2/stats.json`, seed
20260927, produced while this write-up started, finished before it did):

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | [1.0000, 1.0000] | 0.00% |
| aa | **1.0010** | [0.9986, 1.0036] | 0.25% |
| cand | 1.0769 | [1.0726, 1.0810] | 0.42% |

Per case, cand vs aa (`holdout-batch2/stats.json` `per_workload`):

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| cand | 1.0061 | **1.6974** | 1.0488 | 0.9974 | 1.0030 | 1.0000 | 1.0019 | 1.0072 |
| aa | 1.0019 | 0.9984 | 0.9978 | 1.0013 | 1.0018 | 0.9974 | 0.9989 | 1.0107 |

**The ±0.5% rule (§151 rule 1) held on the first attempt, unlike
exp6-ctl's, exp6-rev's and exp6-pv's original batch 2 (§152/§153/§155).**
The A/A leg reads 1.0010, a +0.10% deviation, 95% CI [0.9986, 1.0036]
including 1.0000, half-width 0.25%; no per-case outlier appears at k5 or
k8 this time (`aa`/k5 1.0018, `aa`/k8 1.0107, both within 1.1% of 1). Per
§151 rule 1's ±0.5% check, exp6-both's batch 2 does not owe a retake
(confirmed by the retake chain's own check, `abs(aa_ratio − 1) <= 0.005`
in `chain-retakes.sh`: `chain-retakes.log`, `[retake] … exp6-both batch2
A/A ok, no retake`, §158). `cand`'s number (1.0769) is usable as
confirmed without a retake.

**Gateway** (`run-manifest.json` `gateway.attempts_by_phase`; per-phase
seconds waiting summed from each request's `seconds_waiting` in
`jev-log/exp6-both.jsonl`, which foot to the manifest's total):

| phase | requests | attempts | landed | mean body bytes | seconds waiting |
|---|--:|--:|--:|--:|--:|
| A | 5 | 14 | 5 | 71081.6 | 18.226 |
| B | 5 | 11 | 5 | 41241.0 | 12.555 |
| explore | 9 | 13 | 9 | 21339.4 | 8.001 |
| **total** | **19** | **38** | **19** | — | **38.783** |

`lost_phases: 0`, `lost_rounds: 0` (`run-manifest.json`) — **0 of 19
requests lost** (10 phase requests A+B ×5 rounds, 9 explore requests:
`A.explore`+`B.explore` fired every round except round 5, which had no
`B.explore` since nothing was eligible that phase). Rule 5's threshold
(>2 of 10 phase requests lost invalidates the arm) is not approached; no
re-run under `-b` is needed. `exp6-both-run.log`/`jev-log/exp6-both.jsonl`
show every 503 absorbed by the round's own resend/backoff (up to 5
attempts, round 2 `B.explore`, `n_attempts: 5`, 8.001 s) inside the 600 s
wall budget.

**Rule-4 mechanism check (pv-untried line, corrected reading per §156).**
Grepping `state` or the `.log` finds nothing, as expected (§156); the
sentence lives in `request.questions[*].instructions`:

```
$ grep -c "cost model picked" artifacts/hintbench-search/exp6-both/jev-log/exp6-both.jsonl
9
$ grep -c "cost model picked" artifacts/hintbench-search/exp6-both/jev-log/exp6-both.log
0
$ jq -r '.request.questions[]?.instructions' artifacts/hintbench-search/exp6-both/jev-log/exp6-both.jsonl \
    | grep -c "cost model picked"
34
```

9 requests carry the sentence at least once; 34 is the total copy count
(one copy per vectorized-loop metric per question — width and interleave
— matching §156's pv count exactly, 34, though pv's requests-with-the-phrase
count was 6 against both's 9, since both's revisit mechanism sends extra
`B.explore` requests pv's arm does not). Per round/phase, via
`jq -r '[.round, .phase, (.request.questions[]?.instructions // "" | [scan("cost model picked")] | length)]'`:
round 1 B: 6, B.explore: 4; round 2 B: 4, B.explore: 2; round 3 B: 4,
B.explore: 2; round 4 B: 4, B.explore: 2; round 5 B: 6 (no B.explore that
round) — 10+6+6+6+6 = 34, matching the flat count.

**At k8, round 1's phase-B answers** (the request the task asks about;
`jev-log/exp6-both.jsonl` line 3 is the main, non-explore phase-B request,
line 4 is `B.explore`, the request whose answer the driver actually
applies at k8 since it was newly eligible for exploration that round):

* **Main phase (q2, line 3, site `hbkernels::k8_scale_add@range.rs:1103:12#d2`)**:
  `choice: "KEEP_DEFAULT"`, confidence 0.74, `probabilities.vectorize_width_16: 0.00`
  (`KEEP_DEFAULT` 0.75). The question's `instructions` for this site
  carries the plugin's own per-loop fact ("LLVM vectorized it, with
  vectors of 8 lanes, interleaved 4 times") plus the untried-line sentence
  ("8 is the width LLVM's cost model picked for this loop with no hint …
  Vocabulary values other than 8 not yet tried here: 2, 4, 16").
* **Exploration sub-request (e1, line 4)**: `choice: "interleave_count_1"`,
  confidence 0.16, **`probabilities.vectorize_width_16: 0.02`**.

**P(vectorize_width_16) at k8, round 1, the exploration request that is
actually applied — the number to compare across arms**: exp6-both
**0.02**, matching exp6-pv's **0.02** exactly (§155/§156) to two decimals;
against exp6-ctl's **0.01** (§152) and Exp5's **0.01** (§145) — both of
which ran with `--pv-untried off`, i.e. state format
`state-v5.0-2026-09-23`, no untried-line sentence. This is consistent with
§156's reading: the untried line reached Jev in both exp6-pv and
exp6-both, and in both arms the sampled P at k8 came out around 0.02 (one
hundredth above the `off`-arms' 0.01), never enough to move the argmax
away from the harmful/near-neutral non-`KEEP_DEFAULT` candidate the model
actually picked at that request.

**Score** (`scripts/hintbench_exp4_score.py run artifacts/hintbench-search/exp6-both`,
context per §151 rule 7, not headline):

| round | exact | same-family | miss | harmful | ratio | share of the combination (training) |
|---|--:|--:|--:|--:|--:|--:|
| 1 | 5 | 0 | 7 | 2 | 0.9533 | −53.06% |
| 2 | 5 | 0 | 6 | 3 | 1.0020 | 2.30% |
| 3 | 5 | 0 | 6 | 1 | 0.9237 | −86.58% |
| **4** | **8** | **0** | **3** | **1** | **1.0754** | **85.61%** |
| 5 | 7 | 0 | 4 | 2 | 1.0491 | 55.73% |

Combination's own training ratio, for scale: **1.0881** (`combination_training`
in the score output, identical to exp6-ctl's, exp6-rev's and exp6-pv's,
§152/§153/§155). Round 4's request that round did not ask about the k8
loop (dropped from the phase-B site set, per the rule-3(a) evidence
above), so only 11 of the 12 sites are scored that round (8 function +
3 loop), not 12; the k8-loop truth (`vectorize_width_16`, the +8.8%) is
absent from round 4's tally rather than counted a miss. Round 4's
(accepted) three misses are `inline(always)` at k6 and `inline(never)` at
k8 (truth `KEEP_DEFAULT` at both, function attrs) and `interleave.count=1`
at the k4 loop (truth `KEEP_DEFAULT`, the one `harmful` entry, own-kernel
`pick_ratio` 0.7301 [0.7266, 0.7349] — though this round's actual combined
per-case k4 ratio was 0.9915, not harmful in the full plan's context, the
same pattern exp6-ctl's round 1 showed for its own harmful pick, §152). No
same-family picks appear in any round of this arm (matching exp6-pv,
§155, and unlike exp6-ctl and exp6-rev which each had one).

**What this arm establishes (§151 rule 2, both − ctl and the interaction
on the headline).** Against exp6-ctl (§152: training 1.0742, confirm
1.0776, holdout 1.0735), exp6-rev (§153: training 1.0780, confirm 1.1082,
holdout 1.0812 — confirm and batch 2 there are suspect pending the retake
in §158, but rev's pre-registered *headline* is its training/confirm/
holdout triple as recorded in §153) and exp6-pv (§155: training 1.0518,
confirm 1.0598, holdout 1.0525):

| metric | exp6-ctl | exp6-both | both − ctl (points) | exceeds 0.5 pt noise bar? |
|---|--:|--:|--:|---|
| training (best round) | 1.0742 | 1.0754 | +0.12 | no |
| confirm | 1.0776 | 1.0722 | −0.54 | yes |
| holdout | 1.0735 | 1.0725 | −0.10 | no |

| metric | interaction: both − rev − pv + ctl (points) | exceeds 0.5 pt noise bar? |
|---|--:|---|
| training | +1.98 | yes |
| confirm | −1.82 | yes |
| holdout | +1.23 | yes |

(Arithmetic: training 1.0754 − 1.0780 − 1.0518 + 1.0742 = 1.0198 → +1.98
pt; confirm 1.0722 − 1.1082 − 1.0598 + 1.0776 = 0.9818 → −1.82 pt; holdout
1.0725 − 1.0812 − 1.0525 + 1.0735 = 1.0123 → +1.23 pt.)

both − ctl sits within the 0.5 pt noise bar on training and holdout
(+0.12, −0.10) and just outside it on confirm (−0.54, negative — both's
confirm reads lower than ctl's). The interaction term is outside the bar
on all three readouts, alternating sign (+1.98 training, −1.82 confirm,
+1.23 holdout) — i.e. it is large relative to the 0.5 pt bar but not
consistent in direction across training/confirm/holdout, so it does not
read as one stable interaction effect on this evidence. Rule 3's checks
above establish that, mechanically, the revisit budget in this run did
reach the k8 loop a second time (unlike exp6-rev, where it never did) but
still never picked `vectorize_width_16` there, and rule 4's check
establishes that the untried-line sentence reached Jev in this arm (as it
did in exp6-pv, sharing the same 0.02 sampled P at k8) without moving the
pick toward `vectorize_width_16` either. Neither single-run headline
difference in this section is attributable to either mechanism doing what
it was designed to do at the k8 loop.

### 158. Batch-2 retakes (rev, and pv/both where owed)

Per §151 rule 1, run by the owner's retake chain
(`chain-retakes.sh`; durable logs
`artifacts/hintbench-search/exp6-rev-holdout-batch2b.log` and
`artifacts/hintbench-search/exp6-pv-holdout-batch2b.log`, the script's own
`$A/$1-$2.log` redirect; chain-level log
`/tmp/claude-1000/-home-hiro-prj-jev-optimize/25288dc0-eddf-42fc-99a6-132754ad8c1b/scratchpad/chain-retakes.log`,
session-scoped, cited below only for the pass/fail lines it prints):
exp6-rev's batch 2 (§153) is owed a retake unconditionally (it was never
retaken in this write-up's scope, §153); exp6-pv's and exp6-both's are
retaken only if their original batch-2 A/A fell outside ±0.5%. The chain's
own check (`aa_ok()` in `chain-retakes.sh`, `abs(aa_ratio − 1) <= 0.005`)
ran against each arm's *original* `holdout-batch2/stats.json`:

* **exp6-rev**: not checked by `aa_ok` (retaken unconditionally, per the
  task's instruction); original batch-2 `aa` was 0.9864 (§153), well
  outside ±0.5%.
* **exp6-pv**: original batch-2 `aa` was 0.9846 (§155), outside ±0.5% →
  retaken (`chain-retakes.log`: `[retake] … exp6-pv batch2 A/A outside
  rule -> retake`).
* **exp6-both**: original batch-2 `aa` was 1.0010 (§157), inside ±0.5% →
  **not retaken** (`chain-retakes.log`: `[retake] … exp6-both batch2 A/A
  ok, no retake`).

Commands (both into `holdout-batch2b/`, on each arm's own best round's
binary, `chain-retakes.sh`'s `best()`/`panel()`):

```
scripts/bench_panel.sh artifacts/hintbench-search/exp6-rev/holdout-batch2b 15 3 20260927 \
    base=artifacts/hintbench-sites/baseline/bin \
    cand=artifacts/hintbench-search/exp6-rev/round-03/bin \
    aa=artifacts/hintbench-sites/baseline/bin
scripts/bench_panel.sh artifacts/hintbench-search/exp6-pv/holdout-batch2b 15 3 20260927 \
    base=artifacts/hintbench-sites/baseline/bin \
    cand=artifacts/hintbench-search/exp6-pv/round-02/bin \
    aa=artifacts/hintbench-sites/baseline/bin
```

**exp6-rev retake** (`artifacts/hintbench-search/exp6-rev-holdout-batch2b.log`, `artifacts/hintbench-search/exp6-rev/holdout-batch2b/stats.json`):

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | [1.0000, 1.0000] | 0.00% |
| aa | **1.0012** | [0.9983, 1.0041] | 0.29% |
| cand | 1.1107 | [1.1077, 1.1137] | 0.30% |

Per case, cand vs aa:

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| cand | 1.0015 | **1.6981** | 1.0396 | 1.0079 | **1.2879** | 0.9997 | 1.0092 | 1.0007 |
| aa | 0.9997 | 1.0014 | 1.0002 | 0.9981 | 1.0020 | 1.0002 | 1.0072 | 1.0008 |

**Rule held.** The A/A leg reads 1.0012, a +0.12% deviation, 95% CI
[0.9983, 1.0041] including 1.0000, half-width 0.29% — unlike the original
batch (§153, `aa` 0.9864, −1.36%, CI excluding 1.0000), no per-case outlier
appears at k5 or k8 (`aa`/k5 1.0020, `aa`/k8 1.0008, both within 0.21% of
1); every case sits within 0.72% of 1.0000 (worst: k7, 1.0072). `cand`
reads 1.1107 [1.1077, 1.1137], close to but above §153's original batch-2
cand (1.1083) and its training/confirm (1.0780/1.1082); it is now usable
as confirmed. exp6-rev's earlier reported holdout (1.0812) and headline
table (§153) stay as written; this section adds the retake only.

**exp6-pv retake** (`artifacts/hintbench-search/exp6-pv-holdout-batch2b.log`, `artifacts/hintbench-search/exp6-pv/holdout-batch2b/stats.json`):

| label | aggregate ratio (geomean) | 95% CI | half-width |
|---|--:|---|--:|
| base | 1.0000 | [1.0000, 1.0000] | 0.00% |
| aa | **0.9864** | [0.9839, 0.9893] | 0.27% |
| cand | 1.0661 | [1.0565, 1.0749] | 0.92% |

Per case, cand vs aa:

| | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| cand | 1.0030 | **1.6941** | 1.0524 | 1.0021 | 0.9997 | 0.9979 | 1.0042 | **0.9298** |
| aa | 1.0022 | 0.9958 | 1.0034 | 1.0042 | **0.9150** | 0.9983 | 0.9955 | **0.9802** |

**Rule still did not hold on the retake.** The A/A leg reads 0.9864, a
−1.36% deviation, 95% CI [0.9839, 0.9893] excluding 1.0000 — essentially
unchanged from the original batch (§155, `aa` 0.9846, −1.54%). The same
two cases deviate in the same direction: `aa`/k5 0.9150 (−8.50%, original
0.9236) and `aa`/k8 0.9802 (−1.98%, original 0.9652), while the other six
cases deviate at most 0.46% (k4). Per §151 rule 1 a batch is retaken
*once*; both readings are now reported (original in §155, this retake
here) and neither is treated as a clean confirmation — `cand`'s number
from either batch (1.0551 original, 1.0661 this retake) is not to be used
as a confirmed headline figure.

**exp6-both: not retaken.** §157's own batch-2 `aa` (1.0010, [0.9986,
1.0036], half-width 0.25%) was inside ±0.5% on the first attempt, so
`chain-retakes.sh` skipped it (`chain-retakes.log`: `[retake] … exp6-both
batch2 A/A ok, no retake`); no `holdout-batch2b/` directory exists for
exp6-both. §157's batch-2 `cand` (1.0769) stands as confirmed without a
retake.

### 159. Experiment 6 across the four arms

Write-up: `docs/experiments/hintbench/exp6.md`. No new measurement in this
section; every number is read from existing artifacts under
`artifacts/hintbench-search/`, with the file named next to it. Per-case
tables were printed with a read-only script over each batch's
`stats.json` (`per_workload.<label>.<k>.ratio_vs_base` and `.mean_s`);
rule-2 arithmetic uses the unrounded ratios in `rounds.jsonl` (`ratio`,
`confirm.ratio`) and `holdout/stats.json` (`aggregate.cand.ratio`), so it
can differ from §153/§157's rounded arithmetic in the second decimal.

**Cross-arm table.**

| | exp6-ctl | exp6-rev | exp6-pv | exp6-both |
|---|--:|--:|--:|--:|
| best round (`rounds.jsonl` `accepted`) | 2 | 3 | 2 | 4 |
| training ratio (`rounds.jsonl` `ratio`) | **1.0742** | **1.0780** | **1.0518** | **1.0754** |
| share of combination 1.0881 (`hintbench_exp4_score.py run`) | 84.27% | 88.48% | 58.82% | 85.61% |
| confirm (`round-NN/confirm/stats.json`) | 1.0776 | 1.1082 (k5 mode, below) | 1.0598 | 1.0722 |
| holdout (`holdout/stats.json`) | 1.0735 | 1.0812 | 1.0525 | 1.0725 |
| panel b2, cand / A/A (`holdout-batch2/stats.json`) | 1.0751 / 0.9875 fail | 1.1083 / 0.9864 fail | 1.0551 / 0.9846 fail | 1.0769 / 1.0010 pass |
| panel b2b, cand / A/A (`holdout-batch2b/stats.json`) | 1.0743 / 1.0002 pass | 1.1107 / 1.0012 pass | 1.0661 / 0.9864 fail | not owed |
| lost phases of 10 (`run-manifest.json` `gateway.lost_phases`) | 0 | 0 | 0 | 0 |
| rule 3 (a)/(b)/(c) (§153, §157) | n/a | fail/fail/fail | n/a | pass/fail/fail |
| rule 4: P(`vectorize_width_16`), k8, r1 `B.explore` (`jev-log/<arm>.jsonl` line 4, `e1`) | 0.01 | 0.01 | 0.02 | 0.02 |

**Headline**: three arms +7.4% to +7.8% on training (84–89% of the oracle
combination's training ratio), pv +5.2% (59%); 0 of 40 phase requests
lost. exp6-rev's headline is its training ratio, **1.0780**.

**exp6-rev round-03, the same binary in five batches, per case**
(cand `ratio_vs_base`):

| batch (file under `exp6-rev/`) | k1 | k2 | k3 | k4 | k5 | k6 | k7 | k8 | aggregate |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| training (`round-03/stats.json`) | 0.9991 | 1.6997 | 1.0368 | 1.0095 | **1.0226** | 1.0047 | 1.0026 | 0.9958 | 1.0780 |
| holdout (`holdout/stats.json`) | 1.0031 | 1.6974 | 1.0420 | 1.0155 | **1.0213** | 1.0020 | 1.0066 | 1.0060 | 1.0812 |
| confirm (`round-03/confirm/stats.json`) | 1.0053 | 1.6893 | 1.0391 | 1.0134 | **1.2835** | 1.0019 | 1.0080 | 0.9813 | 1.1082 |
| panel b2 (`holdout-batch2/stats.json`) | 1.0009 | 1.6959 | 1.0342 | 1.0159 | **1.2857** | 1.0000 | 0.9986 | 0.9941 | 1.1083 |
| panel b2b (`holdout-batch2b/stats.json`) | 1.0015 | 1.6981 | 1.0396 | 1.0079 | **1.2879** | 0.9997 | 1.0092 | 1.0007 | 1.1107 |

k5 mean_s, same files (base / cand / aa): training 361.8 / 353.8 / 360.7 ms;
holdout 359.0 / 351.5 / 357.0; confirm 329.4 / 256.6 / 329.1; b2 330.6 /
257.1 / 359.8; b2b 330.7 / 256.8 / 330.0.

Only k5 flips. Both binaries have two k5 modes (base ~358–362 or ~326–333
ms; this cand ~352 or ~257 ms); the ratio is ~1.02 when both are slow and
~1.28 when both are fast. The discrepancy is in the measurement, not the
plan; the A/A leg cannot catch it because base and cand shared a mode in
every batch, including the ones whose A/A passed (confirm 1.0001, b2b
1.0012). Across all four arms, the baseline's k5 was slow in every round
batch (20) and holdout batch (4) and fast in every confirm batch (18) and
every panel base leg (7) (`stats.json` `per_workload.base.k5.mean_s`);
Exp4/Exp5 (`jev-v4-r5`, `jev-v42-r5`) show the same split, but the oracle
sweep does not: all 85 of its batches, confirm seeds included, read base k5
slow (349.8–366.5 ms, `artifacts/hintbench-oracle/**/stats.json`), and
rev's holdout batch, started the second its round-5 confirm ended, flipped
from 326.9 to 359.0 ms — so neither the seed nor what ran before explains
the mode; cause not investigated. Of the seven Exp6 plans with k5 loop
`unroll.count=8`, six read k5 1.019–1.024 in their round batch (both round
1: 0.9593) and all six with a confirm batch read 1.275–1.295 there
(`rounds.jsonl` `per_workload.k5.ratio`, `confirm.per_workload.k5.ratio`).
The oracle's k5 `unroll.count=8` (1.0194, `hintbench-oracle/round-43`) and
combination (1.0881) are slow-mode numbers.
**The 8% vs 11% discrepancy is unresolved**; the 11% readings are not a
result against the oracle.

The other three arms' five-way per-case tables are in exp6.md 2.1; their
aggregate spreads across batches are ctl 0.41 pt, both 0.47 pt, pv 1.43 pt
(all of it pv's k8 cell, 0.826–0.930).

**Rule 2, arithmetic** (points; unrounded ratios as above):

| difference | training | confirm | holdout |
|---|--:|--:|--:|
| rev − ctl | +0.37 | +3.06 | +0.77 |
| pv − ctl | −2.24 | −1.78 | −2.09 |
| both − ctl | +0.12 | −0.54 | −0.10 |
| interaction (both − rev − pv + ctl) | +1.99 | −1.82 | +1.22 |

**Verdict: not resolved at n=1, for every row.** Reasons, from the
artifacts:

* Jev's answers vary on byte-identical input. Round-1 requests with equal
  `request_sha256` (`jev-log/<arm>.jsonl`; ctl ≡ rev and pv ≡ both in all
  four phases; after normalizing the state-format header string, A and
  A.explore are identical in all four arms) gave probabilities differing by
  up to 0.10, and one argmax flipped: ctl/rev phase B `q1` (k4 loop),
  `vectorize_width_16` 0.49 vs `KEEP_DEFAULT` 0.49.
* One pick at one site moved a headline by ~2 pt (pv's k8 loop
  `interleave.count=1`, k8 0.8259).
* The same binary in two arms' round-1 batches read 0.9978 vs 1.0029
  (`bin_sha256 f45bf61f…`, ctl/rev) and 0.9681 vs 0.9533 (`9ca85087…`,
  pv/both) — 0.51 and 1.48 pt.
* rev − ctl on confirm (+3.06) is the k5 mode above.

The binary mechanism checks stand: rule 3 as tabled, and rule 4 (width 16
never chosen at k8 in any arm).

**Correction to §151 rule 2** (per rule 9, §151 is not edited): the 0.5 pt
bar was derived from the oracle's null panel (0.17 pt) and bounds
measurement noise between byte-identical binaries in a quiet batch only. It
does not bound proposer sampling (not measured when the rule was written)
and not the k5 mode, so a single-run difference above 0.5 pt is **not** an
effect under this design. §153's "confirm and holdout deltas exceed the
bar" and §155's "all three deltas exceed the bar" should be read with this
correction.

**Correction to §155/§156 on the k8 pick.** §156's closing note says
"byte-identical inputs (ctl's and pv's phase A / A.explore) … produced
different picks across arms". Phase A and A.explore choices were identical
in all four arms; only probabilities differed. The k8 `B.explore` pick
that differs between ctl (`unroll_count_2`) and pv (`interleave_count_1`)
was made on inputs that differ by the untried line, and it agreed within
each byte-identical pair (ctl/rev `unroll_count_2` 0.23/0.23; pv/both
`interleave_count_1` 0.22/0.24; `interleave_count_1` P 0.12/0.14 off vs
0.22/0.24 on). §155's attribution of that pick to sampling variation is
therefore not supported; at n=2 per cell neither attribution is
established.

**Determinism control.** None found in the documentation: the SystemOne
request documents `state`, `model`, `questions` and per question `type`,
`instructions`, `criteria` (https://docs.typesafe.ai/api.md); the Python
SDK's `system_one()` has no seed/temperature parameter
(https://docs.typesafe.ai/sdk/python/api/clients/sync.md); the
consistency cookbook reports that picked labels can flip across repeats
(https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook.md).
Checked 2026-09-23, documentation only.

### 160. A/A-only panel study (hintbench k5 mode): pre-registration

Written before any number of this study exists. Binary: the frozen baseline
`artifacts/hintbench-sites/baseline/bin` (stripped sha256 a84b7c0dfe37e4f6…,
= Exp6 `timing/base`); nothing built, no HTTP, no tracked file changed.
Command: `scripts/hintbench_aa_study/run.sh` (readout `readout.py`, output
`artifacts/hintbench-aa-study/<panel>/`, summary `readout.txt`).

**Archive (read-only, all 170 hintbench `samples.json`).** The 344
baseline-copy legs split by `c = max(32, (len(argv0)+23) & ~15)` (glibc chunk
of a `len`-byte string) with zero exceptions: c=96 (len 73–88) slow, c=80/112
(len 72, 89–94) fast. k8 co-moves ~2%; other kernels do not. No leg is
bimodal (H1 refuted). Legs of one batch disagree when base/aa straddle 88|89
(`exp6-*/holdout-batch2`, base 90 / aa 88), so H3 and H4 are refuted and
this is the cause of every A/A failure of the "aa k5/k8 slow" shape.

**Hypothesis H6**: the mode is keyed to argv[0] length through the heap
offset of the kernel data (`env::args().collect()` allocates the argv
strings before it; brk randomization is page-granular). Prediction:
plain-`k5` leg slow iff `c % 32 == 0`.

**Panels** (CPU 8, gap 0, stdout pipe, warmup 3, 15 runs; lengths asserted):
1. `p1` `scripts/bench_panel.sh`, 8 kernels, seed 20260927; copies at c =
   112 (base), 80, 96, 128, 144, 160. H6: slow at 96, 128, 160. (Period 64
   would make c=128 differ from c=96.) ~5.5 min.
2. `p2` `bench.py` k5+k8, seed 20260922: copies at len 91 (base) and
   85–94, a same-length twin at 89, two hard links to one inode at 88 and
   89. H6: step exactly at 88|89, twins equal, links differ. H2 (file or
   page-cache placement) needs the links equal. ~3 min.
3. `p3` fixed paths (c 112, c 96); `k5`, `k5 <3800000 zero-padded to
   7/25/41/57 chars>`, `k8`, `k8 920000`, `k8 <padded to 25>`: same work,
   shifted heap. H6: at each path a7 = a41, a25 = a57, a7 ≠ a25. ~2 min.
4. `p4` = p1, seed 20360922. ~5.5 min.
5. `p5a` c 112/80/96 on CPU 10 (H5); `p5b` on CPU 8 with a 4 KiB extra env
   variable and cwd `/` (moves the stack, not the heap: the stack-vs-heap
   discriminator); `p5c` with a busy loop on SMT sibling CPU 9. H6: map
   unchanged in all three. ~2 min.
Drop order if short: p5c, p4, p5b. Total ~18 min.

**Readout rules.** Per run F/S at 345 ms (spikes only; ≥ 4 of 15 runs on
the far side in one leg reopens H1). Per leg, within a panel: split k5 leg
medians at the largest gap if it is ≥ 12 ms (relative, because all kernels
moved ~3% between Exp4 and Exp6); otherwise use 345 ms and flag it. k8: no
mode; leg medians grouped by `c % 32`.
- H6 (length key) confirmed: 0 misses in p1, p2, p4, p5a, p5b.
- Mechanism (heap offset) confirmed only if p3 alternates at both paths. If
  p2 steps at 88|89 but p3 does not alternate, the length key stands and the
  mechanism is recorded as unknown; consequences (a), (b) still apply.
- A leg missing in both p1 and p4 refutes the mod-32 map (record the true
  map); p1/p4 disagreeing reopens H3. H2 only if p2's links agree with
  each other against length; H5 only if p5a's map differs.

**Consequences if H6 holds.** (a) All labels of a batch get argv[0] paths of
equal length (fix the *file name*, e.g. `timing/aa` → a same-length name;
the label `aa` stays, stats code indexes it). (b) Cross-batch comparisons
(round/confirm/holdout/panel/oracle) are valid only within one class; every
batch records `len(argv0)` and class. (c) k5/k8 ground truth is per class:
the oracle's k5 numbers (unroll 8 = 1.0194, combination 1.0881) are class-96,
rev's 1.28 is class-112. Measuring arms in both classes is proposed to the
owner, not done.

### 161. A/A-only panel study (hintbench k5 mode): results

Run by `scripts/hintbench_aa_study/run.sh` (no arguments: p1 p2 p3 p4 p5a
p5b p5c in that order), 2026-09-23 19:41–19:58 JST, all seven panels
completed (`artifacts/hintbench-aa-study-run.log`); none dropped. Readout
`python3 scripts/hintbench_aa_study/readout.py artifacts/hintbench-aa-study`
→ `artifacts/hintbench-aa-study/readout.txt`. Every binary is a stripped
copy (or hard link) of the frozen baseline, stripped sha256 a84b7c0dfe37e4f6
(`p1/panel.txt`, `p4/panel.txt`, `<panel>/paths.tsv`). `len` = byte length
of the absolute path passed as argv[0]; class `c = max(32, (len+23) & ~15)`.
Mode F/S = k5 leg median below/above the panel's largest-gap split (all
seven splits were relative, 343.8–348.0 ms, the 12 ms gap test never fell
back). Medians in ms over 15 runs (warmup 3, CPU 8 unless noted, gap 0,
stdout pipe).

**p1** (`p1/stats.md`, `bench_panel.sh`, 8 kernels, seed 20260927) and
**p4** (`p4/stats.md`, same, seed 20360922):

| leg | len | class | p1 k5 | p1 k8 | p1 mode | p4 k5 | p4 k8 | p4 mode | H6 pred |
|---|--:|--:|--:|--:|:-:|--:|--:|:-:|:-:|
| c112 (base) | 96 | 112 | 329.9 | 334.7 | F | 329.3 | 333.4 | F | F |
| c80 | 70 | 80 | 330.5 | 336.8 | F | 327.1 | 339.2 | F | F |
| c96 | 80 | 96 | 358.9 | 341.2 | S | 358.8 | 342.8 | S | S |
| c128 | 112 | 128 | 358.5 | 342.2 | S | 358.3 | 343.1 | S | S |
| c144 | 128 | 144 | 331.5 | 341.1 | F | 328.1 | 337.6 | F | F |
| c160 | 144 | 160 | 359.0 | 355.7 | S | 359.2 | 350.6 | S | S |

Other kernels (k1–k4, k6, k7) in p1/p4: every 95% CI contains 1.0 except
p1 c128 k7 0.9902 [0.9840, 0.9966] and p4 k3 at c144/c80/c96
(1.0072/1.0068/1.0056, lower bounds 1.0006–1.0017); neither reproduces in
the other panel. Aggregate A/A (geomean, `stats.md`): p1 c80 0.9975, c96
0.9862, c128 0.9832, c144 0.9965, c160 0.9825; p4 c80 0.9992, c96 0.9864,
c128 0.9855, c144 1.0001, c160 0.9848. Under rule 1 (±0.5%) every class-0
(mod 32) leg fails and every class-16 leg passes, in both panels.

**p2** (`p2/stats.md`, `bench.py` k5+k8, seed 20260922; inodes from
`p2/paths.tsv`):

| leg | len | class | k5 | k8 | mode | note |
|---|--:|--:|--:|--:|:-:|---|
| L091 (base) | 91 | 112 | 329.0 | 334.6 | F | |
| L085 | 85 | 96 | 360.9 | 342.4 | S | |
| L086 | 86 | 96 | 360.7 | 342.1 | S | |
| L087 | 87 | 96 | 359.7 | 341.8 | S | |
| L088 | 88 | 96 | 359.6 | 342.5 | S | |
| L089 | 89 | 112 | 332.6 | 334.6 | F | |
| L090 | 90 | 112 | 329.7 | 334.5 | F | |
| L092 | 92 | 112 | 330.1 | 334.8 | F | 1 run > 345 (348) |
| L093 | 93 | 112 | 331.8 | 334.3 | F | |
| L094 | 94 | 112 | 330.5 | 334.2 | F | 1 run > 345 (356) |
| Q089 | 89 | 112 | 331.4 | 333.8 | F | separate copy, twin of L089 |
| H088 | 88 | 96 | 360.3 | 344.1 | S | hard link, inode 1426930 |
| H089 | 89 | 112 | 329.4 | 336.4 | F | hard link, inode 1426930 |

**p3** (`p3/stats.md`, `bench.py`, seed 20360924): two fixed paths, S112
(len 96, class 112) and S096 (len 80, class 96); workload `k5` or `k5
<3800000 zero-padded to 7/25/41/57 chars>` (3800000 = `REP_K5`, same work),
`k8`, `k8 920000` (= `REP_K8`), `k8 <920000 padded to 25>`.

| workload | S112 median | S112 mode | S096 median | S096 mode |
|---|--:|:-:|--:|:-:|
| k5 (a0) | 330.7 | F | 360.7 | S |
| k5 a7 | 361.3 | S | 331.8 | F |
| k5 a25 | 362.1 | S | 333.2 | F (1 run 373) |
| k5 a41 | 362.5 | S | 330.4 | F |
| k5 a57 | 331.9 | F | 359.9 | S |
| k8 (a0) | 335.4 | | 352.9 | |
| k8 a6 | 342.1 | | 338.7 | |
| k8 a25 | 343.3 | | 333.9 | |

**p5a** (CPU 10), **p5b** (CPU 8, extra 4096-byte env variable `AA_ENV_PAD`,
cwd `/`), **p5c** (CPU 8, `while :; do :; done` pinned to SMT sibling CPU 9),
all seed 20260921 (`p5a/stats.md`, `p5b/stats.md`, `p5c/stats.md`):

| panel | leg | len | class | k5 | k8 | mode |
|---|---|--:|--:|--:|--:|:-:|
| p5a | c112 (base) | 96 | 112 | 330.9 | 333.1 | F |
| p5a | c80 | 70 | 80 | 328.3 | 337.0 | F |
| p5a | c96 | 80 | 96 | 358.3 | 341.7 | S |
| p5b | c112 (base) | 96 | 112 | 330.5 | 333.5 | F |
| p5b | c80 | 70 | 80 | 330.4 | 346.4 | F |
| p5b | c96 | 80 | 96 | 359.4 | 341.8 | S |
| p5c | c112 (base) | 96 | 112 | 332.9 | 337.0 | F |
| p5c | c80 | 70 | 80 | 335.1 | 342.1 | F (runs 346, 501 > 345) |
| p5c | c96 | 80 | 96 | 360.9 | 354.5 | S |

**Verdicts, in the order of the §160 rules.**

1. **H6 (length key): confirmed.** Pre-registered legs p1 + p2 + p4 + p5a +
   p5b = 6 + 13 + 6 + 3 + 3 = **31 legs, 0 misses** (readout's total "ok 36,
   miss 0, unassigned 0" additionally counts p3's two `k5` a0 legs and p5c's
   three). Map: **c80 F, c96 S, c112 F, c128 S, c144 F, c160 S**, identical
   in p1 and p4 → the period is **32 bytes** (c128 behaves like c96; period
   64 is excluded). No leg misses in both p1 and p4, so the mod-32 map is
   not refuted. p2 steps exactly at **88|89** (L088 359.6 S → L089 332.6 F).
   Mode gap ~29 ms (329.9 vs 358.9 in p1, ~8.8%).
2. **Mechanism (heap offset): not confirmed — "length key confirmed,
   mechanism unknown".** p3 does not alternate at either path: S112 reads
   a0/a7/a25/a41/a57 = F/S/S/S/F, S096 = S/F/F/F/S (readout: "alternation
   … NO" at both). Measured facts only: an extra argv argument changes the
   mode at both paths; at every one of the five argument lengths the two
   paths (16 bytes apart in argv[0] class) are in opposite modes; k8 moves
   with it (S112/S096: a0 335.4/352.9, a25 343.3/333.9). The predicted
   `a7 = a41, a25 = a57, a7 ≠ a25` pattern is not what happens; no new
   pattern is fitted after the fact. Consequences (a) and (b) of §160 still
   apply.
3. **H2 (file / page-cache placement): refuted.** One inode (1426930) at
   two lengths: H088 360.3 S, H089 329.4 F. Twins at 89 (L089 332.6, Q089
   331.4, different inodes 1426924/1426929) are equal.
4. **H1 (per-run bimodality): not reopened.** Most runs on the far side of
   345 ms in any leg: **2 of 15** (p5c c80, 346 and 501 ms, under SMT load).
   1 of 15 in p2 L092, p2 L094, p3 S096 k5a25; 0 in every other leg.
5. **H3: p1 and p4 agree** leg for leg (6/6 same mode, k5 medians within
   3.4 ms). Not reopened.
6. **H5: p5a map unchanged** on CPU 10 (c80 F, c96 S, c112 F).
7. **p5b: unchanged** with the stack moved (4 KiB env + cwd `/`) and the
   heap not: consistent with a heap-side key, not a proof of it.
8. **p5c: unchanged** with the SMT sibling busy. Level shift: k5 +0.4–1.4%
   against p5b (c112 332.9 vs 330.5, c96 360.9 vs 359.4, c80 335.1 vs
   330.4 with one 501 ms spike); k8 c96 354.5 vs 341.8 (+3.7%).
9. **k8: ~2% co-movement confirmed in direction.** Median of k8 leg medians,
   class mod 32 = 0 vs 16: p1 342.2 / 336.8 (+1.6%), p2 342.4 / 334.5
   (+2.4%), p4 343.1 / 337.6 (+1.6%), p5a 341.7 / 335.0 (+2.0%), p5b 341.8 /
   339.9 (+0.6%), p5c 354.5 / 339.5 (+4.4%). Always higher at mod 0, but
   legs overlap (p5b c80 346.4 at mod 16); k8 has no clean mode. c160 k8 is
   high in both p1/p4 (355.7/350.6).

**Existing cross-class results (footnote table).** Classes read from every
hintbench `samples.json` `header.labels` (170 files, the same set as
§160's archive; class formula as above; the designer's dump
`scripts/hintbench_aa_study/chunk.py` groups the same legs). "Round" =
driver round batch, "confirm" = its confirm batch, "holdout-batch2{,b}" =
the `bench_panel.sh` panels.

| result | lengths (base / cand / aa) | classes | consequence |
|---|---|---|---|
| Oracle rounds (46), confirms (39), null panels 1–2 | 75/75/73, 83/83/81, 76 | all c96 | fine: one class |
| Oracle holdout (`hintbench-oracle-holdout`) | base 74, comb 74, best1f 76, aa 72 | base/comb/best1f c96, **aa c80** | its A/A is cross-class (aa k5 320.7 vs base 350.5, the "1.0938 at k5" of `oracle.md`); the combination **1.0881 is same-class c96** |
| Exp4–6 round batches (`jev-v4-r5`, `random-r5`, `jev-v42-r5`, `exp6-*`) | 83–86 / same / 81–84 | all c96 | same class as the oracle |
| Exp4–6 first holdouts (`*/holdout`) | 82–85 / same / 80–83 | all c96 | same class as the oracle |
| Exp4–6 confirm batches (`*/round-N/confirm`, 32) | 91–94 / same / 89–92 | all **c112** | internally fine, but the confirm rule compared a c96 round ratio with a c112 confirm ratio; rev's **1.28 at k5** (round-3 binary, `unroll.count=8`) is c112, its 1.02 is c96 |
| Exp5 §147 batch 1 (rejected) / batch 2 (used), `jev-v42-r5/holdout{,-batch2}` | 85/85/83 ; 92/92/90 | c96 ; **c112** | batch 2's 1.0724 and its "85.5% of the oracle" are scored against c96 references (cross-class) |
| Exp6 `exp6-ctl`, `exp6-rev` `holdout-batch2` | 90/90/88 | base/cand c112, **aa c96** | the §152/§153 A/A failures (0.9875, 0.9864) |
| Exp6 `exp6-pv` `holdout-batch2` | 89/89/87 | base/cand c112, **aa c96** | the §155 A/A failure (0.9846) |
| Exp6 `exp6-pv` `holdout-batch2b` | 90/90/88 | base/cand c112, **aa c96** (mixed) | the §158 A/A failure (0.9864) |
| Exp6 `exp6-ctl`, `exp6-rev` `holdout-batch2b`; `exp6-both` `holdout-batch2` | 91/91/89 | all c112 | A/A passed (1.0002, 1.0012, 1.0010), but the panel is c112 while the holdouts, rounds and oracle are c96 |

This reproduces decision 95's split exactly: the 20 Exp6 round batches and
4 first holdouts (slow, c96) against the 18 confirm batches and 7 panel base
legs (fast, c112), and all 4 A/A failures of the "aa k5/k8 slow" shape are
the 4 panels whose aa leg alone is c96 (aa lengths 88/88/87/88 against
base 90/90/89/90: ctl b2, rev b2, pv b2, pv b2b). **Which Exp6 numbers are same-class with the oracle:** the
training (round) ratios (1.0742 / 1.0780 / 1.0518 / 1.0754) and the first
holdout ratios — yes (c96). The confirm ratios and every panel
(holdout-batch2/2b) number — no (c112, or mixed). The headlines are not
recomputed here; whether to re-measure the confirms/panels in class 96 is
the owner's call. Only the baseline binary's map is measured; a candidate
binary's k5 may map differently (rev's round-3 binary: 1.02 in c96, 1.28 in
c112).

The fix — every label of a timing batch executed from a path of the same
length, 80 bytes (class 96, the oracle's and every round batch's class) —
is being implemented in `scripts/bench.py` under decision 97.

### 162. The pinned alias verified on hintbench (3-leg A/A, class 96)

Command (2026-09-23 ~20:35 JST, machine idle, pinned mode = default):
```
export TARGET=hintbench
scripts/bench_panel.sh artifacts/hintbench-aa-study/p6-pinned 15 3 20260923 \
    base=artifacts/hintbench-sites/baseline/bin \
    aa=artifacts/hintbench-sites/baseline/bin \
    cand=artifacts/hintbench-sites/baseline/bin
```
All three labels are the same frozen baseline binary (Exp6 `timing/base`,
stripped sha256 a84b7c0dfe37e4f6…, `p6-pinned/panel.txt`) — a 3-leg A/A of
the decision-97 fix itself, not of a plan.

**Pre-stated pass criteria** (written before reading the numbers):
1. All three labels pinned to argv0 length 80, class 96 (`panel.txt`,
   `stats.json`).
2. k5 leg medians in the slow mode (§161 len-80 legs: p1/p4 c96
   358.9/358.8, p5a/b/c c96 358.3/359.4/360.9, p3 S096 a0/a57
   360.7/359.9), not the fast ~326–333 ms mode.
3. Aggregate ratio (geomean) of `aa` and `cand` vs `base` within ±0.5%
   (the study's rule 1, `results.md` §160).

**Numbers** (`artifacts/hintbench-aa-study/p6-pinned/stats.json`,
`panel.txt`):

argv0, from `panel.txt` (`argv0 mode pinned`) and `stats.json`
(`argv0_class: 96`, `argv0_classes: [96]`): all three legs len 80 class
96 — `base` `.../00-base_______________`, `aa` `.../01-aa_________________`,
`cand` `.../02-cand_______________`. Criterion 1: **pass**.

k5 leg medians (ms, `stats.md`): base 356.8, aa 359.4, cand 357.7 — base
and cand sit 0.6–1.5 ms below the study's lowest len-80 slow median (358.3,
p5a), aa is within the len-80 slow spread; all ~24–29 ms above the fast
mode. Unambiguously slow, not fast. k8 leg medians: base 341.2, aa 338.9,
cand 344.8, consistent with the study's slow-class k8 band (p1/p5a/p5b c96:
341.2/341.7/341.8). Criterion 2: **pass**.

Aggregate ratios (geomean, `stats.md`): aa **1.0004** [0.9977, 1.0032],
half-width 0.27%; cand **0.9975** [0.9944, 1.0007], half-width 0.32%. Both
inside ±0.5%. Criterion 3: **pass**.

`ls artifacts/timing-run/` after the run: empty (no leftover pinned-alias
directories).

**Verdict: pass.** The 80-byte pinned alias (decision 97) puts every label
of a batch in class 96, the study's slow mode, and an A/A of three copies
of the same baseline binary through it reads flat (1.0004, 0.9975), inside
the pre-registered A/A tolerance. This closes the loop opened in §160/§161:
the fix works on the binary and workload it was built for.

### 163. argv[0] class check on jaq and zopfli: pre-registration

Written before any number of this check exists (HANDOFF 4 row 3e, decision 97
(d)). Nothing is built, nothing is sent over HTTP. Both targets copy argv onto
the heap before reading input (jaq `cli.rs:167` `args_os()`, zopfli
`main.rs:23` `env::args().skip(1)`). Question: does either target's timing
depend on argv[0]'s byte length the way hintbench's k5 does (results.md 161:
class c = max(32, (len+23) & ~15), c96/c128 slow, c80/c112 fast, period 32)?

**Binaries.** One stripped copy of the frozen baseline per target, four hard
links to that one inode (byte identity is structural; H2, file placement, was
refuted in 161, so a shared inode is safe and removes jaq's copy-to-copy page
placement drift from the comparison):
- jaq: `artifacts/jaq-search/jev-r5/baseline/bin` (sha256 e183c81d…),
  stripped 83f7eb239c786c8c… = `oracle-A2-holdout/timing/base`.
- zopfli: `artifacts/zopfli-headroom/bin/baseline` (sha256 8b0ba235…),
  stripped 79c3322677aa336f… = `zopfli-aa/A1` (24).

**Legs** (exec path length → glibc class): c96 = len 80 (base of every ratio;
the length of bench.py's pinned alias), c80 = len 64, c112 = len 96,
c128 = len 112. The hintbench study used len 70 for c80; 64 is the same class
and, by mimalloc's bin table (hypothesis, not measured), puts the four legs in
four distinct mimalloc bins (64/80/96/112); jaq's global allocator is
mimalloc, so for jaq the glibc class only labels the legs and the hypothesis
is generic length sensitivity, not the hintbench map. zopfli uses glibc.

**Commands** (sequential, never concurrent; `--dry-run` each first):
    scripts/target_aa_classes.sh zopfli   # holdout cases (Stage 0 set), CPU 2,
        # gap 0, stdout pipe, warmup 3, runs 18, shuffle 20260926, ~9.7 min
    scripts/target_aa_classes.sh jaq      # training cases, CPU 4, gap 250 ms,
        # stdout devnull, warmup 3, runs 35, shuffle 20260925, ~9.6 min
Each is one `bench.py run --argv0-raw` panel (4 labels x 3 cases), then
`bench.py stats --base c96 --resamples 10000`, then
`scripts/target_aa_classes_readout.py` → `artifacts/<t>-aa-classes/
{paths.tsv,panel.txt,cmd.txt,samples.json,stats.json,stats.md,readout.txt}`.
Budget: 3.78 s/label-round for jaq (oracle-A2 round-01, 54 label-rounds in
204 s), 6.94 s for zopfli (24 A/A, 36 in 250 s). bench.py's multi-class
WARNING is expected. zopfli writes `hold-*.dat.gz` beside its inputs; the four
legs overwrite the same three files in turn, as in Stage 0.

**Readout rules** (ratio = t_c96 / t_leg, > 1 = leg faster):
  per case w, leg L != c96:
    med_ratio = median(c96 runs) / median(L runs)
    boot ratio + 95% CI = stats.json per_workload[L][w] (mean-based, paired)
    spread = max(IQR/median of L's runs, IQR/median of c96's runs) / 2
    SIGNIFICANT iff the CI excludes 1 AND |med_ratio - 1| > spread
    LARGE iff SIGNIFICANT AND |med_ratio - 1| >= M
      (M = 3% on jaq, its frozen MDE and the top of its 2-4% A/A; 1% on zopfli)
  Rule 1  leg aggregate (geomean) outside [0.995, 1.005] -> flag.
  Rule 2  (broad effect) a leg with every case SIGNIFICANT, one sign, and Rule 1.
  Rule 3  (case-local effect, the hintbench k5 shape) a case in which at least
          two legs are LARGE with the same sign.
  Verdict: CLASS EFFECT if Rule 2 or Rule 3 holds somewhere; otherwise
  FLAG, NOT CLAIMED if Rule 1 flags a leg or any case/leg is LARGE (one leg
  alone is not claimed); otherwise NULL. Reported, not a gate: per case the
  sign of each SIGNIFICANT leg and whether it matches hintbench's map read
  against c96 (c80 and c112 shifted the same way, c128 not shifted).

**Target-specific status of a verdict.**
- zopfli (A/A 0.14% aggregate, 0.29% worst case, 24): one panel decides.
- jaq: same-binary legs move 2-4% within a batch (e.g. oracle-A2 round-01
  objsearch aa 1055.5 vs base 1008.4 ms, both c96), and decision 80 says a
  within-batch CI beyond the MDE needs an independent batch. So (a) Rule 1
  is expected to fire by noise alone: FLAG, NOT CLAIMED is the expected jaq
  null outcome; (b) a jaq CLASS EFFECT from this panel is provisional and
  becomes a result only if a second panel with another seed (~10 min, the
  owner's call) reproduces Rule 2 or Rule 3 in the same case(s) with the same
  signs; (c) a jaq NULL or FLAG means "no length effect >= max(spread, 3%) at
  lengths 64/80/96/112", not "no length effect" (readout prints the panel's
  largest spread threshold).

**Archive classes** (from `header.labels`; every archived batch predates the
decision-97 alias, so the exec path was the label path):
- jaq, `artifacts/jaq-search/**/samples.json`: 167 batches, 505 legs, lengths
  73-87, all c96, none mixed. Pre-search jaq: `jaq-aa` c64, `jaq-plain` c64,
  `jaq-exp1`/`jaq-exp2` holdout c64 (T0) and c80, `jaq-headroom` c80 baseline
  (len 65) with configs mixed c80/c96 in one batch (c96: g1-tailfold-prefer,
  g1-tfstyle-data-and-control, g2-unroll-thr300, g2-unroll-thr1000,
  g2-unroll-runtime, g3-loop-distribute).
- zopfli: `zopfli-aa` c64 (both legs); `zopfli-headroom` headroom/confirm and
  `zopfli-unroll`: c80 baseline (len 65) with configs mixed c80/c96 in one
  batch.

**Consequences.** Either way, every new batch stays pinned to len 80 / class
96 (decision 97); nothing in bench.py changes.
- NULL / FLAG, NOT CLAIMED: recorded as such; no footnotes; campaigns proceed.
- CLASS EFFECT on zopfli: the Stage 0 cross-class ratios (26, 31: c96 configs
  against the c80 baseline; the c64 A/A of 24) get a footnote in the style of
  161's table; zopfli campaigns use class 96 only.
- CLASS EFFECT on jaq, once confirmed: the search/oracle archive is
  single-class (c96) and needs no footnote; the pre-search jaq batches above
  (Stage 0 A/A, headroom, Exp1/Exp2) are cross-class relative to it and get a
  footnote. Headlines are not recomputed here.

### 164. argv[0] class check on jaq and zopfli: results

Per §163's protocol, one `bench.py run --argv0-raw` panel per target (4
labels x 3 cases, hard links to one stripped baseline binary), then
`bench.py stats --base c96 --resamples 10000`, then
`target_aa_classes_readout.py`. Commands, exactly as recorded in each run's
`cmd.txt`:

```
$ python3 -u scripts/bench.py run --cpu 2 --warmup 3 --runs 18 --stdout pipe \
    --gap-ms 0 --shuffle 20260926 --argv0-raw \
    --label c96=artifacts/zopfli-aa-classes/bin/c096xxxxxxxxxxxxxxxx \
    --label c80=artifacts/zopfli-aa-classes/bin/c080 \
    --label c112=artifacts/zopfli-aa-classes/bin/c112xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
    --label c128=artifacts/zopfli-aa-classes/bin/c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
    --workload text=targets/zopfli/workloads/hold-text.dat \
    --workload binary=targets/zopfli/workloads/hold-binary.dat \
    --workload json=targets/zopfli/workloads/hold-json.dat \
    --out artifacts/zopfli-aa-classes/samples.json
$ python3 -u scripts/bench.py stats artifacts/zopfli-aa-classes/samples.json \
    --base c96 --seed 20260926 --resamples 10000 \
    --json artifacts/zopfli-aa-classes/stats.json

$ python3 -u scripts/bench.py run --cpu 4 --warmup 3 --runs 35 --stdout devnull \
    --gap-ms 250 --shuffle 20260925 --argv0-raw \
    --label c96=artifacts/jaq-aa-classes/bin/c096xxxxxxxxxxxxxxxxxxx \
    --label c80=artifacts/jaq-aa-classes/bin/c080xxx \
    --label c112=artifacts/jaq-aa-classes/bin/c112xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
    --label c128=artifacts/jaq-aa-classes/bin/c128xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx \
    --workload objsearch='.[] | select(.k == "v") | .id' \
       targets/jaq/workloads/train-objects.json (x4) \
    --workload strproc='[.[] | .name | ascii_downcase | length] | add' \
       targets/jaq/workloads/train-strings.json (x8) \
    --workload readwrite=-c '.' targets/jaq/workloads/train-ndjson.json (x2) \
    --out artifacts/jaq-aa-classes/samples.json
$ python3 -u scripts/bench.py stats artifacts/jaq-aa-classes/samples.json \
    --base c96 --seed 20260925 --resamples 10000 \
    --json artifacts/jaq-aa-classes/stats.json
```

**Contamination note (zopfli run 1, superseded).** zopfli run 1
(`artifacts/zopfli-aa-classes-run1-contaminated/`, panel 21:11:01-21:21:05
JST) ran during the same window another agent used to invoke
`targets/zopfli/workloads/gen.py`, which truncates-then-rewrites
`targets/zopfli/workloads/hold-{text,binary,json}.dat` in place. Filesystem
timestamps on the three inputs read 21:13 JST, i.e. inside the panel's
10-minute span. This was a protocol violation by that agent: AGENTS.md's
concurrency rule ("never run two timing benchmarks concurrently"; §5 below
extends it explicitly to workload generation) was not followed, and a
zopfli invocation that opened one of the three files during the ~2 s
truncate-then-rewrite window could have read a short (partially-written)
file, silently corrupting that one run's timing (and, since zopfli's output
size depends on input size, potentially its measured wall time). gen.py's
docstring guarantees the *rewritten* content is byte-identical to what was
there before (fixed seed, same size, same bytes) — the input is not stale
data, only briefly incomplete mid-write.

Checked for the resulting outlier: per-run min/median ratios (`stats.md`)
for every leg x case in run 1 are all >= 0.984 (worst: c128 binary min
1659.4/1663.5 = 0.9975; every text/binary/json leg's min ratio sits within
0.16-1.03% of its median ratio) — none of the truncated-read signature
(a much smaller output, hence a much shorter or malformed run) that a short
read would produce. The verdict itself (NULL, see run 1's `readout.txt`)
does not depend on the flagged window. Nonetheless run 1 is recorded as
**contaminated and superseded**, not used for the target-vs-length verdict;
run 2, run cleanly after the contaminating process had finished and with no
further writes to `targets/zopfli/workloads/`, is the record.

**zopfli (run 2, clean; `artifacts/zopfli-aa-classes/`, 21:30:57-21:41:04
JST).** Baseline `artifacts/zopfli-headroom/bin/baseline`
(sha256 8b0ba235be9bf45c1...), stripped 79c3322677aa336f8f... (four hard
links, one inode). Holdout cases (Stage 0 set), CPU 2, gap 0, stdout pipe,
warmup 3, runs 18, shuffle 20260926.

| case | leg | median ms | med ratio vs base | boot ratio | 95% CI | spread | sig |
|---|---|--:|--:|--:|---|--:|:-:|
| text | c96 (base) | 2755.2 | 1 | 1 | | | |
| text | c128 | 2754.2 | 1.0004 | 1.0004 | [0.9965, 1.0044] | 0.52% | no |
| text | c112 | 2761.5 | 0.9977 | 0.9980 | [0.9935, 1.0027] | 0.56% | no |
| text | c80 | 2754.0 | 1.0004 | 1.0002 | [0.9955, 1.0048] | 0.52% | no |
| binary | c96 (base) | 1691.4 | 1 | 1 | | | |
| binary | c128 | 1687.8 | 1.0021 | 0.9986 | [0.9942, 1.0031] | 0.61% | no |
| binary | c112 | 1691.0 | 1.0002 | 1.0000 | [0.9951, 1.0052] | 0.61% | no |
| binary | c80 | 1691.3 | 1.0000 | 0.9990 | [0.9940, 1.0042] | 0.61% | no |
| json | c96 (base) | 2764.0 | 1 | 1 | | | |
| json | c128 | 2742.8 | 1.0077 | 1.0049 | [1.0000, 1.0098] | 0.59% | **yes** |
| json | c112 | 2742.0 | 1.0080 | 1.0053 | [1.0003, 1.0096] | 0.46% | **yes** |
| json | c80 | 2765.6 | 0.9994 | 0.9999 | [0.9953, 1.0046] | 0.45% | no |

| leg | aggregate (geomean) | 95% CI | Rule 1 (+-0.5%) | Rule 2 |
|---|--:|---|:-:|:-:|
| c128 | 1.0013 | [0.9986, 1.0038] | ok | no |
| c112 | 1.0011 | [0.9984, 1.0038] | ok | no |
| c80 | 0.9997 | [0.9972, 1.0023] | ok | no |

Per case, significant legs: text (none), binary (none), json (c128+,
c112+, both under M=1.0%, so not LARGE — "hintbench map: no" for all
three). Largest per-case spread threshold 0.61%; M = 1.0%. json's two
significant-but-not-large legs (c128, c112) do not satisfy Rule 3 (needs
>= 2 LARGE legs, same sign) or Rule 2 (needs every case significant, one
sign — text and binary are not). **Rule 1: no leg flags. Rule 2: no. Rule
3: no. VERDICT: NULL.**

**jaq (`artifacts/jaq-aa-classes/`, 21:21:07-21:30:40 JST).** Baseline
`artifacts/jaq-search/jev-r5/baseline/bin` (sha256 e183c81d1d7e9177...),
stripped 83f7eb239c786c8c98... (four hard links, one inode). Training
cases, CPU 4, gap 250 ms, stdout devnull, warmup 3, runs 35, shuffle
20260925.

| case | leg | median ms | med ratio vs base | boot ratio | 95% CI | spread | sig |
|---|---|--:|--:|--:|---|--:|:-:|
| objsearch | c96 (base) | 1022.3 | 1 | 1 | | | |
| objsearch | c112 | 1031.9 | 0.9907 | 0.9920 | [0.9828, 1.0019] | 1.38% | no |
| objsearch | c80 | 1022.7 | 0.9996 | 1.0050 | [0.9938, 1.0157] | 1.29% | no |
| objsearch | c128 | 1029.2 | 0.9933 | 0.9918 | [0.9810, 1.0029] | 2.08% | no |
| strproc | c96 (base) | 1093.0 | 1 | 1 | | | |
| strproc | c112 | 1093.9 | 0.9992 | 1.0015 | [0.9961, 1.0074] | 1.06% | no |
| strproc | c80 | 1091.6 | 1.0013 | 1.0037 | [0.9977, 1.0100] | 1.06% | no |
| strproc | c128 | 1095.8 | 0.9975 | 1.0012 | [0.9950, 1.0076] | 1.06% | no |
| readwrite | c96 (base) | 885.2 | 1 | 1 | | | |
| readwrite | c112 | 881.9 | 1.0038 | 1.0068 | [0.9984, 1.0171] | 0.66% | no |
| readwrite | c80 | 882.9 | 1.0026 | 1.0006 | [0.9904, 1.0121] | 0.68% | no |
| readwrite | c128 | 882.8 | 1.0028 | 0.9953 | [0.9808, 1.0092] | 0.87% | no |

| leg | aggregate (geomean) | 95% CI | Rule 1 (+-0.5%) | Rule 2 |
|---|--:|---|:-:|:-:|
| c112 | 1.0001 | [0.9951, 1.0060] | ok | no |
| c80 | 1.0031 | [0.9975, 1.0093] | ok | no |
| c128 | 0.9961 | [0.9893, 1.0034] | ok | no |

Per case, significant legs: none in objsearch, strproc or readwrite
("hintbench map: no" throughout). Largest per-case spread threshold
2.08%; M = 3.0% (a jaq shift below max(spread, M) cannot be claimed here,
per §163(c)). **Rule 1: no leg flags. Rule 2: no. Rule 3 (needs >= 2 LARGE
legs in one case): no leg is even SIGNIFICANT. VERDICT: NULL.** This is
the pre-registered expected jaq outcome (§163's "FLAG, NOT CLAIMED is the
expected null" was the *floor* prediction given jaq's 2-4% batch noise;
the panel in fact landed inside tolerance on Rule 1, so the outcome is the
stronger NULL, not FLAG, NOT CLAIMED).

**Verdicts and consequence.** Both targets: **NULL** — no argv[0]-length
class effect distinguishable from A/A noise, at any of lengths 64/80/96/112
(classes c80/c96/c112/c128), on either target. This differs from
hintbench's k5 (results.md §161), which alternates by ~9% with a clean
32-byte period on the same class boundaries; neither jaq nor zopfli shows
anything resembling that mode split. Per decision 97(d)/HANDOFF §4 row 3e:
no footnote is needed for jaq's or zopfli's archive on class grounds (their
existing single-class batches, results.md §163's "Archive classes" table,
stand as measured); every new batch on either target stays pinned to the
80-byte / class-96 alias (decision 97) regardless — that pin was never
conditional on this check finding an effect, it is also what keeps every
batch of a campaign internally comparable. The hintbench k5 length
sensitivity (decision 97) is therefore **target-specific**, not a general
property of "Rust binary reading argv before input" — it does not
generalize to jaq (mimalloc allocator) or zopfli (glibc allocator) on this
machine.

## zopfli campaign --- preparation

### 165. Baseline, training split, A/A and profile

Context: HANDOFF.ja.md §4 row 6 ("get zopfli through the pipeline: perf-mark
hot functions, build an oracle covering both function attributes and loop
metadata, then run Jev" --- gloss of the Japanese row). Decisions 96-99 (per-feature n≥3 ablation rule, hintbench's
argv[0]-length mode and the 80-byte/class-96 pin, vocabulary v6 + zopfli's
search/training split, the jaq/zopfli argv[0]-class NULL and the
no-writes-during-timing rule). Commits `c759f18` (search-training split,
fixed `-hints-allow-reordering=false`, `--seed-offset`, vocabulary v6),
`93117a0`/`820b2f4` (target-generic `scripts/target_sites.sh` /
`target_sites_report.py`, and the `--flags` parsing fix).

**Search-training split.**

```
$ python3 targets/zopfli/workloads/gen.py --check
542239adfe8ca616be6963d9d87cb62d21584ad632bbff84cbd753f17b5e910c    1433600  hold-binary.dat  seed=20260921102
a52a647ea929d8e6b6eac3f8cf73d3c9a177f79fe4c74ab78f724cc9b850e34e    1433600  hold-json.dat  seed=20260921103
40d63cd415fdc8cccee8c262c2455b809087e012aafca203928d8846e7f2a791    1433600  hold-text.dat  seed=20260921101
9f98a1a1c09526555c00126642be81024bac19917ad0bc8600b92f0f61ea271a     917504  search-binary.dat  seed=20260923202
76f17bc27fd2642ccf541f6b6b47e4e39bff95dfb638f08a6ce161e7e08c11c0     917504  search-json.dat  seed=20260923203
8409eac2944d1be6f2140dbf97445aaf82fe853828ec7f9f12545ade6574954e     917504  search-text.dat  seed=20260923201
f84dea12c0831b3a340a64d022290f73dd75c65ae892655dd366f6707de95e49    1433600  train-binary.dat  seed=20260921002
15170b05967a6ab1621b1bea980a49b66a99ccec2cf3ade06cd0a59a603731b3    1433600  train-json.dat  seed=20260921003
d0063a2e4ab40c6791a2a28b75aec370ee9ed2ef65e11700078c1489a335dae8    1433600  train-text.dat  seed=20260921001

$ sha256sum targets/zopfli/workloads/search-{text,binary,json}.dat
8409eac2944d1be6f2140dbf97445aaf82fe853828ec7f9f12545ade6574954e  search-text.dat    (917,504 B = 896 KiB)
9f98a1a1c09526555c00126642be81024bac19917ad0bc8600b92f0f61ea271a  search-binary.dat  (917,504 B = 896 KiB)
76f17bc27fd2642ccf541f6b6b47e4e39bff95dfb638f08a6ce161e7e08c11c0  search-json.dat    (917,504 B = 896 KiB)
```

`gen.py --check` has no built-in pass/fail comparison (it only prints the
sha256/size/seed of whatever files already exist); the built-in guarantee
it does document is that the same seed always regenerates the same bytes.
Checked by hand against §21's six pinned holdout/PGO hashes: `train-text`
`d0063a2e...`, `train-binary` `f84dea12...`, `train-json` `15170b05...`,
`hold-text` `40d63cd4...`, `hold-binary` `542239ad...`, `hold-json`
`a52a647e...` — **all six match §21 exactly, no drift.** The three
`search-*.dat` are new (decision 98): 917,504 B = 896 KiB each, as
specified, disjoint seeds `20260923{201,202,203}` from both `train-*`
(`2026092100{1,2,3}`) and `hold-*` (`2026092110{1,2,3}`). Holdout stays the
§21 set, untouched. `scripts/target_common.sh`'s zopfli case now carries
`FIXED_RUSTFLAGS=('-Cllvm-args=-hints-allow-reordering=false')` (confirmed
by reading the script directly), satisfying non-negotiable 5 for this
target the same way jaq and hintbench already do.

**Plugin-off base build.** `export TARGET=zopfli; scripts/target_sites.sh
base`, log `artifacts/zopfli-sites/step-base.log`:

```
========== a. zopfli baseline, no plugin, profile .../pgo/zopfli/merged.profdata ==========
  build time     5 s (rc=0)
  .text sha256   9aca86fcd89a759f60bb5d83ac768ff83a72b21516bee26ab0cd0982fa76cbdf
```

`.text` sha is **identical** to Stage 0's `9aca86fc...` (§22). Correctness
(`artifacts/zopfli-sites/correctness-base.txt`) lists nine sha256 lines, one
per input's `.gz` output, with no separate PASS/FAIL verdict line in the
file itself; checked by hand: the six train/hold hashes match §21/§22's
`train-text.dat`/`train-binary.dat`/`train-json.dat`/`hold-text.dat`/
`hold-binary.dat`/`hold-json.dat` rows exactly, byte for byte. The three
`search-*.dat` `.gz` hashes have no prior record to compare against (the
search split is new, decision 98) — they are established here as the
reference for future correctness checks on this split.

Identity with Stage 0: `artifacts/zopfli-sites/stage0.sha256` holds the
pre-existing `target-zopfli-pgo-use` binary's sha256, copied in as
`stage0.bin`: `8b0ba235be9bf45c167f7cbf39edb096668e0f2eb1d320dcbd1718d1f97ea8a4`.
`scripts/norm_code_diff.py` compared that binary's normalised code against
the new base build, rc = 0
(`artifacts/zopfli-sites/norm-stage0-vs-base.rc`), summary line
(`norm-stage0-vs-base.txt`):

```
target-zopfli-sites-base/x86_64-unknown-linux-gnu/release/zopfli: hash e4d0dd7fc425c1fe  IDENTICAL
  symbols: 442 (base 442), changed 0, only-in-base 0, only-here 0
```

So the plugin-off base build is code-identical to both Stage 0 records: the
raw `.text` sha256 matches §22's `9aca86fc...`, and the normalised
whole-code hash (442 symbols, 0 changed/added/removed) matches the
pre-existing Stage 0 binary too.

**A/A, class 96 pinned (decision 97).** Pre-registered MDE rule (decision
27's policy floor, stated before the numbers below): MDE = max(2 x worst
per-workload CI half-width, 3%).

```
$ TARGET=zopfli BENCH_SET=training scripts/bench_panel.sh \
    artifacts/zopfli-sites/aa-training 18 3 20260923 \
    base=target-zopfli-sites-base/.../zopfli aa=target-zopfli-sites-base/.../zopfli \
    aa2=target-zopfli-sites-base/.../zopfli
$ TARGET=zopfli BENCH_SET=holdout scripts/bench_panel.sh \
    artifacts/zopfli-sites/aa-holdout 18 3 20260923 \
    base=target-zopfli-sites-base/.../zopfli aa=target-zopfli-sites-base/.../zopfli \
    aa2=target-zopfli-sites-base/.../zopfli
```

Exact `label=path` arguments are not separately logged; the form above is
inferred from `bench_panel.sh`'s "null panel" usage (its header docstring:
several labels pointing at one binary, copied and stripped per label) and
confirmed by the panel logs' own sha lines: all three of
`artifacts/zopfli-sites/aa-training/timing/{base,aa,aa2}` (and the same
three under `aa-holdout/timing/`) hash to
`79c3322677aa336f8fab45c449559cac9568277636afdfc998e9d07bae887a98` --- the
**same stripped hash results.md §164 already recorded** for the Stage 0
baseline (`artifacts/zopfli-headroom/bin/baseline`, sha256 `8b0ba235...`
unstripped, stripped to this same `79c33226...`). This is a
third, independent identity confirmation for the new base build, beyond
this section's raw `.text` sha (matches §22's `9aca86fc...`) and normalised
whole-code hash (matches the pre-existing Stage 0 binary): three separate
build/strip events across the project now collapse to one stripped-binary
hash.

Both panels: `argv0_class` = 96 in `stats.json` (log: "argv0 pinned class
96", all three labels len 80), cpu 2, gap 0 ms, stdout pipe, warmup 3, 18
rounds, bootstrap 10000 resamples seed 20260923. Wall clock: training
21:42:54-21:48:04 JST (~5m10s), holdout 21:48:04-21:55:39 JST (~7m35s), as
given by the task that scheduled this preparation and independently
confirmed here by artifact mtimes on
`artifacts/zopfli-sites/{aa-training,aa-holdout}.log`, which fall exactly
on those two windows.

*Training set* (`artifacts/zopfli-sites/aa-training/stats.json`,
`.log`). Base medians: text 1905.8 ms, binary 1155.6 ms, json 1847.0 ms.

| leg | workload | median ms | ratio vs base | 95% CI |
|---|---|--:|--:|---|
| aa | text | 1908.1 | 1.0006 | [0.9980, 1.0034] |
| aa | binary | 1150.8 | 1.0012 | [0.9912, 1.0092] |
| aa | json | 1843.4 | 1.0034 | [0.9982, 1.0086] |
| aa2 | text | 1913.1 | 0.9976 | [0.9940, 1.0013] |
| aa2 | binary | 1156.3 | 0.9958 | [0.9857, 1.0041] |
| aa2 | json | 1839.5 | 1.0082 | [1.0016, 1.0163] |

Aggregate (geomean): aa 1.0017 [0.9983, 1.0049], aa2 1.0005 [0.9960,
1.0043]. Worst per-workload half-width 0.92% (aa2/binary).

One of the 12 leg x workload legs, aa2/json, has a CI that excludes 1
([1.0016, 1.0163], ratio 1.0082): at 95% coverage roughly 1 in 20 A/A legs
is expected to do this by chance alone, so 1/12 here is unremarkable, and
0.82% sits well under the 3% MDE below — no consequence for this section.
Flagged so a later reader comparing a candidate's training-set json ratio
near +0.8% knows the A/A floor already brushes that range once.

*Holdout set* (`artifacts/zopfli-sites/aa-holdout/stats.json`, `.log`).
Base medians: text 2755.1 ms, binary 1692.8 ms, json 2752.6 ms.

| leg | workload | median ms | ratio vs base | 95% CI |
|---|---|--:|--:|---|
| aa | text | 2758.1 | 0.9986 | [0.9963, 1.0006] |
| aa | binary | 1687.4 | 1.0034 | [0.9996, 1.0072] |
| aa | json | 2757.4 | 0.9992 | [0.9963, 1.0022] |
| aa2 | text | 2751.8 | 1.0008 | [0.9980, 1.0037] |
| aa2 | binary | 1691.8 | 1.0000 | [0.9962, 1.0040] |
| aa2 | json | 2761.0 | 0.9976 | [0.9949, 1.0000] |

Aggregate (geomean): aa 1.0004 [0.9988, 1.0019], aa2 0.9995 [0.9976,
1.0013]. Worst per-workload half-width 0.39% (aa2/binary).

**MDE, applying the rule stated above.** Training: max(2 x 0.92%, 3%) =
**3%**. Holdout: max(2 x 0.39%, 3%) = **3%**. Neither panel pushes the MDE
above the 3% floor — both are quiet (worst CI half-width under 1%,
consistent with the sub-1% class-96 A/A precision already seen at Stage 0
and in results.md §164) — so the pre-registered 3% floor stands as the
minimum-detectable-effect bar for the campaign that follows.

**perf profile.** `SETS=both BIN=target-zopfli-sites-base/.../zopfli
scripts/perf_marks_profile.sh artifacts/zopfli-marks 6`, log
`artifacts/zopfli-marks-profile.log`: perf 7.1.8, cpu 2, repeats 6, freq
5000 Hz, callgraph none, on the plugin-off base binary confirmed identical
to Stage 0 above. Six `.data` files:

| file | size |
|---|--:|
| `hold-text.data` | 3,468,276 B |
| `hold-binary.data` | 2,094,156 B |
| `hold-json.data` | 3,455,956 B |
| `train-text.data` | 2,410,692 B |
| `train-binary.data` | 1,438,732 B |
| `train-json.data` | 2,340,884 B |

Marks (which functions/loops get chosen for the oracle from these profiles)
are a separate agent's task under a pre-stated rule, to be recorded in the
next section.

**Pre-stated for the oracle (to be pre-registered fully in the next
section).** Vocabulary v6 (decision 98); `--site-set
oracle.selected_keys_top6`; no-op skip on; confirmation batches on the
training (search) set; holdout measured once at the end; correctness =
sha256 of all nine `.gz` outputs; argv0 class 96 throughout, per decision
97/99.

### 166. Marks, sites and the oracle pre-registration (zopfli)

Commit `e593960` (`targets/zopfli/jev-marks.txt`,
`targets/zopfli/jev-marks.rationale.md`, `targets/zopfli/sites.json`,
`targets/zopfli/sites.md`). Nothing in this section is a timing measurement;
it records what the marks and sites tooling produced from the §165 profile
and states the oracle sweep's protocol before its first arm runs, per
SPEC.ja.md §7 ("正しさは時間より先に読む" and the freeze-before-numbers
rule of §2 (f)).

**1. Marks.** The selection rule, `targets/zopfli/jev-marks.rationale.md`
§1, was written and saved before the perf tables were read: *"Rank every
function by `reach` on the three search-set profiles aggregated... Walk down
the ranking and add each function to the marks. After each addition,
recompute the union coverage... Stop after the addition that first brings
the union to >= 90% of in-binary cycles."* Non-negotiable 2 applies: Claude,
acting as the human's proxy, says only *where* (decision 58); no hint,
attribute or compiler setting is named anywhere in the marks file or the
rationale.

**6 marks** (`targets/zopfli/jev-marks.txt`), union coverage **93.37%** of
in-binary user cycles on the search set (per case: binary 86.17%, json
93.17%, text 96.58%) and **94.88%** on the holdout (binary 88.87%, json
95.76%, text 96.41%) — `jev-marks.rationale.md` §3. The rule's own walk
first crosses 90% at the seventh addition (`zopfli::lz77::find_longest_match`,
union 93.37%), which is why coverage is 93.37% and not exactly 90%: the
rule adds whole functions, not fractions of one.

The profiling recorder labels the search set `train-*.data`, even though the
bytes it reads are `targets/zopfli/workloads/search-*.dat` (decision 98's
split; `jev-marks.rationale.md` §1 states the recorder's `TRAIN_WORKLOADS`
naming, not why) — `artifacts/zopfli-marks/perf-hotness-train.txt`
is the search-set table, `perf-hotness-hold.txt` the holdout one, both from
`perf record -e cycles:u -F 5000`, 6 runs/case, on the plugin-off base build
(normalised-code identical to Stage 0, §165). Top 10 of 14 functions ranked
by reach on the search set (`self`/`reach` are the marks-file numbers, both
percent of in-binary user cycles; S = search, H = holdout; from the
inline-aware tables in `perf-hotness-{train,hold}.txt`):

| # | self S | reach S | self H | reach H | function | marked |
|--:|--:|--:|--:|--:|---|:-:|
| 1 | 43.31 | 43.31 | 41.76 | 41.76 | `find_longest_match_loop` | y |
| 2 | 40.53 | 40.53 | 42.87 | 42.87 | `squeeze::lz77_optimal` | y |
| 3 | 0.00 | 39.82 | 0.00 | 42.10 | `squeeze::get_best_lengths` | y |
| 4 | 0.00 | 39.82 | 0.00 | 42.10 | `squeeze::lz77_optimal_run` | y |
| 5 | 0.00 | 15.02 | 0.00 | 16.20 | `<ZopfliHash>::update` | y |
| 6 | 0.00 | 11.62 | 0.00 | 12.63 | `<HashThing>::update` | **removed** |
| 7 | 0.00 | 11.15 | 0.00 | 11.58 | `find_longest_match` | y |
| 8 | 0.00 | 11.01 | 0.00 | 11.45 | `<...Cache>::try_get` | n |
| 9 | 9.61 | 9.61 | 10.31 | 10.31 | `<Lz77Store>::follow_path` | n |
| 10 | 0.00 | 6.82 | 0.00 | 7.48 | `Option<u16>::eq` (core) | n |

Row 3/4's `self` is 0.00 because neither function keeps a post-LTO symbol
of its own — fully inlined — while its `reach` (everything inlined into it,
wherever fat LTO placed the code) is the third- and fourth-highest of any
function in the binary.

`<zopfli::hash::HashThing>::update` (row 6, reach 11.62% search / 12.63%
holdout) was the rule's sixth addition — the walk's union was already at
89.87% after `ZopfliHash::update` (the fifth addition) and stayed at
89.87% after `HashThing::update` (rationale §2's walk table: neither
addition moves the union, since both sit inside code the first four
additions already cover), still short of the 90% stop. It was then
**removed by the existence gate** (rationale §1 rule step 4):
`scripts/target_sites.sh dump` resolves it to a function row in both
pre-link modules, but the post-LTO report — the only report whose loop
stage runs — lists it in `unmatched_marks`, so `target_sites_report.py`'s
intersection rule (the same rule `jev_search.py`'s `unmatched_marks()`
uses) reports it **unmatched**. Removing it changed the union by **+0.00
points**, because it had already added +0.00 points on the way in: the
coverage the marks file states, 93.37%, is reached by the walk's seventh
and final addition, `find_longest_match`, with or without
`HashThing::update` in the set. The walk was not continued to refill a
seventh slot after the removal: 6 marks, not 7, is the final set.

`<zopfli::cache::ZopfliLongestMatchCache>::max_sublen` (search reach 4.03%,
14th by reach) never entered the ranking far enough to be a candidate — the
walk stops at rank 7 (`find_longest_match`, union 93.37% >= 90%) and never
reaches rank 14.

**2. Sites.** `scripts/target_sites.sh dump`, `allkeys`, `sites` and
`baseline` (`targets/zopfli/sites.json`, `targets/zopfli/sites.md`;
generated 2026-09-23T13:07:08Z). `allkeys` applies every dumped key once:
**42 keys** total — **37 `attached`**, **5 `ambiguous+attached`** (a key
that names more than one loop, applied once, all copies changed), **0
`unmatched`**, **0 `vanished`**; outputs match. The 5 ambiguous keys are
`...-fetch_sublen-cache.rs-108` (8 copies behind 1 key — the `cache.rs:108`
loop inside `try_get`/`fetch_sublen`, which is itself `loop_in_mark` under
mark 2, `lz77_optimal`; see §3 below) and four distinct
`...-update-hash.rs-150` keys (2 copies each, inside `ZopfliHash::update`,
mark 5) — 16 loops behind those 5 keys (`jev-marks.rationale.md` §3).

Restricted to `loop_in_mark` sites (decision 61 (a) — loops actually inside
a marked function's inline chain, not merely a loop a mark sits inside):
**47 sites** behind **36 distinct keys** (5 of the 36 are the ambiguous
keys above: 4 `hash.rs:150` + 1 `cache.rs:108`). `sites.md` separately
records **6** `mark_in_loop` rows excluded from this count; 42 total
allkeys minus 6 is consistent with, but not separately verified here as
identical to, the 36 `loop_in_mark` keys. Of the 36: no profile count 8,
trip < 2 fifteen, contains a call 11, FP reduction 3; `post_vectorize` set
on 2.

Cap rule, pre-registered result-blind, `sites.md` §"Loop-site cap and oracle
sizing": `no_profile,trip_lt_2,per_mark:2,top:6` — drop keys with no profile
count, drop trip < 2, keep at most 2 per mark by hotness, then keep the top
6 overall. Applied to the 36 keys this selects **5** keys, not 6: only 3 of
the 6 marks own a key that survives `no_profile`/`trip_lt_2` (see below), so
`per_mark:2` yields 2 + 2 + 1 = 5 before `top:6` even has six candidates to
choose from. Site set `oracle.selected_keys_top6`:

| key (`leaf`) | owning mark | hot% | trip | vectorized |
|---|---|--:|--:|---|
| `lz77.rs:530` | `find_longest_match_loop` | 62.70 | 74.2 | - |
| `squeeze.rs:275` | `lz77_optimal` | 16.36 | 272644.1 | - |
| `squeeze.rs:325` | `lz77_optimal` | 16.18 | 9.2 | - |
| `lz77.rs:563` | `find_longest_match_loop` | 0.28 | 5.4 | width 16 |
| `index.rs:184` | `<ZopfliHash>::update` | 0.25 | 15921.6 | - |

**Why only 5, not one or two per each of the 6 marks.** Only 3 marks own a
`loop_in_mark` site that survives `no_profile`/`trip_lt_2` at all:
`find_longest_match_loop` and `lz77_optimal` each contribute their top 2 by
hotness (the table above); `ZopfliHash::update` contributes 1
(`index.rs:184`) because its other `loop_in_mark` sites are the
`hash.rs:150` keys at trip 1.0, dropped by `trip_lt_2`. The other 3 marks
contribute nothing: `get_best_lengths`'s 7 owned sites (`sites.json` mark 3,
`n_sites_owned: 7`) are all `squeeze.rs:261/265/275/325` copies with
`hot=0` — no profile count reached them, dropped by `no_profile`;
`lz77_optimal_run` and `find_longest_match` own **zero** `loop_in_mark`
sites each (`sites.json` marks 4 and 6, `n_sites_owned: 0` both — their
reach comes entirely through the inline chain into functions that own the
loops, not from loops of their own).

Baseline dir `artifacts/zopfli-sites/baseline/` (`baseline.json`): bin
sha256 `8b0ba235be9bf45c167f7cbf39edb096668e0f2eb1d320dcbd1718d1f97ea8a4`,
`.text` sha256
`9aca86fcd89a759f60bb5d83ac768ff83a72b21516bee26ab0cd0982fa76cbdf`,
profdata sha256
`f066f5072627b070f19acfe1bfa4772b25cf5babc7752799931f579036e0ace8`,
`norm_code_diff_rc: "0"` against the plugin-off build (`outputs_match:
true`) — the same three identities §165 already established for the
plugin-off base build, now recorded against the `dump`-mode baseline that
the oracle's own arms will be built and compared against.

**3. A stated limitation (non-negotiable 2).** Stage 0's only global win at
the compiler-flag level, `-unroll-max-count=1` (+1.6%, §31.3), acted
through the `cache.rs:108` loop that sits inside `fetch_sublen`/`try_get`.
Two different things exclude it here, not one:

* `try_get` itself, the function, ranks 8th by reach (11.01% search /
  11.45% holdout, row 8 above) and lies outside the 90%-stop marks set (the
  walk stopped at rank 7). **No function-level arm (`inline_always` /
  `inline_never`) can be tried on `try_get`**: it is unmarked, full stop.
* The `cache.rs:108` **loop** is a different matter: it *is* `loop_in_mark`
  under mark 2 (`lz77_optimal`) — it is one of the 5 ambiguous keys in §2,
  `...-fetch_sublen-cache.rs-108`, 8 copies behind 1 key, hot% 1.09, trip
  6.4 (`sites.md`'s keys table). It is excluded from
  `oracle.selected_keys_top6` **by the cap rule, not by the marks set**:
  mark 2's `per_mark:2` allowance is already spent on `squeeze.rs:275`
  (hot% 16.36) and `squeeze.rs:325` (hot% 16.18), both far hotter than
  `cache.rs:108`'s 1.09, so the cap drops it before `top:6` is even applied.

**This oracle cannot measure that global win's site either way**, but the
loop half of that statement is a cap-rule fact, not a marks-coverage fact:
a different `--site-set` (a wider cap, or a hand-added key) built on the
*same* 6 marks could reach `cache.rs:108` without touching the marks file
at all. Only the function-attribute half (`try_get`) actually requires a
wider marks set.

The marks rule (§1 above) and the cap rule (§2 above) were each written and
saved before their respective tables were read, and neither is changed now
that this consequence is known — doing so would be the "the selection rule
drives the answer" failure mode both frozen rules exist to prevent.
Widening the marks set to include `try_get`, or changing the cap rule to
reach `cache.rs:108`, are each a separate, later registration, only if the
owner directs it (HANDOFF.ja.md §2 row 4 lets the human, not an agent,
redirect the marks).

**4. Oracle command**, pre-registered exactly as it will be run:

```
export TARGET=zopfli
scripts/jev_search.py --target zopfli \
    --marks targets/zopfli/jev-marks.txt \
    --sites targets/zopfli/sites.json \
    --site-set oracle.selected_keys_top6 \
    --proposer oracle --oracle-phase all --vocab v6 \
    -n 15 --warmup 3 \
    --baseline-dir artifacts/zopfli-sites/baseline \
    --out artifacts/zopfli-search/oracle
```

Dry run: **68 arms** = 12 fn (6 marks x {`inline_always`, `inline_never`},
`FN_CANDIDATES_V6` in `scripts/jev_vocab.py`) + 55 loop (5 sites x 11 v6
loop candidates: `unroll_count_{2,4,8}`, `unroll_disable` (decision 98),
`vectorize_width_{2,4,8,16}`, `interleave_count_{1,2,4}`, each against
`KEEP_DEFAULT`) + 1 combination.

**5. Rules before numbers.**

- Training set = `search-*.dat` (decision 98, §165); holdout
  (`hold-*.dat`) measured once at the end with `bench_panel.sh`, four
  labels (base, combination, best single function arm, best single loop
  arm) plus `aa`.
- MDE = **3%** (§165's rule and its floor; SPEC §2). The rule itself,
  `max(2 x worst per-workload CI half-width, 3%)`, is recomputed against
  this sweep's own null panel and holdout batch when they are taken (the
  same way hintbench's holdout batch got its own MDE at readout, §126) —
  it is not the specific 3% value carried over unevaluated from §165's
  training/holdout A/A, though §165's panels were quiet enough (worst
  half-width under 1%) that 3% is also the expected outcome here.
- "Good" = the round batch's CI excludes 1 **and** an independent
  confirmation batch agrees in sign (decision 80 (a)), and the gain exceeds
  the MDE. "Harmful" is the symmetric rule on the loss side.
- Combination arm = every site whose best candidate was confirmed with a
  ratio > 1, one candidate per site (the site's best confirmed arm, not the
  best point estimate — decision 80 (a)'s replacement rule, hintbench
  §118 (c)).
- No-op skip on (decision 80 (b)): an arm whose build is `identical` to the
  baseline (normalised instruction sequence and symbol table both match) is
  not timed and is recorded as ratio 1.0, `ci95: null`. Skipped arms are
  listed by candidate, not silently dropped from the arm count.
- Correctness: sha256 of all nine `.gz` outputs (three cases x
  train/hold/search, `correctness-base.txt`'s layout, §165) identical to
  the baseline's; an arm whose output differs is rejected regardless of
  speed and does not enter the combination arm (non-negotiable 5).
- All arms carry `-Cllvm-args=-hints-allow-reordering=false` (§165,
  `target_common.sh`'s zopfli `FIXED_RUSTFLAGS`).
- argv0 pinned to length 80, class 96 (decision 97) for every label in
  every batch; a batch whose recorded class is not 96 is `measure-failed`
  and is not silently accepted at another class.
- Per-case (text/binary/json) ratios are reported alongside the aggregate
  for every accepted arm, not only the geometric mean.
- Expected shape, stated as a prediction and not a result. Four of the
  five selected sites are unvectorized (`lz77.rs:530`, `squeeze.rs:275`,
  `squeeze.rs:325`, `index.rs:184`); the fifth, `lz77.rs:563`, already
  carries `post_vectorize` width 16. Decision 37's zopfli-specific account
  of Stage 0's flat loop-hint sweep is "early-exit byte scan (67%)", which
  points at `find_longest_match_loop` (`lz77.rs:530` sits in it) rather
  than at the other three unvectorized sites by name. Decision 22 examined
  Stage 0's two hottest loops directly and found two different reasons for
  no headroom: `hash.rs:150`'s near-zero average trip (0.95 — a loop that
  almost never runs twice has no room for a prologue) is a correctly-made
  cost-model call, and separately, `cache.rs:108` (excluded from this
  sweep, §3 above) is a loop whose trip count LLVM's own analysis fails to
  compute, so width hints cannot reach it at all — only `unroll`'s full
  range moved it, by +1.6%. Neither of those two loops is a candidate
  here (`hash.rs:150` cut by `trip_lt_2`, `cache.rs:108` by the cap), so
  decision 22's specific finding cannot be re-tested by this sweep; the
  prediction is only the general pattern decision 37 states across all
  four targets measured so far — the four unvectorized candidate sites are
  likely flat under loop-metadata hints. `inline(always)`/`inline(never)`
  on the six marked functions is a dimension Stage 0's compiler-flag sweep
  never measured at all, and is where a result, if any, is more likely to
  appear (by analogy with jaq's `Val::hash inline_always`, §138, and
  hintbench's `k2_mix inline_always`, §123).
- Cost estimate, from §165's measured medians and the driver's own batch
  shape. `scripts/jev_search.py`'s `measure()` times **3** labels per batch
  (`base`, `cand`, an in-run `aa` copy of `base` — `scripts/jev_search.py:
  3852`), not 2, over `warmup 3 + n 15 = 18` rounds each, across the 3
  search-set cases. Using §165's search-set base medians summed across
  cases (text 1905.8 ms + binary 1155.6 ms + json 1847.0 ms ~= 4.91 s per
  label per round): one batch ~= 18 rounds x 3 labels x 4.91 s ~= 265 s
  ~= 4.4 min. A confirmed arm carries two independent batches (decision
  80 (a)) ~= 8.8 min of timing, plus a build. Zopfli's plugin-off base
  build took 5 s (§165, `step-base.log`); an apply-mode arm build was not
  separately timed for this target, so the nearest sourced analogue is
  hintbench's oracle, whose 46 measured arms averaged 290 s each
  build-plus-two-batches under a different reps/label count (§127).
  **Worst case, no arm skipped and every arm confirmed: order 10 h**
  (68 x ~9 min, dominated by the ~8.8 min of timing); **expected well
  under that**, since hintbench's precedent skipped 39 of 84 arms as
  identical builds (§120, 3.1 of 3.8 hours saved) and an arm whose first
  batch does not clear the MDE is never confirmed at all.
- Measuring agent and write-up agent are separate (HANDOFF.ja.md §5): this
  section is written by the write-up agent before the measuring agent's
  first arm, and nothing in it is edited once the run starts.

### 167. Jev vs random on zopfli: pre-registration (decision 96, n=3 each)

Written before the oracle (§166) has finished and before any Jev number for
zopfli exists. This section fixes the six runs, the command, and the rules
that will govern their reading, per SPEC.ja.md §2's per-feature-effect
bullet (decision 96) and AGENTS.md non-negotiable 4 (every Jev decision is
an independent toggle, ablated against a random control).

**Six runs.**

| run id | proposer | seed-offset |
|---|---|--:|
| `zopfli-jev-r0` | jev | 0 |
| `zopfli-rand-r0` | random | 0 |
| `zopfli-jev-r1` | jev | 1000 |
| `zopfli-rand-r1` | random | 1000 |
| `zopfli-jev-r2` | jev | 2000 |
| `zopfli-rand-r2` | random | 2000 |

**Command** (one template, `<proposer>`/`<seed-offset>`/`<run id>`
substituted per row above; everything else fixed across all six runs):

```
export TARGET=zopfli
scripts/jev_search.py --target zopfli \
    --marks targets/zopfli/jev-marks.txt \
    --sites targets/zopfli/sites.json \
    --site-set oracle.selected_keys_top6 \
    --proposer <jev|random> --seed-offset <0|1000|2000> \
    --rounds 5 --vocab v6 --readout forced_top1 \
    --source-comments strip --explore 2 --explore-revisit 0 --pv-untried off \
    -n 15 --warmup 3 \
    --baseline-dir artifacts/zopfli-sites/baseline \
    --measure-holdout --out artifacts/zopfli-search/<run id>
```

**Why this configuration.** Of Experiment 6's four hintbench arms (ctl,
rev, pv, both --- §150-§159), `ctl` is the only one with a clean mechanism
record: `rev`'s revisit budget is under redesign (decision 93 --- it never
reached the argmax-non-KEEP site it was built for), and `pv`'s
`post_vectorize`-untried judgement line is null (decision 93, the P mass it
was meant to move stayed at 0.01-0.02). So this campaign runs zopfli's
first Jev/random comparison at `ctl`'s settings: `--explore 2
--explore-revisit 0 --pv-untried off`, `--readout forced_top1`,
`--source-comments strip`, vocabulary v6 (decision 98, adds
`unroll.disable` for zopfli's unvectorized loops), 5 rounds, n=15/warmup=3
per batch, site set `oracle.selected_keys_top6` (§166, 5 sites behind 6
marks), baseline dir from §166. `--measure-holdout` is added on every run
(all six, jev and random alike) so the holdout ratio is available per run
without a separate pass.

**Rules, stated before any run starts (SPEC.ja.md §2's per-feature-effect
bullet, decision 96).**

- n = 3 per arm, fixed now; no replicates are added after seeing results
  (optional stopping is prohibited --- an added replicate is a new,
  separately pre-registered experiment, decision 96(f)).
- Per-run representative value = that run's best *accepted* plan's training
  ratio (the ratio the run's own acceptance rule, decision 80(a), promoted
  to best).
- Arm representative = median of its 3 per-run values, reported with the
  range (min-max) alongside it, never the median alone.
- Direction is pre-registered: **Jev >= random**. This is called an effect
  only if (i) the two arms' ranges do not overlap in that direction and
  (ii) the median difference exceeds the MDE (3%, §165/§166's floor,
  recomputed against this sweep's own A/A when taken). A range that fails
  to overlap in the *opposite* direction is recorded as "reverse
  indication," not an effect. Anything else is reported as "not resolved
  at n=3" (decision 96(b): under exchangeability, non-overlap at n=3 has a
  5% one-sided false-positive rate on its own, so a numeric miss here is
  not strong evidence of "no effect," only "not shown at this n").
- k/n mechanism checks, computed per Jev run (n=1 is enough for each,
  decision 96(c)) and then aggregated across the 3 Jev runs as k/3:
  (a) the run's final plan contains the oracle's best confirmed positive
      site, if the oracle confirms one at all --- if the oracle's §166
      sweep confirms no positive site, (a) is void and the honest
      description of a run that changes nothing is "flat; correct
      no-ops," not a failed check;
  (b) the run's final plan contains no arm the oracle confirmed harmful;
  (c) Jev's `KEEP_DEFAULT` rate at the sites the oracle measured flat
      (ratio inside the MDE band both directions).
- Jev nondeterminism (decision 94/96(e)): for every pair among the 3 Jev
  runs, round-1 requests carry empty history and should be byte-identical
  (`request_sha256`). For each byte-identical pair, record the max |delta
  P| and the number of argmax flips, per phase.
- Gateway rule as Experiment 6 (decision 92(d)/95): a run that loses more
  than 2 of its 10 main-phase requests to unrecovered 503s is invalid and
  is rerun once, suffixed `-b`; retries within a request stay at the fixed
  2 s +/-20% backoff, 200 attempts / 600 s wall budget per request
  (decision 92/95).
- Correctness gate: sha256 of all nine `.gz` outputs must match the
  baseline for every accepted arm in the plan (non-negotiable 5); a plan
  containing an output-mismatched arm is rejected regardless of speed and
  does not become the run's representative value.
- argv0 pinned to length 80 / class 96 for every label in every batch
  (decision 97); a batch recorded at another class is `measure-failed`,
  not silently accepted (decision 99 found no argv0-length effect on
  zopfli itself, but the fixed-class *procedure* stays regardless, per
  decision 99(b)).
- Holdout is measured once per run via `--measure-holdout` and reported,
  but arm selection and the representative value are both read from the
  training (search) set only --- the holdout number is transfer evidence,
  not a selection criterion.
- Caps (SPEC.ja.md §2(f)): 6 runs total; approximately 25 logical Jev
  requests per Jev run (10 main-phase-equivalent + ~6-7 exploration
  phases across 5 rounds, by Experiment 6's own measured shape, decision
  96(f)) --- so <= 75 Jev requests across the 3 Jev runs (random runs make
  no Jev requests); per-request retries capped at 200 attempts / 600 s
  wall, as above.
- Wall-clock estimate, structural (no zopfli-specific jev_search.py
  round-batch timing is sourced yet, only the oracle's fixed 3-label
  batch, §166). §166's batch unit --- 18 rounds x 3 labels (base, cand, an
  in-run aa) x 3 search-set cases, ~4.91 s/label/round summed across cases
  --- comes to ~4.4 min per batch. A jev_search.py round is one build
  (zopfli's plugin-off build was 5 s, §165; an apply-mode build was not
  separately timed for this target, so §166's hintbench analogue, ~290 s
  build-plus-two-batches per arm, is the nearest sourced figure) + one
  round batch (which, unlike the oracle's fixed 3-label batches, carries a
  label for every site with a live candidate that round, so its true cost
  is >= the ~4.4 min unit and was not separately measured) + a
  confirmation batch (decision 80(a)) only for candidates whose round
  batch already cleared the MDE. 5 rounds + one `--measure-holdout` pass
  (sized like a training batch, taken once) is therefore at least
  5 build+round-batch units + 0-5 confirmation batches + 1 holdout batch
  per run --- a floor of roughly 6-11 batch-units, i.e. on the order of
  30-50 min of timing alone per run at the ~4.4 min/unit floor, understating
  the true figure since round batches are wider than the oracle's. Six
  runs run one after another (never two timings concurrently, AGENTS.md)
  is therefore expected to take on the order of hours; no sourced number
  for this target supports a tighter bound, but it should be well under
  §166's ~10 h oracle worst case, since each jev_search.py run touches far
  fewer builds than the oracle's 68 arms.
- Order of runs: alternate jev and random --- `zopfli-jev-r0`,
  `zopfli-rand-r0`, `zopfli-jev-r1`, `zopfli-rand-r1`, `zopfli-jev-r2`,
  `zopfli-rand-r2` --- so that any time-of-day or machine-state drift
  across the session affects both arms alike rather than concentrating in
  one arm's later runs.
- Measuring agent and write-up agent are separate (HANDOFF.ja.md §5).
  Nothing in this section is edited once `zopfli-jev-r0` starts.

### 168. Oracle (zopfli): results

Written from artifacts only, by a write-up agent separate from the measuring
agent (HANDOFF.ja.md §5), while the §167 Jev/random chain runs on the same
machine; nothing below was re-measured for this section. The rules applied
are §166 "5. Rules before numbers", unchanged, in the order §166 states them.

**What was run.** Exactly §166's "4. Oracle command"
(`scripts/jev_search.py --target zopfli ... --proposer oracle --oracle-phase
all --vocab v6 -n 15 --warmup 3 --baseline-dir artifacts/zopfli-sites/baseline
--out artifacts/zopfli-search/oracle`), 68 rounds = 12 function arms + 55 loop
arms + 1 combination, as the dry run said. Provenance
(`artifacts/zopfli-search/oracle/run-manifest.json`): vocabulary
`v6-2026-09-23`, state `state-v6.0-2026-09-23`, case set `training`
(= `search-{text,binary,json}.dat`, decision 98), CPU 2, gap 0 ms, seed
20260921, baseline binary `8b0ba235...`, profdata `f066f507...`, plugin
`ca4a6625...`, marks `5bfd79ad...`, config `25274b5b...`, argv0 len 80 /
class 96. Rounds, per-arm records: `rounds.jsonl` (68 rows); human table
`summary.md`; logs `artifacts/zopfli-search/oracle-run.part1.log` (rounds
1-67) and `oracle-run.log` (part 1 + the resumed round 68). Copies in
`docs/experiments/zopfli/oracle/`; write-up `docs/experiments/zopfli/oracle.md`.

**A field-name warning, before any number.** In `rounds.jsonl` the field
`confirmed` is the **own-kernel** confirmation (`scripts/jev_search.py`
builds it from `rec["kernel"]["ci95"]`, lines 4872-4873). zopfli's
workloads are not per-site kernels (`own_workload: null` on every row;
`summary.md`'s "own kernel" column is `-` throughout), so `confirmed` is
`false` on all 68 rows, including arms that lost 8% in both batches. The
two-batch sign confirmation of decision 80 (a) --- both batches' aggregate
95% CI exclude 1 with the same sign --- is `confirmed_aggregate` /
`confirmed_aggregate_sign`. That is the field used below. The MDE gate is
not a field; it is applied here from `ratio`, `confirm.ratio` and each
batch's own `mde`.

#### 168.1 Correctness (all arms)

**68 of 68 rounds `correct: true`**: every arm's nine `.gz` sha256 lines
(three cases x train/hold/search) match
`artifacts/zopfli-sites/baseline`'s, including the combination
(`round-68/correctness.txt`, checked line by line against the baseline's nine
hashes, e.g. `search-json.dat b764ae1f...`). Every plan entry was applied
(`apply problems: none` in all 68 rows of `summary.md`). No arm is rejected
by non-negotiable 5.

#### 168.2 No-op skips: 38 of 67 one-factor arms built the baseline

Classified `identical` (normalised instructions and symbol table both match
the baseline) and therefore not timed, ratio 1.0 by construction, `ci95:
null` (decision 80 (b)):

| site | identical arms | count |
|---|---|--:|
| `lz77::find_longest_match_loop` (fn) | `inline_never` (r2) | 1 |
| `squeeze::lz77_optimal` (fn) | `inline_never` (r4) | 1 |
| `squeeze::get_best_lengths` (fn) | `inline_always` (r5) | 1 |
| `squeeze::lz77_optimal_run` (fn) | `inline_always` (r7) | 1 |
| `lz77.rs:530` (unvectorized) | `vectorize_width_{2,4,8,16}`, `interleave_count_{1,2,4}`, `unroll_disable` (r16-23) | 8 |
| `squeeze.rs:275` (unvectorized) | same eight (r27-34) | 8 |
| `squeeze.rs:325` (unvectorized) | same eight (r38-45) | 8 |
| `index.rs:184` (unvectorized) | same eight (r60-67) | 8 |
| `lz77.rs:563` (vectorized, VF 16 / IC 4 at baseline) | `vectorize_width_16` (r52), `interleave_count_4` (r55) | 2 |
| **total** | | **38** |

What this says about the baseline, read off the compiler and not guessed:

* The four function no-ops are the attribute the baseline already has in
  effect. `find_longest_match_loop` and `lz77_optimal` keep their own
  post-LTO symbols (they are not inlined, so `inline(never)` changes
  nothing); `get_best_lengths` and `lz77_optimal_run` have no symbol of their
  own at all (§166 table rows 3-4, self 0.00: already fully inlined, so
  `inline(always)` changes nothing).
* On the four unvectorized loops, **no width, no interleave count and not
  `unroll.disable` changes a single instruction.** The vectorizer does not
  take these loops at any forced width (§166's `vectorized: -`), and
  `unroll.disable` is a no-op because LLVM is not unrolling them in the
  first place. The only loop candidates that reach code there are
  `unroll.count=2/4/8` --- i.e. *more* unrolling.
* On `lz77.rs:563`, the one vectorized loop, the two no-ops are exactly the
  baseline's own choice (`post_vectorize`: VF 16, IC 4, `sites.json`).

Cost: a skipped arm took 29.4 s on average (two builds, correctness, code
comparison; 38 arms, 1117 s in total) against 562 s for a measured arm with a
confirmation batch and 295 s without one.

#### 168.3 The 29 measured one-factor arms

`two-batch sign` = `confirmed_aggregate_sign` (decision 80 (a)); `n/a` = the
first batch's CI included 1, so no confirmation batch was triggered. Verdict
per §166: **good** = sign-confirmed positive and the gain exceeds the batch's
MDE in both batches; **harmful** = the symmetric rule on the loss side;
everything else is **flat** (inside the MDE band), with sign-confirmed
sub-MDE effects labelled as such rather than lumped with the null arms. Per
case = the round batch's text/binary/json ratios. Changed syms = the number
of symbols whose normalised instructions differ from the baseline.

| round | site | candidate | changed syms | ratio | 95% CI | confirm ratio | confirm 95% CI | text | binary | json | two-batch sign | verdict (§166) |
|--:|---|---|--:|--:|---|--:|---|--:|--:|--:|---|---|
| 1 | `lz77::find_longest_match_loop` | `inline_always` | 5 | 0.9932 | [0.9901, 0.9963] | 0.9909 | [0.9878, 0.9939] | 0.9896 | 0.9986 | 0.9915 | **-** | flat (confirmed -, below MDE) |
| 3 | `squeeze::lz77_optimal` | `inline_always` | 6 | 0.9874 | [0.9846, 0.9902] | 0.9876 | [0.9851, 0.9902] | 0.9828 | 0.9867 | 0.9927 | **-** | flat (confirmed -, below MDE) |
| 6 | `squeeze::get_best_lengths` | `inline_never` | 9 | 0.9799 | [0.9764, 0.9832] | 0.9783 | [0.9755, 0.9812] | 0.9866 | 0.9681 | 0.9851 | **-** | flat (confirmed -, below MDE) |
| 8 | `squeeze::lz77_optimal_run` | `inline_never` | 8 | 0.9779 | [0.9718, 0.9842] | 0.9817 | [0.9773, 0.9863] | 0.9801 | 0.9824 | 0.9711 | **-** | flat (confirmed -, below MDE) |
| 9 | `<hash::ZopfliHash>::update` | `inline_always` | 4 | 0.9999 | [0.9958, 1.0041] | not triggered | - | 1.0012 | 0.9996 | 0.9987 | n/a | flat |
| 10 | `<hash::ZopfliHash>::update` | `inline_never` | 3 | 0.9914 | [0.9894, 0.9936] | 0.9967 | [0.9944, 0.9992] | 0.9980 | 0.9840 | 0.9923 | **-** | flat (confirmed -, below MDE) |
| 11 | `lz77::find_longest_match` | `inline_always` | 8 | 0.9799 | [0.9754, 0.9851] | 0.9796 | [0.9770, 0.9822] | 0.9862 | 0.9680 | 0.9855 | **-** | flat (confirmed -, below MDE) |
| 12 | `lz77::find_longest_match` | `inline_never` | 9 | 0.9777 | [0.9753, 0.9803] | 0.9732 | [0.9706, 0.9760] | 0.9842 | 0.9674 | 0.9816 | **-** | flat (confirmed -, below MDE) |
| 13 | `lz77.rs:530` | `unroll_count_2` | 1 | 0.9856 | [0.9836, 0.9876] | 0.9879 | [0.9854, 0.9904] | 0.9821 | 0.9932 | 0.9816 | **-** | flat (confirmed -, below MDE) |
| 14 | `lz77.rs:530` | `unroll_count_4` | 1 | 0.9943 | [0.9886, 0.9998] | 0.9914 | [0.9881, 0.9946] | 0.9908 | 0.9990 | 0.9930 | **-** | flat (confirmed -, below MDE) |
| 15 | `lz77.rs:530` | `unroll_count_8` | 1 | 0.9906 | [0.9865, 0.9942] | 0.9939 | [0.9902, 0.9981] | 0.9913 | 0.9899 | 0.9906 | **-** | flat (confirmed -, below MDE) |
| 24 | `squeeze.rs:275` | `unroll_count_2` | 1 | 0.9843 | [0.9827, 0.9860] | 0.9868 | [0.9842, 0.9896] | 0.9811 | 0.9878 | 0.9839 | **-** | flat (confirmed -, below MDE) |
| 25 | `squeeze.rs:275` | `unroll_count_4` | 1 | 0.9639 | [0.9595, 0.9677] | 0.9668 | [0.9647, 0.9689] | 0.9550 | 0.9776 | 0.9591 | **-** | **harmful** |
| 26 | `squeeze.rs:275` | `unroll_count_8` | 1 | 0.9169 | [0.9149, 0.9189] | 0.9156 | [0.9127, 0.9185] | 0.9000 | 0.9592 | 0.8931 | **-** | **harmful** |
| 35 | `squeeze.rs:325` | `unroll_count_2` | 1 | 1.0095 | [1.0056, 1.0133] | 1.0100 | [1.0048, 1.0148] | 1.0123 | 1.0056 | 1.0107 | **+** | flat (confirmed +, below MDE) |
| 36 | `squeeze.rs:325` | `unroll_count_4` | 1 | 1.0072 | [1.0034, 1.0110] | 1.0049 | [1.0013, 1.0086] | 1.0133 | 0.9962 | 1.0121 | **+** | flat (confirmed +, below MDE) |
| 37 | `squeeze.rs:325` | `unroll_count_8` | 1 | 1.0126 | [1.0096, 1.0154] | 1.0129 | [1.0099, 1.0158] | 1.0176 | 1.0034 | 1.0168 | **+** | flat (confirmed +, below MDE) |
| 46 | `lz77.rs:563` | `unroll_count_2` | 1 | 1.0041 | [1.0016, 1.0068] | 1.0023 | [0.9991, 1.0052] | 1.0071 | 1.0023 | 1.0029 | no | flat |
| 47 | `lz77.rs:563` | `unroll_count_4` | 1 | 1.0044 | [1.0020, 1.0068] | 1.0020 | [0.9992, 1.0050] | 1.0039 | 0.9997 | 1.0096 | no | flat |
| 48 | `lz77.rs:563` | `unroll_count_8` | 1 | 1.0050 | [1.0011, 1.0089] | 1.0040 | [1.0005, 1.0082] | 1.0068 | 0.9983 | 1.0098 | **+** | flat (confirmed +, below MDE) |
| 49 | `lz77.rs:563` | `vectorize_width_2` | 1 | 0.9997 | [0.9968, 1.0025] | not triggered | - | 0.9987 | 0.9993 | 1.0013 | n/a | flat |
| 50 | `lz77.rs:563` | `vectorize_width_4` | 1 | 0.9935 | [0.9850, 1.0000] | 1.0013 | [0.9969, 1.0059] | 1.0011 | 0.9942 | 0.9855 | no | flat |
| 51 | `lz77.rs:563` | `vectorize_width_8` | 1 | 0.9981 | [0.9947, 1.0014] | not triggered | - | 0.9975 | 0.9950 | 1.0018 | n/a | flat |
| 53 | `lz77.rs:563` | `interleave_count_1` | 1 | 1.0010 | [0.9963, 1.0059] | not triggered | - | 1.0020 | 1.0016 | 0.9995 | n/a | flat |
| 54 | `lz77.rs:563` | `interleave_count_2` | 1 | 0.9997 | [0.9946, 1.0045] | not triggered | - | 1.0066 | 0.9952 | 0.9973 | n/a | flat |
| 56 | `lz77.rs:563` | `unroll_disable` | 1 | 0.9980 | [0.9933, 1.0029] | not triggered | - | 0.9969 | 0.9984 | 0.9986 | n/a | flat |
| 57 | `index.rs:184` | `unroll_count_2` | 1 | 0.9978 | [0.9926, 1.0031] | not triggered | - | 1.0005 | 0.9954 | 0.9976 | n/a | flat |
| 58 | `index.rs:184` | `unroll_count_4` | 1 | 0.9948 | [0.9898, 0.9997] | 0.9966 | [0.9916, 1.0013] | 0.9997 | 0.9948 | 0.9898 | no | flat |
| 59 | `index.rs:184` | `unroll_count_8` | 1 | 0.9977 | [0.9939, 1.0014] | not triggered | - | 0.9977 | 0.9982 | 0.9973 | n/a | flat |

Batch MDEs (`max(2 x worst per-workload half-width, 3%)`, recomputed per
batch by the driver as §166 requires): **3% for every batch except two** ---
round 50's first batch (`lz77.rs:563 vectorize_width_4`, json half-width
2.20% -> MDE 4.41%; its confirmation, 1.0013, did not agree in sign, so it is
flat either way) and round 68's confirmation batch (json half-width 1.86% ->
MDE 3.73%, see 168.4). No verdict depends on which of the two MDE values is
used.

In-run A/A (a second stripped copy of the baseline inside every timed batch):
**0 of 30** round batches and **1 of 22** confirmation batches had an
aggregate interval excluding 1 (round 15's confirmation, 1.0037 [1.0006,
1.0066]); worst round-batch A/A half-width 0.83% (round 50, the
same batch whose json half-width lifted its MDE to 4.41%). On this target
the within-batch interval is honest at the aggregate, as §165's A/A said it
would be --- the hintbench shape (§120: 5 of 45), not the jaq shape (§113: 41
of 90).

**Counts.**

| verdict | arms |
|---|--:|
| **good** | **0** |
| **harmful** (both batches beyond -3%) | **2**: `squeeze.rs:275 unroll_count_8` 0.9169 / 0.9156, `squeeze.rs:275 unroll_count_4` 0.9639 / 0.9668 |
| flat, sign-confirmed negative below MDE | 11 (7 function arms, 4 loop arms) |
| flat, sign-confirmed positive below MDE | 4 (`squeeze.rs:325 unroll_count_{2,4,8}`, `lz77.rs:563 unroll_count_8`) |
| flat, not sign-confirmed | 12 |
| identical to the baseline (168.2) | 38 |
| **one-factor total** | **67** |

17 arms were sign-confirmed in two batches (11 - , 4 + , 2 harmful); 21 of the
29 triggered a confirmation batch.

Where the losses are. The worst arm of the sweep is
`squeeze.rs:275 unroll_count_8`, **-8.3% / -8.4%**, json 0.8931 and text
0.9000 in the round batch: `squeeze.rs:275` is `get_best_lengths`' outer
`while i < inend` loop (inlined into `lz77_optimal`, trip 272644, 680-1092
body instructions, contains calls, `sites.json`), and forcing an 8x (4x)
unroll on it is the one thing in the vocabulary that clears the MDE ---
downwards. `unroll_count_2` at the same loop is -1.6% / -1.3%, so the curve
is monotone in the count.

The function attributes, all 12 of them: **4 identical, 8 changed code, 7 of
the 8 sign-confirmed negative, none beyond the MDE, none positive.**
`inline(always)` costs -0.7% (`find_longest_match_loop`, r1: 0.9932 / 0.9909)
to -2.0% (`find_longest_match`, r11: 0.9799 / 0.9796); `inline(never)` costs
-0.9% / -0.3% (`ZopfliHash::update`, r10: 0.9914 / 0.9967) to -2.7%
(`find_longest_match`, r12: 0.9777 / 0.9732, binary 0.9674). The eighth
code-changing arm, `ZopfliHash::update inline_always`, is 0.9999 [0.9958,
1.0041]. The binary case carries the biggest per-case losses (0.9674-0.9681
on the three -2% arms).

Where the gains are. **Only unrolling the `squeeze.rs:325` loop** --- the
"Lengths" loop over `sublen` inside `get_best_lengths` (inlined into
`lz77_optimal`; trip 9.2, 76 body instructions, no calls, FP reduction,
unvectorized) --- **is positive and sign-confirmed at every count**: 2x
+0.95% / +1.00%, 4x +0.72% / +0.49%, **8x +1.26% / +1.29%** (text +1.76%,
json +1.68%, binary +0.34%). Best per site among the sign-confirmed positive
arms: `squeeze.rs:325` -> `unroll_count_8`; `lz77.rs:563` -> `unroll_count_8`
(+0.50% / +0.40%; its confirmation CI [1.0005, 1.0082] only just excludes 1,
and `unroll_count_2/4` at the same loop did not confirm). No other site has a
sign-confirmed positive arm.

#### 168.4 The combination (round 68)

§166's combination rule is "every site whose best candidate was confirmed with
a ratio > 1, one candidate per site", where *confirmed* is decision 80 (a)'s
two-batch sign rule, not the MDE-gated "good". Applied as written, it
selects two sites, both sub-MDE (`round-68/plan-b.json`,
`arm.selected_by: "confirmed in two batches, ratio > 1"`):

* `squeeze.rs:325` `unroll_count_8` (r37, +1.26% / +1.29%)
* `lz77.rs:563` `unroll_count_8` (r48, +0.50% / +0.40%)

The one-batch rule and the point-estimate rule (both recorded beside it in
the round) would have picked the same two. Build: 2 loop entries applied,
`code`, 2 symbols changed (`find_longest_match_loop`, `lz77_optimal`),
output identical, bin sha256 `10023110...`.

| batch | aggregate | 95% CI | text | binary | json | A/A | MDE |
|---|--:|---|--:|--:|--:|---|--:|
| round | **1.0181** | [1.0159, 1.0203] | 1.0193 | 1.0094 | 1.0257 | 1.0011 +-0.0019 | 3% |
| confirmation (seed 20360989) | **1.0206** | [1.0155, 1.0287] | 1.0199 | 1.0068 | 1.0354 | 1.0003 +-0.0033 | 3.73% |

Both batches are sign-confirmed positive and **both are below the MDE**:
+1.81% and +2.06% against 3% and 3.73%. **The combination is not "good".**
The two parts multiply to 1.0126 x 1.0050 = +1.77%; the combination measured
+1.81% / +2.06%, so here, unlike jaq (§140: +6.96% independent, +0.17%
measured), the parts add up --- they are two different loops in two
different functions. The driver's acceptance rule promoted round 68 to
`best` (its CI lower bound 1.0159 beats round 37's 1.0126); acceptance is
not the §166 verdict and is reported only for completeness.

#### 168.5 The holdout panel

§166: "holdout measured once at the end with `bench_panel.sh`, four labels
(base, combination, best single function arm, best single loop arm) plus
`aa`". Run by the measuring agent, 06:28:50-06:37:08 JST 2026-09-24
(`artifacts/zopfli-search/oracle-holdout-panel.log`, file mtimes):

```
$ TARGET=zopfli BENCH_SET=holdout scripts/bench_panel.sh \
    artifacts/zopfli-search/oracle/holdout-panel 15 3 20260924 \
    base=artifacts/zopfli-sites/baseline/bin aa=artifacts/zopfli-sites/baseline/bin \
    comb=artifacts/zopfli-search/oracle/round-68/bin \
    bestloop=artifacts/zopfli-search/oracle/round-37/bin
```

(argument list from the running process table; `BENCH_SET=holdout` inferred
from the log header "case set holdout", which is also `bench_panel.sh`'s
default.) CPU 2, gap 0, warmup 3, 15 rounds, bootstrap 10000 resamples seed
20260924, argv0 pinned, all four labels len 80 / **class 96**
(`stats.json` `argv0_class: 96`). Stripped shas: base = aa =
`79c33226...` (the same stripped baseline hash as §164/§165 and as every
round's `timing/base`), comb `e67837b3...`, bestloop `636cb74a...`.

**Deviation from §166, with its reason:** there is **no "best single function
arm" label**. `holdout-picks.json` records `"fn": null` --- no function arm
was sign-confirmed positive (168.3), so there was nothing to pick --- and
`"loop": [37, 1.0126], "loop_tier": "positive_below_mde"`, i.e. the loop
pick is round 37 and the picker itself labels it sub-MDE. Also: the panel
used 15 timed rounds (the oracle's `-n 15`), not §165's A/A panels' 18.

| label | aggregate (geomean) | 95% CI | half-width | text | binary | json |
|---|--:|---|--:|--:|--:|--:|
| base | 1.0000 | --- | --- | 2660.4 ms | 1621.9 ms | 2660.0 ms |
| aa | 0.9998 | [0.9979, 1.0018] | 0.20% | 0.9993 [0.9963, 1.0022] | 1.0011 [0.9982, 1.0040] | 0.9989 [0.9957, 1.0019] |
| **comb** (r68) | **1.0177** | [1.0163, 1.0193] | 0.15% | **1.0224** [1.0201, 1.0247] | 1.0033 [1.0003, 1.0065] | **1.0276** [1.0255, 1.0301] |
| **bestloop** (r37, `squeeze.rs:325 unroll_count_8`) | **1.0133** | [1.0116, 1.0151] | 0.17% | **1.0184** [1.0163, 1.0205] | 1.0025 [0.9997, 1.0055] | **1.0191** [1.0150, 1.0229] |

(base row: median ms.) MDE by §166's rule on this batch: worst per-workload
half-width 0.40% (bestloop/json) -> `max(0.80%, 3%)` = **3%**. The A/A leg
is inside +-0.2% everywhere, no interval excluding 1.

**The holdout reproduces the training numbers almost exactly and stays
under the MDE**: comb +1.77% (training +1.81% / +2.06%), bestloop +1.33%
(training +1.26% / +1.29%). Per case the effect is text and json (+1.8 to
+2.8%), with binary at +0.3% --- the same shape as training. These are
real, reproducible, transferring effects of ~1.3-1.8%, and by the
pre-registered rule they are below what this protocol calls detectable, so
**neither is "good"**. No per-case holdout ratio reaches 3% either (the
largest is comb/json, +2.76%).

#### 168.6 Wall clock, and the interruption

Round `ts` 2026-09-23 22:21:48 (round 1) to 02:35:44 (round 67); the part-1
log ends at 02:36 with round 68 built, correctness OK and "code vs baseline:
code (2 symbols changed, symbol table moved)", i.e. during round 68's first
timing batch. **Windows/WSL rebooted at 05:53 JST** (reported by the
measuring agent; the log simply stops). A stale
`artifacts/timing-run/8954fa25` argv0-alias directory left by the killed
batch was removed, and at 05:57 the same command was re-run with
`--resume`: `[resume] 67 rounds already recorded (0 of them lost), best =
round-37 (1.0126)`. **Only round 68 was re-run**; rounds 1-67 were neither
rebuilt nor re-timed. Round 68 rebuilt (05:57:20-05:57:31), passed
correctness again, and its round batch and confirmation were taken
05:57:51-06:06:54.

Is the resumed round-68 timing comparable? What can be checked: the plan is
the same (`plan_sig c905f2b9...`, chosen by the same rule from the same 67
records), the rebuild reports the same code class and the same symbol
change as the part-1 log's last line (`code`, 2 symbols), the in-batch
`timing/base` copy hashes to `79c33226...` like all 52 base copies of the
run (30 round batches + 22 confirmation batches),
argv0 is class 96, and the in-run A/A is quiet (1.0011 +-0.0019 round,
1.0003 +-0.0033 confirmation). What cannot be checked: the pre-reboot
round-68 binary's sha256 was never logged and its directory was overwritten
by the resume, so "the same binary" rests on the build being deterministic
(the §165 identities --- three independent builds of the baseline collapsing
to one hash --- are the evidence for that, not a direct comparison). No
pre-reboot round-68 timing exists to compare against: the batch it was in
never completed. The ratio is within-batch (base, cand and aa timed
together after the reboot), so a machine-state change across the reboot
affects all three labels alike.

Timing: sum of `wall_s` over the 68 rounds **15838 s = 4.40 h** (38 skips
1117 s; 22 measured arms with a confirmation, mean 562 s; 8 without, mean
295 s). Elapsed: 22:21:48-02:36 plus 05:57-06:07, about 4.4 h of work in
8.4 h of calendar time. §166's worst case was "order 10 h", its expected
"well under that".

#### 168.7 Verdict, per the pre-registered rules

* **Good: 0 of 67.** Harmful: **2** (both `squeeze.rs:275`, `unroll_count_4`
  and `unroll_count_8`). Flat: 27 measured (15 of them sign-confirmed, all
  below the MDE). Identical: 38.
* **The combination (+1.81% / +2.06% training, +1.77% holdout) and the best
  single arm (`squeeze.rs:325 unroll_count_8`, +1.26% / +1.29% training,
  +1.33% holdout) are below the 3% MDE in every batch.** On zopfli, under
  `-Copt-level=3 -Ctarget-cpu=native -Clto=fat -Ccodegen-units=1` + PGO,
  the ceiling of vocabulary v6 on the 6 marks / 5 sites of §166 is under
  what this protocol can call an effect --- about +1.8%, measured, and it
  transfers.
* **The pre-registered prediction did not hold.** The loop dimension,
  predicted flat, holds every arm that cleared the MDE (both harmful) and
  every sign-confirmed gain; the inline dimension, predicted as the likely
  source of a result, produced none. The part that did hold: width,
  interleave and `unroll.disable` were no-ops on all four unvectorized
  loops (32 of 32 identical). In detail, §166 predicted "the four unvectorized candidate sites are likely flat
  under loop-metadata hints" and "`inline(always)`/`inline(never)` ... is
  where a result, if any, is more likely to appear". Loops: width,
  interleave and `unroll.disable` were no-ops on all four (32 of 32
  identical), but `unroll.count` was *not* flat everywhere --- it produced
  the sweep's only gains (`squeeze.rs:325`, sub-MDE) and its only harmful
  arms (`squeeze.rs:275`, -3.6% and -8.3%). Inlining: 8 of 12 arms moved
  code and **none helped** --- 7 are sign-confirmed losses of 0.3-2.7%,
  both directions of forcing. The dimension the prediction pointed at is
  the one that is uniformly (mildly) negative; the analogy with jaq's
  `Val::hash inline(always)` (§138) and hintbench's `k2_mix inline(always)`
  (§123) did not carry over. The baseline's own inlining decisions on these
  six functions are, as far as this vocabulary can tell, already the best
  available.
* **Stage 0 correspondence.** Stage 0's only global win,
  `-unroll-max-count=1` (+1.59% [+1.30%, +1.82%], §31.3), worked by
  *reducing* the baseline's x8 runtime unroll of `cache.rs:108` (615 -> 50
  instructions). **No v6 arm in this sweep corresponds to it.** The v6
  candidate added for exactly that case, `unroll_disable` (decision 98), was
  `identical` at all four unvectorized sites (`lz77.rs:530`,
  `squeeze.rs:275`, `squeeze.rs:325`, `index.rs:184`; r23/34/45/67) and
  flat at the vectorized `lz77.rs:563` (r56, 0.9980 [0.9933, 1.0029], not
  triggered): these loops are not being unrolled, so there is nothing to
  disable --- consistent with §31.4, where `-unroll-max-count=1` left
  `find_longest_match_loop` and `ZopfliHash::update` byte-identical. Round
  37, the best single arm, is `unroll_count_8` at `squeeze.rs:325`: the
  **opposite** direction (more unrolling, at a different loop).
  `cache.rs:108`, the one loop where `unroll_disable` would have acted, is
  outside `oracle.selected_keys_top6` by the cap rule (§166 §3), so decision
  98's motivation for v6 remains **untested**, not refuted. That the two
  numbers are about the same size (+1.6% global flag, +1.3% one site / +1.8%
  combination) is a coincidence of magnitude, not the same effect.

#### 168.8 What this means for §167's k/n checks

Following §167's wording, with the §166 verdicts above:

* **(a) "the run's final plan contains the oracle's best confirmed positive
  site, if the oracle confirms one at all --- if the oracle's §166 sweep
  confirms no positive site, (a) is void".** Read strictly against §166's
  verdict (a confirmed positive = "good"), the sweep has **no** good site,
  so **(a) is void**, and a Jev run that changes nothing is described as
  "flat; correct no-ops", not as a failed check. There is an ambiguity in
  the wording that must be stated rather than resolved after the fact:
  `squeeze.rs:325 unroll_count_8` *is* sign-confirmed positive in two
  batches (decision 80 (a)'s sense of "confirmed"), only not above the MDE.
  The strict reading is the one applied. As a **descriptive line, not a
  pre-registered check**, the write-up of §167 may additionally report
  whether each final plan contains `squeeze.rs:325 unroll_count_8` (and
  `lz77.rs:563 unroll_count_8`); it carries no pass/fail.
* **(b) "the run's final plan contains no arm the oracle confirmed
  harmful"**: the harmful set is exactly **`squeeze.rs:275 unroll_count_4`
  and `squeeze.rs:275 unroll_count_8`** (both batches beyond -3%). The 11
  sign-confirmed sub-MDE losses are not "harmful" under §166 and are not in
  the set; they can be reported descriptively (e.g. a final plan carrying
  `find_longest_match inline_never`, -2.2% / -2.7%).
* **(c) "Jev's `KEEP_DEFAULT` rate at the sites the oracle measured flat
  (ratio inside the MDE band both directions)"**: every site except
  `squeeze.rs:275` has all of its measured arms inside the band --- the six
  function marks, `lz77.rs:530`, `squeeze.rs:325`, `lz77.rs:563`,
  `index.rs:184`. `squeeze.rs:275` is flat for its other nine candidates
  but has two harmful ones, so it is not a "flat site" for (c).
* The prediction §167's own shape implies: with a ceiling of ~+1.8% and an
  MDE of 3%, §167's effect rule (ranges non-overlapping **and** median
  difference > MDE) cannot be met by any Jev-vs-random difference that this
  oracle could produce, unless random draws a harmful arm that the speed
  gate fails to stop. The expected headline of §167 is therefore "not
  resolved at n=3" with (a) void; stated here before any §167 run has been
  read.

#### 168.9 Deviations, and what is not established

* Holdout panel: no best-function label (none qualified); 15 rounds, not 18
  (168.5).
* Round 68 was interrupted by a host reboot and re-run by `--resume`; the
  pre-reboot binary's sha is not recorded (168.6).
* `cache.rs:108` (Stage 0's lever) and `try_get` (rank 8 by reach) are not in
  this sweep, by the frozen cap and marks rules (§166 §3). Adding them is a
  separate registration by the owner.
* The sub-MDE effects at `squeeze.rs:325` are reproducible (four batches, two
  input sets, the same size) and very likely real; this protocol still does
  not call them effects, and nothing here relabels them after the fact.
* The per-case readout is the three input cases, not per-site kernels: a
  site's own contribution is not separated from layout effects elsewhere in
  the binary (the function arms change 3-9 symbols each).

### 169. Jev vs random on zopfli: results (n=3 each)

This section was written from artifacts only, by a write-up agent separate from the
measuring agent (HANDOFF.ja.md §5). Nothing was re-measured for it. The rules
are §167's, unchanged, read with §168.8's statement of what (a), (b) and (c)
mean against the oracle's verdicts. All six runs sit under
`artifacts/zopfli-search/zopfli-{jev,rand}-r{0,1,2}/`, with the per-round
records in `rounds.jsonl`, the provenance and totals in `run-manifest.json`
and a human table in `summary.md`. Jev requests are in
`jev-log/<run>.jsonl` and `.log`. Run logs are `artifacts/zopfli-search/<run>-run.log`.
Copies are in `docs/experiments/zopfli/jev-vs-random/`, and the write-up is
`docs/experiments/zopfli/jev-vs-random.md`.

**Command.** `run-manifest.json` has no argv field. The command comes from
the chain script that launched the runs, which was checked against the live
process table for `zopfli-rand-r2`. It is §167's template word for word,
with `<proposer>`/`<seed-offset>`/`<run id>` filled in from §167's table:

```
export TARGET=zopfli
python3 -u scripts/jev_search.py --target zopfli \
    --marks targets/zopfli/jev-marks.txt --sites targets/zopfli/sites.json \
    --site-set oracle.selected_keys_top6 \
    --proposer <jev|random> --seed-offset <0|1000|2000> \
    --rounds 5 --vocab v6 --readout forced_top1 \
    --source-comments strip --explore 2 --explore-revisit 0 --pv-untried off \
    -n 15 --warmup 3 \
    --baseline-dir artifacts/zopfli-sites/baseline \
    --measure-holdout --out artifacts/zopfli-search/<run id> \
    > artifacts/zopfli-search/<run id>-run.log 2>&1
```

Each manifest confirms its own parameters: `proposer`, `seed_offset`
0/1000/2000, and `seed` 20260921 / 20261921 / 20262921 (= 20260921 +
offset). The following are identical in all six runs:
`exploration {k: 2, revisit: 0, max_visits: 2, pv_untried: off}`,
`readout forced_top1`, `source_comments strip`, vocabulary `v6-2026-09-23`,
state `state-v6.0-2026-09-23`, `repetitions 15`, `warmup 3`,
`taskset_cpu 2`, `case_set training`, and `argv0 {len: 80, class: 96}`.
The provenance hashes also match §168's oracle in all six: config
`25274b5b…`, marks `5bfd79ad…`, plugin `ca4a6625…`, profdata `f066f507…`,
baseline binary `8b0ba235…`. Runs were started one after another in §167's
alternating order and never overlapped (chain log, times JST 2026-09-24):

| run | start | exit | `wall_s` |
|---|---|---|--:|
| `zopfli-jev-r0` | 06:37:08 | 07:34:42 (rc 0) | 3453.1 s (57.6 min) |
| `zopfli-rand-r0` | 07:34:42 | 08:22:58 (rc 0) | 2896.1 s (48.3 min) |
| `zopfli-jev-r1` | 08:22:58 | 09:14:37 (rc 0) | 3098.7 s (51.6 min) |
| `zopfli-rand-r1` | 09:14:37 | 10:06:26 (rc 0) | 3108.6 s (51.8 min) |
| `zopfli-jev-r2` | 10:06:26 | 11:01:46 (rc 0) | 3319.3 s (55.3 min) |
| `zopfli-rand-r2` | 11:01:46 | 11:53:56 (rc 0) | 3130.0 s (52.2 min) |

#### 169.1 Per-run rounds

How to read the columns. **Phase A / phase B picks** are the proposer's
non-`KEEP_DEFAULT` answers that went into the plan. For Jev these are the
argmax, and `(forced)` marks the one hint `forced_top1` adds when a whole
phase answered `KEEP_DEFAULT`. **explored** lists the driver's `--explore 2`
picks: a site nothing has been tried at yet is asked again with `KEEP` not on
offer, and Jev's top-ranked candidate is built. The random proposer answers
every question at random and makes no exploration picks. `always` / `never`
= `inline_always` / `inline_never`. Loop sites are named by source line; the
driver's key also carries the inlining context (`#dN`). **ratio / 95% CI** are
the round batch's aggregate (geomean over text, binary and json) against the
in-batch baseline. The MDE is 3% except where the table notes otherwise.
**confirm** is decision 80(a)'s confirmation batch, and `sign -` means
`confirmed_aggregate_sign = -1` (both batches' CIs exclude 1 on the loss
side). **A/A** is the in-batch second copy of the baseline. **accepted** is
the run's acceptance rule, decision 80(a)/89(a).

`zopfli-jev-r0` (`artifacts/zopfli-search/zopfli-jev-r0/rounds.jsonl`):

| round | phase A picks | phase B picks | explored | ratio | 95% CI | confirm | A/A | accepted |
|--:|---|---|---|--:|---|---|---|---|
| 1 | `lz77::find_longest_match_loop` always, `ZopfliHash::update` always, `lz77::find_longest_match` always | `index.rs:184` unroll_count_4 (forced) | `squeeze::lz77_optimal` always, `squeeze::get_best_lengths` always | 0.9826 | [0.9803, 0.9851] | 0.9806 [0.9783, 0.9825] (sign -) | 1.0009 ±0.0024 | no |
| 2 | `lz77::find_longest_match` always | `lz77.rs:563` unroll_count_2 (forced) | `squeeze::lz77_optimal_run` always, `lz77.rs:530` unroll_count_4, `squeeze.rs:275` unroll_disable | 0.9656 | [0.9624, 0.9683] | 0.9664 [0.9647, 0.9680] (sign -) | 1.0002 ±0.0016 | no |
| 3 | `ZopfliHash::update` always, `lz77::find_longest_match` always | `lz77.rs:530` unroll_count_4 (forced) | `squeeze.rs:325` unroll_disable | 0.9681 | [0.9662, 0.9698] | 0.9685 [0.9666, 0.9705] (sign -) | 0.9979 ±0.0020 | no |
| 4 | `lz77::find_longest_match` always | `lz77.rs:530` unroll_count_4, `lz77.rs:563` unroll_count_2, `squeeze.rs:275` unroll_disable | none | 0.9684 | [0.9671, 0.9697] | 0.9662 [0.9651, 0.9673] (sign -) | 0.9996 ±0.0017 | no |
| 5 | `squeeze::lz77_optimal_run` always | `lz77.rs:530` unroll_count_4, `squeeze.rs:275` unroll_disable, `lz77.rs:563` unroll_count_2, `index.rs:184` unroll_count_4 | none | 0.9861 | [0.9842, 0.9880] | 0.9872 [0.9853, 0.9890] (sign -) | 1.0001 ±0.0018 | no |

`zopfli-jev-r1` (`artifacts/zopfli-search/zopfli-jev-r1/rounds.jsonl`):

| round | phase A picks | phase B picks | explored | ratio | 95% CI | confirm | A/A | accepted |
|--:|---|---|---|--:|---|---|---|---|
| 1 | `lz77::find_longest_match_loop` always, `ZopfliHash::update` always, `lz77::find_longest_match` always | `index.rs:184` unroll_count_2 (forced) | `squeeze::lz77_optimal` always, `squeeze::get_best_lengths` always | 0.9832 | [0.9813, 0.9853] | 0.9824 [0.9807, 0.9839] (sign -) | 1.0005 ±0.0027 | no |
| 2 | `ZopfliHash::update` always, `lz77::find_longest_match` always | `lz77.rs:530` unroll_count_2 (forced) | `squeeze::lz77_optimal_run` always, `lz77.rs:563` unroll_count_2, `squeeze.rs:275` unroll_disable | 0.9669 | [0.9651, 0.9691] | 0.9647 [0.9613, 0.9669] (sign -) | 0.9995 ±0.0025 | no |
| 3 | `ZopfliHash::update` always, `lz77::find_longest_match` always | `lz77.rs:530` unroll_count_2 (forced) | `squeeze.rs:325` unroll_disable | 0.9657 | [0.9644, 0.9671] | 0.9640 [0.9627, 0.9653] (sign -) | 1.0019 ±0.0016 | no |
| 4 | `lz77::find_longest_match_loop` always | `index.rs:184` unroll_count_2 (forced) | none | 0.9967 | [0.9882, 1.0115] (MDE 6.58%) | not triggered | 1.0076 ±0.0104 | no |
| 5 | `lz77::find_longest_match_loop` always | `index.rs:184` unroll_count_2 | none | 0.9895 | [0.9853, 0.9925] | 0.9907 [0.9896, 0.9919] (sign -) | 1.0002 ±0.0016 | no |

`zopfli-jev-r2` (`artifacts/zopfli-search/zopfli-jev-r2/rounds.jsonl`):

| round | phase A picks | phase B picks | explored | ratio | 95% CI | confirm | A/A | accepted |
|--:|---|---|---|--:|---|---|---|---|
| 1 | `lz77::find_longest_match_loop` always, `ZopfliHash::update` always, `lz77::find_longest_match` always | `index.rs:184` unroll_count_4 (forced) | `squeeze::lz77_optimal` always, `squeeze::get_best_lengths` always | 0.9825 | [0.9808, 0.9843] | 0.9811 [0.9799, 0.9824] (sign -) | 1.0020 ±0.0013 | no |
| 2 | `lz77::find_longest_match` always | `lz77.rs:530` unroll_count_4 (forced) | `squeeze::lz77_optimal_run` always, `lz77.rs:563` unroll_count_2, `squeeze.rs:275` unroll_disable | 0.9689 | [0.9672, 0.9707] | 0.9675 [0.9659, 0.9691] (sign -) | 1.0019 ±0.0035 | no |
| 3 | `ZopfliHash::update` always (forced) | `index.rs:184` unroll_count_4 (forced) | `squeeze.rs:325` unroll_disable | 1.0001 | [0.9988, 1.0013] | not triggered | 1.0005 ±0.0019 | no |
| 4 | `ZopfliHash::update` always (forced) | `index.rs:184` unroll_count_4 (forced) | none | 0.9974 | [0.9953, 0.9995] | 0.9965 [0.9945, 0.9984] (sign -) | 1.0010 ±0.0020 | no |
| 5 | `ZopfliHash::update` always (forced) | `index.rs:184` unroll_count_4 (forced) | none | 0.9964 | [0.9931, 0.9990] | 0.9959 [0.9930, 0.9987] (sign -) | 1.0044 ±0.0051 | no |

`zopfli-rand-r0` (`artifacts/zopfli-search/zopfli-rand-r0/rounds.jsonl`):

| round | phase A picks | phase B picks | explored | ratio | 95% CI | confirm | A/A | accepted |
|--:|---|---|---|--:|---|---|---|---|
| 1 | `lz77::find_longest_match_loop` always, `squeeze::lz77_optimal` never, `squeeze::lz77_optimal_run` always, `lz77::find_longest_match` never | `squeeze.rs:325` interleave_count_4, `squeeze.rs:275` unroll_count_8, `index.rs:184` unroll_count_2 | none | 0.9429 | [0.9410, 0.9453] | 0.9427 [0.9412, 0.9440] (sign -) | 1.0000 ±0.0020 | no |
| 2 | `lz77::find_longest_match_loop` never, `squeeze::lz77_optimal` always, `squeeze::get_best_lengths` always, `squeeze::lz77_optimal_run` always, `ZopfliHash::update` never | `lz77.rs:530` vectorize_width_16, `lz77.rs:563` unroll_count_2 | none | 0.9908 | [0.9893, 0.9924] | 0.9899 [0.9884, 0.9917] (sign -) | 1.0002 ±0.0021 | no |
| 3 | `lz77::find_longest_match_loop` always, `squeeze::lz77_optimal` never, `squeeze::get_best_lengths` never, `ZopfliHash::update` never | none | none | 0.9727 | [0.9698, 0.9754] | 0.9746 [0.9726, 0.9764] (sign -) | 0.9996 ±0.0019 | no |
| 4 | `squeeze::lz77_optimal` always, `squeeze::get_best_lengths` never, `squeeze::lz77_optimal_run` never, `ZopfliHash::update` never, `lz77::find_longest_match` never | `lz77.rs:530` vectorize_width_2, `lz77.rs:563` vectorize_width_4 | none | 0.9702 | [0.9684, 0.9720] | 0.9673 [0.9655, 0.9688] (sign -) | 1.0004 ±0.0022 | no |
| 5 | `squeeze::lz77_optimal` always, `squeeze::get_best_lengths` never, `squeeze::lz77_optimal_run` always, `lz77::find_longest_match` always | `lz77.rs:530` unroll_disable, `lz77.rs:563` unroll_count_4 | none | 0.9882 | [0.9786, 1.0027] (MDE 6.67%) | not triggered | 0.9879 ±0.0162 | no |

`zopfli-rand-r1` (`artifacts/zopfli-search/zopfli-rand-r1/rounds.jsonl`):

| round | phase A picks | phase B picks | explored | ratio | 95% CI | confirm | A/A | accepted |
|--:|---|---|---|--:|---|---|---|---|
| 1 | `squeeze::lz77_optimal` never, `squeeze::get_best_lengths` never, `squeeze::lz77_optimal_run` never, `lz77::find_longest_match` never | `lz77.rs:530` interleave_count_4, `index.rs:184` unroll_count_4, `lz77.rs:563` unroll_count_2 | none | 0.9712 | [0.9695, 0.9728] | 0.9719 [0.9697, 0.9749] (sign -) | 1.0004 ±0.0016 | no |
| 2 | `lz77::find_longest_match_loop` always, `squeeze::lz77_optimal` never, `squeeze::lz77_optimal_run` always, `ZopfliHash::update` always | `squeeze.rs:275` vectorize_width_8, `squeeze.rs:325` unroll_count_4, `index.rs:184` vectorize_width_4 | none | 0.9978 | [0.9961, 0.9994] | 0.9968 [0.9951, 0.9984] (sign -) | 1.0000 ±0.0020 | no |
| 3 | `lz77::find_longest_match_loop` always, `squeeze::get_best_lengths` always, `lz77::find_longest_match` always | `squeeze.rs:275` vectorize_width_2, `squeeze.rs:325` vectorize_width_8 | none | 0.9768 | [0.9748, 0.9788] | 0.9786 [0.9771, 0.9802] (sign -) | 1.0002 ±0.0017 | no |
| 4 | `squeeze::get_best_lengths` never, `squeeze::lz77_optimal_run` always, `lz77::find_longest_match` always | `lz77.rs:530` unroll_count_4, `lz77.rs:563` interleave_count_4 | none | 0.9646 | [0.9619, 0.9680] | 0.9631 [0.9609, 0.9656] (sign -) | 1.0012 ±0.0028 | no |
| 5 | `lz77::find_longest_match_loop` always, `squeeze::lz77_optimal` never, `squeeze::get_best_lengths` never, `squeeze::lz77_optimal_run` always, `ZopfliHash::update` never | none | none | 0.9739 | [0.9710, 0.9763] | 0.9927 [0.9738, 1.0183] (no sign) | 0.9980 ±0.0030 | no |

`zopfli-rand-r2` (`artifacts/zopfli-search/zopfli-rand-r2/rounds.jsonl`):

| round | phase A picks | phase B picks | explored | ratio | 95% CI | confirm | A/A | accepted |
|--:|---|---|---|--:|---|---|---|---|
| 1 | `squeeze::get_best_lengths` always, `squeeze::lz77_optimal_run` never | `lz77.rs:530` vectorize_width_4, `lz77.rs:563` unroll_disable | none | 0.9787 | [0.9771, 0.9804] | 0.9807 [0.9786, 0.9824] (sign -) | 0.9995 ±0.0015 | no |
| 2 | `squeeze::lz77_optimal` always, `squeeze::lz77_optimal_run` never | `lz77.rs:530` vectorize_width_2, `lz77.rs:563` unroll_disable, `index.rs:184` unroll_disable | none | 0.9779 | [0.9755, 0.9802] | 0.9770 [0.9736, 0.9813] (sign -) | 1.0011 ±0.0026 | no |
| 3 | `lz77::find_longest_match_loop` always, `squeeze::get_best_lengths` always, `ZopfliHash::update` always | `squeeze.rs:275` unroll_count_8, `squeeze.rs:325` unroll_count_2, `index.rs:184` vectorize_width_8 | none | 0.8803 | [0.8785, 0.8820] | 0.8786 [0.8771, 0.8799] (sign -) | 1.0004 ±0.0025 | no |
| 4 | `lz77::find_longest_match_loop` never, `squeeze::lz77_optimal` always, `squeeze::get_best_lengths` never, `squeeze::lz77_optimal_run` always, `lz77::find_longest_match` always | `lz77.rs:530` interleave_count_4, `lz77.rs:563` unroll_disable | none | 0.9801 | [0.9794, 0.9808] | 0.9825 [0.9804, 0.9843] (sign -) | 1.0008 ±0.0011 | no |
| 5 | `lz77::find_longest_match_loop` never, `squeeze::lz77_optimal` always, `squeeze::get_best_lengths` never, `squeeze::lz77_optimal_run` always | `lz77.rs:530` vectorize_width_8, `lz77.rs:563` vectorize_width_4, `index.rs:184` unroll_disable | none | 0.9805 | [0.9779, 0.9835] | 0.9801 [0.9779, 0.9825] (sign -) | 1.0018 ±0.0025 | no |

**Correctness.** All 30 rounds of all six runs are `correct: true`,
i.e. all nine `.gz` sha256 lines match the baseline. No round has an apply
problem (`summary.md`, "apply problems: none"). The correctness gate
rejected no plan, because no plan needed rejecting.

**No round was accepted in any run.** Every built plan but one measured
slower than the baseline; the exception is described below. 27 of the 30 round batches exclude 1 on the loss
side, and so does every confirmation batch that ran except
`zopfli-rand-r1` round 5's. The three batches without a confirmation
did not trigger one because their CI included 1 (jev-r1 r4 [0.9882, 1.0115] with MDE 6.58%; jev-r2 r3 [0.9988, 1.0013]; rand-r0 r5 [0.9786, 1.0027] with MDE 6.67%). The best
single round of the whole study is `zopfli-jev-r2` round 3, at 1.0001
[0.9988, 1.0013]: `ZopfliHash::update inline_always` (oracle 0.9999,
§168.3) plus `index.rs:184 unroll_count_4` (oracle 0.9948 / 0.9966) plus
`squeeze.rs:325 unroll_disable`, which the oracle found identical to the
baseline (§168.2). It is a null plan in all but name.

#### 169.2 Per-run representative and holdout

§167 defines the representative as "that run's best *accepted* plan's
training ratio (the ratio the run's own acceptance rule ... promoted to
best)". The acceptance rule starts from the baseline as incumbent, "(the
baseline, 1.0000, is the first)" in every `summary.md`. No round was
promoted, so each run's `best` is `{"round": 0, "ratio": 1.0, "label":
"baseline", "plan": null}` (`run-manifest.json`). **Every run's
representative is therefore 1.0000: the baseline was kept.** §167 does not
treat a baseline-kept run as a special case. By its own definition the
value is the incumbent's ratio, 1.0000, and it counts like any other value.
It is not a missing value and not a failed run.

`--measure-holdout` measures the run's best plan once on the holdout cases.
Here the best plan is the baseline, so every holdout batch is a **null arm**
(`holdout.null_arm: true`): cand, base and aa are all the baseline binary.
The holdout ratio is therefore a three-leg A/A, not transfer evidence.
There is no plan whose transfer could be tested.

| run | representative (training) | holdout ratio | holdout 95% CI | holdout in-run A/A | holdout MDE | file |
|---|--:|--:|---|---|--:|---|
| `zopfli-jev-r0` | 1.0000 (baseline kept) | 1.0008 | [0.9993, 1.0022] | 1.0004 ±0.0015 | 3.00% | `zopfli-jev-r0/holdout/stats.md` |
| `zopfli-jev-r1` | 1.0000 (baseline kept) | 1.0029 | [0.9988, 1.0094] | 0.9981 ±0.0029 | 3.03% | `zopfli-jev-r1/holdout/stats.md` |
| `zopfli-jev-r2` | 1.0000 (baseline kept) | 0.9971 | [0.9922, 1.0004] | 0.9871 ±0.0163 | 8.89% | `zopfli-jev-r2/holdout/stats.md` |
| `zopfli-rand-r0` | 1.0000 (baseline kept) | 1.0360 | [0.9853, 1.0850] | 1.0218 ±0.0373 | 18.26% | `zopfli-rand-r0/holdout/stats.md` |
| `zopfli-rand-r1` | 1.0000 (baseline kept) | 1.0219 | [1.0006, 1.0554] | 1.0101 ±0.0154 | 12.56% | `zopfli-rand-r1/holdout/stats.md` |
| `zopfli-rand-r2` | 1.0000 (baseline kept) | 1.0019 | [0.9999, 1.0038] | 1.0004 ±0.0018 | 3.00% | `zopfli-rand-r2/holdout/stats.md` |

Several of these holdout batches were disturbed. They compare a binary
with itself, so any deviation is noise. In `zopfli-rand-r0`, the means sit
above the medians by as much as 11.5% (base binary: mean 1921.1 ms, median
1722.7 ms; base text: 3171.7 against 2895.7 ms), which put the per-workload half-widths at 6.7–9.1% and
the MDE at 18.26%. `zopfli-rand-r1`'s aggregate CI [1.0006, 1.0554] excludes
1 **for the baseline against itself**, with per-case half-widths up to
6.28% (MDE 12.56%). `zopfli-jev-r2`'s aa/binary leg reads 0.9663 [0.9097,
0.9986] (half-width 4.45%, MDE 8.89%). These are interference readings,
consistent with other work on the machine at those times (§168's write-up
was done while this chain ran; what else ran is not recorded). They are not proposer
effects, and no conclusion uses them. The three clean holdouts
(`zopfli-jev-r0`, `zopfli-jev-r1`, `zopfli-rand-r2`, MDE ≈ 3%) read 1.0008,
1.0029 and 1.0019, i.e. the baseline against itself.

#### 169.3 The pre-registered comparison

| arm | run representatives | median | range |
|---|---|--:|---|
| Jev | 1.0000, 1.0000, 1.0000 | **1.0000** | [1.0000, 1.0000] |
| random | 1.0000, 1.0000, 1.0000 | **1.0000** | [1.0000, 1.0000] |

* Direction pre-registered: Jev >= random. Both medians are 1.0000, so the difference is 0 and has no direction.
* Do the ranges overlap? Yes. Both ranges are the single point [1.0000, 1.0000] and coincide, so there is no non-overlap in either direction and no "reverse indication" either.
* Median difference: 0.00 pt, against an MDE of 3%. All round batches
  had MDE 3% except the flagged ones, and none of those is a
  representative.
* **Verdict: not resolved at n=3.** Neither arm moved zopfli, and their
  representatives are identical. This is the outcome §168.8 predicted
  before any §167 run was read.

What the verdict does *not* say. It is not "Jev equals random" as a
proposer. The two arms proposed different plans that lost different
amounts (169.5), and the speed gate rejected both. The representative
measures what survives the gate, and on zopfli nothing did. A descriptive
line, not pre-registered and carrying no verdict: the median of the 15 Jev
round ratios is 0.9826 (range 0.9656–1.0001). The median of the
15 random round ratios is 0.9768 (range 0.8803–0.9978).
Jev built 6 of 15 plans that lost more than 3% in both batches;
random built 3 of 15 (169.5).

#### 169.4 Mechanism checks, k/n (§167, as refined by §168.8)

**(a) void.** The oracle confirmed no "good" site (§168.7: 0 of 67), so
under §167's own words (a) does not apply. A run that changes nothing is
described as "flat; correct no-ops", not as a failed check.
*Descriptive line, not pre-registered, no pass/fail.* **No Jev plan in any
round contains `squeeze.rs:325 unroll_count_8`** (the oracle's best single
arm, sub-MDE +1.26% / +1.29%), and **none contains `lz77.rs:563
unroll_count_8`**. Jev reached `squeeze.rs:325` only through exploration, in
round 3 of every Jev run. The exploration question offers 11 non-`KEEP`
candidates. Jev's top pick was `unroll_disable` at P = 0.54 / 0.54 / 0.48,
and the oracle found `unroll_disable` identical to the baseline there. The
sub-MDE positive arms got little mass: P(`unroll_count_2`) = 0.11 / 0.12 /
0.18 and P(`unroll_count_8`) = 0.02 in all three
(`rounds.jsonl` round 3 `phase_b.why`). In the main-phase answers at that
loop, Jev put P(`KEEP_DEFAULT`) at 0.74–0.98 in every round.

**(b) no oracle-harmful arm in the final plan: 3/3, but vacuously.** Every
Jev final plan is the baseline, and the baseline contains no arm. The
informative count is over every *built* plan. **0 of the 15 Jev round plans
contain `squeeze.rs:275 unroll_count_4` or `unroll_count_8`.** Jev's only
entry at `squeeze.rs:275` was `unroll_disable`: `zopfli-jev-r0` rounds 2, 4
and 5 and `zopfli-jev-r1` / `zopfli-jev-r2` round 2, via exploration or
argmax. The oracle found that arm identical to the baseline (§168.2), so
putting it in a plan is a no-op, not a sign that Jev avoided the harmful
arms. When `squeeze.rs:275` was explored, the harmful `unroll_count_4` was
Jev's second-ranked candidate (P = 0.17 / 0.19 / 0.17) behind
`unroll_disable` (0.46 / 0.46 / 0.45), and `unroll_count_8` had P = 0.01. The
losses in the rounds that carried `squeeze.rs:275 unroll_disable` come from
their other entries.

**(c) Jev's `KEEP_DEFAULT` rate at oracle-flat sites.** Flat sites (§168.8)
are the six function marks and `lz77.rs:530`, `squeeze.rs:325`,
`lz77.rs:563` and `index.rs:184`, i.e. every site except `squeeze.rs:275`.
The count is over Jev's main-phase answers (phases A and B, all rounds;
exploration questions have no `KEEP` option and are excluded), from
`jev-log/<run>.jsonl` `response.answers[].choice`:

| run | KEEP at flat sites, all rounds | round 1 only | rounds whose raw answers were all-`KEEP` (A / B / both) |
|---|--:|--:|---|
| `zopfli-jev-r0` | 32 / 45 (71%) | 4 / 7 | 0 / 3 / 0 of 5 |
| `zopfli-jev-r1` | 33 / 43 (77%) | 4 / 7 | 0 / 4 / 0 of 5 |
| `zopfli-jev-r2` | 42 / 46 (91%) | 4 / 7 | 3 / 5 / 3 of 5 |
| total | 107 / 134 (80%) | 12 / 21 | --- |

(The all-`KEEP` columns are `phase_{a,b}.readout.all_keep_default` in
`rounds.jsonl`.) The 27 non-`KEEP` answers at flat sites break down as
follows. Twenty-one are `inline_always` on four functions:
`find_longest_match` 4+3+2 answers, `ZopfliHash::update` 2+3+1,
`find_longest_match_loop` 1+3+1, `lz77_optimal_run` 1+0+0. In the oracle
these are `inline_always` at −2.0% / −2.0%, 0.9999 (flat, unconfirmed),
−0.7% / −0.9% and identical to the baseline, respectively (§168.2, §168.3):
sub-MDE losses or no-ops, never gains. The other six are loop unrolls:
`lz77.rs:530 unroll_count_4` 2 and `lz77.rs:563 unroll_count_2` 2 (jev-r0
rounds 4–5), plus `index.rs:184 unroll_count_4` (jev-r0 round 5) and
`unroll_count_2` (jev-r1 round 5). All six are flat or sub-MDE in the oracle.

In round 1 the request was byte-identical across the three runs (169.6).
All three runs answered the same way: `inline_always` at
`find_longest_match_loop` (P 0.64–0.68), `ZopfliHash::update` (0.46–0.50 vs
`KEEP` 0.44–0.46) and `find_longest_match` (0.49–0.56 vs `KEEP` 0.40–0.47),
with `KEEP` at the other three functions. The last two are near-ties. Over
the rounds the rate rises in every run as the history of losses
accumulates. By rounds 3–5, `zopfli-jev-r2` answered `KEEP_DEFAULT` at every
site in both phases. Its last three plans (`ZopfliHash::update
inline_always` + `index.rs:184 unroll_count_4`, with round 3 also carrying
one exploration pick, `squeeze.rs:325 unroll_disable`) exist only because
`forced_top1` builds one hint per all-`KEEP` phase. **So Jev's own answers
reached "keep the baseline" in 1 of 3 runs (jev-r2, from round 3), and in
0 of 3 runs in round 1.** In all 15 Jev rounds the driver built a non-empty
plan. `forced_top1` plus `--explore 2` make an all-`KEEP` round impossible
by construction (`docs/search-driver.md`). The baseline survived in every
run because the speed gate rejected every plan, not because Jev proposed
it.

#### 169.5 Random's picks

The random proposer drew non-`KEEP` answers at 2–5 of the 6 function marks
and 0–3 loops per round. **It drew an oracle-harmful arm in 2
of 15 rounds.** `zopfli-rand-r0` round 1 carried `squeeze.rs:275
unroll_count_8` (oracle −8.3% / −8.4%) together with six other hints and
measured **0.9429 [0.9410, 0.9453], confirmation 0.9427** (sign −). The speed gate
rejected it, as it should.
`zopfli-rand-r2` round 3 drew the same arm, `squeeze.rs:275
unroll_count_8`, together with `inline_always` on three functions,
`squeeze.rs:325 unroll_count_2` and `index.rs:184 vectorize_width_8`. It
measured **0.8803 [0.8785, 0.8820], confirmation 0.8786** (sign −; json
0.8453, text 0.8573). That is a −12% plan, the worst of the study, and the gate rejected it
too. `zopfli-rand-r1` touched `squeeze.rs:275` twice, with
`vectorize_width_8` (round 2) and `vectorize_width_2` (round 3), both
identical to the baseline in the oracle. Random's round ratios:
`zopfli-rand-r0` 0.9429 / 0.9908 / 0.9727 / 0.9702 / 0.9882,
`zopfli-rand-r1` 0.9712 / 0.9978 / 0.9768 / 0.9646 / 0.9739, `zopfli-rand-r2` 0.9787 / 0.9779 / 0.8803 / 0.9801 / 0.9805.
Plans beyond −3% in both batches: `zopfli-rand-r0` round 1 and
`zopfli-rand-r1` round 4 (0.9646 / 0.9631), and `zopfli-rand-r2` round 3 (0.8803 / 0.8786). That is 3 of 15, and two of the three carry the harmful arm.

Jev built 6 such plans of 15: `zopfli-jev-r0` rounds 2/3/4
(0.9656 / 0.9664, 0.9681 / 0.9685, 0.9684 / 0.9662), `zopfli-jev-r1` rounds
2/3 (0.9669 / 0.9647, 0.9657 / 0.9640) and `zopfli-jev-r2` round 2 (0.9689 /
0.9675). All six carry `lz77::find_longest_match inline_always` (oracle
−2.0%), and all six also carry an unroll at `lz77.rs:530` (and in four of
them at `lz77.rs:563` too), loop keys taken under a changed inlining context that the
oracle never timed together. The product of the oracle's single-arm round
ratios predicts 0.9783 (jev-r0 r2/r4, jev-r2 r2: 0.9799 × 0.9943 ×
1.0041), 0.9742 (jev-r0 r3), 0.9695 (jev-r1 r2) and 0.9657 (jev-r1 r3).
The measured values are equal to that or up to 1.3 pt worse. Those oracle
arms were timed under the baseline's inlining, not under these plans'
inlining. None contains an
oracle-harmful arm.

#### 169.6 Jev nondeterminism (decision 94/96(e))

Round-1 requests carry an empty history. **For every pair of Jev runs, all
round-1 requests are byte-identical**: A, A.explore and B, with the same
`request_sha256` in all three `jev-log/<run>.jsonl`. Round 1 had no
B.explore request (one loop site, forced). From round 2 on, every request
differs across runs, because the history differs (measured ratios), so no
later pair is on identical input.

| round-1 phase | pair | identical | questions | max \|ΔP\| (where) | argmax flips |
|---|---|---|--:|---|--:|
| A | r0–r1 | yes | 6 | 0.07 (`get_best_lengths`, `KEEP`) | 0 |
| A | r0–r2 | yes | 6 | 0.07 (`lz77_optimal`, `KEEP`) | 0 |
| A | r1–r2 | yes | 6 | 0.07 (`get_best_lengths`, `KEEP`) | 0 |
| A.explore | r0–r1 | yes | 2 | 0.06 (`get_best_lengths`, `inline_always`) | 0 |
| A.explore | r0–r2 | yes | 2 | 0.03 | 0 |
| A.explore | r1–r2 | yes | 2 | 0.03 | 0 |
| B | r0–r1 | yes | 1 | 0.02 | 0 |
| B | r0–r2 | yes | 1 | 0.01 | 0 |
| B | r1–r2 | yes | 1 | 0.02 | 0 |

**0 argmax flips in 27 compared answers; max |ΔP| 0.07.** That is smaller
than hintbench's 0.10 and one flip (exp6.md §4). The two argmax near-ties
(`ZopfliHash::update`, margin 0.01–0.06, and `find_longest_match`, margin
0.02–0.16) held in all three runs. **The plan still differed.** Phase B was
all-`KEEP` (P 0.83–0.85), so `forced_top1` built the best non-`KEEP`
candidate at `index.rs:184`. That was `unroll_count_4` in r0 (0.07 vs
`unroll_count_2` 0.05) and r2 (0.08 vs 0.05), but a tie in r1 (0.07 / 0.07)
went to `unroll_count_2`. So r0 and r2 built plan `5ed127e9…` and r1 built
`ebad178d…`. A 0.02 move on a secondary probability changed the built plan
with no argmax flip. The measured cost of that difference is small (0.9826
/ 0.9825 vs 0.9832).

Measurement-only component, for decision 96(d): the same `bin_sha256`
measured in different batches gave the following.
* `3a7068aa…` (jev-r0 r1, jev-r2 r1): 0.9826 / 0.9825.
* `6469d3a8…` (jev-r0 r2, jev-r0 r4, jev-r2 r2): 0.9656 / 0.9684 / 0.9689,
  a 0.33 pt spread. jev-r0 r4's plan differs from r2's only by
  `lz77_optimal_run inline_always`, which the oracle found identical.
* `25e9dca2…` (jev-r2 r3/r4/r5): 1.0001 / 0.9974 / 0.9964, 0.37 pt.
* `f7d611dd…` (rand-r0 r3, rand-r1 r5): 0.9727 / 0.9739.
* `5a5b95ae…` (jev-r1 r4/r5): 0.9967 / 0.9895. r4's batch was disturbed
  (MDE 6.58%, A/A 1.0076 ±0.0104).

The k5 argv0 mode of hintbench does not apply here (decision 99, NULL on
zopfli). Every batch was taken at class 96: `argv0.class` and
`confirm.argv0.class` are 96 on all 30 rows, `status: measured` on all 30,
and every holdout is at class 96, so no batch was `measure-failed`.

**In-run A/A.** Over the round and confirmation batches, the aa aggregate
CI excluded 1 in 4 of 28 Jev batches (jev-r0 r3 0.9979; jev-r1 r3 1.0019 and
r4 1.0076; jev-r2 r1 1.0020) and in 2 of 29 random batches (rand-r0 r3/r4
confirmations 0.9986 / 0.9984; rand-r2 0 of 10). All of these are within ±0.8%.
Batches with MDE above 3% were: jev-r1 r4 (6.58%), rand-r0 r5 (6.67%) and
rand-r1 r5's confirmation (12.76%); rand-r2 had none, plus the holdouts in 169.2. No
verdict depends on any of them, because none was accepted and none is a
representative.

#### 169.7 Gateway

§167's gateway rule makes a run invalid if it loses more than 2 of its 10
main-phase requests. **No Jev run lost any request**: all 14 requests of
each run landed, with 0 exhausted, 0 lost phases and 0 lost rounds. All
three Jev runs are valid and no `-b` rerun was owed. Figures from
`run-manifest.json` `gateway`:

| run | A req / attempts / mean bytes | B req / attempts / mean bytes | explore req / attempts / mean bytes | total attempts | seconds waiting |
|---|---|---|---|--:|--:|
| `zopfli-jev-r0` | 5 / 61 / 57 580 | 5 / 42 / 42 463 | 4 / 5 / 18 584 | 108 | 188.5 |
| `zopfli-jev-r1` | 5 / 23 / 57 581 | 5 / 37 / 38 766 | 4 / 12 / 18 614 | 72 | 117.6 |
| `zopfli-jev-r2` | 5 / 65 / 57 578 | 5 / 65 / 44 482 | 4 / 4 / 18 575 | 134 | 238.9 |
| total | 15 / 149 | 15 / 144 | 12 / 21 | 314 | 545.0 |

The largest attempt counts per request were jev-r0 round 4 A (25) and
round 5 B (29), and jev-r2 round 5 B (41), all within the 200-attempt /
600 s budget. Random runs make no requests (`gateway: null`).

#### 169.8 Cost

| | jev-r0 | jev-r1 | jev-r2 | total |
|---|--:|--:|--:|--:|
| HTTP requests (landed) | 14 | 14 | 14 | 42 |
| Choice questions | 55 | 53 | 56 | 164 |
| latency total / max | 24.2 s / 2250 ms | 29.3 s / 2826 ms | 27.9 s / 3047 ms | 81.4 s |
| tokens in / out | 189 860 / 4 735 | 184 206 / 4 420 | 192 948 / 4 865 | 567 014 / 14 020 |
| cost | $0.00 | $0.00 | $0.00 | $0.00 |
| Jev share of wall clock | 0.70% | 0.95% | 0.84% | --- |

(Source: `run-manifest.json` `jev_totals` and each `summary.md`. The
503 wait time is in 169.7 and is not included in latency.) The total of
42 requests is within §167's cap of ≤ 75. Wall clock was 48–58 min per run
(table above), over §167's structural floor estimate of "30–50 min of
timing alone". The six runs took 19 005.8 s = 5.28 h of `wall_s`, and 06:37:08–11:53:56 elapsed h in total.

#### 169.9 Deviations

* **`best-plan.json` does not exist in any of the six run directories.**
  Every `summary.md` still says "`best-plan.json` is a copy of it". When the
  best is the baseline (`plan: null`), the driver writes no file and the
  summary text is wrong. This is recorded as a driver inconsistency and was
  not patched. Nothing was copied for it; the baseline-kept best is in each
  manifest's `best` field.
* The holdout batches are null arms (169.2), and three of them were
  disturbed (MDE 8.9–18.3%).
* Nothing was re-run, and no run was added after the results were seen
  (optional stopping, §167).
* None of the six runs needed a `-b` rerun, a resume or a manual intervention.

#### 169.10 Verdict

* **Representatives: Jev 1.0000 / 1.0000 / 1.0000, random 1.0000 / 1.0000 /
  1.0000. Not resolved at n=3.** Both arms have median 1.0000 and range [1.0000, 1.0000]. The difference is 0 pt, the ranges coincide, and the MDE is 3%.
* **Flat, but not correct no-ops from Jev.** Jev proposed non-`KEEP` hints
  in every round. 14 of its 15 plans measured slower than the baseline
  (0.9656–0.9974), and the 15th read 1.0001 with its CI across 1.
  6 of the 15 lost more than 3% in both batches. The baseline was kept 3/3
  because the acceptance gate rejected every plan. Jev's hints were the
  oracle's known sub-MDE losses, above all `find_longest_match
  inline_always`, the same pick in round 1 of every run. Jev drifted toward
  `KEEP_DEFAULT` as its history filled (KEEP at flat sites 71% / 77% / 91%),
  and reached an all-`KEEP` answer set in 1 of 3 runs (jev-r2, rounds 3–5).
* **(a) void. (b) 3/3 vacuously; 0/15 Jev built plans contain a harmful
  arm. (c) 80% `KEEP` at flat sites (12/21 in round 1).** Random drew the
  harmful `squeeze.rs:275 unroll_count_8` twice (rand-r0 r1, 0.9429; rand-r2
  r3, 0.8803), and the gate rejected both.
* **Nondeterminism:** round-1 requests were byte-identical across all three
  pairs, with max |ΔP| 0.07 and 0 argmax flips. A 0.07/0.07 tie on a
  secondary probability changed the forced pick and hence the built plan
  in 1 of 3 runs.
* **Not established:** any Jev-vs-random difference in outcome, and
  whether Jev finds a good hint on zopfli where one exists. None is reachable
  in this vocabulary and site set (§168: ceiling +1.8%, under the MDE).
  Also not established: anything about `cache.rs:108`, which lies outside
  this site set.

### 170. Measurement protocol v2 (confirm at MDE, no A/A leg in oracle arms, fewer reps): verification on toy and hintbench

**Why.** On zopfli 95% of the measurement time was timing, not builds, and
20 of the 22 confirmation batches of the oracle confirmed differences below
the MDE (§168; decision 103). Protocol v2 cuts the timing without changing
what the MDE rule reads. Protocol v1 (decision 80) stays the default and
every frozen comparison keeps it. `jev-opt.toml` gained the keys
`confirm_when = "ci"` and `aa_leg = true` (v1 values) plus comments, so a
run's `config_sha256` changes from this commit on **without any frozen
value changing**.

**What v2 is** (`scripts/jev_search.py --protocol v2`, or the
`[evaluation]` keys / flags `confirm_when`, `aa_leg`, `reps_oracle`, `mde`;
`docs/search-driver.md` "Measurement protocol v1 and v2"):

| | v1 (default) | v2 |
|---|---|---|
| confirmation batch when | first batch's 95% CI excludes 1 (aggregate or own kernel) | \|ratio − 1\| ≥ MDE (aggregate or own kernel); MDE = frozen `mde` if set, else the batch's own max(2 × worst half-width, 3%) |
| oracle one-factor arm batch | base + cand + aa, n = 15 | base + cand, `reps_oracle` = 8 |
| confirmation batch | 3 labels, n | 3 labels, the first batch's n |
| search rounds, combination arm, holdout | 3 labels, n | unchanged |

Rules stated before the numbers: (1) correctness must pass on every arm
under both protocols; (2) on the k2 arm both protocols must fire the
confirmation and confirm the same sign; (3) the wall clock is read from
`rounds.jsonl` `wall_s`; batch times from file mtimes (`correctness.txt` →
`samples.json`, `stats.json` → `confirm/samples.json`). No speed claim is
made from any of these runs.

#### 170.1 Stub checks (no timing)

```
python3 -m py_compile scripts/jev_search.py
python3 <scratchpad>/test_protocol.py     # stubbed bench.py / stats
```

`confirm_trigger(rule="mde")` fires at ratio 1.031 and 0.969 and not at
1.029 / 0.971 (MDE 3%; `ci` fires on all four), uses a per-batch MDE above
the floor (4.41%: 1.035 aggregate not fired, own kernel 1.10 fired), and
floors a frozen `mde` of 0.01 to 0.03. `batch_plan()`: under v2 an oracle
one-factor arm is (n 8, no A/A), a search round and the combination arm
(15, A/A); under v1 everything is (15, A/A); a `--aa-leg on` flag beats the
preset (protocol `custom`). `measure()` with a stubbed `bench.py run`
passed 2 `--label`s with `aa=False` and 3 with `aa=True`. All passed.

#### 170.2 toy: the function-attribute oracle under v1 and v2

```
export TARGET=toy
scripts/jev_search.py --target toy --marks artifacts/plugin-day3/marks/toy-all.txt \
    --proposer oracle --oracle-phase A --vocab v6 --protocol v2 \
    --out artifacts/toy-search/protocol-v2          # fresh baseline (plugin of today)
scripts/jev_search.py --target toy --marks artifacts/plugin-day3/marks/toy-all.txt \
    --proposer oracle --oracle-phase A --vocab v6 \
    --baseline-dir artifacts/toy-search/protocol-v2/baseline \
    --out artifacts/toy-search/protocol-v1
```

7 rounds each (6 one-factor arms + the combination). `inline_always` on all
three functions and the combination were `identical` (no-op, 7.8–8.3 s
each, not timed). Correctness 7/7 and 7/7.

| arm | v1 wall s | v1 ratio / hw / MDE | v2 wall s | v2 ratio / hw / MDE | v2 note |
|---|--:|---|--:|---|---|
| `count_quotes inline_never` | 69.1 | 0.9980 / 0.0085 / 6.44% | 33.0 | 1.0016 / 0.0062 / 3.44% | |
| `dot_f64 inline_never` | 69.2 | 0.9994 / 0.0058 / 3.88% | 32.9 | 1.0051 / 0.0042 / 3.00% | CI [1.0009, 1.0093] excludes 1: v1 would confirm, v2 `flat_below_mde` |
| `find_special inline_never` | 69.2 | 1.0019 / 0.0035 / 3.00% | 32.9 | 0.9955 / 0.0085 / 6.92% | |
| run `wall_s` | 239.3 | | 136.6 | | |

(hw = aggregate CI half-width.) A measured arm costs 69.1 s under v1 and
32.9 s under v2; minus the ~7.8 s build + correctness + code_class, the
timing is 61.3 s → 25.1 s (**0.41×**; the label × rep count predicts
16/45 = 0.36, warmup and per-batch fixed cost make up the rest). For
scale, the "Search driver (smoke)" round (n = 3, warmup 1, 3 labels, two
builds) was 26 s. Every per-batch MDE above 3% here comes from one noisy
case of the four.

#### 170.3 hintbench: one known arm (`k2_mix inline_always`) under v1 and v2

```
export TARGET=hintbench
# marks file with the single line hbkernels::k2_mix
scripts/jev_search.py --target hintbench --marks <scratchpad>/hb-k2.txt \
    --sites artifacts/hintbench-sites/sites.json \
    --site-set oracle.selected_keys_loop_hint_kernels \
    --proposer oracle --oracle-phase A --oracle-candidates inline_always --rounds 1 \
    --vocab v6 -n 15 --warmup 3 --baseline-dir artifacts/hintbench-sites/baseline \
    --out artifacts/hintbench-search/protocol-v1-k2
# the same + --protocol v2 --out artifacts/hintbench-search/protocol-v2-k2
```

Case set `holdout-as-search` (hintbench declares no training set), argv0
len 80 / class 96 on every batch, `code_class: code`, correctness OK in both.

| | v1 | v2 |
|---|---|---|
| first batch | 15 reps, base/cand/aa, **146.9 s** | 8 reps, base/cand, **59.9 s** |
| aggregate ratio, CI hw | 1.0654, ±0.0035 | 1.0628, ±0.0035 |
| k2 ratio, CI hw | 1.6721, ±0.0063 | 1.6747, ±0.0099 |
| in-run A/A hw | 0.0030 | (no leg) |
| batch MDE | 4.63% | 5.13% |
| trigger | CI excludes 1: aggregate + k2 | ≥ MDE: aggregate + k2 |
| confirmation batch | 15 reps, 3 labels, 146.4 s: 1.0640 ±0.0019, k2 1.6737 ±0.0062 | 8 reps, 3 labels, 89.5 s: 1.0639 ±0.0022, k2 1.6695 ±0.0073, A/A hw 0.0043 |
| `confirmed` / `confirmed_aggregate` | true / true | true / true |
| arm `wall_s` | **303.4** | **159.2** |

The +67% arm is found and confirmed both ways (rule 2 holds), and it is the
oracle's §85 arm at the same size. First batch 0.41× (as on the toy),
confirmation 0.61× (8/15 reps, labels unchanged), arm with its confirmation
0.52×.

#### 170.4 CI half-width at n = 8 vs n = 15, from existing batches (no new timing)

Each of the first 12 `samples.json` of `artifacts/hintbench-oracle` and of
`artifacts/zopfli-search/oracle` re-read by `bench.py stats` (2000
resamples, seed 1) on all 15 rounds and on the first 8 rounds only (rounds
are shuffled and interleaved, so the first 8 are a valid 8-rep batch):

| batches | n | cand aggregate hw (median) | A/A aggregate hw | worst per-case hw | batch MDE median / max |
|---|--:|--:|--:|--:|---|
| hintbench oracle (12) | 15 | 0.0028 | 0.0028 | 0.0211 | 4.21% / 7.40% |
| hintbench oracle (12) | 8 | 0.0027 | 0.0034 | 0.0264 | 5.28% / 10.77% |
| zopfli oracle (12) | 15 | 0.0033 | 0.0036 | 0.0074 | 3.00% / 3.00% |
| zopfli oracle (12) | 8 | 0.0047 | 0.0051 | 0.0112 | 3.00% / 3.10% |

Median ratio of the 8-rep to the 15-rep half-width: zopfli 1.39 (worst
case 1.47), hintbench 1.24 (1.26), against √(15/8) = 1.37. On zopfli the
8-rep aggregate half-width (~0.5%) is a sixth of the 3% MDE and the MDE
stays at the floor: v2 loses nothing the MDE rule needs. **On hintbench it
does**: the per-batch MDE is set by k8 (per-case hw 1.3–3.6% at n = 15) and
rises to a median 5.3%, max 10.8%, so the known k3 `unroll 4` (+4.4%) would
not reach its batch's MDE and would be reported flat. On such a target run
v2 with a frozen `--mde` (the target's A/A MDE, floor 3%) or with
`--reps-oracle 15`. This is documented in `docs/search-driver.md`.

#### 170.5 Projected cost under v2 (projection, not a measurement)

Inputs are `artifacts/zopfli-search/*/rounds.jsonl` `wall_s` and the 0.41 /
0.61 factors measured in 170.2–170.3.

* **zopfli-sized oracle (68 arms), v1 as run: 4.40 h.** 38 no-ops × 29.4 s;
  29 one-factor measured arms at 294.6 s (no confirmation; 265 s of it
  timing) or 562.0 s (confirmed; 22 of 30); the combination 1 arm.
  **v2:** 38 × 29.4 s = 0.31 h; 29 × (29.4 + 0.41 × 265.2 = 138 s) = 1.11 h;
  confirmations only where |ratio − 1| ≥ MDE = 2 of 22 (rounds 25, 26:
  `squeeze.rs:275` unroll 4 / 8) × 0.61 × 267 s = 0.09 h; the combination
  at v1 cost 0.16 h. **≈ 1.67 h (2.6×).** A measured one-factor arm goes from
  491 s (mean, confirmations included) to ~149 s (**3.3×**). Staged with
  `--site-filter vectorized` for the width / interleave / disable arms, the
  32 no-op builds on the four unvectorized loops are not built either:
  **≈ 1.41 h (3.1×)**. The owner's ~5× is not reached at n = 8: what remains
  is the fixed 29 s build + correctness + code_class per arm and the 8 reps.
* **5-round search (jev or random), v2:** round batches keep 3 labels and
  n = 15, so only the confirmation rule saves. The six zopfli runs (§169)
  took 2475–3078 s (mean 2781 s) with 27 confirmations in 30 rounds, 9 of
  them at ≥ MDE. Dropping 18 confirmations × ~270 s ≈ 810 s per run gives
  **≈ 1970 s (33 min) per run, 1.4×**.

#### 170.6 What changed in the driver

`--protocol v1|v2`, `--confirm-when`, `--aa-leg`, `--reps-oracle`,
`--mde`; `rounds.jsonl` rows carry `protocol`, `confirm_rule`, `reps`,
`labels`, and under `mde` also `confirm_trigger_ci_rule`, `confirm_mde`,
`flat_below_mde`; the manifest has a `protocol` block; `summary.md` states
the protocol. An arm without the A/A leg has `aa: null`. For the oracle,
`--rounds N` now caps the arms (it was ignored), `--oracle-candidates GLOB`
filters arms by candidate at every site alike, `--site-filter vectorized`
keeps only loops the baseline dump's `post_vectorize` says were vectorized
(oracle only; refuses a dump without the record), and every arm prints
`[oracle] progress: skipped / measured / other / remaining, ETA`. Under
`confirm_when = "mde"` a sub-MDE round cannot pass acceptance rule 4, so a
search can no longer promote it (v1 could).

### 171. MDE rule v2 (2 × A/A, floor 1%): a post-hoc re-read of the oracles

**Post hoc, labelled as such.** Every pre-registered verdict in this file
(§117-128 hintbench, §135-142 jaq A2, §166/§168 zopfli) used the v1 MDE,
`max(2 × worst per-workload CI half-width, 3%)`, recomputed **per batch**
(decision 27's 3% policy floor). Those verdicts stand as recorded and are not
relabelled. This section re-reads the same `rounds.jsonl` records under a
rule stated after the numbers were known; **nothing was re-measured**, no
build or timing was run. It exists because the owner redirected the goal on
2026-09-24: "+α on top of O3 + native + fat LTO + PGO", on any target;
small reproducible gains must not be discarded by an arbitrary floor ---
"if it is not noise, it goes in" (decision 105).

**Rule v2 (for all new pre-registrations from decision 105 on).**

* `MDE = max(2 × h, 1%)`, where `h` is the **worst per-case 95% CI
  half-width over the A/A legs of the target's registered A/A panel**
  (identical-binary legs only; candidate labels do not count). The value is
  **frozen per target** before the arms run, not recomputed per batch, so a
  noisy batch does not raise its own bar (decision 104 (b)).
* **Effect (oracle arm)**: the round batch **and** the independent
  confirmation batch are both beyond the MDE on the same side
  (`ratio − 1 ≥ MDE` in both = effect; `1 − ratio ≥ MDE` in both =
  harmful). Same logic as decision 80 (a) / §166, new threshold. The ratio
  is the one the target's readout uses: the aggregate (geomean) on zopfli and
  jaq, the arm's own kernel on hintbench.
* **For the article** additionally: the holdout panel agrees (beyond the
  holdout panel's own v2 MDE, same side) where a holdout was measured.
* Because `h` is the worst *per-case* half-width while zopfli's and jaq's
  readout is the geomean, the rule is conservative for aggregate claims (the
  aggregate A/A half-width is 2-3× smaller, below). This is the rule as
  directed; alternatives are listed under "sensitivity", not adopted.

Source of every number below: the named fields of
`artifacts/{zopfli-search/oracle,hintbench-oracle,jaq-search/oracle-A2}/rounds.jsonl`
(`ratio`, `confirm.ratio`, `kernel.ratio`, `confirm.kernel.ratio`, `mde`,
`confirm.mde`) and of the panels' `stats.json`
(`per_workload.<label>.<case>.halfwidth`, `aggregate.<label>.halfwidth`),
read by an ad-hoc Python script in the session scratchpad (not committed;
it only reads and compares these fields).

#### 171.1 The v2 MDE per target

| target | registered A/A panel | worst per-case A/A half-width (leg / case) | v2 MDE | v1 MDE used |
|---|---|--:|--:|---|
| zopfli, training | §165 `artifacts/zopfli-sites/aa-training/stats.json` (aa, aa2; n 18; class 96) | 0.919% (aa2 / binary) | **1.838%** | 3% (every batch but two, §168.3) |
| zopfli, holdout | §165 `artifacts/zopfli-sites/aa-holdout/stats.json` | 0.391% (aa2 / binary) | 0.78% -> **1.00%** (floor) | 3% (§168.5) |
| hintbench, oracle (§118-128) | §119 null panels `artifacts/hintbench-oracle-nullpanel-{1,2}/stats.json` (n1-n3 × 2 batches; n 15) | 1.876% (panel 2, n3 / k8) | **3.752%** | per batch, 3.00-11.88% on round batches |
| hintbench, future (pinned) | §162 `artifacts/hintbench-aa-study/p6-pinned/stats.json` (aa, cand = same binary; class 96; n 15) | 1.588% (aa / k8) | **3.176%** | --- |
| jaq, Oracle A2 (§135-142) | §140 holdout panel `aa` leg, `artifacts/jaq-search/oracle-A2-holdout/stats.json` (n 15, gap 250 ms) | 1.63% (aa / objsearch) | **3.26%** | 3% (§139) |
| jaq, cross-check | §164 `artifacts/jaq-aa-classes/stats.json` (argv0-class legs c80/c112/c128 vs c96, all NULL; n 35) | 1.42% (c128 / readwrite) | 2.84% | --- |

Headline: **v2 lowers the bar only on zopfli.** On hintbench and jaq one
noisy case (k8; objsearch) puts `2 × h` above 3%, so v2 *raises* the bar
there; the "between 1% and 3%" band the owner's direction is about is empty
on both under the rule as written.

For scale, the aggregate A/A half-widths of the same panels (not used by the
rule): zopfli training 0.33% / 0.41%, holdout 0.15% / 0.19%; hintbench null
panels 0.20-0.27%, §162 0.28% / 0.32%; jaq A2 holdout aa 0.56%.

jaq panel choice, stated: the A2 holdout `aa` leg is the only A/A leg taken
under A2's own conditions outside the arms. §113's dedicated null panel
belongs to Oracle A (pre-closure-fix) and is not borrowed. The §164 panel is
listed as a cross-check only (its legs differ in argv[0] length class, and it
has n 35). On jaq the within-batch half-width is also known to be
over-confident (A2 in-run A/A: 28 of 60 intervals exclude 1, range 5.43 pt,
sd 1.10%, §139; decision 80), so any half-width-based MDE understates jaq's
noise.

#### 171.2 zopfli (training 1.838%, holdout 1.00%)

All sign-confirmed and two-batch rows of §168.3 re-read. Ratios from
`artifacts/zopfli-search/oracle/rounds.jsonl` (`ratio`, `confirm.ratio`),
holdout from `artifacts/zopfli-search/oracle/holdout-panel/stats.json`.

| round | site | candidate | round | confirm | holdout | §168 verdict (v1) | v2 |
|--:|---|---|--:|--:|--:|---|---|
| 68 | combination (325 + 563 unroll 8) | --- | +1.811% | +2.063% | +1.77% [1.0163, 1.0193] | flat (sub-MDE) | **flat, borderline**: round batch 0.027 pt under 1.838%; confirm and holdout pass |
| 37 | `squeeze.rs:325` | `unroll_count_8` | +1.256% | +1.285% | +1.33% [1.0116, 1.0151] | flat (sub-MDE) | flat on training (both under 1.838%); holdout passes 1.00% |
| 12 | `lz77::find_longest_match` | `inline_never` | −2.229% | −2.676% | --- | flat (confirmed −) | **harmful** (flip) |
| 11 | `lz77::find_longest_match` | `inline_always` | −2.014% | −2.039% | --- | flat (confirmed −) | **harmful** (flip) |
| 6 | `squeeze::get_best_lengths` | `inline_never` | −2.012% | −2.173% | --- | flat (confirmed −) | **harmful** (flip) |
| 8 | `squeeze::lz77_optimal_run` | `inline_never` | −2.215% | −1.829% | --- | flat (confirmed −) | flat, **borderline**: confirm 0.009 pt under |
| 25 | `squeeze.rs:275` | `unroll_count_4` | −3.614% | −3.324% | --- | harmful | harmful |
| 26 | `squeeze.rs:275` | `unroll_count_8` | −8.305% | −8.443% | --- | harmful | harmful |

Every other measured arm (the remaining 21 of §168.3) is inside 1.838% in at
least one batch and stays flat. **Under v2 as written, zopfli has 0 effects
and 5 harmful arms** (was 0 and 2); the combination misses by 0.027 pt in
its round batch, the one leg of three that does not clear. The two
borderlines are reported at three decimals and are not rounded either way.

**Sensitivity (not the rule; each is a different frozen `h` the owner could
register instead).**

| alternative `h` | MDE | combination (r68) | `squeeze.rs:325 unroll_count_8` (r37) |
|---|--:|---|---|
| §165 holdout panel's worst per-case, 0.391% | 1.00% | effect (1.81 / 2.06 / holdout 1.77) | effect (1.26 / 1.29 / holdout 1.33) |
| §165 training panel's **aggregate** A/A, 0.414% (aa2) | 1.00% (floor) | effect | effect |
| the oracle run's own worst round-batch in-run A/A (aggregate), 0.83% (§168.3) | 1.66% | effect | flat |

Under the 1.00% readings, the negative side also grows: r3
`lz77_optimal inline_always` (−1.26 / −1.24), r8, r13 `lz77.rs:530
unroll_count_2` (−1.44 / −1.21) and r24 `squeeze.rs:275 unroll_count_2`
(−1.57 / −1.32) become harmful as well (9 harmful in all).

#### 171.3 hintbench (3.752%, §119 null panels)

The oracle's gate (§122's "MDE gate", §124) used each batch's own MDE, which
ran 3.00-11.88% on round batches. Freezing the MDE at the panel's 3.752%
changes four arms, all through the freeze rather than through the floor
(own-kernel ratios, `artifacts/hintbench-oracle/rounds.jsonl` `kernel.ratio`
/ `confirm.kernel.ratio`; batch MDEs `mde` / `confirm.mde`):

| round | site | candidate | round | confirm | batch MDEs (v1) | v1 gate | v2 |
|--:|---|---|--:|--:|---|---|---|
| 74 | k3 loop | `unroll_count_2` | +4.23% | +3.94% | 4.92% / 3.83% | flat | **effect** (flip) |
| 2 | `k1_step` | `inline_never` | −4.55% | −4.34% | 3.00% / 4.57% | flat | **harmful** (flip) |
| 61 | k4 loop | `interleave_count_2` | −6.04% | −6.07% | 6.81% / 6.97% | flat | **harmful** (flip) |
| 72 | k8 loop | `interleave_count_2` | −5.44% | −4.06% | 7.59% / 6.03% | flat | **harmful** (flip) |

No v1 effect or harmful arm drops out (the smallest v1 effect, k3
`unroll_count_4`, is +4.36% / +4.24%). The combination (1.0881 / 1.0856,
holdout 1.0847) is unchanged. The 1-3% arms stay flat under v2:

| round | site | candidate | round | confirm | v2 (3.752%) |
|--:|---|---|--:|--:|---|
| 48 | k5 loop | `vectorize_width_16` | +2.65% | +2.85% | flat |
| 42 | k5 loop | `unroll_count_4` | +2.07% | +1.70% | flat |
| 43 | k5 loop | `unroll_count_8` | +1.94% | +1.19% | flat |
| 17 | `k4_count_bytes` | `inline_never` | +1.52% | +1.86% | flat |
| 52 | k4 loop | `unroll_count_2` | −1.52% | −1.40% | flat |

Side note, **not the v2 rule**: hintbench is read per kernel, so a
per-case MDE (each kernel's own worst A/A half-width in the §119 panels:
k1 0.445%, k2 0.527%, k3 0.635%, k4 0.344%, k5 0.482%, k6 0.546%, k7 0.494%,
k8 1.876%, i.e. MDE 1.0-1.27% except k8's 3.75%) would make all five rows
above clear (four effects, k4 loop `unroll_count_2` harmful). That is a
different rule; whether to register it is the owner's call.

#### 171.4 jaq Oracle A2 (3.26%)

`artifacts/jaq-search/oracle-A2/rounds.jsonl`, aggregate ratios:

| round | mark | candidate | round | confirm | §139 (3%) | v2 (3.26%) |
|--:|---|---|--:|--:|---|---|
| 66 | `Val::hash` | `inline_always` | +4.26% | +4.84% | effect | effect |
| 7 | `Lex::seq` | `inline_never` | −9.39% | −5.74% | harmful | harmful |
| 26 | `write::write` | `inline_always` | −5.55% | −6.63% | harmful | harmful |
| 17 | `write_until` | `inline_never` | −3.75% | −3.22% | harmful | **flat** (confirm 0.04 pt under) |

Nothing on jaq lies between its v2 MDE and 3%; r17 leaves "harmful" (under
the 2.84% cross-check it would stay). The best arm's holdout aggregate
(+1.68%) and the combination (+0.17%) are under 3.26% as before.

#### 171.5 What is NOT established

* **Nothing here is pre-registered.** The v2 verdicts above are a post-hoc
  re-read; §168.7's "good: 0 of 67" and decision 100 (a)'s "後から呼び直さない"
  stand. No v2 verdict is a result until an arm is measured under a v2
  pre-registration.
* **The Jev-run headlines are not re-scored.** hintbench Exp4-6 and the
  jaq/zopfli Jev-vs-random runs were accepted and read under the v1 rule
  (per-batch MDE, 3% floor); their acceptances would differ under v2, and
  this section does not recompute them.
* **v2 changes acceptance for future runs, not only reading.** Under
  protocol v2 (`confirm_when = "mde"`, decision 104 (c)) a sub-MDE plan
  cannot be accepted; with v2's lower zopfli MDE a sub-3% plan now can.
* **Driver not yet able to run v2.** `scripts/jev_search.py` floors a frozen
  `--mde` at 0.03 (lines 3885, 4983; `--mde` help at 5628) and
  `scripts/bench.py` hardcodes `max(2 * worst, 0.03)` (line 350); a v2 run
  today silently gets 3%. The floor must become 0.01 (and the frozen per-target
  value must be passed) before any v2 pre-registration is run. No code was
  changed here.
* **Sampling variance weighs more at 1-2%.** Decision 94's caveat (the same
  binary moved 0.37-1.48 pt between runs) is of the same size as a 1-2%
  effect; for Jev-vs-random comparisons it is n ≥ 3 per arm (decision 96),
  not a single batch pair, that makes a 1-2% claim honest.
* **hintbench under protocol v2 needs the frozen value.** At n = 8 the
  per-batch MDE rises to a median 5.3% (§170.4); v2 runs there must pass
  `--mde 0.0318` (§162) so the freeze, not n, sets the bar (decision 104 (b)).
* The zopfli combination is **not** a confirmed α under v2 as written (round
  batch 0.027 pt short). It is confirmed under the sensitivity readings in
  171.2; which frozen `h` zopfli registers is the owner's choice.

### 172. MDE rule v2 final (aggregate A/A × 2, floor 1%) in the driver; toy verification

**The owner's decision (2026-09-24, "おすすめでなおして", decision 106).**
MDE rule v2 final: `MDE = max(2 × h, 1%)`, where `h` is the **aggregate
(geomean) 95% CI half-width of the A/A legs** of the target's registered A/A
panel on the measured case set (the worst over the panel's identical-binary
legs), frozen per target before the arms run. A **per-case** claim (e.g.
hintbench's own-kernel readout) uses `max(2 × that case's A/A half-width,
1%)`. Effect = round batch and confirmation batch both beyond the MDE on the
same side (decision 80 (a), §171). Decision 27's 3% policy floor is
withdrawn. This replaces §171's "worst per-case half-width" reading of `h`
for aggregate claims: the headline is an aggregate, so its MDE comes from the
aggregate A/A. Every verdict before this section stands as recorded (v1:
per-batch `max(2 × worst per-case half-width, 3%)`).

#### 172.1 The v2 MDE per target

Half-widths read from the panels' `stats.json`
(`aggregate.<leg>.halfwidth`, `per_workload.<leg>.<case>.halfwidth`; worst
over the A/A legs named), no new timing:

```
python3 -c "import json; d=json.load(open(P)); print({l: a['halfwidth'] for l, a in d['aggregate'].items()})"
```

| target / case set | registered A/A panel (legs) | aggregate A/A half-width | v2 MDE (aggregate) | per-case v2 MDEs |
|---|---|--:|--:|---|
| zopfli, training | §165 `artifacts/zopfli-sites/aa-training/stats.json` (aa 0.332%, aa2 0.414%) | 0.414% | 0.83% -> **1.00%** (floor) | text 1.00, binary 1.84, json 1.48% |
| zopfli, holdout | §165 `artifacts/zopfli-sites/aa-holdout/stats.json` (aa 0.154%, aa2 0.187%) | 0.187% | 0.37% -> **1.00%** (floor) | --- |
| hintbench (pinned, future runs) | §162 `artifacts/hintbench-aa-study/p6-pinned/stats.json` (aa 0.275%, cand = same binary 0.317%) | 0.317% | 0.63% -> **1.00%** (floor) | k1 1.58, k2 1.35, k3 2.24, k4 1.63, k5 1.70, k6 1.00, k7 2.53, k8 3.18% |
| hintbench (§118-128 oracle) | §119 null panels `artifacts/hintbench-oracle-nullpanel-{1,2}/stats.json` (n1-n3; 0.198-0.268%) | 0.268% | 0.54% -> **1.00%** (floor) | 1.00-1.27%, k8 3.75% (§171.3 side note) |
| jaq, Oracle A2 | §140 `artifacts/jaq-search/oracle-A2-holdout/stats.json` (aa) | 0.564% | **1.13%** | objsearch 3.27, strproc 1.13, readwrite 1.00% |
| jaq, cross-check | §164 `artifacts/jaq-aa-classes/stats.json` (c80/c112/c128 vs c96) | 0.707% (c128) | 1.41% | --- |

jaq is the one target the floor does not reach. Its within-batch half-width
is known to be over-confident (A2 in-run A/A: 28 of 60 intervals exclude 1,
sd 1.10%, §139; decision 80), so 1.13% is a lower bound on jaq's noise, not
an estimate of it.

For hintbench runs under protocol v2 the frozen values are
`--mde 0.01 --mde-case k1=0.0158,k2=0.0135,k3=0.0224,k4=0.0163,k5=0.0170,k6=0.0100,k7=0.0253,k8=0.0318`
(§162; the own-kernel readout uses `--mde-case`, the aggregate `--mde`).
This supersedes decision 104 (b)'s single `--mde 0.0318`.

#### 172.2 What now counts (post hoc, labelled)

**zopfli (training 1.00%, holdout 1.00%)**, numbers from §171.2
(`artifacts/zopfli-search/oracle/rounds.jsonl` `ratio`, `confirm.ratio`;
`holdout-panel/stats.json`):

| round | arm | round batch | confirm | holdout | v2 final |
|--:|---|--:|--:|--:|---|
| 68 | combination (`squeeze.rs:325` + `:563` `unroll_count_8`) | +1.811% | +2.063% | +1.77% [1.0163, 1.0193] | **effect** (all three clear 1.00%) |
| 37 | `squeeze.rs:325` `unroll_count_8` | +1.256% | +1.285% | +1.33% [1.0116, 1.0151] | **effect** (all three clear 1.00%) |

This is a reproducible +α of about +1.8% on top of O3 + native + fat LTO +
PGO on zopfli, **read post hoc**: the oracle was pre-registered under v1 (3%)
and §168.7's "good: 0 of 67" stands as the pre-registered verdict. On the
negative side the 1.00% reading makes 9 arms harmful (§171.2 sensitivity
list). A v2 pre-registration that re-measures these arms would remove the
post-hoc label.

**jaq (1.13%)**, re-read of `artifacts/jaq-search/oracle-A2/rounds.jsonl`
(`ratio`, `confirm.ratio`) at 1.128% with the same ad-hoc read-only script
as §171, post hoc: effects r66 `Val::hash inline_always` (+4.26 / +4.84%) and
r16 `write_until inline_always` (+1.53 / +2.15%); harmful r1 `read::parse
inline_always` (−2.59 / −2.62), r5 `read::parse align_64` (−1.44 / −1.51),
r7, r17, r26, r51 `Rc<IndexMap>::drop_slow inline_always` (−4.75 / −1.52).
Given the over-confident half-width above, these are the least trustworthy
of the three targets.

**hintbench**: the oracle's own-kernel arms are per-case claims; their
per-kernel re-read is §171.3's side note (post hoc). **The hintbench Jev
headlines (Exp4-6, +7.4-7.8%) are not re-scored** under v2; they stand under
v1 as recorded.

#### 172.3 The driver change

`scripts/bench.py stats` gains `--mde-floor` (default 0.01) and
`--mde-from aggregate|worst_case` (default `aggregate`). `stats.json` now
carries `mde` (the selected rule), `mde_aggregate`, `mde_worst_case`,
`mde_per_case`, `mde_h_labels` (the A/A labels `aa*`, or, in a batch without
an A/A leg, the non-base labels = the candidate's own spread),
`mde_halfwidth_aggregate`, `mde_rule` (`v2-aggregate` / `worst-case`),
`mde_from`, `mde_floor`. `scripts/jev_search.py` reads `[evaluation]
mde_floor` / `mde_from` / `mde_case` (flags `--mde-floor`, `--mde-from`,
`--mde-case`), passes them to every timed batch (round, confirmation,
holdout), floors a frozen `--mde` at `mde_floor` (was 0.03), uses the
per-case MDE for the own-kernel readout under `mde_from = aggregate`, and
records `mde_rule`, `mde_floor`, `mde_from` in each `rounds.jsonl` record,
`holdout.json` and the manifest's `protocol` block (plus `mde_per_case` per
batch, `confirm_mde_case` beside `confirm_mde`). The state text's `{mde}` is
now the frozen `mde` if set, else `mde_floor` ("1%"; it was always "3%"), so
Jev is shown a different number in new runs; the template is unchanged and
the manifest fields distinguish the runs. `jev-opt.toml` sets `mde_floor =
0.01`, `mde_from = "aggregate"` explicitly, so `config_sha256` changes from
this commit on. The report scripts (`hintbench_oracle_report.py`,
`hintbench_exp4_score.py`) read each round's recorded `mde` and are
unchanged (their 0.03 is a missing-value fallback). No recorded artifact was
altered.

#### 172.4 Toy verification

(1) `python3 -m py_compile scripts/jev_search.py scripts/bench.py`: OK.

(2) The old rule is reproduced bit for bit. Re-running `bench.py stats` on
recorded toy batches with their own seed and resamples:

```
python3 scripts/bench.py stats artifacts/toy-search/<run>/round-NN/samples.json --base base \
    --seed <stats.json seed> --resamples <stats.json resamples> \
    --mde-from worst_case --mde-floor 0.03 --json <scratch>
```

| batch | recorded `mde` | worst_case / 0.03 | equal | aggregate / 0.01 (h from) |
|---|--:|--:|---|---|
| `protocol-v2/round-02` (no A/A leg) | 0.034434 | 0.034434 | yes | 1.24% (cand 0.62%) |
| `protocol-v2/round-04` (no A/A leg) | 0.030000 | 0.030000 | yes | 1.00% (cand 0.42%) |
| `protocol-v1/round-02` (A/A leg) | 0.064413 | 0.064413 | yes | 1.00% (aa 0.34%) |

A stub check of `confirm_thresholds` (in-process, no timing): aggregate
threshold = max(rec `mde`, floor) (a frozen 0.005 becomes 0.01); the kernel
threshold is the frozen `mde_case[case]`, else the frozen `mde`, else the
batch's `mde_per_case[case]`; with `per_case = False` (mde_from worst_case)
and floor 0.03 both thresholds equal the old `max(mde, 0.03)`.

(3) One toy oracle run, protocol v2, MDE v2 defaults, reusing §170's
baseline:

```
export TARGET=toy
python3 scripts/jev_search.py --target toy --marks artifacts/plugin-day3/marks/toy-all.txt \
    --proposer oracle --oracle-phase A --vocab v6 --protocol v2 \
    --baseline-dir artifacts/toy-search/protocol-v2/baseline \
    --out artifacts/toy-search/mde-v2        # log: artifacts/toy-search/mde-v2-run.log
```

Manifest `protocol` block: `name v2, confirm_when mde, aa_leg_oracle_arms
false, reps 15, reps_oracle 8, mde null, mde_case null, mde_rule
v2-aggregate, mde_floor 0.01, mde_from aggregate, mde_source "per batch,
max(2 x aggregate A/A half-width, 1%)"`. Every round record carries
`mde_rule v2-aggregate, mde_floor 0.01, mde_from aggregate`. 7 rounds (4
no-op, not timed), correctness 7/7, wall 135.4 s.

| round | arm | ratio | 95% CI | batch MDE (v2) | same batch, old rule | confirm |
|--:|---|--:|---|--:|--:|---|
| 2 | `count_quotes inline_never` | 0.9981 | [0.9878, 1.0113] | 2.35% | 10.94% | none (sub-MDE) |
| 4 | `dot_f64 inline_never` | 0.9944 | [0.9875, 1.0022] | 1.47% | 4.91% | none |
| 6 | `find_special inline_never` | 0.9972 | [0.9887, 1.0057] | 1.69% | 5.35% | none |

All three batch MDEs are below 3% under the new rule (1.47-2.35%); the old
rule on the same samples gives 4.9-10.9% (the toy's `sum` case is noisy per
case at n = 8). Without an A/A leg (v2 oracle arms) the aggregate `h` is the
candidate's own spread, as the old rule's was.

#### 172.5 Caveats

* **Post hoc.** 172.2's effects are a re-read under a rule fixed after the
  numbers were known; the pre-registered verdicts (§139, §124, §168) stand.
* **A 1-2% claim needs n ≥ 3.** Decision 94's sampling variance (the same
  binary moved 0.37-1.48 pt between runs) is the size of a 1-2% effect; a
  Jev-vs-random comparison at 1-2% needs n ≥ 3 per arm (decision 96).
* **Not re-scored**: the hintbench Jev headlines (Exp4-6) and the jaq / zopfli
  Jev-vs-random runs keep their v1 reading.
* **Acceptance changes for future runs.** Under protocol v2 a plan is
  accepted only through a confirmation, which now fires at ≥ 1% on zopfli;
  sub-3% plans can be accepted where they could not before (decision 104
  (c)).

## Prompt study 2 (API only) --- can Jev find the loop truths, and pick fewer harmful hints?

### 173. Prompt study 2 (API only): can Jev find the loop truths? Pre-registration

Written 2026-09-24 before any request of this study was sent. API only: no
build, no timing, no cargo. Script: `scripts/jev_prompt_study2.py`
(`truth`, `render`, `run`, `score`); logs `artifacts/jev-prompt-study-2/`
(copies to `docs/experiments/jev-prompt-study-2/` at the end).

**Question.** Jev's one-shot answers found the function-attribute truths on
hintbench (decision 87: fn 7/8, including k2 `inline(always)` +67.8%) and none
of the loop truths (loop 0/4; zopfli `squeeze.rs:325 unroll_count_8` got P
0.02, decision 101). Does any uniform way of calling Jev (what facts the
state shows, how loop candidates are described, how the question is posed)
make Jev pick the loop truths, without breaking the function results?
Second goal (owner, added before any request; "phase 2" below): reduce the
probability Jev puts on arms the oracle measured harmful, with no side effect
on the truths.

#### 173.1 What the baseline request is (B0)

B0 is what the driver sends in round 1 today, reproduced with the driver's
own objects exactly as `scripts/jev_oneshot.py` does (`Search.run()` with
`--print-state` against the frozen baseline dump, then `questions_for()` /
`state_header()` / `state_section()`): vocabulary `v6-2026-09-23`, state
`state-v6.0-2026-09-23`, `--source-comments strip`, `--explore 0`,
`--pv-untried off`. Phase A = every function site in one Choice request;
phase B = every loop site in one Choice request, against the baseline dump,
with `function attributes this round already applied: none` (the one-shot
caveat of `jev_oneshot.py`: phase B is not asked against phase A's build).

| target | marks / sites / site set | baseline dir (reused, not rebuilt) | phases |
|---|---|---|---|
| hintbench | `targets/hintbench/jev-marks.txt`, `artifacts/hintbench-sites/sites.json`, `oracle.selected_keys_loop_hint_kernels` | `artifacts/hintbench-sites/baseline` | A (8 fn), B (4 loops) |
| zopfli | `targets/zopfli/jev-marks.txt`, `targets/zopfli/sites.json`, `oracle.selected_keys_top6` | `artifacts/zopfli-sites/baseline` | A (6 fn), B (5 loops) |
| jaq | `targets/jaq/jev-marks.txt`, `targets/jaq/sites.json`, `oracle.selected_keys_top3` | `artifacts/jaq-search/jev-r5/baseline` (Oracle A2's) | A (15 fn) only |

jaq loops are skipped: there is no jaq loop oracle (decision 103) and the
rendered phase-B state is 5.0 MB. There is no earlier v6 one-shot on any of
the three targets, so B0 measured here is the study's own regression
baseline; the absolute bar hintbench fn >= 7/8 (decision 87) applies too.

#### 173.2 Truth (mechanical, from the oracles' own records)

`scripts/jev_prompt_study2.py truth` -> `docs/experiments/jev-prompt-study-2/truth.json`.
Rule (decision 106, MDE v2 final): an arm is **good** if its round batch AND
its confirmation batch are both above `1 + MDE`, **harmful** if both are below
`1 - MDE`, **noop** if the build was identical to the baseline, else flat.
Truth best = the good arm with the highest `min(batch1, batch2)`, else
`KEEP_DEFAULT`. MDEs: hintbench per kernel (own-kernel readout, §162 / §172.1:
k1 1.58, k2 1.35, k3 2.24, k4 1.63, k5 1.70, k6 1.00, k7 2.53, k8 3.18%),
ratios from each round's `stats.json` / `confirm/stats.json`
`per_workload.cand.<k>`; zopfli training aggregate 1.00% (`rounds.jsonl`
`ratio`, `confirm.ratio`); jaq 1.13% (same fields; decision 106 notes 1.13%
is a lower bound on jaq's noise). Rows the task summary glossed, stated
explicitly: hintbench fn k4 `inline_never` 1.0152 < 1.63% -> KEEP; k3 loop
has two good arms (`unroll_count_2`, `unroll_count_4`); k5 loop `unroll_count_4`
/ `_8` do not clear 1.70% in both batches, so width 16 is the only good arm;
zopfli `squeeze.rs:325 unroll_count_2` (1.0095 / 1.0100) does not clear 1.00%;
zopfli has 9 harmful arms at 1.00% (not just `squeeze.rs:275` unroll 4/8);
jaq `reserve_rehash inline_always` (1.0104 / 1.0096) is not good,
`Rc<IndexMap>::drop_slow inline_always` (0.9525 / 0.9848) is harmful at
1.13%, `str_fold inline_never` (0.9861 / 0.9928) is not.

**hintbench**

| site | truth best | good (both batches > MDE) | harmful (both < -MDE) | noop arms |
|---|---|---|---|--:|
| `fn k1_step` | `KEEP_DEFAULT` | - | `inline_never` 0.955/0.957 | 4 |
| `fn k2_mix` | `inline_always` | `inline_always` 1.678/1.674 | - | 2 |
| `fn k3_fill_run` | `KEEP_DEFAULT` | - | `inline_never` 0.829/0.830 | 4 |
| `fn k4_count_bytes` | `KEEP_DEFAULT` | - | - | 4 |
| `fn k5_mul_reduce` | `KEEP_DEFAULT` | - | - | 4 |
| `fn k6_hot_loop` | `KEEP_DEFAULT` | - | - | 2 |
| `fn k7_error_path` | `KEEP_DEFAULT` | - | - | 4 |
| `fn k8_scale_add` | `KEEP_DEFAULT` | - | - | 4 |
| k3 loop `lib.rs:174` | `unroll_count_4` | `unroll_count_2` 1.042/1.039, `unroll_count_4` 1.044/1.042 | `unroll_disable` 0.706/0.707 | 8 |
| k4 loop `macros.rs:180` | `KEEP_DEFAULT` | - | `interleave_count_1` 0.730/0.728, `interleave_count_2` 0.940/0.939, `unroll_disable` 0.731/0.728, `vectorize_width_16` 0.579/0.579, `vectorize_width_2` 0.202/0.202, `vectorize_width_4` 0.674/0.669 | 1 |
| k5 loop `macros.rs:180` | `vectorize_width_16` | `vectorize_width_16` 1.026/1.028 | `interleave_count_1` 0.296/0.294, `interleave_count_2` 0.595/0.592, `unroll_disable` 0.294/0.294, `vectorize_width_2` 0.279/0.279, `vectorize_width_4` 0.557/0.558 | 1 |
| k8 loop `range.rs:1103` | `vectorize_width_16` | `vectorize_width_16` 1.088/1.075 | `interleave_count_1` 0.803/0.803, `interleave_count_2` 0.946/0.959, `unroll_disable` 0.823/0.849, `vectorize_width_2` 0.447/0.456, `vectorize_width_4` 0.917/0.941 | 1 |

**zopfli**

| site | truth best | good | harmful | noop arms |
|---|---|---|---|--:|
| `fn ZopfliHash::update` | `KEEP_DEFAULT` | - | - | 0 |
| `fn lz77::find_longest_match` | `KEEP_DEFAULT` | - | `inline_always` 0.980/0.980, `inline_never` 0.978/0.973 | 0 |
| `fn lz77::find_longest_match_loop` | `KEEP_DEFAULT` | - | - | 1 |
| `fn squeeze::get_best_lengths` | `KEEP_DEFAULT` | - | `inline_never` 0.980/0.978 | 1 |
| `fn squeeze::lz77_optimal` | `KEEP_DEFAULT` | - | `inline_always` 0.987/0.988 | 1 |
| `fn squeeze::lz77_optimal_run` | `KEEP_DEFAULT` | - | `inline_never` 0.978/0.982 | 1 |
| `index.rs:184` | `KEEP_DEFAULT` | - | - | 8 |
| `lz77.rs:530` | `KEEP_DEFAULT` | - | `unroll_count_2` 0.986/0.988 | 8 |
| `lz77.rs:563` | `KEEP_DEFAULT` | - | - | 2 |
| `squeeze.rs:275` | `KEEP_DEFAULT` | - | `unroll_count_2` 0.984/0.987, `unroll_count_4` 0.964/0.967, `unroll_count_8` 0.917/0.916 | 8 |
| `squeeze.rs:325` | `unroll_count_8` | `unroll_count_8` 1.013/1.013 | - | 8 |

**jaq** (function sites of Oracle A2; `align_*` arms are not in vocabulary v6
and are ignored)

| site | truth best | good | harmful | noop arms |
|---|---|---|---|--:|
| `Val::hash` | `inline_always` | `inline_always` 1.043/1.048 | - | 2 |
| `write_until` | `inline_always` | `inline_always` 1.015/1.022 | `inline_never` 0.962/0.968 | 1 |
| `read::parse` | `KEEP_DEFAULT` | - | `inline_always` 0.974/0.974 | 2 |
| `Lex::seq` | `KEEP_DEFAULT` | - | `inline_never` 0.906/0.943 | 4 |
| `write::write` | `KEEP_DEFAULT` | - | `inline_always` 0.944/0.934 | 2 |
| `Rc<IndexMap>::drop_slow` | `KEEP_DEFAULT` | - | `inline_always` 0.952/0.985 | 4 |
| the other 9 (`str_fold`, `TermId::run`, `base{closure#3}`, `Path::run{closure#0}`, `Adapter::write_str`, `reserve_rehash`, `base_run{closure#7}`, `path::run`, `String::fmt`) | `KEEP_DEFAULT` | - | - | 1-5 |

Positive-truth sites: hintbench fn k2; hintbench loops k3, k5, k8; zopfli loop
`squeeze.rs:325`; jaq fn `Val::hash`, `write_until`. The loop targets of this
study are **k3 `unroll_count_4`, k5 / k8 `vectorize_width_16`, zopfli 325
`unroll_count_8`**. Every other site's truth is `KEEP_DEFAULT`.

**Two state facts that already argue against loop truths** (read off the
rendered B0 state, before any answer): (i) the loop verdict line "element type
... one 256-bit vector register holds 8 of them, so the widest
`vectorize.width` in this list that fits one register is 8" is printed at
k5 (u32; truth width 16); (ii) at zopfli `squeeze.rs:325` the post-vectorize
line says the loop "is no longer in the program ... so a hint attached to it
has nothing left to act on", while the oracle measured `unroll_count_8` there
changing 1 symbol and +1.3%. The *fact* (not found by signature at
VectorizerEnd) is the plugin's; the *inference* is contradicted by
measurement. Recorded here as a state finding; the plugin is not changed.

#### 173.3 Metrics (per variant, per target, per repeat; then median of 3 and range)

For a Choice readout `P` is Jev's `probabilities` (a candidate missing from
the answer counts 0) and the pick is the argmax.

* **(a)** P on the truth best at each positive-truth site; also P on the good
  set (k3 has two good arms).
* **(b)** argmax hit rate. At a positive site: pick in the good set. At a
  KEEP site: pick == `KEEP_DEFAULT` (strict; this is the 7/8 of decision 87).
  A "no-op-equivalent" hit (pick is `KEEP_DEFAULT` or an arm the oracle built
  identical to the baseline) is reported beside it.
* **(c)** harmful mass: P summed over the site's harmful arms, averaged over
  the sites that have any; and the number of sites whose argmax is harmful.
* **(d)** KEEP rate at KEEP-truth sites: mean P(`KEEP_DEFAULT`), and the share
  of those sites whose argmax is `KEEP_DEFAULT`.
* **(e)** (phase 2) = (c), plus the same mass restricted to the arms the
  owner named: hintbench k4 loop `vectorize_width_16`, k5 loop
  `interleave_count_1`, k8 loop `interleave_count_1`, k1 fn `inline_never`,
  k4 and k8 loop `interleave_count_2`; zopfli `find_longest_match
  inline_always` and the other 4 harmful fn arms, `squeeze.rs:275
  unroll_count_4/8`; jaq `write_until inline_never`.
* Nondeterminism (decision 94): each variant is sent **3 times**, unchanged;
  the script records `request_sha256` so byte-identity across repeats is
  checked, and max |ΔP| / argmax flips between repeats are reported.

Non-Choice readouts, fixed now:

* **Score (L7)**: one Score question per (site, candidate), `KEEP_DEFAULT`
  included, 5 ordered levels (much slower > 5% / slower 1-5% / no measurable
  change within 1% / faster 1-5% / much faster > 5%). Pick = the candidate
  with the highest expected score (ties -> `KEEP_DEFAULT`). (a) is reported
  as the truth candidate's expected score and its P(faster or much faster),
  not as a Choice P; (c)/(d) are reported via picks only.
* **Two-step (L8)**: request 1 asks every site "is any hint from this list
  likely to make the program measurably faster?" (Choice `HINT` /
  `KEEP_DEFAULT`); request 2 asks every site (all of them, not selected by
  request 1, so no dependency) "suppose one hint will be applied: which?"
  over the non-KEEP candidates. Combined P(c) = P1(HINT) x P2(c),
  P(KEEP) = P1(KEEP); pick = argmax of the combined P.
* **Inverse (L9)**: "which hint is most likely to make the program SLOWER?"
  over the non-KEEP candidates. Reported: P_harm mass on oracle-harmful arms
  (vs the harmful share of the list, the chance level), and the complement
  pick = argmin P_harm (vocabulary order breaks ties; never KEEP, so (b) at
  KEEP sites is 0 by construction and is not a finding).

#### 173.4 Variants (each one change from B0; uniform across sites)

Phase 1:

| id | change | phases sent |
|---|---|---|
| B0 | baseline (173.1) | A, B |
| L1 | loop candidate texts rewritten ("v7 candidate"): what each hint makes LLVM do, one "helps where" and one "hurts where" sentence each, the same text for every value N of a kind | B |
| L2 | loop verdict block replaced by short labelled raw facts (trip, body, calls, fp reduction, depth, element type, post-vectorize vectorized / VF / IC or "not found", verbatim leaf remarks or "shared by N loops"), no inferential clause | B |
| L3 | loop verdict block with only the lane-count conclusion removed (element type kept) | B |
| L4 | the post-vectorize "no longer in the program ... nothing left to act on" line replaced by a neutral "not found by its signature; this does not establish whether a hint has anything to act on" | B |
| L5 | loop verdict block + the unroller's own baseline outcome at the leaf location (factor N / no unroll remark / UNKNOWN if shared) + unroll arithmetic for factors 2/4/8 from the trip count | B |
| L6 | the leaf-location remarks (loops) / the callee-matched inline remarks (fn) copied verbatim into the question, next to the options | A, B |
| L7 | Score per (site, candidate) (173.3) | A, B |
| L8 | two-step (173.3) | A, B |
| L9 | inverse framing (173.3) | A, B |
| L10 | one request per site (same header, one section, one question) | A, B |
| L11 | candidates in one fixed random order (seed 20260924; the same permutation at every site of a kind) | A, B |
| L12 | "No hint has been measured at this site in this run ..." line in every question | A, B |
| L13 | source excerpts dropped from the state (replaced by "(source excerpt omitted from this request)") | A, B |

A variant that changes phase B only sends nothing for phase A; its function
half is B0's answers by construction (the transform does not touch phase A).
L3, L4 and L5 are the agent's own additions, suggested by the rendered B0
state (173.2), not by any Jev answer.

Phase 2 (false positives), registered now, sent after phase 1:

| id | change | phases |
|---|---|---|
| H1 | each non-KEEP candidate description gets one appended sentence "Known ways it hurts, stated the same at every site: ..." (per hint kind: unroll count, unroll disable, width, interleave count, inline always, inline never) | A, B |
| H2 | explicit fact lines appended to the question: fn = baseline inlining of the function from the callee-matched inline remarks ("inlined at all N call sites, so `inline_always` asks for what the baseline already does ..."), loop = LLVM's chosen VF x IC and what a lower / higher width or count changes, register arithmetic when the element type is known, or "LLVM did not vectorize this loop, so there is no width or interleave count to change" | A, B |
| H3 | KEEP-first question wording: "Answer KEEP_DEFAULT unless a fact ... says that a hint from the list will make the program measurably faster" | A, B |
| H4 | inverse veto, readout only (no new request): P'(c) proportional to P_B0(c) x (1 - P_L9(c)) for non-KEEP c, P'(KEEP) = P_B0(KEEP), renormalised; pairs B0 and L9 by repeat index | A, B |
| H5 | = L8's two-step, re-read for (e) (no new request) | A, B |
| C1 | best phase-1 loop variant composed with the best phase-2 variant (question-level transforms compose in order; at most one structural shape), sent x3 | A, B |

Selection rules for C1, fixed now: best phase-1 loop variant = the highest
median (over repeats) of the summed P(truth best) over the 4 loop targets
(Choice-readout variants only) among those that pass the fn bar (173.5);
best phase-2 variant = the lowest median (e) among H1-H5 that passes the
side-effect bar (173.5). If none passes, C1 is not sent and that is reported.

Disclosure. Every variant text was written by an agent that had read the
oracle. The texts name no site, kernel, file or measured number; a mechanical
check (`jev_prompt_study2.py leak`: regex over every static variant text for
`k1`-`k8`, target / crate / file names, `325`/`275`/`563`/`530`/`184`, the
truth percentages) must print `clean` and is written into every run log.
Rendered facts (trip counts, VF, remark text) come from the dump by the same
rule at every site.

#### 173.5 Decision rules (fixed before any answer)

* A variant **moves** a loop truth if its median P(truth best) at that site
  exceeds B0's maximum over the 3 repeats and the two ranges do not overlap
  (decision 96). It **finds** it if the argmax hits in >= 2 of 3 repeats.
* **fn bar** (phase 1 regression): hintbench fn strict argmax hits, median
  >= 7/8, and k2 `inline_always` argmax in >= 2/3; jaq fn hits median >= B0's
  median and jaq harmful argmax count median <= B0's median.
* **Phase-2 bar** (false positives down, truths not): (e) median below B0's
  minimum with non-overlapping ranges on at least one target, and on every
  target: hintbench fn hits median >= 7/8, k2 still argmax, P(k3
  `unroll_count_4`) and P(k8 `vectorize_width_16`) medians not below B0's
  (and not below the phase-1 best variant's, for C1), zopfli KEEP-truth
  sites' argmax-KEEP rate not below B0's median, jaq P(`Val::hash`
  `inline_always`) and P(`write_until` `inline_always`) medians not below
  B0's.
* A v7 proposal is written to HANDOFF §4 only if a variant passes both the
  "finds >= 1 loop target" rule with the fn bar, or the phase-2 bar; nothing
  is frozen by this study either way (owner decides).

#### 173.6 Requests, cost, 503 policy

Requests per repeat (from `build_requests`): hintbench 41, zopfli 40, jaq 27
(B0 2/2/1; L1-L5 1 each on hintbench and zopfli; L6/L7/L9/L11/L12/L13 2/2/1;
L8 4/4/2; L10 12/11/15; H1-H3 2/2/1). x 3 repeats = **324 requests**, plus
C1 (at most 3 x 38) and **one smoke request per target** (the first request
of B0 phase A, logged under run prefix `ps2smoke`, excluded from scoring) to
check the wire format. Largest request: the L7 Score request (78 questions
on zopfli B). Cost expected $0 (free tier; `[jev] api_cost_budget_usd` 5.0).
503 policy = `jev-opt.toml [jev]` as the driver uses it: up to 200 attempts
per request within a 600 s wall budget, a fixed 2.0 s pause between attempts
(jitter set to 0 in this script, `S.RETRY_JITTER = 0.0`), then up to 2
unchanged re-sends after 10 s; a request that never lands is recorded as
lost and its site's answers count as missing (not as KEEP). Every request and
response is logged as JSONL plus one `.log` line (latency, tokens, cost);
the Authorization header is never logged.

#### 173.7 Deviations registered during sending (before the affected requests)

Written 2026-09-24 15:30 JST, after 9 hintbench and 10 zopfli phase-1
requests of repeat 1 had landed and before any further request.

1. **Concurrency.** The first launch (one process, targets in series) was
   stopped after 10 hintbench requests to run the targets in parallel; its
   JSONL is kept as `aborted-ps2-hintbench.jsonl` and is **not scored**
   (the scored repeats all come from the relaunch). Running three targets at
   once brought HTTP 429s; jaq was stopped (1 landed + 1 lost request,
   kept as `aborted-ps2-jaq.*`, not scored) and is re-run after hintbench,
   so at most two targets send at a time.
2. **Score (L7) requests are split.** The whole-phase Score requests are
   62-160 KB (every (site, candidate) question carries the site's verdict
   block). hintbench L7.A (98.7 KB) failed 3 sends of 91-116 attempts each
   (503/429) and zopfli L7.B (60 questions) was exhausting too; zopfli L7.A
   (18 questions) landed whole. From now on an L7 request is split into
   chunks of at most 60 000 bytes that share the **same state** and carry
   the same questions (tags `A.c0`, `A.c1`, ...). Questions in one request
   are answered independently (`docs/jev-samples/README.md`), so the
   questions asked do not change; only their grouping does. zopfli repeat
   1's whole L7.A is superseded by its chunked re-send and not scored.
3. **Resume.** `run --resume` skips a (repeat, variant, tag) request that
   already landed in the target's JSONL, so the relaunch does not re-ask
   what was answered; exhausted lines stay in the JSONL and are not scored.
4. **jaq sites are batched** (registered 17:25 JST, before any scored jaq
   request). The relaunched jaq run landed B0 repeat 1 (119 KB) after 52
   attempts and lost L6 (126 KB) after 142 attempts in 600 s; at that rate
   jaq alone would take many hours and lose requests. Its JSONL is kept as
   `aborted2-ps2-jaq.*` and is **not scored**. Every jaq request of every
   variant (B0 included) is now sent in site batches of at most 40 000
   state characters, cut by the same rule as the driver's own `_batches`
   (SPEC.ja.md 6: "split only when the state would be too large"): 3
   batches of 5 / 8 / 2 function sites, each with the full state header.
   L10 (one site per request) is unchanged. hintbench and zopfli are not
   batched (their phase states are 22-54 KB and landed).

### 174. Prompt study 2: results

Rules: §173 (unchanged) plus the §173.7 deviations. All numbers from:

```
scripts/jev_prompt_study2.py run --resume --targets <t> --variants B0 L1 ... L13 --repeats 3 --run-prefix ps2
scripts/jev_prompt_study2.py run --resume --targets <t> --variants H1 H2 H3 --repeats 3 --run-prefix ps2
scripts/jev_prompt_study2.py report  --out artifacts/jev-prompt-study-2/report.md
scripts/jev_prompt_study2.py stability
scripts/jev_prompt_study2.py gateway artifacts/jev-prompt-study-2/*.jsonl
```

Logs (gzip) and the full report: `docs/experiments/jev-prompt-study-2/`
(`ps2-<target>.jsonl.gz`, `.log`, `report.md`, `truth.json`). Cells are
median [min, max] over the 3 repeats. "P(best)" is Jev's Choice probability
on the truth-best arm, **except** L7 (expected Score level, 0 = much slower,
2 = no change, 4 = much faster) and L9 (P that the truth-best arm is the
MOST HARMFUL hint). "harm" = P mass on oracle-harmful arms, averaged over the
sites that have any. Loop-only variants (L1-L5) send nothing in phase A; their
function half is B0 by construction and is not repeated below.

#### 174.1 Loops

**hintbench** (truth: k3 `unroll_count_4` (good set {2, 4}), k5 / k8
`vectorize_width_16`, k4 KEEP)

| variant | P(best) k3 | P(best) k5 | P(best) k8 | argmax hits /4 | harm | harm argmax /4 |
|---|---|---|---|---|---|---|
| B0 | 0.14 [0.14, 0.17] | 0.00 | 0.00 | 1 (k4 KEEP) | 0.12 | 0 |
| L1 v7 texts | 0.12 [0.12, 0.14] | 0.01 [0.01, 0.01] | 0.03 [0.02, 0.04] | 1 [0, 1] | 0.19 | 0 [0, 1] |
| L2 raw facts | 0.06 | 0.00 | 0.00 | 1 [0, 1] | 0.25 | 0 [0, 1] |
| L3 no lane line | 0.13 | 0.00 | 0.00 | 1 | 0.07 | 0 |
| L4 neutral not-found | 0.15 | 0.00 | 0.00 | 1 | 0.14 | 0 |
| L5 unroll facts | 0.11 | 0.00 | 0.00 | 1 | 0.15 | 0 |
| L6 remarks in question | 0.08 | 0.00 | 0.00 | 1 | 0.13 | 0 |
| L7 Score | 1.97 | 1.69 | 1.84 | 0 | - | 1 [1, 2] |
| L8 two-step | 0.01 | 0.00 | 0.00 | 1 | 0.01 | 0 |
| L9 inverse (P harmful) | 0.04 | 0.28 | 0.26 | 0 | 0.51 | 0 |
| L10 per site | 0.14 [0.11, 0.14] | 0.00 | 0.00 | 1 [0, 1] | 0.13 | 0 [0, 1] |
| L11 random order | 0.19 [0.17, 0.22] | 0.00 | 0.01 | 0 [0, 1] | 0.15 | 1 [0, 1] |
| L12 no-hint-measured | 0.14 | 0.00 | 0.00 | 1 | 0.14 | 0 |
| L13 no source | 0.15 [0.14, 0.18] | 0.00 | 0.00 | 0 [0, 1] | 0.16 | 1 [0, 1] |

**zopfli** (truth: `squeeze.rs:325` `unroll_count_8`; the other 4 loops KEEP)

| variant | P(best) 325 | argmax hits /5 | harm | harm argmax /2 | KEEP argmax at KEEP sites /4 |
|---|---|---|---|---|---|
| B0 | 0.00 | 4 | 0.22 | 0 | 4 |
| L1 | 0.05 [0.05, 0.06] | 4 | 0.08 | 0 | 4 |
| L2 | 0.01 [0.01, 0.02] | 4 | 0.13 | 0 | 4 |
| L3 | 0.00 | 4 | 0.24 | 0 | 4 |
| L4 | 0.01 | 4 | 0.21 | 0 | 4 |
| L5 | 0.01 | 4 | 0.25 | 0 | 4 |
| L6 | 0.00 | 4 | 0.13 | 0 | 4 |
| L7 (score) | 1.98 | 0 [0, 1] | - | 0 [0, 1] | 0 [0, 1] |
| L8 | 0.00 | 4 | 0.01 | 0 | 4 |
| L9 (P harmful) | 0.52 [0.43, 0.54] | 0 | 0.36 | 0 | 0 |
| L10 / L11 / L12 / L13 | 0.00 | 4 | 0.17 / 0.21 / 0.20 / 0.24 | 0 | 4 |

The 4 hits are the 4 KEEP-truth loops; `squeeze.rs:325` is KEEP_DEFAULT in
every repeat of every Choice variant.

**Pre-registered readings (173.5).** *Finds* (argmax hit >= 2/3) any loop
target: **no variant, at any of the 4 targets** (k3, k5, k8, zopfli 325).
*Moves* (median above B0's max, ranges disjoint): L1 at k5 (0.01 vs 0.00),
k8 (0.03 vs 0.00) and zopfli 325 (0.05 vs 0.00); L2 at 325 (0.01); L4 and L5
at 325 (0.01). Every "move" leaves P <= 0.05. L11 at k3 (0.19 [0.17, 0.22])
touches B0's max 0.17 and does not count. **Nothing moves a loop truth to a
pick.** L3 (lane line removed) did not raise k5 width 16 (0.00) and L4 (the
contradicted "nothing left to act on" inference replaced) did not raise 325
(0.01): the two suspect state facts of 173.2 are not what holds the loop
truths down.

What Jev believes about the truth arms, read from the non-Choice framings:
the inverse question gives the truth arm P(most harmful) 0.28 (k5 width 16),
0.26 (k8 width 16) and 0.52 (325 `unroll_count_8`, the top harm pick there);
the Score question puts them at 1.69-1.98 on the 0-4 scale, i.e. "no change"
to "slower". Jev does not rank these hints low by accident of wording: it
expects them to hurt.

#### 174.2 Functions (regression bar)

| target | variant | P(best) | strict argmax hits | harm | harm argmax | KEEP argmax at KEEP sites |
|---|---|---|---|---|---|---|
| hintbench | B0 | k2 0.66 [0.66, 0.68] | 7/8 (k6 `inline_always`, flat) | 0.03 | 0/2 | 6/7 |
| hintbench | L6, L10, L11, L12, L13 | k2 0.60-0.64 | 7/8 each | 0.02-0.04 | 0 | 6/7 |
| hintbench | L7 Score | k2 1.99 (no change) | 6 [5, 6]/8 | - | 0 | 6 [5, 6]/7 |
| hintbench | L8 two-step | k2 0.15 | 7/8 (k2 lost, k6 fixed) | 0.03 | 0 | 7/7 |
| hintbench | L9 inverse | - | 0/8 by construction | - | - | - |
| zopfli | B0 | - | 3 [3, 4]/6 | 0.23 | 1 [0, 1]/4 | 3 [3, 4]/6 |
| zopfli | L7 / L8 / L10 | - | 5 / 6 / 5 | - / 0.06 / 0.18 | 0 | 5 / 6 / 5 |
| zopfli | L6, L11, L12, L13 | - | 3-4 | 0.24-0.26 | 1 | 3-4 |
| jaq | B0 | Val::hash 0.08, write_until 0.76 | 13/15 (`write_until` found; `Val::hash` KEEP; `Adapter::write_str` `inline_always`, flat) | 0.08 | 0/5 | 12/13 |
| jaq | L6, L11, L12, L13 | write_until 0.64-0.82 | 13 each (L11 [12, 14]) | 0.08-0.13 | 0 | 12 |
| jaq | L10 per site | write_until 0.63 | 10 [9, 10] | 0.16 | 0 | 9 [8, 9] |
| jaq | L7 Score | write_until 1.97 | 11 | - | 0 | 11 |
| jaq | L8 two-step | write_until 0.30 | 13 (write_until lost) | 0.03 | 0 | 13/13 |

fn bar (hintbench >= 7/8 and k2 argmax >= 2/3; jaq hits >= B0 and harm
argmax <= B0): **passed** by L6, L10 (fails jaq: 10 < 13), L11, L12, L13 and,
trivially, L1-L5; **failed** by L7 (hintbench 6/8, k2 lost), L8 (k2 lost 3/3)
and L9 (by construction). B0 itself reproduces decision 87's function result
on v6: 7/8, k2 found, k6 the one miss, 3/3 repeats.

Loop harmful picks under B0 are already **0/4 on hintbench and 0/2 on
zopfli** in all repeats (decision 87's k4 width 16 at P 0.85 was v4; under v6
with the post-vectorize facts it is gone).

#### 174.3 Stability and the gateway

Every repeated request was byte-identical across its 3 repeats
(`stability`: all request groups `byte-identical 3/3`). max |dP| between
repeats per variant 0.04-0.18 (zopfli L6 0.18); Choice argmax flips 0-2 per
variant over all its questions. Readings above use medians, so single flips
do not decide any row.

| JSONL | requests | landed | lost | HTTP attempts | 503 | 429 | seconds waiting | tokens in / out | cost |
|---|--:|--:|--:|--:|--:|--:|--:|---|--:|
| ps2-hintbench | 146 | 144 | 2 (L7.A whole, before 173.7(2)) | 1609 | 1389 | 76 | 5174 | 2 090 850 / 44 809 | $0 |
| ps2-zopfli | 140 | 139 | 1 (L7.B whole, before 173.7(2)) | 1535 | 1324 | 71 | 4871 | 1 934 778 / 49 753 | $0 |
| ps2-jaq | 162 | 162 | 0 | 940 | 778 | 0 | 1556 | 1 899 357 / 24 314 | $0 |
| aborted (not scored) + smoke | 17 | 15 | 2 | 543 | 515 | 13 | 1443 | - | $0 |

Total **465 requests** (448 scored-run + 17 aborted/smoke), 4 lost, all
before the deviation that fixed their cause; **no scored cell has a missing
site**. Cost $0 (free tier). Wall clock 14:37-18:09 JST.

#### 174.4 Verdict (phase 1)

**No way of calling Jev tried here makes it pick a loop truth.** Across 14
uniform variants x 3 repeats, k3 `unroll_count_4`, k5 / k8
`vectorize_width_16` and zopfli `squeeze.rs:325 unroll_count_8` are never the
argmax; the best P on any of them is 0.19 (k3, L11, not separable from B0)
and <= 0.05 on the other three. The v7 candidate texts (L1) move P by
0.01-0.05 in the right direction and nothing more. The inverse and Score
framings show why: Jev expects the truth arms to be neutral or harmful. The
function half is robust to wording (5 variants keep 7/8 and k2), and loses k2
exactly when the framing pushes toward KEEP (two-step, Score). **v7 is not
proposed for freezing.**

### 175. Phase 2: false positives

Rules: §173.3 (e), §173.4 phase 2, §173.5 phase-2 bar. H4 and H5 are
readouts of phase-1 requests (B0 x L9, L8); H1-H3 were sent x 3.

**Harmful mass (e) down vs truths kept, one table per target** (median [range]):

| target | variant | harm (all harmful arms) | named-FP mass | truth kept? |
|---|---|---|---|---|
| hintbench fn | B0 | 0.03 | 0.03 | k2 argmax 3/3 (P 0.66), hits 7/8 |
| hintbench fn | H1 hurts-when texts | 0.01 | 0.01 | **k2 lost 3/3** (P 0.23); k6 fixed; 7/8 |
| hintbench fn | H2 fact lines | 0.01 | 0.02 | **k2 lost 3/3** (P 0.38) |
| hintbench fn | H3 KEEP-first | 0.01 | 0.00 | **k2 lost 3/3** (P 0.15) |
| hintbench fn | H4 inverse veto | 0.00 | 0.00 | **k2 lost 3/3** (P 0.42) |
| hintbench fn | H5 two-step | 0.03 | 0.01 | **k2 lost 3/3** (P 0.15) |
| hintbench loops | B0 | 0.12 [0.12, 0.13] | 0.38 [0.38, 0.40] | P k3 0.14, k8 0.00 |
| hintbench loops | H1 | 0.10 [0.09, 0.11] | 0.33 [0.27, 0.36] | k3 0.10 (lower) |
| hintbench loops | H2 | 0.14 | 0.45 | k3 0.16, k8 0.01 |
| hintbench loops | H3 | **0.02 [0.02, 0.04]** | **0.06 [0.06, 0.11]** | k3 **0.03** (lower) |
| hintbench loops | H4 | 0.12 | 0.36 | k3 0.14 |
| hintbench loops | H5 | **0.01** | **0.03** | k3 **0.01** (lower) |
| zopfli fn | B0 | 0.23 [0.22, 0.23] | 0.90 [0.89, 0.91] | KEEP argmax 3 [3, 4]/6, harm argmax 1 [0, 1]/4 |
| zopfli fn | H1 | **0.14** | 0.57 | KEEP 6/6, harm argmax 0 |
| zopfli fn | H2 | 0.15 | 0.59 | KEEP 5 [5, 6]/6, harm argmax 0 |
| zopfli fn | H3 | **0.08** | 0.33 | KEEP 6/6, harm argmax 0 |
| zopfli fn | H4 | 0.14 | 0.54 | KEEP 6 [5, 6]/6 |
| zopfli fn | H5 | **0.06** | 0.24 | KEEP 6/6 |
| zopfli loops | B0 | 0.22 | 0.19 | KEEP 4/4; P 325 0.00 |
| zopfli loops | H1 / H2 / H3 / H4 / H5 | 0.13 / 0.20 / **0.02** / 0.22 / **0.01** | 0.01 / 0.21 / 0.02 / 0.18 / 0.01 | KEEP 4/4 in all; P 325 0.00 in all |
| jaq fn | B0 | 0.08 | 0.02 | write_until argmax 3/3 (P 0.76), hits 13/15 |
| jaq fn | H1 | 0.08 | 0.07 | **write_until lost 3/3** (P 0.32); 13/15 |
| jaq fn | H2 | 0.08 | 0.04 | **write_until lost 3/3** (P 0.38); 12/15 |
| jaq fn | H3 | 0.03 | 0.02 | **write_until lost 3/3** (P 0.29) |
| jaq fn | H4 | 0.02 | 0.02 | write_until kept 3/3 (P 0.55), **Val::hash P 0.08 -> 0.01** |
| jaq fn | H5 | 0.03 | 0.02 | **write_until lost 3/3** (P 0.30) |

**Pre-registered reading (173.5).** (e) falls below B0's range on at least
one target for H1, H3, H4 and H5 (zopfli fn 0.23 -> 0.06-0.14; hintbench
loops 0.12 -> 0.01-0.02 for H3/H5). But **every phase-2 variant fails the
side-effect bar**: all five turn hintbench k2 `inline(always)` (+67.8%, the
largest confirmed effect in the project) into KEEP in 3/3 repeats; H1, H2,
H3 and H5 also lose jaq `write_until inline_always` 3/3; H4 keeps it but drops
`Val::hash` from 0.08 to 0.01; H3 and H5 cut k3 `unroll_count_4` from 0.14 to
0.01-0.03. Hence, by the rule fixed before the answers, **C1 (best loop
variant + best phase-2 variant) was not sent**: no phase-2 variant qualified.

Why, in one line: at hintbench k2 and k6 the state says the same thing (the
baseline declines to inline; one gains +67.8%, the other is flat), and at
zopfli `find_longest_match` it says the same again (harmful). A uniform
change that makes Jev more cautious moves all of these together; none of the
wording, fact lines or veto readouts gives Jev something that separates the
true positive from the false ones. The false positives that remain under B0
are few already (loop harmful argmax 0 on both targets; fn harmful argmax
1 [0, 1] of 4 on zopfli, 0 on hintbench and jaq), and the ones left cannot be
removed by wording without removing the true ones.

**Verdict (phase 2):** false positives can be cut 2-10x in probability mass by
a KEEP-first wording or the two-step ask, **but only by losing the function
truths** (k2, `write_until`). No variant passes both bars; nothing is
proposed for freezing. Under B0 the per-round speed gate remains what stops
the residual false positives (decision 101).

#### 174.5 Addendum (same session, before hand-off): three pre-registered items and one correction

* **Correction to 174.2**: L10 is listed among the variants that pass the fn
  bar and, in the same parenthesis, as failing jaq (10 < 13). It **fails**
  the fn bar (jaq hits 10 [9, 10] < B0's 13). The passing set is L6, L11,
  L12, L13 (and L1-L5 by construction).
* **(a) P on the good set at k3** (`unroll_count_2` + `unroll_count_4`,
  the only site where it differs from P(best)): B0 0.30 [0.27, 0.33]; L13
  0.35 [0.34, 0.39] (disjoint from B0, so it *moves* by the 173.5 rule), L5
  0.35 [0.31, 0.35], L11 0.32 [0.28, 0.33], L3 0.30, L4 0.29, H2 0.29, L10 /
  L12 / H1 0.25, L1 0.18, L6 0.17, L2 0.15, H3 0.05, L8 0.01. The argmax at
  k3 stays `KEEP_DEFAULT` in every repeat of every Choice variant, so no
  finding changes.
* **(b) no-op-equivalent hits** equal the strict hits for every Choice
  variant on every target (no Choice argmax ever landed on an arm the oracle
  built identical to the baseline); they differ only for L7 Score (zopfli
  loops 2-3/5 vs 0-1/5, jaq 12 vs 11, hintbench fn 6 vs 5-6).
* **Score framing is worse on (c), not only on (a)**: L7 is the only framing
  with harmful argmax picks on loops (hintbench 1 [1, 2]/4, zopfli
  0 [0, 1]/2); every Choice variant has 0 there except the single-repeat
  flips of L1/L2/L10/L11/L13 on hintbench (0 [0, 1]/4).
* **Deviation 173.7(4) did not move the jaq baseline**: the three
  *unbatched* jaq B0.A requests that landed before it (the smoke request and
  one in each aborted run; not scored) give the same argmax as batched B0
  repeat 1 at **15/15** sites each, max |ΔP| 0.12-0.15, `write_until
  inline_always` P 0.70-0.78 (batched 0.77), `Val::hash` KEEP with
  P(`inline_always`) 0.13-0.15 (batched 0.11).
* `truth.json` still lists jaq `read::parse` `align_64` as harmful (an
  Oracle A2 v4 arm). v6 has no `align_*` candidates, so it never receives
  probability and does not enter any number above.

### 176. Marks study (API only): can Jev choose the marks from perf? Pre-registration

Written 2026-09-24 before any request of this study was sent. API only: no
build, no timing, no cargo, no binary run (the only local work is reading
the perf tables and perf.data already on disk and `nm -S` / `objcopy` on the
profiled binaries). Script: `scripts/jev_marks_study.py` (`build`, `render`,
`run`, `score`); logs `artifacts/jev-marks-study/` (copied gzip'd to
`docs/experiments/jev-marks-study/` at the end).

**Question (owner, 2026-09-24).** The marks (where jev-opt works) are chosen
today by Claude from perf tables (jaq "Marks (jaq)" 80-86, zopfli 166 and
`targets/zopfli/jev-marks.rationale.md`). Can Jev do that step from the
profile data alone, with no hand-written logic, so the pipeline has no
manual point? Reference = Claude's marks; truth = where the oracles found
an effect.

#### 176.1 Inputs, uniform per function

| target | table (on disk) | binary (`.text` sha256 checked) | listed | N (Claude's marks) |
|---|---|---|--:|--:|
| jaq | `artifacts/jaq-marks/perf-{self,inline}.tsv` (the tables "Marks (jaq)" 82-85 cite; one recording of all six workloads; the perf.data files were not kept, 86) | `target-jaq-pgo-use/.../jaq` `642dd55e…` | 124 | 15 |
| zopfli | `artifacts/zopfli-marks/perf-{self,inline}-{train,hold}.tsv` (+ the six `*.data` for union coverage) | `target-zopfli-sites-base/.../zopfli` `9aca86fc…` | 26 | 6 |
| hintbench | none: 8 kernels, 12.5% each by construction (`targets/hintbench/jev-marks.txt` header) | `target-hintbench-pgo-use/.../hintbench` `df5968bc…` | 8 | 8 |

* **One row per row of the inline table** (one source function, generic
  instantiations and closures are separate rows, as `perf_hotness.py`
  writes them). No merging, no crate filter, no entry-glue skip (none of
  `main` / `lang_start` reaches the floor on either target).
* **List floor** (mechanical, for request size): a row is listed if its
  reach is >= 1.0% in the training or the holdout set. This keeps every
  one of Claude's marks and every oracle-positive function on both targets
  (checked by `build`: `missing none`), so overlap is not capped by
  construction. jaq 124 rows listed (1553 below the floor), zopfli 26 (459).
* **Excluded**: rows in C (`lang c` in the self table, or a name without
  `::` / `<`: jaq's 14 mimalloc rows at >= 1%), because a plugin has no IR
  to put a hint on (86). Said in the state in one sentence.
* **Fields** (the same sentence for every row): id (`F001`... in
  alphabetical order of the name, not by hotness), demangled name (cut at
  300 characters with `…`, uniform), self % training / holdout, reach %
  training / holdout, own symbol yes/no (`nm -C` of the profiled binary has
  a text symbol of exactly that name), size (bytes of those symbols, `-` if
  none). **Call counts: not given** (no call graphs on this machine,
  decision 59), stated in the state. jaq's training / holdout values are the
  equal-weight means of the three per-case columns (its table has one
  aggregate over all six workloads); zopfli's are the tables' own
  summed-period aggregates per set. hintbench: reach 12.5% in both sets,
  self `-` ("not measured"), own symbol and size from `nm` (only `k2_mix`
  and `k6_hot_loop` have one).
* **Not in the state**: Stage 0, oracle, sites, candidates, Claude's marks,
  N, any hint name, any measured speed. The state header says what the
  program is (Rust, opt-level 3, native, fat LTO, 1 CGU, PGO), that a hint is
  a function attribute or loop metadata, how the profile was taken and what
  the columns mean. `leak_check()` greps the rendered state and questions
  (with the function names blanked) for hint names, oracle / Stage 0 /
  Claude / marks-file words and `+digit`; all three targets are clean
  before sending.

#### 176.2 Questions (fixed texts, identical for every function)

* **Q1** (Choice, one question per listed function): "Function {id} of the
  table in the state (`{name}`). Decide whether to mark it. A marked
  function is one where a compiler hint (function attribute or loop
  metadata on its loops) could plausibly change the program's speed;
  unmarked functions are never touched." Options `mark` / `skip`.
* **Q2** (Score, one question per listed function, 5 ordered levels "Very
  unlikely" ... "Very likely"): "... How likely is a hint on this function
  to change the program's speed? A hint is a compiler hint on this
  function: a function attribute, or loop metadata on its loops." Read out
  as the API's probability-weighted `score`.
* The state is the whole table; the questions are split into chunks so each
  request body is <= 60 000 bytes (the study-2 size at which requests
  landed, 174 deviation), every chunk carrying the same full state. Plan:
  jaq Q1 3 chunks, Q2 3 chunks; zopfli and hintbench 1 each. **Each request
  is sent 3 times** (decision 94): 3 x (6 + 2 + 2) = **30 requests**.
  Retry policy and logging are `jev_search.JevClient` (as study 2: 200
  attempts / 600 s per request, fixed 2 s pause, up to 2 re-sends).

#### 176.3 Readouts (per repeat; then median over the 3 repeats)

* **Jev Q1** = {functions with P(mark) > 0.5} (its size M is Jev's; it is
  not forced to N). Secondary: **Q1-top** = top N by P(mark).
* **Jev Q2** = top N by Score. Ties (both readouts) are broken by list
  order (alphabetical), never by hotness.
* Also reported: the sets from the per-function median over the 3 repeats
  (median P > 0.5; top N by median Score), and the per-repeat churn.

#### 176.4 Controls (mechanical)

* **top-N reach**: top N by training reach.
* **top-N self**: top N by training self.
* **90%-reach rule** (zopfli only): the rationale 1 walk (training reach
  order; add until the union covers >= 90% of in-binary training cycles),
  union computed exactly from the six perf.data files with
  `perf_hotness.py`'s own resolution. No existence gate (the plugin's view
  is not an input to any arm; `HashThing::update`, which the gate removed
  from Claude's marks, stays listed and is footnoted wherever it is picked).
  **jaq: not applicable** (22.9% of in-binary cycles are mimalloc, so 90%
  is unreachable, and the perf.data needed for a union is gone).
  hintbench: every control is all 8 (equal shares).

#### 176.5 Metrics (for every Jev readout and every control)

* **(a) overlap** = |Claude's marks hit| / N. A selected row hits mark M if
  its name with the depth-0 `::<…>` groups removed equals M's (so either
  instantiation of `write_until` or `seq` hits the mark; a closure row does
  not hit its parent).
* **(b) oracle-positive coverage** (same hit rule): jaq `Val::hash`
  (`inline(always)` +4.5%) and `write_until` (`inline(always)` +1.5 / +2.2%
  under MDE v2), 2 functions; zopfli `lz77_optimal` (owns `squeeze.rs:325`,
  +1.3%), 1 function, and **separately** `find_longest_match_loop` (owns
  `lz77.rs:563`, +0.5%, below the MDE); hintbench k2, k3, k8.
* **(c) oracle-harmful functions covered** (informational): jaq
  `write_until` (`inline(never)`); zopfli `find_longest_match`,
  `get_best_lengths`, `lz77_optimal` (owner of `squeeze.rs:275`).
* **(d) cycles covered**: zopfli the exact union (training / holdout);
  jaq bounds over the six-workload table, lower = max(sum of self, max
  reach), upper = min(100, sum of reach) (no perf.data, 86); hintbench
  12.5% per function.
* Reported alongside: the reach rank of `write_until` (and of `Val::hash`)
  in the listed table; functions Jev picked that no control picked and vice
  versa; the range over repeats; requests, 503s, cost.

#### 176.6 Verdict rule

For each Jev readout (Q1, Q2) separately: Jev **"adds something"** if, on
**both** jaq and zopfli, the median over the 3 repeats of (b) is >= (b) of
**every** control available for that target, and the median of (a) is
>= 0.6. If at least one readout passes, the verdict is "Jev can choose the
marks" and decision 108 proposes `--marks-by jev` (design only). Otherwise
the verdict is **"marks are a mechanical rule"**, which is also a valid
conclusion: the rule needs no Claude judgement either, so it removes the
manual point too. hintbench is a sanity check only and does not enter the
verdict: with 8 equal rows and N = 8, Q2 and every control are all 8 by
construction; only Q1 (does Jev mark every kernel?) is informative.

**Caveats written before the numbers.** Claude's marks were themselves
chosen by ranking perf tables (jaq by self + a judgement to add the lexer
children, zopfli by the 90% rule), so (a) mostly measures agreement with
hotness; **(b) versus the controls is the informative part**. On zopfli
both positives are in the top 2 of every control, so (b) cannot separate
Jev from a control there; jaq's `write_until` (self 0, reach 7.5%) and
`Val::hash` (self 1.2%, reach 1.2%) are the discriminating cases. A tie
with the controls on (b) passes the rule as written ("Jev matches the
mechanical rule"); the write-up will say whether it tied or exceeded.

**Deviations** will be recorded here as 176.7 before any request they
affect.

#### 176.7 Amendment (coordinator / owner, 2026-09-24 20:05): input set v2, hybrid Q3, optional Q4

Registered while the v1 requests of 176.1-176.6 were in flight (hintbench
and zopfli landed, jaq in progress) and **before any v2 request**. The v1
run is completed and scored exactly as pre-registered; v2 is a second,
separate input set with its own logs (`ms2-*`), not a replacement.

**Why.** `targets/jaq/jev-marks.rationale.md` "Why these fifteen" shows that
Claude's jaq marks used, besides reach, post-LTO binary facts (instruction
and backedge counts, called vs inlined, per-workload shares) and skipped
library plumbing, compiler-generated glue, C and thunks. v1 gave Jev less
than Claude had. v2 gives Jev the same kind of facts, uniformly, and still
no judgement text.

**v2 inputs** (`build --inputs v2`, `inputs-v2.json`): the v1 rows and
fields (same floor, same exclusions, same order and ids) plus, per row:
`crate` (the tables' crate column; name only), `reach per case`
(jaq objsearch / readwrite / strproc, zopfli binary / json / text; mean of
the training and holdout runs of that case), `insns` and `loops`
(`scripts/inline_structure.py` `reach` / `reachbe`: machine instructions
and backward jumps of the code that belongs to the function, including
what is inlined into it, over **every symbol that received a sample**;
hintbench: over every text symbol, since there is no profile), `hosts`
(`nhosts`). Structure tables regenerated from the verified binaries into
`artifacts/jev-marks-study/{jaq,zopfli,hintbench}-inline-structure.tsv`
(every listed row resolved). The column texts are fixed in
`V2_COLS`; `leak_check` clean on all three targets (crate names blanked
like function names: `hbkernels` is data).

**Questions on v2.** Q1 and Q2 unchanged (texts, readouts). New:

* **Q3 hybrid.** A mechanical rule, fixed now, decides the clear cases
  without Jev: **skip** if training reach < 1% or the function's code is a
  thunk (`insns` <= 8); **mark** if training reach >= 5% and `loops` > 0;
  C / no-IR rows are already excluded from the list. Everything else is
  **gray** and gets the Q1 question (same text, same v2 state showing the
  whole table); Q3 set = rule-marks + gray rows with P(mark) > 0.5. Rule
  counts: jaq 15 mark / 101 gray / 8 skip; zopfli 10 / 14 / 2; hintbench
  5 / 3 / 0 (k1, k2, k7 are gray: no machine loop). Scored like the others
  plus a **requests / questions** column. Two mechanical references are
  also reported: rule-marks only (gray skipped) and rule-marks + all gray.
* **Q4 (exploratory, lowest priority, optional).** Q1 plus a comment-
  stripped source excerpt for gray rows only. Run only if time allows after
  Q1-Q3 on v2; if not run, it is said so in 177. Not part of any verdict.

**Plan.** v2: 3 repeats x (jaq Q1 3 + Q2 4 + Q3 3 chunks, zopfli 3,
hintbench 3) = 48 requests, sequential after the v1 run ends (never two
senders at once).

**Verdict with v2.** The 176.6 rule is applied to each readout of each input
set (v1 Q1, v1 Q2, v2 Q1, v2 Q2, v2 Q3). Q3's rule part is mechanical, so a
Q3 pass is reported as "hybrid passes"; it counts as "Jev adds something"
only if Q3 also beats "rule-marks only" on (b) or (a) on some target.

### 177. Marks study: results

Sent 2026-09-24 19:58-21:17 JST, sequentially, one sender at a time (v2
queued behind v1). No build, no timing. Commands:

```
scripts/jev_marks_study.py build                    # v1 inputs (176.1)
scripts/jev_marks_study.py run                      # v1: Q1, Q2 x 3
scripts/jev_marks_study.py score                    # -> scores.json, report.md
scripts/inline_structure.py --binary <verified binary> --names-from <perf-self tsv> \
    --top 300 --tsv artifacts/jev-marks-study/<target>-inline-structure.tsv   # 176.7
scripts/jev_marks_study.py --inputs v2 build
scripts/jev_marks_study.py --inputs v2 run --questions Q1 Q2 Q3
scripts/jev_marks_study.py --inputs v2 score        # -> scores-v2.json, report-v2.md
```

Full tables (every readout, per repeat, per function P(mark) / Score, reach
rank): `docs/experiments/jev-marks-study/report.md` (v1) and `report-v2.md`
(v2). Below, "median (range)" is over the 3 repeats; `(a)` overlap with
Claude's marks / N; `(b)` oracle-positive functions covered; `(c)`
oracle-harmful functions covered; `(d)` cycles covered (zopfli exact union
training / holdout; jaq bounds lower-upper over all six workloads, 176.5).

#### 177.1 jaq (N = 15, 124 functions listed; positives `Val::hash`, `write_until`)

| arm | size | (a) | (b) | (c) | (d) |
|---|--:|--:|--:|--:|--:|
| v1 Q1 (P > 0.5) | 17 (16-20) | 0.53 (0.53-0.67) | 1/2 | 1 | 51-100% |
| v1 Q1-top N | 15 | 0.53 (0.53-0.60) | 1/2 | 1 | 50-100% |
| v1 Q2 top N | 15 | 0.53 (0.47-0.53) | 1/2 | 1 | 52-94% |
| **v2 Q1 (P > 0.5)** | 25 (24-25) | **0.67** (0.67-0.67) | 1/2 | 1 | 54-100% |
| v2 Q1-top N | 15 | 0.60 (0.60-0.67) | 1/2 | 1 | 51-100% |
| v2 Q2 top N | 15 | 0.47 (0.47-0.53) | 1/2 | 1 | 48-100% |
| **v2 Q3 hybrid** | 25 (24-28) | **0.67** (0.67-0.73) | 1/2 (1/2-2/2) | 1 | 51-100% |
| hybrid rule only (gray skipped) | 15 | 0.40 | 1/2 | 1 | 42-100% |
| hybrid rule + every gray row | 116 | 1.00 | 2/2 | 1 | 65-100% |
| top-N reach | 15 | 0.40 | 1/2 (`write_until`) | 1 | 42-100% |
| top-N self | 15 | 0.80 | 1/2 (`Val::hash`) | 0 | 63% |
| 90%-reach rule | n/a (176.4) | | | | |
| Claude's marks (reference) | 15 marks = 17 rows | 1.00 | 2/2 | 1 | 60-91% (60.91% measured, "Marks (jaq)" 85) |

**The two discriminating functions.**

* `write_until` (`::<…str_fold::string_end>` instantiation, self 0.00%,
  reach 7.5%): **reach rank 10 of 124**, so top-N reach catches it and
  top-N self cannot. Jev marks it in every repeat of every readout
  (P(mark) v1 0.77-0.83, v2 0.78-0.83; Score 1.41-1.66, rank ~6). The other
  instantiation (`num_bytes_with`, reach 1.2%, rank 77) gets P 0.22-0.33;
  either would hit the mark.
* `Val::hash` (self = reach 1.2%, 1492 insns / 90 loops): **reach rank 83**,
  so only top-N self catches it (self rank 14). Jev does not mark it: v1
  P(mark) 0.30-0.38, v2 0.45-0.46, Q3 (gray) 0.42 / 0.44 / **0.52** --- one
  Q3 repeat crosses 0.5, which is the only 2/2 of any Jev readout. The v2
  facts (`loops` 90) moved it by about +0.12, not across the line.

So on (b) every Jev readout **ties** both controls at 1/2, but with the
control that shares its bias: Jev finds what reach finds (`write_until`) and
misses what only self finds (`Val::hash`). No Jev readout covers both in
its median; Claude's set does.

Claude's marks that Jev v2 Q1 (median P) does not mark: `Val::hash`,
`Rc<IndexMap>::drop_slow`, `Adapter::write_str`, `<&String as
Display>::fmt`, `base_run::{closure#7}` --- all five are self-hot bodies on
the write / object path with reach < 5%. What Jev v2 Q1 marks that neither
control has: `parse_num`, `num_string_with`, `Val::index`, `index_opt`,
`Path<Result>::run`, `FromFn<fold>`, `RawTableInner::reserve_rehash_inner`,
`IndexMapCore::insert_full` variants and **`core::ptr::drop_glue`** (which
the rationale left out as compiler-generated). What the controls have and
Jev does not: the `core::iter` adapters under the lexer (top-N reach) and
the `Display` / `write_str` / `drop_slow` / `FlatMap` bodies (top-N self).

#### 177.2 zopfli (N = 6, 26 functions listed; positive `lz77_optimal`, extra `find_longest_match_loop`)

| arm | size | (a) | (b) | extra | (c) of 3 | (d) train / hold |
|---|--:|--:|--:|--:|--:|--:|
| v1 Q1 (P > 0.5) | 9 (8-10) | **1.00** (0.83-1.00) | 1/1 | 1 | 3 | 94.0 / 95.5% |
| v1 Q1-top N | 6 | 0.67 | 1/1 | 1 | 2 | 94.0 / 95.5% |
| v1 Q2 top N | 6 | 0.67 | 1/1 | 1 | 2 | 94.0 / 95.5% |
| **v2 Q1 (P > 0.5)** | 13 (12-13) | **1.00** | 1/1 | 1 | 3 | 96.3 / 96.9% |
| v2 Q1-top N | 6 | 0.67 | 1/1 | 1 | 2 | 94.0 / 95.5% |
| v2 Q2 top N | 6 | 0.67 | 1/1 | 1 | 2 | 94.0 / 95.5% |
| **v2 Q3 hybrid** | 12 (11-12) | **1.00** | 1/1 | 1 | 3 | 95.6 / 96.3% |
| hybrid rule only | 10 | 1.00 | 1/1 | 1 | 3 | 94.0 / 95.5% |
| hybrid rule + every gray row | 24 | 1.00 | 1/1 | 1 | 3 | 97.6 / 98.3% |
| top-N reach | 6 | 0.83 | 1/1 | 1 | 2 | 89.9 / 91.1% |
| top-N self | 6 | 0.33 | 1/1 | 1 | 1 | 96.8 / 97.5% |
| 90%-reach rule | 7 | 1.00 | 1/1 | 1 | 3 | 93.4 / 94.9% |
| Claude's marks | 6 | 1.00 | 1/1 | 1 | 3 | 93.4 / 94.9% |

`find_longest_match_loop` and `lz77_optimal` are reach ranks 1 and 2 and get
P(mark) 0.97-0.99 in every repeat; (b) cannot separate anything here, as
176.6 said. The forced-N readouts (Q1-top, Q2) replace
`get_best_lengths` and `lz77_optimal_run` (reach 39.8%, no own symbol, no
self time) with `follow_path` and `try_get` (self-hot, own symbol) and
`find_longest_match`; the P > 0.5 readouts keep all six of Claude's and add
3-7 more. `HashThing::update` (removed from Claude's set by the existence
gate) is marked by v1/v2 Q1 (P 0.59-0.69) and by the hybrid rule; it is
footnoted, not scored against anyone (176.4).

#### 177.3 hintbench (sanity; N = 8)

v1 and v2 Q1 mark 6 of 8 (median; one v1 repeat 7): **`k1_step` and
`k7_error_path` are skipped** (P 0.34-0.54), both the kernels without a
machine-code loop that are not called on their own (k2, loop-free but with
its own symbol, gets P 0.96). All three positives (k2, k3, k8) are marked in
every repeat. Q1-top N, Q2 and every control are all 8 by construction. The
hybrid rule alone marks the 5 kernels with loops and misses **k2** (0 loops,
gray); Jev then marks k2 in the gray zone (P 0.96), so Q3 = 6/8 with 3/3
positives while "rule only" is 2/3.

#### 177.4 Verdict (176.6, applied as written)

| readout | jaq (a) >= 0.6 | jaq (b) >= every control | zopfli (a) >= 0.6 | zopfli (b) >= every control | passes |
|---|:-:|:-:|:-:|:-:|:-:|
| v1 Q1 | 0.53 no | 1/2 = 1/2 tie | 1.00 | tie | **no** |
| v1 Q2 | 0.53 no | tie | 0.67 | tie | **no** |
| v2 Q1 | 0.67 | tie | 1.00 | tie | **yes** |
| v2 Q1-top N (secondary) | 0.60 | tie | 0.67 | tie | yes (at the bar) |
| v2 Q2 | 0.47 no | tie | 0.67 | tie | **no** |
| v2 Q3 hybrid | 0.67 | tie | 1.00 | tie | **yes**; beats "rule only" on jaq (a) 0.67 vs 0.40 and hintbench (b) 3/3 vs 2/3 |

**Verdict: Jev can choose the marks from the profile when it is given the
same binary facts Claude used (input set v2), at the pre-registered bar,
and only there.** With perf shares alone (v1) it fails on jaq (0.53).
Honest reading of the pass:

1. **It ties the mechanical rules on the oracle positives; it never beats
   them.** Jev's selection behaves like a reach ranking with extra weight on
   own symbols and loops: it catches `write_until` (reach rank 10) and misses
   `Val::hash` (reach rank 83, P <= 0.52). No mechanical control covers both
   either; only Claude's set did.
2. **What it gains over a single mechanical ranking is agreement across
   both targets**: no single control reaches (a) >= 0.6 on both (top-N self
   0.80 / 0.33, top-N reach 0.40 / 0.83), v2 Q1 reaches 0.67 / 1.00. Part
   of that comes from marking more (jaq 25 rows vs 15, zopfli 13 vs 6); with
   the size forced to N it is 0.60 / 0.67, exactly at the bar.
3. The Score framing (Q2) is worse than Choice on jaq in both input sets
   (0.53, 0.47), as in study 2 (174).
4. The hybrid (rule decides the clear cases, Jev the gray zone) is as good
   as v2 Q1 at 81% (jaq 101/124) and 54% (zopfli 14/26) of the questions,
   the same number of HTTP requests on jaq (3 per repeat per question set,
   set by state size) and fixes the rule's one blind spot on hintbench (k2).

Q4 (source excerpts for the gray zone, 176.7) was **not run** (optional,
lowest priority).

#### 177.5 Nondeterminism

Across the 3 repeats: jaq v1 Q1 set union 22 / intersection 13, v2 Q1 27 /
21, v2 Q3 29 / 23; Q1-top and Q2 at N = 15: union 16-17, intersection
12-13. zopfli v2 Q1 13 / 12, Q1-top and Q2 6 / 6. hintbench v2 6 / 6. The
metric ranges are in the tables; the only positive that flips is
`Val::hash` in v2 Q3 (0.42 / 0.44 / 0.52).

#### 177.6 Requests, gateway, cost

| run | requests | questions | 503 responses | exhausted (re-sent) | max body | billed | list price |
|---|--:|--:|--:|--:|--:|--:|--:|
| v1 (`ms-*`) | 31 | 989 | 658 | 1 (jaq r1 Q2.c2, landed on the re-send) | 59 781 B | $0 | $0.017 |
| v2 (`ms2-*`) | 48 | 1302 | 565 | 0 | 59 959 B | $0 | $0.031 |

503s are almost all on the ~60 KB jaq requests (v1 655 of 658, v2 556 of
565); zopfli and hintbench (7-27 KB) landed on the first or second attempt.
No phase lost. Latency of landed requests 0.9-2.4 s.

**Deviations.** None from 176 / 176.7 in what was sent. Report labels only:
the jaq (d) column prints lower-upper bounds (the report script first
printed them as "lo / hi" like zopfli's training / holdout; fixed before
this section was written, numbers unchanged).

#### 176.8 Amendment (owner via coordinator, 2026-09-24 21:40): phase 3, verdict lines and per-case questions

Registered after 177 was written and **before any phase-3 request**. API
only. Same v2 state (176.7), same list, ids, floor and metrics; logs
`ms3-*`; `scripts/jev_marks_study.py --inputs v2 run --run-prefix ms3
--questions ...`.

**Why.** Decisions 73 / 84: Jev followed mechanical readings placed next to
the question (not in the state) and balanced option texts, where it ignored
the same facts in the state. Goal: rescue the functions Claude marked and
Jev (v2 Q1) dropped --- jaq `Val::hash` (P 0.45) and the per-workload picks
(`Rc<IndexMap>::drop_slow`, `Adapter::write_str`, `<&String as
Display>::fmt`, `base_run::{closure#7}`) --- without adding marks outside
every reference set, and with no per-function judgement text.

**Variants** (all Choice mark / skip, one question per listed function, the
Q1 instruction text as the base):

* **M1 verdict lines**: the Q1 question plus a fixed block (preamble: "Mechanical
  readings for this function. Each line is produced by a tool from the table
  in the state, by the same rule for every function in this request; none of
  them is an opinion about whether to mark it.") with exactly these lines,
  from the v2 facts: `machine-code loops after LTO: yes (N backward jumps)` /
  `no (0 backward jumps)` / `unknown (…)`; `called, not inlined: yes` /
  `yes, and copies are also inlined into K other symbols` / `no (its code is
  inlined into K symbols)` (from own symbol + `hosts`); `own symbol in the
  final binary: yes/no`; `generic from another crate instantiated inside this
  program's LTO unit: yes/no` (yes = the name's crate is not one of the
  program's own crates and the name contains `<own crate>::`; own crates:
  jaq `jaq, jaq_json, jaq_core, jaq_std, jaq_all`, zopfli `zopfli`,
  hintbench `hbkernels, hintbench`); `share of cycles per case (reach): …`
  (per-case reach of the v2 table; hintbench "not measured"); `reach rank: r
  of M`; `self-time rank: r of M` (training values, competition ranking,
  ties share a rank; hintbench self "not measured"). The self-time rank is
  added to the coordinator's list because it is the ranking under which
  `Val::hash` is visible (rank 13); it is the same mechanical line for every
  function.
* **M2 per-case questions**: the Q1 question prefixed "For the `<case>`
  workload only." and "Decide whether to mark it for this workload.", one
  question set per case (jaq objsearch / readwrite / strproc, zopfli binary /
  json / text; not applicable to hintbench, which has no per-case data).
  Readout = union over cases of P > 0.5; per-case sets are reported too.
* **M3 uniform criteria**: the option texts become (lengths 214 / 229
  characters): mark = "Mark this function. A function attribute can change
  the program's speed only if the function is called (not inlined) or is
  inlined at a call with constant arguments; loop metadata can change it only
  if a machine-code loop survives LTO."; skip = "Do not mark this function.
  Neither condition holds for it: it is not called and not inlined at a call
  with constant arguments, and no machine-code loop of it survives LTO; it
  will never be touched."
* **M4** = M1 + M3. **M5** = M1 + M2 + M3.

**Plan and order** (sequential, one sender, `--resume`, 60 KB chunks as
before): first M1, M3, M4 on hintbench, zopfli, jaq (3 repeats; jaq 17
requests per repeat), then M2 on zopfli, jaq (jaq 12 per repeat), then M5
(jaq 21 per repeat) "if budget allows": M5 is sent only if the gateway
landed M1-M4 and M2 without a lost request; if it is cut, 178 says so.
About 150 jaq requests in total at ~60 KB (v2 needed ~20 attempts each).

**Readouts and metrics**: as 176.3 / 176.5 (median over 3 repeats; set from
the median P), plus **false marks** = selected functions (generic-stripped)
that are in **no** reference set (top-N reach, top-N self, 90% rule,
Claude's marks). This is a proxy: the oracle measured only Claude's marks,
so "false" means "outside every reference", not "measured worthless".
Reference values computed with the same code on the v2 data before this
amendment: v2 Q1 false marks jaq 10 (9-10 per repeat), zopfli 3, hintbench 0.

**Success rule per variant** (fixed now): a variant **rescues** if its
median-P set contains `Val::hash` (jaq (b) 2/2) **or** raises jaq (a) above
v2 Q1's 0.67, **while** jaq false marks <= 10, zopfli (a) = 1.00 with (b)
1/1, and hintbench (M1/M3/M4) keeps k2, k3, k8. `Val::hash`'s P per repeat
is reported for every variant. A variant that rescues is proposed as the
Choice text of `--marks-by jev` in decision 108's addendum; otherwise 108
stands unchanged.

### 178. Marks study phase 3: verdict lines, per-case questions, criteria block (results)

Sent 2026-09-24 22:05 to 2026-09-25 00:10 JST, sequentially (M1/M3/M4, then
M2, then M5, since M1-M4 and M2 lost nothing, 176.8). Commands:

```
scripts/jev_marks_study.py --inputs v2 run --run-prefix ms3 --resume --targets hintbench zopfli jaq --questions M1 M3 M4
scripts/jev_marks_study.py --inputs v2 run --run-prefix ms3 --resume --targets zopfli jaq --questions M2
scripts/jev_marks_study.py --inputs v2 run --run-prefix ms3 --resume --targets zopfli jaq --questions M5
scripts/jev_marks_study.py --inputs v2 score --run-prefix ms3 --out artifacts/jev-marks-study/scores-v3.json --report artifacts/jev-marks-study/report-v3.md
```

Sets from the per-function median P over 3 repeats (per-repeat values in
`docs/experiments/jev-marks-study/report-v3.md`; the per-repeat ranges are
narrow: jaq sizes vary by at most 3, (a) by at most 0.07). "false" =
functions outside every reference set (176.8). The v2 Q1 row is 177's.

#### 178.1 jaq (N = 15)

| variant | size | (a) | (b) | `Val::hash` P (3 repeats) | false | (d) lower-upper |
|---|--:|--:|--:|---|--:|--:|
| v2 Q1 (177) | 25 | 0.67 | 1/2 | 0.46 0.45 0.45 | 10 | 54-100% |
| M1 verdict lines | 47 | 1.00 | **2/2** | **0.76 0.80 0.79** | 16 | 65-100% |
| M2 per case (union) | 45 | 0.80 | 1/2 | max over cases 0.37 0.31 0.45 | 23 | 60-100% |
| M3 criteria block | 65 | 1.00 | **2/2** | 0.89 0.84 0.87 | 32 | 66-100% |
| M4 = M1 + M3 | 109 | 1.00 | 2/2 | 1.00 1.00 1.00 | 70 | 66-100% |
| M5 = M1 + M2 + M3 | 109 | 1.00 | 2/2 | 1.00 (every case) | 70 | 66-100% |
| M1 top N (176.3 secondary) | 15 | 0.60 | 1/2 | | 4 | 54-87% |
| M2 top N | 15 | 0.53 | 0/2 | | 3 | 51-100% |
| M3 / M4 / M5 top N | 15 | 0.47 / 0.33 / 0.33 | 0/2 | | 5-6 | |

M2's per-case sets (repeat 1): objsearch 29, readwrite 23, strproc 27
functions; the union gains `Adapter::write_str` and `base_run::{closure#7}`
over v2 Q1 but still misses `Val::hash`, `Rc<IndexMap>::drop_slow` and
`<&String as Display>::fmt`.

#### 178.2 zopfli (N = 6) and hintbench (N = 8)

| variant | zopfli size | (a) | (b) | false | (d) train / hold | hintbench size | k2 / k3 / k8 | k2 P |
|---|--:|--:|--:|--:|--:|--:|:-:|---|
| v2 Q1 (177) | 13 | 1.00 | 1/1 | 3 | 96.3 / 96.9% | 6 | yes | 0.96 |
| M1 | 15 | 1.00 | 1/1 | 5 | 96.5 / 97.2% | 6 | yes | 0.65 0.74 0.76 |
| M2 | 15 | 1.00 | 1/1 | 5 | 96.5 / 97.2% | n/a | | |
| M3 | 15 | 1.00 | 1/1 | 4 | 97.6 / 98.3% | 5 | **k2 lost** | 0.14 0.16 0.11 |
| M4 | 19 | 1.00 | 1/1 | 8 | 97.7 / 98.4% | 6 | yes | 0.99 |
| M5 | 19 | 1.00 | 1/1 | 8 | 97.7 / 98.4% | n/a | | |

The top-N readouts under M3-M5 collapse on zopfli too ((a) 0.33 / 0.17 /
0.17, (b) 0/1): P saturates near 1 for most rows, so the top N is decided by
the alphabetical tie-break, not by Jev.

#### 178.3 Reading against the 176.8 rule

**No variant rescues.** Every variant that brings `Val::hash` in (M1, M3,
M4, M5) does it by lowering the bar for everything: jaq false marks go
10 -> 16 / 32 / 70 / 70 (rule: <= 10), and the marked set grows from 25 to
47 / 65 / 109 of 124 functions. M2 raises jaq (a) to 0.80 but adds 23 false
marks and does not bring `Val::hash` in. zopfli (a) stays 1.00 with (b) 1/1
in every variant; hintbench keeps k2 / k3 / k8 in M1 and M4 but loses k2
in M3 (the criteria block reads the loop-free k2 as a "skip").

What the numbers say about the mechanism:

1. **The readings are followed, as in decision 73, but as a threshold,
   not as a ranking.** With the loop / called lines next to the question
   (M1), Jev marks almost every function whose reading says "yes", whatever
   its share: `Val::hash` rises from 0.45 to 0.79, but so do 22 other rows.
   The criteria block (M3) states two sufficient-looking conditions and Jev
   marks every row that meets either one; M4 saturates (109 rows at P ~1).
2. **Per-case questions (M2) reproduce Claude's balancing only
   partly**: the write-path picks come in, `Val::hash` (1.7% of objsearch)
   does not, and each case adds its own tail.
3. **Nothing here separates `Val::hash` from its neighbours with a
   mechanical line.** The facts that single it out for Claude (self rank
   13, 90 loops, called) are shared by many rows Claude skipped; the
   reference set's choice among them was a judgement about the object path,
   which is not in any uniform line.

**Correction to 176.8**: the M3 option lengths are 235 (mark) / 197 (skip)
characters, not 214 / 229 as written there; the texts are as quoted.

#### 178.4 Requests, gateway, cost

| target | requests | questions | 503 responses | exhausted | max body | billed | list price |
|---|--:|--:|--:|--:|--:|--:|--:|
| hintbench | 9 | 72 | 1 | 0 | 14 145 B | $0 | $0.0013 |
| zopfli | 27 | 702 | 96 | 0 | 45 608 B | $0 | $0.0125 |
| jaq | 150 | 3348 | 1911 | 0 | 59 981 B | $0 | $0.1383 |

186 requests, none lost, $0 billed ($0.15 at list price), about 2 h of
wall clock, almost all of it retrying the ~60 KB jaq requests.

### 179. Marks by rule ∪ Jev gray zone: implementation and API check

#### 179.1 Pre-registration

Written 2026-09-25 before any request of this check was sent. API only: no
build, no timing, no cargo, no binary run (local work: reading the perf
tables and structure tables already on disk, `nm` / `objcopy` on the
profiled binaries). Script: `scripts/target_marks.py` (new); logs
`artifacts/jev-marks/<target>/tm-<target>.{jsonl,log}` (copied gzip'd to
`docs/experiments/jev-marks-study/impl/` at the end).

**What is adopted (owner, 2026-09-25; decision 109).** Marks = a mechanical
seed ∪ a Jev gray zone, on the marks study's input set v2 (176.7):

* **Listed**: every row of the perf inline table with reach >= 1% or self
  >= 1% in the training or the holdout set (max of the two), C rows
  removed. Same rows, ids (alphabetical) and state as the study's v2; the
  rendered state is **byte-identical** to the `ms2-*` requests (sha256
  prefixes jaq `99e52fc3cc9e40e6`, zopfli `c0e751e12a1768ad`, hintbench
  `27271d841a2cbc97`), and every row field (self, reach, own symbol, size,
  crate, per-case reach, insns, loops, hosts) equals `inputs-v2.json`.
* **Excluded** (never marked, never asked): no IR / C (`lang c`, or a name
  without `::` / `<`; not in the list at all), **thunks** = `insns` <= 8
  (the study's 176.7 threshold, `--thunk-insns`; the owner's words were
  "one-instruction thunks", and on these tables the literal 1 would exclude
  nothing and send six 4-8 instruction helpers as questions), and rows below
  the 1% floor in both reach and self.
* **Seed** (always marked, no question): top N by **training** reach ∪ top N
  by **training** self, ranked among the listed rows that are neither
  excluded nor compiler-generated (`drop_glue` / `drop_in_place` / vtable
  shims, regex `(^|::)drop_(glue|in_place)(::<|$)|{vtable.shim}|{shim:`);
  ties broken alphabetically. **"Own IR symbol" is read as "a Rust function
  the plugin has IR for"** (= not C, not a thunk, not compiler-generated),
  **not** as the study's `own symbol` column (a text symbol in the final
  binary): Claude's frozen marks `seq`, `str_fold`, `get_best_lengths`,
  `lz77_optimal_run` and 6 of the 8 hintbench kernels have no final-binary
  symbol and were resolved by the plugin and measured by the oracles; the
  `own symbol` column stays a fact in the state and the rationale.
  Compiler-generated rows are not excluded; they go to the gray zone.
* **Gray zone**: every other listed row whose marks line is not already
  matched by a seed line. One Choice {mark, skip} each, the study's Q1 text
  and criteria unchanged (the questions of 176.7's Q3), on the whole v2
  state; no verdict lines, no criteria block (108 addendum). **3 repeats;
  marked if the median P(mark) over the landed repeats is >= 0.5** (the
  owner's ">="; the study used "> 0.5" --- no study value sits at exactly
  0.50 for these rows, so the two agree unless an answer lands on 0.50,
  which will be reported).
* **Marks lines**: a row's name with the depth-0 `::<…>` groups removed
  when that still matches the row under the plugin's rule (equal /
  continues with `::` / ends with `::` + line, `plugin/README.md`), else the
  full name; a line matched by another selected line is folded into it
  (e.g. `jaq_json::read::parse::<…>::{closure#1}` into
  `jaq_json::read::parse`). The final set may exceed N.
* **N** = the size of Claude's frozen marks: jaq 15, zopfli 6, hintbench 8
  (`--marks-n`).

**Inputs.** jaq `artifacts/jaq-marks/perf-{self,inline}.tsv`, zopfli
`artifacts/zopfli-marks/perf-{self,inline}-{train,hold}.tsv`, structure
`artifacts/jev-marks-study/<t>-inline-structure.tsv`, binaries as in 176.1
(`.text` prefixes checked: `642dd55e`, `9aca86fc`, `df5968bc`). hintbench
has no perf table: as in the study, the 8 functions of
`targets/hintbench/jev-marks.txt` at 12.5% each (`--equal-shares`). That
row list **is** the frozen marks, so hintbench cannot test selection; it
only checks that the rule does not drop a kernel.

**Dry run (mechanical; `scripts/target_marks.py --target <t> --dry-run`),
computed before any request:**

| target | listed | seed rows / lines | covered by a seed line | gray (questions) | excluded (thunk) | requests per repeat |
|---|--:|--:|--:|--:|--:|--:|
| jaq | 124 | 27 / 26 | 7 | 85 | 5 | 2 (59 863 B, 57 081 B) |
| zopfli | 26 | 10 / 10 | 1 | 14 | 1 | 1 (15 784 B) |
| hintbench | 8 | 8 / 8 | 0 | **0** | 0 | **0** |

Seed-level facts (no Jev): jaq covers all 15 frozen marks and **both
oracle positives** (`Val::hash` self rank 13, `write_until` reach rank 10);
zopfli covers 5 of 6 frozen marks (`find_longest_match`, reach rank 7, is
gray) and `lz77_optimal` + `find_longest_match_loop`; hintbench seeds all 8
(top 8 by reach of 8 tied rows) and so covers k2 / k3 / k8 **without a
question**.

**Expectations (written now; they are checks, not verdicts):**

1. jaq: final set covers both positives (via the seed, independent of Jev)
   and all 15 frozen marks. Size: 26 seed lines + the gray rows Jev marks;
   the study's v2 Q1 marked about 10 rows outside every control (177.1),
   most of them gray here, so about 30-40 lines.
2. zopfli: `lz77_optimal` covered (seed); the frozen 6 all covered if Jev
   marks `find_longest_match` in the gray zone (v2 Q1 marked it, 177.2).
3. hintbench: **the coordinator's expectation ("k2 rescued by Jev in the
   gray zone, as in 177") does not apply to the adopted rule** and is
   corrected here: that rescue came from 176.7's hybrid (mark only with
   reach >= 5% **and** loops > 0), which was not adopted. Under the
   adopted rule hintbench has seed 8 / gray 0, and no request is sent.

**Reported per target**: seed set, gray-zone size and Jev's answers (P per
repeat, median), final set size, overlap with Claude's frozen marks (a
frozen mark is covered if a listed row it matches is matched by a selected
line), oracle-positive coverage (jaq `Val::hash`, `write_until`; zopfli
`lz77_optimal`, separately `find_longest_match_loop`; hintbench k2 / k3 /
k8), the lines Claude did not mark with their facts, requests / HTTP 503 /
cost. Deviations will be recorded as 179.2 before any request they affect.

#### 179.2 Results

Sent 2026-09-25 03:42-03:54 JST (last response), sequentially (zopfli, then jaq; hintbench
sent nothing), one sender, no other process running. Commands:

```
scripts/target_marks.py --target <t> --dry-run                     # 179.1 table
scripts/target_marks.py --target <t> --jev --json artifacts/jev-marks/<t>-table.json
scripts/target_marks.py --target <t> --jev --resume --json artifacts/jev-marks/<t>-table.json   # see deviation
```

**Deviation (no effect on what was sent).** The first `--jev` pass crashed
*after* its requests had landed and the marks file was written, while
writing the rationale (a `KeyError` on the request counter: zopfli and jaq;
hintbench, with no requests, completed). Fixed in the script, then all three
were re-run with `--resume`, which reuses every landed request of the log
and sends nothing (console: `landed earlier` for all 3 / 6 requests). The
marks files and rationales committed are those of the `--resume` pass; the
`# Produced by:` header line says so.

| target | seed lines | gray questions | gray marked (median P >= 0.5) | final lines | N | frozen marks covered | oracle positives |
|---|--:|--:|--:|--:|--:|--:|---|
| jaq | 26 (27 rows) | 85 | 8 | **34** | 15 | **15 / 15** | `Val::hash` yes (seed, self rank 13), `write_until` yes (seed, reach rank 10): **2/2** |
| zopfli | 10 | 14 | 4 | **14** | 6 | **6 / 6** | `lz77_optimal` yes (seed), `find_longest_match_loop` yes (seed) |
| hintbench | 8 | 0 | - | **8** | 8 | 8 / 8 | k2 / k3 / k8 yes (seed; no question) |

**Gray-zone answers** (P(mark) per repeat; full tables in
`targets/<t>/jev-marks.jev.rationale.md`). No median was exactly 0.50, so
">= 0.5" and the study's "> 0.5" give the same sets; every question was
answered in all 3 repeats.

* zopfli, marked: `ZopfliLongestMatchCache::try_get` 0.96 0.96 0.95,
  `find_longest_match` 0.87 0.89 0.91 (the frozen mark the seed missed,
  reach rank 7), `ZopfliLongestMatchCache::fetch_sublen` 0.51 0.60 0.68,
  `get_cost_stat` 0.52 0.53 0.57. Next below: `max_sublen` 0.44,
  `Lz77Store::append_store_item` 0.43. Per-repeat sets identical (4 / 4 / 4).
* jaq, marked: `read::parse_num` 0.88-0.90, `FromFn<fold…>::next` 0.61-0.67,
  `num_string_with` 0.61-0.65, `<Val as ValT>::index` 0.55-0.66,
  `Val::index_opt` 0.61-0.66, `IndexMapCore::push_entry` 0.50-0.57,
  `RawTableInner::reserve_rehash_inner` 0.46-0.55, `Path<Result>::combinations`
  0.49-0.56. Next below: `jaq_json::funs::base::{closure#3}` 0.47,
  `BufWriter::write_fmt` 0.45, `drop_glue::<Val>` 0.45. Per-repeat sets 7 / 7
  / 8 (union 8, intersection 6): the last three marked rows straddle 0.5.
  The compiler-generated rows (10 `drop_glue` / `drop_in_place`) are all
  below 0.5 here (v2 Q1 had marked a `drop_glue`, 177.1).

**Lines Claude did not mark** (facts: training reach / self, insns / backward
jumps, own symbol):

* jaq, from the seed (11): `<&isize as Display>::fmt` (self rank 15; 1.03 /
  1.03%, 222 / 17, own), `<&str as Display>::fmt` (self 12; 1.25 / 1.25%, 480
  / 25, own), `BufWriter::write_all` (reach 5.17%, self 0, 226 / 3, own),
  `Copied<Iter<u8>>::position` and `::try_fold` and `Iter<u8>::try_fold` (the
  iterator adapters under the lexer, reach 5.62% each, 43 / 2, no own symbol;
  one line each after stripping, their 80-insn second instantiations
  covered), `FlatMap<…>::next` (self 10; 1.59 / 1.59%, 434 / 18, own),
  `IndexMap::insert` (reach 8.16%, 284 / 10, no own symbol),
  `IndexMap::insert_full` (8.16%, 234 / 10, own), `IndexMapCore::insert_full`
  (6.19%, 205 / 9), `read::parse_string` (reach 7.65%, 715 / 46, own). From
  the gray zone (8): the eight rows above (reach 0.99-3.24%, self 0 except
  `FromFn` and `combinations` at ~1%, 76-1052 insns, 5-35 backward jumps).
* zopfli, from the seed (5): `Cache::store` (self rank 5; 1.10 / 1.10%, 127
  / 4), `HashThing::update` (reach 11.62%, 348 / 15, no own symbol; the
  plugin reported it `unmatched` when Claude's rule picked it, so `dump`'s
  existence gate would remove it again), `katajainen::Thing::boundary_pm`
  (self 4; 1.62%, 123 / 6), `Lz77Store::follow_path` (self 3; 9.61%, 921 /
  56), `Lz77Store::lit_len_dist` (self 6; train self 0.62%, reach 0.99%,
  listed by its holdout reach; 790 / 40). From the gray zone (3): `try_get`
  (reach 11.01%, 705 / 32, own), `fetch_sublen` (6.53%, 547 / 27),
  `get_cost_stat` (4.41%, 191 / 3, own).
* hintbench: none (the row list is the frozen marks, 179.1).

**Against the expectations of 179.1**: (1) jaq covers both positives through
the seed and all 15 frozen marks; 34 lines, inside the 30-40 expected. (2)
zopfli covers `lz77_optimal` and all 6 frozen marks; `find_longest_match`
came in through the gray zone (P 0.87-0.91). (3) hintbench: seed 8, gray 0,
no request, as corrected in 179.1; the "k2 rescued in the gray zone"
expectation does not apply to the adopted rule.

**What the rule costs in marks.** The final sets are 2.3x (jaq, 34 vs 15)
and 2.3x (zopfli, 14 vs 6) the frozen sizes; the seed alone is already 1.7x
on both (26, 10), because top-N reach and top-N self overlap little on these
tables (jaq: 3 functions in both lists of 15). The oracle's build count grows
with the marks (SPEC.ja.md 2: Σ sites x candidates + 1), so a site cap
(`SITE_CAP_RULE`) matters more with these files than with the frozen ones.
Whether a `.jev.txt` replaces a frozen file is the owner's call per target,
in a new registration; nothing measured so far used these files.

**Requests, gateway, cost** (`artifacts/jev-marks/<t>/tm-<t>.jsonl`):

| target | requests | questions | HTTP attempts | HTTP 503 | exhausted | max body | billed | list price |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| zopfli | 3 | 42 | 4 | 1 | 0 | 15 784 B | $0 | $0.0007 |
| jaq | 6 | 255 | 201 | 195 | 0 | 59 863 B | $0 | $0.0057 |
| hintbench | 0 | 0 | 0 | 0 | 0 | - | $0 | $0 |

**Driver integration (owner's additions, 2026-09-25, during this check).**
`scripts/jev_search.py --marks` is now optional: explicit file -> the newest
generated `jev-marks.jev[.vN].txt` -> generate once via `target_marks.py`;
`--marks-regenerate` writes the next versioned file; `run-manifest.json`
records `marks_provenance` (how, file, sha256, rationale, Jev log). When a
target's perf / structure tables are missing, `target_marks.py --jev` (and so
the driver's generation) takes them: busy check, perf present or "run
`scripts/perf_local.sh setup` first", plugin-off baseline, `SETS=training
perf_marks_profile.sh`, `perf_hotness.py --inline`, `inline_structure.py`.
**The auto-profile path is implemented but not exercised: no profile was
taken in this session** (all three targets have their tables); it and the
resolution order are covered by 15 unit tests with stubs
(`python3 scripts/test_target_marks.py`: 15 passed). The resolution was also
checked read-only on zopfli (no `--marks` -> `existing generated`
`targets/zopfli/jev-marks.jev.txt`, Jev log path read from its header;
explicit `--marks targets/zopfli/jev-marks.txt` -> `explicit`), and the
frozen-target entry point once as `__main__` with no build or timing:
`scripts/jev_search.py --target zopfli --marks targets/zopfli/jev-marks.txt
--proposer random --dry-run --vocab v6 --sites targets/zopfli/sites.json
--site-set oracle.selected_keys_top6 --baseline-dir
artifacts/zopfli-sites/baseline --out <scratch>` reused the baseline and
listed the same 6 function + 5 loop sites. No search was run.

**State check after the post-send edits.** The `--resume` pass re-rendered
the state with the edited script; its sha256 equals that of every sent
request (jaq `99e52fc3cc9e40e6`, zopfli `c0e751e12a1768ad`, the 179.1
values), so the reused answers belong to the state they were given for.

### 180. State without source excerpts: request size and landing rate (API only)

Pre-registration, written before any request of this section was sent
(decision 110 is filled in after the run). Nothing is built, nothing is
timed. Question: does dropping the source excerpt from the state (prompt
study 2's L13) shrink the request enough to land more often on the gateway,
without costing the function-attribute answers?

**The option.** `scripts/jev_search.py --source-excerpt {full,none}`
(default `full` = every run so far). `none` wraps the driver's `SourceBook`
in `NoExcerptSource`: every excerpt becomes the one line
`  (source excerpt omitted from this request)` (`S.SOURCE_OMITTED`, the
literal study 2's `_NoSource` sent), every mechanical fact line stays
(verdict block, remarks, post_vectorize, inline outcomes, platform block).
It is its own state format: `state-v5.0-noexcerpt-2026-09-25`,
`state-v5.1-noexcerpt-2026-09-25` (with `--pv-untried on`),
`state-v6.0-noexcerpt-2026-09-25`; other vocabularies exit. The frozen
templates and names are untouched. Recorded in `run-manifest.json`, in every
`rounds.jsonl` record and in every Jev JSONL line (`source_excerpt`).

**Unit check (done, no HTTP).**

```
$ scripts/jev_search.py --target hintbench --proposer jev --vocab v5 --print-state \
    --source-excerpt {full,none} --marks targets/hintbench/jev-marks.txt \
    --sites artifacts/hintbench-sites/sites.json \
    --site-set oracle.selected_keys_loop_hint_kernels \
    --baseline-dir artifacts/hintbench-sites/baseline --out <scratch>
$ scripts/jev_search.py --target zopfli --proposer jev --vocab v6 --print-state \
    --source-excerpt {full,none} --marks targets/zopfli/jev-marks.txt \
    --sites targets/zopfli/sites.json --site-set oracle.selected_keys_top6 \
    --baseline-dir artifacts/zopfli-sites/baseline --out <scratch>
$ diff <full> <none>
$ scripts/jev_noexcerpt_probe.py render
```

`diff` of the two `--print-state` outputs: every removed line is an excerpt
line (a `file:line (lines a-b, ...)` header or a numbered source line) or
the state-format string (4 state headers + 2 phase banners per target);
nothing else is removed (checked with a filter: 0 other `<` lines on either
target). Added lines: the placeholder (hintbench 21, zopfli 16) and, where
the loop's leaf file has no quotable source under `full` (std-library leaf
locations), the header "source at the loop's innermost location ..." plus a
placeholder (hintbench 5, zopfli 1). The latter is what L13 sent too
(`_NoSource.excerpt` answers for any non-empty path); it is kept so that the
driver's `none` is L13 to the byte. `--print-state` output (whole text,
state + questions): hintbench 155 154 -> 119 890 bytes, zopfli 150 131 ->
111 109.

**L13 identity (done, no HTTP).** `jev_noexcerpt_probe.py render` rebuilds
study 2's v6 round-1 phase-A/B requests with the driver's `none` and
compares them with the L13 bodies study 2 logged
(`docs/experiments/jev-prompt-study-2/ps2-<t>.jsonl.gz`, repeat 1): hintbench
A 280/280 lines, B 212/212, zopfli A 247/247, B 189/189; **exactly one line
differs in each** (line 1, `state-v6.0-noexcerpt-2026-09-25` vs
`state-v6.0-2026-09-23`), and the questions are identical. So §174's L13
numbers are numbers for this rendering.

**Bodies probed** (`artifacts/jev-noexcerpt-probe/bodies/`; HTTP body bytes
= `json.dumps({"model","state","questions"})`, what the gateway receives).
Rendered as `--print-state` renders round 1: hintbench `--vocab v5`, zopfli
`--vocab v6`, phase A (function sites + the build knob), phase B (loop
sites), and the phase-B exploration request (`--explore 2`, KEEP_DEFAULT
assumed everywhere).

| target | body | full bytes | none bytes | none / full |
|---|---|--:|--:|--:|
| hintbench | A (8 q) | 65 317 | 46 266 | 0.71 |
| hintbench | B (4 q) | 44 475 | 36 180 | 0.81 |
| hintbench | explore (2 q) | 25 995 | 21 638 | 0.83 |
| zopfli | A (6 q) | 54 552 | 38 594 | 0.71 |
| zopfli | B (5 q) | 51 605 | 38 445 | 0.74 |
| zopfli | explore (2 q) | 23 549 | 17 990 | 0.76 |

The state shrinks by 41-53 %, the body by 17-29 %: the questions (which
carry the verdict block) are unchanged and are now most of the body.

**Protocol.**

```
$ scripts/jev_noexcerpt_probe.py probe      # -> docs/experiments/jev-prompt-study-2/noexcerpt/probe.{jsonl,log}
$ scripts/jev_noexcerpt_probe.py table
$ scripts/jev_noexcerpt_probe.py choice     # -> .../noexcerpt/nx-{hintbench,zopfli}.{jsonl,log}
$ scripts/jev_prompt_study2.py report --targets hintbench zopfli --variants L13 \
    --run-prefix nx --log-dir docs/experiments/jev-prompt-study-2/noexcerpt
```

1. *Landing probe.* Each of the 12 bodies is sent **10 times**, **one HTTP
   attempt per send** (`retries = 1`, so the status is the gateway's answer
   to that one attempt, no retry hides it), **3 s** between sends, strictly
   sequential (no concurrency; the 429s of earlier passes came from
   overlapping senders). Order: for send 1..10, for target, for body, the
   full/none pair --- full first on odd sends, none first on even sends.
   Logged per send: bytes, sha256, status, latency (JevClient JSONL/.log,
   `source_excerpt` on every line; no Authorization header).
2. *Choice re-check.* Study 2's v6 phase-A and phase-B requests rendered by
   the driver with `none` (byte-identical to L13 apart from line 1, above),
   3 repeats per target, hintbench and zopfli, the driver's retry policy
   (`jev-opt.toml [jev]`: up to 200 attempts / 600 s, 2 re-sends). Scored
   with study 2's own `report` against `truth.json` (MDE v2, decision 106).
   hintbench is scored under **v6** (study 2's vocabulary), not v5, so that
   the loop candidate set is L13's.

**Metrics.** Per body and condition: request bytes; landed / sends;
mean sends to land (= sends / landed, since there is no retry inside a
send); status counts. Choice re-check: fn argmax hits, k2 argmax, fn harm
argmax, loop argmax hits, loop harm argmax, P(best) at the loop targets
(k3/k5/k8, `squeeze.rs:325`), median [min, max] over 3 repeats.

**Rule** (`none` is adopted as the default for NEW runs if both hold;
frozen comparisons keep `full` whatever the outcome):

* **(a) Landing.** Summed over the 6 bodies, `none` lands at least as often
  as `full` in this probe (landed_none >= landed_full out of 60 each). A
  per-body table is reported beside it. If both land 60/60 (a good day),
  (a) holds on a tie and **says nothing about size dependence**; it is then
  recorded as "not informative", not as evidence that size matters.
* **(b) The L13 bar**, from §174 (the evidence for this exact rendering):
  (b1) functions: hintbench fn hits >= 7/8 with k2 argmax >= 2/3 repeats,
  jaq fn hits >= B0's 13/15 with harm argmax <= B0's 0/5 --- §174 L13:
  hintbench 7 [7, 7]/8, k2 3/3, jaq 13 [13, 13]/15, harm 0 --- **holds**.
  (b2) loops no worse than B0 (median loop argmax hits >= B0's, median loop
  harm argmax <= B0's, on hintbench and zopfli). **Stated before sending,
  from §174's own table: (b2) does not hold on hintbench.** L13 loop hits
  0 [0, 1]/4 vs B0 1 [1, 1]/4 and harm argmax 1 [0, 1]/4 vs 0 [0, 0]/4: k4
  flips from KEEP_DEFAULT to `vectorize_width_16` (oracle-harmful) in
  repeats 1 and 3 (P 0.43, 0.45; B0 k4 KEEP at 0.53-0.56). zopfli loops are
  unchanged (4/5, harm 0/2). The task statement's "loops unchanged" is
  therefore true on zopfli only; this is recorded, not corrected away.
* **(c) Reproduction** (reported, not a gate): the re-check's medians of fn
  hits and loop hits equal §174's L13 medians on both targets.

Reading, fixed now: (a) holds and (b1)+(b2) hold -> adopt `none` for new
runs. (a) holds, (b1) holds, (b2) fails -> **not adopted as the default**;
`none` stays an opt-in option, and the loop regression is named as the
reason (a phase-A-only `none` would be a new, unmeasured variant and is only
proposed). (a) fails -> not adopted.
