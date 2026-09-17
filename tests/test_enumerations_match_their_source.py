# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hand-written lists that must keep covering the thing they enumerate.

This repository's signature defect is a list someone typed out that is supposed
to cover "all of some category", and silently stops covering it when a new
member is added somewhere else. It has produced a wrong cached answer three
times (`validator`, then `designer`/`designer_version`, then the BoltzGen
parameters), a plugin interface that could not be used, and a disposition
missing from the report's table.

The lists below are currently complete. Nothing ties them to what they mirror,
which is the condition under which every previous instance went wrong -- the
list was right on the day it was written too.

Each test derives the source of truth and compares, rather than restating the
list a third time.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import get_args

REPO = Path(__file__).resolve().parents[1]


class TestEveryRankWeightReachesTheCompositeScore:
    """`component_cols` pairs each score column with the weight that scales it.

    It is a hand-written list of five tuples beside a Pydantic model with five
    fields. `RunConfig` would accept and validate a YAML config setting a sixth
    weight, and `rank_validated` would compute the composite exactly as before:
    the user's configuration silently contributes nothing, with no warning and
    no error. A ranking that ignores what the user asked for is the same failure
    as `bindsight rank` discarding a run's configured weights, which this
    project has already fixed once.

    `RankWeights._at_least_one_weight_is_positive`, fifteen lines away in
    `config.py`, iterates `model_fields` rather than naming them -- the generic
    treatment this list did not get.
    """

    @staticmethod
    def _weights_used_by_the_composite() -> set[str]:
        """Every `weights.<field>` read inside `component_cols`.

        Parsed from the source because the list is built inside the function
        that uses it, so there is nothing importable to compare against.
        """
        source = (REPO / "bindsight" / "rank" / "scoring.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        found: set[str] = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                continue
            target = node.targets[0]
            if not (isinstance(target, ast.Name) and target.id == "component_cols"):
                continue
            for attribute in ast.walk(node.value):
                if (
                    isinstance(attribute, ast.Attribute)
                    and isinstance(attribute.value, ast.Name)
                    and attribute.value.id == "weights"
                ):
                    found.add(attribute.attr)
        return found

    def test_the_scan_finds_the_list(self) -> None:
        """Without this, a scan that matched nothing would pass the check below."""
        found = self._weights_used_by_the_composite()

        assert len(found) >= 3, (
            f"the AST scan found only {sorted(found)} in scoring.py; it has stopped working"
        )

    def test_every_configurable_weight_is_applied(self) -> None:
        from bindsight.config import RankWeights

        declared = set(RankWeights.model_fields)
        applied = self._weights_used_by_the_composite()

        assert declared <= applied, (
            f"{sorted(declared - applied)} can be set in a config and never reaches "
            "the composite score, so a user who sets one gets a ranking that "
            "silently ignores it"
        )

    def test_no_weight_is_applied_that_cannot_be_configured(self) -> None:
        from bindsight.config import RankWeights

        declared = set(RankWeights.model_fields)
        applied = self._weights_used_by_the_composite()

        assert applied <= declared, (
            f"{sorted(applied - declared)} is read from RankWeights but is not a "
            "field on it; this would be an AttributeError at rank time"
        )


class TestEveryOutcomeClassCanBeRendered:
    """Four dicts key on the outcome taxonomy; a fifth class would be invisible.

    `OutcomeClass` is a `Literal` of four members, and the module frames them as
    a closed set that "must never be merged". The study's Markdown and its
    figures each carry two dicts keyed on those four, written out as bare
    strings rather than the imported constants, so adding a class would render
    it without a title, a note, a colour or a label -- and the docstring's own
    reason for the taxonomy is that these classes must stay distinguishable to
    a reader.
    """

    @staticmethod
    def _classes() -> set[str]:
        from bindsight.benchmark.outcomes import OutcomeClass

        return set(get_args(OutcomeClass))

    def test_the_taxonomy_is_readable(self) -> None:
        classes = self._classes()

        assert len(classes) >= 4, f"only read {classes} from OutcomeClass"

    def test_the_study_report_titles_and_notes_cover_every_class(self) -> None:
        from bindsight.benchmark.study_report import _CLASS_NOTE, _CLASS_TITLE

        classes = self._classes()

        assert classes <= set(_CLASS_TITLE), (
            f"{sorted(classes - set(_CLASS_TITLE))} has no section title in the study report"
        )
        assert classes <= set(_CLASS_NOTE), (
            f"{sorted(classes - set(_CLASS_NOTE))} has no explanatory note in the study report"
        )

    def test_the_figures_colour_and_label_every_class(self) -> None:
        from bindsight.benchmark.study_figures import _CLASS_LABEL, _COLOURS

        classes = self._classes()

        assert classes <= set(_COLOURS), (
            f"{sorted(classes - set(_COLOURS))} has no colour, so its bar would not draw"
        )
        assert classes <= set(_CLASS_LABEL), (
            f"{sorted(classes - set(_CLASS_LABEL))} has no axis label in the figures"
        )

    def test_nothing_is_rendered_that_is_not_a_class(self) -> None:
        """A stale key is a row nobody can reach and a note nobody maintains."""
        from bindsight.benchmark.study_figures import _CLASS_LABEL, _COLOURS
        from bindsight.benchmark.study_report import _CLASS_NOTE, _CLASS_TITLE

        classes = self._classes()
        for name, mapping in (
            ("_CLASS_TITLE", _CLASS_TITLE),
            ("_CLASS_NOTE", _CLASS_NOTE),
            ("_COLOURS", _COLOURS),
            ("_CLASS_LABEL", _CLASS_LABEL),
        ):
            assert set(mapping) <= classes, (
                f"{name} carries {sorted(set(mapping) - classes)}, which is not an outcome class"
            )
