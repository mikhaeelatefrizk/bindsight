# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared isolated provisioning for local, Kaggle, Colab and Modal GPU jobs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

import requests

from bindsight.runners import gpu_recipe as pins
from bindsight.runners import tools
from bindsight.runners.boltz_assets import prepare_boltz_assets
from bindsight.runners.boltz_runtime_wheel import prepare_boltz_runtime_wheel
from bindsight.runners.installer_security import (
    CERTIFI_REQUIREMENT,
    MICROMAMBA_SHA256,
    MICROMAMBA_URL,
    download_verified_uv,
    package_environment,
    uv_install_command,
)

LOG = logging.getLogger(__name__)


def write_json(path: Path, value: Any) -> None:
    """Atomically retain public runtime evidence without importing web components."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def _implementation_digest(files: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(files):
        digest.update(name.encode() + b"\0")
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def current_implementation_sha256() -> str:
    """Identify running package code without including documentation or cache files."""
    package = Path(__file__).resolve().parents[1]
    return _implementation_digest(
        [
            (path.relative_to(package.parent).as_posix(), path.read_bytes())
            for path in package.rglob("*.py")
            if "__pycache__" not in path.parts and not path.is_symlink()
        ]
    )


def source_identity(source: Path) -> dict[str, Any]:
    """Identify actual wheel bytes or the runnable project files, never a version alone."""
    source = source.resolve(strict=True)
    if source.is_file() and source.suffix == ".whl":
        with zipfile.ZipFile(source) as wheel:
            names = [
                name
                for name in wheel.namelist()
                if name.startswith("bindsight/") and name.endswith(".py")
            ]
            if len(names) != len(set(names)) or "bindsight/__init__.py" not in names:
                raise ValueError("The source wheel has invalid Bindsight implementation entries")
            implementation = _implementation_digest([(name, wheel.read(name)) for name in names])
        return {
            "kind": "wheel",
            "filename": source.name,
            "bytes": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "implementation_sha256": implementation,
        }
    if not source.is_dir() or not (source / "pyproject.toml").is_file():
        raise ValueError("--source must identify an actual Bindsight wheel or project directory")
    files = [source / "pyproject.toml"]
    files.extend(
        path
        for path in (source / "bindsight").rglob("*.py")
        if path.is_file() and "__pycache__" not in path.parts
    )
    if not (source / "bindsight/__init__.py").is_file():
        raise ValueError("The source project does not contain the Bindsight package")
    digest = hashlib.sha256()
    for path in sorted(files):
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("The source project contains a file outside its own directory")
        digest.update(path.relative_to(source).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {
        "kind": "project",
        "sha256": digest.hexdigest(),
        "files": len(files),
        "scope": "pyproject.toml and package Python implementation",
        "implementation_sha256": _implementation_digest(
            [
                (path.relative_to(source).as_posix(), path.read_bytes())
                for path in files
                if path.suffix == ".py"
            ]
        ),
    }


def source_matches_current(identity: Any) -> bool:
    """Fail closed when a ready environment was built from different package code."""
    if (
        not isinstance(identity, dict)
        or identity.get("implementation_sha256") != current_implementation_sha256()
    ):
        return False
    if identity.get("kind") == "wheel":
        digest = identity.get("sha256")
        return (
            isinstance(digest, str)
            and len(digest) == 64
            and all(c in "0123456789abcdef" for c in digest)
        )
    if identity.get("kind") == "project":
        from bindsight.runners.source_wheel import find_repo_root

        current = find_repo_root()
        return current is not None and identity == source_identity(current)
    return False


def execution_overrides(
    root: Path, gpu_index: int, mode: str = "design_and_validate"
) -> dict[str, str]:
    """Return required managed settings only; never serialize host credentials."""
    result = {
        "BINDSIGHT_LOCAL_NATIVE": "1",
        "BINDSIGHT_BOLTZ_PYTHON": str(root / "boltz/bin/python"),
        "BINDSIGHT_TOOLS_ROOT": str(root / "tools"),
        "BOLTZ_CACHE": str(root / "boltz-cache"),
        "CUDA_VISIBLE_DEVICES": str(gpu_index),
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1",
        "PYTHONNOUSERSITE": "1",
    }
    if mode == "design_and_validate":
        result["BINDSIGHT_DESIGN_PYTHON"] = str(root / "se3-python")
    return result


def execution_environment(
    root: Path, gpu_index: int, mode: str = "design_and_validate"
) -> dict[str, str]:
    """Ignore user executable overrides when launching managed scientific tools."""
    env = dict(os.environ)
    for key in (
        "BINDSIGHT_BOLTZ_BIN",
        "BINDSIGHT_LOCAL_IMAGE",
        "BINDSIGHT_DESIGN_PYTHON",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
    ):
        env.pop(key, None)
    env.update(execution_overrides(root, gpu_index, mode))
    return env


def nvidia_smi() -> str:
    """Use WSL's fixed driver location when its directory is absent from PATH."""
    located = shutil.which("nvidia-smi")
    fallback = Path("/usr/lib/wsl/lib/nvidia-smi")
    return located or (
        str(fallback) if sys.platform == "linux" and fallback.is_file() else "nvidia-smi"
    )


def devices() -> list[dict[str, Any]]:
    """Read actual NVIDIA memory/capability, never infer CUDA support from a model name."""
    try:
        result = subprocess.run(
            [
                nvidia_smi(),
                "--query-gpu=index,name,memory.total,memory.free,compute_cap",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if sys.platform == "win32"
            else 0,
        )
        if result.returncode:
            return []
        found = []
        for row in csv.reader(result.stdout.splitlines()):
            if len(row) != 5:
                continue
            index, name, total, free, capability = (x.strip() for x in row)
            major, minor = (int(x) for x in capability.split("."))
            found.append(
                {
                    "index": int(index),
                    "name": name,
                    "memory_mib": int(total),
                    "free_memory_mib": int(free),
                    "compute_capability": [major, minor],
                }
            )
        return found
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def command(argv: list[str], env: dict[str, str]) -> None:
    """Stream real installation output with fixed argv and a bounded step timeout."""
    LOG.info("Running %s", shlex.join(argv))
    with subprocess.Popen(argv, env=env) as process:
        try:
            code = process.wait(timeout=3600)
        except subprocess.TimeoutExpired:
            stop_children(process)
            raise
        if code:
            raise subprocess.CalledProcessError(code, argv)


def stop_children(process: subprocess.Popen[Any]) -> None:
    """Reap a timed-out command's descendants without killing unrelated processes."""
    psutil = importlib.import_module("psutil")

    try:
        children = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        children = []
    for child in reversed(children):
        with suppress(psutil.NoSuchProcess):
            child.kill()
    process.kill()
    process.wait(timeout=30)
    psutil.wait_procs(children, timeout=10)


def download(
    url: str, destination: Path, expected: str | None, *, maximum: int, minimum: int = 1
) -> str:
    """Stream a fixed HTTPS artifact; enforce published pins where available."""
    if destination.is_file():
        with destination.open("rb") as stream:
            existing_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if minimum <= destination.stat().st_size <= maximum and (
            expected is None or existing_digest == expected
        ):
            return existing_digest
        raise RuntimeError(f"Existing {destination.name} does not match its pinned SHA256.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial")
    digest = hashlib.sha256()
    total = 0
    with requests.get(url, stream=True, timeout=(20, 90)) as response:
        response.raise_for_status()
        with temporary.open("wb") as output:
            for block in response.iter_content(1024 * 1024):
                total += len(block)
                if total > maximum:
                    raise RuntimeError(f"{destination.name} exceeds the fixed download size limit.")
                digest.update(block)
                output.write(block)
    if total < minimum or (expected is not None and digest.hexdigest() != expected):
        raise RuntimeError(f"{destination.name} is empty or does not match its pinned SHA256.")
    temporary.replace(destination)
    LOG.info(
        "Downloaded %s: %d bytes, SHA256 %s; expected pin %s",
        destination.name,
        total,
        digest.hexdigest(),
        expected or "not established",
    )
    return digest.hexdigest()


def smoke(
    root: Path, env: dict[str, str], *, require_cuda: bool = True, mode: str = "design_and_validate"
) -> dict[str, Any]:
    """Inspect actual interpreters and libraries, and run only requested CUDA checks."""
    if mode not in pins.MODES:
        raise ValueError(f"Unsupported GPU mode: {mode}")
    programs = {}
    if mode == "design_and_validate":
        programs["se3"] = (
            root / "se3-python",
            "import rfdiffusion.inference.model_runners, se3_transformer, dgl, e3nn; "
            + f"sys.path.insert(0, {str(root / 'tools/ProteinMPNN')!r}); "
            + "import protein_mpnn_utils; from pathlib import Path; "
            + "assert Path(protein_mpnn_utils.__file__).resolve() == "
            + f"Path({str(root / 'tools/ProteinMPNN/protein_mpnn_utils.py')!r}).resolve(); ",
        )
    programs["boltz"] = (
        root / "boltz/bin/python",
        "import boltz.main; from bindsight.runners.boltz_checkpoint import _verify_runtime; "
        "_verify_runtime(boltz.main, torch); ",
    )
    result = {}
    for name, (python, imports) in programs.items():
        expected_torch = pins.SE3_TORCH if name == "se3" else pins.BOLTZ_TORCH
        expected_python = pins.SE3_PYTHON if name == "se3" else pins.BOLTZ_PYTHON
        program = (
            "import json, sys, platform, torch; from importlib.metadata import version; "
            + imports
            + f"assert torch.__version__ == {expected_torch!r}, 'Unexpected torch version'; "
            + f"assert platform.python_version() == {expected_python!r}, 'Unexpected Python version'; "
            + (
                f"assert version('dgl') == {pins.SE3_DGL!r}; "
                f"assert version('numpy') == {pins.SE3_NUMPY!r}; "
                f"assert version('e3nn') == {pins.SE3_E3NN!r}; "
                if name == "se3"
                else f"assert version('boltz') == {pins.BOLTZ_RUNTIME_VERSION!r}, 'Unexpected Boltz version'; "
                f"assert version('numpy') == {pins.BOLTZ_NUMPY!r}; "
                f"assert version('trifast') == {pins.BOLTZ_TRIFAST!r}; "
            )
        )
        if require_cuda:
            program += (
                "assert torch.cuda.is_available(), 'CUDA is unavailable'; "
                "assert torch.cuda.get_device_capability(0) >= (7,5), 'Unsupported GPU'; "
                "x=torch.ones(4,device='cuda'); assert (x+1).sum().item()==8; torch.cuda.synchronize(); "
            )
            if name == "se3":
                program += (
                    "g=dgl.graph(([0],[1]),num_nodes=2,device='cuda'); "
                    "g.ndata['x']=torch.ones((2,1),device='cuda'); "
                    "g.update_all(dgl.function.copy_u('x','m'),dgl.function.sum('m','y')); "
                    "assert g.ndata['y'].sum().item()==1, 'DGL CUDA reduction failed'; "
                    "torch.cuda.synchronize(); "
                )
        program += (
            "import hashlib; "
            "curand_paths=sorted({line.split()[-1] for line in open('/proc/self/maps') "
            "if 'libcurand.so.10' in line and line.split()[-1].startswith('/')}); "
            "curand_hashes={path:hashlib.file_digest(open(path,'rb'),'sha256').hexdigest() "
            "for path in curand_paths}; "
            + (
                f"assert set(curand_hashes.values()) == {{{pins.CUDA12_CURAND_SHA256!r}}}, 'Unexpected loaded cuRAND binary'; "
                if name == "se3"
                else ""
            )
            + "print(json.dumps({'python':platform.python_version(),'executable':sys.executable,"
            "'torch':torch.__version__,'cuda':torch.version.cuda,"
            "'cuda_tested':" + repr(require_cuda) + ","
            "'dgl_cuda_tested':" + repr(require_cuda and name == "se3") + ","
            "'device':torch.cuda.get_device_name(0) if " + repr(require_cuda) + " else None,"
            "'capability':list(torch.cuda.get_device_capability(0)) if "
            + repr(require_cuda)
            + " else None,"
            "'dgl':version('dgl') if " + repr(name == "se3") + " else None,"
            "'numpy':version('numpy'),"
            "'loaded_curand_sha256':curand_hashes,"
            "'distributed_dgl_supported':False,"
            "'checkpoint_loader_checked':" + repr(name == "boltz") + ","
            "'boltz':version('boltz') if " + repr(name == "boltz") + " else None,"
            "'trifast':version('trifast') if " + repr(name == "boltz") + " else None}))"
        )
        completed = subprocess.run(
            [str(python), "-c", program],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        LOG.info("%s runtime check: %s", name, completed.stdout.strip())
        result[name] = json.loads(completed.stdout.strip().splitlines()[-1])
    return result


def patch_e3nn_constants_loader(site: Path) -> dict[str, str]:
    """Allow only slice while reading the byte-verified e3nn 0.3.3 constants."""
    module = site / "e3nn/o3/_wigner.py"
    constants = site / "e3nn/o3/constants.pt"
    original_hash = pins.E3NN_LOADER_SHA256
    constants_hash = pins.E3NN_CONSTANTS_SHA256
    original_line = b"_Jd, _W3j_flat, _W3j_indices = torch.load(os.path.join(os.path.dirname(__file__), 'constants.pt'))"
    replacement = (
        b"with torch.serialization.safe_globals([slice]):\n"
        b"    _Jd, _W3j_flat, _W3j_indices = torch.load("
        b"os.path.join(os.path.dirname(__file__), 'constants.pt'), weights_only=True)"
    )
    if any(path.is_symlink() or not path.is_file() for path in (module, constants)):
        raise RuntimeError("The audited e3nn constants or loader is missing or is a symlink")
    if hashlib.sha256(constants.read_bytes()).hexdigest() != constants_hash:
        raise RuntimeError("e3nn constants differ from the reviewed 0.3.3 wheel")
    content = module.read_bytes()
    # A retry may find our exact patch. Reconstruct and verify the original;
    # never accept an unknown installed module based on a substring alone.
    original = content.replace(replacement, original_line) if replacement in content else content
    if hashlib.sha256(original).hexdigest() != original_hash or original.count(original_line) != 1:
        raise RuntimeError("e3nn loader differs from the reviewed 0.3.3 source")
    patched = original.replace(original_line, replacement)
    module.write_bytes(patched)
    return {
        "original_sha256": original_hash,
        "patched_sha256": hashlib.sha256(patched).hexdigest(),
        "constants_sha256": constants_hash,
        "scope": "slice constructor only, during the verified local constants load",
    }


def collect_model_weights(root: Path, evidence: Path) -> dict[str, Any]:
    """Hash a bounded allowlist; distinguish cached files from successful tool use."""
    root = root.resolve(strict=True)
    commands = []
    for path in evidence.glob("attempt-*/commands/*.json"):
        if not path.is_symlink() and path.stat().st_size < 16 * 2**20:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("outcome") == "ok" and record.get("returncode") == 0:
                commands.append(record)
    mpnn_commands = [
        record
        for record in commands
        if any(str(arg).endswith("/protein_mpnn_run.py") for arg in record.get("argv", []))
        and not {
            "--ca_only",
            "--use_soluble_model",
            "--path_to_model_weights",
            "--model_name",
        }.intersection(record.get("argv", []))
    ]
    mpnn_header = any(
        "model_name=v_48_020" in path.read_text(encoding="utf-8", errors="replace")[:2048]
        for path in evidence.glob("attempt-*/raw/mpnn_out/**/seqs/*")
        if path.is_file() and not path.is_symlink() and path.stat().st_size < 2**20
    )
    boltz_used = any(
        "bindsight.runners.boltz_compat" in record.get("argv", [])
        and "predict" in record.get("argv", [])
        and "--checkpoint" not in record.get("argv", [])
        and "--model" not in record.get("argv", [])
        for record in commands
    )
    rows = []

    def add(relative: str, role: str, used: bool, basis: str) -> None:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            return
        if not path.resolve().is_relative_to(root) or any(
            parent.is_symlink() for parent in path.parents if parent.is_relative_to(root)
        ):
            raise ValueError("A model receipt path escapes the managed root")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        rows.append(
            {
                "name": path.name,
                "relative_path": relative,
                "sha256": digest,
                "bytes": path.stat().st_size,
                "role": role,
                "present": True,
                "used": used,
                "usage_evidence": basis,
            }
        )

    for name in tools.RFDIFF_WEIGHTS:
        used = any(
            any(str(arg).endswith("/run_inference.py") for arg in record.get("argv", []))
            and name
            in (record.get("stdout", {}).get("text", "") + record.get("stderr", {}).get("text", ""))
            for record in commands
        )
        add(
            "tools/RFdiffusion/models/" + name,
            "rfdiffusion",
            used,
            "successful RFdiffusion log names this checkpoint" if used else "cached presence only",
        )
    add(
        "tools/ProteinMPNN/vanilla_model_weights/v_48_020.pt",
        "proteinmpnn",
        bool(mpnn_commands and mpnn_header),
        "successful default-model command and native FASTA model_name header"
        if mpnn_commands and mpnn_header
        else "cached presence only",
    )
    add(
        "boltz-cache/boltz2_conf.ckpt",
        "boltz",
        boltz_used,
        "successful default Boltz-2 prediction command" if boltz_used else "cached presence only",
    )
    add(
        "boltz-cache/boltz2_aff.ckpt",
        "boltz",
        False,
        "downloaded by upstream; protein structure workflow does not request affinity",
    )
    add(
        "boltz-cache/mols.tar", "auxiliary", False, "download archive; extracted CCD files are used"
    )
    for name in [
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "CYS",
        "GLN",
        "GLU",
        "GLY",
        "HIS",
        "ILE",
        "LEU",
        "LYS",
        "MET",
        "PHE",
        "PRO",
        "SER",
        "THR",
        "TRP",
        "TYR",
        "VAL",
        "UNK",
    ]:
        add(
            f"boltz-cache/mols/{name}.pkl",
            "auxiliary",
            boltz_used,
            "Boltz 2.0.3 load_canonicals allowlist" if boltz_used else "cached presence only",
        )
    return {"schema": "bindsight-model-weights/1", "model_weights": rows}


def reset_owned_environment(root: Path, name: str) -> None:
    """Recreate only named private environments, retaining tools, models and receipts."""
    if name not in {"se3", "boltz", "cuda11"} or root.is_symlink():
        raise ValueError("Refusing an unrecognized environment cleanup target")
    root = root.resolve(strict=True)
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise ValueError("The runtime root must be a dedicated directory")
    target = root / name
    if target.is_symlink() or target.resolve().parent != root:
        raise ValueError("Refusing environment cleanup outside the owned runtime root")
    if target.exists():
        if not target.is_dir():
            raise ValueError("The private environment path is not a directory")
        shutil.rmtree(target)


def verify_managed_checkout(git: str, target: Path, env: dict[str, str]) -> None:
    """Reject reused scientific-source edits and injected importable files."""
    if target.is_symlink() or target.parent.is_symlink():
        raise RuntimeError("Managed scientific source must not be a symbolic link")
    dirty = subprocess.run(
        [git, "-C", str(target), "status", "--porcelain=v1", "--untracked-files=no"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    if dirty:
        raise RuntimeError(
            f"Managed source has tracked edits; preserve or move them before setup: {target}"
        )
    files = subprocess.run(
        [git, "-C", str(target), "ls-files", "-z", "--cached"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout
    tracked = set(files.split("\0")) - {""}
    for path in target.rglob("*"):
        relative = path.relative_to(target)
        if path.is_symlink():
            raise RuntimeError(f"Managed source contains an unexpected symbolic link: {relative}")
        if ".git" in relative.parts or not path.is_file():
            continue
        if relative.as_posix() in tracked:
            continue
        if "__pycache__" in relative.parts and path.suffix in {".pyc", ".pyo"}:
            path.unlink()  # Only generated bytecode, never source or model data.
            continue
        if path.suffix.lower() not in {".py", ".pyi", ".pyc", ".pyo", ".so", ".pyd", ".pth"}:
            continue
        # Setuptools may retain build/lib copies. Accept only exact tracked
        # source bytes, never arbitrary extra modules in that generated folder.
        before, marker, after = relative.as_posix().partition("build/lib/")
        original = target / (before + after)
        if (
            marker
            and (before + after) in tracked
            and original.is_file()
            and path.read_bytes() == original.read_bytes()
        ):
            continue
        raise RuntimeError(
            f"Managed source contains unexpected untracked importable code: {relative}"
        )


def provision(
    root: Path,
    *,
    source: Path,
    mode: str = "design_and_validate",
    gpu_index: int = 0,
    check_only: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Provision one recorded recipe from actual source bytes in an owned Linux root."""
    if sys.platform != "linux" or mode not in pins.MODES:
        raise RuntimeError("Managed GPU provisioning requires Linux and a supported mode.")
    if root.is_symlink():
        raise ValueError("The managed runtime root must not be a symbolic link")
    root = root.resolve()
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise ValueError("The runtime root must be a dedicated directory")
    source = source.resolve(strict=True)
    identity = source_identity(source)
    if not check_only:
        gpu = next((g for g in devices() if g["index"] == gpu_index), None)
        if (
            not gpu
            or gpu["memory_mib"] < pins.MIN_MEMORY_MIB
            or tuple(gpu["compute_capability"]) < (7, 5)
        ):
            raise RuntimeError("The selected GPU does not meet the recorded runtime requirements.")
    root.mkdir(parents=True, exist_ok=True)
    env = package_environment(execution_environment(root, gpu_index, mode), root / "uv-cache")
    env.update(
        MAMBA_ROOT_PREFIX=str(root / "mamba"),
        PIP_CONFIG_FILE=os.devnull,
        PIP_INDEX_URL="https://pypi.org/simple",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
    )
    env.pop("PIP_EXTRA_INDEX_URL", None)
    env.pop("UV_NO_PYTHON_DOWNLOADS", None)
    env.update(
        UV_PYTHON_INSTALL_DIR=str(root / "python"),
        GIT_TERMINAL_PROMPT="0",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    (root / "ready.json").unlink(missing_ok=True)

    def phase(name: str) -> None:
        LOG.info("%s", name)
        if progress:
            progress(name)

    phase("Download the pinned environment manager")
    manager = root / "micromamba"
    download(MICROMAMBA_URL, manager, MICROMAMBA_SHA256, maximum=100 * 2**20)
    manager.chmod(0o755)

    phase("Verify the independent secure package installer")
    installer = download_verified_uv(root / "uv", report=phase)

    def mamba(*args: str) -> None:
        command([str(manager), *args], env)

    def pip(environment: str, *args: str) -> None:
        command(
            uv_install_command(
                installer,
                root / environment / "bin/python",
                ["-c", str(root / (environment + ".constraints.txt")), *args],
            ),
            env,
        )

    (root / "se3.constraints.txt").write_text(
        f"torch=={pins.SE3_TORCH}\ndgl=={pins.SE3_DGL}\nnumpy=={pins.SE3_NUMPY}\ne3nn=={pins.SE3_E3NN}\n"
        + CERTIFI_REQUIREMENT
        + "\n",
        encoding="ascii",
        newline="\n",
    )
    # Preserve Boltz/NumPy/trifast while using the security-patched Torch runtime.
    (root / "boltz.constraints.txt").write_text(
        f"torch=={pins.BOLTZ_TORCH}\nboltz=={pins.BOLTZ_RUNTIME_VERSION}\nnumpy=={pins.BOLTZ_NUMPY}\ntrifast=={pins.BOLTZ_TRIFAST}\n"
        + CERTIFI_REQUIREMENT
        + "\n",
        encoding="ascii",
        newline="\n",
    )

    phase("Prepare private Python environments")
    environments = [("boltz", pins.BOLTZ_PYTHON)]
    if mode == "design_and_validate":
        environments.insert(0, ("se3", pins.SE3_PYTHON))
    for name, version in environments:
        reset_owned_environment(root, name)
        command([str(installer), "--no-config", "python", "install", version, "--no-bin"], env)
        command(
            [
                str(installer),
                "--no-config",
                "venv",
                "--managed-python",
                "--python",
                version,
                str(root / name),
            ],
            env,
        )
        pip(name, CERTIFI_REQUIREMENT)
    checkpoint_hashes = {}
    compatibility_patches = {}
    auxiliary_packages = {}
    auxiliary_libraries = {}
    if mode == "design_and_validate":
        # Conda supplies git only. Both scientific interpreters come from the
        # same exact uv-managed Python build already exercised on T4.
        mamba(
            "install" if (root / "git/bin/git").is_file() else "create",
            "-y",
            "-p",
            str(root / "git"),
            "--override-channels",
            "-c",
            "conda-forge",
            "git",
        )
        git = str(root / "git/bin/git")
        phase("Fetch the recorded design-tool revisions")
        sources = (
            ("RFdiffusion", tools.RFDIFF_REPO, tools.RFDIFF_COMMIT),
            ("ProteinMPNN", tools.PROTEINMPNN_REPO, tools.PROTEINMPNN_COMMIT),
        )
        for name, url, revision in sources:
            target = root / "tools" / name
            if not (target / ".git").is_dir():
                command([git, "clone", "--quiet", url, str(target)], env)
            verify_managed_checkout(git, target, env)
            command([git, "-C", str(target), "checkout", "--detach", revision], env)
            actual = subprocess.run(
                [git, "-C", str(target), "rev-parse", "HEAD"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=20,
            ).stdout.strip()
            if actual != revision:
                raise RuntimeError(f"{name} checkout does not match its pinned revision")

        phase("Install the isolated RFdiffusion and ProteinMPNN environment")
        pip("se3", pins.TORCH_WHEEL, pins.SE3_DGL_WHEEL, *pins.SE3_EXTRA_PIP)
        reset_owned_environment(root, "cuda11")
        pip("se3", "--target", str(root / "cuda11"), "--no-deps", *pins.CUDA11_PIP)
        from importlib.metadata import distributions

        auxiliary_packages = {
            dist.metadata["Name"]: dist.version
            for dist in distributions(path=[str(root / "cuda11")])
        }
        for library in sorted((root / "cuda11/nvidia").glob("*/lib/*.so*")):
            if library.is_symlink() or not library.is_file():
                raise RuntimeError("Unexpected CUDA11 library layout")
            with library.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            auxiliary_libraries[library.relative_to(root / "cuda11").as_posix()] = {
                "bytes": library.stat().st_size,
                "sha256": digest,
            }
        se3 = root / "tools/RFdiffusion/env/SE3Transformer"
        # Upstream requirements include training-only loggers. Neither source
        # package declares them as required metadata; the actual inference
        # imports and uv pip check verify the deliberately bounded runtime.
        pip("se3", "--no-deps", str(se3))
        pip("se3", "--no-deps", "-e", str(root / "tools/RFdiffusion"))
        wrapper = root / "se3-python"
        python_minor = ".".join(pins.SE3_PYTHON.split(".")[:2])
        site = root / f"se3/lib/python{python_minor}/site-packages"
        compatibility_patches["e3nn_constants_loader"] = patch_e3nn_constants_loader(site)
        libraries = ":".join(
            str(path)
            for path in [
                site / "torch/lib",
                *sorted((site / "nvidia").glob("*/lib")),
                *sorted((root / "cuda11/nvidia").glob("*/lib")),
            ]
        )
        wrapper.write_text(
            "#!/bin/sh\nexport DGLBACKEND=pytorch\n"
            + "export LD_LIBRARY_PATH="
            + shlex.quote(libraries)
            + ':"${LD_LIBRARY_PATH:-}"\n'
            + "exec "
            + shlex.quote(str(root / "se3/bin/python"))
            + ' "$@"\n',
            encoding="utf-8",
            newline="\n",
        )
        wrapper.chmod(0o755)
        phase("Download design checkpoints and record their exact hashes")
        for name, url in [] if check_only else tools.RFDIFF_WEIGHTS.items():
            checkpoint_hashes[name] = download(
                url,
                root / "tools/RFdiffusion/models" / name,
                tools.RFDIFF_WEIGHT_SHA256.get(name),
                maximum=2 * 2**30,
                minimum=2**20,
            )
    phase("Install the isolated Boltz prediction environment")
    boltz_wheel, boltz_wheel_receipt = prepare_boltz_runtime_wheel(root / "patched-wheels")
    pip(
        "boltz",
        pins.TORCH_WHEEL,
        str(boltz_wheel),
        f"trifast=={pins.BOLTZ_TRIFAST}",
        f"numpy=={pins.BOLTZ_NUMPY}",
        "biopython>=1.88,<2",
    )
    pip("boltz", str(source))
    phase(
        "Check installed software versions and imports without GPU operations"
        if check_only
        else "Check both environments with real CUDA operations"
    )
    checks = smoke(root, env, require_cuda=not check_only, mode=mode)
    if checks["boltz"]["boltz"] != pins.BOLTZ_RUNTIME_VERSION:
        raise RuntimeError("The installed Boltz version does not match the reviewed recipe.")
    boltz_assets = {}
    if not check_only:
        phase("Verify publisher-pinned Boltz model and chemical-component assets")
        boltz_assets = prepare_boltz_assets(Path(env["BOLTZ_CACHE"]))
    freezes = {}
    for name, _version in environments:
        command(
            [
                str(installer),
                "--no-config",
                "pip",
                "check",
                "--python",
                str(root / name / "bin/python"),
            ],
            env,
        )
        result = subprocess.run(
            [
                str(installer),
                "--no-config",
                "pip",
                "freeze",
                "--python",
                str(root / name / "bin/python"),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        freezes[name] = result.stdout.splitlines()
    receipt = {
        "schema": "bindsight-gpu-runtime/1",
        "mode": mode,
        "recipe_id": pins.recipe()["id"],
        "recipe": pins.recipe(),
        "source_identity": identity,
        "tools_root": str(root / "tools"),
        "design_python": str(root / "se3-python") if mode == "design_and_validate" else None,
        "boltz_python": str(root / "boltz/bin/python"),
        "execution_environment": execution_overrides(root, gpu_index, mode),
        "cuda_smoke_passed": not check_only,
        "cuda_tested": not check_only,
        "models_downloaded": bool(checkpoint_hashes or boltz_assets),
        "checks": checks,
        "checkpoint_sha256": checkpoint_hashes,
        "checkpoint_expected_sha256": tools.RFDIFF_WEIGHT_SHA256
        if mode == "design_and_validate"
        else {},
        "installed_packages": freezes,
        "compatibility_patches": compatibility_patches,
        "boltz_runtime_wheel": boltz_wheel_receipt,
        "boltz_assets": boltz_assets,
        "auxiliary_cuda11_packages": auxiliary_packages,
        "auxiliary_cuda11_libraries": auxiliary_libraries,
        "security_boundary": pins.recipe()["security_boundary"],
        "scientific_gpu_validation": "not established by setup checks",
        "boltz_weights": "Publisher-pinned assets verified before predictor use"
        if boltz_assets
        else "Not downloaded in CPU check mode",
    }
    write_json(root / "provision-receipt.json", receipt)
    if check_only:
        phase("CPU recipe import check completed; CUDA and models were not tested")
    else:
        write_json(root / "ready.json", receipt)
        phase("Environment setup completed; full scientific validation is separate")
    return receipt


def main() -> None:
    """Expose the same wheel-aware provisioner to every managed GPU backend."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--mode", choices=pins.MODES, default="design_and_validate")
    parser.add_argument("--gpu-index", type=int, default=0)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    result = provision(
        args.root,
        source=args.source,
        mode=args.mode,
        gpu_index=args.gpu_index,
        check_only=args.check_only,
    )
    if args.receipt:
        write_json(args.receipt, result)


if __name__ == "__main__":
    main()
