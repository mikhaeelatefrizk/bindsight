"""Kaggle Notebooks runner — re-exports KaggleRunner from local_docker module.

Kaggle's free tier (T4×2, 30 hr/week quota) is the same shape as Colab from
the runner's POV: write a notebook, user runs it, drop the tarball back.
v0.0.x exposes the cost estimator only; live submit lands in v0.1.0-rc2.
"""

from __future__ import annotations

from bindsight.runners.local_docker import KaggleRunner

__all__ = ["KaggleRunner"]
