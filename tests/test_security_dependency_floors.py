# SPDX-License-Identifier: AGPL-3.0-or-later
"""Known vulnerable resolutions must not satisfy published or mirrored metadata."""

import importlib.util
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def discovery_requirements():
    dependencies = yaml.safe_load((ROOT / "envs/discover.yaml").read_text())["dependencies"]
    return {
        requirement.name.lower(): requirement
        for item in dependencies
        if isinstance(item, str) and not item.startswith("python=")
        for requirement in [Requirement(item)]
    }


@pytest.mark.parametrize(
    ("name", "affected", "audited"),
    [
        # GHSA-9hjg-9r4m-mvj7 and GHSA-gc5v-m9x4-r6x2.
        ("requests", "2.32.3", "2.34.2"),
        # GHSA-3r8g-cqwr-jr29 and GHSA-qpmf-fgh3-ff25.
        ("pydantic", "2.14.1", "2.14.2"),
        # GHSA-cpwx-vrp4-4pq7; upstream's 3.1.6 security release.
        ("jinja2", "3.1.5", "3.1.6"),
        # GHSA-x3vf-39hj-gxr4; the scientific constraint already pins 1.88.
        ("biopython", "1.86", "1.88"),
    ],
)
def test_metadata_and_real_environment_gate_exclude_known_affected_versions(
    name, affected, audited, monkeypatch
):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    requirements = project["dependencies"] + project["optional-dependencies"]["discover"]
    published = {
        requirement.name.lower(): requirement for requirement in map(Requirement, requirements)
    }
    for requirement in (published[name], discovery_requirements()[name]):
        assert affected not in requirement.specifier
        assert audited in requirement.specifier
    assert published[name].specifier == discovery_requirements()[name].specifier

    # Drive the same gate CI uses, reading the actual metadata rather than a
    # replacement range. An already-installed vulnerable dependency must fail.
    module_spec = importlib.util.spec_from_file_location(
        "security_floor_environment_gate", ROOT / "scripts/check_pinned_environment.py"
    )
    gate = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(gate)
    monkeypatch.setattr(gate, "_installed", lambda package: affected if package == name else None)
    assert len(gate.check_ranges()) == 1
    monkeypatch.setattr(gate, "_installed", lambda package: audited if package == name else None)
    assert gate.check_ranges() == []


@pytest.mark.parametrize(
    ("name", "affected", "patched"),
    [("pip", "26.2.1", "26.2.2"), ("certifi", "2026.7.22", "2026.10.19")],
)
def test_discovery_bootstrap_excludes_certificate_incident_versions(name, affected, patched):
    requirement = discovery_requirements()[name]
    assert affected not in requirement.specifier
    assert patched in requirement.specifier
