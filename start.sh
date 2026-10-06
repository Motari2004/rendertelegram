#!/bin/bash
set -e

# Start the Local Bot API Server in the background
telegram-bot-api \
  --api-id="${TELEGRAM_API_ID}" \
  --api-hash="${TELEGRAM_API_HASH}" \
  --local \
  --http-port=8081 \
  --dir=/data/telegram-bot-api \
  --log=/data/telegram-bot-api/server.log &

# Give it a moment to start
sleep 3

# Start Flask on Render's assigned PORT
exec gunicorn -w 2 -b 0.0.0.0:${PORT:-10000} app:app