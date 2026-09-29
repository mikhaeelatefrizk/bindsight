# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run existing design, validation, ranking and reporting in an isolated child run."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from bindsight.provenance import append as provenance
from bindsight.provenance.manifest import Manifest, new_manifest, sha256_file
from bindsight.report.web.gpu import (
    MIN_FREE_MEMORY_MIB,
    MIN_MEMORY_MIB,
    devices,
    execution_environment,
    recipe,
    recorded_outputs,
)
from bindsight.report.web.workspace import write_json

LOG = logging.getLogger(__name__)
STAGES = {
    "design": ["design/metrics.jsonl", "design/results.tar.gz"],
    "validate": ["validate/validated.parquet"],
    "rank": ["rank/ranking.parquet"],
    "report": ["report.html"],
}


def _contained(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"A recorded discovery artifact is missing or escapes its run: {relative}")
    return path


def prepare(config: dict[str, Any]) -> Path:
    """Copy verified source artifacts and selected epitopes without modifying discovery."""
    import pandas as pd
    import yaml

    from bindsight.cli import _design_ranges
    from bindsight.config import RunConfig
    from bindsight.io.paths import resolve_run_path

    source = Path(config["source_run"]).resolve()
    output = Path(config["out_dir"])
    signature = sha256_file(source / "run_manifest.jsonld")
    if signature != config["source_manifest_sha256"]:
        raise RuntimeError("The source discovery manifest changed after this job was requested.")
    if sha256_file(source / "config.yaml") != config["source_config_sha256"]:
        raise RuntimeError(
            "The source discovery configuration changed after this job was requested."
        )
    protocol_path = output / "gpu_request.json"
    if protocol_path.is_file():
        if json.loads(protocol_path.read_text(encoding="utf-8")) != config:
            raise RuntimeError(
                "The saved GPU request changed; refusing to resume a different analysis."
            )
        imports = json.loads((output / "gpu_import_files.json").read_text(encoding="utf-8"))
        if any(sha256_file(_contained(output, name)) != digest for name, digest in imports.items()):
            raise RuntimeError(
                "An imported discovery artifact changed; refusing to reuse downstream predictions."
            )
        return output
    output.mkdir(parents=True, exist_ok=True)
    original = Manifest.read(source / "run_manifest.jsonld")
    recorded = recorded_outputs(source, original)
    copies = ["deg/results.parquet", "targets/candidates.parquet", "config.yaml"]
    copies += [
        name
        for name in (
            "deg/fit_diagnostics.json",
            "taxonomy/failure_taxonomy.parquet",
            "annotation_coverage.json",
        )
        if (source / name).is_file()
    ]
    imported = {}
    for name in copies:
        src = _contained(source, name)
        if name != "config.yaml" and recorded.get(name) != sha256_file(src):
            raise RuntimeError(f"Source artifact no longer matches its provenance: {name}")
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        imported[name] = target
    shutil.copyfile(source / "run_manifest.jsonld", output / "source_discovery_manifest.jsonld")
    epitopes = _contained(source, "epitopes/epitopes.parquet")
    if recorded.get("epitopes/epitopes.parquet") != sha256_file(epitopes):
        raise RuntimeError("The source epitopes no longer match their recorded hash.")
    frame = pd.read_parquet(epitopes)
    selected_rows = []
    for selected in config["selected_targets"]:
        matches = []
        for _, row in frame.iterrows():
            residues = list(row.get("residues")) if row.get("residues") is not None else []
            if (
                str(row.get("uniprot_id")) == selected["uniprot"]
                and str(row.get("chain") or "A") == selected["chain"]
                and [int(r) for r in residues] == selected["residues"]
                and [list(x) for x in _design_ranges(row.get("design_ranges"))]
                == [list(x) for x in selected["design_ranges"]]
            ):
                matches.append(row.copy())
        if len(matches) != 1:
            raise RuntimeError("A selected target no longer maps to exactly one recorded epitope.")
        row = matches[0]
        structure = resolve_run_path(source, row["structure_path"])
        if (
            structure is None
            or structure.is_symlink()
            or not structure.resolve().is_relative_to(source)
            or sha256_file(structure) != selected["structure_sha256"]
        ):
            raise RuntimeError("A selected target structure changed or escaped its discovery run.")
        if (
            recorded.get(structure.resolve().relative_to(source).as_posix())
            != selected["structure_sha256"]
        ):
            raise RuntimeError("The selected structure has no matching original discovery hash.")
        relative = "structures/" + selected["structure_sha256"][:20] + structure.suffix
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(structure, target)
        imported[relative] = target
        row["structure_path"] = relative
        selected_rows.append(row)
    (output / "epitopes").mkdir(exist_ok=True)
    pd.DataFrame(selected_rows).to_parquet(output / "epitopes/epitopes.parquet", index=False)
    imported["epitopes/epitopes.parquet"] = output / "epitopes/epitopes.parquet"
    settings = yaml.safe_load((output / "config.yaml").read_text(encoding="utf-8"))
    chosen = config["options"]
    settings.update(out_dir=str(output), backend="local_docker")
    settings.setdefault("params", {})["design"] = {
        "designer": "rfdiff_mpnn",
        "n_trajectories": chosen["trajectories"],
        "seed": chosen["seed"],
        "binder_length_min": chosen["binder_length_min"],
        "binder_length_max": chosen["binder_length_max"],
        "prescreen_top_k": None,
    }
    settings["params"]["validate"] = {
        "validator": "boltz2",
        "diffusion_samples": 1,
        "max_parallel_samples": 1,
    }
    checked = RunConfig.model_validate(settings)
    (output / "config.yaml").write_text(
        yaml.safe_dump(checked.model_dump(mode="json", by_alias=True)),
        encoding="utf-8",
        newline="\n",
    )
    manifest = new_manifest(
        name="Protein design from " + (original.name or "local discovery"),
        config_path="config.yaml",
    )
    manifest.write(output / "run_manifest.jsonld")
    provenance.record(
        output,
        name="import_discovery",
        tool="bindsight.report.web.gpu_worker",
        inputs={"source_manifest": output / "source_discovery_manifest.jsonld"},
        outputs=imported,
        params={
            "source_run_id": original.run_id,
            "selected_targets": config["selected_targets"],
            "gpu_recipe": recipe(),
        },
    )
    # Preserve the exact original contrast and fit provenance without claiming a new fit.
    original_deg = next((s for s in original.stages if s.name == "deg"), None)
    if original_deg is not None:
        original_deg = original_deg.model_copy(deep=True)
        original_deg.status = "skipped_cache"
        original_deg.cache_status = "hit"
        original_deg.notes = (
            "Imported the hash-verified fit from source_discovery_manifest.jsonld; not recomputed."
        )
        portable_outputs = []
        for ref in original_deg.outputs:
            path = Path(ref.path)
            if path.is_absolute() and path.resolve().is_relative_to(source):
                ref = ref.model_copy(update={"path": path.resolve().relative_to(source).as_posix()})
            portable_outputs.append(ref)
        original_deg.outputs = portable_outputs
        provenance.append_stage(output, original_deg)
    imported["source_discovery_manifest.jsonld"] = output / "source_discovery_manifest.jsonld"
    write_json(
        output / "gpu_import_files.json",
        {name: sha256_file(path) for name, path in imported.items()},
    )
    write_json(protocol_path, config)
    return output


def auxiliary_files(run: Path, name: str) -> dict[str, str]:
    """Fingerprint the loose inputs consumed by later CLI/report stages too."""
    folder = {"design": "design/_targets", "validate": "validate"}.get(name)
    if folder is None:
        return {}
    directory = run / folder
    result = {}
    if directory.is_symlink() or not directory.resolve().is_relative_to(run.resolve()):
        raise ValueError("A GPU output directory escaped its analysis.")
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("GPU analysis outputs must not contain symbolic links.")
        if path.is_file():
            relative = path.relative_to(run).as_posix()
            if relative not in STAGES[name]:
                result[relative] = sha256_file(_contained(run, relative))
    return result


def stage_receipt(run: Path, name: str) -> Path:
    """One atomic integrity receipt per successful local GPU stage."""
    return run / f"gpu_integrity_{name}.json"


def verified_stage(run: Path, name: str, *, require_receipt: bool = True) -> bool:
    """Resume only complete scientific stages whose recorded outputs still match."""
    try:
        manifest = Manifest.read(run / "run_manifest.jsonld")
        next(s for s in manifest.stages if s.name == name and s.status == "completed")
        recorded = recorded_outputs(run, manifest, stage_name=name)
        if not all(
            recorded.get(path) == sha256_file(_contained(run, path)) for path in STAGES[name]
        ):
            return False
        if not require_receipt:
            return True
        receipt = json.loads(stage_receipt(run, name).read_text(encoding="utf-8"))
        if receipt.get("outputs") != {path: recorded[path] for path in STAGES[name]}:
            return False
        if receipt.get("auxiliary") != auxiliary_files(run, name):
            raise RuntimeError(
                f"The {name} stage's loose outputs changed or went missing after completion. "
                "Start a new protein-design analysis; these files cannot be safely reused."
            )
        return True
    except (OSError, ValueError, StopIteration):
        return False


def run(config: dict[str, Any], directory: Path) -> None:
    """Run genuine existing CLI stages; a zero exit alone never establishes success."""
    from bindsight.report.web.gpu_setup import smoke

    root = Path(config["gpu_root"])
    if config["recipe_id"] != recipe()["id"]:
        raise RuntimeError(
            "The GPU recipe changed; prepare a new analysis using the current environment."
        )
    selected = next((g for g in devices() if g["index"] == config["gpu_index"]), None)
    if (
        not selected
        or selected["memory_mib"] < MIN_MEMORY_MIB
        or selected["free_memory_mib"] < MIN_FREE_MEMORY_MIB
        or tuple(selected["compute_capability"]) < (7, 5)
    ):
        raise RuntimeError(
            "The GPU is unavailable, busy, or no longer meets the supported requirements. "
            "Free at least 14,900 MiB before resuming; a specific target may need more."
        )
    env = execution_environment(root, config["gpu_index"])
    checks = smoke(root, env)
    output = prepare(config)
    write_json(output / "gpu_environment.json", {"recipe": recipe(), "cuda_checks": checks})
    commands = {
        "design": [
            "design",
            str(output),
            "--backend",
            "local_docker",
            "--designer",
            "rfdiff_mpnn",
            "--validator",
            "boltz2",
            "--trajectories",
            str(config["options"]["trajectories"]),
        ],
        "validate": ["validate", str(output), "--backend", "local_docker", "--validator", "boltz2"],
        "rank": ["rank", str(output)],
        "report": ["report", str(output), "--format", "html"],
    }
    upstream_recomputed = False
    for name, arguments in commands.items():
        write_json(directory / "progress.json", {"phase": name})
        if not upstream_recomputed and verified_stage(output, name):
            LOG.info("Resuming after verified completed stage: %s", name)
            continue
        upstream_recomputed = True
        stage_receipt(output, name).unlink(missing_ok=True)
        LOG.info("Starting actual %s stage", name)
        from bindsight.report.web.gpu_setup import stop_children

        argv = [sys.executable, "-m", "bindsight.cli", *arguments]
        with subprocess.Popen(argv, env=env) as process:
            try:
                code = process.wait(timeout=24 * 3600)
            except subprocess.TimeoutExpired:
                stop_children(process)
                raise
            if code:
                raise subprocess.CalledProcessError(code, argv)
        if not verified_stage(output, name, require_receipt=False):
            raise RuntimeError(f"The {name} command did not produce a complete verified stage.")
        write_json(
            stage_receipt(output, name),
            {
                "outputs": {path: sha256_file(output / path) for path in STAGES[name]},
                "auxiliary": auxiliary_files(output, name),
            },
        )
    write_json(directory / "progress.json", {"phase": "completed"})
    LOG.info(
        "Completed computational design and prediction; experimental binding remains unverified."
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    try:
        path = Path(sys.argv[1])
        run(json.loads(path.read_text(encoding="utf-8")), path.parent)
    except Exception:
        LOG.exception("GPU analysis failed; completed verified stages remain available for resume")
        raise SystemExit(1) from None
