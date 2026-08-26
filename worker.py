import os
import asyncio
import logging
import aiohttp
from telegram import Bot

logger = logging.getLogger("worker")

async def process_export_queue(bot_token: str, chat_id: str, notebook_title: str, items: list, cookies: str = ""):
    """Railway cloud server downloads authenticated Google CDN files and streams to Telegram."""
    bot = Bot(token=bot_token)
    total_items = len(items)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🚀 **Starting Cloud Studio Export**\n"
                f"📁 **Notebook:** `{notebook_title}`\n"
                f"📦 **Total Items:** `{total_items}`\n\n"
                f"⚡ _Railway cloud server is downloading & streaming directly to Telegram..._"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send initial status message: {e}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": "https://notebook.google.com/",
        "Origin": "https://notebook.google.com"
    }
    if cookies:
        headers["Cookie"] = cookies

    success_count = 0

    for idx, item in enumerate(items, start=1):
        title = item.get("title", f"Studio_Item_{idx}").replace("/", "_").replace("\\", "_").strip()
        url = item.get("url", "").strip()
        item_type = item.get("type", "video").lower()

        if not url or url.startswith("blob:"):
            logger.warning(f"Skipping {title}: Invalid or empty URL")
            continue

        temp_ext = "mp4" if item_type == "video" else "mp3" if item_type == "audio" else "txt"
        temp_file = f"/tmp/{idx}_{title}.{temp_ext}"

        try:
            # 1. Railway server downloads file using Google Auth Cookies
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                    if resp.status == 200:
                        with open(temp_file, "wb") as f:
                            while chunk := await resp.content.read(1024 * 1024):
                                f.write(chunk)
                    else:
                        logger.error(f"Failed download for {title}: HTTP {resp.status}")
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ [{idx}/{total_items}] Could not download `{title}` (HTTP {resp.status})."
                        )
                        continue

            # 2. Check File Size (Telegram Standard Bot Upload Limit: 50MB)
            file_size_mb = os.path.getsize(temp_file) / (1024 * 1024)
            if file_size_mb > 49.5:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"⚠️ [{idx}/{total_items}] `{title}` is {file_size_mb:.1f} MB (exceeds Telegram 50MB bot upload limit).\n\n"
                        f"🔗 **Direct Auth Link:** {url}"
                    )
                )
                success_count += 1
            else:
                # 3. Stream from Railway directly into Telegram
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

        # Safe rate limit delay between Telegram dispatches
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
        logger.error(f"Failed to send completion message: {e}")
