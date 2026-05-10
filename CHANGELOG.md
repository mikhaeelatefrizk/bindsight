# Changelog

All notable changes to `xpr2bind` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added — Phase 3 "perfect demo" (2026-05-11)
- **`xpr2bind demo`** — one-command end-to-end run on a shipped 10-gene
  tumor-vs-normal cohort. Takes ~30 s on a CPU laptop, no internet required,
  no GPU required. The pipeline rediscovers ERBB2 (HER2) and EGFR as top
  antibody-tractable surface antigens, producing a real HTML report.
- **`examples/demo/`** — bundled `counts.tsv`, `design.tsv`, `config.yaml`
  for the demo. Files ship with the wheel via `[tool.hatch.build.targets.wheel.force-include]`.
- **`xpr2bind.report.html.render_run`** — paper-style HTML report renderer.
  Self-contained single-file output: embedded CSS, base64 PNG volcano plot,
  candidates table with badges, epitopes table, full PROV-O provenance table,
  styled to look like a Nature methods page. Pure jinja2 + matplotlib, no
  Quarto / Jupyter dependency.
- **`xpr2bind.report.streamlit_app`** — interactive Streamlit dashboard for
  browsing a run. Launched via `xpr2bind report <run> --format streamlit`.
- **`xpr2bind report`** is now wired (was stub).
- **`xpr2bind.targets.ensembl_uniprot`** — bundled offline ENSG → UniProt
  fallback map (~15 well-known cancer surface antigens + drivers). Used when
  Open Targets is disabled or unreachable; status `bundled_fallback` is
  recorded in the candidates table.
- **`docs/colab-design-howto.md`** — step-by-step recipe for running
  RFdiffusion + ProteinMPNN + Boltz-2 on Colab against a `xpr2bind` discover
  output. Documents the manual flow until live runner integration in v0.1.0-rc2.
- **README polished**: feature matrix showing what works today vs. what's
  pending; 60-second quickstart; cleaner install instructions.
- 18 new tests (demo E2E, ensembl_uniprot fallback, HTML report renderer,
  CLI demo + report). Total: **156 fast tests passing**, all green.
- Windows console fix: `sys.stdout.reconfigure(encoding='utf-8')` at CLI
  startup so Rich box-drawing chars + ≥/×/→ glyphs render on cp1252 terminals
  without crashing.

### Added — Phase 2 GPU-half scaffold (2026-05-10)
- `xpr2bind.cost` — real GPU cost estimator. Pricing table for Modal /
  Colab Pro+ / Kaggle / local across A100 / H100 / L4 / T4 / RTX4090 etc.
  Per-designer + per-validator timing tables (45 s/trajectory for
  RFdiff+MPNN, 240 s for BindCraft, 20 s/design for Boltz-2). Powers
  `--dry-run`. 15 tests.
- `xpr2bind.runners.notebook` — Jinja2-backed Jupyter notebook builder
  (envelope, code/markdown cells, strict-undefined rendering).
- `xpr2bind.runners.colab` — real Colab runner. Builds a self-contained
  `.ipynb` Jupyter notebook with Colab GPU metadata, install + spec +
  designer + package cells; user runs it and drops the resulting tarball
  back into the results directory for `poll`/`fetch` to detect. 6 tests.
- `xpr2bind.runners.modal_runner`, `xpr2bind.runners.kaggle`,
  `xpr2bind.runners.local_docker` — runner stubs with working cost
  estimators. Live `submit` lands in v0.1.0-rc2. 5 tests.
- Designer plugins (entry-point registered):
  - `xpr2bind.design.rfdiff_mpnn` — default designer. Real cache-key
    construction; mock-runner round-trip works today (real RFdiffusion in
    v0.1.0-rc2).
  - `xpr2bind.design.bindcraft` — premium designer (≥32 GB VRAM), stub.
  - `xpr2bind.design.boltzgen` — newest designer (MIT weights), stub.
- Validator plugins (entry-point registered):
  - `xpr2bind.validate.boltz2` — default validator.
  - `xpr2bind.validate.chai1r` — alt for cross-model agreement.
  - `xpr2bind.validate.af2_ig` — opt-in (non-commercial weights, license
    banner shown by CLI).
- 14 designer/validator tests including entry-point loader checks against
  pyproject.toml.
- `xpr2bind design` now prints a Rich cost panel before exiting; with
  `--dry-run` it returns 0 cleanly.
- `xpr2bind validate` now prints a Rich cost panel.
- Total: 124 fast tests + 1 slow real-pydeseq2 test, all green.

### Added — docs (2026-05-10)
- `docs/what-is-xpr2bind.md` — 5-minute pitch / "deal-breaker" explanation.
- `docs/how-to-use.md` — end-to-end user guide with troubleshooting.
- `docs/use-cases.md` — four sized scenarios.
- README links the three docs at the top.

### Added — Phase 1 wiring (2026-05-09 batch 2)
- `xpr2bind.config` — Pydantic v2 `RunConfig` + per-stage param models with
  YAML loader. Validates the bundled `examples/tcga_luad.yaml` and rejects
  extras at every level so config drift fails loudly.
- `xpr2bind.deg.pydeseq2_runner.PyDESeq2Runner` — real pydeseq2 wrapper.
  Standardised Parquet output schema documented in the module docstring.
  ``slow`` test against the tiny fixture confirms end-to-end works.
- `xpr2bind.pipelines.discover` — orchestrator that joins:
  DEGs → Open Targets enrichment → SURFY surfaceome filter → tractability +
  safety filters → AlphaFoldDB structure pull → top-N ranking. Emits
  `targets/candidates.parquet`, `epitopes/epitopes.parquet`, and a per-run
  `run_manifest.jsonld` with PROV-O records for both stages.
- `xpr2bind discover` is now wired to the real pipeline (no longer a stub).
- `xpr2bind doctor` — diagnoses Python, optional deps, cache state, and
  vendored data root. Saves users from "why doesn't this work" tickets.
- `scripts/run_deg.py` and `scripts/run_discover.py` now call the real
  pipeline, not stubs.
- 24 new tests (config, deg runner, discover pipeline, doctor): 81/81 pass.
- `RENAME.md` — checklist for the eventual rename pass before publishing.

### Changed
- `xpr2bind discover` exits non-zero with a Pydantic ValidationError if the
  config is malformed (was: stub no-op).

### Added — Initial scaffold (2026-05-09 batch 1)
- Repository scaffold: README, ARCHITECTURE, LICENSING, CONTRIBUTING, CITATION.cff, LICENSE
- Python package skeleton with all module stubs (`io`, `deg`, `targets`, `surfaceome`, `structures`, `epitopes`, `design`, `runners`, `validate`, `rank`, `provenance`, `report`)
- `xpr2bind.provenance.manifest` — Pydantic v2 schema for `run_manifest.jsonld` (PROV-O JSON-LD)
- `xpr2bind` CLI shell (Click) with stubs for `discover`, `design`, `validate`, `rank`, `report`, `run`, `export`, `verify-licenses`
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
