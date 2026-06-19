# Running the design half on a FREE GPU — produce the first real binders ($0)

The design code is **real and CPU-verified** (the full `design → validate → parse →
tabulate` chain runs end-to-end on the `mock` backend), but it has **never run on a
real GPU**. One free-GPU run produces bindsight's first genuine *de novo* binders,
fills `benchmarks/designer_benchmark/` with real numbers, completes the v0.2
validation, and produces the held-out data the thesis benchmark needs.

**Cost: $0.** Use **Colab** or **Kaggle** free tiers. Do **not** use Modal for this —
it charges after the trial; the free tiers are sufficient.

## What is verified vs. what is yours
- ✅ **Verified on CPU here:** the whole orchestration (mock backend), the notebook
  generator, and that the generated notebook installs the real pinned stack
  (RFdiffusion + weights + SE3-Transformer, ProteinMPNN, Boltz-2, and bindsight
  **from GitHub** — it is not on PyPI).
- 🔫 **Yours (needs a GPU + your Google/Kaggle login):** pressing *Run*. A cloud
  container has no GPU and can't authenticate your account, so the actual GPU run is
  the one step that must happen on your side. It is genuinely one click once set up.

---

## Step 0 — CPU smoke test (proves the harness, no GPU, ~5 s)
```bash
pip install -e ".[discover,report]"
python benchmarks/run_designer_benchmark.py --backend mock --trajectories 10 --out /tmp/dbench
```
Prints a per-designer table and writes `/tmp/dbench/RESULTS.md` marked **MOCK**.

## Step 1 — Fetch the target structure (start with the cleanest target: ERBB2)
```bash
mkdir -p data/target_structures
# ERBB2/HER2 — your validation already surfaces it; AlphaFold model exists.
# (v6 is the current AlphaFold DB release. bindsight's own AlphaFoldDB client always
# tracks the live version, and the benchmark auto-fetches the structure if absent —
# so if this exact URL ever 404s, just let the harness fetch it for you.)
curl -sSL https://alphafold.ebi.ac.uk/files/AF-P04626-F1-model_v6.cif \
  -o data/target_structures/P04626.cif
```

## Path A — Google Colab (recommended for the *first* run; the notebook self-installs everything)
1. Generate the notebook (CPU, no GPU needed):
   ```bash
   python benchmarks/run_designer_benchmark.py --backend colab \
       --designers rfdiff_mpnn --trajectories 10 \
       --structures-dir data/target_structures \
       --out runs/dbench_colab
   ```
   This writes a ready-to-run `.ipynb` per target under `runs/dbench_colab/`.
2. Open <https://colab.research.google.com> → **File → Upload notebook** → pick the
   generated `.ipynb` → **Runtime → Change runtime type → T4 GPU** → **Runtime → Run all**.
   It runs RFdiffusion → ProteinMPNN → Boltz-2 and writes `<id>.tar.gz`.
3. Download `<id>.tar.gz` into `runs/dbench_colab/` where the runner expects it; the
   harness fetches, scores, and writes `results.json` + `RESULTS.md`.

## Path B — Kaggle Notebooks (free **T4×2, ~30 GPU-hr/week**; fully headless once set up)
```bash
pip install -e ".[runners]"          # adds the Kaggle API client
# put your token at ~/.kaggle/kaggle.json  (Kaggle → Account → Create New API Token)
python benchmarks/run_designer_benchmark.py --backend kaggle \
    --designers rfdiff_mpnn --trajectories 10 \
    --structures-dir data/target_structures \
    --out benchmarks/designer_benchmark/run
```
This pushes a kernel, polls it, and pulls the results tarball automatically — no
manual download. Use `rfdiff_mpnn` here too — it's the one designer that fits a
single free T4 (see the GPU-memory note below).

## Step 2 — Estimate cost before ever touching a paid backend
```bash
bindsight design --dry-run examples/benchmark_held_out.yaml --backend modal --designer rfdiff_mpnn
```
Prints the `bindsight.cost` estimate. Colab/Kaggle report **$0**.

## Step 3 — Do the held-out comparison (this is the thesis data)
Repeat Path A/B for the mechanistically-distinct held-out AML targets:
`CD33` (UniProt **P20138**) and `CD123 / IL3RA` (**P26951**). Running the **same**
protocol across `rfdiff_mpnn`, `bindcraft`, `boltzgen` is the three-way comparison
that fills `RESULTS_TEMPLATE.md`.

## Step 4 — Commit the real result
Rename the produced `RESULTS.md` over `RESULTS_TEMPLATE.md`, note the GPU + date +
`bindsight --version`, keep `results.json` and the designed PDBs for provenance, and
commit. The empty template becomes a result — and the only credibility asterisk on
bindsight is gone.

## GPU memory — what actually fits a FREE GPU (read before picking designers)
Free Colab/Kaggle give a **single T4 (16 GB)**. Per the VRAM table in
`DESIGNER_BENCHMARK.md`, only one of the three designers fits it:

| designer | min VRAM | fits a free T4 (16 GB)? |
|---|---:|---|
| `rfdiff_mpnn` | ~16 GB | ✅ yes — this is the free arm |
| `boltzgen` | ~24 GB | ❌ no — needs an A100-class (paid) GPU |
| `bindcraft` | ≥32 GB | ❌ no — needs ≥32 GB (paid) |

So the **free** path produces real binders for the **`rfdiff_mpnn`** arm only. (Kaggle's
"T4×2" is two separate 16 GB cards, **not** a unified 32 GB — it doesn't raise the
per-card limit without model parallelism.) The full three-way comparison needs a bigger
GPU: run `boltzgen` / `bindcraft` via `--backend modal` (or local Docker with an
A100-class card) using the prebuilt image — that is the paid step, by hardware necessity.

## Tips
- **First run = ERBB2 + `rfdiff_mpnn` only** (smallest; T4-friendly, ~45 s/trajectory).
  Expand to the other designers and AML targets once the path is proven.
- Free sessions can time out; the runners checkpoint **per-trajectory** with
  idempotent rerun keys, so just re-run — completed trajectories are skipped.
