# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Figures for the rediscovery study, generated from the committed artifacts.

Two figures, each answering a question a table answers badly.

:func:`plot_surfaced_ranks` shows where each surfaced antigen landed *relative to
the list it was ranked within*. An absolute rank of 34 means something very
different in a shortlist of 40 than in one of 285, and a bar chart of raw ranks
would hide exactly that. The bars are drawn against the shortlist, so the reader
sees the proportion rather than being asked to divide.

:func:`plot_outcome_classes` shows the four outcomes side by side. The single
most misleading thing the previous results page did was collapse them into one
recall number, and a stacked bar makes the collapse visibly wrong.

Nothing here recomputes anything. Both read the same ``results.json`` the tables
read, so a figure can never disagree with the text beside it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["plot_outcome_classes", "plot_surfaced_ranks", "render_figures"]

#: Colour-blind-safe, and consistent between the two figures.
_COLOURS = {
    "ranked": "#0072B2",
    "gated_out": "#E69F00",
    "not_reachable": "#CC79A7",
    "infrastructure": "#999999",
}

_CLASS_LABEL = {
    "ranked": "Reached the shortlist",
    "gated_out": "Excluded by a filter",
    "not_reachable": "Outside the instrument",
    "infrastructure": "Invalid, must re-run",
}


def plot_surfaced_ranks(summary: dict[str, Any], out_path: Path) -> Path | None:
    """Rank of each surfaced antigen against the shortlist it was drawn from.

    Returns the written path, or ``None`` if nothing was surfaced.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    surfaced = sorted(
        (p for p in summary.get("pairs", []) if isinstance(p.get("rank"), int)),
        key=lambda p: p["rank"],
        reverse=True,
    )
    if not surfaced:
        return None

    labels = [f"{p['symbol']}\n{str(p['project']).removeprefix('TCGA-')}" for p in surfaced]
    ranks = [p["rank"] for p in surfaced]
    shortlists = [p.get("shortlist_size") or 0 for p in surfaced]

    fig, ax = plt.subplots(figsize=(8, 0.75 * len(surfaced) + 2))
    y = range(len(surfaced))
    # The full shortlist as a pale bar, the antigen's rank as the filled part:
    # position is read against the list, never in isolation.
    ax.barh(list(y), shortlists, color="#E8E8E8", label="shortlist size")
    ax.barh(list(y), ranks, color=_COLOURS["ranked"], label="rank of the antigen")
    for i, (rank, size) in enumerate(zip(ranks, shortlists, strict=True)):
        ax.text(size + max(shortlists) * 0.01, i, f"{rank} of {size}", va="center", fontsize=9)

    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Position in the candidate shortlist (lower is better)")
    # Scope named, as the outcome figure's is. These two sit side by side and
    # count different panels: this one plots every surfaced antigen, that one
    # counts the pre-registered denominator only.
    ax.set_title(
        "Where each surfaced antigen ranked, against the list it was ranked within\n"
        "(every scored pair; the outcome figure counts the pre-registered denominator)",
        fontsize=11,
    )
    ax.set_xlim(0, max(shortlists) * 1.18)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def plot_outcome_classes(summary: dict[str, Any], out_path: Path) -> Path | None:
    """The four outcomes as separate bars, because merging them hides the cause.

    Returns the written path, or ``None`` if there is nothing to plot.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    counts = summary.get("outcome_class_counts") or {}
    if not counts or not sum(counts.values()):
        return None

    order = ["ranked", "gated_out", "not_reachable", "infrastructure"]
    values = [counts.get(k, 0) for k in order]
    labels = [_CLASS_LABEL[k] for k in order]
    colours = [_COLOURS[k] for k in order]

    fig, ax = plt.subplots(figsize=(8, 3.4))
    bars = ax.bar(labels, values, color=colours)
    for bar, value in zip(bars, values, strict=True):
        if value:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value,
                str(value),
                ha="center",
                va="bottom",
                fontsize=10,
            )
    ax.set_ylabel("Antigen-cohort pairs")
    # The bars count the pre-registered denominator, which is fewer pairs than
    # the study scored. An untitled denominator reads as a total of the panel.
    tiers = (summary.get("design") or {}).get("tiers_in_primary_denominator") or []
    scope = (
        " ".join(str(t).replace("_", " ") for t in tiers) + "-tier pairs"
        if tiers
        else "every scored pair"
    )
    ax.set_title(f"Four outcomes ({scope}), reported separately rather than as one rate")
    ax.set_ylim(0, max(values) * 1.2 if max(values) else 1)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", labelsize=9)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def render_figures(summary: dict[str, Any], fig_dir: Path) -> dict[str, Path]:
    """Write every study figure into ``fig_dir``; return what was produced.

    A figure that could not be drawn is simply absent from the result rather than
    written empty, so a page never links a picture with nothing in it.
    """
    produced: dict[str, Path] = {}
    for name, fn in (
        ("surfaced_ranks", plot_surfaced_ranks),
        ("outcome_classes", plot_outcome_classes),
    ):
        path = fn(summary, fig_dir / f"{name}.png")
        if path is not None:
            produced[name] = path
    return produced
