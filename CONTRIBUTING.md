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
mypy bindsight scripts benchmarks

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

See [README.md § Repository map](README.md#repository-map) and [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Where to start

- **First-time contributors:** look at issues tagged `good-first-issue`.
- **Adding a new designer:** implement the `bindsight.design.Designer` Protocol (defined in `bindsight/design/protocol.py`); follow `bindsight/design/boltzgen.py` as the reference implementation, and add an entry to `pyproject.toml` `[project.entry-points."bindsight.designers"]`. Note that the CLI currently validates `--designer` against a fixed `click.Choice` list, so a third-party designer also needs its name added there and to the dispatcher in `bindsight/runners/job_exec.py` (see [ARCHITECTURE.md](ARCHITECTURE.md) — lifting that restriction is a roadmap item).
- **Adding a new validator:** same pattern, `bindsight.validate.Validator` Protocol.
- **Adding a new GPU runner:** implement `bindsight.runners.GPURunner`; example in `bindsight/runners/mock.py`.
- **Adding a new data source:** implement a typed client in `bindsight/<module>/`; emit Parquet with documented schema; add a manifest entry.

---

## Testing

Three markers are declared in `pyproject.toml` (`gpu`, `slow`, `integration`), but
only `slow` is currently applied to anything — a single real-API test in
`tests/test_deg_runner.py`. No test carries `gpu` or `integration` yet, and
nothing runs on a nightly schedule; CI runs one job:

```bash
pytest -m "not gpu and not slow" --cov-fail-under=75   # what CI runs
pytest                                                  # everything, incl. the slow test
```

The `gpu` and `integration` markers are reserved so that real-hardware and
end-to-end tests can be added without another CI change. Everything else is
pure-CPU unit tests with mocked GPU runners.

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
- [ ] Linters pass, over the same scope CI uses:
      `ruff check bindsight tests scripts benchmarks`,
      `ruff format --check bindsight tests scripts benchmarks`,
      `mypy bindsight scripts benchmarks`
- [ ] Docstrings on public functions
- [ ] Manifest schema updated if a new artifact type is introduced
- [ ] [LICENSING.md](LICENSING.md) updated if a new dependency is added
- [ ] [CHANGELOG.md](CHANGELOG.md) entry under `## [Unreleased]`
- [ ] Conventional commit subject

---

## Releasing (maintainer notes)

1. Bump version in `pyproject.toml`, `CITATION.cff`, `.zenodo.json` and `codemeta.json`.
2. Move `## [Unreleased]` entries in `CHANGELOG.md` to a new `## [vX.Y.Z] - YYYY-MM-DD` section.
3. Tag: `git tag -a vX.Y.Z -m "vX.Y.Z"`. (Tags and commits in this repository are
   **not** GPG-signed — see [SECURITY.md](SECURITY.md) for what is and is not
   verified about a release.)
4. Push: `git push origin vX.Y.Z`, then publish the GitHub release for that tag.
5. On release publish, `release-artifacts.yml` builds the wheel + sdist and attaches
   them with SHA-256 checksums. The PyPI upload job is gated on the
   `PYPI_TRUSTED_PUBLISHING` repository variable and is currently inert. The Zenodo
   DOI is minted by the GitHub–Zenodo integration when the release is published —
   there is no Zenodo workflow in this repository.

---

## Code of conduct

We follow the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) v2.1, reproduced in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## Questions

Open a discussion on GitHub. For licensing concerns, tag the issue `licensing` and we'll prioritize it.
