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
>
> That is checked against the artifacts, not asserted: `tests/test_target_chain_artifact.py` reads every committed `*_complex.cif` and requires exactly one chain to equal the native target in `target/P04626_domain_IV.pdb`.

| designer | designs | mean ipTM | median ipTM | mean PAE-int | mean affinity | success@0.65 | backbones hit | est. cost (USD) | GPU-h |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| rfdiff_mpnn | 20 | 0.508 | 0.492 | 15.6 | — | 8/20 = 40% (15%–70%) | 5/10 | 0 | 0.722 |

**ipTM** / **PAE-interaction** / **affinity** are the validator's (Boltz-2) interface-confidence and predicted-affinity outputs; **success@0.65** is the fraction of designs with ipTM ≥ 0.65, with a 95% interval **bootstrapped over backbones**, not over designs: ProteinMPNN produces several sequences per RFdiffusion trajectory, so the designs are not independent trials and a binomial interval over them reads narrower than the run earns. **backbones hit** is the fraction of trajectories that yielded any design over the bar, which is the count of independent attempts that worked. Read the interval, not the point: two runs of the same target differing only in seed returned 2/20 and 6/20, which a Fisher exact test cannot separate. Cost is the `bindsight.cost` estimate for the run on the chosen backend.

> **This success rate is withdrawn as a measure of design quality.** A paired control folded each of these twenty designs in one job alongside a shuffle of its own sequence — same length, same amino-acid composition, same target, same validator, same card, same session. Under a seeded validator averaging five diffusion draws per binder, the **shuffles pass more often than the designs**: 50% of shuffles clear 0.65 against 30% of designs. The paired difference is −0.043 (95% CI −0.142 to +0.054, exact sign-flip p = 0.40), and 9 of 20 designs beat their own shuffle where 10 is chance.
>
> Two causes were found in the pipeline and fixed — the validator and the designer were both invoked without a seed, so every number in this table is a single unseeded draw of a sequence that was itself an unseeded draw. Refolding these twenty sequences moves ipTM by a median of 0.172, against a measured per-draw spread of 0.139. But the fixes did not rescue the result: five times the sampling effort moved it slightly further against the designs, and 85% of the remaining spread is real pair-to-pair variation that no amount of resampling reduces.
>
> The numbers in this table are real Boltz-2 outputs. What is withdrawn is the claim that the rate measures the designs. See `benchmarks/calibration/README.md`.
