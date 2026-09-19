# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the HTML report renderer."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from bindsight.provenance import (
    InputRef,
    OutputRef,
    StageRecord,
    ToolRef,
    new_manifest,
)
from bindsight.report.html import (
    _deg_thresholds,
    _df_to_records,
    _significance_basis,
    render_run,
)


def _make_run(tmp_path: Path) -> Path:
    """Build a minimal but realistic run directory for the renderer."""
    run = tmp_path / "run"
    (run / "deg").mkdir(parents=True)
    (run / "targets").mkdir(parents=True)
    (run / "epitopes").mkdir(parents=True)

    deg = pd.DataFrame(
        {
            "gene_id": ["ENSG00000141736", "ENSG00000146648", "ENSG00000142208"],
            "symbol": ["ERBB2", "EGFR", "AKT1"],
            "log2fc": [3.5, 2.8, 0.1],
            "lfc_se": [0.5, 0.5, 0.4],
            "stat": [7.0, 5.6, 0.25],
            "pvalue": [1e-10, 1e-7, 0.8],
            "padj": [1e-9, 1e-6, 0.95],
            "baseMean": [800.0, 600.0, 500.0],
            "contrast": ["condition__tumor_vs_normal"] * 3,
            "significant": [True, True, False],
        }
    )
    deg.to_parquet(run / "deg" / "results.parquet", index=False)

    candidates = pd.DataFrame(
        {
            "gene_id": ["ENSG00000141736", "ENSG00000146648"],
            "symbol": ["ERBB2", "EGFR"],
            "uniprot_id": ["P04626", "P00533"],
            "log2fc": [3.5, 2.8],
            "padj": [1e-9, 1e-6],
            "tractable_modalities": ["Antibody", "Antibody"],
            "open_targets_status": ["bundled_fallback", "bundled_fallback"],
            "n_safety_events": [2, 1],
            "is_surface": [True, True],
            "alphafold_structure_path": ["", ""],
            "has_alphafold_structure": [False, False],
            "rank": [1, 2],
            "rank_in_top_n": [True, True],
        }
    )
    candidates.to_parquet(run / "targets" / "candidates.parquet", index=False)

    epitopes = pd.DataFrame(
        {
            "gene_id": ["ENSG00000141736", "ENSG00000146648"],
            "symbol": ["ERBB2", "EGFR"],
            "uniprot_id": ["P04626", "P00533"],
            "structure_path": ["", ""],
            "site_id": [None, None],
            "chain": ["A", "A"],
            "residues": [[], []],
            "score": [None, None],
            "seed_pdb_path": [None, None],
            "epitope_status": ["surface_bind_not_configured"] * 2,
        }
    )
    epitopes.to_parquet(run / "epitopes" / "epitopes.parquet", index=False)

    # Manifest
    counts = run / "counts.tsv"
    counts.write_text("g\ts1\n1\t10\n")
    m = new_manifest(name="renderer-test")
    m.append(
        StageRecord(
            name="deg",
            tool=ToolRef(name="pydeseq2", version="0.5.4", license="MIT"),
            inputs=[InputRef(role="counts", path="counts.tsv", sha256="0" * 64, bytes=10)],
            outputs=[
                OutputRef(role="deg_table", path="deg/results.parquet", sha256="1" * 64, bytes=100)
            ],
        )
    )
    m.stages[0].mark_completed()
    m.append(
        StageRecord(
            name="discover",
            tool=ToolRef(name="bindsight/0.0.1.dev0", version="0.0.1.dev0", license="MIT"),
        )
    )
    m.stages[1].mark_completed()
    m.write(run / "run_manifest.jsonld")

    return run


def test_render_run_produces_self_contained_html(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    out = render_run(run)

    assert out.exists()
    assert out.name == "report.html"
    assert out.stat().st_size > 5000

    text = out.read_text(encoding="utf-8")
    assert "<title>bindsight report" in text
    assert ":root {" in text  # CSS embedded
    assert "data:image/png;base64," in text  # volcano embedded
    assert "ERBB2" in text  # candidate row rendered
    assert "P04626" in text
    # Limitations section is always rendered (honest scope of discovery).
    assert "<h2>Limitations</h2>" in text
    assert "cell-surface protein abundance" in text
    # The cell-composition caveat. Its wording used to be tumour-specific, so a
    # drug-treatment run came back describing tumour purity; it now states the
    # general case and names the tumour instance as one example. Assert on the
    # general clause, so the test tracks the limitation rather than one phrasing.
    assert "cannot tell whether a transcript" in text
    assert "different mixtures of cells" in text


def test_render_run_handles_missing_optional_files(tmp_path: Path) -> None:
    """Renderer should not crash if some artifacts are missing."""
    run = tmp_path / "skinny"
    (run / "deg").mkdir(parents=True)
    out = render_run(run)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    # No crash; report explains the empty state
    assert "<title>bindsight report" in text


def test_render_run_custom_out_path(tmp_path: Path) -> None:
    run = _make_run(tmp_path)
    custom_out = tmp_path / "elsewhere" / "my_report.html"
    out = render_run(run, custom_out)
    assert out == custom_out
    assert out.exists()


def test_df_to_records_handles_none() -> None:
    assert _df_to_records(None, ["x"]) == []


def test_df_to_records_formats_floats() -> None:
    df = pd.DataFrame({"a": [3.14159, 0.000001, 1.0]})
    rows = _df_to_records(df, ["a"])
    # All values formatted as %.3g
    assert isinstance(rows[0]["a"], str)
    assert "3.14" in rows[0]["a"]


def test_manifest_round_trip_through_renderer(tmp_path: Path) -> None:
    """The manifest written by the pipeline survives parsing in the renderer."""
    run = _make_run(tmp_path)
    out = render_run(run)
    manifest = json.loads((run / "run_manifest.jsonld").read_text(encoding="utf-8"))
    assert manifest["stages"][0]["name"] == "deg"
    text = out.read_text(encoding="utf-8")
    assert "deg" in text
    assert "pydeseq2" in text


# ---------------------------------------------------------------------------
# The report omitted the run's actual output
# ---------------------------------------------------------------------------
class TestTheReportShowsTheDesignedBinders:
    """A run that designed forty binders rendered a report containing none.

    `--include-binders` was accepted, documented as embedding designed binder
    structures, recorded in the manifest's params, and never passed to
    `render_run` — which had no such parameter and never read the ranking at
    all. The paper-style HTML covered the discovery half and stopped.
    """

    @staticmethod
    def _run(tmp_path: Path) -> Path:
        run = tmp_path / "run"
        (run / "rank").mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "rank": 1,
                    "binder_id": "P32970_binder_6_seq0",
                    "symbol": "CD70",
                    "target_uniprot": "P32970",
                    "iptm": 0.946,
                    "pae_interaction": 3.3,
                    "score": 0.937,
                    "passes_thresholds": "pass",
                },
                {
                    "rank": 2,
                    "binder_id": "Q16790_binder_0_seq1",
                    "symbol": "CA9",
                    "target_uniprot": "Q16790",
                    "iptm": 0.167,
                    "pae_interaction": 28.0,
                    "score": 0.201,
                    "passes_thresholds": "fail",
                },
            ]
        ).to_parquet(run / "rank" / "ranking.parquet", index=False)
        return run

    def test_the_ranked_binders_appear_without_any_flag(self, tmp_path: Path) -> None:
        """The table is the run's output, not an optional extra."""
        from bindsight.report import render_run

        html = render_run(self._run(tmp_path)).read_text(encoding="utf-8")
        assert "Designed binders" in html
        assert "P32970_binder_6_seq0" in html
        assert "Q16790_binder_0_seq1" in html
        assert "0.946" in html

    def test_sequences_are_embedded_only_when_asked_for(self, tmp_path: Path) -> None:
        import tarfile

        run = self._run(tmp_path)
        targets = run / "design" / "_targets"
        targets.mkdir(parents=True)
        fasta = tmp_path / "P32970_binder_6_seq0.fasta"
        fasta.write_text(">P32970_binder_6_seq0\nMKTAYIAKQRQISFVKSHFSRQ\n")
        with tarfile.open(targets / "P32970.tar.gz", "w:gz") as tf:
            tf.add(fasta, arcname="design/P32970_binder_6_seq0.fasta")

        from bindsight.report import render_run

        plain = render_run(run, run / "plain.html").read_text(encoding="utf-8")
        assert "MKTAYIAKQRQISFVKSHFSRQ" not in plain
        assert "--include-binders" in plain, "the report should say the flag exists"

        withseq = render_run(run, run / "withseq.html", include_binders=True).read_text(
            encoding="utf-8"
        )
        assert "MKTAYIAKQRQISFVKSHFSRQ" in withseq

    def test_a_run_without_designs_says_so(self, tmp_path: Path) -> None:
        from bindsight.report import render_run

        run = tmp_path / "empty"
        run.mkdir()
        html = render_run(run).read_text(encoding="utf-8")
        assert "No designed binders in this run" in html

    def test_the_cli_flag_reaches_the_renderer(self, tmp_path: Path) -> None:
        """The regression was "the flag existed and changed nothing", and this
        test asserted only that ``render_run`` has the parameter — which is
        exactly the state the regression was in: a signature that accepts a value
        and ignores it would pass.

        ``test_sequences_are_embedded_only_when_asked_for`` already drives the
        renderer directly, so what is checked here is the half nothing else
        covers: that ``bindsight report --include-binders`` actually reaches it.
        """
        import tarfile

        from click.testing import CliRunner

        from bindsight.cli import main

        run = self._run(tmp_path)
        targets = run / "design" / "_targets"
        targets.mkdir(parents=True)
        fasta = tmp_path / "P32970_binder_6_seq0.fasta"
        fasta.write_text(">P32970_binder_6_seq0\nMKTAYIAKQRQISFVKSHFSRQ\n")
        with tarfile.open(targets / "P32970.tar.gz", "w:gz") as tf:
            tf.add(fasta, arcname="design/P32970_binder_6_seq0.fasta")

        runner = CliRunner()
        assert runner.invoke(main, ["report", str(run)]).exit_code == 0
        without = (run / "report.html").read_text(encoding="utf-8")

        assert runner.invoke(main, ["report", str(run), "--include-binders"]).exit_code == 0
        with_sequences = (run / "report.html").read_text(encoding="utf-8")

        assert "MKTAYIAKQRQISFVKSHFSRQ" not in without
        assert "MKTAYIAKQRQISFVKSHFSRQ" in with_sequences, (
            "`report --include-binders` did not reach the renderer, which is the "
            "defect this test is named for"
        )


class TestTheComplexesTravelInsideTheReport:
    """The report draws the predicted complexes, and stays one file.

    It did not, and the reason given in ``html.py`` was that "a structure viewer
    needs a script from a CDN". That was never true here: 3Dmol.js is vendored
    into the package. The real constraint is size, and a budget is the honest
    form of it -- with the report saying what it left out, because a report that
    silently showed three of twenty would be the defect this project keeps
    removing, wearing a size limit as an excuse.
    """

    @staticmethod
    def _run_with_structures(tmp_path: Path, n: int = 3) -> Path:
        """A run whose design archives hold complexes, as a real one does."""
        import tarfile

        run = tmp_path / "run"
        (run / "rank").mkdir(parents=True)
        ids = [f"P32970_binder_{i}_seq0" for i in range(n)]
        pd.DataFrame(
            [
                {
                    "rank": i + 1,
                    "binder_id": bid,
                    "symbol": "CD70",
                    "target_uniprot": "P32970",
                    "iptm": 0.9 - i / 100,
                    "pae_interaction": 3.3,
                    "score": 0.9 - i / 100,
                    "passes_thresholds": "pass",
                }
                for i, bid in enumerate(ids)
            ]
        ).to_parquet(run / "rank" / "ranking.parquet", index=False)

        targets = run / "design" / "_targets"
        targets.mkdir(parents=True)
        staging = tmp_path / "staging"
        staging.mkdir()
        with tarfile.open(targets / "P32970.tar.gz", "w:gz") as tf:
            for bid in ids:
                cif = staging / f"{bid}_model_0.cif"
                cif.write_text(f"data_{bid}\n_entry.id {bid}\n", encoding="utf-8")
                tf.add(cif, arcname=f"validate/{bid}/{bid}_model_0.cif")
        return run

    def test_the_structures_and_the_viewer_are_in_the_file(self, tmp_path: Path) -> None:
        from bindsight.report import render_run

        html = render_run(self._run_with_structures(tmp_path)).read_text(encoding="utf-8")

        assert "BINDSIGHT_STRUCTURES" in html, "the report carries no structures"
        assert "createViewer" in html, "the report carries no viewer"
        assert "data-binder-viewer" in html, "the report has nowhere to draw"
        for i in range(3):
            assert f"P32970_binder_{i}_seq0" in html

    def test_it_stays_one_file(self, tmp_path: Path) -> None:
        """Self-contained is the whole point of this renderer.

        The viewer is inlined rather than linked precisely so that embedding it
        does not turn one file into a directory.
        """
        from bindsight.report import render_run

        html = render_run(self._run_with_structures(tmp_path)).read_text(encoding="utf-8")

        external = re.findall(r"<(?:script|link|img)[^>]*(?:src|href)=\"(?!#)(?!data:)", html)
        assert not external, f"the report references {len(external)} external file(s)"

    def test_turning_it_off_leaves_the_numbers(self, tmp_path: Path) -> None:
        """``--no-embed-structures`` is for a small file, not a lesser one."""
        from bindsight.report import render_run

        run = self._run_with_structures(tmp_path)
        big = render_run(run, tmp_path / "big.html").read_text(encoding="utf-8")
        small = render_run(run, tmp_path / "small.html", embed_structures=False).read_text(
            encoding="utf-8"
        )

        assert "BINDSIGHT_STRUCTURES" not in small
        assert "createViewer" not in small
        assert len(small) < len(big)
        # The binder table is a run output, not part of the viewer.
        assert "P32970_binder_0_seq0" in small

    @staticmethod
    def _collapse(page: str) -> str:
        """Jinja re-wraps the sentence; compare on words, not on line breaks."""
        return " ".join(page.split())

    def test_a_budget_that_cannot_hold_everything_says_so(self, tmp_path: Path) -> None:
        """Silently showing a subset is the failure this guards.

        The budget is set from the measured sizes to admit exactly two of
        three, and the assertion is on the sentence the reader sees, with its
        numbers. What this replaced ended in
        ``assert "more are in" in page or "structures_omitted" not in page``.
        ``structures_omitted`` is a Jinja variable name and never survives into
        rendered output, so the right disjunct was always true and the
        assertion could not fail -- it passed while the report said nothing.
        """
        from bindsight.report import html as html_mod
        from bindsight.report import render_run

        run = self._run_with_structures(tmp_path, n=3)
        order = [f"P32970_binder_{i}_seq0" for i in range(3)]

        everything, none_left = html_mod._binder_structures(run, order, budget=10**9)
        assert len(everything) == 3, "the fixture lost a structure"
        assert none_left == 0, "a budget of a gigabyte still omitted something"

        sizes = [len(everything[b].encode("utf-8")) for b in order]
        budget = sizes[0] + sizes[1]
        embedded, omitted = html_mod._binder_structures(run, order, budget=budget)
        assert sorted(embedded) == sorted(order[:2]), "the budget did not admit exactly two"
        assert omitted == 1

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(html_mod, "_STRUCTURE_BUDGET_BYTES", budget)
            page = self._collapse(render_run(run).read_text(encoding="utf-8"))

        assert "The 2 that fit are embedded, best-ranked first; 1 more is in" in page
        assert "design/_targets/" in page
        # The two it kept are named in the picker; the third is not.
        assert f'value="{order[0]}"' in page
        assert f'value="{order[1]}"' in page
        assert f'value="{order[2]}"' not in page

    def test_a_budget_that_holds_nothing_still_says_so(self, tmp_path: Path) -> None:
        """The section used to vanish in silence when nothing fit.

        ``if spent + cost > budget and embedded: break`` embedded the first
        structure whatever its size, which hid this case: there was always at
        least one complex, so nobody noticed that zero would render no heading,
        no explanation and no pointer to where the structures went. With the
        budget honoured strictly that case is reachable, so the report has to
        speak for it.
        """
        from bindsight.report import html as html_mod
        from bindsight.report import render_run

        run = self._run_with_structures(tmp_path, n=3)
        order = [f"P32970_binder_{i}_seq0" for i in range(3)]

        embedded, omitted = html_mod._binder_structures(run, order, budget=1)
        assert embedded == {}, "a one-byte budget embedded a structure"
        assert omitted == 3

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(html_mod, "_STRUCTURE_BUDGET_BYTES", 1)
            page = self._collapse(render_run(run).read_text(encoding="utf-8"))

        assert "The complexes themselves" in page, "the section disappeared silently"
        assert "None are embedded here." in page
        assert "3 predicted complexes" in page
        assert "design/_targets/" in page
        # No viewer, because there is nothing for it to draw.
        assert "BINDSIGHT_STRUCTURES" not in page
        assert "data-binder-picker" not in page

    def test_an_oversized_structure_does_not_cost_the_ones_below_it(self, tmp_path: Path) -> None:
        """``break`` charged every lower-ranked complex for one large one.

        The loop stopped at the first structure that did not fit, so a small
        complex ranked below a large one was dropped with room to spare: the
        reader lost it for no reason and the report came out smaller than its
        own budget allowed.
        """
        import tarfile

        from bindsight.report import html as html_mod

        run = self._run_with_structures(tmp_path, n=3)
        order = [f"P32970_binder_{i}_seq0" for i in range(3)]

        # Re-write the archive so the middle-ranked complex is the large one.
        targets = run / "design" / "_targets"
        archives = sorted(targets.glob("*.tar.gz"))
        assert archives, "the fixture wrote no design archive"
        staging = tmp_path / "restage"
        staging.mkdir()
        with tarfile.open(archives[0], encoding="utf-8") as tf:
            tf.extractall(staging, filter="data")
        cifs = sorted(staging.rglob("*.cif"))
        assert len(cifs) == 3, [p.name for p in cifs]
        small = cifs[0].read_text(encoding="utf-8")
        for path in cifs:
            stem = path.name.removesuffix("_model_0.cif")
            path.write_text(small * (40 if stem == order[1] else 1), encoding="utf-8")
        archives[0].unlink()
        with tarfile.open(archives[0], "w:gz") as tf:
            for path in sorted(staging.rglob("*.cif")):
                tf.add(path, arcname=f"T/{path.name}")

        one = len(small.encode("utf-8"))
        embedded, omitted = html_mod._binder_structures(run, order, budget=one * 3)

        assert order[1] not in embedded, "the oversized complex was embedded anyway"
        assert order[2] in embedded, (
            "the smallest-ranked complex fit the budget but was dropped because "
            "an oversized one outranked it"
        )
        assert sorted(embedded) == sorted([order[0], order[2]])
        assert omitted == 1

    def test_a_structure_cannot_close_the_script_that_carries_it(self, tmp_path: Path) -> None:
        """mmCIF has no reason to contain "</script>", which is exactly when an
        assumption like that stops being checked."""
        import tarfile

        run = tmp_path / "hostile"
        (run / "rank").mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "rank": 1,
                    "binder_id": "X_binder_0_seq0",
                    "symbol": "X",
                    "target_uniprot": "X",
                    "iptm": 0.9,
                    "pae_interaction": 1.0,
                    "score": 0.9,
                    "passes_thresholds": "pass",
                }
            ]
        ).to_parquet(run / "rank" / "ranking.parquet", index=False)
        targets = run / "design" / "_targets"
        targets.mkdir(parents=True)
        staged = tmp_path / "x_model_0.cif"
        staged.write_text("data_x\n# </script><script>alert(1)</script>\n", encoding="utf-8")
        with tarfile.open(targets / "X.tar.gz", "w:gz") as tf:
            tf.add(staged, arcname="validate/X_binder_0_seq0/X_binder_0_seq0_model_0.cif")

        from bindsight.report import render_run

        page = render_run(run).read_text(encoding="utf-8")
        payload = page.split("BINDSIGHT_STRUCTURES = ", 1)[1].split("</script>", 1)[0]

        assert "</script>" not in payload, "a structure closed the script that carries it"
        assert "\\u003c" in payload or "u003c" in payload


def test_the_report_funnel_matches_the_canonical_disposition_list() -> None:
    """The report hand-copies the funnel order; the copy had already drifted.

    `safety_unassessed` was added to the pipeline's cascade and not to the
    report's list, so a run withholding a candidate for an unmeasured safety
    record would have rendered a funnel that silently omitted it.
    """
    from bindsight.pipelines.discover import TAXONOMY_DISPOSITIONS
    from bindsight.report.html import _DISPOSITION_ORDER

    missing = set(TAXONOMY_DISPOSITIONS) - set(_DISPOSITION_ORDER)
    assert not missing, f"the report cannot render these dispositions: {sorted(missing)}"


# ---------------------------------------------------------------------------
# The volcano's guide lines
# ---------------------------------------------------------------------------
def _set_deg_params(run: Path, **params: float) -> None:
    """Record cutoffs on the manifest's ``deg`` stage, as a real run does."""
    path = run / "run_manifest.jsonld"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for stage in manifest["stages"]:
        if stage["name"] == "deg":
            stage.setdefault("params", {}).update(params)
            break
    else:  # pragma: no cover - the fixture always has a deg stage
        raise AssertionError("fixture has no deg stage")
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _caption(html: str) -> str:
    """The paragraph under the Differential expression heading."""
    import re

    match = re.search(r"Volcano plot.*?</p>", html, re.S)
    assert match, "the report no longer carries a volcano caption"
    return " ".join(match.group(0).split())


def _capture_axes(monkeypatch) -> list:
    """Record the axes the renderer draws on, so the guide lines can be read
    back from the real figure rather than from a re-implementation of them."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    seen: list = []
    original = plt.subplots

    def _subplots(*a, **kw):
        fig, ax = original(*a, **kw)
        seen.append(ax)
        return fig, ax

    monkeypatch.setattr(plt, "subplots", _subplots)
    return seen


class TestVolcanoThresholds:
    """The plot drew dashed lines at padj = 0.05 and |log2FC| = 1 whatever the
    run had configured. For a run using anything else those lines cut straight
    through the red points, telling the reader a cutoff that was never applied.
    """

    def test_the_guide_lines_sit_at_the_cutoffs_the_run_recorded(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Driven through ``render_run`` so the manifest-to-plot wiring is what
        is under test, not a helper read back on its own."""
        import math

        run = _make_run(tmp_path)
        _set_deg_params(run, fdr_threshold=0.01, log2fc_threshold=1.5)
        axes = _capture_axes(monkeypatch)

        render_run(run)

        assert axes, "the renderer drew no figure"
        ax = axes[0]
        horizontals = [ln.get_ydata()[0] for ln in ax.lines if len(set(ln.get_ydata())) == 1]
        verticals = [ln.get_xdata()[0] for ln in ax.lines if len(set(ln.get_xdata())) == 1]
        assert any(math.isclose(y, -math.log10(0.01), abs_tol=1e-9) for y in horizontals), (
            f"no guide line at padj = 0.01; horizontals were {horizontals}"
        )
        assert any(math.isclose(x, 1.5, abs_tol=1e-9) for x in verticals), verticals
        assert any(math.isclose(x, -1.5, abs_tol=1e-9) for x in verticals), verticals
        # The old hardcoded positions must be gone, not merely joined.
        assert not any(math.isclose(x, 1.0, abs_tol=1e-9) for x in verticals), (
            f"a line still sits at the library default of 1.0: {verticals}"
        )
        assert not any(math.isclose(y, -math.log10(0.05), abs_tol=1e-9) for y in horizontals), (
            f"a line still sits at the library default of 0.05: {horizontals}"
        )

    def test_a_run_that_recorded_no_cutoffs_gets_no_guide_lines(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Drawing an unlabelled line at a value the run did not use is worse
        than drawing none: the reader cannot tell it is a guess."""
        run = _make_run(tmp_path)  # the fixture's deg stage records no params
        axes = _capture_axes(monkeypatch)

        render_run(run)

        assert axes
        assert not axes[0].lines, (
            "guide lines were drawn for a run that never recorded its cutoffs: "
            f"{[(ln.get_xdata(), ln.get_ydata()) for ln in axes[0].lines]}"
        )

    def test_the_caption_states_the_cutoffs_rather_than_the_word_threshold(
        self, tmp_path: Path
    ) -> None:
        run = _make_run(tmp_path)
        _set_deg_params(run, fdr_threshold=0.01, log2fc_threshold=1.5)

        caption = _caption(render_run(run).read_text(encoding="utf-8"))

        assert "0.01" in caption, caption
        assert "1.5" in caption, caption
        assert "&lt;&nbsp;threshold" not in caption, (
            "the caption still says 'threshold' where the number belongs"
        )

    def test_the_caption_admits_when_the_cutoffs_were_not_recorded(self, tmp_path: Path) -> None:
        caption = _caption(render_run(_make_run(tmp_path)).read_text(encoding="utf-8"))

        assert "did not record" in caption, caption
        assert "no threshold lines are drawn" in caption, caption

    def test_thresholds_are_read_from_whichever_stage_recorded_them(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)
        _set_deg_params(run, fdr_threshold=0.2, log2fc_threshold=0.5)
        manifest = json.loads((run / "run_manifest.jsonld").read_text(encoding="utf-8"))

        assert _deg_thresholds(manifest) == (0.2, 0.5)
        assert _deg_thresholds(None) == (None, None)
        assert _deg_thresholds({"stages": []}) == (None, None)

    def test_significance_prefers_the_analysis_own_verdict(self) -> None:
        """The ``significant`` column already applied both cutoffs; re-deriving
        it from padj alone would silently drop the fold-change half."""
        assert _significance_basis(["padj", "significant"], 0.01) == ("column", None)
        assert _significance_basis(["padj"], 0.01) == ("padj", 0.01)
        assert _significance_basis(["padj"], None) == ("assumed", 0.05)


# ---------------------------------------------------------------------------
# A headline number must count the run, not the view of it
# ---------------------------------------------------------------------------
def _many_candidates(tmp_path: Path, n: int = 45) -> Path:
    """A run whose candidate table is longer than the display cap."""
    import pandas as pd

    run = _make_run(tmp_path)
    base = pd.read_parquet(run / "targets" / "candidates.parquet")
    grown = pd.concat([base] * ((n // len(base)) + 1), ignore_index=True).head(n)
    grown["uniprot_id"] = [f"P{i:05d}" for i in range(len(grown))]
    grown["gene_id"] = [f"ENSG{i:011d}" for i in range(len(grown))]
    grown["rank"] = range(1, len(grown) + 1)
    grown.to_parquet(run / "targets" / "candidates.parquet", index=False)
    return run


class TestTheSummaryCountsTheRunNotTheTable:
    """The "candidate targets" KPI read ``candidates_table|length``, and that
    table is capped at twenty rows. Every run with more than twenty candidates
    published "20" as its candidate count -- the committed run has 291.
    """

    @staticmethod
    def _stats(html: str) -> dict[str, str]:
        """Every ``.stat`` on the page, by its label.

        Reads the shared component rather than the report's old private
        ``.kpi``: the report and the served interface use one design system, and
        ``.stat`` is what carries the rule that a figure appears with its
        denominator.
        """
        import re

        found: dict[str, str] = {}
        for block in re.findall(
            r'<div class="stat[^"]*">(.*?)</div>\s*(?=<div|</div>)', html, re.S
        ):
            label = re.search(r'class="stat__label">([^<]+)<', block)
            value = re.search(r'class="stat__value">([^<]+)<', block)
            if label and value:
                found[label.group(1).strip().lower()] = value.group(1).strip()
        return found

    def test_the_kpi_reports_every_candidate(self, tmp_path: Path) -> None:
        run = _many_candidates(tmp_path, n=45)

        html = render_run(run).read_text(encoding="utf-8")

        stats = self._stats(html)
        assert stats.get("candidate targets") == "45", (
            f"the report states {stats.get('candidate targets')} for a 45-candidate "
            "run; it is counting the truncated display table"
        )

    def test_the_report_states_the_run_s_real_candidate_count(self, tmp_path: Path) -> None:
        """The number a reader of the shipped report actually meets.

        Built from a fixture rather than read from ``runs/join``: that directory
        is gitignored, so this skipped as "committed run not present" everywhere
        but the machine that produced it -- for a condition that is permanent,
        not environmental. The KPI it guards is the one that published **20**
        where the truth was 291, by counting the length of its own display table.

        It also used to render into the repository tree
        (``runs/join/_guard_report.html``) and unlink afterwards, which leaks the
        file whenever an assertion above it raises first.
        """
        import pandas as pd

        run = _make_run(tmp_path)
        expected = len(pd.read_parquet(run / "targets" / "candidates.parquet"))
        assert expected, "the fixture produced no candidates to count"

        html = render_run(run, tmp_path / "report.html").read_text(encoding="utf-8")

        stats = self._stats(html)
        assert stats.get("candidate targets") == str(expected), (
            f"the report does not state the run's {expected} candidates"
        )
        # The move to `.stat` is what makes this checkable: the number must now
        # appear beside what it is a count *of*. A bare count is the shape the
        # 20-instead-of-291 defect hid in.
        assert "stat__of" in html, (
            "the summary renders figures without their denominators, which is the "
            "rule the shared component exists to keep"
        )

    def test_a_truncated_binder_table_does_not_claim_to_be_every_design(
        self, tmp_path: Path
    ) -> None:
        """ "Every design the run produced" captioned a table capped at 40 rows."""
        run = _make_run(tmp_path)

        html = render_run(run).read_text(encoding="utf-8")

        if "best-scoring of the" in html:
            assert "Every\n    design the run produced" not in html
        else:
            # Not truncated on this fixture; the claim is then true.
            assert "design the run produced" in html


class TestTheReportDescribesTheRankingItActuallyUses:
    """ "How to read this report" told the reader candidates are ranked by
    structural druggability, then log2FC. They are ranked by
    pi = log2FC x -log10(padj); structure availability selects which of the
    top-ranked ones can be designed against, and does not affect the order.
    """

    def test_the_reading_guide_names_the_combined_score(self, tmp_path: Path) -> None:
        html = render_run(_make_run(tmp_path)).read_text(encoding="utf-8")

        assert "log2FC" in html
        assert "padj" in html
        assert "has_alphafold_structure first" not in html, (
            "the reading guide still describes the abandoned ordering"
        )

    def test_the_described_ranking_is_the_implemented_one(self) -> None:
        """Tied to the code, so a change to either fails until both move."""
        source = (
            Path(__file__).resolve().parents[1] / "bindsight" / "pipelines" / "discover.py"
        ).read_text(encoding="utf-8")

        assert 'sort_values(by="pi_score", ascending=False)' in source, (
            "the pipeline no longer ranks candidates by the combined score; the "
            "report's reading guide describes it as doing so"
        )


class TestTheEpitopeLegendDistinguishesAnOutageFromAnAbsence:
    """The legend explained three statuses and omitted the fourth, so a lookup
    that errored was left to read as "this protein has no targetable site" -- a
    measured negative the run never made.
    """

    def test_the_failed_lookup_status_is_explained(self, tmp_path: Path) -> None:
        html = render_run(_make_run(tmp_path)).read_text(encoding="utf-8")

        assert "surface_bind_lookup_failed" in html
        assert "errored" in html

    def test_every_status_the_pipeline_emits_appears_in_the_legend(self, tmp_path: Path) -> None:
        """Discovered from the pipeline's own status set, so a status added later
        cannot be the one nobody documented."""
        import re

        source = (
            Path(__file__).resolve().parents[1] / "bindsight" / "pipelines" / "discover.py"
        ).read_text(encoding="utf-8")
        statuses = set(re.findall(r'"(surface_bind_[a-z_]+|no_surface_bind_site)"', source))
        assert statuses, "no epitope statuses found in the pipeline"

        html = render_run(_make_run(tmp_path)).read_text(encoding="utf-8")

        missing = sorted(s for s in statuses if s not in html)
        assert not missing, f"epitope statuses absent from the report's legend: {missing}"


class TestTheVolcanoIsReadable:
    """Every significant gene was text-labelled. On a real cohort that is ~4,400
    overlapping annotations, which renders as a black bar and identifies nothing.
    """

    def test_only_the_strongest_points_are_labelled(self, tmp_path: Path, monkeypatch) -> None:
        import pandas as pd

        from bindsight.report.html import _MAX_VOLCANO_LABELS, _render_volcano

        n = _MAX_VOLCANO_LABELS * 5
        deg = pd.DataFrame(
            {
                "gene_id": [f"ENSG{i:011d}" for i in range(n)],
                "symbol": [f"SYM{i}" for i in range(n)],
                "log2fc": [3.0 + i * 0.01 for i in range(n)],
                "padj": [1e-10] * n,
                "significant": [True] * n,
            }
        )
        axes = _capture_axes(monkeypatch)

        _render_volcano(deg, fdr_threshold=0.05, log2fc_threshold=1.0)

        assert axes
        assert len(axes[0].texts) == _MAX_VOLCANO_LABELS, (
            f"{len(axes[0].texts)} labels drawn for {n} significant genes; the cap "
            f"is {_MAX_VOLCANO_LABELS}"
        )

    def test_the_labelled_points_are_the_strongest_ones(self, tmp_path: Path, monkeypatch) -> None:
        """A cap that kept an arbitrary twenty would hide the genes worth naming."""
        import pandas as pd

        from bindsight.report.html import _MAX_VOLCANO_LABELS, _render_volcano

        n = _MAX_VOLCANO_LABELS * 3
        deg = pd.DataFrame(
            {
                "gene_id": [f"ENSG{i:011d}" for i in range(n)],
                "symbol": [f"SYM{i}" for i in range(n)],
                "log2fc": [1.0 + i for i in range(n)],  # strongest last
                "padj": [1e-5] * n,
                "significant": [True] * n,
            }
        )
        axes = _capture_axes(monkeypatch)

        _render_volcano(deg, fdr_threshold=0.05, log2fc_threshold=1.0)

        drawn = {t.get_text() for t in axes[0].texts}
        assert f"SYM{n - 1}" in drawn, "the strongest gene is not labelled"
        assert "SYM0" not in drawn, "the weakest gene is labelled over stronger ones"


class TestTheReportIsWellFormedHtml:
    """Every generated report closed twelve more `<div>`s than it opened.

    Introduced by the note conversion when the interface was rebuilt: seven plain
    paragraphs were given the `</p></div></div>` ending that belongs to a note
    block, so each emitted two closers for divs nothing had opened.

    Browsers recover from it silently, which is exactly why it survived. A
    validator does not, and neither does a print-to-PDF path or anything that
    parses the file rather than renders it — and this report is the artifact a
    collaborator is meant to open from an email.
    """

    def test_the_div_tags_balance(self, tmp_path: Path) -> None:
        import re

        html = render_run(_make_run(tmp_path), tmp_path / "r.html").read_text(encoding="utf-8")

        opened = len(re.findall(r"<div\b", html))
        closed = len(re.findall(r"</div>", html))

        assert closed == opened, (
            f"the report opens {opened} <div> and closes {closed}; "
            f"{abs(closed - opened)} tag(s) do not match"
        )

    def test_no_line_of_the_template_closes_a_div_that_is_not_open(self) -> None:
        """Located, not just counted — a balanced total can still be misnested."""
        import re

        template = (
            Path(__file__).resolve().parents[1]
            / "bindsight"
            / "report"
            / "templates"
            / "report.html.j2"
        ).read_text(encoding="utf-8")

        depth = 0
        offenders: list[str] = []
        for lineno, line in enumerate(template.split("\n"), 1):
            depth += len(re.findall(r"<div\b", line)) - len(re.findall(r"</div>", line))
            if depth < 0:
                offenders.append(f"line {lineno}: {line.strip()[:70]}")
                depth = 0

        assert not offenders, "template lines closing an unopened <div>:\n  " + "\n  ".join(
            offenders
        )
        assert depth == 0, f"the template leaves {depth} <div> unclosed"
