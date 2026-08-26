# ⚡ Irfan Super Project - Railway Telegram Bot

Pure-Python, zero-browser automated cloud exporter for Gemini Notebook (NotebookLM) Studio media artifacts.

## Deployment on Railway
1. Push this repository to GitHub or run `railway up`.
2. Set Environment Variables in Railway Service Settings:
   - `TELEGRAM_BOT_TOKEN` = `77t5:7865`
   - `ALLOWED_USER_ID` = `xyz`
3. In Telegram, message your bot:
   - `/auth <cookie_string>` or `/auth <full_json_config>`
   - Send any Notebook ID or link to export all Studio items!
