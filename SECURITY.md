# Security & provenance

`bindsight` v0.1.0 onwards uses **cryptographic commit signing** as part of
its provenance guarantees.

## Verified commits

Every commit and tag from this point forward is signed with an SSH signing
key registered to the author's GitHub account. GitHub renders a green
**"Verified"** badge next to every signed commit; you can verify any commit
yourself:

```bash
git log --show-signature -1 <commit-sha>
```

This complements the other provenance layers in `bindsight`:

- The [LICENSE](LICENSE) (AGPL-3.0-or-later) carries the copyright notice.
- [CITATION.cff](CITATION.cff) carries the author + ORCID + DOI metadata.
- The Zenodo DOI [10.5281/zenodo.20121496](https://doi.org/10.5281/zenodo.20121496)
  archives the v0.1.0 release; v0.2.0 and later are archived on publish via
  the GitHub–Zenodo integration (CERN-operated).
- Per-run [PROV-O](https://www.w3.org/TR/prov-o/) JSON-LD manifests are
  emitted by every pipeline stage and bundled into RO-Crate exports.
- ORCID [0009-0006-1069-9558](https://orcid.org/0009-0006-1069-9558)
  cryptographically links the author identity to the GitHub commits, the
  Zenodo DOI, and the JOSS paper.

## Reporting a vulnerability

Please open a private security advisory at
<https://github.com/mikhaeelatefrizk/bindsight/security/advisories/new> or
email the author at `mikhaeelatefrizk@proton.me` with the subject
`[bindsight security]`. Coordinated disclosure window: 90 days.

## Supply-chain notes

- Default pipeline components are MIT / Apache / BSD / CC-BY only — see
  [LICENSING.md](LICENSING.md) for the full per-dependency inventory.
- All Python dependencies are pinned with minimum versions in
  [pyproject.toml](pyproject.toml). Container image digests will be pinned
  for reproducible runs in a future release.
- `bindsight verify-licenses` prints the per-component license inventory
  on demand.
