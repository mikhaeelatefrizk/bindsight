# Designer benchmark protocol

A reproducible, three-way comparison of the binder designers bindsight ships —
**RFdiffusion + ProteinMPNN**, **BindCraft**, and **BoltzGen** — over a fixed
target set with a fixed validator (**Boltz-2**), reporting per-designer binder
quality (ipTM, PAE-interaction, predicted affinity, success rate) and GPU cost.

This is the designer half of the v0.2 validation. The harness is real and
runnable; the numbers come from a real GPU run. The **first real result** —
RFdiffusion + ProteinMPNN against ERBB2 domain IV (the trastuzumab epitope), on
Kaggle's free P100 — is committed in [`RESULTS.md`](RESULTS.md) (20 designs,
mean ipTM 0.60, 40% success@0.65), with the designed binders in `binders/` and
the raw metrics in `results.json`.

> **Free-GPU quickstart ($0):** to reproduce or extend it on a Kaggle free GPU,
> follow [`RUN_FREE_GPU.md`](RUN_FREE_GPU.md). The steps below are the
> full/Modal protocol for the complete three-way comparison.

## Why this needs a GPU

RFdiffusion, BindCraft and BoltzGen are GPU-only. The harness is therefore
**CPU-tested with the mock backend** (which exercises the full
design → validate → parse → tabulate orchestration with clearly-synthetic
numbers) and **run for real on a GPU backend**. A green mock run is a faithful
dry-run of the real job: it uses the production plugin stack
(`bindsight.plugins`, each designer's `make_spec`/`submit`,
`bindsight.cost`) verbatim.

| designer | min VRAM | reference speed (A100) |
|---|---|---|
| `rfdiff_mpnn` | ~16 GB (free Colab T4 works) | ~45 s / trajectory |
| `boltzgen` | ~24 GB | ~40 s / trajectory |
| `bindcraft` | ≥32 GB | ~3–5 min / trajectory |

(Speeds are the `bindsight.cost` reference estimates; see
`bindsight/cost.py`, pricing table version in `PRICE_TABLE_VERSION`.)

## Target set

Defaults to the held-out known antigens (`benchmarks/known.tsv`): ERBB2, EGFR,
MSLN, CD33, IL3RA. Epitope residues are left empty (whole-target design) until
SURFACE-Bind epitope prediction lands in v0.2; this is valid per `DesignSpec`.

## Step 0 — CPU smoke test (no GPU, no network)

```bash
pip install -e ".[discover,report]"
python benchmarks/run_designer_benchmark.py --backend mock --trajectories 10 --out /tmp/dbench
```

This must print a per-designer table and write `/tmp/dbench/RESULTS.md`
(clearly marked **MOCK**). It is also covered by `tests/test_designer_bench.py`.

## Step 1 — Estimate cost before spending money

```bash
# Per designer, for the full target set:
for d in rfdiff_mpnn bindcraft boltzgen; do
  bindsight design --dry-run examples/benchmark_held_out.yaml --backend modal --designer "$d"
done
```

## Step 2 — Provide target structures

Place real target structures named `<UNIPROT>.cif` (or `.pdb`) under a directory,
e.g. `data/target_structures/P04626.cif`. If a structure is missing the harness
falls back to an AlphaFoldDB fetch for that UniProt.

```bash
# Example: fetch AlphaFold models for the default targets.
mkdir -p data/target_structures
for u in P04626 P00533 Q13421 P20138 P26951; do
  curl -sSL "https://alphafold.ebi.ac.uk/files/AF-${u}-F1-model_v6.cif" \
    -o "data/target_structures/${u}.cif"
done
```

## Step 3 — Run the real benchmark on a GPU backend

```bash
# Modal (headless cloud GPUs). Swap --backend for local_docker / kaggle as needed.
python benchmarks/run_designer_benchmark.py \
    --backend modal \
    --designers rfdiff_mpnn bindcraft boltzgen \
    --validator boltz2 \
    --trajectories 50 \
    --structures-dir data/target_structures \
    --out benchmarks/designer_benchmark/run
```

Each designer is run over the identical target set with the identical validator,
so differences in the output table are attributable to the designer alone.

## Step 4 — Record results

For the headless Kaggle path, score the returned tarball straight into the
committed artifacts:

```bash
python benchmarks/designer_benchmark/score_run.py <out_dir>/<id>.tar.gz \
    --n-trajectories 10 --out benchmarks/designer_benchmark
```

This writes `results.json` + `RESULTS.md` (`is_mock=False`, stamped with GPU +
date + `bindsight --version`) and stages the designed binder PDBs into
`binders/`. For the Modal path the run writes `run/results.json` + `RESULTS.md`
directly; copy those up and commit. Keep `results.json` and `binders/` for
provenance.

## Metrics

- **ipTM** — Boltz-2 interface predicted-TM (higher = more confident interface).
  The primary metric for protein binders.
- **PAE-interaction** — predicted aligned error across the interface (lower = better);
  comes from Boltz-2's full-PAE output (not the confidence JSON), so it is blank in the
  Kaggle quickstart result.
- **predicted affinity** — Boltz-2 `affinity_pred_value`. **Ligand-only**: Boltz-2 does
  not predict protein–protein affinity, so it is blank for protein binders.
- **success@0.65** — fraction of designs with ipTM ≥ 0.65 (standard de novo criterion).

The scoring math lives in `bindsight/benchmark/designer_bench.py`; it parses the
same `metrics.jsonl` the runner/job executor produces, so CPU (mock) and GPU
runs are scored identically.
