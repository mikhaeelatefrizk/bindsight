# Publishing bindsight to PyPI

Wheel + sdist are pre-built and validated by twine in `dist/`:
- `bindsight-0.1.0-py3-none-any.whl` (97 KB)
- `bindsight-0.1.0.tar.gz` (482 KB)

Once published, anyone in the world can install with:

```bash
pip install bindsight
```

Your name appears as the author on https://pypi.org/project/bindsight/.

---

## Step 1 — Create a PyPI account (~3 min, one time)

1. Go to https://pypi.org/account/register/
2. Fill the form (use your existing email `mikhaeelatefrizk@proton.me`)
3. Confirm via the email PyPI sends
4. Enable 2FA at https://pypi.org/manage/account/two-factor/ — required for uploads

## Step 2 — Generate an API token (~1 min)

1. Go to https://pypi.org/manage/account/token/
2. Token name: `bindsight-v0.1.0`
3. Scope: **Project: bindsight** (after first upload)
   - **First upload only:** scope must be **Entire account** because the
     project doesn't exist yet on PyPI. After the first upload succeeds, you
     can delete this token and create a project-scoped one.
4. Click "Create token"
5. Copy the token (starts with `pypi-`). PyPI shows it once.

## Step 3 — Upload (~30 sec)

In PowerShell from the repo directory:

```powershell
$env:TWINE_USERNAME = '__token__'
$env:TWINE_PASSWORD = 'pypi-PASTE-YOUR-TOKEN-HERE'
.\.venv\Scripts\python.exe -m twine upload dist\*
```

You should see:

```
Uploading bindsight-0.1.0-py3-none-any.whl
Uploading bindsight-0.1.0.tar.gz
View at: https://pypi.org/project/bindsight/0.1.0/
```

## Step 4 — Add the PyPI badge to README

Run this once after upload succeeds:

```powershell
$readme = Get-Content README.md -Raw
$badge = '[![PyPI](https://img.shields.io/pypi/v/bindsight.svg)](https://pypi.org/project/bindsight/)' + "`n"
$readme = $readme -replace '(\[!\[Open in Streamlit\][^\n]+\n)', "`$1$badge"
Set-Content README.md -NoNewline $readme
git add README.md && git commit -m "docs: add PyPI badge" && git push
```

(Or just paste the badge manually right after the Streamlit badge in README.)

## What changes in the install flow after this

**Before PyPI:**
```bash
git clone https://github.com/mikhaeelatefrizk/bindsight && cd bindsight
pip install -e ".[discover,report]"
```

**After PyPI:**
```bash
pip install "bindsight[discover,report]"
```

One command, no clone needed, anywhere on Earth.

## Future releases

When you bump to v0.2:

```powershell
# 1. Bump version in pyproject.toml + CITATION.cff
# 2. Tag and push:
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
# 3. Build:
.\.venv\Scripts\python.exe -m build
# 4. Upload (token from Step 2 still works for the same project):
.\.venv\Scripts\python.exe -m twine upload dist\bindsight-0.2.0*
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `403 Forbidden` on upload | Token has wrong scope (use account-wide for first upload) or 2FA isn't enabled |
| `Project name in use` | Someone else took `bindsight`. Pick a different name in pyproject.toml + republish. |
| `File already exists` | You've already uploaded v0.1.0; bump version and rebuild |

## Why I can't do this for you

PyPI's account creation requires identity verification and 2FA setup that
must be done by the human account owner. The token itself is sensitive
credential material that should never appear in a chat log unless you
explicitly want me to use it (and even then, you should rotate it after).
