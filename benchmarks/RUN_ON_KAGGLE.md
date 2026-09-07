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

## 3. The corrected designer benchmark — start here

This is the run that matters most. The committed benchmark was produced with
ProteinMPNN redesigning the target chain as well as the binder, so its ipTM
figures are disclaimed and uninterpretable. This re-run supersedes them.

One target, ERBB2 domain IV, the clinically validated trastuzumab epitope:

```bash
python benchmarks/run_designer_benchmark.py --backend kaggle --trajectories 10
```

Budget: roughly **1 GPU-hour**, about 3% of the weekly allowance. Most of the
wall-clock is the environment build, not the science.

When it finishes, the committed benchmark is replaced by figures produced under
the corrected protocol, and the caveat currently attached to every mention of
those numbers can be removed.

---

## 4. The complete provenance chain

The second thing worth spending quota on: one run that goes from RNA-seq counts
to a designed binder with an unbroken chain back to the patients. The discovery
half is already done and committed for fifteen cohorts, so this only needs the
design half.

Clear-cell kidney is the best cohort for it. CA9 ranks first of 291 candidates
there, so the top-ranked target is a real, strongly over-expressed antigen.

```bash
cp -r runs/study/kirc runs/join
python -m bindsight.cli design runs/join --backend kaggle --trajectories 10
python -m bindsight.cli validate runs/join
python -m bindsight.cli rank runs/join
python -m bindsight.cli report runs/join --format html
python -m bindsight.cli export runs/join --out runs/join.crate.zip
```

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
  designer commits and the backend. Re-running skips whatever already completed
  and only pays for what did not.
- **Differential expression is cached** separately, so nothing on the discovery
  side ever re-runs.
- Simply re-issue the same command after the reset. It resumes.

The backend is part of the design cache key deliberately. Without it, a run on
`--backend mock` and a later real run would share a cache entry, and the real
run would silently return the mock's synthetic numbers wearing a real result's
label.

---

## 6. What is verified, and what is not

| Component | Status |
|---|---|
| RFdiffusion, ProteinMPNN, Boltz-2 on a T4 | Ready; the committed run used this stack under a since-corrected protocol |
| AlphaFold initial-guess | Prepared; PyRosetta is credential-free for non-commercial use, submodule clone fixed |
| BindCraft, BoltzGen | Prepared for reduced targets only; both need more memory than 16 GB for a full receptor |
| Chai-1r | **Cannot run on any free GPU.** It requires bfloat16, which needs an Ampere card or newer. Verifying it means renting roughly an hour of an L4. |

BoltzGen's integration was rewritten because the command bindsight built,
`boltzgen design --target ...`, does not exist upstream. That path had never
executed. It now emits a design-spec YAML and calls `boltzgen run`, and passes
`--use_kernels false` because its Triton kernels need compute capability 8.0 and
a T4 is 7.5.
