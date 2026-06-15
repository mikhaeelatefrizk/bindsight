"""Three-way designer benchmark: RFdiffusion+ProteinMPNN vs BindCraft vs BoltzGen.

Runs each designer over the *same* target set with the *same* validator (Boltz-2
by default) on a chosen GPU backend, then tabulates per-designer binder quality
(ipTM, PAE-interaction, predicted affinity, success rate). The comparison the
v0.2 validation paper promises.

The real three-way comparison needs a GPU — RFdiffusion, BindCraft and BoltzGen
do not run on CPU — so this module is **CPU-tested with the mock backend** and
**runs for real on ``--backend modal|local_docker|kaggle``**. With the mock
backend the numbers are clearly labelled synthetic (CI/orchestration only) and
are never written as if they were real results.

Reuses the production plugin stack verbatim: :mod:`bindsight.plugins` to resolve
designers/validators/runners, each designer's ``make_spec``/``submit``, and
:mod:`bindsight.cost` for the GPU-cost estimate — so a green mock run is a
faithful dry-run of the real GPU job.
"""

from __future__ import annotations

import json
import logging
import statistics
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bindsight import __version__
from bindsight import cost as cost_mod
from bindsight.plugins import get_designer, get_runner

LOG = logging.getLogger(__name__)

DEFAULT_DESIGNERS = ("rfdiff_mpnn", "bindcraft", "boltzgen")
DEFAULT_IPTM_SUCCESS = 0.65

# Minimal valid PDB so the mock/dry-run path has a structure to ship without a
# network fetch. Real GPU runs pass a true AlphaFold/PDB target structure.
_PLACEHOLDER_PDB = (
    "ATOM      1  CA  GLY A   1      0.000   0.000   0.000  1.00  0.00           C\n"
    "ATOM      2  CA  SER A   2      3.800   0.000   0.000  1.00  0.00           C\n"
    "ATOM      3  CA  HIS A   3      7.600   0.000   0.000  1.00  0.00           C\n"
    "END\n"
)


@dataclass(frozen=True)
class Target:
    """One antigen to design binders against."""

    uniprot: str
    symbol: str
    epitope_residues: list[int] = field(default_factory=list)
    epitope_chain: str = "A"


# Default target set: the held-out known antigens (benchmarks/known.tsv). Epitope
# residues are left empty (whole-target design) until SURFACE-Bind epitope
# prediction lands in v0.2 — which is honest and valid per DesignSpec.
DEFAULT_TARGETS = [
    Target("P04626", "ERBB2"),
    Target("P00533", "EGFR"),
    Target("Q13421", "MSLN"),
    Target("P20138", "CD33"),
    Target("P26951", "IL3RA"),
]


@dataclass
class DesignerScore:
    """Aggregate binder-quality metrics for one designer over the target set."""

    designer: str
    n_targets: int = 0
    n_designs: int = 0
    mean_iptm: float | None = None
    median_iptm: float | None = None
    mean_pae_interaction: float | None = None
    mean_affinity: float | None = None
    success_rate: float | None = None  # fraction of designs with ipTM >= threshold
    per_target: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float | None = None
    gpu_hours: float | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Structure resolution
# ---------------------------------------------------------------------------
def _resolve_structure(target: Target, structures_dir: Path | None, scratch: Path) -> Path:
    """Return a target-structure path: provided file, AlphaFold fetch, or placeholder.

    For ``--backend mock`` (no structures_dir) a placeholder PDB is written so the
    harness runs offline; real backends should pass ``structures_dir`` with true
    structures or rely on the AlphaFoldDB fetch.
    """
    if structures_dir is not None:
        for ext in (".cif", ".pdb", ".mmcif"):
            cand = structures_dir / f"{target.uniprot}{ext}"
            if cand.exists():
                return cand
        # Fall through to AlphaFold fetch if not found locally.
        try:
            from bindsight.structures.alphafolddb import AlphaFoldDBClient

            fetched = AlphaFoldDBClient().fetch(target.uniprot)
            if fetched is not None:
                return Path(fetched)
        except Exception as e:  # pragma: no cover - network edge cases
            LOG.warning("AlphaFold fetch failed for %s: %s", target.uniprot, e)

    placeholder = scratch / f"{target.uniprot}.pdb"
    placeholder.write_text(_PLACEHOLDER_PDB, encoding="utf-8")
    return placeholder


# ---------------------------------------------------------------------------
# Metrics parsing
# ---------------------------------------------------------------------------
def _read_metrics(metrics_jsonl: Path) -> list[dict[str, Any]]:
    if not metrics_jsonl.exists():
        return []
    rows = []
    for line in metrics_jsonl.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _floats(rows: list[dict[str, Any]], key: str) -> list[float]:
    out = []
    for r in rows:
        v = r.get(key)
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


# ---------------------------------------------------------------------------
# Run one designer over the target set
# ---------------------------------------------------------------------------
def run_one_designer(
    designer_name: str,
    targets: list[Target],
    *,
    backend: str,
    validator: str,
    n_trajectories: int,
    seed: int,
    structures_dir: Path | None,
    scratch: Path,
) -> DesignerScore:
    """Design + validate binders for every target with one designer; aggregate."""
    score = DesignerScore(designer=designer_name, n_targets=len(targets))
    try:
        designer = get_designer(designer_name)
        runner = get_runner(backend)
    except Exception as e:
        score.error = f"plugin load failed: {e!r}"
        return score

    all_iptm: list[float] = []
    all_pae: list[float] = []
    all_aff: list[float] = []
    n_designs = 0

    for target in targets:
        struct = _resolve_structure(target, structures_dir, scratch)
        spec = designer.make_spec(
            target_uniprot=target.uniprot,
            target_structure_path=struct,
            epitope_residues=target.epitope_residues,
            epitope_chain=target.epitope_chain,
            n_trajectories=n_trajectories,
            seed=seed,
        )
        # Pin the validator so the remote executor validates identically across
        # designers (job_exec reads extra_params['validator']).
        spec = spec.model_copy(
            update={"extra_params": {**spec.extra_params, "validator": validator}}
        )
        try:
            result = designer.submit(spec, runner)
        except Exception as e:
            LOG.warning("%s/%s submit failed: %s", designer_name, target.symbol, e)
            score.per_target.append({"symbol": target.symbol, "error": repr(e)})
            continue

        rows = _read_metrics(Path(result.metrics_jsonl_path))
        iptm = _floats(rows, "iptm")
        pae = _floats(rows, "pae_interaction")
        aff = _floats(rows, "affinity_pred_value")
        all_iptm += iptm
        all_pae += pae
        all_aff += aff
        n_designs += len(rows)
        score.per_target.append(
            {
                "symbol": target.symbol,
                "uniprot": target.uniprot,
                "n_designs": len(rows),
                "mean_iptm": round(statistics.fmean(iptm), 4) if iptm else None,
                "mean_affinity": round(statistics.fmean(aff), 4) if aff else None,
            }
        )

    score.n_designs = n_designs
    if all_iptm:
        score.mean_iptm = round(statistics.fmean(all_iptm), 4)
        score.median_iptm = round(statistics.median(all_iptm), 4)
        score.success_rate = round(
            sum(1 for v in all_iptm if v >= DEFAULT_IPTM_SUCCESS) / len(all_iptm), 4
        )
    if all_pae:
        score.mean_pae_interaction = round(statistics.fmean(all_pae), 4)
    if all_aff:
        score.mean_affinity = round(statistics.fmean(all_aff), 4)

    # Cost estimate for the real GPU job (zero on mock).
    try:
        _d, _v, combined = cost_mod.estimate_full_run(
            backend=backend,
            designer=designer_name,
            validator=validator,
            n_targets=len(targets),
            n_trajectories=n_trajectories,
        )
        score.cost_usd = combined.usd_estimate
        score.gpu_hours = combined.gpu_hours
    except Exception as e:  # pragma: no cover - unknown plugin/backend
        LOG.warning("cost estimate failed for %s: %s", designer_name, e)

    return score


# ---------------------------------------------------------------------------
# Orchestration + reporting
# ---------------------------------------------------------------------------
def run_designer_benchmark(
    *,
    out_dir: Path,
    backend: str,
    designers: tuple[str, ...] = DEFAULT_DESIGNERS,
    validator: str = "boltz2",
    targets: list[Target] | None = None,
    n_trajectories: int = 50,
    seed: int = 42,
    structures_dir: Path | None = None,
) -> dict[str, Any]:
    """Run every designer over the target set and write results + a summary table.

    Writes ``results.json`` and ``RESULTS.md`` under ``out_dir``. On ``mock`` the
    summary is clearly marked synthetic.
    """
    import datetime as _dt

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = targets or DEFAULT_TARGETS

    scores: list[DesignerScore] = []
    with tempfile.TemporaryDirectory(prefix="bindsight_designerbench_") as tmp:
        scratch = Path(tmp)
        for name in designers:
            LOG.info("=== designer benchmark: %s (%d targets) ===", name, len(targets))
            scores.append(
                run_one_designer(
                    name,
                    targets,
                    backend=backend,
                    validator=validator,
                    n_trajectories=n_trajectories,
                    seed=seed,
                    structures_dir=structures_dir,
                    scratch=scratch,
                )
            )

    is_mock = backend == "mock"
    summary = {
        "schema": "bindsight-designer-benchmark/1",
        "generated_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "bindsight_version": __version__,
        "backend": backend,
        "validator": validator,
        "n_trajectories": n_trajectories,
        "is_mock": is_mock,
        "targets": [t.symbol for t in targets],
        "designers": [_score_dict(s) for s in scores],
    }
    (out_dir / "results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out_dir / "RESULTS.md").write_text(_render_md(summary), encoding="utf-8")
    LOG.info("designer benchmark complete; wrote %s", out_dir)
    return summary


def _score_dict(s: DesignerScore) -> dict[str, Any]:
    return {
        "designer": s.designer,
        "n_targets": s.n_targets,
        "n_designs": s.n_designs,
        "mean_iptm": s.mean_iptm,
        "median_iptm": s.median_iptm,
        "mean_pae_interaction": s.mean_pae_interaction,
        "mean_affinity": s.mean_affinity,
        "success_rate": s.success_rate,
        "cost_usd": s.cost_usd,
        "gpu_hours": s.gpu_hours,
        "per_target": s.per_target,
        "error": s.error,
    }


def _render_md(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    a = lines.append
    a("# bindsight designer benchmark — results\n")
    if summary["is_mock"]:
        a(
            "> **⚠ MOCK BACKEND — synthetic numbers for CI/orchestration only.** "
            "These are NOT real GPU results. Re-run with `--backend modal` (or "
            "`local_docker`/`kaggle`) on a GPU to produce real metrics.\n"
        )
    a(f"- Generated: `{summary['generated_utc']}` · bindsight `{summary['bindsight_version']}`")
    a(
        f"- Backend: `{summary['backend']}` · validator: `{summary['validator']}` · "
        f"trajectories/target: {summary['n_trajectories']}"
    )
    a(f"- Targets: {', '.join(summary['targets'])}\n")

    a(
        "| designer | designs | mean ipTM | median ipTM | mean PAE-int | mean affinity | "
        "success@0.65 | est. cost (USD) | GPU-h |"
    )
    a("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for d in summary["designers"]:

        def fmt(v: Any, pct: bool = False) -> str:
            if v is None:
                return "—"
            return f"{v:.0%}" if pct else f"{v:.3g}"

        a(
            f"| {d['designer']} | {d['n_designs']} | {fmt(d['mean_iptm'])} | "
            f"{fmt(d['median_iptm'])} | {fmt(d['mean_pae_interaction'])} | "
            f"{fmt(d['mean_affinity'])} | {fmt(d['success_rate'], pct=True)} | "
            f"{fmt(d['cost_usd'])} | {fmt(d['gpu_hours'])} |"
        )
    a("")
    a(
        "**ipTM** / **PAE-interaction** / **affinity** are the validator's "
        "(Boltz-2) interface-confidence and predicted-affinity outputs; "
        "**success@0.65** is the fraction of designs with ipTM ≥ 0.65. Cost is the "
        "`bindsight.cost` estimate for the run on the chosen backend.\n"
    )
    return "\n".join(lines)
