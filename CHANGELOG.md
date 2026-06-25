# Changelog

All notable changes to `bindsight` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Fixed — Snakemake provenance manifest now populated + docs refreshed
- `scripts/assemble_manifest.py` now folds each per-rule `manifest_fragment.jsonld`
  (`{stage, status, metrics}`) into a real `bindsight.provenance.StageRecord`, so the
  Snakemake front-end's `run_manifest.jsonld` records the run's stages exactly like the
  Click CLI path does — previously it only logged the fragments and wrote an empty manifest.
  The assembly logic is a pure `assemble()` helper covered by `tests/test_assemble_manifest.py`
  (CI-safe, no Snakemake runtime); stale `v0.0.x` version references were removed.
- Documentation refreshed to match the shipped state: README "Status & roadmap" /
  "What works today" (the opt-in discovery-quality filters, developability, ESM-2 visualizer,
  honesty caveats) + repository layout (`pipelines/`, `config.py`); ARCHITECTURE module map
  (`pipelines/`, `benchmark/`, new submodules); and DESIGNER_BENCHMARK.md (PAE-interaction is
  now reported — mean 13.7 Å; `*_complex.cif` complexes replace the poly-glycine PDBs;
  SURFACE-Bind has landed). `examples/benchmark_held_out.yaml` surfaces the opt-in flags
  (commented, default off).

### Added — real Boltz-2 predicted binder complexes (+ PAE-interaction)
- `bindsight/runners/job_exec.py` now stages the Boltz-2 **predicted complex** (`*_model_0.cif`) plus
  the PAE / pLDDT arrays into the results tarball — previously only the confidence JSONs were kept, so
  the actual folded binder–target structures were lost — and fills `pae_interaction` (mean inter-chain
  PAE from the predicted PAE matrix). `score_run.py` stages those complexes into `binders/` as
  `<id>_complex.cif` and no longer stages the poly-glycine RFdiffusion backbones. Unit-tested in
  `tests/test_job_exec_retention.py`. New `--targets` flag on `run_designer_benchmark.py`.
- **Re-ran ERBB2 on the free P100 with the fix** → the committed designer benchmark now ships the
  **20 real folded Boltz-2 complexes** (`binders/*_complex.cif`): mean ipTM **0.59**, best **0.84**,
  **50 %** success@0.65, mean PAE-interaction **13.7 Å** (a fresh run — the v0.2.0 run's structures
  weren't retained). The misleading poly-glycine PDBs are removed; the developability and ESM-2
  embedding artifacts are regenerated from the new sequences so everything is consistent.

### Added — pLM embedding visualizer (ESM-2 → PCA, pre-GPU sequence space)
- New `bindsight/design/embeddings.py`: real protein-language-model embeddings via **ESM-2**
  (`facebook/esm2_t6_8M_UR50D`, CPU-capable) with mean-pooled per-protein vectors, plus a
  dependency-free NumPy `pca_2d` projection and a matplotlib `render_embedding_png`. Lets you *see*
  the designed-binder sequence space (which cluster / are outliers) before any GPU spend — the
  ProtSpace idea. ESM-2 lives behind a new optional extra `bindsight[embed]` (torch + transformers),
  kept out of `all` so the core stays CPU-lean; the PCA/PNG path needs no heavy deps.
- `benchmarks/designer_benchmark/embed_binders.py` produced real artifacts for the 20 ERBB2 binders:
  `binders/embedding_coords.tsv` + `binders/embedding_space.png` (real ESM-2 inference). Tests:
  `tests/test_embeddings.py` runs PCA/PNG on a committed real 20×320 ESM-2 fixture (CI-safe) and the
  live ESM-2 path under `importorskip` (verified locally).

### Added — binder developability scoring (sequence biophysics)
- New `bindsight/design/developability.py` scores a designed binder's *sequence* on deterministic,
  offline biophysical descriptors via Biopython ProtParam: instability index, GRAVY, isoelectric
  point, aromaticity, free cysteines, an aggregation-prone fraction (Kyte-Doolittle window), and a
  composite `developability_score` ∈ [0,1]. Wired into `rank/scoring.py` as a sequence-optional
  `score_developability` component (new `RankWeights.developability`; inert when no sequence column).
  `benchmarks/designer_benchmark/score_developability.py` computes it for the real committed binders
  → `binders/developability.tsv` (mean score 0.69, 11/20 predicted stable). Tests:
  `tests/test_developability.py` (exact ProtParam values on a real binder + rank integration).
  (T-cell-epitope / immunogenicity scoring is deliberately deferred — it needs a licensed/heavy MHC
  predictor this layer can't compute exactly offline.)

### Added — normal-tissue safety filter (GTEx, on-target/off-tumor toxicity)
- New `bindsight/targets/gtex.py` downloads + caches real GTEx v8 gene-median-TPM-by-tissue and
  exposes `max_expression(gene, tissues)`. A good antibody/ADC target is over-expressed in tumour
  but low in vital normal tissues; discovery previously only used Open Targets adverse-event counts
  and left the `vital_tissues` / `vital_tissue_max_tpm` config orphaned. Now, with opt-in
  `target_discovery.use_gtex_safety`, candidates whose median expression in any vital tissue exceeds
  the threshold are flagged `high_normal_tissue_expression` (new disposition) and dropped from design;
  `max_vital_tissue_tpm` is surfaced per candidate. Off by default (requires the GTEx download), so
  existing runs are unchanged. Tests: `tests/test_gtex.py` against a fixture built from real GTEx v8
  medians (ERBB2 ~47.8 TPM in lung — the trastuzumab cardiotox concern; NY-ESO-1/MAGEA4 = 0 in vital
  tissues) + gate tests in `tests/test_failure_taxonomy.py`.

### Added — topology-aware epitope selection (UniProt extracellular domain)
- New `bindsight/structures/topology.py` fetches real UniProt membrane topology (transmembrane,
  topological domains, signal peptide) and exposes the extracellular ranges. A binder can only
  reach the extracellular part of a surface protein, so when `target_discovery.use_uniprot_topology`
  is enabled discovery annotates each candidate's `extracellular_ranges` / `has_extracellular_domain`,
  targets the ECD for whole-surface design (`design_ranges`), and reports each SURFACE-Bind site's
  `fraction_extracellular`. Opt-in `require_extracellular_domain` drops non-accessible targets with a
  new `no_extracellular_domain` disposition. Both flags default off (UniProt network), so existing
  runs are unchanged. Tests: `tests/test_topology.py` against a real downloaded UniProt fixture
  (ERBB2 P04626) + gate/annotation tests in `tests/test_failure_taxonomy.py`.

### Added — disorder-aware filter (AlphaFold pLDDT)
- New `bindsight/structures/plddt.py` reads per-residue confidence (pLDDT) straight from the
  AlphaFold mmCIF B-factor column (no network, graceful on bad files). Discovery now surfaces a
  `mean_plddt` per candidate and a `mean_epitope_plddt` per epitope (don't design against a
  disordered region). A new opt-in `target_discovery.min_mean_plddt` gate (default 0 = off) drops
  models below the threshold with a new `low_confidence_structure` disposition in the failure
  taxonomy; the report shows pLDDT columns and the new disposition. Tests: `tests/test_plddt.py`
  (real fixture mmCIF) + a gate test in `tests/test_failure_taxonomy.py`.

## [0.2.0] - 2026-06-19

### Added — first real de novo binders (designer benchmark populated)
- The designer benchmark now ships a **real result**, not an empty template:
  RFdiffusion → ProteinMPNN → Boltz-2, run on a **free Kaggle Tesla P100**, produced
  **20 binders** against ERBB2 extracellular domain IV (the trastuzumab epitope) —
  mean ipTM 0.60, best 0.83, 40 % pass ipTM ≥ 0.65 — at $0. The designs (PDB + FASTA),
  per-design metrics, `results.json`, and a populated `RESULTS.md` live in
  `benchmarks/designer_benchmark/`. New `prepare_erbb2_target.py` (extracts the
  domain-IV target from the AlphaFold model) and `score_run.py` (aggregates a returned
  results tarball into the committed artifacts).
- **Kaggle split-environment backend** (`bindsight/runners/kaggle_kernel.py`): the free
  Kaggle GPU is a P100 (sm_60) whose preinstalled stack runs neither RFdiffusion's
  legacy deps nor shares a Python env with the modern Boltz-2 validator, so the kernel
  builds two micromamba environments — `se3` (py3.9 / torch 1.12.1+cu113 → RFdiffusion +
  ProteinMPNN) and `boltz` (py3.11 / torch 2.2.2+cu118 → Boltz-2 + bindsight) — and runs
  `job_exec` across them. Boltz-2 is pinned to fp32 (the P100/T4 lack bfloat16).
- `bindsight/runners/tools.py`: the design and validator interpreters are overridable via
  `BINDSIGHT_DESIGN_PYTHON` / `BINDSIGHT_BOLTZ_BIN` — the minimal seam that lets one
  `job_exec` span a legacy designer env and a modern validator env (defaults unchanged).

### Fixed — Kaggle runner + Boltz-2 protein-binder validation
- `KaggleRunner.submit()` now embeds the spec + structure as base64 in a self-contained
  kernel instead of referencing a Kaggle dataset it never created; `poll()` reads the real
  `KernelWorkerStatus` enum (it previously mis-parsed the status and never saw completion).
- `job_exec` / `validate/boltz2.py`: disable Boltz-2 affinity for protein binders (it is
  ligand-only) and use valid single-letter chain IDs — previously Boltz-2 silently skipped
  every design, so all metrics came back null. ipTM is now produced; PAE-interaction and
  affinity are intentionally blank for protein binders.

### Added — negative-result taxonomy (failure modes as a first-class output)
- `bindsight/pipelines/discover.py` now emits `taxonomy/failure_taxonomy.parquet`:
  one disposition per differentially-expressed gene explaining why it did / didn't
  become a surfaced candidate — `not_significant`, `down_regulated`,
  `below_enrichment_cutoff`, `no_uniprot`, `not_surfaceome`, `fails_tractability`,
  `fails_safety`, `no_alphafold_model`, `not_top_n`, `no_surface_bind_site`,
  `surfaced`. The funnel is **exhaustive** (counts sum to the DEG total), so the
  failure modes are auditable rather than silently discarded. The HTML report
  renders a "Why candidates dropped" breakdown, and the per-disposition counts
  land in the run manifest. New `tests/test_failure_taxonomy.py`.

### Added — rediscovery validation + designer benchmark
- **Rediscovery validation** on six real indication-matched TCGA cohorts
  (`bindsight/benchmark/rediscovery.py`, driver `benchmarks/run_validation.py`,
  artifacts in `benchmarks/validation/`, write-up in `paper/validation/`). The
  discovery half resurfaces **ERBB2 at rank 4** in HER2-enriched breast cancer
  (PAM50-stratified) and is specific — antigens not transcriptionally
  over-expressed at the bulk level (EGFR, CEA) are correctly not surfaced.
  Results are grouped by *measured* over-expression under a uniform pre-stated
  rule; every number is produced by the runs, none hand-set.
- **cBioPortal PAM50 fetcher** (`bindsight/io/cbioportal.py`) and a GDC fetcher
  extension to select STAR-Counts by explicit case barcodes (subtype-stratified
  cohorts). Eval set extended with CEACAM5 (CEA) and NECTIN4 (Padcev target).
- **Three-way designer benchmark** harness + protocol
  (`bindsight/benchmark/designer_bench.py`, `benchmarks/designer_benchmark/`):
  RFdiffusion+ProteinMPNN vs BindCraft vs BoltzGen on a shared target set,
  CPU-tested with the mock backend, runnable for real on a GPU backend (the
  `rfdiff_mpnn` arm is now populated with a real run — see *first real de novo
  binders* above; the empty template is gone).
- **Free-GPU design path made runnable**: bindsight installs from GitHub (it is
  not on PyPI) and a $0 Kaggle runbook
  (`benchmarks/designer_benchmark/RUN_FREE_GPU.md`) walks through producing real
  binders on a free P100 via the split-environment kernel.

### Added — SURFACE-Bind targetable-site lookup
- **SURFACE-Bind site lookup implemented** (`bindsight/epitopes/surface_bind.py`):
  `SurfaceBindClient.has/sites/metadata` read a *vendored* data tree
  (`data/surface_bind/sites/<UNIPROT>/sites.json`; user-supplied — SURFACE-Bind
  has no public API). Wired into discovery (`pipelines/discover.py`): top-N
  candidates get real epitope residues when a qualifying site exists (focused
  RFdiffusion design), filtered by `min_surface_bind_score`, and
  `require_surface_bind_site` carries only sited candidates when data is vendored.
  With no vendored data, discovery falls back to whole-surface design and records
  an honest `epitope_status` (`surface_bind_site` / `no_surface_bind_site` /
  `surface_bind_not_configured`); the pinned commit SHA is exposed via
  `client.metadata()` for provenance.

### Changed — discovery ranking, license audit
- Discovery now ranks candidates by the combined DE score π = log2fc × −log10(padj)
  (Xiao et al. 2014), matching the documented intent (the code previously sorted
  by raw fold-change only). This moves strongly-and-confidently over-expressed
  antigens up the shortlist (e.g. ERBB2 in HER2-enriched breast: rank 25 → 4).
- `bindsight verify-licenses --config <cfg>` now performs a real per-config
  audit (resolves the chosen designer/validator/backend and flags any
  non-commercial component) instead of a stub.

### Removed — repository cleanup
- Removed ops/marketing residue not meant for a public scientific repo:
  `GO_LIVE.ps1`, `tools/keep-warm/`, `announcement/`, `CUSTOM_DOMAIN.md`,
  `PUBLISH_PYPI.md`, a redundant keep-warm workflow, and `docs/hf-spaces-deploy.md`
  / `docs/keeping-the-demo-warm.md` (with their dangling references). Fixed the
  PyPI `Homepage`/`Documentation` URLs to point at the live docs site.

### Added — docs site, container image, eval-set enrichment
- **mkdocs-material documentation site** (`mkdocs.yml` + `docs/index.md`) with a
  GitHub Pages deploy workflow (`.github/workflows/docs.yml`) and a `docs` extra.
- **Dockerfile** (CPU image for the discovery half + CLI) + a `Docker` workflow
  that builds it on every PR and publishes to GHCR on `main`/tags.
- Held-out eval set extended with **FOLH1/PSMA** (prostate, `Q04609`); the
  bundled ENSG→UniProt map gained FOLH1, CD33, and CD123/IL3RA so offline runs
  resolve those real targets.

### Changed — the demo now runs on REAL data
- **`bindsight demo` runs on a real TCGA-BRCA cohort** (NIH/GDC), not synthetic
  counts. A new GDC fetcher (`bindsight.io.gdc`) auto-downloads a tumor-vs-
  adjacent-normal STAR-Counts cohort on first run (cached after), the full
  ~2,886-protein SURFY surfaceome is auto-populated
  (`surfaceome.populate_surfy_cache`), and the top up-regulated DEGs are enriched
  via Open Targets — a genuine surfaceome-wide discovery with full provenance
  (`provenance.json` with GDC UUIDs + SHA-256). The fabricated
  `examples/demo/counts.tsv`/`design.tsv` are deleted. Config gains
  `inputs.download` (`bindsight.config.GDCSource`).
- Discovery scales to real cohorts: enrichment is capped to the top up-regulated
  DEGs and AlphaFold structures are fetched only for the carried-forward
  candidates.

### Changed — Snakemake front-end is now real
- The `Snakefile` + `scripts/run_*.py` were stubs (they wrote
  `"This is a placeholder"`) and never actually ran (a `from __future__` import
  ordering bug broke them under Snakemake's script wrapper). They now call the
  same `bindsight.*` pipeline functions as the CLI, so `snakemake --configfile
  <cfg> --cores N` runs discover → design → validate → rank → report → manifest
  end-to-end. Added a `workflow` extra and a Snakemake E2E test. Docs corrected:
  the CLI and Snakemake are two equivalent front-ends over the same functions
  (the CLI does **not** "drive Snakemake").
- The `mock` backend now emits a realistically-shaped results tarball
  (metrics.jsonl + per-binder dirs) so the whole orchestration runs E2E in CI.

### Docs
- Swept the docs/README/paper/announcements for stale claims now that the
  design half and Snakemake are real: removed "v0.1+/coming/stub/templated"
  language, fixed the version (`0.0.1.dev0` → `0.1.0`), "Quarto" → the actual
  self-contained HTML report, and the "synthetic 10-gene demo" → the real
  TCGA-BRCA demo. SURFACE-Bind targetable-site prediction is stated honestly as
  a roadmap item (the design step targets the whole surface today).

### Added — real design pipeline (all plugins, zero stubs)
- **RFdiffusion → ProteinMPNN → Boltz-2 run end-to-end for real** via a single
  executor (`bindsight.runners.job_exec`) shared by every backend. The Modal,
  local/Docker, and Kaggle runners now genuinely submit + fetch (no more
  `NotImplementedError`); the Colab notebook is a thin wrapper over the same
  executor. Commands + parsers live once in `bindsight.runners.tools` (pinned
  real upstream commit SHAs). `bindsight design`/`validate` actually launch and
  materialise `validated.parquet`.
- **All alternative plugins implemented for real** (no stubs): BindCraft +
  BoltzGen designers, Chai-1r + AF2-IG validators (AF2-IG keeps its
  non-commercial banner), and the Kaggle runner.

### Fixed
- **CLDN6 accession corrected**: the bundled map listed `Q14953` for CLDN6, but
  `Q14953` is **KIR2DS5**. The correct CLDN6 accession is **`P56747`**
  (`ENSG00000184697`); MSLN's gene id is corrected to `ENSG00000102854`
  (was `ENSG00000133110` = POSTN). Both verified against UniProt/Ensembl.
- **AlphaFoldDB model version** bumped `v4 → v6` (the old URLs now 404), so
  structure fetching works again.
- `parse_boltz_output` searches recursively (Boltz writes to
  `predictions/<name>/`), the target structure is now actually shipped to the
  GPU, and the designer's `metrics.jsonl` path is populated.

### Added — held-out evaluation set + benchmark tooling
- **Real held-out evaluation set** under `benchmarks/`: literature-validated
  binders for the AML targets **CD33** (P20138) and **CD123/IL3RA** (P26951) —
  gemtuzumab ozogamicin, lintuzumab, vadastuximab talirine, tagraxofusp,
  talacotuzumab/CSL362, flotetuzumab — plus the solid-tumor antigens HER2, EGFR,
  MSLN and CLDN6. Every binder carries a verifiable citation (ChEMBL / NCT /
  PMID / DOI / PDB); five structurally-resolved binders ship byte-exact VH/VL
  sequences pulled from their PDB co-crystals (`9VL2`, `4JZJ`, `1N8Z`, `1S78`,
  `1YY9`). `benchmarks/build_eval_set.py` regenerates everything from the public
  sources with full provenance + SHA-256 (`benchmarks/sources.json`,
  `benchmarks/PROVENANCE.md`).
- **`bindsight benchmark` command** (`bindsight.benchmark`): scores one or more
  finished run dirs by the rank of each known antigen in the candidate
  shortlist, computes recall@k, and renders a side-by-side HTML report — the
  workflow `docs/use-cases.md` referenced but never shipped.
- **`examples/benchmark_held_out.yaml`**: the held-out benchmark run config the
  docs referenced (previously missing).

### Fixed
- **CLDN6 accession corrected**: the bundled map listed `Q14953` for CLDN6, but
  `Q14953` is **KIR2DS5**. The correct CLDN6 accession is **`P56747`**
  (`ENSG00000184697`), verified against UniProt.

## [0.1.0] - 2026-05-11

The "real invention" release. Every CLI command works end-to-end (no
``_not_implemented`` calls). The Colab notebook generated by
``bindsight design --backend colab`` contains real RFdiffusion +
ProteinMPNN + Boltz-2 install + inference cells (patterned on the upstream
ColabDesign / dl_binder_design notebooks). A polished multi-page web UI
launches via ``bindsight ui`` and is one-click deployable to Streamlit
Cloud.

### Added — v0.1.0 highlights
- **Web UI** (`bindsight.report.webapp`): multi-page Streamlit app with
  Home / Demo / "Run on my data" / Browse / About pages. Polished CSS,
  inline volcano plot rendering, embedded HTML report viewer, file upload
  for user data, downloadable Parquet artifacts. Same app deploys to
  Streamlit Cloud via the root-level ``streamlit_app.py`` + ``requirements.txt``.
- **`bindsight ui` CLI command** — launches the local Streamlit server
  with the right port, headless flag, and clear output URL.
- **Real ranking module** (`bindsight.rank.scoring`): `rank_validated()`
  + `rank_run()` produce a composite score from iPTM, pAE_interaction,
  RMSD, affinity prediction, and DE evidence. Configurable weights;
  graceful when columns are missing. Output Parquet has both the
  composite and every component for downstream re-ranking.
- **Real RO-Crate exporter** (`bindsight.export.ro_crate`): emits a
  ``.crate.zip`` with `ro-crate-metadata.json` (RO-Crate 1.1 spec) and
  `software.bib` listing every upstream tool used in the run. Ready for
  direct Zenodo deposit.
- **Real full-pipeline orchestrator** (`bindsight.pipelines.full_run`):
  drives discover → design (artifact check) → validate (artifact check)
  → rank → report → export. Skip flags per stage; CPU stages always
  execute; GPU stages run when artifacts are present.
- **Real Boltz-2 validator** (`bindsight.validate.boltz2`): JSON parser
  for Boltz-2 output (``confidence_*.json`` + ``affinity_*.json``).
  Builds the Boltz YAML config from a target+binder pair. Raises
  ``MissingValidationError`` with a clear pointer to the GPU step when
  output is missing.
- **Real Colab design notebook** (`bindsight.runners.notebook_content`):
  16-cell notebook with proper RFdiffusion install (with weight
  downloads from IPD), ProteinMPNN install, Boltz-2 install via pip,
  spec loading, inference, packaging. Patterned on ColabDesign and
  dl_binder_design.
- **`bindsight run` CLI** wired to the orchestrator with `--dry-run`
  cost estimate.
- **`bindsight export` CLI** wired to the RO-Crate emitter.
- **`bindsight rank` CLI** wired to the scoring module.
- **`bindsight validate` CLI** prints clear "GPU step pending" panel
  pointing to the Colab notebook + how-to doc; exits 0.
- 18 new tests (rank, export, full_run): **175 fast tests passing** in
  under 4 minutes.

### Changed
- **Renamed** package: `xpr2bind` → `bindsight`. PyPI name, package
  directory, all imports, entry points, env vars (`BINDSIGHT_SURFACE_BIND_DATA`),
  conda env names, citation metadata, all docs.
- **Bumped version**: 0.0.1.dev0 → 0.1.0.
- **Removed** every `_not_implemented` call from `bindsight rank`,
  `bindsight run`, `bindsight export`. The CLI is now real end-to-end.

### Added — Phase 3 "perfect demo" (2026-05-11)
- **`bindsight demo`** — one-command end-to-end run on a shipped 10-gene
  tumor-vs-normal cohort. Takes ~30 s on a CPU laptop, no internet required,
  no GPU required. The pipeline rediscovers ERBB2 (HER2) and EGFR as top
  antibody-tractable surface antigens, producing a real HTML report.
- **`examples/demo/`** — bundled `counts.tsv`, `design.tsv`, `config.yaml`
  for the demo. Files ship with the wheel via `[tool.hatch.build.targets.wheel.force-include]`.
- **`bindsight.report.html.render_run`** — paper-style HTML report renderer.
  Self-contained single-file output: embedded CSS, base64 PNG volcano plot,
  candidates table with badges, epitopes table, full PROV-O provenance table,
  styled to look like a Nature methods page. Pure jinja2 + matplotlib, no
  Quarto / Jupyter dependency.
- **`bindsight.report.streamlit_app`** — interactive Streamlit dashboard for
  browsing a run. Launched via `bindsight report <run> --format streamlit`.
- **`bindsight report`** is now wired (was stub).
- **`bindsight.targets.ensembl_uniprot`** — bundled offline ENSG → UniProt
  fallback map (~15 well-known cancer surface antigens + drivers). Used when
  Open Targets is disabled or unreachable; status `bundled_fallback` is
  recorded in the candidates table.
- **`docs/colab-design-howto.md`** — step-by-step recipe for running
  RFdiffusion + ProteinMPNN + Boltz-2 on Colab against a `bindsight` discover
  output. Documents the manual flow until live runner integration in v0.1.0-rc2.
- **README polished**: feature matrix showing what works today vs. what's
  pending; 60-second quickstart; cleaner install instructions.
- 18 new tests (demo E2E, ensembl_uniprot fallback, HTML report renderer,
  CLI demo + report). Total: **156 fast tests passing**, all green.
- Windows console fix: `sys.stdout.reconfigure(encoding='utf-8')` at CLI
  startup so Rich box-drawing chars + ≥/×/→ glyphs render on cp1252 terminals
  without crashing.

### Added — Phase 2 GPU-half scaffold (2026-05-10)
- `bindsight.cost` — real GPU cost estimator. Pricing table for Modal /
  Colab Pro+ / Kaggle / local across A100 / H100 / L4 / T4 / RTX4090 etc.
  Per-designer + per-validator timing tables (45 s/trajectory for
  RFdiff+MPNN, 240 s for BindCraft, 20 s/design for Boltz-2). Powers
  `--dry-run`. 15 tests.
- `bindsight.runners.notebook` — Jinja2-backed Jupyter notebook builder
  (envelope, code/markdown cells, strict-undefined rendering).
- `bindsight.runners.colab` — real Colab runner. Builds a self-contained
  `.ipynb` Jupyter notebook with Colab GPU metadata, install + spec +
  designer + package cells; user runs it and drops the resulting tarball
  back into the results directory for `poll`/`fetch` to detect. 6 tests.
- `bindsight.runners.modal_runner`, `bindsight.runners.kaggle`,
  `bindsight.runners.local_docker` — runner stubs with working cost
  estimators. Live `submit` lands in v0.1.0-rc2. 5 tests.
- Designer plugins (entry-point registered):
  - `bindsight.design.rfdiff_mpnn` — default designer. Real cache-key
    construction; mock-runner round-trip works today (real RFdiffusion in
    v0.1.0-rc2).
  - `bindsight.design.bindcraft` — premium designer (≥32 GB VRAM), stub.
  - `bindsight.design.boltzgen` — newest designer (MIT weights), stub.
- Validator plugins (entry-point registered):
  - `bindsight.validate.boltz2` — default validator.
  - `bindsight.validate.chai1r` — alt for cross-model agreement.
  - `bindsight.validate.af2_ig` — opt-in (non-commercial weights, license
    banner shown by CLI).
- 14 designer/validator tests including entry-point loader checks against
  pyproject.toml.
- `bindsight design` now prints a Rich cost panel before exiting; with
  `--dry-run` it returns 0 cleanly.
- `bindsight validate` now prints a Rich cost panel.
- Total: 124 fast tests + 1 slow real-pydeseq2 test, all green.

### Added — docs (2026-05-10)
- `docs/what-is-bindsight.md` — 5-minute pitch / "deal-breaker" explanation.
- `docs/how-to-use.md` — end-to-end user guide with troubleshooting.
- `docs/use-cases.md` — four sized scenarios.
- README links the three docs at the top.

### Added — Phase 1 wiring (2026-05-09 batch 2)
- `bindsight.config` — Pydantic v2 `RunConfig` + per-stage param models with
  YAML loader. Validates the bundled `examples/tcga_luad.yaml` and rejects
  extras at every level so config drift fails loudly.
- `bindsight.deg.pydeseq2_runner.PyDESeq2Runner` — real pydeseq2 wrapper.
  Standardised Parquet output schema documented in the module docstring.
  ``slow`` test against the tiny fixture confirms end-to-end works.
- `bindsight.pipelines.discover` — orchestrator that joins:
  DEGs → Open Targets enrichment → SURFY surfaceome filter → tractability +
  safety filters → AlphaFoldDB structure pull → top-N ranking. Emits
  `targets/candidates.parquet`, `epitopes/epitopes.parquet`, and a per-run
  `run_manifest.jsonld` with PROV-O records for both stages.
- `bindsight discover` is now wired to the real pipeline (no longer a stub).
- `bindsight doctor` — diagnoses Python, optional deps, cache state, and
  vendored data root. Saves users from "why doesn't this work" tickets.
- `scripts/run_deg.py` and `scripts/run_discover.py` now call the real
  pipeline, not stubs.
- 24 new tests (config, deg runner, discover pipeline, doctor): 81/81 pass.
- `RENAME.md` — checklist for the eventual rename pass before publishing.

### Changed
- `bindsight discover` exits non-zero with a Pydantic ValidationError if the
  config is malformed (was: stub no-op).

### Added — Initial scaffold (2026-05-09 batch 1)
- Repository scaffold: README, ARCHITECTURE, LICENSING, CONTRIBUTING, CITATION.cff, LICENSE
- Python package skeleton with all module stubs (`io`, `deg`, `targets`, `surfaceome`, `structures`, `epitopes`, `design`, `runners`, `validate`, `rank`, `provenance`, `report`)
- `bindsight.provenance.manifest` — Pydantic v2 schema for `run_manifest.jsonld` (PROV-O JSON-LD)
- `bindsight` CLI shell (Click) with stubs for `discover`, `design`, `validate`, `rank`, `report`, `run`, `export`, `verify-licenses`
- Snakefile skeleton with `discover` rule
- Conda env `envs/discover.yaml` for the CPU discovery half
- Example pipeline config `examples/tcga_luad.yaml`
- pytest smoke test for the manifest schema
- GitHub Actions CI workflow (lint + test)
- `.gitignore`, `.editorconfig`

### Changed
- N/A (initial release)

### Removed
- N/A (initial release)

---

## [0.0.1-dev] - 2026-05-09

Initial scaffold. Not functional yet — see Phase 0 in [ARCHITECTURE.md](ARCHITECTURE.md#11-phased-roadmap).
