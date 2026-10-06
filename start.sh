#!/bin/bash
set -e

echo "=== Checking binary ==="
/usr/local/bin/telegram-bot-api --version || {
  echo "ERROR: Binary cannot execute"
  exit 1
}

echo "=== Starting Bot API server ==="
telegram-bot-api \
  --api-id="${TELEGRAM_API_ID}" \
  --api-hash="${TELEGRAM_API_HASH}" \
  --local \
  --http-port=8081 \
  --dir=/data/telegram-bot-api \
  --log=/data/telegram-bot-api/server.log &

BOT_API_PID=$!
sleep 3

if ! kill -0 $BOT_API_PID 2>/dev/null; then
  echo "ERROR: Bot API server died:"
  cat /data/telegram-bot-api/server.log
  exit 1
fi

for i in {1..30}; do
  curl -s "http://localhost:8081" > /dev/null 2>&1 && break
  sleep 1
done

echo "=== Starting Flask ==="
exec gunicorn --workers 2 --timeout 600 --bind 0.0.0.0:${PORT:-10000} app:app