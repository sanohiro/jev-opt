# argv[0] class check: jaq and zopfli

Pre-registration: `results.md` §163. Results: `results.md` §164 (decision 99).
Both targets: NULL, no class effect distinguishable from A/A noise at
lengths 64/80/96/112 (classes c80/c96/c112/c128).

zopfli's first panel (`zopfli-run1-contaminated-readout.txt`) ran while
`targets/zopfli/workloads/gen.py` rewrote the holdout inputs mid-panel; it
is superseded by the clean rerun (`zopfli-*`). Timing evidence (min/median
ratios >= 0.984 per leg x case) shows no short-read outlier either way.
