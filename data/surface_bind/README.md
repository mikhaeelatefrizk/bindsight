# SURFACE-Bind data root

This directory is **not** populated by `git clone`. SURFACE-Bind data must be
downloaded separately and placed (or symlinked) here.

## What goes here

A vendored copy of the [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind)
data tree at a pinned commit SHA. The `bindsight` SURFACE-Bind client expects to
find a structure like:

```
data/surface_bind/
    .commit_sha           # the upstream commit SHA we pinned to
    sites/                # one directory per UniProt
        P04626/
            sites.json    # SURFACE-Bind site records
            seeds/        # docked binder seeds (PDB)
        P00533/
        ...
```

## How to populate

### Option 1 — clone-and-pin (recommended for development)

```bash
cd data/surface_bind
git clone https://github.com/hamedkhakzad/SURFACE-Bind.git tmp_clone
cd tmp_clone
git checkout <COMMIT_SHA>
# Move the relevant data subtree (specifics depend on SURFACE-Bind's layout)
mv path/to/results ../sites
echo <COMMIT_SHA> > ../.commit_sha
cd .. && rm -rf tmp_clone
```

### Option 2 — point at an existing copy via env var

Skip the `data/surface_bind/` subtree entirely and set:

```bash
export bindsight_SURFACE_BIND_DATA=/path/to/your/surface_bind/sites
```

The `bindsight` SURFACE-Bind client reads this environment variable in
preference to the local `data/surface_bind/sites` path.

## Why not auto-download?

1. SURFACE-Bind doesn't ship a public REST API — there's nothing to query.
2. The data tree is sizable and we'd rather not re-download it on every CI run.
3. Keeping the user explicitly in the loop on which SURFACE-Bind commit they're
   running against is a feature for reproducibility — the commit SHA appears in
   the per-run manifest.

## License

SURFACE-Bind is BSD-3-Clause licensed. See the upstream repository for the
full text. bindsight itself is MIT-licensed and does not redistribute
SURFACE-Bind data.
