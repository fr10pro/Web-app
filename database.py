# database.py

import sqlite3
from datetime import datetime

# Connect to SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect("bot_data.db", check_same_thread=False)
cur = conn.cursor()

# Create tables
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    join_date TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS downloads (
    user_id INTEGER,
    file_name TEXT,
    timestamp TEXT
)
""")

# Add a new user if not exists
def add_user(user_id):
    cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (id, join_date) VALUES (?, ?)", (user_id, datetime.utcnow().isoformat()))
        conn.commit()

# Log a download
def add_download(user_id, file_name):
    cur.execute("INSERT INTO downloads (user_id, file_name, timestamp) VALUES (?, ?, ?)",
                (user_id, file_name, datetime.utcnow().isoformat()))
    conn.commit()

# Get total user and download stats
def get_stats():
    total_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_downloads = cur.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    return total_users, total_downloads

# Get recent user activity
def get_recent_activity(limit=10):
    return cur.execute("SELECT * FROM downloads ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()