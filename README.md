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
- Status: `https://automate-keka.vercel.app/api/cron?action=status`
- Test clock-in: `https://automate-keka.vercel.app/api/cron?action=in`
- Test clock-out: `https://automate-keka.vercel.app/api/cron?action=out`
- OAuth helper info: `https://automate-keka.vercel.app/api/cron?action=auth-start`

---

## Web OAuth flow (optional, advanced)
Use only if your Keka OAuth client whitelists your callback URL.

1. Set env vars:
   - `KEKA_REDIRECT_URI=https://automate-keka.vercel.app/api/cron?action=oauth-callback`
   - `KEKA_USE_DYNAMIC_CALLBACK=true`
2. Open: `https://automate-keka.vercel.app/api/cron?action=auth-start`
3. Copy/open the `auth_url` shown in response.

If provider shows **"An error occured while processing your request"**, callback is not whitelisted. Use the reliable local setup (`python keka.py setup`) instead.

---

## If you see "No tokens found"
Either:
- run local setup once (`python keka.py setup` with `KV_URL`), or
- set fallback envs: `KEKA_TOKENS_JSON` or `KEKA_REFRESH_TOKEN` (+ optional access token/expiry).
