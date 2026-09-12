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

> **This success rate is withdrawn as a measure of design quality.** A paired control folded each of these twenty designs in one job alongside a shuffle of its own sequence — same length, same amino-acid composition, same target, same validator, same card. Designs and shuffles cleared 0.65 at the *same* rate (40% and 40%), the paired difference was +0.030 (95% CI −0.070 to +0.127, exact sign-flip p = 0.57), and one shuffle scored 0.815 — above nineteen of the twenty designs. The run bounds any real advantage at about 0.14 ipTM rather than showing there is none.
>
> A cause was found and fixed: Boltz-2 builds structures by diffusion, and the validator was invoked with neither `--seed` nor `--diffusion_samples`, so every number here is a single unseeded draw. Refolding the same twenty sequences moved ipTM by a median of 0.129 and flipped eight of twenty verdicts. The numbers in this table are real outputs; what is withdrawn is the claim that they measure the designs. See `benchmarks/calibration/README.md`.
