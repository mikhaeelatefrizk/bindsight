# Licensing inventory

> **Read this before any commercial use.** `bindsight` itself is AGPL-3.0-or-later, and it orchestrates external tools and data sources whose licenses differ. This document is the single source of truth for what is and isn't commercially safe.
>
> Last reviewed: 2026-06-15 — upstream code `LICENSE` files re-verified on this date for every GitHub-hosted component (designers, validators, surfaceome, viewers, workflow tooling); all match the table below. Model-weights and data-source terms (AF2/RFdiffusion weights, TCGA/GTEx/Open Targets/HPA/SURFY/AlphaFoldDB/RCSB) are unchanged from the prior review. **Verify the upstream `LICENSE` file** before relying on this document for legal decisions — these projects update.

---

## 1. bindsight itself

**GNU AGPL-3.0-or-later.** See [LICENSE](LICENSE).

You may use, study, modify, and redistribute `bindsight` for any purpose, commercial or academic — it is free and open-source software. The AGPL adds one core obligation (copyleft): if you **distribute** a modified version, **or run a modified version as a network/web service**, you must make your complete corresponding source available to its users under the same AGPL terms, preserving the copyright notice and attribution. This keeps bindsight and everything built on it open.

If those copyleft terms don't fit your use (e.g. embedding bindsight in a closed-source product), a separate **commercial license** is available from the author — as sole copyright holder, the author can dual-license. Contact: mikhaeelatefrizk@proton.me.

Documentation, manuscripts, figures, and generated results (e.g. `paper/`) are licensed under **CC BY 4.0** ([paper/LICENSE](paper/LICENSE)) — reuse freely with attribution.

---

## 2. Default pipeline (commercial-friendly)

The default `bindsight` configuration uses **only** components with permissive licenses suitable for commercial use:

| Component | License | Commercial use |
|---|---|---|
| [pydeseq2](https://github.com/owkin/PyDESeq2) | MIT | ✅ Yes |
| [Open Targets Platform](https://platform-docs.opentargets.org/) data | CC0 | ✅ Yes |
| Open Targets Python client | Apache-2.0 | ✅ Yes |
| [Human Protein Atlas](https://www.proteinatlas.org/) data | CC BY-SA 3.0 | ✅ Yes (with attribution + share-alike for derivatives of the data itself) |
| [GTEx](https://gtexportal.org/) data | Open (NIH dbGaP for protected) | ✅ Yes for v8 public release |
| [SURFY](https://wlab.ethz.ch/surfaceome/) gene list | CC BY | ✅ Yes (with attribution) |
| [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind) | BSD-3-Clause | ✅ Yes |
| [AlphaFoldDB](https://alphafold.ebi.ac.uk/) structures | CC BY 4.0 | ✅ Yes (with attribution) |
| [RCSB PDB](https://www.rcsb.org/) | Public domain (CC0) | ✅ Yes |
| [PDBe API](https://www.ebi.ac.uk/pdbe/api/doc/) | Open | ✅ Yes |
| [recount3](https://rna.recount.bio/) | Open (TCGA terms apply) | ✅ Yes for open subset |
| [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion) (code) | BSD-3-Clause | ✅ Yes |
| [RFdiffusion weights](https://github.com/RosettaCommons/RFdiffusion#download-the-models) | Per Baker Lab announcement, open for research and commercial | ✅ Yes (verify the LICENSE in your weights mirror) |
| [ProteinMPNN](https://github.com/dauparas/ProteinMPNN) | MIT | ✅ Yes |
| [Boltz-2](https://github.com/jwohlwend/boltz) (code + weights) | MIT | ✅ Yes |
| [Chai-1r](https://github.com/chaidiscovery/chai-lab) | Apache-2.0 | ✅ Yes |
| [BoltzGen](https://github.com/HannesStark/boltzgen) (code + weights) | MIT | ✅ Yes |
| [BindCraft](https://github.com/martinpacesa/BindCraft) | MIT | ✅ Yes |
| [fpocket](https://github.com/Discngine/fpocket) | MIT | ✅ Yes |
| [Snakemake](https://github.com/snakemake/snakemake) | MIT | ✅ Yes |
| [py3Dmol](https://pypi.org/project/py3Dmol/) | BSD-3 | ✅ Yes |
| [NGL Viewer](https://github.com/nglviewer/ngl) | MIT | ✅ Yes |
| [ColabFold](https://github.com/sokrypton/ColabFold) (code) | MIT | ✅ Yes |
| [MMseqs2](https://github.com/soedinglab/MMseqs2) | MIT | ✅ Yes |

---

## 3. Optional / opt-in components (commercial caveats)

These are **not** enabled by default. They require explicit opt-in via a CLI flag, and the CLI prints a license banner when used.

| Component | License | Commercial use | Mitigation |
|---|---|---|---|
| [AlphaFold2 weights](https://github.com/google-deepmind/alphafold) (DeepMind) | CC BY 4.0 (data); model weights restricted to non-commercial | ⚠️ Restricted | Use Boltz-2 / Chai-1r / BoltzGen instead, or obtain AF2 weights via DeepMind's commercial path |
| AF2-IG validator (via [dl_binder_design](https://github.com/nrbennet/dl_binder_design)) | Inherits AF2 weights restriction | ⚠️ Restricted | Same as above |
| [DESeq2](https://bioconductor.org/packages/DESeq2/) | LGPL-3 | ✅ Yes (LGPL allows commercial use of LGPL libraries from non-LGPL apps) | Default `pydeseq2` (MIT) is recommended to avoid the question entirely |
| [edgeR](https://bioconductor.org/packages/edgeR/) | GPL-2 | ⚠️ GPL — calling from non-GPL code is a runtime dependency, generally OK, but distribution of bundled binaries triggers GPL | Default to `pydeseq2`; do not vendor edgeR |
| [PyMOL OSS](https://github.com/schrodinger/pymol-open-source) | Custom (research-friendly, commercial restrictions) | ⚠️ Check terms | Use `py3Dmol` / NGL instead (both MIT/BSD) |
| [ColabFold MSA server](https://colabfold.com/) | Free service operated by Steinegger lab | ⚠️ Not for commercial scale | Provide BYO MMseqs2 path for commercial users |
| [TCGA controlled-access subsets](https://gdc.cancer.gov/) | NIH dbGaP, requires DAC approval | ⚠️ Requires approval | Default examples use only the open subset |

---

## 4. Per-component verification checklist

Before enabling a new component in `bindsight`, verify all of:

- [ ] License file in upstream repo at the pinned commit SHA
- [ ] Weights license (if ML model) — separate from code license
- [ ] Patent grant terms (if any)
- [ ] Attribution requirements
- [ ] Whether redistribution is permitted (matters if we vendor)
- [ ] Whether modification is permitted
- [ ] Whether the data the component uses (training data, reference data) is itself license-clean

Record the verification in the relevant `envs/*.yaml` or `bindsight/<module>/_LICENSING.md`.

---

## 5. What this means for users

### Academic users
Everything is fine. Use whatever you want. Cite all upstream tools (the per-run manifest emits `software.bib` to make this easy).

### Industry / commercial users
- **Default config** is commercially safe.
- **Opt-in** components carry banners. Read them.
- Use the `bindsight verify-licenses` command (available since v0.1) to audit a specific run config and flag any non-commercial components.

### Pharma / IND filings
- Treat `bindsight` as an in-silico discovery aid, not a regulated tool.
- The provenance graph (PROV-O / RO-Crate) is a starting point for an audit trail, not a substitute for GxP-validated systems.
- Specific clinical-grade validation of any output binder is the user's responsibility.

---

## 6. Reporting a licensing concern

If you spot a license issue (out-of-date attribution, missing notice, incompatible component), please open an issue tagged `licensing`. We treat these as high priority.
