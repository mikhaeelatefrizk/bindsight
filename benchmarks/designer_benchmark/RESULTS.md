# bindsight designer benchmark — results

> ## ⚠️ These results predate the ProteinMPNN target-chain fix (v0.2.1)
>
> This run invoked ProteinMPNN **without `--pdb_path_chains`**, so ProteinMPNN
> redesigned the ERBB2 target chain in addition to the binder chain. Every design
> below was therefore optimised against a **partly-invented HER2 surface**, and then
> scored by Boltz-2 against the **native** one. The mismatch is a protocol error, not
> a measurement error: the ipTM / PAE-interaction values are genuine Boltz-2 output
> and reproduce exactly from the committed artifacts, and nothing here has been
> altered.
>
> What that means for the numbers: they are **not** a valid estimate of what
> bindsight's design half achieves against ERBB2 domain IV. They could be optimistic
> (the binders fit a surface the designer was free to co-adapt) or pessimistic (the
> co-adapted target drifted away from the native epitope) — the run cannot tell you
> which. Treat mean ipTM 0.585 / best 0.840 / 50 % success@0.65 as **provisional**.
>
> The fix ships in v0.2.1 (the target chain is now pinned via `--pdb_path_chains`, so
> only the binder chain is redesigned). A corrected re-run on the same target and the
> same free-GPU protocol will supersede this file; the pre-fix numbers stay here for
> comparison.

- Generated: `2026-06-25T21:11:21+00:00` · bindsight `0.2.0` (**pre-fix protocol** — see above)
- Backend: `kaggle` · validator: `boltz2` · trajectories/target: 10
- Targets: ERBB2 domain IV (UniProt P04626, residues 511-652; trastuzumab epitope)

| designer | designs | mean ipTM | median ipTM | mean PAE-int | mean affinity | success@0.65 | est. cost (USD) | GPU-h |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| rfdiff_mpnn | 20 | 0.585 | 0.663 | 13.7 | — | 50% | — | — |

**ipTM** / **PAE-interaction** / **affinity** are the validator's (Boltz-2) interface-confidence and predicted-affinity outputs; **success@0.65** is the fraction of designs with ipTM ≥ 0.65. Cost is the `bindsight.cost` estimate for the run on the chosen backend.

## Run provenance

- **Real GPU run** — backend `kaggle`, GPU `Tesla P100-16GB (Kaggle free)`, date `2026-06-25T21:11:21+00:00`, bindsight `0.2.0`.
- **Target:** ERBB2 domain IV (UniProt P04626, residues 511-652; trastuzumab epitope). The full ERBB2 (1255 aa) does not fit a free 16 GB GPU, so binders are designed against extracellular **domain IV** — the clinically validated trastuzumab epitope — extracted from the AlphaFold model (`prepare_erbb2_target.py`).
- **Pipeline:** RFdiffusion → ProteinMPNN → Boltz-2, run via the split-environment Kaggle kernel (`bindsight.runners.kaggle_kernel`).
- **Known protocol defect (pre-v0.2.1):** ProteinMPNN was called without `--pdb_path_chains`, so it redesigned the target chain along with the binder chain. See the warning at the top of this file — the designs were optimised against a partly-invented target and validated against the native one.
- **Metrics:** **ipTM** is the primary de novo binder-quality metric and **success@0.65** is the standard ipTM≥0.65 criterion. **PAE-interaction** is the mean inter-chain predicted aligned error (Å) from the Boltz-2 complex (lower = more confident interface). The **affinity column is intentionally blank** — Boltz-2 affinity prediction is ligand-only and these are protein binders.
- The real Boltz-2 **predicted complex structures** are staged in `binders/` as `<binder_id>_complex.cif` (the actual folded binder–target complex behind each ipTM), alongside the ProteinMPNN FASTAs, per-design `metrics.jsonl`, and `results.json`.

## Developability (sequence biophysics)

Deterministic ProtParam descriptors for each designed binder are in
[`binders/developability.tsv`](binders/) — instability index, GRAVY, isoelectric point,
aromaticity, free cysteines, aggregation-prone fraction, and a composite
`developability_score` ∈ [0, 1]. Across the 20 designs: mean `developability_score`
**0.65**, **9/20** predicted stable (ProtParam instability index < 40); best
`binder_3_seq1` (0.93), worst `binder_8_seq0` (0.45). Reproduce with
`python benchmarks/designer_benchmark/score_developability.py`. (No GPU, no network.)

## Sequence-space visualization (ESM-2 → PCA)

A ProtSpace-style view of the binder set, computed with a real protein-language model
(**ESM-2 `esm2_t6_8M`**) on a CPU: each binder's mean-pooled embedding projected to 2-D.
Per-binder PC1/PC2 in [`binders/embedding_coords.tsv`](binders/), scatter in
[`binders/embedding_space.png`](binders/embedding_space.png). A *pre-GPU* triage — see which
designs cluster or are outliers before spending GPU on validation. Reproduce with
`pip install 'bindsight[embed]'` then `python benchmarks/designer_benchmark/embed_binders.py`.
