from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

api_id = 28593211
api_hash = "27ad7de4fe5cab9f8e310c5cc4b8d43d"
bot_token = "7696316358:AAGZw4OUGAT628QX2DBleIVV2JWQTfiQu88"

bot = Client("webapp_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

@bot.on_message(filters.command("start"))
async def welcome(client, message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("View My Telegram Info", web_app=WebAppInfo(url="https://web-app-ggro.onrender.com"))]
    ])
    await message.reply("Welcome! Click below to view your Telegram details.", reply_markup=keyboard)

bot.run()
