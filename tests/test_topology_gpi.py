# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""GPI-anchored antigens are cell-surface and were classified unreachable.

UniProt annotates topological domains *relative to* a transmembrane segment. A
GPI-anchored protein is held in the outer leaflet by a lipid and has no
transmembrane helix, so it gets no topological domain either — and reading
extracellular extent from topological domains alone returned "no extracellular
domain" for an entire class of cell-surface protein.

The class includes some of the best-validated antibody targets there are. MSLN
is the target of multiple clinical antibody-drug conjugates and CAR-T
programmes, and it sits in this project's own default target set. With
``require_extracellular_domain`` enabled, discovery dropped such candidates from
design carry-forward as "not antibody-accessible", which is the opposite of the
truth.

The fixture below is the live UniProt record for Q13421, checked field by field
against the REST API rather than invented.
"""

from __future__ import annotations

from typing import Any

from bindsight.structures.topology import parse_topology

#: Q13421 (MSLN), length 622. Verified against
#: rest.uniprot.org/uniprotkb/Q13421.json: signal 1-36, GPI omega site 598,
#: propeptide 599-622 "Removed in mature form", no Transmembrane, no
#: Topological domain.
MSLN: dict[str, Any] = {
    "features": [
        {
            "type": "Signal",
            "description": "",
            "location": {"start": {"value": 1}, "end": {"value": 36}},
        },
        {
            "type": "Propeptide",
            "description": "Removed in mature form",
            "location": {"start": {"value": 599}, "end": {"value": 622}},
        },
        {
            "type": "Lipidation",
            "description": "GPI-anchor amidated serine",
            "location": {"start": {"value": 598}, "end": {"value": 598}},
        },
    ]
}

#: A single-pass receptor, to prove the usual path is untouched.
ERBB2: dict[str, Any] = {
    "features": [
        {
            "type": "Signal",
            "description": "",
            "location": {"start": {"value": 1}, "end": {"value": 22}},
        },
        {
            "type": "Topological domain",
            "description": "Extracellular",
            "location": {"start": {"value": 23}, "end": {"value": 652}},
        },
        {
            "type": "Transmembrane",
            "description": "Helical",
            "location": {"start": {"value": 653}, "end": {"value": 675}},
        },
        {
            "type": "Topological domain",
            "description": "Cytoplasmic",
            "location": {"start": {"value": 676}, "end": {"value": 1255}},
        },
    ]
}


class TestGpiAnchoredProteinsAreReachable:
    def test_mesothelin_is_no_longer_classified_unreachable(self) -> None:
        topo = parse_topology("Q13421", MSLN)
        assert topo.has_extracellular, (
            "MSLN is entirely extracellular and a validated ADC target; it was "
            "being dropped as having nothing a binder can reach"
        )

    def test_the_anchor_is_recorded(self) -> None:
        topo = parse_topology("Q13421", MSLN)
        assert topo.gpi_anchor == 598
        assert topo.is_gpi_anchored

    def test_the_reachable_region_is_the_mature_chain(self) -> None:
        """After the signal peptide, up to the omega site — not the whole entry.

        Residues past the omega site are the propeptide UniProt marks "Removed
        in mature form": they are gone before the protein reaches the surface,
        so designing against them would target a sequence no cell displays.
        """
        topo = parse_topology("Q13421", MSLN)
        assert topo.extracellular_ranges == ((37, 598),)
        residues = topo.extracellular_residues()
        assert 37 in residues
        assert 598 in residues
        assert 36 not in residues, "the signal peptide is cleaved"
        assert 599 not in residues, "the propeptide is removed in the mature form"

    def test_a_transmembrane_protein_is_unaffected(self) -> None:
        """The usual path must not move: topological domains still win."""
        topo = parse_topology("P04626", ERBB2)
        assert topo.extracellular_ranges == ((23, 652),)
        assert topo.gpi_anchor is None
        assert not topo.is_gpi_anchored

    def test_an_unannotated_entry_still_reports_nothing(self) -> None:
        """Absence of annotation is not evidence of a reachable domain."""
        topo = parse_topology("X", {"features": []})
        assert not topo.has_extracellular
        assert topo.gpi_anchor is None

    def test_a_gpi_protein_that_also_has_topology_keeps_its_topology(self) -> None:
        """Annotated domains are the better evidence; the fallback must not override."""
        entry = {"features": ERBB2["features"] + MSLN["features"][2:]}
        topo = parse_topology("hybrid", entry)
        assert topo.extracellular_ranges == ((23, 652),)

    def test_a_gpi_protein_with_a_transmembrane_segment_is_not_inferred(self) -> None:
        """With a helix present, the topological-domain annotation is the authority."""
        entry = {
            "features": [
                {
                    "type": "Transmembrane",
                    "description": "Helical",
                    "location": {"start": {"value": 100}, "end": {"value": 120}},
                },
                MSLN["features"][2],
            ]
        }
        topo = parse_topology("odd", entry)
        assert topo.extracellular_ranges == ()
        assert not topo.is_gpi_anchored

    def test_no_signal_peptide_starts_at_residue_one(self) -> None:
        entry = {"features": [MSLN["features"][2]]}
        assert parse_topology("x", entry).extracellular_ranges == ((1, 598),)

    def test_an_omega_site_inside_the_propeptide_defers_to_the_cleavage(self) -> None:
        """A malformed pair must not produce a range that runs backwards."""
        entry = {
            "features": [
                {
                    "type": "Signal",
                    "description": "",
                    "location": {"start": {"value": 1}, "end": {"value": 20}},
                },
                {
                    "type": "Propeptide",
                    "description": "Removed in mature form",
                    "location": {"start": {"value": 500}, "end": {"value": 600}},
                },
                {
                    "type": "Lipidation",
                    "description": "GPI-anchor amidated serine",
                    "location": {"start": {"value": 550}, "end": {"value": 550}},
                },
            ]
        }
        topo = parse_topology("x", entry)
        assert topo.extracellular_ranges == ((21, 499),)
        for start, end in topo.extracellular_ranges:
            assert start <= end
