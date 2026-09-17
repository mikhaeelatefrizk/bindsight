# SPDX-FileCopyrightText: 2026 Mikhaeel Atef Rizk Wahba
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The rediscovery evaluation panel: which antigens, in which cohorts, and why.

This module is data, deliberately separated from the code that runs the study so
the panel can be read, cited and criticised on its own.

Three design rules govern what is in here, and each replaces something the
earlier six-cohort study did wrong.

**1. Cohorts are never defined by the answer.** The previous study selected
TCGA-BRCA tumours by PAM50 HER2-enriched subtype and then reported discovering
ERBB2. ERBB2 is one of the fifty genes the PAM50 centroid classifier is built
on, so the tumour arm was chosen partly by high ERBB2 expression. EGFR is also a
PAM50 gene. No cohort here is stratified by any biomarker: the arms are
**every patient in the project who contributed both a primary tumour and a
solid-tissue normal**, and nothing about the antigen under test enters that
choice.

That is a subset of the project, and saying so matters. This used to read
"all primary tumour against all solid-tissue normal", which is not what runs:
``study.prepare_cohort`` calls ``matched_pair_cases``, so a tumour with no
matched normal is not in the contrast. In TCGA-UCEC that leaves 23 pairs. A
reader who takes the older sentence literally is wrong about the denominator
of every number downstream of it. The pairing is a design choice about the
contrast, not a selection on the answer, so the non-circularity argument below
is unaffected -- but the two are different claims and only one of them was true.

Two properties have to hold and they are not the same thing:

- *Non-circular* — the stratifier is not derived from the run's own counts.
- *Not enriched for the answer* — the stratifier is not a measurement of the
  antigen under test on any analyte.

Clinical HER2 immunohistochemistry passes the first and fails the second: it is
a protein assay, so it is not circular, but it still selects for the very
antigen being sought. Such an arm may only ever appear as a labelled sensitivity
analysis answering "can the pipeline find HER2 in a HER2-enriched population",
and it must never produce a recall number. See
:data:`ADMISSIBLE_STRATIFIER_RULE`.

**2. Reachability is decided before the run, not inferred afterwards.** An
antigen absent from the surfaceome reference can never be surfaced however
over-expressed it is, and reporting that as a ranking miss would be false. Two
antigens in this panel are in exactly that position — see
:data:`UNREACHABLE_NOTE`.

**3. Regulatory status is graded, not asserted.** "Clinically validated" is
doing a lot of work in most benchmark papers. Each pair here carries a
:attr:`AntigenCohort.tier` so the primary denominator can be pre-registered on
approved agents alone and the wider sets reported as sensitivity analyses.

Every sample count below was verified live against the GDC files API for open
``Gene Expression Quantification`` / ``STAR - Counts`` files, and every Ensembl
gene id was resolved from the UniProt cross-reference for its accession.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: The rule governing whether a cohort may be stratified at all. Stated once,
#: applied identically to every cohort, and never tuned per antigen.
ADMISSIBLE_STRATIFIER_RULE = (
    "A stratifying variable is admissible only if BOTH hold: (a) it is computable "
    "without the run's own counts matrix, and (b) it is not a measurement of the "
    "antigen under test on any analyte. PAM50 and every other mRNA-cluster subtype "
    "fails (a). Clinical HER2 IHC/FISH passes (a) but fails (b), so it may appear "
    "only as a labelled sensitivity analysis and never in a recall denominator. "
    "Receptor status for a different receptor, histology and stage pass both."
)

#: The instrument-coverage gap this study found, and what closing it took.
UNREACHABLE_NOTE = (
    "CA9 (Q16790) and STEAP1 (Q9UHE8) are absent from the SURFY surfaceome list — "
    "verified against both the vendored file and the upstream one, so a genuine "
    "reference gap rather than a build error. Under SURFY alone neither could "
    "enter the candidate table at any expression level, and CA9 measures a log2 "
    "fold change of 9.58 in clear-cell kidney, the largest effect anywhere in this "
    "panel. That is an instrument-coverage failure, not a ranking failure, and the "
    "fix was a better instrument: the extended reference adds UniProt's curated "
    "cell-membrane annotations, 1,915 further accessions, and makes both reachable. "
    "Runs with `use_extended_surfaceome=False` reproduce the SURFY-only behaviour, "
    "under which these two are still reported as unreachable rather than as misses."
)

#: Minimum solid-tissue normals for a cohort to enter a recall denominator.
#: Cohorts below this are still run and published, but excluded from every rate.
MIN_NORMALS_FOR_POWER = 10

#: Solid-tissue-normal STAR-Counts files per TCGA project, verified against the
#: GDC files API. Projects absent from this mapping have none.
PROJECT_NORMALS: dict[str, int] = {
    "TCGA-BRCA": 113,
    "TCGA-KIRC": 72,
    "TCGA-LUAD": 59,
    "TCGA-THCA": 59,
    "TCGA-PRAD": 52,
    "TCGA-LUSC": 51,
    "TCGA-LIHC": 50,
    "TCGA-HNSC": 44,
    "TCGA-COAD": 41,
    "TCGA-STAD": 36,
    "TCGA-UCEC": 35,
    "TCGA-KIRP": 32,
    "TCGA-KICH": 25,
    "TCGA-BLCA": 19,
    "TCGA-ESCA": 13,
    "TCGA-READ": 10,
    "TCGA-CHOL": 9,
    "TCGA-GBM": 5,
    "TCGA-PAAD": 4,
    "TCGA-CESC": 3,
    "TCGA-PCPG": 3,
    "TCGA-SARC": 2,
    "TCGA-THYM": 2,
    "TCGA-SKCM": 1,
}

#: Patients contributing BOTH a tumour and a normal sample, per project. This is
#: what the paired design can actually use, and it is nearly all of the normals —
#: which is why pairing is the largest free power gain available.
PROJECT_MATCHED_PAIRS: dict[str, int] = {
    "TCGA-BRCA": 113,
    "TCGA-KIRC": 72,
    "TCGA-THCA": 59,
    "TCGA-LUAD": 58,
    "TCGA-PRAD": 52,
    "TCGA-LUSC": 51,
    "TCGA-LIHC": 50,
    "TCGA-HNSC": 43,
    "TCGA-COAD": 41,
    "TCGA-STAD": 33,
    "TCGA-KIRP": 32,
    "TCGA-KICH": 25,
    "TCGA-UCEC": 23,
    "TCGA-BLCA": 19,
    "TCGA-ESCA": 13,
    "TCGA-READ": 9,
    "TCGA-PAAD": 4,
}

#: Regulatory tier of the targeting agent. The primary denominator is
#: pre-registered on ``approved`` alone; the wider tiers are sensitivity
#: analyses, reported with their own denominators.
Tier = Literal["approved", "late_clinical", "clinical_stage"]

#: Whether the cohort can carry a tumour-vs-normal contrast at all.
Usability = Literal["scored", "underpowered", "no_normals"]


@dataclass(frozen=True)
class AntigenCohort:
    """One antigen evaluated in one indication cohort.

    Attributes:
        project: TCGA project code; the cohort is the whole project, unstratified.
        symbol: HGNC gene symbol.
        uniprot: UniProt accession, the key bindsight's surfaceome filter uses.
        ensembl: Ensembl gene id, resolved from the UniProt cross-reference.
        agent: The targeting agent that makes this a surface antigen of interest.
        tier: Regulatory standing of that agent.
        usable: Whether this pair enters the scored panel.
        note: What a reader needs in order to interpret the result, including any
            reason to expect a null result a priori. Writing that expectation down
            before the run is what stops a miss being explained away afterwards.
    """

    project: str
    symbol: str
    uniprot: str
    ensembl: str
    agent: str
    tier: Tier
    usable: Usability
    note: str

    @property
    def key(self) -> str:
        """Stable identifier for this antigen-cohort pair."""
        return f"{self.project.removeprefix('TCGA-').lower()}_{self.symbol.lower()}"

    @property
    def n_normals(self) -> int:
        """Solid-tissue normals available in this project."""
        return PROJECT_NORMALS.get(self.project, 0)

    @property
    def n_matched_pairs(self) -> int:
        """Patients contributing both arms, which the paired design uses."""
        return matched_pairs_for(self.project)


def matched_pairs_for(project: str) -> int:
    """Patients contributing both a tumour and a normal arm in ``project``.

    One reader for the table. ``AntigenCohort.n_matched_pairs`` wrapped it and
    was never called, while the two places that actually need the number indexed
    ``PROJECT_MATCHED_PAIRS`` directly -- so the accessor could have changed its
    default or its lookup without either caller noticing.
    """
    return PROJECT_MATCHED_PAIRS.get(project, 0)


PANEL: list[AntigenCohort] = [
    # -- Breast ------------------------------------------------------------
    AntigenCohort(
        project="TCGA-BRCA",
        symbol="ERBB2",
        uniprot="P04626",
        ensembl="ENSG00000141736",
        agent="trastuzumab, pertuzumab, T-DXd",
        tier="approved",
        usable="scored",
        note="The unstratified BRCA cohort is the honest contrast. HER2-positive "
        "disease is roughly a fifth of breast cancer, so averaging across the whole "
        "project dilutes the signal; that dilution is the finding, not a flaw to be "
        "engineered away by selecting HER2-enriched tumours.",
    ),
    AntigenCohort(
        project="TCGA-BRCA",
        symbol="TACSTD2",
        uniprot="P09758",
        ensembl="ENSG00000184292",
        agent="sacituzumab govitecan, datopotamab deruxtecan",
        tier="approved",
        usable="scored",
        note="TROP2. Approved in metastatic triple-negative and HR-positive breast "
        "cancer. Broadly expressed across epithelia, so normal breast expression is "
        "not negligible.",
    ),
    # -- Kidney ------------------------------------------------------------
    AntigenCohort(
        project="TCGA-KIRC",
        symbol="CA9",
        uniprot="Q16790",
        ensembl="ENSG00000107159",
        agent="[89Zr]Zr-girentuximab (imaging, under FDA review)",
        tier="clinical_stage",
        usable="scored",
        note="Carbonic anhydrase IX is the defining clear-cell RCC surface antigen. "
        "Measured here at log2fc 9.58 with an adjusted p below floating-point "
        "resolution, the largest effect in the panel. Two notes: the girentuximab "
        "ADJUVANT phase 3 (ARISER) FAILED its primary endpoint, so the live asset is "
        "the diagnostic imaging agent rather than a therapeutic; and CA9 is absent "
        "from the SURFY list, so under that reference alone it was unreachable at any "
        "expression level. It is reachable through the extended reference, and this "
        "pair is why that extension exists.",
    ),
    AntigenCohort(
        project="TCGA-KIRP",
        symbol="MET",
        uniprot="P08581",
        ensembl="ENSG00000105976",
        agent="telisotuzumab vedotin",
        tier="approved",
        usable="scored",
        note="MET is the defining driver of type 1 papillary RCC. A second MET "
        "indication in the panel, giving a within-antigen control against LUAD.",
    ),
    # -- Lung --------------------------------------------------------------
    AntigenCohort(
        project="TCGA-LUAD",
        symbol="MET",
        uniprot="P08581",
        ensembl="ENSG00000105976",
        agent="telisotuzumab vedotin",
        tier="approved",
        usable="scored",
        note="Approved May 2025 for c-Met-overexpressing non-squamous NSCLC with a "
        "companion diagnostic, which is what qualifies MET as a validated surface "
        "antigen rather than only a kinase target.",
    ),
    AntigenCohort(
        project="TCGA-LUAD",
        symbol="TACSTD2",
        uniprot="P09758",
        ensembl="ENSG00000184292",
        agent="datopotamab deruxtecan",
        tier="approved",
        usable="scored",
        note="TROP2 in lung adenocarcinoma. Second indication for TROP2 in the panel.",
    ),
    AntigenCohort(
        project="TCGA-LUAD",
        symbol="ERBB2",
        uniprot="P04626",
        ensembl="ENSG00000141736",
        agent="T-DXd (tumour-agnostic, HER2 IHC3+)",
        tier="approved",
        usable="scored",
        note="Third ERBB2 indication. HER2 in lung adenocarcinoma is usually mutation-"
        "driven rather than over-expressed, so a null here is the expected result and "
        "is recorded as such in advance.",
    ),
    AntigenCohort(
        project="TCGA-LUAD",
        symbol="EGFR",
        uniprot="P00533",
        ensembl="ENSG00000146648",
        agent="cetuximab, necitumumab",
        tier="approved",
        usable="scored",
        note="EGFR drives lung adenocarcinoma through mutation and amplification, not "
        "bulk mRNA over-expression. The published run measured log2fc 0.06 (padj 0.75, "
        "not significant), so a null is the a-priori expectation and is a statement "
        "about the biology, not about the ranker. This note quoted 0.42 until a check "
        "against the artifact caught it -- 0.41 is ERBB2's log2fc in the same cohort, "
        "not EGFR's.",
    ),
    AntigenCohort(
        project="TCGA-LUSC",
        symbol="EGFR",
        uniprot="P00533",
        ensembl="ENSG00000146648",
        agent="necitumumab",
        tier="approved",
        usable="scored",
        note="Necitumumab remains FDA-approved for squamous NSCLC but was rejected by "
        "NICE and has had minimal uptake, so this is an approved agent that is not a "
        "current standard of care. EGFR is more genuinely over-expressed in squamous "
        "than in adenocarcinoma.",
    ),
    # -- Prostate ----------------------------------------------------------
    AntigenCohort(
        project="TCGA-PRAD",
        symbol="FOLH1",
        uniprot="Q04609",
        ensembl="ENSG00000086205",
        agent="[177Lu]Lu-PSMA-617 (Pluvicto)",
        tier="approved",
        usable="scored",
        note="PSMA is highly expressed in prostate cancer but is also abundant in "
        "normal prostate, so the tumour-vs-adjacent-normal fold change is modest. A "
        "designed test of the lineage-antigen blind spot, not a hoped-for hit.",
    ),
    AntigenCohort(
        project="TCGA-PRAD",
        symbol="STEAP1",
        uniprot="Q9UHE8",
        ensembl="ENSG00000164647",
        agent="xaluritamig (phase 3)",
        tier="late_clinical",
        usable="scored",
        note="STEAP1 is prostate-restricted and a strong a-priori positive. Like CA9 it "
        "is absent from the SURFY list, so under that reference alone it was "
        "unreachable by construction. Reachable through the extended reference.",
    ),
    # -- Stomach and oesophagus -------------------------------------------
    AntigenCohort(
        project="TCGA-STAD",
        symbol="CLDN18",
        uniprot="P56856",
        ensembl="ENSG00000066405",
        agent="zolbetuximab (Vyloy)",
        tier="approved",
        usable="scored",
        note="Claudin-18.2, approved October 2024 for CLDN18.2-positive gastric and GEJ "
        "adenocarcinoma. Stated up front: gene-level RNA-seq cannot separate the "
        "CLDN18.2 isoform from CLDN18.1, and normal gastric mucosa expresses CLDN18.2 "
        "highly, so a near-zero bulk fold change is the honest expectation. This pair "
        "is a designed test of the isoform blind spot.",
    ),
    AntigenCohort(
        project="TCGA-STAD",
        symbol="ERBB2",
        uniprot="P04626",
        ensembl="ENSG00000141736",
        agent="trastuzumab, T-DXd",
        tier="approved",
        usable="scored",
        note="Second, independent, non-breast test of ERBB2. This is what makes an "
        "ERBB2 result generalisable rather than a HER2 demonstration.",
    ),
    AntigenCohort(
        project="TCGA-STAD",
        symbol="FGFR2",
        uniprot="P21802",
        ensembl="ENSG00000066468",
        agent="bemarituzumab (phase 3)",
        tier="late_clinical",
        usable="scored",
        note="FORTITUDE-101 met its interim overall-survival endpoint in FGFR2b-"
        "overexpressing first-line gastric cancer, but the benefit attenuated with "
        "longer follow-up. Reported as equivocal late-stage rather than validated.",
    ),
    AntigenCohort(
        project="TCGA-ESCA",
        symbol="CLDN18",
        uniprot="P56856",
        ensembl="ENSG00000066405",
        agent="zolbetuximab (Vyloy)",
        tier="approved",
        usable="scored",
        note="Zolbetuximab's label covers gastro-oesophageal junction adenocarcinoma, "
        "which TCGA-ESCA contains. Only 13 normals, just above the power floor, so its "
        "per-cohort power must be published alongside the result. ESCA mixes squamous "
        "and adenocarcinoma and CLDN18.2 biology is adenocarcinoma-specific, so the "
        "histology split is a pre-registered stratum.",
    ),
    # -- Colorectal --------------------------------------------------------
    AntigenCohort(
        project="TCGA-COAD",
        symbol="EGFR",
        uniprot="P00533",
        ensembl="ENSG00000146648",
        agent="cetuximab, panitumumab",
        tier="approved",
        usable="scored",
        note="Third EGFR indication, enabling a within-antigen comparison across four cancers.",
    ),
    AntigenCohort(
        project="TCGA-COAD",
        symbol="CEACAM5",
        uniprot="P06731",
        ensembl="ENSG00000105388",
        agent="tusamitamab ravtansine, labetuzumab govitecan (phase 2/3)",
        tier="late_clinical",
        usable="scored",
        note="CEA is abundantly expressed in normal colonic epithelium, and the "
        "published run measured log2fc -0.48 (padj 0.045, not significant: the rule requires both an adjusted p below the FDR threshold and an absolute log2 fold change at or above the floor, and this clears only the first). Together with FOLH1 "
        "and CLDN18 this makes three pre-registered lineage-antigen nulls, which is "
        "what turns an anecdote into a measured statement about the blind spot.",
    ),
    # -- Bladder -----------------------------------------------------------
    AntigenCohort(
        project="TCGA-BLCA",
        symbol="NECTIN4",
        uniprot="Q96NY8",
        ensembl="ENSG00000143217",
        agent="enfortumab vedotin (Padcev)",
        tier="approved",
        usable="scored",
        note="Nectin-4 is expressed in the large majority of urothelial carcinomas. "
        "Only 19 normals, the weakest retained cohort, so its power estimate must be "
        "published. Note the TROP2 alternative for this indication is unusable: "
        "sacituzumab govitecan's urothelial approval was withdrawn in October 2024.",
    ),
    # -- Head and neck -----------------------------------------------------
    AntigenCohort(
        project="TCGA-HNSC",
        symbol="EGFR",
        uniprot="P00533",
        ensembl="ENSG00000146648",
        agent="cetuximab",
        tier="approved",
        usable="scored",
        note="The EGFR indication where a positive expectation is most defensible: "
        "EGFR is genuinely over-expressed in head and neck squamous carcinoma.",
    ),
    # -- Liver -------------------------------------------------------------
    AntigenCohort(
        project="TCGA-LIHC",
        symbol="GPC3",
        uniprot="P51654",
        ensembl="ENSG00000147257",
        agent="GPC3 CAR-T and bispecifics (phase 1/2)",
        tier="clinical_stage",
        usable="scored",
        note="Glypican-3 is oncofetal and near-absent in adult liver, making it the "
        "panel's strongest a-priori positive outside ERBB2. No approved GPC3 agent "
        "exists, so it is labelled clinical-stage and excluded from the approved-only "
        "primary denominator.",
    ),
    # -- Endometrium -------------------------------------------------------
    AntigenCohort(
        project="TCGA-UCEC",
        symbol="ERBB2",
        uniprot="P04626",
        ensembl="ENSG00000141736",
        agent="T-DXd (tumour-agnostic accelerated approval)",
        tier="approved",
        usable="scored",
        note="Fourth ERBB2 indication. 35 normals but only 23 matched pairs, the "
        "weakest pairing in the panel, so the paired primary analysis is underpowered "
        "here and this cohort carries the least weight of any in the study. There is "
        "no unpaired secondary: study.prepare_cohort refuses to fall back to an "
        "unpaired design rather than substitute a different contrast, so an "
        "underpowered pair is reported as underpowered instead of being rescued.",
    ),
    AntigenCohort(
        project="TCGA-UCEC",
        symbol="FOLR1",
        uniprot="P15328",
        ensembl="ENSG00000110195",
        agent="mirvetuximab soravtansine (Elahere)",
        tier="approved",
        usable="scored",
        note="Folate receptor alpha has full approval in ovarian cancer with a "
        "companion diagnostic, and endometrial carcinoma is a phase 2 indication. This "
        "is the only way to test FOLR1 at all, because its on-label indication has no "
        "TCGA normals.",
    ),
]

#: Pairs published for transparency but excluded from every recall denominator.
#: They are run where a run is possible, and their numbers are reported, but a
#: rate computed over them would be meaningless.
EXCLUDED: list[AntigenCohort] = [
    AntigenCohort(
        project="TCGA-PAAD",
        symbol="MSLN",
        uniprot="Q13421",
        ensembl="ENSG00000102854",
        agent="anetumab ravtansine, MSLN CAR-T (phase 1/2)",
        tier="clinical_stage",
        usable="underpowered",
        note="Mesothelin is genuinely over-expressed in pancreatic adenocarcinoma, but "
        "TCGA-PAAD ships only 4 solid-tissue normals. The published run measured "
        "log2fc 2.31 at padj 0.14 — not significant purely for lack of normals, which "
        "is a statement about the cohort and not about the antigen.",
    ),
    AntigenCohort(
        project="TCGA-OV",
        symbol="FOLR1",
        uniprot="P15328",
        ensembl="ENSG00000110195",
        agent="mirvetuximab soravtansine (Elahere)",
        tier="approved",
        usable="no_normals",
        note="The strongest ovarian surface-antigen evidence of any target, and "
        "untestable here: TCGA-OV ships zero solid-tissue normals. Substituting GTEx "
        "ovary would confound the contrast with a cross-study batch effect and must "
        "not be done silently.",
    ),
    AntigenCohort(
        project="TCGA-LAML",
        symbol="CD33",
        uniprot="P20138",
        ensembl="ENSG00000105383",
        agent="gemtuzumab ozogamicin (Mylotarg)",
        tier="approved",
        usable="no_normals",
        note="TCGA-LAML ships zero solid-tissue normals; its normals are blood-derived, "
        "which is not a tissue-of-origin comparator for a leukaemia. A case-level GDC "
        "query appears to return LAML cases with a normal, which is an artefact of "
        "filter combination; the file-level facet returns none.",
    ),
    AntigenCohort(
        project="TCGA-LAML",
        symbol="IL3RA",
        uniprot="P26951",
        ensembl="ENSG00000185291",
        agent="tagraxofusp",
        tier="approved",
        usable="no_normals",
        note="CD123. Same limitation as CD33: no solid-tissue normal reference exists "
        "in TCGA-LAML.",
    ),
    AntigenCohort(
        project="TCGA-OV",
        symbol="CLDN6",
        uniprot="P56747",
        ensembl="ENSG00000184697",
        agent="BNT211 CLDN6 CAR-T (phase 1/2)",
        tier="clinical_stage",
        usable="no_normals",
        note="Oncofetal claudin-6. Same zero-normal limitation as FOLR1 in TCGA-OV. "
        "Note the canonical accession is P56747, not Q14953, which is a different gene.",
    ),
]

#: Projects run with no antigen attached, purely to calibrate the null models and
#: audit shortlist composition. Both have ample normals and neither has a surface
#: antigen with an approved or phase-3 agent, so including them as scored pairs
#: would be inventing an expectation.
NULL_CALIBRATION_PROJECTS: tuple[str, ...] = ("TCGA-THCA", "TCGA-KICH")


def scored_panel(*, tiers: tuple[Tier, ...] = ("approved",)) -> list[AntigenCohort]:
    """Pairs entering a recall denominator at the given regulatory tiers.

    The primary analysis is pre-registered on ``("approved",)``. Wider tiers are
    sensitivity analyses and must be reported with their own denominators rather
    than silently merged.
    """
    return [
        c
        for c in PANEL
        if c.usable == "scored" and c.tier in tiers and c.n_normals >= MIN_NORMALS_FOR_POWER
    ]


def deduplicated_panel(*, tiers: tuple[Tier, ...] = ("approved",)) -> list[AntigenCohort]:
    """One cohort per antigen, so the confidence interval sees independent trials.

    ERBB2 appears in four indications, EGFR in four and MET and TACSTD2 in two, so
    a plain binomial interval over all pairs would understate uncertainty by
    treating repeats of one antigen as independent evidence. The retained cohort
    for each antigen is the one with the most solid-tissue normals, chosen by that
    rule alone rather than by outcome.
    """
    best: dict[str, AntigenCohort] = {}
    for c in scored_panel(tiers=tiers):
        current = best.get(c.uniprot)
        if current is None or c.n_normals > current.n_normals:
            best[c.uniprot] = c
    return sorted(best.values(), key=lambda c: (c.symbol, c.project))


def projects_in_panel() -> list[str]:
    """Distinct TCGA projects the scored panel touches, plus null-calibration ones."""
    return sorted(
        {c.project for c in PANEL if c.usable == "scored"} | set(NULL_CALIBRATION_PROJECTS)
    )


def reachability(uniprot: str, surfaceome: frozenset[str] | set[str]) -> dict[str, bool]:
    """Whether an antigen could be surfaced at all, decided before the run.

    Returns the two properties that make a pair reachable by bindsight's
    instrument: a resolvable UniProt accession and membership of the surfaceome
    reference. A pair failing either is an instrument-coverage failure, and
    reporting it as a ranking miss would be false.
    """
    return {
        "uniprot_resolved": bool(uniprot),
        "in_surfaceome": bool(uniprot) and uniprot in surfaceome,
    }
