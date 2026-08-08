# bindsight — CPU image for the discovery half + CLI (reproducible runs).
#
# Builds an image that runs `bindsight discover/rank/report/benchmark/run` and
# the Snakemake front-end on any machine. The GPU design half (RFdiffusion +
# ProteinMPNN + Boltz-2) needs CUDA and runs via a runner backend
# (Modal/Kaggle/local GPU) — see docs/colab-design-howto.md — so it is not baked
# into this CPU image.
#
# Build:  docker build -t bindsight:local .
# Run:    docker run --rm -v "$PWD:/work" bindsight:local discover /work/my.yaml --out /work/runs/x
#
# NOTE: this is the CLI image (it runs `bindsight` and exits). It is NOT the
# Hugging Face Space web entrypoint — the Space has its own Dockerfile that
# launches Streamlit on port 8501 and lives in the Space's own git repo
# (see .huggingface/README.md).
# Pinned by digest, not by tag: `python:3.11.9-slim-bookworm` is republished
# whenever its base is patched, so the tag alone does not identify an image and
# a rebuild in a year would not be the same environment. The tag is kept
# alongside for readability only — the digest is what Docker resolves.
FROM python:3.11.9-slim-bookworm@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317

# git: VCS-aware pip + the design tools' runtime clone; build-essential: wheels
# that need a compiler on slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
# Constraints pin the scientific stack to the versions this release was tested
# against, so the image and a local `pip install -c envs/constraints.txt` agree.
RUN pip install --no-cache-dir -c envs/constraints.txt -e ".[discover,report]"

ENTRYPOINT ["bindsight"]
CMD ["--help"]
