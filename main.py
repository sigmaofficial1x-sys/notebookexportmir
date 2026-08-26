import os
import asyncio
import logging
import uvicorn
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

from worker import process_export_queue

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise ValueError("CRITICAL: TELEGRAM_BOT_TOKEN environment variable is not set!")

app = FastAPI(title="NotebookLM Studio Exporter")
tg_app = Application.builder().token(BOT_TOKEN).build()

# --- Telegram Bot Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg = (
        f"👋 **NotebookLM Studio Export Bot is Active!**\n\n"
        f"🆔 **Your Telegram Chat ID:** `{chat_id}`\n\n"
        f"📋 **Setup Instructions:**\n"
        f"1. Copy your Chat ID above.\n"
        f"2. Paste it in your **IrfanLM Tools** Chrome extension popup.\n"
        f"3. Open your notebook in `notebook.google.com` and tap **'Extract & Send to Telegram'**."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

tg_app.add_handler(CommandHandler("start", start_command))

# --- Server Lifecycle ---
@app.on_event("startup")
async def startup_event():
    await tg_app.initialize()
    await tg_app.start()
    asyncio.create_task(tg_app.updater.start_polling(drop_pending_updates=True))
    logger.info("Telegram Bot polling started successfully.")

@app.on_event("shutdown")
async def shutdown_event():
    await tg_app.updater.stop()
    await tg_app.stop()
    await tg_app.shutdown()

# --- Health Check ---
@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "NotebookLM Studio Exporter"
    }

# --- Batch Export Webhook (No Pydantic Strict Checks = Zero 422 Errors) ---
@app.post("/api/export-batch")
async def export_batch(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"Failed to decode JSON: {e}")
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON body"})

    chat_id = str(data.get("chat_id") or "")
    notebook_id = str(data.get("notebook_id") or "")
    notebook_title = str(data.get("notebook_title") or "Notebook Export")
    raw_items = data.get("items") or []

    if not chat_id:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Missing chat_id"})

    # Normalize items to ensure safe execution
    clean_items = []
    for idx, itm in enumerate(raw_items, start=1):
        if isinstance(itm, dict):
            clean_items.append({
                "title": str(itm.get("title") or f"Item {idx}"),
                "type": str(itm.get("type") or "video"),
                "url": str(itm.get("url") or "")
            })

    logger.info(f"Accepted batch of {len(clean_items)} items for notebook '{notebook_title}' (Chat ID: {chat_id})")

    # Run queue in background
    background_tasks.add_task(
        process_export_queue,
        bot_token=BOT_TOKEN,
        chat_id=chat_id,
        notebook_title=notebook_title,
        items=clean_items
    )

    return JSONResponse(content={
        "ok": True,
        "status": "queued",
        "total_items": len(clean_items),
        "notebook": notebook_title
    })

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
