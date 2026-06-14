# Changelog

All notable changes to `bindsight` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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

Initial scaffold. Not functional yet — see Phase 0 in [ARCHITECTURE.md](ARCHITECTURE.md#phased-roadmap).
