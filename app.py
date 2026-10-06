import os
import uuid
import time
import asyncio
import sqlite3
import threading
import logging
import requests
from flask import Flask, render_template, request, jsonify, send_file, abort
from werkzeug.utils import secure_filename
from telegram import Bot

from config import (
    BOT_TOKEN, CHAT_ID, BOT_API_URL, UPLOAD_FOLDER,
    MAX_FILE_SIZE, BASE_URL, CLEANUP_HOURS, DB_PATH,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'mp4', 'mkv', 'mov', 'avi', 'webm', 'flv', 'm4v'}


# ---------- Database ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id TEXT PRIMARY KEY,
            filename TEXT,
            path TEXT,
            telegram_link TEXT,
            file_id TEXT,
            message_id INTEGER,
            created_at REAL
        )
    """)
    conn.commit()
    conn.close()


def save_upload(uid, filename, path, telegram_link, file_id, message_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO uploads VALUES (?, ?, ?, ?, ?, ?, ?)",
        (uid, filename, path, telegram_link, file_id, message_id, time.time())
    )
    conn.commit()
    conn.close()


def get_upload(uid):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT filename, path, telegram_link FROM uploads WHERE id = ?", (uid,)
    ).fetchone()
    conn.close()
    return row


def get_upload_by_message(message_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id, filename, telegram_link FROM uploads WHERE message_id = ?",
        (message_id,)
    ).fetchone()
    conn.close()
    return row


def cleanup_old_uploads(max_age_hours):
    """Delete files + DB rows older than max_age_hours."""
    while True:
        cutoff = time.time() - (max_age_hours * 3600)
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT id, path FROM uploads WHERE created_at < ?", (cutoff,)
        ).fetchall()
        for uid, path in rows:
            try:
                if os.path.exists(path):
                    os.remove(path)
                conn.execute("DELETE FROM uploads WHERE id = ?", (uid,))
                logger.info(f"Cleaned up {uid}")
            except Exception as e:
                logger.warning(f"Cleanup failed for {uid}: {e}")
        conn.commit()
        conn.close()
        time.sleep(3600)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------- Telegram ----------
async def upload_to_telegram(file_path, caption=""):
    """Upload via the LOCAL Bot API server (2GB limit, not 20MB)."""
    bot = Bot(token=BOT_TOKEN, base_url=BOT_API_URL)

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

        save_upload(
            uid=uid,
            filename=safe_name,
            path=filepath,
            telegram_link=result['link'],
            file_id=result['file_id'],
            message_id=result['message_id'],
        )

        return jsonify({
            'success': True,
            'link': result['link'],
            'download_link': f"{BASE_URL}/download/{uid}",
            'file_id': result['file_id'],
            'message_id': result['message_id'],
        })

    except Exception as e:
        logger.exception("Upload failed")
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'error': str(e)}), 500


@app.route('/download/<uid>')
def download(uid):
    """Serve the video file while the server is awake."""
    row = get_upload(uid)
    if not row:
        abort(404)
    filename, path, _ = row
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=filename)


@app.route('/link/<int:message_id>')
def get_link_by_message(message_id):
    """Look up a download link using the Telegram message ID."""
    row = get_upload_by_message(message_id)
    if not row:
        return jsonify({'error': 'No upload found for that message ID'}), 404
    uid, filename, telegram_link = row
    return jsonify({
        'download_link': f"{BASE_URL}/download/{uid}",
        'telegram_link': telegram_link,
        'filename': filename,
    })


@app.route('/health')
def health():
    """Health check endpoint for the test tab."""
    checks = []

    # 1. Local Bot API server reachable?
    try:
        r = requests.get(f"{BOT_API_URL}/bot{BOT_TOKEN}/getMe", timeout=5)
        data = r.json()
        if data.get('ok'):
            checks.append({
                'name': 'Bot API server',
                'ok': True,
                'detail': f"@{data['result']['username']}"
            })
        else:
            checks.append({
                'name': 'Bot API server',
                'ok': False,
                'detail': data.get('description', 'Unknown error')
            })
    except Exception as e:
        checks.append({
            'name': 'Bot API server',
            'ok': False,
            'detail': str(e)[:60]
        })

    # 2. Channel accessible?
    try:
        r = requests.get(
            f"{BOT_API_URL}/bot{BOT_TOKEN}/getChat",
            params={'chat_id': CHAT_ID},
            timeout=5
        )
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
        checks.append({
            'name': 'Channel access',
            'ok': False,
            'detail': str(e)[:60]
        })

    # 3. BASE_URL configured?
    if BASE_URL and 'localhost' not in BASE_URL:
        checks.append({
            'name': 'BASE_URL',
            'ok': True,
            'detail': BASE_URL
        })
    else:
        checks.append({
            'name': 'BASE_URL',
            'ok': False,
            'detail': 'Not set to a public URL'
        })

    # 4. Upload folder writable?
    try:
        test_file = os.path.join(UPLOAD_FOLDER, '.writetest')
        with open(test_file, 'w') as f:
            f.write('ok')
        os.remove(test_file)
        checks.append({
            'name': 'Upload folder',
            'ok': True,
            'detail': UPLOAD_FOLDER
        })
    except Exception as e:
        checks.append({
            'name': 'Upload folder',
            'ok': False,
            'detail': str(e)[:60]
        })

    return jsonify({'checks': checks})


@app.route('/lookup', methods=['POST'])
def lookup_file():
    """Generate a download link for an existing file_id."""
    data = request.get_json() or {}
    file_id = data.get('file_id', '').strip()

    if not file_id:
        return jsonify({'error': 'No file_id provided'}), 400

    try:
        r = requests.get(
            f"{BOT_API_URL}/bot{BOT_TOKEN}/getFile",
            params={'file_id': file_id},
            timeout=15
        )
        result = r.json()

        if not result.get('ok'):
            return jsonify({
                'error': result.get('description', 'File lookup failed')
            }), 400

        file_path = result['result']['file_path']

        return jsonify({
            'download_link': f"{BASE_URL}/stream/{file_id}",
            'file_path': file_path,
            'file_size': result['result'].get('file_size'),
        })

    except Exception as e:
        logger.exception("Lookup failed")
        return jsonify({'error': str(e)}), 500


@app.route('/stream/<file_id>')
def stream_file(file_id):
    """Stream a file from Telegram via the local Bot API server."""
    try:
        r = requests.get(
            f"{BOT_API_URL}/bot{BOT_TOKEN}/getFile",
            params={'file_id': file_id},
            timeout=15
        )
        result = r.json()

        if not result.get('ok'):
            abort(404)

        file_path = result['result']['file_path']
        file_url = f"{BOT_API_URL}/file/bot{BOT_TOKEN}/{file_path}"

        req = requests.get(file_url, stream=True, timeout=60)
        return app.response_class(
            req.iter_content(chunk_size=8192),
            content_type=req.headers.get('Content-Type', 'video/mp4'),
            headers={
                'Content-Disposition': f'attachment; filename="{file_id}.mp4"',
            }
        )

    except Exception as e:
        logger.exception("Stream failed")
        abort(500)


@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'File too large. Max size is 2GB.'}), 413


if __name__ == '__main__':
    init_db()
    threading.Thread(
        target=cleanup_old_uploads, args=(CLEANUP_HOURS,), daemon=True
    ).start()
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))