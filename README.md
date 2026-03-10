# Keka Attendance Automation

Auto clock-in/clock-out on weekdays using Vercel cron + Redis token storage.

## The easiest working setup (recommended)

### 1) Deploy + KV
1. Deploy this repo to Vercel.
2. Add **Vercel KV** and connect it to the project (sets `KV_URL`).

### 2) One-time token setup (most reliable)
Do this on your local machine:

```bash
npm i -g vercel
vercel link
vercel env pull .env.local
# copy KV_URL from .env.local
export KV_URL="redis://..."
python keka.py setup
```

This saves tokens directly into your Vercel KV.

### 3) Done
Cron is already configured:
- clock in: `30 3 * * 1-5` (9:00 AM IST)
- clock out: `00 13 * * 1-5` (6:30 PM IST)

---

## URLs you can use
- Status: `https://<your-domain>/api/cron?action=status`
- Test clock-in: `https://<your-domain>/api/cron?action=in`
- Test clock-out: `https://<your-domain>/api/cron?action=out`
- One-click OAuth (no copy/paste): `https://<your-domain>/api/cron?action=auth-auto`
- OAuth helper info: `https://<your-domain>/api/cron?action=auth-start`

---

## Web OAuth flow (optional, advanced)
Use only if your Keka OAuth client whitelists your callback URL.

### Fully automated (no copy/paste)
1. Open: `https://<your-domain>/api/cron?action=auth-auto`
2. Login in Keka. Callback should return to your app and save tokens automatically.
3. Verify with `?action=status` (expect `loaded=True`).

If your setup requires explicit control, use env vars:
- `KEKA_USE_DYNAMIC_CALLBACK=true` (force app callback)
- `KEKA_USE_STATIC_REDIRECT=true` (force `KEKA_REDIRECT_URI` value)

If provider shows **"An error occured while processing your request"**, callback is not whitelisted. Use local setup (`python keka.py setup`) or whitelist callback properly.

---

## If you see "No tokens found"
Either:
- run local setup once (`python keka.py setup` with `KV_URL`), or
- set fallback envs: `KEKA_TOKENS_JSON` or `KEKA_REFRESH_TOKEN` (+ optional access token/expiry).
