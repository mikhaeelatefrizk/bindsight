# bindsight designer benchmark — results

- Generated: `2026-09-07T06:05:26+00:00` · bindsight `0.2.2`
- Backend: `kaggle` · validator: `boltz2` · trajectories/target: 10
- Targets: ERBB2
- GPU: `Tesla T4-16GB (Kaggle free)`
- Code: working-tree wheel bindsight-0.2.2-py3-none-any.whl

> **The target chain was held fixed.** ProteinMPNN is invoked with
> `--pdb_path_chains` so it redesigns the binder only. A superseded run
> omitted that flag, rewrote the target as well, and therefore optimised
> its designs against a partly-invented surface before scoring them
> against the native one; its figures are withdrawn. Every design here
> carries a target chain byte-identical to the prepared structure.

| designer | designs | mean ipTM | median ipTM | mean PAE-int | mean affinity | success@0.65 | est. cost (USD) | GPU-h |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| rfdiff_mpnn | 20 | 0.508 | 0.492 | 15.6 | — | 40% | 0 | 0.722 |

**ipTM** / **PAE-interaction** / **affinity** are the validator's (Boltz-2) interface-confidence and predicted-affinity outputs; **success@0.65** is the fraction of designs with ipTM ≥ 0.65. Cost is the `bindsight.cost` estimate for the run on the chosen backend.
