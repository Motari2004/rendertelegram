#!/bin/bash
set -e

echo "Starting Local Telegram Bot API Server..."

# Start the Bot API server in the background
telegram-bot-api \
  --api-id="${TELEGRAM_API_ID}" \
  --api-hash="${TELEGRAM_API_HASH}" \
  --local \
  --http-port=8081 \
  --dir=/data/telegram-bot-api \
  --log=/data/telegram-bot-api/server.log &

BOT_API_PID=$!
echo "Bot API server PID: $BOT_API_PID"

# Diagnostic: verify the binary can run
echo "Checking binary dependencies:"
ldd /usr/local/bin/telegram-bot-api || echo "WARNING: ldd failed"

# Check if process died immediately
sleep 2
if ! kill -0 $BOT_API_PID 2>/dev/null; then
  echo "ERROR: Bot API server died. Log:"
  cat /data/telegram-bot-api/server.log 2>/dev/null || echo "No log"
  exit 1
fi

# Wait for server to be ready
for i in {1..30}; do
  if curl -s "http://localhost:8081" > /dev/null 2>&1; then
    echo "Bot API server is ready."
    break
  fi
  echo "Waiting... ($i/30)"
  sleep 1
done

echo "Starting Flask on port ${PORT:-10000}..."
exec gunicorn \
  --workers 2 \
  --timeout 600 \
  --bind 0.0.0.0:${PORT:-10000} \
  --access-logfile - \
  --error-logfile - \
  app:app