import os
import asyncio
import logging
import aiohttp
from telegram import Bot

logger = logging.getLogger("worker")

async def process_export_queue(bot_token: str, chat_id: str, notebook_title: str, items: list, cookies: str = ""):
    """Railway cloud server downloads Google CDN files and delivers native video and audio to Telegram."""
    bot = Bot(token=bot_token)
    total_items = len(items)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🚀 **Starting Studio Media Export**\n"
                f"📁 **Notebook:** `{notebook_title}`\n"
                f"📦 **Total Items:** `{total_items}`\n\n"
                f"⚡ _Downloading MP4 videos and MP3 audio in the cloud..._"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send initial status: {e}")

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

        # If it's a video or undefined, make it MP4. If audio, make it MP3.
        temp_ext = "mp3" if item_type == "audio" else "mp4"
        temp_file = f"/tmp/{idx}_{title}.{temp_ext}"

        if not url or "notebook.google.com" in url:
            caption = f"📌 [{idx}/{total_items}] **{title}** ({item_type.upper()})\n📁 `{notebook_title}`"
            try:
                await bot.send_message(chat_id=chat_id, text=caption, parse_mode="Markdown")
                success_count += 1
            except Exception as e:
                logger.error(f"Error sending card: {e}")
            await asyncio.sleep(2.0)
            continue

        try:
            # 1. Download file from Google CDN
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                    if resp.status == 200:
                        with open(temp_file, "wb") as f:
                            while chunk := await resp.content.read(1024 * 1024):
                                f.write(chunk)
                    else:
                        logger.error(f"Download failed for {title}: HTTP {resp.status}")
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ [{idx}/{total_items}] Could not download `{title}` (HTTP {resp.status})."
                        )
                        continue

            # 2. Check File Size (Telegram Bot Limit: 50MB)
            file_size_mb = os.path.getsize(temp_file) / (1024 * 1024)
            if file_size_mb > 49.5:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"⚠️ [{idx}/{total_items}] `{title}` is {file_size_mb:.1f} MB (exceeds Telegram 50MB bot limit).\n\n"
                        f"🔗 **Direct Auth Link:** {url}"
                    )
                )
                success_count += 1
            else:
                # 3. Send video directly as Telegram Video or Audio
                caption = f"[{idx}/{total_items}] 📁 {notebook_title}\n📌 {title}"
                with open(temp_file, "rb") as media_file:
                    if temp_ext == "mp4":
                        await bot.send_video(
                            chat_id=chat_id,
                            video=media_file,
                            caption=caption,
                            supports_streaming=True
                        )
                    else:
                        await bot.send_audio(
                            chat_id=chat_id,
                            audio=media_file,
                            caption=caption
                        )
                
                success_count += 1

        except Exception as e:
            logger.error(f"Error uploading {title}: {e}")
            await bot.send_message(chat_id=chat_id, text=f"❌ Error on `{title}`: {str(e)}")
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

        # 2.5s safe delay to prevent Telegram flood limits
        await asyncio.sleep(2.5)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🎉 **Batch Export Finished!**\n\n"
                f"✅ **Delivered:** `{success_count}/{total_items}` media files\n"
                f"📁 **Notebook:** `{notebook_title}`"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error sending final completion: {e}")
        
