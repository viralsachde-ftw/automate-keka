# Quick Deployment Guide - Keka Attendance Automation

## 🚀 Best Hosting Option: **Vercel** (Recommended)

**Why Vercel?**
- ✅ Already configured in your project
- ✅ Free tier with reliable cron jobs
- ✅ Built-in Redis (Vercel KV) for token storage
- ✅ Serverless - no server management
- ✅ Runs cron jobs "sharp" on schedule
- ✅ Easy deployment from GitHub

## 📋 Deployment Steps

### 1. Push to GitHub
```bash
git init
git add .
git commit -m "Keka attendance automation"
git remote add origin YOUR_GITHUB_REPO_URL
git push -u origin main
```

### 2. Deploy to Vercel
1. Go to [vercel.com](https://vercel.com) and sign up/login
2. Click **Add New** → **Project**
3. Import your GitHub repository
4. Click **Deploy** (no build settings needed)

### 3. Set Up Vercel KV (Redis)
1. In Vercel Dashboard → Your Project → **Storage** tab
2. Click **Create Database** → Select **Vercel KV**
3. Name it `keka-store` → Choose region → Create
4. Click **Connect Project** → Select your project
   - This auto-adds `KV_URL` environment variable

### 4. Initial Authentication (One-time Setup)
**Option A: Using Vercel CLI (Recommended)**
```bash
npm i -g vercel
cd keka-trial
vercel link
vercel env pull .env.local
# Copy KV_URL from .env.local
export KV_URL="your-kv-url-here"
python keka.py setup
```

**Option B: Manual Token Setup**
1. Run locally: `python keka.py setup`
2. Copy tokens from `keka_tokens.json`
3. In Vercel Dashboard → Storage → Your KV → Add key `keka_tokens` with JSON value

### 5. Verify Cron Jobs
- Go to Vercel Dashboard → Your Project → **Settings** → **Cron Jobs**
- You should see:
  - **Clock In**: `30 3 * * 1-5` (9:00 AM IST weekdays)
  - **Clock Out**: `00 13 * * 1-5` (6:30 PM IST weekdays)

## ⏰ Cron Schedule (IST Timezone)
- **Clock In**: 9:00 AM IST (03:30 UTC) - Monday to Friday
- **Clock Out**: 6:30 PM IST (13:00 UTC) - Monday to Friday


## 🔐 Token Expiry Reality Check
- Hobby accounts only allow daily cron schedules on Vercel, so avoid `0 */3 * * *` unless you are on Pro.
- Access tokens are short-lived (few hours) by design.
- On Hobby plan, this project does **not** use a separate 3-hour refresh cron. Instead, each clock-in/out run refreshes proactively when needed, and retries once with a forced refresh if Keka returns 401/403.
- If refresh token itself is revoked/expired by Keka, you must run `python keka.py setup` again to re-authenticate.
- You can check token health quickly via: `https://your-app.vercel.app/api/cron?action=status`

## 🔍 Monitoring
- Check logs: Vercel Dashboard → **Logs** tab
- Test manually: Visit `https://your-app.vercel.app/api/cron?action=in` or `?action=out`

## 🆚 Alternative Hosting Options

### Railway (Good Alternative)
- Pros: Simple, $5/month, persistent storage
- Cons: Paid, need to set up cron differently

### Render (Free Tier Available)
- Pros: Free tier, cron support
- Cons: Free tier spins down after inactivity

### PythonAnywhere (Simple)
- Pros: Easy Python hosting, cron support
- Cons: Less modern, limited free tier

### GitHub Actions (Free but Limited)
- Pros: Free, reliable
- Cons: Not designed for this, rate limits

## ✅ Why Vercel Wins
1. **Free tier** covers your needs
2. **Reliable cron** execution (runs sharp on time)
3. **Already configured** in your project
4. **No server management** needed
5. **Built-in Redis** (Vercel KV) for token storage
6. **Easy monitoring** via dashboard

---

**Your cron jobs are configured to run sharp at:**
- 9:00 AM IST (clock in)
- 6:30 PM IST (clock out)

Both run Monday-Friday only (weekdays).


### Fallback token bootstrap (if Redis key is empty)
- Set one of these in Vercel Project → Settings → Environment Variables:
  - `KEKA_TOKENS_JSON` (JSON with `access_token`, `refresh_token`, optional `token_expiry`)
  - or `KEKA_REFRESH_TOKEN` (optionally with `KEKA_ACCESS_TOKEN`, `KEKA_TOKEN_EXPIRY`)
- On first run, the app will load these and write them to Redis automatically.


## 🔄 Fully automated web re-auth (no code copy/paste)
1. Set `KEKA_REDIRECT_URI` to `https://your-app.vercel.app/api/cron?action=oauth-callback` in Vercel env vars.
2. Simplest: open `https://your-app.vercel.app/api/cron?action=auth-start` (auto-redirects to Keka login).
   - Alternate: use `?action=auth-url` and open `open_url=...` manually.
3. Login to Keka and approve.
4. Keka redirects back to `/api/cron?action=oauth-callback&code=...&state=...` and tokens are saved automatically to Redis.

Use this same flow anytime refresh token is revoked/expired.
