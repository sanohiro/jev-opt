# Marks by rule ∪ Jev gray zone: API check (results.md 179, decision 109)

Script `scripts/target_marks.py`; outputs `targets/<t>/jev-marks.jev.txt` and
`targets/<t>/jev-marks.jev.rationale.md`.

| file | what |
|---|---|
| `tm-<target>.jsonl.gz`, `tm-<target>.log` | every gray-zone request/response (no Authorization header), per-request latency/tokens/cost, per-run totals (zopfli, jaq; hintbench sent none) |
| `<target>-table.json.gz` | the classified table (`--json`): rows with rule (seed / covered / gray / excluded), P per repeat, median, final lines |
| `run.log` | console of the first `--jev` pass (the report writer crashed after the requests landed; see results.md 179.2) |

Re-derive the files without sending anything: gunzip the JSONL into
`artifacts/jev-marks/<t>/` and run `scripts/target_marks.py --target <t> --jev --resume`.
