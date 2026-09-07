# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
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
from bindsight.benchmark.statistics import cluster_bootstrap_interval, wilson_interval
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
    # The numerator and a Wilson interval for it. Two runs of the same target
    # differing only in seed returned 2/20 and 6/20 - 10% and 30% - which a
    # Fisher exact test cannot separate (p = 0.24). A bare percentage from
    # twenty designs claims a precision the sample does not carry, so the
    # interval travels with it.
    n_success: int | None = None
    # The reported interval, clustered over backbones. See _success_intervals.
    success_ci_low: float | None = None
    success_ci_high: float | None = None
    success_ci_method: str | None = None
    # The same interval computed as if every design were independent, kept so a
    # reader can see how much the clustering costs rather than taking it on
    # trust. Never the reported figure.
    success_ci_independent_low: float | None = None
    success_ci_independent_high: float | None = None
    # Backbone-level view: how many RFdiffusion trajectories yielded any design
    # over the bar. This is the number of independent attempts that worked.
    n_backbones: int | None = None
    n_backbones_with_success: int | None = None
    per_target: list[dict[str, Any]] = field(default_factory=list)
    # Results tarballs this designer produced, so the binder artifacts can be
    # staged after the run. Excluded from the serialised summary: a local scratch
    # path is not a published result.
    archives: list[Path] = field(default_factory=list)
    cost_usd: float | None = None
    gpu_hours: float | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Structure resolution
# ---------------------------------------------------------------------------
#: Where prepared target structures live by default. Leaving this unset used to
#: mean "write a placeholder", which is catastrophic on a real backend.
DEFAULT_STRUCTURES_DIR = Path("data/target_structures")


def _resolve_structure(
    target: Target,
    structures_dir: Path | None,
    scratch: Path,
    *,
    allow_placeholder: bool = False,
) -> Path:
    """Return a real target structure, or fail.

    The placeholder is a three-residue stub. It exists so the harness can run
    offline on ``--backend mock``, and it is worthless anywhere else: RFdiffusion
    will happily design binders against three residues, Boltz-2 will score them,
    and the run will report ipTM figures for a target that was never present.
    That is the most expensive kind of silent failure this project can produce —
    it costs GPU hours and yields numbers that look real.

    So ``allow_placeholder`` is False by default and only the mock backend passes
    True. A real backend with no resolvable structure raises.

    Resolution order: the structures directory, then AlphaFoldDB. The directory
    is consulted even when the caller passed none, because the default location
    is where ``prepare_erbb2_target.py`` writes.

    Raises:
        FileNotFoundError: On a real backend when no structure could be resolved.
    """
    search_dir = structures_dir if structures_dir is not None else DEFAULT_STRUCTURES_DIR
    for ext in (".cif", ".pdb", ".mmcif"):
        cand = Path(search_dir) / f"{target.uniprot}{ext}"
        if cand.exists():
            LOG.info("%s: using %s", target.symbol, cand)
            return cand

    try:
        from bindsight.structures.alphafolddb import AlphaFoldDBClient

        fetched = AlphaFoldDBClient().fetch(target.uniprot)
        if fetched is not None:
            LOG.info("%s: using AlphaFold model %s", target.symbol, fetched)
            return Path(fetched)
    except Exception as e:  # pragma: no cover - network edge cases
        LOG.warning("AlphaFold fetch failed for %s: %s", target.uniprot, e)

    if not allow_placeholder:
        raise FileNotFoundError(
            f"no structure for {target.symbol} ({target.uniprot}). Looked in "
            f"{search_dir}/ and AlphaFoldDB. A real backend will not fall back to "
            "the three-residue placeholder: designing against it burns GPU hours "
            "and produces ipTM figures for a target that was never there. Prepare "
            "the structure first, e.g. "
            "`python benchmarks/designer_benchmark/prepare_erbb2_target.py`."
        )

    LOG.warning(
        "%s: no structure found; writing the three-residue placeholder. This is "
        "only meaningful on the mock backend.",
        target.symbol,
    )
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
    bindsight_wheel: Path | None = None,
) -> DesignerScore:
    """Design + validate binders for every target with one designer; aggregate."""
    score = DesignerScore(designer=designer_name, n_targets=len(targets))
    try:
        designer = get_designer(designer_name)
        # get_runner forwards only the kwargs a given runner accepts, so this is
        # inert for backends that install nothing.
        runner = get_runner(backend, bindsight_wheel=bindsight_wheel)
    except Exception as e:
        score.error = f"plugin load failed: {e!r}"
        return score

    all_iptm: list[float] = []
    all_pae: list[float] = []
    all_aff: list[float] = []
    outcomes_by_backbone: dict[str, list[bool]] = {}
    archives: list[Path] = []
    n_designs = 0

    for target in targets:
        try:
            struct = _resolve_structure(
                target, structures_dir, scratch, allow_placeholder=(backend == "mock")
            )
        except FileNotFoundError as e:
            # Abort the whole designer: submitting the remaining targets would
            # spend GPU time on a run whose summary is already incomplete.
            LOG.error("%s", e)
            score.error = str(e)
            return score
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

        archives.append(Path(result.results_archive_path))
        rows = _read_metrics(Path(result.metrics_jsonl_path))
        iptm = _floats(rows, "iptm")
        pae = _floats(rows, "pae_interaction")
        aff = _floats(rows, "affinity_pred_value")
        all_iptm += iptm
        all_pae += pae
        all_aff += aff
        for row in rows:
            value = row.get("iptm")
            if value is None:
                continue
            key = _backbone_of(str(row.get("binder_id", "")))
            outcomes_by_backbone.setdefault(key, []).append(float(value) >= DEFAULT_IPTM_SUCCESS)
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
        n_ok = sum(1 for v in all_iptm if v >= DEFAULT_IPTM_SUCCESS)
        score.success_rate = round(n_ok / len(all_iptm), 4)
        score.n_success = n_ok
        for field, value in _success_intervals(outcomes_by_backbone).items():
            setattr(score, field, value)
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

    score.archives = archives
    return score


# ---------------------------------------------------------------------------
# Orchestration + reporting
# ---------------------------------------------------------------------------
def stage_binder_artifacts(archives: list[Path], out_dir: Path) -> dict[str, int]:
    """Replace ``out_dir/binders/`` with the artifacts these archives contain.

    A benchmark that rewrites ``results.json`` but leaves the previous run's
    structures in place produces a directory whose metrics and whose molecules
    describe different runs. The Real-results page renders those structures, so
    the mismatch would be published as one coherent result. Staging is therefore
    destructive by design: superseded ``.fasta`` and ``_complex.cif`` files are
    removed before the new ones are written.

    Files a run does not produce — developability descriptors, embedding
    coordinates — are left alone, because they are derived by separate scripts
    from whatever binders are present and are regenerated by running those.

    Args:
        archives: results tarballs from the run, in target order.
        out_dir: the benchmark directory holding ``binders/``.

    Returns:
        Counts of what was removed and written.
    """
    import tarfile

    binders = Path(out_dir) / "binders"
    binders.mkdir(parents=True, exist_ok=True)

    removed = 0
    for stale in list(binders.glob("*.fasta")) + list(binders.glob("*_complex.cif")):
        stale.unlink()
        removed += 1

    written = 0
    metrics_lines: list[str] = []
    for archive in archives:
        if not Path(archive).is_file():
            LOG.warning("results archive missing, cannot stage: %s", archive)
            continue
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                name = Path(member.name).name
                src = tf.extractfile(member)
                if src is None:
                    continue
                if member.name.startswith("design/") and name.endswith(".fasta"):
                    (binders / name).write_bytes(src.read())
                    written += 1
                elif member.name.startswith("validate/") and name.endswith(".cif"):
                    # Boltz-2 writes the predicted complex under validate/<binder_id>/.
                    binder_id = Path(member.name).parts[1]
                    (binders / f"{binder_id}_complex.cif").write_bytes(src.read())
                    written += 1
                elif name == "metrics.jsonl":
                    metrics_lines += [ln for ln in src.read().decode().splitlines() if ln.strip()]

    if metrics_lines:
        (binders / "metrics.jsonl").write_text("\n".join(metrics_lines) + "\n", encoding="utf-8")
    LOG.info("staged %d binder artifact(s); removed %d superseded", written, removed)
    return {"written": written, "removed": removed}


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
    bindsight_wheel: Path | None = None,
) -> dict[str, Any]:
    """Run every designer over the target set and write results + a summary table.

    Writes ``results.json`` and ``RESULTS.md`` under ``out_dir``. On ``mock`` the
    summary is clearly marked synthetic.

    Args:
        out_dir: directory to write ``results.json``, ``RESULTS.md`` and staged
            binder artifacts into.
        backend: runner backend to submit design jobs to (``kaggle``, ``modal``,
            ``local_docker``, ``mock``).
        designers: designer plugins to score, one arm each.
        validator: validator plugin used to score every design.
        targets: targets to design against; ``DEFAULT_TARGETS`` when omitted.
        n_trajectories: backbones per target, per designer.
        seed: seed forwarded to each designer.
        structures_dir: directory of prepared target structures. A real backend
            errors rather than falling back to the placeholder.
        bindsight_wheel: a wheel built from the working tree, embedded in the
            remote job so the GPU runs this code. Without it a remote backend
            pip-installs bindsight from git and silently exercises the default
            branch, which is how a benchmark launched to validate a fix came
            back having run the unfixed code.

    Returns:
        The summary dict that was written to ``results.json``.
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
                    bindsight_wheel=bindsight_wheel,
                    structures_dir=structures_dir,
                    scratch=scratch,
                )
            )

    is_mock = backend == "mock"
    # Never stage mock output into the committed binder directory: the whole
    # point of that directory is that it holds real predicted complexes.
    if not is_mock:
        archives = [a for sc in scores for a in getattr(sc, "archives", [])]
        if archives:
            stage_binder_artifacts(archives, out_dir)
    summary = {
        "schema": "bindsight-designer-benchmark/1",
        "generated_utc": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
        "bindsight_version": __version__,
        "backend": backend,
        "validator": validator,
        "n_trajectories": n_trajectories,
        "is_mock": is_mock,
        # Which bindsight actually ran. A result that cannot name its own code
        # is not reproducible, and "the default branch at some past moment" is
        # not a name.
        "bindsight_source": (
            "mock backend: nothing is installed and no GPU runs"
            if is_mock
            else f"working-tree wheel {Path(bindsight_wheel).name}"
            if bindsight_wheel
            else "pip install from the repository default branch"
        ),
        "targets": [t.symbol for t in targets],
        "designers": [_score_dict(s) for s in scores],
    }
    if _would_erase_a_real_result(out_dir, summary):
        salvage = out_dir / "results.failed.json"
        salvage.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        LOG.error(
            "this run produced no designs, and %s records a run that did. Refusing "
            "to overwrite it; the failed run is saved to %s. Fix the cause and "
            "re-run, or delete the committed result deliberately if it is genuinely "
            "superseded.",
            out_dir / "results.json",
            salvage,
        )
        return summary

    (out_dir / "results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out_dir / "RESULTS.md").write_text(_render_md(summary), encoding="utf-8")
    LOG.info("designer benchmark complete; wrote %s", out_dir)
    return summary


def _design_count(summary: dict[str, Any]) -> int:
    """Total designs across every arm of a benchmark summary."""
    return sum(int(d.get("n_designs") or 0) for d in summary.get("designers", []))


def _would_erase_a_real_result(out_dir: Path, summary: dict[str, Any]) -> bool:
    """True when writing ``summary`` would replace a real result with an empty one.

    A benchmark that fails after the GPU work is done still reaches the write,
    and an empty summary is a perfectly well-formed one. That is not
    hypothetical: a corrected ERBB2 re-run completed on the T4, produced its
    tarball, and then the harness hit an encoding error writing the kernel log
    and recorded zero designs — which promptly overwrote twenty committed
    binders' worth of measurements with dashes, while ``binders/`` still held
    the structures those measurements described.

    Refusing the write is the conservative direction. The two ways to lose data
    here are not symmetric: a stale-but-real result is visibly stale and can be
    replaced deliberately, whereas an overwritten one is gone.

    Args:
        out_dir: the benchmark directory.
        summary: the summary this run would write.

    Returns:
        True if the existing ``results.json`` records designs and this one does not.
    """
    if _design_count(summary) > 0:
        return False
    existing = out_dir / "results.json"
    if not existing.is_file():
        return False
    try:
        prior = json.loads(existing.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # An unreadable prior result is not evidence worth protecting.
        return False
    return _design_count(prior) > 0


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
        "n_success": s.n_success,
        "success_ci_low": s.success_ci_low,
        "success_ci_high": s.success_ci_high,
        "success_ci_method": s.success_ci_method,
        "success_ci_independent_low": s.success_ci_independent_low,
        "success_ci_independent_high": s.success_ci_independent_high,
        "n_backbones": s.n_backbones,
        "n_backbones_with_success": s.n_backbones_with_success,
        "cost_usd": s.cost_usd,
        "gpu_hours": s.gpu_hours,
        "per_target": s.per_target,
        "error": s.error,
    }


def _backbone_of(binder_id: str) -> str:
    """The trajectory a design came from.

    Ids are ``<target>_<backbone>_seq<i>``, so several designs share a backbone:
    ProteinMPNN produces multiple sequences per RFdiffusion trajectory. A
    designer whose ids carry no ``_seq`` suffix gets one cluster per design,
    which is the right degradation — nothing is assumed to be correlated that
    is not known to be.
    """
    return binder_id.rsplit("_seq", 1)[0]


def _success_intervals(outcomes: dict[str, list[bool]]) -> dict[str, Any]:
    """Interval for the success rate, clustered over backbones.

    Designs are not independent trials. Ten RFdiffusion trajectories times two
    ProteinMPNN sequences is twenty designs but ten attempts, and success
    clusters hard: on the committed ERBB2 run five backbones yielded nothing,
    three yielded two, and within-trajectory ipTM correlates at about 0.55.
    A binomial interval over the designs therefore claims more precision than
    the run contains — it gave (22%, 61%) where clustering gives (15%, 70%).

    This is the same error the study half was already fixed for, where one
    antigen appearing in several cohorts is one piece of evidence rather than
    several; :func:`cluster_bootstrap_interval` exists for it and was simply
    never called from here.

    Args:
        outcomes: backbone id -> whether each of its designs cleared the bar.

    Returns:
        Fields to merge into the score: the clustered interval, the
        independence-assuming one for contrast, and the backbone-level counts.
    """
    flat = [ok for v in outcomes.values() for ok in v]
    n_ok = sum(flat)
    independent = wilson_interval(n_ok, len(flat))
    out: dict[str, Any] = {
        "n_backbones": len(outcomes),
        "n_backbones_with_success": sum(1 for v in outcomes.values() if any(v)),
        "success_ci_independent_low": round(independent.low, 4),
        "success_ci_independent_high": round(independent.high, 4),
    }
    try:
        clustered = cluster_bootstrap_interval(outcomes, n_boot=10_000, seed=0)
    except ValueError:  # no clusters with outcomes; nothing to report
        return out
    out["success_ci_low"] = round(clustered.low, 4)
    out["success_ci_high"] = round(clustered.high, 4)
    out["success_ci_method"] = clustered.method
    return out


def _success_cell(d: dict[str, Any]) -> str:
    """Render success@0.65 with its interval, never as a bare percentage.

    The interval is clustered over backbones, because designs sharing a
    trajectory are not independent trials. A binomial interval over the designs
    reads narrower than the run earns.
    """
    rate = d.get("success_rate")
    if rate is None:
        return "—"
    low, high = d.get("success_ci_low"), d.get("success_ci_high")
    n_ok, n = d.get("n_success"), d.get("n_designs")
    if low is None or high is None or n_ok is None or not n:
        return f"{rate:.0%}"
    return f"{n_ok}/{n} = {rate:.0%} ({low:.0%}–{high:.0%})"


def _backbone_cell(d: dict[str, Any]) -> str:
    """Backbones that yielded any design over the bar — the independent attempts."""
    hit, total = d.get("n_backbones_with_success"), d.get("n_backbones")
    if hit is None or not total:
        return "—"
    return f"{hit}/{total} = {hit / total:.0%}"


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
    a(f"- Targets: {', '.join(summary['targets'])}")
    if summary.get("gpu"):
        a(f"- GPU: `{summary['gpu']}`")
    if summary.get("bindsight_source"):
        # Which bindsight actually ran. Remote backends pip-install it, so the
        # code that produced a result is not necessarily the code that submitted
        # the job — a benchmark launched to validate a fix once ran the unfixed
        # code because the kernel installed the repository's default branch.
        a(f"- Code: {summary['bindsight_source']}")
    if not summary["is_mock"]:
        a(
            "\n> **The target chain was held fixed.** ProteinMPNN is invoked with\n"
            "> `--pdb_path_chains` so it redesigns the binder only. A superseded run\n"
            "> omitted that flag, rewrote the target as well, and therefore optimised\n"
            "> its designs against a partly-invented surface before scoring them\n"
            "> against the native one; its figures are withdrawn. Every design here\n"
            "> carries a target chain byte-identical to the prepared structure."
        )
    a("")

    a(
        "| designer | designs | mean ipTM | median ipTM | mean PAE-int | mean affinity | "
        "success@0.65 | backbones hit | est. cost (USD) | GPU-h |"
    )
    a("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for d in summary["designers"]:

        def fmt(v: Any, pct: bool = False) -> str:
            if v is None:
                return "—"
            return f"{v:.0%}" if pct else f"{v:.3g}"

        a(
            f"| {d['designer']} | {d['n_designs']} | {fmt(d['mean_iptm'])} | "
            f"{fmt(d['median_iptm'])} | {fmt(d['mean_pae_interaction'])} | "
            f"{fmt(d['mean_affinity'])} | {_success_cell(d)} | {_backbone_cell(d)} | "
            f"{fmt(d['cost_usd'])} | {fmt(d['gpu_hours'])} |"
        )
    a("")
    a(
        "**ipTM** / **PAE-interaction** / **affinity** are the validator's "
        "(Boltz-2) interface-confidence and predicted-affinity outputs; "
        "**success@0.65** is the fraction of designs with ipTM ≥ 0.65, with a 95% "
        "interval **bootstrapped over backbones**, not over designs: ProteinMPNN "
        "produces several sequences per RFdiffusion trajectory, so the designs are "
        "not independent trials and a binomial interval over them reads narrower "
        "than the run earns. **backbones hit** is the fraction of trajectories that "
        "yielded any design over the bar, which is the count of independent attempts "
        "that worked. Read the interval, not the point: two runs of the same target "
        "differing only in seed returned 2/20 and 6/20, which a Fisher exact test "
        "cannot separate. Cost is the "
        "`bindsight.cost` estimate for the run on the chosen backend.\n"
    )
    return "\n".join(lines)
