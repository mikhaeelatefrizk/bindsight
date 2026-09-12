# What ipTM 0.65 is worth

20 committed ERBB2 designs, each folded in the same job as a shuffle of its own sequence: same length, same amino-acid composition, same target, same validator, same card, same session. Only the residue order differs.

| | n | mean | median | sd | min | max |
|---|---|---|---|---|---|---|
| designs | 20 | 0.527 | 0.525 | 0.176 | 0.183 | 0.803 |
| scrambles | 20 | 0.570 | 0.644 | 0.186 | 0.126 | 0.737 |

Paired difference (design − scramble): median -0.015, mean -0.043. 9 of 20 designs beat their own scramble.

95% bootstrap interval on the mean difference: **[-0.142, +0.054]**. With 20 pairs and a spread of 0.230 between them, the smallest difference this run would catch 80% of the time is **0.144** — so it bounds any real advantage rather than showing there is none.

Exact paired sign-flip test over all 1,048,576 assignments: **p = 0.40420** (floor for 20 pairs: 1.91e-06).

## At the threshold the project ships (0.65)

- designs clearing 0.65: **30%**
- scrambles clearing 0.65: **50%** — the false-positive rate this threshold carries

| threshold | designs | scrambles |
|---|---|---|
| 0.50 | 60% | 75% |
| 0.55 | 40% | 60% |
| 0.60 | 35% | 55% |
| 0.65 | 30% | 50% |
| 0.70 | 25% | 30% |
| 0.75 | 10% | 0% |
| 0.80 | 5% | 0% |
| 0.85 | 0% | 0% |

10 of 20 scrambles clear 0.65. With 20 controls that is an exact 95% upper bound of **72.8%** — not 50%, which is what the count alone would suggest.

## Operating point

The lowest threshold whose false-positive **upper bound** clears each target. Judged on the bound rather than the count, so a threshold is never accepted on the strength of a rate this many controls cannot establish.

- **≤25% false positives → threshold 0.73**, keeping 15% of designs (bound 24.9%).
- **≤5% false positives: not established by this run.** 20 controls cannot certify a rate below 16.8% however cleanly the arms separate; 72 would be needed. This is a limit of the control set's size, not a statement about the designs.

## The metric's own noise

Each binder was folded 5 time(s), so every ipTM above is a mean of that many diffusion draws and each carries the spread of its own draws. Pooled across 40 binders, one draw has a standard deviation of **0.139** (range 0.022–0.282 within a single binder), which puts the standard error of each reported mean at **0.062**.

Measured inside one job on one input under one installed version, so unlike the refold comparison below nothing is confounded with anything.

The design-versus-scramble effect is 0.043. That is smaller than the spread of a single design's own draws, so the comparison is being made underneath the metric's noise floor.

### Where the spread actually is

Of the 0.230 spread between pairs, **15%** is the validator resampling the same input and **85%** is real variation from one design/scramble pair to the next.

That decides the next experiment, and the two answers look nothing alike. Drawing more structures per binder attacks only the first share; the second is a property of the designs themselves and no amount of resampling touches it. Against the irreducible part alone:

- detecting a 0.10 difference at 80% power needs **36 pairs**, however many draws each gets
- detecting a 0.05 difference at 80% power needs **142 pairs**, however many draws each gets

## Refold drift

The same 20 sequences also carry committed ipTM values from an earlier job. Refolding them here gives a bound on how far a number moves between runs — but the earlier job's Boltz-2 version was never recorded (see `PRECISION.md`), so this is run drift and version drift together, not a determinism measurement.

Absolute change: median 0.172, max 0.573.

The two runs agree on **rank** at Spearman r = 0.293 (Pearson 0.312), and **4 of 20** pass/fail verdicts at 0.65 differ between them. A drift that preserved rank would be an offset; one that does not leaves no per-design claim standing.
