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
        "n_designs_above_scramble": sum(x > 0 for x in diffs),
        "exact_signflip_p": p,
        "n_permutations": n_perm,
        "design_pass_rate": _rate_at(designs, DEFAULT_IPTM_SUCCESS),
        "scramble_pass_rate": _rate_at(scrambles, DEFAULT_IPTM_SUCCESS),
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


def render(report: dict[str, Any]) -> str:
    """The report as Markdown."""
    d, s = report["designs"], report["scrambles"]
    diff = report["paired_difference"]
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
        f"Exact paired sign-flip test over all {report['n_permutations']:,} assignments: "
        f"**p = {report['exact_signflip_p']:.5f}**.",
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
