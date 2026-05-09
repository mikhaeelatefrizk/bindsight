# Renaming `xpr2bind` to your final name

`xpr2bind` is the working name used throughout this scaffold. When you pick the
real name (something special and different for your GitHub) you'll need to do a
global rename. The list below is exhaustive — once these are done, `pytest -q`
should still pass.

## What you're renaming

Pick one short identifier (`{newname}`) for the package, and use the same string
everywhere. Conventions to follow:

- All-lowercase, no underscores ideally (e.g. `bindscope`, `surfaceforge`,
  `transbind`, `xpr2bind`, `targetforge`). PyPI prefers no dashes for new
  packages but allows them.
- Display title can be different (e.g. package = `bindscope`, paper title =
  "BindScope: …").
- Reserve the PyPI name early (`pip install build twine; python -m build;
  twine upload --repository testpypi dist/*`) before announcing.

## Files to update (`xpr2bind` → `{newname}`)

```
pyproject.toml                       # name, scripts entry, package, entry-points (5 occurrences)
CITATION.cff                         # title, repository-code, url
README.md                            # all references in prose, badges, repo path
ARCHITECTURE.md                      # all references
LICENSING.md                         # all references
CONTRIBUTING.md                      # all references
CHANGELOG.md                         # latest entry
LICENSE                              # copyright holder line stays; the comment block at the bottom mentions "xpr2bind itself" — update
data/surface_bind/README.md          # internal references
envs/discover.yaml                   # name field (`xpr2bind-discover` → `{newname}-discover`)
envs/design.yaml                     # name field
envs/validate.yaml                   # name field
envs/report.yaml                     # name field
examples/tcga_luad.yaml              # any prose references in comments
Snakefile                            # any prose references in comments
scripts/*.py                         # logger names ("xpr2bind.deg" → "{newname}.deg") + module docstrings
xpr2bind/**/*.py                     # ALL imports, logger names, docstrings, error messages, user-agents
tests/**/*.py                        # imports
.github/workflows/ci.yml             # any references
.github/workflows/zenodo.yml         # any references
```

## The directory rename

The Python package directory itself (`xpr2bind/`) needs to become `{newname}/`.

## One-shot rename recipe (PowerShell)

```powershell
$old = "xpr2bind"
$new = "yournewname"   # <-- edit this

# 1. Rename the package directory
Rename-Item -Path $old -NewName $new

# 2. Substitute all string occurrences (case-sensitive)
Get-ChildItem -Recurse -File `
    -Include *.py,*.md,*.toml,*.cff,*.yaml,*.yml,Snakefile,LICENSE `
    | Where-Object { $_.FullName -notmatch '\\\.venv\\|\\\.git\\|\\\.pytest_cache\\|\\\.ruff_cache\\|\\\.mypy_cache\\|__pycache__' } `
    | ForEach-Object {
        (Get-Content $_.FullName) -replace [regex]::Escape($old), $new `
            | Set-Content $_.FullName
    }

# 3. Reinstall in the venv so the entrypoint script regenerates
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" --quiet

# 4. Verify
.\.venv\Scripts\python.exe -m pytest -m "not gpu and not slow" -q
```

**Heads-up on side effects:**

- The CLI entry-point name comes from `pyproject.toml`'s `[project.scripts]`. After
  renaming, the binary moves from `.venv\Scripts\xpr2bind.exe` to
  `.venv\Scripts\{newname}.exe`. Step 3 above takes care of that.
- The cache directory under `%LOCALAPPDATA%\xpr2bind\Cache` won't move — clear or
  rename it: `Remove-Item -Recurse -Force "$env:LOCALAPPDATA\xpr2bind"`.
- `MANIFEST_SCHEMA_VERSION` doesn't need to change for a simple rename — only bump it
  if you change the schema shape.

## What does *not* need renaming

- The `data/surface_bind/` directory — that name comes from the upstream
  SURFACE-Bind project, not from `xpr2bind`.
- The `surfy_offline.txt` file inside the surfaceome module — that name comes from
  the upstream SURFY project.

## Final verification before pushing to GitHub

```powershell
# Lint, type-check, test
.\.venv\Scripts\python.exe -m ruff check {newname} tests scripts
.\.venv\Scripts\python.exe -m ruff format --check {newname} tests scripts
.\.venv\Scripts\python.exe -m pytest -m "not gpu and not slow" -q

# Sanity-check that no stale "xpr2bind" strings remain
Select-String -Path *.md,*.toml,*.cff,*.yaml,Snakefile,LICENSE,**\*.py `
    -Pattern "xpr2bind" `
    | Where-Object { $_.Path -notmatch '\\\.venv\\|\\\.git\\' }
# expect: 0 matches
```

Then create the GitHub repo, set the remote, and push:

```powershell
gh repo create mikhaeelatefrizk/{newname} --public --description "..."
git remote add origin git@github.com:mikhaeelatefrizk/{newname}.git
git push -u origin main
git tag -s v0.0.1 -m "v0.0.1 — initial scaffold"
git push origin v0.0.1     # triggers the Zenodo deposit hook
```

That's it.
