# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reject ambiguous input identities before pandas mangling or inference."""

import gzip
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from bindsight.config import DEGParams
from bindsight.deg.pydeseq2_runner import PyDESeq2Runner

COUNTS = (
    "gene\t01\t02\t03\t04\t05\tsample.1\n0001\t11\t12\t13\t14\t15\t16\nNA\t21\t22\t23\t24\t25\t26\n"
)
DESIGN = (
    "sample\tcondition\n01\tnormal\n02\tnormal\n03\tnormal\n04\ttumor\n05\ttumor\nsample.1\ttumor\n"
)


def _write(path: Path, content: str, compressed: bool) -> Path:
    raw = content.encode("utf-8")
    path.write_bytes(gzip.compress(raw, mtime=0) if compressed else raw)
    return path


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize(
    ("counts", "design", "message"),
    [
        # Pandas would invent 01.2 because a literal 01.1 also exists.
        (COUNTS.replace("01\t02\t03", "01\t01\t01.1"), DESIGN, "duplicate column"),
        (COUNTS.replace("gene\t01", "01\t01"), DESIGN, "duplicate column"),
        (COUNTS + "0001\t0\t0\t0\t0\t0\t0\n", DESIGN, "gene IDs must be unique"),
        (COUNTS, DESIGN + "01\tnormal\n", "sample IDs must be unique"),
        (COUNTS, DESIGN + "absent\tnormal\nabsent\ttumor\n", "sample IDs must be unique"),
        (COUNTS, DESIGN.replace("condition", "sample"), "duplicate column"),
        (COUNTS.replace("gene\t01", "gene\t "), DESIGN, "nonblank sample/factor"),
        (COUNTS.replace("0001\t", "\t"), DESIGN, "gene IDs must be nonblank"),
        (COUNTS, DESIGN.replace("01\tnormal", " \tnormal"), "sample IDs must be nonblank"),
    ],
)
def test_ambiguous_ids_fail_before_alignment_filtering_or_inference(
    tmp_path: Path, compressed: bool, counts: str, design: str, message: str
) -> None:
    suffix = ".tsv.gz" if compressed else ".tsv"
    counts_path = _write(tmp_path / f"counts{suffix}", counts, compressed)
    design_path = _write(tmp_path / f"design{suffix}", design, compressed)
    runner = PyDESeq2Runner(
        DEGParams(
            design_formula="~ condition",
            contrast=["condition", "tumor", "normal"],
            min_count=10,
            min_replicates=3,
        )
    )
    with patch.object(runner, "_run_pydeseq2") as fit:
        with pytest.raises(ValueError, match=message):
            runner.run(counts_path, design_path, tmp_path / "output.parquet")
        fit.assert_not_called()
    assert not (tmp_path / "output.parquet").exists()


@pytest.mark.parametrize("compressed", [False, True])
def test_literal_ids_and_legitimate_suffixes_preserve_counts_and_alignment(
    tmp_path: Path, compressed: bool
) -> None:
    suffix = ".tsv.gz" if compressed else ".tsv"
    # Blank first headings are the conventional unnamed dataframe index.
    counts_path = _write(
        tmp_path / f"counts{suffix}", COUNTS.replace("gene\t", "\t", 1), compressed
    )
    design_path = _write(
        tmp_path / f"design{suffix}", DESIGN.replace("sample\t", "\t", 1), compressed
    )
    counts = PyDESeq2Runner.load_counts(counts_path)
    design = PyDESeq2Runner.load_design(design_path, ["condition"])
    assert counts.index.tolist() == ["0001", "NA"]
    assert counts.columns.tolist() == ["01", "02", "03", "04", "05", "sample.1"]
    assert design.index.tolist() == counts.columns.tolist()
    expected = pd.DataFrame(
        [[11, 12, 13, 14, 15, 16], [21, 22, 23, 24, 25, 26]],
        index=counts.index,
        columns=counts.columns,
    )
    pd.testing.assert_frame_equal(counts, expected)
    assert design.condition.tolist() == ["normal"] * 3 + ["tumor"] * 3
