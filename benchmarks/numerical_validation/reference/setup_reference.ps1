# Recreate an isolated reference from the recorded official binary downloads.
# Does not execute R's installer or modify PATH, associations, or registry.
param([Parameter(Mandatory = $true)][string]$Destination)
$ErrorActionPreference = 'Stop'
$destinationRoot = [System.IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
$manifest = Get-Content (Join-Path $PSScriptRoot 'setup-provenance.json') -Raw | ConvertFrom-Json
foreach ($archive in $manifest.archives) {
    $targetPath = [System.IO.Path]::GetFullPath((Join-Path $destinationRoot $archive.file))
    if (-not $targetPath.StartsWith($destinationRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Archive destination escapes the reference directory'
    }
    New-Item -ItemType Directory -Path (Split-Path $targetPath) -Force | Out-Null
    if (-not (Test-Path -LiteralPath $targetPath)) {
        Invoke-WebRequest -Uri $archive.source -OutFile $targetPath
    }
    if ((Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $archive.sha256) {
        throw "Archive checksum mismatch: $($archive.file)"
    }
}
$extractorRoot = Join-Path $destinationRoot 'innoextract'
$runtimeRoot = Join-Path $destinationRoot 'runtime'
if (-not (Test-Path -LiteralPath $extractorRoot)) {
    Expand-Archive -LiteralPath (Join-Path $destinationRoot 'downloads\innoextract-1.9-windows.zip') -DestinationPath $extractorRoot
}
if (-not (Test-Path -LiteralPath $runtimeRoot)) {
    & (Join-Path $extractorRoot 'innoextract.exe') --extract --silent --output-dir $runtimeRoot (Join-Path $destinationRoot 'downloads\R-4.6.1-win.exe')
    if ($LASTEXITCODE -ne 0) { throw 'R archive extraction failed' }
}
foreach ($name in @('user', 'library', 'tmp')) {
    New-Item -ItemType Directory -Path (Join-Path $destinationRoot $name) -Force | Out-Null
}
$env:R_USER = Join-Path $destinationRoot 'user'
$env:R_LIBS_USER = Join-Path $destinationRoot 'library'
$env:R_LIBS_SITE = Join-Path $destinationRoot 'library'
$env:TMPDIR = Join-Path $destinationRoot 'tmp'
$env:LC_ALL = 'C'
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$installerScript = Join-Path $destinationRoot 'install_recorded_packages.R'
@'
args <- commandArgs(trailingOnly = TRUE)
root <- normalizePath(args[[1]], winslash = "/", mustWork = TRUE)
lib <- file.path(root, "library")
.libPaths(c(lib, .Library))
archives <- list.files(file.path(root, "downloads", "packages"), pattern = "[.]zip$", full.names = TRUE)
install.packages(archives, lib = lib, repos = NULL, type = "win.binary", Ncpus = 1L)
suppressPackageStartupMessages(library(DESeq2))
stopifnot(as.character(packageVersion("DESeq2")) == "1.52.0")
print(sessionInfo())
'@ | Set-Content -LiteralPath $installerScript -Encoding utf8
& (Join-Path $runtimeRoot 'app\bin\Rscript.exe') --vanilla $installerScript $destinationRoot
if ($LASTEXITCODE -ne 0) { throw 'Recorded R package installation failed' }
Write-Output "Reference runtime ready at $destinationRoot"
