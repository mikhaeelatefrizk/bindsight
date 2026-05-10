"""Tests for the Jinja-based notebook builder."""

from __future__ import annotations

import json

import pytest
from jinja2.exceptions import UndefinedError

from bindsight.runners.notebook import (
    build_notebook,
    code_cell_from_template,
    markdown_cell,
    render_template,
    write_notebook,
)


def test_build_notebook_envelope_is_valid_jupyter() -> None:
    nb = build_notebook(
        cells=[markdown_cell("# hello"), code_cell_from_template("print({{ n }})", {"n": 42})],
        gpu="T4",
        title="x",
    )
    assert nb["nbformat"] == 4
    assert nb["metadata"]["accelerator"] == "GPU"
    assert nb["metadata"]["colab"]["gpuType"] == "T4"
    assert len(nb["cells"]) == 2


def test_render_template_strict_undefined_raises() -> None:
    with pytest.raises(UndefinedError):
        render_template("hello {{ name }}", {})


def test_render_template_works_with_context() -> None:
    out = render_template("hello {{ name }}", {"name": "world"})
    assert out == "hello world"


def test_code_cell_from_template_produces_jupyter_code_cell() -> None:
    cell = code_cell_from_template("import {{ pkg }}\nprint({{ pkg }})", {"pkg": "json"})
    assert cell["cell_type"] == "code"
    assert "json" in "".join(cell["source"])


def test_write_notebook_round_trip(tmp_path) -> None:
    nb = build_notebook(cells=[markdown_cell("# x")], gpu="A100", title="t")
    out = tmp_path / "nested" / "x.ipynb"
    written = write_notebook(nb, out)
    assert written == out
    parsed = json.loads(out.read_text())
    assert parsed["metadata"]["colab"]["gpuType"] == "A100"
