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

### November 2026 certificate incident maintenance

Version 0.3.7 updates the publishing action for upstream
[GHSA-5xjx-3w67-w9x9](https://github.com/pypa/gh-action-pypi-publish/security/advisories/GHSA-5xjx-3w67-w9x9)
and raises the runtime certificate-bundle floor to certifi 2026.10.19.
The desktop setup uses verified uv 0.13.6 and Python 3.12.16; the CPU container
uses a new Python 3.11.18 image digest and refreshed system certificates.
GPU installers use the same verified uv release instead of network operations
through the legacy environment's pip. Scientific package pins are unchanged.

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
Rebuild containers without old cached layers. The generated GPU workflow still
needs Python 3.9 for its pinned RFdiffusion dependencies; Python 3.9 is end-of-life.
Using a patched external installer protects package downloads but does not make
that scientific interpreter a maintained Python release. No compromise of this
project was established by the maintenance investigation.

- Default pipeline code is MIT / Apache / BSD and its data sources CC0 / CC BY,
  except the SURFY surfaceome list, whose source states no terms — see
  [LICENSING.md](LICENSING.md) for the full per-dependency inventory.
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
