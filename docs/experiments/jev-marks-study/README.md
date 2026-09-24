# Marks study (API only) --- can Jev choose the marks from perf?

Pre-registration `results.md` 176 (+ amendment 176.7), results 177,
decision 108. Script `scripts/jev_marks_study.py`.

| file | what |
|---|---|
| `ms-<target>.jsonl.gz`, `ms-<target>.log` | input set v1 (176.1): every request/response (no Authorization header), per-request latency/tokens/cost, per-run totals |
| `ms2-<target>.jsonl.gz`, `ms2-<target>.log` | input set v2 + hybrid Q3 (176.7) |
| `run-v1.log`, `run-v2.log` | the sender's console output |
| `inputs.json.gz`, `inputs-v2.json.gz` | the function tables the states were rendered from (`build`) |
| `*-inline-structure.tsv.gz` | `scripts/inline_structure.py` output the v2 `insns` / `loops` / `hosts` columns come from |
| `scores*.json.gz`, `report.md`, `report-v2.md` | `score` output: every readout per repeat, per-function P(mark) / Score, reach rank |

Re-score from these files: gunzip into `artifacts/jev-marks-study/` and run
`scripts/jev_marks_study.py score` / `--inputs v2 score` (zopfli coverage
needs `artifacts/zopfli-marks/*.data` and the verified zopfli binary).
| `ms3-<target>.jsonl.gz`, `ms3-<target>.log`, `run-v3{a,b,c}.log` | phase 3 (176.8): M1-M5 |
| `scores-v3.json.gz`, `report-v3.md` | phase-3 scores (`--inputs v2 score --run-prefix ms3`) |
