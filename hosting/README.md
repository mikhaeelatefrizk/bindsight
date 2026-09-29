# Hosted workspace publication

Every successful CI run for the latest `main` revision triggers the Docs workflow.
It builds the documentation and `site/workspace` from that same commit, including
original evidence, a local source download, and the four platform companions
from that exact successful CI run. Each companion must have a matching revision,
checksum and successful packaged self-test before publication. The workflow refuses an older
revision and deploys through the protected `github-pages` environment.

The existing public Sites address uses `site-proxy.mjs` to serve this fixed origin:
https://mikhaeelatefrizk.github.io/bindsight/workspace/

The relay accepts only GET/HEAD requests for authored artifact paths. It does not
accept analysis uploads, forward visitor credentials, or execute scientific jobs.
An unavailable upstream produces an explicit 503 response. Short cache lifetimes
mean a successful GitHub publication can take a little time to become visible.
The unavailable page also links directly to the GitHub Pages workspace so a
relay failure does not leave visitors without access to a healthy publication.

The relay uses `redirect: 'manual'` and explicitly rejects every redirect or
other non-success response. `redirect: 'error'` is unsupported by the tested
workerd runtime and throws during request construction, even when the upstream
would respond without a redirect. Failure logs contain only a bounded reason,
upstream status and exception type. They omit visitor URLs/headers, upstream
bodies, redirect locations and exception messages.

`release.json`, the evidence bundle and `SOURCE_REVISION.json` inside the download
identify the source revision. Existing local installations do not update
silently: download a new workspace to use a new release. Changes to the relay
itself require a new deployment of the existing Site; ordinary interface,
evidence and analysis-engine changes follow the GitHub publication automatically.

The Site intentionally has no cloud database. Published evidence is versioned in
GitHub, while private uploads, job state and results remain in each visitor's
local workspace. Accounts or shared projects would require a separate data and
access design; a database would not provide local GPU execution.

Run the relay's tests with `node --test hosting/site-proxy.test.mjs`.

The Node tests alone do not enforce worker-runtime request options. A separate
regression uses actual workerd request construction with explicitly synthetic
HTTP fixtures and no upstream network access. It reproduces the rejected old
option and verifies that the revised relay succeeds while refusing redirects.
The tested versions are Miniflare `5.20260926.1-alpha` and its exact workerd
dependency `1.20260926.1`. This local runtime check does not replace checking the
actual deployed service when investigating an outage.

To run it from the repository root in PowerShell, install the pinned runtime
into a temporary project directory, then identify that directory explicitly:

```powershell
npm install --prefix work/relay-runtime-check --save-exact miniflare@5.20260926.1-alpha --no-audit --no-fund
$env:BINDSIGHT_MINIFLARE_DIR = (Resolve-Path work/relay-runtime-check).Path
node --test hosting/site-proxy.workerd-test.mjs
```

The runtime test requires this installation; it fails with an instruction when
the directory is unspecified rather than silently skipping the check. It does
not modify a Sites checkout, deploy a site, or change the scientific pipeline.
