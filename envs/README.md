# `envs/` — conda environments

| File | What it is |
|---|---|
| `discover.yaml` | The discovery half's dependencies, for conda/mamba users |
| `constraints.txt` | Exact versions this release was tested against |

## Using it

```bash
mamba env create -f envs/discover.yaml
mamba activate bindsight-discover
pip install -e ".[dev,report]"
```

Plain `pip install -e ".[discover,report]"` from the root works too and is the
canonical path in the [README](../README.md); this exists for people who prefer
conda to resolve the scientific stack.

## Why upper bounds are pinned

The bounds on `pandas`, `numpy`, `scipy` and `pydeseq2` are not caution for its
own sake. These are the libraries whose release can move a number a run reports
— `formulaic`, pydeseq2's design-matrix engine, can change a log2 fold change on
its own. `constraints.txt` records what was actually tested, so a result can be
reproduced against the stack that produced it.
