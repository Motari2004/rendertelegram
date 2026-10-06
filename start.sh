#!/bin/bash
set -e

echo "Starting Local Telegram Bot API Server..."

telegram-bot-api \
  --api-id="${TELEGRAM_API_ID}" \
  --api-hash="${TELEGRAM_API_HASH}" \
  --local \
  --http-port=8081 \
  --dir=/data/telegram-bot-api \
  --log=/data/telegram-bot-api/server.log &

BOT_API_PID=$!
echo "Local Bot API Server started (PID: $BOT_API_PID)"

for i in {1..30}; do
  if curl -s "http://localhost:8081" > /dev/null 2>&1; then
    echo "Local Bot API Server is ready."
    break
  fi
  echo "Waiting for Bot API Server... ($i/30)"
  sleep 1
done

echo "Starting Flask app on port ${PORT:-10000}..."
exec gunicorn \
  --workers 2 \
  --timeout 600 \
  --bind 0.0.0.0:${PORT:-10000} \
  --access-logfile - \
  --error-logfile - \
  app:app