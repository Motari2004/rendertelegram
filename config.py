import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ✅ FIXED: Added /bot suffix so python-telegram-bot builds valid URLs
BOT_API_URL = os.getenv("BOT_API_URL", "http://localhost:8081/bot")

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/app/uploads")
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB

BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000")

CLEANUP_HOURS = int(os.getenv("CLEANUP_HOURS", "168"))
DB_PATH = os.getenv("DB_PATH", "/app/uploads.db")