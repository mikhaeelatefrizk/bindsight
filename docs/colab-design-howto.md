---
description: Generate and run Bindsight's managed Colab notebook, then import its recorded design and prediction results.
---

# Generate a managed Colab notebook

Bindsight can write a notebook for RFdiffusion → ProteinMPNN → Boltz-2 using
the shared GPU provisioner and job executor. **A complete live Colab GPU run has
not been verified.** Local checks cover notebook generation and result import;
they do not establish that a particular Colab allocation can finish the job.
See [validation status](validation-status.md) and the
[managed runtime guide](gpu-runtime.md) for current evidence and requirements.

## Before you start

- Use a completed discovery run with its `config.yaml`,
  `epitopes/epitopes.parquet`, and target structure files available. The examples
  below use `runs/my-analysis`; replace it with your own run directory.
- Generate the notebook with the published Bindsight release you intend to run.
  Its setup verifies and installs that exact release from PyPI. Maintainers can
  explicitly select a candidate wheel through the Python runner interface;
  ordinary notebook generation never implicitly transfers checkout changes.
- Use a Colab GPU allocation that meets the [managed runtime requirements](gpu-runtime.md),
  including sufficient GPU memory and setup disk. Free access does not guarantee
  those resources. Check your account's available runtime and quota before starting.

Keep historical runs and their result archives intact when starting new work.
The notebook carries the recorded target structure, chain, hotspots and design
ranges, along with the configured seed and binder-length bounds.

## 1. Generate notebooks for your targets

Preview the target count and estimated work without launching a job or writing
notebooks:

```bash
bindsight design runs/my-analysis --backend colab --designer rfdiff_mpnn --validator boltz2 --trajectories 1 --dry-run
```

`--trajectories 1` requests one backbone trajectory **per eligible target**, not
one job for the entire run. The estimate is a planning aid, not a runtime or
resource guarantee. If the CLI reports no targets with structures, complete the
discovery and structure-fetching steps first.

Remove `--dry-run` to generate the notebooks:

```bash
bindsight design runs/my-analysis --backend colab --designer rfdiff_mpnn --validator boltz2 --trajectories 1
```

The notebooks appear under `runs/my-analysis/design/`, one for each selected
target/site. Keep their generated filenames and the accompanying `.spec.json`
files in that directory; the result importer checks those saved job inputs.

## 2. Run the generated notebook in Colab

1. Open a generated `.ipynb` in Colab and select a GPU runtime. The notebook
   requests a T4; setup checks the device actually supplied.
2. Run its cells in order. The setup cell verifies the Bindsight release wheel
   and installer, creates private environments, and prepares the shared
   scientific runtime and authenticated model assets.
3. Check the structure-loading cell. It normally restores the embedded target;
   if it reports a missing structure, upload the required file to the exact
   location it prints before continuing.
4. Run the design and prediction cell. It invokes Bindsight's managed executor
   with the recorded job specification and environment receipt.

The generated setup and execution cells provide the complete tool installation
and Boltz invocation. They include the supported dependency recipe, model checks
and GPU precision handling. Preserve the cell output if setup or execution fails;
a detected GPU or a successful installation is not a completed prediction.

## 3. Download and import the results

The final notebook cell downloads `<handle>.tar.gz` from `/content/`. Save the
original archive, with its generated filename, directly into your local
`runs/my-analysis/design/` directory. Complete and download the result for every
notebook generated for that run before final validation. Leave the archives
packed; Bindsight performs the import.

Keep the notebooks and the setup receipt
(`/content/bindsight_tools/provision-receipt.json`) with your run records. The
result archives carry the generated designs, prediction outputs and execution
evidence.

On your own computer, run:

```bash
bindsight validate runs/my-analysis
bindsight rank runs/my-analysis
bindsight report runs/my-analysis --format html
```

Validation imports matching notebook results and materialises their recorded
metrics; it does not launch another Boltz prediction. The import checks the
expected job identity and archive paths and refuses conflicting output. If a
result is missing or rejected, inspect the message and retain the original files
rather than overwriting existing research results.

These outputs are computational predictions. Sharing an executor does not
establish identical numerical results across different hardware, and confidence
scores do not establish experimental binding or specificity.

## Headless alternative: Kaggle

The Kaggle backend runs jobs and retrieves their results automatically. Set up
your own account credentials and review the current quota, then preview the work:

```bash
bindsight design runs/my-analysis --backend kaggle --designer rfdiff_mpnn --validator boltz2 --trajectories 1 --dry-run
```

Remove `--dry-run` when ready to submit. After successful retrieval, use the same
`validate`, `rank`, and `report` commands above. See the
[Kaggle setup guide](https://github.com/mikhaeelatefrizk/bindsight/blob/main/benchmarks/RUN_ON_KAGGLE.md) and
[current runtime status](gpu-runtime.md). The preserved
[historical benchmark walkthrough](https://github.com/mikhaeelatefrizk/bindsight/blob/v0.3.7/benchmarks/designer_benchmark/RUN_FREE_GPU.md)
describes the earlier campaign; its old environment versions are not the current
managed setup.
