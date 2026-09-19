# Running the design half on a free Kaggle GPU

Everything here is prepared and tested up to the point where a real GPU is
needed. What remains is one command, and the credential that lets it run.

---

## 1. Install the API token (you, once)

bindsight never sees your key. You download it and place it yourself.

1. Open <https://www.kaggle.com/settings> → **API** → **Create New Token**.
   A `kaggle.json` downloads.
2. Move it to `%USERPROFILE%\.kaggle\kaggle.json` on Windows, or
   `~/.kaggle/kaggle.json` elsewhere.
3. Confirm it is picked up:

```bash
python -c "import kaggle; kaggle.api.authenticate(); print('kaggle: authenticated')"
```

Phone verification on your Kaggle account is also required before notebooks get
GPU and internet access. Kaggle prompts for it the first time you enable either.

---

## 2. Know the budget before you start

| | |
|---|---|
| GPU | T4, 16 GB, pinned explicitly |
| Weekly allowance | About 30 GPU-hours, renewing |
| Session cap | 12 hours |
| Persistent output | About 20 GB in `/kaggle/working` |
| Cost | Free, no card |

**The accelerator is pinned to a T4 on purpose.** Kaggle's default is a P100, and
Kaggle's own CLI documentation now warns that the P100 cannot run current
PyTorch, which ships no Pascal kernels. The failure mode is the worst kind:
`torch.cuda.is_available()` returns `True` and the first real kernel launch dies
hours into the run. The kernel now reads compute capability up front and exits
immediately if it is below 7.5, naming the fix.

There is **no API for your remaining quota.** Kaggle shows it in the notebook
editor sidebar and nowhere else. Plan against the weekly allowance, and check the
sidebar if a run behaves as though it has been throttled.

Every stage of the kernel now prints free disk on each volume and GPU memory in
use, so the constraints become numbers in the run log rather than assumptions.
This matters because Kaggle documents only the 20 GB persisted volume and never
publishes the scratch size, while the environment build needs roughly 60 GB.

---

## 3. The designer benchmark

One target, ERBB2 domain IV, the clinically validated trastuzumab epitope:

```bash
python benchmarks/run_designer_benchmark.py --backend kaggle --trajectories 10 --designers rfdiff_mpnn --targets ERBB2
```

Budget: roughly **1 GPU-hour**, about 3% of the weekly allowance. Most of the
wall-clock is the environment build, not the science. Restrict to
`rfdiff_mpnn`: the other two designers need more than 16 GB against a full
receptor and will fail after burning several minutes each.

**The GPU runs the code you have, and that is not free.** Remote backends
pip-install bindsight, and for this project's whole history that meant
`git+<repo>` with no ref — so every Kaggle run installed the default branch,
whatever was checked out locally. A benchmark launched to validate a fix ran the
unfixed code and said nothing about it; that is exactly how a "corrected"
re-run came back carrying pre-fix binder ids. The harness now builds a wheel
from your working tree and embeds it in the kernel, and `results.json` records
`bindsight_source` so the artifact names its own code. `--install-from-git` opts
out, and the log says what that costs.

The committed run is the one this produces: 20 designs, best ipTM 0.88,
8/20 = 40% success@0.65 (95% CI 15–70%, clustered over backbones), on a T4. Every design carries a target chain byte-identical to the
native domain IV, which is checked before the results are promoted.

> **This success rate is withdrawn as a measure of design quality.** A paired control folded each of these twenty designs in one job alongside a shuffle of its own sequence — same length, same amino-acid composition, same target, same validator, same card, same session. Under a seeded validator averaging five diffusion draws per binder, the **shuffles pass more often than the designs**: 50% of shuffles clear 0.65 against 30% of designs. The paired difference is −0.043 (95% CI −0.142 to +0.054, exact sign-flip p = 0.40), and 9 of 20 designs beat their own shuffle where 10 is chance.
>
> Two causes were found in the pipeline and fixed — the validator and the designer were both invoked without a seed, so every number in this table is a single unseeded draw of a sequence that was itself an unseeded draw. Refolding these twenty sequences moves ipTM by a median of 0.172, against a measured per-draw spread of 0.139. But the fixes did not rescue the result: five times the sampling effort moved it slightly further against the designs, and 85% of the remaining spread is real pair-to-pair variation that no amount of resampling reduces.
>
> The numbers in this table are real Boltz-2 outputs. What is withdrawn is the claim that the rate measures the designs. See `benchmarks/calibration/README.md`.


---

## 4. The complete provenance chain

The second thing worth spending quota on: one run that goes from RNA-seq counts
to a designed binder with an unbroken chain back to the patients. The discovery
half is already done and committed for fifteen cohorts, so this only needs the
design half.

Clear-cell kidney is the best cohort for it. CA9 ranks first of 291 candidates
there, so the top-ranked target is a real, strongly over-expressed antigen.

`examples/provenance_join.yaml` is committed for this, pointing at the study
cohort so the differential-expression cache hits, and carrying `top_n: 2`
because the chain is demonstrated by one binder and the second target only shows
the join is not a special case.

```bash
python -m bindsight.cli discover examples/provenance_join.yaml --out runs/join
python -m bindsight.cli design runs/join --backend kaggle
python -m bindsight.cli validate runs/join
python -m bindsight.cli rank runs/join
python -m bindsight.cli report runs/join --format html
python -m bindsight.cli export runs/join --out runs/join.crate.zip
```

Two targets at ten trajectories is roughly **2 GPU-hours** of design and
validation. Budget wall-clock, not GPU-hours: each target is a separate kernel
that rebuilds both micromamba environments first, and the committed two-target
run took 3h17m for CA9 and 1h29m for CD70 on a free T4 — 4h46m against about
two hours of actual science. The build dominates.

**Check the cost before launching.** Twenty targets at ten trajectories is about
10 GPU-hours, a third of the weekly allowance. Add `--dry-run` to the design
command to see the estimate without launching anything:

```bash
python -m bindsight.cli design runs/join --backend kaggle --trajectories 10 --dry-run
```

To spend less, cut the carry-forward in the discover config
(`params.target_discovery.top_n`) and re-run discovery, which is cheap and
CPU-only. Five targets costs roughly 2.5 GPU-hours and still demonstrates the
chain completely.

---

## 5. If you run out of quota

The allowance renews weekly. Nothing is lost when it runs out:

- **Design results are cached** by a key covering the target, its structure
  content, the epitope, the design ranges, the trajectory count, the seed, the
  designer commits, the backend, and which bindsight will run. Re-running skips
  whatever already completed and only pays for what did not.
- **Differential expression is cached** separately, so nothing on the discovery
  side ever re-runs.
- Simply re-issue the same command after the reset. It resumes.

The backend is part of the design cache key deliberately. Without it, a run on
`--backend mock` and a later real run would share a cache entry, and the real
run would silently return the mock's synthetic numbers wearing a real result's
label.

So is the identity of the bindsight that will execute — the embedded wheel's
content hash, or failing that the git ref. Without it, a run of fixed code would
be handed the unfixed run's cached result, which is the same failure one step
further along.

---

## 6. What is verified, and what is not

| Component | Status |
|---|---|
| RFdiffusion, ProteinMPNN, Boltz-2 on a T4 | **Verified.** The committed run used this stack under the corrected protocol, from a wheel built out of the working tree; all 20 designs hold the target chain fixed |
| AlphaFold initial-guess | Prepared; PyRosetta is credential-free for non-commercial use, submodule clone fixed |
| BindCraft, BoltzGen | Prepared for reduced targets only; both need more memory than 16 GB for a full receptor |
| Chai-1r | **Cannot run on any free GPU.** It requires bfloat16, which needs an Ampere card or newer. Verifying it means renting roughly an hour of an L4. |

BoltzGen's integration was rewritten because the command bindsight built,
`boltzgen design --target ...`, does not exist upstream. That path had never
executed. It now emits a design-spec YAML and calls `boltzgen run`, and passes
`--use_kernels false` because its Triton kernels need compute capability 8.0 and
a T4 is 7.5.
