import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # e.g., @vidvaultgroup

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/app/uploads")
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB (Telegram cloud API limit)

BASE_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000")
DB_PATH = os.getenv("DB_PATH", "/app/uploads.db")