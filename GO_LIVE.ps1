# GO_LIVE.ps1 — push bindsight to https://github.com/mikhaeelatefrizk/bindsight
# ============================================================================
# One-shot script: authenticate (if needed), create the GitHub repo, push,
# tag v0.1.0. After this finishes, deploy to Streamlit Cloud per the
# README "Try it in 60 seconds" section.
#
# Usage (in a PowerShell window, in this directory):
#
#     .\GO_LIVE.ps1
#
# Re-running is safe — every step is idempotent. If gh auth fails or the
# repo already exists, the script reports it and continues.
# ============================================================================

$ErrorActionPreference = 'Stop'
$gh = "$env:LOCALAPPDATA\gh\bin\gh.exe"

if (-not (Test-Path $gh)) {
    Write-Host "gh CLI not found at $gh. Re-run the install one-liner from the previous turn." -ForegroundColor Red
    exit 1
}

# 1. Auth (interactive on first run; instant on re-run)
$authStatus = & $gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Authenticating with GitHub (web browser will open)..." -ForegroundColor Cyan
    & $gh auth login --web --hostname github.com --git-protocol https --scopes 'repo,workflow'
    if ($LASTEXITCODE -ne 0) { Write-Host "Auth failed." -ForegroundColor Red; exit 1 }
}
Write-Host "✓ gh authenticated" -ForegroundColor Green

# 2. Create the repo (skip if it already exists)
Write-Host "Creating github.com/mikhaeelatefrizk/bindsight..." -ForegroundColor Cyan
& $gh repo create mikhaeelatefrizk/bindsight `
    --public `
    --description "RNA-seq counts to ranked de novo protein binder candidates, with full provenance back to the patient cohort." `
    --homepage "https://github.com/mikhaeelatefrizk/bindsight" `
    --disable-issues=false `
    --disable-wiki=true 2>&1 | Out-Host
# Repo creation returns non-zero if it already exists; that's fine, we proceed.

# 3. Push main + tag
Write-Host "Pushing main..." -ForegroundColor Cyan
git push -u origin main
if ($LASTEXITCODE -ne 0) { Write-Host "Push failed." -ForegroundColor Red; exit 1 }

Write-Host "Pushing tag v0.1.0..." -ForegroundColor Cyan
git push origin v0.1.0
if ($LASTEXITCODE -ne 0) { Write-Host "Tag push failed." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "================================================================"
Write-Host "DONE. Live at:" -ForegroundColor Green
Write-Host "    https://github.com/mikhaeelatefrizk/bindsight" -ForegroundColor Green
Write-Host ""
Write-Host "Next: deploy the web demo (5 min, free)" -ForegroundColor Cyan
Write-Host "    1. https://share.streamlit.io  ->  New app"
Write-Host "    2. Repo: mikhaeelatefrizk/bindsight  Branch: main  File: streamlit_app.py"
Write-Host "    3. Deploy.  Public URL: https://bindsight.streamlit.app  (or similar)"
Write-Host "================================================================"
