# Deployment Guide

This project is now documented in **README.md** with simplified setup and troubleshooting.

## Quick start
1. Deploy to Vercel.
2. Attach Vercel KV.
3. Set `KEKA_REDIRECT_URI` (recommended default: `https://alchemy.keka.com`).
4. Open `https://<your-domain>/api/cron?action=auth-start` and login once.
5. Verify `https://<your-domain>/api/cron?action=status`.

## Notes
- Vercel Hobby supports only daily cron expressions.
- Token refresh is handled during clock-in/out runs.
