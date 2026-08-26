import os
import asyncio
import logging
import uvicorn
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

from worker import process_export_queue

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("app")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is missing!")

app = FastAPI(title="NotebookLM Studio Exporter")
tg_app = Application.builder().token(BOT_TOKEN).build()

# Pydantic Schemas
class StudioItem(BaseModel):
    title: str
    type: str  # 'video' | 'audio' | 'document'
    url: str

class ExportBatchRequest(BaseModel):
    chat_id: str
    notebook_id: str
    notebook_title: str
    cookies: str
    items: List[StudioItem]

# Telegram Bot Commands
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    welcome_msg = (
        f"👋 **NotebookLM Studio Export Bot is Active!**\n\n"
        f"Your Chat ID: `{chat_id}`\n\n"
        f"📋 **Setup Instructions:**\n"
        f"1. Copy your Chat ID above.\n"
        f"2. Paste it into your **IrfanLM Tools** Chrome extension popup.\n"
        f"3. Open your notebook on NotebookLM and click **'Extract & Send to Telegram'**."
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

tg_app.add_handler(CommandHandler("start", start_command))

@app.on_event("startup")
async def startup_event():
    await tg_app.initialize()
    await tg_app.start()
    # Start Telegram polling in background
    asyncio.create_task(tg_app.updater.start_polling(drop_pending_updates=True))
    logger.info("Telegram Bot polling started successfully.")

@app.on_event("shutdown")
async def shutdown_event():
    await tg_app.updater.stop()
    await tg_app.stop()
    await tg_app.shutdown()

@app.get("/")
def health_check():
    return {"status": "ok", "service": "NotebookLM Studio Exporter"}

@app.post("/api/export-batch")
async def export_batch(payload: ExportBatchRequest, background_tasks: BackgroundTasks):
    """Endpoint called by the Chrome Extension to trigger cloud background export."""
    if not payload.items:
        raise HTTPException(status_code=400, detail="No studio items provided in payload.")

    logger.info(f"Received batch of {len(payload.items)} items for notebook: {payload.notebook_title}")

    # Queue export task to run in the background
    background_tasks.add_task(
        process_export_queue,
        bot_token=BOT_TOKEN,
        chat_id=payload.chat_id,
        notebook_title=payload.notebook_title,
        cookies=payload.cookies,
        items=[item.dict() for item in payload.items]
    )

    return {
        "status": "queued",
        "message": f"Queued {len(payload.items)} items for export.",
        "notebook": payload.notebook_title
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
