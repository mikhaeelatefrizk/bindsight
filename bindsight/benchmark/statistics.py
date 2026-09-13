# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Null models and interval estimates for the rediscovery study.

A rank is not evidence on its own. "ERBB2 at rank 4" means something entirely
different in a shortlist of 27 than in a shortlist of 2,000, and a recall rate
quoted without a denominator, an interval and a null is decoration rather than a
measurement. This module supplies the three things that turn a rank into a claim
a reviewer can check.

**Nulls — would a random surface protein have done this well?**

- :func:`uniform_rank_p` is the weakest and cheapest. Under the null that the
  pipeline orders the eligible surfaceome arbitrarily, an antigen's rank is
  uniform, so the one-sided p-value is its rank over the size of the set it was
  ranked within. The reference set is the *up-regulated* eligible surfaceome,
  not the whole of it: using the whole set roughly halves the p-value and is
  anticonservative. This null ignores that abundant, high-dispersion genes are
  likelier to reach significance at all, and says so.
- :func:`decoy_null_p` is the primary null and corrects exactly that. Each true
  antigen is compared against decoys matched on expression abundance and
  dispersion, pushed through the same ranking, so the question becomes "did this
  antigen beat comparable genes" rather than "did it beat all genes".
- :func:`permutation_null_p` asks the panel-level question the per-antigen nulls
  cannot: is bindsight matching antigens to the *right* indications, or merely
  surfacing generic epithelial biology that happens to include them? Permuting
  which antigen is expected in which cohort tests exactly that, and needs no
  differential expression re-run.

**Intervals.** :func:`wilson_interval` is the reported interval and
:func:`clopper_pearson_interval` the conservative cross-check; both behave
correctly at zero and at one, which a Wald interval does not, and at the panel
sizes here that matters constantly. :func:`cluster_bootstrap_interval` handles
the fact that one antigen appears in several cohorts, so pairs are not
independent trials.

Nothing here draws on the pipeline's own output to decide its reference set, and
every function takes an explicit seed so a published number is reproducible.
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "Interval",
    "MeanEstimate",
    "benjamini_hochberg",
    "clopper_pearson_interval",
    "cluster_bootstrap_interval",
    "cluster_bootstrap_mean",
    "decoy_null_p",
    "permutation_null_p",
    "uniform_rank_p",
    "wilson_interval",
]


@dataclass(frozen=True)
class Interval:
    """A point estimate with a confidence interval and the counts behind it."""

    point: float
    low: float
    high: float
    numerator: int
    denominator: int
    method: str
    confidence: float = 0.95

    def as_dict(self) -> dict[str, Any]:
        """Serialisable form, including the counts so a reader can recompute it."""
        return {
            "point": self.point,
            "low": self.low,
            "high": self.high,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "method": self.method,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class MeanEstimate:
    """A mean with a confidence interval, its spread, and the counts behind it.

    :class:`Interval` carries a numerator and a denominator because it describes
    a proportion. A mean standing has neither, and forcing one into those fields
    would put a number in front of a reader that does not mean what it says.
    """

    point: float
    low: float
    high: float
    sd: float
    n_clusters: int
    n_observations: int
    method: str
    confidence: float = 0.95

    def as_dict(self) -> dict[str, Any]:
        """Serialisable form, including the counts so a reader can recompute it."""
        return {
            "point": self.point,
            "low": self.low,
            "high": self.high,
            "sd": self.sd,
            "n_clusters": self.n_clusters,
            "n_observations": self.n_observations,
            "method": self.method,
            "confidence": self.confidence,
        }


def _z_for(confidence: float) -> float:
    """Two-sided normal quantile, without pulling in scipy for one number."""
    # Inverse of the standard normal CDF via the Beasley-Springer-Moro style
    # rational approximation used by Acklam; accurate to ~1e-9 over (0, 1),
    # which is far beyond what a confidence interval needs.
    p = 1.0 - (1.0 - confidence) / 2.0
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def wilson_interval(successes: int, trials: int, *, confidence: float = 0.95) -> Interval:
    """Wilson score interval for a proportion.

    The reported interval. Unlike a Wald interval it does not collapse to zero
    width at 0 successes or at 100%, which is the situation this panel is most
    likely to be in.

    Raises:
        ValueError: If ``trials`` is not positive or ``successes`` is out of range.
    """
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not 0 <= successes <= trials:
        raise ValueError(f"successes {successes} outside 0..{trials}")
    z = _z_for(confidence)
    n = float(trials)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return Interval(
        point=p,
        low=max(0.0, centre - half),
        high=min(1.0, centre + half),
        numerator=successes,
        denominator=trials,
        method="wilson",
        confidence=confidence,
    )


def clopper_pearson_interval(successes: int, trials: int, *, confidence: float = 0.95) -> Interval:
    """Clopper-Pearson exact interval, the conservative cross-check.

    Reported alongside Wilson so a reader can see the interval is not an artefact
    of one approximation. Wider than Wilson by construction.

    Raises:
        ValueError: If ``trials`` is not positive or ``successes`` is out of range.
    """
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not 0 <= successes <= trials:
        raise ValueError(f"successes {successes} outside 0..{trials}")
    from scipy import stats  # lazy: only the reporting path needs scipy

    alpha = 1.0 - confidence
    low = (
        0.0
        if successes == 0
        else float(stats.beta.ppf(alpha / 2, successes, trials - successes + 1))
    )
    high = (
        1.0
        if successes == trials
        else float(stats.beta.ppf(1 - alpha / 2, successes + 1, trials - successes))
    )
    return Interval(
        point=successes / trials,
        low=low,
        high=high,
        numerator=successes,
        denominator=trials,
        method="clopper-pearson",
        confidence=confidence,
    )


def cluster_bootstrap_interval(
    clusters: Mapping[str, Sequence[bool]],
    *,
    n_boot: int = 10_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> Interval:
    """Percentile bootstrap over antigens, which are the independent unit.

    One antigen can appear in several cohorts — ERBB2 in four, EGFR in four — so
    the pairs are correlated and a binomial interval over all of them would
    understate uncertainty. Resampling *antigens* with replacement, and taking
    all of a resampled antigen's cohorts with it, respects that structure.

    **Known limitation, and why the Wilson interval is still reported.** A
    percentile bootstrap cannot express uncertainty it cannot resample. If every
    outcome is a hit, every replicate is also all hits and the interval collapses
    to exactly (1.0, 1.0) — which would be a false claim of certainty. The same
    happens at zero hits. Those are precisely the cases a small panel lands in,
    so the bootstrap is a *supplement* to :func:`wilson_interval`, never a
    replacement, and ``degenerate`` marks any interval a reader must not quote
    alone.

    Args:
        clusters: antigen accession -> its per-cohort outcomes (hit or miss).
        n_boot: bootstrap replicates.
        confidence: interval width.
        seed: fixed so a published interval is reproducible.

    Raises:
        ValueError: If no clusters or no outcomes were supplied.
    """
    keys = [k for k, v in clusters.items() if len(v) > 0]
    if not keys:
        raise ValueError("no clusters with outcomes")
    flat = [bool(o) for k in keys for o in clusters[k]]
    if not flat:
        raise ValueError("no outcomes")

    rng = random.Random(seed)
    estimates: list[float] = []
    n_clusters = len(keys)
    for _ in range(n_boot):
        hits = total = 0
        for _ in range(n_clusters):
            drawn = clusters[keys[rng.randrange(n_clusters)]]
            hits += sum(1 for o in drawn if o)
            total += len(drawn)
        if total:
            estimates.append(hits / total)
    estimates.sort()
    alpha = 1.0 - confidence
    lo_i = max(0, math.floor(alpha / 2 * len(estimates)))
    hi_i = min(len(estimates) - 1, math.ceil((1 - alpha / 2) * len(estimates)) - 1)
    low, high = estimates[lo_i], estimates[hi_i]
    method = f"cluster-bootstrap(n_clusters={n_clusters}, B={n_boot})"
    if low == high:
        # No variation to resample: the data are all hits or all misses. Say so
        # in the method string rather than letting a zero-width interval be read
        # as certainty.
        method += " [degenerate: no variation to resample; quote the Wilson interval]"
    return Interval(
        point=sum(flat) / len(flat),
        low=low,
        high=high,
        numerator=sum(flat),
        denominator=len(flat),
        method=method,
        confidence=confidence,
    )


def cluster_bootstrap_mean(
    clusters: Mapping[str, Sequence[float]],
    *,
    n_boot: int = 10_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> MeanEstimate:
    """Percentile bootstrap of a mean, resampling clusters rather than values.

    The continuous counterpart of :func:`cluster_bootstrap_interval`, and it
    exists for the same reason: one antigen contributes a standing in several
    cohorts, so the values are not independent draws and an interval built from
    the values alone would be too narrow.

    Each cluster contributes the mean of its own values, so a cluster measured
    in ten cohorts does not outweigh one measured in two -- the antigen is the
    unit, not the measurement.

    Args:
        clusters: cluster key -> its values (e.g. antigen -> per-cohort standings).
        n_boot: bootstrap replicates.
        confidence: interval width.
        seed: fixed so a published interval is reproducible.

    Raises:
        ValueError: If no cluster carries a value.
    """
    keys = [k for k, v in clusters.items() if len(v) > 0]
    if not keys:
        raise ValueError("no clusters with values")

    per_cluster = [sum(clusters[k]) / len(clusters[k]) for k in keys]
    n_observations = sum(len(clusters[k]) for k in keys)
    point = sum(per_cluster) / len(per_cluster)
    sd = (
        math.sqrt(sum((v - point) ** 2 for v in per_cluster) / (len(per_cluster) - 1))
        if len(per_cluster) > 1
        else 0.0
    )

    rng = random.Random(seed)
    n_clusters = len(keys)
    estimates = []
    for _ in range(n_boot):
        drawn = [per_cluster[rng.randrange(n_clusters)] for _ in range(n_clusters)]
        estimates.append(sum(drawn) / n_clusters)
    estimates.sort()
    alpha = 1.0 - confidence
    lo_i = max(0, math.floor(alpha / 2 * len(estimates)))
    hi_i = min(len(estimates) - 1, math.ceil((1 - alpha / 2) * len(estimates)) - 1)
    method = f"cluster-bootstrap-mean(n_clusters={n_clusters}, B={n_boot})"
    if estimates[lo_i] == estimates[hi_i]:
        # One cluster, or every cluster identical: nothing to resample. Said in
        # the method string rather than left to read as certainty.
        method += " [degenerate: no variation to resample]"
    return MeanEstimate(
        point=point,
        low=estimates[lo_i],
        high=estimates[hi_i],
        sd=sd,
        n_clusters=n_clusters,
        n_observations=n_observations,
        method=method,
        confidence=confidence,
    )


def uniform_rank_p(rank: int, n_eligible: int) -> float:
    """One-sided p-value under a uniform-rank null.

    ``n_eligible`` must be the size of the set the rank was taken *within* — for
    bindsight that is the up-regulated eligible surfaceome, not the whole
    surfaceome. Passing the whole set roughly halves the p-value and is
    anticonservative, because roughly half of the significant genes are
    down-regulated and were never in contention.

    Raises:
        ValueError: On a non-positive rank or eligible count, or a rank outside
            the eligible set.
    """
    if rank < 1:
        raise ValueError(f"rank must be >= 1, got {rank}")
    if n_eligible < 1:
        raise ValueError(f"n_eligible must be >= 1, got {n_eligible}")
    if rank > n_eligible:
        raise ValueError(f"rank {rank} exceeds the eligible set size {n_eligible}")
    return rank / n_eligible


def decoy_null_p(
    antigen_rank: int,
    decoy_ranks: Sequence[int],
) -> float:
    """One-sided p-value against abundance-matched decoys — the primary null.

    Each decoy is a surface protein matched to the antigen on expression
    abundance and dispersion, pushed through the identical filter cascade and
    ranking. The p-value is the fraction of decoys that ranked at least as well,
    with the standard add-one correction so it can never be reported as exactly
    zero on a finite number of draws.

    Raises:
        ValueError: If no decoys were supplied.
    """
    if not decoy_ranks:
        raise ValueError("decoy null needs at least one decoy")
    at_least_as_good = sum(1 for r in decoy_ranks if r <= antigen_rank)
    return (1 + at_least_as_good) / (1 + len(decoy_ranks))


def match_decoys(
    candidates: Sequence[dict[str, Any]],
    target: dict[str, Any],
    *,
    n_decoys: int = 1000,
    strata: Sequence[str] = ("base_mean_decile", "dispersion_decile"),
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Draw decoys from the same abundance and dispersion strata as ``target``.

    Sampling is without replacement while the stratum can supply it, then with
    replacement, so a thin stratum degrades gracefully instead of silently
    returning too few decoys. The caller is expected to report the achieved match
    quality rather than assume it.

    Raises:
        ValueError: If the strata columns are missing from ``target``.
    """
    missing = [s for s in strata if s not in target]
    if missing:
        raise ValueError(f"target is missing strata columns: {missing}")
    key = tuple(target[s] for s in strata)
    pool = [
        c
        for c in candidates
        if all(s in c for s in strata)
        and tuple(c[s] for s in strata) == key
        and c.get("uniprot") != target.get("uniprot")
    ]
    if not pool:
        return []
    rng = random.Random(seed)
    if len(pool) >= n_decoys:
        return rng.sample(pool, n_decoys)
    return [pool[rng.randrange(len(pool))] for _ in range(n_decoys)]


def permutation_null_p(
    scores: dict[str, dict[str, float]],
    assignment: dict[str, str],
    *,
    n_perm: int = 10_000,
    seed: int = 0,
    higher_is_better: bool = True,
    exact_limit: int = 200_000,
) -> dict[str, Any]:
    """Panel-level p-value for indication specificity.

    Asks whether bindsight matches antigens to the *right* cancers, rather than
    surfacing generic epithelial biology that happens to contain them. The
    antigen-to-cohort assignment is permuted and the panel statistic recomputed.
    No differential expression is re-run, so this is cheap.

    **The null permutes the assignment; it does not resample cohorts.** This
    drew each antigen a *distinct* cohort from the whole panel, which put the
    observation outside the null's support the moment two antigens shared an
    indication — and two do. FOLH1 and STEAP1 are both single-indication and
    both TCGA-PRAD, so the observed statistic counts prostate twice while no
    draw from ``sample`` ever could. Both score near the top there, so the
    observed statistic was systematically larger than anything the null could
    produce, and the p-value was not a tail probability of it under any
    distribution the code sampled. It reached the reporting floor, which is
    exactly what that failure looks like.

    Shuffling which antigen receives which of the *observed* cohorts fixes the
    support — the observation is the identity permutation, so it is always in
    the null — and controls for cohort difficulty as a side effect: every
    permutation uses the same cohorts the observation did, so a cohort whose
    standings run high cannot inflate one arm and not the other.

    Enumerated exactly when the antigen count allows, because a p-value that
    could be exact should not carry Monte Carlo error or a sampling floor.

    Args:
        scores: antigen -> {cohort -> score}. Must be complete: a missing score
            is an antigen that was never evaluated in that cohort, which would
            bias the permutation.
        assignment: antigen -> its own indication. The observed statistic is
            computed from this rather than passed in, so the observation and
            the null cannot be built from different rules.
        n_perm: permutations to sample when exact enumeration is too large.
        seed: fixed for reproducibility.
        higher_is_better: whether a larger statistic is a better result.
        exact_limit: enumerate when ``n!`` is at most this.

    Returns:
        ``observed``, ``p_value``, ``p_value_floor``, ``n_permutations`` and
        ``exact``.

    Raises:
        ValueError: If fewer than two antigens are supplied, the score matrix is
            ragged, or an assignment names a cohort or antigen not in ``scores``.
    """
    antigens = sorted(scores)
    if len(antigens) < 2:
        raise ValueError("permutation null needs at least two antigens")
    cohorts = sorted({c for row in scores.values() for c in row})
    ragged = [a for a in antigens if set(scores[a]) != set(cohorts)]
    if ragged:
        raise ValueError(
            "score matrix is ragged; every antigen must be scored in every cohort. "
            f"incomplete: {ragged[:5]}"
        )
    if set(assignment) != set(antigens):
        raise ValueError(
            "every antigen must have exactly one assigned cohort; "
            f"mismatch: {sorted(set(antigens) ^ set(assignment))[:5]}"
        )
    unknown = sorted({c for c in assignment.values() if c not in set(cohorts)})
    if unknown:
        raise ValueError(f"assigned cohorts absent from the score matrix: {unknown}")

    # The multiset the observation actually used. Repeats are kept: two antigens
    # sharing an indication is a property of the panel, not an error, and
    # removing it is what put the observation outside the null before.
    assigned = [assignment[a] for a in antigens]
    n = len(antigens)
    observed = sum(scores[a][c] for a, c in zip(antigens, assigned, strict=True)) / n

    def _stat(order: Sequence[int]) -> float:
        return sum(scores[antigens[i]][assigned[j]] for j, i in enumerate(order)) / n

    def _as_extreme(stat: float) -> bool:
        # Tolerance, not equality: permutations that only swap two antigens
        # sharing a cohort reproduce the observed statistic through a different
        # summation order, and floating point does not guarantee the same bits.
        return (stat >= observed - 1e-12) if higher_is_better else (stat <= observed + 1e-12)

    total = math.factorial(n)
    if total <= exact_limit:
        extreme = sum(1 for order in itertools.permutations(range(n)) if _as_extreme(_stat(order)))
        # Exact: the identity permutation is always counted, so this can never
        # be zero and needs no add-one correction.
        return {
            "observed": observed,
            "p_value": extreme / total,
            "p_value_floor": 1.0 / total,
            "n_permutations": total,
            "exact": True,
        }

    rng = random.Random(seed)
    order = list(range(n))
    extreme = 0
    for _ in range(n_perm):
        rng.shuffle(order)
        if _as_extreme(_stat(order)):
            extreme += 1
    return {
        "observed": observed,
        "p_value": (1 + extreme) / (1 + n_perm),
        "p_value_floor": 1.0 / (1 + n_perm),
        "n_permutations": n_perm,
        "exact": False,
    }


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values, order preserved.

    Reported alongside raw p-values because the panel tests roughly twenty
    hypotheses at once, and a single nominally significant result among twenty is
    not news.

    Raises:
        ValueError: If any p-value is outside [0, 1].
    """
    if any(not 0.0 <= p <= 1.0 for p in p_values):
        raise ValueError("p-values must lie in [0, 1]")
    n = len(p_values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: p_values[i])
    adjusted = [0.0] * n
    running = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        i = n - rank + 1
        running = min(running, p_values[idx] * n / i)
        # Never below the raw value. Every term in the running minimum is
        # p_(j) * n / j with j >= i, and n / j >= 1, so the exact adjusted
        # p-value is always at least p_(i); this is arithmetic, not a fudge
        # factor. In floating point the largest p-value's own term, p * n / n,
        # can land one unit in the last place below p — observed here as an
        # adjusted 0.8170212765957445 against a raw 0.8170212765957446 — and a
        # corrected p-value printed below the one it corrects is wrong however
        # small the margin.
        adjusted[idx] = max(running, p_values[idx])
    return adjusted
