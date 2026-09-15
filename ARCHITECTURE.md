# Architecture

> Architectural source of truth for `bindsight`. Read this before changing module contracts. Last reviewed: 2026-09-04.

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
   pydeseq2              │
        ▼                │
   DEGs.parquet          │
        │                │
   target.discover ──────┼── Open Targets, GTEx (REST/GraphQL)
        ▼                │
   candidates.parquet ───┼── SURFACE-Bind (UniProt join, vendored at pinned commit)
        ▼                │
   epitopes.parquet ─────┼── AlphaFoldDB (mmCIF pull)
        ▼                │
   design.spec.yaml ─────┼─────────► Colab / Modal / Kaggle / local-Docker
                         │             ├── BindCraft (paid, ≥32GB GPU)
                         │             ├── RFdiffusion + ProteinMPNN (T4 OK)
                         │             └── BoltzGen
                         │             ▼
                         │           Boltz-2 affinity & structure
                         │             ▼
   results.tar.gz ◄──────┼─────────── designed PDBs + metrics.json
        ▼                │
   ranking.parquet       │
        ▼                │
   provenance.jsonld     │
        ▼                │
   HTML report +         │
   web interface         │
        ▼                │
   RO-Crate zip (Zenodo) │
```

---

## 3. Module decomposition

```
bindsight/
├── io/              # GDC + cBioPortal cohort clients; run-directory path helpers
├── deg/             # pydeseq2 wrapper
├── targets/         # Open Targets GraphQL client + ENSG→UniProt fallback + GTEx safety
├── surfaceome/      # SURFY filter + the UniProt cell-membrane extension
├── structures/      # AlphaFoldDB fetch (RCSB/PDBe planned); pLDDT (disorder) + UniProt topology
├── epitopes/        # SURFACE-Bind site lookup; fpocket fallback (planned)
├── design/          # Designer plugin interface (RFdiffusion+MPNN, BindCraft, BoltzGen);
│                    #   developability scoring + ESM-2 embeddings
├── runners/         # Colab / Modal / Kaggle / local-Docker adapters
├── validate/        # Boltz-2 (default), Chai-1r, AF2-IG (opt-in)
├── rank/            # Multi-objective scoring (incl. developability component)
├── pipelines/       # End-to-end orchestrators (discover.py) + honesty caveats
├── benchmark/       # Rediscovery study: pre-registered panel, four-way outcome
│                    #   classification, null models + intervals, designer bench
├── provenance/      # Pydantic schema for run_manifest.jsonld + provenance fragments
├── export/          # RO-Crate emitter (FAIR bundle for Zenodo)
├── report/          # HTML report template + web interface (+ Limitations section)
├── cost.py          # Per-run cost estimation (GPU-type aware)
├── plugins.py       # Designer/validator plugin registry
├── config.py        # Pydantic run-configuration models
└── cli.py           # Click entrypoint
```

### 3.1 Module contracts

This section previously described a uniform contract — a typed input model,
a typed output model, a `run(input, params, manifest) -> output` function
and a per-module `version` string — that every module was said to export.
That contract is aspirational, not implemented, and the description has
been corrected rather than left as a specification readers would test
against.

What is actually true today:

- **Pydantic v2 models are used widely** for configuration and for
  structured stage outputs, but not as a mandatory paired input/output
  model on every module.
- **A module-level `run()` exists in three places only** —
  `pipelines/discover.py`, `pipelines/full_run.py` and `cli.py` — plus a
  `run()` method on the pydeseq2 runner class. Stages are otherwise called
  through ordinary functions with stage-specific signatures.
- **No module defines a `version` string.** Versioning is at the package
  level, in `pyproject.toml`.

Swapping a stage therefore means matching that stage's own signature and
its call site in the pipeline, not implementing a shared interface. Making
the uniform contract real is a plausible refactor, but it has not happened
yet and nothing in the codebase depends on it.

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

- DEG analysis (pydeseq2)
- Database queries (Open Targets) + the bundled ENSG→UniProt fallback
- SURFACE-Bind site lookup
- AlphaFoldDB structure fetching
- Multi-objective ranking
- self-contained HTML + web-interface reports
- Provenance emission

### 4.2 What runs remotely (GPU, offloaded)

- RFdiffusion / BindCraft / BoltzGen backbone generation
- ProteinMPNN sequence design
- Boltz-2 / Chai-1r / AF2-IG validation
- (Optionally) ESMFold for structures missing from AlphaFoldDB

### 4.3 The runner abstraction

```python
class GPURunner(Protocol):
    def estimate_cost(self, spec_size: int) -> CostEstimate: ...
    def submit(self, spec_path: Path, *, results_dir: Path) -> JobHandle: ...
    def poll(self, handle: JobHandle) -> JobStatus: ...
    def fetch(self, handle: JobHandle) -> Path: ...  # returns local path to results.tar.gz
```

Copied from `bindsight/runners/protocol.py`, and checked against it by
`tests/test_docs_claims.py`: this block used to show `submit(spec: DesignSpec)`
and `estimate_cost(spec: DesignSpec)`, neither of which is the real signature, in
the document that presents itself as the interface contract.

Implementations:

- `runners/colab.py` — templates a Colab notebook from a Jinja template, opens it in a browser, polls a Drive folder for results
- `runners/modal.py` — Python-native `modal.Function` calls
- `runners/kaggle.py` — Kaggle Notebooks API
- `runners/local_docker.py` — for users with their own GPU
- `runners/mock.py` — returns canned results for CI

### 4.4 Idempotency

Every GPU work unit has a deterministic cache key, computed in two steps. First
over the work itself:

```
sha256(target_uniprot ‖ target_structure_content ‖ epitope_chain ‖ epitope_residues
       ‖ design_ranges ‖ binder_length_bounds ‖ n_trajectories ‖ seed
       ‖ validator ‖ designer ‖ designer_version ‖ prescreen_top_k
       ‖ diffusion_samples ‖ max_parallel_samples ‖ mode ‖ designer_commits)
```

`designer` and `designer_version` were missing from this list. `job_exec` reads
`designer` straight out of `extra_params` to choose which tool executes, so two
jobs differing only in it shared a key; that they did not actually collide was
incidental, resting on the three adapters passing distinct pinned commits
through `designer_commits`. Nothing carried `designer_version` at all, so
bumping a designer's version without bumping its pinned commit produced an
identical key and recorded the new version against the old cached numbers.

then folded with where the work will run, which code will run there, and any
binders shipped with the job:

```
sha256(work_key ‖ backend ‖ code_identity ‖ payload_digest)
```

Reruns skip completed work, and `cache_status` records the hit or miss on both
the `DesignResult` and the manifest's `StageRecord`, so a reader can tell reused
work from repeated work without re-running anything.

Every component is there because leaving it out produced, or would have
produced, a wrong answer that looked right:

- **Target structure content**, not just the accession. A new AlphaFold model
  for the same protein is different work, and keying on the accession alone
  would silently reuse a result computed against the superseded structure.
- **Seed**, so that re-running an identical configuration reuses the work
  instead of redrawing it. Two of the three designers cannot keep the other half
  of that promise: at the pinned commits BindCraft draws its own seed per
  trajectory (`bindcraft.py:91`) and the `boltzgen` CLI has no seed option, so a
  cache *miss* under an identical seed yields different binders. The executor
  warns whenever one of them runs, and `UNSEEDABLE_DESIGNERS` in
  `bindsight/runners/job_exec.py` carries the evidence. RFdiffusion, ProteinMPNN,
  Boltz-2 and Chai-1 all take the run's seed.
- **Validator.** The remote executor runs whichever validator the spec names, so
  without it a Boltz-2 run and a Chai-1r run shared an entry and the second
  returned the first's numbers under the other validator's name.
- **Prescreen size**, because the ESM-2 screen drops designs before they are
  scored, which changes the result rather than just the cost.
- **Diffusion samples.** The validator averages ipTM over that many draws from a
  stochastic model, so one draw and five are different measurements of the same
  design, not the same measurement at different precisions.
- **Parallel sample batch.** This looks like a performance knob and is not one:
  the sampler draws noise shaped by the batch, so one seed consumes the RNG
  stream differently at batch 1 and batch 5 and produces different structures.
- **Mode.** A `validate_only` job runs no designer at all; it scores binders it
  was handed.
- **Payload digest** — the content and the relative path of every shipped binder.
  The spec-derived key covers what a *designer* would be told to produce, and a
  validate-only job produces nothing: the binders travel in the payload and the
  spec is identical whichever ones go. Two calibration sets against one target
  hashed alike, so the second would have been served the first's rows — the right
  number of well-formed metrics for the right target, and wrong.
- **Backend.** Two runs differing only in where they executed are not the same
  work: one of them may be a mock's canned numbers wearing a real result's
  label.
- **Code identity** — the content hash of the working-tree wheel the runner will
  install, falling back to the git ref, then to the installed version. A
  corrected benchmark was once submitted against a branch whose fixes existed
  only locally, so the GPU installed the default branch and produced pre-fix
  output. Had that run been cached, a later run of the fixed code would have
  been handed the unfixed result under the same key.

Each of these is asserted by varying it and checking the key moves, so this
description cannot drift away from the implementation unnoticed.

This was previously specified here and not implemented — the key was computed
and then used only as a directory name, so every rerun resubmitted.

---

## 5. The provenance contract: `run_manifest.jsonld`

Every run emits a single PROV-O JSON-LD manifest. **This is the moat.** A reviewer or clinician must be able to walk from a designed binder PDB back to:

- the gene's expression in the upstream cohort,
- the structural model used,
- the targetable site predicted,
- the trajectory seed and the resolved design parameters,
- the validator metrics,
- the image digest of any containerised step, where that image was pulled by digest.

The digest is recorded only when it can be verified from the local image store, so a
containerised step carries a real digest or none at all — never a guessed one. CPU stages run
outside a container in a normal CLI invocation, and remote Modal/Kaggle images cannot be
inspected from the orchestrator.

Schema is in `bindsight/provenance/manifest.py`, enforced by Pydantic v2 with `extra="forbid"` on every model, so a malformed stage record fails at write time. (A standalone `schemas/run_manifest.schema.json` for non-Python consumers is not yet emitted.)

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

The real DAG, as `Snakefile` declares it. Seven rules, plus `all`:

```
rule deg:                                   # counts + design  →  deg/results.parquet
    conda:  envs/discover.yaml
    script: scripts/run_deg.py

rule discover:                              # deg table  →  candidates, epitopes, taxonomy
    conda:  envs/discover.yaml
    script: scripts/run_discover.py

rule design:                                # epitopes  →  design/results.tar.gz
    params: backend                         # dispatched to the selected runner
    script: scripts/run_design.py

rule validate:                              # results.tar.gz  →  validated.parquet
    params: backend
    script: scripts/run_validate.py

rule rank:                                  # validated + candidates  →  ranking.parquet
    script: scripts/run_rank.py

rule manifest:                              # five fragments  →  run_manifest.jsonld
    script: scripts/assemble_manifest.py

rule report:                                # ranking + manifest  →  report.html
    script: scripts/run_report.py
```

Every stage rule also emits a `manifest_fragment.jsonld`, and `manifest`
stitches the five of them together. That rule runs **before** `report`, not
after: `report/html.py` reads `run_manifest.jsonld` to render its provenance
table, so while the manifest was assembled last, every Snakemake-produced
report shipped with an empty Provenance section. `report` now takes the
manifest as an input and appends its own record after rendering.

Only `deg` and `discover` declare `conda:`. The design half runs wherever its
backend sends it, so pinning a local environment for those rules would describe
something that is not where the work happens.

The Click CLI and the Snakefile are two front-ends over the same
``bindsight.*`` pipeline functions: the CLI calls them directly, and each
Snakemake rule's ``scripts/`` wrapper calls the same functions.

They are **not** interchangeable, and this document previously claimed they
produced identical artifacts. The concrete difference is that **there is no
`export_crate` rule.** `bindsight export`, which writes the RO-Crate, exists
only on the CLI, so the full Snakemake DAG terminates at `report.html` and
produces no crate. Treat the CLI as the reference and the Snakemake path as a
DAG-driven equivalent for the stages it covers.

```bash
bindsight discover   ≈  snakemake --until discover     # --until also runs deg
bindsight design     ≈  snakemake --until design
bindsight run <cfg>  ≈  snakemake                      # full DAG, minus the crate
```

The full DAG stops at `report.html`. To get a crate, run `bindsight export`
against the same output directory afterwards.

---

## 7. Key OSS components

This heading used to read "(verified)", over a table whose own rows say
**not implemented**. Licences and versions here are checked; the GPU column
is what the tool requires, not what this project has run it on. The
**Status** column says which is which.

| Stage | Tool | License | GPU | Status | Notes |
|---|---|---|---|---|---|
| DE analysis | [pydeseq2](https://github.com/owkin/PyDESeq2) v0.5.4 | MIT | No | Run | scverse-maintained. Not bit-equivalent to R DESeq2 — documented |
| Target evidence | [Open Targets Platform](https://platform-docs.opentargets.org/) GraphQL | CC0 / Apache | No | Run | Rate-limited but generous |
| Tissue baselines | [GTEx](https://gtexportal.org/) | open | No | Run | Specificity filtering |
| Tissue baselines (planned) | [HPA](https://www.proteinatlas.org/) | CC BY-SA 3.0 | No | Planned | **No client implemented.** Listed as intended, not shipped |
| Surfaceome list | SURFY (Bausch-Fluck et al.) | CC-BY | No | Run | 2,886 accessions. The shipped default unions this with a UniProt cell-membrane extension, 4,801 in total, because SURFY omits CA9 and STEAP1 |
| Targetable sites | [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind) | BSD-3 | No | Run | 2,800+ proteins, sites + seeds |
| Structures | [AlphaFoldDB](https://alphafold.ebi.ac.uk/) | CC-BY 4.0 | No | Run | mmCIF by UniProt. RCSB/PDBe clients are planned, **not implemented** |
| Epitope fallback (planned) | [fpocket](https://github.com/Discngine/fpocket) | MIT | No | **Not implemented** | Intended for proteins SURFACE-Bind does not cover. No code exists |
| Designer (default) | [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion) + [ProteinMPNN](https://github.com/dauparas/ProteinMPNN) | BSD-3 / MIT | T4, ~16 GB | Run on Kaggle T4 | The verified design path. The committed benchmark used a since-corrected ProteinMPNN protocol; see `benchmarks/designer_benchmark/RESULTS.md` for which run its numbers come from |
| Designer (premium) | [BindCraft](https://github.com/martinpacesa/BindCraft) | MIT | A100 (≥32 GB) full; T4 for a reduced target | Prepared | Fits a free T4 only below roughly 250 total residues |
| Designer (newest) | [BoltzGen](https://github.com/HannesStark/boltzgen) | MIT (code+weights) | Yes | Prepared, not executed | The command this project built, `boltzgen design`, does not exist upstream, so this path had never run. Rewritten to emit a design-spec YAML and call `boltzgen run` |
| Validator (default) | [Boltz-2](https://github.com/jwohlwend/boltz) | MIT (code+weights) | Yes | Run on Kaggle T4 | Structure + affinity, has CLI |
| Validator (alt) | [Chai-1r](https://github.com/chaidiscovery/chai-lab) | Apache-2 | **Ampere or newer** | Cannot run on any free GPU | Needs bfloat16, which Turing lacks. Commercially usable (Apache-2.0), as Boltz-2 also is; worth renting an hour for a second opinion from an independent model |
| Validator (gold, opt-in) | AF2-IG via [dl_binder_design](https://github.com/nrbennet/dl_binder_design) | AF2 weights non-commercial | Yes | Prepared | Behind license-banner flag |
| MSA | [ColabFold](https://github.com/sokrypton/ColabFold) MSA server | MIT (code) | Remote | Run | BYO MMseqs2 fallback |
| Workflow | [Snakemake](https://github.com/snakemake/snakemake) | MIT | No | Run | DAG, conda envs, --report |
| Provenance | PROV-O JSON-LD + [RO-Crate](https://www.researchobject.org/ro-crate/) | W3C / Apache | No | Run | |
| Visualization | [3Dmol.js](https://github.com/3dmol/3Dmol.js) / NGL | BSD-3 / MPL | No | Run | Vendored in the web interface |

See [LICENSING.md](LICENSING.md) for the full inventory and commercial-use guidance.

---

## 8. Comparison vs. existing tools

| Tool | Input | Output | Where this is different |
|---|---|---|---|
| [ProteinDJ](https://www.biorxiv.org/content/10.1101/2025.09.24.678028v2) | Target structure + epitope | Binders (HPC) | We start upstream — could hand off to ProteinDJ |
| [Ovo](https://www.biorxiv.org/content/10.1101/2025.11.27.691041v1) | Various | General OSS framework | Opinionated narrow vertical, deeply pinned |
| [dl_binder_design](https://github.com/nrbennet/dl_binder_design) | Target + interface | Filtered designs | AF2-IG step is one opt-in validator |
| [Tamarind.bio](https://www.tamarind.bio/) | Target | Binders (SaaS) | Open, reproducible, license-defensible |
| [nf-binder-design](https://github.com/Australian-Protein-Design-Initiative/nf-binder-design) | Target | Binders (Nextflow) | Targets non-HPC users + adds genomics front-end |
| [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind) | UniProt ID | Sites + seeds | Data dependency, not competitor |
| **`bindsight`** | **RNA-seq counts** | **Ranked binders + provenance** | **Only one that starts at counts** |

---

## 9. Differentiation moat (why this isn't a weekend project)

1. **The opinionated, validated *join*.** The work is the empirical defense of the defaults: which DE thresholds × surfaceome filter × specificity penalty × designer × validator combination produces designs that pass an orthogonal check on held-out known antigens (HER2, CLDN6, MSLN, EGFR).
2. **Provenance graph + RO-Crate.** Every ranked candidate is one click from "show me the gene, the patients it came from, the structure, the trajectory seed, the docker digest." No existing protein-design tool does this.
3. **Negative-result curation.** Catalogue targets that fail discovery (no AF model, no SURFACE-Bind site, fails specificity, designer fails to converge, validator rejects). Publish the failure taxonomy. *(Shipped for the discovery half: `taxonomy/failure_taxonomy.parquet` — an exhaustive per-gene disposition, rendered in the HTML report.)*
4. **Cost-aware orchestration.** `--dry-run` estimates GPU $ before running. ProteinDJ/Ovo/BindCraft/dl_binder_design assume HPC.
5. **A web interface with 3Dmol.js structure viewing, plus a self-contained HTML report.** The web interface renders the actual Boltz-2 predicted binder–target complexes in 3-D; the HTML report stays dependency-free and offline-openable. Together they are the artifact that sells the tool in a 5-minute talk.

---

## 10. Risks (honest)

1. **Licensing landmines** — see [LICENSING.md](LICENSING.md). Defaults to MIT/Apache/BSD/CC-BY components.
2. **GPU offload latency** — free sessions die mid-run. Mitigation: content-addressed design caching keyed on the target, its structure's contents, the epitope, the design ranges, the trajectory count, the seed, the designer commits and the backend, so a re-issued command resumes rather than repeats. Kaggle is the verified backend; Colab is an interactive on-ramp, not a reproducibility path, because Google's API does not permit launching a free-tier notebook from a CLI.
3. **Model output instability across versions** — pin commit SHA + weights hash + CUDA in containers; document that exact reproducibility requires the same digest.
4. **Compute cost** — 5 targets × 50 trajectories ≈ 5–10 A100-hours ≈ $20–40 on Modal. Mitigation: the `--cheap` profile, **shipped**: RFdiffusion+ProteinMPNN, `n_trajectories=10`, costed against a T4, and an ESM-2 pre-screen that keeps the 5 most representative designs per target before validation (`bindsight/design/prescreen.py`, applied inside `runners/job_exec.run_job` between design and validation — the only point where dropping a design saves GPU). On the demo config against Modal this takes the `--dry-run` estimate from ~$27.89 (A100) to ~$4.26 (T4). The pre-screen is off unless `params.design.prescreen_top_k` is set, degrades to validating everything if the optional `embed` extra is absent, and records what it screened out.
5. **SURFACE-Bind coverage gaps** — roughly 2,800 proteins against a shipped surfaceome of 4,801 (SURFY's 2,886 unioned with a UniProt cell-membrane extension). Extending the surfaceome widened this gap rather than closing it: more proteins are now reachable by expression than have a known targetable site. Mitigation: graceful drop tagged `no_surfacebind_entry`, which is recorded rather than silent. The fpocket fallback that would close it is not implemented.
6. **Designer choice will age.** Mitigation: a plugin interface, with RFdiff+MPNN as the shipped default and BindCraft and BoltzGen wired behind flags. Only the first is executable: no shipped backend builds an environment the other two can run in, so the three-way benchmark is deferred, not delivered.
7. **Disease specificity is hard, and the signal is weaker than this section used to claim.** "Up in cancer, low in vital tissue" does *not* predictably find known antigens. Measured against a pre-registered panel over fifteen unstratified TCGA projects, recall at rank 20 is 1 of 17 on approved-agent antigens (95% CI 0.01 to 0.27) and 0 of 8 over independent antigens. Twelve of seventeen are not over-expressed in a bulk tumour-versus-normal contrast: eleven fail the significance rule and a twelfth is measured as down-regulated. (This said "thirteen", which is the count across all twenty-two pairs, not across the seventeen approved-tier ones.) Their agents are licensed, so the antigens are real; the limit is in the signal, not the ranking. The earlier claim survived because the headline cohort was stratified by a PAM50 subtype call, and ERBB2 is one of the fifty genes that classifier is built from. Layering scRNA-seq, co-expression and immunopeptidomics is the plausible route to a stronger signal, and none of it is implemented.
8. **Competing with VC-funded teams** (Tamarind, Chai, Generate). Mitigation: compete on transparency + reproducibility + provenance + academic integration. JOSS + bioRxiv + Zenodo + GitHub stars is a real moat for academic users.
9. **PyDESeq2 ≠ DESeq2 numerically.** Documented in `bindsight/deg/pydeseq2_runner.py`. There is no R bridge: users who need exact DESeq2/edgeR numbers must run those tools themselves and feed the resulting DEG table in.
10. **R-strong dev learning Python+Snakemake.** The DEG step is pure Python (pydeseq2); Snakemake's R rule support is unused.

---

## 11. Phased roadmap

### Phase 0 — Preflight ✅ done
- [x] Confirm SURFACE-Bind / RFdiffusion / BindCraft licenses
- [x] Repo skeleton, foundational docs
- [x] Pydantic manifest schema
- [x] Click CLI shell
- [x] Canonical TCGA-LUAD example (auto-downloaded from NIH/GDC)

### Phase 1 — Discovery half, no GPU ✅ done
- [x] Snakemake front-end (rules call the same functions as the CLI)
- [x] `deg/` (pydeseq2 wrapper)
- [x] `targets/` (Open Targets GraphQL client + bundled ENSG→UniProt fallback)
- [x] `surfaceome/` (SURFY filter; full list auto-populated)
- [x] `structures/` (AlphaFoldDB pull)
- [x] Manifest emission (PROV-O JSON-LD)
- [x] `bindsight discover` end-to-end on a real TCGA cohort
- [x] `epitopes/` SURFACE-Bind targetable-site lookup — reads a vendored data tree (user-supplied; no public API) and focuses design on real sites; whole-surface fallback when the data isn't vendored

### Phase 2 — GPU design half ✅ done for the shipped stack

The default designer and validator run end to end on free hardware. The
alternative plugins are wired and dispatched but have no environment on any
backend, so they are listed unchecked rather than folded into the tick above.

- [x] `runners/` (Colab, Modal, Kaggle, local-Docker, mock) over one executor (`job_exec`)
- [x] `design/` RFdiffusion+ProteinMPNN — run end to end on a free Kaggle T4
- [ ] `design/` BindCraft, BoltzGen — dispatched by the executor, but no backend
      builds an environment they can run in
- [x] `validate/` Boltz-2 — run end to end on a free Kaggle T4
- [ ] `validate/` Chai-1r, AF2-IG — same gap; Chai-1r additionally needs bfloat16,
      which no free-tier GPU has
- [x] `rank/` multi-objective scoring
- [x] End-to-end `bindsight run` + Snakemake DAG
- [x] Mocked-runner CI for the GPU half

### Phase 3 — Provenance, report, polish ✅ done
- [x] RO-Crate output
- [x] Self-contained HTML report (jinja2; no Quarto dependency)
- [x] Server-rendered web interface (FastAPI + Jinja2)
- [x] `--dry-run` GPU cost estimator
- [x] Held-out evaluation set + `bindsight benchmark`
- [x] `v0.1.0`, Zenodo DOI
- [ ] Published Docker image with pinned digests (`.github/workflows/docker.yml`)
      — the image **builds** on every push and the push to `ghcr.io` is refused
      (`denied: permission_denied: write_package`). The package predates the
      current repository object, so it is not linked to it; re-linking is an
      account-level action. Ticked before it was ever true.
- [x] mkdocs-material documentation site (`.github/workflows/docs.yml`)

### Phase 4 — Validation paper (in progress)
- [x] Rediscovery study: fifteen whole, unstratified TCGA projects run as
  patient-paired contrasts against a pre-registered panel of 22 antigen-cohort
  pairs. Recall at rank 20 is 1/17 on approved-agent antigens (95% CI
  0.01-0.27); CA9 surfaces at rank 1 of 291 in clear-cell kidney. Four outcome
  classes are reported separately rather than as one rate, and that separation
  found two pipeline defects, both since fixed. Artifacts in
  `benchmarks/study/`, write-up in `paper/validation/manuscript.md`. Supersedes
  a six-cohort version whose ERBB2-at-rank-4 headline is withdrawn: its breast
  cohort was stratified by a PAM50 call, and ERBB2 is one of the PAM50 genes.

- [x] Designer benchmark — `rfdiff_mpnn` arm run for real under the corrected
  protocol: 20 ERBB2 domain-IV binders on a free Kaggle T4, best ipTM 0.88,
  mean 0.51, 40% success@0.65 (8/20, 95% CI 15–70% over backbones), with the real folded Boltz-2 complexes
  committed.
  Artifacts in `benchmarks/designer_benchmark/RESULTS.md`. **That success rate
  is withdrawn as a measure of design quality**: a paired control folded each
  design alongside a shuffle of its own sequence, and under a seeded validator
  averaging five diffusion draws the shuffles pass more often than the designs —
  50% against 30%, a paired difference of -0.043
  (95% CI -0.142 to +0.054, exact sign-flip p = 0.40). The first
  paired run used an unseeded validator at one draw and found a tie; that run is
  superseded. See `benchmarks/calibration/README.md`. The
  target chain was
  held fixed, and that is verified rather than asserted: all 20 designs carry a
  chain byte-identical to the native 142-residue domain IV. A superseded run on
  a P100 reported best ipTM 0.84 and 50% success; it invoked ProteinMPNN without
  `--pdb_path_chains`, so it redesigned the target as well as the binder, and
  its higher mean is an artefact of scoring designs against a surface they
  helped invent. BindCraft / BoltzGen arms need ≥24–32 GB GPUs (pending)
- [x] Negative-result taxonomy on full DEG list (`taxonomy/failure_taxonomy.parquet`, exhaustive per-gene disposition)
- [ ] single-cell RNA-seq input + async Modal submission
- [x] **Milestone:** `v0.2.0` — first real de novo binders (ERBB2 on a free GPU); no preprint deposited yet

### Phase 5 — Coverage and community (post-preprint, ongoing)
- v0.3: ESMFold fallback; fpocket fallback; scRNA-seq input via scanpy markers; BoltzGen as primary; live async Modal/Colab submission
- v0.4: nf-core compatibility; HPC SLURM runner; immunogenicity layer (NetMHCpan)
- v0.5: bispecific / multi-epitope; LigandMPNN
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
