# The Hugging Face Space's Dockerfile, version-controlled here.
#
# It used to exist only in the Space repository, hand-maintained and invisible
# to review, which is how the Space came to silently ignore a .streamlit/
# config for its whole life: that file sat at this repository's root, the Space
# never received it, and the theme and telemetry settings it declared therefore
# applied to local runs only while the file's own comment named the Space.
#
# `.github/workflows/sync-hf-space.yml` uploads this file to the Space on every
# release, so the build and the repository can no longer drift.

# Digest-pinned, like the root Dockerfile. A floating tag means the public
# demo can be rebuilt onto a different base than the one it was tested on,
# and nothing records which base produced a given deployment.
FROM python:3.13.5-slim@sha256:4c2cf9917bd1cbacc5e9b07320025bdb7cdf2df7b0ceaccb55e9dd7e30987419

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# bindsight itself arrives through requirements.txt, version-controlled here as
# `.huggingface/requirements.txt` and uploaded with this file. It installs the
# package from git at `main`; nothing is copied from a source tree, so a
# rebuild serves the released code rather than whatever the Space last held.
COPY requirements.txt ./
# bindsight's _find_repo_root() walks up from the installed package looking
# for examples/demo/config.yaml; on this Space the package is in
# site-packages so the walk fails and the function falls back to Path.cwd()
# == /app.  Copy the shipped demo cohort to /app/examples/ so the fallback
# finds the data.
COPY examples/ ./examples/
# The Real results page reads committed artifacts through
# bindsight.report.showcase.benchmarks_root(), which walks up for a benchmarks/
# directory. Without this COPY it returns None and the page renders nothing,
# while the README promises 20 binders rendered in 3-D. 6.8 MB, and it is the
# difference between a demo that shows the evidence and one that claims to.
COPY benchmarks/ ./benchmarks/

# The interface is server-rendered now: its stylesheet, templates and vendored
# assets travel inside the package, so there is no separate config to copy and
# no theme that applies only to a clone. The previous arrangement read its
# config from $CWD, which meant a pip-installed user running the app from their
# home directory silently got default styling and half the documented upload
# limit.

RUN pip3 install -r requirements.txt

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/ || exit 1

ENTRYPOINT ["python", "-c", "import uvicorn; from bindsight.report.web.app import create_app; uvicorn.run(create_app(), host='0.0.0.0', port=8501, log_level='warning')"]
