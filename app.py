import os
import time
import uuid
import asyncio
import sqlite3
import logging
import requests
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from telegram import Bot

from config import (
    BOT_TOKEN, CHAT_ID, UPLOAD_FOLDER,
    MAX_FILE_SIZE, BASE_URL, DB_PATH,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'mp4', 'mkv', 'mov', 'avi', 'webm', 'flv', 'm4v'}

TG_API = "https://api.telegram.org"
TG_FILE = "https://api.telegram.org/file"


# ---------- Database ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id TEXT PRIMARY KEY,
            filename TEXT,
            file_id TEXT,
            message_id INTEGER,
            telegram_link TEXT,
            created_at REAL
        )
    """)
    conn.commit()
    conn.close()


def save_upload(uid, filename, file_id, message_id, telegram_link):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO uploads VALUES (?, ?, ?, ?, ?, ?)",
        (uid, filename, file_id, message_id, telegram_link, time.time())
    )
    conn.commit()
    conn.close()


def list_uploads():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, filename, file_id, message_id, telegram_link, created_at "
        "FROM uploads ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return rows


def get_upload_by_id(uid):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT filename, file_id, message_id, telegram_link "
        "FROM uploads WHERE id = ?",
        (uid,)
    ).fetchone()
    conn.close()
    return row


def delete_upload_record(uid):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM uploads WHERE id = ?", (uid,))
    conn.commit()
    conn.close()


# Initialize DB at import time (runs under gunicorn too)
init_db()


# ---------- Helpers ----------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


async def upload_to_telegram(file_path, caption=""):
    """Upload via the PUBLIC Telegram API — file_ids are permanent and portable."""
    bot = Bot(token=BOT_TOKEN)

    async with bot:
        with open(file_path, 'rb') as video:
            message = await bot.send_video(
                chat_id=CHAT_ID,
                video=video,
                caption=caption,
                supports_streaming=True,
                read_timeout=300,
                write_timeout=300,
                connect_timeout=60,
            )

        chat_id_str = str(CHAT_ID)
        if chat_id_str.startswith('@'):
            link = f"https://t.me/{chat_id_str[1:]}/{message.message_id}"
        else:
            clean_id = chat_id_str.replace('-100', '', 1)
            link = f"https://t.me/c/{clean_id}/{message.message_id}"

        return {
            'link': link,
            'message_id': message.message_id,
            'file_id': message.video.file_id if message.video else None,
        }


# ---------- Routes ----------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file provided'}), 400

    file = request.files['video']
    caption = request.form.get('caption', '')

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400

    uid = uuid.uuid4().hex
    safe_name = secure_filename(file.filename)
    filename = f"{uid}_{safe_name}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    try:
        result = asyncio.run(upload_to_telegram(filepath, caption))
        file_id = result['file_id']

        if not file_id:
            raise Exception("Telegram did not return a file_id")

        # Save to DB for the Manage tab
        save_upload(
            uid=uid,
            filename=safe_name,
            file_id=file_id,
            message_id=result['message_id'],
            telegram_link=result['link'],
        )

        return jsonify({
            'success': True,
            'link': result['link'],
            'download_link': f"{BASE_URL}/stream/{file_id}",
            'file_id': file_id,
            'message_id': result['message_id'],
            'uid': uid,
        })

    except Exception as e:
        logger.exception("Upload failed")
        return jsonify({'error': str(e)}), 500

    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


@app.route('/stream/<file_id>')
def stream_file(file_id):
    """Stream a file from Telegram via the PUBLIC cloud API."""
    try:
        url = f"{TG_API}/bot{BOT_TOKEN}/getFile"
        r = requests.get(url, params={'file_id': file_id}, timeout=15)
        result = r.json()

        if not result.get('ok'):
            return jsonify({
                'error': result.get('description', 'File not found')
            }), 404

        file_path = result['result']['file_path']
        file_url = f"{TG_FILE}/bot{BOT_TOKEN}/{file_path}"
        req = requests.get(file_url, stream=True, timeout=120)

        # Force video/mp4 so Buffer/Zernio accept it
        return app.response_class(
            req.iter_content(chunk_size=8192),
            content_type='video/mp4',
            headers={
                'Content-Disposition': f'attachment; filename="{file_id}.mp4"',
                'Accept-Ranges': 'bytes',
            }
        )

    except Exception as e:
        logger.exception("Stream failed")
        return jsonify({'error': str(e)}), 500


@app.route('/videos')
def list_videos():
    """List all tracked uploads for the Manage tab."""
    rows = list_uploads()
    videos = []
    for uid, filename, file_id, message_id, telegram_link, created_at in rows:
        videos.append({
            'uid': uid,
            'filename': filename,
            'file_id': file_id,
            'message_id': message_id,
            'telegram_link': telegram_link,
            'stream_link': f"{BASE_URL}/stream/{file_id}",
            'created_at': created_at,
        })
    return jsonify({'videos': videos})


@app.route('/videos/delete/<uid>', methods=['POST'])
def delete_video(uid):
    """Delete a video from Telegram and remove it from the DB."""
    row = get_upload_by_id(uid)
    if not row:
        return jsonify({'error': 'Upload not found'}), 404

    filename, file_id, message_id, telegram_link = row

    try:
        url = f"{TG_API}/bot{BOT_TOKEN}/deleteMessage"
        r = requests.post(url, data={
            'chat_id': CHAT_ID,
            'message_id': message_id,
        }, timeout=15)
        result = r.json()

        if not result.get('ok'):
            logger.warning(f"Telegram delete failed: {result.get('description')}")

        delete_upload_record(uid)

        return jsonify({
            'success': True,
            'deleted_message_id': message_id,
            'telegram_deleted': result.get('ok', False),
        })

    except Exception as e:
        logger.exception("Delete failed")
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    """Health check endpoint for the test tab."""
    checks = []

    try:
        url = f"{TG_API}/bot{BOT_TOKEN}/getMe"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get('ok'):
            checks.append({
                'name': 'Telegram API',
                'ok': True,
                'detail': f"@{data['result']['username']}"
            })
        else:
            checks.append({
                'name': 'Telegram API',
                'ok': False,
                'detail': data.get('description', 'Unknown error')
            })
    except Exception as e:
        checks.append({'name': 'Telegram API', 'ok': False, 'detail': str(e)[:60]})

    try:
        url = f"{TG_API}/bot{BOT_TOKEN}/getChat"
        r = requests.get(url, params={'chat_id': CHAT_ID}, timeout=5)
        data = r.json()
        if data.get('ok'):
            checks.append({
                'name': 'Channel access',
                'ok': True,
                'detail': data['result'].get('title', CHAT_ID)
            })
        else:
            checks.append({
                'name': 'Channel access',
                'ok': False,
                'detail': data.get('description', 'Not reachable')
            })
    except Exception as e:
        checks.append({'name': 'Channel access', 'ok': False, 'detail': str(e)[:60]})

    if BASE_URL and 'localhost' not in BASE_URL:
        checks.append({'name': 'BASE_URL', 'ok': True, 'detail': BASE_URL})
    else:
        checks.append({'name': 'BASE_URL', 'ok': False, 'detail': 'Not set to a public URL'})

    try:
        test_file = os.path.join(UPLOAD_FOLDER, '.writetest')
        with open(test_file, 'w') as f:
            f.write('ok')
        os.remove(test_file)
        checks.append({'name': 'Upload folder', 'ok': True, 'detail': UPLOAD_FOLDER})
    except Exception as e:
        checks.append({'name': 'Upload folder', 'ok': False, 'detail': str(e)[:60]})

    return jsonify({'checks': checks})


@app.route('/lookup', methods=['POST'])
def lookup_file():
    """Generate a download link for an existing file_id."""
    data = request.get_json() or {}
    file_id = data.get('file_id', '').strip()

    if not file_id:
        return jsonify({'error': 'No file_id provided'}), 400

    try:
        url = f"{TG_API}/bot{BOT_TOKEN}/getFile"
        r = requests.get(url, params={'file_id': file_id}, timeout=15)
        result = r.json()

        if not result.get('ok'):
            return jsonify({
                'error': result.get('description', 'File lookup failed')
            }), 400

        return jsonify({
            'download_link': f"{BASE_URL}/stream/{file_id}",
            'file_size': result['result'].get('file_size'),
        })

    except Exception as e:
        logger.exception("Lookup failed")
        return jsonify({'error': str(e)}), 500


@app.errorhandler(413)
def too_large(e):
    return jsonify({
        'error': 'File too large. Max size is 20MB (Telegram cloud API limit).'
    }), 413


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))