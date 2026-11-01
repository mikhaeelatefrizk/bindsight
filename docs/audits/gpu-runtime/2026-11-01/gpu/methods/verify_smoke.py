"""Independently check a real 142+60-residue GPU smoke; never execute TRB/pickle data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import zipfile
from datetime import datetime, timezone
from email.parser import BytesParser
from pathlib import Path

import numpy as np
import yaml
from Bio.PDB.MMCIF2Dict import MMCIF2Dict

HERE = Path(__file__).resolve().parent
TARGET_SHA = "8286bf0a965a761b41258460cb3e850882b78dd09439eafbced72ec986f72178"
SPEC_SHA = "e779ae496bdeafbe7e26264ab5d360c3cf80c3162570f2e715f2a7f40b59c389"
BOLTZ_RUNTIME_VERSION = "2.0.3+bindsight.1"
BOLTZ_UPSTREAM_SHA = "5851dd10c7819d4c011534a4e5c9cc495d95e42e0e1336617a1e9e78d6c4cf12"
CURAND_CUDA12_SHA = "12411c1e921cd3cac4e0d2f58024a3e6bbb7cea584d5cd768ad908ec762c5545"
BOLTZ_PUBLISHER_REVISION = "6fdef46d763fee7fbb83ca5501ccceff43b85607"
BOLTZ_ASSETS = {
    "boltz2_conf.ckpt": {
        "bytes": 2286561469,
        "sha256": "090e82ac8c92f5e943fa1b39e7410a44027bea7243c0bbb3caa67a77fc1428e1",
    },
    "boltz2_aff.ckpt": {
        "bytes": 2062139170,
        "sha256": "dcc5cd3722b1c9eaa34267e4ae32f55cbbf1963f4c19319381ccfa30fdd2ca9e",
    },
    "mols.tar": {
        "bytes": 1855662080,
        "sha256": "39e076d96dbec6b4e86982bbda16f3a53a2a60c9bdc17828d88f6f9a0c7d1fd7",
    },
}
BOLTZ_DEPENDENCY_CHANGES = {
    "hydra-core": {"from": "1.3.2", "to": "1.3.8"},
    "pytorch-lightning": {"from": "2.5.0", "to": "2.6.6"},
    "requests": {"from": "2.32.3", "to": "2.34.2"},
    "biopython": {"from": "1.84", "to": "1.88"},
}
RF_WEIGHTS = {
    "Base_ckpt.pt": "0fcf7d7c32b4848030aca3a051e6768de194616f96ba6c38186351a33bfc6eca",
    "Complex_base_ckpt.pt": "76e4e260aefee3b582bd76b77ab95d2592e64f00c51bf344968ab9239f3250bc",
}
AA3 = dict(
    zip(
        "ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL".split(),
        "ARNDCQEGHILKMFPSTWYV",
    )
)
IDS = [f"P04626_binder_42_seq{i}" for i in range(2)]


class Incomplete(Exception):
    pass


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def verify_boltz_patch(receipt, upstream_path, patched_path):
    """Independently compare the actual local wheels against the runtime receipt."""
    if not receipt:
        raise Incomplete("Missing Boltz metadata-patch receipt")
    require(
        receipt.get("schema") == "bindsight-boltz-dependency-patch/1",
        "Unknown Boltz patch schema",
    )
    require(
        receipt.get("upstream_sha256") == BOLTZ_UPSTREAM_SHA,
        "Unreviewed upstream Boltz wheel",
    )
    require(
        sha(upstream_path) == BOLTZ_UPSTREAM_SHA, "Local upstream Boltz bytes differ"
    )
    require(
        upstream_path.stat().st_size == 263964, "Unexpected upstream Boltz wheel size"
    )
    require(
        receipt.get("upstream_version") == "2.0.3", "Unexpected upstream Boltz version"
    )
    require(
        receipt.get("installed_version") == BOLTZ_RUNTIME_VERSION,
        "Unexpected patched Boltz version",
    )
    require(
        receipt.get("patched_sha256") == sha(patched_path),
        "Installed Boltz wheel identity differs",
    )
    require(
        receipt.get("unchanged_implementation") is True,
        "Boltz implementation preservation absent",
    )
    require(
        receipt.get("dependency_changes") == BOLTZ_DEPENDENCY_CHANGES,
        "Unreviewed Boltz dependency changes",
    )
    old_info = "boltz-2.0.3.dist-info/"
    new_info = f"boltz-{BOLTZ_RUNTIME_VERSION}.dist-info/"
    with (
        zipfile.ZipFile(upstream_path) as upstream,
        zipfile.ZipFile(patched_path) as patched,
    ):

        def renamed(name):
            return (
                new_info + name[len(old_info) :] if name.startswith(old_info) else name
            )

        names = upstream.namelist()
        require(
            set(patched.namelist()) == {renamed(name) for name in names},
            "Boltz patch added/removed files",
        )
        hashes = {
            name: hashlib.sha256(upstream.read(name)).hexdigest()
            for name in names
            if name.startswith("boltz/")
        }
        require(
            receipt.get("unchanged_package_files") == hashes,
            "Boltz payload receipt differs from official bytes",
        )
        for name in names:
            if name not in {old_info + "METADATA", old_info + "RECORD"}:
                require(
                    upstream.read(name) == patched.read(renamed(name)),
                    f"Boltz source/resource changed: {name}",
                )
        header, separator, body = upstream.read(old_info + "METADATA").partition(
            b"\n\n"
        )
        lines = header.split(b"\n")
        changes = {b"Version: 2.0.3": f"Version: {BOLTZ_RUNTIME_VERSION}".encode()}
        changes.update(
            {
                f"Requires-Dist: {name} =={delta['from']}".encode(): f"Requires-Dist: {name} =={delta['to']}".encode()
                for name, delta in BOLTZ_DEPENDENCY_CHANGES.items()
            }
        )
        require(
            all(lines.count(old) == 1 for old in changes),
            "Unexpected official metadata",
        )
        expected = (
            b"\n".join(changes.get(line, line) for line in lines) + separator + body
        )
        require(
            patched.read(new_info + "METADATA") == expected,
            "Unexpected Boltz metadata transformation",
        )
    return {
        "upstream_sha256": BOLTZ_UPSTREAM_SHA,
        "patched_sha256": sha(patched_path),
        "unchanged_package_files": len(hashes),
    }


def one(root, pattern):
    found = sorted(p for p in root.rglob(pattern) if p.is_file())
    if not found:
        raise Incomplete(f"Missing {pattern} under {root}")
    require(len(found) == 1, f"Expected exactly one {pattern}; found {len(found)}")
    return found[0]


def fasta(path):
    records = []
    for line in Path(path).read_text().splitlines():
        if line.startswith(">"):
            records.append([line[1:], ""])
        elif line.strip():
            require(records, f"FASTA sequence before header: {path}")
            records[-1][1] += line.strip()
    require(records, f"Empty FASTA: {path}")
    return records


def structure(path):
    """Read residue identities and actual coordinates, independent of Bindsight parsers."""
    path = Path(path)
    atoms = []
    if path.suffix == ".cif":
        data = MMCIF2Dict(str(path))
        keys = [
            "label_asym_id",
            "label_seq_id",
            "label_comp_id",
            "label_atom_id",
            "Cartn_x",
            "Cartn_y",
            "Cartn_z",
        ]
        columns = [data.get("_atom_site." + key, []) for key in keys]
        require(
            all(isinstance(col, list) for col in columns), "Malformed mmCIF atom table"
        )
        require(
            len({len(col) for col in columns}) == 1 and columns[0],
            "Missing mmCIF atom fields",
        )
        for chain, residue, comp, atom, x, y, z in zip(*columns, strict=True):
            if residue not in {".", "?"}:
                atoms.append(
                    (
                        chain,
                        (int(residue), ""),
                        comp,
                        atom,
                        (float(x), float(y), float(z)),
                    )
                )
    else:
        for line in path.read_text().splitlines():
            if line.startswith("ATOM  "):
                atoms.append(
                    (
                        line[21],
                        (int(line[22:26]), line[26]),
                        line[17:20],
                        line[12:16].strip(),
                        tuple(float(line[i : i + 8]) for i in (30, 38, 46)),
                    )
                )
    require(atoms, f"No protein atoms in {path}")
    residues, ca = {}, {}
    for chain, residue, comp, atom, xyz in atoms:
        require(
            all(math.isfinite(value) for value in xyz),
            f"Nonfinite coordinate in {path}",
        )
        require(comp in AA3, f"Nonstandard residue {comp} in {path}")
        previous = residues.setdefault(chain, {}).setdefault(residue, comp)
        require(previous == comp, f"Conflicting residue identity in {path}")
        if atom == "CA":
            ca.setdefault(chain, {})[residue] = xyz
    sequences = {
        chain: "".join(AA3[rows[key]] for key in sorted(rows))
        for chain, rows in residues.items()
    }
    require(
        all(set(ca.get(chain, {})) == set(rows) for chain, rows in residues.items()),
        f"Missing alpha-carbon residues in {path}",
    )
    coordinates = {
        chain: np.array([rows[key] for key in sorted(rows)], dtype=float)
        for chain, rows in ca.items()
    }
    return sequences, coordinates


def matching_chains(sequences, target, binder=None):
    target_chains = [chain for chain, seq in sequences.items() if seq == target]
    require(
        len(target_chains) == 1 and len(sequences) == 2,
        "Complex must contain one unchanged target and one binder",
    )
    target_chain = target_chains[0]
    binder_chain = next(chain for chain in sequences if chain != target_chain)
    sequence = sequences[binder_chain]
    require(
        len(sequence) == 60 and set(sequence) <= set(AA3.values()),
        "Binder must contain 60 standard amino acids",
    )
    if binder is not None:
        require(
            sequence == binder,
            "Predicted/designed binder sequence does not match FASTA",
        )
    return target_chain, binder_chain


def rfdiffusion_trajectory(path):
    """Read the pinned writer's ENDMDL-delimited frames without executing TRB data."""
    path = Path(path)
    require(path.stat().st_size <= 32 * 1024 * 1024, "RF trajectory exceeds bounded size")
    frames, atoms, residues, ca = [], set(), {}, {}
    model_open = False
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("MODEL"):
                require(not atoms and not model_open, "Nested RF trajectory MODEL")
                model_open = True
            elif line.startswith("ENDMDL"):
                require(atoms, "Empty RF trajectory frame")
                require(len(frames) < 50, "More than 50 RF trajectory frames")
                require(
                    all(set(ca.get(chain, {})) == set(rows) for chain, rows in residues.items()),
                    "Missing CA in RF trajectory frame",
                )
                sequences = {
                    chain: "".join(AA3[rows[key]] for key in sorted(rows))
                    for chain, rows in residues.items()
                }
                coordinates = {
                    chain: np.array([rows[key] for key in sorted(rows)], dtype=float)
                    for chain, rows in ca.items()
                }
                frames.append((sequences, coordinates))
                atoms, residues, ca = set(), {}, {}
                model_open = False
            elif line.startswith("ATOM  "):
                require(len(line) >= 54 and line[16] == " ", "Malformed RF trajectory atom")
                chain = line[21]
                residue = (int(line[22:26]), line[26])
                component, atom = line[17:20], line[12:16].strip()
                key = (chain, residue, atom)
                require(key not in atoms, "Duplicate atom in RF trajectory frame")
                atoms.add(key)
                require(len(atoms) <= 202 * 27, "Oversized RF trajectory frame")
                require(component in AA3, "Nonstandard residue in RF trajectory")
                xyz = tuple(float(line[index:index + 8]) for index in (30, 38, 46))
                require(all(math.isfinite(value) for value in xyz), "Nonfinite RF trajectory coordinate")
                previous = residues.setdefault(chain, {}).setdefault(residue, component)
                require(previous == component, "Conflicting RF trajectory residue identity")
                if atom == "CA":
                    ca.setdefault(chain, {})[residue] = xyz
    require(not atoms and not model_open, "Unterminated RF trajectory frame")
    require(len(frames) == 50, f"Expected 50 RF trajectory frames, found {len(frames)}")
    return frames


def pair_distance_delta(original, actual):
    return float(np.max(np.abs(
        np.linalg.norm(original[:, None] - original[None, :], axis=-1)
        - np.linalg.norm(actual[:, None] - actual[None, :], axis=-1)
    )))


def aligned_ca_geometry(original, actual):
    """Report proper rigid-superposition diagnostics, without an empirical quality gate."""
    reference = original - original.mean(axis=0)
    moving = actual - actual.mean(axis=0)
    u, _, vt = np.linalg.svd(moving.T @ reference)
    correction = np.diag([1.0, 1.0, np.sign(np.linalg.det(u @ vt))])
    rotation = u @ correction @ vt
    displacement = np.linalg.norm(moving @ rotation - reference, axis=1)
    require(np.isclose(np.linalg.det(rotation), 1.0), "Improper target alignment rotation")
    return {
        "aligned_ca_rmsd_angstrom": float(np.sqrt(np.mean(displacement ** 2))),
        "max_aligned_ca_displacement_angstrom": float(displacement.max()),
        "pair_distance_max_delta_angstrom": pair_distance_delta(original, actual),
        "rotation_determinant": float(np.linalg.det(rotation)),
        "scope": "Final upstream model prediction; diagnostic only, not a calibrated quality gate",
    }


def verify_rfdiffusion_trajectory(xt_path, px0_path, original, sequences, coordinates, target_chain):
    """Check the actual invariant in pinned RFdiffusion's self-conditioning sampler.

    Commit2d0c003: model_runners.py881-896 restores the motif only before the
    final step, then clones px0; run_inference.py101-114 reverses both stacks.
    Therefore frame0 is t1, and frames1..49 are the rigid-target t2..50 inputs.
    Each 3-decimal PDB pair distance rounds by at most sqrt(3)*0.001A;
    comparison of two rounded files doubles that bound. Add 1e-6A for
    numerical comparison, not an empirical structural allowance.
    """
    xt = rfdiffusion_trajectory(xt_path)
    px0 = rfdiffusion_trajectory(px0_path)
    for name, frames in (("Xt-1", xt), ("pX0", px0)):
        for index, (frame_sequences, frame_coordinates) in enumerate(frames):
            require(frame_sequences == sequences, f"{name} frame{index} changed sequence/chain mapping")
            require(
                all(frame_coordinates[chain].shape == coordinates[chain].shape for chain in sequences),
                f"{name} frame{index} changed coordinate membership",
            )
        require(
            all(np.array_equal(frames[0][1][chain], coordinates[chain]) for chain in sequences),
            f"Final RF backbone does not equal {name} frame0",
        )
    deltas = [pair_distance_delta(original, frame[1][target_chain]) for frame in xt[1:]]
    quantization_bound = 2 * math.sqrt(3) * 0.001 + 1e-6
    require(max(deltas) <= quantization_bound, f"Nonfinal RF target geometry changed beyond PDB quantization: {max(deltas)} A")
    return {
        "frames_per_trajectory": 50,
        "nonfinal_rigid_frames": 49,
        "frame_order": "t1 first; t50 last, after upstream stack reversal",
        "nonfinal_target_pair_delta_max_angstrom": max(deltas),
        "nonfinal_pair_delta_limit_angstrom": quantization_bound,
        "final_rf_equals_xt_and_px0_frame0": True,
        "xt_sha256": sha(xt_path),
        "px0_sha256": sha(px0_path),
        "final_target_geometry": aligned_ca_geometry(original, coordinates[target_chain]),
    }


def npz_array(path, key):
    with np.load(path, allow_pickle=False) as data:
        require(key in data.files, f"Missing {key} array in {path}; keys={data.files}")
        array = np.asarray(data[key])
        require(np.issubdtype(array.dtype, np.number), f"Nonnumeric {key} array")
        require(bool(np.isfinite(array).all()), f"Nonfinite {key} values")
        return array.copy()


def argument(argv, option, default=None):
    if option in argv:
        index = argv.index(option)
        require(index + 1 < len(argv), f"Missing value for {option}")
        return argv[index + 1]
    return default


def finite_json_numbers(value):
    if isinstance(value, dict):
        for child in value.values():
            finite_json_numbers(child)
    elif isinstance(value, list):
        for child in value:
            finite_json_numbers(child)
    elif isinstance(value, float):
        require(math.isfinite(value), "Nonfinite number in raw confidence JSON")


def verify(args):
    root = args.results.resolve()
    evidence, raw = root / "evidence", root / "evidence/raw"
    report = {
        "schema": "bindsight-real-gpu-smoke-verification/1",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "results": str(root),
        "status": "incomplete",
        "checks": [],
        "summary": {},
        "limits": [
            "Software/GPU execution check only; no biological binding or numerical-equivalence claim.",
            "TRB files are hashed and never deserialized.",
            "A 142+60-residue run does not establish capacity for larger targets or other GPUs.",
        ],
    }

    def check(name, fn):
        try:
            detail = fn()
        except (Incomplete, FileNotFoundError) as exc:
            item = {"name": name, "status": "incomplete", "detail": str(exc)}
        except Exception as exc:
            item = {
                "name": name,
                "status": "failed",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        else:
            item = {"name": name, "status": "passed", "detail": detail}
        report["checks"].append(item)
        return item["status"] == "passed"

    state = {}

    def protocol():
        require(sha(args.expected_spec) == SPEC_SHA, "Expected spec differs from frozen original input")
        expected = read_json(args.expected_spec)
        actual = read_json(evidence / "spec.json")
        for key in (
            "target_uniprot",
            "epitope_chain",
            "epitope_residues",
            "design_ranges",
            "binder_length_min",
            "binder_length_max",
            "n_trajectories",
            "seed",
        ):
            require(actual.get(key) == expected[key], f"Spec changed: {key}")
        for key in (
            "designer",
            "validator",
            "mode",
            "diffusion_samples",
            "max_parallel_samples",
        ):
            require(
                actual["extra_params"].get(key) == expected["extra_params"][key],
                f"Protocol changed: {key}",
            )
        require(
            sha(args.expected_target) == TARGET_SHA,
            "Expected target is not the frozen published fixture",
        )
        require(
            sha(raw / "target.pdb") == TARGET_SHA,
            "Executed target bytes differ from frozen fixture",
        )
        sequences, coords = structure(args.expected_target)
        require(
            set(sequences) == {"A"} and len(sequences["A"]) == 142,
            "Expected 142-residue chain A",
        )
        state.update(target=sequences["A"], target_ca=coords["A"])
        return {
            "seed": 42,
            "spec_sha256": SPEC_SHA,
            "target_sha256": TARGET_SHA,
            "target_residues": 142,
            "binder_residues": 60,
            "trajectories": 1,
            "designs": 2,
            "diffusion_samples": 1,
        }

    protocol_ok = check("frozen_protocol_and_target", protocol)

    def integrity():
        manifest = read_json(evidence / "manifest.json")
        require(
            manifest.get("status") == "completed", "Executor did not record completion"
        )
        if manifest.get("skipped"):
            raise Incomplete(f"Raw evidence was skipped: {manifest['skipped']}")
        for row in manifest["files"]:
            file = raw / row["path"]
            require(
                file.resolve().is_relative_to(raw.resolve()) and not file.is_symlink(),
                "Evidence path escapes raw directory",
            )
            require(
                sha(file) == row["sha256"] and file.stat().st_size == row["bytes"],
                f"Evidence hash/size mismatch: {row['path']}",
            )
        return {
            "verified_raw_files": len(manifest["files"]),
            "manifest_sha256": sha(evidence / "manifest.json"),
        }

    check("transported_evidence_integrity", integrity)

    def runtime():
        receipt = read_json(args.runtime_receipt)
        identity = receipt.get("source_identity", {})
        if not identity or "sha256" not in identity:
            raise Incomplete("Runtime receipt lacks source wheel identity")
        require(
            identity.get("kind") == "wheel", "Expected exact installed source wheel"
        )
        require(
            identity["sha256"] == sha(args.candidate_wheel),
            "Runtime source wheel hash differs",
        )
        require(
            identity["bytes"] == args.candidate_wheel.stat().st_size,
            "Runtime source wheel size differs",
        )
        provenance = read_json(evidence / "provenance.json")
        with zipfile.ZipFile(args.candidate_wheel) as wheel:
            for module, field in (
                ("job_exec.py", "executor_sha256"),
                ("tools.py", "tool_commands_sha256"),
            ):
                require(
                    hashlib.sha256(
                        wheel.read("bindsight/runners/" + module)
                    ).hexdigest()
                    == provenance.get(field),
                    f"Actually executed {module} differs from candidate wheel",
                )
            metadata_names = [
                name
                for name in wheel.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            require(len(metadata_names) == 1, "Ambiguous candidate wheel metadata")
            metadata = BytesParser().parsebytes(wheel.read(metadata_names[0]))
            require(
                metadata["Name"] == "bindsight"
                and metadata["Version"] == provenance.get("bindsight_version"),
                "Actual Bindsight version differs from candidate wheel",
            )
        checks = receipt.get("checks", {})
        for environment in ("se3", "boltz"):
            observed = checks.get(environment)
            if not observed:
                raise Incomplete(f"Missing {environment} runtime checks")
            for key in (
                "python",
                "executable",
                "torch",
                "cuda",
                "cuda_tested",
                "device",
                "capability",
            ):
                if observed.get(key) is None:
                    raise Incomplete(f"Missing observed {environment}.{key}")
            require(
                observed["python"] == "3.11.18"
                and observed["torch"] == "2.14.1+cu126"
                and observed["cuda"] == "12.6",
                f"Runtime versions differ from frozen recipe in {environment}",
            )
            require(
                observed["cuda_tested"] is True, f"{environment} never executed CUDA"
            )
            require(
                tuple(observed["capability"]) >= (7, 5),
                f"Unsupported GPU in {environment}",
            )
        require(
            checks["se3"].get("dgl_cuda_tested") is True,
            "Design DGL did not execute a CUDA graph operation",
        )
        require(
            checks["se3"].get("dgl") == "1.0.2+cu118"
            and checks["se3"].get("numpy") == "1.23.5"
            and checks["boltz"].get("numpy") == "1.26.4"
            and checks["boltz"].get("trifast") == "0.1.11",
            "Scientific library versions differ from frozen recipe",
        )
        require(
            checks["boltz"].get("boltz") == BOLTZ_RUNTIME_VERSION,
            "Unexpected actual Boltz version",
        )
        require(
            checks["boltz"].get("checkpoint_loader_checked") is True,
            "Actual checkpoint loader source/descriptor preflight is missing",
        )
        patch_proof = verify_boltz_patch(
            receipt.get("boltz_runtime_wheel"),
            args.boltz_upstream_wheel,
            args.boltz_runtime_wheel,
        )
        asset_receipt = receipt.get("boltz_assets")
        if not asset_receipt:
            raise Incomplete("Missing authenticated publisher Boltz assets receipt")
        require(
            asset_receipt.get("schema") == "bindsight-boltz-assets/1",
            "Unknown Boltz asset receipt schema",
        )
        require(
            asset_receipt.get("publisher_revision") == BOLTZ_PUBLISHER_REVISION,
            "Unexpected model publisher revision",
        )
        for name, pin in BOLTZ_ASSETS.items():
            row = asset_receipt.get("assets", {}).get(name)
            if not row:
                raise Incomplete(f"Missing authenticated publisher asset: {name}")
            require(
                row.get("sha256") == pin["sha256"]
                and row.get("bytes") == pin["bytes"]
                and row.get("pin_match") is True,
                f"Publisher asset identity differs: {name}",
            )
            require(
                row.get("url")
                == f"https://huggingface.co/boltz-community/boltz-2/resolve/{BOLTZ_PUBLISHER_REVISION}/{name}",
                f"Unreviewed asset source: {name}",
            )
        molecules = asset_receipt.get("molecules", {})
        require(
            molecules.get("verified_against_authenticated_archive") is True,
            "Extracted CCD cache not authenticated",
        )
        require(
            molecules.get("files", 0) >= 21
            and molecules.get("bytes", 0) > 0
            and re.fullmatch("[0-9a-f]{64}", molecules.get("inventory_sha256", "")),
            "Missing valid extracted CCD inventory",
        )
        loaded_curand = checks["se3"].get("loaded_curand_sha256")
        if not loaded_curand:
            raise Incomplete("Missing actual loaded cuRAND library identity")
        require(
            all(value == CURAND_CUDA12_SHA for value in loaded_curand.values()),
            "Design process loaded unreviewed cuRAND bytes",
        )
        text = args.hardware_log.read_text(errors="replace")
        require(bool(text.strip()), "Empty hardware log")
        for name in {checks["se3"]["device"], checks["boltz"]["device"]}:
            require(
                name in text or name.removeprefix("Tesla ") in text,
                f"Hardware log does not identify {name}",
            )
        state["runtime"] = receipt
        return {
            "source_wheel_sha256": identity["sha256"],
            "checks": checks,
            "hardware_log_sha256": sha(args.hardware_log),
            "boltz_patch_proof": patch_proof,
            "boltz_assets": asset_receipt,
            "loaded_curand_sha256": loaded_curand,
        }

    runtime_ok = check("actual_supported_cuda_runtime", runtime)

    def weights():
        rows = read_json(evidence / "weights.json")
        observed = {row["name"]: row for row in rows}
        for name, expected in RF_WEIGHTS.items():
            if name not in observed:
                raise Incomplete(f"Missing executed RF checkpoint receipt: {name}")
            require(
                observed[name]["sha256"] == expected, f"RF checkpoint mismatch: {name}"
            )
            require(
                observed[name]["expected_sha256"] == expected
                and observed[name]["pin_match"] is True,
                f"RF checkpoint was not checked against expected bytes: {name}",
            )
        if args.weights_receipt is None:
            raise Incomplete(
                "Missing post-run ProteinMPNN/Boltz/auxiliary weight receipt (--weights-receipt)"
            )
        document = read_json(args.weights_receipt)
        model_rows = (
            document
            if isinstance(document, list)
            else document.get("model_weights", [])
        )
        for name, pin in BOLTZ_ASSETS.items():
            matching = [
                row for row in model_rows if Path(row.get("name", "")).name == name
            ]
            if len(matching) != 1:
                raise Incomplete(
                    f"Missing unique post-run publisher asset identity: {name}"
                )
            require(
                matching[0].get("sha256") == pin["sha256"]
                and matching[0].get("bytes") == pin["bytes"],
                f"Post-run publisher asset changed: {name}",
            )
        for role in ("proteinmpnn", "boltz"):
            selected = [row for row in model_rows if row.get("role") == role]
            if not selected:
                raise Incomplete(f"Missing {role} weight identity")
            for row in selected:
                require(
                    bool(re.fullmatch("[0-9a-f]{64}", row.get("sha256", "")))
                    and row.get("bytes", 0) > 0,
                    f"Invalid {role} weight receipt",
                )
        for role, name in (
            ("proteinmpnn", "v_48_020.pt"),
            ("boltz", "boltz2_conf.ckpt"),
        ):
            selected = [
                row
                for row in model_rows
                if row.get("role") == role
                and Path(row.get("name", "")).name == name
                and row.get("used") is True
            ]
            if len(selected) != 1:
                raise Incomplete(
                    f"Expected one observed-used checkpoint receipt for {name}"
                )
        require(
            not any(
                Path(row.get("name", "")).name == "boltz2_aff.ckpt"
                and row.get("used") is True
                for row in model_rows
            ),
            "Ligand affinity checkpoint unexpectedly used",
        )
        canonical_names = {name + ".pkl" for name in (*AA3.keys(), "UNK")}
        canonical_receipts = {
            Path(row.get("name", "")).name
            for row in model_rows
            if row.get("role") == "auxiliary"
            and row.get("used") is True
            and row.get("bytes", 0) > 0
            and re.fullmatch("[0-9a-f]{64}", row.get("sha256", ""))
        }
        if not canonical_names <= canonical_receipts:
            raise Incomplete(
                f"Missing loaded Boltz canonical CCD hashes: {sorted(canonical_names - canonical_receipts)}"
            )
        runtime_receipt = read_json(args.runtime_receipt)
        canonical_pins = (
            runtime_receipt.get("boltz_assets", {})
            .get("molecules", {})
            .get("canonical_files", {})
        )
        for name in sorted(canonical_names):
            if name not in canonical_pins:
                raise Incomplete(f"Missing authenticated CCD member identity: {name}")
            matching = [
                row for row in model_rows if Path(row.get("name", "")).name == name
            ]
            require(len(matching) == 1, f"Ambiguous CCD identity: {name}")
            require(
                all(
                    matching[0].get(key) == canonical_pins[name].get(key)
                    for key in ("bytes", "sha256")
                ),
                f"Post-run CCD member differs from publisher archive: {name}",
            )
        return {
            "rfdiffusion": observed,
            "additional_model_weights": model_rows,
            "note": "Supplemental hashes identify recorded model files; used/present semantics remain those of the runtime receipt.",
        }

    check("model_weight_identity", weights)

    def commands():
        if not runtime_ok:
            raise Incomplete("Runtime receipt must pass before command/precision verification")
        paths = sorted((evidence / "commands").glob("*.json"))
        if not paths:
            raise Incomplete("No actual subprocess receipts")
        rows = [read_json(path) for path in paths]
        # Setup probes may fail before an actionable error; inference commands must succeed.
        rfdiff = [
            row
            for row in rows
            if any(str(arg).endswith("run_inference.py") for arg in row["argv"])
        ]
        mpnn = [
            row
            for row in rows
            if any(str(arg).endswith("protein_mpnn_run.py") for arg in row["argv"])
        ]
        boltz = [
            row
            for row in rows
            if "bindsight.runners.boltz_compat" in row["argv"]
            and "predict" in row["argv"]
        ]
        require(
            len(rfdiff) == 1 and len(mpnn) == 1 and len(boltz) == 2,
            "Expected one RFdiffusion, one MPNN, two Boltz executions",
        )
        preflight = [
            row for row in rows if "design runtime" in row["stdout"].get("text", "")
        ]
        if not preflight:
            raise Incomplete(
                "Missing successful selected design-interpreter preflight output"
            )
        if runtime_ok:
            receipt = state["runtime"]
            selected_design = receipt.get("design_python")
            selected_boltz = receipt.get("boltz_python")
            if not selected_design or not selected_boltz:
                raise Incomplete(
                    "Runtime receipt lacks selected design/validation interpreter paths"
                )
            require(
                all(
                    row["argv"][0] == selected_design
                    for row in rfdiff + mpnn + preflight
                ),
                "Design commands used a different interpreter than the observed CUDA runtime",
            )
            require(
                all(row["argv"][0] == selected_boltz for row in boltz),
                "Boltz commands used a different interpreter than the observed CUDA runtime",
            )
            observed = receipt["checks"]["se3"]
            text = preflight[-1]["stdout"]["text"]
            require(
                f"design runtime {observed['python']}" in text
                and f"torch {observed['torch']}" in text
                and f"dgl {observed['dgl']}" in text,
                "Selected interpreter metadata differs from the independent runtime receipt",
            )
        for row in rfdiff + mpnn + boltz:
            require(
                row["outcome"] == "ok" and row["returncode"] == 0,
                "Model command did not succeed",
            )
            if row["stdout"].get("truncated") or row["stderr"].get("truncated"):
                raise Incomplete("A model command log was truncated")
        argv = rfdiff[0]["argv"]
        for option in (
            "inference.deterministic=True",
            "inference.design_startnum=42",
            "inference.num_designs=1",
            "contigmap.contigs=[A511-652/0 60-60]",
        ):
            require(option in argv, f"RFdiffusion protocol missing {option}")
        for option, expected in (
            ("--seed", "42"),
            ("--num_seq_per_target", "2"),
            ("--sampling_temp", "0.1"),
        ):
            require(
                argument(mpnn[0]["argv"], option) == expected,
                f"ProteinMPNN protocol mismatch {option}",
            )
        state["mpnn_designed_chain"] = argument(mpnn[0]["argv"], "--pdb_path_chains")
        for identifier in IDS:
            matches = [
                row
                for row in boltz
                if any(
                    Path(str(arg)).name == identifier + ".yaml" for arg in row["argv"]
                )
            ]
            require(len(matches) == 1, f"Missing actual Boltz command for {identifier}")
            row = matches[0]
            seed = int.from_bytes(
                hashlib.sha256(f"42:{identifier}".encode()).digest()[:4], "big"
            )
            require(
                argument(row["argv"], "--seed") == str(seed),
                f"Boltz seed mismatch for {identifier}",
            )
            require(
                argument(row["argv"], "--diffusion_samples", "1") == "1",
                "Changed Boltz draw count",
            )
            precision = (
                "bf16-mixed"
                if runtime_ok
                and tuple(state["runtime"]["checks"]["boltz"]["capability"]) >= (8, 0)
                else "32"
            )
            observed_precision = re.search(
                r"Boltz 2\.0\.3\+bindsight\.1 precision=(32|bf16-mixed)\b",
                row["stdout"]["text"],
            )
            if observed_precision is None:
                raise Incomplete("Actual Boltz precision receipt is missing")
            if runtime_ok:
                require(
                    observed_precision.group(1) == precision,
                    "Boltz precision disagrees with observed GPU capability",
                )
        return {
            "recorded_commands": len(rows),
            "model_commands": 4,
            "design_preflight": [
                row for row in rows if "design runtime" in row["stdout"].get("text", "")
            ],
        }

    commands_ok = check("observed_model_protocol_and_precision", commands)

    def backbone():
        if not protocol_ok:
            raise Incomplete(
                "Frozen input checks must pass before backbone verification"
            )
        pdb = one(raw / "rfdiff_out", "binder_42.pdb")
        require(
            len(list((raw / "rfdiff_out").glob("binder_*.pdb"))) == 1,
            "Expected exactly one final RFdiffusion backbone",
        )
        trb = one(raw / "rfdiff_out", "*.trb")
        sequences, coordinates = structure(pdb)
        target_chain, binder_chain = matching_chains(sequences, state["target"])
        require(
            sequences[binder_chain] == "G" * 60,
            "Expected unsequenced poly-glycine RF backbone",
        )
        original = state["target_ca"]
        actual = coordinates[target_chain]
        trajectory = verify_rfdiffusion_trajectory(
            one(raw / "rfdiff_out", "binder_42_Xt-1_traj.pdb"),
            one(raw / "rfdiff_out", "binder_42_pX0_traj.pdb"),
            original, sequences, coordinates, target_chain,
        )
        if commands_ok:
            require(
                state["mpnn_designed_chain"] == binder_chain,
                "ProteinMPNN was not restricted to the binder chain",
            )
        state.update(
            backbone_coordinates=coordinates,
            target_chain=target_chain,
            binder_chain=binder_chain,
        )
        return {
            "target_chain": target_chain,
            "binder_chain": binder_chain,
            "target_pair_distance_max_delta_angstrom": pair_distance_delta(original, actual),
            "trajectory": trajectory,
            "pdb_sha256": sha(pdb),
            "trb_sha256": sha(trb),
            "trb_inspection": "hashed only; not unpickled",
        }

    backbone_ok = check("rfdiffusion_target_and_chain_mapping", backbone)

    def designs():
        if not backbone_ok:
            raise Incomplete("Backbone checks must pass before sequence verification")
        raw_fasta = one(raw / "mpnn_out", "*.fa")
        records = fasta(raw_fasta)
        require(
            len(records) == 3,
            "ProteinMPNN must retain native plus two generated records",
        )
        sequences = [row[1].split("/") for row in records[1:]]
        native = records[0][1].split("/")
        require(
            native == ["G" * 60],
            "Native ProteinMPNN FASTA must contain the designed binder chain only",
        )
        header = records[0][0]
        for label, chain in (
            ("fixed_chains", state["target_chain"]),
            ("designed_chains", state["binder_chain"]),
        ):
            require(
                bool(re.search(rf"{label}=\[['\"]{re.escape(chain)}['\"]\]", header)),
                f"ProteinMPNN header does not confirm {label}",
            )
        require(
            bool(re.search(r"\bmodel_name=v_48_020(?:,|$)", header))
            and bool(re.search(r"\bseed=42(?:,|$)", header)),
            "ProteinMPNN model/seed receipt differs",
        )
        designed = {}
        for index, identifier in enumerate(IDS):
            require(
                len(sequences[index]) == 1,
                "ProteinMPNN must emit only the one designed chain",
            )
            sequence = sequences[index][-1]
            local = fasta(root / "design" / (identifier + ".fasta"))
            require(
                len(local) == 1 and local[0][1] == sequence,
                "Exported FASTA differs from raw ProteinMPNN sample",
            )
            chains, coords = structure(root / "design" / (identifier + ".pdb"))
            target_chain, binder_chain = matching_chains(
                chains, state["target"], sequence
            )
            require(
                np.array_equal(
                    coords[target_chain],
                    state["backbone_coordinates"][state["target_chain"]],
                ),
                "ProteinMPNN export moved fixed target coordinates",
            )
            require(
                np.array_equal(
                    coords[binder_chain],
                    state["backbone_coordinates"][state["binder_chain"]],
                ),
                "Designed backbone differs from RFdiffusion backbone",
            )
            designed[identifier] = sequence
        state["designs"] = designed
        return {
            "n_designs": len(designed),
            "sequence_sha256": {
                name: hashlib.sha256(seq.encode()).hexdigest()
                for name, seq in designed.items()
            },
        }

    designs_ok = check("proteinmpnn_sequences_and_fixed_context", designs)

    def predictions():
        if not designs_ok:
            raise Incomplete("Design checks must pass before prediction verification")
        rows = [
            json.loads(line)
            for line in (root / "metrics.jsonl").read_text().splitlines()
            if line.strip()
        ]
        require(
            len(rows) == 2 and {row["binder_id"] for row in rows} == set(IDS),
            "Missing or duplicate metric design IDs",
        )
        measurements = {}
        for identifier, sequence in state["designs"].items():
            row = next(row for row in rows if row["binder_id"] == identifier)
            finite_json_numbers(row)
            require(
                row["validator_name"] == "boltz2"
                and row["validator_version"] == BOLTZ_RUNTIME_VERSION,
                "Metrics report wrong/unrecorded validator",
            )
            require(row.get("iptm_n_samples") == 1, "Metric sample count differs")
            require(
                row.get("affinity_pred_value") is None
                and row.get("affinity_probability_binary") is None,
                "Ligand affinity unexpectedly reported for protein binder",
            )
            input_yaml = yaml.safe_load(
                (raw / "boltz_out" / (identifier + ".yaml")).read_text()
            )
            proteins = [item["protein"] for item in input_yaml["sequences"]]
            require(
                [(p["id"], p["sequence"]) for p in proteins]
                == [("T", state["target"]), ("B", sequence)],
                "Boltz input chain sequence/order changed",
            )
            require(
                not input_yaml.get("properties"),
                "Boltz protein input requests ligand affinity",
            )
            if not all(p.get("msa") == "empty" for p in proteins):
                msa = [
                    p
                    for p in (raw / "boltz_out" / identifier).rglob("*")
                    if p.is_file()
                    and {"msa", "msas"} & set(p.parts)
                    and p.suffix in {".a3m", ".csv", ".npz", ".fa", ".fasta"}
                    and p.stat().st_size
                ]
                if not msa:
                    raise Incomplete(
                        f"No retained MSA for {identifier}; input did not explicitly select empty MSA"
                    )
            output = root / "validate" / identifier
            confidence = read_json(one(output, "confidence_*.json"))
            finite_json_numbers(confidence)
            iptm = float(confidence["iptm"])
            require(math.isfinite(iptm) and 0 <= iptm <= 1, "Invalid ipTM")
            require(
                math.isclose(float(row["iptm"]), iptm, rel_tol=1e-7, abs_tol=1e-7),
                "Reported ipTM differs from raw model output",
            )
            complexes = list(output.rglob("*_model_0.cif")) + list(
                output.rglob("*_model_0.pdb")
            )
            if not complexes:
                raise Incomplete(f"Missing actual predicted complex for {identifier}")
            require(len(complexes) == 1, "Ambiguous predicted complexes")
            chains, _ = structure(complexes[0])
            target_chain, binder_chain = matching_chains(chains, state["target"], sequence)
            require(
                list(chains) == [target_chain, binder_chain],
                "Predicted structure order is not target then binder",
            )
            processed_record = read_json(
                one(raw / "boltz_out" / identifier, f"processed/records/{identifier}.json")
            )
            require(
                [(c["chain_id"], c["chain_name"], c["num_residues"], c["valid"])
                 for c in processed_record["chains"]]
                == [(0, "T", 142, True), (1, "B", 60, True)],
                "Processed Boltz chain/token order differs from target then binder",
            )
            split = len(chains[target_chain])
            binder_count = len(chains[binder_chain])
            pae = npz_array(one(output, "pae_*.npz"), "pae")
            require(
                pae.shape == (202, 202) and bool(((pae >= 0) & (pae <= 32)).all()),
                "Invalid PAE shape/range",
            )
            interface = float(
                (
                    np.sum(pae[:split, split:], dtype=np.float64)
                    + np.sum(pae[split:, :split], dtype=np.float64)
                )
                / (2 * split * binder_count)
            )
            require(
                math.isfinite(float(row["pae_interaction"]))
                and math.isclose(
                    float(row["pae_interaction"]), interface, rel_tol=1e-6, abs_tol=1e-6
                ),
                "Reported interface PAE differs from independent off-diagonal calculation",
            )
            plddt = npz_array(one(output, "plddt_*.npz"), "plddt")
            require(
                plddt.size == 202 and bool(((plddt >= 0) & (plddt <= 1)).all()),
                "Invalid per-residue confidence shape/range",
            )
            measurements[identifier] = {
                "iptm": iptm,
                "independent_pae_interaction": interface,
                "plddt_shape": list(plddt.shape),
                "plddt_min": float(plddt.min()),
                "plddt_max": float(plddt.max()),
                "complex_sha256": sha(complexes[0]),
                "processed_token_chain_order": ["T:142", "B:60"],
                "observed_structure_chain_order": list(chains),
            }
        report["summary"]["predictions"] = measurements
        return measurements

    check("actual_boltz_complexes_and_finite_metrics", predictions)
    statuses = {row["status"] for row in report["checks"]}
    report["status"] = (
        "failed"
        if "failed" in statuses
        else "incomplete"
        if "incomplete" in statuses
        else "passed"
    )
    report["summary"].update(
        passed=sum(row["status"] == "passed" for row in report["checks"]),
        failed=sum(row["status"] == "failed" for row in report["checks"]),
        incomplete=sum(row["status"] == "incomplete" for row in report["checks"]),
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--runtime-receipt", type=Path, required=True)
    parser.add_argument(
        "--boltz-upstream-wheel",
        type=Path,
        default=HERE / "boltz-source/boltz-2.0.3-py3-none-any.whl",
    )
    parser.add_argument(
        "--boltz-runtime-wheel",
        type=Path,
        default=HERE / "boltz-source/boltz-2.0.3+bindsight.1-py3-none-any.whl",
    )
    parser.add_argument("--hardware-log", type=Path, required=True)
    parser.add_argument("--candidate-wheel", type=Path, required=True)
    parser.add_argument("--weights-receipt", type=Path)
    parser.add_argument("--expected-spec", type=Path, default=HERE / "smoke-spec.json")
    parser.add_argument("--expected-target", type=Path, default=HERE / "target.pdb")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "summary": report["summary"],
                "checks": [
                    {"name": row["name"], "status": row["status"]}
                    for row in report["checks"]
                ],
            },
            indent=2,
        )
    )
    return {"passed": 0, "failed": 1, "incomplete": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
