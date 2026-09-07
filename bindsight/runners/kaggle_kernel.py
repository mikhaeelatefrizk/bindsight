# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Builder for the self-contained Kaggle kernel that runs the design+validation job.

Kaggle's *default* free GPU is a **Tesla P100 (sm_60)**, which current PyTorch
cannot drive at all: it ships no Pascal kernels, so CUDA reports available and
the first real launch dies hours into a run. This kernel therefore pins
``machine_shape`` to a **Tesla T4 (sm_75)** and checks compute capability before
doing any work.

Even on a T4, the preinstalled stack
(py3.12 / torch 2.10+cu128) supports neither that image's CUDA nor RFdiffusion's
legacy requirements. RFdiffusion (the only designer that fits 16 GB) needs an old
py3.9 / torch-1.12 environment, and that environment is mutually exclusive with
the modern Boltz-2 validator (torch ≥2.2 / py ≥3.10). So the kernel builds **two
micromamba environments** on the T4 and runs the existing executor
(:mod:`bindsight.runners.job_exec`) across them:

- ``se3``  (py3.9, torch 1.12.1+cu113 — supports sm_60): RFdiffusion + ProteinMPNN.
- ``boltz`` (py3.11, torch 2.2.2+cu118 — still ships sm_60): Boltz-2 + bindsight.

``job_exec`` runs under ``boltz`` and invokes the design tools with the ``se3``
interpreter via ``BINDSIGHT_DESIGN_PYTHON`` (a wrapper that does ``micromamba run
-p .../se3``), so there is still exactly one executor — only the per-tool
interpreter differs. The design spec + target structure are embedded as base64
(no Kaggle dataset needed); the results tarball is written to
``/kaggle/working/<handle_id>.tar.gz`` for :meth:`KaggleRunner.fetch`.

The pinned upstream revisions come from :mod:`bindsight.runners.tools` so the
kernel can never drift from the Colab/Modal/local paths.
"""

from __future__ import annotations

from typing import Any

from bindsight.runners import tools

# Channels-free pip recipe for RFdiffusion's legacy env. RFdiffusion's own
# env/SE3nv.yml pins pytorch=1.9/cudatoolkit=11.1 via conda channels whose ancient
# builds are unreliable to solve today; the cu113 pip wheels below are the
# community-proven equivalent and (unlike Kaggle's default cu128 torch) include the
# P100's sm_60 kernels. SE3-Transformer's own requirements (e3nn==0.3.3, dllogger,
# …) come from RFdiffusion/env/SE3Transformer/requirements.txt at install time.
# cu113 is the newest CUDA wheel line for torch 1.12.1; the dgl cu113 wheels at the
# find-links below are therefore built against this exact torch. Package name is
# plain ``dgl`` with a ``+cu113`` local version (the old ``dgl-cu113`` name is gone).
_SE3_TORCH = "torch==1.12.1+cu113"
_SE3_TORCH_INDEX = "https://download.pytorch.org/whl/cu113"
_SE3_DGL = "dgl==1.0.2+cu113"
_SE3_DGL_FIND = "https://data.dgl.ai/wheels/cu113/repo.html"
_SE3_EXTRA_PIP = [
    "hydra-core==1.3.2",
    "pyrsistent",
    "omegaconf",
    "icecream",
    "scipy",
    "numpy<1.24",
    "opt_einsum",
    "opt_einsum_fx",
    "e3nn==0.3.3",
]
# Boltz-2 env: a torch that still ships sm_60 (Kaggle's default cu128 does not).
_BOLTZ_TORCH = "torch==2.2.2"
_BOLTZ_TORCH_INDEX = "https://download.pytorch.org/whl/cu118"


_BINDSIGHT_REPO = "https://github.com/mikhaeelatefrizk/bindsight.git"


def build_kernel_script(
    *,
    handle_id: str,
    payload: dict[str, str],
    bindsight_ref: str | None = None,
    n_trajectories_note: int | None = None,
    bindsight_wheel_b64: str | None = None,
    bindsight_wheel_name: str = "bindsight-0.0.0-py3-none-any.whl",
) -> str:
    """Return the full Python source of the Kaggle kernel.

    Args:
        handle_id: stable id; the results tarball is ``<handle_id>.tar.gz``.
        payload: ``{filename: base64}`` for the spec dir (``spec.json`` + the
            target structure file the spec references).
        bindsight_ref: optional git ref (branch/tag/sha) to install bindsight from;
            defaults to the repository's default branch. Used to run a feature
            branch before it is merged.
        n_trajectories_note: optional, embedded only as a log breadcrumb.
        bindsight_wheel_b64: optional base64 of a wheel built from the working
            tree. When given the kernel installs it instead of pip-installing
            from git, which is the only way an unpushed change reaches the GPU.
            Without it a run silently exercises whatever the ref resolves to.
        bindsight_wheel_name: the wheel's filename, which must be a valid PEP 427
            name. pip parses the distribution, version and compatibility tags out
            of it and rejects anything else outright: writing the payload to
            ``bindsight-embedded.whl`` failed a run with "Invalid wheel filename
            (wrong number of parts)" after the environment build had finished.
    """
    git_url = f"git+{_BINDSIGHT_REPO}" + (f"@{bindsight_ref}" if bindsight_ref else "")
    # A wheel built from the working tree beats any git ref: it is the code that
    # launched the run, rather than whatever the named branch points at by the
    # time pip resolves it. Without one, an unpushed fix is invisible to the GPU.
    install_source = "embedded wheel" if bindsight_wheel_b64 else git_url
    # Emit Python *literals* with repr(), not json.dumps() — JSON's null/true/false
    # are not valid Python identifiers (an early bug embedded ``= null``).
    consts = {
        "HANDLE_ID": handle_id,
        "PAYLOAD": payload,
        "N_TRAJ_NOTE": n_trajectories_note,
        "RFDIFF_REPO": tools.RFDIFF_REPO,
        "RFDIFF_COMMIT": tools.RFDIFF_COMMIT,
        "RFDIFF_WEIGHTS": tools.RFDIFF_WEIGHTS,
        "RFDIFF_WEIGHT_SHA256": tools.RFDIFF_WEIGHT_SHA256,
        "MPNN_REPO": tools.PROTEINMPNN_REPO,
        "MPNN_COMMIT": tools.PROTEINMPNN_COMMIT,
        "BOLTZ_PIP": tools.BOLTZ_PIP,
        "SE3_TORCH": _SE3_TORCH,
        "SE3_TORCH_INDEX": _SE3_TORCH_INDEX,
        "SE3_DGL": _SE3_DGL,
        "SE3_DGL_FIND": _SE3_DGL_FIND,
        "SE3_EXTRA_PIP": _SE3_EXTRA_PIP,
        "BOLTZ_TORCH": _BOLTZ_TORCH,
        "BOLTZ_TORCH_INDEX": _BOLTZ_TORCH_INDEX,
        "BINDSIGHT_GIT": git_url,
        "BINDSIGHT_WHEEL_B64": bindsight_wheel_b64 or "",
        "BINDSIGHT_WHEEL_NAME": bindsight_wheel_name,
        "INSTALL_SOURCE": install_source,
        "MIN_CC": MIN_COMPUTE_CAPABILITY,
    }
    header_lines = ["# Auto-generated by bindsight KaggleRunner — split-env design+validation."]
    header_lines += [f"{name} = {value!r}" for name, value in consts.items()]
    return "\n".join(header_lines) + "\n\n" + _BODY


#: Kaggle accelerator to request. ``enable_gpu`` alone gets Kaggle's default,
#: which is a P100 — and Kaggle's own CLI documentation now warns that the P100
#: is unusable for GPU compute with the default image, because current PyTorch
#: builds ship no Pascal (sm_60) kernels. The failure mode is nasty:
#: ``torch.cuda.is_available()`` returns True and the first real kernel launch
#: dies with ``cudaErrorNoKernelImageForDevice``. The T4 (sm_75) is also what
#: current JAX supports, which is what makes BindCraft and AF2 initial-guess
#: reachable at all.
KAGGLE_ACCELERATOR = "NvidiaTeslaT4"

#: Compute capability the kernel requires. Turing is 7.5. Anything lower is a
#: P100 or older and cannot run the pinned stack; the kernel fails fast rather
#: than burning quota to discover it mid-run.
MIN_COMPUTE_CAPABILITY = (7, 5)

#: The same accelerator under the name :mod:`bindsight.cost` knows it by.
#:
#: These two constants have to agree. When the accelerator was pinned to a T4,
#: ``KaggleRunner`` kept defaulting to ``"P100"``, so every Kaggle runtime and
#: cost estimate was computed against a card the run would never be given —
#: a 3.0x slowdown factor applied where 4.0x was correct, quietly under-quoting
#: every estimate by a quarter. Deriving the default from here removes the
#: opportunity to make that mistake twice.
KAGGLE_COST_GPU = "T4"


def build_kernel_metadata(
    *, username: str, slug: str, accelerator: str = KAGGLE_ACCELERATOR
) -> dict[str, Any]:
    """kernel-metadata.json for a GPU + internet script kernel (no dataset sources).

    ``machine_shape`` pins which accelerator Kaggle attaches. Without it Kaggle
    picks its default, so the hardware a published result was produced on would
    not be under version control. See :data:`KAGGLE_ACCELERATOR`.
    """
    return {
        "id": f"{username}/{slug}",
        "title": slug,
        "code_file": "kernel.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "machine_shape": accelerator,
        "enable_internet": True,
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
    }


# The static kernel body. References the variables defined in the generated header
# above; kept brace-safe (no .format) so the embedded shell/Python is verbatim.
_BODY = r'''
import base64, hashlib, json, os, pathlib, subprocess, sys, time

MR = "/opt/mamba"                       # MAMBA_ROOT_PREFIX (off the /kaggle/working output volume)
MM = "/opt/micromamba/bin/micromamba"
TOOLS = "/opt/tools"
SE3 = f"{MR}/envs/se3"
BOLTZ = f"{MR}/envs/boltz"
# dgl's C lib dlopen()s CUDA 11's libcusparse.so.11 etc. via the system loader, so
# those libs must be on LD_LIBRARY_PATH. We install conda cudatoolkit=11.3 into the
# se3 env (puts them in $SE3/lib) and also keep torch's bundled libs (torch/lib).
SE3_LD = f"{SE3}/lib:{SE3}/lib/python3.9/site-packages/torch/lib"
os.environ["MAMBA_ROOT_PREFIX"] = MR


def sh(cmd, env=None):
    """Run a shell command, streaming output; raise on non-zero exit."""
    print(f"\n+ {cmd}", flush=True)
    t0 = time.time()
    r = subprocess.run(cmd, shell=True, env={**os.environ, **(env or {})})
    print(f"  ({time.time()-t0:.0f}s, exit={r.returncode})", flush=True)
    if r.returncode != 0:
        raise SystemExit(f"step failed: {cmd}")


def disk_report(label):
    """Print free space on every volume that matters.

    Kaggle documents 20 GB of persisted /kaggle/working and does not publish the
    size of the scratch area, while this build needs roughly 60 GB for two torch
    stacks plus model weights. Rather than assume it fits, every stage records
    what was actually available, so the constraint is a published number in the
    run log instead of a guess in a README.
    """
    import shutil

    parts = []
    for path in ("/", "/kaggle/working", "/kaggle/temp", "/opt", "/tmp"):
        try:
            u = shutil.disk_usage(path)
        except OSError:
            continue
        parts.append(f"{path} {u.free / 2**30:.1f}/{u.total / 2**30:.1f} GiB free")
    print(f"[disk @ {label}] " + " | ".join(parts), flush=True)


def gpu_report(label):
    """Print current and peak VRAM, so every memory claim is a measurement."""
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.used,memory.total",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True,
    )
    if out.returncode == 0 and out.stdout.strip():
        print(f"[gpu @ {label}] {out.stdout.strip()}", flush=True)


def step(msg):
    print(f"\n========== {msg} ==========", flush=True)
    disk_report(msg)
    gpu_report(msg)


step("GPU check")
sh("nvidia-smi --query-gpu=name,memory.total,compute_cap,driver_version "
   "--format=csv,noheader || true")

# Fail fast on the wrong accelerator. On a P100 the default Kaggle image reports
# torch.cuda.is_available() == True and then dies on the first kernel launch with
# cudaErrorNoKernelImageForDevice, hours into the run. Checking compute capability
# up front costs a second and turns that into an immediate, legible failure.
_cc = subprocess.run(
    ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
    capture_output=True, text=True,
)
_cc_text = (_cc.stdout or "").strip().splitlines()[0].strip() if _cc.stdout.strip() else ""
if _cc_text:
    _major, _, _minor = _cc_text.partition(".")
    _have = (int(_major), int(_minor or 0))
    print(f"compute capability {_have[0]}.{_have[1]} (need >= {MIN_CC[0]}.{MIN_CC[1]})", flush=True)
    if _have < tuple(MIN_CC):
        raise SystemExit(
            f"this kernel needs compute capability >= {MIN_CC[0]}.{MIN_CC[1]} "
            f"but got {_have[0]}.{_have[1]}. Kaggle attached the wrong accelerator: set "
            "machine_shape to NvidiaTeslaT4 in kernel-metadata.json. The default P100 "
            "(6.0) reports CUDA as available and then fails on the first kernel launch."
        )
else:
    print("WARNING: could not read compute capability; continuing unguarded", flush=True)

step("install micromamba")
pathlib.Path("/opt/micromamba/bin").mkdir(parents=True, exist_ok=True)
sh("curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest "
   "| tar -xj -C /opt/micromamba bin/micromamba")
sh(f"{MM} --version")

step("clone RFdiffusion + ProteinMPNN, fetch weights")
pathlib.Path(TOOLS).mkdir(parents=True, exist_ok=True)
if not pathlib.Path(f"{TOOLS}/RFdiffusion").exists():
    sh(f"git clone -q {RFDIFF_REPO} {TOOLS}/RFdiffusion")
    sh(f"git -C {TOOLS}/RFdiffusion checkout -q {RFDIFF_COMMIT}")
pathlib.Path(f"{TOOLS}/RFdiffusion/models").mkdir(parents=True, exist_ok=True)
for name, url in RFDIFF_WEIGHTS.items():
    dst = f"{TOOLS}/RFdiffusion/models/{name}"
    if not pathlib.Path(dst).exists():
        sh(f"wget -q '{url}' -O '{dst}'")
    # Hash every checkpoint and print it. Until now these ~480 MB of model
    # parameters arrived over plain HTTP, were loaded and executed, and nothing
    # checked that what landed was what was asked for. A truncated transfer
    # produces a checkpoint that may still load and quietly design differently.
    # Printing the digest unconditionally is also how a pin gets established:
    # the first run publishes it into this log.
    _h = hashlib.sha256()
    with open(dst, "rb") as _fh:
        for _chunk in iter(lambda: _fh.read(1 << 20), b""):
            _h.update(_chunk)
    _digest = _h.hexdigest()
    print(f"checkpoint {name}: {pathlib.Path(dst).stat().st_size} bytes sha256={_digest}", flush=True)
    _want = RFDIFF_WEIGHT_SHA256.get(name)
    if _want and _digest != _want:
        raise SystemExit(
            f"{name}: sha256 {_digest} does not match the pinned {_want}. "
            "Refusing to design against a checkpoint that is not the one this "
            "result would claim."
        )
if not pathlib.Path(f"{TOOLS}/ProteinMPNN").exists():
    sh(f"git clone -q {MPNN_REPO} {TOOLS}/ProteinMPNN")
    sh(f"git -C {TOOLS}/ProteinMPNN checkout -q {MPNN_COMMIT}")

step("build se3 env (RFdiffusion: py3.9 / torch1.12+cu113 — covers sm_75)")
sh(f"{MM} create -y -p {SE3} -c conda-forge python=3.9 pip")
# CUDA 11.3 runtime libs (libcusparse.so.11 …) that dgl's C library dlopen()s.
sh(f"{MM} install -y -p {SE3} -c conda-forge cudatoolkit=11.3")
sh(f"{MM} run -p {SE3} pip install -q --no-input {SE3_TORCH} --extra-index-url {SE3_TORCH_INDEX}")
sh(f"{MM} run -p {SE3} pip install -q --no-input {SE3_DGL} -f {SE3_DGL_FIND}")
sh(f"{MM} run -p {SE3} pip install -q --no-input " + " ".join(f"'{p}'" for p in SE3_EXTRA_PIP))
# SE3-Transformer's own requirements (e3nn pin, dllogger, …), then the packages.
sh(f"{MM} run -p {SE3} pip install -q --no-input -r {TOOLS}/RFdiffusion/env/SE3Transformer/requirements.txt")
sh(f"{MM} run -p {SE3} pip install -q --no-input --no-deps {TOOLS}/RFdiffusion/env/SE3Transformer")
sh(f"{MM} run -p {SE3} pip install -q --no-input --no-deps -e {TOOLS}/RFdiffusion")

step("write se3 interpreter wrapper (sets LD_LIBRARY_PATH for dgl's CUDA libs)")
# Invoke the se3 python directly (not via `micromamba run`) so the explicit
# LD_LIBRARY_PATH reliably reaches the loader when dgl dlopen()s its CUDA deps.
wrapper = "/opt/se3_python.sh"
pathlib.Path(wrapper).write_text(
    "#!/bin/bash\n"
    f"export LD_LIBRARY_PATH={SE3_LD}:$LD_LIBRARY_PATH\n"
    "export DGLBACKEND=pytorch\n"
    f"exec {SE3}/bin/python \"$@\"\n"
)
os.chmod(wrapper, 0o755)

# Sanity: RFdiffusion importable + CUDA usable on the pinned T4 — via the wrapper, so the
# import-time dgl CUDA-lib load is exercised exactly as the real run will do it.
sh(f"{wrapper} -c \""
   "import torch, dgl, e3nn; "
   "print('se3 torch', torch.__version__, 'dgl', dgl.__version__, 'cuda', torch.cuda.is_available(), "
   "torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO-CUDA'); "
   "x=torch.zeros(4,device='cuda'); print('se3 cuda op ok', (x+1).sum().item())\"")

step("build boltz env (Boltz-2 + bindsight: py3.11 / torch2.2+cu118 — covers sm_75)")
sh(f"{MM} create -y -p {BOLTZ} -c conda-forge python=3.11 pip")
sh(f"{MM} run -p {BOLTZ} pip install -q --no-input {BOLTZ_TORCH} --index-url {BOLTZ_TORCH_INDEX}")
sh(f"{MM} run -p {BOLTZ} pip install -q --no-input '{BOLTZ_PIP}' biopython")
print("bindsight install source:", INSTALL_SOURCE, flush=True)
if BINDSIGHT_WHEEL_B64:
    # Install the exact tree that launched this run. Pinning a branch name would
    # still leave the GPU installing whatever that branch points at now, and an
    # unpushed commit would be invisible entirely.
    # The filename matters: pip reads the distribution, version and
    # compatibility tags out of it, and rejects a name it cannot parse.
    _whl = f"/tmp/{BINDSIGHT_WHEEL_NAME}"
    pathlib.Path(_whl).write_bytes(base64.b64decode(BINDSIGHT_WHEEL_B64))
    print("  wheel bytes:", pathlib.Path(_whl).stat().st_size, flush=True)
    sh(f"{MM} run -p {BOLTZ} pip install -q --no-input '{_whl}'")
else:
    sh(f"{MM} run -p {BOLTZ} pip install -q --no-input {BINDSIGHT_GIT}")
sh(f"{MM} run -p {BOLTZ} python -c \""
   "import bindsight; print('bindsight', bindsight.__version__, 'from', bindsight.__file__)\"")
sh(f"{MM} run -p {BOLTZ} python -c \""
   "import torch; print('boltz torch', torch.__version__, 'cuda', torch.cuda.is_available(), "
   "torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO-CUDA'); "
   "x=torch.zeros(4,device='cuda'); print('boltz cuda op ok', (x+1).sum().item())\"")

step("patch Boltz-2 precision for non-bf16 GPUs (T4 is sm_75; bf16 needs sm_80+)")
# Boltz-2 hardcodes precision="bf16-mixed" (main.py). bfloat16 needs compute
# capability 8.0+, and no free-tier GPU has it — the T4 this kernel pins is 7.5 —
# so force full fp32, which is what the boltz1 path already uses and is
# numerically safe. This patch stays necessary for as long as the free tier is
# pre-Ampere.
import glob as _glob  # noqa: E402

_bm = _glob.glob(f"{BOLTZ}/lib/python*/site-packages/boltz/main.py")[0]
_txt = pathlib.Path(_bm).read_text()
_patched = _txt.replace('precision=32 if model == "boltz1" else "bf16-mixed"', "precision=32")
assert _patched != _txt, "could not find Boltz-2 precision line to patch"
pathlib.Path(_bm).write_text(_patched)
print("patched", _bm, "-> precision=32")

step("materialise spec + target structure (embedded base64)")
spec_dir = pathlib.Path("/tmp/spec"); spec_dir.mkdir(parents=True, exist_ok=True)
for name, b64 in PAYLOAD.items():
    (spec_dir / name).write_bytes(base64.b64decode(b64))
    print("  wrote", name, (spec_dir / name).stat().st_size, "bytes")
print("  spec:", (spec_dir / "spec.json").read_text()[:400])

step("run job_exec (RFdiffusion -> ProteinMPNN under se3; Boltz-2 + orchestration under boltz)")
out_tmp = f"/tmp/{HANDLE_ID}.tar.gz"
job_env = {
    "BINDSIGHT_TOOLS_ROOT": TOOLS,
    "BINDSIGHT_DESIGN_PYTHON": wrapper,
}
sh(f"{MM} run -p {BOLTZ} python -m bindsight.runners.job_exec "
   f"{spec_dir}/spec.json {out_tmp}", env=job_env)

step("stage tarball to /kaggle/working (keep the output volume lean)")
pathlib.Path("/kaggle/working").mkdir(parents=True, exist_ok=True)
sh(f"cp {out_tmp} /kaggle/working/{HANDLE_ID}.tar.gz")
sz = pathlib.Path(f"/kaggle/working/{HANDLE_ID}.tar.gz").stat().st_size
print(f"\nDONE -> /kaggle/working/{HANDLE_ID}.tar.gz ({sz/1e6:.2f} MB)")
'''
