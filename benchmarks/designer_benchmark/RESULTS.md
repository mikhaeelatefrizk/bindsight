# bindsight designer benchmark — results

- Generated: `2026-06-19T20:42:17+00:00` · bindsight `0.1.0`
- Backend: `kaggle` · validator: `boltz2` · trajectories/target: 10
- Targets: ERBB2 domain IV (UniProt P04626, residues 511-652; trastuzumab epitope)

| designer | designs | mean ipTM | median ipTM | mean PAE-int | mean affinity | success@0.65 | est. cost (USD) | GPU-h |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| rfdiff_mpnn | 20 | 0.598 | 0.606 | — | — | 40% | — | — |

**ipTM** / **PAE-interaction** / **affinity** are the validator's (Boltz-2) interface-confidence and predicted-affinity outputs; **success@0.65** is the fraction of designs with ipTM ≥ 0.65. Cost is the `bindsight.cost` estimate for the run on the chosen backend.

## Run provenance

- **Real GPU run** — backend `kaggle`, GPU `Tesla P100-PCIE-16GB (Kaggle free)`, date `2026-06-19T20:42:17+00:00`, bindsight `0.1.0`.
- **Target:** ERBB2 domain IV (UniProt P04626, residues 511-652; trastuzumab epitope). The full ERBB2 (1255 aa) does not fit a free 16 GB GPU, so binders are designed against extracellular **domain IV** — the clinically validated trastuzumab epitope — extracted from the AlphaFold model (`prepare_erbb2_target.py`).
- **Pipeline:** RFdiffusion → ProteinMPNN → Boltz-2, run via the split-environment Kaggle kernel (`bindsight.runners.kaggle_kernel`).
- **Affinity is N/A** for protein binders: Boltz-2 affinity prediction is ligand-only, so `affinity` is blank; **ipTM** (and PAE-interaction) are the de novo binder-quality metrics, with **success@0.65** the standard ipTM≥0.65 success criterion.
- Per-design metrics and the designed PDBs are in `binders/` and `results.json`.
