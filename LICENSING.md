# Licensing inventory

> **Read this before commercial use or redistribution.** `bindsight` itself is AGPL-3.0-or-later, and it orchestrates external tools and data sources whose licenses differ. This inventory records the stated terms and review scope; it does not certify legal suitability for a particular use or distribution.
>
> Last reviewed: 2026-11-01 — scoped DGL review for candidate 0.3.9. The authenticated upstream DGL 1.0.2+cu118 wheel contains Apache-2.0 licence text. The downstream RPC-removal wheel preserves it byte-for-byte and marks its modified Python files. The native libraries remain unchanged; this is not a fresh review of their embedded dependencies.
>
> Earlier scoped review, 2026-11-01, release 0.3.8: checked PyTorch 2.14.1's source licence; licences inside the hash-verified Hydra 1.3.8, e3nn 0.3.3, PyTorch Lightning 2.6.6, Requests 2.34.2 and Biopython 1.88 release wheels; and the three pinned CUDA 11 packages' licence metadata against NVIDIA's CUDA 11.8 EULA. The e3nn compatibility patch and Boltz distribution-metadata patch retain their upstream licences. This is not a complete transitive-dependency review; unchanged rows keep their earlier review scope.
>
> Earlier scoped review, 2026-11-01, release 0.3.7: the [2026-09-29 tool-registry change](https://github.com/mikhaeelatefrizk/bindsight/commit/3b08a00c273ba9e4b22deb633242cf29e8f8a4ce) routed Boltz through Bindsight's precision shim without changing upstream tool or model pins. That review re-checked Boltz 2.0.3's code licence and model-weight statement, and uv 0.13.6's bootstrap licences. It did not refresh every data-provider or transitive-dependency row.
>
> Previous full inventory review: 2026-09-20 — every row re-checked on this date against the source it names: the GitHub licence API and the `LICENSE` file for each code row, the publisher's own terms page for each data row. Eight rows changed as a result. Human Protein Atlas data is CC BY 4.0, not CC BY-SA 3.0. The AlphaFold2 model parameters are CC BY 4.0 with no non-commercial clause, and the AF2-IG row now names the real basis of its restriction, PyRosetta's non-commercial terms, rather than the weights. The SURFY site states no licence and the article it accompanies is CC BY-NC-ND 4.0, so that row no longer says CC BY. recount3 states no reuse terms of its own. The RFdiffusion weights row cites the `LICENSE` file, which covers code and weights, rather than an announcement. The ColabFold MSA server row credits the ColabFold team and its fair-use policy, which is how the project states it. The pydeseq2 row follows the repository to `scverse`. A row for an Open Targets Python client was deleted: this package has no such dependency. **Verify the upstream `LICENSE` file** before relying on this document for legal decisions — these projects update.

---

## 1. bindsight itself

**GNU AGPL-3.0-or-later.** See [LICENSE](LICENSE).

You may use, study, modify, and redistribute `bindsight` for any purpose, commercial or academic — it is free and open-source software. The AGPL adds one core obligation (copyleft): if you **distribute** a modified version, **or run a modified version as a network/web service**, you must make your complete corresponding source available to its users under the same AGPL terms, preserving the copyright notice and attribution. This keeps bindsight and everything built on it open.

If those copyleft terms don't fit your use (e.g. embedding bindsight in a closed-source product), a separate **commercial license** is available from the author — as sole copyright holder, the author can dual-license. Contact: mikhaeelatefrizk@proton.me.

Documentation, manuscripts, figures, and generated results (e.g. `paper/`) are licensed under **CC BY 4.0** ([paper/LICENSE](paper/LICENSE)) — reuse freely with attribution.

---

## 2. Default pipeline components

The table below records the application and data components reviewed previously,
including the SURFY list whose publisher states no terms of its own and the
reference-only rows not integrated into Bindsight. The managed GPU runtime adds
the separately licensed components described below the table.

| Component | License | Commercial use |
|---|---|---|
| [pydeseq2](https://github.com/scverse/PyDESeq2) | MIT | ✅ Yes |
| [Open Targets Platform](https://platform-docs.opentargets.org/) data | CC0 | ✅ Yes |
| [Human Protein Atlas](https://www.proteinatlas.org/) data | CC BY 4.0 | ✅ Yes (with attribution) |
| [GTEx](https://gtexportal.org/) data | Open (NIH dbGaP for protected) | ✅ Yes for v8 public release |
| [SURFY](https://wollscheidlab.org/SURFY/) gene list | Not stated by the source; the article it accompanies (Bausch-Fluck et al., PNAS 2018) is CC BY-NC-ND 4.0 | ⚠️ Verify before commercial use — this package redistributes the list as a table of identifiers with attribution; ask the Wollscheid lab if your use needs more than that |
| [SURFACE-Bind](https://github.com/hamedkhakzad/SURFACE-Bind) | BSD-3-Clause | ✅ Yes |
| [AlphaFoldDB](https://alphafold.ebi.ac.uk/) structures | CC BY 4.0 | ✅ Yes (with attribution) |
| [RCSB PDB](https://www.rcsb.org/) | Public domain (CC0) | ✅ Yes (used only by `benchmarks/build_eval_set.py`; **no structure client in `bindsight/structures/`** — planned) |
| [PDBe API](https://www.ebi.ac.uk/pdbe/api/doc/) | Open | ✅ Yes (**not integrated**; listed for reference only) |
| [recount3](https://rna.recount.bio/) | Not stated by recount3; the data it re-hosts carry their sources' terms (TCGA, GTEx) | ⚠️ Verify per source (**not integrated**; listed for reference only) |
| [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion) (code) | BSD-3-Clause | ✅ Yes |
| [RFdiffusion weights](https://github.com/RosettaCommons/RFdiffusion#download-the-models) | BSD-3-Clause (the LICENSE file states it covers code and model weights) | ✅ Yes (verify the LICENSE in your weights mirror) |
| [ProteinMPNN](https://github.com/dauparas/ProteinMPNN) | MIT | ✅ Yes |
| [Boltz-2 2.0.3](https://github.com/jwohlwend/boltz/tree/v2.0.3) (code + weights) | MIT ([code licence](https://github.com/jwohlwend/boltz/blob/v2.0.3/LICENSE); [code and weights statement](https://github.com/jwohlwend/boltz/blob/v2.0.3/README.md#license)) | ✅ Yes (retain the MIT copyright and permission notice when redistributing) |
| [Chai-1r](https://github.com/chaidiscovery/chai-lab) | Apache-2.0 | ✅ Yes |
| [BoltzGen](https://github.com/HannesStark/boltzgen) (code + weights) | MIT | ✅ Yes |
| [BindCraft](https://github.com/martinpacesa/BindCraft) | MIT | ✅ Yes |
| [fpocket](https://github.com/Discngine/fpocket) | MIT | ✅ Yes |
| [Snakemake](https://github.com/snakemake/snakemake) | MIT | ✅ Yes |
| [3Dmol.js](https://github.com/3dmol/3Dmol.js) (vendored, see `bindsight/report/web/static/vendor/3Dmol.LICENSE`) | BSD-3-Clause | ✅ Yes |
| [NGL Viewer](https://github.com/nglviewer/ngl) | MIT | ✅ Yes |
| [ColabFold](https://github.com/sokrypton/ColabFold) (code) | MIT | ✅ Yes |
| [MMseqs2](https://github.com/soedinglab/MMseqs2) | MIT | ✅ Yes |

### Installer bootstrap

| Component | License | Commercial use |
|---|---|---|
| [uv 0.13.6](https://github.com/astral-sh/uv/blob/0.13.6/README.md#license) | MIT OR Apache-2.0, at the user's option ([MIT](https://github.com/astral-sh/uv/blob/0.13.6/LICENSE-MIT), [Apache-2.0](https://github.com/astral-sh/uv/blob/0.13.6/LICENSE-APACHE)) | ✅ Yes, subject to the chosen licence's notice and redistribution requirements |

The companion and GPU/Kaggle installers download an official uv archive during setup and verify its pinned size and SHA-256 before extracting the executable. The uv binary is not bundled in Bindsight's Python package or companion executable. If redistributing an installed workspace or image containing uv, include the applicable licence and copyright notices and account for its third-party components; the code licence above is not an audit of every dependency in the binary. Downloading Python and scientific packages through uv does not change their separate licence terms.

### Managed GPU runtime — scoped 0.3.8 and 0.3.9 reviews

| Component | Verified licence and source | Scope and obligations |
| --- | --- | --- |
| DGL 1.0.2+cu118, installed as `1.0.2+cu118.bindsight.rpcoff1` | Apache-2.0, licence text inside the [authenticated upstream wheel](https://data.dgl.ai/wheels/cu118/dgl-1.0.2%2Bcu118-cp311-cp311-manylinux1_x86_64.whl) | The downstream build retains the original licence and marks its Python modifications. The scientific graph implementation and native libraries are unchanged. |
| PyTorch 2.14.1+cu126 | BSD-style 3-clause, [v2.14.1 source LICENSE](https://github.com/pytorch/pytorch/blob/v2.14.1/LICENSE) | Preserve source/binary notices and avoid implied endorsement. Vendored components and CUDA libraries have separate terms. |
| hydra-core 1.3.8 | MIT, `hydra_core-1.3.8.dist-info/licenses/LICENSE` inside the [official release wheel](https://pypi.org/project/hydra-core/1.3.8/#files) | The wheel's size and SHA256 matched PyPI metadata. Retain the Facebook and affiliates copyright and permission notice. |
| e3nn 0.3.3 | MIT, `e3nn-0.3.3.dist-info/LICENSE` inside the [official release wheel](https://pypi.org/project/e3nn/0.3.3/#files) | The wheel's size and SHA256 matched PyPI metadata. Retain the UC/LBNL, EPFL, Free University of Berlin and Kostiantyn Lapchevskyi notices, including in a redistributed modified package. |
| PyTorch Lightning 2.6.6 | Apache-2.0, `licenses/LICENSE` inside the [official release wheel](https://pypi.org/project/pytorch-lightning/2.6.6/#files) | The wheel's size and SHA256 matched PyPI metadata. Preserve the licence and applicable notices under its redistribution terms. |
| Requests 2.34.2 | Apache-2.0, `licenses/LICENSE` and `licenses/NOTICE` inside the [official release wheel](https://pypi.org/project/requests/2.34.2/#files) | The wheel's size and SHA256 matched PyPI metadata. Preserve its licence and Kenneth Reitz copyright notice under the applicable terms. |
| Biopython 1.88 | Biopython License Agreement, `licenses/LICENSE.rst` inside the [official Linux CPython 3.11 release wheel](https://pypi.org/project/biopython/1.88/#files) | The wheel's size and SHA256 matched PyPI metadata. Retain copyright and permission notices; contributor names require permission for advertising. Only files explicitly marked accordingly offer the alternative BSD 3-clause licence. |
| NVIDIA CUDA 11 runtime libraries listed below | NVIDIA Proprietary Software in exact-version PyPI metadata; [CUDA 11.8 EULA](https://docs.nvidia.com/cuda/archive/11.8.0/eula/index.html) | These are not open-source components. Use and redistribution have NVIDIA's separate conditions. |

The CUDA 11 package versions are
[`nvidia-cuda-runtime-cu11` 11.8.89](https://pypi.org/project/nvidia-cuda-runtime-cu11/11.8.89/),
[`nvidia-cusparse-cu11` 11.7.5.86](https://pypi.org/project/nvidia-cusparse-cu11/11.7.5.86/) and
[`nvidia-cublas-cu11` 11.11.3.6](https://pypi.org/project/nvidia-cublas-cu11/11.11.3.6/).
They are downloaded into a separate auxiliary prefix for DGL; they are not
bundled in Bindsight's wheel or companion. The review checked package metadata
and the official EULA, not each NVIDIA wheel's embedded licence file.

NVIDIA's Attachment A lists the relevant shared libraries as redistributable
with applications, subject to its distribution requirements. These include
added application functionality and consistent distribution terms. Downloading
them during setup does not grant unrestricted redistribution or resolve the
licensing of a bundled AGPL application. Before redistributing an installed
environment or image, review its NVIDIA and third-party notices and applicable
terms. This inventory is not a licence-compatibility opinion.

The Boltz runtime distribution `2.0.3+bindsight.1` changes its version and four
dependency requirements, renames its metadata directory and regenerates its
wheel record. All 106 files under `boltz/` and its original MIT licence remain
byte-identical to the verified upstream 2.0.3 wheel. The local version identifies
this downstream packaging change; it does not replace the upstream licence or
the separate licences of the newly selected dependencies.

Bindsight changes one e3nn constant loader after verifying the original file
and constants hashes. The adjustment retains `weights_only=True` with a scoped
`slice` allowlist; it leaves the package's MIT licence in place. It is a
compatibility modification, not a new licence for e3nn. Runtime testing and
scientific validation are documented separately in [the runtime guide](docs/gpu-runtime.md).

---

## 3. Optional / opt-in components (commercial caveats)

These are **not** enabled by default. They require explicit opt-in via a CLI flag, and the CLI prints a license banner when used.

| Component | License | Commercial use | Mitigation |
|---|---|---|---|
| [AlphaFold2 weights](https://github.com/google-deepmind/alphafold) (DeepMind) | CC BY 4.0 (model parameters; code Apache-2.0) | ✅ Yes (with attribution) | None needed for the weights. This row said "non-commercial" until 2026-09-20 and was wrong; the restriction on the AF2-IG path is PyRosetta's, next row |
| AF2-IG validator (via [dl_binder_design](https://github.com/nrbennet/dl_binder_design)) | MIT code; AF2 parameters CC BY 4.0; PyRosetta non-commercial (free only for non-commercial use) | ⚠️ Restricted by PyRosetta | Use Boltz-2 / Chai-1r instead, or obtain a PyRosetta commercial licence from UW CoMotion |
| [DESeq2](https://bioconductor.org/packages/DESeq2/) | LGPL-3 | ✅ Yes (LGPL allows commercial use of LGPL libraries from non-LGPL apps) | **Not integrated; listed for reference only.** There is no R bridge — `pydeseq2` (MIT) is the only DEG engine |
| [edgeR](https://bioconductor.org/packages/edgeR/) | GPL-2 | ⚠️ GPL — calling from non-GPL code is a runtime dependency, generally OK, but distribution of bundled binaries triggers GPL | **Not integrated; listed for reference only.** Not selectable from any config; do not vendor edgeR |
| [PyMOL OSS](https://github.com/schrodinger/pymol-open-source) | Custom (research-friendly, commercial restrictions) | ⚠️ Check terms | Use 3Dmol.js / NGL instead (BSD-3 / MIT) |
| [ColabFold MSA server](https://colabfold.com/) | Free, rate-limited public resource operated by the ColabFold team; subject to a fair-use policy | ⚠️ Not for commercial scale | Provide BYO MMseqs2 path for commercial users |
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
Academic use still requires the relevant data-access, attribution and software
licence terms, including NVIDIA's GPU-library terms. Cite upstream tools; the
per-run manifest emits `software.bib` to help with attribution.

### Industry / commercial users
- **Default components** have the stated terms in §2. The SURFY list states no licence, and the managed GPU runtime includes proprietary NVIDIA libraries; assess those terms for the intended use and any redistribution.
- **Opt-in** components carry banners. Read them.
- `bindsight verify-licenses` prints a static inventory; it does not inspect current upstream terms or audit every installed transitive dependency.

### Pharma / IND filings
- Treat `bindsight` as an in-silico discovery aid, not a regulated tool.
- The provenance graph (PROV-O / RO-Crate) is a starting point for an audit trail, not a substitute for GxP-validated systems.
- Specific clinical-grade validation of any output binder is the user's responsibility.

---

## 6. Reporting a licensing concern

If you spot a license issue (out-of-date attribution, missing notice, incompatible component), please open an issue tagged `licensing`. We treat these as high priority.
