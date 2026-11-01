# GPU runtime evidence staging — 2026-11-01

This is evidence for candidate 0.3.8, prepared before completion of the final
RFdiffusion → ProteinMPNN → Boltz GPU run. **Full GPU inference is pending.**
No file in this directory establishes a completed final scientific workflow.

* `components/` records real T4 component probes. The RF/SE3 probe used Hydra
  1.3.6; the later Boltz probe used Hydra 1.3.8 and the four-dependency metadata
  patch. Neither loaded scientific checkpoints or ran predictions.
* `ci/` records the canonical runtime import/setup check and all 18 passing jobs
  at `8773fed9baf6d75c0ec35ba5f1df9223e20c5efe`,
  [CI run 41321659720](https://github.com/mikhaeelatefrizk/bindsight/actions/runs/41321659720).
  The two saved freezes exactly match that receipt. The CUDA11 audit versions
  also match its auxiliary package inventory. Setup checks did not run CUDA or
  download models.
* `security/` includes advisory-query inputs/results/exclusions plus the manual
  DGL review. The CI DGL package query was skipped; its known unpatched RPC
  advisory remains applicable. Source packages and local wheels are outside
  package-database lookup. No result claims comprehensive freedom from vulnerabilities.
* `preservation/` records historical-file and wheel identity checks. These
  preserve implementation/result bytes, not numerical equivalence under a new
  dependency set. The submitted candidate wheel's comparison does not prove its
  still-pending GPU job completed.

The manifest gives original workspace-relative source paths and SHA256 values,
public artifact hashes, purpose and limitations. JSON is reformatted. Personal
Windows paths and CI home paths are replaced by explicit logical roots such as
`repository`, `upstream/...`, `/CI_RUNTIME` and `/CI_REPOSITORY`; package/version
and checksum identities are retained. Freeze and scope records with normalized
local paths are evidence, not executable installation instructions. The RF
setup receipt keeps selected identity/result fields; verbose loader reports
and duplicate hardware payloads are omitted. The CI summary omits step detail.
Internal collaboration identifiers are omitted from the DGL review.

No model weights, scientific input structures, credentials, private mail,
complete runtime environments or unrelated logs are included. The review is
static where explicitly identified; it does not establish network isolation,
native-library safety, successful Colab/Modal execution or biological efficacy.

DGL excerpts are from the checksum-verified official 1.0.2+cu118 wheel and remain
under Apache2.0 (see `licenses/`). RFdiffusion/SE3 excerpts retain their upstream
licence and copyright notices. Source identities and excerpts appear in the DGL
boundary record; this packaging does not change their licences.
