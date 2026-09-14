# `benchmarks/` — the evidence

Everything this project claims, and the controls that test those claims. Four
independent bodies of work; read them in this order.

## [`study/`](study/) — does the discovery half find known antigens?

Fifteen whole, unstratified TCGA projects, patient-paired, scored against a
panel of 22 antigen-cohort pairs fixed in git before any cohort ran. Carries two
null models that point in different directions, and reports both.

**Start at [`study/RESULTS.md`](study/RESULTS.md).**

## [`calibration/`](calibration/) — what is an ipTM score worth?

A paired scramble control: every design folded beside a shuffle of its own
sequence. Its interpretation table was written down *before* the data arrived,
and the outcome it names as disqualifying is the one that happened — the
shuffles score as well as the designs.

This is why `success@0.65` is withdrawn as a measure of design quality.

**Start at [`calibration/README.md`](calibration/README.md).**

## [`designer_benchmark/`](designer_benchmark/) — the design half, run for real

20 ERBB2 domain-IV binders produced end to end on a free Kaggle T4, with the
real Boltz-2 complexes committed. Read it alongside the calibration above: the
structures are real, the confidence numbers are real, and what they do not
establish is binding.

**Reproducing it needs a GPU: [`RUN_FREE_GPU.md`](designer_benchmark/RUN_FREE_GPU.md).**

## [`provenance_join/`](provenance_join/) — the chain, exhibited once

The claim the project rests on: start at a ranked binder, reach the patient
samples. Run end to end on a target the discovery half chose for itself. That
directory states precisely which steps you can verify from a clone and which
need the crate rebuilt.

## Also here

- `known.tsv`, `binders.tsv`, `binders.fasta`, `sources.json` — the held-out
  known-antigen evaluation set, with provenance for every entry
- [`PROVENANCE.md`](PROVENANCE.md) — where the evaluation set came from
- [`RUN_ON_KAGGLE.md`](RUN_ON_KAGGLE.md) — running design work on free hardware
- `gpu_capacity/` — measured VRAM ceilings, which is why some designers are
  marked unrunnable on free hardware rather than merely untried
