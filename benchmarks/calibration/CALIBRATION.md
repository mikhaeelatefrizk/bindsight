# What ipTM 0.65 is worth

20 committed ERBB2 designs, each folded in the same job as a shuffle of its own sequence: same length, same amino-acid composition, same target, same validator, same card, same session. Only the residue order differs.

| | n | mean | median | sd | min | max |
|---|---|---|---|---|---|---|
| designs | 20 | 0.550 | 0.568 | 0.218 | 0.200 | 0.868 |
| scrambles | 20 | 0.520 | 0.559 | 0.224 | 0.091 | 0.815 |

Paired difference (design − scramble): median +0.028, mean +0.030. 13 of 20 designs beat their own scramble.

95% bootstrap interval on the mean difference: **[-0.070, +0.127]**. With 20 pairs and a spread of 0.231 between them, the smallest difference this run would catch 80% of the time is **0.145** — so it bounds any real advantage rather than showing there is none.

Exact paired sign-flip test over all 1,048,576 assignments: **p = 0.56622** (floor for 20 pairs: 1.91e-06).

## At the threshold the project ships (0.65)

- designs clearing 0.65: **40%**
- scrambles clearing 0.65: **40%** — the false-positive rate this threshold carries

| threshold | designs | scrambles |
|---|---|---|
| 0.50 | 55% | 55% |
| 0.55 | 50% | 50% |
| 0.60 | 50% | 40% |
| 0.65 | 40% | 40% |
| 0.70 | 30% | 15% |
| 0.75 | 30% | 15% |
| 0.80 | 10% | 5% |
| 0.85 | 5% | 0% |

8 of 20 scrambles clear 0.65. With 20 controls that is an exact 95% upper bound of **63.9%** — not 40%, which is what the count alone would suggest.

## Operating point

The lowest threshold whose false-positive **upper bound** clears each target. Judged on the bound rather than the count, so a threshold is never accepted on the strength of a rate this many controls cannot establish.

- **≤25% false positives → threshold 0.80**, keeping 10% of designs (bound 24.9%).
- **≤5% false positives: not established by this run.** 20 controls cannot certify a rate below 16.8% however cleanly the arms separate; 72 would be needed. This is a limit of the control set's size, not a statement about the designs.

## Refold drift

The same 20 sequences also carry committed ipTM values from an earlier job. Refolding them here gives a bound on how far a number moves between runs — but the earlier job's Boltz-2 version was never recorded (see `PRECISION.md`), so this is run drift and version drift together, not a determinism measurement.

Absolute change: median 0.129, max 0.667.
