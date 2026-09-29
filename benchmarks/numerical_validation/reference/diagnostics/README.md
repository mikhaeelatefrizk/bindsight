# Bounded localization of historical eight-pair discrepancies

These files diagnose the regularization-only Python adapter, before the later mean-floor correction. They do not describe a fresh cohort fit with the corrected adapter. The diagnostic Python fit matched the saved historical `repaired_eight/forward.parquet` exactly, including all table values; its metadata and source hashes are retained here. It used one CPU. The ten genes were selected because they had large differences or changed significance decisions, with a high-mean control included.

`eight-outlier-diagnostics.tsv.gz` contains R and Python dispersion estimates and convergence/outlier flags. `eight-R-dispersion-means.tsv.gz` contains means from an R gene-wise rerun on these ten genes with the saved size factors; it reproduced the original R gene-wise dispersions within `1e-12`. `eight-mean-floor-proof.json` holds controlled dispersion comparisons. `eight-wald-floor-proof.json` holds controlled covariance comparisons with coefficients and dispersions fixed. No whole-cohort result was replaced by these diagnostic experiments.

For `ENSG00000139800`, six pre-dispersion means fell below 0.5. Flooring only those means, with the Python dispersion prior unchanged, moved MAP dispersion 5.096570 to 8.955560, compared with R 9.068652. Using R's means and prior gave 9.069180. Similar sparse-mean effects appear for `ENSG00000214978` and several other selected genes. For `ENSG00000156096`, fixing the existing coefficient and dispersion estimates while flooring only covariance means changed SE from 1.030699 to 0.993707, compared with R 0.994860. A covariance-only change cannot predict the final effect where dispersion also changes; the JSON retains examples where one isolated change moves further from R.

The largest historical SE discrepancy, `ENSG00000074803`, instead involved dispersion-outlier classification. R's gene-wise estimate 2.505196 matched the Python method-of-moments starting value; the R `noIncrease` rule can retain that starting value after insufficient objective improvement. R then retained it as an outlier, whereas Python used MAP dispersion 1.155398. R and Python MAP estimates were already close (1.156166 and 1.155398). All three Python gene-wise, MAP and coefficient convergence flags for this example were true. This is a separate heuristic difference; it is not evidence that one implementation is biological ground truth and was not copied into the adapter.

The exact R 1.52.0 release source archive identified in the parent README was inspected: `estimateDispersionsGeneEst` floors `fitMu` before dispersion, and `src/DESeq2.cpp::fitBeta` floors means before final weights and covariance. The Python 0.5.4 source returns raw IRLS means and passes them to these stages. This stage contract, together with objective/covariance regression tests, motivated a general repair independent of selecting favorable gene results.

## Replay the cheap Python calculations

The full cohort model/array files remain outside the repository with hashes and sizes in [artifact-manifest.json](artifact-manifest.json). The small [sparse-fixture.json](sparse-fixture.json) preserves all numeric inputs needed for these calculations. The following can be saved as a temporary Python file and run from the repository root in the pinned Python environment. It loads the explicitly hash-checked historical adapter source snapshot; it does not edit the installed library or current adapter. The checks reproduce the recorded diagnostic calculations, not an acceptance criterion for R agreement.

```python
import base64
import hashlib
import json
from pathlib import Path
import types

import numpy as np
from pydeseq2.utils import irls_solver, wald_test

root = Path("benchmarks/numerical_validation")
here = root / "reference/diagnostics"
snapshot = json.loads((root / "source_snapshots/regularization_only.json").read_text())
entry = snapshot["files"]["bindsight/deg/inference.py"]
source = base64.b64decode(entry["base64"])
assert hashlib.sha256(source).hexdigest() == entry["sha256"]
assert entry["sha256"] == "62a98b187accc69483e58fd266ae53bc94b306561576585ef4beb94ed2d7f764"
historical = types.ModuleType("historical_inference")
exec(compile(source, "historical_inference.py", "exec"), historical.__dict__)
inference = historical.RegularizedInference(n_cpus=1)
fixture = json.loads((here / "sparse-fixture.json").read_text())
expected_map = json.loads((here / "eight-mean-floor-proof.json").read_text())
expected_wald = json.loads((here / "eight-wald-floor-proof.json").read_text())
design = np.asarray(fixture["design_matrix"], dtype=float)
for gene, saved in fixture["genes"].items():
    counts = np.asarray(saved["counts"], dtype=float)
    mu = np.asarray(saved["python_mu_hat"], dtype=float)
    args = dict(
        counts=counts[:, None],
        design_matrix=design,
        mu=np.maximum(mu, 0.5)[:, None],
        alpha_hat=np.array([saved["python_fitted_dispersion"]]),
        min_disp=1e-8,
        max_disp=16.0,
        prior_disp_var=fixture["python_prior_disp_var"],
        prior_reg=True,
        cr_reg=True,
    )
    clipped, _ = inference.alpha_mle(**args)
    matched, _ = inference.alpha_mle(
        **(
            args
            | {
                "mu": np.asarray(saved["R_mu_hat"])[:, None],
                "alpha_hat": np.array([saved["R_dispFit"]]),
                "prior_disp_var": fixture["R_prior_disp_var"],
            }
        )
    )
    np.testing.assert_allclose(
        [clipped[0], matched[0]],
        [
            expected_map[gene]["python_MAP_clipping_only_same_prior"],
            expected_map[gene]["python_MAP_with_R_means_and_R_prior"],
        ],
        rtol=1e-9,
        atol=1e-10,
    )
    if gene in expected_wald:
        beta, raw_mu, _, _ = irls_solver(
            counts, np.asarray(fixture["size_factors"]), design, saved["python_final_dispersion"]
        )
        contrast = np.zeros(design.shape[1])
        contrast[-1] = 1
        args = dict(
            design_matrix=design,
            disp=saved["python_final_dispersion"],
            lfc=beta,
            mu=raw_mu,
            ridge_factor=np.eye(len(contrast)) * 1e-6,
            contrast=contrast,
            lfc_null=0,
            alt_hypothesis=None,
        )
        original = wald_test(**args)
        floored = wald_test(**(args | {"mu": np.maximum(raw_mu, 0.5)}))
        np.testing.assert_allclose(
            [original[0], original[2] / np.log(2), floored[0], floored[2] / np.log(2)],
            [
                saved["python_p"],
                saved["python_SE"],
                expected_wald[gene]["Python_same_fit_floored_covariance_p"],
                expected_wald[gene]["Python_same_fit_floored_covariance_SE"],
            ],
            rtol=1e-9,
            atol=1e-10,
        )
print("Reproduced ten dispersion and three fixed-fit covariance diagnostics.")
```

The original diagnostic scripts and original R reference script are preserved as exact base64 source bytes with SHA256 in this directory's manifest. The fixture export is a documented subset, not a substitute for the full R/Python cohort fits. Public-data input provenance is in the parent cohort directories, and full-cohort comparison denominators remain visible in each report.
