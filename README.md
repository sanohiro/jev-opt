# jev-opt

An experiment: can Jev (TypeSafe AI's small, fast, cheap decision model) make
an already strongly optimised Rust binary (`opt-level=3`, `target-cpu=native`,
fat LTO, one codegen unit, PGO) faster by choosing LLVM hints for the
functions that are marked? Hints are function attributes and loop metadata
applied by our LLVM pass plugin; the target's sources are never modified, and
speed is measured, never assumed.

For depth: `SPEC.ja.md` (the spec), `HANDOFF.ja.md` (state and plan),
`docs/search-driver.md` (the driver), `docs/decisions.ja.md` (numbered
decisions), `results.md` (every measurement, append-only), `AGENTS.md`
(working rules).

## Prerequisites

* **Toolchain**: pinned in `rust-toolchain.toml` (a nightly with its own LLVM;
  the plugin is built against the same LLVM major).
* **LLVM plugin**: `scripts/build_plugin.sh` -> `plugin/build/libjevplugin.so`
  (see `plugin/README.md` for modes, env vars and the plan schema).
* **`perf` is a required external command.** `scripts/perf_local.sh setup`
  installs it without root (Debian `linux-perf` unpacked into
  `/tmp/perf-local`; `scripts/perf_local.sh path` prints the wrapper). On WSL2
  the kernel needs `CONFIG_PERF_EVENTS`; with `perf_event_paranoid` 2 only
  user-mode cycles (`cycles:u`) are sampled. The driver's marks generation
  refuses to take a profile without it ("run `scripts/perf_local.sh setup`
  first").
* **Jev**: two routes (decision 111), picked by `--jev-endpoint` >
  `JEV_ENDPOINT` (env/`.env`) > `[jev] endpoint` (`jev-opt.toml`) > auto
  (whichever key below is present; both present keeps `gateway`). **gateway**
  (default, every run before decision 111): a Vercel AI Gateway key,
  `AI_GATEWAY_API_KEY` (free Hobby tier is enough). **direct**: TypeSafe's own
  API, `TYPESAFE_API_KEY` --- no free tier, $0.042 / 1M input tokens, output
  free (roughly $0.03 for a 5-round search's ~0.6M input tokens); implemented
  from documentation only (docs.typesafe.ai) and **not exercised against the
  live API in this project** (no TypeSafe key here). Shape of both in
  `.env.example`; `.env` is git-ignored and neither key is ever printed or
  logged. Before trusting `--jev-endpoint direct` with a real key, run the
  one-request smoke check, which prints the route chosen, the HTTP status
  and the response's top-level keys and exits 0 only if an answer landed:

  ```bash
  scripts/jev_search.py --jev-smoke --jev-endpoint direct
  ```

## Marks file

`targets/<t>/jev-marks.txt` (frozen, written by a human or by Claude as the
human's proxy) or the generated `targets/<t>/jev-marks.jev.txt`. It says
**where** jev-opt works, never what to do there.

* One demangled Rust v0 function name per line, spelled exactly as the tools
  print it (`llvm-symbolizer`, `llvm-nm -C`; `perf_hotness.py` output).
* `#` starts a comment **only as the first non-space character of a line**
  (a closure is spelled `{closure#3}`); blank lines are ignored.
* Optional share comment: the comment block directly above a name (no blank
  line in between) may carry `share N%` and `reach N%`; the driver reads them
  with `shares_from_marks_file` (`scripts/jev_search.py`):
  `MARK_SHARE_RE = re.compile(r"\bshare\s+(\d+(?:\.\d+)?)%")` and
  `MARK_REACH_RE = re.compile(r"\breach\s+(\d+(?:\.\d+)?)%")`, e.g.
  `# share 29.29%, reach 29.29% (...)`.
* Matching (plugin rule, `plugin/README.md` "Marks file"): a line matches a
  function whose full demangled name equals it, continues with `::` (every
  monomorphization `::<…>`, closures, inner items) or ends with `::` + the
  line. Function attributes go on the mark's own functions and every
  monomorphization but not on its closures unless `--fn-attr-scope all`.
* Resolution in `scripts/jev_search.py` (decision 109): explicit `--marks FILE`
  -> the newest generated `jev-marks.jev[.vN].txt` -> generated once by
  `scripts/target_marks.py` (mechanical seed = top N by reach ∪ top N by self;
  every other function over 1% is a Jev mark/skip question, 3 repeats, median
  P >= 0.5). `--marks-regenerate` writes the next versioned file. Frozen files
  are never rewritten; the manifest records which file was used, its sha256
  and how it was produced.
* A generated file's rationale is `jev-marks.jev.rationale.md` next to it;
  its Jev requests/responses are in `artifacts/jev-marks/<t>/tm-<t>.jsonl`
  (named in the file's `# Jev log:` header line).

## Sites file

`targets/<t>/sites.json` (+ `sites.md`) lists the marked functions and the
loops inside them, from the plugin's `dump`, produced by
`scripts/target_sites.sh` (`base`, `dump`, `allkeys`, `sites`, `baseline`).
The loop-site cap is a pre-registered rule (`SITE_CAP_RULE`, default
`no_profile,trip_lt_2,per_mark:2,top:6`) and the driver is frozen to one list
with `--site-set` (e.g. `oracle.selected_keys_top6`). See
`docs/search-driver.md` "Sites for a new target".

## Quick start for a new target

```bash
export TARGET=mytarget     # `export`, not a one-command assignment (decision 31)
# 1. add the recipe to scripts/target_common.sh: MANIFEST, BIN_NAME,
#    WORKLOADS (holdout), TRAIN_WORKLOADS (search/training), TRAIN_INPUTS (PGO),
#    CORRECTNESS_IN, FIXED_RUSTFLAGS if the target needs one
scripts/target_pgo_baseline.sh            # the frozen PGO profile, once
scripts/target_sites.sh base              # plugin-off baseline
scripts/target_sites.sh marks             # dry run: seed / gray / exclusions
MARKS_JEV=1 scripts/target_sites.sh marks # profile if missing, ask Jev, write
export MARKS=$PWD/targets/$TARGET/jev-marks.jev.txt
scripts/target_sites.sh dump && scripts/target_sites.sh allkeys
scripts/target_sites.sh sites && scripts/target_sites.sh baseline
```

Then the **staged oracle** under `--protocol v2` (function attributes first,
then only the loops LLVM actually touches; decisions 103, 104): `jev_search.py
--proposer oracle --site-set … --baseline-dir artifacts/$TARGET-sites/baseline`.
**Stop rule**: if the oracle finds no good site (above the MDE, same sign in
both batches), record "no ceiling" and do not run the search (decision 103).
Otherwise run Jev n=3 and random n=3 on the same marks, sites and vocabulary,
and report per-feature effects against the random control.

## Measurement rules

One timing at a time on the machine: never run two benchmarks concurrently,
and check `ps -eo cmd | grep -E 'bench.py|jev_search'` before starting one.
Every timed executable path has a pinned argv[0] length of 80 bytes (decision
97). The MDE comes from the target's own A/A run (aggregate half-width x 2,
floor 1%; decision 106). Never write a target's input files while a timing
runs (decision 99). A plan whose output differs bitwise from the baseline is
rejected, and every arm carries `-Cllvm-args=-hints-allow-reordering=false`.
