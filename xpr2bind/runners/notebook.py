"""Helpers for building Colab/Kaggle notebooks programmatically.

The notebook format is just JSON; we construct it as Python dicts and serialize
with the standard library, instead of carrying a heavy ``nbformat`` dependency.
This keeps the install lean and CI fast.

A notebook has a small fixed envelope and a list of cells. Each cell is either:

- ``code`` — a list of source lines + execution metadata
- ``markdown`` — a list of source lines

We emit Colab-flavored notebooks (the ``colab`` metadata block tells Colab
which runtime to provision; e.g. ``GPU`` with ``T4`` or ``A100``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from jinja2 import BaseLoader, Environment, StrictUndefined

NotebookGPU = Literal["T4", "L4", "A100", "V100"]


def _code_cell(src: str | list[str]) -> dict:
    if isinstance(src, str):
        src = src.splitlines(keepends=True)
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": src,
    }


def _markdown_cell(src: str | list[str]) -> dict:
    if isinstance(src, str):
        src = src.splitlines(keepends=True)
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": src,
    }


def build_notebook(
    *,
    cells: list[dict],
    gpu: NotebookGPU = "T4",
    title: str = "xpr2bind job",
) -> dict:
    """Return a Jupyter v4 notebook dict with the given cells and Colab GPU runtime.

    Pass the result to :func:`json.dumps` (or use :func:`write_notebook`) to
    save as ``.ipynb``.
    """
    return {
        "nbformat": 4,
        "nbformat_minor": 0,
        "metadata": {
            "colab": {
                "name": title,
                "provenance": [],
                "gpuType": gpu,
                "machine_shape": "hm",
            },
            "kernelspec": {
                "display_name": "Python 3",
                "name": "python3",
                "language": "python",
            },
            "accelerator": "GPU",
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }


def write_notebook(notebook: dict, path: Path) -> Path:
    """Write a notebook dict to ``path`` as JSON. Creates parent dirs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notebook, indent=1))
    return path


def render_template(template_str: str, context: dict) -> str:
    """Render a Jinja2 template string against ``context`` with strict undefined.

    Strict-undefined means a missing variable raises immediately rather than
    silently producing empty output — important when the template generates
    code that will run on a remote GPU we can't easily debug.
    """
    env = Environment(
        loader=BaseLoader(),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.from_string(template_str).render(**context)


def code_cell_from_template(template_str: str, context: dict) -> dict:
    """Convenience: render a Jinja template and wrap as a code cell."""
    return _code_cell(render_template(template_str, context))


def markdown_cell(src: str | list[str]) -> dict:
    """Public alias for the markdown cell constructor."""
    return _markdown_cell(src)
