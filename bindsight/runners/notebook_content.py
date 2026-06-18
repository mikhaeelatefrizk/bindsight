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

import json
from pathlib import Path
from typing import Any

from bindsight.runners import tools
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
    spec_json = json.dumps(spec, indent=2)
    cells = [
        markdown_cell(_intro(handle_id, designer, gpu_type)),
        code_cell_from_template(_GPU_CHECK_CELL, {}),
        markdown_cell(
            "## 1. Install RFdiffusion + ProteinMPNN + Boltz-2 + bindsight\n\n"
            "Pinned upstream revisions (~5–10 min first run, cached afterwards)."
        ),
        code_cell_from_template(
            _INSTALL_CELL,
            {
                "rfdiff_repo": tools.RFDIFF_REPO,
                "rfdiff_commit": tools.RFDIFF_COMMIT,
                "mpnn_repo": tools.PROTEINMPNN_REPO,
                "mpnn_commit": tools.PROTEINMPNN_COMMIT,
                "boltz_pip": tools.BOLTZ_PIP,
                "base_url": tools.RFDIFF_WEIGHTS["Base_ckpt.pt"],
                "complex_url": tools.RFDIFF_WEIGHTS["Complex_base_ckpt.pt"],
            },
        ),
        markdown_cell("## 2. Load the design spec + target structure"),
        code_cell_from_template(
            _LOAD_SPEC_CELL,
            {"handle_id": handle_id, "spec_json": spec_json.replace("\\", "\\\\")},
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


_GPU_CHECK_CELL = """\
# Confirm a CUDA GPU is available — RFdiffusion and Boltz-2 both require it.
import subprocess, sys
try:
    info = subprocess.check_output(['nvidia-smi'], text=True)
    print(info.split('\\n')[8])  # GPU model line
    print('GPU OK ✓')
except (FileNotFoundError, subprocess.CalledProcessError):
    print('No GPU. Runtime → Change runtime type → T4 GPU.', file=sys.stderr)
    raise SystemExit(1)
"""

_INSTALL_CELL = """\
# Install the pinned design tools + bindsight, then point bindsight at them via
# BINDSIGHT_TOOLS_ROOT so the executor reuses them instead of re-cloning.
import os, pathlib, subprocess
ROOT = pathlib.Path('/content/bindsight_tools'); ROOT.mkdir(exist_ok=True)
os.environ['BINDSIGHT_TOOLS_ROOT'] = str(ROOT)

def sh(*cmd): subprocess.run(list(cmd), check=True)

# RFdiffusion (https://github.com/RosettaCommons/RFdiffusion)
rfdiff = ROOT / 'RFdiffusion'
if not rfdiff.exists():
    sh('git', 'clone', '-q', '{{ rfdiff_repo }}', str(rfdiff))
    sh('git', '-C', str(rfdiff), 'checkout', '-q', '{{ rfdiff_commit }}')
    models = rfdiff / 'models'; models.mkdir(exist_ok=True)
    for url, name in [('{{ base_url }}', 'Base_ckpt.pt'), ('{{ complex_url }}', 'Complex_base_ckpt.pt')]:
        if not (models / name).exists():
            sh('wget', '-q', url, '-O', str(models / name))
    sh('pip', 'install', '-q', '-r', str(rfdiff / 'env/SE3Transformer/requirements.txt'))
    sh('pip', 'install', '-q', '-e', str(rfdiff))

# ProteinMPNN (https://github.com/dauparas/ProteinMPNN)
mpnn = ROOT / 'ProteinMPNN'
if not mpnn.exists():
    sh('git', 'clone', '-q', '{{ mpnn_repo }}', str(mpnn))
    sh('git', '-C', str(mpnn), 'checkout', '-q', '{{ mpnn_commit }}')

# Boltz-2 + bindsight (bindsight is not on PyPI yet — install from GitHub)
sh('pip', 'install', '-q', '{{ boltz_pip }}', 'git+https://github.com/mikhaeelatefrizk/bindsight.git')
print('tools installed ✓')
"""

_LOAD_SPEC_CELL = """\
# Write the design spec + target structure the executor will read.
import base64, json, pathlib
JOB_ID = '{{ handle_id }}'
SPEC = json.loads('''{{ spec_json }}''')
spec_dir = pathlib.Path(f'/content/{JOB_ID}_spec'); spec_dir.mkdir(exist_ok=True)
(spec_dir / 'spec.json').write_text(json.dumps(SPEC, indent=2))
name = SPEC.get('extra_params', {}).get('target_structure_name', 'target.pdb')
if 'target_structure_b64' in SPEC:
    (spec_dir / name).write_bytes(base64.b64decode(SPEC['target_structure_b64']))
    print('target structure written:', name)
else:
    print('WARNING: no target_structure_b64 in spec; upload', name, 'into', spec_dir)
print('target:', SPEC.get('target_uniprot'), '| residues:', SPEC.get('epitope_residues'))
"""

_RUN_CELL = """\
# Run the real RFdiffusion → ProteinMPNN → Boltz-2 pipeline via the executor.
import subprocess, sys
JOB_ID = '{{ handle_id }}'
subprocess.run(
    [sys.executable, '-m', 'bindsight.runners.job_exec',
     f'/content/{JOB_ID}_spec/spec.json', f'/content/{JOB_ID}.tar.gz'],
    check=True,
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
