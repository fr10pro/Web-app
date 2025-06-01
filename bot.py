import telebot
import requests
import random
import schedule
import time
import threading
from datetime import datetime
from flask import Flask, request

# === CONFIGURATION ===
BOT_TOKEN = '7696316358:AAGZw4OUGAT628QX2DBleIVV2JWQTfiQu88'
CHANNEL_USERNAME = '@orfiai'
OPENROUTER_API_KEY = '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'  # Replace with real key

POST_COUNT_PER_DAY = 15
POST_CATEGORIES = ['crypto', 'finance', 'memes']

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
scheduled_times = []

# === GPT POST GENERATION ===
def generate_post(topic):
    try:
        prompt = f"Write a creative and engaging Telegram post related to {topic} with a little humor and include mention @ORFIAI. Keep it short (max 300 characters)."
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://chat.openai.com/",
            "Content-Type": "application/json"
        }
        data = {
            "model": "openrouter/auto",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 300
        }
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print("[ERROR] Failed to generate post:", e)
        return None

# === SCHEDULE POST JOB ===
def post_job():
    topic = random.choice(POST_CATEGORIES)
    post = generate_post(topic)
    if post:
        try:
            bot.send_message(CHANNEL_USERNAME, post)
            print(f"[POSTED] at {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print("[ERROR] Failed to send post:", e)

# === RANDOM TIME GENERATOR ===
def setup_schedule():
    schedule.clear()
    global scheduled_times
    scheduled_times = []

    if POST_COUNT_PER_DAY > (22 - 8):
        print("[WARN] POST_COUNT_PER_DAY is too high for time range (8-22h)")
        return

    times = random.sample(range(8, 22), POST_COUNT_PER_DAY)
    times.sort()
    scheduled_times = times

    for hour in times:
        time_str = f"{hour:02d}:{random.randint(0,59):02d}"
        schedule.every().day.at(time_str).do(post_job)
        print(f"[SCHEDULED] Post at {time_str}")

# === AUTO DELETE FUNCTION ===
def delete_demo_post(chat_id, msg_id):
    try:
        bot.delete_message(chat_id, msg_id)
        print(f"[AutoDelete] Deleted message {msg_id}")
    except Exception as e:
        print("[AutoDelete Error]", e)

# === TELEGRAM COMMANDS ===
@bot.message_handler(commands=['130'])
def demo_post_handler(message):
    try:
        bot.send_message(message.chat.id, "⏳ Generating demo post...")
        topic = random.choice(POST_CATEGORIES)
        content = generate_post(topic)
        if not content:
            bot.send_message(message.chat.id, "⚠️ Failed to generate post.")
            return
        sent = bot.send_message(CHANNEL_USERNAME, content)
        post_id = sent.message_id
        bot.send_message(message.chat.id, f"✅ Posted to {CHANNEL_USERNAME}, will delete in 130s...")
        threading.Timer(130, delete_demo_post, args=(CHANNEL_USERNAME, post_id)).start()
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {e}")
        print("[/130 ERROR]", e)

@bot.message_handler(commands=['status'])
def status_handler(message):
    try:
        bot.get_me()
        status = "🤖 Bot Status\nBot is Alive ✅"
    except:
        status = "❌ Bot is not responding!"
    try:
        test_msg = bot.send_message(CHANNEL_USERNAME, "✅ Channel check", disable_notification=True)
        bot.delete_message(CHANNEL_USERNAME, test_msg.message_id)
        status += "\nChannel Connected: ✅"
    except:
        status += "\nChannel Connected: ❌"

    status += f"\n\n🕒 Scheduled Posts Today: {len(scheduled_times)}"
    for t in scheduled_times:
        status += f"\n• {t:02d}:00"

    bot.send_message(message.chat.id, status)

# === BACKGROUND THREAD ===
def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(30)

# === FLASK WEB SERVER ===
@app.route('/')
def home():
    return "🤖 Telegram Bot Web Service is running."

@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK', 200

# === MAIN ===
if __name__ == '__main__':
    print("[STARTING] Setting up schedule...")
    setup_schedule()

    # Start background thread
    thread = threading.Thread(target=run_schedule)
    thread.daemon = True
    thread.start()

    # Start polling (for local dev), OR comment this out when using webhook
    threading.Thread(target=bot.infinity_polling, daemon=True).start()

    print("[WEB SERVICE] Running Flask app...")
    app.run(host='0.0.0.0', port=8080)
