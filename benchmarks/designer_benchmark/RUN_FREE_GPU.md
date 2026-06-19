# Running the design half on a FREE GPU — produce real binders ($0)

The design half (RFdiffusion → ProteinMPNN → Boltz-2) runs **headlessly on Kaggle's
free GPU** via `bindsight`'s Kaggle backend. This is the path that produced the
committed result in `RESULTS.md` — real *de novo* binders against ERBB2, at **$0**, no
local GPU. See `results.json` / `binders/` for the actual run.

## The reality of "free GPU" (why this is a split-environment build)
Kaggle's free accelerator is a **Tesla P100 (16 GB, compute capability sm_60)**, and its
preinstalled stack (Python 3.12 / PyTorch 2.10) supports **neither** the P100 chip **nor**
RFdiffusion's legacy requirements. So the kernel `bindsight.runners.kaggle_kernel` builds
**two micromamba environments** on the P100 and runs the one executor
(`bindsight.runners.job_exec`) across them:

- **`se3`** — Python 3.9 / torch 1.12.1+cu113 (+ cudatoolkit 11.3 for dgl): RFdiffusion +
  ProteinMPNN.
- **`boltz`** — Python 3.11 / torch 2.2.2+cu118: Boltz-2 + bindsight.

`job_exec` runs under `boltz` and invokes the design tools with the `se3` interpreter via
`BINDSIGHT_DESIGN_PYTHON`; the validator binary is likewise overridable via
`BINDSIGHT_BOLTZ_BIN` (it defaults to `boltz` on PATH, which is correct here since `job_exec`
already runs inside the `boltz` env). Both hooks live in `bindsight/runners/tools.py`. All of
this is automatic — you just need a Kaggle token.

## Step 0 — CPU smoke test (proves the harness, no GPU, ~5 s)
```bash
pip install -e ".[discover,report]"
python benchmarks/run_designer_benchmark.py --backend mock --trajectories 10 --out /tmp/dbench
```
Prints a per-designer table and writes `/tmp/dbench/RESULTS.md` marked **MOCK**.

## Step 1 — Prepare the target (ERBB2 domain IV — the trastuzumab epitope)
The full ERBB2 (1255 aa) does not fit a 16 GB GPU (RFdiffusion holds the whole target in
the diffusion), so design against extracellular **domain IV** — the clinically validated
trastuzumab epitope (~142 residues):
```bash
python benchmarks/designer_benchmark/prepare_erbb2_target.py
# -> data/target_structures/P04626.pdb  (chain A, residues 511–652, from AlphaFold)
```

## Step 2 — Run it on Kaggle's free GPU (headless)
```bash
pip install -e ".[runners]"          # adds the Kaggle API client
# Auth: Kaggle → Settings → API → Create New Token, then either
#   export KAGGLE_API_TOKEN=KGAT_...            (new token format), or
#   put the legacy kaggle.json at ~/.kaggle/kaggle.json
# Your Kaggle account must be phone-verified (required for GPU + internet kernels).

python benchmarks/run_designer_benchmark.py --backend kaggle \
    --designers rfdiff_mpnn --trajectories 10 \
    --structures-dir data/target_structures \
    --out benchmarks/designer_benchmark/run
```
This pushes a self-contained kernel (spec + structure embedded as base64 — no Kaggle
dataset needed), builds the two environments, runs RFdiffusion → ProteinMPNN → Boltz-2 on
the P100, polls to completion (~20 min for 2 trajectories; ~60–70 min for 10), and pulls
back `<id>.tar.gz`. **Use `rfdiff_mpnn` only** — it is the one designer that fits 16 GB
(see the VRAM table below).

## Step 3 — Score + commit the result
```bash
python benchmarks/designer_benchmark/score_run.py <out_dir>/<id>.tar.gz \
    --n-trajectories 10 --out benchmarks/designer_benchmark
```
Writes `results.json` + `RESULTS.md` (marked `is_mock=False`) and stages the designed
binder PDBs into `binders/`. Commit them — the empty template becomes a real result.

## What the metrics mean
- **ipTM** (Boltz-2 interface confidence) is the primary de novo binder-quality metric;
  **success@0.65** is the standard fraction of designs with ipTM ≥ 0.65.
- **Affinity is N/A** for protein binders: Boltz-2 affinity prediction is *ligand-only*,
  so `affinity_pred_value` is blank. ipTM + plDDT are the protein–protein metrics.
- Boltz-2 runs in **fp32** here because the P100/T4 lack bfloat16 (Boltz-2's default).

## GPU memory — what fits a FREE GPU (read before picking designers)
The free Kaggle GPU is a single **P100/T4 (16 GB)**. Per the VRAM table in
`DESIGNER_BENCHMARK.md`, only one designer fits:

| designer | min VRAM | fits a free 16 GB GPU? |
|---|---:|---|
| `rfdiff_mpnn` | ~16 GB | ✅ yes — this is the free arm |
| `boltzgen` | ~24 GB | ❌ no — needs an A100-class (paid) GPU |
| `bindcraft` | ≥32 GB | ❌ no — needs ≥32 GB (paid) |

The full three-way comparison needs a bigger GPU: run `boltzgen` / `bindcraft` via
`--backend modal` (or local Docker with an A100-class card) using the prebuilt image —
that is the paid step, by hardware necessity.

## Tips
- **First run = ERBB2 domain IV + `rfdiff_mpnn`** (smallest; proven). Expand to other
  targets once the path is confirmed.
- Kaggle gives ~30 GPU-hr/week free; a 10-trajectory ERBB2 run is ~1 GPU-hour.
- Remember to **expire the Kaggle token** after a run if you pasted it anywhere shared.
