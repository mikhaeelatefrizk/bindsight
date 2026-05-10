# How to design binders on Colab (the real recipe)

> Step-by-step: how to take the `xpr2bind discover` output (target structures
> + epitopes) and produce real, designed binder PDBs on free or paid Google
> Colab. No GPU on your laptop required.

---

## What you need before starting

- A finished `xpr2bind discover` run (e.g. `runs/luad_v01/`).
- A Google account (Colab is free; Colab Pro+ is $50/month and gives A100 access).
- About 15 minutes (T4) or 5 minutes (A100) of attention.

If you haven't run discover yet:

```bash
xpr2bind discover examples/demo/config.yaml --out runs/demo
# or
xpr2bind demo
```

---

## Step 1 — Pick a target

Open the `epitopes.parquet` from your run:

```python
import pandas as pd
e = pd.read_parquet("runs/demo/epitopes/epitopes.parquet")
print(e[["symbol", "uniprot_id", "structure_path"]].head())
```

Pick one row. You'll need its `uniprot_id`, the `structure_path` (mmCIF
file), and a list of "hotspot" residues to design against. If your run had
SURFACE-Bind populated, hotspots are in the `residues` column. If not, you
can pick by inspecting the structure in PyMOL or NGL — surface residues with
small side chains and good solvent exposure tend to make good hotspots.

For HER2 (P04626), well-known hotspots are around the ECD subdomain II / IV
interfaces — residues 244–267 (subdomain II) or 575–613 (subdomain IV).

---

## Step 2 — Open the canonical Colab notebook

Use the [ColabDesign / dl_binder_design notebook](https://colab.research.google.com/github/sokrypton/ColabDesign/blob/main/rf/examples/diffusion.ipynb)
as your starting point. It runs RFdiffusion + ProteinMPNN end-to-end and is
maintained by the community (the same group that develops AlphaFold's
upstream MSA pipeline).

Alternative: the [BindCraft Colab](https://colab.research.google.com/github/martinpacesa/BindCraft/blob/main/notebooks/BindCraft.ipynb)
which is one-shot but needs A100 (≥32 GB). Use this if you have Colab Pro+.

---

## Step 3 — Configure the notebook with your target

In the ColabDesign diffusion notebook:

1. **Upload your target structure.** Drag the mmCIF from `runs/demo/structures/`
   into the Colab file browser. Note its filename (e.g. `AF-P04626-F1-model_v4.cif`).

2. **Set the inputs cell:**
   ```python
   pdb = "AF-P04626-F1-model_v4.cif"        # target structure
   target_chain = "A"
   binder_length = 80                        # 50–150 typical
   hotspot_residues = "A244,A245,A246,A247"  # hotspots from step 1
   num_designs = 5                           # 5 on T4, 50 on A100
   ```

3. **Run all cells.** The pipeline will:
   - Install RFdiffusion (~3 min, cached after first install)
   - Install ProteinMPNN (~30 s)
   - Run RFdiffusion (~30 s/design on A100; ~2 min/design on T4)
   - Run ProteinMPNN to design sequences (~5 s/design)
   - Output: PDB files in `outputs/` with the binders modeled

---

## Step 4 — Validate with Boltz-2

Add a new cell after ProteinMPNN finishes:

```python
!pip install -q boltz==2.* 2>/dev/null

from pathlib import Path
import yaml

# Build a Boltz-2 input YAML for each design
for pdb in Path("outputs").glob("*.pdb"):
    # Extract binder sequence from the PDB
    # ... (use Bio.PDB or simple parsing)
    cfg = {
        "sequences": [
            {"protein": {"id": "T", "sequence": target_seq}},
            {"protein": {"id": "B", "sequence": binder_seq}},
        ],
        "properties": [{"affinity": {"binder": "B"}}],
    }
    cfg_path = pdb.with_suffix(".yaml")
    cfg_path.write_text(yaml.safe_dump(cfg))
    !boltz predict {cfg_path} --use_msa_server --out_dir boltz_out
```

This gives you an iPTM and a predicted affinity per design. Sort by either
to rank.

---

## Step 5 — Bring the results back

Tarball the `outputs/` and `boltz_out/` directories on Colab:

```python
!tar -czf binders.tar.gz outputs boltz_out
from google.colab import files
files.download("binders.tar.gz")
```

Drop `binders.tar.gz` into your local `runs/demo/design/` (creating the
directory if needed). When `xpr2bind validate` and `xpr2bind rank` ship
their live implementations in v0.1.0-rc2, they'll pick up the tarball
automatically.

For now, you can still inspect the binders manually:

```bash
mkdir -p runs/demo/design && tar -xzf binders.tar.gz -C runs/demo/design/
ls runs/demo/design/outputs/      # designed binder PDBs
```

Open them in PyMOL, NGL, or ChimeraX.

---

## Cost expectations

| Tier | GPU | Designs you can run | Approx wall time | Cost |
|---|---|---|---|---|
| Colab free | T4 (16 GB) | 5–10 | 30–60 min | $0 |
| Colab Pro | T4 / V100 | 20–50 | 1–2 hr | $10/mo |
| Colab Pro+ | A100 (40 GB) | 50–200 | 30 min | $50/mo |
| Modal | A100 (40 GB) | 50–200 | 20 min | ~$3 |

The `xpr2bind design --backend modal --dry-run` command gives you a precise
estimate for your specific config:

```bash
xpr2bind design runs/demo --backend modal --designer rfdiff_mpnn \
    --trajectories 50 --dry-run
# → Cost estimate panel shows GPU-hours and USD
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| RFdiffusion install fails on Colab | weights download from IPD's server timed out | re-run the install cell; sometimes you need to wait for a less-loaded time of day |
| OOM on T4 | binder too long or target too big | reduce `binder_length` to ≤100, or upgrade to A100 |
| Boltz-2 install fails | torch version mismatch | restart Colab runtime and re-install in a fresh runtime |
| All designs look the same | RFdiffusion converged on one minimum | increase `num_designs` and add `noise_scale=0.3` |

---

## Why we don't auto-launch Colab from the CLI

Google's Colab API doesn't let third-party apps spin up free-tier notebooks
without OAuth (and rate-limits the OAuth flow heavily). Modal is the right
backend for "no clicks, runs on a schedule" workflows; Colab is the right
backend for "free GPU and I'm willing to click two buttons." `xpr2bind`
supports both — pick per command via `--backend`.

---

## When this becomes a single command

In v0.1.0-rc2 the live runner integration lands and you'll be able to do:

```bash
xpr2bind design runs/demo --backend colab --designer rfdiff_mpnn
# → templates a notebook, opens it in your browser, polls for results
```

Until then, the recipe above is the manual version. Same end result, just a
few extra clicks.
