# Getting help

## Start here

Most questions are answered by something already in the repository:

| Question | Where |
|---|---|
| How do I install and run it? | [README — Install](README.md#install) |
| What does this number mean? | [docs/glossary.md](docs/glossary.md) |
| What has bindsight actually shown? | [README — What the evidence says](README.md#what-the-evidence-says) |
| How do I reproduce a published figure? | [README — Reproducing the results](README.md#reproducing-the-results) |
| Will it work on my data? | [README — Scope](README.md#scope--what-it-accepts) |
| How does it work internally? | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Something is broken in my environment | Run `bindsight doctor` first — it reports dependencies, caches and vendored data |

## If that did not answer it

- **A question** — open a [discussion](https://github.com/mikhaeelatefrizk/bindsight/discussions).
- **A bug** — open an [issue](https://github.com/mikhaeelatefrizk/bindsight/issues/new/choose).
- **A published number that does not reproduce** — please open an issue using the
  reproducibility template. That is a serious bug in a project whose argument is
  that its claims are checkable, and it is worth reporting even if you suspect
  you made a mistake: an instruction that is easy to follow incorrectly is also
  a defect.
- **A security vulnerability** — see [SECURITY.md](SECURITY.md). Please report
  privately.

## What to expect

bindsight is maintained by one person alongside other work. Issues are read;
replies may take some days. Reports that include the exact command, the full
error and whether it happens on a clean clone get resolved fastest, because that
is usually enough to reproduce without a round trip.
