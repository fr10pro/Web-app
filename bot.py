import os
import re
import asyncio
import logging
import requests
from flask import Flask, request, render_template_string, redirect
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from yt_dlp import YoutubeDL

API_ID = 28593211  # your api_id
API_HASH = "27ad7de4fe5cab9f8e310c5cc4b8d43d"
BOT_TOKEN = "7696316358:AAGZw4OUGAT628QX2DBleIVV2JWQTfiQu88"
ADMIN_IDS = [5559075560]  # your Telegram user ID(s)

app = Flask(__name__)
bot = Client("downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

USERS = set()
WELCOME_MESSAGE = "Send me a link to download from any social/media/streaming site!"
THUMBNAIL = "https://telegra.ph/file/f9a07ab1e9e7c2a57e71e.jpg"

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# --- Helper Functions ---
def format_bytes(size):
    power = 2**10
    n = 0
    Dic_powerN = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB'}
    while size > power:
        size /= power
        n += 1
    return f"{size:.2f}{Dic_powerN[n]}"

async def progress_hook(current, total, message: Message):
    try:
        await message.edit_text(f"**Progress:** {format_bytes(current)} / {format_bytes(total)}")
    except Exception:
        pass

def download_media(url):
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(title).80s.%(ext)s',
        'noplaylist': True,
        'quiet': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(result), result.get('thumbnail')

# --- Telegram Bot Handlers ---

@bot.on_message(filters.private & filters.command("start"))
async def start(_, msg):
    USERS.add(msg.from_user.id)
    kb = [[InlineKeyboardButton("Source", url="https://github.com/")]]
    await msg.reply(WELCOME_MESSAGE, reply_markup=InlineKeyboardMarkup(kb))

@bot.on_message(filters.private & filters.text & ~filters.command(["start"]))
async def handle_download(_, msg):
    url = msg.text.strip()
    user_id = msg.from_user.id
    if not re.match(r'^https?://', url):
        await msg.reply("Please send a valid link.")
        return

    USERS.add(user_id)
    status = await msg.reply("Downloading...")

    try:
        filepath, thumb_url = download_media(url)
        fname = os.path.basename(filepath)

        caption = f"{fname}\n\nMade by @fr10pro"

        thumb = None
        if thumb_url:
            thumb_data = requests.get(thumb_url).content
            with open("thumb.jpg", "wb") as f:
                f.write(thumb_data)
            thumb = "thumb.jpg"

        await status.edit_text("Uploading...")
        await msg.reply_document(filepath, caption=caption, thumb=thumb)

    except Exception as e:
        await status.edit_text(f"Error: {e}")
    finally:
        for f in [filepath, "thumb.jpg"]:
            if os.path.exists(f):
                os.remove(f)

# --- Flask Web Admin ---

ADMIN_PASS = "admin123"

@app.route("/")
def home():
    return redirect("/admin")

@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASS:
            return redirect("/panel")
        else:
            return "Wrong password."
    return '''<form method="post">
        <input type="password" name="password" placeholder="Admin password"/>
        <input type="submit"/>
    </form>'''

@app.route("/panel")
def admin_panel():
    return render_template_string("""
        <h2>Welcome Admin</h2>
        <ul>
            <li><a href="/broadcast">Broadcast</a></li>
            <li><a href="/stats">User Stats</a></li>
            <li><a href="/update_welcome">Change Welcome Msg</a></li>
            <li><a href="/update_thumb">Update Thumbnail</a></li>
        </ul>
    """)

@app.route("/broadcast", methods=["GET", "POST"])
def broadcast():
    if request.method == "POST":
        msg = request.form.get("message")
        asyncio.run(send_broadcast(msg))
        return "Broadcast sent!"
    return '''<form method="post">
        <textarea name="message" rows="4" cols="50"></textarea>
        <input type="submit" value="Send"/>
    </form>'''

@app.route("/stats")
def stats():
    return f"<h3>Total Users: {len(USERS)}</h3>"

@app.route("/update_welcome", methods=["GET", "POST"])
def update_welcome():
    global WELCOME_MESSAGE
    if request.method == "POST":
        WELCOME_MESSAGE = request.form.get("message")
        return "Updated!"
    return f'''<form method="post">
        <textarea name="message">{WELCOME_MESSAGE}</textarea>
        <input type="submit" value="Update"/>
    </form>'''

@app.route("/update_thumb", methods=["GET", "POST"])
def update_thumb():
    global THUMBNAIL
    if request.method == "POST":
        THUMBNAIL = request.form.get("thumb")
        return "Thumbnail updated!"
    return f'''<form method="post">
        <input type="text" name="thumb" value="{THUMBNAIL}" />
        <input type="submit" value="Update"/>
    </form>'''

# --- Run Bot & Panel Together ---
async def main():
    await bot.start()
    print("Bot is running.")
    app.run(port=8080)

if __name__ == "__main__":
    asyncio.run(main())
