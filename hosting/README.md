# Hosted workspace publication

Every successful CI run for the latest `main` revision triggers the Docs workflow.
It builds the documentation and `site/workspace` from that same commit, including
original evidence and a local source download. The workflow refuses an older
revision and deploys through the protected `github-pages` environment.

The existing public Sites address uses `site-proxy.mjs` to serve this fixed origin:
https://mikhaeelatefrizk.github.io/bindsight/workspace/

The relay accepts only GET/HEAD requests for authored artifact paths. It does not
accept analysis uploads, forward visitor credentials, or execute scientific jobs.
An unavailable upstream produces an explicit 503 response. Short cache lifetimes
mean a successful GitHub publication can take a little time to become visible.

`release.json`, the evidence bundle and `SOURCE_REVISION.json` inside the download
identify the source revision. Existing local installations do not update
silently: download a new workspace to use a new release. Changes to the relay
itself require a new deployment of the existing Site; ordinary interface,
evidence and analysis-engine changes follow the GitHub publication automatically.

Run the relay's tests with `node --test hosting/site-proxy.test.mjs`.
