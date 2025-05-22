# config.py

import os

# Telegram API Credentials
API_ID = int(os.getenv("API_ID", "123456"))         # Replace with your API ID
API_HASH = os.getenv("API_HASH", "your_api_hash")   # Replace with your API Hash
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token")

# Admins
ADMINS = [5559075560]  # Telegram user IDs

# Default messages
WELCOME_MESSAGE = "Welcome to the Advanced Downloader Bot!"
DEFAULT_CAPTION = "{filename}\nMade by @fr10pro"

# Basic Auth for Flask
FLASK_USERNAME = "admin"
FLASK_PASSWORD = "password"

# Files
THUMBNAIL_PATH = "default_thumb.jpg"