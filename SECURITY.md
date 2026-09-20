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
