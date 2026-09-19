# The provenance chain, run end to end

The claim this project rests on is that a reviewer can start at a ranked binder
and reach the patients it came from. This directory exhibits that walk, performed
once end to end on a target the discovery half chose for itself.

**What you can check from this clone, and what you cannot.** This directory holds
three committed files: the run's manifest (`run_manifest.jsonld`), the crate's
RO-Crate metadata (`ro-crate-metadata.json`), and the crate's checksum
(`SHA256SUMS`). The crate itself is 74 MB and is not committed, and `runs/` is
gitignored in full.

So of the seven steps below, **the first three are verifiable by reading the
files in this directory, with one exception.** The binder id, its target and the
structure it was built against are all in `ro-crate-metadata.json` — not in
`run_manifest.jsonld`, which records the stages and their parameters rather than
the designs. The design range beside them is in neither, so that one line of
step 3 has to be taken on trust until the crate is rebuilt. **Steps 4 to 7 are
not verifiable from this clone at all.** The gene identifier, the cohort, and
the patient barcodes live in the crate, which you have to rebuild. The walk was genuinely performed
against the full crate, and the transcript below is that walk — but a reader
with only this clone can confirm half of it, and this file previously implied
otherwise. See **Regenerating**.

## The run

| | |
|---|---|
| Cohort | TCGA-KIRC, 144 samples — 72 tumour and 72 solid-tissue normal, patient-paired |
| Design formula | `~ case_barcode + condition`, the paired contrast |
| Discovery | 291 candidates from the whole unstratified project |
| Targets designed | CA9 (Q16790) rank 1, CD70 (P32970) rank 2 |
| Design ranges | UniProt topology: CA9 38-414, CD70 39-193 |
| Designer / validator | RFdiffusion + ProteinMPNN, Boltz-2 |
| GPU | free Kaggle Tesla T4, 3h17m for CA9 and 1h29m for CD70 |
| Designs | 40, all with distinct ids |

## The walk, as performed against the full crate

Steps 1–3 are reproducible from the committed manifest in this directory.
Steps 4–7 require the rebuilt crate.

    1. ranked binder   P32970_binder_6_seq0   rank 1, ipTM 0.946
    2. target          P32970 (CD70)
    3. structure       structures/AF-P32970-F1-model_v6.cif
       design range    39-193, from uniprot_topology
    4. DEG             ENSG00000125726  log2fc 8.246  padj 2.3e-179
    5. cohort          144 samples: 72 tumour, 72 normal
    6. patients        72 TCGA cases, e.g. TCGA-A3-3358, TCGA-A3-3387
    7. cohort origin   TCGA-KIRC / STAR - Counts (GENCODE v36), retrieved 2026-09-06

Every step reads a file the crate carries. The cohort files sit outside the run
directory, where real cohorts live, and the exporter resolves them from the
manifest — an earlier crate of this same run shipped 31 artifacts with no
cohort in it at all, which broke the walk at step 5.

The barcodes above are TCGA case identifiers from the open-access tier of the
NCI Genomic Data Commons. They are pseudonymous study identifiers, not patient
identifiers, and they are quoted here because naming what the chain reaches is
the entire point of exhibiting it.

## What this manifest does not carry

The design stage records the designer, the validator, the backend and the
trajectory count, and **not the seed**. That is a gap against ARCHITECTURE 5,
which names the trajectory seed among the things a reviewer walks to. It was
found by reading this manifest after the run finished, and the code now records
it — but this artifact predates the fix.

The gap is stated rather than repaired. Regenerating the record means re-running
the design stage; the working-tree wheel would rebuild, the code identity in the
cache key would change, and the cache would correctly miss, costing roughly five
GPU-hours to fill in one field. The alternative, pinning the wheel for the life
of a run, would reintroduce the failure this project already had once, where a
GPU run installed code that was not the code under test.

The seed was 42. It is verifiable independently of this manifest, in the spec
payload embedded in the kernel scripts under `runs/_design/kaggle_*/kernel.py`.

## Regenerating

The crate is reproducible from the run directory:

    bindsight export runs/join --out runs/join.crate.zip

`SHA256SUMS` records the digest of the crate this README describes. A crate
rebuilt from the same run will differ in its `datePublished` field, so compare
contents rather than the digest unless rebuilding from the same day.
