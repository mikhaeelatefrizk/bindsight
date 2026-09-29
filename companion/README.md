# Bindsight desktop companion

The companion is a small standalone Tk desktop application. A packaged build
needs no existing Python. Nothing is downloaded on import or before **Set up
Bindsight** is approved. Setup installs a private managed Python 3.12.12, then
the verified source release's constrained `discover,report` CPU dependencies.
The editable source installation keeps the scientific evidence and input data
available to the local workbench. GPU dependencies are a separate workflow.

Installation and logs live in the user's Bindsight application-data directory:
`%LOCALAPPDATA%\Bindsight`, `~/Library/Application Support/Bindsight`, or
`${XDG_DATA_HOME:-~/.local/share}/Bindsight`. Setup needs internet and at least
4 GB free storage. An OS advisory lock covers installation and the server.
Only a completed import-checked install atomically replaces `current.json`.
Failures retain diagnostic files; retry never treats a partial install as ready.
Stop/cancel terminates owned work and preserves saved runs.

Approved setup creates a persistent per-user launcher and registers the exact
`bindsight://open` URI. Windows uses HKCU, macOS uses the bundle's declared scheme
and Launch Services, and Linux uses a user desktop entry plus `xdg-mime`.
No URI parameters, paths, query strings or extra command-line arguments are
accepted. An already running same-release workspace is reopened in the browser.
Reopening a completed CPU installation starts its local runtime without package
downloads. Keep the companion window open while working.

## Windows GPU workspace

The **GPU workspace** button starts a separately managed Linux workspace.
Stop the active CPU workspace before switching. Readiness checks an initialized
non-root user in Ubuntu 22.04/24.04 on WSL2, x86_64, and a visible NVIDIA GPU
with at least 15,360 MiB total memory. This is prerequisite admission, not proof
that CUDA, model installation or inference works. The Linux browser provides a
further explicit GPU installation approval and its own readiness diagnostics.
Windows runs are not silently copied or converted to Linux runs.
While the Linux workspace is active, `bindsight://open` reopens its browser.
After stopping it, reopen the companion and select **GPU workspace** again;
the current bridge requires a visible approval before checking/downloading its
matching Linux companion. An installed native CPU workspace opens by default.

**Install Windows Linux support…** is a distinct confirmation. It invokes only
the fixed Windows-owned `wsl.exe --install --distribution Ubuntu-24.04 --no-launch`
action through normal administrator approval. It never reboots, changes policy,
converts an existing WSL1 distro, or claims installation completed. Follow the
Windows prompts, restart if requested, then open Ubuntu from Start and create
its user account before returning to readiness checks. No WSL installation was
performed on the owner's machine during development validation.

## Verified downloads and scope

- `pins.json` records the fixed official Astral uv 0.12.19 artifacts, exact sizes
  and SHA256 hashes for Windows x64, Linux x64, and macOS x64/arm64. Primary source:
  [official uv release](https://github.com/astral-sh/uv/releases/tag/0.12.19) and
  [official release API](https://api.github.com/repos/astral-sh/uv/releases/tags/0.12.19).
- Managed Python is installed by that verified uv binary, using its bundled
  download metadata. Private cache/runtime/temp locations are passed explicitly;
  system Python, global PATH and Python registry discovery are not changed.
  [uv managed Python documentation](https://docs.astral.sh/uv/concepts/python-versions/).
- Source metadata, checksum list and ZIP are fetched only from the fixed
  [Bindsight release location](https://mikhaeelatefrizk.github.io/bindsight/workspace/release.json).
  The manifest, embedded build revision, and ZIP's `SOURCE_REVISION.json` must
  agree. A mixed publication asks for the current companion; it does not silently
  upgrade code. SHA256 checks establish integrity against the trusted HTTPS
  publication, not a detached cryptographic signature.
- Downloads have bounded sizes and checked redirects. ZIPs are inspected before
  extraction, with member/count/expanded-size limits and rejection of traversal,
  duplicate case aliases, device names, links and special files. No `shell=True`.
- CPU packages use the release constraints and the public PyPI index. These
  dependencies are version constrained, not a full hash-locked transitive package
  set. GPU model weights and CUDA are not part of CPU setup.
- Packaged-library search paths are sanitized for external processes, following
  [PyInstaller's primary guidance](https://pyinstaller.org/en/v6.16.0/common-issues-and-pitfalls.html#launching-external-programs-from-the-frozen-application).
  This is process-local compatibility handling, not an OS security change.

## Build and validation

Build on each target OS with Python 3.12 and `requirements-build.txt` installed:

```text
python companion/build.py --revision FULL_CHECKED_OUT_GIT_SHA --output companion-dist
```

The source must be committed and match that revision. `--allow-dirty` is only
for local development smoke builds, records that fact, and must never be published.
The build checks the packaged executable with `--self-test` before emitting only
the artifact and `build.json` (revision, platform, filename, bytes, SHA256, and
self-test result). macOS archives preserve the app bundle with `ditto`; Linux's
ZIP stores executable mode 0755. Distribution files are:

```text
Bindsight-Companion-windows-x64.exe
Bindsight-Companion-macos-arm64.zip
Bindsight-Companion-macos-x64.zip
Bindsight-Companion-linux-x64.zip
```

`--self-test` checks embedded metadata, pins and Tcl without a GUI or downloads.
`--verify-only --source ZIP --release JSON --checksums TXT` additionally checks an
offline source fixture. Neither mode proves that dependencies install or a GPU
works. A developer can perform a genuine CPU install into a separate work folder:

```text
python companion/smoke_install.py --root ../companion-install-smoke --revision FULL_PUBLISHED_SHA --approve-downloads
```

This does not create launchers or protocol associations. It verifies real imports
and HTTP 200 from the actual workbench, then cancels its own server. To check that
a packaged process can start this external managed Python without downloading:

```text
Bindsight-Companion-windows-x64.exe --smoke-existing-root ../companion-install-smoke --self-test-output ../companion-install-smoke/packaged-smoke-receipt.json
```

The latter receipt separately records companion and installed source revisions;
it is a developer interoperability check, not a mixed-release public installation.
On Windows, wait for the GUI-subsystem executable to finish before reading output.

Development validation on Windows downloaded the published source revision
`338adf6003540d8c989f99cd8b32b4455dc082fa`, source ZIP SHA256
`f562eb0644033d8b924d5d5edb83eba9f698e4964f342ba24036593055e394a7`,
installed Python 3.12.12 and 71 packages, checked imports, and served the real
workbench. A PyInstaller 6.16.0 Windows build also passed Tcl 8.6.12 self-test and
the external managed-Python/workbench smoke. Raw receipts/logs remain under
`work/companion-install-smoke` outside the repository. Tests cover download
approval, checksums, archive boundaries, process cancellation, locks, strict URI
handling, fixed WSL approvals, and bridge behavior without installing WSL.

The current binaries are **not Authenticode signed or Apple notarized**. Normal
OS download protections remain enabled; no bypass is implemented or recommended.
Packaging self-tests on other platforms run in CI; GUI interactions, macOS URL
registration and an eligible WSL GPU installation have not been exercised on the
owner's Windows laptop. Linux desktop behavior depends on its archive manager
preserving executable permissions and its normal downloaded-app policy.
