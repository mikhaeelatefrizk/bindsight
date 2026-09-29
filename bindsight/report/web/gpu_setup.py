# SPDX-License-Identifier: AGPL-3.0-or-later
"""User-approved, isolated Linux GPU provisioning from fixed upstream sources."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import os
import shlex
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

import requests

from bindsight.report.web.gpu import (
    MICROMAMBA_SHA256,
    MICROMAMBA_URL,
    MIN_MEMORY_MIB,
    devices,
    execution_environment,
    recipe,
)
from bindsight.report.web.workspace import write_json
from bindsight.runners import tools
from bindsight.runners.kaggle_kernel import _SE3_EXTRA_PIP

LOG = logging.getLogger(__name__)


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


def smoke(root: Path, env: dict[str, str], *, require_cuda: bool = True) -> dict[str, Any]:
    """Import actual tool entrypoints; optionally test small CUDA operations, never inference."""
    result = {}
    programs = {
        "se3": (
            root / "se3-python",
            "import rfdiffusion.inference.model_runners, se3_transformer, dgl, e3nn; "
            + f"sys.path.insert(0, {str(root / 'tools/ProteinMPNN')!r}); "
            + "import protein_mpnn_utils; from pathlib import Path; "
            + "assert Path(protein_mpnn_utils.__file__).resolve() == "
            + f"Path({str(root / 'tools/ProteinMPNN/protein_mpnn_utils.py')!r}).resolve(), "
            + "'ProteinMPNN was not imported from the managed source'; ",
        ),
        "boltz": (root / "boltz/bin/python", "import boltz.main; "),
    }
    for name, (python, imports) in programs.items():
        expected_torch = "1.12.1+cu113" if name == "se3" else "2.2.2+cu118"
        expected_python = (3, 9) if name == "se3" else (3, 11)
        program = (
            "import json, sys, torch; from importlib.metadata import version; "
            + imports
            + f"assert torch.__version__ == {expected_torch!r}, 'Unexpected torch version'; "
            + f"assert sys.version_info[:2] == {expected_python!r}, 'Unexpected Python version'; "
            + (
                "assert version('dgl') == '1.0.2+cu113', 'Unexpected DGL version'; "
                if name == "se3"
                else "assert version('boltz') == '2.0.3', 'Unexpected Boltz version'; "
                "assert version('numpy') == '1.26.4', 'Unexpected NumPy version'; "
            )
        )
        if require_cuda:
            program += (
                "assert torch.cuda.is_available(), 'CUDA is unavailable'; "
                "assert torch.cuda.get_device_capability(0) >= (7,5), 'Unsupported GPU'; "
            )
            program += "x=torch.ones(4,device='cuda'); assert (x+1).sum().item()==8; torch.cuda.synchronize(); "
            if name == "se3":
                program += (
                    "g=dgl.graph(([0],[1]),num_nodes=2,device='cuda'); "
                    "g.ndata['x']=torch.ones((2,1),device='cuda'); "
                    "g.update_all(dgl.function.copy_u('x','m'),dgl.function.sum('m','y')); "
                    "assert g.ndata['y'].sum().item()==1, 'DGL CUDA reduction failed'; "
                    "torch.cuda.synchronize(); "
                )
        program += (
            "print(json.dumps({'torch':torch.__version__,'cuda':torch.version.cuda,"
            "'cuda_tested':" + repr(require_cuda) + ","
            "'dgl_cuda_tested':" + repr(require_cuda and name == "se3") + ","
            "'device':torch.cuda.get_device_name(0) if " + repr(require_cuda) + " else None,"
            "'boltz':version('boltz') if " + repr(name == "boltz") + " else None}))"
        )
        completed = subprocess.run(
            [str(python), "-c", program],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        LOG.info(
            "%s %s check: %s",
            name,
            "CUDA" if require_cuda else "import/version",
            completed.stdout.strip(),
        )
        result[name] = json.loads(completed.stdout.strip().splitlines()[-1])
    return result


def install(config: dict[str, Any], job_directory: Path, *, check_recipe: bool = False) -> None:
    """Build the demonstrated two-environment recipe without elevation or global changes."""
    if sys.platform != "linux" or config["recipe_id"] != recipe()["id"]:
        raise RuntimeError("This setup requires the current reviewed Linux GPU recipe.")
    if not check_recipe:
        gpu = next((g for g in devices() if g["index"] == config["gpu_index"]), None)
        if (
            not gpu
            or gpu["memory_mib"] < MIN_MEMORY_MIB
            or tuple(gpu["compute_capability"]) < (7, 5)
        ):
            raise RuntimeError(
                "The selected NVIDIA GPU no longer meets this workflow's requirements."
            )
    root = Path(config["gpu_root"])
    root.mkdir(parents=True, exist_ok=True)
    env = execution_environment(root, config["gpu_index"])
    env.update(
        MAMBA_ROOT_PREFIX=str(root / "mamba"),
        PIP_CONFIG_FILE=os.devnull,
        PIP_INDEX_URL="https://pypi.org/simple",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
    )
    env.pop("PIP_EXTRA_INDEX_URL", None)
    (root / "ready.json").unlink(missing_ok=True)

    def phase(name: str) -> None:
        write_json(job_directory / "progress.json", {"phase": name})

    phase("Download the pinned environment manager")
    manager = root / "micromamba"
    download(MICROMAMBA_URL, manager, MICROMAMBA_SHA256, maximum=100 * 2**20)
    manager.chmod(0o755)

    def mamba(*args: str) -> None:
        command([str(manager), *args], env)

    def pip(environment: str, *args: str) -> None:
        command(
            [
                str(root / environment / "bin/python"),
                "-m",
                "pip",
                "install",
                "--no-input",
                "-c",
                str(root / (environment + ".constraints.txt")),
                *args,
            ],
            env,
        )

    (root / "se3.constraints.txt").write_text(
        "torch==1.12.1+cu113\ndgl==1.0.2+cu113\nnumpy==1.23.5\ne3nn==0.3.3\n", encoding="ascii"
    )
    (root / "boltz.constraints.txt").write_text(
        "torch==2.2.2+cu118\nboltz==2.0.3\nnumpy==1.26.4\n", encoding="ascii"
    )

    phase("Prepare private Python environments")
    for name, version in (("se3", "3.9"), ("boltz", "3.11")):
        if not (root / name / "bin/python").is_file():
            mamba(
                "create",
                "-y",
                "-p",
                str(root / name),
                "--override-channels",
                "-c",
                "conda-forge",
                f"python={version}",
                "pip",
                "git",
            )
    # Use the managed git; no system administrator or Git installation is required.
    git = str(root / "boltz/bin/git")
    # pip's fixed upstream VCS requirements also invoke git through PATH.
    env["PATH"] = str(root / "boltz/bin") + os.pathsep + env.get("PATH", "")
    phase("Fetch the recorded design-tool revisions")
    sources = (
        ("RFdiffusion", tools.RFDIFF_REPO, tools.RFDIFF_COMMIT),
        ("ProteinMPNN", tools.PROTEINMPNN_REPO, tools.PROTEINMPNN_COMMIT),
    )
    for name, url, revision in sources:
        target = root / "tools" / name
        if not (target / ".git").is_dir():
            command([git, "clone", "--quiet", url, str(target)], env)
        command([git, "-C", str(target), "checkout", "--detach", revision], env)

    phase("Install the isolated RFdiffusion and ProteinMPNN environment")
    mamba(
        "install",
        "-y",
        "-p",
        str(root / "se3"),
        "--override-channels",
        "-c",
        "conda-forge",
        "cudatoolkit=11.3",
    )
    pip("se3", "torch==1.12.1+cu113", "--extra-index-url", "https://download.pytorch.org/whl/cu113")
    pip("se3", "dgl==1.0.2+cu113", "-f", "https://data.dgl.ai/wheels/cu113/repo.html")
    pip("se3", *_SE3_EXTRA_PIP)
    se3 = root / "tools/RFdiffusion/env/SE3Transformer"
    pip("se3", "-r", str(se3 / "requirements.txt"))
    pip("se3", "--no-deps", str(se3))
    pip("se3", "--no-deps", "-e", str(root / "tools/RFdiffusion"))
    wrapper = root / "se3-python"
    libraries = f"{root / 'se3/lib'}:{root / 'se3/lib/python3.9/site-packages/torch/lib'}"
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
    checkpoint_hashes = {}
    for name, url in [] if check_recipe else tools.RFDIFF_WEIGHTS.items():
        checkpoint_hashes[name] = download(
            url,
            root / "tools/RFdiffusion/models" / name,
            tools.RFDIFF_WEIGHT_SHA256.get(name),
            maximum=2 * 2**30,
            minimum=2**20,
        )
    phase("Install the isolated Boltz prediction environment")
    pip(
        "boltz",
        "torch==2.2.2+cu118",
        tools.BOLTZ_PIP,
        "numpy==1.26.4",
        "biopython>=1.83,<2",
        "--extra-index-url",
        "https://download.pytorch.org/whl/cu118",
    )
    source = Path(__file__).resolve().parents[3]
    if not (source / "pyproject.toml").is_file():
        raise RuntimeError(
            "This GPU setup needs the complete installed Bindsight workspace source."
        )
    pip("boltz", str(source))
    phase(
        "Check installed software versions and imports without GPU operations"
        if check_recipe
        else "Check both environments with real CUDA operations"
    )
    checks = smoke(root, env, require_cuda=not check_recipe)
    if checks["boltz"]["boltz"] != "2.0.3":
        raise RuntimeError("The installed Boltz version does not match the reviewed recipe.")
    freezes = {}
    for name in ("se3", "boltz"):
        result = subprocess.run(
            [str(root / name / "bin/python"), "-m", "pip", "freeze"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        freezes[name] = result.stdout.splitlines()
    if check_recipe:
        write_json(
            job_directory / "recipe_check.json",
            {
                "recipe_id": recipe()["id"],
                "checks": checks,
                "installed_packages": freezes,
                "cuda_tested": False,
                "models_downloaded": False,
                "scope": "Software installation and imports only; no GPU-ready or scientific success claim",
            },
        )
        phase("CPU recipe installation/import check completed; CUDA and models were not tested")
        return
    receipt = {
        "recipe_id": recipe()["id"],
        "recipe": recipe(),
        "cuda_smoke_passed": True,
        "checks": checks,
        "checkpoint_sha256": checkpoint_hashes,
        "checkpoint_expected_sha256": tools.RFDIFF_WEIGHT_SHA256,
        "installed_packages": freezes,
        "scientific_gpu_validation": "not established by setup checks",
        "boltz_weights": "Downloaded by the pinned upstream predictor at first use",
    }
    write_json(root / "ready.json", receipt)
    output = Path(config["out_dir"])
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "gpu_setup_receipt.json", receipt)
    phase("Environment setup completed; full scientific GPU validation remains unverified")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("config", nargs="?", type=Path)
        parser.add_argument("--check-recipe", action="store_true")
        parser.add_argument("--root", type=Path)
        args = parser.parse_args()
        if args.check_recipe:
            if not args.root or args.root.exists():
                raise ValueError("Recipe checks require --root naming a new, separate directory.")
            args.root.mkdir(parents=True)
            install(
                {
                    "gpu_root": str(args.root / "environments"),
                    "gpu_index": 0,
                    "out_dir": str(args.root / "output"),
                    "recipe_id": recipe()["id"],
                },
                args.root,
                check_recipe=True,
            )
        elif args.config:
            install(json.loads(args.config.read_text(encoding="utf-8")), args.config.parent)
        else:
            parser.error("Supply a job configuration, or --check-recipe --root NEW_DIRECTORY")
    except Exception:
        LOG.exception("GPU environment setup failed; partial files remain available for retry")
        raise SystemExit(1) from None
