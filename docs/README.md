# `docs/` — the documentation site source

Built with [mkdocs-material](https://squidfunk.github.io/mkdocs-material/). The
navigation is defined in [`../mkdocs.yml`](../mkdocs.yml).

| Page | What it is |
|---|---|
| `index.md` | The site landing page |
| `results.md` | **Generated** — do not edit by hand |
| `glossary.md` | **Generated** — do not edit by hand |
| `what-is-bindsight.md` | The five-minute read |
| `how-to-use.md` | Task-oriented walkthrough |
| `try-your-data.md` | Check your own counts matrix and design table, in the browser |
| `use-cases.md` | Worked scenarios |
| `colab-design-howto.md` | Designing on Colab |
| `positioning.md` | How bindsight relates to neighbouring tools |

## The two generated pages

`results.md` and `glossary.md` are written by
[`../scripts/build_docs_results.py`](../scripts/build_docs_results.py), which
reads the committed artifacts under `../benchmarks/`. Editing them by hand is
pointless — the next build overwrites it — and a test fails if they drift from
their generator.

```bash
python scripts/build_docs_results.py   # regenerate; the diff should be empty
```

That is also the fastest way to check a published number: everything on the
results page is read from a file in this repository.

## Building the site

```bash
pip install -e ".[docs]"
mkdocs serve      # http://localhost:8000
```

The root [README](../README.md) is deliberately self-sufficient: everything a
visitor needs is reachable on GitHub without this site.
