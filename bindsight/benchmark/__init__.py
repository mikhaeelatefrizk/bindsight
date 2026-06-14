"""Rediscovery benchmarking against the held-out known-antigen set.

Scores one or more finished ``bindsight`` run directories by how well they
resurface the literature-validated known antigens in ``benchmarks/known.tsv``
(rank of each known antigen, recall@k, enrichment), and renders a side-by-side
HTML report. This is the implementation behind the ``bindsight benchmark``
command referenced in ``docs/use-cases.md``.
"""

from __future__ import annotations

from bindsight.benchmark.core import (
    KnownAntigen,
    RunScore,
    load_known_antigens,
    render_benchmark_html,
    run_benchmark,
    score_run,
)

__all__ = [
    "KnownAntigen",
    "RunScore",
    "load_known_antigens",
    "render_benchmark_html",
    "run_benchmark",
    "score_run",
]
