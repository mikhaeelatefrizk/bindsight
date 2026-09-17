# `tests/` — 1,600+ tests, and most of them are not about code

78 test modules. The unusual thing about this suite is how much of it guards
**published claims** rather than functions.

## What the categories are

| Pattern | What it checks |
|---|---|
| `test_docs_claims.py` | Every number, command and claim in shipped prose against the artifact it comes from. The largest file here |
| `test_published_numbers_match_artifacts.py` | The study and designer-benchmark figures, wherever they are quoted |
| `test_silent_success.py` | Paths that could report success without having done the work |
| `test_correctness_regressions.py` | Specific defects that shipped once, each pinned so it cannot return |
| `test_packaging_pins.py` | What a wheel contains, what a container pins, what an entry point resolves to |
| `test_*_artifact.py` | Committed artifacts against the code that produced them |
| everything else | Ordinary unit and integration tests of the pipeline stages |

## Why so many guards on prose

The project's argument is that its claims are checkable. That only holds if the
prose and the artifacts agree — and they have not, more than once. A withdrawn
headline stayed live on six surfaces at the same time. So the numbers are read
out of the artifacts and compared against every document that states them.

## The rule these guards follow

**Discover, do not list.** A hand-written list of files or names is the defect
class this repository keeps finding: it passes while silently covering less than
it claims. Guards here glob, parse the AST, or introspect the registry. Where a
list is unavoidable, a sweep fails when the list goes stale.

The same rule caught a subtler failure: three tests read a file that
`.gitignore` excludes, so the suite was green here and red on every fresh clone.
File discovery is now git-aware for exactly that reason.

## Running them

```bash
pip install -e ".[dev,discover,report]"
python -m pytest -q          # no network, no GPU
```

Nine are skipped without `snakemake`, which will not build on every Python
version; those run in CI.
