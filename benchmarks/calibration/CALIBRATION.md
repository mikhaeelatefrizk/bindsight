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

- **≤25% false positives → threshold 0.73**, keeping 3/20 = 15% of designs (3%–38%); control bound 24.9% over 20 controls. Threshold chosen from 101 candidates, so the design rate is in-sample.
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

## Does the target matter?

The same 20 designs folded against an unrelated receptor — NECTIN4's Ig-like V-type domain, 113 residues against the native target's 142, no shared fold or family. Paired per design, so each is its own control.

| | mean | median | min | max | clears 0.65 |
|---|---|---|---|---|---|
| designed target | 0.527 | 0.525 | 0.183 | 0.803 | 30% |
| unrelated target | 0.652 | 0.656 | 0.393 | 0.876 | 50% |

Paired difference (designed − unrelated): median -0.119, mean -0.125; 3 of 20 score higher on the target they were designed for. Exact sign-flip p = 0.01131.
95% interval on that difference: [-0.207, -0.041]; the smallest difference this many designs would catch 80% of the time is 0.124.

**That raw comparison is confounded, and the direction is the tell.** The unrelated receptor scores higher with *everything*, shuffles included: their mean rises from 0.570 on the designed target to 0.769 on it — a larger jump than the designs make. A target that folds well with any partner moves both arms, so native-versus-decoy measures the target's own propensity rather than whether these binders pick it out.

Subtracting each binder's own shuffle on each target cancels that. What is left is the question specificity actually asks: does a design beat its own shuffle by more on the receptor it was designed for?

- on the designed target, a design beats its shuffle by **-0.043**
- on the unrelated one, by **-0.117**
- difference: **+0.074** (95% CI -0.032 to +0.180, exact sign-flip p = 0.19984; 12 of 20 designs favour their own target)

So the controlled estimate points the expected way and does not clear its own noise: this many designs would only catch a difference of 0.156 or larger. Neither specificity nor its absence is established here — which is a different and weaker statement than the raw comparison appears to make.

The two arms are two jobs, because a spec carries one target. Same sequences, same pinned validator, same seeded derivation, five draws each — so read the difference against the refold drift below, which bounds what moves between runs on its own.

## Refold drift

The same 20 sequences also carry committed ipTM values from an earlier job. Refolding them here gives a bound on how far a number moves between runs — but the earlier job's Boltz-2 version was never recorded (see `PRECISION.md`), so this is run drift and version drift together, not a determinism measurement.

Absolute change: median 0.172, max 0.573.

The two runs agree on **rank** at Spearman r = 0.293 (Pearson 0.312), and **4 of 20** pass/fail verdicts at 0.65 differ between them. A drift that preserved rank would be an offset; one that does not leaves no per-design claim standing.
