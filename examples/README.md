# `examples/` — runnable configurations

Each file is a complete run configuration. Point `bindsight` at one and it runs.

| File | What it does |
|---|---|
| `tcga_luad.yaml` | Lung adenocarcinoma from TCGA, downloaded on first use. The config the Quickstart uses |
| `benchmark_held_out.yaml` | Scores rediscovery against the held-out known-antigen set |
| `provenance_join.yaml` | The end-to-end join: discovery through design, with the full provenance chain |
| `demo/` | What `bindsight demo` runs — a real TCGA-BRCA tumour-versus-normal cohort |

## Using one

```bash
bindsight discover examples/tcga_luad.yaml --out runs/luad
```

The `config` argument is positional, not a `--config` flag.

## Writing your own

The schema is [`bindsight/config.py`](../bindsight/config.py) — Pydantic models,
so an invalid config fails at load with a message naming the field rather than
part way through a run.

The minimum is a counts matrix and a sample design table naming a two-level
factor. Nothing on that path is cancer-specific; the `inputs.download` block
that knows about TCGA is optional, and pointing `inputs.counts` and
`inputs.design` at your own files skips it entirely.
