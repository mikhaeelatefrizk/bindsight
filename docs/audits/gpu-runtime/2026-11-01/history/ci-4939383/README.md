# Final CI evidence for 4939383

This package records [CI run 41336508233](https://github.com/mikhaeelatefrizk/bindsight/actions/runs/41336508233)
for head `493938376ffbbd554998c6b559a7c265827ffb73`. All 18 CI jobs passed; the separate Docker build also passed.
GitHub tested synthetic merge `831e8bc0ec84b0479c810a065a9ea7785edcb57c` of that
head into main `1b2c255d5b35a841aedabe60fb9fdec187d12804`.

The runtime receipt is an actual **CPU setup/import check**: both interpreters
report Python 3.11.18; CUDA execution and model downloads are false. This package
does not establish a completed full GPU workflow, scientific equivalence, or
successful hosted Colab/Modal execution. CPU CI and real GPU acceptance are
separate. The Linux Python 3.11 test job passed 2,893 tests with 84.61% coverage;
its complete 11-skip list and the selection basis for the MSA alarm, POSIX
snapshot, and SIGTERM cases are in `ci/run-summary.json` and
`ci/linux-test-summary.txt`. Quiet CI output does not list individual passing
test names; the evidence records selected cases plus the full passing outcome.

`ci/recipe-check.json` comes from artifact 13095970191; its original ZIP digest
was compared with GitHub's SHA256. `ci/artifact-provenance.json` records the
original archive/member hashes. Both freezes are derived exactly from that
receipt before public path normalization. `ci/auxiliary-cuda11-packages.json`
contains the separate auxiliary package inventory.

Compared with prior CI head `8773fed9baf6d75c0ec35ba5f1df9223e20c5efe`, all 56 RF/SE3 freeze entries and all four
auxiliary versions are identical. Their original 2026-11-01 advisory reports
are retained with an explicit prior basis, not represented as fresh queries.
The old query clock was not recorded; the prior evidence packaging timestamp
is retained. Boltz's sole dependency delta is platformdirs 4.14.2 to 4.14.3.
A fresh pip-audit 2.10.1/PyPI query of all 101 final normalized Boltz packages
ran from 2026-11-01T18:37:23.228658+00:00 to 2026-11-01T18:37:36.027422+00:00; it reported no known
vulnerabilities and skipped none. Inputs, response, exclusions and invocation
are included under `security/`.

Those package queries exclude the local Bindsight/Boltz wheels and pinned
RFdiffusion/SE3 sources. DGL is skipped by the package database query and retains
the known unpatched [RPC advisory](https://github.com/dmlc/dgl/security/advisories/GHSA-3x5x-fw77-g54c).
Distributed DGL/RPC is unsupported; local graph use does not remove the vulnerable
code. These reports do not certify comprehensive safety or native binary safety.

The manifest hashes every public file and records original input hashes and
transformations. CI paths are replaced with logical roots `/CI_RUNTIME`,
`/CI_REPOSITORY`, `/CI_TEMP` and `/CI_USER`; package names, versions and checksum
values are unchanged. Scope/query file references point to public files in this
package. Full logs, temporary signed download URLs, personal paths, credentials,
model bytes and runtime environments are excluded. Normalized freezes are
evidence, not executable installation instructions. Earlier evidence is preserved
outside this new directory and was not overwritten.
