# bot.py

import asyncio
import os
import time
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from config import API_ID, API_HASH, BOT_TOKEN, ADMINS, DEFAULT_CAPTION, WELCOME_MESSAGE, THUMBNAIL_PATH
from utils import download_from_url, get_thumbnail, format_bytes
from database import add_user

app = Client("downloader-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.private & filters.command("start"))
async def start_handler(client, message: Message):
    add_user(message.from_user.id)
    await message.reply_photo(
        photo=THUMBNAIL_PATH if os.path.exists(THUMBNAIL_PATH) else None,
        caption=WELCOME_MESSAGE,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Source", url="https://github.com")]]
        )
    )

@app.on_message(filters.private & filters.text & ~filters.command("start"))
async def link_handler(client, message: Message):
    url = message.text.strip()
    msg = await message.reply("Processing your link...")

    try:
        file_path, file_name, file_size = await download_from_url(url, message)
        thumb = get_thumbnail(file_path)
        caption = DEFAULT_CAPTION.format(filename=file_name)

        await msg.edit("Uploading file...")
        await client.send_document(
            chat_id=message.chat.id,
            document=file_path,
            caption=caption,
            file_name=file_name,
            thumb=thumb,
            progress=progress_bar,
            progress_args=(msg, time.time(), file_name)
        )
        os.remove(file_path)
    except Exception as e:
        await msg.edit(f"Error: {e}")

async def progress_bar(current, total, msg, start, filename):
    now = time.time()
    diff = now - start
    speed = current / diff if diff > 0 else 0
    percent = current * 100 / total
    bar = f"[{'█' * int(percent // 10)}{' ' * (10 - int(percent // 10))}]"
    current_mb = format_bytes(current)
    total_mb = format_bytes(total)
    await msg.edit(f"{filename}\n{bar} {percent:.2f}%\n{current_mb} / {total_mb} @ {format_bytes(speed)}/s")