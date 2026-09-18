# Security & provenance

`bindsight` backs its results with per-run provenance manifests, content
hashes and archived releases. This page describes what those guarantees
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
- [CITATION.cff](CITATION.cff) carries the author + ORCID + DOI metadata.
- The Zenodo concept DOI [10.5281/zenodo.PENDING](https://doi.org/10.5281/zenodo.PENDING)
  resolves to the latest archived release; every tagged release gets its own
  version DOI on publish via `.github/workflows/zenodo.yml`, which deposits
  through Zenodo's (CERN-operated) API.
- Per-run [PROV-O](https://www.w3.org/TR/prov-o/) JSON-LD manifests are
  emitted by every pipeline stage and bundled into RO-Crate exports.
- ORCID [0009-0006-1069-9558](https://orcid.org/0009-0006-1069-9558)
  identifies the author across the Zenodo record and the repository
  metadata. ORCID is an identifier registry, not a cryptographic
  attestation, and it does not sign or verify commits.

## Reporting a vulnerability

Please open a private security advisory at
<https://github.com/mikhaeelatefrizk/bindsight/security/advisories/new> or
email the author at `mikhaeelatefrizk@proton.me` with the subject
`[bindsight security]`. Coordinated disclosure window: 90 days.

## Supply-chain notes

- Default pipeline components are MIT / Apache / BSD / CC-BY only — see
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
