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

def generate_sapisid_hash(cookie_str, origin="https://notebooklm.google.com"):
    sapisid_match = re.search(r'(?:SAPISID|__Secure-3PAPISID)=([^; ]+)', cookie_str)
    if not sapisid_match:
        return ""
    sapisid = sapisid_match.group(1)
    timestamp = str(int(time.time()))
    payload = f"{timestamp} {sapisid} {origin}"
    sha1_hash = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"SAPISIDHASH {timestamp}_{sha1_hash}"

def fetch_studio_artifacts_irfanlm_v8(notebook_id, session_cfg):
    """
    Direct implementation of IrfanLM Tools v8 `gArtLc` parser.
    """
    url = "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute"
    
    cookies = session_cfg.get("cookie_header", "")
    token = session_cfg.get("token", "")
    bl = session_cfg.get("bl", "boq_labs-tailwind-frontend_20260824.15_p0")
    fsid = session_cfg.get("fsid", "")
    authuser = str(session_cfg.get("authuser", "0"))

    auth_hash = generate_sapisid_hash(cookies, "https://notebooklm.google.com")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Cookie": cookies,
        "Referer": f"https://notebooklm.google.com/notebook/{notebook_id}",
        "Origin": "https://notebooklm.google.com",
        "X-Same-Domain": "1",
        "Authorization": auth_hash,
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
    }

    params = {
        "rpcids": "gArtLc",
        "source-path": f"/notebook/{notebook_id}",
        "bl": bl,
        "authuser": authuser,
        "_reqid": str(int(time.time() * 1000))[-6:]
    }

    # IrfanLM Tools exact argument schema
    inner_args = json.dumps([[2], notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"'])
    rpc_envelope = [[["gArtLc", inner_args, None, "generic"]]]

    data = {
        "f.req": json.dumps(rpc_envelope),
        "at": token
    }
    if fsid:
        data["f.sid"] = fsid

    resp = requests.post(url, params=params, data=data, headers=headers, timeout=35)
    resp_text = resp.text

    items = []

    # Parse Google batchexecute response stream
    for line in resp_text.splitlines():
        if not line.strip() or line.startswith(")]}'"):
            continue
        try:
            chunk = json.loads(line)
            if isinstance(chunk, list):
                for envelope in chunk:
                    if len(envelope) > 2 and envelope[0] == "wrb.fr" and envelope[1] == "gArtLc":
                        parsed_payload = json.loads(envelope[2])
                        
                        # parsed_payload[0] holds artifact records list
                        artifact_list = parsed_payload[0] if (isinstance(parsed_payload, list) and len(parsed_payload) > 0 and isinstance(parsed_payload[0], list)) else parsed_payload
                        
                        if isinstance(artifact_list, list):
                            for art in artifact_list:
                                if not isinstance(art, list) or len(art) < 5:
                                    continue
                                
                                art_title = art[1] if len(art) > 1 and art[1] else "Studio Overview"
                                art_type = art[2]   # 1 = Audio, 3 = Video
                                art_status = art[4] # 3 = Ready
                                
                                media_url = None
                                
                                # Audio extractor (raw[6])
                                if art_type == 1 and len(art) > 6 and isinstance(art[6], list):
                                    if len(art[6]) > 3 and art[6][3]:
                                        media_url = art[6][3]
                                    elif len(art[6]) > 2 and art[6][2]:
                                        media_url = art[6][2]
                                
                                # Video extractor (raw[8])
                                elif art_type == 3 and len(art) > 8 and isinstance(art[8], list):
                                    if len(art[8]) > 3 and art[8][3]:
                                        media_url = art[8][3]
                                    elif len(art[8]) > 1 and art[8][1]:
                                        media_url = art[8][1]

                                if media_url:
                                    clean_url = media_url.split("?")[0]
                                    flag = "=m22-dv" if art_type == 3 else "=m140-dv-mp2"
                                    
                                    if "=m" not in clean_url:
                                        clean_url += f"{flag}?authuser={authuser}"
                                    elif not clean_url.endswith(f"authuser={authuser}"):
                                        clean_url += f"?authuser={authuser}"
                                        
                                    items.append({
                                        "title": art_title,
                                        "type": "video" if art_type == 3 else "audio",
                                        "url": clean_url
                                    })
        except Exception:
            continue

    # Fallback to direct URL scan if Google nested array changed
    if not items:
        cdn_matches = list(dict.fromkeys(re.findall(r'https://lh3\.googleusercontent\.com/notebooklm/[a-zA-Z0-9_\-=]+', resp_text)))
        titles_found = [t for t in re.findall(r'\["([A-Za-z0-9\s\-_,\.\'\?!]{3,80})"', resp_text) if not t.startswith("http") and "notebook" not in t.lower() and len(t) > 3]

        for idx, u in enumerate(cdn_matches):
            clean_u = u.split("?")[0]
            is_vid = "m22" in clean_u or "video" in clean_u
            flag = "=m22-dv" if is_vid else "=m140-dv-mp2"
            clean_u += f"{flag}?authuser={authuser}"
            t = titles_found[idx] if idx < len(titles_found) else f"Studio Overview {idx + 1}"
            items.append({
                "title": t,
                "type": "video" if is_vid else "audio",
                "url": clean_u
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

# ================= TELEGRAM HANDLERS =================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
        return
    msg = (
        "⚡ *IrfanLM Cloud Exporter (Railway Powered)* ⚡\n\n"
        "1. Send `/auth <json_credentials>` to configure\n"
        "2. Send any **Notebook ID or link** to export all Studio items using Railway's server bandwidth (Zero phone data used)!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def auth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
        return

    raw_text = update.message.text.replace("/auth", "").strip()
    if not raw_text:
        await update.message.reply_text("❌ Usage: `/auth <json>`", parse_mode="Markdown")
        return

    try:
        data = json.loads(raw_text)
        if "auth_config" in data:
            data.update(data["auth_config"])
        save_session(data)
        await update.message.reply_text("✅ *Session credentials saved!* Ready to process notebooks.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Invalid JSON format: `{str(e)}`", parse_mode="Markdown")

async def handle_notebook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
        return

    text = update.message.text.strip()
    match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', text, re.I)
    notebook_id = match.group(1) if match else text

    session_cfg = load_session()
    if not session_cfg:
        await update.message.reply_text("❌ No credentials configured. Please send `/auth` first.", parse_mode="Markdown")
        return

    status_msg = await update.message.reply_text(f"🔍 *Querying Studio Artifacts (gArtLc RPC):* `{notebook_id}`...", parse_mode="Markdown")

    try:
        items = fetch_studio_artifacts_irfanlm_v8(notebook_id, session_cfg)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ RPC Query Failed: `{str(e)}`", parse_mode="Markdown")
        return

    total = len(items)
    if total == 0:
        await status_msg.edit_text(f"⚠️ No ready Studio artifacts found in notebook `{notebook_id}`.", parse_mode="Markdown")
        return

    await status_msg.edit_text(f"📦 Found *{total}* Studio item(s)! Railway cloud server is downloading & forwarding...", parse_mode="Markdown")

    http_session = requests.Session()
    http_session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": session_cfg.get("cookie_header", "")
    })

    for idx, item in enumerate(items, 1):
        media_type = item["type"]
        url = item["url"]
        title = item["title"]
        ext = ".mp4" if media_type == "video" else ".m4a"
        raw_file = f"cloud_item_{idx}{ext}"

        try:
            # Download takes place entirely on Railway (Zero phone data)
            with http_session.get(url, stream=True, timeout=180) as r:
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
            await update.message.reply_text(f"⚠️ Failed to deliver {title}: `{str(err)}`", parse_mode="Markdown")

        finally:
            for temp in [raw_file, f"cmp_{raw_file}"]:
                if os.path.exists(temp):
                    os.remove(temp)

    await update.message.reply_text(f"🎉 *Batch Export Complete!* Processed {total} artifacts via cloud server.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("auth", auth_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_notebook))
    print("🚀 IrfanLM Railway Pure-RPC Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
                                
