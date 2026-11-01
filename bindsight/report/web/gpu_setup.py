# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web job adapter for the shared managed GPU runtime provisioner."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from bindsight.report.web.gpu import recipe
from bindsight.report.web.workspace import write_json
from bindsight.runners import gpu_runtime
from bindsight.runners.gpu_runtime import smoke as smoke
from bindsight.runners.gpu_runtime import stop_children as stop_children
from bindsight.runners.source_wheel import find_repo_root

LOG = logging.getLogger(__name__)


def install(config: dict[str, Any], job_directory: Path, *, check_recipe: bool = False) -> None:
    """Retain the web's recipe approval and progress contract around shared setup."""
    if config["recipe_id"] != recipe()["id"]:
        raise RuntimeError("The requested GPU recipe no longer matches this installed release.")
    source = Path(config["source"]) if config.get("source") else find_repo_root()
    if source is None:
        from bindsight import __version__
        from bindsight.runners.release_bootstrap import download_release_wheel

        source = download_release_wheel(__version__, Path(config["gpu_root"]) / "source")
    result = gpu_runtime.provision(
        Path(config["gpu_root"]),
        source=source,
        mode=config.get("mode", "design_and_validate"),
        gpu_index=config["gpu_index"],
        check_only=check_recipe,
        progress=lambda phase: write_json(job_directory / "progress.json", {"phase": phase}),
    )
    if check_recipe:
        write_json(job_directory / "recipe_check.json", result)
    else:
        output = Path(config["out_dir"])
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "gpu_setup_receipt.json", result)


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
