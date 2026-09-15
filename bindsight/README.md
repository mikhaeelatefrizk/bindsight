# `bindsight/` — the package

77 modules. The pipeline runs in stages, and the directories follow them.

## The discovery half (CPU, no GPU)

| Module | What it does |
|---|---|
| [`io/`](io/) | Readers and writers: Parquet, FASTA, PDB, mmCIF, manifests, and the NIH/GDC and cBioPortal clients that fetch a cohort |
| [`deg/`](deg/) | Differential expression. A pydeseq2 wrapper with a cache key covering the library version, because an upgraded DESeq2 moves log2 fold changes |
| [`targets/`](targets/) | Open Targets client, ENSG→UniProt resolution, and the GTEx normal-tissue safety gate |
| [`surfaceome/`](surfaceome/) | Which proteins reach the cell surface: the SURFY list plus a UniProt curated-membrane extension, vendored so a run never depends on a live fetch |
| [`structures/`](structures/) | AlphaFoldDB structures, pLDDT disorder gating, UniProt topology |
| [`epitopes/`](epitopes/) | SURFACE-Bind targetable-site lookup |

## The design half (GPU, via a backend)

| Module | What it does |
|---|---|
| [`design/`](design/) | The designer plugin interface, developability scoring, ESM-2 embeddings |
| [`runners/`](runners/) | Where GPU work goes: Kaggle, Modal, local Docker, Colab. See the runner status table in the [root README](../README.md) — they do not carry equal evidence |
| [`validate/`](validate/) | Boltz-2 by default; Chai-1r and AF2-initial-guess behind flags |
| [`rank/`](rank/) | Multi-objective composite scoring of validated binders |

## Across both

| Module | What it does |
|---|---|
| [`pipelines/`](pipelines/) | The discovery orchestrator, and the caveats it attaches to its own output |
| [`provenance/`](provenance/) | PROV-O JSON-LD emission and the RO-Crate exporter — the audit trail from a binder back to the cohort |
| [`benchmark/`](benchmark/) | The scoring harnesses: rediscovery study, designer benchmark, and the statistics behind every published interval |
| [`report/`](report/) | The HTML report and the web interface |
| [`config.py`](config.py) | Pydantic run-configuration models — the single definition of what a run config may contain |
| [`cli.py`](cli.py) | The Click entry point for every `bindsight` command |
| [`cost.py`](cost.py) | GPU cost estimation, so `--dry-run` can price a job before it runs |
| [`plugins.py`](plugins.py) | Entry-point loading for third-party designers and validators |

## A note on what lives where

Statistics live in [`benchmark/statistics.py`](benchmark/statistics.py), not
scattered through the reporting code, because every published interval has to
come from one implementation that is tested once. If you are checking how a
number was computed, start there.
