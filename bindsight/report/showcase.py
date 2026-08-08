# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read-only loaders for the real, committed benchmark results.

``benchmarks/`` already holds the strongest evidence this project has:

- ``benchmarks/validation/`` — the rediscovery experiment over six real TCGA
  cohorts (ERBB2 resurfaced at rank 4), with volcano and recall figures.
- ``benchmarks/designer_benchmark/`` — 20 real ERBB2 binders designed on a free
  Kaggle P100, each with the actual Boltz-2 predicted complex ``.cif``,
  per-design metrics, developability descriptors, and ESM-2 embedding coords.

Until now none of it was reachable from the web app, so a visitor saw a Demo
button and had to take the science on faith. This module is the single source
of truth both the Streamlit app and the documentation site read from, so the
numbers on screen can never drift from the numbers in ``benchmarks/``.

Everything here is read-only, network-free, and degrades to ``None`` rather
than raising: ``benchmarks/`` is not packaged into the wheel
(``pyproject.toml`` ships only the ``bindsight`` package), so an installed-from
-PyPI user has no such tree. The Hugging Face Space and the Streamlit Cloud
mirror both deploy the full repository and therefore get the real thing.

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

_VALIDATION_SUBDIR = "validation"
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
        if (candidate / _VALIDATION_SUBDIR).is_dir() or (candidate / _DESIGNER_SUBDIR).is_dir():
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
# Rediscovery validation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ValidationShowcase:
    """The rediscovery experiment, as committed in ``benchmarks/validation/``."""

    generated_utc: str
    bindsight_version: str
    recall_at_k: dict[str, float]
    # Not a specificity measurement: antigens failing the over-expression rule
    # are excluded from candidacy by that same rule, so the check cannot fail.
    exclusion_check: dict[str, Any]
    cohorts: list[dict[str, Any]]
    data_limited: list[dict[str, Any]]
    figures: dict[str, Path]
    report_html: Path | None

    @property
    def over_expressed(self) -> list[dict[str, Any]]:
        """Cohorts whose expected antigen is genuinely over-expressed."""
        return [c for c in self.cohorts if c.get("category") == "over_expressed"]

    @property
    def not_over_expressed(self) -> list[dict[str, Any]]:
        """Cohorts scored for specificity rather than sensitivity."""
        return [c for c in self.cohorts if c.get("category") != "over_expressed"]

    @property
    def headline(self) -> dict[str, Any] | None:
        """The best-ranked rediscovered antigen, i.e. the sensitivity result."""
        ranked = [
            c
            for c in self.over_expressed
            if isinstance(c.get("expected"), dict) and c["expected"].get("rank") is not None
        ]
        if not ranked:
            return None
        return min(ranked, key=lambda c: c["expected"]["rank"])

    def rows(self) -> list[dict[str, Any]]:
        """Flatten the cohorts into one row per antigen, for tabular display.

        Fold-change and adjusted p-value are taken from ``deg_expected`` — the
        *measured* differential expression, which is present for every cohort.
        ``expected`` only carries them when the antigen was actually surfaced,
        so reading from there alone silently blanks the antigens the benchmark
        most wants to be transparent about (NECTIN4, FOLH1, MSLN).

        Returns:
            One dict per cohort with normalised, display-ready fields.
        """
        out: list[dict[str, Any]] = []
        for c in self.cohorts:
            expected = c.get("expected") or {}
            measured = c.get("deg_expected") or {}
            cohort = c.get("cohort") or {}
            out.append(
                {
                    "antigen": expected.get("symbol") or cohort.get("expected_symbol") or "—",
                    "cohort": cohort.get("label", ""),
                    "project": cohort.get("project", ""),
                    "over_expressed": c.get("category") == "over_expressed",
                    "log2fc": _as_float(measured.get("log2fc", expected.get("log2fc"))),
                    "padj": _as_float(measured.get("padj", expected.get("padj"))),
                    "rank": expected.get("rank"),
                    "note": cohort.get("note", ""),
                }
            )
        return out


def load_validation(root: Path | None = None) -> ValidationShowcase | None:
    """Load the rediscovery validation results.

    Args:
        root: Optional explicit ``benchmarks/`` directory; discovered when omitted.

    Returns:
        A :class:`ValidationShowcase`, or ``None`` when the results are absent.
    """
    base = (root or benchmarks_root() or Path()) / _VALIDATION_SUBDIR
    data = _read_json(base / "results.json")
    if data is None:
        return None

    figures: dict[str, Path] = {}
    fig_dir = base / "figures"
    if fig_dir.is_dir():
        figures = {p.stem: p for p in sorted(fig_dir.glob("*.png"))}

    report = base / "report.html"
    return ValidationShowcase(
        generated_utc=str(data.get("generated_utc", "")),
        bindsight_version=str(data.get("bindsight_version", "")),
        recall_at_k={str(k): float(v) for k, v in (data.get("recall_at_k") or {}).items()},
        exclusion_check=data.get("exclusion_consistency_check") or {},
        cohorts=list(data.get("cohorts") or []),
        data_limited=list(data.get("data_limited") or []),
        figures=figures,
        report_html=report if report.is_file() else None,
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
        """Reported fraction of designs at or above the ipTM 0.65 criterion."""
        for d in self.designers:
            rate = _as_float(d.get("success_rate"))
            if rate is not None:
                return rate
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

    validation = load_validation()
    if validation is not None:
        top = validation.headline
        if top is not None:
            exp = top["expected"]
            stats.append(
                Headline(
                    value=f"rank {exp['rank']}",
                    label=f"{exp['symbol']} rediscovered",
                    detail=f"{top['cohort']['label']} · log2fc {exp['log2fc']:.2f}",
                )
            )
        check = validation.exclusion_check or {}
        if check.get("n"):
            stats.append(
                Headline(
                    value=f"{check.get('consistent', 0)}/{check['n']}",
                    label="consistency check",
                    detail="not-over-expressed antigens excluded by construction",
                )
            )

    designer = load_designer_benchmark()
    if designer is not None:
        best = designer.best
        if best is not None and best.iptm is not None:
            stats.append(
                Headline(
                    value=f"{best.iptm:.2f}",
                    label="best ipTM",
                    detail=f"{designer.n_designs} de novo binders on {designer.gpu or 'a free GPU'}",
                )
            )
        rate = designer.success_rate
        if rate is not None:
            stats.append(
                Headline(
                    value=f"{rate * 100:.0f}%",
                    label="success @ ipTM 0.65",
                    detail=f"validated with {designer.validator or 'Boltz-2'}",
                )
            )

    return stats
