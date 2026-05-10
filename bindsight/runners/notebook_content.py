"""Real Colab notebook cell content for the GPU stages.

Generates a self-contained Jupyter notebook (Colab-flavoured) that runs
the full design + validation pipeline on a single target. Cells follow the
canonical install patterns from the upstream tool READMEs:

- `RFdiffusion <https://github.com/RosettaCommons/RFdiffusion>`_ (BSD-3)
- `ProteinMPNN <https://github.com/dauparas/ProteinMPNN>`_ (MIT)
- `Boltz-2 <https://github.com/jwohlwend/boltz>`_ (MIT, code + weights)

The notebook is intentionally conservative: every cell can fail gracefully
with a clear message; weight downloads are pinned; the install matches what
ColabDesign and dl_binder_design have validated on free Colab T4. First-run
install takes ~5–10 minutes; subsequent runs (same Colab session) are
instant.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    spec: dict,
) -> dict:
    """Build the design + validation notebook for a single GPU job.

    Args:
        handle_id: stable ID for the run; results tarball will be ``<handle_id>.tar.gz``.
        designer: ``"rfdiff_mpnn"`` is the only one fully wired in v0.1.
        gpu_type: ``"T4"`` (free Colab) or ``"A100"`` (Pro+/Modal).
        spec: design spec dict as produced by ``DesignSpec.model_dump()``.

    Returns:
        Jupyter v4 notebook dict ready for serialisation.
    """
    spec_json = json.dumps(spec, indent=2)
    cells = [
        markdown_cell(_intro(handle_id, designer, gpu_type)),
        code_cell_from_template(_GPU_CHECK_CELL, {}),
        markdown_cell(
            "## 1. Install dependencies\n\nRFdiffusion + ProteinMPNN + Boltz-2 "
            "(~5–10 min on first run, cached afterwards)."
        ),
        code_cell_from_template(_INSTALL_RFDIFF_CELL, {}),
        code_cell_from_template(_INSTALL_PROTEINMPNN_CELL, {}),
        code_cell_from_template(_INSTALL_BOLTZ_CELL, {}),
        markdown_cell("## 2. Load the design spec"),
        code_cell_from_template(
            _LOAD_SPEC_CELL,
            {"handle_id": handle_id, "spec_json": spec_json.replace("\\", "\\\\")},
        ),
        markdown_cell(
            "## 3. RFdiffusion — generate binder backbones\n\n"
            "Generates `n_trajectories` independent backbones targeting the "
            "specified epitope hotspots. ~30 s/backbone on A100, ~2 min on T4."
        ),
        code_cell_from_template(_RUN_RFDIFF_CELL, {}),
        markdown_cell(
            "## 4. ProteinMPNN — design sequences for each backbone\n\n"
            "Fast (~2 s/sequence). Produces 1 sequence per backbone, biased "
            "for solubility."
        ),
        code_cell_from_template(_RUN_MPNN_CELL, {}),
        markdown_cell(
            "## 5. Boltz-2 — predict structure + binding affinity\n\n"
            "Validates each design by predicting the target+binder complex "
            "structure and a continuous affinity score. ~20 s/design on A100."
        ),
        code_cell_from_template(_RUN_BOLTZ_CELL, {}),
        markdown_cell(
            "## 6. Package results\n\nTarballs the designs + metrics into "
            f"`{handle_id}.tar.gz`. Download via the file browser on the left and "
            "place into your local `<run_dir>/design/`."
        ),
        code_cell_from_template(
            _PACKAGE_CELL,
            {"handle_id": handle_id},
        ),
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
    spec: dict,
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
        f"**Designer:** `{designer}`  ·  **GPU:** `{gpu_type}`  ·  **Job ID:** `{handle_id}`\n\n"
        "Run all cells (Runtime → Run all). Total time: ~10–30 min.\n\n"
        "1. **Cell 1** — confirm GPU is available\n"
        "2. **Cells 2–4** — install RFdiffusion, ProteinMPNN, Boltz-2\n"
        "3. **Cell 5** — load the design spec\n"
        "4. **Cell 6** — RFdiffusion (backbone generation)\n"
        "5. **Cell 7** — ProteinMPNN (sequence design)\n"
        "6. **Cell 8** — Boltz-2 (validation)\n"
        "7. **Cell 9** — package results into a tarball you download\n\n"
        "Source notebooks this is patterned on:\n"
        "- ColabDesign / RFdiffusion: https://github.com/sokrypton/ColabDesign\n"
        "- dl_binder_design: https://github.com/nrbennet/dl_binder_design\n"
        "- Boltz-2: https://github.com/jwohlwend/boltz\n"
    )


_GPU_CHECK_CELL = """\
# Confirm a CUDA GPU is available — Boltz-2 and RFdiffusion both require it.
import subprocess, sys
try:
    info = subprocess.check_output(['nvidia-smi'], text=True)
    print(info.split('\\n')[8])  # GPU model line
    print('GPU OK ✓')
except (FileNotFoundError, subprocess.CalledProcessError):
    print('No GPU found. Switch runtime: Runtime → Change runtime type → T4 GPU.', file=sys.stderr)
    raise SystemExit(1)
"""

_INSTALL_RFDIFF_CELL = """\
# Install RFdiffusion (https://github.com/RosettaCommons/RFdiffusion, BSD-3)
import os, pathlib, subprocess
RFDIFF_DIR = pathlib.Path('/content/RFdiffusion')
if not RFDIFF_DIR.exists():
    subprocess.run(['git', 'clone', '-q', '--depth=1',
                    'https://github.com/RosettaCommons/RFdiffusion.git', str(RFDIFF_DIR)],
                   check=True)
    # Pinned weight URLs from IPD's public mirror — see RFdiffusion README.
    weights_dir = RFDIFF_DIR / 'models'
    weights_dir.mkdir(exist_ok=True)
    base_ckpt = weights_dir / 'Base_ckpt.pt'
    complex_ckpt = weights_dir / 'Complex_base_ckpt.pt'
    for url, dst in [
        ('http://files.ipd.uw.edu/pub/RFdiffusion/6f5902ac237024bdd0c176cb93063dc4/Base_ckpt.pt', base_ckpt),
        ('http://files.ipd.uw.edu/pub/RFdiffusion/e29311f6f1bf1af907f9ef9f44b8328b/Complex_base_ckpt.pt', complex_ckpt),
    ]:
        if not dst.exists():
            print(f'downloading {dst.name} (~1.5 GB) …')
            subprocess.run(['wget', '-q', url, '-O', str(dst)], check=True)
    subprocess.run(['pip', 'install', '-q', '-r', str(RFDIFF_DIR / 'env/SE3Transformer/requirements.txt')],
                   check=True)
    subprocess.run(['pip', 'install', '-q', '-e', str(RFDIFF_DIR)], check=True)
print('RFdiffusion installed ✓')
"""

_INSTALL_PROTEINMPNN_CELL = """\
# Install ProteinMPNN (https://github.com/dauparas/ProteinMPNN, MIT)
import pathlib, subprocess
MPNN_DIR = pathlib.Path('/content/ProteinMPNN')
if not MPNN_DIR.exists():
    subprocess.run(['git', 'clone', '-q', '--depth=1',
                    'https://github.com/dauparas/ProteinMPNN.git', str(MPNN_DIR)],
                   check=True)
print('ProteinMPNN installed ✓')
"""

_INSTALL_BOLTZ_CELL = """\
# Install Boltz-2 (https://github.com/jwohlwend/boltz, MIT)
import subprocess
subprocess.run(['pip', 'install', '-q', 'boltz>=2.0,<3.0'], check=True)
print('Boltz-2 installed ✓')
"""

_LOAD_SPEC_CELL = """\
# Load the design spec produced by `bindsight design`.
import json, pathlib
JOB_ID = '{{ handle_id }}'
SPEC = json.loads('''{{ spec_json }}''')
print('spec keys:', list(SPEC.keys()))
print('target:', SPEC.get('target_uniprot'))
print('epitope chain:', SPEC.get('epitope_chain'))
print('epitope residues:', SPEC.get('epitope_residues'))
print('n_trajectories:', SPEC.get('n_trajectories'))
WORK = pathlib.Path(f'/content/{JOB_ID}_work')
WORK.mkdir(exist_ok=True)
TARGET_PDB = WORK / 'target.pdb'

# Materialise the target structure embedded in the spec (or referenced by path).
import base64
if 'target_structure_b64' in SPEC:
    TARGET_PDB.write_bytes(base64.b64decode(SPEC['target_structure_b64']))
elif SPEC.get('target_structure_path'):
    src = pathlib.Path(SPEC['target_structure_path'])
    if src.exists():
        TARGET_PDB.write_bytes(src.read_bytes())
    else:
        print(f'WARNING: target structure not found at {src}; upload target.pdb manually.')
print(f'target structure: {TARGET_PDB} ({TARGET_PDB.stat().st_size if TARGET_PDB.exists() else 0} bytes)')
"""

_RUN_RFDIFF_CELL = """\
# Run RFdiffusion to generate `n_trajectories` binder backbones.
import os, subprocess, pathlib
os.chdir('/content/RFdiffusion')
OUT_DIR = pathlib.Path(f'/content/{JOB_ID}_work/rfdiff_out')
OUT_DIR.mkdir(exist_ok=True)

# Hotspot string for RFdiffusion's `ppi.hotspot_res=[A30,A31,...]` syntax.
chain = SPEC.get('epitope_chain', 'A')
hotspots = '[' + ','.join(f'{chain}{r}' for r in SPEC.get('epitope_residues', [])) + ']'

# Build the contig: keep the full target chain, append a binder of length L.
binder_lo = SPEC.get('binder_length_min', 50)
binder_hi = SPEC.get('binder_length_max', 100)

cmd = [
    'python', 'scripts/run_inference.py',
    f'inference.input_pdb={TARGET_PDB}',
    f'inference.output_prefix={OUT_DIR}/binder',
    f'inference.num_designs={SPEC.get("n_trajectories", 5)}',
    f'ppi.hotspot_res={hotspots}',
    f'contigmap.contigs=[A1-9999/0\\\\ {binder_lo}-{binder_hi}]',
]
print('RFdiffusion command:', ' '.join(cmd))
result = subprocess.run(cmd, capture_output=True, text=True)
print(result.stdout[-2000:])
if result.returncode != 0:
    print('STDERR:', result.stderr[-2000:])
    raise RuntimeError('RFdiffusion failed')
print('RFdiffusion produced:', sorted(p.name for p in OUT_DIR.glob('*.pdb')))
"""

_RUN_MPNN_CELL = """\
# ProteinMPNN — design sequences for each RFdiffusion backbone.
import os, subprocess, pathlib
MPNN_OUT = pathlib.Path(f'/content/{JOB_ID}_work/mpnn_out')
MPNN_OUT.mkdir(exist_ok=True)
MPNN_DIR = pathlib.Path('/content/ProteinMPNN')

for pdb in sorted(OUT_DIR.glob('binder_*.pdb')):
    designs_dir = MPNN_OUT / pdb.stem
    designs_dir.mkdir(exist_ok=True)
    cmd = ['python', str(MPNN_DIR / 'protein_mpnn_run.py'),
           '--pdb_path', str(pdb),
           '--out_folder', str(designs_dir),
           '--num_seq_per_target', '2',
           '--sampling_temp', '0.1',
           '--seed', str(SPEC.get('seed', 0))]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print('MPNN STDERR for', pdb.name, ':', result.stderr[-500:])
        continue
print('ProteinMPNN produced sequences for', len(list(MPNN_OUT.iterdir())), 'backbones')
"""

_RUN_BOLTZ_CELL = """\
# Boltz-2 — structure + binding affinity prediction for each design.
import json, subprocess, pathlib, yaml
BOLTZ_OUT = pathlib.Path(f'/content/{JOB_ID}_work/boltz_out')
BOLTZ_OUT.mkdir(exist_ok=True)

# Read the target sequence from the original target.pdb (chain A, all residues)
def _seq_from_pdb(pdb_path):
    aa3to1 = {
        'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q','GLU':'E',
        'GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K','MET':'M','PHE':'F',
        'PRO':'P','SER':'S','THR':'T','TRP':'W','TYR':'Y','VAL':'V',
    }
    seq = []
    seen = set()
    for line in pathlib.Path(pdb_path).read_text().splitlines():
        if line.startswith('ATOM') and line[12:16].strip() == 'CA':
            chain = line[21]
            resi = int(line[22:26])
            resn = line[17:20].strip()
            key = (chain, resi)
            if chain == 'A' and key not in seen:
                seen.add(key)
                seq.append(aa3to1.get(resn, 'X'))
    return ''.join(seq)

target_seq = _seq_from_pdb(TARGET_PDB)
print('target seq length:', len(target_seq))

metrics = []
for backbone_dir in sorted(MPNN_OUT.iterdir()):
    fasta = next((backbone_dir / 'seqs').glob('*.fa'), None)
    if not fasta:
        continue
    # Boltz expects FASTA-like sequence; ProteinMPNN writes one per backbone.
    fasta_text = fasta.read_text().strip().split('\\n')
    if len(fasta_text) < 2:
        continue
    binder_seq = fasta_text[1]
    binder_id = backbone_dir.name
    spec_yaml = {
        'version': 1,
        'sequences': [
            {'protein': {'id': 'T', 'sequence': target_seq}},
            {'protein': {'id': binder_id, 'sequence': binder_seq}},
        ],
        'properties': [{'affinity': {'binder': binder_id}}],
    }
    yaml_path = BOLTZ_OUT / f'{binder_id}.yaml'
    yaml_path.write_text(yaml.safe_dump(spec_yaml, sort_keys=False))
    cmd = ['boltz', 'predict', str(yaml_path),
           '--use_msa_server', '--out_dir', str(BOLTZ_OUT / binder_id)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print('Boltz STDERR for', binder_id, ':', result.stderr[-500:])
        continue
    # Parse the per-design output JSONs Boltz wrote.
    bd = BOLTZ_OUT / binder_id
    iptm = pae = aff_v = aff_p = None
    for jpath in bd.rglob('confidence_*.json'):
        try:
            d = json.loads(jpath.read_text())
            iptm = d.get('iptm', iptm)
            pae = d.get('pae_interaction', pae) or d.get('interface_pae', pae)
        except Exception:
            pass
    for jpath in bd.rglob('affinity_*.json'):
        try:
            d = json.loads(jpath.read_text())
            aff_v = d.get('affinity_pred_value', aff_v)
            aff_p = d.get('affinity_probability_binary', aff_p)
        except Exception:
            pass
    metrics.append({
        'binder_id': binder_id,
        'target_uniprot': SPEC.get('target_uniprot'),
        'iptm': iptm,
        'pae_interaction': pae,
        'affinity_pred_value': aff_v,
        'affinity_probability_binary': aff_p,
    })

# Write the validated metrics in the same shape as bindsight.validate expects.
metrics_path = pathlib.Path(f'/content/{JOB_ID}_work/metrics.jsonl')
with metrics_path.open('w') as f:
    for m in metrics:
        f.write(json.dumps(m) + '\\n')
print(f'Wrote {len(metrics)} validation results to {metrics_path}')
"""

_PACKAGE_CELL = """\
# Tarball + download.
import pathlib, tarfile
tarball = pathlib.Path(f'/content/{{ handle_id }}.tar.gz')
work = pathlib.Path(f'/content/{{ handle_id }}_work')
with tarfile.open(tarball, 'w:gz') as tf:
    tf.add(work, arcname=f'{{ handle_id }}')
print(f'Wrote {tarball} ({tarball.stat().st_size / 1e6:.1f} MB)')
print('Download from the Files panel (left), drop into <run_dir>/design/ on your machine.')
try:
    from google.colab import files
    files.download(str(tarball))
except ImportError:
    pass  # not on Colab — user downloads manually
"""
