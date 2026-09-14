# The Hugging Face Space's Dockerfile, version-controlled here.
#
# It used to exist only in the Space repository, hand-maintained and invisible
# to review, which is how the Space came to silently ignore .streamlit/config.toml
# for its whole life: the file sits at this repository's root, the Space never
# received it, and the theme and telemetry settings it declares therefore
# applied to local runs only while the file's own comment named the Space.
#
# `.github/workflows/sync-hf-space.yml` uploads this file and that config to the
# Space on every release, so the two can no longer drift.

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

COPY requirements.txt ./
COPY src/ ./src/
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

# Streamlit reads its config from $CWD/.streamlit/config.toml, and WORKDIR is
# /app, so this is what makes the navy theme and gatherUsageStats=false apply
# to the hosted demo rather than only to local clones.
COPY .streamlit/ ./.streamlit/

RUN pip3 install -r requirements.txt

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

ENTRYPOINT ["streamlit", "run", "src/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
