import os
import asyncio
import logging
import aiohttp
from telegram import Bot

logger = logging.getLogger("worker")

async def process_export_queue(bot_token: str, chat_id: str, notebook_title: str, cookies: str, items: list):
    """Processes items one by one, downloads them, and pushes them to Telegram safely."""
    bot = Bot(token=bot_token)
    
    total_items = len(items)
    await bot.send_message(
        chat_id=chat_id,
        text=f"🚀 **Starting Studio Export for:** `{notebook_title}`\n📦 **Total Items:** {total_items}\n\n_Processing in background..._",
        parse_mode="Markdown"
    )

    headers = {
        "Cookie": cookies,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": "https://notebooklm.google.com/"
    }

    success_count = 0

    for idx, item in enumerate(items, start=1):
        title = item.get("title", f"Studio_Item_{idx}").replace("/", "_")
        url = item.get("url")
        item_type = item.get("type", "video").lower()

        if not url:
            logger.warning(f"Skipping {title} (no direct URL)")
            continue

        temp_ext = "mp4" if item_type == "video" else "mp3" if item_type == "audio" else "txt"
        temp_file = f"/tmp/{idx}_{title}.{temp_ext}"

        try:
            # 1. Download file from Google CDN
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                    if resp.status == 200:
                        with open(temp_file, "wb") as f:
                            while chunk := await resp.content.read(1024 * 1024):
                                f.write(chunk)
                    else:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ [{idx}/{total_items}] Failed downloading `{title}` (HTTP {resp.status})."
                        )
                        continue

            # 2. Check File Size (Telegram Standard Bot Limit: 50MB)
            file_size_mb = os.path.getsize(temp_file) / (1024 * 1024)
            if file_size_mb > 49.5:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ [{idx}/{total_items}] `{title}` is {file_size_mb:.1f} MB (exceeds Telegram 50MB limit).\nDirect Link: {url}"
                )
            else:
                # 3. Send to Telegram
                with open(temp_file, "rb") as media_file:
                    caption = f"[{idx}/{total_items}] 📁 {notebook_title}\n📌 {title}"
                    if item_type == "video":
                        await bot.send_video(chat_id=chat_id, video=media_file, caption=caption)
                    elif item_type == "audio":
                        await bot.send_audio(chat_id=chat_id, audio=media_file, caption=caption)
                    else:
                        await bot.send_document(chat_id=chat_id, document=media_file, caption=caption)
                
                success_count += 1

            # Cleanup temp file
            if os.path.exists(temp_file):
                os.remove(temp_file)

        except Exception as e:
            logger.error(f"Error processing item {title}: {e}")
            await bot.send_message(chat_id=chat_id, text=f"❌ Error uploading `{title}`: {str(e)}")
            if os.path.exists(temp_file):
                os.remove(temp_file)

        # Telegram Flood Control: 2.5 second safe delay between files
        await asyncio.sleep(2.5)

    await bot.send_message(
        chat_id=chat_id,
        text=f"🎉 **Export Completed!**\n✅ Successfully exported {success_count}/{total_items} items from `{notebook_title}`.",
        parse_mode="Markdown"
    )
