# Hosting Guide for Keka on Vercel

This guide explains how to host your script on **Vercel** (Serverless) using **Vercel KV (Redis)** for storing tokens.

## Prerequisites
- A GitHub account (to push your code)
- A Vercel account (free)
- [Vercel CLI](https://vercel.com/docs/cli) installed (optional, but good for local dev)

## Step 1: Prepare Repository
1. Initialize a git repository if you haven't:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   ```
2. Push this code to a new GitHub repository (private is recommended).

## Step 2: Deploy to Vercel
1. Go to [Vercel Dashboard](https://vercel.com/dashboard).
2. Click **Add New** > **Project**.
3. Import your GitHub repository.
4. Keep the default build settings.
5. Click **Deploy**.

## Step 3: Configure Storage (Redis)
Since Vercel is serverless, files are deleted after execution. We need a database to store your login tokens.

1. Go to your Vercel Project Dashboard.
2. Click **Storage** tab.
3. Click **Create Database** -> Select **Vercel KV**.
4. Give it a name (e.g., `keka-store`) and region.
5. Once created, click **Connect Project** and select your project.
   - This automatically sets environment variables like `KV_URL`, `KV_REST_API_URL`, etc.

## Step 4: Final Setup (Authentication)
You need to generate the initial tokens and save them to the Redis store. You can do this by running the script locally *connected* to the remote Redis, or by manually setting the environment variables locally.

**Easiest Method: Run Locally with Linked Project**
1. Install Vercel CLI: `npm i -g vercel`
2. Link your local folder to the Vercel project:
   ```bash
   vercel link
   ```
3. Pull environment variables (including Redis credentials):
   ```bash
   vercel env pull .env.local
   ```
4. Run the setup script using these variables:
   ```bash
   # Export variables from .env.local first, or just run python if you trust the script to pick up .env (it doesn't by default without python-dotenv)
   # Better way:
   export KV_URL="redis://default:..." (copy value from .env.local)
   python3 keka.py setup
   ```
   
   If `python3 keka.py setup` detects the `KV_URL`, it will say "Tokens saved to Redis".

## Step 5: Verify Cron Jobs
1. Go to your Vercel Project > **Settings** > **Cron Jobs**.
2. You should see two jobs listed (03:30 UTC for 9:00 AM IST, etc).
3. They will run automatically on weekdays.

## Troubleshooting
- **Check Logs**: Go to Vercel Dashboard > **Logs** to see if the cron job ran and what happened.
- **Token Issues**: If logs say "No tokens found", repeat Step 4 to ensure tokens are in Redis.


## Hobby plan limitation (important)
- Vercel Hobby only supports daily cron schedules.
- Do **not** add a `0 */3 * * *` token-refresh cron on Hobby, it will fail validation.
- This project is designed to refresh tokens during the actual clock-in/out runs, so it still works without a separate refresh cron.



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


- If login shows **"An error occured while processing your request"**, your `redirect_uri` is not allowed for this OAuth client.
  - Default client usually allows `https://alchemy.keka.com`.
  - `?action=auth-url` now returns `redirect_uri=...` so you can verify what is being sent.
  - Only set `KEKA_USE_DYNAMIC_CALLBACK=true` if your Keka OAuth app explicitly whitelists your Vercel callback URL.
