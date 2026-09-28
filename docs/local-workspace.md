# The local research workspace

The hosted website is a read-only explorer of committed research evidence. To analyse your own data, download the workspace there or clone this repository. The Python package in `bindsight/` runs the scientific work on your computer. `benchmarks/` contains the published evidence; `data/` contains bundled references; `tests/`, `docs/`, `envs/`, and `examples/` support the application. Keep these folders together.

## Install and open

1. Install **Python 3.11, 3.12, or 3.13** from [python.org](https://www.python.org/downloads/). On Windows, enable “Add Python to PATH”.
2. Extract the downloaded workspace into a folder you own.
3. On Windows, double-click **Start bindsight.cmd**. On macOS or Linux, open a terminal in that folder and run `python3 launch.py` using a supported Python version.
4. The first launch installs the CPU analysis packages into `.venv-bindsight/` inside that folder, applying `envs/constraints.txt`. Keep the launch window open while using the app. Later launches reuse the environment.

The app opens on a loopback address. The **New analysis** page measures the available CPU, RAM, storage and detected NVIDIA GPU. Detection does not prove that a dataset fits in memory or that the separate GPU toolchain is ready. Platform support for the CPU package does not mean every GPU workflow runs on every platform.

The public website charges no computing-service fee. Local work still uses your computer's electricity, storage and internet connection. Initial setup and reference queries require internet access. Selected gene identifiers are queried against public annotation services; uploaded count matrices, sample metadata, and results are not sent to the hosted website. Check your institution's data-handling requirements before querying sensitive gene lists.

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

The basic installer includes **CPU discovery and evidence exploration**. It does not install RFdiffusion, ProteinMPNN, Boltz model weights or a CUDA runtime. The repository's successful published design run used a Kaggle T4; this release has not been exercised end to end on every local GPU or operating system.

Advanced users with an already configured NVIDIA/CUDA environment can use the existing `local_docker` runner in native mode (`BINDSIGHT_LOCAL_NATIVE=1`). Follow the tool-specific environments in `envs/` and the configuration in [the architecture guide](https://github.com/mikhaeelatefrizk/bindsight/blob/main/ARCHITECTURE.md). Windows CUDA setups normally need an appropriately configured Linux/WSL2 environment. The current CUDA design stack does not run on a Mac GPU. Do not mistake the CPU-only default Docker image for a complete GPU environment.

For reproducible GPU work, record actual model/checkpoint versions, seeds, sampling settings and hardware in the run. Model licences differ; inspect [LICENSING.md](https://github.com/mikhaeelatefrizk/bindsight/blob/main/LICENSING.md) and upstream terms. Protein design remains computational prediction until independently tested.
