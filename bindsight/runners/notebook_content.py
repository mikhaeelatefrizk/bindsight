# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Colab notebook generator for the GPU design+validation job.

The notebook is a thin wrapper over the real executor
(:mod:`bindsight.runners.job_exec`) — the SAME code the Modal / local-Docker /
Kaggle backends run — so there is exactly one source of truth for the pipeline.
It:

1. confirms a GPU,
2. installs the pinned tools (RFdiffusion + ProteinMPNN + Boltz-2, revisions
   from :mod:`bindsight.runners.tools`) and bindsight itself,
3. materialises the design spec + target structure (embedded as base64),
4. runs ``python -m bindsight.runners.job_exec`` (real RFdiffusion → ProteinMPNN
   → Boltz-2),
5. packages the results tarball for download.

Because the notebook calls the executor rather than re-implementing the tool
invocations, the contig/hotspot construction, FASTA parsing, and Boltz output
parsing are all the (tested) functions in ``bindsight.runners.tools`` — no
divergent copy lives here.
"""

from __future__ import annotations

import base64
import inspect
import json
import re
from pathlib import Path
from typing import Any

from bindsight.runners import installer_security, release_bootstrap, tools
from bindsight.runners.notebook import (
    build_notebook,
    code_cell_from_template,
    markdown_cell,
    write_notebook,
)


def build_design_notebook(
    *,
    handle_id: str,
    designer: str,
    gpu_type: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Build the design + validation notebook for a single GPU job.

    Args:
        handle_id: stable ID; results tarball is ``<handle_id>.tar.gz``.
        designer: ``rfdiff_mpnn`` | ``bindcraft`` | ``boltzgen``.
        gpu_type: ``T4`` (free Colab) or ``A100`` (Pro+/Modal).
        spec: design spec dict (``DesignSpec.model_dump()``); include
            ``target_structure_b64`` so the target is materialised on the GPU.

    Returns:
        Jupyter v4 notebook dict ready for serialisation.
    """
    from bindsight import __version__

    version = release_bootstrap.published_version(__version__)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", handle_id):
        raise ValueError("The notebook job ID must be a safe directory name.")
    mode = spec.get("extra_params", {}).get("mode", "design_and_validate")
    if mode not in {"design_and_validate", "validate_only"}:
        raise ValueError("Unsupported GPU job mode.")
    spec_b64 = base64.b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")
    cells = [
        markdown_cell(_intro(handle_id, designer, gpu_type)),
        code_cell_from_template(_GPU_CHECK_CELL, {}),
        markdown_cell(
            "## 1. Install RFdiffusion + ProteinMPNN + Boltz-2 + bindsight\n\n"
            f"Uses published Bindsight {version} and its canonical managed GPU recipe. "
            "Unpublished changes are not included. The first setup downloads packages and models."
        ),
        code_cell_from_template(
            _INSTALL_CELL,
            {
                "bootstrap_source": _bootstrap_source(),
                "version": version,
                "mode": mode,
            },
        ),
        markdown_cell("## 2. Load the design spec + target structure"),
        code_cell_from_template(
            _LOAD_SPEC_CELL,
            {"handle_id": handle_id, "spec_b64": spec_b64},
        ),
        markdown_cell(
            "## 3. Run the design + validation pipeline\n\n"
            "This calls `bindsight.runners.job_exec` — RFdiffusion (backbones) → "
            "ProteinMPNN (sequences) → Boltz-2 (structure + affinity) — the exact "
            "code the Modal/local backends run."
        ),
        code_cell_from_template(_RUN_CELL, {"handle_id": handle_id}),
        markdown_cell(
            "## 4. Download results\n\nDownload "
            f"`{handle_id}.tar.gz` and drop it into your local `<run_dir>/design/`."
        ),
        code_cell_from_template(_DOWNLOAD_CELL, {"handle_id": handle_id}),
    ]
    return build_notebook(
        cells=cells,
        gpu=gpu_type if gpu_type in {"T4", "L4", "A100", "V100"} else "T4",  # type: ignore[arg-type]
        title=f"bindsight {designer} {handle_id[:8]}",
    )


def write_design_notebook(
    out_path: Path,
    *,
    handle_id: str,
    designer: str,
    gpu_type: str,
    spec: dict[str, Any],
) -> Path:
    """Build and write the design notebook to ``out_path``."""
    notebook = build_design_notebook(
        handle_id=handle_id, designer=designer, gpu_type=gpu_type, spec=spec
    )
    return write_notebook(notebook, out_path)


# ---------------------------------------------------------------------------
# Cell content
# ---------------------------------------------------------------------------
def _intro(handle_id: str, designer: str, gpu_type: str) -> str:
    return (
        f"# bindsight design + validate — `{handle_id}`\n\n"
        f"**Designer:** `{designer}`  ·  **GPU:** `{gpu_type}`\n\n"
        "Runtime → Run all. This notebook wraps `bindsight.runners.job_exec` (the "
        "same executor the Modal / local-Docker / Kaggle backends use), so the "
        "design+validation pipeline here is identical to the headless one.\n\n"
        "Upstream tools:\n"
        f"- RFdiffusion {tools.RFDIFF_REPO} @ `{tools.RFDIFF_COMMIT[:10]}`\n"
        f"- ProteinMPNN {tools.PROTEINMPNN_REPO} @ `{tools.PROTEINMPNN_COMMIT[:10]}`\n"
        "- Boltz-2 https://github.com/jwohlwend/boltz\n"
    )


def _bootstrap_source() -> str:
    """Embed reviewed stdlib helpers, without fetching executable bootstrap code."""
    source = inspect.getsource(release_bootstrap).replace(
        "from __future__ import annotations\n", ""
    )
    constants = "\n".join(
        f"{name} = {getattr(installer_security, name)!r}"
        for name in (
            "UV_ARCHIVE_URLS",
            "UV_ARCHIVE_BYTES",
            "UV_ARCHIVE_SHA256",
            "CERTIFI_REQUIREMENT",
        )
    )
    functions = "\n\n".join(
        inspect.getsource(function)
        for function in (
            installer_security.extract_verified_uv,
            installer_security.download_verified_uv,
            installer_security.package_environment,
            installer_security.uv_install_command,
        )
    )
    return (
        "from __future__ import annotations\nfrom collections.abc import Callable\n"
        + source
        + "\n"
        + constants
        + "\n"
        + functions
    )


_GPU_CHECK_CELL = """\
# Confirm a CUDA GPU is available — RFdiffusion and Boltz-2 both require it.
import subprocess, sys
try:
    info = subprocess.check_output(['nvidia-smi'], text=True)
    print(info)
    print('GPU detected; managed setup will check compatibility.')
except (FileNotFoundError, subprocess.CalledProcessError):
    print('No GPU. Runtime → Change runtime type → T4 GPU.', file=sys.stderr)
    raise SystemExit(1)
"""

_INSTALL_CELL = """\
{{ bootstrap_source }}

# RFdiffusion, ProteinMPNN and Boltz use the shared managed GPU provisioner.
# The notebook's global Python environment is not modified.
import os, subprocess
ROOT = Path('/content/bindsight_tools'); ROOT.mkdir(exist_ok=True)
RELEASE_VERSION = '{{ version }}'
UV = download_verified_uv(ROOT / 'bootstrap/uv', report=print)
WHEEL = download_release_wheel(RELEASE_VERSION, ROOT / 'release')
ENV = package_environment(dict(os.environ), ROOT / 'uv-cache')
ENV.pop('UV_NO_PYTHON_DOWNLOADS', None)
ENV['UV_PYTHON_INSTALL_DIR'] = str(ROOT / 'python')
subprocess.run([str(UV), '--no-config', 'python', 'install', '3.11.18'], env=ENV, check=True)
DRIVER = ROOT / 'driver/bin/python'
subprocess.run([str(UV), '--no-config', 'venv', '--python', '3.11.18', '--managed-python',
                str(ROOT / 'driver')], env=ENV, check=True)
subprocess.run(uv_install_command(UV, DRIVER, [str(WHEEL), "psutil>=5.9,<8"]), env=ENV, check=True)
subprocess.run([str(DRIVER), '-I', '-m', 'bindsight.runners.gpu_runtime',
                '--root', str(ROOT / 'runtime'), '--source', str(WHEEL),
                '--mode', '{{ mode }}', '--receipt', str(ROOT / 'provision-receipt.json')],
               env=ENV, check=True)
print('Managed GPU recipe prepared; source wheel receipt:', WHEEL.with_suffix('.source.json'))
"""

_LOAD_SPEC_CELL = """\
# Write the design spec + target structure the executor will read.
import base64, json, pathlib
JOB_ID = '{{ handle_id }}'
SPEC = json.loads(base64.b64decode('{{ spec_b64 }}', validate=True).decode('utf-8'))
spec_dir = pathlib.Path(f'/content/{JOB_ID}_spec'); spec_dir.mkdir(exist_ok=True)
(spec_dir / 'spec.json').write_text(json.dumps(SPEC, indent=2))
name = SPEC.get('extra_params', {}).get('target_structure_name', 'target.pdb')
if 'target_structure_b64' in SPEC:
    if not isinstance(name, str):
        raise ValueError('Target structure path must be a string.')
    target = spec_dir / name
    if ('\\\\' in name or '..' in pathlib.PurePosixPath(name).parts
            or not target.resolve().is_relative_to(spec_dir.resolve())
            or target.resolve() in {spec_dir.resolve(), (spec_dir / 'spec.json').resolve()}):
        raise ValueError('Target structure path escapes its job directory.')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(SPEC['target_structure_b64'], validate=True))
    print('target structure written:', name)
else:
    print('WARNING: no target_structure_b64 in spec; upload', name, 'into', spec_dir)
print('target:', SPEC.get('target_uniprot'), '| residues:', SPEC.get('epitope_residues'))
"""

_RUN_CELL = """\
# Run the real RFdiffusion → ProteinMPNN → Boltz-2 pipeline via the executor.
import json, os, subprocess
JOB_ID = '{{ handle_id }}'
receipt = json.loads((ROOT / 'provision-receipt.json').read_text())
job_env = dict(os.environ)
for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE',
            'BINDSIGHT_BOLTZ_BIN', 'BINDSIGHT_LOCAL_IMAGE', 'BINDSIGHT_DESIGN_PYTHON'):
    job_env.pop(key, None)
job_env.update(receipt['execution_environment'])
subprocess.run(
    [receipt['boltz_python'], '-I', '-m', 'bindsight.runners.job_exec',
     f'/content/{JOB_ID}_spec/spec.json', f'/content/{JOB_ID}.tar.gz'],
    env=job_env, check=True,
)
print('done -> /content/{{ handle_id }}.tar.gz')
"""

_DOWNLOAD_CELL = """\
# Download the results tarball; drop it into <run_dir>/design/ on your machine.
import pathlib
tarball = pathlib.Path('/content/{{ handle_id }}.tar.gz')
print(f'{tarball} ({tarball.stat().st_size / 1e6:.1f} MB)' if tarball.exists() else 'no tarball produced')
try:
    from google.colab import files
    files.download(str(tarball))
except ImportError:
    pass  # not on Colab — download manually from the Files panel
"""
