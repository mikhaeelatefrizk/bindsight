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
# NOTE: this is the CLI image -- it runs `bindsight` and exits. The web
# interface is served by `bindsight ui` out of this same package, so there is
# no second image to keep in step with it. There was one once, for a hosted
# deployment that is now retired; it drifted because it was maintained
# somewhere this repository could not see.
#
# Pinned by digest, not by tag: `python:3.11.18-slim-bookworm` is republished
# whenever its base is patched, so the tag alone does not identify an image and
# a rebuild in a year would not be the same environment. The tag is kept
# alongside for readability only — the digest is what Docker resolves.
FROM python:3.11.18-slim-bookworm@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd

# ghcr.io reads this label to connect the image's package to the repository
# that built it. The package predates the current repository object (the
# repository was recreated on 2026-09-14) and nothing else re-links them.
LABEL org.opencontainers.image.source="https://github.com/mikhaeelatefrizk/bindsight"

# git: VCS-aware pip + the design tools' runtime clone; build-essential: wheels
# that need a compiler on slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
# Constraints pin the scientific stack to the versions this release was tested
# against, so the image and a local `pip install -c envs/constraints.txt` agree.
# `workflow` is here because this image's own header promises the Snakemake
# front-end runs in it; without the extra, snakemake is simply absent.
RUN pip install --no-cache-dir -c envs/constraints.txt -e ".[discover,report,workflow]"

ENTRYPOINT ["bindsight"]
CMD ["--help"]
