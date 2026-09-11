# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the paired calibration run and say what ipTM 0.65 is worth.

``DEFAULT_IPTM_SUCCESS = 0.65`` carries the project's headline number —
"40% success@0.65" — and arrived as a bare constant with no citation. This turns
it into a measured quantity by giving it something to be measured against.

**The comparison.** Each of the twenty committed ERBB2 designs was folded in the
same job as a shuffle of its own sequence. A shuffle preserves length and
amino-acid composition exactly and destroys only the residue order, which is the
entire content of the design. Both arms went through the same validator, against
the same target, on the same card, in the same session, so the only difference
between a pair is the order of its residues.

**What comes out.** For a threshold to mean anything it needs a false-positive
rate: the fraction of scrambles that clear it. A design scoring 0.7 is only
evidence if scrambles of the same composition do not also score 0.7.

**The test.** Paired, and exact. With twenty pairs the sign-flip null has
2^20 = 1,048,576 members, so it is enumerated rather than sampled — no Monte
Carlo error on a number this small, and nothing to justify about a draw count.
The pairing is what makes it powerful: composition, length and target are held
fixed within a pair, so the difference isolates order.

**What this does not measure.** Run-to-run and version-to-version drift, if a
committed metrics file is supplied for comparison, is reported separately and
labelled as such — the committed designs were folded by an earlier run under an
unrecorded Boltz-2 (see ``PRECISION.md``), so that comparison confounds the two
and is a bound, not a determinism figure.

Usage::

    python benchmarks/calibration/analyse.py --metrics runs/_design/<key>/metrics.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

#: The constant under examination.
from bindsight.benchmark.designer_bench import DEFAULT_IPTM_SUCCESS  # noqa: E402

COMMITTED = REPO / "benchmarks" / "designer_benchmark" / "binders" / "metrics.jsonl"

#: Suffix :mod:`stage_scrambles` gives a shuffled sequence.
SCRAMBLE_SUFFIX = "_scram"

#: Chunk size for enumerating the sign-flip null. 2^20 sign patterns times 20
#: differences is 160 MB as one array; in chunks it is a few megabytes, which
#: keeps an exact test from being the reason a laptop swaps.
_CHUNK = 1 << 16


def _load(path: Path) -> dict[str, float]:
    """``binder_id -> iptm`` for every row that has one."""
    rows: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        iptm = row.get("iptm")
        if iptm is not None:
            rows[row["binder_id"]] = float(iptm)
    return rows


def exact_signflip_p(diffs: list[float]) -> tuple[float, int]:
    """Two-sided exact paired permutation p-value over all 2^n sign flips.

    Under the null that order carries nothing, a design and its scramble are
    exchangeable, so each pair's difference is equally likely to take either
    sign. Enumerating every assignment gives the exact null distribution of the
    mean difference.

    Args:
        diffs: one difference per pair.

    Returns:
        ``(p, n_permutations)``.

    Raises:
        ValueError: If there are no pairs, or too many to enumerate.
    """
    n = len(diffs)
    if n == 0:
        raise ValueError("no pairs to test")
    if n > 22:
        raise ValueError(f"{n} pairs is {2**n} sign patterns; sample instead of enumerating")

    d = np.asarray(diffs, dtype=np.float64)
    observed = abs(float(d.sum()))
    total = 1 << n
    bits = np.arange(n, dtype=np.uint32)
    extreme = 0
    for start in range(0, total, _CHUNK):
        idx = np.arange(start, min(start + _CHUNK, total), dtype=np.uint32)
        # +1/-1 per pair, one row per sign pattern.
        signs = 1.0 - 2.0 * ((idx[:, None] >> bits) & 1).astype(np.float64)
        extreme += int(np.count_nonzero(np.abs(signs @ d) >= observed - 1e-12))
    return extreme / total, total


#: Resamples for the paired bootstrap interval, and the seed that fixes it.
_BOOTSTRAP = 20_000
_BOOTSTRAP_SEED = 20260912


def paired_interval(diffs: list[float], *, confidence: float = 0.95) -> dict[str, float]:
    """Percentile bootstrap interval for the mean paired difference.

    A p-value says whether an effect was detected. It does not say what effects
    the run could have detected, and a null result reported without that is
    unreadable: "no difference found" and "no difference larger than X" are
    different claims, and only the second is what twenty pairs can support.

    Bootstrapped over pairs rather than assuming normal differences — the
    differences here are not obviously normal, and the resample costs
    milliseconds.

    Args:
        diffs: one difference per pair.
        confidence: interval confidence level.

    Returns:
        The mean difference, its interval, and the smallest difference this many
        pairs would detect at 80% power. A single pair has no spread to
        resample, so its record says ``estimable: False`` and carries no bounds
        — the same shape :func:`operating_point` uses for a target it cannot
        reach, and for the same reason: a missing number must not be reported
        as a number.

    Raises:
        ValueError: If there are no pairs at all.
    """
    n = len(diffs)
    if n == 0:
        raise ValueError("no pairs to summarise")
    if n < 2:
        return {"estimable": False, "mean": float(diffs[0]), "n_pairs": n}

    d = np.asarray(diffs, dtype=np.float64)
    rng = np.random.default_rng(_BOOTSTRAP_SEED)
    means = d[rng.integers(0, n, size=(_BOOTSTRAP, n))].mean(axis=1)
    alpha = 1.0 - confidence
    low, high = (float(x) for x in np.quantile(means, [alpha / 2, 1 - alpha / 2]))

    # Smallest true difference this design detects 80% of the time at a
    # two-sided 5% level, from the observed spread of the differences.
    sd = float(d.std(ddof=1))
    mde = (1.959963985 + 0.841621234) * sd / math.sqrt(n)
    return {
        "estimable": True,
        "mean": float(d.mean()),
        "low": low,
        "high": high,
        "sd": sd,
        "n_pairs": n,
        "min_detectable_difference_80pct": mde,
        "n_resamples": _BOOTSTRAP,
    }


def _describe(values: list[float]) -> dict[str, float]:
    """Summary statistics, or NaNs when there is nothing to summarise."""
    if not values:
        return dict.fromkeys(("n", "mean", "median", "sd", "min", "max"), math.nan)
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "sd": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def _rate_at(values: list[float], threshold: float) -> float:
    """Fraction of ``values`` at or above ``threshold``."""
    if not values:
        return math.nan
    return sum(v >= threshold for v in values) / len(values)


def _fpr(scrambles: list[float], threshold: float) -> dict[str, Any]:
    """False-positive rate at ``threshold``, with an exact interval.

    Twenty scrambles resolve a rate to steps of 5%, so the point estimate is
    the least interesting number here: zero of twenty is not a 0% false-positive
    rate, it is a rate whose 95% upper bound is 16.8%. Reporting the point
    alone would read as a much stronger claim than twenty draws can support.

    Clopper-Pearson comes from :mod:`bindsight.benchmark.statistics` rather than
    being written again here — it is the interval the rest of the project
    reports, and a second implementation is a second thing to get wrong.
    """
    from bindsight.benchmark.statistics import clopper_pearson_interval

    passing = sum(v >= threshold for v in scrambles)
    interval = clopper_pearson_interval(passing, len(scrambles))
    return {
        "threshold": threshold,
        "n_passing": passing,
        "n": len(scrambles),
        "point": interval.point,
        "upper95": interval.high,
    }


def operating_point(
    designs: list[float],
    scrambles: list[float],
    *,
    max_fpr: float,
    grid: tuple[float, ...] = tuple(i / 100 for i in range(101)),
) -> dict[str, Any]:
    """Lowest threshold whose scramble false-positive rate is at most ``max_fpr``.

    Lowest, not highest: raising a threshold past the point where it does its job
    only discards real designs. The bound used is the interval's **upper** limit,
    not the point estimate, so a threshold is not accepted on the strength of a
    rate twenty draws cannot actually establish.

    Args:
        designs: design scores.
        scrambles: scores of the composition-matched controls.
        max_fpr: the largest acceptable upper bound on the false-positive rate.
        grid: candidate thresholds, ascending.

    Returns:
        A record that always names ``max_fpr`` and whether it was
        ``reachable``. When it was not, the record carries how many controls
        *would* reach it instead of a threshold — an unreachable bound is a
        statement about the size of the control set, not about the designs, and
        reporting it as a missing threshold would blame the wrong thing.
    """
    for threshold in sorted(grid):
        fpr = _fpr(scrambles, threshold)
        if fpr["upper95"] <= max_fpr:
            return {
                "max_fpr": max_fpr,
                "reachable": True,
                "threshold": threshold,
                "false_positive_rate": fpr,
                "design_pass_rate": _rate_at(designs, threshold),
            }
    return {
        "max_fpr": max_fpr,
        "reachable": False,
        "n_controls": len(scrambles),
        "best_attainable_upper95": _fpr(scrambles, max(grid))["upper95"],
        "n_controls_needed": controls_needed_for(max_fpr),
    }


def controls_needed_for(max_fpr: float, *, confidence: float = 0.95) -> int:
    """How many controls a false-positive bound of ``max_fpr`` requires.

    Even a control set where *nothing* passes cannot prove an arbitrarily small
    rate: with none of ``n`` passing, the Clopper-Pearson upper limit is
    ``1 - (alpha/2)**(1/n)``, which is about 17% at twenty and does not reach 5%
    until seventy-two. So a threshold cannot be certified below that no matter
    how cleanly the arms separate, and the ceiling is a property of the
    experiment's size rather than of its result.

    This is the honest answer to "why is there no 5% operating point": not
    because the designs failed, but because twenty controls cannot establish one.

    This assumes the controls are independent, which shuffles of the *same*
    design are not: four shuffles of one sequence share its length and exact
    composition, so a set built that way is clusters-of-shuffles rather than
    independent draws. Against such a set this is a **lower** bound on the count
    required, and the interval itself has to come from
    :func:`~bindsight.benchmark.statistics.cluster_bootstrap_interval` instead.
    See this directory's README.

    Args:
        max_fpr: the desired upper bound on the false-positive rate.
        confidence: the interval's confidence level.

    Returns:
        The smallest ``n`` whose zero-passing upper limit is at or below
        ``max_fpr``, assuming independence.

    Raises:
        ValueError: If ``max_fpr`` is not strictly between 0 and 1.
    """
    if not 0.0 < max_fpr < 1.0:
        raise ValueError(f"max_fpr must be in (0, 1); got {max_fpr}")
    alpha = 1.0 - confidence
    # 1 - (alpha/2)**(1/n) <= max_fpr, solved for n and rounded up.
    return math.ceil(math.log(alpha / 2) / math.log(1.0 - max_fpr))


def analyse(metrics: Path, committed: Path | None = None) -> dict[str, Any]:
    """Compare each design against its own scramble. Returns the report as a dict."""
    scored = _load(metrics)
    pairs: list[tuple[str, float, float]] = []
    for binder_id, iptm in sorted(scored.items()):
        if binder_id.endswith(SCRAMBLE_SUFFIX):
            continue
        scramble = scored.get(binder_id + SCRAMBLE_SUFFIX)
        if scramble is not None:
            pairs.append((binder_id, iptm, scramble))

    if not pairs:
        raise ValueError(
            f"{metrics} holds no design/scramble pairs; the two arms must be "
            "folded in one job for the comparison to mean anything"
        )

    designs = [d for _, d, _ in pairs]
    scrambles = [s for _, _, s in pairs]
    diffs = [d - s for _, d, s in pairs]
    p, n_perm = exact_signflip_p(diffs)

    report: dict[str, Any] = {
        "n_pairs": len(pairs),
        "threshold": DEFAULT_IPTM_SUCCESS,
        "designs": _describe(designs),
        "scrambles": _describe(scrambles),
        "paired_difference": _describe(diffs),
        "paired_interval": paired_interval(diffs),
        "n_designs_above_scramble": sum(x > 0 for x in diffs),
        "exact_signflip_p": p,
        "n_permutations": n_perm,
        # The smallest p this many pairs can produce: only the observed sign
        # assignment and its mirror are as extreme as a perfect separation. A
        # p at the floor means "as low as twenty pairs can go", not "vanishing",
        # and the study's decoy null reports its own floor for the same reason.
        "exact_signflip_p_floor": 2 / n_perm,
        "design_pass_rate": _rate_at(designs, DEFAULT_IPTM_SUCCESS),
        "scramble_pass_rate": _rate_at(scrambles, DEFAULT_IPTM_SUCCESS),
        "false_positive_rate_at_threshold": _fpr(scrambles, DEFAULT_IPTM_SUCCESS),
        # Two bounds rather than one: 0.25 is a threshold that mostly works,
        # 0.05 is one that can carry a published success rate. Reporting both
        # shows what the shipped 0.65 buys and what it would cost to do better.
        "operating_points": [
            operating_point(designs, scrambles, max_fpr=0.25),
            operating_point(designs, scrambles, max_fpr=0.05),
        ],
        "sweep": [
            {
                "threshold": t,
                "designs": _rate_at(designs, t),
                "scrambles": _rate_at(scrambles, t),
            }
            for t in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85)
        ],
        "pairs": [
            {"binder_id": b, "design": d, "scramble": s, "difference": d - s} for b, d, s in pairs
        ],
    }

    if committed is not None and committed.is_file():
        # Not a determinism figure: these were folded in an earlier run under a
        # Boltz-2 whose version was never recorded, so this bounds run drift and
        # version drift together. Reported because a bound is worth having and
        # because pretending it is one thing would be worse than saying it is two.
        before = _load(committed)
        drift = [
            {"binder_id": b, "committed": before[b], "refolded": d, "delta": d - before[b]}
            for b, d, _ in pairs
            if b in before
        ]
        if drift:
            report["refold_drift"] = {
                "n": len(drift),
                "note": "run-to-run and version-to-version drift together, not determinism",
                "abs_delta": _describe([abs(x["delta"]) for x in drift]),
                "per_binder": drift,
            }
    return report


def _fmt_p(p: float) -> str:
    """A p-value that stays readable when it is very small.

    ``{:.5f}`` renders the twenty-pair floor of 1.9e-06 as ``0.00000``, which
    reads as zero. No p from an exact test is zero.
    """
    return f"{p:.2e}" if 0 < p < 1e-4 else f"{p:.5f}"


def render(report: dict[str, Any]) -> str:
    """The report as Markdown."""
    d, s = report["designs"], report["scrambles"]
    diff = report["paired_difference"]
    ci = report["paired_interval"]
    t = report["threshold"]
    lines = [
        "# What ipTM 0.65 is worth",
        "",
        f"{report['n_pairs']} committed ERBB2 designs, each folded in the same job as a "
        "shuffle of its own sequence: same length, same amino-acid composition, same "
        "target, same validator, same card, same session. Only the residue order differs.",
        "",
        "| | n | mean | median | sd | min | max |",
        "|---|---|---|---|---|---|---|",
        f"| designs | {d['n']:.0f} | {d['mean']:.3f} | {d['median']:.3f} | {d['sd']:.3f} "
        f"| {d['min']:.3f} | {d['max']:.3f} |",
        f"| scrambles | {s['n']:.0f} | {s['mean']:.3f} | {s['median']:.3f} | {s['sd']:.3f} "
        f"| {s['min']:.3f} | {s['max']:.3f} |",
        "",
        f"Paired difference (design − scramble): median {diff['median']:+.3f}, "
        f"mean {diff['mean']:+.3f}. "
        f"{report['n_designs_above_scramble']} of {report['n_pairs']} designs beat their "
        "own scramble.",
        "",
        (
            f"95% bootstrap interval on the mean difference: "
            f"**[{ci['low']:+.3f}, {ci['high']:+.3f}]**. With {ci['n_pairs']} pairs and a "
            f"spread of {ci['sd']:.3f} between them, the smallest difference this run "
            f"would catch 80% of the time is "
            f"**{ci['min_detectable_difference_80pct']:.3f}** — so it bounds any real "
            "advantage rather than showing there is none."
            if ci["estimable"]
            else f"{ci['n_pairs']} pair gives no spread to interval, so this run bounds nothing."
        ),
        "",
        f"Exact paired sign-flip test over all {report['n_permutations']:,} assignments: "
        f"**p = {_fmt_p(report['exact_signflip_p'])}**"
        + (
            f" — the floor for {report['n_pairs']} pairs, "
            f"so this is as low as this many pairs can go."
            if report["exact_signflip_p"] <= report["exact_signflip_p_floor"]
            else f" (floor for {report['n_pairs']} pairs: "
            f"{_fmt_p(report['exact_signflip_p_floor'])})."
        ),
        "",
        f"## At the threshold the project ships ({t})",
        "",
        f"- designs clearing {t}: **{report['design_pass_rate']:.0%}**",
        f"- scrambles clearing {t}: **{report['scramble_pass_rate']:.0%}** "
        "— the false-positive rate this threshold carries",
        "",
        "| threshold | designs | scrambles |",
        "|---|---|---|",
    ]
    lines += [
        f"| {r['threshold']:.2f} | {r['designs']:.0%} | {r['scrambles']:.0%} |"
        for r in report["sweep"]
    ]

    fpr = report["false_positive_rate_at_threshold"]
    lines += [
        "",
        f"{fpr['n_passing']} of {fpr['n']} scrambles clear {t}. With {fpr['n']} controls "
        f"that is an exact 95% upper bound of **{fpr['upper95']:.1%}** — not "
        f"{fpr['point']:.0%}, which is what the count alone would suggest.",
        "",
        "## Operating point",
        "",
        "The lowest threshold whose false-positive **upper bound** clears each "
        "target. Judged on the bound rather than the count, so a threshold is "
        "never accepted on the strength of a rate this many controls cannot "
        "establish.",
        "",
    ]
    for op in report["operating_points"]:
        if op["reachable"]:
            keeps = op["design_pass_rate"]
            line = (
                f"- **≤{op['max_fpr']:.0%} false positives → threshold "
                f"{op['threshold']:.2f}**, keeping {keeps:.0%} of designs "
                f"(bound {op['false_positive_rate']['upper95']:.1%})."
            )
            if keeps == 0.0:
                line += (
                    " That threshold keeps nothing: the only way to exclude the "
                    "controls is to exclude the designs with them, which means "
                    "the metric is not separating them."
                )
            lines.append(line)
        else:
            lines.append(
                f"- **≤{op['max_fpr']:.0%} false positives: not established by this run.** "
                f"{op['n_controls']} controls cannot certify a rate below "
                f"{op['best_attainable_upper95']:.1%} however cleanly the arms separate; "
                f"{op['n_controls_needed']} would be needed. This is a limit of the "
                "control set's size, not a statement about the designs."
            )

    if "refold_drift" in report:
        drift = report["refold_drift"]
        a = drift["abs_delta"]
        lines += [
            "",
            "## Refold drift",
            "",
            f"The same {drift['n']} sequences also carry committed ipTM values from an "
            "earlier job. Refolding them here gives a bound on how far a number moves "
            "between runs — but the earlier job's Boltz-2 version was never recorded "
            "(see `PRECISION.md`), so this is run drift and version drift together, "
            "not a determinism measurement.",
            "",
            f"Absolute change: median {a['median']:.3f}, max {a['max']:.3f}.",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the calibration report. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--committed", type=Path, default=COMMITTED)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent)
    args = parser.parse_args(argv)

    if not args.metrics.is_file():
        print(f"no metrics at {args.metrics}", file=sys.stderr)
        return 1

    report = analyse(args.metrics, args.committed)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "RESULTS.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.out / "CALIBRATION.md").write_text(render(report), encoding="utf-8")
    print(render(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
