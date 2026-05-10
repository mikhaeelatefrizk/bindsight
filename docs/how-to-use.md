# How to use `bindsight`

> Practical walkthrough for the v0.0.x discovery half (which works today) and
> what's coming in v0.1 for the design half.

---

## Install

`bindsight` is not yet on PyPI. From source:

```bash
git clone <your-repo-url> bindsight
cd bindsight
python -m venv .venv
.venv\Scripts\activate                              # Windows
# source .venv/bin/activate                          # macOS / Linux
pip install -e ".[dev,discover]"
```

Then:

```bash
bindsight --version           # 0.0.1.dev0
bindsight doctor              # check the install
bindsight verify-licenses     # see the license inventory
```

`bindsight doctor` is the first thing to run if anything looks weird later.
It tells you what's installed, what's cached, and what's missing.

---

## Concept: a "run"

A *run* is one invocation of the pipeline against one config + one input
dataset, producing one self-contained output directory. The output looks like:

```
runs/luad_v01/
├── deg/
│   └── results.parquet          # one row per gene
├── targets/
│   └── candidates.parquet       # one row per (gene, UniProt) candidate
├── epitopes/
│   └── epitopes.parquet         # one row per top-N target
├── structures/                  # mmCIFs cached in your global cache, not here
├── design/                      # populated by `bindsight design` (v0.1+)
├── validate/                    # populated by `bindsight validate` (v0.1+)
├── rank/                        # populated by `bindsight rank` (v0.1+)
├── report.html                  # populated by `bindsight report` (v0.1+)
└── run_manifest.jsonld          # PROV-O audit trail of every stage
```

The `run_manifest.jsonld` is the artifact that makes the run reproducible.
Treat it like a lab notebook entry: never edit, always commit.

---

## Step 1 — Author a config

Configs are YAML files validated by `bindsight.config.RunConfig`. Start by
copying the bundled example:

```bash
cp examples/tcga_luad.yaml my_config.yaml
```

Open it and adjust:

```yaml
name: my_first_run
out_dir: runs/my_first_run

inputs:
  counts: data/recount3_cache/tcga_luad/counts.tsv.gz   # gene x sample, integer counts
  design: data/recount3_cache/tcga_luad/design.tsv      # sample, condition, ...

params:
  deg:
    design_formula: "~ condition"
    contrast: ["condition", "tumor", "normal"]
    fdr_threshold: 0.05
    log2fc_threshold: 1.0

  target_discovery:
    require_surfy: true
    surfy_allow_offline_fallback: false
    require_tractable_modality: ["Antibody"]
    max_safety_events: 5
    require_surface_bind_site: true     # set false for v0.0.x
    top_n: 5

backend: colab
```

Validation runs at load time, so misconfigured runs fail loudly *before* any
compute is spent. If you mistype `fdr_threshhold` (sic), Pydantic will refuse
the run with a precise error pointing to the field.

---

## Step 2 — Provide the data

The minimum is two files:

### counts matrix (`counts.tsv` or `counts.tsv.gz`)

Tab-separated, gene IDs in the first column, samples in subsequent columns,
integer counts.

```
gene_id          sample_001  sample_002  sample_003  ...
ENSG00000141736  1245        1389        1452        ...
ENSG00000146648  890         923         941         ...
...
```

### sample design (`design.tsv`)

Tab-separated, sample IDs in the first column, factors in subsequent columns.

```
sample        condition  age  sex
sample_001    tumor      62   F
sample_002    tumor      71   M
...
```

The `condition` column (or whatever you reference in your `design_formula`)
must contain the levels you reference in `contrast`.

### Where to get real data

- **TCGA (cancer) and GTEx (tissue baselines):** [recount3](https://rna.recount.bio/)
  ships pre-aligned counts so you don't deal with FASTQs.
- **Your own RNA-seq:** any standard aligner output (STAR, Salmon, kallisto)
  feeds into the same format after counts extraction.

---

## Step 3 — Populate caches before the first real run

`bindsight` caches three external data sources locally. The `doctor` command
shows you which are populated. For real runs, you need:

### 3a. Full SURFY surfaceome list

The bundled fallback has ~10 proteins (test-only). For real discovery,
download the full SURFY table from https://wlab.ethz.ch/surfaceome (CC-BY) and
write the UniProt accessions to:

```
%LOCALAPPDATA%\bindsight\Cache\surfy\surfy_v1.uniprot.txt    # Windows
~/.cache/bindsight/surfy/surfy_v1.uniprot.txt                # Linux
~/Library/Caches/bindsight/surfy/surfy_v1.uniprot.txt        # macOS
```

One UniProt accession per line. Lines starting with `#` are ignored.

### 3b. SURFACE-Bind data

See [data/surface_bind/README.md](../data/surface_bind/README.md) for the
clone-and-pin recipe. Required when `require_surface_bind_site: true` (the
default). Skipped if `false`.

### 3c. AlphaFoldDB and Open Targets

These auto-populate on first use — no manual setup required, but expect ~5 MB
per AlphaFoldDB structure (mmCIF) and ~1–10 KB per Open Targets query.

---

## Step 4 — Run discovery

```bash
bindsight discover my_config.yaml --out runs/my_first_run
```

What happens:

1. Loads + validates `my_config.yaml`.
2. Reads counts + design TSVs.
3. Runs pydeseq2; writes `runs/my_first_run/deg/results.parquet`.
4. For each significant gene (FDR < threshold AND |log2FC| > threshold):
   - Queries Open Targets GraphQL → UniProt accessions, tractability, safety
   - Filters by SURFY surfaceome membership
   - Filters by tractable modality (default: Antibody)
   - Filters by safety event count
5. Sorts by `(has_alphafold_structure, log2fc)`, marks top-N.
6. For each top-N candidate, fetches the AlphaFoldDB mmCIF.
7. Writes `targets/candidates.parquet` and `epitopes/epitopes.parquet`.
8. Writes `run_manifest.jsonld` with one PROV-O record per stage.

Expected wall time on a laptop: **5–15 minutes** for ~3,000 DEGs, dominated by
Open Targets API calls (cached after first run).

### Inspect what you got

```bash
python -c "import pandas as pd; print(pd.read_parquet('runs/my_first_run/targets/candidates.parquet').head(10))"
```

Or open the manifest:

```bash
type runs\my_first_run\run_manifest.jsonld | python -m json.tool
```

---

## Step 5 — (v0.1+) Design

Once Phase 2 lands:

```bash
# Estimate GPU cost before launching
bindsight design runs/my_first_run --backend modal --dry-run

# Launch on Modal A100s, 50 trajectories per target
bindsight design runs/my_first_run --backend modal --designer rfdiff_mpnn --trajectories 50
```

The `--backend` choice is yours per command:

| Backend | Cost | Speed | When to use |
|---|---|---|---|
| `colab` | Free (T4) or paid (A100) | Slowest, queue-prone | Casual exploration, free tier |
| `kaggle` | Free (T4×2) | Slow, 30 hr/week quota | Free tier with quota |
| `modal` | $0.50–4/hr | Fast, no queue | Real runs, paid |
| `local_docker` | Your hardware | Fastest | If you have a local GPU |
| `mock` | Free | Instant | CI / testing |

`--dry-run` always works without a GPU — it just prints the DAG and a cost
estimate.

---

## Step 6 — (v0.1+) Validate, rank, report, export

```bash
bindsight validate runs/my_first_run --backend modal --validator boltz2
bindsight rank     runs/my_first_run
bindsight report   runs/my_first_run --format html --include-binders
bindsight export   runs/my_first_run --format ro-crate --out runs/my_first_run.crate.zip
```

The `--format html` report is a self-contained Quarto document with embedded
NGL viewers — open it in a browser to rotate the binders. The `--format
streamlit` variant launches an interactive dashboard.

The RO-Crate zip is ready for Zenodo / Figshare deposit.

---

## Reproducibility recipe

To ensure your run is byte-identical (modulo seeds) for someone else:

1. Commit the config YAML.
2. Distribute the run manifest (`run_manifest.jsonld`).
3. The recipient runs:
   ```bash
   docker run --rm \
       -v $PWD:/work \
       ghcr.io/<your-handle>/bindsight@sha256:<digest> \
       bindsight run /work/my_config.yaml --out /work/runs/repro
   ```
4. They compare manifests. SHA-256s of every artifact match.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `bindsight doctor` shows `dep: pydeseq2 = not installed` | Discover extras not installed | `pip install -e ".[discover]"` |
| `discover` exits with `validation error` on the config | Pydantic rejected a field name or type | Read the error — it says exactly which field |
| `discover` says `samples in counts but not design` | Sample IDs don't match between files | Check the first column of `design.tsv` |
| `AlphaFoldDB has no model for X` | UniProt accession not in AlphaFoldDB | Expected for some predicted proteins; row gets tagged and continues |
| Real cohort run with `surfy_allow_offline_fallback: true` returns suspiciously few targets | You're running against the 10-protein fallback | Populate the full SURFY cache (Step 3a) |
| `discover` runs but `tractable_modalities` is always empty | Open Targets cache is from a previous schema | Delete `~/.cache/bindsight/opentargets/` and re-run |

---

## Where to learn more

- [What is bindsight?](what-is-bindsight.md) — the 5-minute pitch
- [Use cases](use-cases.md) — three concrete scenarios
- [ARCHITECTURE.md](../ARCHITECTURE.md) — design rationale and module contracts
- [LICENSING.md](../LICENSING.md) — per-component license inventory
- [CONTRIBUTING.md](../CONTRIBUTING.md) — how to add a designer / validator / runner
