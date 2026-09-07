# bindsight designer benchmark — results

- Generated: `2026-09-07T03:37:11+00:00` · bindsight `0.2.2`
- Backend: `kaggle` · validator: `boltz2` · trajectories/target: 10
- Targets: ERBB2

| designer | designs | mean ipTM | median ipTM | mean PAE-int | mean affinity | success@0.65 | est. cost (USD) | GPU-h |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| rfdiff_mpnn | 0 | — | — | — | — | — | 0 | 0.722 |
| bindcraft | 0 | — | — | — | — | — | 0 | 2.89 |
| boltzgen | 0 | — | — | — | — | — | 0 | 0.666 |

**ipTM** / **PAE-interaction** / **affinity** are the validator's (Boltz-2) interface-confidence and predicted-affinity outputs; **success@0.65** is the fraction of designs with ipTM ≥ 0.65. Cost is the `bindsight.cost` estimate for the run on the chosen backend.
