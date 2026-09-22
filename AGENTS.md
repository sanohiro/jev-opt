# AGENTS.md — working rules for any agent (Claude, Codex, human) on jev-opt

Read this first, then `HANDOFF.ja.md` (full handoff, Japanese), then `SPEC.ja.md` (the spec) and
`docs/decisions.ja.md` (numbered log of what we learned and what we therefore do or skip).

## What this project is

An experiment: **can Jev (TypeSafe AI's small, fast, cheap decision model) make a Rust binary
faster by choosing compiler hints for functions that a human or a strong model has marked?**
The baseline is already strong (`-Copt-level=3 -Ctarget-cpu=native -Clto=fat -Ccodegen-units=1`
+ PGO). Speed is measured, never assumed. Hints are LLVM function attributes and loop metadata
applied by our LLVM pass plugin; target sources are never modified.

## The owner's non-negotiables (do not relitigate)

1. **The subject is Jev's hints.** Anything that makes the binary faster by other means
   (training-set selection, source edits, picking a different program) is preparation or out
   of scope, not a result. Do not change the thesis; only the owner can.
2. **Preparation may be done by a strong model or a human** (profiling, marking hot functions,
   enumerating candidates). Claude/Codex are the human's proxy, not part of the product. But
   preparation must not choose hints per site — that would make the strong model the optimizer.
   The hint vocabulary is fixed and identical for every mark (`SPEC.ja.md` §1(2)).
3. **Truth is the oracle.** A hint is "good" only if a one-factor sweep measured it faster than
   baseline with a confirmation batch. Claude's own predictions scored 1/8 on the hint
   benchmark; never use them as ground truth.
4. **Every Jev decision is an independent toggle** and is measured by ablation (with a random
   proposer as the control). Report per-feature effects, not a bundled total.
5. **Correctness gate:** a plan whose program output differs bitwise from baseline is rejected,
   even if faster. All arms carry `-Cllvm-args=-hints-allow-reordering=false`.
6. **Honesty over narrative.** Null and negative results are recorded as such. If a measurement
   fails or is skipped, say so in `results.md`.

## How to work here

- **One target measured at a time on this machine.** Never run two timing benchmarks
  concurrently (we lost a day to that). Builds while another agent times are tolerated only when
  small; check `ps -eo cmd | grep -E 'bench.py|jev_search'` first.
- **Never edit a running shell script** (`scripts/*.sh`) — bash re-reads it mid-run and dies.
- **Frozen things** (vocabulary texts in `scripts/jev_vocab.py`, state templates, site sets in
  `targets/*/sites.json`, marks, `EXPECTED.md` §1–§4): changing them means re-running every
  comparison that used them. Add a new version instead of editing an old one.
- **Record decisions.** Any time an experiment changes what we do or stop doing, append a
  numbered entry to `docs/decisions.ja.md` in the form 知見 → 判断 → 影響 (Japanese), with a
  pointer to the `results.md` section holding the numbers.
- **Record results.** `results.md` is append-only: one `##` section per experiment, every number
  next to the command that produced it, pre-registered rules stated before the numbers.
- **Jev logs.** Every request/response to Jev is logged as JSONL plus a human-readable `.log`
  (per-request latency/tokens/cost, per-run totals). The `Authorization` header is never logged.
  Hand-sent samples live in `docs/jev-samples/`.
- **Language.** Code, comments, commit messages, PR text, README/AGENTS, CLI output, `results.md`:
  **English**. `SPEC.ja.md`, `docs/decisions.ja.md`, `HANDOFF.ja.md`, explanations to the owner:
  **Japanese**. An English `SPEC.md` is planned once the spec settles.
- **Commits.** Small, explicit paths (`git add <files>`, never `-A`), English message, end with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` when a Claude agent authored it
  (use your own model line if you are not Claude). Do not push unless the owner asks.
- **Secrets.** `.env` holds `AI_GATEWAY_API_KEY` (Vercel AI Gateway, Hobby plan, free tier is
  enough). It is git-ignored; never print or commit it. `.env.example` shows the shape.
- **`work/` is frozen** (old spec versions, review, hint catalogue, article draft). Do not
  maintain it; the owner will write the article later.

## Where things are

| Path | What |
|---|---|
| `SPEC.ja.md` | The spec (v0.5 + amendments; header lists reflected decisions) |
| `docs/decisions.ja.md` | Numbered knowledge/decision log (start at the end) |
| `HANDOFF.ja.md` | Full handoff: state, plan, pitfalls, owner's principles |
| `results.md` | All measurements, append-only, with commands |
| `docs/search-driver.md` | How `scripts/jev_search.py` works (vocab/state versions, readout, acceptance, exploration) |
| `docs/experiments/` | Per-experiment write-ups and logs |
| `plugin/` (`README.md`) | LLVM pass plugin: `off`/`dump`/`apply`/`apply-dump`, env vars, plan/report schema |
| `scripts/` | Driver, benchmarks, profiling, analysis (see HANDOFF for the map) |
| `targets/{toy,zopfli,oxipng,jaq,hintbench}` | Targets (submodules pinned; `jev-marks.txt`, `sites.json`, `EXPECTED.md`) |
| `jev-opt.toml`, `rust-toolchain.toml` | Config; pinned `nightly-2026-09-21` (LLVM 23.1.1) |
| `artifacts/`, `pgo/`, `remarks/`, `target-*/`, `third_party/` | Generated, git-ignored |

## Quick start for a new agent

```bash
cd ~/prj/jev-optimize
git log --oneline | head            # what happened last
tail -120 docs/decisions.ja.md      # latest decisions
sed -n '1,60p' HANDOFF.ja.md        # state and plan
scripts/jev_search.py --help
export TARGET=hintbench             # `export`, not a temporary assignment (bash quirk, decision 31)
```
