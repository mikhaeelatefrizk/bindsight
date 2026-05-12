# Deploying bindsight to a Hugging Face Space (free, redundant backup)

The primary live demo lives at <https://bindsight.streamlit.app/>.  This
guide walks you through deploying a redundant copy on **Hugging Face
Spaces** as a backup that runs entirely independently — same code, same
behaviour, different hosting platform, also free.

## Why bother

| Concern | Streamlit Community Cloud (free) | Hugging Face Spaces (free CPU basic) |
|---|---|---|
| RAM ceiling | ~1 GB | ~16 GB |
| Auto-sleep on inactivity | Yes (mitigated by `.github/workflows/keep-warm.yml`) | No (always-on) |
| Memory-overrun behaviour | Hard 503 "over capacity" | Container restart, then keeps serving |
| First-visitor cold start | ~15 s warm, ~60-120 s after sleep | ~5-10 s wake-up |
| Discoverability for biology PIs | Lower | Higher (HF is where the ML/bio researchers already are) |

If Streamlit Cloud has a bad day, the HF Space keeps the demo alive for
every academic visitor.  If you want a single canonical URL, you can also
point [`bindsight.streamlit.app`](https://bindsight.streamlit.app/)'s About
page at the HF Space and treat HF as the primary.

## One-time setup (~10 minutes)

### 1. Create a free Hugging Face account

Go to <https://huggingface.co/join>.  You only need an email + username.
No payment method, no card, no quotas to worry about for a Streamlit Space
on Free CPU basic.

### 2. Create a new Space

1. Visit <https://huggingface.co/new-space>
2. **Owner**: your username
3. **Space name**: `bindsight`
4. **License**: `mit`
5. **SDK**: select **Streamlit**
6. **Streamlit SDK version**: pick the latest available (currently 1.36+)
7. **Hardware**: `CPU basic — 16 GB RAM, 2 vCPU` (free)
8. **Visibility**: Public
9. Click **Create Space**

### 3. Copy the repo

The Space is its own git repo at
`https://huggingface.co/spaces/<your-username>/bindsight`.  The simplest
way to populate it is to mirror the GitHub repo:

```bash
# from a fresh directory
git clone https://github.com/mikhaeelatefrizk/bindsight.git
cd bindsight

# add the HF Space as a second remote
git remote add huggingface https://huggingface.co/spaces/<your-username>/bindsight

# push main to the Space
git push huggingface main
```

You'll be prompted for an HF access token (create one at
<https://huggingface.co/settings/tokens> with `write` scope on Spaces).

### 4. Add the Space metadata file

Hugging Face Spaces requires a `README.md` at the repo root with YAML
frontmatter declaring the SDK, app file, etc.  A ready-to-use copy lives
at [`.huggingface/README.md`](../.huggingface/README.md) in this repo.

```bash
cp .huggingface/README.md README.md
git add README.md
git commit -m "docs: add Hugging Face Space metadata"
git push huggingface main
```

(Note: this *replaces* the project README on the HF Space repo only.  The
GitHub repo still uses the original `README.md` at the root.)

### 5. Wait for the build

Hugging Face Spaces will detect the push, install dependencies from
`requirements.txt`, and start the Streamlit app.  First build is usually
3-7 minutes.  Watch progress at:

```
https://huggingface.co/spaces/<your-username>/bindsight
```

When the status badge turns green, your demo is live at the same URL.

## Keeping it in sync with GitHub

After the initial push, every time you push a change to GitHub `main`,
mirror it to HF with:

```bash
git push huggingface main
```

Or automate this via a GitHub Action (out of scope for this guide — see
the official docs at <https://huggingface.co/docs/hub/spaces-github-actions>
when you're ready).

## Updating the cold-outreach links

Once the HF Space is live, update outreach materials to mention both URLs:

- `outreach/email_template.md` — add a sentence at the bottom of the
  bindsight introduction: *"Mirror also live at
  https://huggingface.co/spaces/<your-username>/bindsight"*
- LinkedIn About + Twitter pinned tweet — same one-liner
- `README.md` (the GitHub one) — add the HF link to the badges section

## Cost reality

Hugging Face Spaces Free CPU basic is genuinely free, forever, with no
trial period.  The constraint is fair-use: ~16 GB RAM, 2 vCPU, no GPU.
For the bindsight discovery half this is more than enough.  The design
half (RFdiffusion + ProteinMPNN + Boltz-2) still runs on Colab/Modal as
documented in [`colab-design-howto.md`](colab-design-howto.md), so HF
Spaces never needs GPU.
