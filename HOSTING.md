# Hosting Notes

For full instructions, use **README.md**.

## Required pieces
- Vercel project deployment
- Vercel KV connected (`KV_URL`)
- One-time OAuth login via `/api/cron?action=auth-start`

## Debug endpoints
- `/api/cron?action=status`
- `/api/cron?action=auth-url`

## Common issue
If you see provider page saying *"An error occured while processing your request"*, verify that the `redirect_uri` returned by `?action=auth-url` is whitelisted in your Keka OAuth settings.
