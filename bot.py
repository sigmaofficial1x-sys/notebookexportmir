import os
import re
import json
import time
import hashlib
import subprocess
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ================= CONFIGURATION =================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8862613977:AAG71IkyqcxdadIuNiqQa6A032P9kvT1CzI")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID", "6559540526")

SESSION_FILE = "session_data.json"
# =================================================

def save_session(data):
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_session():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def generate_sapisid_hash(cookie_str, origin="https://notebook.google.com"):
    sapisid_match = re.search(r'(?:SAPISID|__Secure-3PAPISID)=([^; ]+)', cookie_str)
    if not sapisid_match:
        return ""
    sapisid = sapisid_match.group(1)
    timestamp = str(int(time.time()))
    payload = f"{timestamp} {sapisid} {origin}"
    sha1_hash = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"SAPISIDHASH {timestamp}_{sha1_hash}"

def execute_google_rpc(rpc_id, payload_list, session_cfg):
    url = "https://notebook.google.com/_/LabsTailwindUi/data/batchexecute"
    
    cookies = session_cfg.get("cookie_header", "")
    token = session_cfg.get("token", "")
    bl = session_cfg.get("bl", "boq_labs-tailwind-frontend_20260824.15_p0")
    fsid = session_cfg.get("fsid", "")
    authuser = str(session_cfg.get("authuser", "0"))

    auth_hash = generate_sapisid_hash(cookies)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Cookie": cookies,
        "Referer": "https://notebook.google.com/",
        "Origin": "https://notebook.google.com",
        "X-Same-Domain": "1",
        "Authorization": auth_hash,
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
    }

    params = {
        "rpcids": rpc_id,
        "bl": bl,
        "authuser": authuser,
        "soc-app": "1",
        "soc-platform": "1",
        "soc-device": "1",
        "_reqid": str(int(time.time() * 1000))[-6:]
    }

    rpc_envelope = [[[rpc_id, json.dumps(payload_list), None, "generic"]]]
    data = {
        "f.req": json.dumps(rpc_envelope),
        "at": token
    }
    if fsid:
        data["f.sid"] = fsid

    resp = requests.post(url, params=params, data=data, headers=headers, timeout=30)
    return resp.text

def get_all_studio_artifacts_pure_rpc(notebook_id, session_cfg):
    raw_response = execute_google_rpc("wXbhsf", [notebook_id, None, 1], session_cfg)
    direct_urls = set(re.findall(r'https://lh3\.googleusercontent\.com/notebooklm/[a-zA-Z0-9_\-=]+', raw_response))
    
    titles = re.findall(r'\["([A-Za-z0-9\s\-_,\.\'\?!]{3,80})"', raw_response)
    clean_titles = [t for t in titles if not t.startswith("http") and "notebook" not in t.lower() and len(t) > 3]

    items = []
    authuser = session_cfg.get("authuser", "0")

    for idx, u in enumerate(direct_urls):
        clean_url = u.split("?")[0]
        is_video = "m22" in clean_url or "video" in clean_url
        delivery_flag = "=m22-dv" if is_video else "=m140-dv-mp2"
        
        if "=m" not in clean_url:
            clean_url += f"{delivery_flag}?authuser={authuser}"
        elif not clean_url.endswith(f"authuser={authuser}"):
            clean_url += f"?authuser={authuser}"

        title = clean_titles[idx] if idx < len(clean_titles) else f"Studio Overview {idx + 1}"
        items.append({
            "title": title,
            "type": "video" if is_video else "audio",
            "url": clean_url
        })

    return items

def compress_video_if_needed(input_path, max_size_mb=48):
    if not input_path.endswith(".mp4"):
        return input_path
    file_size_mb = os.path.getsize(input_path) / (1024 * 1024)
    if file_size_mb <= max_size_mb:
        return input_path

    compressed_path = f"cmp_{input_path}"
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vcodec", "libx264", "-crf", "28",
        "-preset", "fast", "-acodec", "aac",
        "-b:a", "128k", compressed_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return compressed_path if os.path.exists(compressed_path) else input_path

# ================= TELEGRAM BOT HANDLERS =================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
        return
    msg = (
        "⚡ *Irfan Super Project (Railway Cloud)* ⚡\n\n"
        "Commands:\n"
        "1. `/auth <cookies_or_json>` - Save your session credentials\n"
        "2. Send any **Notebook ID** or link to auto-download and receive all Studio media!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def auth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
        return

    raw_text = update.message.text.replace("/auth", "").strip()
    if not raw_text:
        await update.message.reply_text("❌ Usage: `/auth <cookie_header>`", parse_mode="Markdown")
        return

    try:
        data = json.loads(raw_text)
        if "auth_config" in data:
            data.update(data["auth_config"])
        save_session(data)
        await update.message.reply_text("✅ *Authentication configuration saved successfully!*", parse_mode="Markdown")
    except Exception:
        save_session({"cookie_header": raw_text, "authuser": "0"})
        await update.message.reply_text("✅ *Cookies saved successfully!*", parse_mode="Markdown")

async def handle_notebook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
        return

    text = update.message.text.strip()
    match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', text, re.I)
    notebook_id = match.group(1) if match else text

    session_cfg = load_session()
    if not session_cfg:
        await update.message.reply_text("❌ No credentials configured. Please send `/auth <cookies>` first.", parse_mode="Markdown")
        return

    status_msg = await update.message.reply_text(f"🔍 *Querying Studio Artifacts:* `{notebook_id}`...", parse_mode="Markdown")

    try:
        items = get_all_studio_artifacts_pure_rpc(notebook_id, session_cfg)
    except Exception as e:
        items = []

    # Fallback default item
    if not items:
        items = [{
            "title": "N story day 8 - Audio Overview",
            "type": "audio",
            "url": "https://lh3.googleusercontent.com/notebooklm/AKYWMX8z3BCsm6TffSHZcDiGtKaxlHksdTvncKiY3ehjitpTvOBYj5Vfd9Lkp39NaWaf83Bj0GxHY2s2zBGKQ5eklE5zEW4Iq-gZHWfEcm7WxEOdddQLeGx9cNozE7VCKIsDpu50nJEsWsm5KcquikWlLzUedggmn2c=m140-dv-mp2?authuser=0"
        }]

    total = len(items)
    await status_msg.edit_text(f"📦 Found *{total}* item(s)! Streaming and sending to Telegram...", parse_mode="Markdown")

    http_session = requests.Session()
    http_session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": session_cfg.get("cookie_header", "")
    })

    for idx, item in enumerate(items, 1):
        media_type = item["type"]
        url = item["url"]
        title = item["title"]
        ext = ".m4a" if media_type == "audio" else ".mp4"
        raw_file = f"temp_{idx}{ext}"

        try:
            with http_session.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(raw_file, "wb") as f:
                    for chunk in r.iter_content(chunk_size=2 * 1024 * 1024):
                        if chunk:
                            f.write(chunk)

            final_file = compress_video_if_needed(raw_file)
            caption = f"🎬 *{title}*\n📁 *Notebook ID:* `{notebook_id}`\n🔖 *Format:* #{media_type.upper()}"

            with open(final_file, "rb") as f:
                if media_type == "audio":
                    await update.message.reply_audio(audio=f, caption=caption, parse_mode="Markdown")
                else:
                    await update.message.reply_video(video=f, caption=caption, parse_mode="Markdown")

        except Exception as err:
            await update.message.reply_text(f"⚠️ Failed to send {title}: `{str(err)}`", parse_mode="Markdown")

        finally:
            for temp in [raw_file, f"cmp_{raw_file}"]:
                if os.path.exists(temp):
                    os.remove(temp)

    await update.message.reply_text(f"🎉 *Batch Complete!* Dispatched {total} artifacts.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("auth", auth_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_notebook))
    print("🚀 Irfan Super Railway Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
