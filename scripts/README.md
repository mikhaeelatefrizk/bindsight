# `scripts/` — generators and stage entry points

Two kinds of thing live here. Neither is part of the installed package.

## Generators — they write committed files

Run these when the thing they generate needs to change; the output is committed.

| Script | Writes | Needs |
|---|---|---|
| `build_docs_results.py` | `docs/results.md`, `docs/glossary.md`, published figures | nothing — reads committed artifacts |
| `make_og_image.py` | `docs/assets/og-image.png` | nothing |
| `build_surfy_list.py` | the vendored SURFY surfaceome | network |
| `build_surfy_gene_map.py` | the SURFY gene map | network |
| `build_surfaceome_extension.py` | the UniProt membrane extension | network |

`build_docs_results.py` is the one to know: everything on the published results
page is read from committed files, so running it should produce no diff. A test
fails if it does.

## Stage entry points — Snakemake calls these

`run_deg.py`, `run_discover.py`, `run_design.py`, `run_validate.py`,
`run_rank.py`, `run_report.py`, `assemble_manifest.py`.

Thin wrappers that let the [`Snakefile`](../Snakefile) drive the same stage
functions the CLI calls. They are not an alternative API — if you are writing
code against bindsight, import from the package.

## Why these are linted and type-checked

CI runs `ruff check bindsight tests scripts benchmarks`,
`ruff format --check bindsight tests scripts benchmarks` and
`mypy bindsight scripts benchmarks`. An
arity bug in a stage wrapper here left the Snakemake front-end dead for five
weeks without a single test noticing, because the wrappers were outside the
checked scope. They are inside it now.
