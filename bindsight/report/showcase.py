# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read-only loaders for the real, committed benchmark results.

``benchmarks/`` already holds the strongest evidence this project has:

- ``benchmarks/study/`` — the rediscovery study over fifteen whole, unstratified
  TCGA projects (CA9 surfaced at rank 1 of 291), with its rank and outcome-class
  figures.
- ``benchmarks/designer_benchmark/`` — 20 real ERBB2 binders designed on a free
  Kaggle T4, each with the actual Boltz-2 predicted complex ``.cif``, per-design
  metrics, developability descriptors, and ESM-2 embedding coords. The run used
  the corrected ProteinMPNN protocol, and every design carries a target chain
  byte-identical to the native domain IV.

Until now none of it was reachable from the web app, so a visitor saw a Demo
button and had to take the science on faith. This module is the single source
of truth both the web interface and the documentation site read from, so the
numbers on screen can never drift from the numbers in ``benchmarks/``.

Everything here is read-only, network-free, and degrades to ``None`` rather
than raising: ``benchmarks/`` is not packaged into the wheel
(``pyproject.toml`` ships only the ``bindsight`` package), so a user who
installed from a wheel has no such tree and sees the page degrade.

The Hugging Face Space does **not** deploy the full repository -- its image is
built from ``.huggingface/Dockerfile``, which copies a named set of paths. That
docstring used to claim otherwise, and the claim was false: ``benchmarks/`` was
not among them, so ``benchmarks_root()`` returned ``None`` on the Space and the
Real results page rendered nothing while the README promised twenty binders in
3-D. The Dockerfile now copies it, and
``tests/test_packaging_pins.py`` checks that it still does.

Only the standard library is imported at module scope, so this stays importable
without pandas or Streamlit.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENV_BENCHMARKS_DIR = "BINDSIGHT_BENCHMARKS_DIR"

_STUDY_SUBDIR = "study"
_DESIGNER_SUBDIR = "designer_benchmark"


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
def benchmarks_root() -> Path | None:
    """Locate the repository's ``benchmarks/`` tree.

    Honours the ``BINDSIGHT_BENCHMARKS_DIR`` environment variable first — the
    same override style as ``BINDSIGHT_SURFACE_BIND_DATA`` — then walks up from
    this file looking for the directory.

    Returns:
        The ``benchmarks/`` directory, or ``None`` when running from a wheel
        install where it was never shipped.
    """
    override = os.environ.get(ENV_BENCHMARKS_DIR)
    if override:
        p = Path(override).expanduser()
        return p if p.is_dir() else None

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "benchmarks"
        if (candidate / _STUDY_SUBDIR).is_dir() or (candidate / _DESIGNER_SUBDIR).is_dir():
            return candidate
    return None


def _read_json(path: Path) -> dict[str, Any] | None:
    """Parse ``path`` as JSON, returning ``None`` if absent or malformed."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_tsv(path: Path) -> list[dict[str, str]]:
    """Parse a TSV into a list of row dicts, returning ``[]`` on any failure."""
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh, delimiter="\t"))
    except OSError:
        return []


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse a JSON-lines file, skipping unparseable lines."""
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError:
        return []
    return rows


def _as_float(value: object) -> float | None:
    """Coerce to float, returning ``None`` for missing or non-numeric input."""
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_optional_bool(value: object) -> bool | None:
    """Coerce a JSON boolean, returning ``None`` when it is absent or unreadable.

    Provenance that cannot be read must never collapse into ``False``: an
    artifact with no flag has *unknown* provenance, and a caller has to be able
    to tell that apart from an affirmative "this was recorded as real".

    Args:
        value: The raw value read from the artifact, or ``None`` when absent.

    Returns:
        The boolean, or ``None`` when the artifact did not state one.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


# ---------------------------------------------------------------------------
# Rediscovery study
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StudyShowcase:
    """The rediscovery study, as committed in ``benchmarks/study/``.

    Replaces the earlier six-cohort validation, whose single positive result came
    from a cohort selected by a classifier keyed on the antigen being sought, and
    whose denominator was chosen after seeing which antigens turned out to be
    over-expressed. Neither survives here: cohorts are whole unstratified TCGA
    projects, and the denominators are pre-registered.
    """

    design: dict[str, Any]
    recall_cascade: dict[str, Any]
    tier_sensitivity: dict[str, Any]
    primary_interval: dict[str, Any]
    #: Outcome counts over the **pre-registered denominator only** (the tiers in
    #: ``design.tiers_in_primary_denominator``), not over every scored pair. Use
    #: :attr:`outcome_counts_every_tier` for the whole panel, and never show
    #: either without saying which one it is.
    outcome_counts: dict[str, int]
    pairs: list[dict[str, Any]]
    set_sizes: dict[str, dict[str, int]]
    surfaceome_size: int
    figures: dict[str, Path]
    #: The indication-specificity permutation null. The strongest claim the
    #: study supports, and until this field existed no generated surface could
    #: render it: it lived only in ``benchmarks/study/RESULTS.md``, absent from
    #: every README, docs page and manuscript.
    specificity_null: dict[str, Any] = field(default_factory=dict)
    #: The abundance- and dispersion-matched decoy null. Its headline is a
    #: negative, which is exactly why it has to travel with the positive one.
    decoy_null: dict[str, Any] = field(default_factory=dict)
    #: Cohorts carrying no panel antigen, run to show what no signal looks like.
    null_calibration: dict[str, Any] = field(default_factory=dict)

    @property
    def specificity_is_at_its_floor(self) -> bool:
        """Whether the permutation p is the smallest this design can express.

        Seven antigens give 5,040 orderings, and two of them are prostate, so
        every distinct assignment is enumerated twice: the floor is 2/5040 and
        the observed p sits on it. A surface that prints the p without saying so
        implies a precision the design does not have.
        """
        spec = self.specificity_null
        p_value, floor = spec.get("p_value"), spec.get("p_value_floor")
        if p_value is None or floor is None:
            return False
        return bool(p_value <= floor * 1.000001)

    @property
    def indication_gap(self) -> dict[str, Any]:
        """The within-antigen difference between own and off indication.

        The paired contrast, not the two means side by side: each antigen is its
        own control, which is what makes the interval meaningful at this panel
        size.
        """
        return dict(self.null_calibration.get("paired_difference") or {})

    @property
    def decoy_rows(self) -> list[dict[str, Any]]:
        """Pairs carrying a decoy-null p, best first. The null lives per pair."""
        rows = [p for p in self.pairs if p.get("p_decoy") is not None]
        return sorted(rows, key=lambda r: r["p_decoy"])

    @property
    def decoy_nominal(self) -> int:
        """Pairs nominally significant against abundance-matched decoys."""
        return sum(1 for r in self.decoy_rows if r["p_decoy"] < 0.05)

    @property
    def decoy_surviving_correction(self) -> int:
        """Pairs surviving Benjamini-Hochberg across the panel."""
        return sum(
            1 for r in self.decoy_rows if r.get("p_decoy_bh") is not None and r["p_decoy_bh"] < 0.05
        )

    @property
    def smallest_attainable_decoy_bh(self) -> float | None:
        """The smallest BH-adjusted p any pair in this panel could have produced.

        Each pair's decoy p is bounded below by its own stratum size, so the
        panel's best possible adjusted value follows from the design rather than
        from the data. When that bound already exceeds 0.05, "none survives
        correction" was settled before a single number was computed, and
        reporting it as a finding overstates what the experiment could ever have
        shown. The study's headline negative is exactly this case.
        """
        rows = self.decoy_rows
        if not rows:
            return None
        floors = sorted(r["p_decoy_floor"] for r in rows if r.get("p_decoy_floor") is not None)
        if not floors:
            return None
        n = len(rows)
        # Benjamini-Hochberg at its most generous: every pair sits on its floor.
        return min(float(floors[i] * n) / (i + 1) for i in range(len(floors)))

    @property
    def decoy_negative_was_forced_by_design(self) -> bool:
        """True when no pair could have survived correction whatever the data."""
        bound = self.smallest_attainable_decoy_bh
        return bound is not None and bound >= 0.05

    @property
    def surfaced(self) -> list[dict[str, Any]]:
        """Pairs that reached the candidate shortlist, best rank first."""
        ranked = [p for p in self.pairs if isinstance(p.get("rank"), int)]
        return sorted(ranked, key=lambda p: p["rank"])

    @property
    def headline(self) -> dict[str, Any] | None:
        """The best-ranked surfaced antigen."""
        surfaced = self.surfaced
        return surfaced[0] if surfaced else None

    @property
    def primary_tiers(self) -> tuple[str, ...]:
        """The regulatory tiers the headline denominator was pre-registered on."""
        return tuple(self.design.get("tiers_in_primary_denominator") or ())

    @property
    def outcome_counts_every_tier(self) -> dict[str, int]:
        """The same four outcomes over every scored pair.

        Counted from :attr:`pairs` rather than read from the artifact, because
        the artifact records only the primary-denominator counts and a reader
        comparing them against the pair table needs the other frame too.
        """
        counts: dict[str, int] = {}
        for pair in self.pairs:
            outcome = str(pair.get("outcome_class") or "")
            if outcome:
                counts[outcome] = counts.get(outcome, 0) + 1
        return counts

    @property
    def n_scored(self) -> int:
        """Antigen-cohort pairs in the scored panel."""
        return len(self.pairs)

    @property
    def n_projects(self) -> int:
        """TCGA projects the study covers."""
        return len(self.set_sizes)

    def recall_row(self, denominator: str = "all") -> dict[str, Any]:
        """One denominator's rates across every reported cutoff."""
        block = self.recall_cascade.get(denominator) or {}
        return {
            "median_shortlist": block.get("median_shortlist_size"),
            "at_k": {k: v.get("wilson", {}) for k, v in (block.get("at_k") or {}).items()},
        }

    def rows(self) -> list[dict[str, Any]]:
        """One display-ready row per antigen-cohort pair.

        Every row carries the size of the set its rank was taken within, because
        a rank without it cannot be interpreted, and the outcome class, because
        an antigen the instrument could not see and one the ranking placed low
        are different findings.
        """
        out: list[dict[str, Any]] = []
        for pair in self.pairs:
            out.append(
                {
                    "antigen": pair.get("symbol", "—"),
                    "cohort": str(pair.get("project", "")).removeprefix("TCGA-"),
                    "agent": pair.get("agent", ""),
                    "tier": pair.get("tier", ""),
                    "outcome": pair.get("outcome_class", ""),
                    "log2fc": _as_float(pair.get("log2fc")),
                    "padj": _as_float(pair.get("padj")),
                    "rank": pair.get("rank"),
                    "shortlist": pair.get("shortlist_size"),
                    "counterfactual_rank": pair.get("counterfactual_rank"),
                    "eligible": pair.get("n_eligible"),
                    "why": pair.get("reason", ""),
                }
            )
        return sorted(out, key=lambda r: (r["rank"] is None, r["rank"] or 0, r["antigen"]))


def load_study(root: Path | None = None) -> StudyShowcase | None:
    """Load the rediscovery study results.

    Args:
        root: Optional explicit ``benchmarks/`` directory; discovered when omitted.

    Returns:
        A :class:`StudyShowcase`, or ``None`` when the results are absent.
    """
    base = (root or benchmarks_root() or Path()) / _STUDY_SUBDIR
    data = _read_json(base / "results.json")
    if data is None:
        return None

    figures: dict[str, Path] = {}
    fig_dir = base / "figures"
    if fig_dir.is_dir():
        figures = {p.stem: p for p in sorted(fig_dir.glob("*.png"))}

    return StudyShowcase(
        design=dict(data.get("design") or {}),
        recall_cascade=dict(data.get("recall_cascade") or {}),
        tier_sensitivity=dict(data.get("tier_sensitivity") or {}),
        primary_interval=dict(data.get("primary_interval") or {}),
        outcome_counts=dict(data.get("outcome_class_counts") or {}),
        pairs=list(data.get("pairs") or []),
        set_sizes=dict(data.get("set_sizes_by_cohort") or {}),
        surfaceome_size=int(data.get("surfaceome_size") or 0),
        figures=figures,
        specificity_null=dict(data.get("specificity_null") or {}),
        decoy_null=dict(data.get("decoy_null") or {}),
        null_calibration=dict(data.get("null_calibration") or {}),
    )


# ---------------------------------------------------------------------------
# Designer benchmark
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BinderDesign:
    """One designed binder, joined across metrics, developability and embedding."""

    binder_id: str
    iptm: float | None = None
    pae_interaction: float | None = None
    target_uniprot: str = ""
    validator_name: str = ""
    validator_version: str = ""
    complex_cif: Path | None = None
    fasta: Path | None = None
    developability: dict[str, float] = field(default_factory=dict)
    pc1: float | None = None
    pc2: float | None = None

    @property
    def sequence(self) -> str | None:
        """Read the designed sequence from the committed FASTA, if present."""
        if self.fasta is None or not self.fasta.is_file():
            return None
        try:
            lines = self.fasta.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        return "".join(ln.strip() for ln in lines if ln and not ln.startswith(">")) or None


@dataclass(frozen=True)
class DesignerShowcase:
    """The designer benchmark, as committed in ``benchmarks/designer_benchmark/``."""

    generated_utc: str
    bindsight_version: str
    backend: str
    gpu: str
    validator: str
    n_trajectories: int
    #: ``True`` mock backend, ``False`` real GPU run, ``None`` when the artifact
    #: never stated it. Unknown is not "real": a benchmark that does not record
    #: its own provenance cannot be advertised as a genuine GPU result.
    is_mock: bool | None
    targets: list[str]
    designers: list[dict[str, Any]]
    binders: list[BinderDesign]

    @property
    def scored(self) -> list[BinderDesign]:
        """Binders that carry a validator ipTM, best first."""
        have = [b for b in self.binders if b.iptm is not None]
        return sorted(have, key=lambda b: b.iptm or 0.0, reverse=True)

    @property
    def best(self) -> BinderDesign | None:
        """The highest-ipTM design."""
        ranked = self.scored
        return ranked[0] if ranked else None

    @property
    def success_rate(self) -> float | None:
        """Fraction of designs at or above the ipTM 0.65 criterion, as recorded.

        **Withdrawn as a measure of design quality.** The rate is a real count
        of a real artifact, and it is reported for comparability with published
        de novo work — but a paired control folded each design beside a shuffle
        of its own sequence, and the shuffles cleared the same bar more often
        (50% against 30%; paired difference -0.043, 95% CI -0.142 to +0.054).

        Any surface rendering this must carry that with it, adjacently, and
        ``bindsight.report.web`` does. It is deliberately not a headline
        statistic anywhere: a caveat underneath a number does not travel with
        the number.

        See ``benchmarks/calibration/``.
        """
        for d in self.designers:
            rate = _as_float(d.get("success_rate"))
            if rate is not None:
                return rate
        return None

    @property
    def n_success(self) -> int | None:
        """Designs at or above the criterion, as the artifact counts them."""
        for d in self.designers:
            value = d.get("n_success")
            if value is not None:
                return int(value)
        return None

    @property
    def success_interval(self) -> tuple[float, float] | None:
        """The reported interval around the success rate, if the artifact has one.

        Clustered over backbones, because designs sharing an RFdiffusion
        trajectory are not independent trials. A page that prints the rate
        without it claims a precision twenty designs from ten backbones do not
        carry.
        """
        for d in self.designers:
            low = _as_float(d.get("success_ci_low"))
            high = _as_float(d.get("success_ci_high"))
            if low is not None and high is not None:
                return (low, high)
        return None

    @property
    def mean_iptm(self) -> float | None:
        """Mean ipTM as the benchmark artifact reports it."""
        for d in self.designers:
            value = _as_float(d.get("mean_iptm"))
            if value is not None:
                return value
        return None

    @property
    def n_designs(self) -> int:
        """Total number of designs in the benchmark."""
        return len(self.binders)

    def with_structures(self) -> list[BinderDesign]:
        """Designs whose real predicted complex structure is available."""
        return [b for b in self.scored if b.complex_cif is not None]


def load_designer_benchmark(root: Path | None = None) -> DesignerShowcase | None:
    """Load the designer benchmark and join the per-binder artifacts.

    Args:
        root: Optional explicit ``benchmarks/`` directory; discovered when omitted.

    Returns:
        A :class:`DesignerShowcase`, or ``None`` when the results are absent.
    """
    base = (root or benchmarks_root() or Path()) / _DESIGNER_SUBDIR
    data = _read_json(base / "results.json")
    if data is None:
        return None

    binder_dir = base / "binders"
    dev_by_id: dict[str, dict[str, float]] = {}
    for row in _read_tsv(binder_dir / "developability.tsv"):
        bid = row.get("binder_id")
        if not bid:
            continue
        dev_by_id[bid] = {
            k: v
            for k, v in ((k, _as_float(v)) for k, v in row.items() if k != "binder_id")
            if v is not None
        }

    coords: dict[str, tuple[float | None, float | None]] = {}
    for row in _read_tsv(binder_dir / "embedding_coords.tsv"):
        bid = row.get("binder_id")
        if bid:
            coords[bid] = (_as_float(row.get("pc1")), _as_float(row.get("pc2")))

    binders: list[BinderDesign] = []
    for row in _read_jsonl(binder_dir / "metrics.jsonl"):
        bid = str(row.get("binder_id") or "")
        if not bid:
            continue
        cif = binder_dir / f"{bid}_complex.cif"
        fasta = binder_dir / f"{bid}.fasta"
        pc1, pc2 = coords.get(bid, (None, None))
        binders.append(
            BinderDesign(
                binder_id=bid,
                iptm=_as_float(row.get("iptm")),
                pae_interaction=_as_float(row.get("pae_interaction")),
                target_uniprot=str(row.get("target_uniprot") or ""),
                validator_name=str(row.get("validator_name") or ""),
                validator_version=str(row.get("validator_version") or ""),
                complex_cif=cif if cif.is_file() else None,
                fasta=fasta if fasta.is_file() else None,
                developability=dev_by_id.get(bid, {}),
                pc1=pc1,
                pc2=pc2,
            )
        )

    return DesignerShowcase(
        generated_utc=str(data.get("generated_utc", "")),
        bindsight_version=str(data.get("bindsight_version", "")),
        backend=str(data.get("backend", "")),
        gpu=str(data.get("gpu", "")),
        validator=str(data.get("validator", "")),
        n_trajectories=int(data.get("n_trajectories") or 0),
        is_mock=_as_optional_bool(data.get("is_mock")),
        targets=[str(t) for t in (data.get("targets") or [])],
        designers=list(data.get("designers") or []),
        binders=binders,
    )


# ---------------------------------------------------------------------------
# Headline figures shared by the app and the docs site
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Headline:
    """One published number, with the label and context it must be shown with."""

    value: str
    label: str
    detail: str


def headline_stats() -> list[Headline]:
    """Derive the landing-page numbers from the committed results.

    Every value is read from ``benchmarks/`` rather than written by hand, so the
    marketing surface cannot overstate what the benchmarks actually show.

    Returns:
        Zero to four :class:`Headline` entries, depending on what is available.
    """
    stats: list[Headline] = []

    study = load_study()
    if study is not None:
        top = study.headline
        if top is not None:
            stats.append(
                Headline(
                    value=f"rank {top['rank']}",
                    label=f"{top['symbol']} surfaced",
                    detail=(
                        f"{str(top['project']).removeprefix('TCGA-')} · "
                        f"of {top['shortlist_size']} candidates · "
                        f"log2fc {top['log2fc']:.2f}"
                    ),
                )
            )
        if study.n_projects:
            stats.append(
                Headline(
                    value=f"{study.n_scored} pairs",
                    label=f"across {study.n_projects} TCGA cohorts",
                    detail="whole unstratified projects, paired on patient",
                )
            )

    # The fourth card used to be `success@0.65`, with the withdrawal riding in
    # its caption. That is the same shape as a retracted headline on a front
    # page: the number is what a reader takes away, and a caveat underneath does
    # not travel with it. The rate is still reported in full on the Real results
    # page, beside the control that withdrew it.
    designer = load_designer_benchmark()
    if designer is not None and designer.n_designs:
        stats.append(
            Headline(
                value=f"{designer.n_designs} binders",
                label="designed and folded",
                detail=(
                    f"on {designer.gpu or 'a free GPU'}, structures committed; "
                    "interface confidence is a triage order, not binding evidence"
                ),
            )
        )

    # The study's one positive result, which no surface carried until now.
    if study is not None:
        gap = study.indication_gap
        if gap.get("point") is not None and gap.get("low") is not None:
            stats.append(
                Headline(
                    value=f"{gap['point']:.2f}",
                    label="indication-specific gap",
                    detail=(
                        f"95% CI {gap['low']:.2f}–{gap['high']:.2f}, excludes zero — "
                        "antigens rank higher in the cancer they are actually used in"
                    ),
                )
            )

    return stats
