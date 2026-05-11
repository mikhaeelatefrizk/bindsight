# Setting up a custom domain for the Streamlit demo

The default URL is `https://bindsight.streamlit.app`. A custom domain like
`bindsight.org` or `bindsight.app` looks more professional on a CV / paper /
talk slide and is permanent (independent of Streamlit Cloud's branding).

This is **optional** — `bindsight.streamlit.app` works fine and is permanent.
Custom domains add ~$12/year cost and ~10 minutes of one-time setup.

---

## Step 1 — Pick + buy a domain (~3 min, ~$12/year)

Recommended registrars (in priority order — by support quality + privacy):

| Registrar | Cost (`.org`) | Cost (`.app`) | Notes |
|---|---|---|---|
| Cloudflare | $9.15 | $13.50 | At-cost pricing; best Whois privacy; recommended |
| Porkbun | $9.13 | $13.32 | Free Whois privacy; no upsells |
| Namecheap | $11.98 | $14.98 | Common, well-known |

**Suggested name picks (check availability):**

- `bindsight.org` — non-profit-sounding, fits open-science vibe
- `bindsight.app` — modern, app-y; paired well with the Streamlit URL
- `bindsight.bio` — bio-specific TLD (~$70/year, more expensive)
- `bindsight.dev` — dev-focused (Google-controlled TLD, ~$15/year, requires HTTPS)
- `bind-sight.com` — fallback with hyphen if .com taken

**Steps for Cloudflare:**

1. Go to https://dash.cloudflare.com/?to=/:account/registrar
2. Search for `bindsight.org` (or your pick)
3. Click "Purchase" → confirm with payment
4. Cloudflare auto-configures DNS; you'll have control over records in ~2 min

## Step 2 — Configure DNS (~5 min)

Streamlit Cloud needs a CNAME record pointing your domain to their app.

### In Cloudflare DNS dashboard:

1. Go to https://dash.cloudflare.com/?to=/:account/<your-zone>/dns/records
2. Add a CNAME record:
   - **Type:** `CNAME`
   - **Name:** `@` (for root `bindsight.org`) OR `app` (for `app.bindsight.org`)
   - **Target:** `bindsight.streamlit.app`
   - **Proxy status:** **DNS only** (gray cloud) — Streamlit Cloud handles its own TLS
   - **TTL:** Auto
3. Save

If you want both `bindsight.org` AND `www.bindsight.org` to work, add a
second CNAME with name=`www`, target=`bindsight.streamlit.app`.

### TTL note

Cloudflare's DNS propagates globally in ~30 seconds. Other registrars can
take up to 4 hours.

## Step 3 — Tell Streamlit Cloud about the domain (~2 min)

1. Go to https://share.streamlit.io
2. Click your bindsight app → settings (right sidebar gear icon) → General
3. Under "Custom subdomain" or "Custom domain":
   - Enter `bindsight.org` (or whatever you bought)
   - Click "Save"
4. Streamlit Cloud will issue a Let's Encrypt TLS certificate within ~2 min
5. Test: open `https://bindsight.org` — should serve your Streamlit app

## Step 4 — Update README + CITATION.cff (~30 sec)

Once `https://bindsight.org` is live:

```bash
# Replace bindsight.streamlit.app with bindsight.org everywhere
git ls-files -z | xargs -0 sed -i 's/bindsight\.streamlit\.app/bindsight.org/g'
git diff
git add -A
git commit -m "docs: switch to bindsight.org custom domain"
git push
```

The Streamlit Cloud URL (`bindsight.streamlit.app`) keeps working as a
backup; you're just promoting `bindsight.org` to be the canonical URL.

## Step 5 — (Optional) Email forwarding

If you bought `bindsight.org`, you can also set up email forwarding so
`hello@bindsight.org` → `mikhaeelatefrizk@proton.me`:

**Cloudflare Email Routing** (free):
1. https://dash.cloudflare.com → Email → Email Routing → Get started
2. Add forwarding rule: `hello@bindsight.org` → `mikhaeelatefrizk@proton.me`
3. Verify the destination email
4. Streamlit Cloud / GitHub / Zenodo can now use `hello@bindsight.org` as
   a contact address

---

## Cost summary

| One-time | Recurring (yearly) |
|---|---|
| Domain registration: $9–14 | Domain renewal: $9–14 |
| | (No fees from Cloudflare DNS or Streamlit Cloud) |

Total recurring: **~$10/year**. Streamlit Cloud is free; Cloudflare DNS is
free; Let's Encrypt TLS is free.

---

## Why I can't do this for you

Domain purchase requires entering your payment details and consenting to
the registrar's terms of service. After purchase, the domain is your
property and the registrar holds you legally accountable for it. This is
exactly the kind of action my safety rules require you to do yourself,
and rightly so — a domain is a long-term commercial commitment.

Once you've bought and configured the DNS, the Streamlit Cloud setup
(steps 3–4) takes ~3 minutes and I can drive your browser through it if
you ask.
