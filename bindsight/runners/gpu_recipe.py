# SPDX-License-Identifier: AGPL-3.0-or-later
"""One recorded scientific-runtime recipe for every managed Linux GPU backend."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bindsight import archive_bounds
from bindsight.runners import dgl_runtime_wheel, installer_security, tools
from bindsight.runners.boltz_runtime_wheel import RUNTIME_VERSION as _BOLTZ_RUNTIME_VERSION

BOLTZ_RUNTIME_VERSION = _BOLTZ_RUNTIME_VERSION

MIN_MEMORY_MIB = 15360
MIN_FREE_MEMORY_MIB = 14900
SETUP_DISK_BYTES = 60 * 2**30

# The supported-Python T4 probe passed CUDA, local DGL reduction, imports and
# nonzero SE3 forward/equivariance checks. Full model validation is separate.
SE3_PYTHON = "3.11.18"
SE3_TORCH = "2.14.1+cu126"
TORCH_WHEEL = (
    "https://download.pytorch.org/whl/cu126/"
    "torch-2.14.1%2Bcu126-cp311-cp311-manylinux_2_28_x86_64.whl"
    "#sha256=acffcaa38f734dc04ba243d6192875a6ca185a2d2f19aac07fd16dc1aa7c926f"
)
SE3_DGL = dgl_runtime_wheel.RUNTIME_VERSION
SE3_DGL_UPSTREAM_WHEEL = dgl_runtime_wheel.UPSTREAM_URL
SE3_DGL_PATCHED_SHA256 = dgl_runtime_wheel.PATCHED_SHA256
SE3_NUMPY = "1.23.5"
SE3_E3NN = "0.3.3"
E3NN_LOADER_SHA256 = "e32eef83faf0878ccd87cf77bc4d8cb99ea95612054822326f896d30ac3cbc58"
E3NN_CONSTANTS_SHA256 = "279fb1f7844b2b85df092550bf7854a70fe3b427b312672f6a1e1fef0a786876"
SE3_EXTRA_PIP = (
    "hydra-core==1.3.8",
    "pyrsistent",
    "omegaconf==2.3.0",
    "icecream",
    "scipy==1.13.1",
    f"numpy=={SE3_NUMPY}",
    "opt_einsum==3.4.0",
    "opt_einsum_fx==0.1.4",
    "decorator==5.1.1",
    f"e3nn=={SE3_E3NN}",
)
# Keep CUDA 11 distributions outside Python's environment: their headers
# otherwise overwrite Torch's CUDA 12 files. DGL uses only these three packages.
CUDA11_PIP = (
    "nvidia-cuda-runtime-cu11==11.8.89",
    "nvidia-cusparse-cu11==11.7.5.86",
    "nvidia-cublas-cu11==11.11.3.6",
)
CUDA12_CURAND_SHA256 = "12411c1e921cd3cac4e0d2f58024a3e6bbb7cea584d5cd768ad908ec762c5545"
BOLTZ_PYTHON = "3.11.18"
BOLTZ_TORCH = SE3_TORCH
BOLTZ_NUMPY = "1.26.4"
BOLTZ_TRIFAST = "0.1.11"
MODES = ("design_and_validate", "validate_only")


def recipe() -> dict[str, Any]:
    """Fingerprint exact runtime controls without implying numerical equivalence."""
    runtime = Path(__file__).with_name("gpu_runtime.py")
    body: dict[str, Any] = {
        "version": 3,
        "designer": "rfdiff_mpnn",
        "validator": "boltz2",
        "rfdiffusion_commit": tools.RFDIFF_COMMIT,
        "proteinmpnn_commit": tools.PROTEINMPNN_COMMIT,
        "boltz": tools.BOLTZ_PIP,
        "boltz_runtime": BOLTZ_RUNTIME_VERSION,
        "se3": {
            "python": SE3_PYTHON,
            "torch": SE3_TORCH,
            "dgl": SE3_DGL,
            "dgl_upstream_sha256": dgl_runtime_wheel.UPSTREAM_SHA256,
            "dgl_patched_sha256": SE3_DGL_PATCHED_SHA256,
            "numpy": SE3_NUMPY,
            "e3nn": SE3_E3NN,
            "private_cuda11": list(CUDA11_PIP),
        },
        "validation": {
            "python": BOLTZ_PYTHON,
            "torch": BOLTZ_TORCH,
            "numpy": BOLTZ_NUMPY,
            "trifast": BOLTZ_TRIFAST,
        },
        "package_installer": {
            "uv": installer_security.UV_VERSION,
            "sha256": installer_security.UV_ARCHIVE_SHA256,
            "certifi": installer_security.CERTIFI_REQUIREMENT,
            "source_sha256": hashlib.sha256(
                Path(installer_security.__file__).read_bytes()
            ).hexdigest(),
        },
        "security_boundary": {
            "dgl": "Authenticated downstream wheel removes distributed Python RPC; local graph and native payload bytes retained",
            "dgl_remediated_advisory": dgl_runtime_wheel.ADVISORY,
            "dgl_native_rpc": "Present in unchanged native libraries; unrelated local-file deserialization remains",
            "e3nn_loader": "Verified constants; scoped slice allowlist; weights_only remains enabled",
            "boltz_loader": "Publisher-pinned checkpoints; same authenticated handle; scoped fixed globals; weights_only=True",
        },
        "checkpoint_expected_sha256": tools.RFDIFF_WEIGHT_SHA256,
        "minimum_memory_mib": MIN_MEMORY_MIB,
        "minimum_free_memory_mib": MIN_FREE_MEMORY_MIB,
        "minimum_setup_disk_bytes": SETUP_DISK_BYTES,
        "installer_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
        "recipe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "implementation_helpers_sha256": {
            "archive_bounds.py": hashlib.sha256(
                Path(archive_bounds.__file__).read_bytes()
            ).hexdigest(),
            **{
                name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                for name in (
                    "boltz_runtime_wheel.py",
                    "dgl_runtime_wheel.py",
                    "boltz_assets.py",
                    "boltz_checkpoint.py",
                    "boltz_msa.py",
                    "job_exec.py",
                    "tools.py",
                    "boltz_compat.py",
                )
            },
        },
    }
    body["id"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body
