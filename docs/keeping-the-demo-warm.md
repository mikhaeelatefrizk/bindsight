# Keeping the live demo warm — free-tier playbook

This doc explains how bindsight's live demos stay reachable 24/7 on
$0 hosting, and what to do if the in-repo `keep-warm` workflow ever
goes down.

> tl;dr — three free, redundant layers ping the Hugging Face Space
> well under its 48-hour sleep threshold. You don't need any paid tier
> as long as at least one layer is firing.

---

## The sleep problem

Both bindsight demos run on free-tier hosts that sleep on inactivity:

| Host | Free-tier sleep window | What triggers wake |
|---|---|---|
| Hugging Face Space (`mikhaeelatefrizk-bindsight.hf.space`) | ~48 h | Any HTTP GET to the UI or app URL |
| Streamlit Community Cloud (`bindsight.streamlit.app`) | ~7 d | Owner-authenticated reboot, OR a normal browser visit that completes Streamlit's interactive wake handshake |

The HF wake-up is fully scriptable; the Streamlit Cloud wake is partially
scriptable (the auth-session handshake) but the final "spin up the
container" step on a deeply asleep app requires either:

1. A browser visit (Streamlit Cloud's JS handles the wake POST internally), or
2. Owner login at <https://share.streamlit.io> → click reboot.

This means the HF Space is the **primary** demo target for the
keep-warm strategy, and the Streamlit Cloud mirror is best-effort
secondary.

---

## Layer 1 — in-repo GitHub Actions cron (default, $0)

Two workflows in `.github/workflows/` ping the HF Space every 30
minutes on average (staggered to give redundancy against GitHub's
documented occasional schedule misses):

| Workflow | Schedule | What it does |
|---|---|---|
| `keep-warm.yml` | `0 * * * *` (top of each hour) | HF API stage check + true health probe; warns on Streamlit asleep |
| `keep-warm-redundant.yml` | `30 * * * *` (half past each hour) | Lightweight URL ping |

Public-repo GitHub Actions are free with no minute cap, so this layer
costs nothing. Combined hourly cadence is ~48× under the HF sleep
threshold; either workflow alone is sufficient.

**Status badge:** the README's "Keep demo warm" badge tracks
`keep-warm.yml`. If it ever turns red, check the run logs for either
"HF Space stuck" (real problem) or "Streamlit mirror asleep" (warning,
HF still primary).

---

## Layer 2 — external uptime monitor (recommended, $0)

If GitHub Actions billing is ever blocked or schedules go fully dark,
you want an out-of-band ping. Two no-cost options, in order of
recommendation:

### cron-job.org — no account required (anonymous), 1-min granularity

1. Visit <https://cron-job.org>.
2. Sign up with email (free, no credit card).
3. Create job:
   - Title: `bindsight HF Space keep-warm`
   - URL: `https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight`
   - Schedule: every 30 minutes (cron `*/30 * * * *`).
   - Request method: GET.
   - Notifications: enable failure email.
4. Save. The job starts immediately.

You can add a second job pointing at
`https://mikhaeelatefrizk-bindsight.hf.space/` for redundancy.

### UptimeRobot — free tier, 5-min granularity, status page included

1. Visit <https://uptimerobot.com> and sign up for free.
2. Add monitor:
   - Type: HTTP(s).
   - URL: `https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight`.
   - Interval: 5 minutes.
3. (Optional) Add a public status page at `stats.uptimerobot.com/...`
   linkable from this repo's README, so visitors can see live
   reachability.

Free tier covers 50 monitors and unlimited status pages.

---

## Layer 3 — Cloudflare Workers Cron Triggers ($0, geeky-fast)

The most reliable cron path available on a free plan, if you have the
appetite for a 30-line Worker:

1. Sign up at <https://workers.cloudflare.com> (free; no credit card).
2. Create a new Worker called `bindsight-keep-warm`.
3. Paste:
   ```js
   export default {
     async scheduled(event, env, ctx) {
       const urls = [
         "https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight",
         "https://mikhaeelatefrizk-bindsight.hf.space/",
       ];
       await Promise.all(urls.map(u =>
         fetch(u, { method: "GET", redirect: "follow" })
       ));
     },
   };
   ```
4. In **Settings → Triggers**, add Cron `*/15 * * * *` (every 15 min).
5. Deploy.

Cloudflare's free Workers tier covers 100 k requests/day; this uses
~2 k/month. Cron Triggers are free.

This is overkill given Layers 1 + 2, but it's the platform with the
most reliable cron in the free world (no published peak-time skips
unlike GitHub Actions).

---

## Layer 4 — HF Community Grant (best long-term outcome, $0)

The cleanest fix is to ask Hugging Face directly for free hardware
upgrade. They grant ZeroGPU and persistent CPU upgrades to qualifying
open-source / scientific projects (bindsight qualifies: JOSS
submission, Zenodo DOI, MIT licensed, no commercial backing).

How to apply:

1. On the Space page → **Settings → Hardware → Request community grant**.
2. Mention:
   - bindsight is open-source under MIT.
   - JOSS submission in review; Zenodo DOI 10.5281/zenodo.20121496.
   - Scientific reproducibility tooling for the cancer immunotherapy
     research community.
3. Wait. HF reviews these in 1–4 weeks.

If granted, the Space gets a persistent CPU upgrade (no auto-sleep)
at no charge.

---

## Detecting that the system is working

Cheapest way to spot-check from your workstation:

```bash
curl -s "https://huggingface.co/api/spaces/Mikhaeelatefrizk/bindsight" \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['runtime']; \
                print('stage:', r['stage']); \
                print('domain:', r['domains'][0]['stage'])"
```

Expected output when warm:
```
stage: RUNNING
domain: READY
```

If you ever see `SLEEPING` / `STOPPED` and Layer 1 has been firing
green, that's an HF-side incident; check
<https://status.huggingface.co>.

---

## Manual recovery (when all else fails)

If the HF Space is wedged:

1. Go to <https://huggingface.co/spaces/Mikhaeelatefrizk/bindsight/settings>
2. Click **Factory rebuild** (forces a fresh image build from current
   GitHub `main`).
3. Watch the build logs; first build can take 5–10 min as it
   re-installs `bindsight[discover,report]` from PyPI.

If the Streamlit Cloud mirror is wedged:

1. Visit <https://share.streamlit.io> and sign in with the account that
   owns the deploy.
2. Find the `bindsight.streamlit.app` deployment → **Reboot**.
3. Wait 60–120 s for the container to restart.

After a manual reboot, the Layer 1 cron will keep it warm thereafter.
