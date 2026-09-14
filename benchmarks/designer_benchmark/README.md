# `benchmarks/designer_benchmark/` — the design half, run on a free GPU

20 de novo binders against ERBB2 extracellular domain IV — the clinically
validated trastuzumab epitope — produced end to end on a free Kaggle Tesla T4,
with the real Boltz-2 predicted complexes committed.

## Read this first

**[`RESULTS.md`](RESULTS.md)** — the scored run, generated from `results.json`.

## Read it alongside the control

The structures are real and the confidence numbers are real Boltz-2 outputs.
What they do **not** establish is that these designs bind: a paired control in
[`../calibration/`](../calibration/) folded each design beside a shuffle of its
own sequence, and the shuffles cleared the customary 0.65 bar more often than
the designs did. `success@0.65` is withdrawn as a measure of design quality.

Every rendering of that rate in this directory carries the withdrawal with it.

## What is here

| File | What it is |
|---|---|
| [`RESULTS.md`](RESULTS.md) | The scored run |
| `results.json` | The artifact the prose is generated from |
| `binders/` | 20 FASTAs, 20 Boltz-2 complexes (CIF), per-design `metrics.jsonl` |
| `target/` | The prepared ERBB2 domain IV structure |
| [`DESIGNER_BENCHMARK.md`](DESIGNER_BENCHMARK.md) | The protocol and what each metric means |
| [`RUN_FREE_GPU.md`](RUN_FREE_GPU.md) | **How to reproduce it**, on free hardware |

## Reproducing it

Needs a GPU. `score_run.py` is a scorer, not a runner — it consumes the archive
a GPU run produces. The full chain is in
[`RUN_FREE_GPU.md`](RUN_FREE_GPU.md).

## What the protocol fixed

An earlier run invoked ProteinMPNN without `--pdb_path_chains`, so it redesigned
the HER2 target chain along with the binder and scored the designs against a
surface they had helped invent. Its figures are withdrawn. The committed run
holds the target fixed, and that is checked rather than asserted: all 20 designs
carry a target chain byte-identical to the native 142-residue domain IV.

## What has not been run

The three-way comparison against BindCraft and BoltzGen. Both need 24–32 GB
against anything larger than a small domain; `../gpu_capacity/` holds the
measurements that establish this, so it is a measured limit rather than an
untried one.
