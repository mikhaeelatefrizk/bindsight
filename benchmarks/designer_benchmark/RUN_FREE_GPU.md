# Running the design half on a FREE GPU — produce real binders ($0)

The design half (RFdiffusion → ProteinMPNN → Boltz-2) runs **headlessly on Kaggle's
free GPU** via `bindsight`'s Kaggle backend. This is the path that produced the
committed result in `RESULTS.md` — real *de novo* binders against ERBB2, at **$0**, no
local GPU. See `results.json` / `binders/` for the actual run.

## The reality of "free GPU" (why this is a split-environment build)
Kaggle's *default* accelerator is a **Tesla P100 (16 GB, compute capability sm_60)**,
and current PyTorch ships no Pascal kernels, so that card cannot run the stack at all.
The failure mode is the expensive kind: `torch.cuda.is_available()` returns `True` and
the first real kernel launch dies, hours into a run. The kernel therefore pins
`machine_shape` to a **Tesla T4 (16 GB, sm_75)** and reads compute capability up front,
exiting immediately if it is below 7.5.

Even on a T4, Kaggle's preinstalled stack (Python 3.12 / PyTorch 2.10) does not satisfy
RFdiffusion's legacy requirements. So the kernel `bindsight.runners.kaggle_kernel` builds
**two micromamba environments** and runs the one executor
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
the T4, polls to completion (~20 min for 2 trajectories; ~60–70 min for 10), and pulls
back `<id>.tar.gz`. **Use `rfdiff_mpnn` only** — it is the one designer that fits 16 GB
(see the VRAM table below).

## Step 3 — Score + commit the result
```bash
python benchmarks/designer_benchmark/score_run.py <out_dir>/<id>.tar.gz \
    --n-trajectories 10 --out benchmarks/designer_benchmark
```
Writes `results.json` + `RESULTS.md` (marked `is_mock=False`) and stages every file from
the run's `design/` directory — the designed binder PDBs and FASTAs plus the per-design
`metrics.jsonl` — into `binders/`. Commit them to record (or refresh) the benchmark result.

## What the metrics mean
- **ipTM** (Boltz-2 interface confidence) is the primary de novo binder-quality metric;
  **success@0.65** is the standard fraction of designs with ipTM ≥ 0.65.
  It is **withdrawn as a measure of design quality**: shuffles of these
  designs' own sequences clear it at the same rate. See
  `benchmarks/calibration/README.md`.
- **Affinity is N/A** for protein binders: Boltz-2 affinity prediction is *ligand-only*,
  so `affinity_pred_value` is blank. ipTM + plDDT are the protein–protein metrics.
- Boltz-2 runs in **fp32** here because Turing lacks bfloat16, which is Boltz-2's
  default. This is also why Chai-1r cannot run on any free GPU: its bfloat16
  assumption is spread through its modules rather than behind one argument.

## GPU memory — what fits a FREE GPU (read before picking designers)
The Kaggle GPU this kernel requests is a single **T4 (16 GB)**. Per the VRAM table in
`DESIGNER_BENCHMARK.md`, only one designer fits:

| designer | min VRAM | fits a free 16 GB GPU? |
|---|---:|---|
| `rfdiff_mpnn` | **14.9 GB measured** | ✅ yes — this is the free arm, with ~500 MiB to spare |
| `boltzgen` | ~24 GB (estimate) | ❌ no — needs an A100-class (paid) GPU |
| `bindcraft` | ≥32 GB (estimate) | ❌ no — needs ≥32 GB (paid) |

The `rfdiff_mpnn` figure is a measurement, not an estimate: **14,859 MiB of
15,360 — 97% of the card** — sampled every five seconds through a complete run
against a 377-residue extracellular domain. The kernel log is committed at
[`benchmarks/gpu_capacity/`](../gpu_capacity/), with what was measured and what
it does not license you to assume. The short version: the free arm fits, but
barely, and attention memory grows with target length, so a larger domain
should be expected to exhaust the card rather than merely run slower. The other
two rows remain estimates — nothing has run them.

The full three-way comparison needs a bigger GPU: run `boltzgen` / `bindcraft` via
`--backend modal` (or local Docker with an A100-class card) using the prebuilt image —
that is the paid step, by hardware necessity.

## Tips
- **First run = ERBB2 domain IV + `rfdiff_mpnn`** (smallest; proven). Expand to other
  targets once the path is confirmed.
- Kaggle gives ~30 GPU-hr/week free; a 10-trajectory ERBB2 run is ~1 GPU-hour.
- Remember to **expire the Kaggle token** after a run if you pasted it anywhere shared.
