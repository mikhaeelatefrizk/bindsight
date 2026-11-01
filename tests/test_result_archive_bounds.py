# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Result readers reject compressed extended-header bombs before tar allocation."""

from __future__ import annotations

import gzip
import json
import tarfile
from pathlib import Path

import pytest
from click import ClickException

from bindsight import cli
from bindsight.benchmark.designer_bench import stage_binder_artifacts
from bindsight.design import _common
from bindsight.report import html
from tests.test_colab_result_import import assert_not_imported, make_jobs, result_files


def oversized_extended_archive(
    path: Path, kind: bytes, *, prefix: dict[str, bytes] | None = None
) -> None:
    """Only small headers exist; no oversized allocation/body is needed by the test."""
    chunks = []
    for name, data in (prefix or {}).items():
        member = tarfile.TarInfo(name)
        member.size = len(data)
        chunks.extend([member.tobuf(format=tarfile.GNU_FORMAT), data])
        chunks.append(b"\0" * (-len(data) % tarfile.BLOCKSIZE))
    bomb = tarfile.TarInfo("././@LongLink" if kind != tarfile.XHDTYPE else "pax")
    bomb.type = kind
    bomb.size = 8 * 1024**3 + 1
    chunks.extend([bomb.tobuf(format=tarfile.GNU_FORMAT), b"\0" * 1024])
    path.write_bytes(gzip.compress(b"".join(chunks)))
    assert path.stat().st_size < 4096


@pytest.fixture
def forbid_extended_parser(monkeypatch):
    def unsafe_parser_entered(*args, **kwargs):
        pytest.fail("tarfile reached an oversized extended-header parser before rejecting its size")

    # Both methods read header.size bytes before returning a logical member.
    # Their invocation would already cross the unsafe allocation boundary.
    monkeypatch.setattr(tarfile.TarInfo, "_proc_pax", unsafe_parser_entered)
    monkeypatch.setattr(tarfile.TarInfo, "_proc_gnulong", unsafe_parser_entered)


@pytest.mark.parametrize(
    "kind", [tarfile.XHDTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK]
)
def test_colab_rejects_compressed_extended_header_before_import_or_parser(
    tmp_path: Path, kind: bytes, forbid_extended_parser
) -> None:
    run, specs = make_jobs(tmp_path)
    files, _ = result_files(specs[0])
    archive = specs[0].with_name(specs[0].name.removesuffix(".spec.json") + ".tar.gz")
    oversized_extended_archive(archive, kind, prefix=files)
    before = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    stage = tmp_path / "direct-stage"
    stage.mkdir()
    with pytest.raises((tarfile.TarError, ValueError)):
        cli._read_colab_archive(archive, json.loads(specs[0].read_text()), stage)
    assert not list(stage.iterdir()), (
        "No imported artifact may be written before validation finishes"
    )
    with pytest.raises(ClickException, match="Cannot import Colab results"):
        cli._finalize_validate(run)
    assert_not_imported(run)
    assert {
        path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()
    } == before


def test_cache_metrics_and_archive_count_reject_header_bomb(
    tmp_path: Path, forbid_extended_parser
) -> None:
    design = tmp_path / "design"
    design.mkdir()
    archive = design / "result.tar.gz"
    oversized_extended_archive(archive, tarfile.XHDTYPE)
    destination = tmp_path / "metrics.jsonl"
    assert _common._archive_is_readable(archive) is False
    _common.extract_member(archive, "metrics.jsonl", destination)
    assert not destination.exists()
    assert cli._archive_carries_designs(archive) is False
    assert cli._count_designs(design) is None


def test_report_previews_and_benchmark_staging_reject_header_bomb(
    tmp_path: Path, forbid_extended_parser
) -> None:
    targets = tmp_path / "run/design/_targets"
    targets.mkdir(parents=True)
    archive = targets / "result.tar.gz"
    oversized_extended_archive(archive, tarfile.GNUTYPE_LONGNAME)
    assert html._binder_sequences(tmp_path / "run") == {}
    assert html._binder_structures(tmp_path / "run", ["binder"], budget=1024) == ({}, 0)
    with pytest.raises(tarfile.TarError):
        stage_binder_artifacts([archive], tmp_path / "benchmark")
    assert not list((tmp_path / "benchmark/binders").iterdir())


def test_revalidation_and_finalize_reject_header_before_extracting(
    tmp_path: Path, forbid_extended_parser, monkeypatch
) -> None:
    import bindsight.plugins

    run = tmp_path / "run"
    targets = run / "design/_targets"
    targets.mkdir(parents=True)
    target = {
        "uniprot": "P04626",
        "chain": "A",
        "residues": [10],
        "design_ranges": [[1, 50]],
        "structure_path": str(tmp_path / "target.pdb"),
    }
    archive = targets / (cli._target_artifact_stem(target) + ".tar.gz")
    oversized_extended_archive(archive, tarfile.XHDTYPE)
    monkeypatch.setattr(cli, "_top_targets", lambda directory: [target])
    monkeypatch.setattr(cli, "_gpu_type_from_run", lambda directory: None)
    monkeypatch.setattr(cli, "_working_tree_wheel", lambda *args: None)
    monkeypatch.setattr(bindsight.plugins, "get_runner", lambda *args, **kwargs: object())
    with pytest.raises(tarfile.TarError):
        cli._launch_revalidate(run, backend="mock", validator="boltz2")
    # Finalization logs corrupt target archives and produces no binder result.
    assert cli._finalize_validate(run) == 0
    assert not list((run / "validate").glob("*/complex.*"))
