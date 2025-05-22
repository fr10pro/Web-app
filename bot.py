import os
import re
import time
import logging
from datetime import datetime
from io import BytesIO
from typing import Dict, List, Tuple, Optional

import requests
import tgcrypto
from flask import Flask, render_template, request, redirect, url_for, session, flash
from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery,
    InputMediaPhoto, InputMediaVideo, InputMediaDocument
)
from pyrogram.errors import FloodWait

# ===================== Configuration =====================
API_ID = 28593211
API_HASH = "27ad7de4fe5cab9f8e310c5cc4b8d43d"
BOT_TOKEN = "7696316358:AAGZw4OUGAT628QX2DBleIVV2JWQTfiQu88"
ADMINS = [5559075560]
WEB_ADMIN_USERNAME = "admin"
WEB_ADMIN_PASSWORD = "password"
DATABASE_FILE = "bot_database.db"
THUMBNAIL_DIR = "thumbnails"
MAX_CONCURRENT_DOWNLOADS = 3

# Flask app configuration
app = Flask(__name__)
app.secret_key = "your_secret_key_for_flask_sessions"
app.config['UPLOAD_FOLDER'] = THUMBNAIL_DIR

# Ensure directories exist
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

# ===================== Database Setup =====================
import sqlite3

def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        join_date TEXT,
        last_activity TEXT,
        downloads INTEGER DEFAULT 0
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        welcome_message TEXT,
        default_thumbnail TEXT,
        auto_caption TEXT DEFAULT "{filename} Made by @fr10pro"
    )
    ''')
    
    cursor.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
        INSERT INTO settings (welcome_message, default_thumbnail)
        VALUES (?, ?)
        ''', ("Welcome to the downloader bot!", ""))
    
    conn.commit()
    conn.close()

init_db()

# ===================== Helper Functions =====================
def get_db_connection():
    return sqlite3.connect(DATABASE_FILE)

def format_bytes(size: float) -> str:
    power = 2**10
    n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size > power and n < len(power_labels) - 1:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}"

def get_current_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def update_user_activity(user_id: int, username: str, first_name: str, last_name: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, join_date, last_activity)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name, get_current_time(), get_current_time()))
    
    cursor.execute('''
    UPDATE users SET 
        username = ?,
        first_name = ?,
        last_name = ?,
        last_activity = ?
    WHERE user_id = ?
    ''', (username, first_name, last_name, get_current_time(), user_id))
    
    conn.commit()
    conn.close()

def increment_user_downloads(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(''
    UPDATE users SET downloads = downloads + 1 WHERE user_id = ?
    ''', (user_id,))
    conn.commit()
    conn.close()

def get_setting(setting_name: str) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f'SELECT {setting_name} FROM settings LIMIT 1')
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else ""

def update_setting(setting_name: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f'UPDATE settings SET {setting_name} = ?', (value,))
    conn.commit()
    conn.close()

def get_user_stats() -> Dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('''
    SELECT COUNT(*) FROM users 
    WHERE last_activity > datetime('now', '-1 day')
    ''')
    daily_active = cursor.fetchone()[0]
    
    cursor.execute('SELECT SUM(downloads) FROM users')
    total_downloads = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return {
        'total_users': total_users,
        'daily_active': daily_active,
        'total_downloads': total_downloads
    }

def get_recent_users(limit: int = 10) -> List[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT user_id, username, first_name, last_name, last_activity, downloads 
    FROM users 
    ORDER BY last_activity DESC 
    LIMIT ?
    ''', (limit,))
    
    users = []
    for row in cursor.fetchall():
        users.append({
            'user_id': row[0],
            'username': row[1],
            'first_name': row[2],
            'last_name': row[3],
            'last_activity': row[4],
            'downloads': row[5]
        })
    
    conn.close()
    return users

# ===================== Downloader Functions =====================
def extract_info_from_url(url: str) -> Tuple[str, str]:
    filename = os.path.basename(url.split('?')[0])
    
    if not filename or '.' not in filename:
        filename = f"file_{int(time.time())}"
    
    if '.' in filename:
        name, ext = os.path.splitext(filename)
        ext = ext.lower()
    else:
        name = filename
        ext = ""
    
    return name, ext

def is_supported_url(url: str) -> bool:
    supported_domains = [
        'instagram.com', 'facebook.com', 'twitter.com', 'tiktok.com',
        'youtube.com', 'youtu.be', 'reddit.com', 'pinterest.com',
        'tumblr.com', 'vimeo.com', 'dailymotion.com', 'soundcloud.com',
        'twitch.tv', 'streamable.com', 'bandcamp.com', 'm3u8', 'mpd'
    ]
    
    return any(domain in url.lower() for domain in supported_domains)

def download_file(url: str, filename: str) -> Tuple[bool, str]:
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            
            with open(filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
            
            return True, filename
    except Exception as e:
        return False, str(e)

def get_thumbnail(url: str) -> Optional[str]:
    try:
        if 'youtube.com' in url or 'youtu.be' in url:
            video_id = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url).group(1)
            return f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        response = requests.get(url, headers=headers)
        og_image = re.search(r'<meta property="og:image" content="([^"]+)"', response.text)
        if og_image:
            return og_image.group(1)
        
        twitter_image = re.search(r'<meta name="twitter:image" content="([^"]+)"', response.text)
        if twitter_image:
            return twitter_image.group(1)
        
    except Exception:
        pass
    
    return None

# ===================== Telegram Bot =====================
bot = Client(
    "AdvancedDownloaderBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=MAX_CONCURRENT_DOWNLOADS
)

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    user = message.from_user
    update_user_activity(user.id, user.username, user.first_name, user.last_name)
    
    welcome_message = get_setting("welcome_message")
    await message.reply_text(
        welcome_message,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Help", callback_data="help")]
        ])
    )

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    help_text = """
📌 **How to use this bot:**
1. Send me a direct download link or a link from supported platforms:
   - Instagram, Facebook, Twitter, TikTok, YouTube, etc.
   - Direct file links (PDF, APK, ZIP, etc.)
   - Streaming links (M3U8, MPD, etc.)

2. The bot will automatically process the link and download the best quality available.

3. You can rename the file before downloading.

🔹 **Features:**
- Auto thumbnail detection
- Download progress tracking
- Support for many platforms
- Fast and reliable downloads

⚠️ **Note:** Some platforms may have restrictions.
"""
    await message.reply_text(help_text)

@bot.on_message(filters.text & filters.private)
async def handle_links(client: Client, message: Message):
    user = message.from_user
    update_user_activity(user.id, user.username, user.first_name, user.last_name)
    
    url = message.text.strip()
    
    if not re.match(r'^https?://', url, re.I):
        await message.reply_text("⚠️ Please send a valid HTTP/HTTPS URL.")
        return
    
    if not is_supported_url(url):
        await message.reply_text("⚠️ This URL doesn't appear to be from a supported platform. Trying to download anyway...")
    
    name, ext = extract_info_from_url(url)
    default_filename = f"{name}{ext}" if ext else name
    
    await message.reply_text(
        f"🔗 URL detected: {url}\n\n"
        f"📂 Default filename: {default_filename}\n\n"
        "Would you like to rename the file before downloading?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Keep Default Name", callback_data=f"download|{url}|{default_filename}")],
            [InlineKeyboardButton("Rename File", callback_data=f"rename|{url}|{default_filename}")]
        ])
    )

@bot.on_callback_query()
async def handle_callbacks(client: Client, callback_query: CallbackQuery):
    user = callback_query.from_user
    data = callback_query.data
    
    if data == "help":
        await help_command(client, callback_query.message)
        await callback_query.answer()
        return
    
    if data.startswith("download|"):
        _, url, filename = data.split("|", 2)
        await process_download(client, callback_query, url, filename)
    
    elif data.startswith("rename|"):
        _, url, default_filename = data.split("|", 2)
        await callback_query.message.edit_text(
            f"Please reply with the new filename (without extension):\n\n"
            f"Current filename: {default_filename}\n"
            f"Example: my_custom_name"
        )
        
        client.user_data[user.id] = {
            'action': 'rename_download',
            'url': url,
            'default_filename': default_filename
        }
        await callback_query.answer()
    
    elif data == "cancel":
        await callback_query.message.edit_text("❌ Download cancelled.")
        await callback_query.answer()

async def process_download(client: Client, callback_query: CallbackQuery, url: str, filename: str):
    user = callback_query.from_user
    message = callback_query.message
    
    await message.edit_text(f"⏳ Processing your download: {filename}\n\nPlease wait...")
    
    try:
        thumbnail_url = get_thumbnail(url)
        thumbnail_path = None
        
        if thumbnail_url:
            thumbnail_path = os.path.join(THUMBNAIL_DIR, f"thumb_{user.id}.jpg")
            success, result = download_file(thumbnail_url, thumbnail_path)
            if not success:
                thumbnail_path = None
        
        if not thumbnail_path:
            default_thumbnail = get_setting("default_thumbnail")
            if default_thumbnail and os.path.exists(default_thumbnail):
                thumbnail_path = default_thumbnail
        
        temp_filename = os.path.join(THUMBNAIL_DIR, f"temp_{user.id}_{int(time.time())}")
        success, result = download_file(url, temp_filename)
        
        if not success:
            raise Exception(f"Download failed: {result}")
        
        file_size = os.path.getsize(temp_filename)
        
        auto_caption = get_setting("auto_caption")
        caption = auto_caption.format(filename=filename)
        
        progress_message = await message.reply_text(f"📤 Uploading: {filename}\n\n🔄 Progress: 0% (0.00 MB / {format_bytes(file_size)})")
        
        start_time = time.time()
        last_update_time = start_time
        
        def progress(current, total):
            nonlocal last_update_time
            now = time.time()
            if now - last_update_time >= 1 or current == total:
                percent = (current / total) * 100
                speed = current / (now - start_time)
                elapsed = now - start_time
                remaining = (total - current) / speed if speed > 0 else 0
                
                progress_text = (
                    f"📤 Uploading: {filename}\n\n"
                    f"🔄 Progress: {percent:.1f}% ({format_bytes(current)} / {format_bytes(total)})\n"
                    f"⚡ Speed: {format_bytes(speed)}/s\n"
                    f"⏱️ Elapsed: {elapsed:.1f}s | Remaining: {remaining:.1f}s"
                )
                
                try:
                    client.loop.create_task(progress_message.edit_text(progress_text))
                except Exception:
                    pass
                
                last_update_time = now
        
        if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp')):
            await client.send_photo(
                chat_id=user.id,
                photo=temp_filename,
                caption=caption,
                reply_to_message_id=message.id,
                progress=progress
            )
        elif filename.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
            await client.send_video(
                chat_id=user.id,
                video=temp_filename,
                caption=caption,
                thumb=thumbnail_path,
                reply_to_message_id=message.id,
                progress=progress
            )
        else:
            await client.send_document(
                chat_id=user.id,
                document=temp_filename,
                caption=caption,
                thumb=thumbnail_path,
                reply_to_message_id=message.id,
                progress=progress
            )
        
        os.remove(temp_filename)
        if thumbnail_path and thumbnail_path != get_setting("default_thumbnail"):
            try:
                os.remove(thumbnail_path)
            except:
                pass
        
        increment_user_downloads(user.id)
        
        await progress_message.delete()
        await message.edit_text(f"✅ Download complete: {filename}")
    
    except FloodWait as e:
        await message.edit_text(f"⚠️ Too many requests. Please wait {e.value} seconds before trying again.")
    except Exception as e:
        await message.edit_text(f"❌ Error: {str(e)}")
    
    await callback_query.answer()

@bot.on_message(filters.private & ~filters.command(["start", "help"]))
async def handle_rename(client: Client, message: Message):
    user = message.from_user
    
    if user.id in client.user_data and client.user_data[user.id].get('action') == 'rename_download':
        url = client.user_data[user.id]['url']
        default_filename = client.user_data[user.id]['default_filename']
        
        new_name = message.text.strip()
        
        if '.' in default_filename:
            _, ext = os.path.splitext(default_filename)
            new_filename = f"{new_name}{ext}"
        else:
            new_filename = new_name
        
        await process_download(
            client,
            CallbackQuery(
                id="manual_rename",
                from_user=user,
                message=message,
                data=f"download|{url}|{new_filename}"
            ),
            url,
            new_filename
        )
        
        del client.user_data[user.id]

# ===================== Flask Admin Panel =====================
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == WEB_ADMIN_USERNAME and password == WEB_ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials', 'error')
    
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))
    
    return render_template('login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    stats = get_user_stats()
    recent_users = get_recent_users(5)
    welcome_message = get_setting("welcome_message")
    auto_caption = get_setting("auto_caption")
    
    return render_template('dashboard.html', 
                         stats=stats, 
                         recent_users=recent_users,
                         welcome_message=welcome_message,
                         auto_caption=auto_caption)

@app.route('/admin/broadcast', methods=['GET', 'POST'])
def admin_broadcast():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        message = request.form.get('message')
        media = request.files.get('media')
        button_text = request.form.get('button_text')
        button_url = request.form.get('button_url')
        
        if not message and not media:
            flash('Message or media is required', 'error')
            return redirect(url_for('admin_broadcast'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users')
        user_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        reply_markup = None
        if button_text and button_url:
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(button_text, url=button_url)]
            ])
        
        success = 0
        failures = 0
        
        for user_id in user_ids:
            try:
                if media:
                    media_path = os.path.join(app.config['UPLOAD_FOLDER'], media.filename)
                    media.save(media_path)
                    
                    if media.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                        await bot.send_photo(
                            chat_id=user_id,
                            photo=media_path,
                            caption=message,
                            reply_markup=reply_markup
                        )
                    elif media.filename.lower().endswith(('.mp4', '.mov', '.avi')):
                        await bot.send_video(
                            chat_id=user_id,
                            video=media_path,
                            caption=message,
                            reply_markup=reply_markup
                        )
                    else:
                        await bot.send_document(
                            chat_id=user_id,
                            document=media_path,
                            caption=message,
                            reply_markup=reply_markup
                        )
                    
                    os.remove(media_path)
                else:
                    await bot.send_message(
                        chat_id=user_id,
                        text=message,
                        reply_markup=reply_markup
                    )
                
                success += 1
            except Exception as e:
                failures += 1
                print(f"Failed to send to {user_id}: {e}")
        
        flash(f"Broadcast sent to {success} users. Failed: {failures}", 'success')
        return redirect(url_for('admin_broadcast'))
    
    return render_template('broadcast.html')

@app.route('/admin/settings', methods=['GET', 'POST'])
def admin_settings():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        setting = request.form.get('setting')
        value = request.form.get('value')
        
        if setting == 'welcome_message':
            update_setting('welcome_message', value)
            flash('Welcome message updated', 'success')
        elif setting == 'auto_caption':
            update_setting('auto_caption', value)
            flash('Auto caption updated', 'success')
        elif setting == 'thumbnail':
            thumbnail = request.files.get('thumbnail')
            if thumbnail:
                filename = "default_thumbnail.jpg"
                filepath = os.path.join(THUMBNAIL_DIR, filename)
                thumbnail.save(filepath)
                update_setting('default_thumbnail', filepath)
                flash('Default thumbnail updated', 'success')
        
        return redirect(url_for('admin_settings'))
    
    welcome_message = get_setting("welcome_message")
    auto_caption = get_setting("auto_caption")
    default_thumbnail = get_setting("default_thumbnail")
    
    return render_template('settings.html',
                         welcome_message=welcome_message,
                         auto_caption=auto_caption,
                         default_thumbnail=default_thumbnail)

# Flask templates
app.jinja_env.globals.update(format_bytes=format_bytes)

@app.context_processor
def inject_template_functions():
    return {
        'format_time': lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S").strftime("%b %d, %Y %H:%M")
    }

# HTML templates as strings
app.jinja_loader = type('CustomLoader', (object,), {
    'get_source': lambda self, env, template: (
        TEMPLATES.get(template, ('', None, None))
    )
})()

TEMPLATES = {
    'login.html': ('''
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; }
        .login-container { max-width: 400px; margin: 100px auto; }
    </style>
</head>
<body>
    <div class="container">
        <div class="login-container">
            <div class="card shadow">
                <div class="card-header bg-primary text-white">
                    <h4 class="mb-0">Admin Login</h4>
                </div>
                <div class="card-body">
                    {% with messages = get_flashed_messages(with_categories=true) %}
                        {% if messages %}
                            {% for category, message in messages %}
                                <div class="alert alert-{{ category }}">{{ message }}</div>
                            {% endfor %}
                        {% endif %}
                    {% endwith %}
                    <form method="POST">
                        <div class="mb-3">
                            <label for="username" class="form-label">Username</label>
                            <input type="text" class="form-control" id="username" name="username" required>
                        </div>
                        <div class="mb-3">
                            <label for="password" class="form-label">Password</label>
                            <input type="password" class="form-control" id="password" name="password" required>
                        </div>
                        <button type="submit" class="btn btn-primary w-100">Login</button>
                    </form>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
''', None, None),

    'dashboard.html': ('''
<!DOCTYPE html>
<html>
<head>
    <title>Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.8.0/font/bootstrap-icons.css">
    <style>
        body { padding-top: 20px; background-color: #f8f9fa; }
        .sidebar { position: fixed; top: 0; bottom: 0; left: 0; z-index: 100; padding: 20px 0; overflow-x: hidden; background-color: #343a40; }
        .sidebar .nav-link { color: rgba(255, 255, 255, 0.75); padding: 10px 20px; }
        .sidebar .nav-link.active { color: #fff; background-color: rgba(255, 255, 255, 0.1); }
        .sidebar .nav-link:hover { color: #fff; }
        .main-content { margin-left: 220px; padding: 20px; }
    </style>
</head>
<body>
    <div class="container-fluid">
        <div class="row">
            <nav class="col-md-2 d-none d-md-block sidebar">
                <div class="sidebar-sticky">
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link active" href="{{ url_for('admin_dashboard') }}">
                                <i class="bi bi-speedometer2 me-2"></i>Dashboard
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('admin_broadcast') }}">
                                <i class="bi bi-megaphone me-2"></i>Broadcast
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('admin_settings') }}">
                                <i class="bi bi-gear me-2"></i>Settings
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('admin_logout') }}">
                                <i class="bi bi-box-arrow-right me-2"></i>Logout
                            </a>
                        </li>
                    </ul>
                </div>
            </nav>
            
            <main role="main" class="col-md-9 ml-sm-auto col-lg-10 px-4 main-content">
                <h2 class="mb-4">Dashboard</h2>
                
                <div class="row mb-4">
                    <div class="col-md-4">
                        <div class="card text-white bg-primary">
                            <div class="card-body">
                                <h5 class="card-title">Total Users</h5>
                                <p class="card-text display-4">{{ stats.total_users }}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card text-white bg-success">
                            <div class="card-body">
                                <h5 class="card-title">Daily Active</h5>
                                <p class="card-text display-4">{{ stats.daily_active }}</p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="card text-white bg-info">
                            <div class="card-body">
                                <h5 class="card-title">Total Downloads</h5>
                                <p class="card-text display-4">{{ stats.total_downloads }}</p>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="row">
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">
                                <h5>Recent Users</h5>
                            </div>
                            <div class="card-body">
                                <div class="table-responsive">
                                    <table class="table table-striped">
                                        <thead>
                                            <tr>
                                                <th>User</th>
                                                <th>Last Activity</th>
                                                <th>Downloads</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {% for user in recent_users %}
                                            <tr>
                                                <td>
                                                    {% if user.username %}
                                                        @{{ user.username }}
                                                    {% else %}
                                                        {{ user.first_name }} {{ user.last_name }}
                                                    {% endif %}
                                                </td>
                                                <td>{{ format_time(user.last_activity) }}</td>
                                                <td>{{ user.downloads }}</td>
                                            </tr>
                                            {% endfor %}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header">
                                <h5>Welcome Message</h5>
                            </div>
                            <div class="card-body">
                                <div class="mb-3">
                                    <textarea class="form-control" rows="3" readonly>{{ welcome_message }}</textarea>
                                </div>
                                <div class="mb-3">
                                    <strong>Auto Caption:</strong>
                                    <p>{{ auto_caption }}</p>
                                </div>
                                <a href="{{ url_for('admin_settings') }}" class="btn btn-primary">Edit Settings</a>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
''', None, None),

    'broadcast.html': ('''
{% extends 'base.html' %}
{% block title %}Broadcast{% endblock %}
{% block content %}
<div class="container-fluid">
    <h2 class="mb-4">Broadcast Message</h2>
    
    <div class="card">
        <div class="card-body">
            <form method="POST" enctype="multipart/form-data">
                <div class="mb-3">
                    <label for="message" class="form-label">Message Text</label>
                    <textarea class="form-control" id="message" name="message" rows="3"></textarea>
                </div>
                
                <div class="mb-3">
                    <label for="media" class="form-label">Media File (optional)</label>
                    <input class="form-control" type="file" id="media" name="media">
                    <div class="form-text">Image, Video, or Document to send with message</div>
                </div>
                
                <div class="row mb-3">
                    <div class="col-md-6">
                        <label for="button_text" class="form-label">Button Text (optional)</label>
                        <input type="text" class="form-control" id="button_text" name="button_text">
                    </div>
                    <div class="col-md-6">
                        <label for="button_url" class="form-label">Button URL (optional)</label>
                        <input type="url" class="form-control" id="button_url" name="button_url">
                    </div>
                </div>
                
                <button type="submit" class="btn btn-primary">Send Broadcast</button>
            </form>
        </div>
    </div>
</div>
{% endblock %}
''', None, None),

    'settings.html': ('''
{% extends 'base.html' %}
{% block title %}Settings{% endblock %}
{% block content %}
<div class="container-fluid">
    <h2 class="mb-4">Bot Settings</h2>
    
    <div class="card mb-4">
        <div class="card-header">
            <h5>Welcome Message</h5>
        </div>
        <div class="card-body">
            <form method="POST">
                <input type="hidden" name="setting" value="welcome_message">
                <div class="mb-3">
                    <textarea class="form-control" name="value" rows="3">{{ welcome_message }}</textarea>
                </div>
                <button type="submit" class="btn btn-primary">Update</button>
            </form>
        </div>
    </div>
    
    <div class="card mb-4">
        <div class="card-header">
            <h5>Auto Caption</h5>
        </div>
        <div class="card-body">
            <form method="POST">
                <input type="hidden" name="setting" value="auto_caption">
                <div class="mb-3">
                    <input type="text" class="form-control" name="value" value="{{ auto_caption }}">
                    <div class="form-text">Use {filename} for the filename placeholder</div>
                </div>
                <button type="submit" class="btn btn-primary">Update</button>
            </form>
        </div>
    </div>
    
    <div class="card">
        <div class="card-header">
            <h5>Default Thumbnail</h5>
        </div>
        <div class="card-body">
            {% if default_thumbnail %}
                <img src="{{ url_for('static', filename=default_thumbnail) }}" class="img-thumbnail mb-3" style="max-height: 200px;">
            {% endif %}
            
            <form method="POST" enctype="multipart/form-data">
                <input type="hidden" name="setting" value="thumbnail">
                <div class="mb-3">
                    <input class="form-control" type="file" name="thumbnail" accept="image/*">
                </div>
                <button type="submit" class="btn btn-primary">Update Thumbnail</button>
            </form>
        </div>
    </div>
</div>
{% endblock %}
''', None, None),

    'base.html': ('''
<!DOCTYPE html>
<html>
<head>
    <title>{% block title %}{% endblock %} - Downloader Bot Admin</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.8.0/font/bootstrap-icons.css">
    <style>
        body { padding-top: 20px; background-color: #f8f9fa; }
        .sidebar { position: fixed; top: 0; bottom: 0; left: 0; z-index: 100; padding: 20px 0; overflow-x: hidden; background-color: #343a40; }
        .sidebar .nav-link { color: rgba(255, 255, 255, 0.75); padding: 10px 20px; }
        .sidebar .nav-link.active { color: #fff; background-color: rgba(255, 255, 255, 0.1); }
        .sidebar .nav-link:hover { color: #fff; }
        .main-content { margin-left: 220px; padding: 20px; }
    </style>
</head>
<body>
    <div class="container-fluid">
        <div class="row">
            <nav class="col-md-2 d-none d-md-block sidebar">
                <div class="sidebar-sticky">
                    <ul class="nav flex-column">
                        <li class="nav-item">
                            <a class="nav-link {% if request.path == url_for('admin_dashboard') %}active{% endif %}" href="{{ url_for('admin_dashboard') }}">
                                <i class="bi bi-speedometer2 me-2"></i>Dashboard
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link {% if request.path == url_for('admin_broadcast') %}active{% endif %}" href="{{ url_for('admin_broadcast') }}">
                                <i class="bi bi-megaphone me-2"></i>Broadcast
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link {% if request.path == url_for('admin_settings') %}active{% endif %}" href="{{ url_for('admin_settings') }}">
                                <i class="bi bi-gear me-2"></i>Settings
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('admin_logout') }}">
                                <i class="bi bi-box-arrow-right me-2"></i>Logout
                            </a>
                        </li>
                    </ul>
                </div>
            </nav>
            
            <main role="main" class="col-md-9 ml-sm-auto col-lg-10 px-4 main-content">
                {% with messages = get_flashed_messages(with_categories=true) %}
                    {% if messages %}
                        {% for category, message in messages %}
                            <div class="alert alert-{{ category }} alert-dismissible fade show">
                                {{ message }}
                                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                            </div>
                        {% endfor %}
                    {% endif %}
                {% endwith %}
                
                {% block content %}{% endblock %}
            </main>
        </div>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
''', None, None)
}

# ===================== Main Execution =====================
def run_bot_and_flask():
    import threading
    
    flask_thread = threading.Thread(
        target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False),
        daemon=True
    )
    flask_thread.start()
    
    print("Starting Telegram bot...")
    bot.run()

if __name__ == "__main__":
    print("""
    ===================== Deployment Instructions for Termux =====================
    1. Install required packages in Termux:
       pkg update && pkg upgrade
       pkg install python git ffmpeg -y
       pip install pyrogram tgcrypto flask requests
    
    2. Save this script as bot.py
    
    3. Run the bot:
       python bot.py
    
    4. To keep the bot running after closing Termux:
       - Install Termux:API and setup termux-wake-lock
       - Or use tmux/screen sessions
    
    5. Access the admin panel:
       - On your local network: http://<your-device-ip>:5000/admin
       - For external access, use ngrok or similar tunneling service
    """)
    
    run_bot_and_flask()
