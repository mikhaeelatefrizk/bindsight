# GPU runtime evidence: candidate 38fb37a

Actual GPU acceptance: **passed-reviewed-small-smoke**. CI package: **included-see-manifest-scope**.
Production checkpoint CPU package: **passed-production-loader-cpu-only**.
Current candidate commit: `38fb37ae748e5a7c6430012dc4610c1a7d7abe2a`. Actual tested commit: `38fb37ae748e5a7c6430012dc4610c1a7d7abe2a`.
Exact tested/source-comparison wheel SHA256: `3e0ee56bcadb88e852ec20243b81b3a8a1226d857886872b4007da52517edea2`.

History retains earlier component probes, CI where supplied, the canceled first
attempt, and candidate4939383's checkpoint failure. Its RF target-geometry finding
and49-frame trajectory invariant are separately scoped partial evidence, not a
successful full pipeline. The final predicted target is upstream px0; no new
geometry quality threshold was invented and no scientific input was changed.

Current CI, strict preservation, checkpoint compatibility review/CPU evidence,
and actual GPU evidence are distinct. Missing inputs remain explicitly pending.
If tested/current commits differ, strict preservation verifies package byte
identity against the tested wheel; it does not relabel old CI as a new-head run.

This bundle records candidate scientific/CI evidence; it does not attest to
final release publication. Release/tag/main CI, built wheel,
website and public download identities are verified separately in the final release record. A small smoke
does not establish historical numerical equivalence or biological binding.
Live Colab/Modal execution remains unverified; the known DGL RPC advisory remains.
Nested manifests retain dates, scope and exclusions. Binary scientific evidence
is copied without deserialization and requires source-owner content review.

The checksums cover raw repository files, not rendered documentation HTML.
The [immutable release files](https://github.com/mikhaeelatefrizk/bindsight/tree/v0.3.8/docs/audits/gpu-runtime/2026-11-01)
retain each manifested file's original bytes. Start with the
[actual GPU verification](gpu/verification.json), [GPU evidence guide](gpu/README.md),
and [CI run record](ci/ci/run-summary.json).
