# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render the rediscovery study as Markdown a reviewer can check.

Two rules govern what this writes, and both exist because the previous results
page broke them.

**Every number carries what it was computed over.** A rank without its shortlist
size, a rate without its numerator and denominator, a p-value without its
reference set: each of those is a number a reader cannot check and cannot
disagree with. The old page reported "ERBB2 at rank 4" and "recall@5 = 33%"
without ever printing the size of the shortlist or the fact that the denominator
was three.

**Every absence says which kind of absence it is.** An antigen the surfaceome
reference does not contain, one a stated filter excluded, and one the ranker
placed low are three different findings. Reporting them as a single miss tells a
reader nothing about what to fix, so each row states its class and its
counterfactual rank.

The page is generated, never hand-edited, so it cannot drift from the artifacts.
"""

from __future__ import annotations

from typing import Any

from bindsight.benchmark import outcomes as O
from bindsight.benchmark import panel as P

__all__ = ["render_markdown"]

_CLASS_TITLE = {
    O.RANKED: "Reached the shortlist",
    O.GATED_OUT: "Measured, then excluded by a stated filter",
    O.NOT_REACHABLE: "Outside the instrument's reach",
    O.INFRASTRUCTURE: "Invalid — a lookup errored or never ran",
}

_CLASS_NOTE = {
    O.RANKED: (
        "These entered the candidate shortlist. The rank is only interpretable "
        "beside the shortlist size, so both are printed."
    ),
    O.GATED_OUT: (
        "These were measured and then excluded by a named filter. The "
        "counterfactual rank says whether the filter or the ranking was "
        "responsible: a low counterfactual rank means a gate excluded an antigen "
        "the ranking would have placed well."
    ),
    O.NOT_REACHABLE: (
        "These are absent from the surfaceome reference, so no expression level "
        "could have surfaced them. They are instrument-coverage failures, not "
        "ranking failures, and are excluded from every rate. The fix is to extend "
        "the reference."
    ),
    O.INFRASTRUCTURE: (
        "A lookup that errored or never ran is not a scientific negative. Any pair "
        "here invalidates itself and must be re-run before publication."
    ),
}


def _fmt(value: Any, places: int = 3) -> str:
    """Numbers to fixed precision, absences as an explicit dash."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if value != value:  # NaN
            return "—"
        if value != 0 and (abs(value) < 1e-3 or abs(value) >= 1e5):
            return f"{value:.2e}"
        return f"{value:.{places}f}"
    return str(value)


def _interval(block: dict[str, Any] | None) -> str:
    """A rate as point estimate, interval and the counts behind it."""
    if not block:
        return "—"
    return (
        f"{block['numerator']}/{block['denominator']} = {block['point']:.3f} "
        f"(95% CI {block['low']:.3f}–{block['high']:.3f})"
    )


def render_markdown(summary: dict[str, Any]) -> str:
    """Render the study summary produced by :func:`bindsight.benchmark.study.summarise`."""
    design = summary.get("design", {})
    lines: list[str] = [
        "# bindsight rediscovery study — results",
        "",
        "Does bindsight's expression-based discovery resurface clinically validated "
        "cell-surface antigens from real TCGA RNA-seq?",
        "",
        "## How this study is built",
        "",
        f"- **Cohorts:** {design.get('cohorts', '—')}.",
        f"- **Contrast:** `{design.get('contrast', '—')}`.",
        "- **Denominators are pre-registered**, not chosen after seeing the data.",
        "- **Every rate carries an interval.** At these panel sizes the interval, "
        "not the point estimate, is the finding.",
        "",
        "### Why cohorts are not stratified",
        "",
        str(design.get("admissible_stratifier_rule", "")),
        "",
        "### Antigens the instrument cannot reach",
        "",
        str(design.get("unreachable_note", "")),
        "",
    ]

    cascade = summary.get("recall_cascade", {})
    if cascade:
        lines += [
            "## Headline",
            "",
            "Three nested denominators. Each is a different question, and merging "
            "them would answer none of them.",
            "",
            "| Denominator | What it asks | Recall@20 |",
            "|---|---|---|",
        ]
        # `all` means every pair in the primary tier, NOT every scored pair: the
        # sensitivity table below counts 22 where this counts 17. Printing "every
        # scored pair" beside 1/17 invited the reader to conclude five pairs had
        # been dropped without explanation. The tier is now named in the label.
        tiers = summary.get("design", {}).get("tiers_in_primary_denominator") or []
        tier_label = "+".join(str(t) for t in tiers) if tiers else "primary tier"
        questions = {
            "all": f"Of every scored **{tier_label}**-tier pair, how many were surfaced?",
            "reachable": "Of those the instrument could see at all?",
            "gate_passed": "Of those that reached the shortlist? This alone measures the ranking.",
        }
        labels = {
            "all": f"all ({tier_label})",
            "reachable": "reachable",
            "gate_passed": "gate_passed",
        }
        for name in ("all", "reachable", "gate_passed"):
            block = cascade.get(name, {})
            lines.append(
                f"| `{labels[name]}` | {questions[name]} | {_interval(block.get('wilson'))} |"
            )
        lines.append("")

        # One cutoff cannot be compared across studies whose shortlists differ in
        # size. The shortlist here is roughly 285 candidates; before the surfaceome
        # pre-filter it was roughly 40, so "within the top 20" quietly became a far
        # harder question. Publishing the range and the shortlist size is what lets
        # a reader see that instead of having to infer it.
        cutoffs = sorted(
            {int(k.removeprefix("recall@")) for b in cascade.values() for k in b.get("at_k", {})}
        )
        if cutoffs:
            lines += [
                "### Recall across cutoffs",
                "",
                "An absolute cutoff is only comparable between cohorts whose "
                "shortlists are of similar size, so the median shortlist is printed "
                "beside each row.",
                "",
                "| Denominator | Median shortlist | " + " | ".join(f"@{k}" for k in cutoffs) + " |",
                "|---|--:|" + "--:|" * len(cutoffs),
            ]
            for name in ("all", "reachable", "gate_passed"):
                block = cascade.get(name, {})
                at_k = block.get("at_k", {})
                if not at_k:
                    continue
                name = labels[name]
                cells = []
                for k in cutoffs:
                    w = at_k.get(f"recall@{k}", {}).get("wilson")
                    cells.append(f"{w['numerator']}/{w['denominator']}" if w else "—")
                lines.append(
                    f"| `{name}` | {block.get('median_shortlist_size', '—')} | "
                    + " | ".join(cells)
                    + " |"
                )
            lines.append("")

    sensitivity = summary.get("tier_sensitivity")
    if sensitivity:
        lines += [
            "### Sensitivity to the regulatory tier",
            "",
            str(sensitivity.get("description", "")),
            "",
            "| Cutoff | Every scored pair |",
            "|---|--:|",
        ]
        for k, block in sensitivity.get("at_k", {}).items():
            lines.append(f"| {k} | {block['numerator']}/{block['denominator']} |")
        lines.append("")

    primary = summary.get("primary_interval")
    if primary:
        lines += [
            "### Interval over independent antigens",
            "",
            str(primary.get("description", "")),
            "",
            f"- Wilson: {_interval(primary.get('wilson'))}",
            f"- Clopper-Pearson: {_interval(primary.get('clopper_pearson'))}",
            f"- Distinct antigens: {primary.get('n_distinct_antigens')}",
            "",
        ]

    bootstrap = summary.get("cluster_bootstrap")
    if bootstrap:
        lines += [
            f"- Cluster bootstrap over antigens: {_interval(bootstrap)}",
            f"  `{bootstrap.get('method', '')}`",
            "",
        ]

    infra = summary.get("infrastructure_failures", {})
    if infra:
        lines += [
            "### Invalid pairs",
            "",
            f"**{infra.get('n', 0)}**. {infra.get('note', '')}",
            "",
        ]
        if infra.get("pairs"):
            lines += [f"Affected: {', '.join(infra['pairs'])}", ""]

    lines += _render_pairs(summary.get("pairs", []))
    lines += _render_set_sizes(summary.get("set_sizes_by_cohort", {}))
    lines += _render_excluded()

    not_run = summary.get("cohorts_not_yet_run") or []
    if not_run:
        lines += [
            "## Cohorts not yet run",
            "",
            "A cohort that has not run is not a cohort that found nothing, so these "
            "are named rather than counted as misses.",
            "",
            ", ".join(sorted(not_run)),
            "",
        ]

    lines += [
        "## Reproduce",
        "",
        "```bash",
        'pip install -e ".[discover,report]"',
        "python benchmarks/run_study.py --list",
        "python benchmarks/run_study.py --all --cpus 2",
        "```",
        "",
        "`--score-only` re-derives every number above from the run directories "
        "already on disk, without re-running any differential expression.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _render_pairs(pairs: list[dict[str, Any]]) -> list[str]:
    """One section per outcome class, so absences are never merged."""
    if not pairs:
        return []
    lines = ["## Results by outcome class", ""]
    by_class: dict[str, list[dict[str, Any]]] = {}
    for pair in pairs:
        by_class.setdefault(str(pair.get("outcome_class")), []).append(pair)

    for cls in (O.RANKED, O.GATED_OUT, O.NOT_REACHABLE, O.INFRASTRUCTURE):
        rows = by_class.get(cls, [])
        if not rows:
            continue
        lines += [
            f"### {_CLASS_TITLE[cls]} ({len(rows)})",
            "",
            _CLASS_NOTE[cls],
            "",
            "| Cohort | Antigen | Agent | Tier | log2FC | padj | Rank / shortlist | "
            "Counterfactual rank / eligible | Direction | Why |",
            "|---|---|---|---|--:|--:|--:|--:|---|---|",
        ]
        for r in sorted(rows, key=lambda x: (str(x.get("project")), str(x.get("symbol")))):
            rank = f"{r['rank']} / {r['shortlist_size']}" if r.get("rank") is not None else "—"
            cf = (
                f"{r['counterfactual_rank']} / {r['n_eligible']}"
                if r.get("counterfactual_rank") is not None
                else "—"
            )
            lines.append(
                f"| {r.get('project')} | **{r.get('symbol')}** ({r.get('uniprot')}) "
                f"| {r.get('agent')} | {r.get('tier')} | {_fmt(r.get('log2fc'), 2)} "
                f"| {_fmt(r.get('padj'))} | {rank} | {cf} | {r.get('direction', '—')} "
                f"| {r.get('reason', '')} |"
            )
        lines.append("")
    return lines


def _render_set_sizes(sizes: dict[str, dict[str, int]]) -> list[str]:
    """The sets every rank and rate above was computed over."""
    if not sizes:
        return []
    lines = [
        "## Set sizes",
        "",
        "A rank means nothing without the size of the set it was taken within, so "
        "those sizes are published rather than left to be inferred.",
        "",
        "| Cohort | Genes tested | Significant | Eligible surfaceome | Candidate shortlist |",
        "|---|--:|--:|--:|--:|",
    ]
    for project in sorted(sizes):
        s = sizes[project]
        lines.append(
            f"| {project} | {s.get('n_genes_tested', '—')} | {s.get('n_significant', '—')} "
            f"| {s.get('n_eligible_surfaceome', '—')} | {s.get('n_candidates', '—')} |"
        )
    lines.append("")
    return lines


def _render_excluded() -> list[str]:
    """Pairs published for transparency but excluded from every denominator."""
    lines = [
        "## Published but excluded from every denominator",
        "",
        "These are reported so a reader can see what was left out and why. A rate "
        "computed over them would be meaningless.",
        "",
        "| Cohort | Antigen | Reason |",
        "|---|---|---|",
    ]
    for c in P.EXCLUDED:
        reason = (
            f"only {c.n_normals} solid-tissue normals, below the floor of {P.MIN_NORMALS_FOR_POWER}"
            if c.usable == "underpowered"
            else "no solid-tissue normals, so no tumour-vs-normal contrast is possible"
        )
        lines.append(f"| {c.project} | **{c.symbol}** ({c.uniprot}) | {reason} |")
    lines.append("")
    return lines
