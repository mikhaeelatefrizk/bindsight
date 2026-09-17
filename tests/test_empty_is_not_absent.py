# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An empty result is not an absent request.

Two places read "the restriction matched nothing" as "no restriction was asked
for", because `[]` and `None` are both falsy and every guard was written `if x:`.

The cohort one is the serious one. `_list_cohort_files` takes
`cases: list[str] | None`, where `None` means "any patient" and a list means
"these patients only". With `[]` it dropped the `cases.submitter_id` clause and
fetched the first *n* tumour files of any subtype, so a subtype that no longer
matched produced an unstratified cohort published under the stratified cohort's
name. Nothing raised, nothing warned, and the provenance recorded
`selection: "first_n"` because `tumor_cases or ...` treated `[]` as absent there
too.

`rediscovery`'s own module docstring calls that stratification "the scientific
prerequisite for recovering a subtype-specific antigen like ERBB2", since a bulk
tumour-versus-normal contrast over the whole project averages the HER2 signal
away. This project has already withdrawn a headline over the mirror-image
mistake -- a cohort that *was* stratified, by a PAM50 call built from ERBB2
itself.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest


class TestAnEmptyCaseListIsNotAnUnrestrictedCohort:
    def test_the_query_builder_refuses_it(self) -> None:
        from bindsight.io.gdc import _list_cohort_files

        with pytest.raises(ValueError, match="matched no patients"):
            _list_cohort_files("TCGA-BRCA", "tumor", 10, cases=[])

    def test_none_still_means_no_restriction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The permitted case must keep working, and without a case clause."""
        import bindsight.io.gdc as gdc

        seen: dict[str, object] = {}

        def fake_post(filters, fields, size):
            seen["filters"] = filters
            return []

        monkeypatch.setattr(gdc, "_post_files_query", fake_post)
        gdc._list_cohort_files("TCGA-BRCA", "tumor", 10, cases=None)

        clauses = json.dumps(seen["filters"])
        assert "cases.submitter_id" not in clauses

    def test_a_real_case_list_still_restricts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import bindsight.io.gdc as gdc

        seen: dict[str, object] = {}

        def fake_post(filters, fields, size):
            seen["filters"] = filters
            return []

        monkeypatch.setattr(gdc, "_post_files_query", fake_post)
        gdc._list_cohort_files("TCGA-BRCA", "tumor", 10, cases=["TCGA-AA-0000"])

        clauses = json.dumps(seen["filters"])
        assert "cases.submitter_id" in clauses
        assert "TCGA-AA-0000" in clauses

    def test_the_study_stops_before_downloading_an_unstratified_cohort(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Raised where the message can name the label that failed to match."""
        import bindsight.benchmark.rediscovery as rediscovery
        import bindsight.io.cbioportal as cbioportal

        monkeypatch.setattr(cbioportal, "patients_with_subtype", lambda *_a, **_k: [])

        cohort = next(
            (c for c in rediscovery.VALIDATION_COHORTS if c.subtype is not None),
            None,
        )
        assert cohort is not None, (
            "no subtype-stratified cohort is configured, so this test would pass "
            "without exercising the path it exists for"
        )

        with pytest.raises(ValueError, match="no patient carries subtype"):
            rediscovery.prepare_cohort(
                cohort,
                tmp_path,
                {"TCGA-AA-0000": "Luminal A"},
            )


class TestAnUnreadableManifestIsNotARunWithoutDigests:
    """`_build_metadata` swallowed a `JSONDecodeError` with a bare `pass`.

    The crate then shipped with an empty run id and no `sha256` on any file, and
    a consumer preparing a deposit could not tell that from a run that genuinely
    recorded no digests. `_external_inputs`, in the same file, logs the
    identical failure.
    """

    def test_it_says_so(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        from bindsight.export.ro_crate import _build_metadata

        run = tmp_path / "run"
        run.mkdir()
        (run / "run_manifest.jsonld").write_text("{ this is not json", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="bindsight.export.ro_crate"):
            _build_metadata(run, files=[], external=[])

        assert any("could not read" in r.getMessage() for r in caplog.records), (
            f"nothing warned; records were {[r.getMessage() for r in caplog.records]}"
        )

    def test_a_readable_manifest_warns_about_nothing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from bindsight.export.ro_crate import _build_metadata

        run = tmp_path / "run"
        run.mkdir()
        (run / "run_manifest.jsonld").write_text(
            json.dumps({"@context": {}, "bindsight:run_id": "r1"}), encoding="utf-8"
        )

        with caplog.at_level(logging.WARNING, logger="bindsight.export.ro_crate"):
            _build_metadata(run, files=[], external=[])

        assert not [r for r in caplog.records if "could not read" in r.getMessage()]
