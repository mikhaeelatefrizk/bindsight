# Managed GPU runtime

The 0.3.8 runtime replaces the historical RFdiffusion Python 3.9 setup with
private Python 3.11.18 environments. Local Linux/WSL, Kaggle, generated Colab
notebooks and Modal call the same provisioner in
[`gpu_runtime.py`](https://github.com/mikhaeelatefrizk/bindsight/blob/main/bindsight/runners/gpu_runtime.py).
The recorded controls live in
[`gpu_recipe.py`](https://github.com/mikhaeelatefrizk/bindsight/blob/main/bindsight/runners/gpu_recipe.py).

**Validation status:** on 2026-11-01, the current recipe completed one
RFdiffusion backbone, two ProteinMPNN sequences and two Boltz predictions on
a Kaggle Tesla T4. The independent artifact verifier passed all eight checks for
the frozen protocol, transported evidence, runtime and model identities,
recorded commands, RF trajectories, sequences, structures and finite metrics.
The [evidence bundle](https://github.com/mikhaeelatefrizk/bindsight/tree/v0.3.8/docs/audits/gpu-runtime/2026-11-01) identifies the exact tested commit
and wheel. This is a small computational smoke, not a numerical-equivalence or
biological-efficacy study. No live Colab or Modal execution is established.

Earlier evidence is retained separately: the design-component probe used
Hydra 1.3.6, and the prediction-component probe used the corrected Boltz
dependencies but loaded no weights and ran no predictions. The first full
attempt ended without a completed archive or an established stopping cause.
The next completed RFdiffusion, ProteinMPNN and hosted MSA, then failed at
restricted checkpoint loading. A subsequent CPU test constructed both real
Boltz models through the production loader while retaining `weights_only=True`.
These dated attempts and component tests are not substituted for the completed run.

## Environment and source identity

| Component | Runtime control |
| --- | --- |
| Scientific Python | 3.11.18, private design and prediction environments |
| PyTorch | 2.14.1+cu126, official wheel URL and SHA256 |
| Local DGL graph library | 1.0.2+cu118, official wheel URL and SHA256 |
| Design NumPy / e3nn | 1.23.5 / 0.3.3 |
| Hydra | 1.3.8 |
| Prediction NumPy | 1.26.4 |
| RFdiffusion / ProteinMPNN | Existing source commits, unchanged |
| Boltz implementation | Upstream 2.0.3, installed as metadata-patched `2.0.3+bindsight.1` |
| Boltz dependency corrections | Hydra 1.3.8, PyTorch Lightning 2.6.6, Requests 2.34.2, Biopython 1.88 |
| Package installer | Verified uv 0.13.6; certifi floor 2026.10.19 |

The DGL wheel needs CUDA 11's runtime, cuSPARSE and cuBLAS libraries even though
PyTorch uses CUDA 12.6. These three packages live in a separate auxiliary prefix
so their files do not overwrite PyTorch's CUDA 12 headers and libraries. CUDA 11
cuRAND and cuSOLVER are not installed. This is a specific compatibility
arrangement, not a claim that arbitrary CUDA versions can be mixed. The NVIDIA
driver must support the selected libraries. The guided setup requires Linux x86_64,
at least 15,360 MiB total GPU memory and 60 GiB free disk for initial setup;
available GPU memory and actual model workload impose additional limits.

The setup fingerprints the Bindsight source, runtime recipe and installer.
It creates fresh owned scientific environments for a changed recipe and records
installed versions and checks in `provision-receipt.json`. A receipt is evidence
of those checks, not evidence of a completed scientific job. Old research and
historical release artifacts are retained separately.

Kaggle can carry the caller's wheel. Without one, it fetches the exact published
Bindsight version; an unshipped development ref cannot silently fall back to a
different release. Kaggle's 1 MB script limit prevents embedding some development
wheels. For these, the runner creates a unique **private** input dataset, attaches
its explicit `owner/slug/1` version and verifies the wheel's recorded size and
SHA256 on the GPU host before installation. The dataset remains a private
execution input for that run; it is not uploaded publicly or updated in place.
This transport changes neither the supplied wheel nor the default exact-version
download for published releases, and is not evidence of completed GPU inference.

Scientific commands stream bounded, redacted progress and write command receipts.
Kaggle also retains periodic progress and partial evidence during execution, so
an abrupt hosted-session termination leaves diagnostics even when final cleanup
cannot run. Boltz's hosted MSA service remains the default. Service queue or
network delays are distinct from GPU inference, and an incomplete run is never
reported as a successful prediction. Full PAE matrices are explicitly requested
to support the inter-chain error calculation without changing model parameters.
The hosted MSA phase has a 30-minute deadline, configurable through
`BINDSIGHT_MSA_TIMEOUT` in seconds (up to six hours). Its downloaded archives
must pass bounded path and file-type checks before extraction. This boundary
also bounds decompression and extended archive headers before parsing them.
Imported result archives use the same parser guard with their own size limits.
The MSA deadline
requires a Linux main thread with no existing alarm timer; an unsupported
execution context fails explicitly. It does not replace an MSA with an empty
alignment or change successful server responses.

Generated Colab notebooks use the exact published version
in a private driver. Modal's initial image installs that version through pip,
then verifies the wheel used to provision its scientific environments. The
shared release downloader checks the official HTTPS source, release metadata,
wheel size, SHA256 and internal package version. It does not follow moving Git
branches. Inherited package-index, certificate and Python-startup overrides are
removed for managed setup; required execution overrides are recorded without
serializing the host's full environment or credentials.

## Checkpoints and compatibility code

The local Boltz version changes distribution metadata to replace four upstream
dependency pins: Hydra 1.3.2 → 1.3.8, PyTorch Lightning 2.5.0 → 2.6.6,
Requests 2.32.3 → 2.34.2 and Biopython 1.84 → 1.88. The helper verifies the
original wheel's expected size and SHA256, updates its version and requirement
metadata, and regenerates the wheel record. All 106 files under `boltz/` remain
byte-identical to the original wheel, as does its licence. This preserves Boltz
implementation bytes; it does not establish identical numerical behavior under
the changed dependencies. The receipt records both wheel identities and the patch.

The publisher checkpoints contain OmegaConf configuration objects as well as
tensors. The production wrapper hashes the same open file before and after
loading, requires the measured metadata types for each pinned asset, and passes
`weights_only=True` explicitly. The allowlist is active only during that
authenticated loading call; the prior permissions and original class loader are
restored on success or failure. PyTorch's allowlist is process-wide, so this
adapter is limited to the single prediction driver and does not support unrelated
concurrent loads. It rejects arbitrary checkpoints. Both actual Boltz models
were constructed on CPU using this exact helper; this CPU result does not claim
GPU prediction. See the [checkpoint evidence](https://github.com/mikhaeelatefrizk/bindsight/tree/v0.3.8/docs/audits/gpu-runtime/2026-11-01).

Both RFdiffusion checkpoint downloads must match pre-established SHA256 pins.
Boltz's confidence checkpoint, affinity checkpoint and CCD molecule archive
must match the publisher's exact sizes and SHA256 values at the immutable
[model revision](https://huggingface.co/boltz-community/boltz-2/tree/6fdef46d763fee7fbb83ca5501ccceff43b85607)
`6fdef46d763fee7fbb83ca5501ccceff43b85607`. Existing cache files are rehashed;
the extracted molecule files are compared against the authenticated archive
before upstream loading. Extraction rejects unsafe paths and links, and the
receipt records the verified asset and molecule identities. The model names,
source commits and scientific weights are unchanged. These checks authenticate
the selected publisher's assets; they do not make arbitrary pickle/checkpoint
files safe or establish independent security review of every model asset.

The e3nn 0.3.3 compatibility adjustment verifies the original constant-loader
source and bundled constants before changing that one loader. It scopes the
`slice` allowlist to the verified constants load and retains PyTorch's
`weights_only=True` behavior. It does not globally disable safe checkpoint
loading. Original licence notices remain applicable to the modified package.

## Security and operating limits

PyTorch and Hydra are updated for the advisories linked in
[SECURITY.md](https://github.com/mikhaeelatefrizk/bindsight/blob/main/SECURITY.md).
The earlier T4 prediction-component probe's advisory lookup reported no known
vulnerabilities in 92 queried PyPI versions on 2026-11-01; its local Boltz wheel
was excluded and reviewed separately. Current CI records the complete measured
freezes and retained dated advisory results for the same versions, with source
package and database exclusions explicit. No new advisory query is claimed by
the freeze comparison. See the [dated audit scope](https://github.com/mikhaeelatefrizk/bindsight/tree/v0.3.8/docs/audits/gpu-runtime/2026-11-01).
These records are not a comprehensive audit of all installed code.
DGL's distributed RPC deserialization advisory remains unpatched. Static review
of the supported Bindsight workflow and pinned RFdiffusion/SE3 source found local
graph operations and no calls to distributed server/RPC entry points. DGL still
imports and retains the vulnerable RPC code. DistDGL/RPC use is unsupported;
the source review is not a runtime network-isolation guarantee or a complete
security audit.

The NVIDIA CUDA libraries have proprietary licence terms separate from the
permissive Python packages. See the scoped
[licensing inventory](https://github.com/mikhaeelatefrizk/bindsight/blob/main/LICENSING.md)
before redistributing an installed environment or container.

For maintainers, the provisioner's `--check-only` mode still installs software
and writes a receipt; it skips GPU operations and checkpoint downloads. It is
an installation/import check, not a read-only preview or full model validation.
Use a disposable owned setup directory for that check.

The preserved historical campaign required 14,859 MiB peak GPU memory on a T4.
A 2 GB MX450 cannot reproduce that workload. That historical measurement is not
the new smoke's memory usage. A completed run establishes computational
execution, not experimental binding, specificity or therapeutic safety. See
[validation status](validation-status.md).
