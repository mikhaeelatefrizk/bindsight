# Calibration: what the confidence numbers are worth

Every binder number bindsight publishes comes from Boltz-2, and until this
directory existed nothing said what those numbers meant.

Two specific gaps:

- **`DEFAULT_IPTM_SUCCESS = 0.65`** carries the project's headline figure —
  "40% success@0.65" — and arrived as a bare constant with no citation.
- **An ipTM of 0.88 has no scale attached.** High relative to what?

Neither is answerable by argument. Both need a control: something that should
*not* score well, run through the identical pipeline, so the scores have
something to be compared against.

## Stated before the data

Written before the first run returned, so the reading cannot be fitted to the
result afterwards. Each outcome below was an acceptable answer when this was
written; only one of them flatters the tool.

**The scramble control.** Take each committed ERBB2 design, shuffle its own
sequence, and fold the shuffle against the same target. A shuffle preserves
length and amino-acid composition exactly and destroys only the residue order —
which is the entire content of the design.

| if | then |
|---|---|
| scrambles score like the designs | ipTM is reporting something about the target, or about folding a peptide of that composition, and **not about the design**. The success rate is then not a design metric and the headline figure has to be withdrawn. |
| scrambles score clearly lower | the bar has a floor under it, and the fraction of scrambles clearing 0.65 is the false-positive rate the threshold carries. |
| scrambles score lower but many still clear 0.65 | the metric discriminates, but 0.65 sits too low to mean what the headline implies, and the operating point moves. |

The third outcome is the one worth naming in advance, because it is the easiest
to report as the second.

### Addendum: how small a rate twenty controls can establish

Added while the first job was still running, from the interval arithmetic rather
than from any result — so it is a statement about the experiment's size, and
could have been worked out before it was launched.

A control set where *nothing* passes still cannot prove an arbitrarily small
false-positive rate. With none of `n` passing, the exact 95% upper limit is
`1 - 0.025**(1/n)`:

| controls | upper bound on the false-positive rate |
|---|---|
| 20 | 16.8% |
| 36 | 9.7% |
| 72 | 5.0% |
| 368 | 1.0% |

So **twenty controls cannot certify a threshold below about 17%**, however
cleanly the two arms separate. The analysis reports the operating point at a
bound twenty controls *can* support, and for the tighter one reports how many
controls would be needed rather than a threshold — because an unreachable bound
is a fact about the control set, not about the designs, and reporting it as a
missing threshold would blame the wrong thing.

This is the concrete next experiment: more scrambles. The shuffle is random, so
each design yields as many controls as wanted, all composition-matched. Four per
design is eighty, past the seventy-two the table asks for, at roughly 2.2
minutes a fold.

**But eighty such controls are not eighty independent ones, and the table above
assumes they are.** Four shuffles of one design share its length and its exact
composition; they are four draws from the permutation distribution of a single
sequence, not four draws from the population of composition-matched peptides.
That makes the set twenty clusters of four, and an interval that assumes
independence would understate its own width — which is the same error this
addendum exists to avoid, one level down.

There is no way around it by rearranging: seventy-two *unrelated* controls would
need seventy-two distinct designs, and there are twenty. So the follow-up has to
be analysed with a cluster-aware interval over designs —
`cluster_bootstrap_interval` in `bindsight/benchmark/statistics.py`, which the
study already uses for exactly this shape — and `controls_needed_for` above,
being an independence calculation, is a **lower** bound on how many clustered
controls the same claim would take. How much larger depends on how correlated
shuffles of one sequence turn out to be, which this run will show and nothing
here should guess.

## What happened: the first row of the table

The first outcome, the one that invalidates the metric. Full numbers in
`CALIBRATION.md`; the short version:

- **Designs and their own shuffles cleared 0.65 at the same rate: 40% and 40%.**
- Paired difference +0.030, 13 of 20 designs beating their own shuffle where 10
  is chance, exact sign-flip p = 0.57.
- One shuffle scored **0.815** — above nineteen of the twenty designs.

So the headline was withdrawn, as this document said in advance it would have to
be. Stated precisely, though: the run **bounds** any real advantage at about
0.14 ipTM (95% CI −0.070 to +0.127). It was not powered to see anything
smaller, and "no difference found" is not "no difference".

### The refold control was worse, and it named the cause

The same twenty sequences also carry ipTM values from the earlier benchmark run.
Refolding them here gave **Spearman r = 0.065** — the same sequences, ranked
almost independently — with a median absolute move of 0.129, a maximum of 0.667,
and **eight of twenty pass/fail verdicts flipped**. The design published as best
(0.881) refolded at 0.418.

That is not a subtle effect, and it pointed at a cause rather than at the
designs. Boltz-2 builds structures by diffusion. Its `--seed` defaults to
`None` — "no seeding", in its own help text — and `--diffusion_samples` to 1,
and bindsight passed neither. **Every confidence number this project had
published was a single unseeded draw from a stochastic model**, and the spread
of that draw is four times the effect the scramble control was trying to
measure.

Both are fixed: the seed reaches the validator (derived per binder, so designs
do not share a random state), every draw is read and averaged rather than the
best one taken, and `iptm_n_samples` and `iptm_sd` record how many draws a
number rests on and how far apart they were.

### What is still open

Whether the designs are genuinely no better than their shuffles, or whether the
metric was simply too noisy to tell, **is not yet decided**. Those are different
conclusions and this run cannot separate them. The seeded re-run with five
diffusion draws per binder is what does: averaging five draws cuts the spread by
√5, which brings the smallest detectable difference from 0.145 down to about
0.065.

Until that lands, the honest statement is the narrow one: *at the threshold the
project ships, designs and composition-matched shuffles of themselves are
indistinguishable, and the measurement was too noisy for that to be evidence
about the designs.*

## Why the two arms are folded in one job

The first submission staged scrambles alone, to be compared against the
committed design scores. That was wrong, and would have been wrong even if it
had run: the committed scores come from a different job, and a control measured
in a different session is not a control.

It turned out to be a different Boltz-2 as well (see `PRECISION.md`), so the
pairing was load-bearing for a reason it was not chosen for. Both arms now go in
one payload: same target, same validator, same card, same session, same
installed version. The only difference inside a pair is the residue order.

## What this does not yet control for

**The target.** A scramble control asks whether the *sequence* matters. It does
not ask whether the *target* matters — the same designs folded against an
unrelated receptor would answer that, and nothing here does it yet. A design
that scores well against everything is not a binder for anything.

This is a real remaining gap, not a detail. It cannot be folded into the same
job, because a spec carries one target, so it necessarily crosses runs — which
is why the refold-drift figure the analysis reports matters: it bounds how far a
number moves between runs, and that bound is what a cross-target comparison has
to be read against.

**Anything beyond ipTM.** PAE-interaction, affinity and pLDDT are left alone
here. One metric, one control, one claim.

## The pieces

| file | what it is |
|---|---|
| `PRECISION.md` | audit of the one line the Kaggle kernel patches in Boltz-2, so fp32 is shown not to put an asterisk on any of this |
| `stage_scrambles.py` | builds the control set; `--with-originals` stages each design beside its own shuffle |
| `submit_calibration.py` | ships the staged set as a `validate_only` job — no designer runs, since the sequences already exist |
| `analyse.py` | the paired comparison and the threshold sweep |
| `CALIBRATION.md`, `RESULTS.json` | generated by `analyse.py` |

```bash
python benchmarks/calibration/stage_scrambles.py --out runs/calibration_paired --with-originals
python benchmarks/calibration/submit_calibration.py --staged runs/calibration_paired
python benchmarks/calibration/analyse.py --metrics runs/_design/<key>/metrics.jsonl
```

## Provenance of the first run

The first paired job was submitted before the validator-provenance fix landed,
so its metrics rows carry the old hardcoded `"2.0.1"` and its kernel log does
not name the installed Boltz-2. Its **design-versus-scramble comparison is
unaffected** — both arms were folded by the same installed version in the same
job, whichever version that was — but its refold-drift figure against the
committed scores confounds run drift with version drift, and is labelled that
way rather than being called determinism.

Runs from `boltz==2.0.3` onward are pinned, and the kernel logs what it
resolved.
