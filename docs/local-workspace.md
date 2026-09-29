# The local research workspace

The hosted website explores committed research evidence and provides the companion for local analysis. To analyse your own data, use **Run locally** and approve the companion setup. The Python package in `bindsight/` runs the scientific work on your computer. `benchmarks/` contains the published evidence; `data/` contains bundled references; `tests/`, `docs/`, `envs/`, and `examples/` support the application. The companion manages these folders together.

## Install and open

1. Open [Run locally](https://bindsight-research.mikha-50.chatgpt.site/#run) and choose your computer.
2. Download and open the **Bindsight Companion**. Mac and Linux downloads are ZIP archives: extract the application first.
3. Approve **Set up and open Bindsight** in its window. The companion downloads a private Python runtime, verifies the source archive against the published checksum and revision, and installs the CPU scientific packages with `envs/constraints.txt`.
4. The research interface opens in your browser. Use **New analysis** for RNA-seq, **Your analyses** for saved work, and **Protein design** for the optional GPU workflow.

You do not need to install Python, type commands or edit configuration files for the companion's CPU setup. Keep the companion open while jobs run. Its real setup log shows failures and allows retry; cancelled or failed installations are never marked ready. Subsequent launches reuse the completed environment. The companion creates a launch shortcut and registers the website's **Open installed companion** link. Browser or organizational policy can prevent an app link from opening; use the shortcut in that case. Environments and runs are saved in a persistent per-user Bindsight folder.

The downloads are built and self-tested on Windows x64, macOS Apple silicon, macOS Intel and Linux x64. These checks do not test every desktop, driver or institutional policy. The binaries are not yet backed by a Windows publisher certificate or Apple notarization credentials; an operating system or institutional policy may require approval or prevent opening them. No security protection is disabled by the installer. A Linux desktop may require approving execution in its file properties.

The application checks available CPU, RAM, storage, actual scientific imports and detected NVIDIA hardware. Memory admission is a conservative scheduling estimate, not a guarantee that an arbitrary experiment will finish. A GPU being present does not mean its scientific environment is installed or that every target fits its memory.

The public website charges no computing-service fee. Local work uses your computer's electricity, storage and internet connection. Setup, model downloads and reference queries need internet access. Selected gene identifiers are queried against public annotation services; uploaded count matrices, sample metadata and results are not sent to the hosted website.

### Manual source installation

The full source workspace remains available under the website's technical-download disclosure. Advanced users may install Python 3.11–3.13, extract the archive and run `launch.py` (or double-click `Start bindsight.cmd` on Windows). This older launcher creates `.venv-bindsight/` beside the source; it is separate from the companion's private managed environment. Keep the extracted source folders together.

## Prepare a real experiment

Supply two tab-separated files (plain TSV or gzip):

- **Counts:** first column contains unique, unversioned human Ensembl gene IDs (`ENSG…`). Remaining columns contain biological samples and finite, nonnegative raw integer counts. TPM, FPKM, and normalised abundance are not valid inputs. Resolve version suffixes and resulting duplicate IDs deliberately before uploading.
- **Design:** first column contains the exact sample identifiers from the counts header. Include a comparison column with exactly two levels, and optionally a donor/patient column for matched samples. Column names must start with a letter and contain only letters, numbers and underscores.

Every row is checked before launch. The workbench requires at least three biological samples per group; that minimum is not a power calculation. Paired analysis requires exactly one sample of each condition per donor. Selected conditions and patient IDs are explicitly categorical, even when labels look numeric. The app accepts at most 2,000 samples, 150,000 gene rows, 512 MB compressed bytes per file, and 1 GB per expanded file. Actual memory needs can impose lower limits.

Choose the condition of interest and reference carefully: log₂ fold changes describe the selected numerator relative to the denominator. FDR and absolute fold-change thresholds apply together. Both expression directions can enter the existing ranking. This workflow covers **two-condition human bulk RNA-seq**, not metagenomics, single-cell differential expression, clinical diagnosis or treatment selection.

## Results and provenance

Runs execute one at a time in a separate process. The interface displays actual logs and terminal status, not estimated progress percentages. Cancellation stops the local worker; partial files are retained and are not marked completed. A restarted app marks unfinished jobs interrupted.

Each analysis is saved under `runs/analysis-…/`; original uploads and job logs are under `runs/_workbench/`. Use **Your analyses** to reopen the report and download candidate tables or the manifest. The run also contains the effective configuration, differential-expression results, annotation coverage and failure taxonomy. Missing reference information is displayed as incomplete annotation and persists in the standalone report. Intentional enrichment/structure caps are reported separately. A completed computation is not experimental validation.

The workbench disables the small historical gene-mapping fallback. It uses the bundled extended surfaceome, enriches at most 300 significant genes, and requests measured normal-tissue/safety evidence. Topology and structure/site coverage have limitations described in the report; these annotations do not certify that a target is safe or physically accessible.

## Protein design on your own GPU

On Windows, choose the companion's **GPU workspace** option before running the discovery that will supply your targets. This opens a separate Linux workspace through Windows Subsystem for Linux (WSL2). If Linux support is missing, a separate approved setup opens Microsoft's installer. Windows may require administrator approval and a restart; Ubuntu's first launch may ask you to create a username and password. Bindsight does not restart the computer, replace an existing Linux distribution or disable security policies. The guided handoff requires initialized Ubuntu 22.04 or 24.04 on WSL2. See [Microsoft's WSL setup documentation](https://learn.microsoft.com/en-us/windows/wsl/install).

The Windows and Linux workspaces keep separate saved runs. Upload your input files through the browser in the workspace you intend to use; files are still processed on your own computer. The companion downloads the matching Linux app only after approval and checks its source revision, file size and checksum.

Open **Protein design** in the local interface. The readiness check reports the actual NVIDIA device, available memory, platform and setup state. The guided recipe requires Linux x86_64 (including a Linux WSL2 workspace), a supported NVIDIA CUDA driver, at least 15,360 MiB total GPU memory (the reported capacity of a nominal 16 GB T4), and at least 60 GiB free disk for initial setup. The existing CUDA design stack does not support a Mac GPU. More available memory may be necessary for a particular target.

After explicit approval, **Prepare GPU tools** creates separate RFdiffusion/ProteinMPNN and Boltz environments, runs CUDA checks and records the environment receipt. It does not replace the CPU discovery environment. Downloads and package installation appear in the actual job log. Model weights can require additional downloads at first prediction. Fixed upstream tool revisions and the micromamba bootstrap checksum are recorded; not every transitive GPU dependency or model-weight download has a pre-established checksum pin.

Select a completed discovery analysis, choose one to three eligible targets and set the number of backbones, seed and candidate-length range. **Run design and prediction** uses the existing RFdiffusion + ProteinMPNN, Boltz, ranking and report stages. Eligible targets need actual recorded structures and extracellular ranges. The child design run preserves its source discovery and records their relationship. A completed setup is an environment check, not an end-to-end scientific validation.

Use the job panel to inspect logs, cancel work, retry supported completed stage boundaries, open the generated report and download recorded artifacts. The predicted-complex viewer loads original saved structure files and displays their checksums. Missing scores or structures are not filled with invented values. Jobs run locally; the public website does not supply a paid GPU service or upload jobs to an external GPU provider.

The current local release has **not** completed a new GPU design campaign on the owner's 2 GB MX450. The original successful recorded campaign used a T4 and 14,859 MiB peak memory (about 14.51 GiB). Neither installer tests, hardware checks nor successful CUDA arithmetic establish binding, specificity, target safety or robustness on every GPU. All resulting candidates remain computational predictions requiring appropriate experimental validation.
