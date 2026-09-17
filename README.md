# bindsight

> **Expression → Binder.** An open-source pipeline that joins cohort RNA-seq target
> discovery to de novo protein binder design in one reproducible workflow, with
> machine-readable provenance from every ranked binder back to the patient samples
> it came from.

[![CI](https://github.com/mikhaeelatefrizk/bindsight/actions/workflows/ci.yml/badge.svg)](https://github.com/mikhaeelatefrizk/bindsight/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Workflow: Snakemake](https://img.shields.io/badge/workflow-Snakemake-brightgreen.svg)](https://snakemake.github.io/)

Genomics tooling stops at *"here are the interesting genes."* Protein-design
tooling starts at *"given a target…"*. The bridge between them is built ad-hoc,
per project, and rarely reproducibly. bindsight ships that bridge as one tool,
and carries a PROV-O / RO-Crate audit trail across the join.

---

## Start here

Everything below is in this repository. Nothing on this page requires a website,
an account, or a GPU to read.

| If you want to… | Go to |
|---|---|
| **Run it in five minutes** | [Install](#install), then `bindsight demo` |
| **See what it has and has not shown** | [What the evidence says](#what-the-evidence-says) |
| **Reproduce a published number** | [Reproducing the results](#reproducing-the-results) |
| **Understand how it works** | [ARCHITECTURE.md](ARCHITECTURE.md) |
| **Read the study** | [`benchmarks/study/`](benchmarks/study/) · [write-up](paper/validation/manuscript.md) |
| **Read the control that withdrew a headline** | [`benchmarks/calibration/`](benchmarks/calibration/) |
| **See the provenance chain, run end to end** | [`benchmarks/provenance_join/`](benchmarks/provenance_join/) |
| **Find your way around the code** | [Repository map](#repository-map) |
| **Use your own data** | [Scope — what it accepts](#scope--what-it-accepts) |
| **Design binders on a free GPU** | [`RUN_FREE_GPU.md`](benchmarks/designer_benchmark/RUN_FREE_GPU.md) |
| **Contribute** | [CONTRIBUTING.md](CONTRIBUTING.md) |
| **Cite it** | [Citation](#citation) |

---

## Install

One command, one way. Python 3.11+, Windows / macOS / Linux, CPU only.

```bash
git clone https://github.com/mikhaeelatefrizk/bindsight.git
cd bindsight
pip install -e ".[discover,report]"
```

Add `dev` if you intend to run the tests (`pip install -e ".[dev,discover,report]"`),
and `runners` if you intend to send work to a GPU backend. Conda users can build the
same dependency set first with `mamba env create -f envs/discover.yaml`.

Check the install, then run the demo:

```bash
bindsight --version
bindsight doctor
bindsight demo
```

`bindsight demo` runs the full discovery half on a **real TCGA-BRCA
tumour-versus-adjacent-normal cohort**, auto-downloaded from NIH/GDC, and writes an
HTML report you can open in a browser. It needs internet on first run (the cohort
and the enrichment lookups are cached afterwards) and takes a few minutes of real
DESeq2. No GPU.

For a local interface over the same thing — the evidence behind every claim
below, the demo, your own cohort, and the predicted binder–target complexes
rendered in 3-D. Served from your machine; nothing is fetched from a network
once installed.

```bash
bindsight ui      # opens http://localhost:8501
```

---

## What the evidence says

Stated plainly, including the parts that did not work. Each claim links to the
artifacts it comes from.

### The discovery half

Run on **fifteen whole, unstratified TCGA projects** as patient-paired contrasts,
scored against a panel of 22 antigen-cohort pairs fixed in git before any cohort was
run. Nothing in a cohort's definition refers to the antigen being sought.

Two null models, and they point in different directions — both are reported, because
reporting only one would make the other the finding:

- **Against abundance- and dispersion-matched decoys — negative.** 3 of 22 pairs are
  nominally significant; **none survives Benjamini-Hochberg** across the panel. The
  smallest adjusted value this panel could have produced is 0.022, so a pair could
  genuinely have survived — the negative is a measurement, but not a sensitive one.
- **Against a permuted indication — positive.** Antigens sit at mean standing 0.765
  in the cancer they are actually used in against 0.417 in cancers that are not
  theirs: a **within-antigen difference of 0.348 (95% CI 0.188–0.513)**, each antigen
  its own control, interval excluding zero, with an exact permutation p of 3.97e-04
  over all 5,040 orderings — the floor this design can express.

That second result is the strongest claim this project supports, and it is a claim
about the **ordering**, not about any individual hit. Absolute recall is low and
stated as such: at rank 20 it is 1 of 17 on approved-agent antigens (95% CI
0.01–0.27). Most clinically validated antigens are simply not significantly
over-expressed in an unstratified bulk contrast.

→ [`benchmarks/study/RESULTS.md`](benchmarks/study/RESULTS.md) · [write-up](paper/validation/manuscript.md)

### The design half

The pipeline runs RFdiffusion → ProteinMPNN → Boltz-2 end to end on a free Kaggle
T4 and produces real predicted complexes. What it does **not** establish is that
those designs bind.

A paired control folds every design beside a shuffle of its own sequence — same
length, same composition, order destroyed. Under a seeded validator averaging five
diffusion draws, **the shuffles cleared the customary ipTM 0.65 bar more often than
the designs did** (50% against 30%; paired difference −0.043, 95% CI −0.142 to
+0.054; 9 of 20 designs beat their own shuffle, where 10 is chance).

`success@0.65` is therefore **withdrawn as a measure of design quality**, and this
page does not quote it as one. The ipTM values are real Boltz-2 outputs; what does
not follow is that the rate measures the designs. The control's predictions were
written down before its data arrived.

→ [`benchmarks/calibration/`](benchmarks/calibration/) · [`benchmarks/designer_benchmark/`](benchmarks/designer_benchmark/)

### The join

The claim the project rests on — a reviewer can start at a ranked binder and reach
the patient samples it came from — was exhibited once, end to end, on a target the
discovery half chose for itself: CA9 at rank 1 and CD70 at rank 2 out of TCGA-KIRC,
carried through to 40 designs and a walkable PROV-O graph. The committed manifest
lets you verify the first three steps of that walk from this clone; the rest needs
the crate rebuilt, and that directory says so precisely.

→ [`benchmarks/provenance_join/`](benchmarks/provenance_join/)

### What has not been done

- The three-way designer comparison (RFdiffusion+ProteinMPNN vs BindCraft vs
  BoltzGen) is **not run**. Both alternatives need 24–32 GB against anything larger
  than a small domain, so those arms require paid backends; on free hardware no
  shipped backend can run them.
- The calibration's own power analysis puts **142 paired designs** at 80% power to
  detect a 0.05 ipTM difference. The committed control has 20.

---

## Scope — what it accepts

The pipeline takes a **counts matrix** and a **sample design table** naming a
two-level factor, and contrasts those two levels. Nothing on that path knows about
cancer. `tumor` and `normal` are values you supply, not values the code expects:
[`tests/test_non_cancer_cohort.py`](tests/test_non_cancer_cohort.py) drives the whole
documented path on a drug-versus-vehicle experiment paired within donor, with no
oncology vocabulary anywhere, and asserts that none leaks into the provenance
manifest.

Three parts *are* domain-specific, and they are separable:

- **The optional `inputs.download` block** fetches a cohort from NIH/GDC, so it knows
  TCGA's sample type names. Point `inputs.counts` and `inputs.design` at your own
  files and it never runs.
- **The rediscovery benchmark** scores recovery of known tumour antigens. It is an
  evaluation harness for the ranker, not part of a run.
- **The safety gate** compares candidates against GTEx normal-tissue baselines. That
  is a human resource, and so are the SURFY surfaceome, the UniProt membrane
  extension and SURFACE-Bind's site inventory.

So the honest scope is **any human bulk RNA-seq contrast between two conditions** —
disease versus healthy, treated versus untreated, responder versus non-responder,
one tissue versus another. Non-human cohorts would need substitutes for four
reference resources, none of which is wired in.

---

## What it does

```
  bulk RNA-seq counts                               Designed protein binders
              │                                              ▲
              │                                              │
              ▼                                              │
   Differential expression  ──►  Surface-exposed  ──►  De novo backbone
   (pydeseq2)                   (SURFY)              (RFdiffusion / BindCraft / BoltzGen)
                                     │                       │
                                     ▼                       ▼
                              Targetable sites          Sequence design
                              (SURFACE-Bind)            (ProteinMPNN)
                                     │                       │
                                     ▼                       ▼
                              AlphaFoldDB structure     Affinity + structure
                                                        validation
                                                        (Boltz-2 / Chai-1r)
                                                              │
                                                              ▼
                                                  Multi-objective ranking
                                                              │
                                                              ▼
                                       HTML report + RO-Crate (Zenodo)
                                       with full PROV-O provenance
```

### Commands

| Capability | Status | How to try |
|---|---|---|
| **`bindsight demo`** — full discovery on a real cohort + report | ✅ ready | `bindsight demo` |
| **`bindsight discover`** — your own RNA-seq cohort → ranked targets | ✅ ready | `bindsight discover my.yaml --out runs/x` |
| **`bindsight ui`** — local interface: the evidence, a demo, your own data, past runs, and the 20 predicted complexes in 3-D | ✅ ready | `bindsight ui` |
| **`bindsight report`** — paper-style HTML, embedded volcano + provenance | ✅ ready | `bindsight report runs/x` |
| **`bindsight run`** — full orchestrator (discover → design → validate → rank → report → export) | ✅ ready | `bindsight run my.yaml --out runs/x` |
| **`bindsight design`** — RFdiffusion + ProteinMPNN + Boltz-2 on a free Kaggle T4 | ✅ runs end to end | `bindsight design runs/x --backend kaggle` |
| **`bindsight design --dry-run`** — GPU cost estimate before spending | ✅ ready | `bindsight design runs/x --backend modal --dry-run` |
| **`bindsight validate`** — materialise the design job's metrics | ✅ ready | `bindsight validate runs/x` |
| **`bindsight rank`** — multi-objective composite scoring | ✅ ready | `bindsight rank runs/x` |
| **`bindsight export`** — RO-Crate zip for a Zenodo deposit | ✅ ready | `bindsight export runs/x --out runs/x.crate.zip` |
| **`bindsight benchmark`** — score rediscovery of held-out known antigens | ✅ ready | `bindsight benchmark runs/x --known-antigens benchmarks/known.tsv` |
| **`bindsight doctor`** — diagnose deps, caches, vendored data | ✅ ready | `bindsight doctor` |
| **`bindsight verify-licenses`** — per-component license inventory | ✅ ready | `bindsight verify-licenses` |
| **Snakemake front-end** — the same stage functions as a DAG | ✅ ready, stops before the crate | `snakemake --configfile my.yaml --cores 4` (needs `.[workflow]`) |
| **BindCraft / BoltzGen / Chai-1r / AF2-IG** | ⚠️ wired, but no shipped backend can run them | The executor dispatches to all four, and no backend builds an environment in which that dispatch succeeds. The CLI refuses the combination locally rather than spending GPU quota discovering it — see below |

### Runner and plugin status

Not every backend carries the same weight of evidence, and presenting them as peers
would be misleading.

| | Status | Why |
|---|---|---|
| **Kaggle** | The verified free path | Headless via the Kaggle API, so a reader can re-run the exact job on their own free quota. Pinned to a T4: Kaggle's own docs warn its default P100 cannot run current PyTorch. |
| **local_docker** | For your own GPU | Native and containerised modes; the native mode is what CPU tests exercise. |
| **Modal** | Prepared, not executed | The paid escape hatch for what free hardware cannot reach. Its image carries the whole design stack, but running it costs money and it has not been run end to end. |
| **Colab** | Interactive on-ramp only | Google's API does not permit launching a free-tier notebook from a CLI, so this path needs a human with a browser tab open. That is a demo, not a reproducibility path. |
| **RFdiffusion, ProteinMPNN, Boltz-2** | Verified on free hardware | The committed benchmark ran the whole stack on a free Kaggle T4, from a wheel built out of this tree. All 20 designs carry a target chain byte-identical to the native domain IV, so "the target was held fixed" is a check rather than a claim. |
| **AF2 initial-guess** | Buildable free | PyRosetta is credential-free for non-commercial use since 2024. Non-commercial weights. |
| **BindCraft, BoltzGen** | Reduced-target only on free hardware | Both fit a 16 GB card against a small domain, not a full receptor. BoltzGen's integration was rewritten after its command was found not to exist upstream. |
| **Chai-1r** | Needs Ampere or newer | It requires bfloat16, which no free-tier GPU has. Verifying it means renting roughly an hour of a modern card. |

> **Note on GPU stages.** The design and validation models require CUDA, so they run
> on the backend you choose, not on the CPU host.

---

## Reproducing the results

Three tiers, because they cost very different things.

**1. Regenerate the published pages from committed artifacts — offline, seconds.**

```bash
python scripts/build_docs_results.py   # rewrites docs/results.md; it should not change
python -m pytest -q                    # 1600+ tests, no network
```

**2. Re-run the rediscovery study — needs network, a few CPU-hours.**

Cohorts are downloaded from NIH/GDC on first use and cached under `data/gdc_cache/`,
which is not committed; the download is the slow part.

```bash
python benchmarks/run_study.py --all --cpus 2   # fetches + runs DESeq2
python benchmarks/run_study.py --score-only     # re-scores what is already on disk
```

**3. Re-run the binder design — needs a GPU.**

`score_run.py` is a scorer, not a runner: it consumes the archive a GPU run
produces. The full chain is in
[`RUN_FREE_GPU.md`](benchmarks/designer_benchmark/RUN_FREE_GPU.md), which runs on a
free Kaggle T4.

```bash
python benchmarks/designer_benchmark/prepare_erbb2_target.py
python benchmarks/run_designer_benchmark.py --backend kaggle \
    --designers rfdiff_mpnn --trajectories 10 \
    --structures-dir data/target_structures \
    --out benchmarks/designer_benchmark/run
python benchmarks/designer_benchmark/score_run.py <out_dir>/<id>.tar.gz \
    --n-trajectories 10 --out benchmarks/designer_benchmark
```

---

## Repository map

Each top-level area carries its own `README.md` explaining what is in it and
why — [`bindsight/`](bindsight/), [`tests/`](tests/), [`scripts/`](scripts/),
[`benchmarks/`](benchmarks/) and each benchmark under it, [`docs/`](docs/),
[`examples/`](examples/), [`envs/`](envs/) and [`paper/`](paper/). Package
subdirectories are documented in the table below rather than individually.

| Path | What it holds |
|---|---|
| [`bindsight/`](bindsight/) | The Python package — [`io`](bindsight/io/), [`deg`](bindsight/deg/), [`targets`](bindsight/targets/), [`surfaceome`](bindsight/surfaceome/), [`structures`](bindsight/structures/), [`epitopes`](bindsight/epitopes/), [`design`](bindsight/design/), [`runners`](bindsight/runners/), [`validate`](bindsight/validate/), [`rank`](bindsight/rank/), [`benchmark`](bindsight/benchmark/), [`pipelines`](bindsight/pipelines/), [`provenance`](bindsight/provenance/), [`export`](bindsight/export/), [`report`](bindsight/report/) |
| [`benchmarks/`](benchmarks/) | All the evidence — the [study](benchmarks/study/), the [calibration control](benchmarks/calibration/), the [designer benchmark](benchmarks/designer_benchmark/), the [provenance join](benchmarks/provenance_join/), and the held-out antigen set |
| [`tests/`](tests/) | 1,600+ tests. Many are guards on published claims, not on code |
| [`paper/`](paper/) | JOSS and bioRxiv manuscripts, and the validation write-up |
| [`docs/`](docs/) | Long-form documentation (mkdocs-material source) |
| [`examples/`](examples/) | Runnable pipeline configs |
| [`envs/`](envs/) | Conda environment for the discovery half, with pinned constraints |
| [`scripts/`](scripts/) | Generators for vendored data and published pages |
| [`.github/workflows/`](.github/workflows/) | CI, docs, docker, release artifacts |

| File | What it is |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | The architectural source of truth |
| [CHANGELOG.md](CHANGELOG.md) | Per-version changes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, testing, commit conventions |
| [LICENSING.md](LICENSING.md) | Per-dependency licence inventory and commercial-use guidance |
| [SECURITY.md](SECURITY.md) | How to report a vulnerability |
| [CITATION.cff](CITATION.cff) | Citation metadata |
| [Snakefile](Snakefile) | The Snakemake DAG front-end |

---

## Who it's for

- **Translational researchers** who want a free, reproducible "data → designed
  binder" pipeline.
- **Clinical biologists** who need an audit trail back from a binder to the cohort.
- **Method developers** who want a held-out evaluation harness to benchmark new
  designers and validators.
- **Anyone with a two-condition human RNA-seq experiment** — the cancer framing
  throughout this document reflects where it has been validated, not what it accepts.

## What's distinctive

| | Existing protein-design tools | bindsight |
|---|---|---|
| Input | Target structure | RNA-seq counts |
| Provenance | PDB + maybe a log | PROV-O JSON-LD + RO-Crate, audit trail to the cohort |
| Hardware | HPC assumed | CPU laptop + offload to a free Kaggle T4 |
| Cost-awareness | None | `--dry-run` estimates GPU spend before running |
| Negative results | Discarded | Catalogued (`failure_taxonomy.parquet`), and published |
| Citability | Code dump | DOI per release, JSON-Schema-validated outputs |

For the full landscape comparison, see
[ARCHITECTURE.md § 8](ARCHITECTURE.md#8-comparison-vs-existing-tools).

---

## Acknowledgments

bindsight is an opinionated wrapper. Real intellectual credit belongs to the upstream
tool authors. See [LICENSING.md](LICENSING.md) for the full inventory; the work this
builds on most directly:

- [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind) (Balbi et al., PNAS 2026) — the targetable-sites catalog that makes the bridge tractable
- [pydeseq2](https://github.com/owkin/PyDESeq2) (Muzellec et al., Bioinformatics 2023) — Python DESeq2 implementation
- [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion) (Watson et al., Nature 2023) — backbone generation
- [ProteinMPNN](https://github.com/dauparas/ProteinMPNN) (Dauparas et al., Science 2022) — sequence design
- [Boltz-2](https://github.com/jwohlwend/boltz) (Wohlwend et al., 2025) — structure + affinity prediction
- [BindCraft](https://github.com/martinpacesa/BindCraft) (Pacesa et al., Nature 2025) — one-shot binder design
- [Snakemake](https://github.com/snakemake/snakemake) (Mölder et al., F1000Research 2021) — workflow orchestration

## Citation

Cite the software by its Zenodo **concept DOI**, which always resolves to the
latest archived version:

> `10.5281/zenodo.PENDING`

> **The DOI is a placeholder until this repository's first Zenodo deposit.** It is
> deliberately not a valid identifier, so it cannot be published by accident.
> After minting, run `python scripts/set_doi.py <the minted DOI>` — it writes the
> value into every file that names one, and a test fails if any is left behind.

Citation metadata also lives in [CITATION.cff](CITATION.cff); GitHub's "Cite this
repository" button generates BibTeX and APA from it. Please also cite the upstream
tools you used — each run emits a `software.bib` to make that straightforward.

## About the author

bindsight is built and maintained by **Mikhaeel Atef Rizk Wahba**, independent
researcher.

- ORCID: [0009-0006-1069-9558](https://orcid.org/0009-0006-1069-9558)
- GitHub: [@mikhaeelatefrizk](https://github.com/mikhaeelatefrizk)
- Email: `mikhaeelatefrizk@proton.me`

## License

- **Code:** [GNU AGPL-3.0-or-later](LICENSE) — copyright notice in [COPYRIGHT](COPYRIGHT). You may use, study, modify, and
  redistribute bindsight freely; if you distribute a modified version **or run it as
  a network service**, you must make your source available under the same licence,
  with attribution preserved. See [LICENSING.md](LICENSING.md) for component-level
  details — bindsight orchestrates external tools that keep their own licences, and
  some carry non-commercial terms.
