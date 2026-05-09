# Contributing to xpr2bind

Thanks for your interest. `xpr2bind` is in active development and contributions of all sizes are welcome.

---

## Quick start

```bash
git clone https://github.com/mikhaeelatefrizk/xpr2bind.git
cd xpr2bind
mamba env create -f envs/discover.yaml
mamba activate xpr2bind-discover
pip install -e ".[dev]"

# Run tests
pytest -m "not gpu"

# Run linters
ruff check .
ruff format --check .
mypy xpr2bind

# Run the discovery-half smoke test on a tiny fixture
xpr2bind discover tests/fixtures/tiny_config.yaml --out /tmp/xpr2bind_smoke
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
- **Adding a new designer:** implement the `xpr2bind.design.Designer` Protocol; add an entry to `pyproject.toml` `[project.entry-points."xpr2bind.designers"]`. Boilerplate in `xpr2bind/design/_template.py`.
- **Adding a new validator:** same pattern, `xpr2bind.validate.Validator` Protocol.
- **Adding a new GPU runner:** implement `xpr2bind.runners.GPURunner`; example in `xpr2bind/runners/mock.py`.
- **Adding a new data source:** implement a typed client in `xpr2bind/<module>/`; emit Parquet with documented schema; add a manifest entry.

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
