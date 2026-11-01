# Security & provenance

`bindsight` backs its results with per-run provenance manifests, content
hashes and checksummed releases. This page describes what those guarantees
actually are.

## Commit signing

**Commits in this repository are not currently signed.** An earlier version
of this page claimed that every commit and tag was signed with an SSH
signing key; that was not accurate, and the claim has been removed rather
than left standing. Of the commits in the published history, none carry a
verifiable author signature. Do not treat the absence of a "Verified" badge
as evidence of tampering, and do not treat its presence on the handful of
merge commits GitHub signed with its own web-flow key as author attestation.

Signing may be adopted in a future release. If it is, this section will say
so on the release that introduces it, not before.

## What the provenance guarantees actually are

- The [LICENSE](LICENSE) (AGPL-3.0-or-later) carries the copyright notice.
- [CITATION.cff](CITATION.cff) carries the author + ORCID metadata.
- **This release is not archived under a DOI.** Cite the repository, the tag
  you ran and the checksums attached to the release. A release is identified by
  its tag, the SHA-256 checksums published with its wheel and sdist, and the
  digest-pinned container image; an identifier that does not resolve is not a
  citation, which is why none is offered.
- Per-run [PROV-O](https://www.w3.org/TR/prov-o/) JSON-LD manifests are
  emitted by every pipeline stage and bundled into RO-Crate exports.
- ORCID [0009-0006-1069-9558](https://orcid.org/0009-0006-1069-9558)
  identifies the author across the repository metadata. ORCID is an identifier
  registry, not a cryptographic attestation, and it does not sign or verify
  commits.

## Reporting a vulnerability

Please open a private security advisory at
<https://github.com/mikhaeelatefrizk/bindsight/security/advisories/new> or
email the author at `mikhaeelatefrizk@proton.me` with the subject
`[bindsight security]`. Coordinated disclosure window: 90 days.

## Disclosure

A fixed vulnerability is announced in three places on the day the fix is
released: a GitHub security advisory in this repository's Security tab, with
the affected and patched version ranges for the `bindsight` package
(ecosystem `pip`) and a CVE requested through GitHub's CNA where the fix is in
a released version; a `### Security` subsection in that release's
[CHANGELOG.md](CHANGELOG.md) entry; and the release notes. The advisory is
published after the release that patches it exists, so the version it names
as patched is one that can be installed.

One is published: [GHSA-3p95-8fx3-2r5r](https://github.com/mikhaeelatefrizk/bindsight/security/advisories/GHSA-3p95-8fx3-2r5r)
— every template of the web interface `bindsight ui` serves was rendered with
Jinja autoescape off. Affects 0.3.0 through 0.3.4; fixed in 0.3.5. The
browser-side defect of the same class that 0.3.3 fixed predates this policy
and is recorded in that release's changelog entry, tag and release notes.

## Supply-chain notes

### 0.3.8: supported-Python GPU runtime (2026-11-01)

New managed GPU environments use Python 3.11.18 instead of the historical
Python 3.9 runtime. One provisioner serves local Linux/WSL, Kaggle, Colab and
Modal. Its source identity, recipe, installed packages and compatibility
adjustments are recorded in the setup receipt. A changed recipe rebuilds its
owned scientific environments; upgrading Bindsight does not patch an old
environment in place. See the [runtime guide](docs/gpu-runtime.md).

The package also raises its direct dependency minimums to the versions already
used in the audited installation: Pydantic 2.14.2, Requests 2.34.2, Jinja2 3.1.6
and, for discovery, Biopython 1.88. Earlier minimums allowed an upgrade to retain
affected installed versions even though fresh installations resolved newer ones.
The relevant upstream fixes include
[Pydantic validation](https://github.com/pydantic/pydantic/security/advisories/GHSA-3r8g-cqwr-jr29),
[Pydantic JSON validation](https://github.com/pydantic/pydantic/security/advisories/GHSA-qpmf-fgh3-ff25),
[Requests](https://github.com/psf/requests/security/advisories/GHSA-gc5v-m9x4-r6x2),
[Jinja 3.1.6](https://github.com/pallets/jinja/releases/tag/3.1.6) and
[Biopython](https://github.com/advisories/GHSA-x3vf-39hj-gxr4).
Their exploitability through Bindsight was not established. These requirement
changes preserve the tested dependency versions; they do not constitute a claim
that every third-party component is free of vulnerabilities.

The managed runtime pins PyTorch 2.14.1, beyond the 2.10.0 fix for checkpoint
deserialization advisory
[GHSA-63cw-57p8-fm3p](https://github.com/advisories/GHSA-63cw-57p8-fm3p).
Hydra 1.3.8 incorporates fixes for
[untrusted instantiation](https://github.com/advisories/GHSA-2cp2-2r3c-7p7r),
[logging callable resolution](https://github.com/advisories/GHSA-c3wx-c55w-pxjq),
[mutable policy bypass](https://github.com/advisories/GHSA-mwj6-rfh8-7qf4) and
[unsafe YAML loading](https://github.com/advisories/GHSA-wf6j-7hvr-gr93).
Hydra's 1.3 policy remains defense in depth: arbitrary untrusted configuration
must not be treated as safe executable model configuration.

Upstream Boltz 2.0.3 pins older vulnerable dependencies. The managed runtime
therefore installs local version `2.0.3+bindsight.1`: its verified upstream wheel
receives four requirement corrections (Hydra 1.3.8, PyTorch Lightning 2.6.6,
Requests 2.34.2 and Biopython 1.88), a local version and a regenerated wheel
record. All 106 files under `boltz/` and its licence remain byte-identical.
This is a distribution-metadata patch; dependency changes can still affect
runtime behavior, so byte preservation does not establish scientific equivalence.

Both RFdiffusion checkpoints have expected SHA256 pins and are checked before
use. Boltz's two checkpoints and CCD molecule archive are pinned by publisher
size and SHA256 at model revision
[`6fdef46d763fee7fbb83ca5501ccceff43b85607`](https://huggingface.co/boltz-community/boltz-2/tree/6fdef46d763fee7fbb83ca5501ccceff43b85607).
Cached files are rehashed and extracted molecule files are compared against
the authenticated archive before upstream loading. Unsafe archive paths,
links and unexpected extracted contents are rejected. This authenticates the
selected publisher's assets, not arbitrary user-provided pickle/checkpoint
files. The Boltz compatibility wrapper additionally authenticates the same file
handle before and after loading, restricts the exact asset-specific configuration
types and explicitly keeps `weights_only=True`. Prior permissions and the class
loader are restored; unrelated concurrent loads are unsupported because the
allowlist is process-wide. Actual CPU tests constructed both publisher models
through this production wrapper. The e3nn patch separately verifies its original
loader and constants before scoping a `slice` allowlist around its restricted
load. Neither adapter globally disables safe loading. These identity and
compatibility checks do not establish numerical equivalence between runtimes.

**Remaining known advisory:** DGL
[GHSA-3x5x-fw77-g54c](https://github.com/advisories/GHSA-3x5x-fw77-g54c)
covers the installed 1.0.2 library and lists no patched release. It concerns
pickle deserialization in distributed RPC services. Static review of the
supported Bindsight workflow and pinned RFdiffusion/SE3 source found local graph
operations and no calls to distributed server/RPC entry points. DGL nevertheless
imports and retains the vulnerable RPC code. DistDGL/RPC use is unsupported;
this source review is not a runtime network-isolation guarantee and does not
justify calling the complete GPU environment free of known vulnerabilities.

The earlier T4 design-component probe used Hydra 1.3.6; the prediction-component
probe used the corrected Boltz dependency patch and Hydra 1.3.8 but loaded no
weights and ran no predictions. Its dated lookup covered 92 PyPI versions,
excluding the local Boltz wheel. Current CI records measured freezes matching
the retained dated advisory reports, including their source-package and database
exclusions; this does not imply a fresh advisory query or comprehensive audit.

On 2026-11-01, the updated recipe completed the recorded one-backbone,
two-sequence, two-prediction smoke on a Kaggle Tesla T4 and passed all eight
independent artifact checks. See [validation status](docs/validation-status.md)
and the [dated evidence](docs/audits/gpu-runtime/2026-11-01/README.md). This computational result does
not remove the DGL advisory above or prove biological efficacy or cross-runtime
numerical equivalence. Historical releases and research artifacts remain retained;
new installations should use the current tested release.

### 0.3.7 certificate incident maintenance — historical record (2026-11-01)

Version 0.3.7 updated the publishing action for upstream
[GHSA-5xjx-3w67-w9x9](https://github.com/pypa/gh-action-pypi-publish/security/advisories/GHSA-5xjx-3w67-w9x9)
and raised the runtime certificate-bundle floor to certifi 2026.10.19.
Its desktop setup used verified uv 0.13.6 and Python 3.12.16; the CPU container
used a new Python 3.11.18 image digest and refreshed system certificates.
GPU installers switched to the same verified uv release instead of network
operations through the legacy environment's pip. That release left scientific
package pins unchanged.

GPU setup and generated Kaggle jobs deliberately ignore inherited uv/pip settings
and remove `SSL_CERT_FILE`, `SSL_CERT_DIR`, and `CURL_CA_BUNDLE` overrides.
Networks that require a private certificate authority through those variables
may therefore fail during setup. Custom certificate configuration is not currently
supported by these installers; use a connection that can validate the public
download endpoints without overriding certificate checks.

Updating this repository does not patch an existing local environment. Download
the new matching companion/source release, or update an existing Python
installation using the [Python security team's instructions](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576).
Those instructions cover patched Python, pip 26.2.2 or newer, uv 0.13.6 or newer,
and certifi 2026.10.19 or newer, including a hash-verified bootstrap for old pip.
Rebuild containers without old cached layers. The GPU workflow in 0.3.7 still
required Python 3.9 for its pinned RFdiffusion dependencies; Python 3.9 was
end-of-life. A patched external installer protected package downloads but did
not make that scientific interpreter maintained. The 0.3.8 runtime addresses
that separate issue above. No compromise of this project was established by
the maintenance investigation.

- Default pipeline code is MIT / Apache / BSD and its data sources CC0 / CC BY,
  except the SURFY surfaceome list, whose source states no terms — see
  [LICENSING.md](LICENSING.md) for the inventory and its review scope. NVIDIA
  CUDA runtime libraries have separate proprietary terms; permissive code
  licences do not describe every component of an installed GPU environment.
- Python dependencies carry minimum versions, and the scientific stack
  carries deliberate upper bounds, in [pyproject.toml](pyproject.toml).
  These are floors and ceilings, not exact pins: two installs on different
  days can resolve to different patch versions.
- The container base image **is** pinned by digest, not by tag, in the
  [Dockerfile](Dockerfile).
- `bindsight verify-licenses` prints a static, hand-maintained inventory of
  per-component licenses. Despite the name it performs no live check
  against upstream `LICENSE` files, so verify upstream yourself before
  relying on it for a legal decision.
