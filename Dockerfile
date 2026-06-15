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
FROM python:3.11.9-slim-bookworm

# git: VCS-aware pip + the design tools' runtime clone; build-essential: wheels
# that need a compiler on slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -e ".[discover,report]"

ENTRYPOINT ["bindsight"]
CMD ["--help"]
