# Keka Attendance Automation (Vercel)

Simple cron-based auto clock-in / clock-out for Keka with token auto-refresh.

## What this does
- Runs two cron jobs on weekdays:
  - **Clock in** at 9:00 AM IST
  - **Clock out** at 6:30 PM IST
- Stores tokens in **Vercel KV (Redis)**.
- Refreshes tokens automatically during runs.

## One-time setup (recommended)

### 1) Deploy to Vercel
1. Push this repo to GitHub.
2. Import the repo in Vercel.
3. Deploy.

### 2) Add Vercel KV
1. Vercel Project → **Storage** → Create **Vercel KV**.
2. Connect it to this project (this sets `KV_URL`).

### 3) Configure env vars (important)
Set these in Vercel Project → **Settings → Environment Variables**:

- `KEKA_REDIRECT_URI=https://alchemy.keka.com`  
  (Use this default unless your own OAuth app whitelists your Vercel callback)
- Optional: `KEKA_USE_DYNAMIC_CALLBACK=true`  
  (Only if your Keka OAuth app explicitly whitelists `https://<your-domain>/api/cron?action=oauth-callback`)

### 4) Login once (web flow)
Open:
- `https://<your-domain>/api/cron?action=auth-start`

Then login + approve in Keka. After redirect, tokens are saved to Redis.

---

## Daily usage
You do not need to do anything daily.

Cron routes in `vercel.json` run automatically:
- `/api/cron?action=in`
- `/api/cron?action=out`

## Useful endpoints
- Token status:
  - `https://<your-domain>/api/cron?action=status`
- Trigger clock-in manually:
  - `https://<your-domain>/api/cron?action=in`
- Trigger clock-out manually:
  - `https://<your-domain>/api/cron?action=out`
- Get OAuth URL + state (debug):
  - `https://<your-domain>/api/cron?action=auth-url`

## If Redis is empty (fallback)
Set either:
- `KEKA_TOKENS_JSON` (JSON containing `access_token`, `refresh_token`, optional `token_expiry`)
- OR `KEKA_REFRESH_TOKEN` (+ optional `KEKA_ACCESS_TOKEN`, `KEKA_TOKEN_EXPIRY`)

On next run, app loads these and saves into Redis.

## Troubleshooting

### Error: "An error occured while processing your request"
Usually redirect URI mismatch.

1. Open `?action=auth-url` and check returned `redirect_uri=...`.
2. Ensure that redirect URI is whitelisted in the Keka OAuth client.
3. If not whitelisted, use default:
   - `KEKA_REDIRECT_URI=https://alchemy.keka.com`
4. Use dynamic callback only when explicitly whitelisted:
   - `KEKA_USE_DYNAMIC_CALLBACK=true`

### Error: "No tokens found in Redis"
- Complete web login once via `?action=auth-start`, OR
- provide fallback env vars (`KEKA_TOKENS_JSON` or `KEKA_REFRESH_TOKEN...`).

### Vercel cron validation error for `0 */3 * * *`
- Hobby plan does not allow it.
- This project already avoids that cron and refreshes on-demand during clock runs.
