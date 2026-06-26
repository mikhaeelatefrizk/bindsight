# Contributing to bindsight

Thanks for your interest. `bindsight` is in active development and contributions of all sizes are welcome.

---

## Quick start

```bash
git clone https://github.com/mikhaeelatefrizk/bindsight.git
cd bindsight
mamba env create -f envs/discover.yaml
mamba activate bindsight-discover
pip install -e ".[dev]"

# Run tests
pytest -m "not gpu"

# Run linters
ruff check .
ruff format --check .
mypy bindsight

# Run the discovery-half smoke test on the bundled example cohort
bindsight demo
```

---

## Development principles

1. **Reproducibility before features.** A new module is not done until its output is byte-deterministic given pinned inputs and a recorded seed.
2. **Provenance is mandatory.** Every module emits a manifest entry. No silent state.
3. **Modules are swappable.** New designers/validators implement a `Protocol`; they don't fork the pipeline.
4. **Honest about limitations.** README, ARCHITECTURE, LICENSING, and per-module docs say what doesn't work and why.
5. **Default to the most permissive license** that achieves the goal. Opt-in for restrictive components.

---

## Repository structure

See [README.md § Repository layout](README.md#repository-layout) and [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Where to start

- **First-time contributors:** look at issues tagged `good-first-issue`.
- **Adding a new designer:** implement the `bindsight.design.Designer` Protocol; add an entry to `pyproject.toml` `[project.entry-points."bindsight.designers"]`. Boilerplate in `bindsight/design/_template.py`.
- **Adding a new validator:** same pattern, `bindsight.validate.Validator` Protocol.
- **Adding a new GPU runner:** implement `bindsight.runners.GPURunner`; example in `bindsight/runners/mock.py`.
- **Adding a new data source:** implement a typed client in `bindsight/<module>/`; emit Parquet with documented schema; add a manifest entry.

---

## Testing

We have three test markers:

- `not gpu` (default in CI) — pure-CPU unit and integration tests with mocked GPU runners. Must pass in <5 min.
- `gpu` — real GPU tests (require local NVIDIA + CUDA). Skipped in CI.
- `slow` — long integration tests against real APIs (rate-limited). Skipped by default; runs nightly.

```bash
pytest -m "not gpu and not slow"   # fast feedback
pytest -m gpu                       # local GPU smoke
pytest -m slow                      # real APIs (cache hit may be required for rate limits)
```

Test fixtures live in `tests/fixtures/`. Follow the existing pattern of small, version-pinned, license-clean inputs.

---

## Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(targets): add HPA tissue-specificity client
fix(provenance): include CUDA version in container digest
docs(architecture): clarify runner abstraction
chore(deps): bump pydeseq2 to 0.5.4
test(rank): cover tie-breaking edge cases
```

Scopes match top-level module names (`io`, `deg`, `targets`, `surfaceome`, `structures`, `epitopes`, `design`, `runners`, `validate`, `rank`, `provenance`, `report`, `cli`, `docs`, `ci`).

---

## Pull request checklist

- [ ] Tests added or updated (in `tests/`)
- [ ] Linters pass (`ruff check`, `ruff format --check`, `mypy`)
- [ ] Docstrings on public functions
- [ ] Manifest schema updated if a new artifact type is introduced
- [ ] [LICENSING.md](LICENSING.md) updated if a new dependency is added
- [ ] [CHANGELOG.md](CHANGELOG.md) entry under `## [Unreleased]`
- [ ] Conventional commit subject

---

## Releasing (maintainer notes)

1. Bump version in `pyproject.toml` and `CITATION.cff`.
2. Move `## [Unreleased]` entries in `CHANGELOG.md` to a new `## [vX.Y.Z] - YYYY-MM-DD` section.
3. Tag: `git tag -s vX.Y.Z -m "vX.Y.Z"`.
4. Push: `git push origin vX.Y.Z`.
5. CI builds the wheel, publishes to PyPI, and triggers the Zenodo deposit workflow which mints a DOI.

---

## Code of conduct

We follow the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).

---

## Questions

Open a discussion on GitHub. For licensing concerns, tag the issue `licensing` and we'll prioritize it.
