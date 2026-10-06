import os
import uuid
import asyncio
import logging
import requests
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from telegram import Bot

from config import (
    BOT_TOKEN, CHAT_ID, BOT_API_URL, UPLOAD_FOLDER,
    MAX_FILE_SIZE, BASE_URL,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'mp4', 'mkv', 'mov', 'avi', 'webm', 'flv', 'm4v'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------- Telegram ----------
async def upload_to_telegram(file_path, caption=""):
    """Upload via the LOCAL Bot API server (2GB limit, not 20MB)."""
    # BOT_API_URL includes /bot suffix — python-telegram-bot appends the token
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

    # Save temp file just for the upload
    filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    try:
        result = asyncio.run(upload_to_telegram(filepath, caption))
        file_id = result['file_id']

        if not file_id:
            raise Exception("Telegram did not return a file_id")

        return jsonify({
            'success': True,
            'link': result['link'],
            'download_link': f"{BASE_URL}/stream/{file_id}",
            'file_id': file_id,
            'message_id': result['message_id'],
        })

    except Exception as e:
        logger.exception("Upload failed")
        return jsonify({'error': str(e)}), 500

    finally:
        # Delete temp file — Telegram holds the permanent copy
        if os.path.exists(filepath):
            os.remove(filepath)


@app.route('/health')
def health():
    """Health check endpoint for the test tab."""
    checks = []

    # 1. Local Bot API server reachable?
    try:
        url = f"{BOT_API_URL}{BOT_TOKEN}/getMe"
        r = requests.get(url, timeout=5)
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
        url = f"{BOT_API_URL}{BOT_TOKEN}/getChat"
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
        # BOT_API_URL includes /bot suffix
        url = f"{BOT_API_URL}{BOT_TOKEN}/getFile"
        r = requests.get(url, params={'file_id': file_id}, timeout=15)
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
        # BOT_API_URL includes /bot suffix
        url = f"{BOT_API_URL}{BOT_TOKEN}/getFile"
        r = requests.get(url, params={'file_id': file_id}, timeout=15)
        result = r.json()

        if not result.get('ok'):
            abort(404)

        file_path = result['result']['file_path']

        # Local Bot API server serves files at:
        #   http://<host>/file/bot<TOKEN>/<file_path>
        # BOT_API_URL looks like "http://host:8081/bot" — strip the trailing "/bot"
        base = BOT_API_URL.rsplit('/bot', 1)[0]
        file_url = f"{base}/file/bot{BOT_TOKEN}/{file_path}"

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
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))