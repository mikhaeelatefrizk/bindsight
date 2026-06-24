"""Tests for UniProt membrane-topology parsing (extracellular-domain awareness)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bindsight.structures.topology import (
    UniProtTopologyClient,
    parse_topology,
)

FIXDIR = Path(__file__).parent / "fixtures" / "topology"


def _erbb2_json() -> dict:
    import json

    return json.loads((FIXDIR / "P04626.topology.json").read_text(encoding="utf-8"))


def test_parse_erbb2_topology() -> None:
    t = parse_topology("P04626", _erbb2_json())
    assert t.extracellular_ranges == ((23, 652),)
    assert t.transmembrane_ranges == ((653, 675),)
    assert t.signal_peptide == (1, 22)
    assert t.has_extracellular is True
    assert len(t.extracellular_residues()) == 630  # 652 - 23 + 1


def test_fraction_extracellular() -> None:
    t = parse_topology("P04626", _erbb2_json())
    assert t.fraction_extracellular([511, 600, 652]) == pytest.approx(1.0)  # domain IV
    assert t.fraction_extracellular([700, 800]) == pytest.approx(0.0)  # cytoplasmic
    assert t.fraction_extracellular([]) is None


def test_no_topology_annotation() -> None:
    t = parse_topology("Q00000", {"features": []})
    assert t.has_extracellular is False
    assert t.extracellular_residues() == set()
    assert t.fraction_extracellular([1, 2, 3]) == 0.0  # nothing a binder can reach


def test_client_reads_cached_without_network(tmp_path: Path) -> None:
    # Point the client cache at the committed fixture (named <acc>.topology.json)
    # so fetch() reads it instead of hitting the network.
    client = UniProtTopologyClient()
    client.cache = FIXDIR
    t = client.fetch("P04626")
    assert t is not None
    assert t.extracellular_ranges == ((23, 652),)


def test_client_empty_id_is_none() -> None:
    assert UniProtTopologyClient().fetch("") is None
