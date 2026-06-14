# Architecture

> Architectural source of truth for `bindsight`. Read this before changing module contracts. Last reviewed: 2026-05-09.

---

## 1. The thesis

The protein-design world starts at *"given a target."* The genomics world stops at *"here are interesting genes."* `bindsight` is the opinionated, reproducible, citable bridge.

The bridge is buildable as a one-person project in 2026 because three keystones already exist:

1. **[SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind)** (BSD-3) ships pre-computed targetable sites + binder seeds for ~2,800 human surface proteins.
2. **[Boltz-2](https://github.com/jwohlwend/boltz)** (MIT, code + weights) gives commercial-friendly structure + affinity validation.
3. **Free GPU tiers** (Colab T4, Kaggle T4, HuggingFace Spaces) are now powerful enough to run RFdiffusion + ProteinMPNN at meaningful scale.

The combination means a CPU-only laptop user can drive a real binder-design pipeline by templating GPU jobs onto free cloud, while keeping all orchestration, data analysis, and provenance local.

---

## 2. High-level dataflow

```
[Local CPU laptop]                                [Remote GPU]

counts.tsv + design.tsv ─┐
        │                │
   pydeseq2 (R bridge to │
   DESeq2/edgeR optional)│
        ▼                │
   DEGs.parquet          │
        │                │
   target.discover ──────┼── Open Targets, HPA, GTEx (REST/GraphQL)
        ▼                │
   candidates.parquet ───┼── SURFACE-Bind (UniProt join, vendored at pinned commit)
        ▼                │
   epitopes.parquet ─────┼── AlphaFoldDB (mmCIF pull) + RCSB/PDBe
        ▼                │
   design.spec.yaml ─────┼─────────► Colab / Modal / Kaggle / local-Docker
                         │             ├── BindCraft (paid, ≥32GB GPU)
                         │             ├── RFdiffusion + ProteinMPNN (T4 OK)
                         │             └── BoltzGen (v0.2)
                         │             ▼
                         │           Boltz-2 affinity & structure
                         │             ▼
   results.tar.gz ◄──────┼─────────── designed PDBs + metrics.json
        ▼                │
   ranking.parquet       │
        ▼                │
   provenance.jsonld     │
        ▼                │
   HTML report +       │
   Streamlit dashboard   │
        ▼                │
   RO-Crate zip (Zenodo) │
```

---

## 3. Module decomposition

```
bindsight/
├── io/              # Parquet, FASTA, PDB, mmCIF, manifest readers
├── deg/             # pydeseq2 wrapper (+ optional R bridge)
├── targets/         # Open Targets GraphQL, HPA, GTEx, recount3
├── surfaceome/      # SURFY filter + SURFACE-Bind client
├── structures/      # AlphaFoldDB + RCSB/PDBe fetch
├── epitopes/        # SURFACE-Bind site lookup; v0.2 fpocket fallback
├── design/          # Designer plugin interface (RFdiffusion+MPNN, BindCraft, BoltzGen)
├── runners/         # Colab / Modal / Kaggle / local-Docker adapters
├── validate/        # Boltz-2 (default), Chai-1r, AF2-IG (opt-in)
├── rank/            # Multi-objective scoring
├── provenance/      # Pydantic schema for run_manifest.jsonld, RO-Crate emitter
├── report/          # HTML report template + Streamlit app
└── cli.py           # Click entrypoint
```

### 3.1 Module contracts

Every module exports:

- **A typed input model** (Pydantic v2) — what it consumes from the previous stage.
- **A typed output model** (Pydantic v2) — what it produces, and the on-disk format.
- **A `run(input, params, manifest) -> output` function** — pure, idempotent given the same inputs and params.
- **A `version` string** — semver, bumped when output schema or default behavior changes.

This keeps modules swappable. If someone wants to plug a different DEG backend (e.g., pyComBat-Seq), they implement `deg.run` and the pipeline doesn't care.

### 3.2 Inter-module artifact format

| Artifact | Format | Why |
|---|---|---|
| Tabular (DEGs, candidates, epitopes, ranking) | Apache Parquet (snappy) | Fast, typed, language-agnostic, Pandas/Polars/R/DuckDB all read it |
| Sequences | FASTA | Universal |
| Structures | mmCIF (preferred), PDB (fallback) | mmCIF handles >9999 residues and modern naming |
| Per-stage params | YAML | Human-editable |
| Provenance | PROV-O JSON-LD | W3C standard, plays with RO-Crate |
| Final bundle | RO-Crate zip | FAIR, Zenodo-friendly |

---

## 4. Local-vs-remote split

### 4.1 What runs locally (CPU)

- DEG analysis (pydeseq2; or R bridge for DESeq2/edgeR)
- All database queries (Open Targets, HPA, GTEx, recount3)
- SURFACE-Bind site lookup
- AlphaFoldDB / RCSB structure fetching
- Multi-objective ranking
- self-contained HTML + Streamlit reports
- Provenance emission

### 4.2 What runs remotely (GPU, offloaded)

- RFdiffusion / BindCraft / BoltzGen backbone generation
- ProteinMPNN sequence design
- Boltz-2 / Chai-1r / AF2-IG validation
- (Optionally) ESMFold for structures missing from AlphaFoldDB

### 4.3 The runner abstraction

```python
class GPURunner(Protocol):
    def submit(self, spec: DesignSpec) -> JobHandle: ...
    def poll(self, handle: JobHandle) -> JobStatus: ...
    def fetch(self, handle: JobHandle) -> Path: ...   # returns local path to results.tar.gz
    def estimate_cost(self, spec: DesignSpec) -> CostEstimate: ...
```

Implementations:

- `runners/colab.py` — templates a Colab notebook from a Jinja template, opens it in a browser, polls a Drive folder for results
- `runners/modal.py` — Python-native `modal.Function` calls
- `runners/kaggle.py` — Kaggle Notebooks API
- `runners/local_docker.py` — for users with their own GPU
- `runners/mock.py` — returns canned results for CI

### 4.4 Idempotency

Every GPU work unit (one trajectory) has a deterministic cache key:

```
sha256(target_uniprot ‖ epitope_residues ‖ designer_commit_sha ‖ designer_params ‖ seed)
```

Reruns skip completed work. The manifest records hits and misses.

---

## 5. The provenance contract: `run_manifest.jsonld`

Every run emits a single PROV-O JSON-LD manifest. **This is the moat.** A reviewer or clinician must be able to walk from a designed binder PDB back to:

- the gene's expression in the upstream cohort,
- the structural model used,
- the targetable site predicted,
- the trajectory seed and designer commit SHA,
- the validator metrics,
- the container digest of every step.

Schema is in `bindsight/provenance/manifest.py`. Validated against a JSON Schema in `schemas/run_manifest.schema.json` on every run.

Final RO-Crate bundles the manifest + all artifacts + a `software.bib` for citation.

---

## 6. Workflow orchestration

**Snakemake**, because:

- DAG export for the paper figure
- Conda env per rule (`--use-conda`)
- Container digests per rule (`--use-singularity`)
- `--report` emits a self-contained HTML methods report
- `--dry-run` shows what would run
- Reviewers in academic bioinformatics already know it

Snakefile structure:

```
rule discover:
    input: counts, design
    output: targets.parquet, epitopes.parquet, manifest.jsonld
    conda: "envs/discover.yaml"
    script: "scripts/discover.py"

rule design:
    input: epitopes.parquet
    output: results.tar.gz, manifest.jsonld
    params: backend=config["backend"], designer=config["designer"]
    script: "scripts/design.py"     # delegates to runners/

rule validate:
    input: results.tar.gz
    output: validated.parquet
    script: "scripts/validate.py"

rule rank:
    input: validated.parquet, targets.parquet
    output: ranking.parquet
    script: "scripts/rank.py"

rule report:
    input: ranking.parquet, manifest.jsonld
    output: "report.html"
    script: "scripts/report.py"

rule export_crate:
    input: report, manifest.jsonld, ranking.parquet
    output: "{run_id}.crate.zip"
    script: "scripts/export_crate.py"
```

The Click CLI and the Snakefile are two equivalent front-ends over the same
``bindsight.*`` pipeline functions — the CLI calls them directly, and each
Snakemake rule's ``scripts/`` wrapper calls the same functions — so you get
identical artifacts whichever you use:

```bash
bindsight discover   ≡  snakemake --until discover
bindsight design     ≡  snakemake --until design
bindsight run <cfg>  ≡  snakemake (full DAG)
```

---

## 7. Key OSS components (verified)

| Stage | Tool | License | GPU | Notes |
|---|---|---|---|---|
| DE analysis | [pydeseq2](https://github.com/owkin/PyDESeq2) v0.5.4 | MIT | No | scverse-maintained. Not bit-equivalent to R DESeq2 — documented |
| Target evidence | [Open Targets Platform](https://platform-docs.opentargets.org/) GraphQL | CC0 / Apache | No | Rate-limited but generous |
| Tissue baselines | [HPA](https://www.proteinatlas.org/), [GTEx](https://gtexportal.org/) | CC-BY / open | No | Specificity filtering |
| Surfaceome list | SURFY (Bausch-Fluck et al.) | CC-BY | No | 2,886 surface proteins |
| Targetable sites | [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind) | BSD-3 | No | 2,800+ proteins, sites + seeds |
| Structures | AlphaFoldDB + [RCSB API](https://data.rcsb.org/) | CC-BY 4.0 | No | mmCIF by UniProt |
| Epitope fallback (v0.2) | [fpocket](https://github.com/Discngine/fpocket) | MIT | No | When SURFACE-Bind has no entry |
| Designer (default) | [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion) + [ProteinMPNN](https://github.com/dauparas/ProteinMPNN) | BSD-3 / MIT | T4 OK (~16GB) | Free-Colab-friendly baseline |
| Designer (premium) | [BindCraft](https://github.com/martinpacesa/BindCraft) | MIT | A100 (≥32GB) | Higher reported success rate |
| Designer (newest) | [BoltzGen](https://github.com/HannesStark/boltzgen) | MIT (code+weights) | Yes | Nov 2025 release; bet on it for v0.2 |
| Validator (default) | [Boltz-2](https://github.com/jwohlwend/boltz) | MIT (code+weights) | Yes | Structure + affinity, has CLI |
| Validator (alt) | [Chai-1r](https://github.com/chaidiscovery/chai-lab) | Apache-2 | Yes | Independent confirmation |
| Validator (gold, opt-in) | AF2-IG via [dl_binder_design](https://github.com/nrbennet/dl_binder_design) | AF2 weights non-commercial | Yes | Behind license-banner flag |
| MSA | [ColabFold](https://github.com/sokrypton/ColabFold) MSA server | MIT (code) | Remote | BYO MMseqs2 fallback |
| Workflow | [Snakemake](https://github.com/snakemake/snakemake) | MIT | No | DAG, conda envs, --report |
| Provenance | PROV-O JSON-LD + [RO-Crate](https://www.researchobject.org/ro-crate/) | W3C / Apache | No | |
| Visualization | [py3Dmol](https://github.com/3dmol/3Dmol.js) / NGL | MIT / MPL | No | Embed in HTML + Streamlit |

See [LICENSING.md](LICENSING.md) for the full inventory and commercial-use guidance.

---

## 8. Comparison vs. existing tools

| Tool | Input | Output | Where this is different |
|---|---|---|---|
| [ProteinDJ](https://www.biorxiv.org/content/10.1101/2025.09.24.678028v2) | Target structure + epitope | Binders (HPC) | We start upstream — could hand off to ProteinDJ |
| [Ovo](https://www.biorxiv.org/content/10.1101/2025.11.27.691041v1) | Various | General OSS framework | Opinionated narrow vertical, deeply pinned |
| [BindCraft](https://github.com/martinpacesa/BindCraft) | Target + hotspots | Binder PDBs | One designer plugin among several |
| [dl_binder_design](https://github.com/nrbennet/dl_binder_design) | Target + interface | Filtered designs | AF2-IG step is one opt-in validator |
| [Tamarind.bio](https://www.tamarind.bio/) | Target | Binders (SaaS) | Open, reproducible, license-defensible |
| [nf-binder-design](https://github.com/Australian-Protein-Design-Initiative/nf-binder-design) | Target | Binders (Nextflow) | Targets non-HPC users + adds genomics front-end |
| [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind) | UniProt ID | Sites + seeds | Data dependency, not competitor |
| **`bindsight`** | **RNA-seq counts** | **Ranked binders + provenance** | **Only one that starts at counts** |

---

## 9. Differentiation moat (why this isn't a weekend project)

1. **The opinionated, validated *join*.** The work is the empirical defense of the defaults: which DE thresholds × surfaceome filter × specificity penalty × designer × validator combination produces designs that pass an orthogonal check on held-out known antigens (HER2, CLDN6, MSLN, EGFR).
2. **Provenance graph + RO-Crate.** Every ranked candidate is one click from "show me the gene, the patients it came from, the structure, the trajectory seed, the docker digest." No existing protein-design tool does this.
3. **Negative-result curation.** Catalogue targets that fail discovery (no AF model, no SURFACE-Bind site, fails specificity, designer fails to converge, validator rejects). Publish the failure taxonomy.
4. **Cost-aware orchestration.** `--dry-run` estimates GPU $ before running. ProteinDJ/Ovo/BindCraft/dl_binder_design assume HPC.
5. **Streamlit + self-contained HTML report with embedded py3Dmol.** The artifact that sells the tool in a 5-minute talk.

---

## 10. Risks (honest)

1. **Licensing landmines** — see [LICENSING.md](LICENSING.md). Defaults to MIT/Apache/BSD/CC-BY components.
2. **GPU offload latency** — Colab sessions die. Mitigation: per-trajectory checkpointing, idempotent rerun keys.
3. **Model output instability across versions** — pin commit SHA + weights hash + CUDA in containers; document that exact reproducibility requires the same digest.
4. **Compute cost** — 5 targets × 50 trajectories ≈ 5–10 A100-hours ≈ $20–40 on Modal. Mitigation: `--cheap` profile (RFdiff+MPNN on T4, 10 trajectories, ESM-2 pre-screen).
5. **SURFACE-Bind coverage gaps** — 2,886 ≠ all surfaceome. Mitigation: graceful drop with `no_surfacebind_entry` tag; v0.2 fpocket fallback.
6. **Designer choice will age.** Mitigation: plugin interface; ship RFdiff+MPNN default, BindCraft and BoltzGen as flags; benchmark all three in the paper.
7. **Disease specificity is hard.** "Up in cancer, low in vital tissue" predictably finds known antigens. *This is a feature for v0.1* (rediscovery validation). Real novelty in v1.0 layers scRNA-seq + co-expression + immunopeptidomics.
8. **Competing with VC-funded teams** (Tamarind, Chai, Generate). Mitigation: compete on transparency + reproducibility + provenance + academic integration. JOSS + bioRxiv + Zenodo + GitHub stars is a real moat for academic users.
9. **PyDESeq2 ≠ DESeq2 numerically.** Documented. Optional R-bridge for users who need exact DESeq2.
10. **R-strong dev learning Python+Snakemake.** Mitigation: write DEG step in R first via Snakemake's R rule support, rewrite to pydeseq2 once the rest works.

---

## 11. Phased roadmap

### Phase 0 — Preflight (1 week, current)
- [x] Confirm SURFACE-Bind / RFdiffusion / BindCraft licenses
- [x] Repo skeleton, foundational docs
- [x] Pydantic manifest schema
- [x] Click CLI shell
- [ ] Pin TCGA-LUAD via recount3 as canonical example

### Phase 1 — Discovery half, no GPU (3–4 weeks)
- [ ] Snakemake skeleton with conda envs
- [ ] `deg/` (pydeseq2 wrapper)
- [ ] `targets/` (Open Targets GraphQL client)
- [ ] `surfaceome/` (SURFY filter + SURFACE-Bind client)
- [ ] `structures/` (AlphaFoldDB pull)
- [ ] `epitopes/` (SURFACE-Bind lookup; fail-soft for missing)
- [ ] Manifest emission
- [ ] `bindsight discover` end-to-end on TCGA-LUAD
- [ ] **Milestone:** `v0.0.1` tag

### Phase 2 — GPU offload + design half (4–6 weeks)
- [ ] `runners/` abstraction (Colab + Modal)
- [ ] `design/` RFdiffusion+ProteinMPNN wrapper (T4-friendly default)
- [ ] `validate/` Boltz-2 wrapper
- [ ] `rank/` multi-objective scoring
- [ ] End-to-end `bindsight run`
- [ ] Mocked-runner CI for GPU half
- [ ] **Milestone:** `v0.1.0-rc1`

### Phase 3 — Provenance, report, polish (3 weeks)
- [ ] RO-Crate output
- [x] Self-contained HTML report (jinja2; no Quarto dependency)
- [ ] Streamlit dashboard
- [ ] `--cheap` profile and `--dry-run` cost estimator
- [ ] Docker image with pinned digests
- [ ] mkdocs-material documentation site
- [ ] **Milestone:** `v0.1.0`, Zenodo DOI

### Phase 4 — Validation paper (4–6 weeks)
- [ ] Rediscovery experiment: 3–5 TCGA cohorts → known antigens (HER2, CLDN6, MSLN, EGFR)
- [ ] Designer benchmark: RFdiff+MPNN vs BindCraft vs BoltzGen
- [ ] Negative-result taxonomy on full DEG list
- [ ] bioRxiv preprint
- [ ] **Milestone:** preprint DOI + `v0.2.0`

### Phase 5 — Coverage and community (post-preprint, ongoing)
- v0.2: ESMFold fallback; fpocket fallback; scRNA-seq input via scanpy markers; BoltzGen as primary
- v0.3: nf-core compatibility; HPC SLURM runner; immunogenicity layer (NetMHCpan)
- v0.4: bispecific / multi-epitope; LigandMPNN
- v1.0: JOSS submission; tutorial workshop; Zenodo all-versions DOI

---

## 12. Glossary

- **Backbone diffusion** — AI model that generates protein 3D backbones (no sequence yet) given a target site.
- **Binder** — A protein designed to bind a target (here: a surface antigen).
- **DE / DEG** — Differential expression / differentially expressed gene.
- **Epitope** — The specific surface region a binder is designed against.
- **iPTM / pAE** — AlphaFold/Boltz-derived confidence metrics for predicted interfaces.
- **PROV-O** — W3C provenance ontology.
- **RO-Crate** — Research Object Crate; FAIR packaging spec for research artifacts.
- **Surfaceome** — The set of proteins present on the cell surface.
- **TCGA** — The Cancer Genome Atlas; standard public cancer-omics dataset.
