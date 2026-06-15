# bindsight designer benchmark — results

<!--
Fill this in from a REAL GPU run (see DESIGNER_BENCHMARK.md). Do NOT paste mock
numbers here. The harness writes a populated RESULTS.md under the --out dir;
copy its table below, then record the run metadata.
-->

- Date: `YYYY-MM-DD`
- bindsight version: `vX.Y.Z`
- Backend / GPU: `modal A100-40GB` (or local_docker / kaggle …)
- Validator: `boltz2`
- Trajectories per target: `50`
- Targets: ERBB2, EGFR, MSLN, CD33, IL3RA
- `results.json`: `benchmarks/designer_benchmark/run/results.json`

| designer | designs | mean ipTM | median ipTM | mean PAE-int | mean affinity | success@0.65 | est. cost (USD) | GPU-h |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| rfdiff_mpnn | — | — | — | — | — | — | — | — |
| bindcraft   | — | — | — | — | — | — | — | — |
| boltzgen    | — | — | — | — | — | — | — | — |

## Notes

<!-- Observations: which designer gave the highest ipTM / best affinity / best
cost-quality trade-off; any per-target outliers (see results.json per_target). -->
