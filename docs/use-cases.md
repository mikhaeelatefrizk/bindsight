# Use cases

> Three concrete scenarios where `bindsight` saves serious time and produces
> defensible artifacts. Each is sized for a single user with a CPU laptop and
> ≤$50 of cloud GPU budget.

---

## Use case 1 — Triaging a cancer cohort for surface-antigen targets

**Scenario.** You're a translational researcher with a TCGA cohort (or your
own RNA-seq study) of tumor vs. matched normal samples. You want a ranked
shortlist of cell-surface antigens that are (a) over-expressed in tumor,
(b) low in vital tissues, and (c) druggable with antibody-class binders. From
that shortlist, you want designed binder candidates.

**Without `bindsight`** (typical workflow today):
- Week 1: Run DESeq2, manually filter, dump gene list.
- Week 2: Cross-check against [SURFY](https://wlab.ethz.ch/surfaceome) by
  hand. Annotate UniProt accessions. Pull AlphaFoldDB structures one by one.
- Week 3: Set up RFdiffusion + ProteinMPNN environment on the cluster. Spend
  3 days on PyRosetta install issues.
- Week 4: Run designs. Set up Boltz-2 separately. Validate. Rank in Excel.
- Week 5: Realize you forgot to filter for safety liabilities. Restart.

**With `bindsight`:**

```bash
bindsight discover my_cohort.yaml --out runs/cohort_v01
bindsight design   runs/cohort_v01 --backend modal --designer rfdiff_mpnn --trajectories 50
bindsight validate runs/cohort_v01 --backend modal --validator boltz2
bindsight rank     runs/cohort_v01
bindsight report   runs/cohort_v01 --format html
bindsight export   runs/cohort_v01 --format ro-crate --out cohort_v01.crate.zip
```

**Wall time:** ~30 min CPU + ~5–10 GPU-hours on Modal A100 (~$25–40), or
several hours of free Colab.

**Output:** Ranked binders with iPTM > 0.65 against the top-5 surface antigens
in your cohort, every one traceable back to the patients it came from.

---

## Use case 2 — Methods benchmark of a new designer

**Scenario.** You're a methods developer who just published a new backbone
diffusion model and want to compare it against RFdiffusion, BindCraft, and
BoltzGen on a held-out target set with a fair upstream pipeline.

**Without `bindsight`:** you write 4 different driver scripts, hope you've
configured each fairly, and reviewers complain that the comparisons aren't
apples-to-apples.

**With `bindsight`:**

1. Implement your designer as a `bindsight.design.Designer` plugin
   (Protocol in `bindsight/design/protocol.py`, ~50 lines).
2. Register it via `pyproject.toml`:
   ```toml
   [project.entry-points."bindsight.designers"]
   my_designer = "my_package:MyDesigner"
   ```
3. Run the same config four times with different `--designer` flags:
   ```bash
   for d in rfdiff_mpnn bindcraft boltzgen my_designer; do
       bindsight run examples/benchmark_held_out.yaml --designer "$d" \
           --out runs/bench_${d}
   done
   ```
4. Compare via the bundled benchmark script:
   ```bash
   bindsight benchmark runs/bench_*/  --known-antigens benchmarks/known.tsv \
       --out benchmark_report.html
   ```

**Output:** A side-by-side comparison of all four designers on identical
inputs (same DEGs, same SURFY filter, same epitope prediction, same Boltz-2
validator), with the raw artifacts shipped as RO-Crates so reviewers can
re-run any cell.

---

## Use case 3 — Teaching computational biology end-to-end

**Scenario.** You're a PI running a graduate course on computational biology
and want one project that touches DEG analysis, structural biology, deep
learning, software engineering, and reproducibility — all in a 12-week
semester.

**The lesson plan with `bindsight`:**

| Week | Topic | Hands-on |
|---|---|---|
| 1–2 | RNA-seq + DEG | Run `bindsight discover` on a public TCGA cohort; interpret the volcano plot |
| 3 | Surfaceome + Open Targets | Inspect the `candidates.parquet`; understand each filter |
| 4 | Protein structure | Pull a candidate's AlphaFoldDB mmCIF; visualize in PyMOL |
| 5–6 | De novo design | Run `bindsight design --backend colab` (free); read the Colab notebook step by step |
| 7 | Validation | Boltz-2 vs Chai-1r — which agrees on which design? |
| 8 | Multi-objective ranking | Modify the rank weights; see which targets move |
| 9 | Reproducibility | Re-run with a different seed; diff the manifests |
| 10 | Report writing | Customize the HTML report template |
| 11 | Plugin development | Each student adds a custom filter or scorer |
| 12 | Final projects | Apply to a different cohort or disease |

The same single repo serves the full arc from "what is differential
expression" to "I added a custom plugin." Students get a portfolio piece.

---

## Use case 4 (bonus) — Pharma early-discovery comparator

**Scenario.** You're at a small biotech with a proprietary scoring model and
a few internal designers. You want a free, reproducible open-source pipeline
to run alongside, both for sanity checks and for collaborator handoffs.

**Why `bindsight` fits:**

- All defaults are MIT/Apache/BSD/CC-BY ([LICENSING.md](../LICENSING.md)).
- Plugin interface lets you wrap your proprietary designer / validator
  without forking. Internal models stay private; only the wrappers are added.
- Container-pinned reproducibility means a partner running the same Docker
  image gets byte-identical outputs.
- RO-Crate exports satisfy increasingly common funder reproducibility
  requirements.

**Concretely:**

```python
# in your_company/internal_designer.py — never published
class InternalDesigner:
    name = "internal_designer_v3"
    version = "3.2.1"

    def make_spec(self, ...) -> DesignSpec: ...
    def submit(self, spec, runner) -> DesignResult:
        # call your internal model, package results to bindsight's schema
        ...
```

Then in `pyproject.toml` of your private package:

```toml
[project.entry-points."bindsight.designers"]
internal_designer = "your_company.internal_designer:InternalDesigner"
```

`bindsight --designer internal_designer` Just Works alongside RFdiff+MPNN /
BindCraft / BoltzGen in the same comparison.

---

## What unifies these use cases

In every scenario above, the value isn't a single algorithm — it's the
*opinionated, reproducible join* between genomics evidence and protein
design, with provenance preserved. You bring the data and the question;
`bindsight` brings the pipeline.

If your use case isn't here, [open a discussion](../CONTRIBUTING.md) — we'd
like to add it.
