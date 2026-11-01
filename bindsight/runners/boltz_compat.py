# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run pinned Boltz with fp32 on GPUs lacking native bfloat16.

Boltz 2.0.3 selects ``bf16-mixed`` in its Trainer call without a CLI precision
option. The measured Kaggle run replaced that argument with 32. Apply the same
change only to this subprocess's Trainer call, leaving installed files intact.
GPU and Boltz imports stay inside ``main`` so CPU orchestration can import this
module. This compatibility shim is not evidence that a particular model fits.
"""

from __future__ import annotations

import hashlib
import inspect
import sys
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

from bindsight.runners.boltz_assets import prepare_boltz_assets
from bindsight.runners.boltz_runtime_wheel import RUNTIME_VERSION, UPSTREAM_MAIN_SHA256
from bindsight.validate.boltz2 import PINNED_BOLTZ2_VERSION

_PRECISION_CALL = 'precision=32 if model == "boltz1" else "bf16-mixed"'


def configure_precision(boltz_main: Any, torch: Any, *, boltz_version: str) -> str:
    """Adapt the inspected pinned Trainer call; refuse an unknown source shape."""
    if boltz_version not in {PINNED_BOLTZ2_VERSION, RUNTIME_VERSION}:
        raise RuntimeError(
            f"Boltz compatibility requires boltz=={PINNED_BOLTZ2_VERSION}; "
            f"found {boltz_version}. Install the pinned validator in its GPU environment."
        )
    if boltz_version == RUNTIME_VERSION:
        source = getattr(boltz_main, "__file__", None)
        if (
            not source
            or hashlib.sha256(Path(source).read_bytes()).hexdigest() != UPSTREAM_MAIN_SHA256
        ):
            raise RuntimeError(
                "The downstream Boltz implementation differs from verified upstream 2.0.3"
            )
    if not torch.cuda.is_available():
        raise RuntimeError("Boltz GPU validation needs a CUDA-enabled PyTorch environment.")
    if all(torch.cuda.get_device_capability(i) >= (8, 0) for i in range(torch.cuda.device_count())):
        return "bf16-mixed"

    callback = boltz_main.predict.callback
    if _PRECISION_CALL not in inspect.getsource(callback):
        raise RuntimeError(
            "The installed Boltz precision code differs from the inspected 2.0.3 source. "
            "Refusing an unverified compatibility change; use a clean pinned install."
        )
    original_trainer = boltz_main.Trainer

    def trainer(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("precision") == "bf16-mixed":
            kwargs["precision"] = 32
        return original_trainer(*args, **kwargs)

    boltz_main.Trainer = trainer
    return "32"


def main(argv: list[str] | None = None) -> int:
    """Invoke Boltz's CLI in this prepared GPU interpreter."""
    import torch

    boltz_main = import_module("boltz.main")
    installed = version("boltz")
    precision = configure_precision(boltz_main, torch, boltz_version=installed)
    # Validate cached bytes again at use, including when setup happened earlier.
    # Keep the upstream model implementation intact while replacing its unpinned
    # downloader and unrestricted archive extraction with authenticated assets.
    setattr(boltz_main, "download_boltz2", prepare_boltz_assets)  # noqa: B010 - dynamic module API
    print(f"bindsight: Boltz {installed} precision={precision}", flush=True)
    boltz_main.cli(args=sys.argv[1:] if argv is None else argv)
    return 0


if __name__ == "__main__":  # pragma: no cover - needs an actual GPU environment
    raise SystemExit(main())
