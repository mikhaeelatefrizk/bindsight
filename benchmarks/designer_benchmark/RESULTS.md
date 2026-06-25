# bindsight designer benchmark — results

- Generated: `2026-06-19T22:00:45+00:00` · bindsight `0.1.0`
- Backend: `kaggle` · validator: `boltz2` · trajectories/target: 10
- Targets: ERBB2 domain IV (UniProt P04626, residues 511-652; trastuzumab epitope)

| designer | designs | mean ipTM | median ipTM | mean PAE-int | mean affinity | success@0.65 | est. cost (USD) | GPU-h |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| rfdiff_mpnn | 20 | 0.598 | 0.606 | — | — | 40% | — | — |

**ipTM** / **PAE-interaction** / **affinity** are the validator's (Boltz-2) interface-confidence and predicted-affinity outputs; **success@0.65** is the fraction of designs with ipTM ≥ 0.65. Cost is the `bindsight.cost` estimate for the run on the chosen backend.

## Run provenance

- **Real GPU run** — backend `kaggle`, GPU `Tesla P100-PCIE-16GB (Kaggle free)`, date `2026-06-19T22:00:45+00:00`, bindsight `0.1.0`.
- **Target:** ERBB2 domain IV (UniProt P04626, residues 511-652; trastuzumab epitope). The full ERBB2 (1255 aa) does not fit a free 16 GB GPU, so binders are designed against extracellular **domain IV** — the clinically validated trastuzumab epitope — extracted from the AlphaFold model (`prepare_erbb2_target.py`).
- **Pipeline:** RFdiffusion → ProteinMPNN → Boltz-2, run via the split-environment Kaggle kernel (`bindsight.runners.kaggle_kernel`).
- **Metrics:** **ipTM** is the primary de novo binder-quality metric here, and **success@0.65** is the standard ipTM≥0.65 success criterion. The **PAE-interaction and affinity columns in the table above are conditional and intentionally blank for this protein-binder run** — Boltz-2 affinity prediction is ligand-only, and PAE-interaction comes from Boltz-2's full-PAE output (not staged here).
- Per-design metrics plus the designed binder PDBs **and FASTAs** are in `binders/` (and `results.json`).

## Developability (sequence biophysics)

Deterministic ProtParam descriptors for each designed binder are in
[`binders/developability.tsv`](binders/) — instability index, GRAVY, isoelectric point,
aromaticity, free cysteines, aggregation-prone fraction, and a composite
`developability_score` ∈ [0, 1]. Across the 20 designs: mean `developability_score`
**0.69**, **11/20** predicted stable (ProtParam instability index < 40); best
`binder_4_seq1` (0.88), worst `binder_9_seq1` (0.49, hydrophobic/aggregation-prone).
Reproduce with `python benchmarks/designer_benchmark/score_developability.py`. (No GPU,
no network — computed from the committed FASTAs.)

## Sequence-space visualization (ESM-2 → PCA)

A ProtSpace-style view of the binder set, computed with a real protein-language model
(**ESM-2 `esm2_t6_8M`**) on a CPU: each binder's mean-pooled embedding projected to 2-D.
Per-binder PC1/PC2 in [`binders/embedding_coords.tsv`](binders/), scatter in
[`binders/embedding_space.png`](binders/embedding_space.png). This is a *pre-GPU* triage —
see which designs cluster or are outliers before spending GPU on validation. Reproduce with
`pip install 'bindsight[embed]'` then `python benchmarks/designer_benchmark/embed_binders.py`.
