import os
import asyncio
import logging
import aiohttp
from telegram import Bot

logger = logging.getLogger("worker")

async def process_export_queue(bot_token: str, chat_id: str, notebook_title: str, items: list):
    """Processes extracted items, streams/downloads them, and delivers them directly to Telegram."""
    bot = Bot(token=bot_token)
    total_items = len(items)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🚀 **Starting Studio Export**\n"
                f"📁 **Notebook:** `{notebook_title}`\n"
                f"📦 **Total Items:** `{total_items}`\n\n"
                f"⏳ _Exporting files in background..._"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send initial status message: {e}")

    success_count = 0

    for idx, item in enumerate(items, start=1):
        title = item.get("title", f"Studio_Item_{idx}").replace("/", "_").strip()
        url = item.get("url", "").strip()
        item_type = item.get("type", "video").lower()

        # If it's a page link or empty, provide a clean reference card
        if not url or "notebook.google.com" in url:
            caption = f"📌 [{idx}/{total_items}] **{title}**\n📁 Notebook: `{notebook_title}`\n🔗 Reference: {url}"
            try:
                await bot.send_message(chat_id=chat_id, text=caption, parse_mode="Markdown")
                success_count += 1
            except Exception as e:
                logger.error(f"Error sending note/link card: {e}")
            await asyncio.sleep(2.0)
            continue

        temp_ext = "mp4" if item_type == "video" else "mp3" if item_type == "audio" else "txt"
        temp_file = f"/tmp/{idx}_{title}.{temp_ext}"

        try:
            # 1. Download file from Google CDN / Storage
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                    if resp.status == 200:
                        with open(temp_file, "wb") as f:
                            while chunk := await resp.content.read(1024 * 1024):
                                f.write(chunk)
                    else:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ [{idx}/{total_items}] Could not download `{title}` (HTTP {resp.status})."
                        )
                        continue

            # 2. Check File Size (Standard Telegram Bot Upload Limit: 50MB)
            file_size_mb = os.path.getsize(temp_file) / (1024 * 1024)
            if file_size_mb > 49.5:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"⚠️ [{idx}/{total_items}] `{title}` is {file_size_mb:.1f} MB (exceeds Telegram 50MB bot upload limit).\n\n"
                        f"🔗 **Direct Link:** {url}"
                    )
                )
                success_count += 1
            else:
                # 3. Send file directly to Telegram
                caption = f"[{idx}/{total_items}] 📁 {notebook_title}\n📌 {title}"
                with open(temp_file, "rb") as media_file:
                    if item_type == "video":
                        await bot.send_video(chat_id=chat_id, video=media_file, caption=caption)
                    elif item_type == "audio":
                        await bot.send_audio(chat_id=chat_id, audio=media_file, caption=caption)
                    else:
                        await bot.send_document(chat_id=chat_id, document=media_file, caption=caption)
                
                success_count += 1

        except Exception as e:
            logger.error(f"Error processing item {title}: {e}")
            await bot.send_message(
                chat_id=chat_id,
                text=f"❌ Error uploading `{title}`: {str(e)}"
            )
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

        # Safe rate limit delay (2.5s) to avoid Telegram 429 FloodWait
        await asyncio.sleep(2.5)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🎉 **Batch Export Finished!**\n\n"
                f"✅ **Processed:** `{success_count}/{total_items}` items\n"
                f"📁 **Notebook:** `{notebook_title}`"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send final completion message: {e}")
        
