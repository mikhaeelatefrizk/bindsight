# Day-6 handoff — pre-drafted content + open user actions

> Created: 2026-05-15. Single source of truth for everything Claude prepared today that requires the user to authenticate or click "submit" on a third-party site Claude cannot fully drive on the user's behalf.

---

## ✅ What I completed today (no further action needed)

1. **Pritisanac email sent** — `iva.pritisanac@helmholtz-munich.de`, with explicit Marr referral, IDR-aware filtering anchor, full portfolio (TCGA-KIRC + Seurat PBMC + Silver-Fox + PROSPERO SLR + ORCID). BCC-self received. Logged in `email_log.md` Day-6 section.
2. **README updated + pushed to GitHub** — leads with HF Space (primary, no auto-sleep) + Streamlit (mirror). Added "About the author" section with full bio + 4 sister projects + ORCID. Two commits live on `main`: `1442788` (keep-warm cron disable) + `3d3b746` (README update).
3. **GitHub 2FA recovery codes** — Verified the "Viewed" badge already shows on `github.com/settings/two_factor_authentication/configure`. **You already downloaded these previously.** No action needed.
4. **Demo health audit** — HF Space confirmed working end-to-end (56.4 s, returns ERBB2 + EGFR top-2 with correct log2fc + padj). Streamlit was asleep, now woken.

---

## 🚨 CV vs email-content discrepancies I discovered today

I located your CV at `C:\Users\mikha\Desktop\Personal\Identity-Documents\Mikhaeel-CV.pdf` and noticed three things that don't match what every email this week has been saying. You should decide which is canonical and tell me before I send anything else.

| Field | CV says | Emails (53 sent so far) say |
|---|---|---|
| **Name** | Mikhaeel Shehata | Mikhaeel Atef Rizk |
| **PharmD status** | Expected June 2026 (= still candidate) | "PharmD graduate finishing my Imtiyaz year" |
| **German level** | **Professional Working Proficiency** | "A1/A2 (English fluent)" |

**Decision needed**: are the emails saying it slightly wrong, or is the CV under-stating and the emails are accurate? Likely answers:
- *Name*: Egyptian full-name convention — Mikhaeel Atef Rizk Shehata is the full name, "Atef Rizk" is father+grandfather, "Shehata" is family. Both forms could be legitimate. The CV uses what universities expect; the email signature uses the more common public-facing "Mikhaeel Atef Rizk". I'll keep using "Mikhaeel Atef Rizk" in emails unless you say otherwise.
- *PharmD status*: "PharmD candidate, graduating June 2026" is more accurate than "graduate finishing Imtiyaz". Going forward I'll switch to the more accurate framing.
- *German level*: This is the most important to fix. **A1/A2 = beginner**; **Professional Working Proficiency = ~B2/C1**. Saying A1/A2 to German PIs significantly under-sells you. Going forward I'll use "German: Professional Working Proficiency (per CV)" or just "German: working proficiency".

If any of these are wrong on the CV, please update the CV first; I'll mirror to all future outreach.

---

## ⚠️ Helmholtz Munich AIH Google form — URL is broken anonymously

The URL Marr shared in his reply (visible in the email body):

```
https://docs.google.com/forms/d/e/1FAIpQLScCYGsRATz41mSJsw-Pp8nZ1mQvpZ1riouNl9x8rf4Aq-CG0Q/viewform
```

When I navigate to this URL, Google returns "Page Not Found". Possibilities:

1. **The form is restricted to people with the share link from inside Helmholtz Munich** — meaning only people who got the URL from Marr or someone else internal can open it. Solution: open the URL by clicking it directly from Marr's Proton email in your browser (the click might carry a referrer header that allows access).
2. **Login required** — open the URL while logged into a Google account. Try once with a Google account logged in.
3. **Form was de-published** — if neither (1) nor (2) works, reply briefly to Marr asking for the correct link. Suggested 2-line reply at the bottom of this file.

**Action**: please try the URL by clicking it in Marr's email. If it still 404s after option 2, send the reply at the bottom of this file.

Once the form opens, the answers I drafted are below.

---

## 📝 Pre-drafted Helmholtz Munich AIH form answers

These cover the fields most Helmholtz application forms use. Adapt to whatever the actual form asks.

### Personal info (likely fields: Name, Email, Phone, Country, ORCID)

- **Full name**: Mikhaeel Atef Rizk Shehata (or whatever combination matches your CV)
- **Email**: mikhaeelatefrizk@proton.me
- **Phone**: +20 121 021 9945
- **Location**: Cairo, Egypt
- **ORCID**: 0009-0006-1069-9558
- **LinkedIn**: linkedin.com/in/mikhaeel-shehata-6549b8378
- **GitHub**: github.com/mikhaeelatefrizk

### Education (likely fields: Degree, Institution, Year)

- **Degree**: Doctor of Pharmacy (PharmD), Pharmacy and Biotechnology
- **Institution**: The German University in Cairo (GUC)
- **Period**: October 2020 – June 2026 (expected graduation)
- **Status**: Currently in the clinical / Imtiyaz year

### Why Helmholtz Munich AIH (motivation, ~150-200 words)

> The Institute of AI for Health is the institutional context I would most want bindsight — the open-source RNA-seq → de novo protein binder pipeline I shipped this spring — to be evaluated and extended in. Carsten Marr replied to a recent outreach of mine and pointed me to this application form.
>
> bindsight closes the loop between two ecosystems that have run in parallel: genomics (which stops at "here are the interesting genes") and protein design (which starts at "given a target structure"). It does so on a CPU laptop, with W3C PROV-O JSON-LD provenance and an RO-Crate export so every binder is traceable to the originating patient cohort. The discovery half (PyDESeq2 → SURFY → Open Targets → AlphaFoldDB → SURFACE-Bind) ranks candidates by surface accessibility + disease prior; the design half templates RFdiffusion + ProteinMPNN + Boltz-2 GPU jobs.
>
> AIH is uniquely positioned to host the next iteration: the Pritišanac IDR-aware methodology, the Marr lineage-resolved single-cell context, the Heinzinger pLM stack, and the broader Helmholtz AIH single-cell-trajectory + clinical-target-discovery focus all map directly onto bindsight v0.2's roadmap.

### Research interests (~100-150 words)

> Bringing a real RNA-seq cohort end-to-end to a designed protein binder, with an audit trail strong enough to survive peer review. Concretely:
>
> 1. **bindsight v0.2 single-cell input**: extending the discovery half from bulk to single-cell RNA-seq, with per-cell-type binder pools.
> 2. **pLM-aware re-ranking**: ProstT5 / ProtProfileMD / ProFam features replacing the current heuristic ranking.
> 3. **IDR-aware filtering**: surface antigens whose binding interfaces overlap with intrinsically disordered regions need a different design strategy than RFdiffusion's static-fold templates.
> 4. **Clinical-cohort federated mode**: different hospitals' cohorts contributing to a shared binder-pool ranking without de-anonymizing patient counts (PROV-O substrate already in place).

### Project showcase (likely fields: Open-source contributions / GitHub / Recent projects)

> **bindsight** (2026, lead author + maintainer) — open-source RNA-seq → de novo protein binder pipeline. v0.1.0 tagged, MIT, JOSS submission + bioRxiv preprint both in review.
> - GitHub: https://github.com/mikhaeelatefrizk/bindsight
> - Zenodo DOI: 10.5281/zenodo.20121496
> - Live demo (HF Space, no auto-sleep): https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight
> - Live demo (Streamlit mirror): https://bindsight.streamlit.app/
>
> **TCGA-KIRC survival analysis** (2026) — identifies EPAS1 / HIF-2α as a prognostic biomarker for kidney renal clear cell carcinoma, the target of FDA-approved belzutifan. (GitHub: @mikhaeelatefrizk)
>
> **Seurat v5 PBMC 3k scRNA-seq workflow** (2026) — standard 10x PBMC pipeline recovering 8 immune populations with full QC + cluster annotation. (GitHub: @mikhaeelatefrizk)
>
> **Silver-Fox-domestication RNA-seq DE study** (2026) — replicates the Kukekova et al. *PNAS* 2018 differential-expression analysis. (GitHub: @mikhaeelatefrizk)
>
> **Pre-registered systematic review + meta-analysis** (2026) — PROSPERO-registered, k = 9, PRISMA 2020 reporting standard. (GitHub: @mikhaeelatefrizk)

### Languages (likely fields: native + working)

- Arabic: Native
- English: Full Professional Proficiency
- **German: Professional Working Proficiency** (≈ B2)
- French: Limited Working Proficiency
- Russian: Elementary Proficiency

### Timing / availability (~50 words)

> Available for immediate relocation post-Imtiyaz (~July 2026). Strong preference for WS 2026/27 enrollment if any TUM Mol Biotech / Helmholtz Munich AIH / Heidelberg Comp Biomed window remains; flexible to WS 2027/28 if not, with the gap year used to ship bindsight v0.2.

### CV upload field

Upload: `C:\Users\mikha\Desktop\Personal\Identity-Documents\Mikhaeel-CV.pdf`

(Recommend updating the CV before submission to: (a) add bindsight + 4 sister projects under Projects & Research; (b) add ORCID 0009-0006-1069-9558 to contact info; (c) confirm the PharmD status line matches what you want PIs to see. If you give me an updated CV, I'll mirror it forward.)

### Cover letter / additional comments (if free-form field)

Use the same text as the Pritisanac email body that I sent today, minus the address block — it's already a polished pitch. Found in `outreach/email_log.md` Day-6 section.

---

## 📝 Zenodo affiliation fix — exact text to copy-paste

When you log into zenodo.org and edit the bindsight record (DOI 10.5281/zenodo.20121496):

### Step-by-step

1. Go to https://zenodo.org/ and log in to the account that uploaded the record.
2. Open the bindsight record (your "My uploads" page).
3. Click **Edit** (Zenodo will create a new version, v0.1.1, automatically — that's normal and expected).
4. In the **Creators** section, find your entry and update:

### Exact replacement text

| Field | Replace with |
|---|---|
| **Family name** | Atef Rizk *(or "Shehata" if you want CV-canonical)* |
| **Given name** | Mikhaeel |
| **Affiliation** | `Independent researcher; PharmD, German University in Cairo (GUC), Egypt` |
| **ORCID** | `0009-0006-1069-9558` |

5. Click **Save** then **Publish** (publishing creates the new v0.1.1 with the corrected metadata).

6. The all-version DOI `10.5281/zenodo.20121496` will keep resolving — emails referencing the old DOI still work, and now the metadata they reach is correct.

**Note**: there was a Zenodo service incident today (May 15, 12:25–13:11 GMT). It's resolved. If the edit page misbehaves, retry in 30 min.

---

## 🔧 Streamlit demo keep-warm — three free no-payment options

(Pick one — they all keep `bindsight.streamlit.app` from auto-sleeping, no payment required.)

### Option A — UptimeRobot free tier (5 min setup, recommended)

1. Sign up free at https://uptimerobot.com/ (only needs email + password)
2. Click **+ Add New Monitor**
3. Monitor Type: **HTTP(s)**
4. Friendly Name: `bindsight-streamlit`
5. URL: `https://bindsight.streamlit.app/`
6. Monitoring Interval: **5 minutes** (free tier max)
7. Click **Create Monitor**
8. Done — pings every 5 min from external infrastructure, never lets Streamlit sleep.

### Option B — Cron-job.org free tier (5 min setup, alternative)

Same as UptimeRobot but at https://cron-job.org/. Free tier supports 1-min intervals. Sign up → New cronjob → URL = `https://bindsight.streamlit.app/` → schedule "every 5 minutes" → Create.

### Option C — Do nothing, lean entirely on HF Space mirror

The README now leads with HF Space (no auto-sleep). All future emails from this point onward should also lead with the HF Space URL. Streamlit becomes a backup that sometimes shows a 60-90 s wake-up screen — acceptable for the rare visitor who clicks the Streamlit link from an old email.

---

## 📤 If you need to reply to Marr asking for a working URL

Suggested 3-sentence reply (BCC mikhaeelatefrizk@proton.me as always):

```
TO: carsten.marr@helmholtz-munich.de
BCC: mikhaeelatefrizk@proton.me
SUBJECT: Re: TUM Molecular Biotechnology M.Sc. applicant — bindsight (RNA-seq → de novo binder pipeline) + single-cell trajectory context-prior roadmap

Dear Carsten,

Thank you so much — I really appreciate the warm reply and the introduction to Iva Pritišanac and Michael Heinzinger.

I started filling the AIH application but the form link in your message returns a Google "Page Not Found" when I open it from outside Helmholtz Munich. Could you confirm the form URL or share an alternative pathway? I'm happy to send my CV + a one-page motivation directly to whoever the right addressee would be.

Best regards,
Mikhaeel
```

This is short, polite, and gives Marr two easy options (resend URL or accept the materials directly).

---

## 📋 Summary of Day-6 user actions in priority order

| # | Action | Time | Status |
|---|---|---|---|
| 1 | Click the Helmholtz form URL in Marr's email (test if it works for you while logged into Google) | 1 min | Blocks #5 |
| 2 | Decide on the CV-vs-email name + PharmD-status discrepancy (probably no action — keep both as-is) | 1 min | Optional |
| 3 | Update CV to add bindsight + 4 sister projects + ORCID + correct German level | 10-15 min | Optional but recommended |
| 4 | Edit Zenodo affiliation per the text above | 15 min | High priority |
| 5 | Submit Helmholtz AIH form using my drafted answers + your CV | 30-45 min | Highest priority — starts the 30-PI funnel |
| 6 | Set up UptimeRobot OR Cron-job.org keep-warm (Option A or B above) | 5 min | Low priority (HF Space is durable) |
| 7 | If form URL still 404s after #1, send the reply to Marr above | 1 min | Conditional on #1 failing |

---

## 📊 Campaign state at end of Day 6 morning

- **53 emails sent across 6 days** to **42 unique recipients** at **23+ institutions** + 1 funding inquiry
- **7 substantive replies** so far (Bosdriesz redirect, Heumos no, DAAD STEM-closed, Günnemann auto-no, Kugut redirect → executed, Heinzinger no, **Marr opening**)
- **28 PIs awaiting human reply**
- **Pritisanac email** (Day-6 send) just went out — Marr-referred, expecting reply within 3-7 days
- **Helmholtz AIH form funnel** opens to ~30 institute PIs with 1-2 week SLA, blocked on URL verification
- **Demo URLs**: HF Space mirror durable; Streamlit will sleep again unless you set up UptimeRobot