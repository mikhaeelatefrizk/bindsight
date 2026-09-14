## What this changes

<!-- One paragraph. What was wrong or missing, and what the change does about it. -->

## Why

<!-- The reasoning, not a restatement of the diff. If it fixes a defect, say how
     the defect could happen; if it adds a claim, say what backs it. -->

## Checks

- [ ] `python -m pytest -q` passes
- [ ] `ruff check bindsight tests scripts` and `ruff format --check` pass
- [ ] `mypy bindsight scripts` passes
- [ ] If it changes a published number, the artifact was regenerated and the
      generator produces no diff
- [ ] If it adds a guard, the guard was **mutation-tested**: the defect
      reintroduced, the guard confirmed to fail, the tree restored

## If this touches a claim

- [ ] Every surface stating the affected figure is updated, not just the one I
      was reading
- [ ] Any withdrawn figure still travels with its withdrawal

<!-- The failure this project keeps finding is a change that is correct in the
     file it was made in and leaves five other files asserting the old thing. -->
